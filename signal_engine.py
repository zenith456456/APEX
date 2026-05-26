"""
signal_engine.py ─ APEX-QUANT signal construction pipeline
  1. Parse klines → numpy arrays
  2. Run all 8 indicators → CSS score
  3. Apply hard filters (with INFO-level logging on each rejection)
  4. Build full signal dict with all 11 required fields

FIX LOG: Every filter rejection is now logged at INFO so Northflank
         logs show exactly why a candle was rejected.
"""
import time
from datetime import datetime, timezone
from typing import Optional
import numpy as np
from config import cfg
from indicators import (calc_arsi, calc_qmo, calc_vpi, calc_vwap,
                        calc_fdi, calc_ema_velocity, calc_mdd,
                        calc_atr_psi, compute_css, compute_atr)
from logger_setup import get_logger

log = get_logger("signal")

MARKET_LABELS = {
    "STRONG_BULL": "🚀 STRONG BULL",
    "STRONG_BEAR": "🔻 STRONG BEAR",
    "HIGH_VOL":    "⚡ HIGH VOLATILITY",
    "CHOPPY":      "↔️ CHOPPY / SIDEWAYS",
    "NORMAL":      "⚖️ NORMAL MARKET",
}


def _parse(raw: list) -> Optional[tuple]:
    if not raw or len(raw) < 10:
        return None
    def col(i): return np.array([float(k[i]) for k in raw])
    return col(1), col(2), col(3), col(4), col(5)   # O H L C V


def _market(ind: dict) -> str:
    psi  = ind["atr_p"]["psi"]
    fdi  = ind["fdi"]["fdi"]
    arsi = ind["arsi"]["arsi"]
    if psi > 1.80:                return "HIGH_VOL"
    if fdi > 1.60:                return "CHOPPY"
    if fdi < 1.45 and arsi > 60: return "STRONG_BULL"
    if fdi < 1.45 and arsi < 40: return "STRONG_BEAR"
    return "NORMAL"


def _direction(ind: dict) -> str:
    votes = sum([
        ind["qmo"]["qmo"]      > 0,
        ind["vpi"]["vpi"]      > 0,
        ind["arsi"]["arsi"]    < 60,
        ind["ema_v"]["cross"]  > 0,
    ])
    return "LONG" if votes >= 2 else "SHORT"


def _dp(price: float) -> int:
    if price >= 1000: return 2
    if price >= 100:  return 3
    if price >= 1:    return 4
    if price >= 0.1:  return 5
    return 6


def _levels(direction: str, entry: float, atr: float) -> dict:
    dp = _dp(entry)
    r  = lambda x: round(x, dp)
    if direction == "LONG":
        el  = r(entry - atr * 0.15)
        eh  = r(entry + atr * 0.15)
        sl  = r(entry - atr * cfg.ATR_SL_MULT)
        tps = [r(entry + atr * m) for m in cfg.ATR_TP_MULTS]
    else:
        el  = r(entry - atr * 0.15)
        eh  = r(entry + atr * 0.15)
        sl  = r(entry + atr * cfg.ATR_SL_MULT)
        tps = [r(entry - atr * m) for m in cfg.ATR_TP_MULTS]
    risk = abs(entry - sl) or 1e-10
    rrs  = [f"1:{round(abs(tp - entry) / risk, 1)}" for tp in tps]
    return {"el": el, "eh": eh, "sl": sl, "tps": tps, "rrs": rrs, "atr": atr}


