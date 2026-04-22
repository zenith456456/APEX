"""
APEX-EDS v4.0 | exchange_monitor.py
─────────────────────────────────────────────────────────────────────────────
Fixes applied:
  1. REMOVED fstream1/2/3 from combined-stream WS fallbacks — those hosts do
     NOT support the ?streams= combined format. Only fstream.binance.com does.
  2. Reduced WS chunk size to 40 symbols (200 streams max per Binance limit).
  3. Added exponential back-off on reconnect (5s → 10s → 20s → 40s max).
  4. miniTicker uses its own single stable connection — not combined streams.
  5. ConnectionClosedError handled gracefully with back-off, not tight loop.

WebSocket streams used:
  wss://fstream.binance.com/ws/!miniTicker@arr     → live price/volume ALL syms
  wss://fstream.binance.com/stream?streams=...      → klines + aggTrade + book

REST only for (unavoidable):
  /fapi/v1/exchangeInfo   → pair list (no WS alternative)
  /fapi/v1/klines         → one-time history seed at startup
"""

import asyncio
import json
import logging
import time
from collections import deque
from typing import Dict, List, Optional, Set

import aiohttp
import websockets

import config

logger = logging.getLogger("ExchangeMonitor")

_HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 ApexEDS/4.0"}

# REST fallbacks (all support exchangeInfo + klines)
_REST_URLS = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
    "https://fapi4.binance.com",
]

# ── CRITICAL FIX ──────────────────────────────────────────────────────────
# Only fstream.binance.com supports the combined ?streams= format.
# fstream1/2/3 are CDN aliases for REST only — they do NOT handle combined WS.
# Using them caused InvalidURI errors on every reconnect attempt.
_COMBINED_WS_HOST = "wss://fstream.binance.com/stream"

# miniTicker broadcast — separate single-symbol stream, does not use combined
_MINI_TICKER_URL  = "wss://fstream.binance.com/ws/!miniTicker@arr"

# Max streams per combined WS connection (Binance hard limit = 200)
# 5 streams per symbol (3 klines + aggTrade + bookTicker)
# 40 symbols × 5 = 200 streams exactly — safe limit
_MAX_SYMBOLS_PER_WS = 40

# Exponential back-off: 5 → 10 → 20 → 40 → 40 → ... (capped at 40s)
_BACKOFF_BASE = 5
_BACKOFF_MAX  = 40


def _backoff(attempt: int) -> float:
    return min(_BACKOFF_BASE * (2 ** attempt), _BACKOFF_MAX)


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
            logger.error("No pairs loaded at startup — retrying in background")

        # Three independent WS coroutines
        asyncio.create_task(self._mini_ticker_ws())
        asyncio.create_task(self._ws_manager())
        asyncio.create_task(self._exchange_info_loop())

        logger.info(
            f"ExchangeMonitor: {len(self.active_pairs)} pairs | "
            f"REST: {self._rest_url} | "
            f"WS combined: {_COMBINED_WS_HOST}"
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

    # ── REST: ENDPOINT PROBE ──────────────────────────────────────────────

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
                    logger.warning(f"{base}: Binance error {data.get('code')}")
                    return set()
                found: Set[str] = set()
                for sym in data.get("symbols", []):
                    if (isinstance(sym, dict)
                            and sym.get("status") == "TRADING"
                            and sym.get("contractType") == "PERPETUAL"
                            and sym.get("quoteAsset") == "USDT"):
                        found.add(sym["symbol"])
                logger.info(f"{base}: {len(found)} pairs")
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
        logger.info(f"Seeding klines for {len(targets)} symbols (one-time REST)...")
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
        logger.info("Kline seed complete — live updates now via WebSocket")

    # ── EXCHANGE INFO LOOP ────────────────────────────────────────────────

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
    # One stable connection. Delivers price/volume/change for ALL symbols
    # every second. No combined-stream URL — uses /ws/ endpoint directly.

    async def _mini_ticker_ws(self):
        attempt = 0
        while self._running:
            try:
                async with websockets.connect(
                    _MINI_TICKER_URL,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=50_000_000,
                    extra_headers={"User-Agent": "Mozilla/5.0 ApexEDS/4.0"},
                ) as ws:
                    logger.info(f"miniTicker WS connected: {_MINI_TICKER_URL}")
                    attempt = 0   # reset back-off on success
                    async for raw in ws:
                        if not self._running:
                            return
                        try:
                            tickers = json.loads(raw)
                            if not isinstance(tickers, list):
                                continue
                            for t in tickers:
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
                delay = _backoff(attempt)
                logger.warning(
                    f"miniTicker WS error: {type(e).__name__} — "
                    f"reconnect in {delay}s (attempt {attempt+1})"
                )
                attempt += 1
                await asyncio.sleep(delay)

    # ── WS MANAGER: klines + aggTrade + bookTicker ────────────────────────

    async def _ws_manager(self):
        """
        Splits all pairs into chunks of _MAX_SYMBOLS_PER_WS.
        Each chunk opens one combined-stream connection on fstream.binance.com.
        Re-evaluates every hour (picks up new listings).
        """
        while self._running:
            for t in self._ws_tasks:
                t.cancel()
            self._ws_tasks.clear()

            pairs = list(self.active_pairs)
            if not pairs:
                logger.warning("WS manager: no pairs yet — waiting 30s")
                await asyncio.sleep(30)
                continue

            chunks = [
                pairs[i:i + _MAX_SYMBOLS_PER_WS]
                for i in range(0, len(pairs), _MAX_SYMBOLS_PER_WS)
            ]
            logger.info(
                f"WS manager: {len(pairs)} pairs → "
                f"{len(chunks)} connections "
                f"({_MAX_SYMBOLS_PER_WS} symbols each max)"
            )
            for chunk in chunks:
                self._ws_tasks.append(
                    asyncio.create_task(self._ws_connection(chunk))
                )

            # Rebuild connections every hour (new listings)
            await asyncio.sleep(config.EXCHANGE_INFO_TTL_SEC)

    async def _ws_connection(self, symbols: List[str]):
        """
        Combined-stream WebSocket for one chunk of symbols.
        Uses ONLY fstream.binance.com — fstream1/2/3 do NOT support
        the combined ?streams= format and cause InvalidURI errors.
        """
        streams = []
        for s in symbols:
            sl = s.lower()
            for iv in config.KLINE_INTERVALS:
                streams.append(f"{sl}@kline_{iv}")
            streams.append(f"{sl}@bookTicker")
            streams.append(f"{sl}@aggTrade")

        url     = f"{_COMBINED_WS_HOST}?streams=" + "/".join(streams)
        attempt = 0

        while True:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=10_000_000,
                    extra_headers={"User-Agent": "Mozilla/5.0 ApexEDS/4.0"},
                ) as ws:
                    logger.debug(
                        f"WS connected: {len(symbols)} symbols, "
                        f"{len(streams)} streams"
                    )
                    attempt = 0   # reset on successful connect
                    async for raw in ws:
                        if not self._running:
                            return
                        try:
                            self._dispatch(json.loads(raw))
                        except Exception:
                            pass

            except asyncio.CancelledError:
                return
            except Exception as e:
                delay = _backoff(attempt)
                logger.warning(
                    f"WS {_COMBINED_WS_HOST}: {type(e).__name__} — "
                    f"reconnect in {delay}s (attempt {attempt+1})"
                )
                attempt += 1
                await asyncio.sleep(delay)

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
