# ─── binance_scanner.py ────────────────────────────────────────────────────
# APEX Signal Bot — Binance Futures WebSocket Scanner
# Uses fstream.binance.com (Futures) — NOT geo-blocked
# Auto-detects new listings every LISTING_CHECK_MIN minutes

import asyncio
import json
import logging
import ssl
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set

import aiohttp
import websockets

logger = logging.getLogger("APEX.Scanner")

# ── Non-geo-blocked Binance Futures endpoints ──────────────────────────────
WS_BASE   = "wss://fstream.binance.com/stream"
REST_BASE = "https://fapi.binance.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
    "Origin":     "https://www.binance.com",
}

# ── Kline field indices ────────────────────────────────────────────────────
K_OPEN_TIME   = 0
K_OPEN        = 1
K_HIGH        = 2
K_LOW         = 3
K_CLOSE       = 4
K_VOLUME      = 5
K_CLOSE_TIME  = 6
K_QUOTE_VOL   = 7
K_TRADES      = 8
K_TAKER_BUY_BASE  = 9
K_TAKER_BUY_QUOTE = 10

TIMEFRAMES = ["1m", "3m", "5m", "15m"]


class CandleStore:
    """Holds rolling OHLCV candles + derived CVD/delta per pair per TF."""

    def __init__(self, max_candles: int = 100):
        self.max = max_candles
        # pair → tf → deque of candle dicts
        self.candles: Dict[str, Dict[str, deque]] = defaultdict(
            lambda: {tf: deque(maxlen=max_candles) for tf in TIMEFRAMES}
        )
        # pair → CVD running value (estimated from taker buy ratio)
        self.cvd: Dict[str, float] = defaultdict(float)
        # pair → 24h stats
        self.ticker: Dict[str, dict] = {}

    def update_kline(self, pair: str, tf: str, k: dict):
        """Store a closed candle."""
        store = self.candles[pair][tf]
        if store and store[-1]["t"] == k["t"]:
            store[-1] = k  # update in place
        else:
            store.append(k)

    def update_ticker(self, pair: str, data: dict):
        self.ticker[pair] = data

    def update_cvd(self, pair: str, delta: float):
        self.cvd[pair] += delta

    def get_candles(self, pair: str, tf: str, n: int = 50) -> List[dict]:
        return list(self.candles[pair][tf])[-n:]

    def get_cvd(self, pair: str) -> float:
        return self.cvd[pair]


