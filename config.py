"""
config.py ─ APEX-QUANT centralised configuration

FIX: load_dotenv(override=False) so Northflank-injected environment
     variables are NEVER overwritten by a local .env file.
     In a container, vars come from the platform — dotenv is only
     a local-dev convenience.
"""
import os
from dotenv import load_dotenv

# override=False  →  platform env vars win over .env file
load_dotenv(override=False)


def _lst(key: str, default: str) -> list[str]:
    return [v.strip() for v in os.getenv(key, default).split(",") if v.strip()]


class Config:
    # ── Telegram ──────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_CHAT_ID:   str = os.getenv("TELEGRAM_CHAT_ID",   "").strip()

    # ── Discord ───────────────────────────────────────────────────
    DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

    # ── Binance REST failover chain ────────────────────────────────
    BINANCE_REST_URLS: list[str] = [
        "https://api.binance.com",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
    ]

    # ── Binance WebSocket URLs (port 443 = geo-unblocked fallback) ─
    BINANCE_WS_URLS: list[str] = [
        "wss://stream.binance.com:9443/stream",
        "wss://stream.binance.com:443/stream",
        "wss://data-stream.binance.com:443/stream",
    ]

    # ── Scan parameters ───────────────────────────────────────────
    SCAN_TIMEFRAMES:  list[str] = _lst("SCAN_TIMEFRAMES", "1m,3m,5m")
    MIN_VOLUME_USDT:  float     = float(os.getenv("MIN_VOLUME_USDT",  "5000000"))
    MIN_CSS_SCORE:    int       = int(os.getenv("MIN_CSS_SCORE",       "75"))
    MAX_PAIRS:        int       = int(os.getenv("MAX_PAIRS",           "30"))
    SIGNAL_COOLDOWN:  int       = int(os.getenv("SIGNAL_COOLDOWN_MINUTES", "5"))

    # ── Candle buffer ─────────────────────────────────────────────
    CANDLE_LIMIT:       int = 100
    MIN_CANDLES_NEEDED: int = 25

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
        "1m":  "5–15 min",  "3m":  "10–25 min", "5m":  "15–35 min",
        "15m": "1–4 hrs",   "30m": "2–6 hrs",
        "1h":  "6–24 hrs",  "4h":  "1–3 days",
    }

    # ── CSS indicator weights ─────────────────────────────────────
    CSS_WEIGHTS: dict = {
        "arsi": 0.18, "qmo": 0.16, "vpi": 0.15, "vwap": 0.14,
        "fdi":  0.12, "ema_v": 0.10, "mdd": 0.09, "atr_p": 0.06,
    }

    # ── Hard-filter thresholds ────────────────────────────────────
    VPI_MIN_ABS: float = float(os.getenv("VPI_MIN_ABS", "20"))
    FDI_MAX:     float = float(os.getenv("FDI_MAX",     "1.60"))
    ATR_PSI_MIN: float = 0.70
    ATR_PSI_MAX: float = 2.20

    # ── New-listing polling ───────────────────────────────────────
    LISTING_POLL_SECS: int = 300

    # ── Health-check server ───────────────────────────────────────
    PORT: int = int(os.getenv("PORT", "8080"))

    # ── Logging ───────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


cfg = Config()


# ── Startup validation ────────────────────────────────────────────
def validate_config() -> tuple[bool, list[str]]:
    """
    Check that all required env vars are present and non-empty.
    Returns (ok: bool, list of error/warning strings).
    Call this from main.py before starting the bot.
    """
    issues: list[str] = []
    ok = True

    def _mask(s: str) -> str:
        """Show first 6 chars + *** so you can verify the value without exposing secrets."""
        if not s:
            return "(empty)"
        return s[:6] + "***" + s[-3:] if len(s) > 9 else s[:3] + "***"

    # Required
    if not cfg.TELEGRAM_BOT_TOKEN:
        issues.append("❌ TELEGRAM_BOT_TOKEN is not set")
        ok = False
    else:
        issues.append(f"✅ TELEGRAM_BOT_TOKEN = {_mask(cfg.TELEGRAM_BOT_TOKEN)}")

    if not cfg.TELEGRAM_CHAT_ID:
        issues.append("❌ TELEGRAM_CHAT_ID is not set")
        ok = False
    else:
        issues.append(f"✅ TELEGRAM_CHAT_ID   = {cfg.TELEGRAM_CHAT_ID}")

    if not cfg.DISCORD_WEBHOOK_URL:
        issues.append("❌ DISCORD_WEBHOOK_URL is not set")
        ok = False
    else:
        issues.append(f"✅ DISCORD_WEBHOOK_URL = {_mask(cfg.DISCORD_WEBHOOK_URL)}")

    # Informational
    issues.append(f"ℹ️  MIN_CSS_SCORE       = {cfg.MIN_CSS_SCORE}")
    issues.append(f"ℹ️  SCAN_TIMEFRAMES     = {cfg.SCAN_TIMEFRAMES}")
    issues.append(f"ℹ️  MAX_PAIRS           = {cfg.MAX_PAIRS}")
    issues.append(f"ℹ️  SIGNAL_COOLDOWN     = {cfg.SIGNAL_COOLDOWN} min")
    issues.append(f"ℹ️  MIN_VOLUME_USDT     = ${cfg.MIN_VOLUME_USDT:,.0f}")
    issues.append(f"ℹ️  PORT                = {cfg.PORT}")
    issues.append(f"ℹ️  LOG_LEVEL           = {cfg.LOG_LEVEL}")

    return ok, issues
