"""
APEX-EDS v4.0 | apex_engine.py
7-Layer Bayesian Scoring Engine.
Scores a SymbolData object and returns a SignalResult or None.
"""

import logging
import time
from typing import Optional

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


class APEXEngine:
    """
    Stateless scorer — call score() once per symbol per scan cycle.
    Returns SignalResult if all 7 layers pass, otherwise None.
    """

    def score(self, sym_data) -> Optional[SignalResult]:

        # ── Gate 0: Freshness + volume ──────────────────────────────────
        if time.time() - sym_data.updated_at > 120:
            return None
        if sym_data.volume_24h < config.MIN_VOLUME_USDT:
            return None
        if sym_data.last_price < config.MIN_PRICE_USDT:
            return None

        closes_1m  = ind.closes(sym_data.candles["1m"])
        closes_5m  = ind.closes(sym_data.candles["5m"])
        closes_15m = ind.closes(sym_data.candles["15m"])

        if len(closes_5m) < 30:
            return None

        price = sym_data.last_price
        if price == 0:
            return None

        # ── Layer 1: CVD + VPIN ──────────────────────────────────────────
        cvd_val  = ind.cvd(sym_data)
        vpin_val = ind.vpin(sym_data)

        if vpin_val < config.VPIN_THRESHOLD:
            return None   # no informed flow — hard gate

        vol_score = min(100.0, abs(cvd_val) * 60 + vpin_val * 40)

        # ── Layer 2: Regime detection ────────────────────────────────────
        regime_name, regime_conf = ind.detect_regime(sym_data.candles["5m"])
        regime = _REGIME_MAP.get(regime_name, Regime.UNKNOWN)

        if regime in (Regime.RANGE, Regime.VOLATILE, Regime.UNKNOWN):
            return None   # hard gate — only trade clear trends

        direction = Direction.LONG if regime == Regime.TREND_UP else Direction.SHORT

        # CVD must agree with direction
        if direction == Direction.LONG  and cvd_val < -0.10:
            return None
        if direction == Direction.SHORT and cvd_val >  0.10:
            return None

        regime_score = regime_conf * 100

        # ── Layer 3: Structure / VPOC ────────────────────────────────────
        vpoc_val = ind.vpoc(sym_data.candles["5m"])
        vpoc_dist = abs(price - vpoc_val) / price if price else 0
        structure_score = min(100.0, vpoc_dist * 2000)

        # ── Layer 4: Momentum (RSI + MACD) ──────────────────────────────
        rsi_val = ind.rsi(closes_5m)
        macd_line, signal_line, _ = ind.macd(closes_5m)

        if direction == Direction.LONG:
            rsi_ok  = 45 < rsi_val < 72
            macd_ok = macd_line > signal_line
        else:
            rsi_ok  = 28 < rsi_val < 55
            macd_ok = macd_line < signal_line

        momentum_score = (50.0 if rsi_ok else 0.0) + (50.0 if macd_ok else 0.0)

        # ── Layer 5: AI proxy (multi-TF momentum) ───────────────────────
        if len(closes_15m) >= 10 and len(closes_1m) >= 10:
            t15 = (closes_15m[-1] - closes_15m[-10]) / (closes_15m[-10] or 1)
            t1  = (closes_1m[-1]  - closes_1m[-5])  / (closes_1m[-5]  or 1)
            raw = (t15 + t1) if direction == Direction.LONG else (-t15 - t1)
            ai_score = min(100.0, max(0.0, raw / 0.02 * 50 + 50))
        else:
            ai_score = 50.0

        # ── Layer 6: Spread quality ──────────────────────────────────────
        if sym_data.bid > 0 and sym_data.ask > 0:
            spread_pct = (sym_data.ask - sym_data.bid) / sym_data.bid * 100
            spread_score = max(0.0, 100.0 - spread_pct * 1000)
        else:
            spread_score = 50.0

        # ── Layer 7: Session quality ─────────────────────────────────────
        session_score = ind.session_quality() * 100

        # ── Composite score ──────────────────────────────────────────────
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
            return None   # score gate

        # ── ATR + price levels ───────────────────────────────────────────
        atr_val = ind.atr(sym_data.candles["5m"], config.ATR_PERIOD)
        if atr_val == 0:
            return None

        sl_d  = atr_val * config.ATR_SL_MULT
        tp1_d = atr_val * config.ATR_TP1_MULT
        tp2_d = atr_val * config.ATR_TP2_MULT
        tp3_d = atr_val * config.ATR_TP3_MULT

        if direction == Direction.LONG:
            entry_low  = price * 0.9990
            entry_high = price * 1.0005
            stop_loss  = price - sl_d
            tp1        = price + tp1_d
            tp2        = price + tp2_d
            tp3        = price + tp3_d
        else:
            entry_low  = price * 0.9995
            entry_high = price * 1.0010
            stop_loss  = price + sl_d
            tp1        = price - tp1_d
            tp2        = price - tp2_d
            tp3        = price - tp3_d

        rr = tp1_d / sl_d if sl_d else 0
        if rr < config.MIN_RR:
            return None   # R:R hard gate

        # ── Scalp type ───────────────────────────────────────────────────
        if len(closes_1m) >= 10:
            scalp_type    = ScalpType.MICRO
            expected_hold = "5 – 15 min"
        elif total >= 88 and len(closes_15m) >= 20:
            scalp_type    = ScalpType.EXTENDED
            expected_hold = "25 – 55 min"
        else:
            scalp_type    = ScalpType.STANDARD
            expected_hold = "12 – 35 min"

        # ── Leverage ─────────────────────────────────────────────────────
        if total >= config.APEX_SCORE_TIER:
            leverage = config.LEVERAGE_APEX
        else:
            leverage = config.LEVERAGE_DEFAULT

        # ── Market condition ─────────────────────────────────────────────
        p24 = sym_data.price_change_24h
        if p24 > 8:
            mkt = MarketCondition.STRONG_BULL
        elif p24 > 2:
            mkt = MarketCondition.BULL
        elif p24 < -8:
            mkt = MarketCondition.STRONG_BEAR
        elif p24 < -2:
            mkt = MarketCondition.BEAR
        elif vpin_val > 0.80:
            mkt = MarketCondition.HIGH_VOL
        else:
            mkt = MarketCondition.NORMAL

        score_bd = ScoreBreakdown(
            volume_score    = round(vol_score,       1),
            regime_score    = round(regime_score,    1),
            structure_score = round(structure_score, 1),
            momentum_score  = round(momentum_score,  1),
            ai_score        = round(ai_score,        1),
            spread_score    = round(spread_score,    1),
            session_score   = round(session_score,   1),
            total           = round(total,           1),
        )

        return SignalResult(
            symbol        = sym_data.symbol,
            direction     = direction,
            scalp_type    = scalp_type,
            market_cond   = mkt,
            regime        = regime,
            entry_price   = round(price,       8),
            entry_low     = round(entry_low,   8),
            entry_high    = round(entry_high,  8),
            stop_loss     = round(stop_loss,   8),
            tp1           = round(tp1,         8),
            tp2           = round(tp2,         8),
            tp3           = round(tp3,         8),
            rr_ratio      = round(rr,          2),
            leverage      = leverage,
            expected_hold = expected_hold,
            score         = score_bd,
            atr           = round(atr_val,     8),
            vpin          = round(vpin_val,    3),
            cvd           = round(cvd_val,     3),
        )
