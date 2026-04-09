#!/usr/bin/env python3
# ============================================================
#  APEX-EDS v4.0  |  main.py
#  Entry point — wires ExchangeMonitor → Scanner → Bots
#  Run:  python main.py
# ============================================================

import asyncio
import logging
import signal
import sys

# ── Logging setup ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("apex_eds.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("Main")

import config
from exchange_monitor import ExchangeMonitor
from scanner          import Scanner
from telegram_bot     import TelegramBot
from discord_bot      import DiscordBot
from apex_engine      import SignalResult


# ── SIGNAL ROUTER ─────────────────────────────────────────────
async def on_signal(sig: SignalResult,
                    tg: TelegramBot,
                    dc: DiscordBot):
    """Called for every qualified signal — routes to all bots."""
    await tg.send_signal(sig)
    await dc.send_signal(sig)


# ── MAIN ──────────────────────────────────────────────────────
async def main():
    logger.info("=" * 60)
    logger.info("  APEX-EDS v4.0 — Starting")
    logger.info("  R:R ≥ 1:4  |  Score ≥ 85  |  VPIN ≥ 0.65")
    logger.info("=" * 60)

    # Validate config
    missing = []
    if not config.TELEGRAM_TOKEN:         missing.append("TELEGRAM_TOKEN")
    if not config.TELEGRAM_CHAT_IDS[0]:  missing.append("TELEGRAM_CHAT_IDS")
    if not config.DISCORD_WEBHOOK_URL and not config.DISCORD_BOT_TOKEN:
        missing.append("DISCORD_WEBHOOK_URL or DISCORD_BOT_TOKEN")
    if missing:
        logger.warning(f"Missing env vars: {missing} — some outputs disabled")

    # Instantiate components
    monitor = ExchangeMonitor()
    tg_bot  = TelegramBot()
    dc_bot  = DiscordBot()
    scanner = Scanner(monitor)

    # Wire signal callback
    scanner.on_signal(lambda sig: on_signal(sig, tg_bot, dc_bot))

    # Start all components
    await tg_bot.start()
    await dc_bot.start()
    await monitor.start()

    # Wait for initial data to accumulate (WebSocket needs a few seconds)
    logger.info("Waiting 30 seconds for initial WS data…")
    await asyncio.sleep(30)

    await scanner.start()

    # Send startup notifications
    await tg_bot.send_startup_message()
    await dc_bot.send_startup_embed()

    logger.info("APEX-EDS running — 24x7 scan active")

    # Keep running until interrupted
    stop_event = asyncio.Event()

    def _handle_shutdown(*args):
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_shutdown)

    await stop_event.wait()

    # Graceful shutdown
    logger.info("Stopping components…")
    await scanner.stop()
    await monitor.stop()
    await tg_bot.stop()
    await dc_bot.stop()
    logger.info("APEX-EDS stopped cleanly")


if __name__ == "__main__":
    asyncio.run(main())
