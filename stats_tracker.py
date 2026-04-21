"""
APEX-EDS v4.0 | stats_tracker.py
Tracks all-time, daily, and monthly performance stats.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("StatsTracker")


def _date_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())

def _month_key() -> str:
    return time.strftime("%Y-%m", time.gmtime())


@dataclass
class TradeRecord:
    trade_num:  int
    symbol:     str
    direction:  str
    entry:      float
    rr_ratio:   float
    score:      float
    date_key:   str   = field(default_factory=_date_key)
    month_key:  str   = field(default_factory=_month_key)
    opened_at:  float = field(default_factory=time.time)
    closed:     bool  = False
    win:        Optional[bool] = None
    pnl_r:      float = 0.0


@dataclass
class PeriodStats:
    wins:   int   = 0
    losses: int   = 0
    pnl_r:  float = 0.0

    @property
    def total_closed(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        if self.total_closed == 0:
            return 0.0
        return self.wins / self.total_closed * 100


class StatsTracker:
    def __init__(self):
        self._trades: List[TradeRecord] = []
        self._total_wins:   int   = 0
        self._total_losses: int   = 0
        self._total_pnl_r:  float = 0.0
        self._daily:   Dict[str, PeriodStats] = {}
        self._monthly: Dict[str, PeriodStats] = {}

    def record_signal(self, symbol: str, direction: str,
                      entry: float, rr_ratio: float, score: float) -> int:
        trade_num = len(self._trades) + 1
        self._trades.append(TradeRecord(
            trade_num=trade_num, symbol=symbol, direction=direction,
            entry=entry, rr_ratio=rr_ratio, score=score,
        ))
        logger.info(f"Stats: #{trade_num} {symbol} {direction} RR={rr_ratio:.1f}")
        return trade_num

    def record_win(self, symbol: str, pnl_r: float):
        rec = self._find_open(symbol)
        if rec:
            rec.closed = True; rec.win = True; rec.pnl_r = pnl_r
            self._total_wins += 1; self._total_pnl_r += pnl_r
            self._add_period(rec.date_key, rec.month_key, True, pnl_r)
            logger.info(f"Stats WIN #{rec.trade_num} {symbol} +{pnl_r:.2f}R | AllWR={self.win_rate:.1f}%")

    def record_loss(self, symbol: str, pnl_r: float = -1.0):
        rec = self._find_open(symbol)
        if rec:
            rec.closed = True; rec.win = False; rec.pnl_r = pnl_r
            self._total_losses += 1; self._total_pnl_r += pnl_r
            self._add_period(rec.date_key, rec.month_key, False, pnl_r)
            logger.info(f"Stats LOSS #{rec.trade_num} {symbol} {pnl_r:.2f}R | AllWR={self.win_rate:.1f}%")

    @property
    def total_trades(self) -> int:   return len(self._trades)
    @property
    def wins(self) -> int:           return self._total_wins
    @property
    def losses(self) -> int:         return self._total_losses
    @property
    def win_rate(self) -> float:
        c = self._total_wins + self._total_losses
        return (self._total_wins / c * 100) if c else 0.0
    @property
    def total_pnl_r(self) -> float:  return self._total_pnl_r
    @property
    def has_closed_trades(self) -> bool:
        return (self._total_wins + self._total_losses) > 0

    # Daily
    @property
    def daily_stats(self) -> PeriodStats:
        return self._daily.get(_date_key(), PeriodStats())
    @property
    def monthly_stats(self) -> PeriodStats:
        return self._monthly.get(_month_key(), PeriodStats())

    def snapshot(self, trade_num: int) -> dict:
        dk  = _date_key()
        mk  = _month_key()
        ds  = self._daily.get(dk, PeriodStats())
        ms  = self._monthly.get(mk, PeriodStats())
        std = sum(1 for t in self._trades if t.date_key  == dk)
        stm = sum(1 for t in self._trades if t.month_key == mk)
        return {
            "trade_num":        trade_num,
            "total_trades":     trade_num,
            # all-time
            "wins":             self._total_wins,
            "losses":           self._total_losses,
            "win_rate":         self.win_rate,
            "total_pnl_r":      self._total_pnl_r,
            "has_history":      self.has_closed_trades,
            # daily
            "daily_wins":       ds.wins,
            "daily_losses":     ds.losses,
            "daily_win_rate":   ds.win_rate,
            "daily_pnl_r":      ds.pnl_r,
            "daily_has_data":   ds.total_closed > 0,
            "sigs_today":       std,
            "today_key":        dk,
            # monthly
            "monthly_wins":     ms.wins,
            "monthly_losses":   ms.losses,
            "monthly_win_rate": ms.win_rate,
            "monthly_pnl_r":    ms.pnl_r,
            "monthly_has_data": ms.total_closed > 0,
            "sigs_month":       stm,
            "month_key":        mk,
        }

    def _find_open(self, symbol: str) -> Optional[TradeRecord]:
        for rec in reversed(self._trades):
            if rec.symbol == symbol and not rec.closed:
                return rec
        return None

    def _add_period(self, dk: str, mk: str, win: bool, pnl: float):
        if dk not in self._daily:   self._daily[dk]   = PeriodStats()
        if mk not in self._monthly: self._monthly[mk] = PeriodStats()
        for ps in (self._daily[dk], self._monthly[mk]):
            if win: ps.wins   += 1
            else:   ps.losses += 1
            ps.pnl_r += pnl
