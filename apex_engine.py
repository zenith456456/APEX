# ============================================================
#  APEX-EDS v4.0  |  apex_engine.py
#  7-Layer Bayesian Scoring Engine
#  Layers: Volume, Regime, Structure, Momentum, AI-proxy,
#           Spread, Time-context → composite 0-100 score
# ============================================================

import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import config
from exchange_monitor import SymbolData, CandleBar

# ── ENUMS & DATA CLASSES ──────────────────────────────────────

class Regime(Enum):
    TREND_UP   = "TREND↑"
    TREND_DOWN = "TREND↓"
    RANGE      = "RANGE"
    VOLATILE   = "VOLATILE"
    UNKNOWN    = "UNKNOWN"

class Direction(Enum):
    LONG  = "LONG"
    SHORT = "SHORT"

class ScalpType(Enum):
    MICRO    = "1M MICRO"     # 1-min, hold 5-15 min
    STANDARD = "5M STANDARD"  # 5-min, hold 12-35 min
    EXTENDED = "15M EXTENDED" # 15-min, hold 25-55 min

class MarketCondition(Enum):
    STRONG_BULL = "STRONG BULL 🟢"
    BULL        = "BULL 📈"
    NORMAL      = "NORMAL 🔵"
    BEAR        = "BEAR 📉"
    STRONG_BEAR = "STRONG BEAR 🔴"
    CHOPPY      = "CHOPPY 🟡"
    HIGH_VOL    = "HIGH VOLATILITY ⚡"


@dataclass
class ScoreBreakdown:
    volume_score:    float = 0.0   # Layer 1: CVD + VPIN
    regime_score:    float = 0.0   # Layer 2: HMM regime
    structure_score: float = 0.0   # Layer 3: S/R + VPOC
    momentum_score:  float = 0.0   # Layer 4: RSI + MACD
    ai_score:        float = 0.0   # Layer 5: momentum proxy
    spread_score:    float = 0.0   # Layer 6: bid-ask quality
    time_score:      float = 0.0   # Layer 7: session
    total:           float = 0.0
    regime:          Regime = Regime.UNKNOWN
    direction:       Direction = Direction.LONG


@dataclass
class SignalResult:
    """Full signal package sent to Telegram/Discord."""
    symbol:          str
    direction:       Direction
    scalp_type:      ScalpType
    market_cond:     MarketCondition

    entry_price:     float
    entry_low:       float    # limit order zone low
    entry_high:      float    # limit order zone high
    stop_loss:       float
    tp1:             float
    tp2:             float
    tp3:             float

    rr_ratio:        float
    leverage:        int
    expected_hold:   str      # e.g. "12–35 min"

    score:           ScoreBreakdown
    atr:             float
    regime:          Regime
    vpin:            float
    cvd_divergence:  float    # normalised CVD delta

    timestamp:       float = field(default_factory=time.time)

    @property
    def rr_string(self) -> str:
        return f"1 : {self.rr_ratio:.1f}"

    @property
    def pair_display(self) -> str:
        return self.symbol.replace("USDT", "/USDT")


# ── TECHNICAL INDICATORS ─────────────────────────────────────

def _closes(candles: deque) -> List[float]:
    return [c.c for c in candles if c.closed]

def _highs(candles: deque) -> List[float]:
    return [c.h for c in candles if c.closed]

def _lows(candles: deque) -> List[float]:
    return [c.l for c in candles if c.closed]

def _volumes(candles: deque) -> List[float]:
    return [c.v for c in candles if c.closed]


def calc_atr(candles: deque, period: int = 14) -> float:
    bars = [c for c in candles if c.closed]
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        hl = bars[i].h - bars[i].l
        hc = abs(bars[i].h - bars[i-1].c)
        lc = abs(bars[i].l - bars[i-1].c)
        trs.append(max(hl, hc, lc))
    return sum(trs[-period:]) / period


