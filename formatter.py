"""
formatter.py — Builds the full signal alert (all 11 fields + stats block).
Outputs:
  build_telegram_text()  → plain str  (no MarkdownV2, avoids escaping errors)
  build_discord_embed()  → dict       (discord.py Embed payload)
"""
from src.config import TP_WEIGHTS, TP_LABELS

REGIME_EMOJI = {
    "Strong Bull":    "🚀",
    "Normal Bull":    "📈",
    "Normal Market":  "📈",
    "Strong Bear":    "🐻",
    "Choppy/Sideways":"↔",
    "High Volatility":"⚡",
}


def _fmt(price: float, symbol: str = "") -> str:
    """Smart decimal formatting based on price magnitude."""
    sym = symbol.upper()
    if "PEPE" in sym or "SHIB" in sym or price < 0.0001:
        return f"{price:.8f}"
    if price < 0.01:
        return f"{price:.6f}"
    if price < 1:
        return f"{price:.4f}"
    if price < 100:
        return f"{price:.3f}"
    return f"{price:.2f}"


def _wr_bar(wr: float, width: int = 10) -> str:
    filled = round(wr / 100 * width)
    return "▓" * filled + "░" * (width - filled)


def _pnl_str(pnl: float) -> str:
    return f"{'+' if pnl >= 0 else ''}{pnl:.2f}R"


def build_telegram_text(signal: dict, trade_num: int, stats: dict) -> str:
    """
    Plain-text Telegram message — safe to send with parse_mode=None.
    No special characters that need MarkdownV2 escaping.
    """
    s   = signal
    sym = s["symbol"]
    fmt = lambda p: _fmt(p, sym)
    il  = s["side"] == "LONG"
    re  = REGIME_EMOJI.get(s["regime"], "📊")
    rr  = s["rr"]
    rrt = "ELITE 🏆" if rr >= 6 else "GOOD ✅" if rr >= 3 else "MIN ⚠"

    d, m, t = stats["daily"], stats["monthly"], stats["total"]
    tp  = stats["tp_buckets"]   # list[5]
    slc = stats["sl_count"]

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
    for i, tp_price in enumerate(s["tps"]):
        sz = int(TP_WEIGHTS[i] * 100)
        lines.append(
            f"   {TP_LABELS[i]}   {fmt(tp_price):<16}  1:{i+1}R   ({sz}% size)"
        )
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
        f"AI Score  {s['ai_score']:.1f}/100  [{s['grade']}]",
        "",
        "━━━━━━━━━━━  PERFORMANCE  ━━━━━━━━━━━",
        "",
        "📊 Win Rate",
        f"   Today    {d['wr']:.1f}%  {_wr_bar(d['wr'])}",
        f"   Monthly  {m['wr']:.1f}%  {_wr_bar(m['wr'])}",
        f"   Total    {t['wr']:.1f}%  {_wr_bar(t['wr'])}",
        "",
        "💰 PNL (R-multiples, front-loaded ladder)",
        f"   Today    {_pnl_str(d['pnl'])}",
        f"   Monthly  {_pnl_str(m['pnl'])}",
        f"   Total    {_pnl_str(t['pnl'])}",
        "",
        "Wins / Losses",
        f"   Today    {d['wins']}W  /  {d['losses']}L",
        f"   Monthly  {m['wins']}W  /  {m['losses']}L",
        f"   Total    {t['wins']}W  /  {t['losses']}L",
        "",
        "🏆 Exit Distribution  (final level only — mutually exclusive)",
        f"   TP1 only  {tp[0]}     TP2 only  {tp[1]}     TP3 only  {tp[2]}",
        f"   TP4 only  {tp[3]}     TP5 all   {tp[4]}     SL hit    {slc}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "IDS v2.0  •  Ignition Detection System",
    ]
    return "\n".join(lines)


def build_discord_embed(signal: dict, trade_num: int, stats: dict) -> dict:
    """
    Returns a payload dict compatible with discord.py:
      { "content": str, "embed": { title, color, description, fields, footer } }
    """
    s   = signal
    sym = s["symbol"]
    fmt = lambda p: _fmt(p, sym)
    il  = s["side"] == "LONG"
    re  = REGIME_EMOJI.get(s["regime"], "📊")
    rr  = s["rr"]

    d, m, t = stats["daily"], stats["monthly"], stats["total"]
    tp  = stats["tp_buckets"]
    slc = stats["sl_count"]

    tp_block = "\n".join(
        f"`{TP_LABELS[i]}` {fmt(tp_p)} — 1:{i+1}R  ({int(TP_WEIGHTS[i]*100)}%)"
        for i, tp_p in enumerate(s["tps"])
    )

    embed = {
        "title": (
            f"{'🟢' if il else '🔴'}  {sym}  {s['side']}"
            f"  —  Trade #{str(trade_num).zfill(4)}"
        ),
        "color": 0x00FF88 if il else 0xFF2055,
        "description": (
            f"**AI Score: {s['ai_score']:.1f} / 100  [{s['grade']}]**\n"
            f"{re} {s['regime']}"
        ),
        "fields": [
            {"name": "① Pair",           "value": sym,                                              "inline": True},
            {"name": "② Entry  [LIMIT]", "value": f"`{fmt(s['entry_lo'])} – {fmt(s['entry_hi'])}`","inline": True},
            {"name": "③ Position",       "value": f"**{'BUY / LONG' if il else 'SELL / SHORT'}**", "inline": True},
            {"name": "④ Leverage",       "value": f"{s['leverage']}x",                             "inline": True},
            {"name": "⑤ Take Profits",   "value": tp_block,                                        "inline": False},
            {"name": "⑥ Stop Loss",      "value": f"`{fmt(s['sl'])}` (-{s['sl_pct']}%)",          "inline": True},
            {"name": "⑦ Trade Type",     "value": s["trade_type"],                                 "inline": True},
            {"name": "⑧ R:R",            "value": f"1 : {rr:.2f}",                                "inline": True},
            {"name": "⑨ Timeframe",      "value": s["timeframe"],                                  "inline": True},
            {"name": "⑩ Est. Time",      "value": s["expected_time"],                              "inline": True},
            {"name": "⑪ Market",         "value": f"{re} {s['regime']}",                          "inline": True},
            {
                "name":   "📊 Win Rate",
                "value":  (
                    f"Today `{d['wr']:.1f}%` | "
                    f"Monthly `{m['wr']:.1f}%` | "
                    f"Total `{t['wr']:.1f}%`"
                ),
                "inline": False,
            },
            {
                "name":   "💰 PNL (R)",
                "value":  (
                    f"Today `{_pnl_str(d['pnl'])}` | "
                    f"Monthly `{_pnl_str(m['pnl'])}` | "
                    f"Total `{_pnl_str(t['pnl'])}`"
                ),
                "inline": False,
            },
            {
                "name":   "Wins / Losses  (Total)",
                "value":  f"✅ `{t['wins']}W`  ❌ `{t['losses']}L`",
                "inline": True,
            },
            {
                "name":   "🏆 Exit Distribution",
                "value":  (
                    f"TP1:`{tp[0]}`  TP2:`{tp[1]}`  TP3:`{tp[2]}`  "
                    f"TP4:`{tp[3]}`  TP5:`{tp[4]}`  SL:`{slc}`"
                ),
                "inline": False,
            },
        ],
        "footer": {"text": "IDS v2.0  •  Ignition Detection System"},
    }
    return {"content": "", "embed": embed}
