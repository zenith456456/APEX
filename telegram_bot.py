# ============================================================
#  APEX-EDS v4.0  |  telegram_bot.py
#  Telegram signal delivery — MarkdownV2, rate-limited queue
# ============================================================

import asyncio
import logging
import re
from typing import Optional

import aiohttp

import config
from apex_engine import SignalResult
from formatter import build_telegram_message

logger = logging.getLogger("TelegramBot")

# Characters that need escaping in MarkdownV2
_MD2_ESCAPE = r'_*[]()~`>#+-=|{}.!'
_ESCAPE_RE   = re.compile(f'([{re.escape(_MD2_ESCAPE)}])')


def escape_md2(text: str) -> str:
    return _ESCAPE_RE.sub(r'\\\1', text)


class TelegramBot:
    """
    Sends signals to one or more Telegram chats.
    Uses asyncio.Queue for rate-limited delivery.
    Max ~30 messages/second (Telegram global limit).
    """

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._base   = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}"
        self._running = False

    async def start(self):
        self._session = aiohttp.ClientSession()
        self._running = True
        asyncio.create_task(self._sender_loop())
        logger.info("TelegramBot started")

    async def stop(self):
        self._running = False
        if self._session:
            await self._session.close()

    async def send_signal(self, sig: SignalResult):
        """Enqueue a signal for delivery."""
        await self._queue.put(sig)

    async def send_text(self, text: str, chat_id: str):
        """Send raw text message (for status/alerts)."""
        await self._queue.put(("text", chat_id, text))

    # ── INTERNAL ──────────────────────────────────────────────

    async def _sender_loop(self):
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                if isinstance(item, SignalResult):
                    await self._send_signal_all(item)
                elif isinstance(item, tuple) and item[0] == "text":
                    _, chat_id, text = item
                    await self._post(chat_id, text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Sender loop error: {e}")

            # Telegram: max 30 msg/s per bot — sleep 100ms between sends
            await asyncio.sleep(0.1)

    async def _send_signal_all(self, sig: SignalResult):
        """Send to all configured chat IDs."""
        msg = build_telegram_message(sig)
        for chat_id in config.TELEGRAM_CHAT_IDS:
            chat_id = chat_id.strip()
            if not chat_id:
                continue
            success = await self._post(chat_id, msg, parse_mode="HTML")
            if success:
                logger.info(f"  → TG sent {sig.symbol} to {chat_id}")
            await asyncio.sleep(0.05)

    async def _post(self, chat_id: str, text: str,
                    parse_mode: str = "HTML") -> bool:
        if not config.TELEGRAM_TOKEN:
            logger.warning("TELEGRAM_TOKEN not set — skipping")
            return False

        url     = f"{self._base}/sendMessage"
        payload = {
            "chat_id":    chat_id,
            "text":       text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            async with self._session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status == 200:
                    return True
                body = await r.text()
                logger.warning(f"TG error {r.status}: {body[:200]}")
                # If MarkdownV2 parse fails, retry as plain text
                if r.status == 400 and "can't parse" in body.lower():
                    payload["parse_mode"] = None
                    payload.pop("parse_mode", None)
                    async with self._session.post(url, json=payload) as r2:
                        return r2.status == 200
                return False
        except Exception as e:
            logger.error(f"TG post exception: {e}")
            return False

    async def send_startup_message(self):
        """Send bot-online notification to all chats."""
        import time
        text = (
            "⚡ <b>APEX-EDS v4.0 ONLINE</b>\n\n"
            "🔍 Scanning 312 Binance USDT-M pairs\n"
            "⚙️ R:R ≥ 1:4  |  Score ≥ 85  |  VPIN ≥ 0.65\n"
            "📊 3 Timeframes  |  7-Layer Bayesian Engine\n"
            f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
        )
        for chat_id in config.TELEGRAM_CHAT_IDS:
            chat_id = chat_id.strip()
            if chat_id:
                await self._post(chat_id, text, parse_mode="HTML")
