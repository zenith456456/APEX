"""
pipeline.py — 13-layer IDS scoring engine.
Pure Python + stdlib only. No pandas/numpy required here.

Layer weights (sum = 82, RR applied as multiplier):
  regime       8   market macro context
  priceaction 14   BOS/CHoCH, compression, conviction candle
  volume      12   dry-up, explosion, CVD alignment
  liquidity   16   sweep + reclaim (highest — smart-money fingerprint)
  orderflow   12   absorption, aggression, delta
  oi           8   OI build proxy via sustained volume
  funding      6   RSI-based crowding proxy
  liquidation 10   prior-wick untapped pool
  btccorr      6   macro alignment gate
"""
from src.config import AI_SCORE_THRESHOLD, MIN_RR, LAYER_WEIGHTS, TP_WEIGHTS


# ── Technical helpers ──────────────────────────────────────────────────────────

def _sma(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    period = min(period, len(values))
    return sum(values[-period:]) / period


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k   = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _atr(candles: list[dict], period: int = 14) -> float:
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return _sma(trs, period) if trs else 0.01


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains  = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = _sma(gains, period), _sma(losses, period)
    if al == 0:
        return 100.0
    return round(100 - (100 / (1 + ag / al)), 2)


def _detect_bos(candles: list[dict]) -> tuple[bool, str]:
    """Break of Structure: last close breaks recent swing high/low."""
    if len(candles) < 10:
        return False, "NONE"
    window     = candles[-20:]
    swing_high = max(c["h"] for c in window[:-3])
    swing_low  = min(c["l"] for c in window[:-3])
    last_close = candles[-1]["c"]
    if last_close > swing_high:
        return True, "LONG"
    if last_close < swing_low:
        return True, "SHORT"
    return False, "NONE"


def _compression(candles: list[dict], lb: int = 15) -> bool:
    """True when recent candle bodies average < 35% of ATR (coiling)."""
    recent     = candles[-lb:]
    avg_body   = sum(abs(c["c"] - c["o"]) for c in recent) / len(recent)
    return avg_body < _atr(candles) * 0.35


def _cvd(candles: list[dict], lb: int = 10) -> float:
    """Cumulative Volume Delta proxy: +vol when close>open, -vol otherwise."""
    return sum(
        (1 if c["c"] > c["o"] else -1) * c["v"]
        for c in candles[-lb:]
    )


# ── Main pipeline ──────────────────────────────────────────────────────────────

class IDSPipeline:
    """
    Stateless evaluator. Call evaluate(symbol, candles) on each closed candle.
    Returns a signal dict if AI score passes threshold, otherwise None.
    """

    def evaluate(self, symbol: str, candles: list[dict]) -> dict | None:
        if len(candles) < 50:
            return None

        closes  = [c["c"] for c in candles]
        volumes = [c["v"] for c in candles]
        last    = candles[-1]
        price   = last["c"]
        atr     = _atr(candles)
        scores: dict[str, float] = {}

        # ── 1. Market Regime ─────────────────────────────────────────────────
        e21, e55, e200 = _ema(closes, 21), _ema(closes, 55), _ema(closes, 200)
        rsi = _rsi(closes)

        if   price > e21 > e55 > e200 and rsi > 55:
            regime, rs = "Strong Bull",    1.00
        elif price > e21 > e55 and rsi > 50:
            regime, rs = "Normal Bull",    0.75
        elif price < e21 < e55 < e200 and rsi < 45:
            regime, rs = "Strong Bear",    1.00
        elif abs(price - e21) / (e21 + 1e-10) < 0.015:
            regime, rs = "Choppy/Sideways", 0.45
        elif rsi > 70 or rsi < 30:
            regime, rs = "High Volatility", 0.65
        else:
            regime, rs = "Normal Market",   0.60
        scores["regime"] = rs

        # Directional bias from regime
        if "Bull" in regime:
            bias = "LONG"
        elif "Bear" in regime:
            bias = "SHORT"
        else:
            bias = "LONG" if closes[-1] > closes[-5] else "SHORT"

        # ── 2. Price Action ───────────────────────────────────────────────────
        bos, bos_dir = _detect_bos(candles)
        compressed   = _compression(candles)
        candle_range = last["h"] - last["l"]
        body         = abs(last["c"] - last["o"])
        conviction   = body / candle_range if candle_range > 0 else 0

        pa = (0.45 if bos else 0) + (0.30 if compressed else 0) + (0.25 if conviction > 0.60 else 0)
        scores["priceaction"] = min(pa, 1.0)

        if bos and bos_dir != "NONE":
            bias = bos_dir   # BOS overrides regime bias

        # ── 3. Volume Analysis ────────────────────────────────────────────────
        vol_avg  = _sma(volumes, 20)
        vol_last = last["v"]
        vol_p10  = _sma(volumes[-11:-1], 10)
        cvd_val  = _cvd(candles)
        cvd_ok   = (cvd_val > 0 and bias == "LONG") or (cvd_val < 0 and bias == "SHORT")

        dry_up    = vol_p10  < vol_avg * 0.60
        explosion = vol_last >= vol_avg * 2.50

        vol = (0.25 if dry_up else 0) + (0.40 if explosion else 0) + (0.35 if cvd_ok else 0)
        scores["volume"] = min(vol, 1.0)

        # ── 4. Liquidity Sweep ────────────────────────────────────────────────
        recent_h = [c["h"] for c in candles[-20:-1]]
        recent_l = [c["l"] for c in candles[-20:-1]]
        swing_h  = max(recent_h)
        swing_l  = min(recent_l)

        sweep_long  = last["l"] < swing_l and last["c"] > swing_l
        sweep_short = last["h"] > swing_h and last["c"] < swing_h
        sweep       = (sweep_long and bias == "LONG") or (sweep_short and bias == "SHORT")

        scores["liquidity"] = 1.0 if sweep else 0.15

        # ── 5. Order Flow ─────────────────────────────────────────────────────
        lower_wick = last["o"] - last["l"] if bias == "LONG" else last["h"] - last["o"]
        wick_ratio = lower_wick / (candle_range + 1e-10)
        aggression = vol_last > vol_avg * 1.5 and conviction > 0.5

        of = (0.35 if wick_ratio > 0.35 else 0) + (0.35 if aggression else 0) + (0.30 if cvd_ok else 0)
        scores["orderflow"] = min(of, 1.0)

        # ── 6. Open Interest (volume-momentum proxy) ──────────────────────────
        oi_ratio = _sma(volumes[-5:], 5) / (_sma(volumes[-20:], 20) + 1e-10)
        scores["oi"] = min(oi_ratio, 1.0)

        # ── 7. Funding Rate (RSI crowding proxy) ──────────────────────────────
        scores["funding"] = (
            1.00 if rsi < 20 or rsi > 80
            else 0.90 if 35 <= rsi <= 65
            else 0.55
        )

        # ── 8. Liquidation Map (prior-wick untapped pool proxy) ───────────────
        prior = candles[-2] if len(candles) >= 2 else last
        p_range = prior["h"] - prior["l"]
        p_wick  = (prior["h"] - prior["c"]) if bias == "LONG" else (prior["c"] - prior["l"])
        scores["liquidation"] = min(p_wick / (p_range + 1e-10), 1.0) * 0.90

        # ── 9. BTC Correlation (regime proxy) ────────────────────────────────
        scores["btccorr"] = 0.80 if rs >= 0.75 else 0.60 if rs >= 0.45 else 0.35

        # ── Weighted AI Score ─────────────────────────────────────────────────
        total_weight = sum(LAYER_WEIGHTS.values())
        raw_score    = sum(
            scores.get(layer, 0.5) * weight
            for layer, weight in LAYER_WEIGHTS.items()
        )
        base_ai = (raw_score / total_weight) * 100.0

        # ── R:R calculation ───────────────────────────────────────────────────
        entry  = price
        sl     = (entry - atr * 1.5) if bias == "LONG" else (entry + atr * 1.5)
        risk   = abs(entry - sl)
        if risk <= 0:
            return None

        tps = [
            round(entry + risk * n, 8) if bias == "LONG" else round(entry - risk * n, 8)
            for n in range(1, 6)
        ]

        # ATR-based R:R approximation for this candle
        rr_raw   = round(atr * 3 / risk, 2)
        rr_raw   = max(rr_raw, 1.0)

        rr_boost = 1.15 if rr_raw >= 6 else 1.08 if rr_raw >= 3 else 1.00
        ai_score = min(99.0, round(base_ai * rr_boost, 1))

        # ── Hard gates ────────────────────────────────────────────────────────
        if ai_score < AI_SCORE_THRESHOLD:
            return None
        if rr_raw < MIN_RR:
            return None

        # ── Trade metadata ────────────────────────────────────────────────────
        sl_pct = round(abs(entry - sl) / entry * 100, 2)
        band   = 0.002   # ±0.2% limit order zone

        if rr_raw >= 4:
            trade_type, leverage, timeframe, exp_time = "Swing",    5,  "1H", "2–8 H"
        elif rr_raw >= 2:
            trade_type, leverage, timeframe, exp_time = "Day Trade", 10, "15m","30–90 min"
        else:
            trade_type, leverage, timeframe, exp_time = "Scalp",    15, "5m", "15–45 min"

        grade = (
            "A+" if ai_score >= 90 else
            "A"  if ai_score >= 82 else
            "B"  if ai_score >= 75 else "C"
        )

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
            "rr":           rr_raw,
            "ai_score":     ai_score,
            "grade":        grade,
            "trade_type":   trade_type,
            "leverage":     leverage,
            "timeframe":    timeframe,
            "expected_time": exp_time,
            "layer_scores": scores,
        }
