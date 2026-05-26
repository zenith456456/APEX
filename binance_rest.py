"""
binance_rest.py ─ Async Binance REST client
• Automatic host failover: api → api1 → api2 → api3
• Rate-limit aware (respects 429 / 418 responses)
• No API key required for all public endpoints used here
"""
import asyncio
from typing import Optional
import aiohttp
from config import cfg
from logger_setup import get_logger

log = get_logger("rest")

_host_idx: int = 0
_session:  Optional[aiohttp.ClientSession] = None

EXCLUDE_SYMBOLS = {
    "BUSDUSDT","USDCUSDT","TUSDUSDT","USDTUSDT",
    "DAIUSDT","FDUSDUSDT","PAXUSDT","EURUSDT","GBPUSDT",
}
EXCLUDE_SUFFIXES = ("UPUSDT","DOWNUSDT","BEARUSDT","BULLUSDT","3LUSDT","3SUSDT")


def _base() -> str:
    return cfg.BINANCE_REST_URLS[_host_idx % len(cfg.BINANCE_REST_URLS)]


async def _session_get() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=12),
            connector=aiohttp.TCPConnector(ssl=True, limit=20),
        )
    return _session


async def _get(path: str, params: dict | None = None, retries: int = 4) -> list | dict | None:
    global _host_idx
    sess = await _session_get()
    for attempt in range(retries):
        url = f"{_base()}{path}"
        try:
            async with sess.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                if resp.status == 429:
                    wait = int(resp.headers.get("Retry-After", 15))
                    log.warning(f"Rate-limited — waiting {wait}s")
                    await asyncio.sleep(wait)
                elif resp.status in (418, 403):
                    log.warning(f"IP restricted on {_base()} — switching host")
                    _host_idx += 1
                else:
                    log.warning(f"HTTP {resp.status} {url}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning(f"REST error attempt {attempt+1}: {exc} — switching host")
            _host_idx += 1
            await asyncio.sleep(2 ** attempt)
    log.error(f"All retries exhausted for {path}")
    return None


# ── Public helpers ────────────────────────────────────────────────────────────

async def get_exchange_info() -> dict:
    return await _get("/api/v3/exchangeInfo") or {}


async def get_ticker_24h() -> list:
    return await _get("/api/v3/ticker/24hr") or []


async def get_klines(symbol: str, interval: str, limit: int = 100) -> list:
    """Returns raw Binance kline list-of-lists."""
    return await _get("/api/v3/klines", {
        "symbol": symbol, "interval": interval, "limit": limit,
    }) or []


async def get_all_usdt_trading_symbols() -> set[str]:
    """All active spot USDT trading pairs from exchangeInfo."""
    info = await get_exchange_info()
    result: set[str] = set()
    for s in info.get("symbols", []):
        if (s.get("quoteAsset") == "USDT"
                and s.get("status") == "TRADING"
                and s.get("isSpotTradingAllowed", False)):
            result.add(s["symbol"])
    return result


async def get_top_usdt_pairs(min_vol: float, max_pairs: int) -> list[str]:
    """Top USDT pairs by 24h quote volume, filtered for quality."""
    tickers = await get_ticker_24h()
    pairs: list[tuple[str, float]] = []
    for t in tickers:
        sym = t.get("symbol", "")
        vol = float(t.get("quoteVolume", 0))
        if (sym.endswith("USDT")
                and sym not in EXCLUDE_SYMBOLS
                and not any(sym.endswith(s) for s in EXCLUDE_SUFFIXES)
                and vol >= min_vol):
            pairs.append((sym, vol))
    pairs.sort(key=lambda x: x[1], reverse=True)
    selected = [p[0] for p in pairs[:max_pairs]]
    log.info(f"Selected {len(selected)} pairs (min vol ${min_vol:,.0f})")
    return selected


async def close():
    global _session
    if _session and not _session.closed:
        await _session.close()
