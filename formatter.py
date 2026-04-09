"""
APEX-EDS v4.0 | formatter.py
Visually rich signal messages for Telegram (HTML) and Discord (embed).
"""

import time
from models import (
    Direction, MarketCondition, Regime,
    ScalpType, SignalResult,
)
import config

# ── PARSE MODE ────────────────────────────────────────────────────────────
TELEGRAM_PARSE_MODE = "HTML"

# ── LOOKUP TABLES ─────────────────────────────────────────────────────────
_TF = {
    ScalpType.MICRO:    ("⚡", "1M MICRO SCALP",    "5 – 15 min",  "Ultra-fast momentum burst"),
    ScalpType.STANDARD: ("🎯", "5M STANDARD SCALP", "12 – 35 min", "Structure breakout play"),
    ScalpType.EXTENDED: ("🔭", "15M EXTENDED SCALP","25 – 55 min", "High-conviction level break"),
}
_COND_EMOJI = {
    MarketCondition.STRONG_BULL: "🟢",
    MarketCondition.BULL:        "📈",
    MarketCondition.NORMAL:      "🔵",
    MarketCondition.BEAR:        "📉",
    MarketCondition.STRONG_BEAR: "🔴",
    MarketCondition.CHOPPY:      "🟡",
    MarketCondition.HIGH_VOL:    "⚡",
}
_REGIME_EMOJI = {
    Regime.TREND_UP:   "📈",
    Regime.TREND_DOWN: "📉",
    Regime.RANGE:      "↔️",
    Regime.VOLATILE:   "⚡",
    Regime.UNKNOWN:    "❔",
}


# ── HELPERS ───────────────────────────────────────────────────────────────

def _fp(price: float) -> str:
    if price >= 10_000: return f"{price:,.2f}"
    if price >= 100:    return f"{price:.3f}"
    if price >= 1:      return f"{price:.4f}"
    if price >= 0.01:   return f"{price:.5f}"
    return f"{price:.8f}"


def _pct(entry: float, target: float) -> str:
    if not entry: return "0.00%"
    p = (target - entry) / entry * 100
    arrow = "▲" if p >= 0 else "▼"
    return f"{arrow} {abs(p):.2f}%"


def _bar(score: float, width: int = 12) -> str:
    filled = round(score / 100 * width)
    block  = "█" if score >= 90 else ("▓" if score >= 80 else "▒")
    return block * filled + "░" * (width - filled)


def _mini(score: float, width: int = 8) -> str:
    filled = round(score / 100 * width)
    return "■" * filled + "□" * (width - filled)


def _tier(score: float) -> str:
    if score >= 95: return "🔥 ELITE"
    if score >= 90: return "⭐ APEX"
    if score >= 85: return "✅ STRONG"
    return "📊 VALID"


def _ts() -> str:
    return time.strftime("%-d %b %Y  %H:%M UTC", time.gmtime())


def _layer(icon: str, name: str, val: float) -> str:
    b   = _mini(val)
    col = ("#00ff88" if val >= 88 else "#00f5ff" if val >= 75 else
           "#ffd700" if val >= 60 else "#ff6b35")
    return (
        f'<code>{icon} {name:<12} {b}  </code>'
        f'<b><span style="color:{col}">{val:.1f}</span></b>'
    )


# ─────────────────────────────────────────────────────────────────────────
#  TELEGRAM  (HTML parse mode)
# ─────────────────────────────────────────────────────────────────────────

