"""
APEX-EDS v4.0 | apex_engine.py
7-Layer Bayesian Scoring Engine.
"""
import logging
import time
from typing import Optional

import config
import indicators as ind
from models import Direction, MarketCondition, Regime, ScalpType, ScoreBreakdown, SignalResult

logger = logging.getLogger("APEXEngine")

_REGIME_MAP = {
    "TREND_UP":   Regime.TREND_UP,
    "TREND_DOWN": Regime.TREND_DOWN,
    "RANGE":      Regime.RANGE,
    "VOLATILE":   Regime.VOLATILE,
    "UNKNOWN":    Regime.UNKNOWN,
}


class APEXEngine:

    def score(self, sym_data) -> Optional[SignalResult]:
        # Gate 0: freshness + volume
        if time.time() - sym_data.updated_at > 120: return None
        if sym_data.volume_24h < config.MIN_VOLUME_USDT: return None
        if sym_data.last_price < config.MIN_PRICE_USDT:  return None

        c1m  = ind.closes(sym_data.candles["1m"])
        c5m  = ind.closes(sym_data.candles["5m"])
        c15m = ind.closes(sym_data.candles["15m"])
        if len(c5m) < 30: return None

        price = sym_data.last_price
        if price == 0: return None

        # Layer 1: CVD + VPIN
        cvd_val  = ind.cvd(sym_data)
        vpin_val = ind.vpin(sym_data)
        if vpin_val < config.VPIN_THRESHOLD: return None
        vol_score = min(100.0, abs(cvd_val)*60 + vpin_val*40)

        # Layer 2: Regime
        regime_name, regime_conf = ind.detect_regime(sym_data.candles["5m"])
        regime = _REGIME_MAP.get(regime_name, Regime.UNKNOWN)
        if regime in (Regime.RANGE, Regime.VOLATILE, Regime.UNKNOWN): return None
        direction = Direction.LONG if regime == Regime.TREND_UP else Direction.SHORT
        if direction == Direction.LONG  and cvd_val < -0.10: return None
        if direction == Direction.SHORT and cvd_val >  0.10: return None
        regime_score = regime_conf * 100

        # Layer 3: Structure / VPOC
        vpoc_val      = ind.vpoc(sym_data.candles["5m"])
        vpoc_dist     = abs(price - vpoc_val) / price if price else 0
        structure_score = min(100.0, vpoc_dist * 2000)

        # Layer 4: Momentum
        rsi_val              = ind.rsi(c5m)
        macd_line, sig_line, _ = ind.macd(c5m)
        if direction == Direction.LONG:
            rsi_ok = 45 < rsi_val < 72; macd_ok = macd_line > sig_line
        else:
            rsi_ok = 28 < rsi_val < 55; macd_ok = macd_line < sig_line
        momentum_score = (50.0 if rsi_ok else 0.0) + (50.0 if macd_ok else 0.0)

        # Layer 5: AI proxy
        if len(c15m) >= 10 and len(c1m) >= 10:
            t15 = (c15m[-1] - c15m[-10]) / (c15m[-10] or 1)
            t1  = (c1m[-1]  - c1m[-5])   / (c1m[-5]  or 1)
            raw = (t15 + t1) if direction == Direction.LONG else (-t15 - t1)
            ai_score = min(100.0, max(0.0, raw/0.02*50 + 50))
        else:
            ai_score = 50.0

        # Layer 6: Spread
        if sym_data.bid > 0 and sym_data.ask > 0:
            spread_score = max(0.0, 100.0 - (sym_data.ask-sym_data.bid)/sym_data.bid*100*1000)
        else:
            spread_score = 50.0

        # Layer 7: Session
        session_score = ind.session_quality() * 100

        # Composite
        total = (vol_score*config.WEIGHT_VOLUME + ai_score*config.WEIGHT_AI +
                 regime_score*config.WEIGHT_REGIME + structure_score*config.WEIGHT_STRUCTURE +
                 momentum_score*config.WEIGHT_MOMENTUM + spread_score*config.WEIGHT_SPREAD +
                 session_score*config.WEIGHT_SESSION)
        total = min(100.0, max(0.0, total))
        if total < config.MIN_SCORE: return None

        # Levels
        atr_val = ind.atr(sym_data.candles["5m"], config.ATR_PERIOD)
        if atr_val == 0: return None
        sl_d = atr_val * config.ATR_SL_MULT
        if sl_d == 0: return None

        if direction == Direction.LONG:
            entry_low, entry_high = price*0.9990, price*1.0005
            stop_loss = price - sl_d
            tp1, tp2, tp3 = price+atr_val*config.ATR_TP1_MULT, price+atr_val*config.ATR_TP2_MULT, price+atr_val*config.ATR_TP3_MULT
        else:
            entry_low, entry_high = price*0.9995, price*1.0010
            stop_loss = price + sl_d
            tp1, tp2, tp3 = price-atr_val*config.ATR_TP1_MULT, price-atr_val*config.ATR_TP2_MULT, price-atr_val*config.ATR_TP3_MULT

        rr = atr_val*config.ATR_TP1_MULT / sl_d
        if rr < config.MIN_RR: return None

        # Scalp type
        if len(c1m) >= 10:
            scalp_type, expected_hold = ScalpType.MICRO, "5 – 15 min"
        elif total >= 88 and len(c15m) >= 20:
            scalp_type, expected_hold = ScalpType.EXTENDED, "25 – 55 min"
        else:
            scalp_type, expected_hold = ScalpType.STANDARD, "12 – 35 min"

        leverage = config.LEVERAGE_APEX if total >= config.APEX_SCORE_TIER else config.LEVERAGE_DEFAULT

        p24 = sym_data.price_change_24h
        if p24 > 8:         mkt = MarketCondition.STRONG_BULL
        elif p24 > 2:       mkt = MarketCondition.BULL
        elif p24 < -8:      mkt = MarketCondition.STRONG_BEAR
        elif p24 < -2:      mkt = MarketCondition.BEAR
        elif vpin_val > 0.80: mkt = MarketCondition.HIGH_VOL
        else:               mkt = MarketCondition.NORMAL

        return SignalResult(
            symbol=sym_data.symbol, direction=direction, scalp_type=scalp_type,
            market_cond=mkt, regime=regime,
            entry_price=round(price,8), entry_low=round(entry_low,8), entry_high=round(entry_high,8),
            stop_loss=round(stop_loss,8), tp1=round(tp1,8), tp2=round(tp2,8), tp3=round(tp3,8),
            rr_ratio=round(rr,2), leverage=leverage, expected_hold=expected_hold,
            score=ScoreBreakdown(
                volume_score=round(vol_score,1), regime_score=round(regime_score,1),
                structure_score=round(structure_score,1), momentum_score=round(momentum_score,1),
                ai_score=round(ai_score,1), spread_score=round(spread_score,1),
                session_score=round(session_score,1), total=round(total,1),
            ),
            atr=round(atr_val,8), vpin=round(vpin_val,3), cvd=round(cvd_val,3),
        )
