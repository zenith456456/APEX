"""
BINANCE SCANNER  v4  —  Smart Signal State Management
═══════════════════════════════════════════════════════
Signal firing rules per coin:

  RULE 1 — Same direction cooldown (60 min):
    After a LONG signal fires, the same coin cannot fire LONG again
    for 60 minutes. Prevents repeated signals on the same trend.

  RULE 2 — TP1 hit re-entry:
    If the current price reaches or exceeds the previous signal's TP1
    level, a new signal is allowed immediately (with updated targets).
    This lets traders ride the continuation.

  RULE 3 — Direction reversal:
    If the coin was signalled LONG but is now qualifying as DUMP
    (or vice versa), a new signal fires after a short cooldown (5 min).
    Catches trend reversals.

  RULE 4 — Different tier:
    T3 and T4 signals for the same coin are tracked independently.
    A T3 signal does not block a T4 signal.
"""
import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Awaitable, Optional

import websockets

from apex_engine import ApexEngine, TickData, Signal, fmt_vol
from exchange_monitor import ExchangeMonitor
from config import (
    BINANCE_WS_URL, VOLUME_MIN_USD, HISTORY_TICKS,
    SIGNAL_HISTORY_MAX, ENABLE_PUMPS, ENABLE_DUMPS,
    RECONNECT_DELAY_SEC, MAX_RECONNECT_TRIES,
)

logger = logging.getLogger("apex.scanner")
SignalCallback = Callable[[Signal], Awaitable[None]]

# ── Cooldown constants ────────────────────────────────────────
# Minimum gap before same coin+tier+direction can fire again
SAME_DIR_COOLDOWN_SEC     = 60 * 60   # 60 minutes — same direction
REVERSAL_COOLDOWN_SEC     = 5  * 60   #  5 minutes — direction reversal
TP1_REENTRY_COOLDOWN_SEC  = 5  * 60   #  5 minutes — after TP1 hit

# ── Signal state per coin+tier ────────────────────────────────
@dataclass
class SignalState:
    direction  : str    # PUMP | DUMP
    tp1        : float  # TP1 price from last signal
    tp2        : float  # TP2 price (for display in re-entry reason)
    entry_ref  : float  # entry reference price
    fire_time  : float  # epoch when signal fired
    tp1_hit    : bool   # True once price crossed TP1
    reason     : str    # "initial" | "tp1_reentry" | "reversal"


