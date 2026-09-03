import asyncio
import json
import logging
from urllib.parse import quote

import aiohttp
import websockets

log = logging.getLogger(__name__)


class Binance:
    def __init__(self, settings):
        self.s = settings
        self.session = None
        self.http_sem = asyncio.Semaphore(8)

    async def start(self):
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=20)
            self.session = aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "binance-signal-bot/1.0"})

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def exchange_info(self):
        # Contract metadata is obtained from the official USD-M Futures REST API.
        return await self.get_json("/fapi/v1/exchangeInfo")

    async def get_json(self, path, params=None):
        if self.session is None or self.session.closed:
            await self.start()
        url = self.s.rest_url + path
        async with self.http_sem:
            async with self.session.get(url, params=params) as r:
                r.raise_for_status()
                return await r.json()

    async def tickers(self):
        return await self.get_json("/fapi/v1/ticker/24hr")

    async def oi(self, symbol):
        return float((await self.get_json("/fapi/v1/openInterest", {"symbol": symbol}))[
            "openInterest"
        ])

    async def funding(self, symbol):
        return float((await self.get_json("/fapi/v1/premiumIndex", {"symbol": symbol}))["lastFundingRate"])

    async def klines(self, symbol, interval, limit):
        return await self.get_json(
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
        )


def symbol_streams(symbols):
    """Build per-symbol public market streams."""
    out = []
    for s in symbols:
        x = s.lower()
        out.extend(
            [
                f"{x}@kline_1m",
                f"{x}@kline_5m",
                f"{x}@kline_15m",
                f"{x}@kline_1h",
                f"{x}@aggTrade",
                f"{x}@depth10@100ms",
            ]
        )
    return out


class MarketWSConnection:
    """
    Binance combined-stream connection.

    IMPORTANT: this does NOT send a SUBSCRIBE control message. The streams are
    supplied in the connection URL itself. This removes the failure mode seen as
    WebSocket close 1008 / Payload too long.
    """

    def __init__(self, settings, streams_, on_event, label):
        self.s = settings
        self.streams = [x.lower() for x in streams_ if x]
        self.on_event = on_event
        self.label = label
        self.stop = False
        self._desired_symbols = []
        self._last_apply = 0.0
        self.ws = None

    def _url(self):
        if not self.streams:
            raise ValueError(f"WS[{self.label}] has no streams")

        # Combined public stream endpoint. No SUBSCRIBE JSON payload is sent.
        stream_path = "/".join([])  # keep lint-friendly; actual value below
        stream_path = "/".join(self.streams)
        # Use the configured base URL but normalize it to the combined-stream path.
        base = self.s.ws_stream_url.rstrip("/")
        if base.endswith("/public/stream"):
            return f"{base}?streams={quote(stream_path, safe='@._-/') }"
        if base.endswith("/stream"):
            return f"{base}?streams={quote(stream_path, safe='@._-/') }"
        # Fallback for a custom URL.
        return f"{base}?streams={quote(stream_path, safe='@._-/') }"

    async def run(self):
        delay = 1
        url = self._url()
        while not self.stop:
            try:
                log.info(
                    "WS[%s] starting: %d streams, URL length=%d",
                    self.label,
                    len(self.streams),
                    len(url),
                )
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_size=50_000_000,
                ) as ws:
                    self.ws = ws
                    delay = 1
                    log.info("WS[%s] connected", self.label)
                    started = asyncio.get_running_loop().time()
                    async for raw in ws:
                        if asyncio.get_running_loop().time() - started >= 23.5 * 3600:
                            log.info("WS[%s] scheduled reconnect before 24h limit", self.label)
                            await ws.close(code=1000, reason="scheduled reconnect")
                            break
                        parsed = json.loads(raw)
                        # Combined streams have: {"stream": "...", "data": {...}}
                        if "data" in parsed:
                            parsed = parsed["data"]
                        if isinstance(parsed, dict):
                            await self.on_event(parsed)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("WS[%s] disconnected: %s", self.label, exc)
                if not self.stop:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60)
            finally:
                self.ws = None

    async def close(self):
        self.stop = True
        if self.ws:
            await self.ws.close()


class MarketWSManager:
    """
    Manages several small combined-stream connections.

    The default is deliberately conservative: 10 symbols per connection.
    With 6 streams per symbol this is only ~60 streams per connection and,
    crucially, there is no SUBSCRIBE payload at all.
    """

    def __init__(self, settings, on_event, symbols_per_connection=10):
        self.s = settings
        self.on_event = on_event
        self.symbols_per_connection = max(1, int(symbols_per_connection))
        self.clients = []
        self.tasks = []
        self.stop = False

    @staticmethod
    def _chunks(items, size):
        for i in range(0, len(items), size):
            yield items[i : i + size]

    async def apply(self, symbols):
        desired_symbols = sorted(set(symbols))
        now = asyncio.get_running_loop().time()
        healthy = self.clients and any(not t.done() for t in self.tasks)
        if desired_symbols == self._desired_symbols and healthy:
            return
        min_interval = max(0, int(getattr(self.s, "ws_reconfigure_min_seconds", 120)))
        membership_changed = desired_symbols != self._desired_symbols
        if healthy and membership_changed and now - self._last_apply < min_interval:
            return
        self._desired_symbols = desired_symbols
        self._last_apply = now

        await self.stop_all()
        if self.stop:
            return

        # One connection for the all-market ticker stream.
        ticker = MarketWSConnection(
            self.s,
            ["!miniTicker@arr"],
            self.on_event,
            "ticker",
        )
        self.clients.append(ticker)
        self.tasks.append(asyncio.create_task(ticker.run()))

        for idx, chunk in enumerate(
            self._chunks(desired_symbols, self.symbols_per_connection), start=1
        ):
            streams_ = symbol_streams(chunk)
            client = MarketWSConnection(
                self.s,
                streams_,
                self.on_event,
                f"symbols-{idx}",
            )
            self.clients.append(client)
            self.tasks.append(asyncio.create_task(client.run()))

        log.info(
            "Market WS: %d symbols split across %d combined-stream connections (+ ticker)",
            len(desired_symbols),
            max(0, len(self.clients) - 1),
        )

    async def stop_all(self):
        old_clients = self.clients
        old_tasks = self.tasks
        self.clients = []
        self.tasks = []

        for client in old_clients:
            await client.close()
        for task in old_tasks:
            if not task.done():
                task.cancel()
        if old_tasks:
            await asyncio.gather(*old_tasks, return_exceptions=True)

    async def close(self):
        self.stop = True
        await self.stop_all()


def streams(symbols):
    return ["!miniTicker@arr"] + symbol_streams(symbols)
