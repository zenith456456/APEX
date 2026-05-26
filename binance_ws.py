"""
binance_ws.py ─ Binance WebSocket combined-stream manager

Geo-unblocked URL chain:
  1. wss://stream.binance.com:9443/stream   (default)
  2. wss://stream.binance.com:443/stream    (port 443 — most firewalls allow)
  3. wss://data-stream.binance.com:443/stream (CDN fallback)

Auto-reconnect with exponential back-off: 2s → 4s → 8s … 60s max.
Fires on_candle_close(symbol, interval, candle) for CLOSED candles only.
Fires on_ticker(list) for miniTicker array messages.
"""
import asyncio
import json
from typing import Callable, Awaitable
import websockets
from config import cfg
from logger_setup import get_logger

log = get_logger("ws")

CandleCB = Callable[[str, str, dict], Awaitable[None]]
TickerCB = Callable[[list],           Awaitable[None]]


class BinanceWS:
    def __init__(self):
        self.on_candle_close: CandleCB | None = None
        self.on_ticker:       TickerCB | None = None
        self._pairs:   list[str] = []
        self._tfs:     list[str] = []
        self._running: bool      = False
        self._url_idx: int       = 0
        self._backoff: float     = 2.0

    def set_pairs(self, pairs: list[str], tfs: list[str]):
        self._pairs = [p.lower() for p in pairs]
        self._tfs   = tfs

    async def run(self, pairs: list[str], tfs: list[str]):
        self._running = True
        self.set_pairs(pairs, tfs)
        while self._running:
            try:
                await self._connect()
                self._backoff = 2.0
            except Exception as exc:
                log.warning(f"WS error: {type(exc).__name__}: {exc} "
                            f"— retry in {self._backoff:.0f}s (url_idx={self._url_idx})")
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2.0, 60.0)
                self._url_idx += 1

    def stop(self):
        self._running = False

    def _url(self) -> str:
        base    = cfg.BINANCE_WS_URLS[self._url_idx % len(cfg.BINANCE_WS_URLS)]
        streams = [f"{p}@kline_{tf}" for p in self._pairs for tf in self._tfs]
        streams.append("!miniTicker@arr")
        return f"{base}?streams={'/'.join(streams)}"

    async def _connect(self):
        url = self._url()
        log.info(f"WS → {url[:100]}…")
        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
            max_size=2 ** 22,
            open_timeout=20,
        ) as ws:
            log.info("WS connected ✓  (listening for closed candles)")
            self._backoff = 2.0
            async for raw in ws:
                if not self._running:
                    break
                try:
                    await self._dispatch(json.loads(raw))
                except Exception as exc:
                    log.error(f"Dispatch error: {exc}")

    async def _dispatch(self, msg: dict):
        stream = msg.get("stream", "")
        data   = msg.get("data", msg)

        # miniTicker array
        if isinstance(data, list) or "miniTicker" in stream:
            if self.on_ticker:
                await self.on_ticker(data if isinstance(data, list) else [])
            return

        # kline — fire ONLY on closed candle (x=True)
        if "@kline_" in stream:
            k = data.get("k", {})
            if not k.get("x", False):
                return
            candle = {
                "open_time":  k["t"],
                "open":       float(k["o"]),
                "high":       float(k["h"]),
                "low":        float(k["l"]),
                "close":      float(k["c"]),
                "volume":     float(k["v"]),
                "close_time": k["T"],
                "quote_vol":  float(k["q"]),
                "trades":     k["n"],
            }
            if self.on_candle_close:
                await self.on_candle_close(k["s"], k["i"], candle)
