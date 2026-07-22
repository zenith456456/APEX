"""
config.py — All settings loaded from environment variables.
Safe defaults so the bot starts even without a .env file (logs only).
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")


def _int(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _float(key: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")

# ── Discord ───────────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN  = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = _int("DISCORD_CHANNEL_ID", 0)

# ── Binance endpoints (non-geo-blocked global edge nodes) ─────────────────────
# fstream.binance.com  → Futures WebSocket stream (works from all Northflank regions)
# fapi.binance.com     → Futures REST API
BINANCE_WS_BASE   = "wss://fstream.binance.com"
BINANCE_REST_BASE = "https://fapi.binance.com"

# ── Scanner ───────────────────────────────────────────────────────────────────
MIN_VOLUME_USDT       = _float("MIN_VOLUME_USDT", 5_000_000)   # 24h quote volume gate
AI_SCORE_THRESHOLD    = _float("AI_SCORE_THRESHOLD", 72.0)      # 0–100
MIN_RR                = _float("MIN_RR", 1.0)                   # hard reject below 1:1
CANDLE_LIMIT          = _int("CANDLE_LIMIT", 200)               # history per symbol
UNIVERSE_REFRESH_SECS = _int("UNIVERSE_REFRESH_SECS", 600)      # 10 min new-listing check
LOG_LEVEL             = os.getenv("LOG_LEVEL", "INFO").upper()

# ── IDS layer weights (must sum to 82; RR applied as multiplier separately) ───
LAYER_WEIGHTS = {
    "regime":      8,
    "priceaction": 14,
    "volume":      12,
    "liquidity":   16,   # highest — smart-money fingerprint
    "orderflow":   12,
    "oi":          8,
    "funding":     6,
    "liquidation": 10,
    "btccorr":     6,
}

# ── TP ladder (front-loaded, must sum to 1.0) ─────────────────────────────────
TP_WEIGHTS = [0.30, 0.25, 0.20, 0.15, 0.10]
TP_LABELS  = ["TP1", "TP2", "TP3", "TP4", "TP5"]

# ── Persistence paths ────────────────────────────────────────────────────────
DATA_DIR    = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
STATE_FILE  = os.path.join(DATA_DIR, "signal_state.json")
STATS_FILE  = os.path.join(DATA_DIR, "stats.json")
