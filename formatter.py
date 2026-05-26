"""
formatter.py ─ Telegram plain-text + Discord embed formatters
All 11 required signal fields included in every message.
"""
from stats_tracker import StatsTracker


def _f(n: float) -> str:
    if n >= 10000: return f"{n:,.2f}"
    if n >= 1000:  return f"{n:,.3f}"
    if n >= 10:    return f"{n:.4f}"
    if n >= 1:     return f"{n:.5f}"
    return f"{n:.6f}"

SEP = "━" * 30


def _css_label(css: float) -> str:
    if css >= 92: return "PRIME 🔥"
    if css >= 86: return "STRONG ✓"
    return "VALID"


# ── Telegram ─────────────────────────────────────────────────────

def tg_signal(sig: dict, stats: StatsTracker) -> str:
    s  = sig
    st = stats.snapshot()
    tp = st["tp"]
    is_long = s["direction"] == "LONG"

    tp_lines = ""
    for i, (price, rr) in enumerate(zip(s["tps"], s["rrs"])):
        mark = " ⭐" if i == 2 else (" 🔥" if i >= 3 else "")
        tp_lines += f"  ✅ TP{i+1} ({rr})  →  {_f(price)}{mark}\n"

    return (
        f"⚡ APEX-QUANT SIGNAL  #{s['trade_no']}\n"
        f"{SEP}\n"
        f"① Coin Pair      :  {s['pair']}\n"
        f"② Entry Zone     :  {_f(s['entry_low'])} – {_f(s['entry_high'])}\n"
        f"                    📌 LIMIT ORDER\n"
        f"③ Position       :  {'🟢 LONG  ▲' if is_long else '🔴 SHORT ▼'}\n"
        f"④ Leverage       :  {s['leverage']}×\n"
        f"{SEP}\n"
        f"⑥ Stop Loss      :  🛑 {_f(s['sl'])}\n"
        f"⑤ Take Profits   :\n"
        f"{tp_lines}"
        f"⑦ Trade Type     :  {s['trade_type']}\n"
        f"⑧ Best R:R       :  {s['rrs'][-1]}\n"
        f"⑨ Timeframe      :  {s['timeframe']}\n"
        f"⑩ Expected Time  :  ⏳ {s['eta']}\n"
        f"⑪ Market         :  {s['market_label']}\n"
        f"{SEP}\n"
        f"🎯 CSS Score      :  {s['css']}/100  [{_css_label(s['css'])}]\n"
        f"💯 Confidence    :  {s['confidence']}%\n"
        f"🕐 Time           :  {s['datetime']}\n"
        f"{SEP}\n"
        f"📊 PERFORMANCE STATS\n"
        f"{'─'*28}\n"
        f"Win Rate  │ Day: {st['daily']['wr']}%  │ Month: {st['monthly']['wr']}%  │ Total: {st['total']['wr']}%\n"
        f"PNL       │ Day: {st['daily']['pnl_str']}  │ Month: {st['monthly']['pnl_str']}  │ Total: {st['total']['pnl_str']}\n"
        f"W / L     │ {st['total']['wins']}W  /  {st['total']['losses']}L   (#{st['trade_count']} signals)\n"
        f"{'─'*28}\n"
        f"TP1 only: {tp['tp1']} ({tp['tp1_pct']}%)  "
        f"TP2: {tp['tp2']} ({tp['tp2_pct']}%)  "
        f"TP3: {tp['tp3']} ({tp['tp3_pct']}%)\n"
        f"TP4: {tp['tp4']} ({tp['tp4_pct']}%)  "
        f"TP5: {tp['tp5']} ({tp['tp5_pct']}%)  "
        f"SL: {tp['sl']} ({tp['sl_pct']}%)\n"
        f"{SEP}\n"
        f"⚠️  Not financial advice  |  APEX-QUANT"
    )


def tg_resolution(event: dict, stats: StatsTracker) -> str:
    st, k = stats.snapshot(), event["type"]
    tp     = st["tp"]
    header = (f"🛑 STOP LOSS HIT  #{event['trade_no']}"
              if k == "SL" else
              f"{'🏆 ALL TARGETS' if event.get('all_done') else '✅ ' + k} HIT  #{event['trade_no']}")
    pnl_note = ("−1.0R" if k == "SL"
                else f"+{event.get('rr','').replace('1:','')}R")
    return (
        f"{header}\n"
        f"{SEP}\n"
        f"  Pair  : {event['pair']}\n"
        f"  Price : {_f(event['price'])}\n"
        f"  PNL   : {pnl_note}\n"
        f"{SEP}\n"
        f"📊 Updated Stats\n"
        f"  WR Today   : {st['daily']['wr']}%  ({st['daily']['wins']}W/{st['daily']['losses']}L)\n"
        f"  PNL Today  : {st['daily']['pnl_str']}\n"
        f"  All-time   : {st['total']['wr']}% WR  |  {st['total']['pnl_str']}\n"
        f"  TP Buckets : TP1={tp['tp1']} TP2={tp['tp2']} TP3={tp['tp3']} "
        f"TP4={tp['tp4']} TP5={tp['tp5']} SL={tp['sl']}\n"
        f"{SEP}\n"
        f"⚠️  Not financial advice  |  APEX-QUANT"
    )