def build_telegram(sig: SignalResult) -> str:
    s  = sig
    sc = s.score
    is_long = s.direction == Direction.LONG

    tf_emoji, tf_label, hold, tf_desc = _TF[s.scalp_type]
    cond_emoji   = _COND_EMOJI.get(s.market_cond, "🔵")
    regime_emoji = _REGIME_EMOJI.get(s.regime, "📈")
    tier         = _tier(sc.total)
    apex_badge   = "⭐ APEX SIGNAL" if sc.total >= config.APEX_SCORE_TIER else "📡 SIGNAL"

    dir_banner = (
        "🟢 ═══  L O N G  ═══ 🟢" if is_long
        else "🔴 ═══  S H O R T  ═══ 🔴"
    )
    tp_icon = "🔼" if is_long else "🔽"
    sl_icon = "🔽" if is_long else "🔼"

    rr1 = f"1 : {s.rr_ratio:.1f}"
    rr2 = f"1 : {s.rr_ratio * 1.375:.1f}"
    rr3 = f"1 : {s.rr_ratio * 1.75:.1f}"

    return (
        f"╔══════════════════════════════╗\n"
        f"║  ⚡ <b>APEX-EDS  v4.0</b>  ·  {apex_badge}\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"  <b>{dir_banner}</b>\n"
        f"\n"
        f"💎  <b>{s.pair_display}</b>   {tf_emoji} <b>{tf_label}</b>\n"
        f"  <i>{tf_desc}</i>  ·  Hold  <b>{hold}</b>\n"
        f"\n"
        f"┌─────────────────────────────┐\n"
        f"│  📌  ENTRY ZONE  (Limit)    │\n"
        f"└─────────────────────────────┘\n"
        f"  <code>{_fp(s.entry_low)}</code>  ──  <code>{_fp(s.entry_high)}</code>\n"
        f"\n"
        f"  {'🔼' if is_long else '🔽'}  <b>Position</b>    <b>{s.direction.value}</b>\n"
        f"  ⚖️  <b>Leverage</b>    <b>{s.leverage}×</b>\n"
        f"\n"
        f"┌─────────────────────────────┐\n"
        f"│  🎯  TAKE PROFIT TARGETS    │\n"
        f"└─────────────────────────────┘\n"
        f"  {tp_icon} <b>TP1</b>  <code>{_fp(s.tp1)}</code>  │  <b>{_pct(s.entry_price, s.tp1)}</b>  │  <b>{rr1}</b>  ← 50%\n"
        f"  {tp_icon} <b>TP2</b>  <code>{_fp(s.tp2)}</code>  │  <b>{_pct(s.entry_price, s.tp2)}</b>  │  <b>{rr2}</b>  ← 30%\n"
        f"  {tp_icon} <b>TP3</b>  <code>{_fp(s.tp3)}</code>  │  <b>{_pct(s.entry_price, s.tp3)}</b>  │  <b>{rr3}</b>  ← 20%\n"
        f"\n"
        f"┌─────────────────────────────┐\n"
        f"│  🛑  STOP LOSS              │\n"
        f"└─────────────────────────────┘\n"
        f"  {sl_icon} <code>{_fp(s.stop_loss)}</code>  │  <b>{_pct(s.entry_price, s.stop_loss)}</b>  │  ATR × 0.8\n"
        f"\n"
        f"────────────────────────────────\n"
        f"  📊  R:R Ratio       <b>{rr1}</b>\n"
        f"  ⏱  Expected Hold   <b>{hold}</b>\n"
        f"  {cond_emoji}  Market          <b>{s.market_cond.value}</b>\n"
        f"  {regime_emoji}  Regime          <b>{s.regime.value}</b>\n"
        f"  💧  VPIN            <b>{s.vpin:.3f}</b>\n"
        f"  📈  CVD Delta      <b>{s.cvd:+.3f}</b>\n"
        f"────────────────────────────────\n"
        f"\n"
        f"┌─────────────────────────────┐\n"
        f"│  🧠  APEX SCORE  ·  {sc.total:.1f}/100  │\n"
        f"│  <code>{_bar(sc.total)}</code>  {tier}  │\n"
        f"└─────────────────────────────┘\n"
        f"<code>"
        f"💧 Vol+VPIN   {_mini(sc.volume_score)}  {sc.volume_score:>5.1f}\n"
        f"🌊 Regime     {_mini(sc.regime_score)}  {sc.regime_score:>5.1f}\n"
        f"🏗 Structure  {_mini(sc.structure_score)}  {sc.structure_score:>5.1f}\n"
        f"⚡ Momentum  {_mini(sc.momentum_score)}  {sc.momentum_score:>5.1f}\n"
        f"🤖 AI Signal  {_mini(sc.ai_score)}  {sc.ai_score:>5.1f}\n"
        f"📊 Spread     {_mini(sc.spread_score)}  {sc.spread_score:>5.1f}\n"
        f"🕐 Session    {_mini(sc.session_score)}  {sc.session_score:>5.1f}"
        f"</code>\n"
        f"\n"
        f"🕐  <i>{_ts()}</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )


# ─────────────────────────────────────────────────────────────────────────
#  DISCORD  (embed dict)
# ─────────────────────────────────────────────────────────────────────────

def _embed_color(sig: SignalResult) -> int:
    is_long = sig.direction == Direction.LONG
    score   = sig.score.total
    if score >= 95:
        return 0xFFD700
    if is_long and score >= 90:
        return 0x00FF88
    if is_long:
        return 0x00C864
    if score >= 90:
        return 0xFF2255
    return 0xFF6B35


def build_discord(sig: SignalResult) -> dict:
    s  = sig
    sc = s.score
    is_long = s.direction == Direction.LONG
    color   = _embed_color(sig)

    tf_emoji, tf_label, hold, tf_desc = _TF[s.scalp_type]
    cond_emoji   = _COND_EMOJI.get(s.market_cond, "🔵")
    regime_emoji = _REGIME_EMOJI.get(s.regime, "📈")
    tier         = _tier(sc.total)
    apex_badge   = "⭐ APEX SIGNAL" if sc.total >= config.APEX_SCORE_TIER else "📡 SIGNAL"
    dir_label    = "🟢  LONG" if is_long else "🔴  SHORT"
    bar          = _bar(sc.total, 14)

    rr1 = f"1 : {s.rr_ratio:.1f}"
    rr2 = f"1 : {s.rr_ratio * 1.375:.1f}"
    rr3 = f"1 : {s.rr_ratio * 1.75:.1f}"
    tp_icon = "🔼" if is_long else "🔽"

    return {
        "title": f"⚡  {s.pair_display}   ·   {dir_label}   ·   {apex_badge}",
        "description": (
            f"{tf_emoji}  **{tf_label}**  ·  *{tf_desc}*  ·  Hold **{hold}**\n"
            f"{cond_emoji}  Market: **{s.market_cond.value}**  "
            f"{regime_emoji}  Regime: **{s.regime.value}**\n"
            f"💧 VPIN: **{s.vpin:.3f}**   📈 CVD: **{s.cvd:+.3f}**"
        ),
        "color": color,
        "fields": [
            # Row 1 ── Entry
            {"name": "📌  Entry Zone (Limit Order)",
             "value": f"```\n{_fp(s.entry_low)}  ──  {_fp(s.entry_high)}\n```",
             "inline": True},
            {"name": "📍  Position",
             "value": f"**{s.direction.value}**",
             "inline": True},
            {"name": "⚖️  Leverage",
             "value": f"**{s.leverage}×**",
             "inline": True},
            # Row 2 ── TPs
            {"name": f"{tp_icon}  TP1  ← Close 50%",
             "value": f"`{_fp(s.tp1)}`\n**{_pct(s.entry_price, s.tp1)}**\nR:R  **{rr1}**",
             "inline": True},
            {"name": f"{tp_icon}  TP2  ← Close 30%",
             "value": f"`{_fp(s.tp2)}`\n**{_pct(s.entry_price, s.tp2)}**\nR:R  **{rr2}**",
             "inline": True},
            {"name": f"{tp_icon}  TP3  ← Close 20%",
             "value": f"`{_fp(s.tp3)}`\n**{_pct(s.entry_price, s.tp3)}**\nR:R  **{rr3}**",
             "inline": True},
            # Row 3 ── SL + R:R + Hold
            {"name": "🛑  Stop Loss  (ATR × 0.8)",
             "value": f"`{_fp(s.stop_loss)}`\n**{_pct(s.entry_price, s.stop_loss)}**",
             "inline": True},
            {"name": "📊  Best R:R",
             "value": f"**{rr1}**",
             "inline": True},
            {"name": "⏱  Expected Hold",
             "value": f"**{hold}**",
             "inline": True},
            # Score (full width)
            {"name": f"🧠  APEX SCORE  ·  {sc.total:.1f} / 100  ·  {tier}",
             "value": (
                 f"```\n{bar}\n```\n"
                 f"💧 Vol+VPIN `{sc.volume_score:>5.1f}`  "
                 f"🌊 Regime `{sc.regime_score:>5.1f}`  "
                 f"🏗 Structure `{sc.structure_score:>5.1f}`\n"
                 f"⚡ Momentum `{sc.momentum_score:>5.1f}`  "
                 f"🤖 AI `{sc.ai_score:>5.1f}`  "
                 f"📊 Spread `{sc.spread_score:>5.1f}`  "
                 f"🕐 Session `{sc.session_score:>5.1f}`"
             ),
             "inline": False},
        ],
        "footer": {
            "text": (
                f"APEX-EDS v4.0  ·  312 Pairs  ·  7-Layer Bayesian  ·  "
                f"R:R ≥ 1:4  ·  Score ≥ 85  ·  {_ts()}"
            )
        },
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
