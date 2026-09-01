import hashlib
import math
import numpy as np

def ema(x, n):
    if len(x) == 0: return x
    a = 2/(n+1)
    y = np.empty_like(x, dtype=float); y[0] = x[0]
    for i in range(1, len(x)): y[i] = a*x[i] + (1-a)*y[i-1]
    return y

def atr(h,l,c,n=14):
    if len(c) < n+1: return float(np.mean(h-l))
    pc=c[:-1]
    tr=np.maximum(h[1:]-l[1:], np.maximum(abs(h[1:]-pc), abs(l[1:]-pc)))
    return float(np.mean(tr[-n:]))

def rvol(v,n=20):
    if len(v)<n+1:return 1.0
    a=float(np.mean(v[-n-1:-1])); return float(v[-1]/a) if a>0 else 1.0

def trend(c):
    if len(c)<50:return 0
    e20,e50=ema(c,20)[-1],ema(c,50)[-1]
    return 1 if c[-1]>e20>e50 else -1 if c[-1]<e20<e50 else 0

def condition(c):
    if len(c)<50:return "NORMAL MARKET"
    e20,e50=ema(c,20)[-1],ema(c,50)[-1]
    vol=float(np.std(np.diff(np.log(c[-30:]+1e-12)))*math.sqrt(30))
    ret=abs(c[-1]/c[-10]-1)
    spread=abs(e20/e50-1)
    if vol>0.055:return "HIGH VOLATILITY"
    if e20>e50 and c[-1]>e20 and spread>0.006 and ret>0.01:return "STRONG BULL"
    if e20<e50 and c[-1]<e20 and spread>0.006 and ret>0.01:return "STRONG BEAR"
    if spread<0.0025:return "CHOPPY / SIDEWAYS"
    return "NORMAL MARKET"

def bos(h,l,c):
    if len(c)<30:return 0,""
    ph=float(np.max(h[-15:-2])); pl=float(np.min(l[-15:-2]))
    if c[-1]>ph:return 20,"Bullish BOS confirmed"
    if c[-1]<pl:return 20,"Bearish BOS confirmed"
    return 0,""

def sweep(h,l,c):
    if len(c)<30:return 0,""
    ph=float(np.max(h[-25:-2])); pl=float(np.min(l[-25:-2]))
    if l[-1]<pl and c[-1]>pl:return 10,"Bullish liquidity sweep completed"
    if h[-1]>ph and c[-1]<ph:return 10,"Bearish liquidity sweep completed"
    return 0,""

def fingerprint(symbol,direction,tf,c):
    x=f"{symbol}|{direction}|{tf}|{round(float(c[-1]),6)}|{round(float(np.max(c[-20:])),6)}|{round(float(np.min(c[-20:])),6)}"
    return hashlib.sha256(x.encode()).hexdigest()[:24]
