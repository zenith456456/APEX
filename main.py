#!/usr/bin/env python3
"""APEX-EDS v4.0 | main.py — Entry point."""
import asyncio, logging, signal, sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("Main")

import config
from exchange_monitor import ExchangeMonitor
from scanner import Scanner
from telegram_sender import TelegramSender
from discord_sender import DiscordSender
from models import SignalResult


async def main():
    logger.info("="*58)
    logger.info("  APEX-EDS v4.0 — Starting")
    logger.info("  R:R >= 1:4  |  Score >= 85  |  VPIN >= 0.65")
    logger.info("  Scanning all Binance USDT-M Perpetual Futures")
    logger.info("="*58)

    missing=[]
    if not config.TELEGRAM_TOKEN:    missing.append("TELEGRAM_TOKEN")
    if not config.TELEGRAM_CHAT_IDS: missing.append("TELEGRAM_CHAT_IDS")
    if not config.DISCORD_WEBHOOK_URL and not config.DISCORD_BOT_TOKEN:
        missing.append("DISCORD_WEBHOOK_URL or DISCORD_BOT_TOKEN")
    if missing: logger.warning(f"Missing env vars: {missing}")

    monitor=ExchangeMonitor(); tg=TelegramSender(); dc=DiscordSender(); scanner=Scanner(monitor)

    async def on_signal(sig: SignalResult, stats: dict):
        await tg.send_signal(sig, stats)
        await dc.send_signal(sig, stats)

    scanner.on_signal(on_signal)

    await tg.start(); await dc.start(); await monitor.start()
    logger.info("Waiting 35s for WebSocket data...")
    await asyncio.sleep(35)
    await scanner.start()
    await tg.startup_message(); await dc.startup_embed()
    logger.info("APEX-EDS running — 24x7 scan active ✓")

    stop_event=asyncio.Event()
    loop=asyncio.get_running_loop()
    for sig_name in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(sig_name, stop_event.set)
        except NotImplementedError: pass

    await stop_event.wait()
    logger.info("Shutting down...")
    await scanner.stop(); await monitor.stop(); await tg.stop(); await dc.stop()
    logger.info("Stopped cleanly.")

if __name__=="__main__":
    asyncio.run(main())
