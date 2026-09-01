from dataclasses import dataclass, field
from enum import Enum

class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"

@dataclass
class Market:
    symbol: str
    last: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    qvol: float = 0.0
    change_pct: float = 0.0
    buy_qty: float = 0.0
    sell_qty: float = 0.0
    bid_qty: float = 0.0
    ask_qty: float = 0.0
    oi: float = 0.0
    funding: float = 0.0
    klines: dict = field(default_factory=dict)
    updated: float = 0.0

@dataclass
class Score:
    market_regime: float
    price_action: float
    volume: float
    trend: float
    liquidity_sweep: float
    order_block_fvg: float
    order_flow: float
    open_interest: float
    funding: float
    btc_context: float
    news: float
    @property
    def total(self):
        return round(sum(self.__dict__.values()), 2)

@dataclass
class Signal:
    signal_id: str
    trade_number: int
    symbol: str
    direction: Direction
    trade_type: str
    market_condition: str
    signal_timeframe: str
    confirmation_timeframe: str
    higher_timeframe: str
    entry_low: float
    entry_high: float
    stop_loss: float
    take_profits: list
    leverage: int
    rr: float
    expected_holding: str
    entry_validity: str
    confidence: float
    reasons: list
    fingerprint: str
    created_at: str
    score: Score
