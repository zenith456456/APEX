"""
APEX-EDS v4.0 | telegram_sender.py
Async Telegram delivery with HTML parse mode and rate-limited queue.
"""

import asyncio
import logging
import time
from typing import Optional

import aiohttp

import config
from formatter import build_telegram, TELEGRAM_PARSE_MODE
from models import SignalResult

logger = logging.getLogger("Telegram")


class TelegramSender:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._queue:   asyncio.Queue = asyncio.Queue()
        self._base     = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}"
        self._running  = False

    async def start(self):
        self._session = aiohttp.ClientSession()
        self._running = True
        asyncio.create_task(self._loop())
        logger.info("TelegramSender ready")

    async def stop(self):
        self._running = False
        if self._session:
            await self._session.close()

    async def send_signal(self, sig: SignalResult):
        await self._queue.put(sig)

    async def send_text(self, text: str):
        """Broadcast plain HTML text to all chats."""
        await self._queue.put(("html", text))

    # ── INTERNAL ──────────────────────────────────────────────────────────

    async def _loop(self):
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                if isinstance(item, SignalResult):
                    await self._broadcast_signal(item)
                elif isinstance(item, tuple) and item[0] == "html":
                    await self._broadcast_html(item[1])
            except Exception as e:
                logger.error(f"Queue error: {e}")
            await asyncio.sleep(0.12)   # ~8 msg/s max

    async def _broadcast_signal(self, sig: SignalResult):
        text = build_telegram(sig)
        for cid in config.TELEGRAM_CHAT_IDS:
            await self._post(cid, text)
            await asyncio.sleep(0.05)

    async def _broadcast_html(self, html: str):
        for cid in config.TELEGRAM_CHAT_IDS:
            await self._post(cid, html)
            await asyncio.sleep(0.05)

    async def _post(self, chat_id: str, text: str) -> bool:
        if not config.TELEGRAM_TOKEN:
            logger.warning("TELEGRAM_TOKEN not set")
            return False
        payload = {
            "chat_id":                  chat_id,
            "text":                     text,
            "parse_mode":               TELEGRAM_PARSE_MODE,
            "disable_web_page_preview": True,
        }
        try:
            async with self._session.post(
                f"{self._base}/sendMessage",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=12),
            ) as r:
                if r.status == 200:
                    return True
                body = await r.text()
                logger.warning(f"TG {r.status}: {body[:200]}")
                # Retry as plain text if HTML parse fails
                if r.status == 400:
                    payload.pop("parse_mode", None)
                    async with self._session.post(
                        f"{self._base}/sendMessage", json=payload
                    ) as r2:
                        return r2.status == 200
                return False
        except Exception as e:
            logger.error(f"TG post: {e}")
            return False

    async def startup_message(self):
        ts  = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        msg = (
            "⚡ <b>APEX-EDS v4.0 — ONLINE</b>\n\n"
            "🔍 Scanning <b>all Binance USDT-M</b> perpetual pairs\n"
            "⚙️ R:R ≥ 1:4  ·  Score ≥ 85  ·  VPIN ≥ 0.65\n"
            "📊 3 Timeframes  ·  7-Layer Bayesian Engine\n"
            "🔄 New listings auto-detected every hour\n"
            "🧠 Smart memory — no duplicate signals\n"
            f"🕐 {ts}"
        )
        await self._broadcast_html(msg)