def calc_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_g  = sum(gains) / period
    avg_l  = sum(losses) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - (100 / (1 + rs))


def calc_ema(values: List[float], period: int) -> List[float]:
    if not values or len(values) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def calc_macd(closes: List[float]) -> Tuple[float, float]:
    """Returns (macd_line, signal_line) — last values."""
    if len(closes) < 35:
        return 0.0, 0.0
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    if not ema12 or not ema26:
        return 0.0, 0.0
    # align lengths
    min_len = min(len(ema12), len(ema26))
    macd_line = [ema12[-min_len+i] - ema26[-min_len+i] for i in range(min_len)]
    signal = calc_ema(macd_line, 9)
    if not signal:
        return 0.0, 0.0
    return macd_line[-1], signal[-1]


def calc_cvd(sym_data: SymbolData) -> float:
    """
    Cumulative Volume Delta from agg_trades.
    Returns normalised divergence score [-1, +1].
    """
    trades = list(sym_data.agg_trades)
    if not trades:
        return 0.0
    buy_vol  = sum(t["p"] * t["q"] for t in trades if not t["m"])
    sell_vol = sum(t["p"] * t["q"] for t in trades if     t["m"])
    total    = buy_vol + sell_vol
    if total == 0:
        return 0.0
    return (buy_vol - sell_vol) / total   # [-1, +1]


def calc_vpin(sym_data: SymbolData) -> float:
    """
    Simplified VPIN: |E[buy_vol] - E[sell_vol]| / total_vol
    Returns [0, 1] — higher = more informed flow.
    """
    b = sym_data.buy_vol_accum
    s = sym_data.sell_vol_accum
    total = b + s
    if total == 0:
        return 0.0
    return abs(b - s) / total


def detect_regime(candles_5m: deque) -> Tuple[Regime, float]:
    """
    Returns (Regime, confidence [0-1]).
    Uses price trend + volatility over last 20 bars.
    """
    bars = [c for c in candles_5m if c.closed]
    if len(bars) < config.REGIME_LOOKBACK:
        return Regime.UNKNOWN, 0.0

    recent = bars[-config.REGIME_LOOKBACK:]
    prices = [b.c for b in recent]
    hi     = max(b.h for b in recent)
    lo     = min(b.l for b in recent)
    rng    = (hi - lo) / prices[0] if prices[0] else 0
    trend  = (prices[-1] - prices[0]) / prices[0] if prices[0] else 0

    if rng > config.REGIME_VOL_THRESH:
        return Regime.VOLATILE, min(1.0, rng / 0.25)
    if trend > config.REGIME_TREND_THRESH:
        conf = min(1.0, trend / 0.15)
        return Regime.TREND_UP, conf
    if trend < -config.REGIME_TREND_THRESH:
        conf = min(1.0, abs(trend) / 0.15)
        return Regime.TREND_DOWN, conf
    return Regime.RANGE, 1.0 - abs(trend) / config.REGIME_TREND_THRESH


def find_vpoc(candles: deque) -> float:
    """Volume Point of Control — price level with highest volume."""
    bars = [c for c in candles if c.closed]
    if not bars:
        return 0.0
    price_vol: Dict[int, float] = {}
    for b in bars:
        key = round(b.c, 4)
        price_vol[key] = price_vol.get(key, 0) + b.v
    return max(price_vol, key=price_vol.get)


def session_quality() -> float:
    """Return 0-1 quality score based on UTC hour (session overlaps)."""
    h = time.gmtime().tm_hour
    # Peak: 08-12 UTC (EU/US overlap), good: 00-04 (Asia), low: 14-18
    if 8 <= h < 12:
        return 1.0
    if 0 <= h < 4:
        return 0.7
    if 12 <= h < 16:
        return 0.6
    if 16 <= h < 20:
        return 0.65
    return 0.45


# ── MAIN SCORING ENGINE ───────────────────────────────────────

