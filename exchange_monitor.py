"""
EXCHANGE MONITOR
════════════════
Fetches active USDT pairs every EXCHANGE_REFRESH_MIN minutes.
Detects newly listed pairs and fires callbacks immediately.

FIX: Uses Spot REST API (api.binance.com) for exchangeInfo because
     Binance Futures REST (fapi.binance.com) returns HTTP 451
     (geo-blocked) on some hosting providers (e.g. Northflank EU).
     The Spot API is not geo-blocked and contains all USDT pairs.
     The Futures WebSocket (fstream.binance.com) is unaffected.
"""
import asyncio
import logging
import time
from typing import Callable, Awaitable

import aiohttp

from config import EXCHANGE_REFRESH_MIN

logger = logging.getLogger("apex.exchange")

# ── REST endpoints tried in order ─────────────────────────────
# Spot API is not geo-restricted — use it as primary source.
# Futures API is a fallback (works in some regions).
SPOT_EXCHANGE_INFO    = "https://api.binance.com/api/v3/exchangeInfo"
FUTURES_EXCHANGE_INFO = "https://fapi.binance.com/fapi/v1/exchangeInfo"

# Back-off on failure: retry after this many seconds before
# waiting for the full EXCHANGE_REFRESH_MIN window
FAILURE_RETRY_SEC = 300   # 5 minutes — stops the spam loop

NewListingCallback = Callable[[str], Awaitable[None]]


class ExchangeMonitor:

    def __init__(self):
        self._symbols      : set[str]                 = set()
        self._first_load   : bool                     = True
        self._last_refresh : float                    = 0.0
        self._callbacks    : list[NewListingCallback] = []
        self._running      : bool                     = False
        self.total_fetches : int                      = 0

    @property
    def active_symbols(self) -> set[str]:
        return set(self._symbols)

    @property
    def symbol_count(self) -> int:
        return len(self._symbols)

    def add_new_listing_callback(self, cb: NewListingCallback):
        self._callbacks.append(cb)

    def stop(self):
        self._running = False

    # ── Main loop ─────────────────────────────────────────────

    async def run(self):
        self._running = True
        while self._running:
            success = False
            try:
                await self._fetch()
                success = True
            except Exception as exc:
                logger.warning(f"Exchange info fetch failed: {exc}")

            if success:
                # Normal path — wait until next full refresh window
                elapsed = time.time() - self._last_refresh
                wait    = max(5.0, EXCHANGE_REFRESH_MIN * 60 - elapsed)
            else:
                # Back-off path — wait 5 min before retrying (stops spam)
                wait = FAILURE_RETRY_SEC
                logger.info(
                    f"Exchange fetch failed — retrying in {wait//60:.0f} min  "
                    f"({self.symbol_count} pairs cached from last good fetch)"
                )

            logger.info(
                f"Next exchange refresh in {wait/60:.1f} min  "
                f"({self.symbol_count} active USDT pairs)"
            )
            await asyncio.sleep(wait)

    # ── Fetch with Spot-first fallback ────────────────────────

    async def _fetch(self):
        """
        Try Spot API first (not geo-blocked).
        Fall back to Futures API if Spot fails.
        """
        # ── Attempt 1: Spot API ───────────────────────────────
        try:
            new_set = await self._fetch_spot()
            if new_set:
                self._apply(new_set)
                return
        except Exception as exc:
            logger.warning(f"Spot exchangeInfo failed ({exc}) — trying Futures API...")

        # ── Attempt 2: Futures API ────────────────────────────
        try:
            new_set = await self._fetch_futures()
            if new_set:
                self._apply(new_set)
                return
        except Exception as exc:
            raise RuntimeError(
                f"Both Spot and Futures exchangeInfo failed. Last error: {exc}"
            )

    async def _fetch_spot(self) -> set[str]:
        """
        GET /api/v3/exchangeInfo from Spot API.
        Filter for USDT quote asset, TRADING status.
        Returns USDT symbol set (e.g. BTCUSDT, ETHUSDT ...).
        """
        logger.info("Fetching exchange info via Spot REST (api.binance.com)...")
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        ) as session:
            async with session.get(SPOT_EXCHANGE_INFO) as resp:
                resp.raise_for_status()
                data = await resp.json()

        result: set[str] = set()
        for s in data.get("symbols", []):
            if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING":
                result.add(s["symbol"])

        logger.info(f"Spot API returned {len(result)} active USDT pairs")
        return result

    async def _fetch_futures(self) -> set[str]:
        """
        GET /fapi/v1/exchangeInfo from Futures API.
        Filter for USDT perpetual contracts.
        """
        logger.info("Fetching exchange info via Futures REST (fapi.binance.com)...")
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        ) as session:
            async with session.get(FUTURES_EXCHANGE_INFO) as resp:
                resp.raise_for_status()
                data = await resp.json()

        result: set[str] = set()
        for s in data.get("symbols", []):
            if (
                s.get("quoteAsset")    == "USDT"
                and s.get("status")   == "TRADING"
                and s.get("contractType") == "PERPETUAL"
            ):
                result.add(s["symbol"])

        logger.info(f"Futures API returned {len(result)} active USDT-M pairs")
        return result

    # ── Apply diff ────────────────────────────────────────────

    def _apply(self, new_set: set[str]):
        """Compare new symbol set to current, fire new listing callbacks."""
        self._last_refresh  = time.time()
        self.total_fetches += 1

        if not new_set:
            logger.warning("exchangeInfo returned 0 symbols — skipping update")
            return

        if self._first_load:
            self._symbols    = new_set
            self._first_load = False
            logger.info(f"✓ Initial load: {len(new_set)} active USDT pairs")
            return

        newly   = new_set - self._symbols
        removed = self._symbols - new_set

        if removed:
            logger.info(f"Removed/delisted: {removed}")

        if newly:
            logger.info(f"NEW LISTINGS DETECTED: {newly}")
            # Fire callbacks (async) — schedule as tasks
            asyncio.ensure_future(self._fire_new_listing_callbacks(sorted(newly)))

        self._symbols = new_set
        logger.info(
            f"✓ Exchange refresh #{self.total_fetches}: "
            f"{len(new_set)} pairs  (+{len(newly)} new  -{len(removed)} removed)"
        )

    async def _fire_new_listing_callbacks(self, symbols: list[str]):
        for sym in symbols:
            for cb in self._callbacks:
                try:
                    await cb(sym)
                except Exception as exc:
                    logger.warning(f"New listing callback error [{sym}]: {exc}")
