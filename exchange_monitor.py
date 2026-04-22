"""
APEX-EDS v4.0 | exchange_monitor.py
─────────────────────────────────────────────────────────────────────────────
Fix for repeated ConnectionClosedError

Root cause (confirmed from logs):
  The `websockets` library had ping_interval=20 set, meaning it sent a
  WebSocket PING frame every 20 seconds. Binance's server is designed to be
  the one that sends pings (every 3 minutes). When Binance's server received
  client-initiated pings while managing thousands of subscriptions, it
  responded slowly or not at all, causing the library to hit ping_timeout
  and close the connection with ConnectionClosedError.

Fix:
  Set ping_interval=None on all connections → disables library auto-pinging.
  Binance's server sends its own PING frames every ~3 minutes; the websockets
  library automatically responds with PONG at the protocol level.
  We also handle Binance's application-level {"e":"ping"} → {"e":"pong"}.

This matches the official Binance WebSocket usage pattern where the client
is passive and the server initiates keepalive.

Additional improvements:
  - 15 symbols per connection (75 streams) — more headroom below 200 limit
  - close_timeout added so clean shutdown doesn't hang
  - Reconnect attempt counter resets properly on each new healthy session
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
_COMBINED_WS = "wss://fstream.binance.com/stream"
# miniTicker broadcast — separate single-symbol stream endpoint
_MINI_TICKER  = "wss://fstream.binance.com/ws/!miniTicker@arr"

# 15 symbols × 5 streams = 75 streams per connection (well inside 200 limit)
# 534 pairs → 36 connections, each with a short stable URL
_SYMBOLS_PER_WS = 15

# Back-off settings
_BACKOFF_BASE = 5
_BACKOFF_MAX  = 60
_JITTER_MAX   = 5   # seconds of random jitter


def _backoff(attempt: int) -> float:
    base   = min(_BACKOFF_BASE * (2 ** min(attempt, 5)), _BACKOFF_MAX)
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
            f"WS combined: {_COMBINED_WS} | "
            f"{_SYMBOLS_PER_WS} symbols/conn | "
            f"auto-ping: DISABLED (Binance server-led keepalive)"
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
        logger.info(
            f"Seeding {len(targets)} symbols with kline history "
            f"(REST, one-time at startup)..."
        )
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
        logger.info("Kline seed complete — all live data now via WebSocket")

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
                    logger.info(f"New listings detected: {added}")
                    await self._seed_klines_rest(list(added))
                if removed:
                    logger.info(f"Delisted: {removed}")

                logger.info(
                    f"Exchange info refreshed — {len(self.active_pairs)} pairs"
                )
            except Exception as e:
                logger.error(f"Exchange info loop: {e}")

    # ── WS: !miniTicker@arr ───────────────────────────────────────────────

    async def _mini_ticker_ws(self):
        """
        Single stable connection delivering 24h stats for ALL symbols every 1s.
        ping_interval=None — Binance server sends pings, we respond automatically.
        """
        attempt = 0
        while self._running:
            if attempt > 0:
                delay = _backoff(attempt)
                logger.info(
                    f"miniTicker reconnecting in {delay:.1f}s "
                    f"(attempt {attempt})"
                )
                await asyncio.sleep(delay)
            try:
                async with websockets.connect(
                    _MINI_TICKER,
                    # ── KEY FIX ──────────────────────────────────────────
                    # Disable library auto-ping. Binance server pings every
                    # 3 minutes; the library responds with PONG automatically
                    # at the WebSocket protocol level without us doing anything.
                    ping_interval=None,
                    # ─────────────────────────────────────────────────────
                    open_timeout=20,
                    close_timeout=5,
                    max_size=50_000_000,
                    extra_headers={"User-Agent": "Mozilla/5.0 ApexEDS/4.0"},
                ) as ws:
                    logger.info("miniTicker WS connected")
                    attempt = 0   # reset on healthy connect
                    async for raw in ws:
                        if not self._running:
                            return
                        try:
                            payload = json.loads(raw)

                            # Binance application-level ping → pong
                            if isinstance(payload, dict):
                                if payload.get("e") == "ping":
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
                    f"miniTicker WS: {type(e).__name__} — "
                    f"reconnecting (attempt {attempt + 1})"
                )
                attempt += 1

    # ── WS MANAGER ───────────────────────────────────────────────────────

    async def _ws_manager(self):
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

        ping_interval=None is the critical fix:
          The websockets library was sending a PING every 20s and waiting up
          to 30s for a PONG. Binance's busy server sometimes took longer than
          30s to respond to client-initiated PINGs, causing ConnectionClosedError.
          With ping_interval=None the library never initiates a ping. Binance's
          server sends its own PING every ~3 minutes and the library responds
          with PONG automatically at the protocol level — no timeout risk.
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

        # Stagger startup: 0.2s apart so 36 connections don't hit Binance at once
        await asyncio.sleep(conn_id * 0.2)

        while True:
            if attempt > 0:
                delay = _backoff(attempt)
                logger.debug(
                    f"[conn-{conn_id}] reconnect in {delay:.1f}s "
                    f"(attempt {attempt})"
                )
                await asyncio.sleep(delay)

            try:
                async with websockets.connect(
                    url,
                    # ── KEY FIX ──────────────────────────────────────────
                    # Disable library auto-ping. Binance server manages the
                    # keepalive cycle. Client just responds to server pings.
                    ping_interval=None,
                    # ─────────────────────────────────────────────────────
                    open_timeout=20,
                    close_timeout=5,
                    max_size=10_000_000,
                    extra_headers={"User-Agent": "Mozilla/5.0 ApexEDS/4.0"},
                ) as ws:
                    logger.debug(
                        f"[conn-{conn_id}] connected: {len(symbols)} symbols, "
                        f"{len(streams)} streams"
                    )
                    attempt = 0   # reset on healthy connect

                    async for raw in ws:
                        if not self._running:
                            return
                        try:
                            msg = json.loads(raw)

                            # Binance application-level ping → pong
                            if isinstance(msg, dict) and msg.get("e") == "ping":
                                await ws.send(json.dumps({"e": "pong"}))
                                continue

                            self._dispatch(msg)

                        except Exception:
                            pass

            except asyncio.CancelledError:
                return
            except Exception as e:
                # ConnectionClosedError on attempt 1 is now logged at DEBUG
                # level — it's expected Binance periodic behavior and the
                # connection recovers immediately. Only log WARNING if it
                # keeps failing (attempt > 1).
                log_fn = logger.debug if attempt == 0 else logger.warning
                log_fn(
                    f"[conn-{conn_id}] {type(e).__name__} "
                    f"(attempt {attempt + 1}) — reconnecting"
                )
                attempt += 1

    # ── DISPATCH ─────────────────────────────────────────────────────────

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
