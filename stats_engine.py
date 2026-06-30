# ─── stats_engine.py ───────────────────────────────────────────────────────
# APEX Signal Bot — Live Performance Statistics Engine
# Tracks WR / PNL / TP breakdown (mutually exclusive) per window

from datetime import datetime, timezone
from typing import Dict, List
from apex_signal_memory import SignalState


class StatsEngine:
    """Computes daily / monthly / all-time stats from SignalState list."""

    def snapshot(self, states: List[SignalState]) -> dict:
        now   = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")

        closed   = [s for s in states if s.is_closed]
        daily    = [s for s in closed if s.emit_date  == today]
        monthly  = [s for s in closed if s.emit_month == month]

        total_trades = len(closed)

        # TP breakdown — each signal counted once at highest TP
        tp_counts = {}
        for n in range(1, 6):
            tp_counts[f"TP{n}"] = sum(1 for s in closed if s.final_outcome == f"TP{n}")
        sl_count  = sum(1 for s in closed if s.final_outcome == "SL")
        win_count = sum(1 for s in closed if s.is_win)
        loss_count= sl_count

        return {
            "total": {
                "wr":     self._wr(closed),
                "pnl":    self._pnl(closed),
                "trades": total_trades,
                "wins":   win_count,
                "losses": loss_count,
            },
            "daily": {
                "wr":     self._wr(daily),
                "pnl":    self._pnl(daily),
                "trades": len(daily),
                "wins":   sum(1 for s in daily if s.is_win),
                "losses": sum(1 for s in daily if not s.is_win),
            },
            "monthly": {
                "wr":     self._wr(monthly),
                "pnl":    self._pnl(monthly),
                "trades": len(monthly),
                "wins":   sum(1 for s in monthly if s.is_win),
                "losses": sum(1 for s in monthly if not s.is_win),
            },
            "tp_counts":    tp_counts,
            "sl_count":     sl_count,
            "total_trades": total_trades,
            "trade_number": total_trades + 1,   # next trade number
        }

    @staticmethod
    def _wr(arr):
        if not arr:
            return 0.0
        return round(sum(1 for s in arr if s.is_win) / len(arr) * 100, 1)

    @staticmethod
    def _pnl(arr):
        return round(sum(s.pnl_pct for s in arr), 2)
