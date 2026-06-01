"""
notifier.py — Telegram + Discord sender
Discord is fully optional — if DISCORD_WEBHOOK_URL is not set, it is silently skipped.
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
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    return _session


# ── Telegram ──────────────────────────────────────────────────────

async def send_telegram(text: str, retries: int = 3) -> bool:
    if not cfg.TELEGRAM_BOT_TOKEN or not cfg.TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — skipping")
        return False
    url  = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": cfg.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    sess = await _sess()
    for attempt in range(retries):
        try:
            async with sess.post(url, json=data) as r:
                body = await r.text()
                if r.status == 200:
                    log.info("Telegram ✓")
                    return True
                elif r.status == 401:
                    log.error(
                        f"Telegram 401 — bot token invalid.\n"
                        f"  Token: {cfg.TELEGRAM_BOT_TOKEN[:10]}…\n"
                        f"  Fix:   update TELEGRAM_BOT_TOKEN in Northflank → Environment"
                    )
                    return False
                elif r.status == 400:
                    log.error(
                        f"Telegram 400: {body[:200]}\n"
                        f"  Chat ID: {cfg.TELEGRAM_CHAT_ID}\n"
                        f"  Fix: make sure bot is added as admin to your channel/group"
                    )
                    return False
                elif r.status == 429:
                    await asyncio.sleep(10)
                else:
                    log.warning(f"Telegram {r.status}: {body[:80]}")
        except Exception as exc:
            log.warning(f"Telegram attempt {attempt+1}: {exc}")
            await asyncio.sleep(2 ** attempt)
    return False


# ── Discord (fully optional) ──────────────────────────────────────

async def send_discord(payload: dict, retries: int = 3) -> bool:
    # Silently skip — no warning — Discord is optional
    if not cfg.DISCORD_WEBHOOK_URL:
        return False
    if not cfg.DISCORD_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/"):
        log.warning("DISCORD_WEBHOOK_URL format looks wrong — skipping Discord")
        return False

    sess = await _sess()
    for attempt in range(retries):
        try:
            async with sess.post(cfg.DISCORD_WEBHOOK_URL, json=payload) as r:
                if r.status in (200, 204):
                    log.info("Discord ✓")
                    return True
                body = await r.text()
                if r.status in (401, 404):
                    log.error(f"Discord {r.status} — webhook invalid or deleted: {body[:80]}")
                    return False
                elif r.status == 429:
                    await asyncio.sleep(10)
                else:
                    log.warning(f"Discord {r.status}: {body[:80]}")
        except Exception as exc:
            log.warning(f"Discord attempt {attempt+1}: {exc}")
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
