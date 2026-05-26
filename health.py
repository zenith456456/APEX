"""
health.py ─ Lightweight HTTP health-check server
Northflank (and any container platform) pings GET /health to confirm
the process is alive. Returns 200 JSON with live stats.
"""
import asyncio
import json
from aiohttp import web
from logger_setup import get_logger

log = get_logger("health")


async def make_health_app(stats_fn) -> web.Application:
    """
    stats_fn: zero-arg callable that returns the current stats snapshot dict.
    """
    app = web.Application()

    async def handle_health(request):
        try:
            st = stats_fn()
        except Exception:
            st = {}
        body = {
            "status":  "ok",
            "service": "apex-quant-bot",
            "stats": {
                "trade_count": st.get("trade_count", 0),
                "total_wr":    st.get("total", {}).get("wr", 0),
                "total_pnl":   st.get("total", {}).get("pnl_str", "0R"),
            },
        }
        return web.Response(
            text=json.dumps(body),
            content_type="application/json",
            status=200,
        )

    async def handle_root(request):
        return web.Response(text="APEX-QUANT running ✓", status=200)

    app.router.add_get("/health", handle_health)
    app.router.add_get("/",       handle_root)
    return app


async def run_health_server(port: int, stats_fn):
    app    = await make_health_app(stats_fn)
    runner = web.AppRunner(app)
    await runner.setup()
    site   = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"Health server listening on port {port}")
