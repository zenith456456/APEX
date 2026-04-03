"""
╔══════════════════════════════════════════════════════════════╗
║            APEX SYSTEM™  —  MASTER CONFIGURATION            ║
╠══════════════════════════════════════════════════════════════╣
║  All secrets are read from ENVIRONMENT VARIABLES.           ║
║                                                             ║
║  Northflank : Project → Service → Environment → Add var    ║
║  Render     : Dashboard → Service → Environment            ║
║  Local      : export TELEGRAM_BOT_TOKEN="…"  in terminal   ║
║                                                             ║
║  NEVER hard-code tokens here — this file is on GitHub.     ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import logging

log = logging.getLogger("apex.config")

# ─────────────────────────────────────────────────────────────
#  SECRETS  — loaded from environment at runtime
# ─────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN",  "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")
TELEGRAM_ADMIN_IDS: list[int] = []   # optional: [123456789]

DISCORD_BOT_TOKEN  = os.environ.get("DISCORD_BOT_TOKEN",  "")
DISCORD_CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID", "0"))
DISCORD_GUILD_ID   = int(os.environ.get("DISCORD_GUILD_ID",   "0"))

# ─────────────────────────────────────────────────────────────
#  BINANCE — Futures (USDT-M Perpetuals)
# ─────────────────────────────────────────────────────────────
BINANCE_WS_URL    = "wss://fstream.binance.com/ws/!miniTicker@arr"
# REST base removed — exchange info now comes from WebSocket stream
# (Binance REST APIs return HTTP 451 on some hosting regions)

# ─────────────────────────────────────────────────────────────
#  SCAN SETTINGS
# ─────────────────────────────────────────────────────────────
VOLUME_MIN_USD       = 500_000   # Min 24H USD volume to track
HISTORY_TICKS        = 30        # Rolling ticks per symbol for AI scoring
EXCHANGE_REFRESH_MIN = 60        # Re-fetch active pair list every N minutes
SIGNAL_COOLDOWN_MIN  = 5         # Same coin+tier silent for N min after firing
SIGNAL_HISTORY_MAX   = 50        # Recent signals in memory (for /signals cmd)

# ─────────────────────────────────────────────────────────────
#  TIER THRESHOLDS
# ─────────────────────────────────────────────────────────────
TIERS: dict[str, dict] = {
    "T3": {
        "min_pct":   10.0,
        "max_pct":   20.0,
        "apex_gate": 35,
        "label":     "STRONG",
        "icon":      "🔥",
        "daily_est": "8–25 signals/day",
    },
    "T4": {
        "min_pct":   20.0,
        "max_pct":   9999.0,
        "apex_gate": 42,
        "label":     "MEGA",
        "icon":      "⭐",
        "daily_est": "2–8 signals/day",
    },
}

# ─────────────────────────────────────────────────────────────
#  TRADE PRESETS  (base_leverage, sl_pct, rr_target) per tier × style
# ─────────────────────────────────────────────────────────────
TRADE_PRESETS: dict[tuple, tuple] = {
    ("T3", "scalp"):  (20,  2.0,  1.5),
    ("T3", "day"):    (10,  3.0,  2.5),
    ("T3", "swing"):  ( 5,  4.5,  3.5),
    ("T4", "scalp"):  (10,  3.0,  2.0),
    ("T4", "day"):    ( 7,  4.0,  3.0),
    ("T4", "swing"):  ( 5,  6.0,  4.0),
}

# ─────────────────────────────────────────────────────────────
#  HISTORICAL WIN RATES  (APEX backtest across 10 coins)
# ─────────────────────────────────────────────────────────────
HIST_WR: dict[str, dict] = {
    # Conservative estimates for v4 engine (2-gate, 3-component).
    # Higher volume + larger move = higher quality signals.
    "T3": {
        "scalp": {"pump": 68,  "dump": 64},
        "day":   {"pump": 75,  "dump": 71},
        "swing": {"pump": 82,  "dump": 78},
    },
    "T4": {
        "scalp": {"pump": 74,  "dump": 70},
        "day":   {"pump": 81,  "dump": 77},
        "swing": {"pump": 88,  "dump": 84},
    },
}

# ─────────────────────────────────────────────────────────────
#  DIRECTION FILTERS
# ─────────────────────────────────────────────────────────────
ENABLE_PUMPS = True   # LONG signals (price rises)
ENABLE_DUMPS = True   # SHORT signals (price falls)

# ─────────────────────────────────────────────────────────────
#  CONNECTION
# ─────────────────────────────────────────────────────────────
RECONNECT_DELAY_SEC = 5
MAX_RECONNECT_TRIES = 999_999

# ─────────────────────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FILE  = os.environ.get("LOG_FILE",  "")   # empty = stdout only (best for containers)

# ─────────────────────────────────────────────────────────────
#  HEALTH CHECK  (tiny HTTP server — Northflank / Render / Docker)
# ─────────────────────────────────────────────────────────────
HEALTH_CHECK_ENABLED = True
HEALTH_CHECK_PORT    = int(os.environ.get("PORT", "8080"))


# ─────────────────────────────────────────────────────────────
#  STARTUP VALIDATION
# ─────────────────────────────────────────────────────────────
def validate() -> bool:
    """
    Confirm at least one bot is fully configured.
    Called once at startup in main.py — exits early if nothing is usable.
    """
    has_tg = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID)
    has_dc = bool(DISCORD_BOT_TOKEN  and DISCORD_CHANNEL_ID and DISCORD_GUILD_ID)

    if not has_tg and not has_dc:
        log.error(
            "\n"
            "  ❌  No bot tokens found!\n"
            "\n"
            "  Add environment variables in your hosting dashboard:\n"
            "\n"
            "    TELEGRAM_BOT_TOKEN   =  your BotFather token\n"
            "    TELEGRAM_CHANNEL_ID  =  @channel  or  -100xxxxxxx\n"
            "\n"
            "    DISCORD_BOT_TOKEN    =  your Discord bot token\n"
            "    DISCORD_CHANNEL_ID   =  channel ID (number)\n"
            "    DISCORD_GUILD_ID     =  server  ID (number)\n"
            "\n"
            "  Northflank: Project → Service → Environment → Add variable\n"
            "  Render    : Dashboard → Your service → Environment\n"
            "  Local     : export TELEGRAM_BOT_TOKEN='...' then python main.py\n"
        )
        return False

    if has_tg:
        log.info(f"✓ Telegram   channel={TELEGRAM_CHANNEL_ID}")
    else:
        log.warning("⚠  Telegram not configured — skipped")

    if has_dc:
        log.info(f"✓ Discord    channel={DISCORD_CHANNEL_ID}  guild={DISCORD_GUILD_ID}")
    else:
        log.warning("⚠  Discord not configured — skipped")

    return True
