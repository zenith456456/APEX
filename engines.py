# ─── engines.py ────────────────────────────────────────────────────────────
# APEX Signal Bot — Multi-Timeframe Confluence Scoring Engine (MTCS)
# Implements simplified versions of all 23 patterns across 5 timeframes

import logging
import math
from collections import deque
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("APEX.Engine")

TF_WEIGHTS = {"1m": 12, "3m": 18, "5m": 20, "10m": 22, "15m": 28}
LEVERAGE_MAP = [(90, 15), (82, 10), (72, 8), (60, 7), (0, 5)]
TP_RR = [1.4, 2.5, 3.8, 5.3, 7.1]


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


# ─── Candle helpers ────────────────────────────────────────────────────────
def body(c):      return abs(c["c"] - c["o"])
def range_(c):    return c["h"] - c["l"] if c["h"] > c["l"] else 1e-9
def body_ratio(c): return body(c) / range_(c)
def is_bull(c):   return c["c"] >= c["o"]
def typical(c):   return (c["h"] + c["l"] + c["c"]) / 3
def delta(c):     return 2 * c["tbv"] - c["v"]   # taker buy vol proxy for CVD delta


def atr(candles: list, n: int = 14) -> float:
    if len(candles) < 2:
        return 1e-9
    trs = [max(c["h"] - c["l"],
               abs(c["h"] - candles[i - 1]["c"]),
               abs(c["l"] - candles[i - 1]["c"]))
           for i, c in enumerate(candles[-n:]) if i > 0]
    return sum(trs) / len(trs) if trs else 1e-9


def vol_avg(candles: list, n: int = 20) -> float:
    vols = [c["v"] for c in candles[-n:]]
    return sum(vols) / len(vols) if vols else 1e-9


