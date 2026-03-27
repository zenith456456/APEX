"""
TELEGRAM BOT — APEX SIGNAL DELIVERY
Commands: /start /stop /stats /status /signals /winrates /help
"""
import asyncio
import logging
import time
from collections import deque

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode
from telegram.error import TelegramError, Forbidden, ChatMigrated

from apex_engine import Signal
from formatter import (
    telegram_signal, telegram_new_listing, telegram_stats,
    telegram_winrates, telegram_recent_signals, telegram_help,
)
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID

logger = logging.getLogger("apex.telegram")


class TelegramBot:

    def __init__(self, scanner_stats: dict, start_time: list, signal_history: deque):
        self.app             = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.bot: Bot        = self.app.bot
        self._stats          = scanner_stats
        self._start          = start_time
        self._history        = signal_history
        self._active         = True
        self._sub_chats: set = set()
        self._sig_count      = 0
        self._dead_chats: set = set()
        self._setup_handlers()

    def _setup_handlers(self):
        for cmd, fn in [
            ("start",    self._cmd_start),
            ("stop",     self._cmd_stop),
            ("stats",    self._cmd_stats),
            ("status",   self._cmd_status),
            ("signals",  self._cmd_signals),
            ("winrates", self._cmd_winrates),
            ("help",     self._cmd_help),
        ]:
            self.app.add_handler(CommandHandler(cmd, fn))

    async def _cmd_start(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        self._sub_chats.add(update.effective_chat.id)
        self._active = True
        msg = (
            "APEX Bot activated!\n\n"
            "You will receive T3 STRONG and T4 MEGA signals.\n\n"
            "Each signal includes:\n"
            "1 Pair  2 Entry zone (limit)  3 Position\n"
            "4 Leverage  5 TP1/TP2/TP3  6 Stop loss\n"
            "7 Trade type  8 R:R  9 Expected time\n"
            "Plus full APEX 5-layer AI score\n\n"
            "/help for all commands.\n"
            "Not financial advice. Always use stop loss."
        )
        await update.message.reply_text(msg)

    async def _cmd_stop(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        self._sub_chats.discard(update.effective_chat.id)
        await update.message.reply_text(
            "Signals paused. Channel alerts continue.\nSend /start to resume."
        )

    async def _cmd_stats(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        uptime = time.time() - self._start[0] if self._start[0] else 0
        await update.message.reply_html(telegram_stats(self._stats, uptime))

    async def _cmd_status(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        uptime = time.time() - self._start[0] if self._start[0] else 0
        h = int(uptime // 3600)
        m = int((uptime % 3600) // 60)
        s = int(uptime % 60)
        pairs  = self._stats.get("pairs_live", 0)
        status = "LIVE scanning" if pairs > 0 else "CONNECTING..."
        await update.message.reply_html(
            f"<b>APEX Bot Status</b>\n\n"
            f"<code>Status     :  {status}</code>\n"
            f"<code>Uptime     :  {h:02d}:{m:02d}:{s:02d}</code>\n"
            f"<code>Pairs      :  {pairs} monitored</code>\n"
            f"<code>T3 fired   :  {self._stats.get('t3_fired', 0)}</code>\n"
            f"<code>T4 fired   :  {self._stats.get('t4_fired', 0)}</code>\n"
            f"<code>Signals    :  {self._sig_count} this session</code>\n"
            f"<code>New list.  :  {self._stats.get('new_listings_seen', 0)}</code>\n"
            f"<code>Reconnects :  {self._stats.get('ws_reconnects', 0)}</code>"
        )

    async def _cmd_signals(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(telegram_recent_signals(self._history))

    async def _cmd_winrates(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(telegram_winrates())

    async def _cmd_help(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(telegram_help())

    async def on_signal(self, sig: Signal):
        if not self._active:
            return
        self._sig_count += 1
        await self._broadcast(telegram_signal(sig))

    async def on_new_listing(self, symbol: str):
        await self._broadcast(telegram_new_listing(symbol))

    async def _broadcast(self, text: str):
        targets = set()
        if TELEGRAM_CHANNEL_ID:
            targets.add(str(TELEGRAM_CHANNEL_ID))
        targets.update(
            str(c) for c in self._sub_chats if c not in self._dead_chats
        )
        for chat_id in list(targets):
            try:
                await self.bot.send_message(
                    chat_id    = chat_id,
                    text       = text,
                    parse_mode = ParseMode.HTML,
                    disable_web_page_preview = True,
                )
            except Forbidden:
                logger.warning(f"Bot blocked by {chat_id}")
                self._dead_chats.add(chat_id)
            except ChatMigrated as e:
                logger.warning(f"Chat migrated {chat_id} -> {e.new_chat_id}")
            except TelegramError as e:
                logger.error(f"TG send failed [{chat_id}]: {e}")

    async def run(self):
        logger.info("Starting Telegram bot (long polling)...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(
            drop_pending_updates = True,
            allowed_updates      = ["message"],
        )
        logger.info("Telegram bot ready and polling")
        while True:
            await asyncio.sleep(60)

    async def shutdown(self):
        try:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
        except Exception:
            pass
