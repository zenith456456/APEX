"""
APEX-EDS v4.0 | indicators.py
Pure technical indicators — no I/O, no state.
"""
import time
from collections import deque
from typing import Dict, List, Tuple


def closes(candles: deque) -> List[float]:
    return [c.c for c in candles if c.closed]

def atr(candles: deque, period: int = 14) -> float:
    bars = [c for c in candles if c.closed]
    if len(bars) < period + 1: return 0.0
    trs = [max(bars[i].h - bars[i].l,
               abs(bars[i].h - bars[i-1].c),
               abs(bars[i].l - bars[i-1].c))
           for i in range(1, len(bars))]
    return sum(trs[-period:]) / period

def ema(values: List[float], period: int) -> List[float]:
    if len(values) < period: return []
    k = 2.0 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out

def rsi(close_list: List[float], period: int = 14) -> float:
    if len(close_list) < period + 1: return 50.0
    deltas = [close_list[i] - close_list[i-1] for i in range(1, len(close_list))]
    gains  = [d if d > 0 else 0.0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0.0 for d in deltas[-period:]]
    ag, al = sum(gains)/period, sum(losses)/period
    if al == 0: return 100.0
    return 100.0 - 100.0 / (1.0 + ag/al)

def macd(close_list: List[float]) -> Tuple[float, float, float]:
    if len(close_list) < 35: return 0.0, 0.0, 0.0
    e12, e26 = ema(close_list, 12), ema(close_list, 26)
    if not e12 or not e26: return 0.0, 0.0, 0.0
    n = min(len(e12), len(e26))
    ml = [e12[-n+i] - e26[-n+i] for i in range(n)]
    sig = ema(ml, 9)
    if not sig: return 0.0, 0.0, 0.0
    return ml[-1], sig[-1], ml[-1] - sig[-1]

def cvd(sym_data) -> float:
    trades = list(sym_data.agg_trades)
    if not trades: return 0.0
    bv = sum(t["p"]*t["q"] for t in trades if not t["m"])
    sv = sum(t["p"]*t["q"] for t in trades if t["m"])
    total = bv + sv
    return (bv - sv) / total if total else 0.0

def vpin(sym_data) -> float:
    b, s = sym_data.buy_vol, sym_data.sell_vol
    total = b + s
    return abs(b - s) / total if total else 0.0

def detect_regime(candles_5m: deque, lookback: int = 20) -> Tuple[str, float]:
    from config import REGIME_TREND_THRESH, REGIME_VOL_THRESH
    bars = [c for c in candles_5m if c.closed]
    if len(bars) < lookback: return "UNKNOWN", 0.0
    recent = bars[-lookback:]
    prices = [b.c for b in recent]
    if prices[0] == 0: return "UNKNOWN", 0.0
    hi    = max(b.h for b in recent)
    lo    = min(b.l for b in recent)
    rng   = (hi - lo) / prices[0]
    trend = (prices[-1] - prices[0]) / prices[0]
    if rng > REGIME_VOL_THRESH:     return "VOLATILE",   min(1.0, rng/0.25)
    if trend > REGIME_TREND_THRESH:  return "TREND_UP",   min(1.0, trend/0.15)
    if trend < -REGIME_TREND_THRESH: return "TREND_DOWN", min(1.0, abs(trend)/0.15)
    return "RANGE", 1.0 - abs(trend)/REGIME_TREND_THRESH

def vpoc(candles: deque) -> float:
    bars = [c for c in candles if c.closed]
    if not bars: return 0.0
    pv: Dict[float, float] = {}
    for b in bars:
        k = round(b.c, 6)
        pv[k] = pv.get(k, 0) + b.v
    return max(pv, key=pv.get)

def session_quality() -> float:
    h = time.gmtime().tm_hour
    if 8 <= h < 12:  return 1.00
    if 0 <= h < 4:   return 0.72
    if 12 <= h < 16: return 0.62
    if 16 <= h < 20: return 0.68
    return 0.48
