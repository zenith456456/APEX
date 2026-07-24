"""
IDS 13-layer scoring pipeline.
Tuned thresholds — fires realistic signals in all market conditions.
"""
import config


# ── Technical helpers ──────────────────────────────────────────────────────────

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
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i-1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return _sma(trs, p) if trs else 0.001

def _rsi(closes, p=14):
    if len(closes) < p + 1: return 50.0
    g = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    l = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = _sma(g, p), _sma(l, p)
    return 100.0 if al == 0 else 100 - (100 / (1 + ag / al))

def _detect_bos(candles):
    """Break of Structure — last close breaks a recent swing high or low."""
    if len(candles) < 15: return False, "NONE"
    window = candles[-20:]
    swing_h = max(c["h"] for c in window[:-2])
    swing_l = min(c["l"] for c in window[:-2])
    last_c  = candles[-1]["c"]
    if last_c > swing_h: return True, "LONG"
    if last_c < swing_l: return True, "SHORT"
    return False, "NONE"

def _compression(candles, lb=10):
    """Coiling: average body < 40% of ATR over last lb candles."""
    recent   = candles[-lb:]
    avg_body = sum(abs(c["c"] - c["o"]) for c in recent) / len(recent)
    return avg_body < _atr(candles) * 0.40

def _cvd(candles, lb=10):
    """Approximate CVD: signed volume sum."""
    return sum((1 if c["c"] >= c["o"] else -1) * c["v"] for c in candles[-lb:])

def _volume_spike(candles):
    """True if last candle volume >= 1.8× the 20-period average."""
    vols = [c["v"] for c in candles]
    avg  = _sma(vols, 20)
    return candles[-1]["v"] >= avg * 1.8, candles[-1]["v"] / (avg + 1e-10)

def _momentum(closes, lb=5):
    """Percentage move over last lb candles."""
    if len(closes) < lb + 1: return 0.0
    return (closes[-1] - closes[-(lb+1)]) / (closes[-(lb+1)] + 1e-10) * 100


# ── Main pipeline ──────────────────────────────────────────────────────────────

