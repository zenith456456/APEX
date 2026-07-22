"""
main.py — IDS Bot entry point.

All application files (config.py, scanner.py, pipeline.py, etc.) sit in the
SAME directory as this file. Python always adds the directory of the running
script to sys.path[0] automatically — so all imports like `import config`
and `from scanner import BinanceScanner` resolve with zero configuration,
regardless of the working directory or PYTHONPATH.

This flat-file layout is the only structure that is guaranteed to work
on every platform (local, Docker, Northflank, Railway, Render, etc.).
"""
import asyncio
import signal as _signal
import sys

# All imports are from files in the same directory — no package prefix needed
import config                           # noqa: F401 (imported for side effects via logger)
from logger           import log
from state            import StateEngine
from stats            import StatsTracker
from scanner          import BinanceScanner
from formatter        import build_telegram_text, build_discord_embed
from telegram_sender  import TelegramSender
from discord_sender   import DiscordSender


class IDSBot:
    def __init__(self):
        log.info("Initialising IDS Bot…")
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
            f"AI={result['ai_score']:.1f}  R:R=1:{result['rr']:.2f}  reason={reason}"
        )

        # Step 3 — stats
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

    def _shutdown():
        log.info("Shutdown signal received")
        asyncio.create_task(_stop(bot))

    for sig in (_signal.SIGTERM, _signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown)

    await bot.run()


async def _stop(bot: IDSBot):
    await bot.discord.close()
    for t in asyncio.all_tasks():
        if t is not asyncio.current_task():
            t.cancel()
    await asyncio.gather(*asyncio.all_tasks(), return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        log.info("Keyboard interrupt — bye")
        sys.exit(0)
