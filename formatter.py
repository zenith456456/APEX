"""
APEX SIGNAL FORMATTER
Builds complete Telegram HTML and Discord Embed messages.
All 9 signal fields + APEX Deep AI score section.
"""
import time, datetime
from typing import Optional
from apex_engine import (Signal, TradeParams, fmt_price, fmt_vol, score_bar,
                          apex_grade, conviction_label, hold_str)
from config import HIST_WR

LAYER_META = [
    ("FMT","◈","Fractal Momentum Tensor"),
    ("LVI","◉","Liquidity Vacuum Index"),
    ("WAS","◆","Whale Accumulation Signature"),
    ("SEC","◐","Spectral Entropy Collapse"),
    ("NRF","◑","Neural Resonance Field"),
]
STYLE_META = {
    "scalp": ("⚡","SCALP","5–15 min"),
    "day":   ("☀","DAY","30–120 min"),
    "swing": ("🌊","SWING","2–8 hours"),
}
DIV  = "─"*36
HDIV = "━"*36

def _utc(): return datetime.datetime.utcnow().strftime("%Y-%m-%d  %H:%M:%S UTC")

def _pct_from(price, target, position):
    if position=="LONG": return (target-price)/price*100
    return (price-target)/price*100

# ── TELEGRAM ─────────────────────────────────────────────────
def telegram_signal(sig):
    t=sig.tier_meta(); ti=t.get("icon","🔥"); tr=sig.trade
    dir_icon="🚀" if sig.direction=="PUMP" else "📉"
    pos_icon="🟢" if tr.position=="LONG"  else "🔴"
    si,sl,_=STYLE_META.get(tr.style,("⚡","SCALP",""))
    new_flag="\n🆕  <b>NEW LISTING DETECTED</b>\n" if sig.is_new_listing else ""
    tp1_pct=_pct_from(sig.price,tr.tp1,tr.position)
    tp2_pct=_pct_from(sig.price,tr.tp2,tr.position)
    tp3_pct=_pct_from(sig.price,tr.tp3,tr.position)
    sl_pct =abs(_pct_from(sig.price,tr.sl,"SHORT" if tr.position=="LONG" else "LONG"))
    layers=""
    for name,icon,_ in LAYER_META:
        s=getattr(sig.layers,name); bar=score_bar(s,10)
        ok="✅" if s>=68 else "⚠️" if s>=55 else "❌"
        layers+=f"\n<code>{icon} {name}  {s:3d}/100  {bar}  {ok}</code>"
    return (
        f"{HDIV}\n"
        f"{ti} <b>T{sig.tier[1]} {t.get('label','').upper()} SIGNAL</b>  {ti}{new_flag}\n"
        f"{HDIV}\n\n"
        f"{dir_icon} <b>{sig.coin()}/USDT</b>  {dir_icon}  <b>{sig.pct:+.2f}%</b>  ·  {si} <b>{sl}</b> Trade\n\n"
        f"<code>📌 ① Pair      :  {sig.coin()}/USDT  (Binance Futures)</code>\n"
        f"<code>💧 Vol 24H    :  {fmt_vol(sig.vol_usd)}</code>\n"
        f"<code>🕐 Time       :  {_utc()}</code>\n"
        f"\n{DIV}\n"
        f"{pos_icon} <b>③ POSITION</b>\n"
        f"<code>Direction    :  {tr.position}</code>\n"
        f"<code>Bias         :  {'Bullish breakout' if sig.direction=='PUMP' else 'Bearish breakdown'}</code>\n"
        f"\n{DIV}\n"
        f"🎯 <b>② ENTRY ZONE  (Limit Order)</b>\n"
        f"<code>Low          :  ${fmt_price(tr.entry_low)}</code>\n"
        f"<code>High         :  ${fmt_price(tr.entry_high)}</code>\n"
        f"<code>Ref Price    :  ${fmt_price(sig.price)}  (current)</code>\n"
        f"<code>⚠ Use LIMIT order — NOT market order</code>\n"
        f"\n{DIV}\n"
        f"⚙️ <b>④ LEVERAGE</b>\n"
        f"<code>Recommended  :  {tr.leverage}×</code>\n"
        f"<code>Max safe     :  {min(tr.leverage+5,25)}×  (risk increases above this)</code>\n"
        f"<code>Risk/trade   :  1–2% of account balance</code>\n"
        f"\n{DIV}\n"
        f"💰 <b>⑤ TAKE PROFIT TARGETS</b>\n"
        f"<code>TP1 🟡  ${fmt_price(tr.tp1)}  ({tp1_pct:+.2f}%)  Close 30%</code>\n"
        f"<code>TP2 🟢  ${fmt_price(tr.tp2)}  ({tp2_pct:+.2f}%)  Close 50%</code>\n"
        f"<code>TP3 🔵  ${fmt_price(tr.tp3)}  ({tp3_pct:+.2f}%)  Close 20%</code>\n"
        f"\n{DIV}\n"
        f"🛑 <b>⑥ STOP LOSS</b>\n"
        f"<code>SL Price     :  ${fmt_price(tr.sl)}</code>\n"
        f"<code>Distance     :  -{sl_pct:.2f}% from entry</code>\n"
        f"<code>⚠ Hard stop — no manual override</code>\n"
        f"\n{DIV}\n"
        f"{si} <b>⑦ TRADE TYPE  :  {sl}</b>\n"
        f"<code>Category     :  {sl} Trade</code>\n"
        f"<code>Hist WR      :  {tr.hist_wr}%  (APEX backtest)</code>\n"
        f"<code>Strategy     :  {'Quick momentum capture' if tr.style=='scalp' else 'Intraday trend follow' if tr.style=='day' else 'Multi-hour swing move'}</code>\n"
        f"\n{DIV}\n"
        f"⚖️ <b>⑧ RISK : REWARD</b>\n"
        f"<code>R:R          :  1 : {tr.rr:.2f}</code>\n"
        f"<code>Risk (SL)    :  {tr.sl_pct:.2f}%</code>\n"
        f"<code>Reward TP2   :  {tr.sl_pct*tr.rr:.2f}%</code>\n"
        f"<code>Reward TP3   :  {tr.sl_pct*tr.rr*1.6:.2f}%</code>\n"
        f"\n{DIV}\n"
        f"⏱ <b>⑨ EXPECTED DURATION</b>\n"
        f"<code>Hold time    :  {hold_str(tr.expected_min)}</code>\n"
        f"<code>Review at    :  +{tr.expected_min//2} min  (check TP1)</code>\n"
        f"\n{HDIV}\n"
        f"🧠 <b>─── APEX SCORE ───</b>\n"
        f"{HDIV}\n"
        f"<code>APEX   :  {sig.apex_score}/100   {score_bar(sig.apex_score,14)}</code>\n"
        f"<code>Grade  :  {apex_grade(sig.apex_score)}</code>\n"
        f"<code>Mode   :  {conviction_label(sig.apex_score)}</code>\n"
        f"{layers}\n\n"
        f"<code>Gates  :  {sig.layers.gates_passed}/9 passed</code>\n"
        f"<code>Burst  :  {sig.layers.vol_ratio:.2f}×  avg volume</code>\n"
        f"<code>Hurst  :  {sig.layers.hurst_proxy:.2f}  (>=0.45 = trend)</code>\n"
        f"{HDIV}\n"
        f"<i>⚠ Not financial advice · Always use stop loss · Manage your risk</i>\n"
        f"<code>APEX SYSTEM™  ·  {_utc()}</code>"
    )

