"""
APEX SIGNAL FORMATTER  —  Visual Edition
═════════════════════════════════════════
Rich, colorful, eye-catching signal cards for Telegram and Discord.
Every field uses distinct visual language so traders can scan instantly.
"""
import time
import datetime
from apex_engine import (
    Signal, TradeParams,
    fmt_price, fmt_vol, score_bar,
    apex_grade, conviction_label, hold_str,
)
from config import HIST_WR

# ── Style lookups ─────────────────────────────────────────────
STYLE_META = {
    "scalp": ("⚡", "SCALP",  "5–15 min"),
    "day":   ("☀️", "DAY",    "30–120 min"),
    "swing": ("🌊", "SWING",  "2–8 hours"),
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
    """Color-coded APEX bar using filled blocks."""
    filled = round(score / 10)
    empty  = 10 - filled
    if score >= 90:
        bar = "🟦" * filled + "⬜" * empty
    elif score >= 82:
        bar = "🟩" * filled + "⬜" * empty
    elif score >= 78:
        bar = "🟨" * filled + "⬜" * empty
    else:
        bar = "🟧" * filled + "⬜" * empty
    return bar

def _rr_stars(rr: float) -> str:
    if rr >= 4.0: return "⭐⭐⭐⭐⭐"
    if rr >= 3.0: return "⭐⭐⭐⭐"
    if rr >= 2.5: return "⭐⭐⭐"
    if rr >= 2.0: return "⭐⭐"
    return "⭐"

def _wr_badge(wr: int) -> str:
    if wr >= 85: return "🏆 ELITE"
    if wr >= 80: return "🥇 HIGH"
    if wr >= 75: return "🥈 SOLID"
    return "🥉 GOOD"


# ══════════════════════════════════════════════════════════════
#  TELEGRAM  —  Rich HTML signal card
# ══════════════════════════════════════════════════════════════

def telegram_signal(sig: Signal) -> str:
    t   = sig.tier_meta()
    tr  = sig.trade
    si, sl, shld = STYLE_META.get(tr.style, ("⚡", "SCALP", "~15 min"))

    # ── Directional theme ─────────────────────────────────────
    is_long = tr.position == "LONG"
    DIR_ARROW  = "🚀" if is_long else "🔻"
    DIR_COLOR  = "LONG  🟢" if is_long else "SHORT 🔴"
    DIR_WORD   = "BULLISH" if is_long else "BEARISH"
    TIER_BADGE = "🔥 STRONG" if sig.tier == "T3" else "⭐ MEGA"

    # ── Re-entry / reversal banner ────────────────────────────
    reason = getattr(sig, "signal_reason", "new_coin")
    REASON_BANNERS = {
        "all_tp_hit": "╔════════════════════════════════╗\n"
                      "║  🎯  ALL TP HIT — RE-ENTRY     ║\n"
                      "║      Fresh targets calculated  ║\n"
                      "╚════════════════════════════════╝",
        "sl_hit":     "╔════════════════════════════════╗\n"
                      "║  🛑  STOP LOSS HIT — RE-ENTRY  ║\n"
                      "║      New setup — clean slate   ║\n"
                      "╚════════════════════════════════╝",
        "reversal":   "╔════════════════════════════════╗\n"
                      "║  🔄  DIRECTION REVERSAL        ║\n"
                      "║      Trend has flipped         ║\n"
                      "╚════════════════════════════════╝",
    }
    reason_block = ""
    if reason in REASON_BANNERS:
        reason_block = f"\n<pre>{REASON_BANNERS[reason]}</pre>\n"

    new_block = ""
    if sig.is_new_listing:
        new_block = "\n<pre>╔════════════════════════════════╗\n" \
                    "║  🆕  NEW BINANCE LISTING       ║\n" \
                    "╚════════════════════════════════╝</pre>\n"

    # ── Trade calculations ────────────────────────────────────
    tp1_d = _pct_from(sig.price, tr.tp1, tr.position)
    tp2_d = _pct_from(sig.price, tr.tp2, tr.position)
    tp3_d = _pct_from(sig.price, tr.tp3, tr.position)
    sl_d  = abs(_pct_from(sig.price, tr.sl, "SHORT" if is_long else "LONG"))
    reward_pct = abs(tp2_d)

    # ── APEX visual bar ───────────────────────────────────────
    apex_bar  = _apex_bar(sig.apex_score)
    rr_stars  = _rr_stars(tr.rr)
    wr_badge  = _wr_badge(tr.hist_wr)
    move_bar  = score_bar(sig.layers.FMT, 10)
    vol_bar   = score_bar(sig.layers.LVI, 10)
    mom_bar   = score_bar(sig.layers.WAS, 10)

    return (
        # ── HEADER ───────────────────────────────────────────
        f"<pre>"
        f"╔══════════════════════════════════╗\n"
        f"║  APEX SYSTEM™   {sig.tier}  {TIER_BADGE}  ║\n"
        f"╚══════════════════════════════════╝"
        f"</pre>"
        f"{reason_block}{new_block}"

        # ── COIN + MOVE ───────────────────────────────────────
        f"\n{DIR_ARROW}  <b>{sig.coin()}/USDT</b>   "
        f"<b>{sig.pct:+.2f}%</b>  24H\n"
        f"📅  <i>{_dt()}</i>\n"
        f"💧  Vol:  <b>{fmt_vol(sig.vol_usd)}</b>\n"

        # ── POSITION BLOCK ────────────────────────────────────
        f"\n<pre>"
        f"┌─────────────────────────────────┐\n"
        f"│  ③  POSITION   {DIR_COLOR:<16}│\n"
        f"│     {DIR_WORD} 24H BREAKOUT          │\n"
        f"│  ④  LEVERAGE   {tr.leverage}×                   │\n"
        f"│     Risk: 1–2% of account       │\n"
        f"└─────────────────────────────────┘"
        f"</pre>"

        # ── ENTRY ─────────────────────────────────────────────
        f"\n🎯  <b>② ENTRY ZONE</b>  <i>(Limit Order)</i>\n"
        f"<pre>"
        f"  Low  ▸  ${fmt_price(tr.entry_low)}\n"
        f"  High ▸  ${fmt_price(tr.entry_high)}\n"
        f"  Now  ▸  ${fmt_price(sig.price)}"
        f"</pre>"

        # ── TAKE PROFITS ──────────────────────────────────────
        f"\n💰  <b>⑤ TAKE PROFIT TARGETS</b>\n"
        f"<pre>"
        f"  🟡 TP1  ${fmt_price(tr.tp1):<14}({tp1_d:+.2f}%)  → 30%\n"
        f"  🟢 TP2  ${fmt_price(tr.tp2):<14}({tp2_d:+.2f}%)  → 50%\n"
        f"  🔵 TP3  ${fmt_price(tr.tp3):<14}({tp3_d:+.2f}%)  → 20%"
        f"</pre>"

        # ── STOP LOSS ─────────────────────────────────────────
        f"\n🛑  <b>⑥ STOP LOSS</b>\n"
        f"<pre>"
        f"  Price ▸  ${fmt_price(tr.sl)}\n"
        f"  Dist  ▸  -{sl_d:.2f}% from entry\n"
        f"  Rule  ▸  Hard stop — no override"
        f"</pre>"

        # ── TRADE SUMMARY ─────────────────────────────────────
        f"\n<pre>"
        f"┌─────────────────────────────────┐\n"
        f"│  ⑦  STYLE    {si} {sl:<20} │\n"
        f"│  ⑧  R:R      1 : {tr.rr:<5.2f}  {rr_stars:<12} │\n"
        f"│  ⑨  TIME     {shld:<22} │\n"
        f"│     WIN RATE {tr.hist_wr}%  {wr_badge:<14}  │\n"
        f"│     REWARD   +{reward_pct:<4.1f}%  if TP2 hit    │\n"
        f"│     RISK     -{sl_d:<4.2f}%  if SL hit     │\n"
        f"└─────────────────────────────────┘"
        f"</pre>"

        # ── APEX SCORE ────────────────────────────────────────
        f"\n<pre>"
        f"┌─────────────────────────────────┐\n"
        f"│  🧠  APEX SCORE   {sig.apex_score:3d} / 100      │\n"
        f"│  {apex_bar}          │\n"
        f"│  {apex_grade(sig.apex_score):<33}│\n"
        f"├─────────────────────────────────┤\n"
        f"│  📐 MOVE   {sig.layers.FMT:2d}/50   {move_bar}  │\n"
        f"│  💧 VOL    {sig.layers.LVI:2d}/35   {vol_bar}  │\n"
        f"│  🔁 MOM    {sig.layers.WAS:2d}/15   {mom_bar}  │\n"
        f"└─────────────────────────────────┘"
        f"</pre>"

        # ── FOOTER ────────────────────────────────────────────
        f"\n<i>⚠️  Not financial advice  ·  Always use stop loss</i>\n"
        f"<i>APEX SYSTEM™  ·  Binance Futures  ·  {_utc()}</i>"
    )


def telegram_new_listing(symbol: str) -> str:
    coin = symbol.replace("USDT", "")
    return (
        f"<pre>"
        f"╔══════════════════════════════════╗\n"
        f"║  🆕  NEW FUTURES LISTING  🆕    ║\n"
        f"╚══════════════════════════════════╝"
        f"</pre>\n"
        f"<b>{coin}/USDT</b>  is now live on Binance Futures\n"
        f"📅  {_dt()}\n\n"
        f"⚡ APEX scanner activated for <b>{coin}/USDT</b>\n"
        f"<i>New listings often see extreme moves in the first 1–6 hours.</i>"
    )


def telegram_stats(stats: dict, uptime_sec: float) -> str:
    h = int(uptime_sec // 3600)
    m = int((uptime_sec % 3600) // 60)
    s = int(uptime_sec % 60)

    def rr(f, r):
        return f"{r/(f+r)*100:.0f}%" if (f + r) > 0 else "n/a"

    t3f = stats.get("t3_fired",    0); t3r = stats.get("t3_rejected", 0)
    t4f = stats.get("t4_fired",    0); t4r = stats.get("t4_rejected", 0)
    last = stats.get("last_signal_ts")
    last_str = f"{int(time.time()-last)//60}m ago" if last else "none yet"

    return (
        f"<pre>"
        f"╔══════════════════════════════════╗\n"
        f"║  📡  APEX BOT  —  LIVE STATS   ║\n"
        f"╚══════════════════════════════════╝\n"
        f"\n"
        f"  ⏱  Uptime       {h:02d}:{m:02d}:{s:02d}\n"
        f"  📊  Pairs live   {stats.get('pairs_live', 0)}\n"
        f"  🔗  WS Frames    {stats.get('frames_total', 0):,}\n"
        f"  ⚡  Last signal  {last_str}\n"
        f"\n"
        f"  🔥 T3 STRONG  (≥10%  APEX≥82)\n"
        f"     Fired    {t3f:>6}\n"
        f"     Rejected {t3r:>6}  ({rr(t3f, t3r)} reject)\n"
        f"\n"
        f"  ⭐ T4 MEGA    (≥20%  APEX≥78)\n"
        f"     Fired    {t4f:>6}\n"
        f"     Rejected {t4r:>6}  ({rr(t4f, t4r)} reject)\n"
        f"\n"
        f"  🔁 Re-entries\n"
        f"     All TP   {stats.get('all_tp_reentries', 0):>6}\n"
        f"     SL Hit   {stats.get('sl_reentries', 0):>6}\n"
        f"     Reversal {stats.get('reversals', 0):>6}"
        f"</pre>"
    )


def telegram_winrates() -> str:
    lines = [
        "<pre>"
        "╔══════════════════════════════════╗\n"
        "║  📈  APEX HISTORICAL WIN RATES  ║\n"
        "╚══════════════════════════════════╝"
        "</pre>"
    ]
    for tier in ["T3", "T4"]:
        gate  = "≥82" if tier == "T3" else "≥78"
        icon  = "🔥" if tier == "T3" else "⭐"
        label = f"T3 STRONG  ≥10%  APEX{gate}" if tier == "T3" \
           else f"T4 MEGA    ≥20%  APEX{gate}"
        lines.append(f"\n{icon}  <b>{label}</b>")
        for style, (si, lbl, hold) in STYLE_META.items():
            wp = HIST_WR[tier][style]["pump"]
            wd = HIST_WR[tier][style]["dump"]
            lines.append(
                f"<code>  {si} {lbl:<5}  🚀 {wp}%   📉 {wd}%   ⏱ {hold}</code>"
            )
    lines.append("\n<i>Conservative estimates. Past performance ≠ future results.</i>")
    return "\n".join(lines)


def telegram_recent_signals(signals) -> str:
    if not signals:
        return (
            "<pre>📭  No signals fired yet this session.\n"
            "     APEX is scanning Binance Futures...</pre>"
        )
    lines = [
        "<pre>"
        "╔══════════════════════════════════╗\n"
        "║  📋  RECENT SIGNALS             ║\n"
        "╚══════════════════════════════════╝"
        "</pre>"
    ]
    for sig in list(signals)[:10]:
        t   = sig.tier_meta()
        ago = int(time.time() - sig.ts_epoch)
        di  = "🚀" if sig.direction == "PUMP" else "🔻"
        si, sl, _ = STYLE_META.get(sig.trade.style, ("⚡", "SCALP", ""))
        reason = getattr(sig, "signal_reason", "")
        rtag = "  🔄" if reason == "reversal" \
          else "  🎯" if reason == "all_tp_hit" \
          else "  🛑" if reason == "sl_hit" else ""
        pos_icon = "🟢" if sig.direction == "PUMP" else "🔴"
        lines.append(
            f"{t.get('icon','🔥')} <b>{sig.coin()}/USDT</b>  "
            f"{di} <code>{sig.pct:+.1f}%</code>  "
            f"{pos_icon} <code>{sig.trade.position}</code>  "
            f"APEX <code>{sig.apex_score}</code>  "
            f"{si} <code>{sl}</code>  "
            f"<code>1:{sig.trade.rr}</code>{rtag}  "
            f"<i>{ago//60}m ago</i>"
        )
    return "\n".join(lines)


def telegram_help() -> str:
    return (
        "<pre>"
        "╔══════════════════════════════════╗\n"
        "║  🧠  APEX SYSTEM™  BOT GUIDE   ║\n"
        "╚══════════════════════════════════╝"
        "</pre>\n"
        "<b>Commands</b>\n"
        "<code>  /start     </code> Activate signals\n"
        "<code>  /stop      </code> Pause signals\n"
        "<code>  /stats     </code> Session statistics\n"
        "<code>  /status    </code> Connection status\n"
        "<code>  /signals   </code> Last 10 signals\n"
        "<code>  /winrates  </code> Historical win rates\n"
        "<code>  /help      </code> This guide\n\n"
        "<b>Signal Tiers</b>\n"
        "<code>  🔥 T3 STRONG  ≥10% 24H  APEX≥82</code>\n"
        "<code>  ⭐ T4 MEGA    ≥20% 24H  APEX≥78</code>\n\n"
        "<b>Each signal includes</b>\n"
        "<code>  ① Pair        ② Entry zone\n"
        "  ③ Position     ④ Leverage\n"
        "  ⑤ TP1/TP2/TP3  ⑥ Stop loss\n"
        "  ⑦ Style        ⑧ R:R\n"
        "  ⑨ Expected time + APEX score</code>\n\n"
        "<b>Re-entry rules</b>  <i>(no timers)</i>\n"
        "<code>  🎯 All 3 TPs hit  → new targets\n"
        "  🛑 Stop loss hit  → fresh setup\n"
        "  🔄 Direction flip → immediate</code>\n\n"
        "<i>Not financial advice · Always use stop loss</i>"
    )


# ══════════════════════════════════════════════════════════════
#  DISCORD  —  Rich color embeds
# ══════════════════════════════════════════════════════════════

# Discord embed colors — distinct per tier × direction
_COLORS = {
    ("T4", "PUMP"): 0x00FFD1,   # cyan-teal   — T4 LONG
    ("T3", "PUMP"): 0x00E676,   # bright green — T3 LONG
    ("T4", "DUMP"): 0xFF1744,   # vivid red    — T4 SHORT
    ("T3", "DUMP"): 0xFF6D00,   # deep orange  — T3 SHORT
}


def discord_embed(sig: Signal) -> dict:
    t    = sig.tier_meta()
    ti   = t.get("icon", "🔥")
    tr   = sig.trade
    si, sl, shld = STYLE_META.get(tr.style, ("⚡", "SCALP", "~15 min"))

    color     = _COLORS.get((sig.tier, sig.direction), 0x34D399)
    is_long   = tr.position == "LONG"
    dir_arrow = "🚀" if is_long else "🔻"
    pos_badge = "🟢 LONG" if is_long else "🔴 SHORT"

    # Reason tag in title
    reason    = getattr(sig, "signal_reason", "new_coin")
    reason_tag = {
        "all_tp_hit": "  🎯 ALL-TP RE-ENTRY",
        "sl_hit"    : "  🛑 SL-HIT RE-ENTRY",
        "reversal"  : "  🔄 REVERSAL",
    }.get(reason, "")
    new_tag = "  🆕 NEW LISTING" if sig.is_new_listing else ""

    tp1_d = _pct_from(sig.price, tr.tp1, tr.position)
    tp2_d = _pct_from(sig.price, tr.tp2, tr.position)
    tp3_d = _pct_from(sig.price, tr.tp3, tr.position)
    sl_d  = abs(_pct_from(sig.price, tr.sl, "SHORT" if is_long else "LONG"))

    apex_bar = _apex_bar(sig.apex_score)
    rr_stars = _rr_stars(tr.rr)
    wr_badge = _wr_badge(tr.hist_wr)

    move_bar = score_bar(sig.layers.FMT, 8)
    vol_bar  = score_bar(sig.layers.LVI, 8)
    mom_bar  = score_bar(sig.layers.WAS, 8)

    title = (
        f"{ti} {sig.tier} {t.get('label','')}  {dir_arrow}  "
        f"{sig.coin()}/USDT  {sig.pct:+.2f}%"
        f"{reason_tag}{new_tag}"
    )

    description = (
        f"## {dir_arrow}  {sig.coin()}/USDT  `{sig.pct:+.2f}%`\n"
        f"> {pos_badge}  ·  Vol `{fmt_vol(sig.vol_usd)}`  ·  `{_dt()}`"
    )

    fields = [
        # Row 1 — Entry + Position + Leverage
        {
            "name" : "🎯 ② Entry Zone (Limit)",
            "value": f"`${fmt_price(tr.entry_low)}` → `${fmt_price(tr.entry_high)}`\nCurrent: `${fmt_price(sig.price)}`",
            "inline": True,
        },
        {
            "name" : "③ Position",
            "value": f"{pos_badge}\n{'Bullish breakout' if is_long else 'Bearish breakdown'}",
            "inline": True,
        },
        {
            "name" : "⚙️ ④ Leverage",
            "value": f"`{tr.leverage}×`\nRisk 1–2% / trade",
            "inline": True,
        },

        # Row 2 — Take Profits (full width)
        {
            "name" : "💰 ⑤ Take Profit Targets",
            "value": (
                f"🟡 **TP1**  `${fmt_price(tr.tp1)}`  `{tp1_d:+.2f}%`  → close **30%**\n"
                f"🟢 **TP2**  `${fmt_price(tr.tp2)}`  `{tp2_d:+.2f}%`  → close **50%**\n"
                f"🔵 **TP3**  `${fmt_price(tr.tp3)}`  `{tp3_d:+.2f}%`  → close **20%**"
            ),
            "inline": False,
        },

        # Row 3 — SL + Style + R:R
        {
            "name" : "🛑 ⑥ Stop Loss",
            "value": f"`${fmt_price(tr.sl)}`\n`-{sl_d:.2f}%` from entry",
            "inline": True,
        },
        {
            "name" : f"{si} ⑦ Trade Type",
            "value": f"**{sl}** Trade\n⏱ {shld}",
            "inline": True,
        },
        {
            "name" : "⚖️ ⑧ R:R",
            "value": f"`1 : {tr.rr:.2f}`\n{rr_stars}",
            "inline": True,
        },

        # Row 4 — Win rate (full width)
        {
            "name" : "📊 Historical Win Rate",
            "value": (
                f"{wr_badge}  **{tr.hist_wr}%** estimated\n"
                f"Risk `{tr.sl_pct:.1f}%`  ·  Reward to TP2 `{abs(tp2_d):.1f}%`"
            ),
            "inline": False,
        },

        # Row 5 — APEX score (full width)
        {
            "name" : "🧠 APEX Score",
            "value": (
                f"**{sig.apex_score}/100**  {apex_bar}\n"
                f"*{apex_grade(sig.apex_score)}*\n"
                f"`📐 MOVE  {sig.layers.FMT:2d}/50   {move_bar}`\n"
                f"`💧 VOL   {sig.layers.LVI:2d}/35   {vol_bar}`\n"
                f"`🔁 MOM   {sig.layers.WAS:2d}/15   {mom_bar}`"
            ),
            "inline": False,
        },
    ]

    return {
        "title"      : title,
        "description": description,
        "color"      : color,
        "fields"     : fields,
        "footer"     : {"text": f"APEX SYSTEM™  ·  Not financial advice  ·  Always use stop loss  ·  {_utc()}"},
    }


def discord_new_listing(symbol: str) -> str:
    coin = symbol.replace("USDT", "")
    return (
        f"## 🆕  New Futures Listing\n"
        f"### **{coin}/USDT** is now live on Binance Futures\n"
        f"> 📅 {_dt()}\n\n"
        f"⚡ APEX scanner is now watching **{coin}/USDT** for T3 🔥 and T4 ⭐ signals.\n"
        f"*New listings often see extreme volatility in the first 1–6 hours.*"
    )


def discord_stats(stats: dict, uptime_sec: float) -> str:
    h = int(uptime_sec // 3600); m = int((uptime_sec % 3600) // 60); s = int(uptime_sec % 60)
    def rr(f, r): return f"{r/(f+r)*100:.0f}%" if (f + r) > 0 else "n/a"
    t3f = stats.get("t3_fired", 0); t3r = stats.get("t3_rejected", 0)
    t4f = stats.get("t4_fired", 0); t4r = stats.get("t4_rejected", 0)
    return (
        f"**📡 APEX Bot — Live Stats**\n"
        f"```\n"
        f"Uptime       {h:02d}:{m:02d}:{s:02d}\n"
        f"Pairs live   {stats.get('pairs_live', 0)}\n"
        f"WS Frames    {stats.get('frames_total', 0):,}\n"
        f"\n"
        f"🔥 T3 STRONG  (≥10%  APEX≥82)\n"
        f"   Fired    {t3f:>6}   Rejected {t3r:>6}  ({rr(t3f,t3r)})\n"
        f"\n"
        f"⭐ T4 MEGA    (≥20%  APEX≥78)\n"
        f"   Fired    {t4f:>6}   Rejected {t4r:>6}  ({rr(t4f,t4r)})\n"
        f"\n"
        f"🎯 All-TP re-entries   {stats.get('all_tp_reentries',0)}\n"
        f"🛑 SL-hit re-entries   {stats.get('sl_reentries',0)}\n"
        f"🔄 Direction reversals {stats.get('reversals',0)}\n"
        f"```\n"
        f"*High rejection rate = higher quality signals*"
    )


def discord_recent_signals(signals) -> str:
    if not signals:
        return "📭 **No signals fired yet this session.**\n> APEX is scanning Binance Futures..."

    lines = ["**📋 Recent Signals**\n"]
    for sig in list(signals)[:10]:
        t   = sig.tier_meta()
        ago = int(time.time() - sig.ts_epoch)
        di  = "🚀" if sig.direction == "PUMP" else "🔻"
        pos = "🟢" if sig.direction == "PUMP" else "🔴"
        si, sl, _ = STYLE_META.get(sig.trade.style, ("⚡", "SCALP", ""))
        reason = getattr(sig, "signal_reason", "")
        rtag = " 🔄" if reason == "reversal" \
          else " 🎯" if reason == "all_tp_hit" \
          else " 🛑" if reason == "sl_hit" else ""
        lines.append(
            f"{t.get('icon','🔥')} **{sig.coin()}/USDT**  "
            f"{di} `{sig.pct:+.1f}%`  {pos} `{sig.trade.position}`  "
            f"APEX `{sig.apex_score}`  {si} `{sl}`  "
            f"R:R `1:{sig.trade.rr}`{rtag}  *{ago//60}m ago*"
        )
    return "\n".join(lines)
