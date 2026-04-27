"""
APEX-EDS v4.0 | apex_engine.py
Rebuilt scoring engine based on diagnostic data.

Changes from previous version:
  - VPIN removed as hard gate (blocked liquid coins, passed illiquid ones)
  - CVD strength is now the primary directional gate
  - MIN_VOLUME_USDT $50M filters thin coins that caused 38 losses
  - Regime scoring reweighted — low confidence regime no longer kills score
  - Momentum (RSI+MACD) given more weight — most reliable with candle data
  - All weights recalibrated so score 68+ is achievable on quality setups
"""
import logging
import time
from typing import List, Optional, Tuple

import config
import indicators as ind
from models import (
    Direction, MarketCondition, Regime,
    ScalpType, ScoreBreakdown, SignalResult,
)

logger = logging.getLogger("APEXEngine")

_REGIME_MAP = {
    "TREND_UP":   Regime.TREND_UP,
    "TREND_DOWN": Regime.TREND_DOWN,
    "RANGE":      Regime.RANGE,
    "VOLATILE":   Regime.VOLATILE,
    "UNKNOWN":    Regime.UNKNOWN,
}

_DIAG_EVERY   = 5
_diag_counter = 0
_diag_results: list = []


class APEXEngine:

    def score(self, sym_data) -> Optional[SignalResult]:
        result, reason, total_score = self._score_internal(sym_data)
        _diag_results.append((sym_data.symbol, total_score, reason))
        return result

    def _score_internal(self, sym_data) -> Tuple[Optional[SignalResult], str, float]:

        # ── Gate 0: Data quality ──────────────────────────────────────────
        age = time.time() - sym_data.updated_at
        if age > 120:
            return None, f"stale ({age:.0f}s)", 0.0

        if sym_data.volume_24h < config.MIN_VOLUME_USDT:
            return None, f"low vol (${sym_data.volume_24h/1e6:.0f}M < ${config.MIN_VOLUME_USDT/1e6:.0f}M)", 0.0

        if sym_data.last_price < config.MIN_PRICE_USDT:
            return None, "price too low", 0.0

        c1m  = ind.closes(sym_data.candles["1m"])
        c5m  = ind.closes(sym_data.candles["5m"])
        c15m = ind.closes(sym_data.candles["15m"])

        if len(c5m) < 20:
            return None, f"need 20 5m candles (have {len(c5m)})", 0.0

        price = sym_data.last_price
        if price == 0:
            return None, "price=0", 0.0

        # ── Gate 1: CVD directional strength ─────────────────────────────
        # Primary filter. |CVD| > 0.35 means real one-sided flow.
        # This replaces VPIN as the main gate — CVD works on all market caps.
        n_trades = len(sym_data.agg_trades)
        cvd_val  = ind.cvd(sym_data)
        vpin_val = ind.vpin(sym_data)

        if n_trades < config.MIN_TRADES_IN_DEQUE:
            return None, f"need {config.MIN_TRADES_IN_DEQUE} trades (have {n_trades})", 0.0

        if abs(cvd_val) < config.CVD_MIN_STRENGTH:
            return None, (
                f"weak CVD {cvd_val:+.3f} (need |cvd|>{config.CVD_MIN_STRENGTH}) "
                f"VPIN={vpin_val:.3f} trades={n_trades}"
            ), 0.0

        # Direction is driven by CVD
        direction = Direction.LONG if cvd_val > 0 else Direction.SHORT

        # ── Gate 2: Regime — must not be VOLATILE or UNKNOWN ──────────────
        regime_name, regime_conf = ind.detect_regime(sym_data.candles["5m"])
        regime = _REGIME_MAP.get(regime_name, Regime.UNKNOWN)

        if regime == Regime.VOLATILE:
            return None, f"volatile market — skip", 0.0

        if regime == Regime.UNKNOWN:
            return None, f"insufficient candle data for regime", 0.0

        # Regime score: TREND gets full credit, RANGE gets partial
        if regime in (Regime.TREND_UP, Regime.TREND_DOWN):
            regime_score = regime_conf * 100
            # Regime direction should agree with CVD direction
            regime_dir = Direction.LONG if regime == Regime.TREND_UP else Direction.SHORT
            if regime_dir != direction:
                # CVD and regime disagree — take CVD direction but penalise
                regime_score *= 0.5
        else:
            # RANGE market — valid only if CVD is very strong
            regime_score = regime_conf * 40

        # ── Layer 3: CVD/VPIN momentum score ─────────────────────────────
        cvd_abs = abs(cvd_val)
        # CVD strength mapped to 0-100
        cvd_score  = min(100.0, (cvd_abs - config.CVD_MIN_STRENGTH) / (1.0 - config.CVD_MIN_STRENGTH) * 100)
        # VPIN adds bonus for informed flow confirmation (not gating)
        vpin_bonus = min(30.0, vpin_val * 60)
        cvd_momentum_score = min(100.0, cvd_score + vpin_bonus)

        # ── Layer 4: RSI + MACD momentum ─────────────────────────────────
        rsi_val             = ind.rsi(c5m)
        macd_line, sig_line, macd_hist = ind.macd(c5m)

        if direction == Direction.LONG:
            # RSI 45-75: not overbought, upward momentum
            rsi_score  = 100 if 45 < rsi_val < 75 else (
                         60  if 38 < rsi_val < 80 else 15)
            macd_score = 100 if (macd_line > sig_line and macd_hist > 0) else (
                         60  if  macd_line > sig_line else 15)
        else:
            # RSI 25-55: not oversold, downward momentum
            rsi_score  = 100 if 25 < rsi_val < 55 else (
                         60  if 20 < rsi_val < 62 else 15)
            macd_score = 100 if (macd_line < sig_line and macd_hist < 0) else (
                         60  if  macd_line < sig_line else 15)

        momentum_score = (rsi_score * 0.45 + macd_score * 0.55)

        # ── Layer 5: Multi-TF alignment ───────────────────────────────────
        multi_tf_score = 50.0   # neutral default
        if len(c15m) >= 10 and len(c1m) >= 5:
            # 15m trend direction
            t15 = (c15m[-1] - c15m[-10]) / (c15m[-10] or 1)
            # 1m recent momentum
            t1  = (c1m[-1]  - c1m[-3])   / (c1m[-3]  or 1)

            if direction == Direction.LONG:
                tf15_aligned = t15 > 0
                tf1_aligned  = t1  > 0
            else:
                tf15_aligned = t15 < 0
                tf1_aligned  = t1  < 0

            multi_tf_score = (
                100 if (tf15_aligned and tf1_aligned) else
                65  if (tf15_aligned or  tf1_aligned) else
                20
            )

        # ── Layer 6: Structure (VPOC distance) ───────────────────────────
        vpoc_val       = ind.vpoc(sym_data.candles["5m"])
        vpoc_dist      = abs(price - vpoc_val) / price if price else 0
        # Price far from VPOC = room to move toward TP
        structure_score = min(100.0, vpoc_dist * 2000)

        # ── Layer 7: Quality (spread + session) ──────────────────────────
        if sym_data.bid > 0 and sym_data.ask > 0:
            spread_pct   = (sym_data.ask - sym_data.bid) / sym_data.bid * 100
            spread_score = max(0.0, 100.0 - spread_pct * 500)
        else:
            spread_score = 65.0

        session_score = ind.session_quality() * 100
        quality_score = spread_score * 0.5 + session_score * 0.5

        # ── Composite ────────────────────────────────────────────────────
        total = (
            cvd_momentum_score * config.WEIGHT_CVD_MOMENTUM +
            regime_score       * config.WEIGHT_REGIME       +
            structure_score    * config.WEIGHT_STRUCTURE    +
            momentum_score     * config.WEIGHT_MOMENTUM     +
            multi_tf_score     * config.WEIGHT_MULTI_TF     +
            quality_score      * config.WEIGHT_QUALITY
        )
        total = min(100.0, max(0.0, total))

        if total < config.MIN_SCORE:
            return None, (
                f"score {total:.1f} < {config.MIN_SCORE} "
                f"(cvd_mom={cvd_momentum_score:.0f} reg={regime_score:.0f} "
                f"str={structure_score:.0f} mom={momentum_score:.0f} "
                f"mtf={multi_tf_score:.0f} qual={quality_score:.0f}) "
                f"CVD={cvd_val:+.3f} VPIN={vpin_val:.3f}"
            ), total

        # ── Price levels ──────────────────────────────────────────────────
        atr_val = ind.atr(sym_data.candles["5m"], config.ATR_PERIOD)
        if atr_val == 0:
            return None, "ATR=0", total

        sl_d = atr_val * config.ATR_SL_MULT
        if sl_d == 0:
            return None, "SL=0", total

        if direction == Direction.LONG:
            entry_low  = price * 0.9992
            entry_high = price * 1.0005
            stop_loss  = price - sl_d
            tp1        = price + atr_val * config.ATR_TP1_MULT
            tp2        = price + atr_val * config.ATR_TP2_MULT
            tp3        = price + atr_val * config.ATR_TP3_MULT
        else:
            entry_low  = price * 0.9995
            entry_high = price * 1.0008
            stop_loss  = price + sl_d
            tp1        = price - atr_val * config.ATR_TP1_MULT
            tp2        = price - atr_val * config.ATR_TP2_MULT
            tp3        = price - atr_val * config.ATR_TP3_MULT

        rr = (atr_val * config.ATR_TP1_MULT) / sl_d
        if rr < config.MIN_RR:
            return None, f"R:R {rr:.2f} < {config.MIN_RR}", total

        # ── Scalp type ────────────────────────────────────────────────────
        if len(c1m) >= 10:
            scalp_type, hold = ScalpType.MICRO,    "5 – 15 min"
        elif total >= 80 and len(c15m) >= 20:
            scalp_type, hold = ScalpType.EXTENDED, "25 – 55 min"
        else:
            scalp_type, hold = ScalpType.STANDARD, "12 – 35 min"

        leverage = (
            config.LEVERAGE_APEX if total >= config.APEX_SCORE_TIER
            else config.LEVERAGE_DEFAULT
        )

        # ── Market condition ──────────────────────────────────────────────
        p24 = sym_data.price_change_24h
        if p24 > 8:          mkt = MarketCondition.STRONG_BULL
        elif p24 > 2:        mkt = MarketCondition.BULL
        elif p24 < -8:       mkt = MarketCondition.STRONG_BEAR
        elif p24 < -2:       mkt = MarketCondition.BEAR
        elif vpin_val > 0.60: mkt = MarketCondition.HIGH_VOL
        else:                mkt = MarketCondition.NORMAL

        return SignalResult(
            symbol        = sym_data.symbol,
            direction     = direction,
            scalp_type    = scalp_type,
            market_cond   = mkt,
            regime        = regime,
            entry_price   = round(price,      8),
            entry_low     = round(entry_low,  8),
            entry_high    = round(entry_high, 8),
            stop_loss     = round(stop_loss,  8),
            tp1           = round(tp1,        8),
            tp2           = round(tp2,        8),
            tp3           = round(tp3,        8),
            rr_ratio      = round(rr,         2),
            leverage      = leverage,
            expected_hold = hold,
            score         = ScoreBreakdown(
                volume_score    = round(cvd_momentum_score, 1),
                regime_score    = round(regime_score,       1),
                structure_score = round(structure_score,    1),
                momentum_score  = round(momentum_score,     1),
                ai_score        = round(multi_tf_score,     1),
                spread_score    = round(spread_score,       1),
                session_score   = round(session_score,      1),
                total           = round(total,              1),
            ),
            atr  = round(atr_val,  8),
            vpin = round(vpin_val, 3),
            cvd  = round(cvd_val,  3),
        ), "", total


def log_diagnostic_summary():
    global _diag_counter, _diag_results
    _diag_counter += 1
    if _diag_counter < _DIAG_EVERY:
        _diag_results = []
        return
    _diag_counter = 0
    if not _diag_results:
        return

    top = sorted(_diag_results, key=lambda x: x[1], reverse=True)[:8]
    lines = ["── Scan Diagnostic ──"]
    passed = 0
    for sym, sc, reason in top:
        if reason == "":
            lines.append(f"  ✅ {sym:<15} score={sc:.1f}  SIGNAL FIRED")
            passed += 1
        else:
            lines.append(f"  ❌ {sym:<15} score={sc:.1f}  {reason}")
    if passed == 0:
        lines.append("  → 0 signals this window")
    logger.info("\n".join(lines))
    _diag_results = []
