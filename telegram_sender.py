"""
telegram_sender.py — Sends signal alerts to a Telegram channel.
Uses python-telegram-bot v21 in pure async mode.
Sends plain text (parse_mode=None) to avoid MarkdownV2 escaping issues.
"""
import asyncio

from telegram import Bot
from telegram.error import TelegramError

from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
from src.logger import log


class TelegramSender:
    def __init__(self):
        self._enabled = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID)
        self._bot     = Bot(token=TELEGRAM_BOT_TOKEN) if self._enabled else None

        if self._enabled:
            log.info(f"Telegram ready — channel {TELEGRAM_CHANNEL_ID}")
        else:
            log.warning(
                "Telegram disabled — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID"
            )

    async def send(self, text: str):
        if not self._enabled:
            log.debug(f"[TG MOCK] {text[:100]}…")
            return
        try:
            # Telegram max message length is 4096 chars
            for chunk in [text[i:i + 4096] for i in range(0, len(text), 4096)]:
                await self._bot.send_message(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    text=chunk,
                    parse_mode=None,              # plain text — no escaping needed
                    disable_web_page_preview=True,
                )
                await asyncio.sleep(0.1)
        except TelegramError as e:
            log.error(f"Telegram send error: {e}")
