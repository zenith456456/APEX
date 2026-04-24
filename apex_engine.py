"""
APEX-EDS v4.0 | apex_engine.py
7-Layer Bayesian Scoring Engine — with diagnostic logging.

Diagnostic mode: every scan cycle, logs the top 5 scoring pairs and
exactly which gate they fail on, so you can see why signals are blocked.
This makes future tuning straightforward.
"""
import logging
import time
from typing import Optional, Tuple

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

# How often to print diagnostic summary (every N scan cycles)
_DIAG_EVERY   = 5
_diag_counter = 0
_diag_results = []   # (symbol, score, fail_reason)


class APEXEngine:

    def score(self, sym_data) -> Optional[SignalResult]:
        """
        Score one symbol. Returns SignalResult if all gates pass, else None.
        Also records diagnostic info for the summary log.
        """
        sym = sym_data.symbol
        result, reason, total_score = self._score_internal(sym_data)

        # Store for diagnostics (keep top 10 by score regardless of pass/fail)
        _diag_results.append((sym, total_score, reason))

        return result

    def _score_internal(
        self, sym_data
    ) -> Tuple[Optional[SignalResult], str, float]:
        """
        Returns (SignalResult|None, fail_reason_str, composite_score).
        fail_reason is empty string on success.
        """
        sym = sym_data.symbol

        # ── Gate 0: Data freshness ────────────────────────────────────────
        age = time.time() - sym_data.updated_at
        if age > 120:
            return None, f"stale data ({age:.0f}s)", 0.0

        if sym_data.volume_24h < config.MIN_VOLUME_USDT:
            return None, f"low volume (${sym_data.volume_24h/1e6:.1f}M < ${config.MIN_VOLUME_USDT/1e6:.0f}M)", 0.0

        if sym_data.last_price < config.MIN_PRICE_USDT:
            return None, "price too low", 0.0

        c1m  = ind.closes(sym_data.candles["1m"])
        c5m  = ind.closes(sym_data.candles["5m"])
        c15m = ind.closes(sym_data.candles["15m"])

        if len(c5m) < 20:
            return None, f"not enough 5m candles ({len(c5m)}<20)", 0.0

        price = sym_data.last_price
        if price == 0:
            return None, "price=0", 0.0

        # ── Layer 1: CVD + VPIN ───────────────────────────────────────────
        cvd_val  = ind.cvd(sym_data)
        vpin_val = ind.vpin(sym_data)
        n_trades = len(sym_data.agg_trades)

        if vpin_val < config.VPIN_THRESHOLD:
            return None, (
                f"VPIN {vpin_val:.3f} < {config.VPIN_THRESHOLD} "
                f"(trades in deque: {n_trades}, "
                f"cvd={cvd_val:+.3f})"
            ), 0.0

        vol_score = min(100.0, abs(cvd_val) * 60 + vpin_val * 40)

        # ── Layer 2: Regime ───────────────────────────────────────────────
        regime_name, regime_conf = ind.detect_regime(sym_data.candles["5m"])
        regime = _REGIME_MAP.get(regime_name, Regime.UNKNOWN)

        if regime in (Regime.VOLATILE, Regime.UNKNOWN):
            return None, f"regime={regime_name} (blocked)", 0.0

        # Allow RANGE regime if other signals are very strong
        if regime == Regime.RANGE and vpin_val < 0.55:
            return None, f"regime=RANGE + weak VPIN ({vpin_val:.3f})", 0.0

        if regime == Regime.RANGE:
            # In range, direction is CVD-driven
            direction = Direction.LONG if cvd_val > 0 else Direction.SHORT
            regime_score = regime_conf * 50   # range gets half credit
        else:
            direction    = Direction.LONG if regime == Regime.TREND_UP else Direction.SHORT
            regime_score = regime_conf * 100

        # CVD must agree with direction
        if direction == Direction.LONG  and cvd_val < -0.15:
            return None, f"CVD disagrees with LONG direction (cvd={cvd_val:+.3f})", 0.0
        if direction == Direction.SHORT and cvd_val >  0.15:
            return None, f"CVD disagrees with SHORT direction (cvd={cvd_val:+.3f})", 0.0

        # ── Layer 3: Structure / VPOC ─────────────────────────────────────
        vpoc_val      = ind.vpoc(sym_data.candles["5m"])
        vpoc_dist     = abs(price - vpoc_val) / price if price else 0
        structure_score = min(100.0, vpoc_dist * 1500)

        # ── Layer 4: Momentum (RSI + MACD) ───────────────────────────────
        rsi_val             = ind.rsi(c5m)
        macd_line, sig_line, _ = ind.macd(c5m)

        if direction == Direction.LONG:
            rsi_ok  = 40 < rsi_val < 75
            macd_ok = macd_line > sig_line
        else:
            rsi_ok  = 25 < rsi_val < 60
            macd_ok = macd_line < sig_line

        momentum_score = (50.0 if rsi_ok else 15.0) + (50.0 if macd_ok else 15.0)

        # ── Layer 5: AI proxy (multi-TF momentum) ────────────────────────
        if len(c15m) >= 10 and len(c1m) >= 5:
            t15 = (c15m[-1] - c15m[-10]) / (c15m[-10] or 1)
            t1  = (c1m[-1]  - c1m[-3])   / (c1m[-3]  or 1)
            raw = (t15 + t1) if direction == Direction.LONG else (-t15 - t1)
            ai_score = min(100.0, max(0.0, raw / 0.015 * 50 + 50))
        else:
            ai_score = 50.0

        # ── Layer 6: Spread quality ───────────────────────────────────────
        if sym_data.bid > 0 and sym_data.ask > 0:
            spread_pct   = (sym_data.ask - sym_data.bid) / sym_data.bid * 100
            spread_score = max(0.0, 100.0 - spread_pct * 500)
        else:
            spread_score = 60.0   # assume OK if no book data yet

        # ── Layer 7: Session quality ──────────────────────────────────────
        session_score = ind.session_quality() * 100

        # ── Composite score ───────────────────────────────────────────────
        total = (
            vol_score       * config.WEIGHT_VOLUME    +
            ai_score        * config.WEIGHT_AI        +
            regime_score    * config.WEIGHT_REGIME    +
            structure_score * config.WEIGHT_STRUCTURE +
            momentum_score  * config.WEIGHT_MOMENTUM  +
            spread_score    * config.WEIGHT_SPREAD    +
            session_score   * config.WEIGHT_SESSION
        )
        total = min(100.0, max(0.0, total))

        if total < config.MIN_SCORE:
            breakdown = (
                f"vol={vol_score:.0f} ai={ai_score:.0f} "
                f"reg={regime_score:.0f} str={structure_score:.0f} "
                f"mom={momentum_score:.0f} spd={spread_score:.0f} "
                f"ses={session_score:.0f}"
            )
            return None, f"score {total:.1f} < {config.MIN_SCORE} ({breakdown})", total

        # ── ATR + price levels ────────────────────────────────────────────
        atr_val = ind.atr(sym_data.candles["5m"], config.ATR_PERIOD)
        if atr_val == 0:
            return None, "ATR=0", total

        sl_d = atr_val * config.ATR_SL_MULT
        if sl_d == 0:
            return None, "SL dist=0", total

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

        rr = atr_val * config.ATR_TP1_MULT / sl_d
        if rr < config.MIN_RR:
            return None, f"R:R {rr:.2f} < {config.MIN_RR}", total

        # ── Scalp type ────────────────────────────────────────────────────
        if len(c1m) >= 10:
            scalp_type, expected_hold = ScalpType.MICRO,    "5 – 15 min"
        elif total >= 80 and len(c15m) >= 20:
            scalp_type, expected_hold = ScalpType.EXTENDED, "25 – 55 min"
        else:
            scalp_type, expected_hold = ScalpType.STANDARD, "12 – 35 min"

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
        elif vpin_val > 0.70: mkt = MarketCondition.HIGH_VOL
        else:                mkt = MarketCondition.NORMAL

        result = SignalResult(
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
            expected_hold = expected_hold,
            score         = ScoreBreakdown(
                volume_score    = round(vol_score,       1),
                regime_score    = round(regime_score,    1),
                structure_score = round(structure_score, 1),
                momentum_score  = round(momentum_score,  1),
                ai_score        = round(ai_score,        1),
                spread_score    = round(spread_score,    1),
                session_score   = round(session_score,   1),
                total           = round(total,           1),
            ),
            atr  = round(atr_val,  8),
            vpin = round(vpin_val, 3),
            cvd  = round(cvd_val,  3),
        )
        return result, "", total


def log_diagnostic_summary():
    """
    Call at the end of each scan cycle to log why symbols are being blocked.
    Shows the top 8 symbols by score and their fail reasons.
    Helps tune thresholds without guessing.
    """
    global _diag_counter, _diag_results

    _diag_counter += 1
    if _diag_counter < _DIAG_EVERY:
        _diag_results = []
        return

    _diag_counter = 0
    if not _diag_results:
        _diag_results = []
        return

    # Sort by score descending, show top 8
    top = sorted(_diag_results, key=lambda x: x[1], reverse=True)[:8]

    lines = ["── Scan Diagnostic (top candidates) ──"]
    passed = 0
    for sym, sc, reason in top:
        if reason == "":
            lines.append(f"  ✅ {sym:<15} score={sc:.1f}  SIGNAL FIRED")
            passed += 1
        else:
            lines.append(f"  ❌ {sym:<15} score={sc:.1f}  blocked: {reason}")

    if passed == 0:
        lines.append("  → 0 signals in this window. Gates too strict or market ranging.")
    logger.info("\n".join(lines))

    _diag_results = []
