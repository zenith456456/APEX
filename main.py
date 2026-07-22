"""
main.py — IDS Bot entry point.

Import path: this file lives at /app/main.py inside the container.
All application code is in /app/src/ (a proper Python package with __init__.py).
Python always adds the directory containing the running script to sys.path,
so /app is always in sys.path and `from src.xxx import yyy` always resolves.

NO sys.path manipulation needed — the flat src/ package layout handles it.
"""
import asyncio
import signal as _signal
import sys

from src.config         import LOG_LEVEL
from src.logger         import log
from src.state          import StateEngine
from src.stats          import StatsTracker
from src.scanner        import BinanceScanner
from src.formatter      import build_telegram_text, build_discord_embed
from src.telegram_sender import TelegramSender
from src.discord_sender  import DiscordSender


class IDSBot:
    def __init__(self):
        log.info("Initialising IDS Bot components…")
        self.state    = StateEngine()
        self.stats    = StatsTracker()
        self.telegram = TelegramSender()
        self.discord  = DiscordSender()
        self.scanner  = BinanceScanner(on_signal_callback=self._on_signal)

    async def run(self):
        log.info("=" * 60)
        log.info("  IDS Bot v2.0 — Ignition Detection System")
        log.info("  Scanning Binance Futures 24/7")
        log.info("=" * 60)

        # Connect Discord in background before scanner starts
        await self.discord.start()

        try:
            await self.scanner.run()
        except asyncio.CancelledError:
            log.info("Bot task cancelled — shutting down")
        finally:
            await self.discord.close()

    async def _on_signal(self, pipeline_result: dict):
        """
        Called by BinanceScanner for every raw signal that passes
        AI score + R:R gates in the pipeline.

        Applies deduplication (StateEngine) before dispatching.
        """
        sym       = pipeline_result["symbol"]
        direction = pipeline_result["side"]
        entry     = pipeline_result["entry"]
        sl        = pipeline_result["sl"]
        tps       = pipeline_result["tps"]

        # ── Deduplication (Step 2) ────────────────────────────────────────────
        decision, reason = self.state.ingest(sym, direction, entry, sl, tps)

        if decision == "SUPPRESS":
            log.debug(f"SUPPRESS {sym} {direction} — same direction, trade still active")
            return

        log.info(
            f"SIGNAL ★  {sym} {direction}  "
            f"AI={pipeline_result['ai_score']:.1f}  "
            f"R:R=1:{pipeline_result['rr']:.2f}  "
            f"reason={reason}"
        )

        # ── Stats snapshot (Step 3) ───────────────────────────────────────────
        stats_snap = self.stats.snapshot()
        trade_num  = self.stats.next_trade_number()

        # ── Format & dispatch ─────────────────────────────────────────────────
        tg_text      = build_telegram_text(pipeline_result, trade_num, stats_snap)
        discord_data = build_discord_embed(pipeline_result, trade_num, stats_snap)

        await asyncio.gather(
            self.telegram.send(tg_text),
            self.discord.send(discord_data),
            return_exceptions=True,
        )


# ── Startup ────────────────────────────────────────────────────────────────────

async def _main():
    bot  = IDSBot()
    loop = asyncio.get_running_loop()

    def _handle_shutdown():
        log.info("Shutdown signal received…")
        asyncio.create_task(_shutdown(bot))

    for sig in (_signal.SIGTERM, _signal.SIGINT):
        loop.add_signal_handler(sig, _handle_shutdown)

    await bot.run()


async def _shutdown(bot: IDSBot):
    await bot.discord.close()
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()
    await asyncio.gather(*asyncio.all_tasks(), return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        log.info("Keyboard interrupt — bye")
        sys.exit(0)
