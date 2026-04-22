"""
APEX-EDS v4.0 | exchange_monitor.py
─────────────────────────────────────────────────────────────────────────────
DATA SOURCE:  100% Binance WebSocket streams — NO REST polling for market data
─────────────────────────────────────────────────────────────────────────────

WebSocket streams used:
  !miniTicker@arr          → 24h price, volume, change % for ALL symbols (1 connection)
  {sym}@kline_1m           → 1-minute candles
  {sym}@kline_5m           → 5-minute candles
  {sym}@kline_15m          → 15-minute candles
  {sym}@aggTrade           → Aggregate trades for CVD + VPIN
  {sym}@bookTicker         → Best bid/ask for spread score

REST is used ONLY for:
  /fapi/v1/exchangeInfo    → Get list of active trading pairs (no WS alternative)
  /fapi/v1/klines          → Seed initial candle history (needed once at startup
                             because WS klines only deliver the current open bar)
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

_REST_URLS = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
    "https://fapi4.binance.com",
]

_WS_URLS = [
    "wss://fstream.binance.com/stream",
    "wss://fstream1.binance.com/stream",
    "wss://fstream2.binance.com/stream",
    "wss://fstream3.binance.com/stream",
]

# Mini-ticker broadcast — delivers stats for every symbol every second
_MINI_TICKER_WS = "wss://fstream.binance.com/ws/!miniTicker@arr"
_MINI_TICKER_WS_FALLBACKS = [
    "wss://fstream.binance.com/ws/!miniTicker@arr",
    "wss://fstream1.binance.com/ws/!miniTicker@arr",
    "wss://fstream2.binance.com/ws/!miniTicker@arr",
]


# ─────────────────────────────────────────────────────────────────────────────
class CandleBar:
    __slots__ = ["t", "o", "h", "l", "c", "v", "closed"]

    def __init__(self, t, o, h, l, c, v, closed):
        self.t = t
        self.o = float(o); self.h = float(h)
        self.l = float(l); self.c = float(c)
        self.v = float(v); self.closed = bool(closed)


class SymbolData:
    """Live market data for one trading pair — fed entirely by WebSocket."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.candles: Dict[str, deque] = {
            "1m":  deque(maxlen=120),
            "5m":  deque(maxlen=120),
            "15m": deque(maxlen=120),
        }
        # Filled by !miniTicker@arr WebSocket stream
        self.last_price:       float = 0.0
        self.price_change_24h: float = 0.0   # percent
        self.volume_24h:       float = 0.0   # quote volume in USDT

        # Filled by bookTicker WebSocket stream
        self.bid: float = 0.0
        self.ask: float = 0.0

        # Filled by aggTrade WebSocket stream (used for CVD + VPIN)
        self.buy_vol:    float = 0.0   # rolling buy volume USDT
        self.sell_vol:   float = 0.0   # rolling sell volume USDT
        self.agg_trades: deque = deque(maxlen=500)

        self.updated_at: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
