"""
discord_sender.py — Sends rich embed alerts to a Discord channel.
Uses discord.py v2 in background task mode.
"""
import asyncio

import discord

from src.config import DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID
from src.logger import log


class DiscordSender:
    def __init__(self):
        self._enabled = bool(DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID)
        self._client: discord.Client | None = None
        self._channel: discord.TextChannel | None = None
        self._ready   = asyncio.Event()

        if self._enabled:
            intents = discord.Intents.default()
            self._client = discord.Client(intents=intents)

            @self._client.event
            async def on_ready():
                ch = self._client.get_channel(DISCORD_CHANNEL_ID)
                if ch:
                    self._channel = ch
                    log.info(f"Discord ready — #{ch.name}")
                    self._ready.set()
                else:
                    log.error(
                        f"Discord channel {DISCORD_CHANNEL_ID} not found. "
                        "Check DISCORD_CHANNEL_ID and bot permissions."
                    )
        else:
            log.warning(
                "Discord disabled — set DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID"
            )

    async def start(self):
        """Connect Discord client. Call once at bot startup."""
        if not self._enabled:
            return
        asyncio.create_task(self._client.start(DISCORD_BOT_TOKEN))
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=30)
        except asyncio.TimeoutError:
            log.error("Discord did not connect within 30s — check token")

    async def send(self, payload: dict):
        """
        payload: dict from formatter.build_discord_embed()
        Keys: content (str), embed (dict with title/color/description/fields/footer)
        """
        if not self._enabled or not self._channel:
            title = payload.get("embed", {}).get("title", "?")
            log.debug(f"[DC MOCK] {title}")
            return
        try:
            raw   = payload.get("embed", {})
            embed = discord.Embed(
                title       = raw.get("title", ""),
                description = raw.get("description", ""),
                color       = raw.get("color", 0x00C8F0),
            )
            for field in raw.get("fields", []):
                embed.add_field(
                    name   = field["name"],
                    value  = field["value"],
                    inline = field.get("inline", False),
                )
            if "footer" in raw:
                embed.set_footer(text=raw["footer"].get("text", ""))

            content = payload.get("content") or None
            await self._channel.send(content=content, embed=embed)

        except discord.DiscordException as e:
            log.error(f"Discord send error: {e}")

    async def close(self):
        if self._client:
            await self._client.close()
