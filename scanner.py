"""
scanner.py — Live Binance Futures WebSocket scanner.

Flow:
  1. REST /fapi/v1/exchangeInfo  → full universe of active USDT-M perps
     Repeated every UNIVERSE_REFRESH_SECS to auto-detect new listings.
  2. REST /fapi/v1/ticker/24hr   → filter by 24h volume >= MIN_VOLUME_USDT
  3. REST /fapi/v1/klines        → prefetch CANDLE_LIMIT history per symbol
  4. WS   fstream.binance.com/stream?streams=sym@kline_5m&...
     On each closed kline → run IDSPipeline → call on_signal_callback

WebSocket endpoint: fstream.binance.com
  Non-geo-blocked global edge — works from all Northflank regions (EU/US/APAC).
  Supports combined streams (up to 1024 streams per connection).
"""
import asyncio
import json
from collections import defaultdict, deque

import aiohttp
import websockets

from src.config import (
    BINANCE_WS_BASE,
    BINANCE_REST_BASE,
    MIN_VOLUME_USDT,
    CANDLE_LIMIT,
    UNIVERSE_REFRESH_SECS,
)
from src.logger  import log
from src.pipeline import IDSPipeline

# Max symbols per single WebSocket connection
WS_BATCH_SIZE  = 180
KLINE_INTERVAL = "5m"


