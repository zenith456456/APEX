"""
APEX SIGNAL FORMATTER  v3
══════════════════════════
Two-color signal card:
  TOP  frame — directional (🟩 green=PUMP / 🟥 red=DUMP)
  BOTTOM frame — trade data (🔷 blue, neutral)

Market condition badge on every signal.
5 TPs always shown: R:R 1:1 → 1:rr_max (dynamic, no cap).
"""
import time
import datetime
from apex_engine import (
    Signal, fmt_price, fmt_vol, score_bar, apex_grade, hold_str,
)
from config import HIST_WR

STYLE_META = {
    "day"  : ("☀️",  "DAY",   "30–120 min"),
    "swing": ("🌊",  "SWING", "2–6 hours"),
    "power": ("🔥",  "POWER", "3–8 hours"),
    "ultra": ("💎",  "ULTRA", "4–10 hours"),
}

def _utc() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def _dt() -> str:
    return datetime.datetime.utcnow().strftime("%d %b %Y  %H:%M UTC")

def _pct_from(price: float, target: float, position: str) -> float:
    if position == "LONG":
        return (target - price) / price * 100
    return (price - target) / price * 100

def _apex_bar(score: int) -> str:
    filled = round(score / 10)
    empty  = 10 - filled
    if score >= 95: return "🟦" * filled + "⬜" * empty
    if score >= 90: return "🟩" * filled + "⬜" * empty
    if score >= 85: return "🟨" * filled + "⬜" * empty
    return               "🟧" * filled + "⬜" * empty

def _rr_stars(rr: float) -> str:
    n = min(int(rr * 0.8), 8)
    return "⭐" * max(n, 1)

def _wr_badge(wr: int) -> str:
    if wr >= 83: return "🏆 ELITE"
    if wr >= 78: return "🥇 HIGH"
    if wr >= 73: return "🥈 SOLID"
    return "🥉 GOOD"


# ══════════════════════════════════════════════════════════════
#  TELEGRAM  —  two-color signal card
# ══════════════════════════════════════════════════════════════

