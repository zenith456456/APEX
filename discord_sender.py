import asyncio
import discord
import config
from logger import log


class DiscordSender:
    def __init__(self):
        self._enabled = bool(config.DISCORD_BOT_TOKEN and config.DISCORD_CHANNEL_ID)
        self._client  = None
        self._channel = None
        self._ready   = asyncio.Event()

        if self._enabled:
            intents = discord.Intents.default()
            self._client = discord.Client(intents=intents)

            @self._client.event
            async def on_ready():
                ch = self._client.get_channel(config.DISCORD_CHANNEL_ID)
                if ch:
                    self._channel = ch
                    log.info(f"Discord ready → #{ch.name}")
                    self._ready.set()
                else:
                    log.error(f"Discord channel {config.DISCORD_CHANNEL_ID} not found")
        else:
            log.warning("Discord disabled — set DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID")

    async def start(self):
        if not self._enabled: return
        asyncio.create_task(self._client.start(config.DISCORD_BOT_TOKEN))
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=30)
        except asyncio.TimeoutError:
            log.error("Discord did not connect in 30s — check token")

    async def send(self, payload):
        if not self._enabled or not self._channel:
            log.debug(f"[DC MOCK] {payload.get('embed',{}).get('title','?')}"); return
        try:
            raw   = payload.get("embed", {})
            embed = discord.Embed(
                title=raw.get("title",""), description=raw.get("description",""),
                color=raw.get("color", 0x00C8F0))
            for f in raw.get("fields",[]):
                embed.add_field(name=f["name"], value=f["value"], inline=f.get("inline",False))
            if "footer" in raw: embed.set_footer(text=raw["footer"].get("text",""))
            await self._channel.send(embed=embed)
        except discord.DiscordException as e:
            log.error(f"Discord error: {e}")

    async def close(self):
        if self._client: await self._client.close()