class ExchangeMonitor:
    """
    Manages all market data via Binance WebSocket streams.
    REST is used only to:
      1. Get the list of active USDT-M perpetual pairs (exchangeInfo)
      2. Seed historical kline data once at startup
    All live price/volume data arrives via WebSocket.
    """

    def __init__(self):
        self.symbols:      Dict[str, SymbolData] = {}
        self.active_pairs: Set[str]              = set()
        self._session:     Optional[aiohttp.ClientSession] = None
        self._ws_tasks:    List[asyncio.Task]    = []
        self._running      = False
        self._rest_url     = _REST_URLS[0]
        self._ws_url       = _WS_URLS[0]

    # ── PUBLIC ────────────────────────────────────────────────────────────

    async def start(self):
        self._running = True
        self._session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=True, limit=60),
            headers=_HEADERS,
        )
        logger.info("ExchangeMonitor: starting (WebSocket-first mode)...")

        # Step 1: Find a working REST endpoint (only used for pair list + kline seed)
        await self._find_rest_endpoint()

        # Step 2: Seed historical klines via REST (one-time, gives instant scoring)
        if self.active_pairs:
            await self._seed_klines_rest()
        else:
            logger.error("No pairs loaded at startup — will retry in background")

        # Step 3: Start all WebSocket streams
        asyncio.create_task(self._mini_ticker_ws())   # 24h stats for ALL symbols
        asyncio.create_task(self._ws_manager())        # klines + aggTrade + bookTicker
        asyncio.create_task(self._exchange_info_loop()) # hourly pair list refresh

        logger.info(
            f"ExchangeMonitor: {len(self.active_pairs)} pairs | "
            f"All live data via WebSocket"
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
    # Only called once at startup and hourly for pair list refresh.

    async def _find_rest_endpoint(self):
        for i, url in enumerate(_REST_URLS):
            logger.info(f"Testing REST endpoint: {url}")
            pairs = await self._fetch_exchange_info(url)
            if pairs:
                self._rest_url = url
                self._ws_url   = _WS_URLS[min(i, len(_WS_URLS) - 1)]
                self.active_pairs = pairs
                for s in pairs:
                    if s not in self.symbols:
                        self.symbols[s] = SymbolData(s)
                logger.info(f"REST endpoint OK: {url} → {len(pairs)} USDT-M pairs")
                return
        logger.error("All REST endpoints failed. Will retry hourly.")

    async def _fetch_exchange_info(self, base: str) -> Set[str]:
        """Fetch active USDT-M perpetual pair list from REST (unavoidable)."""
        url = f"{base}/fapi/v1/exchangeInfo"
        try:
            async with self._session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=True,
            ) as r:
                if r.status == 451:
                    logger.warning(f"{base}: HTTP 451 geo-blocked")
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
                logger.info(f"{base}: {len(found)} USDT-M pairs found")
                return found
        except asyncio.TimeoutError:
            logger.warning(f"{base}: timeout")
            return set()
        except Exception as e:
            logger.warning(f"{base}: {e}")
            return set()

    # ── REST: SEED KLINE HISTORY (one-time at startup) ────────────────────
    # WebSocket kline streams only deliver the current open bar going forward.
    # Without seeding, the bot needs to wait 30×5min = 150min before scoring.
    # This one-time REST fetch fills the deque so scoring starts immediately.

    async def _seed_klines_rest(self, symbols: Optional[List[str]] = None):
        targets = symbols or list(self.active_pairs)
        if not targets:
            return
        logger.info(f"Seeding kline history for {len(targets)} symbols via REST (one-time)...")
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
                        try:
                            rows = await r.json(content_type=None)
                        except Exception:
                            return
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
        logger.info("Kline history seeded. Live updates now via WebSocket only.")

    # ── HOURLY EXCHANGE INFO LOOP ─────────────────────────────────────────

    async def _exchange_info_loop(self):
        """Refresh pair list every hour to catch new listings."""
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
                    logger.warning("Exchange info refresh failed — re-probing endpoints")
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
                    logger.info(f"Delisted pairs: {removed}")

                logger.info(
                    f"Exchange info refreshed — {len(self.active_pairs)} pairs"
                )
            except Exception as e:
                logger.error(f"Exchange info loop: {e}")

    # ── WEBSOCKET: !miniTicker@arr ────────────────────────────────────────
    # Single stream delivers 24h stats (price, volume, change%) for ALL
    # symbols every second. Replaces the REST ticker polling entirely.

    async def _mini_ticker_ws(self):
        """
        Subscribe to !miniTicker@arr — delivers a list of all symbol stats
        every second. Updates last_price, price_change_24h, volume_24h
        for every active symbol without any REST calls.
        """
        ws_urls = _MINI_TICKER_WS_FALLBACKS.copy()
        url_idx = 0

        while self._running:
            url = ws_urls[url_idx % len(ws_urls)]
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=15,
                    max_size=50_000_000,   # miniTicker payload is large
                    extra_headers={"User-Agent": "Mozilla/5.0 ApexEDS/4.0"},
                ) as ws:
                    logger.info(f"miniTicker WS connected: {url}")
                    async for raw in ws:
                        if not self._running:
                            return
                        try:
                            tickers = json.loads(raw)
                            if not isinstance(tickers, list):
                                continue
                            updated = 0
                            for t in tickers:
                                if not isinstance(t, dict):
                                    continue
                                sym = t.get("s", "")
                                if sym not in self.symbols:
                                    continue
                                sd = self.symbols[sym]
                                try:
                                    # e: event type, s: symbol
                                    # c: close price, p: price change %
                                    # q: quote volume (USDT)
                                    sd.last_price       = float(t.get("c", 0) or 0)
                                    sd.price_change_24h = float(t.get("P", 0) or 0)
                                    sd.volume_24h       = float(t.get("q", 0) or 0)
                                    if sd.last_price > 0:
                                        sd.updated_at = time.time()
                                    updated += 1
                                except (ValueError, TypeError):
                                    pass
                            if updated > 0:
                                logger.debug(
                                    f"miniTicker: updated {updated} symbols"
                                )
                        except json.JSONDecodeError:
                            pass
                        except Exception as e:
                            logger.debug(f"miniTicker dispatch: {e}")

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(
                    f"miniTicker WS error ({url}): {e} — "
                    f"reconnecting in {config.WS_RECONNECT_DELAY}s"
                )
                url_idx += 1
                await asyncio.sleep(config.WS_RECONNECT_DELAY)

    # ── WEBSOCKET: klines + aggTrade + bookTicker ─────────────────────────

    async def _ws_manager(self):
        """
        Split all pairs into chunks and open one combined WS per chunk.
        Each connection handles: kline_1m + kline_5m + kline_15m +
                                 aggTrade + bookTicker  (5 streams per symbol)
        """
        while self._running:
            for t in self._ws_tasks:
                t.cancel()
            self._ws_tasks.clear()

            pairs = list(self.active_pairs)
            if not pairs:
                logger.warning("WS manager: no pairs yet, waiting 30s...")
                await asyncio.sleep(30)
                continue

            chunk = max(1, config.WS_STREAMS_PER_CONN // 5)
            chunks = [pairs[i:i+chunk] for i in range(0, len(pairs), chunk)]

            logger.info(
                f"WS manager: {len(pairs)} pairs → "
                f"{len(chunks)} connections via {self._ws_url}"
            )
            for c in chunks:
                self._ws_tasks.append(
                    asyncio.create_task(self._ws_connection(c))
                )

            await asyncio.sleep(config.EXCHANGE_INFO_TTL_SEC)

    async def _ws_connection(self, symbols: List[str]):
        """Single combined-stream WebSocket for a subset of symbols."""
        streams = []
        for s in symbols:
            sl = s.lower()
            for iv in config.KLINE_INTERVALS:
                streams.append(f"{sl}@kline_{iv}")
            streams.append(f"{sl}@bookTicker")
            streams.append(f"{sl}@aggTrade")

        ws_candidates = list(dict.fromkeys([self._ws_url] + _WS_URLS))

        while True:
            for ws_base in ws_candidates:
                url = f"{ws_base}?streams=" + "/".join(streams)
                try:
                    async with websockets.connect(
                        url,
                        ping_interval=20,
                        ping_timeout=15,
                        max_size=10_000_000,
                        extra_headers={"User-Agent": "Mozilla/5.0 ApexEDS/4.0"},
                    ) as ws:
                        logger.debug(
                            f"WS connected: {len(symbols)} symbols "
                            f"({len(streams)} streams)"
                        )
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
                    logger.warning(
                        f"WS {ws_base}: {type(e).__name__} — "
                        f"reconnect in {config.WS_RECONNECT_DELAY}s"
                    )
                    await asyncio.sleep(config.WS_RECONNECT_DELAY)

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
        """
        Handles kline WebSocket messages.
        Updates the rolling candle deque for 1m, 5m, 15m intervals.
        Closed bars (x=True) are appended; open bars replace the last entry.
        """
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
            q[-1] = bar       # update current open bar
        else:
            q.append(bar)     # new bar started
        # Note: last_price is set by miniTicker, not kline
        sd.updated_at = time.time()

    def _on_book(self, data: dict):
        """
        Handles bookTicker WebSocket messages.
        Provides best bid/ask for spread quality scoring.
        """
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
        """
        Handles aggTrade WebSocket messages.
        Accumulates buy/sell volume for CVD and VPIN calculation.
        m=True means the buyer was the market maker (sell trade).
        m=False means the seller was the market maker (buy trade).
        """
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
                sd.sell_vol += usdt   # sell pressure
            else:
                sd.buy_vol  += usdt   # buy pressure

            sd.agg_trades.append({"p": price, "q": qty, "m": maker})

            # aggTrade also updates last_price as a high-frequency backup
            # (miniTicker is primary, aggTrade fills gaps between updates)
            if price > 0:
                sd.last_price = price
                sd.updated_at = time.time()

        except (ValueError, TypeError):
            pass
