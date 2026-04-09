# ============================================================
#  APEX-EDS v4.0  |  formatter.py
#  Visually stunning signal messages — Telegram + Discord
#  Full color, emoji-rich, easy to scan at a glance
# ============================================================

import time
from apex_engine import (
    SignalResult, ScalpType, Direction,
    MarketCondition, Regime
)
import config


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SHARED HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _fmt_price(price: float) -> str:
    if price >= 10_000:  return f"{price:,.2f}"
    if price >= 100:     return f"{price:,.3f}"
    if price >= 1:       return f"{price:.4f}"
    if price >= 0.01:    return f"{price:.5f}"
    return f"{price:.8f}"


def _pct(entry: float, target: float) -> str:
    if entry == 0: return "0.00%"
    p = (target - entry) / entry * 100
    return f"{'▲' if p >= 0 else '▼'} {abs(p):.2f}%"


def _score_bar_blocks(score: float, width: int = 12) -> str:
    """Gradient block bar: green→yellow→orange→red based on score."""
    filled = round(score / 100 * width)
    if score >= 90:
        block = "█"
    elif score >= 80:
        block = "▓"
    else:
        block = "▒"
    return block * filled + "░" * (width - filled)


def _mini_bar(score: float, width: int = 8) -> str:
    filled = round(score / 100 * width)
    return "■" * filled + "□" * (width - filled)


def _tier_label(score: float) -> str:
    if score >= 95: return "🔥 ELITE"
    if score >= 90: return "⭐ APEX"
    if score >= 85: return "✅ STRONG"
    return "📊 VALID"


def _timestamp() -> str:
    return time.strftime("%-d %b %Y  %H:%M UTC", time.gmtime())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM MESSAGE BUILDER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Scalp-type visual identity
_TF_META = {
    ScalpType.MICRO:    ("⚡", "1M MICRO SCALP",    "5 – 15 min",  "Ultra-fast momentum burst"),
    ScalpType.STANDARD: ("🎯", "5M STANDARD SCALP", "12 – 35 min", "Structure breakout play"),
    ScalpType.EXTENDED: ("🔭", "15M EXTENDED SCALP","25 – 55 min", "High-conviction level break"),
}

# Market condition colors and emojis
_COND_EMOJI = {
    MarketCondition.STRONG_BULL: "🟢",
    MarketCondition.BULL:        "📈",
    MarketCondition.NORMAL:      "🔵",
    MarketCondition.BEAR:        "📉",
    MarketCondition.STRONG_BEAR: "🔴",
    MarketCondition.CHOPPY:      "🟡",
    MarketCondition.HIGH_VOL:    "⚡",
}

# Regime colors
_REGIME_EMOJI = {
    Regime.TREND_UP:   "📈",
    Regime.TREND_DOWN: "📉",
    Regime.RANGE:      "↔️",
    Regime.VOLATILE:   "⚡",
    Regime.UNKNOWN:    "❔",
}