class APEXEngine:
    """
    Runs the 7-layer APEX score for a single symbol.
    Returns None if any hard gate fails.
    """

    def score(self, sym_data: SymbolData) -> Optional[SignalResult]:
        # ── Gate 0: data freshness ──────────────────────────
        if time.time() - sym_data.updated_at > 120:
            return None
        if sym_data.volume_24h < config.MIN_VOLUME_USDT:
            return None
        if sym_data.last_trade_price < config.MIN_PRICE_USDT:
            return None

        closes_1m  = _closes(sym_data.candles["1m"])
        closes_5m  = _closes(sym_data.candles["5m"])
        closes_15m = _closes(sym_data.candles["15m"])

        if len(closes_5m) < 30:
            return None

        # ── Layer 1: Volume (CVD + VPIN) ───────────────────
        cvd    = calc_cvd(sym_data)
        vpin   = calc_vpin(sym_data)
        if vpin < config.VPIN_THRESHOLD:
            return None   # no informed flow — skip

        vol_score = (abs(cvd) * 60 + vpin * 40)   # 0-100

        # ── Layer 2: Regime ────────────────────────────────
        regime, regime_conf = detect_regime(sym_data.candles["5m"])
        if regime in (Regime.RANGE, Regime.VOLATILE, Regime.UNKNOWN):
            return None   # hard gate — only trade trending markets
        regime_score = regime_conf * 100

        # Determine direction from regime
        direction = (Direction.LONG if regime == Regime.TREND_UP
                     else Direction.SHORT)
        # Validate CVD agrees with direction
        if direction == Direction.LONG  and cvd < -0.1:
            return None
        if direction == Direction.SHORT and cvd >  0.1:
            return None

        # ── Layer 3: Structure / VPOC ──────────────────────
        vpoc_5m  = find_vpoc(sym_data.candles["5m"])
        price    = sym_data.last_trade_price
        if price == 0:
            return None
        vpoc_dist = abs(price - vpoc_5m) / price   # fractional distance
        structure_score = min(100, vpoc_dist * 2000)  # reward distance

        # ── Layer 4: Momentum (RSI + MACD) ────────────────
        rsi = calc_rsi(closes_5m)
        macd_line, signal_line = calc_macd(closes_5m)

        if direction == Direction.LONG:
            rsi_ok  = 45 < rsi < 72
            macd_ok = macd_line > signal_line
        else:
            rsi_ok  = 28 < rsi < 55
            macd_ok = macd_line < signal_line

        momentum_score = 0.0
        if rsi_ok:    momentum_score += 50
        if macd_ok:   momentum_score += 50

        # ── Layer 5: AI proxy (multi-TF momentum) ─────────
        if len(closes_15m) >= 10 and len(closes_1m) >= 10:
            trend_15m = (closes_15m[-1] - closes_15m[-10]) / closes_15m[-10]
            trend_1m  = (closes_1m[-1]  - closes_1m[-5])  / closes_1m[-5]
            if direction == Direction.LONG:
                ai_score = min(100, max(0, (trend_15m + trend_1m) / 0.02 * 50 + 50))
            else:
                ai_score = min(100, max(0, (-trend_15m - trend_1m) / 0.02 * 50 + 50))
        else:
            ai_score = 50.0

        # ── Layer 6: Spread quality ────────────────────────
        if sym_data.bid > 0 and sym_data.ask > 0:
            spread_pct = (sym_data.ask - sym_data.bid) / sym_data.bid * 100
            spread_score = max(0, 100 - spread_pct * 1000)
        else:
            spread_score = 50.0

        # ── Layer 7: Session time quality ─────────────────
        time_score = session_quality() * 100

        # ── Weighted composite score ───────────────────────
        total = (
            vol_score       * config.WEIGHT_VOLUME   +
            ai_score        * config.WEIGHT_AI_PRED  +
            regime_score    * config.WEIGHT_REGIME   +
            structure_score * config.WEIGHT_STRUCTURE +
            momentum_score  * config.WEIGHT_MOMENTUM +
            spread_score    * config.WEIGHT_SPREAD   +
            time_score      * config.WEIGHT_TIME
        )
        total = min(100, max(0, total))

        if total < config.MIN_SCORE:
            return None   # score gate

        # ── ATR + SL / TP calculation ──────────────────────
        atr_5m = calc_atr(sym_data.candles["5m"])
        if atr_5m == 0:
            return None

        sl_dist  = atr_5m * config.ATR_SL_MULT
        tp1_dist = atr_5m * config.ATR_TP1_MULT
        tp2_dist = atr_5m * config.ATR_TP2_MULT
        tp3_dist = atr_5m * config.ATR_TP3_MULT

        if direction == Direction.LONG:
            entry      = price
            entry_low  = price * 0.9990   # 0.10% below for limit zone
            entry_high = price * 1.0005
            stop_loss  = entry - sl_dist
            tp1        = entry + tp1_dist
            tp2        = entry + tp2_dist
            tp3        = entry + tp3_dist
        else:
            entry      = price
            entry_low  = price * 0.9995
            entry_high = price * 1.0010
            stop_loss  = entry + sl_dist
            tp1        = entry - tp1_dist
            tp2        = entry - tp2_dist
            tp3        = entry - tp3_dist

        rr = tp1_dist / sl_dist

        if rr < config.MIN_RR:
            return None   # R:R hard gate

        # ── Scalp type classification ─────────────────────
        if len(closes_1m) >= 10:
            scalp_type = ScalpType.MICRO
            expected_hold = "5–15 min"
        elif len(closes_15m) >= 20 and total >= 88:
            scalp_type = ScalpType.EXTENDED
            expected_hold = "25–55 min"
        else:
            scalp_type = ScalpType.STANDARD
            expected_hold = "12–35 min"

        # ── Leverage selection ────────────────────────────
        if total >= config.APEX_SCORE_TIER:
            leverage = config.LEVERAGE_APEX
        elif regime in (Regime.RANGE, Regime.VOLATILE):
            leverage = config.LEVERAGE_CHOP
        else:
            leverage = config.LEVERAGE_DEFAULT

        # ── Market condition tag ──────────────────────────
        pct24 = sym_data.price_change_24h
        if pct24 > 8:
            mkt = MarketCondition.STRONG_BULL
        elif pct24 > 2:
            mkt = MarketCondition.BULL
        elif pct24 < -8:
            mkt = MarketCondition.STRONG_BEAR
        elif pct24 < -2:
            mkt = MarketCondition.BEAR
        elif vpin > 0.80:
            mkt = MarketCondition.HIGH_VOL
        else:
            mkt = MarketCondition.NORMAL

        score_bd = ScoreBreakdown(
            volume_score    = round(vol_score, 1),
            regime_score    = round(regime_score, 1),
            structure_score = round(structure_score, 1),
            momentum_score  = round(momentum_score, 1),
            ai_score        = round(ai_score, 1),
            spread_score    = round(spread_score, 1),
            time_score      = round(time_score, 1),
            total           = round(total, 1),
            regime          = regime,
            direction       = direction,
        )

        return SignalResult(
            symbol       = sym_data.symbol,
            direction    = direction,
            scalp_type   = scalp_type,
            market_cond  = mkt,
            entry_price  = round(entry, 8),
            entry_low    = round(entry_low, 8),
            entry_high   = round(entry_high, 8),
            stop_loss    = round(stop_loss, 8),
            tp1          = round(tp1, 8),
            tp2          = round(tp2, 8),
            tp3          = round(tp3, 8),
            rr_ratio     = round(rr, 2),
            leverage     = leverage,
            expected_hold = expected_hold,
            score        = score_bd,
            atr          = round(atr_5m, 8),
            regime       = regime,
            vpin         = round(vpin, 3),
            cvd_divergence = round(cvd, 3),
        )
