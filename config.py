"""
APEX-EDS v4.0 | config.py
All configuration — edit values here or override via environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── BINANCE — multiple fallback base URLs ─────────────────────────────────
# Tried in order until one succeeds (handles geo-blocks on some IPs)
BINANCE_FUTURES_URLS = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
    "https://fapi4.binance.com",
]

# Active base URL — set at runtime after health check
BINANCE_BASE_URL     = os.getenv("BINANCE_BASE_URL", "https://fapi.binance.com")

# WebSocket fallbacks
BINANCE_WS_URLS = [
    "wss://fstream.binance.com/stream",
    "wss://fstream1.binance.com/stream",
    "wss://fstream2.binance.com/stream",
]
BINANCE_WS_BASE      = os.getenv("BINANCE_WS_BASE", "wss://fstream.binance.com/stream")

BINANCE_API_KEY      = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET   = os.getenv("BINANCE_API_SECRET", "")

# Refresh full pair list every hour to catch new listings
EXCHANGE_INFO_TTL_SEC = 3600

# Min 24h USDT volume — filters out illiquid pairs
MIN_VOLUME_USDT      = 3_000_000
MIN_PRICE_USDT       = 0.000001

# ── TELEGRAM ──────────────────────────────────────────────────────────────
TELEGRAM_TOKEN        = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_IDS_RAW = os.getenv("TELEGRAM_CHAT_IDS", "")
TELEGRAM_CHAT_IDS     = [c.strip() for c in TELEGRAM_CHAT_IDS_RAW.split(",") if c.strip()]

# ── DISCORD ───────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL  = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_BOT_TOKEN    = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID   = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")

# ── SIGNAL FILTERS ────────────────────────────────────────────────────────
MIN_RR               = 4.0
MIN_SCORE            = 85
APEX_SCORE_TIER      = 90
VPIN_THRESHOLD       = 0.65

# ── ATR MULTIPLIERS ───────────────────────────────────────────────────────
ATR_SL_MULT          = 0.8
ATR_TP1_MULT         = 4.0
ATR_TP2_MULT         = 5.5
ATR_TP3_MULT         = 7.0

# ── LEVERAGE ──────────────────────────────────────────────────────────────
LEVERAGE_DEFAULT     = 5
LEVERAGE_APEX        = 10
LEVERAGE_CHOP        = 3

# ── REGIME DETECTION ──────────────────────────────────────────────────────
ATR_PERIOD           = 14
REGIME_LOOKBACK      = 20
REGIME_TREND_THRESH  = 0.07
REGIME_VOL_THRESH    = 0.15

# ── SCORING WEIGHTS ───────────────────────────────────────────────────────
WEIGHT_VOLUME        = 0.25
WEIGHT_AI            = 0.20
WEIGHT_REGIME        = 0.20
WEIGHT_STRUCTURE     = 0.15
WEIGHT_MOMENTUM      = 0.10
WEIGHT_SPREAD        = 0.05
WEIGHT_SESSION       = 0.05

# ── WEBSOCKET ─────────────────────────────────────────────────────────────
WS_STREAMS_PER_CONN  = 180
WS_RECONNECT_DELAY   = 5

# ── SCAN LOOP ─────────────────────────────────────────────────────────────
SCAN_INTERVAL_SEC    = 60
MAX_SIGNALS_PER_HOUR = 30
DISCORD_RATE_LIMIT_SEC = 2.0

# ── KLINE INTERVALS ───────────────────────────────────────────────────────
KLINE_INTERVALS      = ["1m", "5m", "15m"]
