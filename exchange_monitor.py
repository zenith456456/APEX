# ============================================================
#  APEX-EDS v4.0  |  exchange_monitor.py
#  Binance REST polling + WebSocket stream manager
#  Auto-detects new listings every hour
# ============================================================

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional, Set

import aiohttp
import websockets

import config

logger = logging.getLogger("ExchangeMonitor")


# ── DATA STRUCTURES ──────────────────────────────────────────
class CandleBar:
    __slots__ = ["t","o","h","l","c","v","closed"]
    def __init__(self, t, o, h, l, c, v, closed):
        self.t = t; self.o = float(o); self.h = float(h)
        self.l = float(l); self.c = float(c); self.v = float(v)
        self.closed = closed


class SymbolData:
    """Live rolling data for one symbol."""
    def __init__(self, symbol: str):
        self.symbol    = symbol
        self.candles   = {"1m": deque(maxlen=100),
                          "5m": deque(maxlen=100),
                          "15m": deque(maxlen=100)}
        self.last_trade_price: float = 0.0
        self.bid:  float = 0.0
        self.ask:  float = 0.0
        self.volume_24h: float = 0.0
        self.price_change_24h: float = 0.0   # percent
        self.buy_vol_accum:  float = 0.0     # rolling buy volume
        self.sell_vol_accum: float = 0.0     # rolling sell volume
        self.agg_trades: deque = deque(maxlen=500)
        self.updated_at: float = 0.0


