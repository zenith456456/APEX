"""
stats_tracker.py — Live performance statistics

FIXED COUNTING RULES:
  • Total signals  = number of signals EMITTED (trade_count)
  • Win            = signal resolved with at least 1 TP hit (counted ONCE)
  • Loss           = signal resolved at SL with ZERO TPs hit (counted ONCE)
  • trade_count    = wins + losses  (always equal)

  A signal resolves in exactly ONE of two ways:
    1. SL hit — if any TP was previously hit → WIN at highest TP achieved
                 if NO TP was hit            → LOSS
    2. All TPs hit                           → WIN at final TP

  Partial TP hits (TP1 hit, waiting for TP2) do NOT touch stats.
  Stats are updated only on full resolution.

TP bucket rule (exclusive):
  Each resolved WIN is counted in exactly ONE bucket — its highest TP.
  TP1-only: hit TP1 and resolved (SL after TP1, or TP1 was the only TP)
  TP2:      highest hit = TP2
  TP3:      highest hit = TP3  (TP1 and TP2 NOT counted here again)
  TP4:      highest hit = TP4
  TP5:      highest hit = TP5
"""
from collections import defaultdict
from datetime import datetime, timezone
from logger_setup import get_logger

log = get_logger("stats")


def _today() -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%d")
def _month() -> str: return datetime.now(timezone.utc).strftime("%Y-%m")


class _Period:
    __slots__ = ("wins", "losses", "pnl")
    def __init__(self): self.wins = 0; self.losses = 0; self.pnl = 0.0

    @property
    def total(self)    -> int:   return self.wins + self.losses
    @property
    def win_rate(self) -> float:
        return round(self.wins / self.total * 100.0, 1) if self.total else 0.0
    @property
    def pnl_str(self)  -> str:
        return f"{'+' if self.pnl >= 0 else ''}{self.pnl:.2f}R"


class StatsTracker:

    def __init__(self):
        self.trade_count: int = 0          # total signals emitted
        self.all   = _Period()
        self._daily:   dict[str, _Period] = defaultdict(_Period)
        self._monthly: dict[str, _Period] = defaultdict(_Period)
        # Exclusive TP buckets: index = highest TP achieved (0=TP1 … 4=TP5)
        self.tp_buckets: list[int] = [0, 0, 0, 0, 0]
        self.sl_hits:    int       = 0     # pure losses (no TP hit)

    # ── Public API ─────────────────────────────────────────────────

    def signal_emitted(self):
        """Call once per signal when it passes dedup and is sent out."""
        self.trade_count += 1

    def record_win(self, highest_tp_idx: int, rr_val: float):
        """
        Record ONE win for a fully resolved signal.
        highest_tp_idx: 0-based index of the highest TP achieved.
        rr_val:         R earned at that TP level.
        Called ONCE per signal — either when all TPs hit OR when SL hits
        after at least one TP was already hit.
        """
        d, m = _today(), _month()
        for p in (self.all, self._daily[d], self._monthly[m]):
            p.wins += 1
            p.pnl   = round(p.pnl + rr_val, 2)
        self.tp_buckets[min(highest_tp_idx, 4)] += 1
        log.info(
            f"[STATS] WIN TP{highest_tp_idx+1} +{rr_val}R | "
            f"All-time {self.all.wins}W / {self.all.losses}L | "
            f"WR {self.all.win_rate}% | "
            f"Total trades {self.trade_count}"
        )
        self._assert_integrity()

    def record_loss(self, risk_r: float = 1.0):
        """
        Record ONE loss — only called when SL is hit AND no TP was ever hit.
        """
        d, m = _today(), _month()
        for p in (self.all, self._daily[d], self._monthly[m]):
            p.losses += 1
            p.pnl     = round(p.pnl - risk_r, 2)
        self.sl_hits += 1
        log.info(
            f"[STATS] LOSS −{risk_r}R | "
            f"All-time {self.all.wins}W / {self.all.losses}L | "
            f"WR {self.all.win_rate}% | "
            f"Total trades {self.trade_count}"
        )
        self._assert_integrity()

    def _assert_integrity(self):
        """Sanity check: resolved = wins + losses <= trade_count."""
        resolved = self.all.wins + self.all.losses
        if resolved > self.trade_count:
            log.error(
                f"[STATS] INTEGRITY ERROR: wins({self.all.wins}) + "
                f"losses({self.all.losses}) = {resolved} "
                f"> trade_count({self.trade_count})"
            )

    @property
    def today(self)      -> _Period: return self._daily[_today()]
    @property
    def this_month(self) -> _Period: return self._monthly[_month()]

    def snapshot(self) -> dict:
        resolved = sum(self.tp_buckets) + self.sl_hits
        def pct(n): return round(n / resolved * 100.0, 1) if resolved else 0.0

        return {
            "trade_count": self.trade_count,
            "resolved":    self.all.wins + self.all.losses,
            "pending":     self.trade_count - (self.all.wins + self.all.losses),
            "daily":   self._pd(self.today),
            "monthly": self._pd(self.this_month),
            "total":   self._pd(self.all),
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
    def _pd(p: _Period) -> dict:
        return {"wins": p.wins, "losses": p.losses, "pnl": p.pnl,
                "pnl_str": p.pnl_str, "wr": p.win_rate, "total": p.total}
