import os
from dotenv import load_dotenv

load_dotenv()

def _bool(k, d=False): return os.getenv(k, str(d)).lower() in ("1","true","yes")
def _int(k, d=0):
    try: return int(os.getenv(k, str(d)))
    except: return d
def _float(k, d=0.0):
    try: return float(os.getenv(k, str(d)))
    except: return d

TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")
DISCORD_BOT_TOKEN   = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID  = _int("DISCORD_CHANNEL_ID", 0)

# Non-geo-blocked Binance global endpoints
BINANCE_WS_BASE   = "wss://fstream.binance.com"
BINANCE_REST_BASE = "https://fapi.binance.com"

MIN_VOLUME_USDT       = _float("MIN_VOLUME_USDT", 5_000_000)
AI_SCORE_THRESHOLD    = _float("AI_SCORE_THRESHOLD", 72.0)
MIN_RR                = _float("MIN_RR", 1.0)
CANDLE_LIMIT          = _int("CANDLE_LIMIT", 200)
UNIVERSE_REFRESH_SECS = _int("UNIVERSE_REFRESH_SECS", 600)
LOG_LEVEL             = os.getenv("LOG_LEVEL", "INFO").upper()

LAYER_WEIGHTS = {
    "regime": 8, "priceaction": 14, "volume": 12,
    "liquidity": 16, "orderflow": 12, "oi": 8,
    "funding": 6, "liquidation": 10, "btccorr": 6,
}

TP_WEIGHTS = [0.30, 0.25, 0.20, 0.15, 0.10]
TP_LABELS  = ["TP1", "TP2", "TP3", "TP4", "TP5"]

DATA_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STATE_FILE = os.path.join(DATA_DIR, "signal_state.json")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")