class BinanceScanner:

    def __init__(self):
        self.engine  = ApexEngine()
        self.monitor = ExchangeMonitor()

        self.history: dict[str, deque[TickData]] = defaultdict(
            lambda: deque(maxlen=HISTORY_TICKS)
        )

        # Smart signal state: key = "SYMBOL_TIER" (e.g. "BTCUSDT_T3")
        self._sig_state : dict[str, SignalState] = {}

        # Symbols seen for first time — internal [NEW] tag only
        self._new_syms  : set[str] = set()

        # Signal delivery callbacks
        self._sig_cbs   : list[SignalCallback] = []

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
            "tp1_reentries"     : 0,
            "reversals"         : 0,
            "new_listings_seen" : 0,
            "ws_reconnects"     : 0,
            "last_signal_ts"    : None,
            "connected_at"      : None,
        }

    # ── Public API ────────────────────────────────────────────

    def add_signal_callback(self, cb: SignalCallback):
        self._sig_cbs.append(cb)

    def add_new_listing_callback(self, cb):
        pass   # disabled — see exchange_monitor.py

    async def run(self):
        self._running = True
        await asyncio.gather(
            self.monitor.run(),
            self._ws_loop(),
        )

    def stop(self):
        self._running = False
        self.monitor.stop()

    # ── Smart cooldown check ──────────────────────────────────

    def _should_fire(
        self,
        sym      : str,
        tier     : str,
        direction: str,
        price    : float,
        trade_tp1: float,   # proposed TP1 from TradeCalculator
    ) -> tuple[bool, str]:
        """
        Returns (should_fire, reason).
        reason: "initial" | "tp1_reentry" | "reversal" | "blocked"
        """
        key   = f"{sym}_{tier}"
        now   = time.time()
        state = self._sig_state.get(key)

        # ── No previous signal for this coin+tier ─────────────
        if state is None:
            return True, "initial"

        elapsed = now - state.fire_time

        # ── Update TP1 hit status ─────────────────────────────
        if not state.tp1_hit:
            if state.direction == "PUMP" and price >= state.tp1:
                state.tp1_hit = True
                logger.info(
                    f"TP1 HIT  {sym} {tier}  "
                    f"price={price:.6g}  tp1={state.tp1:.6g}  "
                    f"→ re-entry unlocked"
                )
            elif state.direction == "DUMP" and price <= state.tp1:
                state.tp1_hit = True
                logger.info(
                    f"TP1 HIT  {sym} {tier}  "
                    f"price={price:.6g}  tp1={state.tp1:.6g}  "
                    f"→ re-entry unlocked"
                )

        # ── Rule 2: TP1 hit re-entry ──────────────────────────
        if state.tp1_hit and elapsed >= TP1_REENTRY_COOLDOWN_SEC:
            return True, "tp1_reentry"

        # ── Rule 3: Direction reversal ────────────────────────
        if direction != state.direction and elapsed >= REVERSAL_COOLDOWN_SEC:
            return True, "reversal"

        # ── Rule 1: Same direction long cooldown ──────────────
        if direction == state.direction and elapsed >= SAME_DIR_COOLDOWN_SEC:
            return True, "initial"

        return False, "blocked"

    def _record_state(
        self,
        sym      : str,
        tier     : str,
        direction: str,
        tp1      : float,
        tp2      : float,
        entry_ref: float,
        reason   : str,
    ):
        key = f"{sym}_{tier}"
        self._sig_state[key] = SignalState(
            direction  = direction,
            tp1        = tp1,
            tp2        = tp2,
            entry_ref  = entry_ref,
            fire_time  = time.time(),
            tp1_hit    = False,
            reason     = reason,
        )

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
        valid      : list[TickData] = []
        frame_syms : set[str]       = set()

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

        # ── Exchange monitor (new listing tracking) ────────────
        if frame_syms:
            first_time = self.monitor.update_from_ws(frame_syms)
            if first_time:
                self._new_syms.update(first_time)
                self.stats["new_listings_seen"] += len(first_time)

        # ── APEX universe stats ───────────────────────────────
        self.engine.update_universe(valid)

        # ── Score T3/T4 movers ────────────────────────────────
        for tick in valid:
            abs_pct   = abs(tick.pct)
            tier      = self.engine.classify_tier(abs_pct)
            if not tier:
                continue

            direction = "PUMP" if tick.pct > 0 else "DUMP"

            if direction == "PUMP" and not ENABLE_PUMPS:
                continue
            if direction == "DUMP" and not ENABLE_DUMPS:
                continue

            # Raw counter
            if tier == "T3":
                self.stats["t3_raw"] += 1
            else:
                self.stats["t4_raw"] += 1

            # Score through APEX AI
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
                        f"APEX={layers.APEX}  gates={layers.gates_passed}  "
                        f"fail={layers.failed_gate}  pct={tick.pct:+.2f}%"
                    )
                continue

            # ── Calculate trade params first (need TP1 for cooldown check)
            is_new = tick.symbol in self._new_syms
            signal = self.engine.build_signal(tick, layers, is_new_listing=is_new, signal_reason=reason)
            tr     = signal.trade
            tp1    = tr.tp1
            entry  = (tr.entry_low + tr.entry_high) / 2

            # ── Smart cooldown check ──────────────────────────
            should_fire, reason = self._should_fire(
                tick.symbol, tier, direction, tick.price, tp1
            )

            if not should_fire:
                continue

            # ✅ Fire the signal
            self._record_state(
                tick.symbol, tier, direction,
                tp1, tr.tp2, entry, reason
            )

            self.stats["last_signal_ts"] = time.time()

            if tier == "T3":
                self.stats["t3_fired"] += 1
            else:
                self.stats["t4_fired"] += 1

            if reason == "tp1_reentry":
                self.stats["tp1_reentries"] += 1
            elif reason == "reversal":
                self.stats["reversals"] += 1

            self.signal_history.appendleft(signal)

            # Build log tag
            new_tag     = "[NEW] "     if is_new           else ""
            reason_tag  = "[TP1 RE-ENTRY] " if reason == "tp1_reentry" \
                     else "[REVERSAL] "      if reason == "reversal"    \
                     else ""

            logger.info(
                f"{new_tag}{reason_tag}"
                f"SIGNAL {signal.coin():10s} {tier} {direction}  "
                f"{tick.pct:+.2f}%  APEX={layers.APEX}  "
                f"Vol={fmt_vol(tick.vol_usd)}  "
                f"-> {tr.style.upper()} {tr.position}  "
                f"x{tr.leverage}  R:R 1:{tr.rr:.1f}"
            )

            results = await asyncio.gather(
                *[cb(signal) for cb in self._sig_cbs],
                return_exceptions=True,
            )
            for exc in results:
                if isinstance(exc, Exception):
                    logger.warning(f"Signal callback error: {exc!r}")
