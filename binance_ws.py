import asyncio
import ssl
import json
import aiohttp
from typing import Callable, Dict, List
import config

FUTURES_REST_BASE = "https://fapi.binance.com"
FUTURES_WS_BASE = "wss://fstream.binance.com/ws"

class BinanceMarketScanner:
    def __init__(self, callback: Callable):
        """
        callback(symbol: str, data: dict) is called on each ticker update.
        data contains: price, volume, timestamp.
        """
        self.callback = callback
        self.known_pairs: set = set()
        self.ws_tasks: Dict[str, asyncio.Task] = {}
        self._session: aiohttp.ClientSession = None
        self._running = True

    async def _create_session(self) -> aiohttp.ClientSession:
        """Create aiohttp session with SSL bypass (for REST) and browser headers."""
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        }
        timeout = aiohttp.ClientTimeout(total=30)
        return aiohttp.ClientSession(
            connector=connector,
            headers=headers,
            timeout=timeout
        )

    async def _fetch_futures_pairs(self) -> List[str]:
        """Get all USDT perpetual pairs from fapi.binance.com."""
        url = f"{FUTURES_REST_BASE}/fapi/v1/exchangeInfo"
        async with self._session.get(url) as resp:
            if resp.status != 200:
                raise ConnectionError(f"Failed to fetch exchange info: {resp.status}")
            data = await resp.json()
        pairs = [
            s["symbol"]
            for s in data["symbols"]
            if s["symbol"].endswith("USDT") and s["status"] == "TRADING"
        ]
        return pairs

    async def _subscribe_ticker(self, symbol: str):
        """Connect and listen to a single symbol's ticker stream with auto-reconnect."""
        stream_name = f"{symbol.lower()}@ticker"
        ws_url = f"{FUTURES_WS_BASE}/{stream_name}"
        while self._running:
            try:
                async with self._session.ws_connect(ws_url) as ws:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            self.callback(
                                symbol,
                                {
                                    "symbol": symbol,
                                    "price": float(data["c"]),
                                    "volume": float(data["q"]),  # quote volume
                                    "timestamp": data["E"],
                                },
                            )
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            break
            except Exception as e:
                print(f"[WS] {symbol} error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def _monitor_pair_changes(self):
        """Periodically check for newly listed pairs and subscribe to them."""
        while self._running:
            await asyncio.sleep(600)  # every 10 minutes
            try:
                current_pairs = await self._fetch_futures_pairs()
                new_pairs = set(current_pairs) - self.known_pairs
                if new_pairs:
                    print(f"[Scanner] New pairs detected: {new_pairs}")
                    for sym in new_pairs:
                        if sym not in self.ws_tasks:
                            self.known_pairs.add(sym)
                            self.ws_tasks[sym] = asyncio.create_task(self._subscribe_ticker(sym))
            except Exception as e:
                print(f"[Scanner] Error refreshing pairs: {e}")

    async def start(self):
        self._session = await self._create_session()
        # Initial pair fetch
        print("[Scanner] Fetching futures pairs from fapi.binance.com...")
        pairs = await self._fetch_futures_pairs()
        self.known_pairs.update(pairs)
        print(f"[Scanner] Found {len(pairs)} USDT perpetual pairs.")
        # Launch WebSocket listeners for all known pairs
        for sym in list(self.known_pairs):
            self.ws_tasks[sym] = asyncio.create_task(self._subscribe_ticker(sym))
        # Start background pair monitor
        asyncio.create_task(self._monitor_pair_changes())
        # Keep the scanner alive
        while self._running:
            await asyncio.sleep(3600)

    async def stop(self):
        self._running = False
        for task in self.ws_tasks.values():
            task.cancel()
        if self._session:
            await self._session.close()