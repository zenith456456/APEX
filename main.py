#!/usr/bin/env python3
"""
APEX SYSTEM™ — MAIN ENTRY POINT
Orchestrates: Binance Scanner + Exchange Monitor + Telegram + Discord + Health Check
Usage: python main.py
"""
import asyncio, logging, os, signal, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import config
from binance_scanner import BinanceScanner

BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║     █████╗ ██████╗ ███████╗██╗  ██╗  SYSTEM™               ║
║    ██╔══██╗██╔══██╗██╔════╝╚██╗██╔╝                         ║
║    ███████║██████╔╝█████╗   ╚███╔╝                          ║
║    ██╔══██║██╔═══╝ ██╔══╝   ██╔██╗                          ║
║    ██║  ██║██║     ███████╗██╔╝ ██╗                         ║
║    ╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝                        ║
║                                                              ║
║   Binance Futures WS  ·  T3 STRONG (>=10%)  +  T4 MEGA(>=20%)
║   Northflank / Render / Docker  ·  24/7 Free Hosting        ║
║                                                              ║
║   Signals: Pair · Entry · Position · Leverage               ║
║            TP1/TP2/TP3 · SL · R:R · Style · Time            ║
║            --- APEX SCORE ---                               ║
╚══════════════════════════════════════════════════════════════╝
"""

def setup_logging():
    level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    fmt   = "%(asctime)s  %(levelname)-8s  %(name)-18s  %(message)s"
    handlers = [logging.StreamHandler(sys.stdout)]
    if config.LOG_FILE:
        try: handlers.append(logging.FileHandler(config.LOG_FILE, encoding="utf-8"))
        except OSError: pass
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers)
    for noisy in ("httpx","httpcore","hpack","websockets.client","websockets.connection",
                  "discord.gateway","discord.http","discord.client",
                  "telegram.ext.Updater","telegram.ext.Application"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger("apex.main")

# ── Health check HTTP server ──────────────────────────────────
_hstats: dict = {}

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (f"APEX SYSTEM™ — OK\n"
                f"pairs_live : {_hstats.get('pairs_live',0)}\n"
                f"t3_fired   : {_hstats.get('t3_fired',0)}\n"
                f"t4_fired   : {_hstats.get('t4_fired',0)}\n"
                f"reconnects : {_hstats.get('ws_reconnects',0)}\n").encode()
        self.send_response(200)
        self.send_header("Content-Type","text/plain")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def log_message(self,*_): pass

def _start_health_server(port: int, stats: dict):
    global _hstats; _hstats = stats
    srv = HTTPServer(("0.0.0.0", port), _HealthHandler)
    Thread(target=srv.serve_forever, daemon=True).start()
    logger.info(f"✓ Health check server on port {port}")

# ── Main ──────────────────────────────────────────────────────
async def main():
    setup_logging()
    print(BANNER)
    if not config.validate():
        sys.exit(1)

    scanner    = BinanceScanner()
    start_time = [time.time()]
    stats_ref  = scanner.stats
    hist_ref   = scanner.signal_history

    if config.HEALTH_CHECK_ENABLED:
        _start_health_server(config.HEALTH_CHECK_PORT, stats_ref)

    tg_bot = None
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHANNEL_ID:
        from telegram_bot import TelegramBot
        tg_bot = TelegramBot(stats_ref, start_time, hist_ref)
        scanner.add_signal_callback(tg_bot.on_signal)
        scanner.add_new_listing_callback(tg_bot.on_new_listing)
        logger.info("✓ Telegram bot registered")

    dc_bot = None
    if config.DISCORD_BOT_TOKEN and config.DISCORD_CHANNEL_ID and config.DISCORD_GUILD_ID:
        from discord_bot import ApexDiscordBot
        dc_bot = ApexDiscordBot(stats_ref, start_time, hist_ref)
        scanner.add_signal_callback(dc_bot.on_signal)
        scanner.add_new_listing_callback(dc_bot.on_new_listing)
        logger.info("✓ Discord bot registered")

    loop = asyncio.get_event_loop()
    def _shutdown(*_):
        logger.info("Shutdown signal received...")
        scanner.stop()
        for t in asyncio.all_tasks(loop): t.cancel()
    for sig_num in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(sig_num, _shutdown)
        except NotImplementedError: pass

    tasks = [asyncio.create_task(scanner.run(), name="scanner")]
    if tg_bot: tasks.append(asyncio.create_task(tg_bot.run(),      name="telegram"))
    if dc_bot: tasks.append(asyncio.create_task(dc_bot.run_bot(),  name="discord"))

    async def _ticker():
        while True:
            await asyncio.sleep(60)
            s = scanner.stats
            tot = s["t3_fired"]+s["t4_fired"]; rej = s["t3_rejected"]+s["t4_rejected"]
            rej_r = f"{rej/(tot+rej)*100:.0f}%" if (tot+rej)>0 else "n/a"
            # Show which APEX gate is blocking the most signals
            gr = scanner.engine.gate_rejects
            top_gate = sorted(gr.items(), key=lambda x: x[1], reverse=True)[:3]
            top_str  = "  ".join(f"{k}:{v}" for k,v in top_gate if v > 0) or "none"
            logger.info(
                f"HEARTBEAT | pairs={s['pairs_live']} frames={s['frames_total']:,} | "
                f"T3:{s['t3_fired']}✓/{s['t3_rejected']}✗  "
                f"T4:{s['t4_fired']}✓/{s['t4_rejected']}✗ | "
                f"reject={rej_r}  top_blocks=[{top_str}]  recon={s['ws_reconnects']}"
            )
    tasks.append(asyncio.create_task(_ticker(), name="ticker"))

    logger.info("🚀 All tasks launched — APEX SYSTEM™ is live")
    logger.info(f"   Scanning Binance Futures · T3>=10% · T4>=20% · Exchange refresh every {config.EXCHANGE_REFRESH_MIN} min")
    try: await asyncio.gather(*tasks)
    except (asyncio.CancelledError, KeyboardInterrupt): pass
    finally:
        logger.info("Shutting down...")
        if tg_bot: await tg_bot.shutdown()
        scanner.stop()
        logger.info("✓ APEX bot stopped cleanly.")

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: print("\nStopped by user.")
