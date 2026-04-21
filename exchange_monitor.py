"""
APEX-EDS v4.0 | exchange_monitor.py
Binance USDT-M Futures data layer.
Accepts HTTP 200 and 202 from Binance CDN nodes.
Auto-detects new listings every hour.
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


class CandleBar:
    __slots__ = ["t","o","h","l","c","v","closed"]
    def __init__(self, t, o, h, l, c, v, closed):
        self.t=t; self.o=float(o); self.h=float(h); self.l=float(l)
        self.c=float(c); self.v=float(v); self.closed=bool(closed)


class SymbolData:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.candles: Dict[str, deque] = {"1m":deque(maxlen=120),"5m":deque(maxlen=120),"15m":deque(maxlen=120)}
        self.last_price=0.0; self.bid=0.0; self.ask=0.0
        self.volume_24h=0.0; self.price_change_24h=0.0
        self.buy_vol=0.0; self.sell_vol=0.0
        self.agg_trades: deque = deque(maxlen=500)
        self.updated_at=0.0


class ExchangeMonitor:

    def __init__(self):
        self.symbols:      Dict[str, SymbolData] = {}
        self.active_pairs: Set[str]              = set()
        self._session:     Optional[aiohttp.ClientSession] = None
        self._ws_tasks:    List[asyncio.Task]    = []
        self._running      = False
        self._rest_url     = config.BINANCE_FUTURES_URLS[0]
        self._ws_url       = config.BINANCE_WS_URLS[0]

    async def start(self):
        self._running = True
        self._session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=True,limit=60),headers=_HEADERS)
        logger.info("ExchangeMonitor: starting...")
        await self._find_endpoint()
        if self.active_pairs:
            await self._bootstrap_klines()
        else:
            logger.error("No pairs loaded — will retry every 60s in background")
        asyncio.create_task(self._info_loop())
        asyncio.create_task(self._ws_manager())
        asyncio.create_task(self._ticker_loop())
        logger.info(f"Monitoring {len(self.active_pairs)} pairs via {self._rest_url}")

    async def stop(self):
        self._running = False
        for t in self._ws_tasks: t.cancel()
        if self._session: await self._session.close()

    def get_symbol_data(self, symbol: str) -> Optional[SymbolData]:
        return self.symbols.get(symbol)

    def get_all_symbols(self) -> List[str]:
        return list(self.active_pairs)

    # ── ENDPOINT DISCOVERY ────────────────────────────────────────────────

    async def _find_endpoint(self):
        for i, url in enumerate(config.BINANCE_FUTURES_URLS):
            logger.info(f"Trying {url} ...")
            pairs = await self._fetch_info(url)
            if pairs:
                self._rest_url = url
                self._ws_url   = config.BINANCE_WS_URLS[min(i, len(config.BINANCE_WS_URLS)-1)]
                self.active_pairs = pairs
                for s in pairs:
                    if s not in self.symbols: self.symbols[s] = SymbolData(s)
                logger.info(f"OK: {url} ({len(pairs)} pairs)")
                return
        logger.error("All endpoints failed. Retrying in background every 60s.")

    async def _fetch_info(self, base: str) -> Set[str]:
        url = f"{base}/fapi/v1/exchangeInfo"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as r:
                if r.status == 451: logger.warning(f"{base}: geo-blocked (451)"); return set()
                if r.status not in (200,202): logger.warning(f"{base}: HTTP {r.status}"); return set()
                try: data = json.loads(await r.text())
                except: return set()
                if not isinstance(data, dict): return set()
                if data.get("code", 0) not in (0, None, ""): return set()
                found = set()
                for sym in data.get("symbols",[]):
                    if (isinstance(sym,dict) and sym.get("status")=="TRADING"
                            and sym.get("contractType")=="PERPETUAL"
                            and sym.get("quoteAsset")=="USDT"):
                        found.add(sym["symbol"])
                return found
        except Exception as e:
            logger.warning(f"{base}: {e}"); return set()

    # ── LOOPS ─────────────────────────────────────────────────────────────

    async def _info_loop(self):
        while self._running:
            await asyncio.sleep(config.EXCHANGE_INFO_TTL_SEC)
            try:
                if not self.active_pairs:
                    await self._find_endpoint()
                    if self.active_pairs: await self._bootstrap_klines()
                    continue
                new = await self._fetch_info(self._rest_url)
                if not new: await self._find_endpoint(); continue
                added = new - self.active_pairs
                self.active_pairs = new
                for s in new:
                    if s not in self.symbols: self.symbols[s] = SymbolData(s)
                if added: logger.info(f"New listings: {added}"); await self._bootstrap_klines(list(added))
                else: logger.info(f"Exchange info refreshed — {len(self.active_pairs)} pairs")
            except Exception as e: logger.error(f"Info loop: {e}")

    async def _bootstrap_klines(self, symbols: Optional[List[str]] = None):
        targets = symbols or list(self.active_pairs)
        if not targets: return
        logger.info(f"Bootstrapping {len(targets)} symbols...")
        sem = asyncio.Semaphore(20)
        async def fetch(sym, iv):
            async with sem:
                try:
                    async with self._session.get(f"{self._rest_url}/fapi/v1/klines",
                        params={"symbol":sym,"interval":iv,"limit":100},
                        timeout=aiohttp.ClientTimeout(total=15)) as r:
                        if r.status not in (200,202): return
                        rows = await r.json(content_type=None)
                        if not isinstance(rows, list): return
                        sd = self.symbols.get(sym)
                        if not sd: return
                        for row in rows:
                            if isinstance(row,list) and len(row)>=6:
                                sd.candles[iv].append(CandleBar(row[0],row[1],row[2],row[3],row[4],row[5],True))
                except Exception as e: logger.debug(f"Kline {sym}/{iv}: {e}")
        await asyncio.gather(*[fetch(s,iv) for s in targets for iv in config.KLINE_INTERVALS])
        logger.info("Kline bootstrap complete")

    async def _ticker_loop(self):
        while self._running:
            if not self.active_pairs: await asyncio.sleep(30); continue
            try:
                async with self._session.get(f"{self._rest_url}/fapi/v1/ticker/24hr",
                        timeout=aiohttp.ClientTimeout(total=30)) as r:
                    if r.status not in (200,202): await asyncio.sleep(60); continue
                    tickers = await r.json(content_type=None)
                    if not isinstance(tickers, list): await asyncio.sleep(60); continue
                    for t in tickers:
                        if not isinstance(t,dict): continue
                        sd = self.symbols.get(t.get("symbol",""))
                        if sd:
                            try:
                                sd.volume_24h       = float(t.get("quoteVolume",0) or 0)
                                sd.price_change_24h = float(t.get("priceChangePercent",0) or 0)
                                sd.last_price       = float(t.get("lastPrice",0) or 0)
                            except: pass
            except Exception as e: logger.error(f"Ticker: {e}")
            await asyncio.sleep(60)

    async def _ws_manager(self):
        while self._running:
            for t in self._ws_tasks: t.cancel()
            self._ws_tasks.clear()
            pairs = list(self.active_pairs)
            if not pairs: await asyncio.sleep(30); continue
            chunk = max(1, config.WS_STREAMS_PER_CONN // 5)
            for c in [pairs[i:i+chunk] for i in range(0, len(pairs), chunk)]:
                self._ws_tasks.append(asyncio.create_task(self._ws_conn(c)))
            logger.info(f"WS: {len(pairs)} pairs, {len(self._ws_tasks)} connections")
            await asyncio.sleep(config.EXCHANGE_INFO_TTL_SEC)

    async def _ws_conn(self, symbols: List[str]):
        streams = []
        for s in symbols:
            sl = s.lower()
            for iv in config.KLINE_INTERVALS: streams.append(f"{sl}@kline_{iv}")
            streams.append(f"{sl}@bookTicker"); streams.append(f"{sl}@aggTrade")
        ws_urls = list(dict.fromkeys([self._ws_url] + config.BINANCE_WS_URLS))
        while True:
            for wb in ws_urls:
                try:
                    async with websockets.connect(
                        f"{wb}?streams=" + "/".join(streams),
                        ping_interval=20, ping_timeout=15, max_size=10_000_000,
                        extra_headers={"User-Agent":"Mozilla/5.0 ApexEDS/4.0"}) as ws:
                        logger.debug(f"WS connected: {len(symbols)} symbols")
                        async for raw in ws:
                            if not self._running: return
                            try: self._dispatch(json.loads(raw))
                            except: pass
                except asyncio.CancelledError: return
                except Exception as e:
                    logger.warning(f"WS {wb}: {e}")
                    await asyncio.sleep(config.WS_RECONNECT_DELAY)

    def _dispatch(self, msg: dict):
        if not isinstance(msg,dict): return
        data=msg.get("data",msg); stream=msg.get("stream","")
        if not isinstance(data,dict): return
        if "@kline_" in stream:    self._on_kline(data)
        elif "@bookTicker" in stream: self._on_book(data)
        elif "@aggTrade" in stream:  self._on_trade(data)

    def _on_kline(self, d: dict):
        k=d.get("k",{})
        if not isinstance(k,dict): return
        sym=k.get("s",""); iv=k.get("i","")
        if sym not in self.symbols or iv not in config.KLINE_INTERVALS: return
        sd=self.symbols[sym]
        try: bar=CandleBar(k["t"],k["o"],k["h"],k["l"],k["c"],k["v"],k["x"])
        except: return
        q=sd.candles[iv]
        if q and not q[-1].closed: q[-1]=bar
        else: q.append(bar)
        sd.updated_at=time.time()

    def _on_book(self, d: dict):
        sd=self.symbols.get(d.get("s",""))
        if sd:
            try: sd.bid=float(d.get("b",0) or 0); sd.ask=float(d.get("a",0) or 0)
            except: pass

    def _on_trade(self, d: dict):
        sd=self.symbols.get(d.get("s",""))
        if not sd: return
        try:
            p=float(d.get("p",0) or 0); q=float(d.get("q",0) or 0)
            maker=bool(d.get("m",False)); usdt=p*q
            if maker: sd.sell_vol+=usdt
            else:     sd.buy_vol+=usdt
            sd.agg_trades.append({"p":p,"q":q,"m":maker})
            sd.last_price=p; sd.updated_at=time.time()
        except: pass
