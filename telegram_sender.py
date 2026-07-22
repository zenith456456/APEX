import asyncio
from telegram import Bot
from telegram.error import TelegramError
import config
from logger import log


class TelegramSender:
    def __init__(self):
        self._enabled = bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHANNEL_ID)
        self._bot     = Bot(token=config.TELEGRAM_BOT_TOKEN) if self._enabled else None
        if self._enabled:
            log.info(f"Telegram ready → {config.TELEGRAM_CHANNEL_ID}")
        else:
            log.warning("Telegram disabled — set TELEGRAM_BOT_TOKEN + TELEGRAM_CHANNEL_ID")

    async def send(self, text):
        if not self._enabled:
            log.debug(f"[TG MOCK] {text[:80]}…"); return
        try:
            for chunk in [text[i:i+4096] for i in range(0,len(text),4096)]:
                await self._bot.send_message(
                    chat_id=config.TELEGRAM_CHANNEL_ID,
                    text=chunk, parse_mode=None,
                    disable_web_page_preview=True)
                await asyncio.sleep(0.1)
        except TelegramError as e:
            log.error(f"Telegram error: {e}")
