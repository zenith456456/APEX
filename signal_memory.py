# ============================================================
#  APEX-EDS v4.0  |  signal_memory.py
#
#  Smart Signal Memory — NO countdown timers
#  State machine logic per coin:
#
#  NEW SIGNAL arrives for coin X
#   └─ Never sent before?          → SEND ✓
#   └─ Direction changed?          → SEND ✓ (reversal)
#   └─ Same direction as before?
#       └─ All TPs achieved?       → SEND ✓ (cycle complete)
#       └─ SL was hit?             → SEND ✓ (re-entry)
#       └─ Still active?           → BLOCK ✗ (duplicate)
# ============================================================

import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

from apex_engine import Direction, SignalResult

logger = logging.getLogger("SignalMemory")


# ── STATE ENUM ────────────────────────────────────────────────
class TradeState(Enum):
    ACTIVE        = auto()   # signal sent, no TP/SL touched yet
    TP1_HIT       = auto()   # price reached TP1
    TP2_HIT       = auto()   # price reached TP2
    ALL_TP_HIT    = auto()   # all targets achieved → allow re-signal
    SL_HIT        = auto()   # stop loss triggered → allow re-signal
    CLOSED        = auto()   # manually marked closed (direction flip)


# ── REMEMBERED SIGNAL ─────────────────────────────────────────
@dataclass
class RememberedSignal:
    symbol:      str
    direction:   Direction
    entry:       float
    stop_loss:   float
    tp1:         float
    tp2:         float
    tp3:         float
    sent_at:     float = field(default_factory=time.time)

    # Mutable state
    state:       TradeState = TradeState.ACTIVE
    tp1_reached: bool = False
    tp2_reached: bool = False
    tp3_reached: bool = False
    sl_reached:  bool = False
    last_checked_price: float = 0.0
    state_changed_at:   float = field(default_factory=time.time)

    # Reason log for debugging
    history: List[str] = field(default_factory=list)

    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S", time.gmtime())
        entry = f"[{ts}] {msg}"
        self.history.append(entry)
        logger.debug(f"  Memory [{self.symbol}]: {msg}")

    @property
    def all_tp_hit(self) -> bool:
        return self.tp1_reached and self.tp2_reached and self.tp3_reached

    @property
    def age_minutes(self) -> float:
        return (time.time() - self.sent_at) / 60

    def to_summary(self) -> str:
        tps = (
            f"TP1{'✓' if self.tp1_reached else '○'} "
            f"TP2{'✓' if self.tp2_reached else '○'} "
            f"TP3{'✓' if self.tp3_reached else '○'}"
        )
        return (
            f"{self.symbol} | {self.direction.value} | {self.state.name} | "
            f"{tps} | SL{'✓' if self.sl_reached else '○'} | "
            f"Age: {self.age_minutes:.1f}m"
        )


# ── DECISION RESULT ───────────────────────────────────────────
@dataclass
class Decision:
    allow:   bool
    reason:  str          # human-readable explanation
    prev:    Optional[RememberedSignal] = None