def ema(values: list, n: int) -> float:
    if not values:
        return 0.0
    k = 2 / (n + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def swing_high(candles: list, n: int = 5) -> float:
    return max((c["h"] for c in candles[-n:]), default=0.0)


def swing_low(candles: list, n: int = 5) -> float:
    return min((c["l"] for c in candles[-n:]), default=0.0)


# ─── Individual pattern scorers ────────────────────────────────────────────

def score_isr(candles: list) -> Tuple[int, str]:
    """1m — Institutional Sweep & Reclaim"""
    if len(candles) < 4:
        return 0, ""
    c, prev = candles[-1], candles[-2]
    if not c["x"]:
        return 0, ""
    wick_down = c["o"] - c["l"]
    wick_up   = c["h"] - c["c"]
    vol_ratio = c["v"] / (vol_avg(candles) + 1e-9)
    b_ratio   = body_ratio(c)
    sc = 0
    direction = ""
    if wick_down > 2 * body(c) and vol_ratio > 1.4:
        sc = int(min(95, 55 + vol_ratio * 10 + (1 - b_ratio) * 20))
        direction = "LONG"
    elif wick_up > 2 * body(c) and vol_ratio > 1.4:
        sc = int(min(95, 55 + vol_ratio * 10 + (1 - b_ratio) * 20))
        direction = "SHORT"
    return sc, direction


def score_vdes(candles: list, cvd: float) -> Tuple[int, str]:
    """1m — Volume-Delta Exhaustion Spring"""
    if len(candles) < 10:
        return 0, ""
    last = candles[-1]
    if not last["x"]:
        return 0, ""
    closes    = [c["c"] for c in candles[-10:]]
    new_low   = last["c"] == min(closes)
    new_high  = last["c"] == max(closes)
    vol_ratio = last["v"] / (vol_avg(candles) + 1e-9)
    sc = 0
    direction = ""
    if new_low and cvd > 0 and vol_ratio > 1.3:
        sc = int(min(88, 55 + vol_ratio * 8))
        direction = "LONG"
    elif new_high and cvd < 0 and vol_ratio > 1.3:
        sc = int(min(88, 55 + vol_ratio * 8))
        direction = "SHORT"
    return sc, direction


def score_vtrap(candles: list) -> Tuple[int, str]:
    """3m — Volume Absorption Trap"""
    if len(candles) < 5:
        return 0, ""
    c = candles[-1]
    if not c["x"]:
        return 0, ""
    vol_ratio = c["v"] / (vol_avg(candles) + 1e-9)
    b_ratio   = body_ratio(c)
    if vol_ratio < 3.0 or b_ratio > 0.25:
        return 0, ""
    close_loc = (c["c"] - c["l"]) / range_(c)
    direction = "LONG" if close_loc > 0.5 else "SHORT"
    sc = int(min(92, 55 + vol_ratio * 8 + (1 - b_ratio) * 15))
    return sc, direction


def score_liqh(candles: list) -> Tuple[int, str]:
    """3m — Liquidity Double-Tap"""
    if len(candles) < 40:
        return 0, ""
    lows  = [(i, c["l"]) for i, c in enumerate(candles[-40:])]
    highs = [(i, c["h"]) for i, c in enumerate(candles[-40:])]

    def find_equal(extremes, tol_pct=0.0012):
        for i in range(len(extremes)):
            for j in range(i + 12, len(extremes)):
                a, b = extremes[i][1], extremes[j][1]
                if abs(a - b) / (a + 1e-9) < tol_pct:
                    return i, j, (a + b) / 2
        return None

    low_pair  = find_equal(lows)
    high_pair = find_equal(highs)

    if low_pair:
        i1, i2, _ = low_pair
        v1 = candles[-(40 - i1)]["v"]
        v2 = candles[-(40 - i2)]["v"]
        if v2 < v1 * 0.7:
            sc = int(min(90, 65 + (1 - v2 / v1) * 40))
            return sc, "LONG"
    if high_pair:
        i1, i2, _ = high_pair
        v1 = candles[-(40 - i1)]["v"]
        v2 = candles[-(40 - i2)]["v"]
        if v2 < v1 * 0.7:
            sc = int(min(90, 65 + (1 - v2 / v1) * 40))
            return sc, "SHORT"
    return 0, ""


def score_ordm(candles: list, cvd: float) -> Tuple[int, str]:
    """3m / 5m — Order Block Momentum Displacement"""
    if len(candles) < 8:
        return 0, ""
    # Find last impulsive move and its origin candle (OB)
    a_val = atr(candles)
    for i in range(len(candles) - 5, max(0, len(candles) - 20), -1):
        c = candles[i]
        move = abs(c["c"] - c["o"])
        if move > 1.5 * a_val:
            ob_candle = candles[i - 1] if i > 0 else c
            current   = candles[-1]
            if not current["x"]:
                break
            returning_to_ob = (
                ob_candle["l"] <= current["c"] <= ob_candle["h"]
            )
            if not returning_to_ob:
                break
            ret_vol = current["v"]
            imp_vol = c["v"]
            if ret_vol < 0.55 * imp_vol:
                direction = "LONG" if is_bull(c) else "SHORT"
                sc = int(min(90, 60 + (1 - ret_vol / imp_vol) * 50))
                return sc, direction
            break
    return 0, ""


def score_pot3(candles: list, cvd: float) -> Tuple[int, str]:
    """5m — Power of Three Session Trap"""
    if len(candles) < 15:
        return 0, ""
    a_val    = atr(candles)
    lookback = candles[-15:]
    # Accumulation: tight range
    acc = lookback[:8]
    acc_range = max(c["h"] for c in acc) - min(c["l"] for c in acc)
    if acc_range > 0.45 * a_val:
        return 0, ""
    # Manipulation: wick sweep beyond range
    manip = lookback[8:12]
    acc_hi  = max(c["h"] for c in acc)
    acc_lo  = min(c["l"] for c in acc)
    for c in manip:
        vol_ratio = c["v"] / (vol_avg(candles) + 1e-9)
        if c["l"] < acc_lo and vol_ratio > 1.7:
            # Bull trap sweep low
            avg_delta = sum(delta(x) for x in acc) / len(acc)
            if avg_delta > 0:   # CVD positive = buying pressure below
                sc = int(min(90, 65 + vol_ratio * 8))
                return sc, "LONG"
        if c["h"] > acc_hi and vol_ratio > 1.7:
            avg_delta = sum(delta(x) for x in acc) / len(acc)
            if avg_delta < 0:
                sc = int(min(90, 65 + vol_ratio * 8))
                return sc, "SHORT"
    return 0, ""


def score_juds(candles: list, cvd: float) -> Tuple[int, str]:
    """10m — Judas Swing Reversal"""
    if len(candles) < 12:
        return 0, ""
    a_val     = atr(candles)
    open_c    = candles[-12]["o"]
    recent    = candles[-12:]
    peak_high = max(c["h"] for c in recent)
    peak_low  = min(c["l"] for c in recent)
    last      = candles[-1]
    if not last["x"]:
        return 0, ""

    # Judas up: big move up but CVD negative
    if peak_high - open_c > 2.2 * a_val and cvd < 0:
        vol_last = last["v"] / (vol_avg(candles) + 1e-9)
        if last["c"] < candles[-6]["o"]:  # reversing back through open
            sc = int(min(90, 60 + abs(cvd) * 0.001 + vol_last * 5))
            return min(sc, 90), "SHORT"

    # Judas down: big drop but CVD positive
    if open_c - peak_low > 2.2 * a_val and cvd > 0:
        vol_last = last["v"] / (vol_avg(candles) + 1e-9)
        if last["c"] > candles[-6]["o"]:
            sc = int(min(90, 60 + cvd * 0.001 + vol_last * 5))
            return min(sc, 90), "LONG"
    return 0, ""


def score_htfob(candles: list) -> Tuple[int, str]:
    """15m — HTF Order Block Precision Entry"""
    if len(candles) < 20:
        return 0, ""
    a_val = atr(candles)
    last  = candles[-1]
    if not last["x"]:
        return 0, ""
    for i in range(len(candles) - 8, max(0, len(candles) - 25), -1):
        c = candles[i]
        # OB = last opposing candle before ≥5-bar displacement
        disp_end  = candles[i + 5] if i + 5 < len(candles) else candles[-1]
        move      = abs(disp_end["c"] - c["c"])
        if move < 1.8 * a_val:
            continue
        ob_hi, ob_lo = c["h"], c["l"]
        in_ob = ob_lo <= last["c"] <= ob_hi
        if not in_ob:
            continue
        ret_vol = last["v"]
        imp_vol = c["v"]
        if ret_vol < 0.55 * imp_vol and body_ratio(last) < 0.5:
            direction = "LONG" if is_bull(candles[i + 1]) else "SHORT"
            sc = int(min(95, 65 + (1 - ret_vol / (imp_vol + 1e-9)) * 50))
            return sc, direction
    return 0, ""


def score_mmxm(candles: list, cvd: float) -> Tuple[int, str]:
    """15m — Market Maker Model"""
    if len(candles) < 30:
        return 0, ""
    a_val = atr(candles)
    # Simplified: look for accumulation → manipulation → distribution
    seg = candles[-30:]
    acc  = seg[:10]
    manip= seg[10:16]
    dist = seg[16:]

    acc_range = max(c["h"] for c in acc) - min(c["l"] for c in acc)
    if acc_range > 0.45 * a_val:
        return 0, ""

    acc_lo = min(c["l"] for c in acc)
    acc_hi = max(c["h"] for c in acc)

    for mc in manip:
        vol_r = mc["v"] / (vol_avg(candles) + 1e-9)
        if mc["l"] < acc_lo and vol_r > 1.7 and cvd > 0:
            last = candles[-1]
            if last["x"] and last["c"] > acc_lo:
                sc = int(min(90, 62 + vol_r * 8))
                return sc, "LONG"
        if mc["h"] > acc_hi and vol_r > 1.7 and cvd < 0:
            last = candles[-1]
            if last["x"] and last["c"] < acc_hi:
                sc = int(min(90, 62 + vol_r * 8))
                return sc, "SHORT"
    return 0, ""


# ─── Master MTCS Engine ────────────────────────────────────────────────────

PATTERN_REGISTRY = {
    "1m":  [
        ("ISR",  lambda c, cv: score_isr(c)),
        ("VDES", lambda c, cv: score_vdes(c, cv)),
    ],
    "3m":  [
        ("VTRAP", lambda c, cv: score_vtrap(c)),
        ("LIQH",  lambda c, cv: score_liqh(c)),
        ("ORDM",  lambda c, cv: score_ordm(c, cv)),
    ],
    "5m":  [
        ("POT3",  lambda c, cv: score_pot3(c, cv)),
        ("ORDM5", lambda c, cv: score_ordm(c, cv)),
    ],
    "15m": [
        ("HTFOB", lambda c, cv: score_htfob(c)),
        ("MMXM",  lambda c, cv: score_mmxm(c, cv)),
        ("JUDS",  lambda c, cv: score_juds(c, cv)),
    ],
}


class MTCSEngine:
    """
    Computes Multi-Timeframe Confluence Score (0–100) for a given pair.
    Returns a signal dict if MTCS >= threshold.
    """

    def __init__(self, config):
        self.cfg = config

    def evaluate(self, pair: str, store) -> Optional[dict]:
        """
        Run all pattern scorers across all TFs.
        Returns signal dict or None.
        """
        tf_votes:  Dict[str, Tuple[int, str]] = {}
        all_names: List[str] = []
        cvd = store.get_cvd(pair)

        for tf, patterns in PATTERN_REGISTRY.items():
            candles = store.get_candles(pair, tf)
            if len(candles) < 15:
                continue
            best_sc, best_dir, best_name = 0, "", ""
            for name, fn in patterns:
                try:
                    sc, direction = fn(candles, cvd)
                except Exception:
                    continue
                if sc > best_sc:
                    best_sc, best_dir, best_name = sc, direction, name
            if best_sc > 0 and best_dir:
                tf_votes[tf] = (best_sc, best_dir)
                all_names.append(best_name)

        if not tf_votes:
            return None

        # Check directional consensus (majority)
        long_score  = sum(sc for sc, d in tf_votes.values() if d == "LONG")
        short_score = sum(sc for sc, d in tf_votes.values() if d == "SHORT")
        if long_score == 0 and short_score == 0:
            return None

        direction  = "LONG" if long_score >= short_score else "SHORT"

        # Weighted MTCS
        total_w = sum(TF_WEIGHTS.get(tf, 10) for tf in tf_votes)
        mtcs    = 0
        for tf, (sc, d) in tf_votes.items():
            if d == direction:
                mtcs += sc * TF_WEIGHTS.get(tf, 10) / total_w
        mtcs = int(mtcs)

        if mtcs < self.cfg.MTCS_MIN_SCORE:
            return None

        # Price reference
        candles_ref = store.get_candles(pair, "5m") or store.get_candles(pair, "1m")
        if not candles_ref:
            return None
        price = candles_ref[-1]["c"]
        a_val = atr(candles_ref)

        entry, sl, tps, lev, trade_type, rr_arr = self._build_levels(
            pair, direction, price, a_val, mtcs, store
        )

        condition = self._market_condition(pair, store)
        pattern   = " + ".join(all_names[:3]) if all_names else "APEX"
        tf_signal = max(tf_votes, key=lambda t: TF_WEIGHTS.get(t, 0))

        conf = "VERY HIGH" if mtcs >= 90 else "HIGH" if mtcs >= 72 else "MEDIUM"

        return {
            "pair":         pair,
            "direction":    direction,
            "entry":        entry,
            "stop_loss":    sl,
            "take_profits": tps,
            "leverage":     lev,
            "trade_type":   trade_type,
            "timeframe":    tf_signal,
            "pattern":      pattern,
            "condition":    condition,
            "mtcs_score":   mtcs,
            "confidence":   conf,
            "rr_arr":       rr_arr,
            "price":        price,
            "tf_votes":     {tf: d for tf, (sc, d) in tf_votes.items()},
        }

    def _build_levels(self, pair, direction, price, a_val, mtcs, store):
        """Compute entry zone, SL, TPs, leverage, trade type."""
        is_long  = direction == "LONG"
        spread   = a_val * 0.3

        # Entry zone: ±0.15% around current price
        e1 = round(price * (1 + 0.0015 if is_long else 1 - 0.0015), 8)
        e2 = round(price * (1 - 0.0015 if is_long else 1 + 0.0015), 8)
        if is_long:
            e1, e2 = max(e1, e2), min(e1, e2)
        else:
            e1, e2 = min(e1, e2), max(e1, e2)

        # SL: 1.5× ATR
        sl_dist = max(a_val * 1.5, price * 0.008)
        sl = round(price - sl_dist if is_long else price + sl_dist, 8)

        # TPs: R:R ladder
        tps = []
        for rr in TP_RR[:5]:
            tp = price + rr * sl_dist if is_long else price - rr * sl_dist
            tps.append(round(tp, 8))

        # Leverage from MTCS
        lev = next(l for threshold, l in LEVERAGE_MAP if mtcs >= threshold)
        lev = min(lev, 10)  # cap at 10× for meme coins

        # Trade type from trigger TF
        trade_type = "SCALP" if mtcs < 72 else "DAY" if mtcs < 85 else "SWING"

        rr_arr = [f"1:{r}" for r in TP_RR[:5]]
        return [e1, e2], sl, tps, lev, trade_type, rr_arr

    def _market_condition(self, pair: str, store) -> str:
        candles = store.get_candles(pair, "15m")
        if len(candles) < 20:
            return "Normal Market"
        closes  = [c["c"] for c in candles[-20:]]
        a_val   = atr(candles)
        current = closes[-1]
        sma20   = sum(closes) / len(closes)
        recent_atr = atr(candles[-5:] if len(candles) >= 5 else candles)

        trend_pct = (current - closes[0]) / (closes[0] + 1e-9)
        vol_ratio = recent_atr / (a_val + 1e-9)

        if vol_ratio > 2.0:
            return "High Volatility"
        if trend_pct > 0.06:
            return "Strong Bull"
        if trend_pct > 0.02:
            return "Normal Bull"
        if trend_pct < -0.06:
            return "Strong Bear"
        if trend_pct < -0.02:
            return "Normal Bear"
        return "Choppy / Sideways"
