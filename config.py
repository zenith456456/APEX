"""
APEX-EDS v4.0 | config.py
All configuration — edit values here or override via environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── BINANCE ───────────────────────────────────────────────────────────────
BINANCE_BASE_URL        = "https://fapi.binance.com"
BINANCE_WS_BASE         = "wss://fstream.binance.com/stream"
BINANCE_API_KEY         = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET      = os.getenv("BINANCE_API_SECRET", "")

# Refresh full pair list every hour to catch new listings
EXCHANGE_INFO_TTL_SEC   = 3600

# Min 24h USDT volume — filters out illiquid pairs
MIN_VOLUME_USDT         = 3_000_000
MIN_PRICE_USDT          = 0.000001

# ── TELEGRAM ──────────────────────────────────────────────────────────────
TELEGRAM_TOKEN          = os.getenv("TELEGRAM_TOKEN", "")
# Comma-separated chat IDs e.g. "-1001234567890,-1009876543210"
TELEGRAM_CHAT_IDS_RAW   = os.getenv("TELEGRAM_CHAT_IDS", "")
TELEGRAM_CHAT_IDS       = [c.strip() for c in TELEGRAM_CHAT_IDS_RAW.split(",") if c.strip()]

# ── DISCORD ───────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL     = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_BOT_TOKEN       = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID      = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")

# ── SIGNAL FILTERS ────────────────────────────────────────────────────────
MIN_RR                  = 4.0     # Minimum Risk:Reward ratio
MIN_SCORE               = 85      # Minimum composite score (0-100)
APEX_SCORE_TIER         = 90      # Label as ⭐ APEX above this score
VPIN_THRESHOLD          = 0.65    # Informed flow gate

# ── ATR MULTIPLIERS (SL / TP) ─────────────────────────────────────────────
ATR_SL_MULT             = 0.8
ATR_TP1_MULT            = 4.0     # TP1 = entry ± 4×ATR  → 1:4 R:R
ATR_TP2_MULT            = 5.5
ATR_TP3_MULT            = 7.0

# ── LEVERAGE ──────────────────────────────────────────────────────────────
LEVERAGE_DEFAULT        = 5
LEVERAGE_APEX           = 10      # Only for score ≥ APEX_SCORE_TIER
LEVERAGE_CHOP           = 3       # Reduced in choppy markets

# ── REGIME DETECTION ──────────────────────────────────────────────────────
ATR_PERIOD              = 14
REGIME_LOOKBACK         = 20      # candles
REGIME_TREND_THRESH     = 0.07    # 7% price move = TREND
REGIME_VOL_THRESH       = 0.15    # 15% range = VOLATILE

# ── SCORING WEIGHTS (must sum to 1.0) ─────────────────────────────────────
WEIGHT_VOLUME           = 0.25    # CVD + VPIN
WEIGHT_AI               = 0.20    # Multi-TF momentum proxy
WEIGHT_REGIME           = 0.20    # HMM regime confidence
WEIGHT_STRUCTURE        = 0.15    # VPOC distance
WEIGHT_MOMENTUM         = 0.10    # RSI + MACD
WEIGHT_SPREAD           = 0.05    # Bid-ask quality
WEIGHT_SESSION          = 0.05    # Trading session overlap

# ── WEBSOCKET ─────────────────────────────────────────────────────────────
WS_STREAMS_PER_CONN     = 180     # Max streams per combined WS connection
WS_RECONNECT_DELAY      = 5       # Seconds before reconnect

# ── SCAN LOOP ─────────────────────────────────────────────────────────────
SCAN_INTERVAL_SEC       = 60      # Full scan cadence
MAX_SIGNALS_PER_HOUR    = 30      # Hard rate cap
SIGNAL_COOLDOWN_SEC     = 300     # Not used — replaced by SignalMemory
DISCORD_RATE_LIMIT_SEC  = 2.0     # Pause between Discord sends

# ── KLINE INTERVALS ───────────────────────────────────────────────────────
KLINE_INTERVALS         = ["1m", "5m", "15m"]