def telegram_new_listing(symbol):
    coin=symbol.replace("USDT","")
    return (f"{HDIV}\n🆕🆕 <b>NEW FUTURES LISTING</b> 🆕🆕\n{HDIV}\n\n"
            f"<code>Pair    :  {coin}/USDT  (Binance Futures)</code>\n"
            f"<code>Status  :  Now ACTIVE — perpetual contract live</code>\n"
            f"<code>Time    :  {_utc()}</code>\n\n"
            f"⚡ Scanner now monitoring <b>{coin}/USDT</b> for T3 🔥 and T4 ⭐ signals.\n"
            f"New listings often see extreme volatility in the first 1–6 hours.\n\n"
            f"<i>APEX SYSTEM™</i>")

def telegram_stats(stats, uptime_sec):
    h=int(uptime_sec//3600); m=int((uptime_sec%3600)//60); s=int(uptime_sec%60)
    def rr(f,r): t=f+r; return f"{r/t*100:.0f}% rejected" if t>0 else "n/a"
    t3f=stats.get("t3_fired",0); t3r=stats.get("t3_rejected",0)
    t4f=stats.get("t4_fired",0); t4r=stats.get("t4_rejected",0)
    last=stats.get("last_signal_ts")
    last_s="none yet"
    if last:
        ago=int(time.time()-last); last_s=f"{ago//60}m {ago%60}s ago"
    return (f"📡 <b>APEX BOT — SESSION STATS</b>\n\n"
            f"<code>Uptime       :  {h:02d}:{m:02d}:{s:02d}</code>\n"
            f"<code>Pairs live   :  {stats.get('pairs_live',0)}</code>\n"
            f"<code>WS frames    :  {stats.get('frames_total',0):,}</code>\n"
            f"<code>Reconnects   :  {stats.get('ws_reconnects',0)}</code>\n"
            f"<code>New listings :  {stats.get('new_listings_seen',0)}</code>\n"
            f"<code>Last signal  :  {last_s}</code>\n\n"
            f"🔥 <b>T3 STRONG (>=10%)</b>\n"
            f"<code>  Fired    :  {t3f}</code>\n"
            f"<code>  Rejected :  {t3r}  ({rr(t3f,t3r)})</code>\n\n"
            f"⭐ <b>T4 MEGA (>=20%)</b>\n"
            f"<code>  Fired    :  {t4f}</code>\n"
            f"<code>  Rejected :  {t4r}  ({rr(t4f,t4r)})</code>\n\n"
            f"<i>High rejection rate = higher win rate</i>")

def telegram_winrates():
    lines=["📈 <b>APEX Historical Win Rates</b>  (backtest)\n"]
    for tier in ["T3","T4"]:
        label="🔥 T3 STRONG (>=10%)" if tier=="T3" else "⭐ T4 MEGA (>=20%)"
        lines.append(f"\n<b>{label}</b>")
        for style,(icon,lbl,hold) in STYLE_META.items():
            wp=HIST_WR[tier][style]["pump"]; wd=HIST_WR[tier][style]["dump"]
            lines.append(f"<code>{icon} {lbl:5s}  🚀 Pump: {wp}%   📉 Dump: {wd}%   Hold: {hold}</code>")
    lines.append("\n<i>Historical reference. Not a guarantee.</i>")
    return "\n".join(lines)

def telegram_recent_signals(signals):
    if not signals:
        return "📭 <b>No signals fired yet this session.</b>\n\n<i>APEX is scanning — signals fire when T3/T4 moves pass all 9 gates.</i>"
    lines=[f"📋 <b>RECENT SIGNALS</b>  (last {min(len(signals),10)})\n"]
    for sig in list(signals)[:10]:
        t=sig.tier_meta(); ago=int(time.time()-sig.ts_epoch)
        d="🚀" if sig.direction=="PUMP" else "📉"
        si,sl,_=STYLE_META.get(sig.trade.style,("⚡","SCALP",""))
        lines.append(f"{t.get('icon','🔥')} <code>{sig.coin():10s}</code>  {d} <code>{sig.pct:+.1f}%</code>  "
                     f"APEX <code>{sig.apex_score}</code>  {si} <code>{sl}</code>  "
                     f"R:R <code>1:{sig.trade.rr}</code>  <i>{ago//60}m ago</i>")
    return "\n".join(lines)

def telegram_help():
    return ("🧠 <b>APEX SYSTEM™  —  Bot Guide</b>\n\n"
            "<b>Commands:</b>\n"
            "/start      Activate signals for this chat\n"
            "/stop       Pause signals\n"
            "/stats      Session statistics\n"
            "/status     Connection status\n"
            "/signals    Last 10 signals fired\n"
            "/winrates   Historical win rate table\n"
            "/help       This message\n\n"
            "<b>Signal Tiers:</b>\n"
            "🔥 T3 STRONG  >=10% 24H move  ·  8–25 signals/day\n"
            "⭐ T4 MEGA    >=20% 24H move  ·  2–8  signals/day\n\n"
            "<b>Each signal includes:</b>\n"
            "① Pair  ② Entry (limit)  ③ Position  ④ Leverage\n"
            "⑤ TP1/TP2/TP3  ⑥ Stop loss  ⑦ Trade type\n"
            "⑧ R:R  ⑨ Expected time  +  APEX AI score\n\n"
            "<i>Not financial advice. Always use stop loss.</i>")

# ── DISCORD ───────────────────────────────────────────────────
def discord_embed(sig):
    t=sig.tier_meta(); ti=t.get("icon","🔥"); tr=sig.trade
    si,sl,hold=STYLE_META.get(tr.style,("⚡","SCALP",""))
    color=(0x00FFD1 if sig.tier=="T4" else 0x34D399) if sig.direction=="PUMP" else (0xFF3366 if sig.tier=="T4" else 0xFF6B35)
    pos_icon="🟢" if tr.position=="LONG" else "🔴"
    tp1_pct=_pct_from(sig.price,tr.tp1,tr.position)
    tp2_pct=_pct_from(sig.price,tr.tp2,tr.position)
    tp3_pct=_pct_from(sig.price,tr.tp3,tr.position)
    sl_pct=abs(_pct_from(sig.price,tr.sl,"SHORT" if tr.position=="LONG" else "LONG"))
    layer_lines=[]
    for name,icon,_ in LAYER_META:
        s=getattr(sig.layers,name); bar=score_bar(s,8)
        ok="✅" if s>=68 else "⚠️" if s>=55 else "❌"
        layer_lines.append(f"`{icon} {name}  {s:3d}  {bar}` {ok}")
    new_tag="  🆕 NEW LISTING" if sig.is_new_listing else ""
    title=f"{ti} {sig.tier} {t.get('label','')}  {'🚀' if sig.direction=='PUMP' else '📉'}  {sig.coin()}/USDT  {sig.pct:+.2f}%  {si} {sl}{new_tag}"
    description=(f"**APEX Score: {sig.apex_score}/100**  `{score_bar(sig.apex_score,14)}`  **{apex_grade(sig.apex_score)}**\n"
                 f"> Vol: `{fmt_vol(sig.vol_usd)}`  ·  Price: `${fmt_price(sig.price)}`  ·  {_utc()}")
    fields=[
        {"name":"📌 ① Coin Pair",      "value":f"`{sig.coin()}/USDT`  (Binance Futures Perpetual)",            "inline":True},
        {"name":"🎯 ② Entry Zone",     "value":f"`${fmt_price(tr.entry_low)}` → `${fmt_price(tr.entry_high)}`\n⚠ Limit order only","inline":True},
        {"name":f"{pos_icon} ③ Position","value":f"`{tr.position}`  {'Bullish breakout' if sig.direction=='PUMP' else 'Bearish breakdown'}","inline":True},
        {"name":"⚙️ ④ Leverage",       "value":f"`{tr.leverage}×`  (max safe `{min(tr.leverage+5,25)}×`)\nRisk 1–2% of balance","inline":True},
        {"name":"💰 ⑤ Take Profit",    "value":(f"🟡 TP1: `${fmt_price(tr.tp1)}`  ({tp1_pct:+.2f}%)  30%\n"
                                                  f"🟢 TP2: `${fmt_price(tr.tp2)}`  ({tp2_pct:+.2f}%)  50%\n"
                                                  f"🔵 TP3: `${fmt_price(tr.tp3)}`  ({tp3_pct:+.2f}%)  20%"),"inline":False},
        {"name":"🛑 ⑥ Stop Loss",      "value":f"`${fmt_price(tr.sl)}`  (-{sl_pct:.2f}% from entry)\n⚠ Hard stop — no override","inline":True},
        {"name":f"{si} ⑦ Trade Type",  "value":f"`{sl} Trade`\nHist WR: **{tr.hist_wr}%**  ·  Hold: {hold_str(tr.expected_min)}","inline":True},
        {"name":"⚖️ ⑧ R:R",            "value":f"`1 : {tr.rr:.2f}`\nRisk {tr.sl_pct:.2f}%  ·  Reward TP2 {tr.sl_pct*tr.rr:.2f}%","inline":True},
        {"name":"⏱ ⑨ Expected Time",   "value":f"`{hold_str(tr.expected_min)}`  ·  review at +{tr.expected_min//2} min","inline":True},
        {"name":"🧠 ─── APEX SCORE ───","value":"\n".join(layer_lines)+f"\n`Gates: {sig.layers.gates_passed}/9`  `Burst: {sig.layers.vol_ratio:.2f}x`  `Hurst: {sig.layers.hurst_proxy:.2f}`","inline":False},
    ]
    return {"title":title,"description":description,"color":color,"fields":fields,
            "footer":{"text":"APEX SYSTEM™  ·  Not financial advice  ·  Always use stop loss"}}

def discord_new_listing(symbol):
    coin=symbol.replace("USDT","")
    return (f"## 🆕 New Futures Listing: **{coin}/USDT**\n"
            f"> Status: Now ACTIVE — Binance Futures Perpetual\n"
            f"> Time: {_utc()}\n\n"
            f"APEX scanner is now monitoring **{coin}/USDT** for T3 🔥 and T4 ⭐ signals.")

def discord_stats(stats, uptime_sec):
    h=int(uptime_sec//3600); m=int((uptime_sec%3600)//60); s=int(uptime_sec%60)
    def rr(f,r): t=f+r; return f"{r/t*100:.0f}%" if t>0 else "n/a"
    t3f=stats.get("t3_fired",0); t3r=stats.get("t3_rejected",0)
    t4f=stats.get("t4_fired",0); t4r=stats.get("t4_rejected",0)
    return (f"**📡 APEX Bot — Session Stats**\n```\n"
            f"Uptime       : {h:02d}:{m:02d}:{s:02d}\n"
            f"Pairs live   : {stats.get('pairs_live',0)}\n"
            f"WS Frames    : {stats.get('frames_total',0):,}\n"
            f"Reconnects   : {stats.get('ws_reconnects',0)}\n"
            f"New listings : {stats.get('new_listings_seen',0)}\n\n"
            f"T3 STRONG  Fired: {t3f:4d}  Rejected: {t3r:5d}  ({rr(t3f,t3r)} reject)\n"
            f"T4 MEGA    Fired: {t4f:4d}  Rejected: {t4r:5d}  ({rr(t4f,t4r)} reject)\n"
            f"```\n*High rejection rate = higher win rate*")

def discord_recent_signals(signals):
    if not signals:
        return "📭 **No signals fired yet this session.**\n> Scanning — signals fire when T3/T4 moves pass all 9 gates."
    lines=[f"**📋 Recent Signals** (last {min(len(signals),10)})"]
    for sig in list(signals)[:10]:
        t=sig.tier_meta(); ago=int(time.time()-sig.ts_epoch)
        d="🚀" if sig.direction=="PUMP" else "📉"
        si,sl,_=STYLE_META.get(sig.trade.style,("⚡","SCALP",""))
        lines.append(f"{t.get('icon','🔥')} `{sig.coin():10s}`  {d} `{sig.pct:+.1f}%`  APEX `{sig.apex_score}`  {si} `{sl}`  R:R `1:{sig.trade.rr}`  *{ago//60}m ago*")
    return "\n".join(lines)
