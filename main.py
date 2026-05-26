"""
main.py — APEX-QUANT entry point
Validates all credentials on startup before launching the scanner.
Fails fast with clear instructions if anything is missing.
"""
import asyncio
import os
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


def validate_config() -> list[str]:
    """
    Check all required env vars are present.
    Returns a list of error strings (empty = all good).
    """
    errors = []

    if not cfg.TELEGRAM_BOT_TOKEN:
        errors.append(
            "TELEGRAM_BOT_TOKEN is not set.\n"
            "  How to fix in Northflank:\n"
            "  1. Go to your service → Environment → Add Variable\n"
            "  2. Key:   TELEGRAM_BOT_TOKEN\n"
            "  3. Value: your bot token from @BotFather\n"
            "  4. Save → Redeploy"
        )
    if not cfg.TELEGRAM_CHAT_ID:
        errors.append(
            "TELEGRAM_CHAT_ID is not set.\n"
            "  How to fix in Northflank:\n"
            "  1. Go to your service → Environment → Add Variable\n"
            "  2. Key:   TELEGRAM_CHAT_ID\n"
            "  3. Value: your channel or group ID (e.g. -1001234567890)\n"
            "  4. To find your ID: add @userinfobot to your group, it replies with the ID\n"
            "  5. Save → Redeploy"
        )
    if not cfg.DISCORD_WEBHOOK_URL:
        errors.append(
            "DISCORD_WEBHOOK_URL is not set.\n"
            "  How to fix in Northflank:\n"
            "  1. Go to your service → Environment → Add Variable\n"
            "  2. Key:   DISCORD_WEBHOOK_URL\n"
            "  3. Value: your Discord webhook URL\n"
            "  4. To create: Discord → Channel → Edit → Integrations → Webhooks → New\n"
            "  5. Save → Redeploy"
        )
    return errors


def print_config_status():
    """Print a clear summary of current configuration."""
    def mask(v: str) -> str:
        if not v:        return "❌ NOT SET"
        if len(v) > 12:  return f"✅ {v[:6]}…{v[-4:]}"
        return            f"✅ {'*' * len(v)}"

    log.info("─" * 48)
    log.info("CONFIGURATION STATUS")
    log.info("─" * 48)
    log.info(f"TELEGRAM_BOT_TOKEN  : {mask(cfg.TELEGRAM_BOT_TOKEN)}")
    log.info(f"TELEGRAM_CHAT_ID    : {mask(cfg.TELEGRAM_CHAT_ID)}")
    log.info(f"DISCORD_WEBHOOK_URL : {mask(cfg.DISCORD_WEBHOOK_URL)}")
    log.info(f"SCAN_TIMEFRAMES     : {cfg.SCAN_TIMEFRAMES}")
    log.info(f"MIN_VOLUME_USDT     : ${cfg.MIN_VOLUME_USDT:,.0f}")
    log.info(f"MIN_CSS_SCORE       : {cfg.MIN_CSS_SCORE}")
    log.info(f"MAX_PAIRS           : {cfg.MAX_PAIRS}")
    log.info(f"SIGNAL_COOLDOWN     : {cfg.SIGNAL_COOLDOWN} min")
    log.info(f"PORT                : {cfg.PORT}")
    log.info(f"LOG_LEVEL           : {cfg.LOG_LEVEL}")
    log.info("─" * 48)


async def main():
    print(BANNER)
    log.info("Starting APEX-QUANT Signal Bot")

    # ── Print config status first so Northflank logs show it ──────
    print_config_status()

    # ── Validate credentials — fail fast with clear instructions ──
    errors = validate_config()
    if errors:
        log.error("=" * 48)
        log.error("STARTUP FAILED — missing required environment variables")
        log.error("=" * 48)
        for i, err in enumerate(errors, 1):
            log.error(f"\n[{i}] {err}")
        log.error("\nSet the variables above in Northflank, then redeploy.")
        log.error("Test locally first:  python check_config.py")
        log.error("=" * 48)
        sys.exit(1)

    log.info("✅ All required env vars present — starting scanner")

    scanner = Scanner()

    # Graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig, lambda: asyncio.create_task(_shutdown(scanner)))

    await asyncio.gather(
        run_health_server(cfg.PORT, scanner.stats.snapshot),
        scanner.start(),
    )


async def _shutdown(scanner: Scanner):
    log.info("Shutdown signal received — cleaning up…")
    scanner.ws.stop()
    await binance_rest.close()
    await notifier.close()
    sys.exit(0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted — bye.")
