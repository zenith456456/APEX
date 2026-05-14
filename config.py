import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Signal detection parameters
MIN_RR = 3.0
MAX_RR = 12.0
LEVERAGE = 10

# Binance connectivity
# Use 'us' for Binance US, 'com' for Binance.com (default)
BINANCE_TLD = os.getenv("BINANCE_TLD", "com")
# Optional HTTPS proxy URL, e.g. "http://user:pass@proxy_ip:port"
BINANCE_PROXY = os.getenv("BINANCE_PROXY")