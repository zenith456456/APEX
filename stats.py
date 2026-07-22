"""
Trade statistics with mutually exclusive TP distribution.
TP2 bucket = trades whose FINAL exit was TP2 only (not TP3+).
Each resolved trade lands in exactly one bucket.
"""
import json, os
from datetime import datetime, timezone
import config
from logger import log


def _now(): return datetime.now(timezone.utc).isoformat()
def _today(): return datetime.now(timezone.utc).strftime("%Y-%m-%d")
def _month(): return datetime.now(timezone.utc).strftime("%Y-%m")


def calc_pnl(final_tp):
    """0=SL → -1.0R.  1-5=TP level → front-loaded R-multiples."""
    if final_tp == 0: return -1.0
    return round(sum(config.TP_WEIGHTS[i] * (i+1) for i in range(final_tp)), 3)


class StatsTracker:
    def __init__(self):
        self._trades  = []
        self._counter = 0
        self._load()

    def record(self, final_tp):
        self._counter += 1
        t = {"id": self._counter, "date": _now(),
             "won": final_tp > 0, "final_tp": final_tp, "pnl": calc_pnl(final_tp)}
        self._trades.append(t)
        self._save()
        log.info(f"Trade #{self._counter}: {'TP'+str(final_tp) if final_tp else 'SL'} | {t['pnl']:+.3f}R")
        return self.snapshot()

    def next_trade_number(self): return self._counter + 1

    def snapshot(self):
        today = _today(); month = _month()
        daily   = [t for t in self._trades if t["date"][:10] == today]
        monthly = [t for t in self._trades if t["date"][:7]  == month]
        total   = self._trades

        def wr(a):  return round(sum(1 for t in a if t["won"]) / len(a) * 100, 1) if a else 0.0
        def pnl(a): return round(sum(t["pnl"] for t in a), 2)
        def wl(a):
            w = sum(1 for t in a if t["won"]); return w, len(a)-w

        dw,dl = wl(daily); mw,ml = wl(monthly); tw,tl = wl(total)
        # Mutually exclusive: count trades whose final_tp == exactly this level
        tp_buckets = [sum(1 for t in total if t["final_tp"] == tp) for tp in range(1, 6)]

        return {
            "trade_number": self._counter,
            "daily":   {"wr": wr(daily),   "pnl": pnl(daily),   "wins": dw, "losses": dl},
            "monthly": {"wr": wr(monthly), "pnl": pnl(monthly), "wins": mw, "losses": ml},
            "total":   {"wr": wr(total),   "pnl": pnl(total),   "wins": tw, "losses": tl},
            "tp_buckets": tp_buckets,
            "sl_count": sum(1 for t in total if t["final_tp"] == 0),
        }

    def _save(self):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        try:
            with open(config.STATS_FILE, "w") as f:
                json.dump({"counter": self._counter, "trades": self._trades}, f, indent=2)
        except Exception as e: log.error(f"Stats save: {e}")

    def _load(self):
        if not os.path.exists(config.STATS_FILE): return
        try:
            with open(config.STATS_FILE) as f: p = json.load(f)
            self._counter = p.get("counter", 0)
            self._trades  = p.get("trades", [])
            log.info(f"Stats loaded — {self._counter} trades")
        except Exception as e: log.error(f"Stats load: {e}")
