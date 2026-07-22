"""
stats.py — Trade statistics tracker (Step 3).

Tracks:
  - Daily / Monthly / All-time win rate + PNL + W/L
  - MUTUALLY EXCLUSIVE TP distribution:
      TP1 bucket = trades whose final resolved exit was TP1 ONLY
      TP2 bucket = final exit TP2 (NOT counted if they also hit TP3+)
      ...each trade lands in exactly ONE bucket
"""
import json
import os
from datetime import datetime, timezone

from src.config import STATS_FILE, DATA_DIR, TP_WEIGHTS
from src.logger import log


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def calc_pnl(final_tp: int) -> float:
    """
    final_tp: 0 = SL hit, 1–5 = highest TP reached as final exit.
    PNL in R-multiples using front-loaded TP ladder.
      SL   → -1.0R
      TP1  → 0.30 × 1R = 0.30R
      TP2  → (0.30×1) + (0.25×2) = 0.80R
      TP3  → + (0.20×3) = 1.40R
      TP4  → + (0.15×4) = 2.00R
      TP5  → + (0.10×5) = 2.50R
    """
    if final_tp == 0:
        return -1.0
    return round(sum(TP_WEIGHTS[i] * (i + 1) for i in range(final_tp)), 3)


class StatsTracker:
    def __init__(self):
        self._trades: list[dict] = []
        self._counter: int       = 0
        self._load()

    # ── Public API ─────────────────────────────────────────────────────────────

    def record(self, final_tp: int) -> dict:
        """
        Record a resolved trade.
        final_tp: 0 = SL, 1–5 = TP level that was the FINAL exit.
        Returns updated stats snapshot.
        """
        self._counter += 1
        entry = {
            "id":       self._counter,
            "date":     _now(),
            "won":      final_tp > 0,
            "final_tp": final_tp,
            "pnl":      calc_pnl(final_tp),
        }
        self._trades.append(entry)
        self._save()
        label = f"TP{final_tp}" if final_tp else "SL"
        log.info(f"Trade #{self._counter} resolved: {label} | PNL {entry['pnl']:+.3f}R")
        return self.snapshot()

    def next_trade_number(self) -> int:
        """Trade number the NEXT fired signal will carry."""
        return self._counter + 1

    def snapshot(self) -> dict:
        """Full stats block embedded in every alert."""
        today = _today()
        month = _month()

        daily   = [t for t in self._trades if t["date"][:10] == today]
        monthly = [t for t in self._trades if t["date"][:7]  == month]
        total   = self._trades

        def _wr(arr):
            if not arr:
                return 0.0
            return round(sum(1 for t in arr if t["won"]) / len(arr) * 100, 1)

        def _pnl(arr):
            return round(sum(t["pnl"] for t in arr), 2)

        def _wl(arr):
            w = sum(1 for t in arr if t["won"])
            return w, len(arr) - w

        dw, dl = _wl(daily)
        mw, ml = _wl(monthly)
        tw, tl = _wl(total)

        # Mutually exclusive buckets — final_tp == bucket number exactly
        tp_buckets = [
            sum(1 for t in total if t["final_tp"] == tp)
            for tp in range(1, 6)
        ]

        return {
            "trade_number": self._counter,
            "daily":   {"wr": _wr(daily),   "pnl": _pnl(daily),   "wins": dw, "losses": dl},
            "monthly": {"wr": _wr(monthly), "pnl": _pnl(monthly), "wins": mw, "losses": ml},
            "total":   {"wr": _wr(total),   "pnl": _pnl(total),   "wins": tw, "losses": tl},
            "tp_buckets": tp_buckets,
            "sl_count":   sum(1 for t in total if t["final_tp"] == 0),
        }

    # ── Persistence ────────────────────────────────────────────────────────────

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            with open(STATS_FILE, "w") as f:
                json.dump(
                    {"counter": self._counter, "trades": self._trades},
                    f, indent=2,
                )
        except Exception as e:
            log.error(f"Stats save failed: {e}")

    def _load(self):
        if not os.path.exists(STATS_FILE):
            return
        try:
            with open(STATS_FILE) as f:
                p = json.load(f)
            self._counter = p.get("counter", 0)
            self._trades  = p.get("trades", [])
            log.info(f"Stats loaded — {self._counter} trades in history")
        except Exception as e:
            log.error(f"Stats load failed: {e}")
