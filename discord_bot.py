# ─── discord_bot.py ────────────────────────────────────────────────────────
# APEX Signal Bot — Discord Broadcasting Integration
# Uses discord.py (async). Runs the gateway client in the background and
# exposes a simple send_message() used by the broadcaster.
# Discord integration is OPTIONAL — bot runs fine with Telegram only.

import logging
import asyncio

logger = logging.getLogger("APEX.Discord")

try:
    import discord
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    logger.warning("discord.py not installed — Discord integration disabled")


class DiscordBroadcastBot:
    """Wraps a discord.Client to send messages to one channel."""

    def __init__(self, token: str, channel_id: str):
        self.token      = (token or "").strip()
        self.channel_id = (channel_id or "").strip()
        self.enabled    = bool(self.token and self.channel_id and DISCORD_AVAILABLE)
        self.client     = None
        self.channel    = None
        self._ready_event = asyncio.Event()

        if self.enabled:
            intents = discord.Intents.default()
            self.client = discord.Client(intents=intents)

            @self.client.event
            async def on_ready():
                try:
                    self.channel = self.client.get_channel(int(self.channel_id))
                    if self.channel is None:
                        self.channel = await self.client.fetch_channel(int(self.channel_id))
                    logger.info(f"Discord bot connected as {self.client.user} → #{self.channel}")
                    await self.channel.send("✅ APEX Signal Bot is now ONLINE and scanning Binance Futures 24/7.")
                except Exception as e:
                    logger.error(f"Discord on_ready error: {e}")
                finally:
                    self._ready_event.set()
        else:
            logger.warning("Discord bot disabled — missing token/channel or discord.py not installed")

    async def start(self):
        """Run the Discord client as a background task. Call once at startup."""
        if not self.enabled:
            return
        asyncio.create_task(self.client.start(self.token))
        await asyncio.wait_for(self._ready_event.wait(), timeout=30)

    async def send_message(self, text: str):
        if not self.enabled or self.channel is None:
            logger.debug("Discord disabled or channel not ready — skipping send")
            return
        try:
            # Discord hard limit: 2000 chars per message
            if len(text) > 1900:
                text = text[:1900] + "\n…(truncated)"
            await self.channel.send(text)
            logger.info("Discord message sent ✅")
        except Exception as e:
            logger.error(f"Discord send_message error: {e}")
