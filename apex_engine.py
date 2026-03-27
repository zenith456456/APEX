"""
APEX DEEP AI  —  5-LAYER SCORING ENGINE
FMT 22% | LVI 24% | WAS 20% | SEC 18% | NRF 16%
APEX = weighted composite. All 9 gates must pass to fire.
"""
import math, time
from dataclasses import dataclass
from typing import Optional
from config import TIERS, HIST_WR, TRADE_PRESETS

@dataclass
class TickData:
    symbol: str; price: float; open24: float; high: float; low: float
    vol_usd: float; pct: float; ts: float

@dataclass
class LayerScores:
    FMT: int=0; LVI: int=0; WAS: int=0; SEC: int=0; NRF: int=0; APEX: int=0
    vol_ratio: float=1.0; hurst_proxy: float=0.0
    gates_passed: int=0; all_gates: bool=False

@dataclass
class TradeParams:
    position: str; style: str; leverage: int
    entry_low: float; entry_high: float
    sl: float; tp1: float; tp2: float; tp3: float
    sl_pct: float; rr: float; expected_min: int; hist_wr: int

@dataclass
class Signal:
    symbol: str; price: float; vol_usd: float; pct: float
    direction: str; tier: str; layers: LayerScores; apex_score: int; ts_epoch: float
    trade: Optional[TradeParams]=None; is_new_listing: bool=False
    def coin(self): return self.symbol.replace("USDT","")
    def tier_meta(self): return TIERS.get(self.tier,{})

def _clamp(v,lo,hi): return max(lo,min(hi,v))
def _log2(x): return math.log2(x) if x>0 else 0.0

def fmt_price(p):
    if p<=0: return "0.00"
    if p<0.00001: return f"{p:.8f}"
    if p<0.001: return f"{p:.7f}"
    if p<0.01: return f"{p:.6f}"
    if p<0.1: return f"{p:.5f}"
    if p<1: return f"{p:.4f}"
    if p<10: return f"{p:.4f}"
    if p<1000: return f"{p:.3f}"
    if p<10000: return f"{p:.2f}"
    return f"{p:.1f}"

def fmt_vol(v):
    if v>=1e9: return f"${v/1e9:.2f}B"
    if v>=1e6: return f"${v/1e6:.2f}M"
    if v>=1e3: return f"${v/1e3:.0f}K"
    return f"${v:.0f}"

def score_bar(score,width=10):
    f=round(_clamp(score,0,100)/100*width)
    return "█"*f+"░"*(width-f)

def apex_grade(a):
    if a>=97: return "S+ ELITE"
    if a>=93: return "S  PRIME"
    if a>=89: return "A+ STRONG"
    if a>=85: return "A  SOLID"
    return "B  PASS"

def conviction_label(a):
    if a>=97: return "MAX CONVICTION  ████████████"
    if a>=93: return "HIGH CONVICTION ██████████░░"
    if a>=89: return "STRONG SIGNAL   ████████░░░░"
    return "STANDARD SIGNAL ██████░░░░░░"

def hold_str(m):
    if m<60: return f"~{m} min"
    h,r=divmod(m,60)
    return f"~{h}h {r:02d}m" if r else f"~{h}h"

class UniverseStats:
    def __init__(self,window=500): self._flows=[]; self._window=window
    def update(self,ticks):
        flows=[t.vol_usd*abs(t.pct) for t in ticks if abs(t.pct)>=5.0]
        if flows:
            self._flows.extend(flows)
            if len(self._flows)>self._window: self._flows=self._flows[-self._window:]
    @property
    def p99_flow(self):
        if not self._flows: return 1.0
        s=sorted(self._flows)
        return s[max(0,int(len(s)*0.99)-1)] or 1.0

class TradeCalculator:
    HOLD_TIMES={"scalp":7,"day":60,"swing":240}
    def calculate(self,tick,layers,tier,direction):
        apex=layers.APEX; price=tick.price; abs_pct=abs(tick.pct)
        style="swing" if (tier=="T4" and apex>=91) else "day" if (tier=="T4" or apex>=88) else "scalp"
        base_lev,base_sl,rr_t=TRADE_PRESETS.get((tier,style),(10,3.0,2.5))
        spread_pct=(tick.high-tick.low)/max(price,1e-12)*100
        atr_sl=_clamp(max(spread_pct*1.2,base_sl),base_sl*0.8,base_sl*1.6)
        lev=max(1,int(base_lev*(0.80+_clamp((apex-80)/20,0,1)*0.20)))
        pos="LONG" if direction=="PUMP" else "SHORT"
        if direction=="PUMP":
            el=price*(1-0.004); eh=price*(1+0.002); er=(el+eh)/2
            sl=er*(1-atr_sl/100); rp=(er-sl)/er*100
            tp1=er*(1+rp/100); tp2=er*(1+rp/100*rr_t); tp3=er*(1+rp/100*rr_t*1.6)
        else:
            el=price*(1-0.002); eh=price*(1+0.004); er=(el+eh)/2
            sl=er*(1+atr_sl/100); rp=(sl-er)/er*100
            tp1=er*(1-rp/100); tp2=er*(1-rp/100*rr_t); tp3=er*(1-rp/100*rr_t*1.6)
        actual_rr=abs(tp2-er)/max(abs(sl-er),1e-12)
        d_key="pump" if direction=="PUMP" else "dump"
        wr=HIST_WR.get(tier,{}).get(style,{}).get(d_key,80)
        return TradeParams(pos,style,lev,el,eh,sl,tp1,tp2,tp3,
                           round(atr_sl,2),round(actual_rr,2),self.HOLD_TIMES[style],wr)