class BinanceScanner:
    """
    Connects to Binance Futures WebSocket streams for:
      • kline (1m/3m/5m/15m) — OHLCV data
      • aggTrade             — taker buy/sell for CVD estimation
      • !miniTicker@arr      — 24h stats + volume filter
    Auto-polls exchangeInfo to detect new listings.
    """

    def __init__(self, config, on_signal_ready: Callable):
        self.cfg            = config
        self.on_signal_ready = on_signal_ready
        self.store          = CandleStore()
        self.active_pairs:  Set[str] = set()
        self.ws_tasks:      List[asyncio.Task] = []
        self._running       = False
        self._ssl_ctx       = self._build_ssl()
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws_connections = {}          # stream_key → ws
        self._reconnect_delay = 5          # seconds

    # ── SSL context (bypass strict cert check for proxied envs) ────────────
    @staticmethod
    def _build_ssl():
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        return ctx

    # ── REST: fetch all PERPETUAL pairs passing volume filter ──────────────
    async def fetch_active_pairs(self) -> Set[str]:
        url = f"{REST_BASE}/fapi/v1/exchangeInfo"
        try:
            async with self._session.get(url, headers=HEADERS, ssl=self._ssl_ctx) as r:
                data = await r.json()
            usdt_perps = set()
            skipped = []
            for s in data.get("symbols", []):
                sym = s.get("symbol", "")
                if not (
                    s.get("quoteAsset") == "USDT"
                    and s.get("contractType") == "PERPETUAL"
                    and s.get("status") == "TRADING"
                ):
                    continue
                # Binance WS stream names must be plain ASCII (lowercase
                # symbol + suffix). Reject anything else (promo/marketing
                # symbols, CJK characters, etc.) before it ever reaches
                # the WebSocket subscriber — such symbols cause silent
                # stream failures or malformed subscription payloads.
                if not sym.isascii() or not sym.replace("_", "").isalnum():
                    skipped.append(sym)
                    continue
                usdt_perps.add(sym)
            if skipped:
                logger.warning(f"Skipped {len(skipped)} non-standard symbol(s): {skipped}")
            logger.info(f"ExchangeInfo: {len(usdt_perps)} USDT perpetuals found")
            return usdt_perps
        except Exception as e:
            logger.error(f"fetch_active_pairs error: {e}")
            return set()

    # ── REST: fetch 24h volume for filtering ─────────────────────────────
    async def fetch_24h_tickers(self) -> Dict[str, float]:
        url = f"{REST_BASE}/fapi/v1/ticker/24hr"
        try:
            async with self._session.get(url, headers=HEADERS, ssl=self._ssl_ctx) as r:
                data = await r.json()
            return {
                d["symbol"]: float(d.get("quoteVolume", 0))
                for d in data
                if isinstance(d, dict)
            }
        except Exception as e:
            logger.error(f"fetch_24h_tickers error: {e}")
            return {}

    # ── REST: fetch historical klines to pre-fill candle store ────────────
    async def prefill_candles(self, pair: str, tf: str, limit: int = 60):
        url = f"{REST_BASE}/fapi/v1/klines"
        params = {"symbol": pair, "interval": tf, "limit": limit}
        try:
            async with self._session.get(
                url, params=params, headers=HEADERS, ssl=self._ssl_ctx
            ) as r:
                data = await r.json()
            for k in data:
                candle = {
                    "t": k[K_OPEN_TIME], "o": float(k[K_OPEN]),
                    "h": float(k[K_HIGH]),  "l": float(k[K_LOW]),
                    "c": float(k[K_CLOSE]), "v": float(k[K_VOLUME]),
                    "qv": float(k[K_QUOTE_VOL]),
                    "n":  int(k[K_TRADES]),
                    "tbv": float(k[K_TAKER_BUY_BASE]),
                    "tbqv": float(k[K_TAKER_BUY_QUOTE]),
                    "x": True,   # all historical = closed
                }
                self.store.update_kline(pair, tf, candle)
            logger.debug(f"Pre-filled {pair} {tf}: {len(data)} candles")
        except Exception as e:
            logger.warning(f"prefill_candles {pair} {tf}: {e}")

    # ── Determine qualifying pairs ─────────────────────────────────────────
    async def refresh_pairs(self):
        all_pairs = await self.fetch_active_pairs()
        volumes   = await self.fetch_24h_tickers()

        qualified = {
            p for p in all_pairs
            if volumes.get(p, 0) >= self.cfg.MIN_VOLUME_USDT
        }
        qualified = set(sorted(qualified, key=lambda p: volumes.get(p, 0), reverse=True)[: self.cfg.MAX_PAIRS])

        new_pairs = qualified - self.active_pairs
        if new_pairs:
            logger.info(f"New pairs detected: {new_pairs}")
            for pair in new_pairs:
                for tf in TIMEFRAMES:
                    await self.prefill_candles(pair, tf)

        self.active_pairs = qualified
        logger.info(f"Monitoring {len(self.active_pairs)} pairs")

    # ── Build combined stream URL ──────────────────────────────────────────
    def _stream_url(self, streams: List[str]) -> str:
        return f"{WS_BASE}?streams=" + "/".join(streams)

    # ── WebSocket listener ────────────────────────────────────────────────
    async def _listen_stream(self, stream_key: str, streams: List[str]):
        url = self._stream_url(streams)
        while self._running:
            try:
                async with websockets.connect(
                    url,
                    ssl=self._ssl_ctx,
                    ping_interval=20,
                    ping_timeout=10,
                    extra_headers=HEADERS,
                ) as ws:
                    self._ws_connections[stream_key] = ws
                    logger.info(f"WS connected: {stream_key} ({len(streams)} streams)")
                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw)
                            await self._dispatch(msg)
                        except Exception as e:
                            logger.debug(f"dispatch error: {e}")
            except Exception as e:
                logger.warning(f"WS {stream_key} disconnected: {e} — reconnecting in {self._reconnect_delay}s")
                await asyncio.sleep(self._reconnect_delay)

    # ── Dispatch incoming WebSocket message ────────────────────────────────
    async def _dispatch(self, msg: dict):
        stream = msg.get("stream", "")
        data   = msg.get("data", msg)

        # ── 24h mini-ticker array ─────────────────────────────────────────
        if stream == "!miniTicker@arr":
            for t in data:
                sym = t.get("s", "")
                if sym in self.active_pairs:
                    self.store.update_ticker(sym, {
                        "price":  float(t.get("c", 0)),
                        "vol24":  float(t.get("q", 0)),
                        "change": float(t.get("P", 0)),
                    })
            return

        # ── Kline ────────────────────────────────────────────────────────
        if data.get("e") == "kline":
            k   = data["k"]
            sym = k["s"]
            tf  = k["i"]
            if sym not in self.active_pairs or tf not in TIMEFRAMES:
                return
            candle = {
                "t":    k["t"],
                "o":    float(k["o"]),
                "h":    float(k["h"]),
                "l":    float(k["l"]),
                "c":    float(k["c"]),
                "v":    float(k["v"]),
                "qv":   float(k["q"]),
                "n":    int(k["n"]),
                "tbv":  float(k["V"]),   # taker buy base vol
                "tbqv": float(k["Q"]),   # taker buy quote vol
                "x":    k["x"],          # is candle closed?
            }
            self.store.update_kline(sym, tf, candle)

            # Fire signal evaluation on closed candles
            if k["x"]:
                await self.on_signal_ready(sym, tf, self.store)
            return

        # ── AggTrade — estimate CVD ───────────────────────────────────────
        if data.get("e") == "aggTrade":
            sym = data.get("s", "")
            if sym not in self.active_pairs:
                return
            qty   = float(data.get("q", 0))
            price = float(data.get("p", 0))
            maker = data.get("m", False)   # maker = sell side
            delta = qty * price if not maker else -(qty * price)
            self.store.update_cvd(sym, delta)

    # ── Subscription chunking (WS limit ~200 streams per connection) ───────
    async def _subscribe_all(self):
        pairs  = list(self.active_pairs)
        chunk  = 50  # pairs per WS connection
        tasks  = []

        # Kline + aggTrade streams
        for i in range(0, len(pairs), chunk):
            batch = pairs[i: i + chunk]
            streams = []
            for p in batch:
                p_lower = p.lower()
                for tf in TIMEFRAMES:
                    streams.append(f"{p_lower}@kline_{tf}")
                streams.append(f"{p_lower}@aggTrade")
            key = f"batch_{i // chunk}"
            tasks.append(asyncio.create_task(self._listen_stream(key, streams)))

        # Global mini-ticker
        tasks.append(asyncio.create_task(
            self._listen_stream("ticker", ["!miniTicker@arr"])
        ))

        self.ws_tasks = tasks
        return tasks

    # ── Periodic listing refresh ───────────────────────────────────────────
    async def _listing_watcher(self):
        while self._running:
            await asyncio.sleep(self.cfg.LISTING_CHECK_MIN * 60)
            logger.info("Checking for new Binance listings…")
            old = set(self.active_pairs)
            await self.refresh_pairs()
            new = self.active_pairs - old
            if new:
                logger.info(f"New listings auto-detected: {new}")
                # Cancel and rebuild WS connections
                for t in self.ws_tasks:
                    t.cancel()
                await asyncio.gather(*self.ws_tasks, return_exceptions=True)
                self.ws_tasks = []
                await self._subscribe_all()

    # ── Main entry ────────────────────────────────────────────────────────
    async def start(self):
        self._running  = True
        connector      = aiohttp.TCPConnector(ssl=self._ssl_ctx)
        self._session  = aiohttp.ClientSession(connector=connector)

        logger.info("Fetching active pairs and pre-filling candles…")
        await self.refresh_pairs()

        logger.info("Starting WebSocket streams…")
        tasks = await self._subscribe_all()
        tasks.append(asyncio.create_task(self._listing_watcher()))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop(self):
        self._running = False
        for t in self.ws_tasks:
            t.cancel()
        if self._session:
            await self._session.close()
        logger.info("Scanner stopped.")
