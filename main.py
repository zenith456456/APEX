"""
main.py — APEX-QUANT entry point
Discord is now fully optional — Telegram only is fine.
"""
import asyncio
import signal
import sys

from config import cfg
from logger_setup import get_logger
from scanner import Scanner
from health import run_health_server
import binance_rest
import notifier

log = get_logger("main")

BANNER = r"""
  ___  ____  ____  _  _       ___  __  __   ___  _  _  ____
 / __)( ___)(  _ \( \/ )___  / __)(  )(  ) / __)( \( )(_  _)
( (__  )__)  )___/ )  ((___)( (_ \ )(__)(  \__ \ )  (   )(
 \___)(____)(_)   (_/\_)     \___/(______) (___/(_)\_) (__)
                                                  v4.0  24/7
"""


def check_and_print_config() -> bool:
    """
    Prints config status.
    Returns True if at least one notification platform is configured.
    Discord is optional — Telegram-only is perfectly valid.
    """
    def mask(v: str) -> str:
        if not v:
            return "❌  NOT SET"
        return f"✅ {v[:6]}…{v[-4:]}" if len(v) > 12 else f"✅ {'*'*len(v)}"

    tg_ok = bool(cfg.TELEGRAM_BOT_TOKEN and cfg.TELEGRAM_CHAT_ID)
    dc_ok = bool(cfg.DISCORD_WEBHOOK_URL)

    log.info("=" * 52)
    log.info("  APEX-QUANT  ·  CONFIGURATION")
    log.info("=" * 52)
    log.info(f"  TELEGRAM_BOT_TOKEN  : {mask(cfg.TELEGRAM_BOT_TOKEN)}")
    log.info(f"  TELEGRAM_CHAT_ID    : {mask(cfg.TELEGRAM_CHAT_ID)}")
    log.info(f"  DISCORD_WEBHOOK_URL : "
             f"{'✅ configured (optional)' if dc_ok else '⬜ not set (optional — OK)'}")
    log.info("─" * 52)
    log.info(f"  SCAN_TIMEFRAMES     : {cfg.SCAN_TIMEFRAMES}")
    log.info(f"  MIN_VOLUME_USDT     : ${cfg.MIN_VOLUME_USDT/1e6:.1f}M")
    log.info(f"  MIN_CSS_SCORE       : {cfg.MIN_CSS_SCORE}")
    log.info(f"  MAX_PAIRS           : {cfg.MAX_PAIRS}")
    log.info(f"  SIGNAL_COOLDOWN     : {cfg.SIGNAL_COOLDOWN} min")
    log.info(f"  PORT                : {cfg.PORT}")
    log.info(f"  LOG_LEVEL           : {cfg.LOG_LEVEL}")
    log.info("=" * 52)

    # Only Telegram is required
    if not cfg.TELEGRAM_BOT_TOKEN:
        log.error(
            "TELEGRAM_BOT_TOKEN is missing!\n"
            "  → Northflank: Service → Environment → Add Variable\n"
            "     Key:   TELEGRAM_BOT_TOKEN\n"
            "     Value: your bot token from @BotFather"
        )
        return False
    if not cfg.TELEGRAM_CHAT_ID:
        log.error(
            "TELEGRAM_CHAT_ID is missing!\n"
            "  → Northflank: Service → Environment → Add Variable\n"
            "     Key:   TELEGRAM_CHAT_ID\n"
            "     Value: your group/channel ID  e.g. -1001234567890\n"
            "     TIP:   Add @userinfobot to your group — it replies with the ID"
        )
        return False

    if tg_ok and dc_ok:
        log.info("✅ Telegram + Discord both configured")
    else:
        log.info("✅ Telegram configured  (Discord optional — not set)")

    return True


async def main():
    print(BANNER)
    log.info("Starting APEX-QUANT Signal Bot")

    if not check_and_print_config():
        sys.exit(1)

    scanner = Scanner()
    loop    = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig, lambda: asyncio.create_task(_shutdown(scanner)))

    await asyncio.gather(
        run_health_server(cfg.PORT, scanner),
        scanner.start(),
    )


async def _shutdown(scanner: Scanner):
    log.info("Shutting down…")
    scanner.ws.stop()
    await binance_rest.close()
    await notifier.close()
    sys.exit(0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted.")
