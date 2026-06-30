# ─── apex_signal_memory.py ─────────────────────────────────────────────────
# APEX Signal Bot — Smart Signal Deduplication & State Memory Engine
# Pure state machine — no countdown timers

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("APEX.Memory")


class SignalStatus:
    ACTIVE      = "ACTIVE"
    TP1_HIT     = "TP1_HIT"
    TP2_HIT     = "TP2_HIT"
    TP3_HIT     = "TP3_HIT"
    TP4_HIT     = "TP4_HIT"
    ALL_TP_HIT  = "ALL_TP_HIT"
    SL_HIT      = "SL_HIT"

TP_STATUS_MAP = {0:"TP1_HIT", 1:"TP2_HIT", 2:"TP3_HIT", 3:"TP4_HIT", 4:"TP4_HIT"}


@dataclass
class SignalState:
    signal_id:     str
    pair:          str
    direction:     str            # "LONG" | "SHORT"
    entry:         List[float]    # [entry1, entry2]
    take_profits:  List[float]    # up to 5 TPs
    stop_loss:     float
    leverage:      int
    trade_type:    str            # SCALP | DAY | SWING
    timeframe:     str
    pattern:       str
    condition:     str
    mtcs_score:    int
    tp_hit:        List[bool]     = field(default_factory=list)
    sl_hit:        bool           = False
    status:        str            = SignalStatus.ACTIVE
    final_outcome: Optional[str]  = None   # "TP1".."TP5" | "SL"
    emit_time:     str            = ""
    close_time:    str            = ""
    emit_date:     str            = ""
    emit_month:    str            = ""
    pnl_pct:       float          = 0.0

    def __post_init__(self):
        if not self.tp_hit:
            self.tp_hit = [False] * len(self.take_profits)
        now = datetime.now(timezone.utc)
        if not self.emit_time:
            self.emit_time  = now.strftime("%H:%M:%S")
            self.emit_date  = now.strftime("%Y-%m-%d")
            self.emit_month = now.strftime("%Y-%m")

    def mark_tp(self, idx: int, base_risk: float = 1.2):
        """Mark TP[idx] as hit. Updates status and computes provisional PNL."""
        if idx >= len(self.take_profits):
            return
        self.tp_hit[idx] = True
        self.final_outcome = f"TP{idx + 1}"

        if all(self.tp_hit):
            self.status = SignalStatus.ALL_TP_HIT
            self.close_time = datetime.now(timezone.utc).strftime("%H:%M:%S")
        else:
            self.status = TP_STATUS_MAP.get(idx, SignalStatus.TP1_HIT)

        self._recalc_pnl(base_risk)
        logger.info(f"[{self.pair}] TP{idx+1} HIT | status={self.status} | pnl={self.pnl_pct:.2f}%")

    def mark_sl(self, base_risk: float = 1.2):
        """Mark stop loss hit."""
        self.sl_hit        = True
        self.status        = SignalStatus.SL_HIT
        self.final_outcome = "SL"
        self.pnl_pct       = -base_risk
        self.close_time    = datetime.now(timezone.utc).strftime("%H:%M:%S")
        logger.warning(f"[{self.pair}] SL HIT | pnl={self.pnl_pct:.2f}%")

    def _recalc_pnl(self, base_risk: float):
        """Weighted PNL across hit TPs with position allocation."""
        alloc = [0.30, 0.25, 0.20, 0.15, 0.10][: len(self.take_profits)]
        rr    = [1.4,  2.5,  3.8,  5.3,  7.1 ][: len(self.take_profits)]
        pnl   = 0.0
        for i, hit in enumerate(self.tp_hit):
            if hit:
                pnl += alloc[i] * rr[i] * base_risk
        self.pnl_pct = round(pnl, 3)

    @property
    def is_closed(self) -> bool:
        return self.status in (SignalStatus.ALL_TP_HIT, SignalStatus.SL_HIT)

    @property
    def is_win(self) -> bool:
        return self.is_closed and self.final_outcome != "SL"


