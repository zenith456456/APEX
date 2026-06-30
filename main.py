# ─── main.py ───────────────────────────────────────────────────────────────
# APEX Signal Bot — Entry Point
# Boots Telegram + Discord, starts Binance scanner, runs forever.
# Uses asyncio.wait(FIRST_EXCEPTION) so a crash in any task is visible
# immediately in Northflank logs instead of silently hanging.

import asyncio
import logging
import signal
import sys

from config import CONFIG
from binance_scanner import BinanceScanner
from signal_manager import SignalManager
from broadcaster import Broadcaster
from telegram_bot import TelegramBroadcastBot
from discord_bot import DiscordBroadcastBot

# ── Logging setup ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, CONFIG.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)-18s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("APEX.Main")


async def main():
    logger.info("=" * 60)
    logger.info(f"🚀 Starting {CONFIG.BOT_NAME}")
    logger.info(f"   Max pairs:      {CONFIG.MAX_PAIRS}")
    logger.info(f"   Min volume:     ${CONFIG.MIN_VOLUME_USDT:,.0f}")
    logger.info(f"   MTCS threshold: {CONFIG.MTCS_MIN_SCORE}")
    logger.info(f"   Listing check:  every {CONFIG.LISTING_CHECK_MIN} min")
    logger.info("=" * 60)

    # ── Init broadcast bots ─────────────────────────────────────────────────
    telegram_bot = TelegramBroadcastBot(
        token=CONFIG.TELEGRAM_BOT_TOKEN,
        channel_id=CONFIG.TELEGRAM_CHANNEL_ID,
    )
    discord_bot = DiscordBroadcastBot(
        token=CONFIG.DISCORD_BOT_TOKEN,
        channel_id=CONFIG.DISCORD_CHANNEL_ID,
    )

    try:
        await telegram_bot.startup_check()
    except Exception as e:
        logger.error(f"Telegram startup_check failed (continuing without it): {e}")

    try:
        await discord_bot.start()
    except Exception as e:
        logger.error(f"Discord start() failed (continuing without it): {e}")

    broadcaster = Broadcaster(telegram_bot=telegram_bot, discord_bot=discord_bot)

    # ── Init signal pipeline ────────────────────────────────────────────────
    manager = SignalManager(CONFIG, broadcaster)

    # ── Init scanner ────────────────────────────────────────────────────────
    scanner = BinanceScanner(CONFIG, on_signal_ready=manager.on_signal_ready)

    # ── Run everything concurrently; surface crashes immediately ───────────
    tasks = [
        asyncio.create_task(scanner.start(),            name="scanner"),
        asyncio.create_task(manager.heartbeat_loop(),    name="heartbeat"),
    ]

    # Graceful shutdown handling
    stop_event = asyncio.Event()

    def _handle_signal():
        logger.info("Shutdown signal received…")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        try:
            loop.add_signal_handler if False else None
            signal.signal(getattr(signal, sig_name), lambda *_: _handle_signal())
        except (ValueError, AttributeError):
            pass  # Windows / restricted environments

    stop_task = asyncio.create_task(stop_event.wait(), name="stop_wait")
    all_tasks = tasks + [stop_task]

    done, pending = await asyncio.wait(all_tasks, return_when=asyncio.FIRST_EXCEPTION)

    # If a real task crashed (not the stop_event), re-raise so Northflank
    # restarts the container and the failure is visible in logs.
    for t in done:
        if t is stop_task:
            continue
        exc = t.exception()
        if exc:
            logger.error(f"Task '{t.get_name()}' crashed: {exc}", exc_info=exc)
            for p in pending:
                p.cancel()
            await scanner.stop()
            raise exc

    logger.info("Shutting down cleanly…")
    for p in pending:
        p.cancel()
    await scanner.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=e)
        sys.exit(1)
