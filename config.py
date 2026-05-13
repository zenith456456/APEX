import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Signal detection parameters (adjustable)
MIN_RR = 3.0             # Minimum reward:risk
MAX_RR = 12.0            # Maximum reward:risk
LEVERAGE = 10            # Fixed leverage for signals

# Binance Futures WebSocket – unlimited pairs, auto-detect new listings
# (Uses binance-python library for REST + WebSocket)