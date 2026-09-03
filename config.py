import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def b(name, default):
    v = os.getenv(name)
    return default if v is None else v.lower() in {"1","true","yes","on"}

def csv(name, default):
    return tuple(x.strip() for x in os.getenv(name, default).split(",") if x.strip())

@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "binance-signal-bot")
    port: int = int(os.getenv("PORT", "8080"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    ws_stream_url: str = os.getenv("BINANCE_WS_URL", "wss://fstream.binance.com/public/stream")
    ws_api_url: str = os.getenv("BINANCE_WS_API_URL", "wss://ws-fapi.binance.com/ws-fapi/v1")
    rest_url: str = os.getenv("BINANCE_REST_URL", "https://fapi.binance.com")
    max_symbols: int = int(os.getenv("MAX_SYMBOLS", "100"))
    ws_symbols_per_connection: int = int(os.getenv("WS_SYMBOLS_PER_CONNECTION", "10"))
    min_24h_quote_volume: float = float(os.getenv("MIN_24H_QUOTE_VOLUME", "5000000"))
    min_mover_24h_pct: float = float(os.getenv("MIN_MOVER_24H_PCT", "2.0"))
    mover_slots: int = int(os.getenv("MOVER_SLOTS", "50"))
    volume_slots: int = int(os.getenv("VOLUME_SLOTS", "75"))
    exchange_info_refresh: int = int(os.getenv("EXCHANGE_INFO_REFRESH_SECONDS", "300"))
    universe_refresh: int = int(os.getenv("UNIVERSE_REFRESH_SECONDS", "60"))
    analysis_interval: int = int(os.getenv("ANALYSIS_INTERVAL_SECONDS", "5"))
    kline_limit: int = int(os.getenv("KLINE_LIMIT", "200"))
    score_threshold: float = float(os.getenv("SCORE_THRESHOLD", "90"))
    min_rr: float = float(os.getenv("MIN_RR", "3"))
    risk_per_trade_pct: float = float(os.getenv("RISK_PER_TRADE_PCT", "1"))
    db_path: str = os.getenv("DB_PATH", "./data/signals.sqlite3")
    news_enabled: bool = b("NEWS_ENABLED", True)
    news_refresh: int = int(os.getenv("NEWS_REFRESH_SECONDS", "60"))
    news_lookback_minutes: int = int(os.getenv("NEWS_LOOKBACK_MINUTES", "30"))
    news_words: tuple[str,...] = csv("NEWS_BLOCK_WORDS", "hack,exploit,halt,delist,delisting,bankrupt,insolvency,lawsuit,sec,investigation")
    rss_urls: tuple[str,...] = csv("NEWS_RSS_URLS", "https://www.coindesk.com/arc/outboundfeeds/rss/,https://cointelegraph.com/rss")
    telegram_enabled: bool = b("TELEGRAM_ENABLED", True)
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    discord_enabled: bool = b("DISCORD_ENABLED", True)
    discord_webhook: str = os.getenv("DISCORD_WEBHOOK_URL", "")

SETTINGS = Settings()
Path(SETTINGS.db_path).parent.mkdir(parents=True, exist_ok=True)
