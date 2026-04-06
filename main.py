#!/usr/bin/env python3
"""
APEX SYSTEM™ — Main Entry Point
Orchestrates: WebSocket scanner + Telegram + Discord + Health check + Heartbeat
"""
import asyncio
import logging
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import config

_health_stats: dict = {}

class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (
            f"APEX OK\n"
            f"pairs={_health_stats.get('pairs_live',0)}\n"
            f"t3={_health_stats.get('t3_fired',0)}\n"
            f"t4={_health_stats.get('t4_fired',0)}\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *_): pass

BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║     █████╗ ██████╗ ███████╗██╗  ██╗  SYSTEM™               ║
║    ██╔══██╗██╔══██╗██╔════╝╚██╗██╔╝                         ║
║    ███████║██████╔╝█████╗   ╚███╔╝                          ║
║    ██╔══██║██╔═══╝ ██╔══╝   ██╔██╗                          ║
║    ██║  ██║██║     ███████╗██╔╝ ██╗                         ║
║    ╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝                        ║
║                                                              ║
║  T3 STRONG ≥10% APEX≥82  ·  T4 MEGA ≥20% APEX≥78           ║
║  TP-State + SL-State Signal Management  ·  No Timers        ║
║  Northflank  ·  24/7  ·  Binance Futures WebSocket          ║
╚══════════════════════════════════════════════════════════════╝
"""


def setup_logging():
    level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    fmt   = "%(asctime)s  %(levelname)-8s  %(name)-18s  %(message)s"
    logging.basicConfig(
        level    = level,
        format   = fmt,
        datefmt  = "%Y-%m-%d %H:%M:%S",
        handlers = [logging.StreamHandler(sys.stdout)],
    )
    for noisy in (
        "httpx", "httpcore", "websockets.client", "websockets.connection",
        "discord.gateway", "discord.http", "discord.client",
        "telegram.ext.Updater", "telegram.ext.Application",
        "apscheduler",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


logger = logging.getLogger("apex.main")


async def main():
    setup_logging()
    print(BANNER)

    if not config.validate():
        sys.exit(1)

    from binance_scanner import BinanceScanner
    scanner    = BinanceScanner()
    start_time = [time.time()]
    stats_ref  = scanner.stats
    hist_ref   = scanner.signal_history

    # ── Health check HTTP server ──────────────────────────────
    if config.HEALTH_CHECK_ENABLED:
        global _health_stats
        _health_stats = stats_ref
        server = HTTPServer(("0.0.0.0", config.HEALTH_CHECK_PORT), _Health)
        Thread(target=server.serve_forever, daemon=True).start()
        logger.info(f"Health check on port {config.HEALTH_CHECK_PORT}")

    # ── Telegram ──────────────────────────────────────────────
    tg_bot = None
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHANNEL_ID:
        from telegram_bot import TelegramBot
        tg_bot = TelegramBot(stats_ref, start_time, hist_ref)
        scanner.add_signal_callback(tg_bot.on_signal)
        logger.info("Telegram bot registered")

    # ── Discord ───────────────────────────────────────────────
    dc_bot = None
    if config.DISCORD_BOT_TOKEN and config.DISCORD_CHANNEL_ID and config.DISCORD_GUILD_ID:
        from discord_bot import ApexDiscordBot
        dc_bot = ApexDiscordBot(stats_ref, start_time, hist_ref)
        scanner.add_signal_callback(dc_bot.on_signal)
        logger.info("Discord bot registered")

    # ── Shutdown handler ──────────────────────────────────────
    loop = asyncio.get_event_loop()
    def _shutdown(*_):
        logger.info("Shutdown received...")
        scanner.stop()
        for t in asyncio.all_tasks(loop):
            t.cancel()
    for sig_num in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(sig_num, _shutdown)
        except NotImplementedError: pass

    # ── Tasks ─────────────────────────────────────────────────
    tasks = [asyncio.create_task(scanner.run(), name="scanner")]
    if tg_bot: tasks.append(asyncio.create_task(tg_bot.run(),     name="telegram"))
    if dc_bot: tasks.append(asyncio.create_task(dc_bot.run_bot(), name="discord"))

    # ── Heartbeat logger ──────────────────────────────────────
    async def _heartbeat():
        while True:
            await asyncio.sleep(60)
            s   = scanner.stats
            tot = s["t3_fired"] + s["t4_fired"]
            rej = s["t3_rejected"] + s["t4_rejected"]
            rr  = f"{rej/(tot+rej)*100:.0f}%" if (tot + rej) > 0 else "n/a"
            gr  = scanner.engine.gate_rejects
            top = sorted(gr.items(), key=lambda x: x[1], reverse=True)
            top_str = "  ".join(f"{k}:{v}" for k, v in top if v > 0) or "none"
            logger.info(
                f"HEARTBEAT | pairs={s['pairs_live']} frames={s['frames_total']:,} | "
                f"T3:{s['t3_fired']}✓/{s['t3_rejected']}✗  "
                f"T4:{s['t4_fired']}✓/{s['t4_rejected']}✗ | "
                f"reject={rr}  "
                f"tp_re={s.get('all_tp_reentries',0)}  "
                f"sl_re={s.get('sl_reentries',0)}  "
                f"rev={s.get('reversals',0)}  "
                f"top_blocks=[{top_str}]  recon={s['ws_reconnects']}"
            )

    tasks.append(asyncio.create_task(_heartbeat(), name="heartbeat"))

    logger.info("🚀 All tasks launched — APEX SYSTEM™ is live")
    logger.info(
        f"   T3 ≥10% APEX≥82  ·  T4 ≥20% APEX≥78  ·  "
        f"Signal rules: TP-state + SL-state (no timers)"
    )

    try:
        await asyncio.gather(*tasks)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        logger.info("Shutting down...")
        if tg_bot: await tg_bot.shutdown()
        scanner.stop()
        logger.info("APEX stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
