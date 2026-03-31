"""
EXCHANGE MONITOR  —  WebSocket-native (no REST required)
═════════════════════════════════════════════════════════
Binance REST APIs return HTTP 451 (geo-blocked) on some hosts.

FIX: Symbol list is built entirely from the live WebSocket stream.
The scanner calls update_from_ws() on every frame with the set of
symbols it just saw.

NEW LISTING DETECTION:
- First N frames (WARMUP_FRAMES) are used to build the baseline
  symbol set silently — NO alerts fired during warmup.
- Only symbols that appear AFTER warmup is complete trigger alerts.
- This prevents the bot from spamming every coin on startup.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Awaitable

logger = logging.getLogger("apex.exchange")

NewListingCallback = Callable[[str], Awaitable[None]]

# How many WS frames to silently absorb before enabling new-listing alerts.
# The full futures symbol list (~400 pairs) arrives within the first 2-3 frames.
WARMUP_FRAMES = 5

# How many seconds a symbol must be absent before considered delisted
DELIST_GRACE_SEC = 300


class ExchangeMonitor:

    def __init__(self):
        self._seen      : dict[str, float]           = {}
        self._callbacks : list[NewListingCallback]   = []
        self._running   : bool                       = False

        # Warmup tracking — suppress alerts until baseline is established
        self._warmup_done   : bool = False
        self._warmup_frames : int  = 0

        # Stats
        self.total_frames : int   = 0
        self.new_listings : int   = 0
        self._last_log    : float = 0.0

    # ── Properties ────────────────────────────────────────────

    @property
    def active_symbols(self) -> set[str]:
        cutoff = time.time() - DELIST_GRACE_SEC
        return {s for s, t in self._seen.items() if t >= cutoff}

    @property
    def symbol_count(self) -> int:
        return len(self.active_symbols)

    # ── Callbacks ─────────────────────────────────────────────

    def add_new_listing_callback(self, cb: NewListingCallback):
        self._callbacks.append(cb)

    # ── Called by BinanceScanner on every WebSocket frame ─────

    def update_from_ws(self, symbols: set[str]):
        """
        Feed the set of USDT symbols from the current WS frame.

        During warmup (first WARMUP_FRAMES frames):
            - All symbols are added to baseline silently.
            - NO new listing callbacks are fired.

        After warmup:
            - Any symbol not previously seen = new listing → fire callback.
        """
        self.total_frames += 1
        now = time.time()

        if not self._warmup_done:
            # Silently absorb all symbols into the baseline
            for sym in symbols:
                self._seen[sym] = now
            self._warmup_frames += 1

            if self._warmup_frames >= WARMUP_FRAMES:
                self._warmup_done = True
                logger.info(
                    f"Exchange monitor baseline established: "
                    f"{len(self._seen)} active USDT pairs  "
                    f"(new listing detection now ACTIVE)"
                )
            return

        # ── Post-warmup: detect genuinely new symbols ─────────
        new_syms = symbols - self._seen.keys()

        # Update last-seen timestamps for all current symbols
        for sym in symbols:
            self._seen[sym] = now

        # Periodic status log every 10 minutes
        if now - self._last_log >= 600:
            logger.info(
                f"Exchange monitor: {self.symbol_count} active USDT pairs "
                f"| {self.new_listings} new listings detected since start"
            )
            self._last_log = now

        # Fire alerts only for genuinely new pairs
        if new_syms:
            for sym in sorted(new_syms):
                self.new_listings += 1
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                logger.info(f"NEW LISTING: {sym}  ({ts})")
                asyncio.ensure_future(self._fire(sym))

    async def _fire(self, symbol: str):
        for cb in self._callbacks:
            try:
                await cb(symbol)
            except Exception as exc:
                logger.warning(f"New listing callback error [{symbol}]: {exc}")

    # ── Lifecycle ─────────────────────────────────────────────

    async def run(self):
        """
        No REST calls needed — driven entirely by update_from_ws().
        This loop just keeps the task alive alongside the WS loop.
        """
        self._running = True
        logger.info(
            f"Exchange monitor started  "
            f"(WebSocket-native · warmup={WARMUP_FRAMES} frames · no REST)"
        )
        while self._running:
            await asyncio.sleep(60)

    def stop(self):
        self._running = False
