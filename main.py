import asyncio
import time
import config
from binance_ws import BinanceMarketScanner
from csm_detector import CSMDetector
from state_manager import StateManager
from stats_tracker import StatsTracker
from notifier import Notifier

class CSMBot:
    def __init__(self):
        self.detector = CSMDetector(min_rr=config.MIN_RR, max_rr=config.MAX_RR)
        self.state = StateManager()
        self.stats = StatsTracker()
        self.notifier = Notifier(config, self.stats)
        # queue of new signals to process (avoid blocking WebSocket)
        self.signal_queue = asyncio.Queue()

    async def setup(self):
        await self.state.load_history()
        self.stats.load(self.state.closed_signals)
        print(f"Bot loaded {len(self.state.closed_signals)} historical trades.")

    async def price_callback(self, symbol: str, data: dict):
        """
        Called from BinanceScanner on every ticker update.
        """
        price = data['price']
        timestamp = data['timestamp']
        # Feed detector to build candles and maybe generate signal
        self.detector.feed_price(symbol, price, timestamp)
        signal = self.detector.generate_signal(symbol)
        if signal:
            # Check against active signal to avoid duplicates
            old = self.state.get_active_signal(symbol)
            if old:
                if old["direction"] != signal["direction"]:
                    # Direction flip: override and accept new signal
                    self.state.flip_direction(signal)
                    self.state.set_active_signal(symbol, signal)
                    await self.signal_queue.put(signal)
                else:
                    # Same direction, only allow if previous signal closed
                    # We'll check if it's still OPEN by update_price below
                    pass  # new signal suppressed
            else:
                # No active signal, accept
                self.state.set_active_signal(symbol, signal)
                await self.signal_queue.put(signal)

        # Update price for active signal management
        active = self.state.get_active_signal(symbol)
        if active:
            result = self.state.update_price(symbol, price)
            if result in ("SL", "CLOSED"):
                self.state.close_signal(symbol, result)
                self.stats.load(self.state.closed_signals)  # refresh stats
                if result == "SL":
                    # Stop loss hit, the pair becomes free
                    pass
                # if closed, we could optionally log, but the signal was already sent

    async def process_signals(self):
        while True:
            signal = await self.signal_queue.get()
            # Broadcast
            await self.notifier.broadcast(signal)
            print(f"[Signal] Sent signal for {signal['symbol']} #{signal['trade_id']}")

    async def start(self):
        await self.setup()
        scanner = BinanceMarketScanner(callback=self.price_callback)
        # Start the scanner in the background
        asyncio.create_task(scanner.start())
        # Process broadcast queue
        await self.process_signals()

if __name__ == "__main__":
    bot = CSMBot()
    asyncio.run(bot.start())