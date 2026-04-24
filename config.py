"""
APEX-EDS v4.0 | config.py
Thresholds recalibrated so signals can actually fire.
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
MIN_VOLUME_USDT       = 10_000_000   # $10M minimum 24h volume (filters illiquid)
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
# These were too strict: VPIN≥0.65 + Score≥85 + 7% regime = zero signals ever.
# Recalibrated to realistic values while staying selective.

# VPIN: over 500 recent trades, imbalance of 0.40 means 70% one-sided volume
# 0.65 was unreachable → lowered to 0.40
VPIN_THRESHOLD  = 0.40

# Composite score: 72 is still top 15% of setups
# 85 required near-perfect on every layer simultaneously → never achieved
MIN_SCORE       = 72

# APEX tier label (star badge) — reserved for elite setups
APEX_SCORE_TIER = 85

# R:R minimum: 3.0 still excellent, 4.0 required 4×ATR move in scalp window
MIN_RR          = 3.0

# ── ATR MULTIPLIERS ───────────────────────────────────────────────────────
ATR_SL_MULT     = 0.8
ATR_TP1_MULT    = 3.0    # TP1 = entry ± 3×ATR  → matches MIN_RR=3.0
ATR_TP2_MULT    = 4.5
ATR_TP3_MULT    = 6.0

# ── LEVERAGE ──────────────────────────────────────────────────────────────
LEVERAGE_DEFAULT = 5
LEVERAGE_APEX    = 10    # Only for score ≥ APEX_SCORE_TIER

# ── REGIME DETECTION ──────────────────────────────────────────────────────
ATR_PERIOD           = 14
REGIME_LOOKBACK      = 20        # 20 bars of 5m = 100 minutes of price history
REGIME_TREND_THRESH  = 0.03      # 3% move = TREND  (was 7% — almost never triggered)
REGIME_VOL_THRESH    = 0.12      # 12% range = VOLATILE

# ── SCORING WEIGHTS (must sum to 1.0) ─────────────────────────────────────
WEIGHT_VOLUME    = 0.25
WEIGHT_AI        = 0.20
WEIGHT_REGIME    = 0.20
WEIGHT_STRUCTURE = 0.15
WEIGHT_MOMENTUM  = 0.10
WEIGHT_SPREAD    = 0.05
WEIGHT_SESSION   = 0.05

# ── WEBSOCKET ─────────────────────────────────────────────────────────────
WS_STREAMS_PER_CONN    = 180
WS_RECONNECT_DELAY     = 5

# ── SCAN LOOP ─────────────────────────────────────────────────────────────
SCAN_INTERVAL_SEC      = 60
MAX_SIGNALS_PER_HOUR   = 30
DISCORD_RATE_LIMIT_SEC = 2.0

# ── KLINE INTERVALS ───────────────────────────────────────────────────────
KLINE_INTERVALS = ["1m", "5m", "15m"]
