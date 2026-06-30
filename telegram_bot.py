# ─── telegram_bot.py ───────────────────────────────────────────────────────
# APEX Signal Bot — Telegram Broadcasting Integration
# Uses python-telegram-bot (async). Sends to a channel/group.
# Token whitespace-stripped to avoid common env var bugs.

import logging
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

logger = logging.getLogger("APEX.Telegram")


class TelegramBroadcastBot:
    """Lightweight wrapper — only used for outbound broadcasting."""

    def __init__(self, token: str, channel_id: str):
        self.token      = (token or "").strip()
        self.channel_id = (channel_id or "").strip()
        self.bot: Bot | None = None
        self.enabled    = bool(self.token and self.channel_id)

        if self.enabled:
            self.bot = Bot(token=self.token)
        else:
            logger.warning("Telegram bot disabled — missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID")

    async def send_message(self, text: str):
        if not self.enabled:
            logger.debug("Telegram disabled — skipping send")
            return
        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=text,
                disable_web_page_preview=True,
            )
            logger.info("Telegram message sent ✅")
        except TelegramError as e:
            logger.error(f"Telegram API error: {e}")
        except Exception as e:
            logger.error(f"Telegram send_message unexpected error: {e}")

    async def startup_check(self):
        """Verify bot token + channel access on boot."""
        if not self.enabled:
            return
        try:
            me = await self.bot.get_me()
            logger.info(f"Telegram bot connected as @{me.username}")
            await self.bot.send_message(
                chat_id=self.channel_id,
                text="✅ APEX Signal Bot is now ONLINE and scanning Binance Futures 24/7.",
            )
        except Exception as e:
            logger.error(f"Telegram startup check failed: {e}")
