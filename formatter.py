"""
APEX-EDS v4.0 | formatter.py
Telegram HTML + Discord embed signal messages.
Every signal shows: Trade#, All-Time WR, Daily WR, Monthly WR, W/L, PNL.
"""
import time
from models import Direction, MarketCondition, Regime, ScalpType, SignalResult
import config

TELEGRAM_PARSE_MODE = "HTML"

_TF = {
    ScalpType.MICRO:    ("⚡","1M MICRO SCALP",    "5 – 15 min",  "Ultra-fast momentum burst"),
    ScalpType.STANDARD: ("🎯","5M STANDARD SCALP", "12 – 35 min", "Structure breakout play"),
    ScalpType.EXTENDED: ("🔭","15M EXTENDED SCALP","25 – 55 min", "High-conviction level break"),
}
_COND = {
    MarketCondition.STRONG_BULL:"🟢", MarketCondition.BULL:"📈",
    MarketCondition.NORMAL:"🔵",       MarketCondition.BEAR:"📉",
    MarketCondition.STRONG_BEAR:"🔴",  MarketCondition.CHOPPY:"🟡",
    MarketCondition.HIGH_VOL:"⚡",
}
_REG = {
    Regime.TREND_UP:"📈", Regime.TREND_DOWN:"📉",
    Regime.RANGE:"↔️",    Regime.VOLATILE:"⚡", Regime.UNKNOWN:"❔",
}


def _fp(p):
    if p>=10000: return f"{p:,.2f}"
    if p>=100:   return f"{p:.3f}"
    if p>=1:     return f"{p:.4f}"
    if p>=0.01:  return f"{p:.5f}"
    return f"{p:.8f}"

def _pct(e, t):
    if not e: return "0.00%"
    v=(t-e)/e*100; return f"{'▲' if v>=0 else '▼'} {abs(v):.2f}%"

def _bar(s, w=12):
    f=round(s/100*w); b="█" if s>=90 else ("▓" if s>=80 else "▒")
    return b*f+"░"*(w-f)

def _mini(s, w=8):
    f=round(s/100*w); return "■"*f+"□"*(w-f)

def _tier(s):
    if s>=95: return "🔥 ELITE"
    if s>=90: return "⭐ APEX"
    if s>=85: return "✅ STRONG"
    return "📊 VALID"

def _ts(): return time.strftime("%-d %b %Y  %H:%M UTC", time.gmtime())
def _wr_e(wr, hd): return ("🔥" if wr>=90 else "✅" if wr>=80 else "📊" if wr>=70 else "⚠️") if hd else "⏳"
def _ps(v, hd): return (f"{'📈' if v>=0 else '📉'} {'+' if v>=0 else ''}{v:.2f}R") if hd else "—"
def _ws(wr, hd): return f"<b>{wr:.1f}%</b>" if hd else "<b>—</b>"
def _wls(w, l, hd): return f"✅{w}W ❌{l}L" if (hd or w+l>0) else "No closed trades yet"


def _stats_block(st: dict) -> str:
    has=st.get("has_history",False); wr=st.get("win_rate",0); w=st.get("wins",0); l=st.get("losses",0); pnl=st.get("total_pnl_r",0)
    dhd=st.get("daily_has_data",False); dwr=st.get("daily_win_rate",0); dw=st.get("daily_wins",0); dl=st.get("daily_losses",0); dpnl=st.get("daily_pnl_r",0); dst=st.get("sigs_today",0); dk=st.get("today_key","")
    mhd=st.get("monthly_has_data",False); mwr=st.get("monthly_win_rate",0); mw=st.get("monthly_wins",0); ml=st.get("monthly_losses",0); mpnl=st.get("monthly_pnl_r",0); smo=st.get("sigs_month",0); mk=st.get("month_key","")
    return (
        f"╔══════════════════════════════════╗\n"
        f"║       📊  BOT PERFORMANCE         ║\n"
        f"╠══════════════════════════════════╣\n"
        f"║\n"
        f"║  🏆  ALL-TIME WIN RATE\n"
        f"║  {_wr_e(wr,has)} {_ws(wr,has)}   {_wls(w,l,has)}\n"
        f"║  💰 Total PNL: <b>{_ps(pnl,has)}</b>\n"
        f"║\n"
        f"║  📅  TODAY  ({dk})\n"
        f"║  {_wr_e(dwr,dhd)} {_ws(dwr,dhd)}   {_wls(dw,dl,dhd)}   Signals: <b>{dst}</b>\n"
        f"║  💰 Daily PNL: <b>{_ps(dpnl,dhd)}</b>\n"
        f"║\n"
        f"║  🗓  THIS MONTH  ({mk})\n"
        f"║  {_wr_e(mwr,mhd)} {_ws(mwr,mhd)}   {_wls(mw,ml,mhd)}   Signals: <b>{smo}</b>\n"
        f"║  💰 Monthly PNL: <b>{_ps(mpnl,mhd)}</b>\n"
        f"║\n"
        f"╚══════════════════════════════════╝"
    )