class SignalMemoryEngine:
    """
    One SignalState per coin pair.
    Dedup rules (no timers):
      1. No prior record          → EMIT (NEW_PAIR)
      2. Direction changed        → EMIT (DIR_CHANGED)
      3. Previous = ALL_TP_HIT   → EMIT (ALL_TP_ACHIEVED)
      4. Previous = SL_HIT       → EMIT (SL_CLEARED)
      5. Still active/partial TP  → BLOCK (DUPLICATE)
    """

    def __init__(self, base_risk: float = 1.2):
        self.base_risk  = base_risk
        self.memory:    Dict[str, SignalState] = {}
        self.history:   List[SignalState]      = []
        self._counter:  int                    = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"APEX-{self._counter:04d}"

    # ── Evaluate ──────────────────────────────────────────────────────────
    def evaluate(self, signal: dict) -> dict:
        """
        Returns {"action":"EMIT"|"BLOCK", "reason":str, "signal_id":str|None}
        """
        pair      = signal["pair"]
        direction = signal["direction"]
        existing  = self.memory.get(pair)

        if existing is None:
            return self._do_emit(signal, "NEW_PAIR")

        if existing.direction != direction:
            return self._do_emit(signal, "DIR_CHANGED")

        if existing.status == SignalStatus.ALL_TP_HIT:
            return self._do_emit(signal, "ALL_TP_ACHIEVED")

        if existing.status == SignalStatus.SL_HIT:
            return self._do_emit(signal, "SL_CLEARED")

        tp_str = " | ".join(f"TP{i+1}{'✓' if h else '○'}"
                             for i, h in enumerate(existing.tp_hit))
        return {
            "action":    "BLOCK",
            "reason":    "DUPLICATE_BLOCK",
            "signal_id": None,
            "message":   f"{pair} {direction} still ACTIVE [{tp_str}]",
        }

    def _do_emit(self, signal: dict, reason: str) -> dict:
        pair = signal["pair"]
        if pair in self.memory:
            old = self.memory.pop(pair)
            if not old.is_closed:
                old.final_outcome = old.final_outcome or "SUPERSEDED"
            self.history.append(old)

        sid   = self._next_id()
        state = SignalState(
            signal_id    = sid,
            pair         = pair,
            direction    = signal["direction"],
            entry        = signal["entry"],
            take_profits = signal["take_profits"],
            stop_loss    = signal["stop_loss"],
            leverage     = signal.get("leverage", 10),
            trade_type   = signal.get("trade_type", "SCALP"),
            timeframe    = signal.get("timeframe", "5m"),
            pattern      = signal.get("pattern", ""),
            condition    = signal.get("condition", ""),
            mtcs_score   = signal.get("mtcs_score", 0),
        )
        self.memory[pair] = state
        logger.info(f"EMIT [{sid}] {pair} {signal['direction']} | {reason}")
        return {"action": "EMIT", "reason": reason, "signal_id": sid, "state": state}

    # ── Price update ──────────────────────────────────────────────────────
    def on_price_update(self, pair: str, price: float):
        state = self.memory.get(pair)
        if not state or state.is_closed:
            return
        is_long = state.direction == "LONG"
        for i, tp in enumerate(state.take_profits):
            if not state.tp_hit[i]:
                if (is_long and price >= tp) or (not is_long and price <= tp):
                    state.mark_tp(i, self.base_risk)
        if not state.sl_hit:
            if (is_long and price <= state.stop_loss) or \
               (not is_long and price >= state.stop_loss):
                state.mark_sl(self.base_risk)

    @property
    def all_states(self) -> List[SignalState]:
        return list(self.memory.values()) + self.history

    @property
    def active_count(self) -> int:
        return sum(1 for s in self.memory.values() if not s.is_closed)
