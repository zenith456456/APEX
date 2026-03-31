"""
DISCORD BOT — APEX SIGNAL DELIVERY
Slash commands: /status /stats /signals /winrates /help

MESSAGE QUEUE: All sends go through an internal async queue with a
1-second gap between messages. This prevents Discord 429 rate-limit
errors even if multiple signals fire close together.
"""
import asyncio
import logging
import time
from collections import deque

import discord
from discord.ext import commands

from apex_engine import Signal
from formatter import (
    discord_embed, discord_new_listing,
    discord_stats, discord_recent_signals,
)
from config import (
    DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID,
    DISCORD_GUILD_ID, HIST_WR,
)

logger = logging.getLogger("apex.discord")

STYLE_META = {
    "scalp": ("⚡", "SCALP",  "5-15 min"),
    "day":   ("☀",  "DAY",    "30-120 min"),
    "swing": ("🌊", "SWING",  "2-8 hours"),
}

# Minimum seconds between Discord messages (respects rate limits)
SEND_INTERVAL_SEC = 1.2


class ApexDiscordBot(commands.Bot):

    def __init__(self, scanner_stats: dict, start_time: list, signal_history: deque):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self._stats    = scanner_stats
        self._start    = start_time
        self._history  = signal_history
        self._channel: discord.TextChannel | None = None
        self._sig_count = 0

        # Internal send queue — prevents 429 rate limits
        # Each item is either a discord.Embed or a str
        self._send_queue: asyncio.Queue = asyncio.Queue()
        self._sender_task: asyncio.Task | None = None

    # ── Lifecycle ─────────────────────────────────────────────

    async def on_ready(self):
        logger.info(f"Discord: logged in as {self.user}  (id={self.user.id})")
        self._channel = self.get_channel(DISCORD_CHANNEL_ID)
        if not self._channel:
            logger.error(
                f"Discord channel {DISCORD_CHANNEL_ID} not found! "
                "Check DISCORD_CHANNEL_ID environment variable."
            )
        guild = discord.Object(id=DISCORD_GUILD_ID) if DISCORD_GUILD_ID else None
        try:
            synced = await self.tree.sync(guild=guild)
            logger.info(f"Synced {len(synced)} slash command(s)")
        except Exception as exc:
            logger.error(f"Slash sync failed: {exc}")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Binance T3 T4 Signals"
            )
        )
        # Start or RESTART the rate-limit-safe sender loop.
        # on_ready fires after every reconnect — cancel the old task first.
        if self._sender_task and not self._sender_task.done():
            self._sender_task.cancel()
            try:
                await self._sender_task
            except (asyncio.CancelledError, Exception):
                pass
        self._sender_task = asyncio.create_task(self._sender_loop())
        logger.info("Discord send queue started (or restarted after reconnect)")

    async def on_disconnect(self):
        logger.warning("Discord WebSocket disconnected — will auto-reconnect")

    async def on_resumed(self):
        logger.info("Discord WebSocket resumed")
        # Refresh channel reference in case it changed
        self._channel = self.get_channel(DISCORD_CHANNEL_ID)

    # ── Rate-limit-safe sender loop ───────────────────────────

    async def _sender_loop(self):
        """
        Drains the send queue one message at a time with a small
        delay between each send. Eliminates 429 rate limit errors
        even when many messages are queued simultaneously.
        """
        while True:
            try:
                item = await self._send_queue.get()
                if not self._channel:
                    self._send_queue.task_done()
                    continue
                try:
                    if isinstance(item, discord.Embed):
                        await self._channel.send(embed=item)
                    else:
                        await self._channel.send(str(item))
                except discord.Forbidden:
                    logger.error("Discord: missing Send Messages permission")
                except discord.HTTPException as exc:
                    logger.warning(f"Discord send error: {exc}")
                finally:
                    self._send_queue.task_done()
                # Pace between messages — respects Discord rate limits
                await asyncio.sleep(SEND_INTERVAL_SEC)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Discord sender loop error: {exc!r}")
                await asyncio.sleep(1)

    def _enqueue(self, item):
        """Put a message into the rate-limited send queue."""
        try:
            self._send_queue.put_nowait(item)
        except asyncio.QueueFull:
            logger.warning("Discord send queue full — message dropped")

    # ── Signal callbacks ──────────────────────────────────────

    async def on_signal(self, sig: Signal):
        if not self._channel:
            return
        self._sig_count += 1
        ed = discord_embed(sig)
        em = discord.Embed(
            title       = ed["title"],
            description = ed["description"],
            color       = ed["color"],
        )
        for f in ed["fields"]:
            em.add_field(name=f["name"], value=f["value"], inline=f.get("inline", False))
        em.set_footer(text=ed["footer"]["text"])
        self._enqueue(em)

    async def on_new_listing(self, symbol: str):
        if not self._channel:
            return
        self._enqueue(discord_new_listing(symbol))

    # ── Slash commands ────────────────────────────────────────

    async def setup_hook(self):
        guild = discord.Object(id=DISCORD_GUILD_ID) if DISCORD_GUILD_ID else None

        @self.tree.command(name="status", description="Bot and scanner status", guild=guild)
        async def cmd_status(interaction: discord.Interaction):
            uptime = time.time() - self._start[0] if self._start[0] else 0
            h = int(uptime // 3600); m = int((uptime % 3600) // 60); s = int(uptime % 60)
            pairs  = self._stats.get("pairs_live", 0)
            colour = 0x34D399 if pairs > 0 else 0xFBBF24
            em = discord.Embed(title="APEX Bot Status", color=colour)
            em.add_field(name="Status",      value="LIVE" if pairs > 0 else "CONNECTING",    inline=True)
            em.add_field(name="Uptime",      value=f"`{h:02d}:{m:02d}:{s:02d}`",             inline=True)
            em.add_field(name="Pairs",       value=f"`{pairs}` monitored",                   inline=True)
            em.add_field(name="T3 Fired",    value=f"`{self._stats.get('t3_fired',0)}`",      inline=True)
            em.add_field(name="T4 Fired",    value=f"`{self._stats.get('t4_fired',0)}`",      inline=True)
            em.add_field(name="Signals",     value=f"`{self._sig_count}` this session",       inline=True)
            em.add_field(name="Reconnects",  value=f"`{self._stats.get('ws_reconnects',0)}`", inline=True)
            em.add_field(name="New Listings",value=f"`{self._stats.get('new_listings_seen',0)}`", inline=True)
            em.set_footer(text="APEX SYSTEM™")
            await interaction.response.send_message(embed=em, ephemeral=True)

        @self.tree.command(name="stats", description="Session statistics", guild=guild)
        async def cmd_stats(interaction: discord.Interaction):
            uptime = time.time() - self._start[0] if self._start[0] else 0
            await interaction.response.send_message(
                discord_stats(self._stats, uptime), ephemeral=True)

        @self.tree.command(name="signals", description="Last 10 signals fired", guild=guild)
        async def cmd_signals(interaction: discord.Interaction):
            await interaction.response.send_message(
                discord_recent_signals(self._history), ephemeral=False)

        @self.tree.command(name="winrates", description="Historical win rate table", guild=guild)
        async def cmd_winrates(interaction: discord.Interaction):
            em = discord.Embed(
                title="APEX Historical Win Rates",
                description="Based on APEX backtest 2020-2024",
                color=0xFBBF24,
            )
            for tier in ["T3", "T4"]:
                label = "T3 STRONG (>=10%)" if tier == "T3" else "T4 MEGA (>=20%)"
                rows  = []
                for style, (icon, lbl, hold) in STYLE_META.items():
                    wp = HIST_WR[tier][style]["pump"]
                    wd = HIST_WR[tier][style]["dump"]
                    rows.append(f"{icon} **{lbl}**  Pump {wp}%  Dump {wd}%  Hold {hold}")
                em.add_field(name=label, value="\n".join(rows), inline=False)
            em.set_footer(text="Historical reference only. Not financial advice.")
            await interaction.response.send_message(embed=em)

        @self.tree.command(name="help", description="APEX bot guide", guild=guild)
        async def cmd_help(interaction: discord.Interaction):
            em = discord.Embed(
                title="APEX SYSTEM™ Bot Guide",
                description="Binance Futures T3/T4 signal bot with 5-layer AI",
                color=0x00FFD1,
            )
            em.add_field(name="Tiers",
                value="T3 STRONG >=10%  |  8-25/day\nT4 MEGA >=20%  |  2-8/day",
                inline=False)
            em.add_field(name="Each Signal",
                value="Pair  Entry  Position  Leverage\nTP1/2/3  SL  Style  R:R  Time\n+ APEX 5-layer score",
                inline=True)
            em.add_field(name="Commands",
                value="`/status` `/stats` `/signals` `/winrates` `/help`",
                inline=False)
            em.set_footer(text="Not financial advice  ·  Always use stop loss")
            await interaction.response.send_message(embed=em, ephemeral=True)

    # ── Runner ────────────────────────────────────────────────

    async def run_bot(self):
        logger.info("Starting Discord bot...")
        async with self:
            await self.start(DISCORD_BOT_TOKEN)
