"""
APEX-EDS v4.0 | config.py
"""
import os
from dotenv import load_dotenv
load_dotenv()

# ── BINANCE ───────────────────────────────────────────────────────────────
BINANCE_FUTURES_URLS = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
    "https://fapi4.binance.com",
]
BINANCE_WS_URLS = [
    "wss://fstream.binance.com/stream",
    "wss://fstream1.binance.com/stream",
    "wss://fstream2.binance.com/stream",
]
BINANCE_API_KEY     = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET  = os.getenv("BINANCE_API_SECRET", "")

EXCHANGE_INFO_TTL_SEC = 3600
MIN_VOLUME_USDT       = 50_000_000    # $50M minimum 24h volume
MIN_PRICE_USDT        = 0.000001

# ── TELEGRAM ──────────────────────────────────────────────────────────────
TELEGRAM_TOKEN        = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_IDS_RAW = os.getenv("TELEGRAM_CHAT_IDS", "")
TELEGRAM_CHAT_IDS     = [c.strip() for c in TELEGRAM_CHAT_IDS_RAW.split(",") if c.strip()]

# ── DISCORD ───────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL   = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_BOT_TOKEN     = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID    = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")

# ── SIGNAL GATES ──────────────────────────────────────────────────────────
CVD_MIN_STRENGTH    = 0.35
MIN_TRADES_IN_DEQUE = 50
MIN_SCORE           = 68
APEX_SCORE_TIER     = 82

# ── R:R RANGE 1:1.5 → 1:3 ────────────────────────────────────────────────
# SL = entry ± 1.0 × ATR  (wider SL = tighter but realistic stop)
# TP1 = entry ± 1.5 × ATR → R:R  1 : 1.5   ← close 50% here
# TP2 = entry ± 2.25× ATR → R:R  1 : 2.25  ← close 30% here
# TP3 = entry ± 3.0 × ATR → R:R  1 : 3.0   ← close 20% here
MIN_RR          = 1.5
ATR_SL_MULT     = 1.0
ATR_TP1_MULT    = 1.5
ATR_TP2_MULT    = 2.25
ATR_TP3_MULT    = 3.0

# ── LEVERAGE ──────────────────────────────────────────────────────────────
LEVERAGE_DEFAULT = 5
LEVERAGE_APEX    = 10

# ── REGIME DETECTION ──────────────────────────────────────────────────────
ATR_PERIOD           = 14
REGIME_LOOKBACK      = 20
REGIME_TREND_THRESH  = 0.025
REGIME_VOL_THRESH    = 0.10

# ── SCORING WEIGHTS ───────────────────────────────────────────────────────
WEIGHT_CVD_MOMENTUM = 0.30
WEIGHT_REGIME       = 0.15
WEIGHT_STRUCTURE    = 0.15
WEIGHT_MOMENTUM     = 0.20
WEIGHT_MULTI_TF     = 0.12
WEIGHT_QUALITY      = 0.08

# ── SCAN LOOP ─────────────────────────────────────────────────────────────
SCAN_INTERVAL_SEC      = 60
MAX_SIGNALS_PER_HOUR   = 20
DISCORD_RATE_LIMIT_SEC = 2.0

# ── KLINE INTERVALS ───────────────────────────────────────────────────────
KLINE_INTERVALS = ["1m", "5m", "15m"]

