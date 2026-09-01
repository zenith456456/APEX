import uuid
from datetime import datetime, timezone
import numpy as np
from indicators import atr,bos,condition,fingerprint,rvol,sweep,trend
from models import Direction, Score, Signal

class SignalEngine:
    def __init__(self,s,news):self.s=s;self.news=news
    def analyze(self,m,btc):
        rows=m.klines.get('15m',[])
        if len(rows)<60 or m.last<=0:return None
        a=np.asarray(rows,float); h,l,c,v=a[:,2],a[:,3],a[:,4],a[:,5]
        tr=trend(c); direction=Direction.LONG if tr>0 else Direction.SHORT if tr<0 else None
        if direction is None:return None
        cond=condition(c); bscore,breason=bos(h,l,c); sscore,sreason=sweep(h,l,c)
        rv=rvol(v); vscore=15 if rv>=1.8 else 11 if rv>=1.35 else 7 if rv>=1.05 else 2
        trscore=10 if tr else 4
        of_ratio=m.buy_qty/max(m.sell_qty,1e-9); of_dir=1 if of_ratio>1.15 else -1 if of_ratio<0.87 else 0
        book=m.bid_qty/max(m.ask_qty,1e-9); book_dir=1 if book>1.15 else -1 if book<0.87 else 0
        if of_dir and of_dir!=tr:return None
        ofscore=10 if of_dir==tr else 6 if of_dir else 3
        if book_dir==tr:ofscore=min(10,ofscore+2)
        oiscore=5 if m.oi>0 else 2
        fscore=5 if abs(m.funding)<0.0007 else 3 if abs(m.funding)<0.0015 else 1
        btcscore=0
        if btc and len(btc.klines.get('15m',[]))>=60:
            bc=np.asarray(btc.klines['15m'],float)[:,4]; bt=trend(bc); btcscore=3 if bt==tr else 2 if bt==0 else 0
        if self.news.conflict(m.symbol):return None
        mascore={'STRONG BULL':10,'STRONG BEAR':10,'NORMAL MARKET':8,'HIGH VOLATILITY':7,'CHOPPY / SIDEWAYS':2}.get(cond,5)
        pascore=bscore + (0 if bscore else 8)
        pascore=min(20,pascore)
        obscore=10 if abs(c[-1]-a[-1,1])>=0.3*atr(h,l,c) else 6
        total=Score(mascore,pascore,vscore,trscore,sscore,obscore,ofscore,oiscore,fscore,btcscore,2).total
        if total<self.s.score_threshold:return None
        if cond=='CHOPPY / SIDEWAYS':return None
        vol=atr(h,l,c)/c[-1]
        if vol<=0:return None
        entry_mid=c[-1]*(1-vol/2 if direction==Direction.LONG else 1+vol/2)
        band=max(c[-1]*0.001,atr(h,l,c)*0.12)
        entry_low=entry_mid-band; entry_high=entry_mid+band
        atrv=atr(h,l,c)
        if direction==Direction.LONG:
            stop=float(min(np.min(l[-8:]),entry_low-0.35*atrv)); risk=entry_high-stop
            if risk<=0:return None
            tps=[entry_high+3*risk,entry_high+4*risk,entry_high+5*risk]
        else:
            stop=float(max(np.max(h[-8:]),entry_high+0.35*atrv)); risk=stop-entry_low
            if risk<=0:return None
            tps=[entry_low-3*risk,entry_low-4*risk,entry_low-5*risk]
        rr=abs(tps[-1]-((entry_low+entry_high)/2))/risk
        if rr<self.s.min_rr:return None
        fp=fingerprint(m.symbol,direction.value,'15m',c)
        reasons=[breason or 'Market structure aligned',f'Strong RVOL ({rv:.2f}x)' if rv>=1.35 else 'Volume confirmed',sreason or 'Liquidity condition monitored','Order block/FVG proxy aligned','Order flow aligned','Open Interest available','Funding not overcrowded' if fscore>=3 else 'Funding elevated','BTC trend aligned' if btcscore==3 else 'BTC context neutral','No detected high-impact news conflict']
        trade='SCALP' if vol>0.018 else 'DAY TRADE' if vol>0.008 else 'SWING'
        lev={'SCALP':5,'DAY TRADE':3,'SWING':2}[trade]
        holding={'SCALP':'15–90 Minutes','DAY TRADE':'2–12 Hours','SWING':'1–5 Days'}[trade]
        valid={'SCALP':'30 Minutes','DAY TRADE':'2 Hours','SWING':'12 Hours'}[trade]
        rnd=lambda x:round(float(x),8) if x<1 else round(float(x),4) if x<100 else round(float(x),1)
        return Signal(str(uuid.uuid4()),0,m.symbol,direction,trade,cond,'15M','5M','1H',rnd(entry_low),rnd(entry_high),rnd(stop),[rnd(x) for x in tps],lev,rr,holding,valid,total,reasons,fp,datetime.now(timezone.utc).isoformat(),Score(mascore,pascore,vscore,trscore,sscore,obscore,ofscore,oiscore,fscore,btcscore,2))
