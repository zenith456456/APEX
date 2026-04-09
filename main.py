#!/usr/bin/env python3
"""
APEX-EDS v4.0 | main.py
Entry point — wires all components together and starts the 24x7 engine.
Run: python main.py
"""

import asyncio
import logging
import signal
import sys

# ── Logging ───────────────────────────────────────────────────────────────
# FileHandler removed — Northflank captures stdout automatically
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("Main")

import config
from exchange_monitor import ExchangeMonitor
from scanner           import Scanner
from telegram_sender   import TelegramSender
from discord_sender    import DiscordSender
from models            import SignalResult


async def main():
    logger.info("=" * 58)
    logger.info("  APEX-EDS v4.0 — Starting")
    logger.info("  R:R >= 1:4  |  Score >= 85  |  VPIN >= 0.65")
    logger.info("  Scanning all Binance USDT-M Perpetual Futures")
    logger.info("=" * 58)

    # ── Validate config ───────────────────────────────────────────────────
    missing = []
    if not config.TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if not config.TELEGRAM_CHAT_IDS:
        missing.append("TELEGRAM_CHAT_IDS")
    if not config.DISCORD_WEBHOOK_URL and not config.DISCORD_BOT_TOKEN:
        missing.append("DISCORD_WEBHOOK_URL or DISCORD_BOT_TOKEN")
    if missing:
        logger.warning(f"Missing env vars: {missing} — those outputs will be skipped")

    # ── Instantiate ───────────────────────────────────────────────────────
    monitor = ExchangeMonitor()
    tg      = TelegramSender()
    dc      = DiscordSender()
    scanner = Scanner(monitor)

    # ── Wire signal callback ──────────────────────────────────────────────
    async def on_signal(sig: SignalResult):
        await tg.send_signal(sig)
        await dc.send_signal(sig)

    scanner.on_signal(on_signal)

    # ── Start components ──────────────────────────────────────────────────
    await tg.start()
    await dc.start()
    await monitor.start()

    logger.info("Waiting 35 s for WebSocket data to accumulate...")
    await asyncio.sleep(35)

    await scanner.start()

    # ── Startup notifications ─────────────────────────────────────────────
    await tg.startup_message()
    await dc.startup_embed()

    logger.info("APEX-EDS running — 24x7 scan active")

    # ── Graceful shutdown ─────────────────────────────────────────────────
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig_name, stop_event.set)
        except NotImplementedError:
            pass   # Windows

    await stop_event.wait()

    logger.info("Shutdown signal received — stopping...")
    await scanner.stop()
    await monitor.stop()
    await tg.stop()
    await dc.stop()
    logger.info("APEX-EDS stopped cleanly")


if __name__ == "__main__":
    asyncio.run(main())
