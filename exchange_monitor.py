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

# Common headers for all Binance REST calls
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "APEX-EDS/4.0",
}


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
        self.last_price:       float = 0.0
        self.bid:              float = 0.0
        self.ask:              float = 0.0
        self.volume_24h:       float = 0.0
        self.price_change_24h: float = 0.0
        self.buy_vol:          float = 0.0
        self.sell_vol:         float = 0.0
        self.agg_trades:       deque = deque(maxlen=500)
        self.updated_at:       float = 0.0


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
        connector = aiohttp.TCPConnector(ssl=True, limit=50)
        self._session = aiohttp.ClientSession(
            connector=connector,
            headers=_HEADERS,
        )
        logger.info("ExchangeMonitor: starting...")
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

    # ── EXCHANGE INFO LOOP ────────────────────────────────────────────────

    async def _exchange_info_loop(self):
        while self._running:
            await asyncio.sleep(config.EXCHANGE_INFO_TTL_SEC)
            try:
                before = set(self.active_pairs)
                await self._refresh_exchange_info()
                new_pairs = self.active_pairs - before
                if new_pairs:
                    logger.info(f"New listings detected: {new_pairs}")
                    await self._bootstrap_klines(list(new_pairs))
            except Exception as e:
                logger.error(f"Exchange info refresh error: {e}")

    async def _refresh_exchange_info(self):
        url = f"{config.BINANCE_BASE_URL}/fapi/v1/exchangeInfo"
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as r:
                if r.status != 200:
                    text = await r.text()
                    logger.error(f"ExchangeInfo HTTP {r.status}: {text[:200]}")
                    return

                # Safely parse JSON
                try:
                    data = await r.json(content_type=None)
                except Exception as e:
                    text = await r.text()
                    logger.error(f"ExchangeInfo JSON parse error: {e} | body: {text[:200]}")
                    return

        except Exception as e:
            logger.error(f"ExchangeInfo request failed: {e}")
            return

        # Validate response structure
        if not isinstance(data, dict):
            logger.error(f"ExchangeInfo unexpected type: {type(data)}")
            return

        symbols_list = data.get("symbols", [])
        if not isinstance(symbols_list, list):
            logger.error(f"ExchangeInfo 'symbols' is not a list: {type(symbols_list)}")
            return

        new_active: Set[str] = set()
        for sym in symbols_list:
            if not isinstance(sym, dict):
                continue
            if (sym.get("status") == "TRADING"
                    and sym.get("contractType") == "PERPETUAL"
                    and sym.get("quoteAsset") == "USDT"):
                s = sym["symbol"]
                new_active.add(s)
                if s not in self.symbols:
                    self.symbols[s] = SymbolData(s)

        if not new_active:
            logger.warning(
                "ExchangeInfo returned 0 USDT-M perpetuals. "
                "Possible geo-block or API change. Retrying in 60s..."
            )
            # Retry once after a short wait
            await asyncio.sleep(60)
            return

        self.active_pairs = new_active
        logger.info(f"Exchange info refreshed — {len(self.active_pairs)} USDT-M pairs active")

    # ── KLINE BOOTSTRAP ───────────────────────────────────────────────────

    async def _bootstrap_klines(self, symbols: Optional[List[str]] = None):
        targets = symbols or list(self.active_pairs)
        if not targets:
            logger.warning("Bootstrap: no symbols to fetch")
            return
        logger.info(f"Bootstrapping klines for {len(targets)} symbols...")
        sem = asyncio.Semaphore(20)

        async def fetch(symbol: str, interval: str):
            async with sem:
                url = f"{config.BINANCE_BASE_URL}/fapi/v1/klines"
                params = {"symbol": symbol, "interval": interval, "limit": 100}
                try:
                    async with self._session.get(
                        url, params=params,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as r:
                        if r.status != 200:
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
                    logger.debug(f"Kline {symbol}/{interval}: {e}")

        tasks = [fetch(s, iv) for s in targets for iv in config.KLINE_INTERVALS]
        await asyncio.gather(*tasks)
        logger.info("Kline bootstrap complete")

    # ── 24H TICKER LOOP ───────────────────────────────────────────────────

    async def _ticker_loop(self):
        while self._running:
            try:
                url = f"{config.BINANCE_BASE_URL}/fapi/v1/ticker/24hr"
                async with self._session.get(
                    url, timeout=aiohttp.ClientTimeout(total=30)
                ) as r:
                    if r.status != 200:
                        logger.warning(f"Ticker HTTP {r.status}")
                        await asyncio.sleep(60)
                        continue

                    try:
                        tickers = await r.json(content_type=None)
                    except Exception as e:
                        logger.error(f"Ticker JSON parse: {e}")
                        await asyncio.sleep(60)
                        continue

                    # Must be a list of dicts
                    if not isinstance(tickers, list):
                        logger.error(
                            f"Ticker response is not a list: {type(tickers)} "
                            f"— value: {str(tickers)[:200]}"
                        )
                        await asyncio.sleep(60)
                        continue

                    updated = 0
                    for t in tickers:
                        if not isinstance(t, dict):
                            continue
                        sym = t.get("symbol", "")
                        if sym in self.symbols:
                            sd = self.symbols[sym]
                            sd.volume_24h       = float(t.get("quoteVolume", 0) or 0)
                            sd.price_change_24h = float(t.get("priceChangePercent", 0) or 0)
                            sd.last_price       = float(t.get("lastPrice", 0) or 0)
                            updated += 1

                    logger.debug(f"Ticker updated {updated} symbols")

            except Exception as e:
                logger.error(f"Ticker loop exception: {e}")

            await asyncio.sleep(60)

    # ── WEBSOCKET MANAGER ─────────────────────────────────────────────────

    async def _ws_manager(self):
        while self._running:
            for t in self._ws_tasks:
                t.cancel()
            self._ws_tasks.clear()

            pairs = list(self.active_pairs)
            if not pairs:
                logger.warning("WS manager: no pairs to stream, waiting 30s...")
                await asyncio.sleep(30)
                continue

            # 5 streams per symbol: 3 klines + bookTicker + aggTrade
            chunk = max(1, config.WS_STREAMS_PER_CONN // 5)
            chunks = [pairs[i:i+chunk] for i in range(0, len(pairs), chunk)]
            logger.info(f"WS manager: {len(pairs)} pairs across {len(chunks)} connections")

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
                    url,
                    ping_interval=20,
                    ping_timeout=15,
                    max_size=10_000_000,
                    extra_headers={"User-Agent": "APEX-EDS/4.0"},
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
                logger.warning(
                    f"WS error ({len(symbols)} symbols): {e} "
                    f"— reconnect in {config.WS_RECONNECT_DELAY}s"
                )
                await asyncio.sleep(config.WS_RECONNECT_DELAY)

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
        sd  = self.symbols[sym]
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
                sd.bid = float(data.get("b", 0) or 0)
                sd.ask = float(data.get("a", 0) or 0)
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
            sd.last_price = price
            sd.updated_at = time.time()
        except (ValueError, TypeError):
            pass
