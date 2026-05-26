"""
indicators.py ─ APEX-QUANT 8-indicator engine
Pure numpy, no TA-Lib, no pandas.

FIX: VPI now defaults to 50 (neutral) instead of 0 when volume data is
flat/missing, preventing the |VPI|<threshold filter from always firing
on coins with low-variance volume (common on 1m candles).
"""
import numpy as np
from typing import Optional


def _s(arr) -> np.ndarray:
    a = np.asarray(arr, dtype=float)
    return np.where(np.isfinite(a), a, 0.0)


def _ema(series: np.ndarray, period: int) -> np.ndarray:
    k   = 2.0 / (period + 1)
    out = np.empty_like(series)
    out[0] = series[0]
    for i in range(1, len(series)):
        out[i] = series[i] * k + out[i - 1] * (1.0 - k)
    return out


def _rsi(closes: np.ndarray, period: int) -> float:
    if len(closes) < period + 1:
        return 50.0
    d  = np.diff(closes[-(period + 2):])
    ag = d[d > 0].mean() if (d > 0).any() else 0.0
    al = (-d[d < 0]).mean() if (d < 0).any() else 0.0
    return 100.0 if al == 0.0 else 100.0 - 100.0 / (1.0 + ag / al)


# ── 1. ARSI ───────────────────────────────────────────────────────

def calc_arsi(closes: np.ndarray, base: int = 14) -> dict:
    c = _s(closes)
    if len(c) < 22:
        return {"score": 50.0, "arsi": 50.0, "period": base}
    ret     = np.diff(c[-22:]) / np.maximum(c[-22:-1], 1e-10)
    sigma   = float(np.std(ret))
    mu      = float(np.mean(np.abs(ret)))
    v_ratio = sigma / mu if mu > 1e-10 else 1.0
    period  = int(np.clip(base * (1.0 + 0.5 * v_ratio), 5, 50))
    arsi    = _rsi(c, period)
    score   = float(np.clip((72.0 - arsi) / (72.0 - 28.0) * 100.0, 0.0, 100.0))
    return {"score": score, "arsi": round(arsi, 2), "period": period}


# ── 2. QMO ────────────────────────────────────────────────────────

def calc_qmo(closes: np.ndarray, n: int = 10) -> dict:
    c = _s(closes)
    if len(c) < n + 2:
        return {"score": 50.0, "qmo": 0.0}
    idx  = np.arange(n, dtype=float)
    w    = np.exp(-0.5 * ((idx - n / 2.0) / (n / 4.0)) ** 2)
    w   /= w.sum()
    mom  = np.array([(c[-1] - c[-1 - i]) / max(c[-1 - i], 1e-10)
                     for i in range(1, n + 1)])
    qmo  = float(np.dot(w, mom[::-1]) * 100.0)
    score = float(np.clip(50.0 + qmo * 15.0, 0.0, 100.0))
    return {"score": score, "qmo": round(qmo, 3)}


# ── 3. VPI ────────────────────────────────────────────────────────

def calc_vpi(opens: np.ndarray, closes: np.ndarray,
             volumes: np.ndarray, lb: int = 14) -> dict:
    """
    FIX: when total volume is near-zero return neutral score 50
    (not 0) so the VPI direction-match filter does not wrongly block signals.
    """
    o, c, v = _s(opens[-lb:]), _s(closes[-lb:]), _s(volumes[-lb:])
    total   = v.sum()
    if total < 1e-10:
        # No volume data → neutral, do not penalise
        return {"score": 50.0, "vpi": 0.0}
    vpi   = float((v[c > o].sum() - v[c < o].sum()) / total * 100.0)
    score = float(np.clip((vpi + 100.0) / 2.0, 0.0, 100.0))
    return {"score": score, "vpi": round(vpi, 2)}


# ── 4. VWAP-σ ─────────────────────────────────────────────────────

def calc_vwap(highs: np.ndarray, lows: np.ndarray,
              closes: np.ndarray, volumes: np.ndarray) -> dict:
    h, l, c, v = (_s(highs[-50:]), _s(lows[-50:]),
                  _s(closes[-50:]), _s(volumes[-50:]))
    tp      = (h + l + c) / 3.0
    cumvol  = np.maximum(np.cumsum(v), 1e-10)
    vwap    = float(np.cumsum(tp * v)[-1] / cumvol[-1])
    std     = float(np.std(tp))
    dev     = abs(float(c[-1]) - vwap) / std if std > 1e-10 else 0.0
    score   = float(np.clip((2.0 - dev) / 2.0 * 100.0, 0.0, 100.0))
    return {"score": score, "vwap": round(vwap, 6),
            "std": round(std, 6), "deviation": round(dev, 3)}