def tg_new_listing(symbol: str) -> str:
    return (
        f"🆕 NEW LISTING DETECTED\n"
        f"{SEP}\n"
        f"  Symbol : {symbol}\n"
        f"  Added to live scan automatically.\n"
        f"⚠️  Not financial advice  |  APEX-QUANT"
    )


# ── Discord ───────────────────────────────────────────────────────

def dc_signal(sig: dict, stats: StatsTracker) -> dict:
    s, st  = sig, stats.snapshot()
    tp     = st["tp"]
    is_long = s["direction"] == "LONG"
    color   = 0x00FF88 if is_long else 0xFF3355

    tp_text = "\n".join(
        f"TP{i+1} `{rr}` → **{_f(p)}**{' ⭐' if i==2 else ''}"
        for i,(p,rr) in enumerate(zip(s["tps"], s["rrs"]))
    )
    stats_text = (
        f"**WR**    Day `{st['daily']['wr']}%` · Month `{st['monthly']['wr']}%` · Total `{st['total']['wr']}%`\n"
        f"**PNL**   Day `{st['daily']['pnl_str']}` · Month `{st['monthly']['pnl_str']}` · Total `{st['total']['pnl_str']}`\n"
        f"**W/L**   `{st['total']['wins']}W / {st['total']['losses']}L`  (#{st['trade_count']} signals)\n"
        f"**TPs**   TP1={tp['tp1']} · TP2={tp['tp2']} · TP3={tp['tp3']} · "
        f"TP4={tp['tp4']} · TP5={tp['tp5']} · SL={tp['sl']}"
    )
    return {"embeds": [{
        "title":       f"⚡ #{s['trade_no']}  {s['pair']}  {'▲ LONG' if is_long else '▼ SHORT'}",
        "description": f"{s['market_label']}\n`CSS {s['css']}/100` · `{s['confidence']}% confidence`",
        "color":       color,
        "fields": [
            {"name": "② Entry Zone (LIMIT ORDER)",
             "value": f"`{_f(s['entry_low'])}` – `{_f(s['entry_high'])}`", "inline": True},
            {"name": "⑥ Stop Loss",
             "value": f"🛑 `{_f(s['sl'])}`", "inline": True},
            {"name": "④ Leverage · ⑦ Type · ⑨ TF",
             "value": f"`{s['leverage']}×` · `{s['trade_type']}` · `{s['timeframe']}`", "inline": False},
            {"name": "⑤ Take Profit Targets",   "value": tp_text,     "inline": False},
            {"name": "⑧ Best R:R",              "value": f"`{s['rrs'][-1]}`", "inline": True},
            {"name": "⑩ Expected Duration",     "value": f"⏳ `{s['eta']}`",  "inline": True},
            {"name": "⑪ Market Condition",      "value": s["market_label"],    "inline": False},
            {"name": "③ Position",
             "value": "▲ **LONG**" if is_long else "▼ **SHORT**", "inline": True},
            {"name": "📊 Performance Stats",    "value": stats_text,  "inline": False},
        ],
        "footer": {"text": f"APEX-QUANT · {s['datetime']} · Not financial advice"},
    }]}


def dc_resolution(event: dict, stats: StatsTracker) -> dict:
    st, k = stats.snapshot(), event["type"]
    color  = 0xFF3355 if k == "SL" else 0x00FF88
    title  = (f"🛑 SL HIT #{event['trade_no']}" if k == "SL"
               else f"✅ {k} HIT #{event['trade_no']}")
    return {"embeds": [{
        "title":       title,
        "description": f"**{event['pair']}** @ `{_f(event['price'])}`",
        "color":       color,
        "fields": [{
            "name":  "Updated Stats",
            "value": (
                f"WR Today `{st['daily']['wr']}%` · All-time `{st['total']['wr']}%`\n"
                f"PNL Today `{st['daily']['pnl_str']}` · Total `{st['total']['pnl_str']}`"
            ),
        }],
        "footer": {"text": "APEX-QUANT · Not financial advice"},
    }]}


def dc_new_listing(symbol: str) -> dict:
    return {"embeds": [{
        "title":       f"🆕 New Listing: {symbol}",
        "description": "Added to live scan automatically.",
        "color":       0x00D4FF,
        "footer":      {"text": "APEX-QUANT · Not financial advice"},
    }]}
