"""
formatter.py — Message formatting for Telegram + Discord
Updated to handle all 4 resolution event types from memory_engine.
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


# ── Signal messages ───────────────────────────────────────────────

def tg_signal(sig: dict, stats: StatsTracker) -> str:
    s, st   = sig, stats.snapshot()
    tp, tot = st["tp"], st["total"]
    is_long = s["direction"] == "LONG"
    tp_lines = "".join(
        f"  ✅ TP{i+1} ({rr})  →  {_f(p)}"
        f"{'  ⭐' if i==2 else '  🔥' if i>=3 else ''}\n"
        for i, (p, rr) in enumerate(zip(s["tps"], s["rrs"]))
    )
    return (
        f"⚡ APEX-QUANT SIGNAL  #{s['trade_no']}\n{SEP}\n"
        f"① Coin Pair      :  {s['pair']}\n"
        f"② Entry Zone     :  {_f(s['entry_low'])} – {_f(s['entry_high'])}\n"
        f"                    📌 LIMIT ORDER\n"
        f"③ Position       :  {'🟢 LONG  ▲' if is_long else '🔴 SHORT ▼'}\n"
        f"④ Leverage       :  {s['leverage']}×\n{SEP}\n"
        f"⑥ Stop Loss      :  🛑 {_f(s['sl'])}\n"
        f"⑤ Take Profits   :\n{tp_lines}"
        f"⑦ Trade Type     :  {s['trade_type']}\n"
        f"⑧ Best R:R       :  {s['rrs'][-1]}\n"
        f"⑨ Timeframe      :  {s['timeframe']}\n"
        f"⑩ Expected Time  :  ⏳ {s['eta']}\n"
        f"⑪ Market         :  {s['market_label']}\n{SEP}\n"
        f"🎯 CSS Score      :  {s['css']}/100  [{_css_label(s['css'])}]\n"
        f"💯 Confidence    :  {s['confidence']}%\n"
        f"🕐 Time           :  {s['datetime']}\n{SEP}\n"
        f"📊 PERFORMANCE STATS\n{'─'*28}\n"
        f"Win Rate  │ Day: {st['daily']['wr']}%  │ Month: {st['monthly']['wr']}%  │ Total: {tot['wr']}%\n"
        f"PNL       │ Day: {st['daily']['pnl_str']}  │ Month: {st['monthly']['pnl_str']}  │ Total: {tot['pnl_str']}\n"
        f"Signals   │ #{st['trade_count']} given  │  {tot['wins']}W / {tot['losses']}L resolved\n"
        f"Pending   │ {st['pending']} signals still active\n"
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


# ── Resolution messages ───────────────────────────────────────────

def tg_resolution(event: dict, stats: StatsTracker) -> str:
    """
    Handles: TP_FINAL, SL_CLEAN, SL_AFTER_TP
    (TP_PARTIAL is handled inline in scanner.py)
    """
    st   = stats.snapshot()
    tp   = st["tp"]
    tot  = st["total"]
    etype= event["type"]

    if etype == "SL_CLEAN":
        header   = f"🛑 STOP LOSS HIT  #{event['trade_no']}"
        detail   = f"  {event['pair']} @ {_f(event['price'])}  |  No TP hit"
        pnl_note = "  PNL: −1.0R  (clean loss)"
    elif etype == "TP_FINAL":
        header   = f"🏆 ALL TARGETS HIT  #{event['trade_no']}"
        detail   = f"  {event['pair']} @ {_f(event['price'])}  |  TP{event['tp_idx']+1} ({event['rr']})"
        pnl_note = f"  PNL: +{event['rr_val']}R"
    elif etype == "SL_AFTER_TP":
        header   = f"✅ WIN (SL after TP{event['tp_idx']+1})  #{event['trade_no']}"
        detail   = f"  {event['pair']} — best: TP{event['tp_idx']+1} ({event['rr']})"
        pnl_note = f"  PNL: +{event['rr_val']}R"
    else:
        header   = f"📊 {etype}  #{event['trade_no']}"
        detail   = f"  {event['pair']}"
        pnl_note = ""

    return (
        f"{header}\n{SEP}\n{detail}\n{pnl_note}\n{SEP}\n"
        f"📊 Updated Stats\n"
        f"  WR Today   : {st['daily']['wr']}%  ({st['daily']['wins']}W / {st['daily']['losses']}L)\n"
        f"  PNL Today  : {st['daily']['pnl_str']}\n"
        f"  All-time   : {tot['wr']}% WR  |  {tot['pnl_str']}\n"
        f"  Resolved   : {tot['wins']}W / {tot['losses']}L of {st['trade_count']} signals\n"
        f"  TP Buckets : TP1={tp['tp1']} TP2={tp['tp2']} TP3={tp['tp3']} "
        f"TP4={tp['tp4']} TP5={tp['tp5']} SL={tp['sl']}\n"
        f"{SEP}\n⚠️  Not financial advice  |  APEX-QUANT"
    )


def tg_new_listing(symbol: str) -> str:
    return (
        f"🆕 NEW LISTING: {symbol}\n{SEP}\n"
        f"Added to live scan automatically.\n"
        f"⚠️  Not financial advice  |  APEX-QUANT"
    )


# ── Discord embeds ────────────────────────────────────────────────

def dc_signal(sig: dict, stats: StatsTracker) -> dict:
    s, st   = sig, stats.snapshot()
    tp, tot = st["tp"], st["total"]
    is_long = s["direction"] == "LONG"
    tp_text = "\n".join(
        f"TP{i+1} `{rr}` → **{_f(p)}**{' ⭐' if i==2 else ''}"
        for i, (p, rr) in enumerate(zip(s["tps"], s["rrs"]))
    )
    return {"embeds": [{
        "title":       f"⚡ #{s['trade_no']}  {s['pair']}  {'▲ LONG' if is_long else '▼ SHORT'}",
        "description": f"{s['market_label']}\n`CSS {s['css']}/100` · `{s['confidence']}% confidence`",
        "color":       0x00FF88 if is_long else 0xFF3355,
        "fields": [
            {"name": "② Entry (LIMIT)", "value": f"`{_f(s['entry_low'])}` – `{_f(s['entry_high'])}`", "inline": True},
            {"name": "⑥ Stop Loss",     "value": f"🛑 `{_f(s['sl'])}`",                               "inline": True},
            {"name": "④ Lev · ⑦ Type · ⑨ TF",
             "value": f"`{s['leverage']}×` · `{s['trade_type']}` · `{s['timeframe']}`", "inline": False},
            {"name": "⑤ Take Profits",  "value": tp_text, "inline": False},
            {"name": "⑧ R:R · ⑩ ETA · ⑪ Market",
             "value": f"`{s['rrs'][-1]}` · `{s['eta']}` · {s['market_label']}", "inline": False},
            {"name": "📊 Stats",
             "value": (
                 f"WR: Day `{st['daily']['wr']}%` Month `{st['monthly']['wr']}%` Total `{tot['wr']}%`\n"
                 f"PNL: `{tot['pnl_str']}` · `{tot['wins']}W/{tot['losses']}L` of `{st['trade_count']}` signals\n"
                 f"TP1={tp['tp1']} TP2={tp['tp2']} TP3={tp['tp3']} TP4={tp['tp4']} TP5={tp['tp5']} SL={tp['sl']}"
             ), "inline": False},
        ],
        "footer": {"text": f"APEX-QUANT · {s['datetime']} · Not financial advice"},
    }]}


def dc_resolution(event: dict, stats: StatsTracker) -> dict:
    st, etype = stats.snapshot(), event["type"]
    tot       = st["total"]
    if etype == "SL_CLEAN":
        color, title = 0xFF3355, f"🛑 SL HIT #{event['trade_no']}"
    elif etype == "TP_FINAL":
        color, title = 0x00FF88, f"🏆 ALL TPs HIT #{event['trade_no']}"
    else:
        color, title = 0x00FF88, f"✅ WIN #{event['trade_no']}"
    return {"embeds": [{
        "title":       title,
        "description": f"**{event['pair']}** @ `{_f(event['price'])}`",
        "color":       color,
        "fields": [{"name": "Stats",
                    "value": (
                        f"WR Today `{st['daily']['wr']}%` · All-time `{tot['wr']}%`\n"
                        f"PNL Today `{st['daily']['pnl_str']}` · Total `{tot['pnl_str']}`\n"
                        f"Resolved: `{tot['wins']}W / {tot['losses']}L` of `{st['trade_count']}` signals"
                    )}],
        "footer": {"text": "APEX-QUANT · Not financial advice"},
    }]}


def dc_new_listing(symbol: str) -> dict:
    return {"embeds": [{
        "title":       f"🆕 New Listing: {symbol}",
        "description": "Added to live scan automatically.",
        "color":       0x00D4FF,
        "footer":      {"text": "APEX-QUANT · Not financial advice"},
    }]}
