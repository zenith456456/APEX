import time
import math
from typing import Optional, Dict, List, Tuple
from collections import defaultdict
import numpy as np

class CSMDetector:
    def __init__(self, min_rr=3, max_rr=12, risk_per_trade=1.0):
        self.min_rr = min_rr
        self.max_rr = max_rr
        self.risk = risk_per_trade
        # Internal rolling window storage per symbol
        self.candles = defaultdict(list)  # list of {'timestamp','price'}

    def feed_price(self, symbol: str, price: float, timestamp: int):
        """
        Called on every ticker update. Builds 1-minute candles.
        """
        minute_timestamp = timestamp // 60000
        if self.candles[symbol]:
            last_candle = self.candles[symbol][-1]
            if last_candle['timestamp'] == minute_timestamp:
                # Update close price of current candle
                last_candle['price'] = price
                return
        self.candles[symbol].append({'timestamp': minute_timestamp, 'price': price})
        # Keep only last 200 candles
        if len(self.candles[symbol]) > 200:
            self.candles[symbol].pop(0)

    def generate_signal(self, symbol: str) -> Optional[Dict]:
        """
        Analyse recent price action and attempt to generate an Omega signal.
        Returns None, or a dict with all signal fields.
        """
        if len(self.candles[symbol]) < 20:
            return None
        prices = np.array([c['price'] for c in self.candles[symbol][-20:]])
        last_price = prices[-1]
        if last_price <= 0.0:
            return None

        # Simple volatility & momentum check
        log_ret = np.diff(np.log(prices))
        vol = np.std(log_ret[-20:]) * math.sqrt(20)  # annualized approx
        if vol < 0.005:   # too quiet
            return None

        # Example signal condition: sharp price drop + volume dummy (we'll use price change)
        # Real system would use order book, etc.
        change_pct = (prices[-1] / prices[-5] - 1) * 100  # 5-min change
        if change_pct < -0.8:   # bearish impulse
            direction = "SHORT"
            # Construct stops/targets based on ATR
            atr = self._calc_atr(prices, period=14)
            if atr <= 0:
                return None
            entry_high = last_price * 1.002
            entry_low = last_price * 0.998
            sl = entry_high + atr * 0.5
            risk = sl - entry_high
            if risk <= 0:
                return None
            tp1 = entry_high - risk * self.min_rr
            tp2 = entry_high - risk * ((self.min_rr + self.max_rr) / 2)
            tp3 = entry_high - risk * self.max_rr
            # Ensure targets are below entry
            tp1 = min(tp1, entry_low * 0.98)
            tp2 = min(tp2, entry_low * 0.96)
            tp3 = min(tp3, entry_low * 0.94)
        elif change_pct > 0.8:  # bullish impulse
            direction = "LONG"
            atr = self._calc_atr(prices, period=14)
            if atr <= 0:
                return None
            entry_high = last_price * 1.002
            entry_low = last_price * 0.998
            sl = entry_low - atr * 0.5
            risk = entry_low - sl
            tp1 = entry_low + risk * self.min_rr
            tp2 = entry_low + risk * ((self.min_rr + self.max_rr) / 2)
            tp3 = entry_low + risk * self.max_rr
            tp1 = max(tp1, entry_high * 1.02)
            tp2 = max(tp2, entry_high * 1.04)
            tp3 = max(tp3, entry_high * 1.06)
        else:
            return None

        # Build targets list
        targets = [
            {"price": tp1, "pct": 30},
            {"price": tp2, "pct": 30},
            {"price": tp3, "pct": 40}
        ]

        # Weighted avg RR
        weighted_rr = (self.min_rr * 0.3) + (((self.min_rr+self.max_rr)/2) * 0.3) + (self.max_rr * 0.4)

        # Determine trade type by expected duration
        # (very rough: based on ATR; assume 1-minute candles)
        expected_minutes = int(risk / (atr * last_price) * 10)
        if expected_minutes < 30:
            trade_type = "Scalp Trade"
        elif expected_minutes < 240:
            trade_type = "Day Trade"
        else:
            trade_type = "Swing Trade"

        signal = {
            "symbol": symbol,
            "direction": direction,
            "entry_min": entry_low,
            "entry_max": entry_high,
            "leverage": 10,  # fixed
            "targets": targets,
            "stop_loss": sl,
            "rr_weighted": round(weighted_rr, 2),
            "expected_time_min": expected_minutes,
            "market_condition": self._classify_market(vol, prices),
            "timestamp": time.time()
        }
        return signal

    def _calc_atr(self, prices, period=14):
        if len(prices) < period + 1:
            return 0
        high = np.maximum(prices[1:], prices[:-1])
        low = np.minimum(prices[1:], prices[:-1])
        tr = high - low
        return np.mean(tr[-period:])

    def _classify_market(self, vol, prices):
        if vol > 0.02:
            return "High Volatility"
        # Use simple trend classification
        short_ma = np.mean(prices[-5:])
        long_ma = np.mean(prices[-20:])
        if short_ma > long_ma * 1.02:
            return "Strong Bull"
        elif short_ma < long_ma * 0.98:
            return "Strong Bear"
        else:
            return "Choppy / Sideways"