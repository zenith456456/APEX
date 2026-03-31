"""
EXCHANGE MONITOR  —  WebSocket-native, time-based warmup + batch guard
═══════════════════════════════════════════════════════════════════════
No REST calls needed. Symbol list built entirely from WebSocket stream.
BinanceScanner calls update_from_ws() on every frame.

THREE-LAYER PROTECTION against startup spam:

  Layer 1 — Time warmup (60s):
    All symbols in the first 60s are silently added to baseline.
    Zero alerts fired during warmup.

  Layer 2 — Batch size guard:
    If more than MAX_BATCH_ALERTS new symbols appear in a single
    frame after warmup, it is treated as residual startup noise
    and the entire batch is silently absorbed. A genuine new listing
    arrives as 1-3 symbols, never 400.

  Layer 3 — Scanner double-guard:
    BinanceScanner._on_new_listing() also checks warmup_done
    before forwarding to Telegram/Discord.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Awaitable

logger = logging.getLogger("apex.exchange")

NewListingCallback = Callable[[str], Awaitable[None]]

# Layer 1: Time-based warmup window (seconds)
WARMUP_SEC = 60

# Layer 2: Max new symbols per frame that count as real listings.
# If a single frame introduces more than this, it's startup noise.
MAX_BATCH_ALERTS = 5

# How long a symbol can be absent before considered delisted
DELIST_GRACE_SEC = 300


class ExchangeMonitor:

    def __init__(self):
        self._seen       : dict[str, float]           = {}
        self._callbacks  : list[NewListingCallback]   = []
        self._running    : bool                       = False
        self._start_time : float                      = time.time()
        self._announced  : bool                       = False

        # Stats
        self.total_frames  : int   = 0
        self.new_listings  : int   = 0
        self.batches_dropped : int = 0
        self._last_log     : float = 0.0

    # ── Properties ────────────────────────────────────────────

    @property
    def warmup_done(self) -> bool:
        return (time.time() - self._start_time) >= WARMUP_SEC

    @property
    def active_symbols(self) -> set[str]:
        cutoff = time.time() - DELIST_GRACE_SEC
        return {s for s, t in self._seen.items() if t >= cutoff}

    @property
    def symbol_count(self) -> int:
        return len(self.active_symbols)

    # ── Public ────────────────────────────────────────────────

    def add_new_listing_callback(self, cb: NewListingCallback):
        self._callbacks.append(cb)

    # ── Called by BinanceScanner on every WebSocket frame ─────

    def update_from_ws(self, symbols: set[str]):
        """
        Layer 1: During warmup → absorb silently, no alerts.
        Layer 2: After warmup → if batch > MAX_BATCH_ALERTS → drop silently.
        Otherwise → fire new listing callbacks.
        """
        self.total_frames += 1
        now = time.time()

        # ── Layer 1: Warmup ───────────────────────────────────
        if not self.warmup_done:
            for sym in symbols:
                self._seen[sym] = now
            return

        # Log once when warmup completes
        if not self._announced:
            self._announced = True
            elapsed = now - self._start_time
            logger.info(
                f"Exchange monitor: warmup complete ({elapsed:.0f}s)  "
                f"Baseline = {len(self._seen)} pairs  "
                f"New listing detection ACTIVE"
            )

        # Find new symbols
        new_syms = symbols - self._seen.keys()

        # Update timestamps
        for sym in symbols:
            self._seen[sym] = now

        # Periodic status log
        if now - self._last_log >= 600:
            logger.info(
                f"Exchange monitor: {self.symbol_count} active USDT pairs  "
                f"| {self.new_listings} new listings  "
                f"| {self.batches_dropped} batches dropped (startup noise)"
            )
            self._last_log = now

        if not new_syms:
            return

        # ── Layer 2: Batch size guard ─────────────────────────
        if len(new_syms) > MAX_BATCH_ALERTS:
            self.batches_dropped += 1
            logger.info(
                f"Exchange monitor: dropped batch of {len(new_syms)} symbols "
                f"(exceeds MAX_BATCH_ALERTS={MAX_BATCH_ALERTS} — startup noise)"
            )
            return

        # ── Genuine new listing(s) — fire callbacks ───────────
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
        self._running = True
        logger.info(
            f"Exchange monitor started  "
            f"(WebSocket-native · {WARMUP_SEC}s warmup · "
            f"batch guard ≤{MAX_BATCH_ALERTS} · no REST)"
        )
        while self._running:
            await asyncio.sleep(60)

    def stop(self):
        self._running = False
