"""
DISCORD BOT — APEX SIGNAL DELIVERY
Slash commands: /status /stats /signals /winrates /help
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
    "day":   ("D",  "DAY",    "30-120 min"),
    "swing": ("W",  "SWING",  "2-8 hours"),
}


class ApexDiscordBot(commands.Bot):

    def __init__(self, scanner_stats: dict, start_time: list, signal_history: deque):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self._stats    = scanner_stats
        self._start    = start_time
        self._history  = signal_history
        self._channel: discord.TextChannel | None = None
        self._sig_count = 0

    async def on_ready(self):
        logger.info(f"Discord: logged in as {self.user}  (id={self.user.id})")
        self._channel = self.get_channel(DISCORD_CHANNEL_ID)
        if not self._channel:
            logger.error(f"Discord channel {DISCORD_CHANNEL_ID} not found!")
        guild = discord.Object(id=DISCORD_GUILD_ID) if DISCORD_GUILD_ID else None
        try:
            synced = await self.tree.sync(guild=guild)
            logger.info(f"Synced {len(synced)} slash command(s)")
        except Exception as e:
            logger.error(f"Slash sync failed: {e}")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Binance T3 T4 Signals"
            )
        )

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
        try:
            await self._channel.send(embed=em)
        except discord.HTTPException as e:
            logger.error(f"Discord send error: {e}")

    async def on_new_listing(self, symbol: str):
        if not self._channel:
            return
        try:
            await self._channel.send(discord_new_listing(symbol))
        except discord.HTTPException as e:
            logger.error(f"Discord new listing error: {e}")

    async def setup_hook(self):
        guild = discord.Object(id=DISCORD_GUILD_ID) if DISCORD_GUILD_ID else None

        @self.tree.command(name="status", description="Bot and scanner status", guild=guild)
        async def cmd_status(interaction: discord.Interaction):
            uptime = time.time() - self._start[0] if self._start[0] else 0
            h = int(uptime // 3600)
            m = int((uptime % 3600) // 60)
            s = int(uptime % 60)
            pairs  = self._stats.get("pairs_live", 0)
            colour = 0x34D399 if pairs > 0 else 0xFBBF24
            em = discord.Embed(title="APEX Bot Status", color=colour)
            em.add_field(name="Status",    value="LIVE" if pairs > 0 else "CONNECTING", inline=True)
            em.add_field(name="Uptime",    value=f"`{h:02d}:{m:02d}:{s:02d}`",          inline=True)
            em.add_field(name="Pairs",     value=f"`{pairs}` monitored",                inline=True)
            em.add_field(name="T3 Fired",  value=f"`{self._stats.get('t3_fired',0)}`",  inline=True)
            em.add_field(name="T4 Fired",  value=f"`{self._stats.get('t4_fired',0)}`",  inline=True)
            em.add_field(name="Signals",   value=f"`{self._sig_count}` session",        inline=True)
            em.add_field(name="New List.", value=f"`{self._stats.get('new_listings_seen',0)}`", inline=True)
            em.add_field(name="Reconnects",value=f"`{self._stats.get('ws_reconnects',0)}`",    inline=True)
            await interaction.response.send_message(embed=em, ephemeral=True)

        @self.tree.command(name="stats", description="Session statistics", guild=guild)
        async def cmd_stats(interaction: discord.Interaction):
            uptime = time.time() - self._start[0] if self._start[0] else 0
            await interaction.response.send_message(
                discord_stats(self._stats, uptime), ephemeral=True
            )

        @self.tree.command(name="signals", description="Last 10 signals", guild=guild)
        async def cmd_signals(interaction: discord.Interaction):
            await interaction.response.send_message(
                discord_recent_signals(self._history), ephemeral=False
            )

        @self.tree.command(name="winrates", description="Historical win rate table", guild=guild)
        async def cmd_winrates(interaction: discord.Interaction):
            em = discord.Embed(
                title       = "APEX Historical Win Rates",
                description = "Based on APEX backtest across 10 coins",
                color       = 0xFBBF24,
            )
            for tier in ["T3", "T4"]:
                label = "T3 STRONG (>=10%)" if tier == "T3" else "T4 MEGA (>=20%)"
                rows  = []
                for style, (icon, lbl, hold) in STYLE_META.items():
                    wp = HIST_WR[tier][style]["pump"]
                    wd = HIST_WR[tier][style]["dump"]
                    rows.append(f"{icon} **{lbl}**  Pump {wp}%  Dump {wd}%  Hold: {hold}")
                em.add_field(name=label, value="\n".join(rows), inline=False)
            em.set_footer(text="Historical reference. Not a guarantee.")
            await interaction.response.send_message(embed=em)

        @self.tree.command(name="help", description="APEX bot guide", guild=guild)
        async def cmd_help(interaction: discord.Interaction):
            em = discord.Embed(
                title       = "APEX SYSTEM — Bot Guide",
                description = "Binance Futures T3/T4 signal bot with 5-layer AI",
                color       = 0x00FFD1,
            )
            em.add_field(name="Tiers",
                value="T3 STRONG >=10%  8-25/day\nT4 MEGA >=20%  2-8/day", inline=False)
            em.add_field(name="Each Signal",
                value="1 Pair  2 Entry  3 Position  4 Leverage\n5 TP1/TP2/TP3  6 SL  7 Type  8 RR  9 Time\nAPEX AI score breakdown", inline=False)
            em.add_field(name="5-Layer AI",
                value="FMT  LVI  WAS  SEC  NRF\nAll 9 gates must pass to fire", inline=False)
            em.add_field(name="Commands",
                value="/status  /stats  /signals  /winrates  /help", inline=False)
            em.set_footer(text="Not financial advice. Always use stop loss.")
            await interaction.response.send_message(embed=em, ephemeral=True)

    async def run_bot(self):
        logger.info("Starting Discord bot...")
        async with self:
            await self.start(DISCORD_BOT_TOKEN)
