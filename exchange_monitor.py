"""
EXCHANGE MONITOR
Fetches all active USDT-M Perpetual futures pairs every EXCHANGE_REFRESH_MIN minutes.
Detects newly listed pairs and fires callbacks immediately.
"""
import asyncio, logging, time
from typing import Callable, Awaitable
import aiohttp
from config import BINANCE_REST_BASE, EXCHANGE_REFRESH_MIN

logger = logging.getLogger("apex.exchange")
NewListingCallback = Callable[[str], Awaitable[None]]

class ExchangeMonitor:
    def __init__(self):
        self._symbols: set[str] = set()
        self._first_load = True
        self._last_refresh = 0.0
        self._callbacks: list[NewListingCallback] = []
        self._running = False
        self.total_fetches = 0

    @property
    def active_symbols(self): return set(self._symbols)
    @property
    def symbol_count(self): return len(self._symbols)
    def add_new_listing_callback(self, cb): self._callbacks.append(cb)
    def stop(self): self._running = False

    async def run(self):
        self._running = True
        while self._running:
            try:
                await self._fetch()
            except Exception as e:
                logger.warning(f"Exchange info fetch failed: {e}")
            elapsed = time.time() - self._last_refresh
            wait = max(5.0, EXCHANGE_REFRESH_MIN * 60 - elapsed)
            logger.info(f"Next exchange refresh in {wait/60:.1f} min ({self.symbol_count} USDT-M pairs)")
            await asyncio.sleep(wait)

    async def _fetch(self):
        url = f"{BINANCE_REST_BASE}/fapi/v1/exchangeInfo"
        logger.info("Fetching Futures exchange info from Binance REST...")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json()
        new_set: set[str] = set()
        for s in data.get("symbols", []):
            if (s.get("quoteAsset")=="USDT" and s.get("status")=="TRADING"
                    and s.get("contractType")=="PERPETUAL"):
                new_set.add(s["symbol"])
        self._last_refresh = time.time()
        self.total_fetches += 1
        if not new_set:
            logger.warning("Exchange info returned 0 symbols — skipping")
            return
        if self._first_load:
            self._symbols = new_set; self._first_load = False
            logger.info(f"✓ Initial load: {len(new_set)} active USDT-M perpetual pairs")
            return
        newly = new_set - self._symbols; removed = self._symbols - new_set
        if removed: logger.info(f"Delisted: {removed}")
        if newly:
            logger.info(f"NEW LISTINGS: {newly}")
            for sym in sorted(newly):
                for cb in self._callbacks:
                    try: await cb(sym)
                    except Exception as e: logger.warning(f"New listing callback error [{sym}]: {e}")
        self._symbols = new_set
        logger.info(f"✓ Refresh #{self.total_fetches}: {len(new_set)} pairs (+{len(newly)} new -{len(removed)} removed)")

    async def fetch_ticker_snapshot(self) -> list[dict]:
        url = f"{BINANCE_REST_BASE}/fapi/v1/ticker/24hr"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json()
        result = [i for i in data if isinstance(i,dict) and i.get("symbol","").endswith("USDT")]
        logger.info(f"✓ Ticker snapshot: {len(result)} pairs")
        return result