def _filter(pair: str, tf: str, ind: dict, css: float,
            levels: dict, direction: str) -> tuple[bool, str]:
    """
    7-layer hard filter.
    Every rejection is logged at INFO level so Northflank logs reveal why.
    """
    vpi  = ind["vpi"]["vpi"]
    fdi  = ind["fdi"]["fdi"]
    gate = ind["atr_p"]["gate_open"]
    psi  = ind["atr_p"]["psi"]
    divg = ind["mdd"]["divergence"]

    prefix = f"[FILTER] {pair} {tf} {direction}"

    # F01 — CSS minimum
    if css < cfg.MIN_CSS_SCORE:
        log.info(f"{prefix} REJECT CSS {css:.1f} < {cfg.MIN_CSS_SCORE}")
        return False, f"CSS {css:.1f} < {cfg.MIN_CSS_SCORE}"

    # F02 — ATR-Ψ gate
    if not gate:
        log.info(f"{prefix} REJECT ATR-Ψ gate closed Ψ={psi:.2f}")
        return False, f"ATR-Ψ gate closed (Ψ={psi:.2f})"

    # F03 — FDI regime
    if fdi > cfg.FDI_MAX:
        log.info(f"{prefix} REJECT FDI {fdi:.3f} > {cfg.FDI_MAX} (choppy)")
        return False, f"FDI {fdi:.3f} choppy"

    # F04 — VPI minimum magnitude
    if abs(vpi) < cfg.VPI_MIN_ABS:
        log.info(f"{prefix} REJECT |VPI| {abs(vpi):.1f} < {cfg.VPI_MIN_ABS}")
        return False, f"|VPI| {abs(vpi):.1f} < {cfg.VPI_MIN_ABS}"

    # F05 — VPI direction match
    if direction == "LONG" and vpi < 0:
        log.info(f"{prefix} REJECT VPI {vpi:.1f} bearish vs LONG")
        return False, f"VPI {vpi:.1f} bearish vs LONG"
    if direction == "SHORT" and vpi > 0:
        log.info(f"{prefix} REJECT VPI {vpi:.1f} bullish vs SHORT")
        return False, f"VPI {vpi:.1f} bullish vs SHORT"

    # F06 — Divergence block
    if divg:
        log.info(f"{prefix} REJECT hidden divergence (MDD)")
        return False, "Hidden divergence"

    # F07 — R:R minimum
    try:
        rr0 = float(levels["rrs"][0].split(":")[1])
    except (IndexError, ValueError):
        rr0 = 0.0
    if rr0 < cfg.MIN_RR:
        log.info(f"{prefix} REJECT R:R {levels['rrs'][0]} < {cfg.MIN_RR}")
        return False, f"R:R {levels['rrs'][0]} too low"

    return True, "All filters passed ✓"


def generate(pair: str, tf: str, klines: list, trade_no: int = 0) -> Optional[dict]:
    """
    Full signal pipeline. Returns signal dict or None if rejected.
    All filter rejections are logged at INFO level.
    """
    parsed = _parse(klines)
    if parsed is None:
        return None
    opens, highs, lows, closes, volumes = parsed

    # ── 8 indicators ──────────────────────────────────────────────
    ind = {
        "arsi":  calc_arsi(closes),
        "qmo":   calc_qmo(closes),
        "vpi":   calc_vpi(opens, closes, volumes),
        "vwap":  calc_vwap(highs, lows, closes, volumes),
        "fdi":   calc_fdi(closes),
        "ema_v": calc_ema_velocity(closes),
        "mdd":   calc_mdd(closes),
        "atr_p": calc_atr_psi(highs, lows, closes),
    }

    css       = compute_css(ind, cfg.CSS_WEIGHTS)
    direction = _direction(ind)
    market    = _market(ind)
    atr       = compute_atr(highs, lows, closes)

    # Log every candle evaluation at DEBUG (visible with LOG_LEVEL=DEBUG)
    log.debug(
        f"[EVAL] {pair} {tf} dir={direction} css={css:.1f} "
        f"vpi={ind['vpi']['vpi']:.1f} fdi={ind['fdi']['fdi']:.3f} "
        f"psi={ind['atr_p']['psi']:.2f} atr={atr:.6g}"
    )

    if atr == 0:
        log.debug(f"[EVAL] {pair} {tf} — ATR=0, skip")
        return None

    levels  = _levels(direction, float(closes[-1]), atr)
    ok, why = _filter(pair, tf, ind, css, levels, direction)
    if not ok:
        return None

    tt  = cfg.TRADE_TYPE_BY_TF.get(tf, "SCALP")
    lev = cfg.LEVERAGE_MAP.get(tt, 10)
    eta = cfg.EXPECTED_TIME.get(tf, "15–30 min")

    return {
        "id":           f"AQ-{int(time.time())}-{pair}-{tf}",
        "trade_no":     trade_no,
        "pair":         pair,
        "timeframe":    tf,
        "datetime":     datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "timestamp":    int(time.time()),
        "direction":    direction,
        "trade_type":   tt,
        "leverage":     lev,
        "entry_low":    levels["el"],
        "entry_high":   levels["eh"],
        "sl":           levels["sl"],
        "tps":          levels["tps"],
        "rrs":          levels["rrs"],
        "eta":          eta,
        "market":       market,
        "market_label": MARKET_LABELS.get(market, market),
        "css":          round(css, 1),
        "confidence":   round(min(css * 1.05, 99.9), 1),
        "atr":          round(atr, 8),
        "indicators": {
            "arsi": round(ind["arsi"]["arsi"], 1),
            "qmo":  round(ind["qmo"]["qmo"],   3),
            "vpi":  round(ind["vpi"]["vpi"],   1),
            "fdi":  round(ind["fdi"]["fdi"],   4),
            "psi":  round(ind["atr_p"]["psi"], 3),
        },
    }
