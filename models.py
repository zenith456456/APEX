"""
APEX-EDS v4.0 | models.py
Shared data classes and enums.
"""
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional


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
    MICRO    = "1M MICRO"
    STANDARD = "5M STANDARD"
    EXTENDED = "15M EXTENDED"


class MarketCondition(Enum):
    STRONG_BULL = "STRONG BULL"
    BULL        = "BULL"
    NORMAL      = "NORMAL"
    BEAR        = "BEAR"
    STRONG_BEAR = "STRONG BEAR"
    CHOPPY      = "CHOPPY"
    HIGH_VOL    = "HIGH VOLATILITY"


class TradeState(Enum):
    ACTIVE     = auto()
    TP1_HIT    = auto()
    TP2_HIT    = auto()
    ALL_TP_HIT = auto()
    SL_HIT     = auto()
    CLOSED     = auto()


@dataclass
class ScoreBreakdown:
    volume_score:    float = 0.0
    regime_score:    float = 0.0
    structure_score: float = 0.0
    momentum_score:  float = 0.0
    ai_score:        float = 0.0
    spread_score:    float = 0.0
    session_score:   float = 0.0
    total:           float = 0.0


@dataclass
class SignalResult:
    symbol:         str
    direction:      Direction
    scalp_type:     ScalpType
    market_cond:    MarketCondition
    regime:         Regime
    entry_price:    float
    entry_low:      float
    entry_high:     float
    stop_loss:      float
    tp1:            float
    tp2:            float
    tp3:            float
    rr_ratio:       float
    leverage:       int
    expected_hold:  str
    score:          ScoreBreakdown
    atr:            float
    vpin:           float
    cvd:            float
    timestamp:      float = field(default_factory=time.time)

    @property
    def pair_display(self) -> str:
        return self.symbol.replace("USDT", "/USDT")

    @property
    def rr_string(self) -> str:
        return f"1 : {self.rr_ratio:.1f}"


@dataclass
class RememberedSignal:
    symbol:           str
    direction:        Direction
    entry:            float
    stop_loss:        float
    tp1:              float
    tp2:              float
    tp3:              float
    sent_at:          float = field(default_factory=time.time)
    state:            TradeState = TradeState.ACTIVE
    tp1_reached:      bool = False
    tp2_reached:      bool = False
    tp3_reached:      bool = False
    sl_reached:       bool = False
    state_changed_at: float = field(default_factory=time.time)
    history:          List[str] = field(default_factory=list)

    @property
    def age_minutes(self) -> float:
        return (time.time() - self.sent_at) / 60
