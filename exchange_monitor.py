"""
EXCHANGE MONITOR  —  WebSocket-native symbol tracker
═════════════════════════════════════════════════════
No REST calls. Symbol list built entirely from the WebSocket stream.
BinanceScanner calls update_from_ws() on every frame.

NEW LISTING DETECTION — INTERNAL ONLY:
  External new listing alerts (to Telegram/Discord) are DISABLED.
  Reason: Binance's !miniTicker@arr stream only sends symbols with
  recent trades. Low-volume pairs can be silent for hours then
  suddenly appear — indistinguishable from a genuine new listing.
  This caused continuous false-positive spam.

  Internally, _new_syms is still tracked so that T3/T4 signals
  from coins that appear for the first time carry a [NEW LISTING]
  tag in the signal message itself.

  Any REAL new Binance listing will generate a T3/T4 signal within
  minutes due to extreme volatility — that signal is the alert.
"""

import asyncio
import logging
import time

logger = logging.getLogger("apex.exchange")

# How long a symbol must be absent before purging from active set
DELIST_GRACE_SEC = 300


class ExchangeMonitor:

    def __init__(self):
        # symbol → last-seen timestamp
        self._seen       : dict[str, float] = {}
        self._running    : bool             = False
        self._start_time : float            = time.time()

        # Stats
        self.total_frames : int   = 0
        self._last_log    : float = 0.0

    # ── Properties ────────────────────────────────────────────

    @property
    def active_symbols(self) -> set[str]:
        cutoff = time.time() - DELIST_GRACE_SEC
        return {s for s, t in self._seen.items() if t >= cutoff}

    @property
    def symbol_count(self) -> int:
        return len(self.active_symbols)

    # ── No-op for API compatibility (no callbacks needed) ─────

    def add_new_listing_callback(self, cb):
        """
        New listing external callbacks are disabled.
        Kept for API compatibility — does nothing.
        """
        pass

    # ── Called by BinanceScanner on every WebSocket frame ─────

    def update_from_ws(self, symbols: set[str]) -> set[str]:
        """
        Update the seen-symbol set with the current frame's symbols.

        Returns the set of symbols appearing for the FIRST TIME ever
        (used by scanner to tag signals as [NEW LISTING] internally).
        No external alerts are fired.
        """
        self.total_frames += 1
        now = time.time()

        new_syms = symbols - self._seen.keys()

        for sym in symbols:
            self._seen[sym] = now

        # Periodic status log every 10 minutes
        if now - self._last_log >= 600:
            logger.info(
                f"Exchange monitor: {self.symbol_count} active USDT pairs  "
                f"({self.total_frames} frames processed)"
            )
            self._last_log = now

        return new_syms   # returned to scanner for internal [NEW] tagging

    # ── Lifecycle ─────────────────────────────────────────────

    async def run(self):
        self._running = True
        logger.info(
            "Exchange monitor started  "
            "(WebSocket-native · no REST · new listing alerts: INTERNAL ONLY)"
        )
        while self._running:
            await asyncio.sleep(60)

    def stop(self):
        self._running = False
