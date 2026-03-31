"""
BINANCE SCANNER
═══════════════
Connects to Binance Futures WebSocket (!miniTicker@arr).
Scores T3/T4 movers through the 5-layer APEX AI (9-gate filter).
Feeds every frame's symbol set to ExchangeMonitor for new-listing detection.
No REST API calls — 100% WebSocket driven.
"""
import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Callable, Awaitable

import websockets

from apex_engine import ApexEngine, TickData, Signal, fmt_vol
from exchange_monitor import ExchangeMonitor
from config import (
    BINANCE_WS_URL, VOLUME_MIN_USD, HISTORY_TICKS,
    SIGNAL_COOLDOWN_MIN, SIGNAL_HISTORY_MAX,
    ENABLE_PUMPS, ENABLE_DUMPS,
    RECONNECT_DELAY_SEC, MAX_RECONNECT_TRIES,
)

logger = logging.getLogger("apex.scanner")
SignalCallback     = Callable[[Signal], Awaitable[None]]
NewListingCallback = Callable[[str],   Awaitable[None]]


class BinanceScanner:

    def __init__(self):
        self.engine  = ApexEngine()
        self.monitor = ExchangeMonitor()

        self.history: dict[str, deque[TickData]] = defaultdict(
            lambda: deque(maxlen=HISTORY_TICKS)
        )
        self._cooldown    : dict[str, float] = {}
        self._new_syms    : set[str]         = set()
        self._sig_cbs     : list[SignalCallback]     = []
        self._list_cbs    : list[NewListingCallback] = []
        self.signal_history: deque[Signal]   = deque(maxlen=SIGNAL_HISTORY_MAX)
        self._running = False

        self.stats: dict = {
            "pairs_live"        : 0,
            "frames_total"      : 0,
            "t3_raw"            : 0,
            "t4_raw"            : 0,
            "t3_fired"          : 0,
            "t4_fired"          : 0,
            "t3_rejected"       : 0,
            "t4_rejected"       : 0,
            "new_listings_seen" : 0,
            "ws_reconnects"     : 0,
            "last_signal_ts"    : None,
            "connected_at"      : None,
        }

    # ── Public API ────────────────────────────────────────────

    def add_signal_callback(self, cb: SignalCallback):
        self._sig_cbs.append(cb)

    def add_new_listing_callback(self, cb: NewListingCallback):
        self._list_cbs.append(cb)

    async def run(self):
        self._running = True
        # Wire up new-listing alerts from ExchangeMonitor → bots
        self.monitor.add_new_listing_callback(self._on_new_listing)
        # Run monitor loop + WS loop concurrently
        await asyncio.gather(
            self.monitor.run(),
            self._ws_loop(),
        )

    def stop(self):
        self._running = False
        self.monitor.stop()

    # ── WebSocket reconnect loop ──────────────────────────────

    async def _ws_loop(self):
        tries = 0
        while self._running and tries < MAX_RECONNECT_TRIES:
            try:
                logger.info(f"WS connecting (attempt {tries + 1})...")
                await self._stream()
                tries = 0   # reset on clean disconnect
            except Exception as exc:
                tries += 1
                self.stats["ws_reconnects"] += 1
                logger.warning(
                    f"WS error: {exc!r}  "
                    f"— reconnect #{self.stats['ws_reconnects']} "
                    f"in {RECONNECT_DELAY_SEC}s"
                )
                await asyncio.sleep(RECONNECT_DELAY_SEC)

    async def _stream(self):
        async with websockets.connect(
            BINANCE_WS_URL,
            ping_interval = 20,
            ping_timeout  = 30,
            close_timeout = 10,
            max_size      = 10 * 1024 * 1024,
        ) as ws:
            self.stats["connected_at"] = time.time()
            logger.info("WebSocket connected — Binance Futures !miniTicker@arr")
            async for raw in ws:
                if not self._running:
                    break
                try:
                    await self._process_frame(json.loads(raw))
                except json.JSONDecodeError:
                    pass
                except Exception as exc:
                    logger.debug(f"Frame error: {exc!r}")

    # ── Frame processing ──────────────────────────────────────

    async def _process_frame(self, data):
        if not isinstance(data, list):
            return

        self.stats["frames_total"] += 1
        valid: list[TickData] = []
        frame_syms: set[str] = set()

        # ── Pass 1: parse ticks ───────────────────────────────
        for item in data:
            sym = item.get("s", "")
            if not sym.endswith("USDT"):
                continue
            try:
                price  = float(item["c"])
                open24 = float(item["o"])
                high   = float(item["h"])
                low    = float(item.get("l") or price * 0.99)
                # "q" = 24H quote volume (USD) on Futures stream
                vol    = float(item.get("q", 0) or item.get("v", 0))
            except (KeyError, ValueError, TypeError):
                continue

            if price <= 0 or vol < VOLUME_MIN_USD:
                continue

            pct  = (price - open24) / open24 * 100 if open24 > 0 else 0.0
            tick = TickData(sym, price, open24, high, low, vol, pct, time.time())
            valid.append(tick)
            frame_syms.add(sym)
            self.history[sym].append(tick)

        self.stats["pairs_live"] = len(valid)

        # ── Feed symbol set to ExchangeMonitor ────────────────
        # This is how new listings are detected — no REST needed
        if frame_syms:
            self.monitor.update_from_ws(frame_syms)

        # ── Update APEX universe stats ────────────────────────
        self.engine.update_universe(valid)

        # ── Pass 2: score T3/T4 movers ────────────────────────
        for tick in valid:
            abs_pct = abs(tick.pct)
            tier    = self.engine.classify_tier(abs_pct)
            if not tier:
                continue

            if tick.pct > 0 and not ENABLE_PUMPS:
                continue
            if tick.pct < 0 and not ENABLE_DUMPS:
                continue

            # Cooldown check
            key = f"{tick.symbol}_{tier}"
            now = time.time()
            if now - self._cooldown.get(key, 0.0) < SIGNAL_COOLDOWN_MIN * 60:
                continue

            # Raw counter
            if tier == "T3":
                self.stats["t3_raw"] += 1
            else:
                self.stats["t4_raw"] += 1

            # Score through 5-layer APEX AI
            hist   = list(self.history[tick.symbol])[:-1]
            layers = self.engine.score(tick, hist)

            if layers is None or not layers.all_gates:
                if tier == "T3":
                    self.stats["t3_rejected"] += 1
                else:
                    self.stats["t4_rejected"] += 1
                if layers:
                    logger.debug(
                        f"REJECT {tick.symbol:12s} {tier}  "
                        f"APEX={layers.APEX}  gates={layers.gates_passed}/9  "
                        f"pct={tick.pct:+.2f}%"
                    )
                continue

            # ✅ All 9 gates passed — fire signal
            self._cooldown[key]          = now
            self.stats["last_signal_ts"] = now

            if tier == "T3":
                self.stats["t3_fired"] += 1
            else:
                self.stats["t4_fired"] += 1

            is_new = tick.symbol in self._new_syms
            signal = self.engine.build_signal(tick, layers, is_new_listing=is_new)
            self.signal_history.appendleft(signal)

            new_tag = "[NEW LISTING] " if is_new else ""
            logger.info(
                f"{new_tag}SIGNAL {signal.coin():10s} {tier} {signal.direction}  "
                f"{tick.pct:+.2f}%  APEX={layers.APEX}  "
                f"Vol={fmt_vol(tick.vol_usd)}  "
                f"-> {signal.trade.style.upper()} {signal.trade.position}  "
                f"x{signal.trade.leverage}  R:R 1:{signal.trade.rr:.1f}"
            )

            # Deliver to Telegram + Discord
            results = await asyncio.gather(
                *[cb(signal) for cb in self._sig_cbs],
                return_exceptions=True,
            )
            for exc in results:
                if isinstance(exc, Exception):
                    logger.warning(f"Signal callback error: {exc!r}")

    # ── New listing handler ───────────────────────────────────

    async def _on_new_listing(self, symbol: str):
        """
        Called by ExchangeMonitor ONLY after warmup is complete.
        Double-guard: if called during warmup, silently ignore.
        """
        if not self.monitor.warmup_done:
            return

        self._new_syms.add(symbol)
        self.stats["new_listings_seen"] += 1
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        logger.info(f"New listing alert: {symbol}  ({ts})")

        results = await asyncio.gather(
            *[cb(symbol) for cb in self._list_cbs],
            return_exceptions=True,
        )
        for exc in results:
            if isinstance(exc, Exception):
                logger.warning(f"New listing notify error: {exc!r}")
