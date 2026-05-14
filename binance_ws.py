import asyncio
import ssl
import json
import random
import aiohttp
from pathlib import Path
from typing import Callable, List, Optional
import config

FUTURES_REST_BASE = "https://fapi.binance.com"
FUTURES_WS_BASE = "wss://fstream.binance.com/ws"
PROXY_CACHE_FILE = Path("/data/working_proxies.txt")


class ProxyManager:
    """Fetches free HTTPS proxies, validates them, caches the good ones."""

    def __init__(self):
        self.good_proxies: List[str] = []
        self.lock = asyncio.Lock()
        self._first_run = True

    async def load_cache(self):
        if PROXY_CACHE_FILE.exists():
            lines = PROXY_CACHE_FILE.read_text().splitlines()
            self.good_proxies = [l.strip() for l in lines if l.strip()]
            print(f"[Proxy] Loaded {len(self.good_proxies)} cached proxies.")

    async def save_cache(self):
        PROXY_CACHE_FILE.write_text("\n".join(self.good_proxies[:20]))

    async def fetch_sources(self) -> List[str]:
        urls = [
            "https://www.proxy-list.download/api/v1/get?type=https",
            "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=https&timeout=10000&country=all&ssl=all&anonymity=all",
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/https.txt",
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/https.txt",
            "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
        ]
        proxies = set()
        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            for line in text.splitlines():
                                line = line.strip()
                                if line and not line.startswith("#") and ":" in line:
                                    proxies.add(f"http://{line}")
                except Exception:
                    continue
        return list(proxies)

    async def validate_proxy(self, proxy: str) -> bool:
        test_url = f"{FUTURES_REST_BASE}/fapi/v1/ping"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    test_url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def refresh(self):
        print("[Proxy] Searching for new proxies...")
        raw = await self.fetch_sources()
        print(f"[Proxy] Fetched {len(raw)} candidates, validating...")
        sample = random.sample(raw, min(50, len(raw)))
        tasks = [self.validate_proxy(p) for p in sample]
        results = await asyncio.gather(*tasks)
        fresh_good = [p for p, ok in zip(sample, results) if ok]
        async with self.lock:
            all_prox = list(set(self.good_proxies + fresh_good))
            random.shuffle(all_prox)
            self.good_proxies = all_prox[:30]
            await self.save_cache()
        print(f"[Proxy] Now have {len(self.good_proxies)} working proxies.")

    def get(self) -> Optional[str]:
        if self.good_proxies:
            return random.choice(self.good_proxies)
        return None

    async def autopilot(self):
        while True:
            await self.refresh()
            await asyncio.sleep(1800)  # every 30 minutes


class BinanceMarketScanner:
    def __init__(self, callback: Callable):
        self.callback = callback
        self.known_pairs: set = set()
        self.ws_tasks: dict = {}
        self._session: aiohttp.ClientSession = None
        self._running = True
        self.proxy_manager = ProxyManager()

    async def _create_session(self, proxy: Optional[str] = None) -> aiohttp.ClientSession:
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
        # Proxy is passed directly to ClientSession, not the connector
        return aiohttp.ClientSession(
            connector=connector,
            headers=headers,
            timeout=timeout,
            proxy=proxy,
        )

    async def _fetch_futures_pairs(self) -> List[str]:
        url = f"{FUTURES_REST_BASE}/fapi/v1/exchangeInfo"
        async with self._session.get(url) as resp:
            if resp.status != 200:
                raise ConnectionError(f"Failed to fetch exchange info: {resp.status}")
            data = await resp.json()
        return [
            s["symbol"]
            for s in data["symbols"]
            if s["symbol"].endswith("USDT") and s["status"] == "TRADING"
        ]

    async def _subscribe_ticker(self, symbol: str):
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
                                    "volume": float(data["q"]),
                                    "timestamp": data["E"],
                                },
                            )
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            break
            except Exception as e:
                print(f"[WS] {symbol} error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def _monitor_pairs(self):
        while self._running:
            await asyncio.sleep(600)
            try:
                current = await self._fetch_futures_pairs()
                new = set(current) - self.known_pairs
                if new:
                    print(f"[Scanner] New pairs: {new}")
                    for sym in new:
                        self.known_pairs.add(sym)
                        self.ws_tasks[sym] = asyncio.create_task(
                            self._subscribe_ticker(sym)
                        )
            except Exception as e:
                print(f"[Scanner] Pair refresh failed: {e}")

    async def _maintain_proxy_session(self) -> bool:
        """Create a new session with a working proxy. Return True if successful."""
        proxy = self.proxy_manager.get()
        if not proxy:
            return False
        if self._session:
            await self._session.close()
        self._session = await self._create_session(proxy=proxy)
        print(f"[Scanner] Using proxy: {proxy}")
        return True

    async def start(self):
        await self.proxy_manager.load_cache()
        # Initial refresh immediately, then every 30 minutes
        await self.proxy_manager.refresh()
        asyncio.create_task(self.proxy_manager.autopilot())

        # Try cached proxies / newly fetched ones until one works
        while self._running:
            if await self._maintain_proxy_session():
                try:
                    print("[Scanner] Fetching futures pairs...")
                    pairs = await self._fetch_futures_pairs()
                    self.known_pairs.update(pairs)
                    print(f"[Scanner] Found {len(pairs)} USDT perpetual pairs.")
                    for sym in list(self.known_pairs):
                        self.ws_tasks[sym] = asyncio.create_task(
                            self._subscribe_ticker(sym)
                        )
                    asyncio.create_task(self._monitor_pairs())
                    break  # success
                except Exception as e:
                    print(f"[Scanner] Failed with current proxy: {e}")
                    # Remove the bad proxy from pool? We'll just loop and try next
                    await asyncio.sleep(5)
            else:
                print("[Scanner] No working proxy yet, retrying in 10s...")
                await asyncio.sleep(10)

        # Keep alive
        while self._running:
            await asyncio.sleep(3600)

    async def stop(self):
        self._running = False
        for t in self.ws_tasks.values():
            t.cancel()
        if self._session:
            await self._session.close()