# ── EXCHANGE MONITOR ─────────────────────────────────────────
class ExchangeMonitor:
    """
    Manages all Binance Futures data.
    - Fetches exchange info every hour (new listing detection)
    - Connects kline + bookTicker WebSocket streams
    - Maintains live SymbolData for every active pair
    """

    def __init__(self):
        self.symbols: Dict[str, SymbolData] = {}
        self.active_pairs: Set[str] = set()
        self._last_exchange_refresh: float = 0.0
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws_tasks: List[asyncio.Task] = []
        self._running = False

    # ── PUBLIC API ────────────────────────────────────────────

    async def start(self):
        """Entry point — call from main coroutine."""
        self._running = True
        self._session = aiohttp.ClientSession()
        logger.info("ExchangeMonitor starting…")

        # Initial load
        await self._refresh_exchange_info()
        await self._bootstrap_klines()

        # Launch background loops
        asyncio.create_task(self._exchange_info_loop())
        asyncio.create_task(self._ws_manager())
        asyncio.create_task(self._ticker_rest_loop())
        logger.info(f"Monitoring {len(self.active_pairs)} pairs")

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

    # ── EXCHANGE INFO (new listing detection) ─────────────────

    async def _exchange_info_loop(self):
        """Refresh exchange info every hour to catch new listings."""
        while self._running:
            await asyncio.sleep(config.EXCHANGE_INFO_TTL)
            try:
                before = set(self.active_pairs)
                await self._refresh_exchange_info()
                new_pairs = self.active_pairs - before
                if new_pairs:
                    logger.info(f"🆕 New listings detected: {new_pairs}")
                    # Bootstrap klines for new pairs only
                    await self._bootstrap_klines(symbols=list(new_pairs))
            except Exception as e:
                logger.error(f"Exchange info refresh error: {e}")

    async def _refresh_exchange_info(self):
        url = f"{config.BINANCE_BASE_URL}/fapi/v1/exchangeInfo"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                data = await r.json()
        except Exception as e:
            logger.error(f"ExchangeInfo fetch failed: {e}")
            return

        new_active = set()
        for sym in data.get("symbols", []):
            if (sym.get("status") == "TRADING"
                    and sym.get("contractType") == "PERPETUAL"
                    and sym.get("quoteAsset") == "USDT"
                    and sym.get("marginAsset") == "USDT"):
                s = sym["symbol"]
                new_active.add(s)
                if s not in self.symbols:
                    self.symbols[s] = SymbolData(s)
                    logger.debug(f"  Added: {s}")

        self.active_pairs = new_active
        self._last_exchange_refresh = time.time()
        logger.info(f"Exchange info refreshed — {len(self.active_pairs)} USDT-M perps active")

    # ── BOOTSTRAP KLINES (REST) ───────────────────────────────

    async def _bootstrap_klines(self, symbols: Optional[List[str]] = None):
        """Seed candle history from REST before WS takes over."""
        targets = symbols or list(self.active_pairs)
        logger.info(f"Bootstrapping klines for {len(targets)} symbols…")

        sem = asyncio.Semaphore(20)   # max 20 concurrent REST calls

        async def fetch_one(symbol: str, interval: str):
            async with sem:
                url = f"{config.BINANCE_BASE_URL}/fapi/v1/klines"
                params = {"symbol": symbol, "interval": interval, "limit": 100}
                try:
                    async with self._session.get(url, params=params,
                                                  timeout=aiohttp.ClientTimeout(total=10)) as r:
                        if r.status != 200:
                            return
                        rows = await r.json()
                        sd = self.symbols.get(symbol)
                        if not sd:
                            return
                        for row in rows:
                            bar = CandleBar(
                                t=row[0], o=row[1], h=row[2],
                                l=row[3], c=row[4], v=row[5],
                                closed=True
                            )
                            sd.candles[interval].append(bar)
                except Exception as e:
                    logger.debug(f"  kline fetch error {symbol}/{interval}: {e}")

        tasks = []
        for sym in targets:
            for iv in config.KLINE_INTERVALS:
                tasks.append(fetch_one(sym, iv))

        await asyncio.gather(*tasks)
        logger.info("Kline bootstrap complete")

    # ── TICKER LOOP (24h stats via REST) ─────────────────────

    async def _ticker_rest_loop(self):
        """Poll 24h ticker every 60s for volume + 24h change."""
        while self._running:
            try:
                url = f"{config.BINANCE_BASE_URL}/fapi/v1/ticker/24hr"
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    tickers = await r.json()
                for t in tickers:
                    sym = t.get("symbol", "")
                    if sym in self.symbols:
                        sd = self.symbols[sym]
                        sd.volume_24h = float(t.get("quoteVolume", 0))
                        sd.price_change_24h = float(t.get("priceChangePercent", 0))
                        sd.last_trade_price = float(t.get("lastPrice", 0))
            except Exception as e:
                logger.error(f"Ticker REST error: {e}")
            await asyncio.sleep(60)

    # ── WEBSOCKET MANAGER ─────────────────────────────────────

    async def _ws_manager(self):
        """
        Split all pairs into groups of WS_STREAMS_PER_CONN and
        maintain one combined-stream connection per group.
        """
        while self._running:
            for t in self._ws_tasks:
                t.cancel()
            self._ws_tasks.clear()

            pairs = list(self.active_pairs)
            # Each connection handles N symbols × 3 intervals
            chunk_size = config.WS_STREAMS_PER_CONN // (len(config.KLINE_INTERVALS) + 1)
            chunks = [pairs[i:i+chunk_size] for i in range(0, len(pairs), chunk_size)]

            for chunk in chunks:
                t = asyncio.create_task(self._ws_connection(chunk))
                self._ws_tasks.append(t)

            # Re-evaluate connections every hour (picks up new listings)
            await asyncio.sleep(config.EXCHANGE_INFO_TTL)

    async def _ws_connection(self, symbols: List[str]):
        """Single combined-stream WebSocket for a subset of symbols."""
        streams = []
        for sym in symbols:
            s = sym.lower()
            for iv in config.KLINE_INTERVALS:
                streams.append(f"{s}@kline_{iv}")
            streams.append(f"{s}@bookTicker")
            streams.append(f"{s}@aggTrade")

        url = f"{config.BINANCE_WS_BASE}?streams=" + "/".join(streams)

        while True:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    max_size=10_000_000
                ) as ws:
                    logger.debug(f"WS connected: {len(symbols)} symbols")
                    async for raw in ws:
                        if not self._running:
                            return
                        try:
                            msg = json.loads(raw)
                            self._dispatch(msg)
                        except Exception:
                            pass
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"WS error: {e} — reconnecting in {config.WS_RECONNECT_DELAY}s")
                await asyncio.sleep(config.WS_RECONNECT_DELAY)

    def _dispatch(self, msg: dict):
        data = msg.get("data", msg)
        stream = msg.get("stream", "")

        if "@kline_" in stream:
            self._handle_kline(data)
        elif "@bookTicker" in stream:
            self._handle_book(data)
        elif "@aggTrade" in stream:
            self._handle_agg_trade(data)

    def _handle_kline(self, data: dict):
        k = data.get("k", {})
        sym = k.get("s", "")
        iv  = k.get("i", "")
        if sym not in self.symbols or iv not in config.KLINE_INTERVALS:
            return
        sd = self.symbols[sym]
        bar = CandleBar(
            t=k["t"], o=k["o"], h=k["h"],
            l=k["l"], c=k["c"], v=k["v"],
            closed=k["x"]
        )
        candles = sd.candles[iv]
        if candles and not candles[-1].closed:
            candles[-1] = bar      # update current open bar
        else:
            candles.append(bar)    # new bar
        sd.updated_at = time.time()

    def _handle_book(self, data: dict):
        sym = data.get("s", "")
        if sym in self.symbols:
            sd = self.symbols[sym]
            sd.bid = float(data.get("b", 0))
            sd.ask = float(data.get("a", 0))

    def _handle_agg_trade(self, data: dict):
        sym = data.get("s", "")
        if sym not in self.symbols:
            return
        sd = self.symbols[sym]
        price = float(data.get("p", 0))
        qty   = float(data.get("q", 0))
        maker = data.get("m", False)   # True = sell taker (price went down)
        if maker:
            sd.sell_vol_accum += qty * price
        else:
            sd.buy_vol_accum  += qty * price
        sd.agg_trades.append({"p": price, "q": qty, "m": maker, "t": data.get("T", 0)})
        sd.last_trade_price = price
        sd.updated_at = time.time()
