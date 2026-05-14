import asyncio
import ssl
import random
import aiohttp
from typing import Callable, Optional
from binance import AsyncClient, BinanceSocketManager
import config

class ProxyManager:
    """
    Periodically fetches free HTTPS proxies, validates them against Binance ping,
    and provides a working proxy URL.
    """
    def __init__(self):
        self.working_proxies = []
        self.lock = asyncio.Lock()
        self._fetch_task = None

    async def _fetch_proxies(self) -> list:
        """Scrape free HTTPS proxies from multiple sources (no auth needed)."""
        urls = [
            "https://www.proxy-list.download/api/v1/get?type=https",
            "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=https&timeout=10000&country=all&ssl=all&anonymity=all",
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/https.txt",
        ]
        proxies = set()
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for url in urls:
                try:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            for line in text.splitlines():
                                line = line.strip()
                                if line and not line.startswith("#"):
                                    if ":" in line:
                                        proxies.add(f"http://{line}")   # some proxies require http://
                except Exception:
                    continue
        return list(proxies)

    async def _validate_proxy(self, proxy_url: str) -> bool:
        """Test if proxy can reach Binance ping."""
        test_url = "https://api.binance.com/api/v3/ping"
        timeout = aiohttp.ClientTimeout(total=8)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(test_url, proxy=proxy_url) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def refresh(self):
        """Fetch and validate proxies, storing only working ones."""
        new_proxies = []
        raw = await self._fetch_proxies()
        print(f"[Proxy] Fetched {len(raw)} candidates, validating...")
        # Validate up to 20 random ones to avoid too many requests
        sample = random.sample(raw, min(20, len(raw)))
        tasks = [self._validate_proxy(p) for p in sample]
        results = await asyncio.gather(*tasks)
        for proxy, valid in zip(sample, results):
            if valid:
                new_proxies.append(proxy)
        async with self.lock:
            self.working_proxies = new_proxies
        print(f"[Proxy] {len(self.working_proxies)} working proxies stored.")

    def get_proxy(self) -> Optional[str]:
        """Return a random working proxy, or None if none available."""
        if self.working_proxies:
            return random.choice(self.working_proxies)
        return None

    async def start_periodic_refresh(self):
        while True:
            await self.refresh()
            await asyncio.sleep(1800)  # refresh every 30 minutes


class BinanceMarketScanner:
    def __init__(self, callback: Callable):
        self.callback = callback
        self.client = None
        self.bm = None
        self.known_pairs = set()
        self.active_streams = {}
        self._session = None
        self.proxy_manager = ProxyManager()

    def _create_session(self, proxy: Optional[str] = None) -> aiohttp.ClientSession:
        """Build an aiohttp session with SSL bypass, browser headers, and proxy."""
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        connector_kwargs = {"ssl": ssl_context}
        if proxy:
            connector_kwargs["proxy"] = proxy
            print(f"[Scanner] Using proxy: {proxy}")

        connector = aiohttp.TCPConnector(**connector_kwargs)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.5",
        }
        timeout = aiohttp.ClientTimeout(total=30)
        session = aiohttp.ClientSession(
            connector=connector,
            headers=headers,
            timeout=timeout
        )
        return session

    async def start(self):
        # Start background proxy refresher
        asyncio.create_task(self.proxy_manager.start_periodic_refresh())
        # Initial proxy fetch (wait until at least one proxy is ready, or fallback to direct)
        await self.proxy_manager.refresh()
        proxy = self.proxy_manager.get_proxy()
        if not proxy:
            print("[Scanner] No working proxy found, falling back to direct connection (may fail).")

        self._session = self._create_session(proxy=proxy)
        self.client = await AsyncClient.create(
            tld=config.BINANCE_TLD,
            session=self._session,
        )
        self.bm = BinanceSocketManager(self.client)
        await self._update_pairs()
        asyncio.create_task(self._refresh_pairs_periodic())
        await self._subscribe_all()
        while True:
            await asyncio.sleep(3600)

    async def _update_pairs(self):
        try:
            exchange_info = await self.client.futures_exchange_info()
            usdt_pairs = [
                s['symbol'] for s in exchange_info['symbols']
                if s['symbol'].endswith('USDT') and s['status'] == 'TRADING'
            ]
            new_pairs = set(usdt_pairs) - self.known_pairs
            if new_pairs:
                print(f"[Scanner] New pairs detected: {new_pairs}")
                self.known_pairs.update(new_pairs)
                await self._subscribe_pairs(new_pairs)
        except Exception as e:
            print(f"[Scanner] Error updating pairs: {e}")

    async def _refresh_pairs_periodic(self):
        while True:
            await asyncio.sleep(600)
            await self._update_pairs()

    async def _subscribe_pairs(self, pairs):
        for symbol in pairs:
            ts = self.bm.futures_symbol_ticker_socket(symbol=symbol)
            self.active_streams[symbol] = ts

    async def _subscribe_all(self):
        for sym in list(self.known_pairs):
            if sym in self.active_streams:
                continue
            ts = self.bm.futures_symbol_ticker_socket(symbol=sym)
            self.active_streams[sym] = ts
            asyncio.create_task(self._listen_to_stream(sym, ts))

    async def _listen_to_stream(self, symbol, ts):
        async with ts as stream:
            while True:
                try:
                    msg = await stream.recv()
                    if msg:
                        data = {
                            'symbol': symbol,
                            'price': float(msg['c']),
                            'volume': float(msg['v']),
                            'timestamp': int(msg['E'])
                        }
                        await self.callback(symbol, data)
                except Exception as e:
                    print(f"[Stream] Error on {symbol}: {e}")
                    await asyncio.sleep(5)
                    break