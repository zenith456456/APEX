"""
health.py — HTTP health-check server for Northflank / container platforms

Endpoints:
  GET /          → 200  plain text "APEX-QUANT running ✓"
  GET /health    → 200  JSON full status (used by Northflank health probe)
  GET /stats     → 200  JSON live trading statistics
  GET /config    → 200  JSON config summary (no secrets)
  GET /pairs     → 200  JSON list of pairs being scanned

Northflank health-check config:
  Protocol : HTTP
  Path     : /health
  Port     : 8080
  Initial delay : 20s
  Period        : 30s
  Timeout       : 10s
  Failure threshold : 3
"""
import asyncio
import json
import time
from datetime import datetime, timezone
from aiohttp import web
from logger_setup import get_logger
from config import cfg

log = get_logger("health")

# Set by scanner.py after startup
_scanner_ref = None
_start_time  = time.time()


def set_scanner(scanner):
    global _scanner_ref
    _scanner_ref = scanner


def _uptime_str() -> str:
    secs = int(time.time() - _start_time)
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m}m {s}s"


async def make_app() -> web.Application:
    app = web.Application()

    # ── GET / ────────────────────────────────────────────────────
    async def handle_root(req):
        return web.Response(
            text="APEX-QUANT running ✓  |  GET /health for status",
            status=200
        )

    # ── GET /health ──────────────────────────────────────────────
    async def handle_health(req):
        sc = _scanner_ref
        try:
            st = sc.stats.snapshot() if sc else {}
            pairs_tracked = len(sc.pairs) if sc else 0
            active_mem    = len(sc.mem.active_pairs()) if sc else 0
            candle_closes = getattr(sc, "_candle_closes", 0) if sc else 0
            ws_connected  = getattr(sc.ws, "_backoff", 2) == 2.0 if sc else False
        except Exception:
            st, pairs_tracked, active_mem, candle_closes, ws_connected = {}, 0, 0, 0, False

        body = {
            "status":      "ok",
            "service":     "apex-quant-bot",
            "version":     "4.0",
            "uptime":      _uptime_str(),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "scanner": {
                "pairs_tracked":  pairs_tracked,
                "active_signals": active_mem,
                "candle_closes":  candle_closes,
                "ws_connected":   ws_connected,
                "signals_emitted":st.get("trade_count", 0),
            },
            "performance": {
                "daily_wr":    st.get("daily",   {}).get("wr",  0),
                "monthly_wr":  st.get("monthly", {}).get("wr",  0),
                "total_wr":    st.get("total",   {}).get("wr",  0),
                "daily_pnl":   st.get("daily",   {}).get("pnl_str", "0R"),
                "monthly_pnl": st.get("monthly", {}).get("pnl_str", "0R"),
                "total_pnl":   st.get("total",   {}).get("pnl_str", "0R"),
                "total_wins":  st.get("total",   {}).get("wins",    0),
                "total_losses":st.get("total",   {}).get("losses",  0),
            },
            "notifications": {
                "telegram_configured": bool(cfg.TELEGRAM_BOT_TOKEN and cfg.TELEGRAM_CHAT_ID),
                "discord_configured":  bool(cfg.DISCORD_WEBHOOK_URL),
            },
        }
        return web.Response(
            text=json.dumps(body, indent=2),
            content_type="application/json",
            status=200,
        )

    # ── GET /stats ───────────────────────────────────────────────
    async def handle_stats(req):
        sc = _scanner_ref
        try:
            st = sc.stats.snapshot() if sc else {}
        except Exception:
            st = {}

        tp = st.get("tp", {})
        body = {
            "trade_count": st.get("trade_count", 0),
            "daily": {
                "win_rate": st.get("daily",   {}).get("wr",  0),
                "pnl":      st.get("daily",   {}).get("pnl_str", "0R"),
                "wins":     st.get("daily",   {}).get("wins",    0),
                "losses":   st.get("daily",   {}).get("losses",  0),
            },
            "monthly": {
                "win_rate": st.get("monthly", {}).get("wr",  0),
                "pnl":      st.get("monthly", {}).get("pnl_str", "0R"),
                "wins":     st.get("monthly", {}).get("wins",    0),
                "losses":   st.get("monthly", {}).get("losses",  0),
            },
            "all_time": {
                "win_rate": st.get("total",   {}).get("wr",  0),
                "pnl":      st.get("total",   {}).get("pnl_str", "0R"),
                "wins":     st.get("total",   {}).get("wins",    0),
                "losses":   st.get("total",   {}).get("losses",  0),
            },
            "tp_buckets": {
                "tp1_only": tp.get("tp1", 0),
                "tp2":      tp.get("tp2", 0),
                "tp3":      tp.get("tp3", 0),
                "tp4":      tp.get("tp4", 0),
                "tp5":      tp.get("tp5", 0),
                "sl_hits":  tp.get("sl",  0),
            },
        }
        return web.Response(
            text=json.dumps(body, indent=2),
            content_type="application/json",
            status=200,
        )

    # ── GET /config ──────────────────────────────────────────────
    async def handle_config(req):
        body = {
            "scan_timeframes":    cfg.SCAN_TIMEFRAMES,
            "min_volume_usdt":    cfg.MIN_VOLUME_USDT,
            "min_css_score":      cfg.MIN_CSS_SCORE,
            "max_pairs":          cfg.MAX_PAIRS,
            "signal_cooldown_min":cfg.SIGNAL_COOLDOWN,
            "vpi_min_abs":        cfg.VPI_MIN_ABS,
            "fdi_max":            cfg.FDI_MAX,
            "atr_tp_mults":       cfg.ATR_TP_MULTS,
            "telegram_set":       bool(cfg.TELEGRAM_BOT_TOKEN and cfg.TELEGRAM_CHAT_ID),
            "discord_set":        bool(cfg.DISCORD_WEBHOOK_URL),
        }
        return web.Response(
            text=json.dumps(body, indent=2),
            content_type="application/json",
            status=200,
        )

    # ── GET /pairs ───────────────────────────────────────────────
    async def handle_pairs(req):
        sc = _scanner_ref
        try:
            pairs  = sc.pairs if sc else []
            active = sc.mem.active_pairs() if sc else []
            body   = {
                "total_tracked":  len(pairs),
                "active_signals": len(active),
                "pairs":          pairs,
                "pairs_with_active_signals": active,
            }
        except Exception as exc:
            body = {"error": str(exc)}
        return web.Response(
            text=json.dumps(body, indent=2),
            content_type="application/json",
            status=200,
        )

    app.router.add_get("/",       handle_root)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/stats",  handle_stats)
    app.router.add_get("/config", handle_config)
    app.router.add_get("/pairs",  handle_pairs)
    return app


async def run_health_server(port: int, scanner=None):
    if scanner is not None:
        set_scanner(scanner)
    app    = await make_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site   = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(
        f"Health server on port {port}\n"
        f"  http://localhost:{port}/         → status\n"
        f"  http://localhost:{port}/health   → full JSON health check\n"
        f"  http://localhost:{port}/stats    → live trading stats\n"
        f"  http://localhost:{port}/config   → active config\n"
        f"  http://localhost:{port}/pairs    → tracked pairs"
    )
