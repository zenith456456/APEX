"""
main.py — APEX-QUANT entry point
• Validates config on startup — warns about missing vars but does NOT crash
• Only hard-fails if BOTH Telegram AND Discord are unconfigured
• Starts health server + scanner concurrently
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
    Print full config status. Return True if safe to start, False to abort.
    Does NOT crash if only one platform is missing — warns and continues.
    Only aborts if NO notification platform is configured at all.
    """
    def mask(v: str) -> str:
        if not v:
            return "❌  NOT SET  ← add this in Northflank → Environment"
        if len(v) > 14:
            return f"✅ {v[:6]}…{v[-4:]}"
        return f"✅ {'*' * len(v)}"

    tg_ok  = bool(cfg.TELEGRAM_BOT_TOKEN and cfg.TELEGRAM_CHAT_ID)
    dc_ok  = bool(cfg.DISCORD_WEBHOOK_URL)

    log.info("=" * 52)
    log.info("  APEX-QUANT  ·  CONFIGURATION STATUS")
    log.info("=" * 52)

    # Telegram
    log.info("── TELEGRAM ─────────────────────────────────")
    log.info(f"  TELEGRAM_BOT_TOKEN  : {mask(cfg.TELEGRAM_BOT_TOKEN)}")
    log.info(f"  TELEGRAM_CHAT_ID    : {mask(cfg.TELEGRAM_CHAT_ID)}")
    if not cfg.TELEGRAM_BOT_TOKEN:
        log.warning(
            "  HOW TO FIX → Northflank: Service → Environment → Add Variable\n"
            "    Key  : TELEGRAM_BOT_TOKEN\n"
            "    Value: your bot token from @BotFather on Telegram"
        )
    if not cfg.TELEGRAM_CHAT_ID:
        log.warning(
            "  HOW TO FIX → Northflank: Service → Environment → Add Variable\n"
            "    Key  : TELEGRAM_CHAT_ID\n"
            "    Value: your channel/group ID  (e.g. -1001234567890)\n"
            "    TIP  : Add @userinfobot to your group — it replies with the ID"
        )

    # Discord
    log.info("── DISCORD ──────────────────────────────────")
    log.info(f"  DISCORD_WEBHOOK_URL : {mask(cfg.DISCORD_WEBHOOK_URL)}")
    if not cfg.DISCORD_WEBHOOK_URL:
        log.warning(
            "  HOW TO FIX → Northflank: Service → Environment → Add Variable\n"
            "    Key  : DISCORD_WEBHOOK_URL\n"
            "    Value: your Discord webhook URL\n"
            "    TIP  : Discord → Channel → Edit ⚙ → Integrations → Webhooks → New Webhook → Copy URL"
        )

    # Scan settings
    log.info("── SCAN SETTINGS ────────────────────────────")
    log.info(f"  SCAN_TIMEFRAMES     : {cfg.SCAN_TIMEFRAMES}")
    log.info(f"  MIN_VOLUME_USDT     : ${cfg.MIN_VOLUME_USDT:,.0f}")
    log.info(f"  MIN_CSS_SCORE       : {cfg.MIN_CSS_SCORE}")
    log.info(f"  MAX_PAIRS           : {cfg.MAX_PAIRS}")
    log.info(f"  SIGNAL_COOLDOWN     : {cfg.SIGNAL_COOLDOWN} min")
    log.info(f"  PORT (health)       : {cfg.PORT}")
    log.info(f"  LOG_LEVEL           : {cfg.LOG_LEVEL}")
    log.info("=" * 52)

    # Decide whether to start
    if tg_ok and dc_ok:
        log.info("✅ Both Telegram and Discord configured — full notifications")
        return True
    elif tg_ok and not dc_ok:
        log.warning("⚠️  Discord not configured — signals sent to Telegram only")
        return True
    elif dc_ok and not tg_ok:
        log.warning("⚠️  Telegram not fully configured — signals sent to Discord only")
        return True
    else:
        # Neither platform configured — abort
        log.error(
            "❌ STARTUP ABORTED — no notification platform configured!\n"
            "   You must set AT LEAST ONE of:\n"
            "   • Telegram: TELEGRAM_BOT_TOKEN  +  TELEGRAM_CHAT_ID\n"
            "   • Discord:  DISCORD_WEBHOOK_URL\n\n"
            "   Steps in Northflank:\n"
            "   1. Go to your service page\n"
            "   2. Click 'Environment' tab\n"
            "   3. Click '+ Add Variable'\n"
            "   4. Enter the Key and Value\n"
            "   5. Click Save\n"
            "   6. Go to 'Deployments' tab → click 'Redeploy'\n\n"
            "   Need help finding values? Run:  python check_config.py"
        )
        return False


async def main():
    print(BANNER)
    log.info("Starting APEX-QUANT Signal Bot")

    # Validate — abort only if no platform is configured at all
    ok = check_and_print_config()
    if not ok:
        sys.exit(1)

    scanner = Scanner()

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
