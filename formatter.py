"""Builds the full 11-field signal message + stats block for Telegram and Discord."""
import config

REGIME_EMOJI = {
    "Strong Bull":"🚀","Normal Bull":"📈","Normal Market":"📈",
    "Strong Bear":"🐻","Choppy/Sideways":"↔","High Volatility":"⚡",
}

def _fmt(p, sym=""):
    s = sym.upper()
    if "PEPE" in s or "SHIB" in s or p < 0.0001: return f"{p:.8f}"
    if p < 0.01: return f"{p:.6f}"
    if p < 1:    return f"{p:.4f}"
    if p < 100:  return f"{p:.3f}"
    return f"{p:.2f}"

def _bar(wr, w=10):
    f = round(wr/100*w)
    return "▓"*f + "░"*(w-f)

def _ps(pnl): return f"{'+' if pnl>=0 else ''}{pnl:.2f}R"


def build_telegram_text(signal, trade_num, stats):
    s   = signal; sym = s["symbol"]; fmt = lambda p: _fmt(p, sym)
    il  = s["side"]=="LONG"
    re  = REGIME_EMOJI.get(s["regime"],"📊")
    rr  = s["rr"]
    rrt = "ELITE 🏆" if rr>=6 else "GOOD ✅" if rr>=3 else "MIN ⚠"
    d,m,t = stats["daily"],stats["monthly"],stats["total"]
    tp  = stats["tp_buckets"]; slc = stats["sl_count"]

    lines = [
        "╔══════════════════════════════════╗",
        f"║  IDS SIGNAL   #{str(trade_num).zfill(4)}               ║",
        "╚══════════════════════════════════╝",
        "",
        f"{'🟢 LONG' if il else '🔴 SHORT'}  •  {sym}",
        "",
        f"① Pair           {sym}",
        f"② Entry Zone     {fmt(s['entry_lo'])} – {fmt(s['entry_hi'])}   [LIMIT ORDER]",
        f"③ Position       {'BUY / LONG' if il else 'SELL / SHORT'}",
        f"④ Leverage       {s['leverage']}x",
        "",
        "⑤ Take Profit Targets:",
    ]
    for i, tp_p in enumerate(s["tps"]):
        sz = int(config.TP_WEIGHTS[i]*100)
        lines.append(f"   {config.TP_LABELS[i]}   {fmt(tp_p):<16}  1:{i+1}R   ({sz}% size)")
    lines += [
        "",
        f"⑥ Stop Loss      {fmt(s['sl'])}   (-{s['sl_pct']}%)",
        "",
        f"⑦ Trade Type     {s['trade_type']}",
        f"⑧ Risk:Reward    1 : {rr:.2f}   {rrt}",
        f"⑨ Timeframe      {s['timeframe']}",
        f"⑩ Est. Time      {s['expected_time']}",
        "",
        f"⑪ Market         {re} {s['regime']}",
        "",
        f"AI Score   {s['ai_score']:.1f}/100   [{s['grade']}]",
        "",
        "━━━━━━━━━  PERFORMANCE  ━━━━━━━━━",
        "",
        "📊 Win Rate",
        f"   Today    {d['wr']:.1f}%  {_bar(d['wr'])}",
        f"   Monthly  {m['wr']:.1f}%  {_bar(m['wr'])}",
        f"   Total    {t['wr']:.1f}%  {_bar(t['wr'])}",
        "",
        "💰 PNL (R-multiples)",
        f"   Today    {_ps(d['pnl'])}",
        f"   Monthly  {_ps(m['pnl'])}",
        f"   Total    {_ps(t['pnl'])}",
        "",
        "Wins / Losses",
        f"   Today    {d['wins']}W  /  {d['losses']}L",
        f"   Monthly  {m['wins']}W  /  {m['losses']}L",
        f"   Total    {t['wins']}W  /  {t['losses']}L",
        "",
        "🏆 Exit Distribution  (final level — mutually exclusive)",
        f"   TP1 only  {tp[0]}     TP2 only  {tp[1]}     TP3 only  {tp[2]}",
        f"   TP4 only  {tp[3]}     TP5 all   {tp[4]}     SL hit    {slc}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "IDS v2.0  •  Ignition Detection System",
    ]
    return "\n".join(lines)


def build_discord_embed(signal, trade_num, stats):
    s   = signal; sym = s["symbol"]; fmt = lambda p: _fmt(p, sym)
    il  = s["side"]=="LONG"
    re  = REGIME_EMOJI.get(s["regime"],"📊")
    rr  = s["rr"]
    d,m,t = stats["daily"],stats["monthly"],stats["total"]
    tp  = stats["tp_buckets"]; slc = stats["sl_count"]

    tp_block = "\n".join(
        f"`{config.TP_LABELS[i]}` {fmt(tp_p)} — 1:{i+1}R  ({int(config.TP_WEIGHTS[i]*100)}%)"
        for i, tp_p in enumerate(s["tps"])
    )
    embed = {
        "title": f"{'🟢' if il else '🔴'}  {sym}  {s['side']}  —  Trade #{str(trade_num).zfill(4)}",
        "color": 0x00FF88 if il else 0xFF2055,
        "description": f"**AI Score: {s['ai_score']:.1f}/100  [{s['grade']}]**\n{re} {s['regime']}",
        "fields": [
            {"name":"① Pair",          "value":sym,                                              "inline":True},
            {"name":"② Entry [LIMIT]", "value":f"`{fmt(s['entry_lo'])} – {fmt(s['entry_hi'])}`","inline":True},
            {"name":"③ Position",      "value":f"**{'BUY / LONG' if il else 'SELL / SHORT'}**", "inline":True},
            {"name":"④ Leverage",      "value":f"{s['leverage']}x",                             "inline":True},
            {"name":"⑤ Take Profits",  "value":tp_block,                                        "inline":False},
            {"name":"⑥ Stop Loss",     "value":f"`{fmt(s['sl'])}` (-{s['sl_pct']}%)",          "inline":True},
            {"name":"⑦ Type",          "value":s["trade_type"],                                  "inline":True},
            {"name":"⑧ R:R",           "value":f"1 : {rr:.2f}",                                "inline":True},
            {"name":"⑨ Timeframe",     "value":s["timeframe"],                                   "inline":True},
            {"name":"⑩ Est. Time",     "value":s["expected_time"],                               "inline":True},
            {"name":"⑪ Market",        "value":f"{re} {s['regime']}",                           "inline":True},
            {"name":"📊 Win Rate",
             "value":f"Today `{d['wr']:.1f}%` | Monthly `{m['wr']:.1f}%` | Total `{t['wr']:.1f}%`","inline":False},
            {"name":"💰 PNL (R)",
             "value":f"Today `{_ps(d['pnl'])}` | Monthly `{_ps(m['pnl'])}` | Total `{_ps(t['pnl'])}`","inline":False},
            {"name":"Wins / Losses",   "value":f"✅ `{t['wins']}W`  ❌ `{t['losses']}L`",       "inline":True},
            {"name":"🏆 TP Distribution",
             "value":f"TP1:`{tp[0]}`  TP2:`{tp[1]}`  TP3:`{tp[2]}`  TP4:`{tp[3]}`  TP5:`{tp[4]}`  SL:`{slc}`",
             "inline":False},
        ],
        "footer":{"text":"IDS v2.0  •  Ignition Detection System"},
    }
    return {"content":"","embed":embed}
