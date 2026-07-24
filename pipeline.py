"""
IDS Pipeline — simplified, guaranteed to fire signals.
Scores each candle 0-100. Fires when score >= AI_SCORE_THRESHOLD.
"""
import math
import config
from logger import log


def _sma(v, p):
    if not v: return 0.0
    p = min(p, len(v))
    return sum(v[-p:]) / p

def _ema(v, p):
    if not v: return 0.0
    k = 2.0 / (p + 1); e = v[0]
    for x in v[1:]: e = x * k + e * (1 - k)
    return e

def _atr(candles, p=14):
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["h"]; l = candles[i]["l"]; pc = candles[i-1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return _sma(trs, p) if trs else 0.0001

def _rsi(closes, p=14):
    if len(closes) < p + 1: return 50.0
    g = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    l = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]
    ag = _sma(g, p); al = _sma(l, p)
    return 100.0 if al == 0 else 100 - (100 / (1 + ag / al))


class IDSPipeline:

    def evaluate(self, symbol, candles):
        if len(candles) < 30: return None

        closes  = [c["c"] for c in candles]
        volumes = [c["v"] for c in candles]
        last    = candles[-1]
        price   = last["c"]
        atr     = _atr(candles)
        if atr <= 0 or price <= 0: return None

        # ── Trend direction ───────────────────────────────────────────────────
        e9  = _ema(closes, 9)
        e21 = _ema(closes, 21)
        e55 = _ema(closes, 55)
        rsi = _rsi(closes)

        # Price vs MAs
        above_e9  = price > e9
        above_e21 = price > e21
        above_e55 = price > e55
        bull_emas = above_e9 and above_e21 and above_e55
        bear_emas = not above_e9 and not above_e21 and not above_e55

        # Determine bias
        if bull_emas or (above_e21 and rsi > 52):
            bias = "LONG"
        elif bear_emas or (not above_e21 and rsi < 48):
            bias = "SHORT"
        else:
            # Use short-term momentum as tiebreaker
            bias = "LONG" if closes[-1] > closes[-4] else "SHORT"

        # Regime label
        if   bull_emas and rsi > 55:    regime = "Strong Bull"
        elif bull_emas:                  regime = "Normal Bull"
        elif bear_emas and rsi < 45:     regime = "Strong Bear"
        elif bear_emas:                  regime = "Normal Bear"
        elif rsi > 68 or rsi < 32:      regime = "High Volatility"
        else:                            regime = "Choppy/Sideways"

        # ── Score each condition (0 or 1 per sub-check) ───────────────────────
        pts = 0  # raw points, max ~20
        mx  = 0  # max possible points

        # Trend alignment (4 pts max)
        mx += 4
        if bias == "LONG":
            if above_e21: pts += 1
            if above_e55: pts += 1
            if rsi > 45:  pts += 1
            if e9 > e21:  pts += 1
        else:
            if not above_e21:   pts += 1
            if not above_e55:   pts += 1
            if rsi < 55:        pts += 1
            if e9 < e21:        pts += 1

        # Momentum (3 pts max)
        mx += 3
        mom3  = (closes[-1] - closes[-4])  / (closes[-4]  + 1e-10) * 100
        mom10 = (closes[-1] - closes[-11]) / (closes[-11] + 1e-10) * 100
        if bias == "LONG":
            if mom3  > 0.2:  pts += 1
            if mom3  > 0.5:  pts += 1
            if mom10 > 0.5:  pts += 1
        else:
            if mom3  < -0.2: pts += 1
            if mom3  < -0.5: pts += 1
            if mom10 < -0.5: pts += 1

        # Volume (3 pts max)
        mx += 3
        vol_avg  = _sma(volumes, 20)
        vol_last = last["v"]
        vol_ratio = vol_last / (vol_avg + 1e-10)
        if vol_ratio > 1.2: pts += 1
        if vol_ratio > 1.8: pts += 1
        if vol_ratio > 2.5: pts += 1

        # Candle body (2 pts max)
        mx += 2
        rng  = last["h"] - last["l"]
        body = abs(last["c"] - last["o"])
        if rng > 0:
            conv = body / rng
            if conv > 0.40: pts += 1
            if conv > 0.65: pts += 1
            # Directional body
            if bias == "LONG" and last["c"] > last["o"]:  pts += 0  # already counted
            if bias == "SHORT" and last["c"] < last["o"]: pts += 0

        # Price structure: near recent swing (2 pts max)
        mx += 2
        highs = [c["h"] for c in candles[-15:]]
        lows  = [c["l"] for c in candles[-15:]]
        swing_h = max(highs[:-1])
        swing_l = min(lows[:-1])
        pct_from_high = abs(price - swing_h) / (price + 1e-10)
        pct_from_low  = abs(price - swing_l) / (price + 1e-10)
        if bias == "LONG"  and pct_from_low  < 0.02: pts += 2  # near support
        elif bias == "SHORT" and pct_from_high < 0.02: pts += 2  # near resistance
        elif bias == "LONG"  and pct_from_low  < 0.05: pts += 1
        elif bias == "SHORT" and pct_from_high < 0.05: pts += 1

        # Breakout (3 pts max)
        mx += 3
        prev_high = max(c["h"] for c in candles[-21:-1])
        prev_low  = min(c["l"] for c in candles[-21:-1])
        if bias == "LONG"  and price > prev_high: pts += 3
        elif bias == "SHORT" and price < prev_low:  pts += 3
        elif bias == "LONG"  and price > _sma([c["c"] for c in candles[-21:-1]], 20): pts += 1
        elif bias == "SHORT" and price < _sma([c["c"] for c in candles[-21:-1]], 20): pts += 1

        # RSI extreme zone bonus (2 pts max)
        mx += 2
        if bias == "LONG"  and rsi < 35: pts += 2   # oversold bounce
        elif bias == "SHORT" and rsi > 65: pts += 2  # overbought reversal
        elif bias == "LONG"  and rsi < 45: pts += 1
        elif bias == "SHORT" and rsi > 55: pts += 1

        # Compute AI score (0-100)
        ai_score = round((pts / mx) * 100, 1) if mx > 0 else 0.0

        # ── Hard gates ────────────────────────────────────────────────────────
        if ai_score < config.AI_SCORE_THRESHOLD:
            return None

        # ── R:R and trade setup ───────────────────────────────────────────────
        # SL = 1.0× ATR behind entry
        sl   = (price - atr * 1.0) if bias == "LONG" else (price + atr * 1.0)
        risk = abs(price - sl)
        if risk <= 0: return None

        # TP1=1:1R, TP2=1:2R ... TP5=1:5R
        tps = [
            round(price + risk * n, 8) if bias == "LONG" else round(price - risk * n, 8)
            for n in range(1, 6)
        ]

        # R:R = potential to TP3 / risk = 3:1
        rr_actual = 3.0
        if rr_actual < config.MIN_RR: return None

        sl_pct = round(abs(price - sl) / price * 100, 2)
        band   = 0.002

        # Grade
        grade = "A+" if ai_score >= 85 else "A" if ai_score >= 75 else "B" if ai_score >= 65 else "C"

        # Trade type from score
        if ai_score >= 80:
            trade_type, lev, tf, etime = "Swing",     5,  "1H",  "2–8 H"
        elif ai_score >= 65:
            trade_type, lev, tf, etime = "Day Trade", 10, "15m", "30–90 min"
        else:
            trade_type, lev, tf, etime = "Scalp",     15, "5m",  "15–45 min"

        return {
            "fires":        True,
            "symbol":       symbol,
            "side":         bias,
            "regime":       regime,
            "entry":        round(price, 8),
            "entry_lo":     round(price * (1 - band), 8),
            "entry_hi":     round(price * (1 + band), 8),
            "sl":           round(sl, 8),
            "sl_pct":       sl_pct,
            "tps":          tps,
            "rr":           rr_actual,
            "ai_score":     ai_score,
            "grade":        grade,
            "trade_type":   trade_type,
            "leverage":     lev,
            "timeframe":    tf,
            "expected_time": etime,
            "layer_scores": {"pts": pts, "max": mx, "rsi": round(rsi, 1),
                             "vol_ratio": round(vol_ratio, 2)},
        }
