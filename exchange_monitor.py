"""
APEX-EDS v4.0 | exchange_monitor.py
Binance USDT-M Futures data layer.
 - Fetches all active perpetual pairs via REST every hour (new listing detection)
 - Opens combined WebSocket streams for klines + aggTrade + bookTicker
 - Maintains live SymbolData for every pair
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


class CandleBar:
    __slots__ = ["t", "o", "h", "l", "c", "v", "closed"]

    def __init__(self, t, o, h, l, c, v, closed):
        self.t = t
        self.o = float(o)
        self.h = float(h)
        self.l = float(l)
        self.c = float(c)
        self.v = float(v)
        self.closed = bool(closed)


class SymbolData:
    """Holds all live data for one trading pair."""

    def __init__(self, symbol: str):
        self.symbol    = symbol
        self.candles: Dict[str, deque] = {
            "1m":  deque(maxlen=120),
            "5m":  deque(maxlen=120),
            "15m": deque(maxlen=120),
        }
        self.last_price:      float = 0.0
        self.bid:             float = 0.0
        self.ask:             float = 0.0
        self.volume_24h:      float = 0.0
        self.price_change_24h: float = 0.0   # percent
        self.buy_vol:         float = 0.0    # rolling buy volume (USDT)
        self.sell_vol:        float = 0.0    # rolling sell volume (USDT)
        self.agg_trades:      deque = deque(maxlen=500)
        self.updated_at:      float = 0.0


class ExchangeMonitor:
    """Manages all Binance Futures data feeds."""

    def __init__(self):
        self.symbols: Dict[str, SymbolData] = {}
        self.active_pairs: Set[str] = set()
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws_tasks: List[asyncio.Task] = []
        self._running = False

    # ── PUBLIC ────────────────────────────────────────────────────────────

    async def start(self):
        self._running = True
        self._session = aiohttp.ClientSession()
        logger.info("ExchangeMonitor: starting…")
        await self._refresh_exchange_info()
        await self._bootstrap_klines()
        asyncio.create_task(self._exchange_info_loop())
        asyncio.create_task(self._ws_manager())
        asyncio.create_task(self._ticker_loop())
        logger.info(f"ExchangeMonitor: monitoring {len(self.active_pairs)} pairs")

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

    # ── EXCHANGE INFO LOOP (new listing detection) ────────────────────────

    async def _exchange_info_loop(self):
        while self._running:
            await asyncio.sleep(config.EXCHANGE_INFO_TTL_SEC)
            try:
                before = set(self.active_pairs)
                await self._refresh_exchange_info()
                new_pairs = self.active_pairs - before
                if new_pairs:
                    logger.info(f"🆕 New listings: {new_pairs}")
                    await self._bootstrap_klines(list(new_pairs))
            except Exception as e:
                logger.error(f"Exchange info refresh: {e}")

    async def _refresh_exchange_info(self):
        url = f"{config.BINANCE_BASE_URL}/fapi/v1/exchangeInfo"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                data = await r.json()
        except Exception as e:
            logger.error(f"ExchangeInfo fetch failed: {e}")
            return

        new_active: Set[str] = set()
        for sym in data.get("symbols", []):
            if (sym.get("status") == "TRADING"
                    and sym.get("contractType") == "PERPETUAL"
                    and sym.get("quoteAsset") == "USDT"):
                s = sym["symbol"]
                new_active.add(s)
                if s not in self.symbols:
                    self.symbols[s] = SymbolData(s)

        self.active_pairs = new_active
        logger.info(f"Exchange info refreshed — {len(self.active_pairs)} pairs active")

    # ── KLINE BOOTSTRAP (REST) ────────────────────────────────────────────

    async def _bootstrap_klines(self, symbols: Optional[List[str]] = None):
        targets = symbols or list(self.active_pairs)
        logger.info(f"Bootstrapping klines for {len(targets)} symbols…")
        sem = asyncio.Semaphore(20)

        async def fetch(symbol: str, interval: str):
            async with sem:
                url = f"{config.BINANCE_BASE_URL}/fapi/v1/klines"
                params = {"symbol": symbol, "interval": interval, "limit": 100}
                try:
                    async with self._session.get(
                        url, params=params, timeout=aiohttp.ClientTimeout(total=15)
                    ) as r:
                        if r.status != 200:
                            return
                        rows = await r.json()
                        sd = self.symbols.get(symbol)
                        if not sd:
                            return
                        for row in rows:
                            sd.candles[interval].append(
                                CandleBar(row[0], row[1], row[2], row[3], row[4], row[5], True)
                            )
                except Exception as e:
                    logger.debug(f"Kline {symbol}/{interval}: {e}")

        tasks = [fetch(s, iv) for s in targets for iv in config.KLINE_INTERVALS]
        await asyncio.gather(*tasks)
        logger.info("Kline bootstrap complete")

    # ── 24H TICKER LOOP ───────────────────────────────────────────────────

    async def _ticker_loop(self):
        while self._running:
            try:
                url = f"{config.BINANCE_BASE_URL}/fapi/v1/ticker/24hr"
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    tickers = await r.json()
                for t in tickers:
                    sym = t.get("symbol", "")
                    if sym in self.symbols:
                        sd = self.symbols[sym]
                        sd.volume_24h = float(t.get("quoteVolume", 0))
                        sd.price_change_24h = float(t.get("priceChangePercent", 0))
                        sd.last_price = float(t.get("lastPrice", 0))
            except Exception as e:
                logger.error(f"Ticker loop: {e}")
            await asyncio.sleep(60)

    # ── WEBSOCKET MANAGER ─────────────────────────────────────────────────

    async def _ws_manager(self):
        while self._running:
            for t in self._ws_tasks:
                t.cancel()
            self._ws_tasks.clear()

            pairs = list(self.active_pairs)
            # streams per symbol: 3 klines + bookTicker + aggTrade = 5
            chunk = max(1, config.WS_STREAMS_PER_CONN // 5)
            chunks = [pairs[i:i+chunk] for i in range(0, len(pairs), chunk)]

            for c in chunks:
                task = asyncio.create_task(self._ws_connection(c))
                self._ws_tasks.append(task)

            await asyncio.sleep(config.EXCHANGE_INFO_TTL_SEC)

    async def _ws_connection(self, symbols: List[str]):
        streams = []
        for s in symbols:
            sl = s.lower()
            for iv in config.KLINE_INTERVALS:
                streams.append(f"{sl}@kline_{iv}")
            streams.append(f"{sl}@bookTicker")
            streams.append(f"{sl}@aggTrade")

        url = f"{config.BINANCE_WS_BASE}?streams=" + "/".join(streams)

        while True:
            try:
                async with websockets.connect(
                    url, ping_interval=20, ping_timeout=15, max_size=10_000_000
                ) as ws:
                    logger.debug(f"WS connected: {len(symbols)} symbols")
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
                logger.warning(f"WS error: {e} — reconnect in {config.WS_RECONNECT_DELAY}s")
                await asyncio.sleep(config.WS_RECONNECT_DELAY)

    def _dispatch(self, msg: dict):
        data   = msg.get("data", msg)
        stream = msg.get("stream", "")
        if "@kline_" in stream:
            self._on_kline(data)
        elif "@bookTicker" in stream:
            self._on_book(data)
        elif "@aggTrade" in stream:
            self._on_trade(data)

    def _on_kline(self, data: dict):
        k = data.get("k", {})
        sym = k.get("s", "")
        iv  = k.get("i", "")
        if sym not in self.symbols or iv not in config.KLINE_INTERVALS:
            return
        sd  = self.symbols[sym]
        bar = CandleBar(k["t"], k["o"], k["h"], k["l"], k["c"], k["v"], k["x"])
        q   = sd.candles[iv]
        if q and not q[-1].closed:
            q[-1] = bar
        else:
            q.append(bar)
        sd.updated_at = time.time()

    def _on_book(self, data: dict):
        sym = data.get("s", "")
        if sym in self.symbols:
            sd = self.symbols[sym]
            sd.bid = float(data.get("b", 0))
            sd.ask = float(data.get("a", 0))

    def _on_trade(self, data: dict):
        sym = data.get("s", "")
        if sym not in self.symbols:
            return
        sd    = self.symbols[sym]
        price = float(data.get("p", 0))
        qty   = float(data.get("q", 0))
        maker = data.get("m", False)
        usdt  = price * qty
        if maker:
            sd.sell_vol += usdt
        else:
            sd.buy_vol += usdt
        sd.agg_trades.append({"p": price, "q": qty, "m": maker})
        sd.last_price = price
        sd.updated_at = time.time()
