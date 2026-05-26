"""
memory_engine.py ─ Smart signal deduplication + live TP/SL monitoring

Rules:
  • Same pair + same direction + active  → BLOCK
  • Same pair + direction changed        → ALLOW (clears old entry)
  • SL hit on prior signal               → ALLOW new same-direction
  • All TPs achieved on prior signal     → ALLOW new same-direction
  • New pair                             → ALLOW always
"""
import time
from dataclasses import dataclass, field
from typing import Optional
from logger_setup import get_logger

log = get_logger("memory")


@dataclass
class ActiveSignal:
    pair:      str
    direction: str
    entry:     float
    sl:        float
    tps:       list
    rrs:       list
    trade_no:  int
    sig_id:    str
    tp_hit:    list = field(default_factory=list)
    sl_hit:    bool = False
    resolved:  bool = False
    created:   float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.tp_hit:
            self.tp_hit = [False] * len(self.tps)

    @property
    def all_tp_done(self) -> bool:
        return bool(self.tp_hit) and all(self.tp_hit)

    @property
    def highest_tp_idx(self) -> int:
        """0-based index of the highest TP achieved, or -1 if none."""
        for i in range(len(self.tp_hit) - 1, -1, -1):
            if self.tp_hit[i]:
                return i
        return -1

    def mark_tp(self, idx: int):
        for i in range(idx + 1):
            self.tp_hit[i] = True
        if self.all_tp_done:
            self.resolved = True

    def mark_sl(self):
        self.sl_hit  = True
        self.resolved = True


class MemoryEngine:

    def __init__(self):
        self._mem: dict[str, ActiveSignal] = {}

    # ── Deduplication ─────────────────────────────────────────────

    def evaluate(self, pair: str, direction: str) -> tuple[bool, str]:
        m = self._mem.get(pair)
        if m is None:
            return True, "New pair — no prior signal."
        if m.direction != direction:
            return True, f"Direction flip {m.direction}→{direction}."
        if m.sl_hit:
            return True, f"Prior SL hit — new {direction} allowed."
        if m.all_tp_done:
            return True, f"All TPs achieved — new {direction} allowed."
        done = m.tp_hit.count(True)
        note = f"TP{done} last hit. " if done else "No TPs yet. "
        return False, f"DUPLICATE {direction} on {pair}. {note}Waiting for resolution."

    def commit(self, sig: dict) -> ActiveSignal:
        pair = sig["pair"]
        entry = (sig["entry_low"] + sig["entry_high"]) / 2.0
        m = ActiveSignal(
            pair=pair, direction=sig["direction"],
            entry=entry, sl=sig["sl"],
            tps=list(sig["tps"]), rrs=list(sig["rrs"]),
            trade_no=sig["trade_no"], sig_id=sig["id"],
        )
        self._mem[pair] = m
        log.info(f"[MEM] Stored {pair} {sig['direction']} #{sig['trade_no']}")
        return m

    # ── Live price check ──────────────────────────────────────────

    def check_price(self, pair: str, price: float) -> Optional[dict]:
        """
        Called on every ticker update for active pairs.
        Returns a resolution event dict when TP or SL is hit, else None.
        """
        m = self._mem.get(pair)
        if m is None or m.resolved:
            return None

        # SL check
        sl_hit = (m.direction == "LONG"  and price <= m.sl) or \
                 (m.direction == "SHORT" and price >= m.sl)
        if sl_hit:
            m.mark_sl()
            log.info(f"[MEM] ⛔ SL {pair} @ {price:.6g}")
            return {"type": "SL", "pair": pair, "price": price,
                    "trade_no": m.trade_no, "sig_id": m.sig_id}

        # TP check — find first unachieved TP
        for i, tp in enumerate(m.tps):
            if m.tp_hit[i]:
                continue
            hit = (m.direction == "LONG"  and price >= tp) or \
                  (m.direction == "SHORT" and price <= tp)
            if hit:
                m.mark_tp(i)
                log.info(f"[MEM] ✅ TP{i+1} {pair} @ {price:.6g}")
                return {"type": f"TP{i+1}", "tp_idx": i, "pair": pair,
                        "price": price, "rr": m.rrs[i],
                        "trade_no": m.trade_no, "sig_id": m.sig_id,
                        "all_done": m.all_tp_done}
        return None

    # ── Maintenance ───────────────────────────────────────────────

    def active_pairs(self) -> list[str]:
        return [p for p, m in self._mem.items() if not m.resolved]

    def purge_old(self, max_age_s: int = 7200):
        """Remove resolved entries older than max_age_s seconds."""
        cut = time.time() - max_age_s
        old = [p for p, m in self._mem.items() if m.resolved and m.created < cut]
        for p in old:
            del self._mem[p]
