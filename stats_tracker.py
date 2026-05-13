import time
from typing import List, Dict
from collections import defaultdict
import datetime

class StatsTracker:
    def __init__(self):
        self.trades: List[Dict] = []  # closed signal records

    def load(self, trades: List[Dict]):
        self.trades = trades

    def get_daily_stats(self) -> Dict:
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        wins = losses = 0
        pnl = 0.0
        for t in self.trades:
            t_date = datetime.datetime.utcfromtimestamp(t["close_time"]).strftime("%Y-%m-%d")
            if t_date == today:
                if t["outcome"] == "TP":
                    wins += 1
                    pnl += t.get("pnl_r", 0)
                else:
                    losses += 1
                    pnl += t.get("pnl_r", 0)
        total = wins + losses
        wr = round(wins / total * 100, 2) if total else 0.0
        return {"wr": wr, "pnl": round(pnl, 2), "wins": wins, "losses": losses}

    def get_monthly_stats(self):
        now = datetime.datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0)
        wins = losses = 0
        pnl = 0.0
        for t in self.trades:
            t_dt = datetime.datetime.utcfromtimestamp(t["close_time"])
            if t_dt >= month_start:
                if t["outcome"] == "TP":
                    wins += 1
                    pnl += t.get("pnl_r", 0)
                else:
                    losses += 1
                    pnl += t.get("pnl_r", 0)
        total = wins + losses
        wr = round(wins / total * 100, 2) if total else 0.0
        return {"wr": wr, "pnl": round(pnl, 2), "wins": wins, "losses": losses}

    def get_alltime_stats(self):
        wins = sum(1 for t in self.trades if t["outcome"] == "TP")
        losses = sum(1 for t in self.trades if t["outcome"] != "TP")
        total = wins + losses
        pnl = sum(t.get("pnl_r", 0) for t in self.trades)
        wr = round(wins / total * 100, 2) if total else 0.0
        return {"wr": wr, "pnl": round(pnl, 2), "wins": wins, "losses": losses}

    def get_precision_histogram(self):
        """
        Counts of max TP hit (only counts highest hit for each signal).
        Returns dict: {1: n, 2: n, 3: n, ...}
        """
        hist = defaultdict(int)
        for t in self.trades:
            if t["outcome"] != "OVERRIDDEN_BY_FLIP":
                max_tp = t.get("max_tp_hit", 0)
                if max_tp > 0:
                    hist[max_tp] += 1
        return dict(hist)