"""
main.py — IDS Bot entry point.
All .py files live in the same directory — no packages, no PYTHONPATH needed.
Python adds the script's own directory to sys.path[0] automatically.
"""
import asyncio
import signal as _signal
import sys
import os

# ── Startup diagnostics (printed before any imports that could fail) ──────────
print(f"[STARTUP] Python {sys.version}", flush=True)
print(f"[STARTUP] Working directory: {os.getcwd()}", flush=True)
print(f"[STARTUP] Script location:   {os.path.abspath(__file__)}", flush=True)
print(f"[STARTUP] sys.path[0]:       {sys.path[0]}", flush=True)
print(f"[STARTUP] Files in script dir: {sorted(os.listdir(os.path.dirname(os.path.abspath(__file__))))}", flush=True)

# All imports are sibling files — plain module names, no package prefix
import config
from logger           import log
from state            import StateEngine
from stats            import StatsTracker
from scanner          import BinanceScanner
from formatter        import build_telegram_text, build_discord_embed
from telegram_sender  import TelegramSender
from discord_sender   import DiscordSender


def _check_config():
    """Log a clear summary of which services are enabled."""
    log.info("── Configuration ────────────────────────────────────")
    log.info(f"  Telegram : {'✓ enabled' if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHANNEL_ID else '✗ disabled (no token/channel)'}")
    log.info(f"  Discord  : {'✓ enabled' if config.DISCORD_BOT_TOKEN and config.DISCORD_CHANNEL_ID else '✗ disabled (no token/channel)'}")
    log.info(f"  Min Volume  : ${config.MIN_VOLUME_USDT:,.0f} USDT")
    log.info(f"  AI Threshold: {config.AI_SCORE_THRESHOLD}")
    log.info(f"  Min R:R     : 1:{config.MIN_RR}")
    log.info(f"  Universe refresh every {config.UNIVERSE_REFRESH_SECS}s")
    log.info("─────────────────────────────────────────────────────")

    if not config.TELEGRAM_BOT_TOKEN and not config.DISCORD_BOT_TOKEN:
        log.warning("No alert destinations configured — signals will only appear in logs.")
        log.warning("Set TELEGRAM_BOT_TOKEN or DISCORD_BOT_TOKEN in environment variables.")


class IDSBot:
    def __init__(self):
        log.info("Initialising IDS Bot components…")
        self.state    = StateEngine()
        self.stats    = StatsTracker()
        self.telegram = TelegramSender()
        self.discord  = DiscordSender()
        self.scanner  = BinanceScanner(on_signal_callback=self._on_signal)

    async def run(self):
        log.info("=" * 58)
        log.info("  IDS Bot v2.0 — Ignition Detection System")
        log.info("  Scanning Binance Futures 24/7")
        log.info("=" * 58)
        _check_config()
        await self.discord.start()
        try:
            await self.scanner.run()
        except asyncio.CancelledError:
            log.info("Bot cancelled — shutting down")
        finally:
            await self.discord.close()

    async def _on_signal(self, result: dict):
        sym       = result["symbol"]
        direction = result["side"]
        entry     = result["entry"]
        sl        = result["sl"]
        tps       = result["tps"]

        # Step 2 — deduplication
        decision, reason = self.state.ingest(sym, direction, entry, sl, tps)
        if decision == "SUPPRESS":
            log.debug(f"SUPPRESS {sym} {direction} — active trade, same direction")
            return

        log.info(
            f"SIGNAL ★  {sym} {direction}  "
            f"AI={result['ai_score']:.1f}  "
            f"R:R=1:{result['rr']:.2f}  "
            f"reason={reason}"
        )

        # Step 3 — stats snapshot
        snap      = self.stats.snapshot()
        trade_num = self.stats.next_trade_number()

        # Format + send both platforms simultaneously
        await asyncio.gather(
            self.telegram.send(build_telegram_text(result, trade_num, snap)),
            self.discord.send(build_discord_embed(result, trade_num, snap)),
            return_exceptions=True,
        )


async def _main():
    bot  = IDSBot()
    loop = asyncio.get_running_loop()

    def _handle_shutdown():
        log.info("Shutdown signal received")
        asyncio.create_task(_stop(bot))

    for sig in (_signal.SIGTERM, _signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_shutdown)
        except (NotImplementedError, RuntimeError):
            pass  # Windows doesn't support add_signal_handler

    await bot.run()


async def _stop(bot: IDSBot):
    await bot.discord.close()
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("[SHUTDOWN] Keyboard interrupt — bye", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"[FATAL] Unhandled exception: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
