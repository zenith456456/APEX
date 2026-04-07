"""
╔══════════════════════════════════════════════════════════════╗
║            APEX SYSTEM™  —  MASTER CONFIGURATION            ║
║                                                              ║
║  Secrets are read from ENVIRONMENT VARIABLES only.          ║
║  NEVER put tokens in this file — it lives on GitHub.       ║
║                                                              ║
║  Northflank : Project → Service → Environment               ║
║  Local      : export TELEGRAM_BOT_TOKEN="…" in terminal    ║
╚══════════════════════════════════════════════════════════════╝
"""
import os
import logging

log = logging.getLogger("apex.config")

# ── Secrets (environment variables) ──────────────────────────
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN",  "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")

DISCORD_BOT_TOKEN  = os.environ.get("DISCORD_BOT_TOKEN",  "")
DISCORD_CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID", "0"))
DISCORD_GUILD_ID   = int(os.environ.get("DISCORD_GUILD_ID",   "0"))

# ── Binance Futures WebSocket ─────────────────────────────────
BINANCE_WS_URL = "wss://fstream.binance.com/ws/!miniTicker@arr"
# NOTE: Binance REST (fapi.binance.com) is geo-blocked (HTTP 451)
# on many cloud hosts. Symbol list is built from the WS stream only.

# ── Scan settings ─────────────────────────────────────────────
VOLUME_MIN_USD     = 500_000   # Min 24H USD volume to consider a pair
HISTORY_TICKS      = 30        # Rolling tick window per symbol
SIGNAL_HISTORY_MAX = 50        # Recent signals kept (for /signals cmd)

# ── Tier definitions ──────────────────────────────────────────
# DO NOT CHANGE apex_gate values — calibrated for v4 engine
TIERS: dict[str, dict] = {
    "T3": {
        "min_pct"  : 10.0,
        "max_pct"  : 20.0,
        "apex_gate": 82,          # APEX ≥ 82  (per image spec)
        "label"    : "STRONG",
        "icon"     : "🔥",
        "daily_est": "5–15 signals/day",
    },
    "T4": {
        "min_pct"  : 20.0,
        "max_pct"  : 9999.0,
        "apex_gate": 78,          # APEX ≥ 78  (per image spec)
        "label"    : "MEGA",
        "icon"     : "⭐",
        "daily_est": "1–6 signals/day",
    },
}

# ── Trade presets  (base_leverage, sl_pct, rr_target) ─────────
# Tiered R:R system — scales with signal quality and move size.
# Minimum R:R = 1:3  |  Maximum R:R = 1:6
#
# Style selection (in apex_engine.py):
#   T3 day    APEX 82–87  → R:R 1:3    (solid move, moderate momentum)
#   T3 swing  APEX 88–94  → R:R 1:4    (strong move, good momentum)
#   T3 power  APEX ≥ 95   → R:R 1:5    (elite move, max momentum)
#   T4 day    APEX 78–84  → R:R 1:3.5  (solid T4, building momentum)
#   T4 swing  APEX 85–94  → R:R 1:4    (strong T4)
#   T4 power  APEX ≥ 95   → R:R 1:5    (elite T4 mega move)
#   T4 ultra  move ≥ 40%  → R:R 1:6    (extreme mega pump/dump)
TRADE_PRESETS: dict[tuple, tuple] = {
    ("T3", "day"):    (10, 3.0, 3.0),   # R:R 1:3
    ("T3", "swing"):  ( 7, 4.0, 4.0),   # R:R 1:4
    ("T3", "power"):  ( 5, 4.5, 5.0),   # R:R 1:5
    ("T4", "day"):    ( 7, 4.0, 3.5),   # R:R 1:3.5
    ("T4", "swing"):  ( 5, 5.0, 4.0),   # R:R 1:4
    ("T4", "power"):  ( 5, 5.5, 5.0),   # R:R 1:5
    ("T4", "ultra"):  ( 3, 6.0, 6.0),   # R:R 1:6  (extreme moves ≥40%)
}

# ── Historical win rates (APEX v4 conservative estimates) ──────
HIST_WR: dict[str, dict] = {
    "T3": {
        "scalp": {"pump": 72, "dump": 68},
        "day":   {"pump": 79, "dump": 75},
        "swing": {"pump": 85, "dump": 81},
    },
    "T4": {
        "scalp": {"pump": 76, "dump": 72},
        "day":   {"pump": 83, "dump": 79},
        "swing": {"pump": 89, "dump": 85},
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

# ── Health check HTTP server ──────────────────────────────────
HEALTH_CHECK_ENABLED = True
HEALTH_CHECK_PORT    = int(os.environ.get("PORT", "8080"))


def validate() -> bool:
    has_tg = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID)
    has_dc = bool(DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID and DISCORD_GUILD_ID)
    if not has_tg and not has_dc:
        log.error(
            "\n  No bot tokens configured!\n"
            "  Set in Northflank: Project → Service → Environment\n"
            "  Required: TELEGRAM_BOT_TOKEN + TELEGRAM_CHANNEL_ID\n"
            "        and: DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID + DISCORD_GUILD_ID\n"
        )
        return False
    if has_tg: log.info(f"Telegram  channel={TELEGRAM_CHANNEL_ID}")
    else:       log.warning("Telegram not configured — skipped")
    if has_dc: log.info(f"Discord   channel={DISCORD_CHANNEL_ID}  guild={DISCORD_GUILD_ID}")
    else:       log.warning("Discord not configured — skipped")
    return True
