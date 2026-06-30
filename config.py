# ─── config.py ─────────────────────────────────────────────────────────────
# APEX Signal Bot — Central Configuration
# All values loaded from environment variables (set in Northflank dashboard)

import os
from dataclasses import dataclass, field
from typing import List

@dataclass
class Config:
    # ── Telegram ────────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN:   str  = ""
    TELEGRAM_CHANNEL_ID:  str  = ""   # e.g. -100123456789 or @yourchannel

    # ── Discord ─────────────────────────────────────────────────────────────
    DISCORD_BOT_TOKEN:    str  = ""
    DISCORD_CHANNEL_ID:   str  = ""   # numeric channel id

    # ── Binance ─────────────────────────────────────────────────────────────
    BINANCE_API_KEY:      str  = ""   # optional (public endpoints only needed)
    BINANCE_API_SECRET:   str  = ""   # optional

    # ── Scanner Settings ────────────────────────────────────────────────────
    SCAN_INTERVAL_SEC:    int  = 30       # how often to re-evaluate signals
    LISTING_CHECK_MIN:    int  = 60       # how often to check for new listings
    MAX_PAIRS:            int  = 200      # max perpetual pairs to monitor
    MIN_VOLUME_USDT:      float = 1_000_000.0  # 24h volume filter (1M USDT)
    MIN_OI_USDT:          float = 500_000.0    # open interest filter

    # ── Signal Thresholds ───────────────────────────────────────────────────
    MTCS_MIN_SCORE:       int  = 55      # minimum MTCS to emit signal
    MTCS_HIGH_SCORE:      int  = 72      # high-confidence threshold
    MTCS_MAX_SCORE:       int  = 90      # very-high confidence threshold

    # ── Risk Defaults ───────────────────────────────────────────────────────
    DEFAULT_LEVERAGE:     int  = 10
    BASE_RISK_PCT:        float = 1.2    # % risk per trade for PNL calc

    # ── Timeframes to scan ──────────────────────────────────────────────────
    TIMEFRAMES: List[str] = field(default_factory=lambda: ["1m","3m","5m","15m"])

    # ── Deployment ──────────────────────────────────────────────────────────
    LOG_LEVEL:            str  = "INFO"
    BOT_NAME:             str  = "APEX Signal Bot"

def load_config() -> Config:
    """Load config from environment variables."""
    cfg = Config()
    cfg.TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN",  "").strip()
    cfg.TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    cfg.DISCORD_BOT_TOKEN   = os.getenv("DISCORD_BOT_TOKEN",   "").strip()
    cfg.DISCORD_CHANNEL_ID  = os.getenv("DISCORD_CHANNEL_ID",  "").strip()
    cfg.BINANCE_API_KEY     = os.getenv("BINANCE_API_KEY",      "").strip()
    cfg.BINANCE_API_SECRET  = os.getenv("BINANCE_API_SECRET",   "").strip()
    cfg.SCAN_INTERVAL_SEC   = int(os.getenv("SCAN_INTERVAL_SEC", "30"))
    cfg.LISTING_CHECK_MIN   = int(os.getenv("LISTING_CHECK_MIN", "60"))
    cfg.MAX_PAIRS           = int(os.getenv("MAX_PAIRS",         "200"))
    cfg.MIN_VOLUME_USDT     = float(os.getenv("MIN_VOLUME_USDT", "1000000"))
    cfg.MTCS_MIN_SCORE      = int(os.getenv("MTCS_MIN_SCORE",    "55"))
    cfg.LOG_LEVEL           = os.getenv("LOG_LEVEL",             "INFO")
    cfg.BOT_NAME            = os.getenv("BOT_NAME",              "APEX Signal Bot")
    return cfg

CONFIG = load_config()
