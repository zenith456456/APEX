"""APEX-EDS v4.0 | discord_sender.py"""
import asyncio, logging, time
from typing import Optional
import aiohttp
import config
from formatter import build_discord
from models import SignalResult
logger = logging.getLogger("Discord")

class DiscordSender:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._queue = asyncio.Queue(); self._running = False

    async def start(self):
        self._session = aiohttp.ClientSession(); self._running = True
        asyncio.create_task(self._loop()); logger.info("DiscordSender ready")

    async def stop(self):
        self._running = False
        if self._session: await self._session.close()

    async def send_signal(self, sig: SignalResult, stats: dict):
        await self._queue.put((sig, stats))

    async def _loop(self):
        while self._running:
            try: item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError: continue
            try: await self._dispatch(build_discord(item[0], item[1]))
            except Exception as e: logger.error(f"Discord queue: {e}")
            await asyncio.sleep(config.DISCORD_RATE_LIMIT_SEC)

    async def _dispatch(self, embed: dict):
        if config.DISCORD_WEBHOOK_URL: await self._webhook(embed)
        elif config.DISCORD_BOT_TOKEN and config.DISCORD_CHANNEL_ID: await self._bot(embed)
        else: logger.warning("Discord not configured")

    async def _webhook(self, embed: dict):
        try:
            async with self._session.post(config.DISCORD_WEBHOOK_URL,
                    json={"username":"APEX-EDS Bot","embeds":[embed]},
                    timeout=aiohttp.ClientTimeout(total=12)) as r:
                if r.status in (200,204): logger.info("  -> Discord sent")
                elif r.status == 429:
                    await asyncio.sleep(int(r.headers.get("Retry-After","5")))
                    await self._webhook(embed)
                else: logger.warning(f"Discord {r.status}: {(await r.text())[:200]}")
        except Exception as e: logger.error(f"Discord webhook: {e}")

    async def _bot(self, embed: dict):
        try:
            async with self._session.post(
                    f"https://discord.com/api/v10/channels/{config.DISCORD_CHANNEL_ID}/messages",
                    json={"embeds":[embed]},
                    headers={"Authorization":f"Bot {config.DISCORD_BOT_TOKEN}"},
                    timeout=aiohttp.ClientTimeout(total=12)) as r:
                if r.status in (200,201): logger.info("  -> Discord bot sent")
                else: logger.warning(f"Discord bot {r.status}")
        except Exception as e: logger.error(f"Discord bot: {e}")

    async def startup_embed(self):
        embed = {
            "title": "⚡ APEX-EDS v4.0 — ONLINE",
            "description": (
                "Scanning **all Binance USDT-M** perpetual pairs\n"
                "**R:R ≥ 1:4** · Score ≥ 85 · VPIN ≥ 0.65\n"
                "3 Timeframes · 7-Layer Bayesian Engine"
            ),
            "color": 0x00F5FF,
            "fields": [
                {"name":"Scalp Types","value":"⚡ 1M Micro · 🎯 5M Standard · 🔭 15M Extended","inline":False},
                {"name":"Every Signal Shows","value":"📊 Trade # · 🏆 All-Time WR · 📅 Daily WR · 🗓 Monthly WR · ✅W/❌L · 💰 PNL","inline":False},
            ],
            "footer": {"text": f"Started {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        await self._dispatch(embed)
