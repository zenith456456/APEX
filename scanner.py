"""
Binance Futures WebSocket scanner.
Endpoint: wss://fstream.binance.com  (non-geo-blocked global edge)
Auto-detects new listings every UNIVERSE_REFRESH_SECS via REST exchangeInfo.
"""
import asyncio, json
from collections import defaultdict, deque

import aiohttp, websockets

import config
from logger   import log
from pipeline import IDSPipeline

WS_BATCH_SIZE  = 180
KLINE_INTERVAL = "5m"


class BinanceScanner:
    def __init__(self, on_signal_callback):
        self._callback = on_signal_callback
        self._pipeline = IDSPipeline()
        self._universe: set        = set()
        self._candles:  dict       = defaultdict(lambda: deque(maxlen=config.CANDLE_LIMIT))
        self._ws_tasks: list       = []
        self._session              = None

    async def run(self):
        log.info("BinanceScanner starting…")
        self._session = aiohttp.ClientSession(
            headers={"User-Agent": "IDS-Bot/2.0"},
            timeout=aiohttp.ClientTimeout(total=30),
        )
        try:
            await self._refresh_universe()
            await self._prefetch_candles()
            await asyncio.gather(
                self._universe_refresh_loop(),
                self._stream_loop(),
            )
        finally:
            await self._session.close()
            log.info("Scanner stopped.")

    # ── Universe ──────────────────────────────────────────────────────────────

    async def _refresh_universe(self):
        try:
            async with self._session.get(f"{config.BINANCE_REST_BASE}/fapi/v1/exchangeInfo") as r:
                data = await r.json(content_type=None)
            active = {
                s["symbol"] for s in data.get("symbols",[])
                if s.get("status")=="TRADING"
                and s.get("quoteAsset")=="USDT"
                and s.get("contractType")=="PERPETUAL"
            }
            async with self._session.get(f"{config.BINANCE_REST_BASE}/fapi/v1/ticker/24hr") as r:
                tickers = await r.json(content_type=None)
            new_uni = {
                t["symbol"] for t in tickers
                if t["symbol"] in active
                and float(t.get("quoteVolume",0)) >= config.MIN_VOLUME_USDT
            }
            added = new_uni - self._universe
            if added: log.info(f"NEW LISTINGS: {sorted(added)}")
            self._universe = new_uni
            log.info(f"Universe: {len(self._universe)} symbols")
        except Exception as e:
            log.error(f"Universe refresh error: {e}")

    async def _universe_refresh_loop(self):
        while True:
            await asyncio.sleep(config.UNIVERSE_REFRESH_SECS)
            old = set(self._universe)
            await self._refresh_universe()
            if self._universe != old:
                log.info("Universe changed — restarting WebSocket streams")
                await self._cancel_ws()

    # ── Candle prefetch ───────────────────────────────────────────────────────

    async def _prefetch_candles(self):
        log.info(f"Prefetching candles for {len(self._universe)} symbols…")
        syms = sorted(self._universe)
        for i in range(0, len(syms), 20):
            await asyncio.gather(*[self._fetch_klines(s) for s in syms[i:i+20]], return_exceptions=True)
            await asyncio.sleep(0.4)
        log.info("Prefetch complete ✓")

    async def _fetch_klines(self, symbol):
        try:
            async with self._session.get(
                f"{config.BINANCE_REST_BASE}/fapi/v1/klines",
                params={"symbol": symbol, "interval": KLINE_INTERVAL, "limit": config.CANDLE_LIMIT}
            ) as r:
                rows = await r.json(content_type=None)
            for row in rows:
                self._candles[symbol].append({
                    "t":row[0],"o":float(row[1]),"h":float(row[2]),
                    "l":float(row[3]),"c":float(row[4]),
                    "v":float(row[5]),"qv":float(row[7])
                })
        except Exception as e:
            log.debug(f"Prefetch {symbol}: {e}")

    # ── WebSocket streams ─────────────────────────────────────────────────────

    async def _stream_loop(self):
        while True:
            syms    = sorted(self._universe)
            batches = [syms[i:i+WS_BATCH_SIZE] for i in range(0,len(syms),WS_BATCH_SIZE)]
            self._ws_tasks = [
                asyncio.create_task(self._ws_batch(batch, idx))
                for idx, batch in enumerate(batches)
            ]
            log.info(f"Started {len(self._ws_tasks)} WebSocket connection(s) — {len(syms)} symbols")
            if self._ws_tasks:
                await asyncio.wait(self._ws_tasks, return_when=asyncio.FIRST_COMPLETED)
            await self._cancel_ws()
            await asyncio.sleep(2)

    async def _cancel_ws(self):
        for t in self._ws_tasks: t.cancel()
        if self._ws_tasks:
            await asyncio.gather(*self._ws_tasks, return_exceptions=True)
        self._ws_tasks.clear()

    async def _ws_batch(self, symbols, batch_idx):
        """
        Combined stream endpoint:
        wss://fstream.binance.com/stream?streams=btcusdt@kline_5m/ethusdt@kline_5m/…
        Non-geo-blocked — works from all Northflank regions.
        """
        streams = "/".join(f"{s.lower()}@kline_{KLINE_INTERVAL}" for s in symbols)
        url     = f"{config.BINANCE_WS_BASE}/stream?streams={streams}"

        while True:
            try:
                log.debug(f"WS[{batch_idx}] connecting ({len(symbols)} symbols)…")
                async with websockets.connect(url, ping_interval=20, ping_timeout=15,
                                              close_timeout=5, max_size=2**22) as ws:
                    log.info(f"WS[{batch_idx}] connected ✓")
                    async for raw in ws:
                        await self._on_message(raw)
            except asyncio.CancelledError:
                log.debug(f"WS[{batch_idx}] cancelled")
                return
            except Exception as e:
                log.warning(f"WS[{batch_idx}] error: {e} — reconnect in 5s")
                await asyncio.sleep(5)

    async def _on_message(self, raw):
        try:
            msg  = json.loads(raw)
            data = msg.get("data", msg)
            if data.get("e") != "kline": return
            k = data["k"]
            if not k.get("x"): return          # only closed candles
            sym    = k["s"]
            candle = {"t":k["t"],"o":float(k["o"]),"h":float(k["h"]),
                      "l":float(k["l"]),"c":float(k["c"]),
                      "v":float(k["v"]),"qv":float(k["q"])}
            self._candles[sym].append(candle)
            await self._evaluate(sym)
        except Exception as e:
            log.debug(f"WS parse: {e}")

    async def _evaluate(self, symbol):
        candles = list(self._candles[symbol])
        if len(candles) < 50: return
        try:
            loop   = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._pipeline.evaluate, symbol, candles)
            if result and result.get("fires"):
                await self._callback(result)
        except Exception as e:
            log.error(f"Pipeline {symbol}: {e}")
