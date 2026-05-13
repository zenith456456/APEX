import asyncio
import json
import time
from typing import Callable, Dict
from binance import AsyncClient, BinanceSocketManager
from binance.exceptions import BinanceAPIException

class BinanceMarketScanner:
    def __init__(self, callback: Callable):
        """
        callback(symbol: str, data: dict) is called on each futures trade tick.
        The data dict contains: price, volume, timestamp, etc.
        """
        self.callback = callback
        self.client = None
        self.bm = None
        self.known_pairs = set()
        self.active_streams = {}

    async def start(self):
        self.client = await AsyncClient.create()
        self.bm = BinanceSocketManager(self.client)
        # Fetch all USDT perpetual futures pairs on startup
        await self._update_pairs()
        # Start a periodic pair checker (every 10 minutes) to spot new listings
        asyncio.create_task(self._refresh_pairs_periodic())
        # Start aggregated trade streams for all known pairs
        await self._subscribe_all()
        # Keep alive
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
                # Subscribe to the new pairs immediately
                await self._subscribe_pairs(new_pairs)
        except Exception as e:
            print(f"[Scanner] Error updating pairs: {e}")

    async def _refresh_pairs_periodic(self):
        while True:
            await asyncio.sleep(600)  # every 10 minutes
            await self._update_pairs()

    async def _subscribe_pairs(self, pairs):
        for symbol in pairs:
            # Use individual aggregated trade socket for each symbol to avoid message limits
            ts = self.bm.futures_symbol_ticker_socket(symbol=symbol)
            stream = ts
            self.active_streams[symbol] = stream

    async def _subscribe_all(self):
        # We can't open one combined stream for all due to payload limits, but we can batch.
        # For simplicity, we'll open one stream per pair using the symbol ticker socket.
        # This is lightweight (ticker only) – faster than aggregated trades.
        # For full order book depth you'd need depth streams, but we'll use price/volume.
        # Start a new task for each pair to consume messages.
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
                            'price': float(msg['c']),  # last close price
                            'volume': float(msg['v']*1),  # 24h volume, we can accumulate
                            'timestamp': int(msg['E'])
                        }
                        # Additional fields if needed
                        await self.callback(symbol, data)
                except Exception as e:
                    print(f"[Stream] Error on {symbol}: {e}")
                    await asyncio.sleep(5)
                    break  # will be reconnected by pair refresh