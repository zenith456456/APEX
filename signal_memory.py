"""
APEX-EDS v4.0 | signal_memory.py
Price-driven deduplication state machine — no timers.
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

    def __init__(self):
        self._mem: Dict[str, RememberedSignal] = {}

    def check(self, sig: SignalResult) -> Decision:
        prev = self._mem.get(sig.symbol)
        if prev is None:
            return Decision(True, "First signal for this pair")
        if prev.direction != sig.direction:
            return Decision(True, f"Direction CHANGED {prev.direction.value}→{sig.direction.value}", prev)
        if prev.state == TradeState.ALL_TP_HIT: return Decision(True, "All TPs hit — new entry", prev)
        if prev.state == TradeState.SL_HIT:     return Decision(True, "SL hit — re-entry allowed", prev)
        if prev.state == TradeState.CLOSED:     return Decision(True, "Previous trade closed", prev)
        tps = f"TP1{'✓' if prev.tp1_reached else '○'}TP2{'✓' if prev.tp2_reached else '○'}TP3{'✓' if prev.tp3_reached else '○'}"
        return Decision(False, f"BLOCKED {sig.symbol} {prev.direction.value} {tps} Age={prev.age_minutes:.1f}m", prev)

    def record(self, sig: SignalResult, prev: Optional[RememberedSignal] = None):
        if prev:
            prev.state = TradeState.CLOSED
            prev.history.append(f"[{_ts()}] Superseded")
        mem = RememberedSignal(
            symbol=sig.symbol, direction=sig.direction, entry=sig.entry_price,
            stop_loss=sig.stop_loss, tp1=sig.tp1, tp2=sig.tp2, tp3=sig.tp3,
        )
        mem.history.append(f"[{_ts()}] Recorded")
        self._mem[sig.symbol] = mem

    def update_price(self, symbol: str, price: float):
        mem = self._mem.get(symbol)
        if not mem or mem.state in (TradeState.ALL_TP_HIT, TradeState.SL_HIT, TradeState.CLOSED):
            return
        changed = False
        is_long = mem.direction == Direction.LONG

        def hit(new_state):
            nonlocal changed
            mem.state = new_state; mem.state_changed_at = time.time(); changed = True

        if is_long:
            if not mem.sl_reached  and price <= mem.stop_loss: mem.sl_reached  = True; hit(TradeState.SL_HIT);     mem.history.append(f"[{_ts()}] SL@{price:.4f}")
            elif not mem.tp1_reached and price >= mem.tp1:     mem.tp1_reached = True; hit(TradeState.TP1_HIT);    mem.history.append(f"[{_ts()}] TP1@{price:.4f}")
            elif mem.tp1_reached and not mem.tp2_reached and price >= mem.tp2: mem.tp2_reached = True; hit(TradeState.TP2_HIT);    mem.history.append(f"[{_ts()}] TP2@{price:.4f}")
            elif mem.tp2_reached and not mem.tp3_reached and price >= mem.tp3: mem.tp3_reached = True; hit(TradeState.ALL_TP_HIT); mem.history.append(f"[{_ts()}] TP3@{price:.4f} ALL DONE")
        else:
            if not mem.sl_reached  and price >= mem.stop_loss: mem.sl_reached  = True; hit(TradeState.SL_HIT);     mem.history.append(f"[{_ts()}] SL@{price:.4f}")
            elif not mem.tp1_reached and price <= mem.tp1:     mem.tp1_reached = True; hit(TradeState.TP1_HIT);    mem.history.append(f"[{_ts()}] TP1@{price:.4f}")
            elif mem.tp1_reached and not mem.tp2_reached and price <= mem.tp2: mem.tp2_reached = True; hit(TradeState.TP2_HIT);    mem.history.append(f"[{_ts()}] TP2@{price:.4f}")
            elif mem.tp2_reached and not mem.tp3_reached and price <= mem.tp3: mem.tp3_reached = True; hit(TradeState.ALL_TP_HIT); mem.history.append(f"[{_ts()}] TP3@{price:.4f} ALL DONE")

        if changed:
            logger.info(f"Memory: {symbol} → {mem.state.name}")

    def get_state(self, symbol: str) -> Optional[RememberedSignal]:
        return self._mem.get(symbol)

    def get_all(self) -> Dict[str, RememberedSignal]:
        return dict(self._mem)

    def active_count(self) -> int:
        return sum(1 for m in self._mem.values() if m.state == TradeState.ACTIVE)

    def cleanup(self, max_age_hours: float = 12.0):
        terminal = {TradeState.ALL_TP_HIT, TradeState.SL_HIT, TradeState.CLOSED}
        cutoff   = time.time() - max_age_hours * 3600
        stale    = [s for s, m in self._mem.items() if m.state in terminal and m.state_changed_at < cutoff]
        for s in stale: del self._mem[s]
        if stale: logger.info(f"Cleaned {len(stale)} stale memory entries")


def _ts(): return time.strftime("%H:%M:%S", time.gmtime())
