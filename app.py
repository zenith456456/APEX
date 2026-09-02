import asyncio
import logging
import os
import sys

from aiohttp import web

from config import SETTINGS
from scanner import Scanner


# Northflank separates stdout and stderr. Keep normal application logs on stdout;
# stderr should be reserved for real exceptions/error output.
logging.basicConfig(
    level=getattr(logging, SETTINGS.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
    force=True,
)

logger = logging.getLogger(__name__)
scanner = Scanner(SETTINGS)


async def health(request):
    return web.json_response(
        {
            "status": "ok",
            "active_symbols": scanner.active,
            "tracked_symbols": len(scanner.market),
        }
    )


async def main():
    app = web.Application()
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", SETTINGS.port))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info("Health server listening on 0.0.0.0:%s", port)

    try:
        await scanner.run()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
