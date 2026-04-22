"""
APEX-EDS v4.0 | exchange_monitor.py
─────────────────────────────────────────────────────────────────────────────
Fix for ConnectionClosedError on fstream.binance.com/stream

Root causes identified from logs:
  1. 40 symbols × 5 streams = 200-stream URL is too long — Binance drops it
  2. 14 connections all reconnect simultaneously — storms Binance and causes
     cascading drops as they all hit the server at once
  3. ping_timeout was too short for high-latency cloud environments

Fixes applied:
  - Chunk reduced to 25 symbols (125 streams — well within safe limit)
  - Random jitter added to reconnect delay to stagger the 21 connections
  - ping_timeout increased to 30s
  - Binance application-level ping {"e":"ping"} → pong handled explicitly
  - open_timeout added so hanging handshakes don't block forever
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import json
import logging
import random
import time
from collections import deque
from typing import Dict, List, Optional, Set

import aiohttp
import websockets

import config

logger = logging.getLogger("ExchangeMonitor")

_HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 ApexEDS/4.0"}

_REST_URLS = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
    "https://fapi4.binance.com",
]

# Only fstream.binance.com supports combined ?streams= WebSocket
_COMBINED_WS  = "wss://fstream.binance.com/stream"
# miniTicker uses its own /ws/ endpoint — separate stable connection
_MINI_TICKER  = "wss://fstream.binance.com/ws/!miniTicker@arr"

# ── TUNED CONSTANTS ───────────────────────────────────────────────────────
# 25 symbols × 5 streams = 125 streams per connection
# URL stays short, well under Binance's 1024-stream limit
# 534 pairs → ~22 connections
_SYMBOLS_PER_WS  = 25

# Back-off: 5 → 10 → 20 → 40s (capped), + 0–5s random jitter each time
_BACKOFF_BASE    = 5
_BACKOFF_MAX     = 40
_JITTER_MAX      = 5     # seconds of random jitter to stagger reconnects


def _backoff(attempt: int) -> float:
    base  = min(_BACKOFF_BASE * (2 ** attempt), _BACKOFF_MAX)
    jitter = random.uniform(0, _JITTER_MAX)
    return base + jitter


# ─────────────────────────────────────────────────────────────────────────────
class CandleBar:
    __slots__ = ["t", "o", "h", "l", "c", "v", "closed"]

    def __init__(self, t, o, h, l, c, v, closed):
        self.t = t
        self.o = float(o); self.h = float(h)
        self.l = float(l); self.c = float(c)
        self.v = float(v); self.closed = bool(closed)


class SymbolData:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.candles: Dict[str, deque] = {
            "1m":  deque(maxlen=120),
            "5m":  deque(maxlen=120),
            "15m": deque(maxlen=120),
        }
        self.last_price:       float = 0.0
        self.price_change_24h: float = 0.0
        self.volume_24h:       float = 0.0
        self.bid:              float = 0.0
        self.ask:              float = 0.0
        self.buy_vol:          float = 0.0
        self.sell_vol:         float = 0.0
        self.agg_trades:       deque = deque(maxlen=500)
        self.updated_at:       float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
class ExchangeMonitor:

    def __init__(self):
        self.symbols:      Dict[str, SymbolData] = {}
        self.active_pairs: Set[str]              = set()
        self._session:     Optional[aiohttp.ClientSession] = None
        self._ws_tasks:    List[asyncio.Task]    = []
        self._running      = False
        self._rest_url     = _REST_URLS[0]

    # ── PUBLIC ────────────────────────────────────────────────────────────

    async def start(self):
        self._running = True
        self._session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=True, limit=60),
            headers=_HEADERS,
        )
        logger.info("ExchangeMonitor: starting...")

        await self._find_rest_endpoint()

        if self.active_pairs:
            await self._seed_klines_rest()
        else:
            logger.error("No pairs loaded at startup — will retry hourly")

        asyncio.create_task(self._mini_ticker_ws())
        asyncio.create_task(self._ws_manager())
        asyncio.create_task(self._exchange_info_loop())

        logger.info(
            f"ExchangeMonitor: {len(self.active_pairs)} pairs | "
            f"REST: {self._rest_url} | "
            f"WS: {_COMBINED_WS} | "
            f"{_SYMBOLS_PER_WS} symbols/conn"
        )

    async def stop(self):
        self._running = False
        for t in self._ws_tasks:
            t.cancel()
        if self._session:
            await self._session.close()

    def get_symbol_data(self, symbol: str) -> Optional[SymbolData]:
        return self.symbols.get(symbol)

    def get_all_symbols(self) -> List[str]:
        return list(self.active_pairs)

    # ── REST: FIND WORKING ENDPOINT ───────────────────────────────────────

    async def _find_rest_endpoint(self):
        for url in _REST_URLS:
            logger.info(f"Trying REST: {url}")
            pairs = await self._fetch_exchange_info(url)
            if pairs:
                self._rest_url    = url
                self.active_pairs = pairs
                for s in pairs:
                    if s not in self.symbols:
                        self.symbols[s] = SymbolData(s)
                logger.info(f"REST OK: {url} — {len(pairs)} USDT-M pairs")
                return
        logger.error("All REST endpoints failed — will retry hourly")

    async def _fetch_exchange_info(self, base: str) -> Set[str]:
        url = f"{base}/fapi/v1/exchangeInfo"
        try:
            async with self._session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=True,
            ) as r:
                if r.status == 451:
                    logger.warning(f"{base}: geo-blocked (451)")
                    return set()
                if r.status not in (200, 202):
                    logger.warning(f"{base}: HTTP {r.status}")
                    return set()
                try:
                    data = json.loads(await r.text())
                except json.JSONDecodeError:
                    return set()
                if not isinstance(data, dict):
                    return set()
                if data.get("code", 0) not in (0, None, ""):
                    logger.warning(f"{base}: error {data.get('code')}")
                    return set()
                found: Set[str] = set()
                for sym in data.get("symbols", []):
                    if (isinstance(sym, dict)
                            and sym.get("status") == "TRADING"
                            and sym.get("contractType") == "PERPETUAL"
                            and sym.get("quoteAsset") == "USDT"):
                        found.add(sym["symbol"])
                logger.info(f"{base}: {len(found)} USDT-M pairs")
                return found
        except asyncio.TimeoutError:
            logger.warning(f"{base}: timeout")
            return set()
        except Exception as e:
            logger.warning(f"{base}: {e}")
            return set()

    # ── REST: ONE-TIME KLINE SEED ─────────────────────────────────────────

    async def _seed_klines_rest(self, symbols: Optional[List[str]] = None):
        targets = symbols or list(self.active_pairs)
        if not targets:
            return
        logger.info(f"Seeding {len(targets)} symbols with kline history (REST, one-time)...")
        sem = asyncio.Semaphore(20)

        async def fetch(symbol: str, interval: str):
            async with sem:
                url    = f"{self._rest_url}/fapi/v1/klines"
                params = {"symbol": symbol, "interval": interval, "limit": 100}
                try:
                    async with self._session.get(
                        url, params=params,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as r:
                        if r.status not in (200, 202):
                            return
                        rows = await r.json(content_type=None)
                        if not isinstance(rows, list):
                            return
                        sd = self.symbols.get(symbol)
                        if not sd:
                            return
                        for row in rows:
                            if isinstance(row, list) and len(row) >= 6:
                                sd.candles[interval].append(
                                    CandleBar(
                                        row[0], row[1], row[2],
                                        row[3], row[4], row[5], True
                                    )
                                )
                except Exception as e:
                    logger.debug(f"Kline seed {symbol}/{interval}: {e}")

        await asyncio.gather(*[
            fetch(s, iv) for s in targets for iv in config.KLINE_INTERVALS
        ])
        logger.info("Kline seed complete — live updates via WebSocket")

    # ── EXCHANGE INFO LOOP (hourly) ───────────────────────────────────────

    async def _exchange_info_loop(self):
        while self._running:
            await asyncio.sleep(config.EXCHANGE_INFO_TTL_SEC)
            try:
                if not self.active_pairs:
                    await self._find_rest_endpoint()
                    if self.active_pairs:
                        await self._seed_klines_rest()
                    continue

                new_pairs = await self._fetch_exchange_info(self._rest_url)
                if not new_pairs:
                    logger.warning("Exchange info refresh failed — re-probing")
                    await self._find_rest_endpoint()
                    continue

                added   = new_pairs - self.active_pairs
                removed = self.active_pairs - new_pairs
                self.active_pairs = new_pairs

                for s in new_pairs:
                    if s not in self.symbols:
                        self.symbols[s] = SymbolData(s)

                if added:
                    logger.info(f"New listings: {added}")
                    await self._seed_klines_rest(list(added))
                if removed:
                    logger.info(f"Delisted: {removed}")

                logger.info(
                    f"Exchange info refreshed — {len(self.active_pairs)} pairs"
                )
            except Exception as e:
                logger.error(f"Exchange info loop: {e}")

    # ── WS: !miniTicker@arr ───────────────────────────────────────────────
    # Single stable connection. Delivers price/vol/change for all symbols
    # every second from Binance — replaces REST ticker polling entirely.

    async def _mini_ticker_ws(self):
        attempt = 0
        while self._running:
            delay = _backoff(attempt) if attempt > 0 else 0
            if delay:
                logger.info(f"miniTicker reconnect in {delay:.1f}s")
                await asyncio.sleep(delay)
            try:
                async with websockets.connect(
                    _MINI_TICKER,
                    ping_interval=20,
                    ping_timeout=30,
                    open_timeout=15,
                    max_size=50_000_000,
                    extra_headers={"User-Agent": "Mozilla/5.0 ApexEDS/4.0"},
                ) as ws:
                    logger.info(f"miniTicker WS connected")
                    attempt = 0
                    async for raw in ws:
                        if not self._running:
                            return
                        try:
                            payload = json.loads(raw)

                            # Handle Binance application-level ping
                            if isinstance(payload, dict) and payload.get("e") == "ping":
                                await ws.send(json.dumps({"e": "pong"}))
                                continue

                            if not isinstance(payload, list):
                                continue

                            for t in payload:
                                if not isinstance(t, dict):
                                    continue
                                sym = t.get("s", "")
                                if sym not in self.symbols:
                                    continue
                                sd = self.symbols[sym]
                                try:
                                    price = float(t.get("c", 0) or 0)
                                    if price > 0:
                                        sd.last_price       = price
                                        sd.price_change_24h = float(t.get("P", 0) or 0)
                                        sd.volume_24h       = float(t.get("q", 0) or 0)
                                        sd.updated_at       = time.time()
                                except (ValueError, TypeError):
                                    pass
                        except Exception:
                            pass

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(
                    f"miniTicker WS: {type(e).__name__} "
                    f"(attempt {attempt + 1})"
                )
                attempt += 1

    # ── WS MANAGER ───────────────────────────────────────────────────────

    async def _ws_manager(self):
        """
        Splits all pairs into chunks of _SYMBOLS_PER_WS.
        Opens one combined-stream connection per chunk.
        Rebuilds every hour to pick up new listings.
        """
        while self._running:
            for t in self._ws_tasks:
                t.cancel()
            self._ws_tasks.clear()

            pairs = list(self.active_pairs)
            if not pairs:
                logger.warning("WS manager: no pairs — waiting 30s")
                await asyncio.sleep(30)
                continue

            chunks = [
                pairs[i:i + _SYMBOLS_PER_WS]
                for i in range(0, len(pairs), _SYMBOLS_PER_WS)
            ]
            logger.info(
                f"WS manager: {len(pairs)} pairs → {len(chunks)} connections "
                f"({_SYMBOLS_PER_WS} symbols × 5 streams = "
                f"{_SYMBOLS_PER_WS * 5} streams each)"
            )
            for idx, chunk in enumerate(chunks):
                self._ws_tasks.append(
                    asyncio.create_task(self._ws_connection(chunk, conn_id=idx))
                )

            await asyncio.sleep(config.EXCHANGE_INFO_TTL_SEC)

    # ── WS CONNECTION ─────────────────────────────────────────────────────

    async def _ws_connection(self, symbols: List[str], conn_id: int = 0):
        """
        Combined-stream WebSocket for one chunk of symbols.
        Handles:
          - Binance application-level {"e":"ping"} → sends pong
          - Reconnect with exponential back-off + jitter
          - open_timeout to prevent hanging handshakes
        """
        streams = []
        for s in symbols:
            sl = s.lower()
            for iv in config.KLINE_INTERVALS:
                streams.append(f"{sl}@kline_{iv}")
            streams.append(f"{sl}@bookTicker")
            streams.append(f"{sl}@aggTrade")

        url     = f"{_COMBINED_WS}?streams=" + "/".join(streams)
        attempt = 0

        # Stagger startup across connections so they don't all hit Binance at once
        startup_delay = conn_id * 0.3   # 0.3s apart per connection
        if startup_delay:
            await asyncio.sleep(startup_delay)

        while True:
            delay = _backoff(attempt) if attempt > 0 else 0
            if delay:
                logger.debug(
                    f"[conn-{conn_id}] reconnect in {delay:.1f}s "
                    f"(attempt {attempt + 1})"
                )
                await asyncio.sleep(delay)

            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=30,      # increased from 15 → 30
                    open_timeout=20,      # handshake timeout
                    max_size=10_000_000,
                    extra_headers={"User-Agent": "Mozilla/5.0 ApexEDS/4.0"},
                ) as ws:
                    logger.debug(
                        f"[conn-{conn_id}] connected: {len(symbols)} symbols, "
                        f"{len(streams)} streams"
                    )
                    attempt = 0   # reset on successful connect

                    async for raw in ws:
                        if not self._running:
                            return
                        try:
                            msg = json.loads(raw)

                            # Binance sends application-level ping periodically.
                            # Must respond with pong or server disconnects.
                            if isinstance(msg, dict) and msg.get("e") == "ping":
                                await ws.send(json.dumps({"e": "pong"}))
                                continue

                            self._dispatch(msg)

                        except Exception:
                            pass

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(
                    f"[conn-{conn_id}] WS {_COMBINED_WS}: "
                    f"{type(e).__name__} — reconnect in "
                    f"{_backoff(attempt):.1f}s (attempt {attempt + 1})"
                )
                attempt += 1

    # ── DISPATCH ──────────────────────────────────────────────────────────

    def _dispatch(self, msg: dict):
        if not isinstance(msg, dict):
            return
        data   = msg.get("data", msg)
        stream = msg.get("stream", "")
        if not isinstance(data, dict):
            return
        if "@kline_" in stream:
            self._on_kline(data)
        elif "@bookTicker" in stream:
            self._on_book(data)
        elif "@aggTrade" in stream:
            self._on_trade(data)

    def _on_kline(self, data: dict):
        k = data.get("k", {})
        if not isinstance(k, dict):
            return
        sym = k.get("s", "")
        iv  = k.get("i", "")
        if sym not in self.symbols or iv not in config.KLINE_INTERVALS:
            return
        sd = self.symbols[sym]
        try:
            bar = CandleBar(
                k["t"], k["o"], k["h"],
                k["l"], k["c"], k["v"], k["x"]
            )
        except (KeyError, ValueError):
            return
        q = sd.candles[iv]
        if q and not q[-1].closed:
            q[-1] = bar
        else:
            q.append(bar)
        sd.updated_at = time.time()

    def _on_book(self, data: dict):
        sym = data.get("s", "")
        if sym in self.symbols:
            sd = self.symbols[sym]
            try:
                bid = float(data.get("b", 0) or 0)
                ask = float(data.get("a", 0) or 0)
                if bid > 0 and ask > 0:
                    sd.bid = bid
                    sd.ask = ask
            except (ValueError, TypeError):
                pass

    def _on_trade(self, data: dict):
        sym = data.get("s", "")
        if sym not in self.symbols:
            return
        sd = self.symbols[sym]
        try:
            price = float(data.get("p", 0) or 0)
            qty   = float(data.get("q", 0) or 0)
            maker = bool(data.get("m", False))
            usdt  = price * qty
            if maker:
                sd.sell_vol += usdt
            else:
                sd.buy_vol  += usdt
            sd.agg_trades.append({"p": price, "q": qty, "m": maker})
            if price > 0:
                sd.last_price = price
                sd.updated_at = time.time()
        except (ValueError, TypeError):
            pass
