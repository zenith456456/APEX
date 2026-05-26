"""
notifier.py — Async Telegram + Discord sender
Provides detailed diagnostics when credentials are missing.
"""
import asyncio
import aiohttp
from typing import Optional
from logger_setup import get_logger
from config import cfg

log = get_logger("notify")

_session: Optional[aiohttp.ClientSession] = None


async def _sess() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15))
    return _session


# ── Telegram ──────────────────────────────────────────────────────

async def send_telegram(text: str, retries: int = 3) -> bool:
    if not cfg.TELEGRAM_BOT_TOKEN:
        log.error(
            "TELEGRAM_BOT_TOKEN is not set.\n"
            "  → Go to Northflank dashboard → Your service → Environment\n"
            "  → Add variable:  TELEGRAM_BOT_TOKEN = <your bot token>\n"
            "  → Get token from @BotFather on Telegram (/newbot)"
        )
        return False
    if not cfg.TELEGRAM_CHAT_ID:
        log.error(
            "TELEGRAM_CHAT_ID is not set.\n"
            "  → Go to Northflank dashboard → Your service → Environment\n"
            "  → Add variable:  TELEGRAM_CHAT_ID = <your chat id>\n"
            "  → To find your chat ID: add @userinfobot to your group/channel"
        )
        return False

    url  = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id":    cfg.TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": "HTML",
    }
    sess = await _sess()
    for attempt in range(retries):
        try:
            async with sess.post(url, json=data) as r:
                body = await r.text()
                if r.status == 200:
                    log.info("Telegram ✓ message sent")
                    return True
                elif r.status == 401:
                    log.error(
                        f"Telegram 401 Unauthorized — bot token is wrong.\n"
                        f"  Token used: {cfg.TELEGRAM_BOT_TOKEN[:10]}…\n"
                        f"  → Check TELEGRAM_BOT_TOKEN in Northflank Environment"
                    )
                    return False
                elif r.status == 400:
                    log.error(
                        f"Telegram 400 Bad Request: {body[:200]}\n"
                        f"  Chat ID used: {cfg.TELEGRAM_CHAT_ID}\n"
                        f"  → Ensure the bot is added to your channel/group as admin\n"
                        f"  → For channels use format: @yourchannel or -100XXXXXXXXXX"
                    )
                    return False
                elif r.status == 429:
                    log.warning("Telegram rate limited — waiting 10s")
                    await asyncio.sleep(10)
                else:
                    log.warning(f"Telegram HTTP {r.status}: {body[:120]}")
        except Exception as exc:
            log.warning(f"Telegram attempt {attempt+1}/{retries}: {exc}")
            await asyncio.sleep(2 ** attempt)
    return False


# ── Discord ───────────────────────────────────────────────────────

async def send_discord(payload: dict, retries: int = 3) -> bool:
    if not cfg.DISCORD_WEBHOOK_URL:
        log.error(
            "DISCORD_WEBHOOK_URL is not set.\n"
            "  → Go to Northflank dashboard → Your service → Environment\n"
            "  → Add variable:  DISCORD_WEBHOOK_URL = <your webhook url>\n"
            "  → Get it from: Discord → Channel → Edit → Integrations → Webhooks"
        )
        return False

    if not cfg.DISCORD_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/"):
        log.error(
            f"DISCORD_WEBHOOK_URL looks wrong: {cfg.DISCORD_WEBHOOK_URL[:40]}…\n"
            f"  → Must start with: https://discord.com/api/webhooks/\n"
            f"  → Check for extra spaces or line breaks in Northflank Environment"
        )
        return False

    sess = await _sess()
    for attempt in range(retries):
        try:
            async with sess.post(cfg.DISCORD_WEBHOOK_URL, json=payload) as r:
                if r.status in (200, 204):
                    log.info("Discord ✓ message sent")
                    return True
                body = await r.text()
                if r.status == 401:
                    log.error(
                        f"Discord 401 Unauthorized — webhook URL is invalid or deleted.\n"
                        f"  URL: {cfg.DISCORD_WEBHOOK_URL[:60]}…\n"
                        f"  → Re-create the webhook in Discord and update the env var"
                    )
                    return False
                elif r.status == 404:
                    log.error(
                        f"Discord 404 Not Found — webhook was deleted.\n"
                        f"  → Re-create webhook in Discord → Integrations → Webhooks"
                    )
                    return False
                elif r.status == 429:
                    log.warning("Discord rate limited — waiting 10s")
                    await asyncio.sleep(10)
                else:
                    log.warning(f"Discord HTTP {r.status}: {body[:120]}")
        except Exception as exc:
            log.warning(f"Discord attempt {attempt+1}/{retries}: {exc}")
            await asyncio.sleep(2 ** attempt)
    return False


# ── Broadcast ─────────────────────────────────────────────────────

async def broadcast(tg_text: str, dc_payload: dict):
    await asyncio.gather(
        send_telegram(tg_text),
        send_discord(dc_payload),
        return_exceptions=True,
    )


async def close():
    global _session
    if _session and not _session.closed:
        await _session.close()