# ── 5. FDI ────────────────────────────────────────────────────────

def calc_fdi(closes: np.ndarray, period: int = 20) -> dict:
    c = _s(closes[-period:])
    if len(c) < 3:
        return {"score": 50.0, "fdi": 1.5}
    rng  = float(np.max(c) - np.min(c))
    path = float(np.sum(np.abs(np.diff(c))))
    if rng < 1e-10 or path < 1e-10:
        return {"score": 50.0, "fdi": 1.5}
    n   = len(c)
    fdi = float(np.clip(np.log(n) / np.log(n * rng / path), 1.0, 2.0))
    score = float(np.clip((2.0 - fdi) * 100.0, 0.0, 100.0))
    return {"score": score, "fdi": round(fdi, 4)}


# ── 6. ΔEMA Velocity ──────────────────────────────────────────────

def calc_ema_velocity(closes: np.ndarray, fast: int = 8, slow: int = 21) -> dict:
    c = _s(closes)
    if len(c) < slow + 2:
        return {"score": 50.0, "velocity": 0.0, "cross": 0.0}
    ef    = _ema(c, fast)
    es    = _ema(c, slow)
    cross = float(ef[-1] - es[-1])
    vel   = float((ef[-1] - ef[-2]) / max(c[-2], 1e-10))
    if abs(vel) < 1e-6:
        # Very slow — neutral score, don't hard-zero anymore
        return {"score": 45.0, "velocity": vel, "cross": cross}
    base  = 50.0 + (50.0 if cross > 0 else -50.0)
    boost = float(np.clip(abs(vel) / 0.002 * 30.0, 0.0, 30.0))
    score = float(np.clip(base + (boost if cross > 0 else -boost), 0.0, 100.0))
    return {"score": score, "velocity": round(vel, 6), "cross": round(cross, 6)}


# ── 7. MDD ────────────────────────────────────────────────────────

def calc_mdd(closes: np.ndarray, period: int = 10) -> dict:
    c = _s(closes[-period:])
    if len(c) < period:
        return {"score": 75.0, "divergence": False, "strength": 0.0}
    mom        = np.diff(c) / np.maximum(c[:-1], 1e-10)
    qmo_approx = np.convolve(mom, np.ones(3) / 3, "same")
    ps = float(np.polyfit(np.arange(len(c)), c, 1)[0])
    ms = float(np.polyfit(np.arange(len(qmo_approx)), qmo_approx, 1)[0])
    div      = np.sign(ps) != np.sign(ms) and abs(ps) > 1e-8
    strength = float(np.clip(abs(ps - ms) / (abs(ps) + 1e-10) * 50.0,
                             0.0, 50.0)) if div else 0.0
    score    = float(np.clip(100.0 - strength * 2.0, 0.0, 100.0))
    return {"score": score, "divergence": bool(div), "strength": round(strength, 2)}


# ── 8. ATR-Ψ ──────────────────────────────────────────────────────

def calc_atr_psi(highs: np.ndarray, lows: np.ndarray,
                 closes: np.ndarray, period: int = 14) -> dict:
    h, l, c = _s(highs), _s(lows), _s(closes)
    n = min(period + 1, len(c))
    if n < 3:
        return {"score": 50.0, "atr": 0.0, "psi": 1.0, "gate_open": True}
    prev = np.roll(c[-n:], 1); prev[0] = c[-n]
    tr   = np.maximum.reduce([
        h[-n:] - l[-n:],
        np.abs(h[-n:] - prev),
        np.abs(l[-n:] - prev),
    ])[1:]
    atr      = float(np.mean(tr[-period:]))
    atr_mean = float(np.mean(tr)) if len(tr) else atr
    psi      = float(atr / atr_mean) if atr_mean > 1e-10 else 1.0
    gate_open = 0.70 < psi < 2.20
    score     = 0.0 if not gate_open else float(
        np.clip(100.0 * np.exp(-0.5 * ((psi - 1.0) / 0.6) ** 2), 0.0, 100.0))
    return {"score": score, "atr": round(atr, 8),
            "psi": round(psi, 3), "gate_open": gate_open}


# ── CSS aggregator ────────────────────────────────────────────────

def compute_css(ind: dict, weights: dict) -> float:
    total, wsum = 0.0, 0.0
    for key, w in weights.items():
        s = ind.get(key, {}).get("score")
        if s is not None:
            total += w * float(s)
            wsum  += w
    return round(total / wsum, 2) if wsum > 0 else 0.0


def compute_atr(highs, lows, closes, period: int = 14) -> float:
    return calc_atr_psi(highs, lows, closes, period)["atr"]
