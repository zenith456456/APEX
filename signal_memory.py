"""
APEX-EDS v4.0 | signal_memory.py
Smart signal deduplication — price-state driven, no timers.

Decision logic per coin:
  ① Never seen before          → SEND ✓
  ② Direction changed          → SEND ✓  (reversal)
  ③ Same dir, ALL_TP_HIT       → SEND ✓  (cycle complete)
  ④ Same dir, SL_HIT           → SEND ✓  (re-entry)
  ⑤ Same dir, CLOSED           → SEND ✓  (force-closed)
  ⑥ Same dir, still ACTIVE     → BLOCK ✗ (duplicate)
"""

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from models import Direction, RememberedSignal, SignalResult, TradeState

logger = logging.getLogger("SignalMemory")


@dataclass
class Decision:
    allow:  bool
    reason: str
    prev:   Optional[RememberedSignal] = None


class SignalMemory:
    """
    Stateful store of the last signal per trading pair.
    Thread-safe within a single asyncio event loop.
    """

    def __init__(self):
        self._mem: Dict[str, RememberedSignal] = {}

    # ── CHECK ─────────────────────────────────────────────────────────────

    def check(self, new_sig: SignalResult) -> Decision:
        sym  = new_sig.symbol
        prev = self._mem.get(sym)

        if prev is None:
            return Decision(True, "First signal for this pair")

        if prev.direction != new_sig.direction:
            return Decision(
                True,
                f"Direction CHANGED {prev.direction.value} → {new_sig.direction.value}",
                prev,
            )

        # Same direction — check state
        if prev.state == TradeState.ALL_TP_HIT:
            return Decision(True, "All TP targets achieved — new entry allowed", prev)

        if prev.state == TradeState.SL_HIT:
            return Decision(True, "Stop loss hit — re-entry allowed", prev)

        if prev.state == TradeState.CLOSED:
            return Decision(True, "Previous trade closed — new signal allowed", prev)

        # Still active
        tps = (
            f"TP1{'✓' if prev.tp1_reached else '○'} "
            f"TP2{'✓' if prev.tp2_reached else '○'} "
            f"TP3{'✓' if prev.tp3_reached else '○'}"
        )
        return Decision(
            False,
            f"BLOCKED — {sym} {prev.direction.value} active | "
            f"{tps} | Age {prev.age_minutes:.1f}m | {prev.state.name}",
            prev,
        )

    # ── RECORD ────────────────────────────────────────────────────────────

    def record(self, sig: SignalResult, prev: Optional[RememberedSignal] = None):
        """Store a signal after it has been approved and sent."""
        if prev is not None:
            prev.state = TradeState.CLOSED
            prev.history.append(f"[{_ts()}] Superseded by new signal")

        mem = RememberedSignal(
            symbol    = sig.symbol,
            direction = sig.direction,
            entry     = sig.entry_price,
            stop_loss = sig.stop_loss,
            tp1       = sig.tp1,
            tp2       = sig.tp2,
            tp3       = sig.tp3,
        )
        mem.history.append(
            f"[{_ts()}] Recorded | Entry:{sig.entry_price} "
            f"SL:{sig.stop_loss} TP1:{sig.tp1} TP2:{sig.tp2} TP3:{sig.tp3}"
        )
        self._mem[sig.symbol] = mem
        logger.info(f"Memory: recorded {mem.symbol} {mem.direction.value}")

    # ── UPDATE PRICE ──────────────────────────────────────────────────────

    def update_price(self, symbol: str, price: float):
        """Call on every price tick to advance TP/SL state."""
        mem = self._mem.get(symbol)
        if mem is None:
            return
        if mem.state in (TradeState.ALL_TP_HIT, TradeState.SL_HIT, TradeState.CLOSED):
            return

        changed = False

        if mem.direction == Direction.LONG:
            if not mem.sl_reached and price <= mem.stop_loss:
                mem.sl_reached = True
                mem.state      = TradeState.SL_HIT
                changed        = True
                mem.history.append(f"[{_ts()}] 🛑 SL hit @ {price:.6f}")
            elif not mem.tp1_reached and price >= mem.tp1:
                mem.tp1_reached = True
                mem.state       = TradeState.TP1_HIT
                changed         = True
                mem.history.append(f"[{_ts()}] 🎯 TP1 hit @ {price:.6f}")
            elif mem.tp1_reached and not mem.tp2_reached and price >= mem.tp2:
                mem.tp2_reached = True
                mem.state       = TradeState.TP2_HIT
                changed         = True
                mem.history.append(f"[{_ts()}] 🎯 TP2 hit @ {price:.6f}")
            elif mem.tp2_reached and not mem.tp3_reached and price >= mem.tp3:
                mem.tp3_reached = True
                mem.state       = TradeState.ALL_TP_HIT
                changed         = True
                mem.history.append(f"[{_ts()}] 🎯 TP3 hit @ {price:.6f} — ALL DONE")
        else:  # SHORT
            if not mem.sl_reached and price >= mem.stop_loss:
                mem.sl_reached = True
                mem.state      = TradeState.SL_HIT
                changed        = True
                mem.history.append(f"[{_ts()}] 🛑 SL hit @ {price:.6f}")
            elif not mem.tp1_reached and price <= mem.tp1:
                mem.tp1_reached = True
                mem.state       = TradeState.TP1_HIT
                changed         = True
                mem.history.append(f"[{_ts()}] 🎯 TP1 hit @ {price:.6f}")
            elif mem.tp1_reached and not mem.tp2_reached and price <= mem.tp2:
                mem.tp2_reached = True
                mem.state       = TradeState.TP2_HIT
                changed         = True
                mem.history.append(f"[{_ts()}] 🎯 TP2 hit @ {price:.6f}")
            elif mem.tp2_reached and not mem.tp3_reached and price <= mem.tp3:
                mem.tp3_reached = True
                mem.state       = TradeState.ALL_TP_HIT
                changed         = True
                mem.history.append(f"[{_ts()}] 🎯 TP3 hit @ {price:.6f} — ALL DONE")

        if changed:
            mem.state_changed_at = time.time()
            logger.info(
                f"Memory state: {symbol} → {mem.state.name} "
                f"TP1:{mem.tp1_reached} TP2:{mem.tp2_reached} "
                f"TP3:{mem.tp3_reached} SL:{mem.sl_reached}"
            )

    # ── UTILS ─────────────────────────────────────────────────────────────

    def get_state(self, symbol: str) -> Optional[RememberedSignal]:
        return self._mem.get(symbol)

    def get_all(self) -> Dict[str, RememberedSignal]:
        return dict(self._mem)

    def force_close(self, symbol: str, reason: str = "manual"):
        mem = self._mem.get(symbol)
        if mem:
            mem.state = TradeState.CLOSED
            mem.history.append(f"[{_ts()}] Force closed: {reason}")

    def active_count(self) -> int:
        return sum(1 for m in self._mem.values() if m.state == TradeState.ACTIVE)

    def cleanup(self, max_age_hours: float = 12.0):
        terminal = {TradeState.ALL_TP_HIT, TradeState.SL_HIT, TradeState.CLOSED}
        cutoff   = time.time() - max_age_hours * 3600
        stale    = [
            s for s, m in self._mem.items()
            if m.state in terminal and m.state_changed_at < cutoff
        ]
        for s in stale:
            del self._mem[s]
        if stale:
            logger.info(f"Memory cleanup: removed {len(stale)} stale entries")

    def summary(self) -> List[str]:
        lines = []
        for m in self._mem.values():
            tps = (
                f"TP1{'✓' if m.tp1_reached else '○'}"
                f"TP2{'✓' if m.tp2_reached else '○'}"
                f"TP3{'✓' if m.tp3_reached else '○'}"
            )
            lines.append(
                f"{m.symbol:<15} {m.direction.value:<5} {m.state.name:<12} "
                f"{tps}  SL{'✓' if m.sl_reached else '○'}  Age {m.age_minutes:.0f}m"
            )
        return lines


def _ts() -> str:
    return time.strftime("%H:%M:%S", time.gmtime())