def build_telegram_message(sig: SignalResult) -> str:
    """
    Craft a visually rich Telegram message.
    Uses MarkdownV2 — all special chars escaped inside code/raw sections.
    Plain text sections with emojis are left unescaped.
    Strategy: Use HTML parse mode for maximum color control.
    """
    s   = sig
    sc  = s.score
    is_long = s.direction == Direction.LONG

    tf_emoji, tf_label, hold_range, tf_desc = _TF_META[s.scalp_type]
    cond_emoji = _COND_EMOJI.get(s.market_cond, "🔵")
    regime_emoji = _REGIME_EMOJI.get(s.regime, "📈")

    score_bar  = _score_bar_blocks(sc.total)
    tier       = _tier_label(sc.total)
    apex_badge = "⭐ APEX SIGNAL" if sc.total >= config.APEX_SCORE_TIER else "📡 SIGNAL"

    # Direction styling
    if is_long:
        dir_banner  = "🟢 ═══  L O N G  ═══ 🟢"
        dir_icon    = "🔼"
        sl_arrow    = "🔽"
        tp_arrow    = "🔼"
    else:
        dir_banner  = "🔴 ═══  S H O R T  ═══ 🔴"
        dir_icon    = "🔽"
        sl_arrow    = "🔼"
        tp_arrow    = "🔽"

    p = _fmt_price

    # TP percentages
    tp1_pct = _pct(s.entry_price, s.tp1)
    tp2_pct = _pct(s.entry_price, s.tp2)
    tp3_pct = _pct(s.entry_price, s.tp3)
    sl_pct  = _pct(s.entry_price, s.stop_loss)

    # RR display
    rr1 = f"1 : {s.rr_ratio:.1f}"
    rr2 = f"1 : {s.rr_ratio * 1.375:.1f}"
    rr3 = f"1 : {s.rr_ratio * 1.75:.1f}"

    # Score layer mini-bars
    def layer_line(name: str, val: float, icon: str) -> str:
        bar = _mini_bar(val)
        return f"{icon} {name:<12} {bar}  {val:>5.1f}"

    score_details = "\n".join([
        layer_line("Vol + VPIN",  sc.volume_score,    "💧"),
        layer_line("Regime",      sc.regime_score,    "🌊"),
        layer_line("Structure",   sc.structure_score, "🏗"),
        layer_line("Momentum",    sc.momentum_score,  "⚡"),
        layer_line("AI Signal",   sc.ai_score,        "🤖"),
        layer_line("Spread",      sc.spread_score,    "📊"),
        layer_line("Session",     sc.time_score,      "🕐"),
    ])

    msg = (
        f"╔══════════════════════════════╗\n"
        f"║  ⚡ APEX-EDS  v4.0  ·  {apex_badge}\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"  {dir_banner}\n"
        f"\n"
        f"💎  <b>{s.pair_display}</b>   {tf_emoji} <b>{tf_label}</b>\n"
        f"     {tf_desc}  ·  Hold  <b>{hold_range}</b>\n"
        f"\n"
        f"┌─────────────────────────────────┐\n"
        f"│  📌  ENTRY ZONE  (Limit Order)  │\n"
        f"└─────────────────────────────────┘\n"
        f"  <code>{p(s.entry_low)}</code>  ──  <code>{p(s.entry_high)}</code>\n"
        f"  Place your limit anywhere in this zone\n"
        f"\n"
        f"  {dir_icon}  Position    <b>{s.direction.value}</b>\n"
        f"  ⚖️  Leverage    <b>{s.leverage}×</b>\n"
        f"\n"
        f"┌─────────────────────────────────┐\n"
        f"│  🎯  TAKE PROFIT  TARGETS       │\n"
        f"└─────────────────────────────────┘\n"
        f"  {tp_arrow} TP1  <code>{p(s.tp1)}</code>  │  <b>{tp1_pct}</b>  │  R:R  <b>{rr1}</b>  ← Close 50%\n"
        f"  {tp_arrow} TP2  <code>{p(s.tp2)}</code>  │  <b>{tp2_pct}</b>  │  R:R  <b>{rr2}</b>  ← Close 30%\n"
        f"  {tp_arrow} TP3  <code>{p(s.tp3)}</code>  │  <b>{tp3_pct}</b>  │  R:R  <b>{rr3}</b>  ← Close 20%\n"
        f"\n"
        f"┌─────────────────────────────────┐\n"
        f"│  🛑  STOP LOSS                  │\n"
        f"└─────────────────────────────────┘\n"
        f"  {sl_arrow} SL  <code>{p(s.stop_loss)}</code>  │  <b>{sl_pct}</b>  │  ATR × 0.8\n"
        f"\n"
        f"────────────────────────────────────\n"
        f"  📊  R:R Ratio       <b>{rr1}</b>\n"
        f"  ⏱  Expected Hold   <b>{hold_range}</b>\n"
        f"  {cond_emoji}  Market            <b>{s.market_cond.value}</b>\n"
        f"  {regime_emoji}  Regime            <b>{s.regime.value}</b>\n"
        f"  💧  VPIN              <b>{s.vpin:.3f}</b>  (≥ 0.65 = smart flow)\n"
        f"  📈  CVD Delta        <b>{s.cvd_divergence:+.3f}</b>\n"
        f"────────────────────────────────────\n"
        f"\n"
        f"┌─────────────────────────────────┐\n"
        f"│  🧠  APEX SCORE  ·  {sc.total:.1f} / 100  │\n"
        f"│  <code>{score_bar}</code>  {tier}  │\n"
        f"└─────────────────────────────────┘\n"
        f"<code>\n"
        f"{score_details}\n"
        f"</code>\n"
        f"\n"
        f"🕐  <i>{_timestamp()}</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    return msg


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DISCORD EMBED BUILDER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Score → embed sidebar color
def _embed_color(sig: SignalResult) -> int:
    is_long = sig.direction == Direction.LONG
    score   = sig.score.total

    if score >= 95:
        return 0xFFD700   # 🥇 Gold  — Elite signal
    if is_long and score >= 90:
        return 0x00FF88   # 🟢 Bright green — Apex long
    if is_long and score >= 85:
        return 0x00C864   # 🟢 Medium green — Strong long
    if not is_long and score >= 90:
        return 0xFF2255   # 🔴 Bright red — Apex short
    if not is_long and score >= 85:
        return 0xFF6B35   # 🟠 Orange — Strong short
    return 0x00F5FF       # 🔵 Cyan — Default


def build_discord_embed(sig: SignalResult) -> dict:
    """
    Returns a single richly-styled Discord embed dict.
    Discord supports **bold**, `code`, and *italic* in field values.
    """
    s   = sig
    sc  = s.score
    is_long = s.direction == Direction.LONG
    p   = _fmt_price

    tf_emoji, tf_label, hold_range, tf_desc = _TF_META[s.scalp_type]
    cond_emoji  = _COND_EMOJI.get(s.market_cond, "🔵")
    regime_emoji = _REGIME_EMOJI.get(s.regime, "📈")
    tier        = _tier_label(sc.total)
    color       = _embed_color(sig)
    score_bar   = _score_bar_blocks(sc.total, 14)

    dir_label = "🟢  LONG" if is_long else "🔴  SHORT"
    tp_icon   = "🔼" if is_long else "🔽"
    sl_icon   = "🔽" if is_long else "🔼"

    tp1_pct = _pct(s.entry_price, s.tp1)
    tp2_pct = _pct(s.entry_price, s.tp2)
    tp3_pct = _pct(s.entry_price, s.tp3)
    sl_pct  = _pct(s.entry_price, s.stop_loss)

    rr1 = f"1 : {s.rr_ratio:.1f}"
    rr2 = f"1 : {s.rr_ratio * 1.375:.1f}"
    rr3 = f"1 : {s.rr_ratio * 1.75:.1f}"

    apex_badge = "⭐ APEX SIGNAL" if sc.total >= config.APEX_SCORE_TIER else "📡 SIGNAL"

    # ── TITLE ────────────────────────────────────────────────
    title = f"⚡  {s.pair_display}   ·   {dir_label}   ·   {apex_badge}"

    # ── DESCRIPTION ──────────────────────────────────────────
    description = (
        f"{tf_emoji}  **{tf_label}**  ·  *{tf_desc}*  ·  Hold **{hold_range}**\n"
        f"{cond_emoji}  Market: **{s.market_cond.value}**   "
        f"{regime_emoji}  Regime: **{s.regime.value}**\n"
        f"💧  VPIN: **{s.vpin:.3f}**   📈  CVD Delta: **{s.cvd_divergence:+.3f}**"
    )

    # ── FIELDS ───────────────────────────────────────────────
    fields = [

        # ── Row 1: Entry ─────────────────────────────────────
        {
            "name":   "📌  Entry Zone  (Limit Order)",
            "value":  f"```\n{p(s.entry_low)}  ──  {p(s.entry_high)}\n```",
            "inline": True,
        },
        {
            "name":   "📍  Position",
            "value":  f"**{s.direction.value}**",
            "inline": True,
        },
        {
            "name":   "⚖️  Leverage",
            "value":  f"**{s.leverage}×**",
            "inline": True,
        },

        # ── Row 2: TP targets ────────────────────────────────
        {
            "name":  "🎯  TP1  ← Close 50%",
            "value": (
                f"`{p(s.tp1)}`\n"
                f"**{tp1_pct}**\n"
                f"R:R  **{rr1}**"
            ),
            "inline": True,
        },
        {
            "name":  "🎯  TP2  ← Close 30%",
            "value": (
                f"`{p(s.tp2)}`\n"
                f"**{tp2_pct}**\n"
                f"R:R  **{rr2}**"
            ),
            "inline": True,
        },
        {
            "name":  "🎯  TP3  ← Close 20%",
            "value": (
                f"`{p(s.tp3)}`\n"
                f"**{tp3_pct}**\n"
                f"R:R  **{rr3}**"
            ),
            "inline": True,
        },

        # ── Row 3: SL + timing ───────────────────────────────
        {
            "name":  "🛑  Stop Loss  (ATR × 0.8)",
            "value": f"`{p(s.stop_loss)}`\n**{sl_pct}**",
            "inline": True,
        },
        {
            "name":  "📊  Best R:R",
            "value": f"**{rr1}**",
            "inline": True,
        },
        {
            "name":  "⏱  Expected Hold",
            "value": f"**{hold_range}**",
            "inline": True,
        },

        # ── APEX SCORE (full width) ───────────────────────────
        {
            "name":  f"🧠  APEX SCORE  ·  {sc.total:.1f} / 100  ·  {tier}",
            "value": (
                f"```\n{score_bar}\n```\n"
                f"💧 Vol+VPIN `{sc.volume_score:>5.1f}`   "
                f"🌊 Regime   `{sc.regime_score:>5.1f}`   "
                f"🏗 Structure `{sc.structure_score:>5.1f}`\n"
                f"⚡ Momentum `{sc.momentum_score:>5.1f}`   "
                f"🤖 AI       `{sc.ai_score:>5.1f}`   "
                f"📊 Spread   `{sc.spread_score:>5.1f}`   "
                f"🕐 Session  `{sc.time_score:>5.1f}`"
            ),
            "inline": False,
        },
    ]

    embed = {
        "title":       title,
        "description": description,
        "color":       color,
        "fields":      fields,
        "footer": {
            "text": (
                f"APEX-EDS v4.0  ·  312 Pairs  ·  7-Layer Bayesian  ·  "
                f"R:R ≥ 1:4  ·  Score ≥ 85  ·  {_timestamp()}"
            ),
            "icon_url": "https://i.imgur.com/4M34hi2.png",
        },
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return embed


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM: parse_mode switch
#  Call build_telegram_message() — uses HTML parse_mode
#  (set parse_mode="HTML" in telegram_bot.py _post() calls)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TELEGRAM_PARSE_MODE = "HTML"
