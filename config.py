# ============================================================
#  APEX-EDS v4.0  |  config.py
#  All tunable parameters — edit here only, never in logic files
# ============================================================

import os
from dotenv import load_dotenv

load_dotenv()

# ── BINANCE ──────────────────────────────────────────────────
BINANCE_API_KEY     = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET  = os.getenv("BINANCE_API_SECRET", "")
BINANCE_BASE_URL    = "https://fapi.binance.com"           # USDT-M Futures
BINANCE_WS_BASE     = "wss://fstream.binance.com/stream"
EXCHANGE_INFO_TTL   = 3600   # seconds — refresh new listings every hour

# ── TELEGRAM ─────────────────────────────────────────────────
TELEGRAM_TOKEN      = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_IDS   = os.getenv("TELEGRAM_CHAT_IDS", "").split(",")  # comma-separated

# ── DISCORD ──────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_BOT_TOKEN   = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID  = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")

# ── SIGNAL FILTERS ────────────────────────────────────────────
MIN_RR              = 4.0    # Minimum Risk:Reward ratio
MIN_SCORE           = 85     # Minimum APEX score (0-100)
APEX_SCORE_TIER     = 90     # Score for ★ APEX tier label
MIN_VOLUME_USDT     = 5_000_000   # Min 24h volume (USDT) for pair to be scanned
MIN_PRICE_USDT      = 0.00001     # Filter dust coins

# ── SCALP HOLD LIMITS ─────────────────────────────────────────
# Timeframe windows (minutes)
TF_MICRO_MAX_HOLD   = 15     # 1M micro scalp
TF_STD_MAX_HOLD     = 35     # 5M standard scalp
TF_EXT_MAX_HOLD     = 55     # 15M extended scalp

# ── ATR / SL / TP PARAMS ─────────────────────────────────────
ATR_PERIOD          = 14
ATR_SL_MULT         = 0.8    # SL = entry ± ATR * this
ATR_TP1_MULT        = 4.0    # TP1 at 4×ATR (R:R 1:4 minimum)
ATR_TP2_MULT        = 5.5    # TP2 at 5.5×ATR
ATR_TP3_MULT        = 7.0    # TP3 at 7×ATR (max target)

# ── LEVERAGE ─────────────────────────────────────────────────
LEVERAGE_DEFAULT    = 5
LEVERAGE_APEX       = 10     # Used only for APEX ≥90 score signals
LEVERAGE_CHOP       = 3      # Reduced leverage in choppy markets

# ── REGIME DETECTION ─────────────────────────────────────────
REGIME_TREND_THRESH = 0.07   # 7% price change over lookback = TREND
REGIME_VOL_THRESH   = 0.15   # 15% range = VOLATILE
REGIME_LOOKBACK     = 20     # candles for regime detection

# ── VPIN / CVD ───────────────────────────────────────────────
VPIN_BUCKET_SIZE    = 50     # trade volume buckets
VPIN_THRESHOLD      = 0.65   # informed flow threshold
CVD_LOOKBACK        = 20     # bars for CVD divergence

# ── SCORING WEIGHTS ──────────────────────────────────────────
WEIGHT_VOLUME       = 0.25   # CVD / VPIN
WEIGHT_AI_PRED      = 0.20   # momentum proxy
WEIGHT_REGIME       = 0.20   # HMM regime confidence
WEIGHT_STRUCTURE    = 0.15   # S/R proximity
WEIGHT_MOMENTUM     = 0.10   # RSI / MACD
WEIGHT_SPREAD       = 0.05   # bid-ask spread
WEIGHT_TIME         = 0.05   # session quality

# ── WEBSOCKET STREAMS ─────────────────────────────────────────
WS_STREAMS_PER_CONN = 200    # Binance limit: 200 streams per combined WS
WS_RECONNECT_DELAY  = 5      # seconds before reconnect on disconnect
KLINE_INTERVALS     = ["1m", "5m", "15m"]

# ── BOT BEHAVIOUR ────────────────────────────────────────────
SCAN_INTERVAL_SEC   = 60     # full scan loop cadence (seconds)
SIGNAL_COOLDOWN_SEC = 300    # don't re-signal same pair within N seconds
MAX_SIGNALS_PER_HOUR = 25    # rate-limit total signals sent
DISCORD_RATE_LIMIT  = 2.0    # seconds between Discord messages

# ── MARKET CONDITION THRESHOLDS ──────────────────────────────
CONDITION_BULL_SCORE    = 70  # BTC 24h % gain threshold for BULL label
CONDITION_BEAR_SCORE    = -5  # BTC 24h % loss threshold for BEAR label
CONDITION_VOL_SCORE     = 8   # BTC 1h % move threshold for VOLATILE label
