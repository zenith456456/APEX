"""
EXCHANGE MONITOR  —  WebSocket-native (no REST required)
═════════════════════════════════════════════════════════
Binance REST APIs (both fapi.binance.com and api.binance.com)
return HTTP 451 on some hosting regions (e.g. Northflank EU).

FIX: The symbol list is built entirely from the live WebSocket
stream instead of REST. The scanner calls update_from_ws() on
every frame with the set of symbols it just saw. Any symbol
that appears for the first time is treated as a new listing
and triggers callbacks immediately — same behaviour as before,
zero REST calls, zero 451 errors.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Awaitable

logger = logging.getLogger("apex.exchange")

NewListingCallback = Callable[[str], Awaitable[None]]

# How many seconds a symbol must be absent before being
# considered delisted (avoids false positives on brief gaps)
DELIST_GRACE_SEC = 300   # 5 minutes


class ExchangeMonitor:

    def __init__(self):
        # symbol → last-seen epoch
        self._seen      : dict[str, float]           = {}
        self._callbacks : list[NewListingCallback]   = []
        self._running   : bool                       = False

        # Stats
        self.total_frames   : int = 0
        self.new_listings   : int = 0
        self._last_log_time : float = 0.0

    # ── Properties ────────────────────────────────────────────

    @property
    def active_symbols(self) -> set[str]:
        """All symbols seen in the last DELIST_GRACE_SEC seconds."""
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
        Feed the set of USDT symbols seen in the current WS frame.
        Detects any symbol that has never appeared before as a
        NEW LISTING and fires callbacks asynchronously.
        """
        self.total_frames += 1
        now        = time.time()
        new_syms   = symbols - self._seen.keys()

        # Update last-seen timestamps
        for sym in symbols:
            self._seen[sym] = now

        # Periodic log every 10 minutes
        if now - self._last_log_time >= 600:
            logger.info(
                f"Exchange monitor: {self.symbol_count} active USDT pairs "
                f"(source: WebSocket stream, {self.total_frames} frames processed)"
            )
            self._last_log_time = now

        # Fire new listing callbacks
        if new_syms:
            for sym in sorted(new_syms):
                self.new_listings += 1
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                logger.info(f"NEW LISTING DETECTED: {sym}  ({ts})")
                asyncio.ensure_future(self._fire_callbacks(sym))

    async def _fire_callbacks(self, symbol: str):
        for cb in self._callbacks:
            try:
                await cb(symbol)
            except Exception as exc:
                logger.warning(f"New listing callback error [{symbol}]: {exc}")

    # ── Lifecycle ─────────────────────────────────────────────

    async def run(self):
        """
        No-op loop — this monitor is now driven entirely by
        update_from_ws() calls from BinanceScanner.
        Kept for API compatibility with BinanceScanner.run().
        """
        self._running = True
        logger.info(
            "Exchange monitor started (WebSocket-native mode — no REST required)"
        )
        while self._running:
            await asyncio.sleep(60)

    def stop(self):
        self._running = False
