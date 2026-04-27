"""
APEX-EDS v4.0 | config.py
Fully recalibrated based on diagnostic data analysis.
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

# Only trade pairs with strong volume — filters thin coins that gave 38 losses
MIN_VOLUME_USDT   = 50_000_000    # $50M minimum 24h volume
MIN_PRICE_USDT    = 0.000001

# ── TELEGRAM ──────────────────────────────────────────────────────────────
TELEGRAM_TOKEN        = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_IDS_RAW = os.getenv("TELEGRAM_CHAT_IDS", "")
TELEGRAM_CHAT_IDS     = [c.strip() for c in TELEGRAM_CHAT_IDS_RAW.split(",") if c.strip()]

# ── DISCORD ───────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL   = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_BOT_TOKEN     = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID    = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")

# ── SIGNAL GATES ──────────────────────────────────────────────────────────
# VPIN removed as hard gate — it systematically blocks liquid coins and passes
# illiquid ones. CVD is now the primary directional confirmation gate.
#
# CVD gate: require meaningful directional imbalance in recent trades.
# |CVD| > 0.35 means 67.5% of recent dollar volume is one-directional.
CVD_MIN_STRENGTH = 0.35

# Minimum number of trades in deque before scoring (ensures data quality)
MIN_TRADES_IN_DEQUE = 50

# Composite score: 68 is achievable on good setups, still filters noise
MIN_SCORE       = 68
APEX_SCORE_TIER = 82    # badge threshold for ⭐ APEX label

# R:R ≥ 1:3 as requested
MIN_RR          = 3.0

# ── ATR MULTIPLIERS ───────────────────────────────────────────────────────
ATR_SL_MULT     = 0.8
ATR_TP1_MULT    = 3.0    # TP1 = entry ± 3.0×ATR  → R:R 1:3.75 (SL=0.8×)
ATR_TP2_MULT    = 4.5
ATR_TP3_MULT    = 6.0

# ── LEVERAGE ──────────────────────────────────────────────────────────────
LEVERAGE_DEFAULT = 5
LEVERAGE_APEX    = 10

# ── REGIME DETECTION ──────────────────────────────────────────────────────
ATR_PERIOD           = 14
REGIME_LOOKBACK      = 20       # 20 bars of 5m = 100 min lookback
REGIME_TREND_THRESH  = 0.025    # 2.5% directional move = trend
REGIME_VOL_THRESH    = 0.10     # 10% total range = volatile

# ── SCORING WEIGHTS ───────────────────────────────────────────────────────
# Reweighted based on diagnostic data:
# - Regime was only 0.20 weight but scores 24-45 → dragging everything down
# - CVD/momentum are the actual predictive signals
WEIGHT_CVD_MOMENTUM = 0.30   # CVD strength + momentum alignment (most predictive)
WEIGHT_REGIME       = 0.15   # regime trend confirmation
WEIGHT_STRUCTURE    = 0.15   # VPOC distance (price far from control = breakout)
WEIGHT_MOMENTUM     = 0.20   # RSI + MACD (was 0.10, now more weight)
WEIGHT_MULTI_TF     = 0.12   # multi-timeframe trend alignment
WEIGHT_QUALITY      = 0.08   # spread + session combined

# ── SCAN LOOP ─────────────────────────────────────────────────────────────
SCAN_INTERVAL_SEC      = 60
MAX_SIGNALS_PER_HOUR   = 20    # conservative — quality over quantity
DISCORD_RATE_LIMIT_SEC = 2.0

# ── KLINE INTERVALS ───────────────────────────────────────────────────────
KLINE_INTERVALS = ["1m", "5m", "15m"]
