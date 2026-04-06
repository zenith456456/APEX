"""
EXCHANGE MONITOR — WebSocket-native symbol tracker
═══════════════════════════════════════════════════
No REST calls. Symbol list built from the live WebSocket stream.
BinanceScanner.update_from_ws() is called on every frame.

External new-listing alerts to Telegram/Discord are DISABLED.
Reason: Binance !miniTicker@arr only streams symbols with recent
trades. Low-volume coins can be silent for hours then suddenly
appear — indistinguishable from a real new listing, causing spam.

Internally, symbols seen for the first time are tracked so that
T3/T4 signals from new coins display a [NEW LISTING] tag.
"""
import asyncio
import logging
import time

logger = logging.getLogger("apex.exchange")


class ExchangeMonitor:

    def __init__(self):
        self._seen      : dict[str, float] = {}   # symbol → last-seen epoch
        self._running   : bool             = False
        self.total_frames: int             = 0
        self._last_log  : float            = 0.0

    @property
    def active_symbols(self) -> set[str]:
        cutoff = time.time() - 300   # 5-min grace for silent pairs
        return {s for s, t in self._seen.items() if t >= cutoff}

    @property
    def symbol_count(self) -> int:
        return len(self.active_symbols)

    def add_new_listing_callback(self, cb):
        pass   # disabled — see module docstring

    def update_from_ws(self, symbols: set[str]) -> set[str]:
        """
        Called by BinanceScanner on every WebSocket frame.
        Updates last-seen timestamps.
        Returns set of symbols appearing for the VERY FIRST TIME
        (used internally to tag signals as [NEW LISTING]).
        No external alerts fired.
        """
        self.total_frames += 1
        now      = time.time()
        new_syms = symbols - self._seen.keys()

        for sym in symbols:
            self._seen[sym] = now

        if now - self._last_log >= 600:
            logger.info(
                f"Exchange monitor: {self.symbol_count} active USDT pairs  "
                f"({self.total_frames} frames processed)"
            )
            self._last_log = now

        return new_syms

    async def run(self):
        """Lightweight keep-alive loop. All work done in update_from_ws()."""
        self._running = True
        logger.info("Exchange monitor started (WebSocket-native · no REST)")
        while self._running:
            await asyncio.sleep(60)

    def stop(self):
        self._running = False
