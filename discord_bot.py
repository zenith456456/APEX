# ─── discord_bot.py ────────────────────────────────────────────────────────
# APEX Signal Bot — Discord Broadcasting Integration
# Uses discord.py (async). Runs the gateway client in the background and
# exposes a simple send_message() used by the broadcaster.
#
# Discord integration is FULLY OPTIONAL and NEVER FATAL:
#   - Missing/empty token or channel id  → silently disabled
#   - Invalid token (LoginFailure)       → disabled, bot continues without Discord
#   - Connect timeout                    → disabled, bot continues without Discord
# The bot must keep running on Telegram-only (or scan-only) even if Discord
# is broken, since Discord is a "nice to have" broadcast channel, not core.

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
    """Wraps a discord.Client to send messages to one channel. Never raises."""

    def __init__(self, token: str, channel_id: str):
        self.token      = (token or "").strip()
        self.channel_id = (channel_id or "").strip()
        self.client     = None
        self.channel    = None
        self._ready_event = asyncio.Event()
        self._login_failed = False

        # Basic sanity check: a real Discord bot token always contains
        # two dots (header.payload.signature). Catches pasted-wrong-value
        # mistakes (Client Secret / Public Key / empty placeholder) before
        # ever calling Discord's API.
        token_looks_valid = self.token.count(".") >= 2

        self.enabled = bool(
            self.token and self.channel_id and DISCORD_AVAILABLE and token_looks_valid
        )

        if self.token and self.channel_id and not token_looks_valid:
            logger.warning(
                "DISCORD_BOT_TOKEN does not look like a valid Discord token "
                "(expected format 'xxxx.yyyy.zzzz') — Discord disabled. "
                "Double-check you copied the BOT token (Developer Portal → Bot → "
                "Reset Token), not the Client Secret or Public Key."
            )

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
            if not self.token or not self.channel_id:
                logger.info("Discord not configured — running without Discord broadcasting")

    async def start(self):
        """
        Run the Discord client as a background task. Call once at startup.
        NEVER raises — any failure just leaves Discord disabled and logs why.
        """
        if not self.enabled:
            return

        async def _runner():
            try:
                await self.client.start(self.token)
            except discord.errors.LoginFailure:
                logger.error(
                    "Discord LOGIN FAILED — token was rejected by Discord (401 Unauthorized). "
                    "Generate a fresh token in the Developer Portal (Bot → Reset Token) and "
                    "update DISCORD_BOT_TOKEN, or leave it blank to disable Discord. "
                    "Discord broadcasting is now disabled; the bot will continue running."
                )
                self._login_failed = True
                self.enabled = False
            except Exception as e:
                logger.error(f"Discord client crashed: {e} — disabling Discord broadcasting")
                self._login_failed = True
                self.enabled = False
            finally:
                self._ready_event.set()

        asyncio.create_task(_runner())

        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=20)
        except asyncio.TimeoutError:
            logger.error(
                "Discord did not become ready within 20s (network issue or invalid "
                "credentials) — disabling Discord broadcasting. Bot will continue running."
            )
            self.enabled = False

        if self._login_failed:
            self.enabled = False

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
