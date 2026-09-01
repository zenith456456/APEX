import asyncio, json, logging, time
from models import Market
from binance import Binance, MarketWSManager
from db import DB
from engine import SignalEngine
from news import NewsFilter
from notifier import Notifier

log=logging.getLogger(__name__)

class Scanner:
    def __init__(self,s):
        self.s=s; self.api=Binance(s); self.db=DB(s.db_path); self.news=NewsFilter(s); self.engine=SignalEngine(s,self.news); self.notify=Notifier(s)
        self.market={}; self.symbols=set(); self.active=[]; self.ws_manager_client=None; self.stop=False; self.last_symbols=[]

    async def exchange_info(self):
        info=await self.api.exchange_info()
        self.symbols={x['symbol'] for x in info.get('symbols',[]) if x.get('status')=='TRADING' and x.get('quoteAsset')=='USDT' and x.get('contractType')=='PERPETUAL'}
        log.info('Exchange info: %s active USDT perpetuals',len(self.symbols))

    async def universe(self):
        tickers=await self.api.tickers(); good=[x for x in tickers if x.get('symbol') in self.symbols and float(x.get('quoteVolume',0))>=self.s.min_24h_quote_volume]; good.sort(key=lambda x:float(x.get('quoteVolume',0)),reverse=True)
        self.active=[x['symbol'] for x in good[:self.s.max_symbols]]
        if 'BTCUSDT' in self.symbols and 'BTCUSDT' not in self.active:self.active.append('BTCUSDT')
        for x in good:
            m=self.market.setdefault(x['symbol'],Market(x['symbol']));m.qvol=float(x.get('quoteVolume',0));m.change_pct=float(x.get('priceChangePercent',0))
        await self.seed_klines(self.active)

    async def seed_klines(self,symbols_):
        sem=asyncio.Semaphore(10)
        async def one(sym):
            async with sem:
                m=self.market.setdefault(sym,Market(sym))
                try:
                    for tf in ('1m','5m','15m','1h'):
                        rows=await self.api.klines(sym,tf,self.s.kline_limit);m.klines[tf]=[[float(r[0]),float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[5])] for r in rows];m.last=float(rows[-1][4]) if rows else m.last
                except Exception as e: log.debug('seed %s: %s',sym,e)
        await asyncio.gather(*(one(x) for x in symbols_))

    async def refresh_exchange(self):
        while not self.stop:
            try:await self.exchange_info()
            except Exception:log.exception('exchange info refresh failed')
            await asyncio.sleep(self.s.exchange_info_refresh)

    async def refresh_universe(self):
        while not self.stop:
            try:await self.universe()
            except Exception:log.exception('universe refresh failed')
            await asyncio.sleep(self.s.universe_refresh)

    async def refresh_fundamentals(self):
        while not self.stop:
            for sym in self.active:
                try:
                    m=self.market.setdefault(sym,Market(sym));m.oi,m.funding=await asyncio.gather(self.api.oi(sym),self.api.funding(sym))
                except Exception:pass
                await asyncio.sleep(.03)
            await asyncio.sleep(20)

    async def refresh_news(self):
        while not self.stop:
            await self.news.refresh(); await asyncio.sleep(self.s.news_refresh)

    async def ws_manager(self):
        self.ws_manager_client = MarketWSManager(
            self.s,
            self.on_event,
            symbols_per_connection=getattr(self.s, "ws_symbols_per_connection", 20),
        )
        while not self.stop:
            wanted = sorted(set(self.active))
            if wanted != self.last_symbols:
                self.last_symbols = wanted
                await self.ws_manager_client.apply(wanted)
            await asyncio.sleep(10)

    async def on_event(self,e):
        et=e.get('e')
        if et=='24hrMiniTicker':
            m=self.market.setdefault(e['s'],Market(e['s']));m.last=float(e['c']);m.qvol=float(e['q']);m.change_pct=float(e['P']);m.updated=e.get('E',0)
        elif et=='kline':
            k=e['k'];m=self.market.setdefault(e['s'],Market(e['s'])); row=[float(k['t']),float(k['o']),float(k['h']),float(k['l']),float(k['c']),float(k['v'])]; arr=m.klines.setdefault(k['i'],[])
            if arr and arr[-1][0]==row[0]:arr[-1]=row
            else:arr.append(row);del arr[:-self.s.kline_limit]
            m.last=row[4]
        elif et=='aggTrade':
            m=self.market.setdefault(e['s'],Market(e['s']));q=float(e['q']);m.sell_qty+=q if e.get('m') else 0;m.buy_qty+=0 if e.get('m') else q
            if m.buy_qty+m.sell_qty>1_000_000:m.buy_qty*=.5;m.sell_qty*=.5
        elif et=='depthUpdate':
            m=self.market.setdefault(e['s'],Market(e['s']));m.bid_qty=sum(float(x[1]) for x in e.get('b',[])[:10]);m.ask_qty=sum(float(x[1]) for x in e.get('a',[])[:10])

    async def analysis(self):
        while not self.stop:
            btc=self.market.get('BTCUSDT')
            for sym in list(self.active):
                if sym=='BTCUSDT':continue
                m=self.market.get(sym)
                if not m:continue
                try:sig=self.engine.analyze(m,btc)
                except Exception:continue
                if not sig:continue
                row=self.db.active(sym)
                if row:
                    if row['direction']!=sig.direction.value:
                        self.db.close(row,'DIRECTION_CHANGED','DIRECTION_CHANGED','BREAKEVEN',0)
                    else:
                        continue
                sig.trade_number=self.db.next_trade(); self.db.save(sig); await self.notify.send(sig,self.db.stats())
            await asyncio.sleep(self.s.analysis_interval)

    async def monitor(self):
        while not self.stop:
            for sym in list(self.active):
                row=self.db.active(sym);m=self.market.get(sym)
                if not row or not m or not m.last:continue
                price=m.last; tps=json.loads(row['tps']); side=row['direction']; entry=(row['entry_low']+row['entry_high'])/2; stop=row['stop']; highest=int(row['highest_tp'] or 0)
                if not row['entry_filled']:
                    if row['entry_low']<=price<=row['entry_high']:self.db.entry(row['id'])
                    continue
                nxt=highest+1
                if nxt<=len(tps):
                    hit=price>=tps[nxt-1] if side=='LONG' else price<=tps[nxt-1]
                    if hit:
                        self.db.tp(row['id'],nxt)
                        if nxt==len(tps):self.db.close(row,'CLOSED','FULL_TP','WIN',float(nxt+2))
                        continue
                sl=price<=stop if side=='LONG' else price>=stop
                if sl:
                    outcome='SL_BEFORE_TP' if highest==0 else f'TP{highest}_THEN_SL'; wl='LOSS' if highest==0 else 'WIN'; pnl=-1.0 if highest==0 else float(highest+2); self.db.close(row,'SL_HIT',outcome,wl,pnl)
            await asyncio.sleep(1)

    async def run(self):
        await self.exchange_info();await self.universe()
        tasks=[asyncio.create_task(x) for x in (self.refresh_exchange(),self.refresh_universe(),self.refresh_fundamentals(),self.refresh_news(),self.ws_manager(),self.analysis(),self.monitor())]
        try:await asyncio.Event().wait()
        finally:
            self.stop=True
            for t in tasks:t.cancel()
            if self.ws_manager_client:await self.ws_manager_client.close()
