import json
import time
from typing import Dict, Optional, List
from collections import defaultdict

class StateManager:
    def __init__(self):
        # In-memory store of active signals per symbol
        self.active_signals = {}   # symbol -> signal dict
        self.trade_counter = 0     # Global trade ID
        # closed signals log for stats
        self.closed_signals = []

    async def load_history(self):
        # Optionally load from disk
        try:
            with open("trade_log.json", "r") as f:
                data = json.load(f)
                self.closed_signals = data.get("closed", [])
                self.trade_counter = data.get("counter", 0)
        except FileNotFoundError:
            pass

    async def save_history(self):
        with open("trade_log.json", "w") as f:
            json.dump({"closed": self.closed_signals, "counter": self.trade_counter}, f)

    def get_active_signal(self, symbol: str) -> Optional[Dict]:
        return self.active_signals.get(symbol)

    def set_active_signal(self, symbol: str, signal: Dict):
        signal["trade_id"] = self.trade_counter = self.trade_counter + 1
        signal["status"] = "OPEN"
        signal["max_tp_hit"] = 0  # 0 = none hit yet
        signal["tp_hit_flags"] = [False] * len(signal["targets"])
        signal["sl_hit"] = False
        signal["time_opened"] = time.time()
        self.active_signals[symbol] = signal

    def update_price(self, symbol: str, price: float) -> Optional[str]:
        """
        Check TP/SL hits for an active signal.
        Returns 'TP', 'SL', 'CLOSED' if all TPs hit, or None if still open.
        """
        if symbol not in self.active_signals:
            return None
        sig = self.active_signals[symbol]
        direction = sig["direction"]
        sl_price = sig["stop_loss"]
        targets = sig["targets"]

        # Check SL
        if direction == "SHORT" and price >= sl_price:
            sig["sl_hit"] = True
            return "SL"
        elif direction == "LONG" and price <= sl_price:
            sig["sl_hit"] = True
            return "SL"

        # Check TPs (cumulative)
        all_hit = True
        for i, tp in enumerate(targets):
            if not sig["tp_hit_flags"][i]:
                if (direction == "SHORT" and price <= tp["price"]) or \
                   (direction == "LONG" and price >= tp["price"]):
                    sig["tp_hit_flags"][i] = True
                    sig["max_tp_hit"] = max(sig["max_tp_hit"], i + 1)
            all_hit = all_hit and sig["tp_hit_flags"][i]

        if all_hit:
            return "CLOSED"
        return None

    def close_signal(self, symbol: str, outcome: str):
        """
        outcome: 'TP' (all hit), 'SL', or 'OVERRIDDEN_BY_FLIP'
        """
        sig = self.active_signals.pop(symbol, None)
        if sig:
            sig["close_time"] = time.time()
            sig["outcome"] = outcome
            # Determine realized PnL in R units (simplified)
            if outcome == "SL":
                sig["pnl_r"] = -1.0
            else:
                # weighted sum of target contributions (simplified full win = weighted avg RR)
                weighted_rr = sum(tp["pct"]/100 * self._calc_target_rr(sig, i) 
                                  for i, tp in enumerate(sig["targets"]))
                sig["pnl_r"] = weighted_rr   # assume full fill of all TPs
            # For partial hit signals, we'd need to track size, but we'll simplify for demo.
            self.closed_signals.append(sig)
            # Save history
            asyncio.create_task(self.save_history())

    def _calc_target_rr(self, sig, idx):
        entry = (sig["entry_min"] + sig["entry_max"]) / 2
        risk = abs(entry - sig["stop_loss"])
        tp_price = sig["targets"][idx]["price"]
        reward = abs(tp_price - entry)
        return reward / risk if risk > 0 else 0

    def flip_direction(self, new_signal: Dict):
        """
        When direction changes, override previous signal.
        Returns the old signal if one was overridden.
        """
        symbol = new_signal["symbol"]
        old = self.active_signals.pop(symbol, None)
        if old:
            old["outcome"] = "OVERRIDDEN_BY_FLIP"
            old["pnl_r"] = 0  # might have partial fill if needed
            self.closed_signals.append(old)
            asyncio.create_task(self.save_history())
        return old

import asyncio  # needed for the create_task call at bottom