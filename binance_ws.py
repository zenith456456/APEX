import asyncio
import os
from typing import Callable
from binance import AsyncClient, BinanceSocketManager
import config

class BinanceMarketScanner:
    def __init__(self, callback: Callable):
        self.callback = callback
        self.client = None
        self.bm = None
        self.known_pairs = set()
        self.active_streams = {}

    async def start(self):
        # Prepare kwargs for AsyncClient
        client_kwargs = {}
        if config.BINANCE_PROXY:
            # AsyncClient will pass this to aiohttp
            client_kwargs["proxies"] = {
                "http": config.BINANCE_PROXY,
                "https": config.BINANCE_PROXY,
            }
        self.client = await AsyncClient.create(
            tld=config.BINANCE_TLD,
            **client_kwargs
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