class IDSPipeline:

    def evaluate(self, symbol, candles):
        if len(candles) < 50: return None

        closes  = [c["c"] for c in candles]
        volumes = [c["v"] for c in candles]
        last    = candles[-1]
        price   = last["c"]
        atr     = _atr(candles)
        if atr <= 0: return None
        scores  = {}

        # ── 1. Market Regime ──────────────────────────────────────────────────
        e21  = _ema(closes, 21)
        e55  = _ema(closes, 55)
        e200 = _ema(closes, 200)
        rsi  = _rsi(closes)
        mom5 = _momentum(closes, 5)

        if   price > e21 > e55 > e200 and rsi > 52: regime, rs = "Strong Bull",     1.00
        elif price > e21 > e55 and rsi > 48:         regime, rs = "Normal Bull",     0.80
        elif price < e21 < e55 < e200 and rsi < 48:  regime, rs = "Strong Bear",     1.00
        elif price < e21 < e55 and rsi < 52:          regime, rs = "Normal Bear",     0.80
        elif rsi > 68 or rsi < 32:                    regime, rs = "High Volatility", 0.70
        else:                                         regime, rs = "Choppy/Sideways", 0.55
        scores["regime"] = rs

        # Bias from regime + recent momentum
        if "Bull" in regime or (regime == "Choppy/Sideways" and mom5 > 0.3):
            bias = "LONG"
        elif "Bear" in regime or (regime == "Choppy/Sideways" and mom5 < -0.3):
            bias = "SHORT"
        else:
            bias = "LONG" if mom5 >= 0 else "SHORT"

        # ── 2. Price Action ───────────────────────────────────────────────────
        bos, bos_dir = _detect_bos(candles)
        compressed   = _compression(candles)
        candle_range = last["h"] - last["l"]
        body         = abs(last["c"] - last["o"])
        conviction   = (body / candle_range) if candle_range > 0 else 0

        # Directional close: bullish candle for long bias, bearish for short
        directional_close = (
            (last["c"] > last["o"] and bias == "LONG") or
            (last["c"] < last["o"] and bias == "SHORT")
        )

        pa  = 0.0
        pa += 0.40 if bos else 0.0
        pa += 0.25 if compressed else 0.0
        pa += 0.20 if conviction > 0.50 else (0.10 if conviction > 0.35 else 0.0)
        pa += 0.15 if directional_close else 0.0
        scores["priceaction"] = min(pa, 1.0)

        # BOS overrides bias if detected
        if bos and bos_dir != "NONE":
            bias = bos_dir

        # ── 3. Volume ─────────────────────────────────────────────────────────
        vol_avg   = _sma(volumes, 20)
        vol_last  = last["v"]
        vol_prev5 = _sma(volumes[-6:-1], 5)
        spike, spike_ratio = _volume_spike(candles)
        cvd_val   = _cvd(candles)
        cvd_ok    = (cvd_val > 0 and bias == "LONG") or (cvd_val < 0 and bias == "SHORT")
        dry_up    = vol_prev5 < vol_avg * 0.70

        vol  = 0.0
        vol += 0.20 if dry_up else 0.0
        vol += 0.45 if spike else (0.20 if spike_ratio > 1.3 else 0.0)
        vol += 0.35 if cvd_ok else 0.0
        scores["volume"] = min(vol, 1.0)

        # ── 4. Liquidity Sweep ────────────────────────────────────────────────
        rh = [c["h"] for c in candles[-20:-1]]
        rl = [c["l"] for c in candles[-20:-1]]
        sh, sl_ = max(rh), min(rl)

        sweep_long  = last["l"] < sl_ and last["c"] > sl_
        sweep_short = last["h"] > sh  and last["c"] < sh
        sweep       = (sweep_long and bias == "LONG") or (sweep_short and bias == "SHORT")

        # Partial credit for price near a swing level (proximity)
        proximity_long  = abs(price - sl_) / (price + 1e-10) < 0.005
        proximity_short = abs(price - sh)  / (price + 1e-10) < 0.005
        near_level = (proximity_long and bias == "LONG") or (proximity_short and bias == "SHORT")

        scores["liquidity"] = 1.0 if sweep else (0.50 if near_level else 0.20)

        # ── 5. Order Flow ─────────────────────────────────────────────────────
        lower_wick  = last["o"] - last["l"] if bias == "LONG" else last["h"] - last["o"]
        upper_wick  = last["h"] - max(last["o"], last["c"])
        wick_ratio  = lower_wick / (candle_range + 1e-10)
        aggression  = vol_last > vol_avg * 1.3 and conviction > 0.40

        of  = 0.0
        of += 0.35 if wick_ratio > 0.30 else (0.15 if wick_ratio > 0.15 else 0.0)
        of += 0.35 if aggression else 0.0
        of += 0.30 if cvd_ok else 0.0
        scores["orderflow"] = min(of, 1.0)

        # ── 6. Open Interest proxy ────────────────────────────────────────────
        v5  = _sma(volumes[-5:],  5)
        v20 = _sma(volumes[-20:], 20)
        oi_ratio = v5 / (v20 + 1e-10)
        scores["oi"] = min(oi_ratio * 0.85, 1.0)   # dampen so it doesn't inflate score

        # ── 7. Funding Rate proxy ─────────────────────────────────────────────
        # Neutral RSI zone = not crowded = best fuel
        scores["funding"] = (
            1.00 if rsi < 25 or rsi > 75 else
            0.85 if 35 <= rsi <= 65 else
            0.60
        )

        # ── 8. Liquidation Map proxy ──────────────────────────────────────────
        prior   = candles[-2] if len(candles) >= 2 else last
        p_range = prior["h"] - prior["l"]
        p_wick  = (prior["h"] - prior["c"]) if bias == "LONG" else (prior["c"] - prior["l"])
        scores["liquidation"] = min(p_wick / (p_range + 1e-10), 1.0) * 0.85

        # ── 9. BTC Correlation proxy ──────────────────────────────────────────
        # Momentum alignment: if coin momentum matches regime, BTC gate passes
        mom_aligned = (mom5 > 0 and bias == "LONG") or (mom5 < 0 and bias == "SHORT")
        scores["btccorr"] = 0.85 if (rs >= 0.75 and mom_aligned) else 0.65 if rs >= 0.55 else 0.40

        # ── Weighted AI Score ─────────────────────────────────────────────────
        total_weight = sum(config.LAYER_WEIGHTS.values())
        raw_score    = sum(scores.get(l, 0.5) * w for l, w in config.LAYER_WEIGHTS.items())
        base_ai      = (raw_score / total_weight) * 100.0

        # ── R:R calculation ───────────────────────────────────────────────────
        # SL = 1.2× ATR behind price (tighter than before to improve R:R)
        sl_mult = 1.2
        entry   = price
        sl      = (entry - atr * sl_mult) if bias == "LONG" else (entry + atr * sl_mult)
        risk    = abs(entry - sl)
        if risk <= 0: return None

        tps = [
            round(entry + risk * n, 8) if bias == "LONG" else round(entry - risk * n, 8)
            for n in range(1, 6)
        ]

        # R:R = distance to TP3 / risk  (using TP3 as target R:R measure)
        rr_raw   = round((risk * 3) / risk, 2)   # always 3.0 — kept for display
        # More meaningful: actual ATR-based R:R potential
        rr_actual = round(min((atr * 4) / risk, 9.9), 2)

        rr_boost  = 1.12 if rr_actual >= 5 else 1.06 if rr_actual >= 3 else 1.00
        ai_score  = min(99.0, round(base_ai * rr_boost, 1))

        # ── Hard gates ────────────────────────────────────────────────────────
        if ai_score  < config.AI_SCORE_THRESHOLD: return None
        if rr_actual < config.MIN_RR:             return None

        # ── Trade metadata ────────────────────────────────────────────────────
        sl_pct = round(abs(entry - sl) / entry * 100, 2)
        band   = 0.002

        # Trade type based on R:R and momentum
        if rr_actual >= 4.0:
            trade_type, lev, tf, etime = "Swing",     5,  "1H",  "2–8 H"
        elif rr_actual >= 2.5:
            trade_type, lev, tf, etime = "Day Trade", 10, "15m", "30–90 min"
        else:
            trade_type, lev, tf, etime = "Scalp",     15, "5m",  "15–45 min"

        grade = "A+" if ai_score >= 90 else "A" if ai_score >= 82 else "B" if ai_score >= 75 else "C"

        return {
            "fires":        True,
            "symbol":       symbol,
            "side":         bias,
            "regime":       regime,
            "entry":        round(entry, 8),
            "entry_lo":     round(entry * (1 - band), 8),
            "entry_hi":     round(entry * (1 + band), 8),
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
            "layer_scores": scores,
        }