class BinanceScanner:
    def __init__(self, on_signal_callback):
        """
        on_signal_callback: async callable(signal: dict)
          Fired whenever IDS produces a valid signal dict.
        """
        self._callback = on_signal_callback
        self._pipeline = IDSPipeline()
        self._universe: set[str]                  = set()
        self._candles:  dict[str, deque]          = defaultdict(lambda: deque(maxlen=CANDLE_LIMIT))
        self._ws_tasks: list[asyncio.Task]        = []
        self._session:  aiohttp.ClientSession | None = None

    # ── Entry point ────────────────────────────────────────────────────────────

    async def run(self):
        log.info("BinanceScanner starting…")
        self._session = aiohttp.ClientSession(
            headers={"User-Agent": "IDS-Bot/2.0"},
            timeout=aiohttp.ClientTimeout(total=30),
        )
        try:
            await self._refresh_universe()
            await self._prefetch_candles()
            # Run universe refresh loop + WebSocket streams concurrently
            await asyncio.gather(
                self._universe_refresh_loop(),
                self._stream_loop(),
            )
        finally:
            await self._session.close()
            log.info("BinanceScanner stopped.")

    # ── Universe management ────────────────────────────────────────────────────

    async def _refresh_universe(self):
        """Fetch all active USDT-M perp symbols, filter by 24h volume."""
        try:
            # Step 1 — all perpetual symbols
            async with self._session.get(
                f"{BINANCE_REST_BASE}/fapi/v1/exchangeInfo"
            ) as r:
                data = await r.json(content_type=None)
            active = {
                s["symbol"]
                for s in data.get("symbols", [])
                if s.get("status")       == "TRADING"
                and s.get("quoteAsset")  == "USDT"
                and s.get("contractType")== "PERPETUAL"
            }

            # Step 2 — volume filter
            async with self._session.get(
                f"{BINANCE_REST_BASE}/fapi/v1/ticker/24hr"
            ) as r:
                tickers = await r.json(content_type=None)
            vol_ok = {
                t["symbol"]
                for t in tickers
                if t["symbol"] in active
                and float(t.get("quoteVolume", 0)) >= MIN_VOLUME_USDT
            }

            new_coins = vol_ok - self._universe
            if new_coins:
                log.info(f"🆕 NEW LISTINGS DETECTED: {sorted(new_coins)}")

            removed = self._universe - vol_ok
            if removed:
                log.info(f"🗑 Symbols removed (low vol): {sorted(removed)}")

            self._universe = vol_ok
            log.info(f"Universe refreshed — {len(self._universe)} symbols active")

        except Exception as e:
            log.error(f"Universe refresh error: {e}")

    async def _universe_refresh_loop(self):
        """Periodically refresh universe to pick up new listings."""
        while True:
            await asyncio.sleep(UNIVERSE_REFRESH_SECS)
            old = set(self._universe)
            await self._refresh_universe()
            if self._universe != old:
                log.info("Universe changed — restarting WebSocket streams")
                await self._cancel_ws_tasks()

    # ── Historical candle prefetch ─────────────────────────────────────────────

    async def _prefetch_candles(self):
        log.info(f"Prefetching {CANDLE_LIMIT} candles for {len(self._universe)} symbols…")
        syms = sorted(self._universe)
        # 20 concurrent REST requests at a time
        for i in range(0, len(syms), 20):
            batch = syms[i:i + 20]
            await asyncio.gather(
                *[self._fetch_rest_klines(s) for s in batch],
                return_exceptions=True,
            )
            await asyncio.sleep(0.4)
        log.info("Candle prefetch complete ✓")

    async def _fetch_rest_klines(self, symbol: str):
        try:
            async with self._session.get(
                f"{BINANCE_REST_BASE}/fapi/v1/klines",
                params={
                    "symbol":   symbol,
                    "interval": KLINE_INTERVAL,
                    "limit":    CANDLE_LIMIT,
                },
            ) as r:
                rows = await r.json(content_type=None)
            for row in rows:
                self._candles[symbol].append(_parse_kline(row))
        except Exception as e:
            log.debug(f"Prefetch {symbol}: {e}")

    # ── WebSocket stream management ────────────────────────────────────────────

    async def _stream_loop(self):
        """Start (and restart when universe changes) WebSocket batches."""
        while True:
            syms    = sorted(self._universe)
            batches = [
                syms[i:i + WS_BATCH_SIZE]
                for i in range(0, len(syms), WS_BATCH_SIZE)
            ]
            self._ws_tasks = [
                asyncio.create_task(self._ws_batch(batch, idx))
                for idx, batch in enumerate(batches)
            ]
            log.info(f"Started {len(self._ws_tasks)} WebSocket connection(s) "
                     f"covering {len(syms)} symbols")
            # Wait until at least one task finishes (= universe changed or error)
            done, _ = await asyncio.wait(
                self._ws_tasks, return_when=asyncio.FIRST_COMPLETED
            )
            await self._cancel_ws_tasks()
            await asyncio.sleep(2)   # brief pause before reconnect

    async def _cancel_ws_tasks(self):
        for t in self._ws_tasks:
            t.cancel()
        if self._ws_tasks:
            await asyncio.gather(*self._ws_tasks, return_exceptions=True)
        self._ws_tasks.clear()

    async def _ws_batch(self, symbols: list[str], batch_idx: int):
        """
        Single WebSocket connection for a batch of symbols.
        URL: wss://fstream.binance.com/stream?streams=btcusdt@kline_5m/ethusdt@kline_5m/…
        This is the combined-stream endpoint — one connection, many symbols.
        """
        streams = "/".join(f"{s.lower()}@kline_{KLINE_INTERVAL}" for s in symbols)
        url     = f"{BINANCE_WS_BASE}/stream?streams={streams}"

        while True:
            try:
                log.debug(f"WS[{batch_idx}] connecting ({len(symbols)} symbols)…")
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=15,
                    close_timeout=5,
                    max_size=2 ** 22,   # 4 MB frame limit
                ) as ws:
                    log.info(f"WS[{batch_idx}] connected ✓  ({len(symbols)} symbols)")
                    async for raw in ws:
                        await self._on_ws_message(raw)

            except asyncio.CancelledError:
                log.debug(f"WS[{batch_idx}] cancelled")
                return
            except Exception as e:
                log.warning(f"WS[{batch_idx}] dropped: {e}  — reconnect in 5s")
                await asyncio.sleep(5)

    # ── Message handler ────────────────────────────────────────────────────────

    async def _on_ws_message(self, raw: str):
        try:
            msg    = json.loads(raw)
            data   = msg.get("data", msg)

            if data.get("e") != "kline":
                return

            k = data["k"]
            if not k.get("x"):          # x=True means this candle is CLOSED
                return

            symbol = k["s"]
            candle = {
                "t":  k["t"],           # open time ms
                "o":  float(k["o"]),
                "h":  float(k["h"]),
                "l":  float(k["l"]),
                "c":  float(k["c"]),
                "v":  float(k["v"]),    # base asset volume
                "qv": float(k["q"]),    # quote volume (USDT)
            }
            self._candles[symbol].append(candle)
            await self._evaluate(symbol)

        except Exception as e:
            log.debug(f"WS message parse error: {e}")

    # ── Pipeline evaluation ────────────────────────────────────────────────────

    async def _evaluate(self, symbol: str):
        candles = list(self._candles[symbol])
        if len(candles) < 50:
            return
        try:
            loop   = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._pipeline.evaluate, symbol, candles
            )
            if result and result.get("fires"):
                await self._callback(result)
        except Exception as e:
            log.error(f"Pipeline error for {symbol}: {e}")


# ── Helper ─────────────────────────────────────────────────────────────────────

def _parse_kline(row: list) -> dict:
    return {
        "t":  row[0],
        "o":  float(row[1]),
        "h":  float(row[2]),
        "l":  float(row[3]),
        "c":  float(row[4]),
        "v":  float(row[5]),
        "qv": float(row[7]),
    }
