"""
IDS 13-layer scoring pipeline. Pure Python stdlib only.
Returns signal dict when AI score >= threshold, else None.
"""
import config


def _sma(v, p):
    if not v: return 0.0
    p = min(p, len(v))
    return sum(v[-p:]) / p

def _ema(v, p):
    if not v: return 0.0
    k = 2.0/(p+1); e = v[0]
    for x in v[1:]: e = x*k + e*(1-k)
    return e

def _atr(candles, p=14):
    trs = [max(c["h"]-c["l"], abs(c["h"]-candles[i-1]["c"]), abs(c["l"]-candles[i-1]["c"]))
           for i,c in enumerate(candles) if i > 0]
    return _sma(trs, p) if trs else 0.01

def _rsi(closes, p=14):
    if len(closes) < p+1: return 50.0
    g = [max(closes[i]-closes[i-1], 0) for i in range(1,len(closes))]
    l = [max(closes[i-1]-closes[i], 0) for i in range(1,len(closes))]
    ag, al = _sma(g,p), _sma(l,p)
    return 100.0 if al==0 else 100-(100/(1+ag/al))

def _detect_bos(candles):
    if len(candles) < 10: return False, "NONE"
    w = candles[-20:]
    sh = max(c["h"] for c in w[:-3])
    sl = min(c["l"] for c in w[:-3])
    lc = candles[-1]["c"]
    if lc > sh: return True, "LONG"
    if lc < sl: return True, "SHORT"
    return False, "NONE"

def _compression(candles, lb=15):
    r = candles[-lb:]
    return sum(abs(c["c"]-c["o"]) for c in r)/len(r) < _atr(candles)*0.35

def _cvd(candles, lb=10):
    return sum((1 if c["c"]>c["o"] else -1)*c["v"] for c in candles[-lb:])


class IDSPipeline:
    def evaluate(self, symbol, candles):
        if len(candles) < 50: return None

        closes  = [c["c"] for c in candles]
        volumes = [c["v"] for c in candles]
        last    = candles[-1]
        price   = last["c"]
        atr     = _atr(candles)
        scores  = {}

        # 1. Regime
        e21,e55,e200 = _ema(closes,21),_ema(closes,55),_ema(closes,200)
        rsi = _rsi(closes)
        if   price>e21>e55>e200 and rsi>55: regime,rs = "Strong Bull",    1.00
        elif price>e21>e55 and rsi>50:       regime,rs = "Normal Bull",    0.75
        elif price<e21<e55<e200 and rsi<45:  regime,rs = "Strong Bear",    1.00
        elif abs(price-e21)/(e21+1e-10)<0.015: regime,rs = "Choppy/Sideways",0.45
        elif rsi>70 or rsi<30:               regime,rs = "High Volatility", 0.65
        else:                                regime,rs = "Normal Market",   0.60
        scores["regime"] = rs

        bias = ("LONG" if "Bull" in regime else
                "SHORT" if "Bear" in regime else
                ("LONG" if closes[-1]>closes[-5] else "SHORT"))

        # 2. Price Action
        bos,bos_dir = _detect_bos(candles)
        compressed  = _compression(candles)
        rng  = last["h"]-last["l"]
        body = abs(last["c"]-last["o"])
        conv = body/rng if rng>0 else 0
        pa = (0.45 if bos else 0)+(0.30 if compressed else 0)+(0.25 if conv>0.60 else 0)
        scores["priceaction"] = min(pa, 1.0)
        if bos and bos_dir != "NONE": bias = bos_dir

        # 3. Volume
        va   = _sma(volumes,20); vl = last["v"]; vp10 = _sma(volumes[-11:-1],10)
        cvd  = _cvd(candles)
        cvd_ok = (cvd>0 and bias=="LONG") or (cvd<0 and bias=="SHORT")
        vol = (0.25 if vp10<va*0.6 else 0)+(0.40 if vl>=va*2.5 else 0)+(0.35 if cvd_ok else 0)
        scores["volume"] = min(vol, 1.0)

        # 4. Liquidity Sweep
        rh=[c["h"] for c in candles[-20:-1]]; rl=[c["l"] for c in candles[-20:-1]]
        sh,sl_=max(rh),min(rl)
        sweep = ((last["l"]<sl_ and last["c"]>sl_ and bias=="LONG") or
                 (last["h"]>sh  and last["c"]<sh  and bias=="SHORT"))
        scores["liquidity"] = 1.0 if sweep else 0.15

        # 5. Order Flow
        lw  = last["o"]-last["l"] if bias=="LONG" else last["h"]-last["o"]
        wr_ = lw/(rng+1e-10)
        agg = vl>va*1.5 and conv>0.5
        of  = (0.35 if wr_>0.35 else 0)+(0.35 if agg else 0)+(0.30 if cvd_ok else 0)
        scores["orderflow"] = min(of, 1.0)

        # 6. OI proxy
        scores["oi"] = min(_sma(volumes[-5:],5)/(_sma(volumes[-20:],20)+1e-10), 1.0)

        # 7. Funding proxy
        scores["funding"] = 1.0 if rsi<20 or rsi>80 else 0.90 if 35<=rsi<=65 else 0.55

        # 8. Liquidation Map proxy
        prior = candles[-2] if len(candles)>=2 else last
        pr    = prior["h"]-prior["l"]
        pw    = (prior["h"]-prior["c"]) if bias=="LONG" else (prior["c"]-prior["l"])
        scores["liquidation"] = min(pw/(pr+1e-10),1.0)*0.90

        # 9. BTC Correlation proxy
        scores["btccorr"] = 0.80 if rs>=0.75 else 0.60 if rs>=0.45 else 0.35

        # AI Score
        tw     = sum(config.LAYER_WEIGHTS.values())
        raw    = sum(scores.get(l,0.5)*w for l,w in config.LAYER_WEIGHTS.items())
        base   = (raw/tw)*100.0

        # R:R
        entry = price
        sl    = (entry-atr*1.5) if bias=="LONG" else (entry+atr*1.5)
        risk  = abs(entry-sl)
        if risk <= 0: return None

        tps = [round(entry+risk*n,8) if bias=="LONG" else round(entry-risk*n,8) for n in range(1,6)]
        rr  = max(round(atr*3/risk, 2), 1.0)

        boost    = 1.15 if rr>=6 else 1.08 if rr>=3 else 1.00
        ai_score = min(99.0, round(base*boost, 1))

        if ai_score < config.AI_SCORE_THRESHOLD: return None
        if rr        < config.MIN_RR:            return None

        sl_pct = round(abs(entry-sl)/entry*100, 2)
        band   = 0.002
        grade  = "A+" if ai_score>=90 else "A" if ai_score>=82 else "B" if ai_score>=75 else "C"

        if rr>=4: trade_type,lev,tf,etime = "Swing",    5,  "1H",  "2–8 H"
        elif rr>=2: trade_type,lev,tf,etime = "Day Trade",10, "15m", "30–90 min"
        else:     trade_type,lev,tf,etime = "Scalp",    15, "5m",  "15–45 min"

        return {
            "fires": True, "symbol": symbol, "side": bias,
            "regime": regime, "entry": round(entry,8),
            "entry_lo": round(entry*(1-band),8), "entry_hi": round(entry*(1+band),8),
            "sl": round(sl,8), "sl_pct": sl_pct, "tps": tps,
            "rr": rr, "ai_score": ai_score, "grade": grade,
            "trade_type": trade_type, "leverage": lev,
            "timeframe": tf, "expected_time": etime,
            "layer_scores": scores,
        }
