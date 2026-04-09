"""
╔══════════════════════════════════════════════════════════════╗
║            APEX SYSTEM™  —  MASTER CONFIGURATION            ║
║                                                              ║
║  Secrets from ENVIRONMENT VARIABLES only.                   ║
║  NEVER put tokens here — this file is on GitHub.           ║
║                                                              ║
║  Northflank : Project → Service → Environment               ║
╚══════════════════════════════════════════════════════════════╝
"""
import os
import logging

log = logging.getLogger("apex.config")

# ── Secrets ───────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN",  "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")
DISCORD_BOT_TOKEN   = os.environ.get("DISCORD_BOT_TOKEN",   "")
DISCORD_CHANNEL_ID  = int(os.environ.get("DISCORD_CHANNEL_ID", "0"))
DISCORD_GUILD_ID    = int(os.environ.get("DISCORD_GUILD_ID",   "0"))

# ── Binance Futures WebSocket ─────────────────────────────────
BINANCE_WS_URL = "wss://fstream.binance.com/ws/!miniTicker@arr"

# ── Scan settings ─────────────────────────────────────────────
VOLUME_MIN_USD     = 300_000
HISTORY_TICKS      = 30
SIGNAL_HISTORY_MAX = 50

# ── Tier definitions ──────────────────────────────────────────
#
# FIX: Gate math proof (why old gates were broken):
#
#   APEX = move + vol + mom
#
#   T3 worst case (10% move, $300K vol, weak mom):
#     move = 10  (hard floor — formula gives exactly 10 at 10%)
#     vol  =  1  ($300K–$500K bracket)
#     mom  =  5  (default neutral)
#     APEX = 16  →  OLD gate=38 IMPOSSIBLE ✗
#
#   T3 typical case (12% move, $1M vol, normal mom):
#     move = 19
#     vol  =  4
#     mom  =  5
#     APEX = 28  →  OLD gate=38 still fails ✗
#
#   T3 strong case (15% move, $5M vol, trending mom):
#     move = 32
#     vol  =  8
#     mom  =  8
#     APEX = 48  →  OLD gate=38 passes ✓ (but only top 5% of T3)
#
#   NEW gate=22 correctly rejects the weakest signals (10% + low vol)
#   while passing genuine 11%+ moves with any real volume.
#
#   T4 worst case (20% move, $300K vol, weak mom):
#     move = 55  (floor at 20%)
#     vol  =  1
#     mom  =  5
#     APEX = 61  →  OLD gate=62 FAILS by 1 point ✗  (crash victim)
#
#   NEW gate=52 captures all genuine T4 movers.
#
TIERS: dict[str, dict] = {
    "T3": {
        "min_pct"  : 10.0,
        "max_pct"  : 20.0,
        # OLD: 38  — mathematically impossible for 10–13% moves
        # NEW: 22  — passes 11%+ moves with $500K+ vol (rejects pure noise)
        "apex_gate": 22,
        "label"    : "STRONG",
        "icon"     : "🔥",
        "daily_est": "8–20 signals/day",
    },
    "T4": {
        "min_pct"  : 20.0,
        "max_pct"  : 9999.0,
        # OLD: 62  — fails 20% moves with <$1M vol (rejects crash dumps)
        # NEW: 52  — captures all 20%+ moves with >$300K vol
        "apex_gate": 52,
        "label"    : "MEGA",
        "icon"     : "⭐",
        "daily_est": "2–8 signals/day",
    },
}

# ── Trade presets  (base_leverage, sl_pct) ────────────────────
TRADE_PRESETS: dict[tuple, tuple] = {
    ("T3", "day")  : (10, 3.0),
    ("T3", "swing"): ( 7, 3.5),
    ("T3", "power"): ( 5, 4.0),
    ("T4", "day")  : ( 7, 4.0),
    ("T4", "swing"): ( 5, 4.5),
    ("T4", "ultra"): ( 3, 5.0),
}

# ── Historical win rates ───────────────────────────────────────
HIST_WR: dict[str, dict] = {
    "T3": {
        "day":   {"pump": 72, "dump": 68},
        "swing": {"pump": 78, "dump": 74},
        "power": {"pump": 83, "dump": 79},
    },
    "T4": {
        "day":   {"pump": 75, "dump": 71},
        "swing": {"pump": 82, "dump": 78},
        "ultra": {"pump": 86, "dump": 82},
    },
}

# ── Filters ───────────────────────────────────────────────────
ENABLE_PUMPS = True
ENABLE_DUMPS = True

# ── Connection ────────────────────────────────────────────────
RECONNECT_DELAY_SEC = 5
MAX_RECONNECT_TRIES = 999_999

# ── Logging ───────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# ── Health check ──────────────────────────────────────────────
HEALTH_CHECK_ENABLED = True
HEALTH_CHECK_PORT    = int(os.environ.get("PORT", "8080"))


def validate() -> bool:
    has_tg = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID)
    has_dc = bool(DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID and DISCORD_GUILD_ID)
    if not has_tg and not has_dc:
        log.error(
            "\n  No bot tokens configured!\n"
            "  Set in Northflank: Project → Service → Environment\n"
        )
        return False
    if has_tg: log.info(f"Telegram  channel={TELEGRAM_CHANNEL_ID}")
    else:       log.warning("Telegram not configured — skipped")
    if has_dc: log.info(f"Discord   channel={DISCORD_CHANNEL_ID}  guild={DISCORD_GUILD_ID}")
    else:       log.warning("Discord not configured — skipped")
    return True