# ── SIGNAL MEMORY ─────────────────────────────────────────────
class SignalMemory:
    """
    Stateful memory of the last signal per trading pair.
    Call  update_price()  on every WebSocket price tick
    to keep TP/SL state current without a timer.
    Call  check()         before sending any new signal.
    Call  record()        after a signal is sent.
    """

    def __init__(self):
        # symbol → RememberedSignal
        self._memory: Dict[str, RememberedSignal] = {}

    # ── PUBLIC API ────────────────────────────────────────────

    def check(self, new_sig: SignalResult) -> Decision:
        """
        Decide whether a new signal should be sent.
        Returns Decision(allow=True/False, reason=...).
        """
        sym  = new_sig.symbol
        prev = self._memory.get(sym)

        # ── 1. Never signalled before ─────────────────────
        if prev is None:
            return Decision(allow=True, reason="First signal for this pair")

        # ── 2. Direction changed → always allow ───────────
        if prev.direction != new_sig.direction:
            reason = (
                f"Direction CHANGED {prev.direction.value} → {new_sig.direction.value} "
                f"(prev state: {prev.state.name})"
            )
            prev.log(f"Overridden by direction flip: {reason}")
            return Decision(allow=True, reason=reason, prev=prev)

        # ── 3. Same direction — check state ───────────────
        if prev.state == TradeState.ALL_TP_HIT:
            return Decision(
                allow=True,
                reason="All TP targets achieved — fresh entry allowed",
                prev=prev
            )

        if prev.state == TradeState.SL_HIT:
            return Decision(
                allow=True,
                reason="Stop loss was hit — re-entry signal allowed",
                prev=prev
            )

        if prev.state == TradeState.CLOSED:
            return Decision(
                allow=True,
                reason="Previous trade closed — new signal allowed",
                prev=prev
            )

        # ── 4. Still active — block duplicate ─────────────
        tps = (
            f"TP1{'✓' if prev.tp1_reached else '○'} "
            f"TP2{'✓' if prev.tp2_reached else '○'} "
            f"TP3{'✓' if prev.tp3_reached else '○'}"
        )
        reason = (
            f"BLOCKED — {sym} {prev.direction.value} still active | "
            f"{tps} | SL{'✓' if prev.sl_reached else '○'} | "
            f"Age {prev.age_minutes:.1f}m | State: {prev.state.name}"
        )
        return Decision(allow=False, reason=reason, prev=prev)

    def record(self, sig: SignalResult, prev: Optional[RememberedSignal] = None):
        """Store a signal that has just been sent."""
        if prev is not None:
            # Mark previous as closed (replaced)
            prev.state = TradeState.CLOSED
            prev.log("Closed — new signal sent for same pair")

        mem = RememberedSignal(
            symbol    = sig.symbol,
            direction = sig.direction,
            entry     = sig.entry_price,
            stop_loss = sig.stop_loss,
            tp1       = sig.tp1,
            tp2       = sig.tp2,
            tp3       = sig.tp3,
        )
        mem.log(f"Recorded | Entry:{sig.entry_price} SL:{sig.stop_loss} "
                f"TP1:{sig.tp1} TP2:{sig.tp2} TP3:{sig.tp3}")
        self._memory[sig.symbol] = mem
        logger.info(f"Memory recorded: {mem.to_summary()}")

    def update_price(self, symbol: str, current_price: float):
        """
        Call on every price tick for a symbol.
        Updates internal TP / SL state.
        """
        mem = self._memory.get(symbol)
        if mem is None or mem.state in (TradeState.ALL_TP_HIT,
                                         TradeState.SL_HIT,
                                         TradeState.CLOSED):
            return   # nothing to track

        mem.last_checked_price = current_price
        changed = False

        if mem.direction == Direction.LONG:
            # Long: price rises to TP, falls to SL
            if not mem.sl_reached and current_price <= mem.stop_loss:
                mem.sl_reached = True
                mem.state      = TradeState.SL_HIT
                mem.state_changed_at = time.time()
                mem.log(f"🛑 SL HIT @ {current_price:.6f} (SL={mem.stop_loss:.6f})")
                changed = True

            elif not mem.tp1_reached and current_price >= mem.tp1:
                mem.tp1_reached = True
                mem.state       = TradeState.TP1_HIT
                mem.state_changed_at = time.time()
                mem.log(f"🎯 TP1 HIT @ {current_price:.6f}")
                changed = True

            elif mem.tp1_reached and not mem.tp2_reached and current_price >= mem.tp2:
                mem.tp2_reached = True
                mem.state       = TradeState.TP2_HIT
                mem.state_changed_at = time.time()
                mem.log(f"🎯 TP2 HIT @ {current_price:.6f}")
                changed = True

            elif mem.tp2_reached and not mem.tp3_reached and current_price >= mem.tp3:
                mem.tp3_reached = True
                mem.state       = TradeState.ALL_TP_HIT
                mem.state_changed_at = time.time()
                mem.log(f"🎯 TP3 HIT @ {current_price:.6f} — ALL TARGETS DONE")
                changed = True

        else:
            # Short: price falls to TP, rises to SL
            if not mem.sl_reached and current_price >= mem.stop_loss:
                mem.sl_reached = True
                mem.state      = TradeState.SL_HIT
                mem.state_changed_at = time.time()
                mem.log(f"🛑 SL HIT @ {current_price:.6f} (SL={mem.stop_loss:.6f})")
                changed = True

            elif not mem.tp1_reached and current_price <= mem.tp1:
                mem.tp1_reached = True
                mem.state       = TradeState.TP1_HIT
                mem.state_changed_at = time.time()
                mem.log(f"🎯 TP1 HIT @ {current_price:.6f}")
                changed = True

            elif mem.tp1_reached and not mem.tp2_reached and current_price <= mem.tp2:
                mem.tp2_reached = True
                mem.state       = TradeState.TP2_HIT
                mem.state_changed_at = time.time()
                mem.log(f"🎯 TP2 HIT @ {current_price:.6f}")
                changed = True

            elif mem.tp2_reached and not mem.tp3_reached and current_price <= mem.tp3:
                mem.tp3_reached = True
                mem.state       = TradeState.ALL_TP_HIT
                mem.state_changed_at = time.time()
                mem.log(f"🎯 TP3 HIT @ {current_price:.6f} — ALL TARGETS DONE")
                changed = True

        if changed:
            logger.info(f"Price update → {mem.to_summary()}")

    def get_state(self, symbol: str) -> Optional[RememberedSignal]:
        return self._memory.get(symbol)

    def get_all_states(self) -> Dict[str, RememberedSignal]:
        return dict(self._memory)

    def force_close(self, symbol: str, reason: str = "manual"):
        """Manually close a remembered signal (admin command)."""
        mem = self._memory.get(symbol)
        if mem:
            mem.state = TradeState.CLOSED
            mem.log(f"Force closed: {reason}")

    def summary(self) -> List[str]:
        """Return human-readable summary of all remembered signals."""
        return [m.to_summary() for m in self._memory.values()]

    def active_count(self) -> int:
        return sum(1 for m in self._memory.values()
                   if m.state == TradeState.ACTIVE)

    def cleanup_old(self, max_age_hours: float = 12.0):
        """
        Remove entries older than max_age_hours that are already
        in a terminal state (ALL_TP_HIT, SL_HIT, CLOSED).
        Keeps memory lean over long bot runs.
        """
        cutoff = time.time() - max_age_hours * 3600
        terminal = {TradeState.ALL_TP_HIT, TradeState.SL_HIT, TradeState.CLOSED}
        to_del = [
            sym for sym, m in self._memory.items()
            if m.state in terminal and m.state_changed_at < cutoff
        ]
        for sym in to_del:
            del self._memory[sym]
        if to_del:
            logger.debug(f"Cleaned {len(to_del)} stale memory entries")
