import asyncio, json, logging, time
import aiohttp
import websockets

log=logging.getLogger(__name__)

class Binance:
    def __init__(self, settings):
        self.s=settings

    async def ws_exchange_info(self):
        req={"id":f"ex-{int(time.time()*1000)}","method":"exchangeInfo","params":{}}
        async with websockets.connect(self.s.ws_api_url,ping_interval=20,ping_timeout=20,max_size=20_000_000) as ws:
            await ws.send(json.dumps(req))
            async for raw in ws:
                d=json.loads(raw)
                if d.get("id")==req["id"]:
                    if d.get("status") not in (None,200): raise RuntimeError(d)
                    return d.get("result",{})

    async def get_json(self,path,params=None):
        url=self.s.rest_url+path
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(url,params=params) as r:
                r.raise_for_status(); return await r.json()

    async def tickers(self): return await self.get_json("/fapi/v1/ticker/24hr")
    async def oi(self,symbol): return float((await self.get_json("/fapi/v1/openInterest",{"symbol":symbol}))["openInterest"])
    async def funding(self,symbol): return float((await self.get_json("/fapi/v1/premiumIndex",{"symbol":symbol}))["lastFundingRate"])
    async def klines(self,symbol,interval,limit): return await self.get_json("/fapi/v1/klines",{"symbol":symbol,"interval":interval,"limit":limit})

class MarketWS:
    def __init__(self,settings,on_event):
        self.s=settings; self.on_event=on_event; self.stop=False; self.ws=None
    async def run(self,streams):
        delay=1
        while not self.stop:
            try:
                async with websockets.connect(self.s.ws_stream_url,ping_interval=20,ping_timeout=20,max_size=50_000_000) as ws:
                    self.ws=ws
                    if streams:
                        await ws.send(json.dumps({"method":"SUBSCRIBE","params":streams,"id":1}))
                    delay=1
                    async for raw in ws:
                        await self.on_event(json.loads(raw).get("data",json.loads(raw)))
            except asyncio.CancelledError: raise
            except Exception as e:
                log.warning("Market WS disconnected: %s",e)
                await asyncio.sleep(delay); delay=min(delay*2,60)
    async def close(self):
        self.stop=True
        if self.ws: await self.ws.close()

def streams(symbols):
    out=["!miniTicker@arr"]
    for s in symbols:
        x=s.lower()
        out += [f"{x}@kline_1m",f"{x}@kline_5m",f"{x}@kline_15m",f"{x}@kline_1h",f"{x}@aggTrade",f"{x}@depth10@100ms"]
    return out
