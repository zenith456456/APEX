# ============================================================
#  APEX-EDS v4.0  |  discord_bot.py
#  Discord signal delivery — rich embeds via webhook or bot
# ============================================================

import asyncio
import logging
import time
from typing import Optional

import aiohttp

import config
from apex_engine import SignalResult
from formatter import build_discord_embed

logger = logging.getLogger("DiscordBot")


class DiscordBot:
    """
    Sends embeds to Discord via:
      1. Webhook (config.DISCORD_WEBHOOK_URL)  — preferred, simpler
      2. Bot token + channel ID                — fallback

    Uses a rate-limited queue (2s between messages by default).
    """

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._queue:   asyncio.Queue = asyncio.Queue()
        self._running = False

    async def start(self):
        self._session = aiohttp.ClientSession()
        self._running = True
        asyncio.create_task(self._sender_loop())
        logger.info("DiscordBot started")

    async def stop(self):
        self._running = False
        if self._session:
            await self._session.close()

    async def send_signal(self, sig: SignalResult):
        await self._queue.put(sig)

    # ── INTERNAL ──────────────────────────────────────────────

    async def _sender_loop(self):
        while self._running:
            try:
                sig = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                await self._dispatch(sig)
            except Exception as e:
                logger.error(f"Discord sender error: {e}")

            # Discord rate limit: 5 req/s per webhook, but be conservative
            await asyncio.sleep(config.DISCORD_RATE_LIMIT)

    async def _dispatch(self, sig: SignalResult):
        embed = build_discord_embed(sig)

        if config.DISCORD_WEBHOOK_URL:
            await self._send_webhook(embed, sig.symbol)
        elif config.DISCORD_BOT_TOKEN and config.DISCORD_CHANNEL_ID:
            await self._send_bot(embed, sig.symbol)
        else:
            logger.warning("Discord not configured (no webhook or bot token)")

    async def _send_webhook(self, embed: dict, symbol: str):
        payload = {
            "username":   "APEX-EDS Signal Bot",
            "avatar_url": "https://i.imgur.com/4M34hi2.png",
            "embeds":     [embed],
        }
        try:
            async with self._session.post(
                config.DISCORD_WEBHOOK_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status in (200, 204):
                    logger.info(f"  → Discord webhook sent {symbol}")
                else:
                    body = await r.text()
                    logger.warning(f"Discord webhook {r.status}: {body[:200]}")
        except Exception as e:
            logger.error(f"Discord webhook exception: {e}")

    async def _send_bot(self, embed: dict, symbol: str):
        """Send via bot token (requires discord.py or raw API call)."""
        if not config.DISCORD_BOT_TOKEN:
            return
        url = f"https://discord.com/api/v10/channels/{config.DISCORD_CHANNEL_ID}/messages"
        headers = {
            "Authorization": f"Bot {config.DISCORD_BOT_TOKEN}",
            "Content-Type":  "application/json",
        }
        payload = {"embeds": [embed]}
        try:
            async with self._session.post(
                url, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status in (200, 201):
                    logger.info(f"  → Discord bot sent {symbol}")
                else:
                    body = await r.text()
                    logger.warning(f"Discord bot {r.status}: {body[:200]}")
        except Exception as e:
            logger.error(f"Discord bot exception: {e}")

    async def send_startup_embed(self):
        """Post an online notification embed."""
        embed = {
            "title":       "⚡ APEX-EDS v4.0 — ONLINE",
            "description": (
                "Scanning **312 Binance USDT-M** perpetual pairs\n"
                "**R:R ≥ 1:4** | Score ≥ 85 | VPIN ≥ 0.65\n"
                "3 Timeframes | 7-Layer Bayesian Engine\n"
                "New listings auto-detected every hour"
            ),
            "color": 0x00F5FF,
            "fields": [
                {"name": "Scalp Types", "value": "⚡ 1M Micro | 🎯 5M Standard | 🔭 15M Extended", "inline": False},
                {"name": "Hard Gates", "value": "VPIN ≥ 0.65 | Score ≥ 85 | R:R ≥ 1:4 | Trend regime only", "inline": False},
            ],
            "footer": {"text": f"Started at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        if config.DISCORD_WEBHOOK_URL:
            payload = {
                "username": "APEX-EDS Signal Bot",
                "embeds":   [embed],
            }
            try:
                async with self._session.post(
                    config.DISCORD_WEBHOOK_URL, json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    logger.info(f"Discord startup embed: {r.status}")
            except Exception as e:
                logger.error(f"Discord startup error: {e}")