def telegram_signal(sig: Signal) -> str:
    t   = sig.tier_meta()
    ti  = t.get("icon", "🔥")
    tr  = sig.trade
    si, sl_name, shld = STYLE_META.get(tr.style, ("💎", "ULTRA", "~6h"))
    is_long = tr.position == "LONG"
    mkt     = getattr(sig, "market_condition", "")
    reason  = getattr(sig, "signal_reason", "new_coin")

    # ── Directional theme ─────────────────────────────────────
    if is_long:
        DIR_ICON  = "🚀"
        DIR_BADGE = "🟢 LONG"
        DIR_WORD  = "BULLISH"
        TOP_ACCENT = "🟩"
        H = "═"
    else:
        DIR_ICON  = "🔻"
        DIR_BADGE = "🔴 SHORT"
        DIR_WORD  = "BEARISH"
        TOP_ACCENT = "🟥"
        H = "═"

    BOT_ACCENT = "🔷"
    B = "─"
    W = 38

    # ── Re-entry / reversal banner ────────────────────────────
    BANNERS = {
        "all_tp_hit": f"\n{TOP_ACCENT} 🎯  ALL TP HIT — FRESH RE-ENTRY (new targets)\n",
        "sl_hit"    : f"\n{TOP_ACCENT} 🛑  STOP LOSS HIT — FRESH SETUP\n",
        "reversal"  : f"\n{TOP_ACCENT} 🔄  DIRECTION REVERSAL SIGNAL\n",
    }
    reason_line = BANNERS.get(reason, "")
    new_line    = f"\n{TOP_ACCENT} 🆕  NEW BINANCE FUTURES LISTING\n" if sig.is_new_listing else ""

    # ── Price calculations ────────────────────────────────────
    def d(tp):   return _pct_from(tr.entry_low, tp, tr.position)
    sl_d = abs(_pct_from(tr.entry_high, tr.sl, "SHORT" if is_long else "LONG"))

    # ── APEX bars ─────────────────────────────────────────────
    apex_bar = _apex_bar(sig.apex_score)
    move_bar = score_bar(sig.layers.FMT, 10)
    vol_bar  = score_bar(sig.layers.LVI, 10)
    mom_bar  = score_bar(sig.layers.WAS, 10)

    rr_str  = f"1:{tr.rr_max:.1f}" if tr.rr_max < 10 else f"1:{tr.rr_max:.0f}"
    tp3_d   = d(tr.tp3)
    tp4_d   = d(tr.tp4)
    tp5_d   = d(tr.tp5)
    tp4_rr  = round(tr.rr_max * 0.6, 1)

    return (
        # ══ TOP FRAME — directional color ════════════════════
        f"<pre>"
        f"╔{H*W}╗\n"
        f"║  {ti} APEX SYSTEM™  {sig.tier} {t.get('label','')}  {DIR_ICON} {DIR_WORD} ║\n"
        f"╠{H*W}╣\n"
        f"║  {sig.coin()}/USDT   {sig.pct:+.2f}%   {DIR_BADGE}        ║\n"
        f"║  {si} {sl_name}  SL {sl_d:.1f}%  R:R {rr_str} (dynamic)   ║\n"
        f"╚{H*W}╝"
        f"</pre>"
        f"{reason_line}{new_line}"

        # ── Market condition + time ───────────────────────────
        f"\n{TOP_ACCENT}  <b>{mkt}</b>\n"
        f"<i>📅 {_dt()}  ·  Vol {fmt_vol(sig.vol_usd)}</i>\n"

        # ── Entry zone (pullback entry) ───────────────────────
        f"\n{TOP_ACCENT}  <b>② ENTRY ZONE</b>  <i>— Limit order near current price</i>\n"
        f"<pre>"
        f"┌{B*W}┐\n"
        f"│  Low   ▸ ${fmt_price(tr.entry_low):<32}│\n"
        f"│  High  ▸ ${fmt_price(tr.entry_high):<32}│\n"
        f"│  Spot  ▸ ${fmt_price(sig.price):<32}│\n"
        f"│  ★  Enter near BOTTOM of dump / TOP of pump  │\n"
        f"│  ⚠  LIMIT order — tight SL above/below entry │\n"
        f"└{B*W}┘"
        f"</pre>"

        # ── Position + leverage ───────────────────────────────
        f"\n{TOP_ACCENT}  <b>③ {DIR_BADGE}   ④ Leverage {tr.leverage}×</b>\n"
        f"<pre>"
        f"┌{B*W}┐\n"
        f"│  Direction  {DIR_WORD} BREAKDOWN / BREAKOUT     │\n"
        f"│  Leverage   {tr.leverage}×   Risk: 1–2% of balance      │\n"
        f"└{B*W}┘"
        f"</pre>"

        # ══ BOTTOM FRAME — neutral blue info ════════════════
        # ── 5 Take profit levels ──────────────────────────────
        f"\n{BOT_ACCENT}  <b>⑤ TAKE PROFIT TARGETS</b>  <i>R:R 1:1 → {rr_str} (no cap)</i>\n"
        f"<pre>"
        f"┌{B*W}┐\n"
        f"│  🟡 TP1  ${fmt_price(tr.tp1):<14} R:R 1:1    close 15%  │\n"
        f"│  🟢 TP2  ${fmt_price(tr.tp2):<14} R:R 1:2    close 20%  │\n"
        f"│  🔵 TP3  ${fmt_price(tr.tp3):<14} R:R 1:3    close 25%  │\n"
        f"│          ({tp3_d:+.1f}% from entry)                  │\n"
        f"│  🟣 TP4  ${fmt_price(tr.tp4):<14} R:R 1:{tp4_rr:<4}  close 20%  │\n"
        f"│          ({tp4_d:+.1f}% from entry)                  │\n"
        f"│  💎 TP5  ${fmt_price(tr.tp5):<14} R:R {rr_str:<6} close 20%  │\n"
        f"│          ({tp5_d:+.1f}% from entry)  ← MAX          │\n"
        f"└{B*W}┘"
        f"</pre>"

        # ── Stop loss ─────────────────────────────────────────
        f"\n{BOT_ACCENT}  <b>⑥ STOP LOSS</b>  <i>— tight, close to current entry</i>\n"
        f"<pre>"
        f"┌{B*W}┐\n"
        f"│  Price  ▸ ${fmt_price(tr.sl):<32}│\n"
        f"│  Dist   ▸ -{sl_d:.1f}% from entry (tight SL)       │\n"
        f"│  ⚠  Hard stop — close position immediately    │\n"
        f"└{B*W}┘"
        f"</pre>"

        # ── Trade summary ─────────────────────────────────────
        f"\n{BOT_ACCENT}  <b>⑦ ⑧ ⑨  TRADE SUMMARY</b>\n"
        f"<pre>"
        f"┌{B*W}┐\n"
        f"│  Style     {si} {sl_name:<28}│\n"
        f"│  Max R:R   {rr_str}  {_rr_stars(tr.rr_max):<24}│\n"
        f"│  Hold      {shld:<29}│\n"
        f"│  Win Rate  {tr.hist_wr}%  {_wr_badge(tr.hist_wr):<24}│\n"
        f"│  TP3 dist  {tp3_d:+.1f}% from entry               │\n"
        f"│  SL dist   -{sl_d:.1f}% (tight — low risk)         │\n"
        f"└{B*W}┘"
        f"</pre>"

        # ── APEX score ────────────────────────────────────────
        f"\n{BOT_ACCENT}  <b>🧠 APEX SCORE</b>\n"
        f"<pre>"
        f"┌{B*W}┐\n"
        f"│  Score  {sig.apex_score:3d}/100  {apex_bar}      │\n"
        f"│  Grade  {apex_grade(sig.apex_score):<29}  │\n"
        f"├{B*W}┤\n"
        f"│  📐 MOVE  {sig.layers.FMT:2d}/50  {move_bar}      │\n"
        f"│  💧 VOL   {sig.layers.LVI:2d}/35  {vol_bar}      │\n"
        f"│  🔁 MOM   {sig.layers.WAS:2d}/15  {mom_bar}      │\n"
        f"└{B*W}┘"
        f"</pre>"

        # ── Footer ────────────────────────────────────────────
        f"\n<i>⚠️ Not financial advice  ·  Use stop loss  ·  Manage risk</i>\n"
        f"<i>APEX SYSTEM™  ·  {_utc()}</i>"
    )


