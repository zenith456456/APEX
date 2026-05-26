"""
stats_tracker.py ─ Live performance statistics
Tracks Daily / Monthly / All-time win rate, PNL, and exclusive TP buckets.

TP bucket rule: count only the HIGHEST TP level per signal (exclusive).
"""
from collections import defaultdict
from datetime import datetime, timezone
from logger_setup import get_logger

log = get_logger("stats")


def _today()  -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%d")
def _month()  -> str: return datetime.now(timezone.utc).strftime("%Y-%m")


class _Period:
    def __init__(self):
        self.wins   = 0
        self.losses = 0
        self.pnl    = 0.0

    @property
    def total(self) -> int: return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return round(self.wins / self.total * 100.0, 1) if self.total else 0.0

    @property
    def pnl_str(self) -> str:
        return f"{'+' if self.pnl >= 0 else ''}{self.pnl:.2f}R"


class StatsTracker:

    def __init__(self):
        self.trade_count = 0              # signals emitted (allowed)
        self.all         = _Period()
        self._daily:   dict[str, _Period] = defaultdict(_Period)
        self._monthly: dict[str, _Period] = defaultdict(_Period)
        # Exclusive TP buckets [TP1-only, TP2, TP3, TP4, TP5]
        self.tp_buckets = [0, 0, 0, 0, 0]
        self.sl_hits    = 0

    # ── Public API ─────────────────────────────────────────────────

    def signal_emitted(self):
        self.trade_count += 1

    def record_win(self, tp_idx: int, rr_val: float):
        """
        tp_idx: 0-based index of the HIGHEST TP hit (0=TP1, 1=TP2, …)
        rr_val: R earned (e.g. 3.0 for 1:3 R:R)
        """
        d, m = _today(), _month()
        for p in (self.all, self._daily[d], self._monthly[m]):
            p.wins += 1
            p.pnl   = round(p.pnl + rr_val, 2)
        self.tp_buckets[min(tp_idx, 4)] += 1
        log.info(f"[STATS] WIN TP{tp_idx+1} +{rr_val}R | "
                 f"All-time {self.all.wins}W/{self.all.losses}L "
                 f"WR {self.all.win_rate}%")

    def record_loss(self, risk_r: float = 1.0):
        d, m = _today(), _month()
        for p in (self.all, self._daily[d], self._monthly[m]):
            p.losses += 1
            p.pnl     = round(p.pnl - risk_r, 2)
        self.sl_hits += 1
        log.info(f"[STATS] LOSS −{risk_r}R | "
                 f"All-time {self.all.wins}W/{self.all.losses}L "
                 f"WR {self.all.win_rate}%")

    @property
    def today(self) -> _Period:
        return self._daily[_today()]

    @property
    def this_month(self) -> _Period:
        return self._monthly[_month()]

    def snapshot(self) -> dict:
        tot = sum(self.tp_buckets) + self.sl_hits
        def pct(n): return round(n / tot * 100.0, 1) if tot else 0.0
        return {
            "trade_count": self.trade_count,
            "daily":   self._period_dict(self.today),
            "monthly": self._period_dict(self.this_month),
            "total":   self._period_dict(self.all),
            "tp": {
                "tp1": self.tp_buckets[0], "tp1_pct": pct(self.tp_buckets[0]),
                "tp2": self.tp_buckets[1], "tp2_pct": pct(self.tp_buckets[1]),
                "tp3": self.tp_buckets[2], "tp3_pct": pct(self.tp_buckets[2]),
                "tp4": self.tp_buckets[3], "tp4_pct": pct(self.tp_buckets[3]),
                "tp5": self.tp_buckets[4], "tp5_pct": pct(self.tp_buckets[4]),
                "sl":  self.sl_hits,       "sl_pct":  pct(self.sl_hits),
            },
        }

    @staticmethod
    def _period_dict(p: _Period) -> dict:
        return {"wins": p.wins, "losses": p.losses,
                "pnl": p.pnl, "pnl_str": p.pnl_str,
                "wr": p.win_rate, "total": p.total}
