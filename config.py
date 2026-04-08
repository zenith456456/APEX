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
VOLUME_MIN_USD     = 500_000
HISTORY_TICKS      = 30
SIGNAL_HISTORY_MAX = 50

# ── Tier definitions  —  DO NOT CHANGE apex_gate values ───────
TIERS: dict[str, dict] = {
    "T3": {
        "min_pct"  : 10.0,
        "max_pct"  : 20.0,
        "apex_gate": 82,       # ← FIXED: T3 ≥ 82
        "label"    : "STRONG",
        "icon"     : "🔥",
        "daily_est": "5–15 signals/day",
    },
    "T4": {
        "min_pct"  : 20.0,
        "max_pct"  : 9999.0,
        "apex_gate": 78,       # ← FIXED: T4 ≥ 78
        "label"    : "MEGA",
        "icon"     : "⭐",
        "daily_est": "1–6 signals/day",
    },
}

# ── Trade presets  (base_leverage, sl_pct) ────────────────────
# sl_pct = tight stop-loss distance from PULLBACK entry.
# R:R is dynamic and uncapped — computed in apex_engine.py
# from move magnitude: rr_max = max(6, abs_pct / sl_pct × 0.7)
#
# Styles:
#   T3 day    APEX 82–87  sl=3.0%  R:R 1:3→∞  (moderate T3)
#   T3 swing  APEX 88–94  sl=3.5%  R:R 1:3→∞  (strong T3)
#   T3 power  APEX ≥ 95   sl=4.0%  R:R 1:3→∞  (elite T3)
#   T4 day    APEX 78–84  sl=4.0%  R:R 1:3→∞  (moderate T4)
#   T4 swing  APEX 85–94  sl=4.5%  R:R 1:3→∞  (strong T4)
#   T4 ultra  move ≥ 40%  sl=5.0%  R:R 1:3→∞  (extreme T4)
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
