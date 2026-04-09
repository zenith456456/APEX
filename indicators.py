"""
APEX-EDS v4.0 | indicators.py
Pure technical indicator functions — no I/O, no state.
All functions operate on plain Python lists/deques.
"""

import math
import time
from collections import deque
from typing import Dict, List, Optional, Tuple


# ── HELPERS ───────────────────────────────────────────────────────────────

def closes(candles: deque) -> List[float]:
    return [c.c for c in candles if c.closed]

def highs(candles: deque) -> List[float]:
    return [c.h for c in candles if c.closed]

def lows(candles: deque) -> List[float]:
    return [c.l for c in candles if c.closed]

def volumes(candles: deque) -> List[float]:
    return [c.v for c in candles if c.closed]


# ── ATR ───────────────────────────────────────────────────────────────────

def atr(candles: deque, period: int = 14) -> float:
    bars = [c for c in candles if c.closed]
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        hl = bars[i].h - bars[i].l
        hc = abs(bars[i].h - bars[i-1].c)
        lc = abs(bars[i].l - bars[i-1].c)
        trs.append(max(hl, hc, lc))
    return sum(trs[-period:]) / period


# ── EMA ───────────────────────────────────────────────────────────────────

def ema(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    k   = 2.0 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


# ── RSI ───────────────────────────────────────────────────────────────────

def rsi(close_list: List[float], period: int = 14) -> float:
    if len(close_list) < period + 1:
        return 50.0
    deltas = [close_list[i] - close_list[i-1] for i in range(1, len(close_list))]
    gains  = [d if d > 0 else 0.0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0.0 for d in deltas[-period:]]
    ag = sum(gains) / period
    al = sum(losses) / period
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


# ── MACD ──────────────────────────────────────────────────────────────────

def macd(close_list: List[float]) -> Tuple[float, float, float]:
    """Returns (macd_line, signal_line, histogram) — last values."""
    if len(close_list) < 35:
        return 0.0, 0.0, 0.0
    e12 = ema(close_list, 12)
    e26 = ema(close_list, 26)
    if not e12 or not e26:
        return 0.0, 0.0, 0.0
    n     = min(len(e12), len(e26))
    mline = [e12[-n + i] - e26[-n + i] for i in range(n)]
    sig   = ema(mline, 9)
    if not sig:
        return 0.0, 0.0, 0.0
    m = mline[-1]
    s = sig[-1]
    return m, s, m - s


# ── BOLLINGER BANDS ───────────────────────────────────────────────────────

def bollinger(close_list: List[float], period: int = 20, std_dev: float = 2.0) -> Tuple[float, float, float]:
    """Returns (upper, mid, lower)."""
    if len(close_list) < period:
        p = close_list[-1] if close_list else 0
        return p, p, p
    window = close_list[-period:]
    mid    = sum(window) / period
    std    = math.sqrt(sum((x - mid) ** 2 for x in window) / period)
    return mid + std_dev * std, mid, mid - std_dev * std


# ── CVD (Cumulative Volume Delta) ─────────────────────────────────────────

def cvd(sym_data) -> float:
    """
    CVD normalised to [-1, +1].
    +1 = all buy volume, -1 = all sell volume.
    """
    trades = list(sym_data.agg_trades)
    if not trades:
        return 0.0
    bv = sum(t["p"] * t["q"] for t in trades if not t["m"])
    sv = sum(t["p"] * t["q"] for t in trades if t["m"])
    total = bv + sv
    if total == 0:
        return 0.0
    return (bv - sv) / total


# ── VPIN (simplified) ─────────────────────────────────────────────────────

def vpin(sym_data) -> float:
    """
    |E[buy_vol] - E[sell_vol]| / total_vol
    Range [0, 1] — higher = more informed (toxic) flow.
    """
    b = sym_data.buy_vol
    s = sym_data.sell_vol
    total = b + s
    if total == 0:
        return 0.0
    return abs(b - s) / total


# ── REGIME DETECTION ──────────────────────────────────────────────────────

def detect_regime(candles_5m: deque, lookback: int = 20) -> Tuple[str, float]:
    """
    Returns (regime_name, confidence [0-1]).
    regime_name: 'TREND_UP' | 'TREND_DOWN' | 'RANGE' | 'VOLATILE'
    """
    from config import REGIME_TREND_THRESH, REGIME_VOL_THRESH
    bars = [c for c in candles_5m if c.closed]
    if len(bars) < lookback:
        return "UNKNOWN", 0.0

    recent = bars[-lookback:]
    prices = [b.c for b in recent]
    hi     = max(b.h for b in recent)
    lo     = min(b.l for b in recent)

    if prices[0] == 0:
        return "UNKNOWN", 0.0

    rng   = (hi - lo) / prices[0]
    trend = (prices[-1] - prices[0]) / prices[0]

    if rng > REGIME_VOL_THRESH:
        return "VOLATILE", min(1.0, rng / 0.25)
    if trend > REGIME_TREND_THRESH:
        return "TREND_UP", min(1.0, trend / 0.15)
    if trend < -REGIME_TREND_THRESH:
        return "TREND_DOWN", min(1.0, abs(trend) / 0.15)
    return "RANGE", 1.0 - abs(trend) / REGIME_TREND_THRESH


# ── VPOC (Volume Point of Control) ────────────────────────────────────────

def vpoc(candles: deque) -> float:
    """Price level with highest cumulative volume."""
    bars = [c for c in candles if c.closed]
    if not bars:
        return 0.0
    pv: Dict[float, float] = {}
    for b in bars:
        key = round(b.c, 6)
        pv[key] = pv.get(key, 0) + b.v
    return max(pv, key=pv.get)


# ── SESSION QUALITY ───────────────────────────────────────────────────────

def session_quality() -> float:
    """
    Returns 0-1 quality multiplier based on UTC hour.
    Peak: EU/US overlap (08-12), active: Asia (00-04), low: dead zone (14-18).
    """
    h = time.gmtime().tm_hour
    if 8 <= h < 12:   return 1.00
    if 0 <= h < 4:    return 0.72
    if 12 <= h < 16:  return 0.62
    if 16 <= h < 20:  return 0.68
    return 0.48