def telegram_new_listing(symbol: str) -> str:
    coin = symbol.replace("USDT", "")
    return (
        f"<pre>╔{'═'*38}╗\n"
        f"║   🆕   NEW FUTURES LISTING             ║\n"
        f"╚{'═'*38}╝</pre>\n"
        f"<b>{coin}/USDT</b>  now live on Binance Futures\n"
        f"<i>{_dt()}</i>\n\n"
        f"⚡ APEX now scanning <b>{coin}/USDT</b> for T3 🔥 T4 ⭐ signals."
    )


def telegram_stats(stats: dict, uptime_sec: float) -> str:
    h = int(uptime_sec // 3600)
    m = int((uptime_sec % 3600) // 60)
    s = int(uptime_sec % 60)
    def rr(f, r): return f"{r/(f+r)*100:.0f}% rejected" if (f+r)>0 else "n/a"
    t3f = stats.get("t3_fired", 0); t3r = stats.get("t3_rejected", 0)
    t4f = stats.get("t4_fired", 0); t4r = stats.get("t4_rejected", 0)
    last = stats.get("last_signal_ts")
    last_str = f"{int(time.time()-last)//60}m ago" if last else "none yet"
    return (
        f"<pre>╔{'═'*38}╗\n"
        f"║   📡   APEX BOT  —  LIVE STATS       ║\n"
        f"╚{'═'*38}╝\n\n"
        f"  ⏱ Uptime       {h:02d}:{m:02d}:{s:02d}\n"
        f"  📊 Pairs live   {stats.get('pairs_live', 0)}\n"
        f"  ⚡ Last signal  {last_str}\n\n"
        f"  🔥 T3 STRONG (≥10% APEX≥82)\n"
        f"     Fired {t3f:>5}  ({rr(t3f, t3r)})\n\n"
        f"  ⭐ T4 MEGA   (≥20% APEX≥78)\n"
        f"     Fired {t4f:>5}  ({rr(t4f, t4r)})\n\n"
        f"  🎯 TP re-entries  {stats.get('all_tp_reentries',0)}\n"
        f"  🛑 SL re-entries  {stats.get('sl_reentries',0)}\n"
        f"  🔄 Reversals      {stats.get('reversals',0)}"
        f"</pre>"
    )


def telegram_winrates() -> str:
    lines = [
        f"<pre>╔{'═'*38}╗\n"
        f"║   📈   APEX WIN RATES                ║\n"
        f"╚{'═'*38}╝</pre>"
    ]
    for tier in ["T3", "T4"]:
        gate  = "≥82" if tier == "T3" else "≥78"
        icon  = "🔥" if tier == "T3" else "⭐"
        lines.append(f"\n{icon}  <b>{tier} {'STRONG' if tier=='T3' else 'MEGA'}  ≥{'10' if tier=='T3' else '20'}%  APEX{gate}</b>")
        for style, (si, lbl, hold) in STYLE_META.items():
            if style not in HIST_WR.get(tier, {}):
                continue
            wp = HIST_WR[tier][style]["pump"]
            wd = HIST_WR[tier][style]["dump"]
            lines.append(f"<code>  {si} {lbl:<5}  🚀 {wp}%   📉 {wd}%   ⏱ {hold}</code>")
    lines.append("\n<i>Pullback entry · Tight SL · Dynamic R:R (no cap)</i>")
    return "\n".join(lines)


def telegram_recent_signals(signals) -> str:
    if not signals:
        return f"<pre>📭  No signals yet.\n     APEX scanning Binance Futures...</pre>"
    lines = [
        f"<pre>╔{'═'*38}╗\n"
        f"║   📋   RECENT SIGNALS               ║\n"
        f"╚{'═'*38}╝</pre>"
    ]
    for sig in list(signals)[:10]:
        t   = sig.tier_meta()
        ago = int(time.time() - sig.ts_epoch)
        di  = "🚀" if sig.direction == "PUMP" else "🔻"
        pos = "🟢" if sig.direction == "PUMP" else "🔴"
        si, sl_name, _ = STYLE_META.get(sig.trade.style, ("💎", "ULTRA", ""))
        reason = getattr(sig, "signal_reason", "")
        rtag = " 🔄" if reason=="reversal" else " 🎯" if reason=="all_tp_hit" else " 🛑" if reason=="sl_hit" else ""
        rr_str = f"1:{sig.trade.rr_max:.0f}" if sig.trade.rr_max >= 10 else f"1:{sig.trade.rr_max:.1f}"
        lines.append(
            f"{t.get('icon','🔥')} <b>{sig.coin()}/USDT</b>  "
            f"{di} <code>{sig.pct:+.1f}%</code>  {pos}  "
            f"APEX <code>{sig.apex_score}</code>  {si} <code>{sl_name}</code>  "
            f"<code>{rr_str}</code>{rtag}  <i>{ago//60}m ago</i>"
        )
    return "\n".join(lines)


def telegram_help() -> str:
    return (
        f"<pre>╔{'═'*38}╗\n"
        f"║   🧠   APEX SYSTEM™  BOT GUIDE      ║\n"
        f"╚{'═'*38}╝</pre>\n"
        "<b>Commands</b>\n"
        "<code>  /start     </code> Activate\n"
        "<code>  /stop      </code> Pause\n"
        "<code>  /stats     </code> Statistics\n"
        "<code>  /status    </code> Status\n"
        "<code>  /signals   </code> Last 10 signals\n"
        "<code>  /winrates  </code> Win rates\n"
        "<code>  /help      </code> This guide\n\n"
        "<b>Tiers</b>\n"
        "<code>  🔥 T3 STRONG  ≥10%  APEX≥82\n"
        "  ⭐ T4 MEGA    ≥20%  APEX≥78</code>\n\n"
        "<b>Entry Strategy</b>\n"
        "<code>  Pullback entry (2.5% retracement)\n"
        "  Tight SL (3–5% from entry)\n"
        "  TP3 only 9–15% away → achievable</code>\n\n"
        "<b>5 Take Profit Levels</b>\n"
        "<code>  🟡 TP1  R:R 1:1    close 15%\n"
        "  🟢 TP2  R:R 1:2    close 20%\n"
        "  🔵 TP3  R:R 1:3    close 25%  ← main\n"
        "  🟣 TP4  R:R 1:~6   close 20%\n"
        "  💎 TP5  R:R 1:MAX  close 20%</code>\n\n"
        "<i>Not financial advice · Always use SL</i>"
    )


# ══════════════════════════════════════════════════════════════
#  DISCORD  —  two-color embed
# ══════════════════════════════════════════════════════════════

_COLORS = {
    ("T4", "PUMP"): 0x00FFD1,
    ("T3", "PUMP"): 0x00E676,
    ("T4", "DUMP"): 0xFF1744,
    ("T3", "DUMP"): 0xFF6D00,
}


def discord_embed(sig: Signal) -> dict:
    t    = sig.tier_meta()
    ti   = t.get("icon", "🔥")
    tr   = sig.trade
    si, sl_name, shld = STYLE_META.get(tr.style, ("💎", "ULTRA", "~6h"))
    color     = _COLORS.get((sig.tier, sig.direction), 0x34D399)
    is_long   = tr.position == "LONG"
    dir_arrow = "🚀" if is_long else "🔻"
    pos_badge = "🟢 LONG" if is_long else "🔴 SHORT"
    mkt       = getattr(sig, "market_condition", "")
    reason    = getattr(sig, "signal_reason", "new_coin")

    reason_tag = {
        "all_tp_hit": "  🎯 ALL-TP RE-ENTRY",
        "sl_hit"    : "  🛑 SL-HIT RE-ENTRY",
        "reversal"  : "  🔄 REVERSAL",
    }.get(reason, "")
    new_tag = "  🆕 NEW" if sig.is_new_listing else ""

    def d(tp): return _pct_from(tr.entry_low, tp, tr.position)
    sl_d = abs(_pct_from(tr.entry_high, tr.sl, "SHORT" if is_long else "LONG"))

    apex_bar = _apex_bar(sig.apex_score)
    move_bar = score_bar(sig.layers.FMT, 8)
    vol_bar  = score_bar(sig.layers.LVI, 8)
    mom_bar  = score_bar(sig.layers.WAS, 8)

    rr_str  = f"1:{tr.rr_max:.1f}" if tr.rr_max < 10 else f"1:{tr.rr_max:.0f}"
    tp4_rr  = round(tr.rr_max * 0.6, 1)

    title = (
        f"{ti} {sig.tier} {t.get('label','')}  {dir_arrow}  "
        f"{sig.coin()}/USDT  {sig.pct:+.2f}%{reason_tag}{new_tag}"
    )

    description = (
        f"## {dir_arrow}  {sig.coin()}/USDT  `{sig.pct:+.2f}%`\n"
        f"> {pos_badge}  ·  Vol `{fmt_vol(sig.vol_usd)}`\n"
        f"> **{mkt}**\n"
        f"> `{_dt()}`"
    )

    fields = [
        {
            "name" : "🎯 ② Entry Zone  *(pullback limit)*",
            "value": (
                f"Low: `${fmt_price(tr.entry_low)}`  High: `${fmt_price(tr.entry_high)}`\n"
                f"Spot: `${fmt_price(sig.price)}`\n"
                f"★ Enter near bottom of dump / top of pump"
            ),
            "inline": True,
        },
        {
            "name" : "③ Position  ④ Leverage",
            "value": f"{pos_badge}\n`{tr.leverage}×`  Risk 1–2% / trade",
            "inline": True,
        },
        {
            "name" : f"💰 ⑤ Take Profit Targets  *(R:R {rr_str} max)*",
            "value": (
                f"🟡 **TP1**  `${fmt_price(tr.tp1)}`  R:R **1:1**   → 15%\n"
                f"🟢 **TP2**  `${fmt_price(tr.tp2)}`  R:R **1:2**   → 20%\n"
                f"🔵 **TP3**  `${fmt_price(tr.tp3)}`  `{d(tr.tp3):+.1f}%`  R:R **1:3**   → 25%\n"
                f"🟣 **TP4**  `${fmt_price(tr.tp4)}`  `{d(tr.tp4):+.1f}%`  R:R **1:{tp4_rr}**  → 20%\n"
                f"💎 **TP5**  `${fmt_price(tr.tp5)}`  `{d(tr.tp5):+.1f}%`  R:R **{rr_str}**  → 20%"
            ),
            "inline": False,
        },
        {
            "name" : "🛑 ⑥ Stop Loss  *(tight)*",
            "value": f"`${fmt_price(tr.sl)}`\n`-{sl_d:.1f}%` from entry  ← tight",
            "inline": True,
        },
        {
            "name" : f"{si} ⑦ Style  ⑧ R:R  ⑨ Time",
            "value": f"**{sl_name}**  `{rr_str}`  {_rr_stars(tr.rr_max)}\n{shld}",
            "inline": True,
        },
        {
            "name" : "📊 Win Rate  ·  Risk/Reward",
            "value": (
                f"{_wr_badge(tr.hist_wr)}  **{tr.hist_wr}%**\n"
                f"TP3 `{d(tr.tp3):+.1f}%`  SL `-{sl_d:.1f}%`"
            ),
            "inline": True,
        },
        {
            "name" : "🧠 APEX Score",
            "value": (
                f"**{sig.apex_score}/100**  {apex_bar}\n"
                f"*{apex_grade(sig.apex_score)}*\n"
                f"`📐 MOVE {sig.layers.FMT:2d}/50 {move_bar}`\n"
                f"`💧 VOL  {sig.layers.LVI:2d}/35 {vol_bar}`\n"
                f"`🔁 MOM  {sig.layers.WAS:2d}/15 {mom_bar}`"
            ),
            "inline": False,
        },
    ]

    return {
        "title"      : title,
        "description": description,
        "color"      : color,
        "fields"     : fields,
        "footer"     : {"text": f"APEX SYSTEM™  ·  {mkt}  ·  Not financial advice  ·  {_utc()}"},
    }


def discord_new_listing(symbol: str) -> str:
    coin = symbol.replace("USDT", "")
    return (
        f"## 🆕  New Futures Listing: **{coin}/USDT**\n"
        f"> {_dt()}\n\n"
        f"APEX scanning **{coin}/USDT** for T3 🔥 T4 ⭐ signals."
    )


def discord_stats(stats: dict, uptime_sec: float) -> str:
    h=int(uptime_sec//3600); m=int((uptime_sec%3600)//60); s=int(uptime_sec%60)
    def rr(f,r): return f"{r/(f+r)*100:.0f}%" if (f+r)>0 else "n/a"
    t3f=stats.get("t3_fired",0); t3r=stats.get("t3_rejected",0)
    t4f=stats.get("t4_fired",0); t4r=stats.get("t4_rejected",0)
    return (
        f"**📡 APEX — Stats**\n```\n"
        f"Uptime     {h:02d}:{m:02d}:{s:02d}\n"
        f"Pairs      {stats.get('pairs_live',0)}\n"
        f"🔥 T3  Fired {t3f:4d}  ({rr(t3f,t3r)} reject)\n"
        f"⭐ T4  Fired {t4f:4d}  ({rr(t4f,t4r)} reject)\n"
        f"🎯 TP re    {stats.get('all_tp_reentries',0)}\n"
        f"🛑 SL re    {stats.get('sl_reentries',0)}\n"
        f"🔄 Reversal {stats.get('reversals',0)}\n"
        f"```*Pullback entry · Dynamic R:R · No cap*"
    )


def discord_recent_signals(signals) -> str:
    if not signals:
        return "📭 **No signals yet.**"
    lines = ["**📋 Recent Signals**\n"]
    for sig in list(signals)[:10]:
        t   = sig.tier_meta()
        ago = int(time.time() - sig.ts_epoch)
        di  = "🚀" if sig.direction=="PUMP" else "🔻"
        pos = "🟢" if sig.direction=="PUMP" else "🔴"
        si, sl_name, _ = STYLE_META.get(sig.trade.style, ("💎","ULTRA",""))
        reason = getattr(sig,"signal_reason","")
        rtag = " 🔄" if reason=="reversal" else " 🎯" if reason=="all_tp_hit" else " 🛑" if reason=="sl_hit" else ""
        rr_str = f"1:{sig.trade.rr_max:.0f}" if sig.trade.rr_max>=10 else f"1:{sig.trade.rr_max:.1f}"
        lines.append(
            f"{t.get('icon','🔥')} **{sig.coin()}/USDT**  "
            f"{di} `{sig.pct:+.1f}%`  {pos}  APEX `{sig.apex_score}`  "
            f"`{rr_str}`{rtag}  *{ago//60}m ago*"
        )
    return "\n".join(lines)