def build_telegram(sig: SignalResult, stats: dict) -> str:
    s=sig; sc=s.score; il=s.direction==Direction.LONG
    te,tl,hold,td=_TF[s.scalp_type]
    ce=_COND.get(s.market_cond,"🔵"); re=_REG.get(s.regime,"📈")
    tier=_tier(sc.total); badge="⭐ APEX SIGNAL" if sc.total>=config.APEX_SCORE_TIER else "📡 SIGNAL"
    dban="🟢 ═══  L O N G  ═══ 🟢" if il else "🔴 ═══  S H O R T  ═══ 🔴"
    ti="🔼" if il else "🔽"; si="🔽" if il else "🔼"
    r1=f"1:{s.rr_ratio:.1f}"; r2=f"1:{s.rr_ratio*1.375:.1f}"; r3=f"1:{s.rr_ratio*1.75:.1f}"
    tn=stats.get("trade_num",1)
    return (
        f"┌─────────────────────────────────┐\n"
        f"│  ⚡ <b>APEX-EDS v4.0</b>  ·  {badge}\n"
        f"│  📊 <b>Trade  # {tn}</b>\n"
        f"└─────────────────────────────────┘\n\n"
        f"  <b>{dban}</b>\n\n"
        f"💎  <b>{s.pair_display}</b>   {te} <b>{tl}</b>\n"
        f"  <i>{td}</i>  ·  Hold  <b>{hold}</b>\n\n"
        f"┌─────────────────────────────────┐\n"
        f"│  📌  ENTRY ZONE  (Limit Order)  │\n"
        f"└─────────────────────────────────┘\n"
        f"  <code>{_fp(s.entry_low)}</code>  ──  <code>{_fp(s.entry_high)}</code>\n\n"
        f"  {'🔼' if il else '🔽'}  <b>Position</b>    <b>{s.direction.value}</b>\n"
        f"  ⚖️  <b>Leverage</b>    <b>{s.leverage}×</b>\n\n"
        f"┌─────────────────────────────────┐\n"
        f"│  🎯  TAKE PROFIT TARGETS        │\n"
        f"└─────────────────────────────────┘\n"
        f"  {ti} <b>TP1</b>  <code>{_fp(s.tp1)}</code>  │  <b>{_pct(s.entry_price,s.tp1)}</b>  │  <b>{r1}</b>  ← 50%\n"
        f"  {ti} <b>TP2</b>  <code>{_fp(s.tp2)}</code>  │  <b>{_pct(s.entry_price,s.tp2)}</b>  │  <b>{r2}</b>  ← 30%\n"
        f"  {ti} <b>TP3</b>  <code>{_fp(s.tp3)}</code>  │  <b>{_pct(s.entry_price,s.tp3)}</b>  │  <b>{r3}</b>  ← 20%\n\n"
        f"┌─────────────────────────────────┐\n"
        f"│  🛑  STOP LOSS                  │\n"
        f"└─────────────────────────────────┘\n"
        f"  {si} <code>{_fp(s.stop_loss)}</code>  │  <b>{_pct(s.entry_price,s.stop_loss)}</b>  │  ATR×0.8\n\n"
        f"────────────────────────────────────\n"
        f"  📊  R:R Ratio       <b>{r1}</b>\n"
        f"  ⏱  Expected Hold   <b>{hold}</b>\n"
        f"  {ce}  Market          <b>{s.market_cond.value}</b>\n"
        f"  {re}  Regime          <b>{s.regime.value}</b>\n"
        f"  💧  VPIN            <b>{s.vpin:.3f}</b>\n"
        f"  📈  CVD Delta      <b>{s.cvd:+.3f}</b>\n"
        f"────────────────────────────────────\n\n"
        f"┌─────────────────────────────────┐\n"
        f"│  🧠  APEX SCORE  ·  {sc.total:.1f}/100  │\n"
        f"│  <code>{_bar(sc.total)}</code>  {tier}  │\n"
        f"└─────────────────────────────────┘\n"
        f"<code>"
        f"💧 Vol+VPIN   {_mini(sc.volume_score)}  {sc.volume_score:>5.1f}\n"
        f"🌊 Regime     {_mini(sc.regime_score)}  {sc.regime_score:>5.1f}\n"
        f"🏗 Structure  {_mini(sc.structure_score)}  {sc.structure_score:>5.1f}\n"
        f"⚡ Momentum  {_mini(sc.momentum_score)}  {sc.momentum_score:>5.1f}\n"
        f"🤖 AI Signal  {_mini(sc.ai_score)}  {sc.ai_score:>5.1f}\n"
        f"📊 Spread     {_mini(sc.spread_score)}  {sc.spread_score:>5.1f}\n"
        f"🕐 Session    {_mini(sc.session_score)}  {sc.session_score:>5.1f}"
        f"</code>\n\n"
        + _stats_block(stats) +
        f"\n🕐  <i>{_ts()}</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )


def _color(sig):
    il=sig.direction==Direction.LONG; s=sig.score.total
    if s>=95: return 0xFFD700
    if il and s>=90: return 0x00FF88
    if il: return 0x00C864
    if s>=90: return 0xFF2255
    return 0xFF6B35


def build_discord(sig: SignalResult, stats: dict) -> dict:
    s=sig; sc=s.score; il=s.direction==Direction.LONG
    te,tl,hold,td=_TF[s.scalp_type]
    ce=_COND.get(s.market_cond,"🔵"); re=_REG.get(s.regime,"📈")
    tier=_tier(sc.total); badge="⭐ APEX SIGNAL" if sc.total>=config.APEX_SCORE_TIER else "📡 SIGNAL"
    dl="🟢  LONG" if il else "🔴  SHORT"; ti="🔼" if il else "🔽"
    r1=f"1:{s.rr_ratio:.1f}"; r2=f"1:{s.rr_ratio*1.375:.1f}"; r3=f"1:{s.rr_ratio*1.75:.1f}"
    tn=stats.get("trade_num",1)

    has=stats.get("has_history",False); wr=stats.get("win_rate",0); w=stats.get("wins",0); l=stats.get("losses",0); pnl=stats.get("total_pnl_r",0)
    dhd=stats.get("daily_has_data",False); dwr=stats.get("daily_win_rate",0); dw=stats.get("daily_wins",0); dl2=stats.get("daily_losses",0); dpnl=stats.get("daily_pnl_r",0); dst=stats.get("sigs_today",0); dk=stats.get("today_key","")
    mhd=stats.get("monthly_has_data",False); mwr=stats.get("monthly_win_rate",0); mw=stats.get("monthly_wins",0); ml2=stats.get("monthly_losses",0); mpnl=stats.get("monthly_pnl_r",0); smo=stats.get("sigs_month",0); mk=stats.get("month_key","")

    def wr_d(r,h): return f"**{r:.1f}%**" if h else "**—**"
    def wl_d(ww,ll,h): return f"✅{ww}W / ❌{ll}L" if (h or ww+ll>0) else "*No closed trades*"
    def ps_d(v,h):
        if not h: return "—"
        return f"{'📈' if v>=0 else '📉'} **{'+' if v>=0 else ''}{v:.2f}R**"

    stats_val = (
        f"**🏆 All-Time**  {wr_d(wr,has)}  ·  {wl_d(w,l,has)}"
        + (f"  ·  PNL: {'+' if pnl>=0 else ''}{pnl:.2f}R" if has else "") + "\n"
        f"**📅 Today** `{dk}`  {wr_d(dwr,dhd)}  ·  {wl_d(dw,dl2,dhd)}"
        f"  ·  {dst} sigs"
        + (f"  ·  PNL: {'+' if dpnl>=0 else ''}{dpnl:.2f}R" if dhd else "") + "\n"
        f"**🗓 Month** `{mk}`  {wr_d(mwr,mhd)}  ·  {wl_d(mw,ml2,mhd)}"
        f"  ·  {smo} sigs"
        + (f"  ·  PNL: {'+' if mpnl>=0 else ''}{mpnl:.2f}R" if mhd else "")
    )

    return {
        "title": f"⚡  {s.pair_display}   ·   {dl}   ·   {badge}   ·   📊 #{tn}",
        "description": (
            f"{te}  **{tl}**  ·  *{td}*  ·  Hold **{hold}**\n"
            f"{ce}  Market: **{s.market_cond.value}**   {re}  Regime: **{s.regime.value}**\n"
            f"💧 VPIN: **{s.vpin:.3f}**   📈 CVD: **{s.cvd:+.3f}**"
        ),
        "color": _color(sig),
        "fields": [
            {"name":"📌  Entry Zone (Limit)","value":f"```\n{_fp(s.entry_low)}  ──  {_fp(s.entry_high)}\n```","inline":True},
            {"name":"📍  Position","value":f"**{s.direction.value}**","inline":True},
            {"name":"⚖️  Leverage","value":f"**{s.leverage}×**","inline":True},
            {"name":f"{ti}  TP1 ← 50%","value":f"`{_fp(s.tp1)}`\n**{_pct(s.entry_price,s.tp1)}**\nR:R **{r1}**","inline":True},
            {"name":f"{ti}  TP2 ← 30%","value":f"`{_fp(s.tp2)}`\n**{_pct(s.entry_price,s.tp2)}**\nR:R **{r2}**","inline":True},
            {"name":f"{ti}  TP3 ← 20%","value":f"`{_fp(s.tp3)}`\n**{_pct(s.entry_price,s.tp3)}**\nR:R **{r3}**","inline":True},
            {"name":"🛑  Stop Loss (ATR×0.8)","value":f"`{_fp(s.stop_loss)}`\n**{_pct(s.entry_price,s.stop_loss)}**","inline":True},
            {"name":"📊  Best R:R","value":f"**{r1}**","inline":True},
            {"name":"⏱  Expected Hold","value":f"**{hold}**","inline":True},
            {"name":f"🧠  APEX SCORE  ·  {sc.total:.1f}/100  ·  {tier}",
             "value":(f"```\n{_bar(sc.total,14)}\n```\n"
                      f"💧Vol+VPIN `{sc.volume_score:>5.1f}`  🌊Regime `{sc.regime_score:>5.1f}`  🏗Structure `{sc.structure_score:>5.1f}`\n"
                      f"⚡Momentum `{sc.momentum_score:>5.1f}`  🤖AI `{sc.ai_score:>5.1f}`  📊Spread `{sc.spread_score:>5.1f}`  🕐Session `{sc.session_score:>5.1f}`"),
             "inline":False},
            {"name":"━━━━━━━━━  📊 BOT PERFORMANCE  ━━━━━━━━━","value":stats_val,"inline":False},
        ],
        "footer":{"text":f"APEX-EDS v4.0  ·  All Binance USDT-M Perps  ·  R:R≥1:4  ·  Score≥85  ·  {_ts()}"},
        "timestamp":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
    }