class ApexEngine:
    GATES={"vol_min":500_000,"fmt_min":68,"lvi_min":68,"was_min":62,
           "sec_min":60,"nrf_min":60,"burst_min":1.5,"dir_min":0.45}
    def __init__(self):
        self.universe=UniverseStats(); self.calculator=TradeCalculator()
    def update_universe(self,ticks): self.universe.update(ticks)
    def classify_tier(self,abs_pct):
        if abs_pct>=20.0: return "T4"
        if abs_pct>=10.0: return "T3"
        return None
    def score(self,tick,history):
        if len(history)<3: return None
        abs_pct=abs(tick.pct); direction=1 if tick.pct>0 else -1
        prev4=history[-4:] if len(history)>=4 else history
        pv=[h.pct for h in prev4]+[tick.pct]
        deltas=[pv[i]-pv[i-1] for i in range(1,len(pv))]
        same_dir=sum(1 for d in deltas if d*direction>0)/max(len(deltas),1)
        FMT=int(_clamp(_clamp(abs_pct*2.9,0,58)+same_dir*40+(5 if abs_pct>=15 else 0),0,100))
        rv=[h.vol_usd for h in history[-20:]] or [tick.vol_usd]
        avg_vol=sum(rv)/len(rv); vol_ratio=tick.vol_usd/max(avg_vol,1.0)
        LVI=int(_clamp(_clamp(_log2(vol_ratio+1)*30,0,62)+_clamp((tick.vol_usd/4e6)*16,0,18)+(12 if vol_ratio>=2.5 else 0),0,100))
        flow=tick.vol_usd*abs_pct; flow_norm=flow/max(self.universe.p99_flow,1.0)
        vb=18 if tick.vol_usd>2e6 else 10 if tick.vol_usd>8e5 else 4
        pb=14 if abs_pct>=15 else 9 if abs_pct>=10 else 4
        WAS=int(_clamp(_clamp(flow_norm*52,0,52)+vb+pb,0,100))
        spread=(tick.high-tick.low)/max(tick.price,1e-12)
        comp=_clamp(1.0-spread*10,0,1); brk=abs_pct/(spread*100+0.001)
        SEC=int(_clamp(comp*60+_clamp(brk*3,0,28)+(10 if spread<0.025 else 0),0,100))
        pv0=history[-1].pct if history else 0.0; accel=tick.pct-pv0
        ac=_clamp(abs(accel)*7*(1.0 if accel*direction>0 else -0.5),-18,46)
        consist=sum(1 for h in prev4 if h.pct*direction>0)/max(len(prev4),1)
        NRF=int(_clamp(ac+consist*36+(14 if abs_pct>=12 else 6)+6,0,100))
        APEX=int(round(FMT*0.22+LVI*0.24+WAS*0.20+SEC*0.18+NRF*0.16))
        tier_id=self.classify_tier(abs_pct) or "T3"
        apex_min=TIERS[tier_id]["apex_gate"]; g=self.GATES
        gates=[tick.vol_usd>=g["vol_min"],FMT>=g["fmt_min"],LVI>=g["lvi_min"],
               WAS>=g["was_min"],SEC>=g["sec_min"],NRF>=g["nrf_min"],
               APEX>=apex_min,vol_ratio>=g["burst_min"],same_dir>=g["dir_min"]]
        return LayerScores(FMT,LVI,WAS,SEC,NRF,APEX,round(vol_ratio,2),round(same_dir,2),sum(gates),all(gates))
    def build_signal(self,tick,layers,is_new_listing=False):
        tier=self.classify_tier(abs(tick.pct)); direction="PUMP" if tick.pct>0 else "DUMP"
        trade=self.calculator.calculate(tick,layers,tier,direction)
        return Signal(tick.symbol,tick.price,tick.vol_usd,tick.pct,direction,tier,layers,layers.APEX,tick.ts,trade,is_new_listing)
