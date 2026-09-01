import asyncio
import json
import logging

import aiohttp
import websockets

log = logging.getLogger(__name__)


class Binance:
    def __init__(self, settings):
        self.s = settings

    async def exchange_info(self):
        # Contract metadata is obtained from the official USD-M Futures REST API.
        return await self.get_json("/fapi/v1/exchangeInfo")

    async def get_json(self, path, params=None):
        url = self.s.rest_url + path
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as r:
                r.raise_for_status()
                return await r.json()

    async def tickers(self):
        return await self.get_json("/fapi/v1/ticker/24hr")

    async def oi(self, symbol):
        return float((await self.get_json("/fapi/v1/openInterest", {"symbol": symbol}))["openInterest"])

    async def funding(self, symbol):
        return float((await self.get_json("/fapi/v1/premiumIndex", {"symbol": symbol}))["lastFundingRate"])

    async def klines(self, symbol, interval, limit):
        return await self.get_json(
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
        )


def symbol_streams(symbols):
    """Build only per-symbol streams. Keep the control payload small."""
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
    """One small Binance public market-data connection."""

    def __init__(self, settings, streams_, on_event, label):
        self.s = settings
        self.streams = [x.lower() for x in streams_ if x]
        self.on_event = on_event
        self.label = label
        self.stop = False
        self.ws = None

    async def run(self):
        delay = 1
        while not self.stop:
            try:
                async with websockets.connect(
                    self.s.ws_stream_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_size=50_000_000,
                ) as ws:
                    self.ws = ws
                    if self.streams:
                        request = {
                            "method": "SUBSCRIBE",
                            "params": self.streams,
                            "id": 1,
                        }
                        payload = json.dumps(request, separators=(",", ":"))
                        log.info(
                            "WS[%s] subscribing to %d streams (%d bytes)",
                            self.label,
                            len(self.streams),
                            len(payload.encode("utf-8")),
                        )
                        await ws.send(payload)

                    delay = 1
                    async for raw in ws:
                        parsed = json.loads(raw)
                        # Subscription acknowledgements have a result/id and no event.
                        if "result" in parsed and "id" in parsed and "stream" not in parsed:
                            continue
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
    """Manages several small subscriptions instead of one huge subscribe payload."""

    def __init__(self, settings, on_event, symbols_per_connection=20):
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
        """Replace the current subscription set atomically from the scanner's view."""
        desired_symbols = sorted(set(symbols))

        # Stop existing connections before applying the new universe.
        await self.stop_all()
        if self.stop:
            return

        # One tiny all-market ticker stream gives live 24h stats and does not need
        # a symbol list. It is kept in its own connection.
        ticker = MarketWSConnection(
            self.s,
            ["!miniTicker@arr"],
            self.on_event,
            "ticker",
        )
        self.clients.append(ticker)
        self.tasks.append(asyncio.create_task(ticker.run()))

        for idx, chunk in enumerate(self._chunks(desired_symbols, self.symbols_per_connection), start=1):
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
            "Market WS: %d symbols split across %d symbol connections (+ ticker)",
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


# Backward-compatible helper for callers that only need the stream names.
def streams(symbols):
    return ["!miniTicker@arr"] + symbol_streams(symbols)
