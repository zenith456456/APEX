"""
BINANCE SCANNER
═══════════════
Connects to Binance Futures WebSocket (!miniTicker@arr).
Scores T3/T4 movers through the 5-layer APEX AI (9-gate filter).
Tracks which symbols are "new" for internal [NEW LISTING] signal tagging.

NO external new-listing alerts are sent to Telegram/Discord.
Genuine new listings generate T3/T4 signals due to their volatility —
the signal itself IS the alert.
"""
import asyncio
import json
import logging
import time
from collections import defaultdict, deque
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
SignalCallback = Callable[[Signal], Awaitable[None]]


class BinanceScanner:

    def __init__(self):
        self.engine  = ApexEngine()
        self.monitor = ExchangeMonitor()

        self.history: dict[str, deque[TickData]] = defaultdict(
            lambda: deque(maxlen=HISTORY_TICKS)
        )
        self._cooldown    : dict[str, float] = {}
        # Symbols that appeared for the first time — used to tag signals [NEW]
        self._new_syms    : set[str]         = set()

        # Signal callbacks (Telegram + Discord)
        self._sig_cbs     : list[SignalCallback] = []

        self.signal_history: deque[Signal] = deque(maxlen=SIGNAL_HISTORY_MAX)
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
            "new_listings_seen" : 0,   # internal counter only
            "ws_reconnects"     : 0,
            "last_signal_ts"    : None,
            "connected_at"      : None,
        }

    # ── Public API ────────────────────────────────────────────

    def add_signal_callback(self, cb: SignalCallback):
        self._sig_cbs.append(cb)

    def add_new_listing_callback(self, cb):
        """
        No-op — external new listing notifications are disabled.
        New listings are caught by T3/T4 signals instead.
        """
        pass

    async def run(self):
        self._running = True
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
                tries = 0
            except Exception as exc:
                tries += 1
                self.stats["ws_reconnects"] += 1
                logger.warning(
                    f"WS error: {exc!r} — "
                    f"reconnect #{self.stats['ws_reconnects']} in {RECONNECT_DELAY_SEC}s"
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

        # ── Parse ticks ───────────────────────────────────────
        for item in data:
            sym = item.get("s", "")
            if not sym.endswith("USDT"):
                continue
            try:
                price  = float(item["c"])
                open24 = float(item["o"])
                high   = float(item["h"])
                low    = float(item.get("l") or price * 0.99)
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

        # ── Update exchange monitor — get internally-new symbols ──
        if frame_syms:
            first_time_syms = self.monitor.update_from_ws(frame_syms)
            if first_time_syms:
                # Tag them internally so signals carry [NEW LISTING] label
                self._new_syms.update(first_time_syms)
                self.stats["new_listings_seen"] += len(first_time_syms)
                # Log only — NO Telegram/Discord alert sent
                for sym in sorted(first_time_syms):
                    logger.debug(f"First-seen symbol (internal): {sym}")

        # ── Update APEX universe stats ────────────────────────
        self.engine.update_universe(valid)

        # ── Score T3/T4 movers ────────────────────────────────
        for tick in valid:
            abs_pct = abs(tick.pct)
            tier    = self.engine.classify_tier(abs_pct)
            if not tier:
                continue

            if tick.pct > 0 and not ENABLE_PUMPS:
                continue
            if tick.pct < 0 and not ENABLE_DUMPS:
                continue

            key = f"{tick.symbol}_{tier}"
            now = time.time()
            if now - self._cooldown.get(key, 0.0) < SIGNAL_COOLDOWN_MIN * 60:
                continue

            if tier == "T3":
                self.stats["t3_raw"] += 1
            else:
                self.stats["t4_raw"] += 1

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

            # ✅ All 9 gates passed
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

            results = await asyncio.gather(
                *[cb(signal) for cb in self._sig_cbs],
                return_exceptions=True,
            )
            for exc in results:
                if isinstance(exc, Exception):
                    logger.warning(f"Signal callback error: {exc!r}")
