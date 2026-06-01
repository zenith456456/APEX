"""
config.py — APEX-QUANT centralised configuration

CHANGES:
  • DISCORD_WEBHOOK_URL removed from required env vars — completely optional,
    set it if you want Discord, leave unset to use Telegram only
  • MAX_PAIRS increased: 30 → 80
  • MIN_VOLUME_USDT lowered: 5M → 2M  (more pairs qualify)
  • SIGNAL_COOLDOWN lowered: 5 → 3 min (faster re-scan)
  • Added BATCH_KLINE_WORKERS to seed buffers faster in parallel
"""
import os
from dotenv import load_dotenv

load_dotenv()

def _lst(key: str, default: str) -> list[str]:
    return [v.strip() for v in os.getenv(key, default).split(",") if v.strip()]


class Config:
    # ── Telegram (required) ───────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID:   str = os.getenv("TELEGRAM_CHAT_ID", "")

    # ── Discord (optional — leave blank to disable) ───────────────
    # Do NOT add DISCORD_WEBHOOK_URL to Northflank env vars unless you want Discord.
    # The bot runs fine with Telegram only.
    DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")

    # ── Binance REST failover chain ───────────────────────────────
    BINANCE_REST_URLS: list[str] = [
        "https://api.binance.com",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
    ]

    # ── Binance WebSocket (non-geo-blocked chain) ─────────────────
    BINANCE_WS_URLS: list[str] = [
        "wss://stream.binance.com:9443/stream",
        "wss://stream.binance.com:443/stream",
        "wss://data-stream.binance.com:443/stream",
    ]

    # ── Scan parameters ───────────────────────────────────────────
    SCAN_TIMEFRAMES: list[str] = _lst("SCAN_TIMEFRAMES", "1m,3m,5m")

    # Lowered from 5M → 2M to include more mid-cap coins
    MIN_VOLUME_USDT: float = float(os.getenv("MIN_VOLUME_USDT", "2000000"))

    MIN_CSS_SCORE:   int   = int(os.getenv("MIN_CSS_SCORE", "75"))

    # Increased from 30 → 80 pairs for broader market coverage
    MAX_PAIRS:       int   = int(os.getenv("MAX_PAIRS", "80"))

    # Reduced from 5 → 3 min cooldown for faster signal throughput
    SIGNAL_COOLDOWN: int   = int(os.getenv("SIGNAL_COOLDOWN_MINUTES", "3"))

    # ── Candle buffer ─────────────────────────────────────────────
    CANDLE_LIMIT:        int = 100
    MIN_CANDLES_NEEDED:  int = 25
    # Parallel workers for seeding buffers on startup
    BATCH_KLINE_WORKERS: int = int(os.getenv("BATCH_KLINE_WORKERS", "20"))

    # ── Signal construction ───────────────────────────────────────
    ATR_SL_MULT:  float       = 1.0
    ATR_TP_MULTS: list[float] = [1.0, 2.0, 3.0, 4.5, 6.0]
    MIN_RR:       float       = 1.0

    LEVERAGE_MAP: dict = {"SCALP": 10, "DAY": 5, "SWING": 3}
    TRADE_TYPE_BY_TF: dict = {
        "1m": "SCALP", "3m": "SCALP", "5m": "SCALP",
        "15m": "DAY",  "30m": "DAY",
        "1h": "SWING", "4h": "SWING", "1d": "SWING",
    }
    EXPECTED_TIME: dict = {
        "1m":  "5–15 min",   "3m":  "10–25 min",
        "5m":  "15–35 min",  "15m": "1–4 hrs",
        "30m": "2–6 hrs",    "1h":  "6–24 hrs",
        "4h":  "1–3 days",
    }

    # ── CSS weights ───────────────────────────────────────────────
    CSS_WEIGHTS: dict = {
        "arsi":  0.18, "qmo":   0.16, "vpi":   0.15,
        "vwap":  0.14, "fdi":   0.12, "ema_v": 0.10,
        "mdd":   0.09, "atr_p": 0.06,
    }

    # ── Filter thresholds ─────────────────────────────────────────
    VPI_MIN_ABS: float = float(os.getenv("VPI_MIN_ABS", "20"))
    FDI_MAX:     float = float(os.getenv("FDI_MAX",     "1.60"))
    ATR_PSI_MIN: float = 0.70
    ATR_PSI_MAX: float = 2.20

    # ── Listing poll ──────────────────────────────────────────────
    LISTING_POLL_SECS: int = 300

    # ── Health server ─────────────────────────────────────────────
    PORT: int = int(os.getenv("PORT", "8080"))

    # ── Logging ───────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


cfg = Config()
