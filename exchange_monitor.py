"""
APEX-EDS v4.0 | exchange_monitor.py
Binance USDT-M Futures data layer with geo-block fallback.
 - Auto-detects working Binance endpoint at startup
 - Tries fapi.binance.com → fapi1 → fapi2 → fapi3 → fapi4
 - Same fallback for WebSocket streams
 - New listing detection every hour
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

_HEADERS = {
    "Accept":     "application/json",
    "User-Agent": "APEX-EDS/4.0",
}


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
        self.symbol    = symbol
        self.candles: Dict[str, deque] = {
            "1m": deque(maxlen=120),
            "5m": deque(maxlen=120),
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


# ─────────────────────────────────────────────────────────────────────────────
class ExchangeMonitor:

    def __init__(self):
        self.symbols:      Dict[str, SymbolData] = {}
        self.active_pairs: Set[str]              = set()
        self._session:     Optional[aiohttp.ClientSession] = None
        self._ws_tasks:    List[asyncio.Task]    = []
        self._running      = False
        self._base_url     = config.BINANCE_FUTURES_URLS[0]
        self._ws_url       = config.BINANCE_WS_URLS[0]

    # ── PUBLIC ────────────────────────────────────────────────────────────

    async def start(self):
        self._running = True
        self._session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=True, limit=60),
            headers=_HEADERS,
        )
        logger.info("ExchangeMonitor: starting...")

        # Probe all base URLs — find one that works
        found = await self._probe_endpoints()
        if not found:
            logger.critical(
                "All Binance endpoints returned HTTP 451 (geo-blocked).\n"
                "ACTION REQUIRED: Change your Northflank deployment region to\n"
                "  Europe (Frankfurt) or US East (Virginia) then redeploy."
            )
            # Keep running — will retry on next exchange_info_loop cycle
        else:
            logger.info(f"Using Binance endpoint: {self._base_url}")
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

    # ── ENDPOINT PROBE ────────────────────────────────────────────────────

    async def _probe_endpoints(self) -> bool:
        """
        Try each Binance futures base URL in order.
        Set self._base_url and self._ws_url to the first working one.
        Returns True if a working endpoint is found.
        """
        for rest_url, ws_url in zip(config.BINANCE_FUTURES_URLS,
                                     config.BINANCE_WS_URLS +
                                     [config.BINANCE_WS_URLS[-1]] * 10):
            try:
                probe = f"{rest_url}/fapi/v1/ping"
                async with self._session.get(
                    probe, timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    if r.status == 200:
                        self._base_url = rest_url
                        self._ws_url   = ws_url
                        logger.info(
                            f"Endpoint probe OK: {rest_url} (HTTP {r.status})"
                        )
                        return True
                    else:
                        logger.warning(
                            f"Endpoint probe {rest_url} → HTTP {r.status} "
                            f"(geo-blocked or unavailable)"
                        )
            except Exception as e:
                logger.warning(f"Endpoint probe {rest_url} → error: {e}")

        return False

    # ── EXCHANGE INFO LOOP ────────────────────────────────────────────────

    async def _exchange_info_loop(self):
        while self._running:
            await asyncio.sleep(config.EXCHANGE_INFO_TTL_SEC)
            try:
                # Re-probe in case region changed or endpoint recovered
                if not self.active_pairs:
                    found = await self._probe_endpoints()
                    if not found:
                        logger.error(
                            "Still geo-blocked. Change Northflank region to "
                            "EU (Frankfurt) or US East."
                        )
                        continue
                before = set(self.active_pairs)
                await self._refresh_exchange_info()
                new_pairs = self.active_pairs - before
                if new_pairs:
                    logger.info(f"New listings: {new_pairs}")
                    await self._bootstrap_klines(list(new_pairs))
            except Exception as e:
                logger.error(f"Exchange info loop: {e}")

    async def _refresh_exchange_info(self):
        url = f"{self._base_url}/fapi/v1/exchangeInfo"
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as r:
                if r.status == 451:
                    logger.error(
                        "Binance HTTP 451 — geo-blocked.\n"
                        "  → Go to Northflank → Service Settings → Region\n"
                        "  → Change to: Europe (Frankfurt) or US East (Virginia)\n"
                        "  → Save and redeploy."
                    )
                    return
                if r.status != 200:
                    text = await r.text()
                    logger.error(f"ExchangeInfo HTTP {r.status}: {text[:200]}")
                    return
                try:
                    data = await r.json(content_type=None)
                except Exception as e:
                    logger.error(f"ExchangeInfo JSON: {e}")
                    return
        except Exception as e:
            logger.error(f"ExchangeInfo request: {e}")
            return

        if not isinstance(data, dict):
            logger.error(f"ExchangeInfo unexpected type: {type(data)}")
            return

        symbols_list = data.get("symbols", [])
        if not isinstance(symbols_list, list):
            logger.error("ExchangeInfo 'symbols' not a list")
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
            logger.warning("ExchangeInfo returned 0 USDT-M pairs")
            return

        self.active_pairs = new_active
        logger.info(
            f"Exchange info refreshed — {len(self.active_pairs)} USDT-M pairs "
            f"via {self._base_url}"
        )

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
                url    = f"{self._base_url}/fapi/v1/klines"
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
                                    CandleBar(row[0], row[1], row[2],
                                              row[3], row[4], row[5], True)
                                )
                except Exception as e:
                    logger.debug(f"Kline {symbol}/{interval}: {e}")

        await asyncio.gather(*[
            fetch(s, iv) for s in targets for iv in config.KLINE_INTERVALS
        ])
        logger.info("Kline bootstrap complete")

    # ── 24H TICKER LOOP ───────────────────────────────────────────────────

    async def _ticker_loop(self):
        retry_delay = 60
        while self._running:
            if not self.active_pairs:
                await asyncio.sleep(30)
                continue
            try:
                url = f"{self._base_url}/fapi/v1/ticker/24hr"
                async with self._session.get(
                    url, timeout=aiohttp.ClientTimeout(total=30)
                ) as r:
                    if r.status == 451:
                        logger.warning(
                            "Ticker geo-blocked (451). "
                            "Change Northflank region to EU/US."
                        )
                        await asyncio.sleep(retry_delay)
                        continue
                    if r.status != 200:
                        logger.warning(f"Ticker HTTP {r.status}")
                        await asyncio.sleep(retry_delay)
                        continue
                    try:
                        tickers = await r.json(content_type=None)
                    except Exception as e:
                        logger.error(f"Ticker JSON: {e}")
                        await asyncio.sleep(retry_delay)
                        continue
                    if not isinstance(tickers, list):
                        logger.error(f"Ticker not a list: {type(tickers)}")
                        await asyncio.sleep(retry_delay)
                        continue

                    updated = 0
                    for t in tickers:
                        if not isinstance(t, dict):
                            continue
                        sym = t.get("symbol", "")
                        if sym in self.symbols:
                            sd = self.symbols[sym]
                            try:
                                sd.volume_24h       = float(t.get("quoteVolume", 0) or 0)
                                sd.price_change_24h = float(t.get("priceChangePercent", 0) or 0)
                                sd.last_price       = float(t.get("lastPrice", 0) or 0)
                                updated += 1
                            except (ValueError, TypeError):
                                pass

                    logger.debug(f"Ticker updated {updated} symbols")
                    retry_delay = 60   # reset on success

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
            if not pairs:
                logger.warning(
                    "WS manager: 0 pairs — waiting for exchange info. "
                    "If geo-blocked, change Northflank region to EU/US."
                )
                await asyncio.sleep(30)
                continue

            chunk = max(1, config.WS_STREAMS_PER_CONN // 5)
            chunks = [pairs[i:i+chunk] for i in range(0, len(pairs), chunk)]
            logger.info(
                f"WS: {len(pairs)} pairs → {len(chunks)} connections "
                f"via {self._ws_url}"
            )
            for c in chunks:
                self._ws_tasks.append(
                    asyncio.create_task(self._ws_connection(c))
                )

            await asyncio.sleep(config.EXCHANGE_INFO_TTL_SEC)

    async def _ws_connection(self, symbols: List[str]):
        streams = []
        for s in symbols:
            sl = s.lower()
            for iv in config.KLINE_INTERVALS:
                streams.append(f"{sl}@kline_{iv}")
            streams.append(f"{sl}@bookTicker")
            streams.append(f"{sl}@aggTrade")

        # Try each WS URL in order
        ws_candidates = list(dict.fromkeys(
            [self._ws_url] + config.BINANCE_WS_URLS
        ))

        while True:
            for ws_base in ws_candidates:
                url = f"{ws_base}?streams=" + "/".join(streams)
                try:
                    async with websockets.connect(
                        url,
                        ping_interval=20, ping_timeout=15,
                        max_size=10_000_000,
                        extra_headers={"User-Agent": "APEX-EDS/4.0"},
                    ) as ws:
                        logger.debug(
                            f"WS connected: {len(symbols)} symbols via {ws_base}"
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
                    logger.warning(f"WS {ws_base}: {e}")
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
        sd = self.symbols[sym]
        try:
            bar = CandleBar(k["t"], k["o"], k["h"],
                            k["l"], k["c"], k["v"], k["x"])
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
