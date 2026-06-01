"""
memory_engine.py — Smart deduplication + live TP/SL monitoring

RESOLUTION RULES (fixed):
  • Signal resolves in exactly ONE of two ways:
    1. SL hit:      if any TP was hit before → WIN at highest TP
                    if no TP was hit         → LOSS
    2. All TPs hit: WIN at final TP

  • Partial TP hits (some TPs done, not all, no SL yet) → signal stays ACTIVE
    check_price() returns a "TP_PARTIAL" type which scanner does NOT record in stats.

  • check_price() return types:
    "TP_PARTIAL"  → TP hit but signal not yet resolved (more TPs remain)
    "TP_FINAL"    → All TPs hit → caller should record_win(highest_tp_idx)
    "SL_CLEAN"    → SL hit with NO prior TPs → caller should record_loss()
    "SL_AFTER_TP" → SL hit but TP was hit before → caller should record_win(highest_tp_idx)
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
    # Track whether stats have been recorded for this signal (prevent double-count)
    stats_recorded: bool = False

    def __post_init__(self):
        if not self.tp_hit:
            self.tp_hit = [False] * len(self.tps)

    @property
    def all_tp_done(self) -> bool:
        return bool(self.tp_hit) and all(self.tp_hit)

    @property
    def any_tp_hit(self) -> bool:
        return any(self.tp_hit)

    @property
    def highest_tp_idx(self) -> int:
        """0-based index of highest TP achieved, -1 if none."""
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
        self.sl_hit   = True
        self.resolved = True


class MemoryEngine:

    def __init__(self):
        self._mem: dict[str, ActiveSignal] = {}

    # ── Deduplication ─────────────────────────────────────────────

    def evaluate(self, pair: str, direction: str) -> tuple[bool, str]:
        m = self._mem.get(pair)
        if m is None:
            return True, "New pair."
        if m.direction != direction:
            return True, f"Direction flip {m.direction}→{direction}."
        if m.sl_hit:
            return True, f"Prior SL hit — new {direction} allowed."
        if m.all_tp_done:
            return True, f"All TPs achieved — new {direction} allowed."
        done = m.tp_hit.count(True)
        note = f"TP{done} last hit. " if done else "No TPs yet. "
        return False, f"DUPLICATE {direction} on {pair}. {note}Waiting resolution."

    def commit(self, sig: dict) -> ActiveSignal:
        pair  = sig["pair"]
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

    def get(self, pair: str) -> Optional[ActiveSignal]:
        return self._mem.get(pair)

    # ── Live price check ──────────────────────────────────────────

    def check_price(self, pair: str, price: float) -> Optional[dict]:
        """
        Returns a resolution event dict or None.

        Event types:
          TP_PARTIAL   — TP hit, signal still active (more TPs remain)
          TP_FINAL     — All TPs hit → record_win(highest_tp_idx)
          SL_CLEAN     — SL hit, no prior TP → record_loss()
          SL_AFTER_TP  — SL hit, but TP was hit before → record_win(highest_tp_idx)
        """
        m = self._mem.get(pair)
        if m is None or m.resolved:
            return None

        # ── SL check ──────────────────────────────────────────────
        sl_hit = (m.direction == "LONG"  and price <= m.sl) or \
                 (m.direction == "SHORT" and price >= m.sl)
        if sl_hit:
            had_tp = m.any_tp_hit
            htidx  = m.highest_tp_idx
            m.mark_sl()
            if had_tp:
                # Win at the highest TP reached before SL
                rr = m.rrs[htidx]
                try:    rr_val = float(rr.split(":")[-1])
                except: rr_val = 1.0
                log.info(f"[MEM] SL_AFTER_TP {pair} @ {price:.6g} "
                         f"(best TP{htidx+1} {rr})")
                return {
                    "type":      "SL_AFTER_TP",
                    "pair":      pair,
                    "price":     price,
                    "trade_no":  m.trade_no,
                    "sig_id":    m.sig_id,
                    "tp_idx":    htidx,
                    "rr":        rr,
                    "rr_val":    rr_val,
                }
            else:
                log.info(f"[MEM] SL_CLEAN {pair} @ {price:.6g} (no TP hit)")
                return {
                    "type":     "SL_CLEAN",
                    "pair":     pair,
                    "price":    price,
                    "trade_no": m.trade_no,
                    "sig_id":   m.sig_id,
                }

        # ── TP check — find next unachieved TP ────────────────────
        for i, tp_price in enumerate(m.tps):
            if m.tp_hit[i]:
                continue
            hit = (m.direction == "LONG"  and price >= tp_price) or \
                  (m.direction == "SHORT" and price <= tp_price)
            if hit:
                m.mark_tp(i)
                rr = m.rrs[i]
                try:    rr_val = float(rr.split(":")[-1])
                except: rr_val = 1.0

                if m.all_tp_done:
                    log.info(f"[MEM] TP_FINAL TP{i+1} {pair} @ {price:.6g} (all done)")
                    return {
                        "type":     "TP_FINAL",
                        "pair":     pair,
                        "price":    price,
                        "trade_no": m.trade_no,
                        "sig_id":   m.sig_id,
                        "tp_idx":   i,
                        "rr":       rr,
                        "rr_val":   rr_val,
                    }
                else:
                    log.info(f"[MEM] TP_PARTIAL TP{i+1} {pair} @ {price:.6g} "
                             f"({m.tp_hit.count(True)}/{len(m.tps)} done)")
                    return {
                        "type":       "TP_PARTIAL",
                        "tp_num":     i + 1,
                        "pair":       pair,
                        "price":      price,
                        "trade_no":   m.trade_no,
                        "sig_id":     m.sig_id,
                        "tp_idx":     i,
                        "rr":         rr,
                        "rr_val":     rr_val,
                        "tps_done":   m.tp_hit.count(True),
                        "tps_total":  len(m.tps),
                    }
        return None

    # ── Maintenance ───────────────────────────────────────────────

    def active_pairs(self) -> list[str]:
        return [p for p, m in self._mem.items() if not m.resolved]

    def purge_old(self, max_age_s: int = 7200):
        cut  = time.time() - max_age_s
        dead = [p for p, m in self._mem.items()
                if m.resolved and m.created < cut]
        for p in dead:
            del self._mem[p]
        if dead:
            log.debug(f"Purged {len(dead)} stale memory entries")
