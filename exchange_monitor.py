"""
APEX-EDS v4.0 | exchange_monitor.py
─────────────────────────────────────────────────────────────────────────────
Fixes:
  1. VPIN BUG: buy_vol/sell_vol accumulated forever without reset → VPIN
     drifted toward 0 over hours as buy/sell balanced out → ALL symbols
     failed VPIN gate → zero signals generated.
     Fix: VPIN is now calculated from recent agg_trades deque only (last 500
     trades). buy_vol/sell_vol are reset every 30 minutes so they don't
     represent stale old volume.

  2. CPU/MEMORY: Scanning all 534 pairs with 36 WS connections is wasteful.
     Fix: Filter to top MAX_SCAN_PAIRS (150) pairs by 24h USDT volume.
     Only liquid pairs can produce valid signals anyway. This cuts WS
     connections from 36 to 10, reducing CPU/memory by ~70%.

  3. WS stability: ping_interval=None (Binance server-led keepalive) retained.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import json
import logging
import random
import time
from collections import deque
from typing import Dict, List, Optional, Set

import aiohttp
import websockets

import config

logger = logging.getLogger("ExchangeMonitor")

_HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 ApexEDS/4.0"}

_REST_URLS = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
    "https://fapi4.binance.com",
]

_COMBINED_WS = "wss://fstream.binance.com/stream"
_MINI_TICKER = "wss://fstream.binance.com/ws/!miniTicker@arr"

# ── KEY PERFORMANCE CONSTANTS ─────────────────────────────────────────────
# Only scan the top N pairs by 24h USDT volume.
# 150 pairs → 10 WS connections vs 36 for all 534 pairs.
# Illiquid pairs (low volume) can never pass VPIN/CVD gates anyway.
MAX_SCAN_PAIRS   = 150

# Symbols per combined WS connection (15 × 5 streams = 75 streams each)
_SYMBOLS_PER_WS  = 15

# Reset accumulated buy/sell volume every N seconds to keep VPIN fresh.
# Without this, buy_vol and sell_vol both grow huge and nearly equal,
# causing VPIN → 0 over time, blocking all signals.
_VOL_RESET_SEC   = 1800   # 30 minutes

# Back-off
_BACKOFF_BASE    = 5
_BACKOFF_MAX     = 60
_JITTER_MAX      = 5


def _backoff(attempt: int) -> float:
    base   = min(_BACKOFF_BASE * (2 ** min(attempt, 5)), _BACKOFF_MAX)
    jitter = random.uniform(0, _JITTER_MAX)
    return base + jitter


# ─────────────────────────────────────────────────────────────────────────────
class CandleBar:
    __slots__ = ["t", "o", "h", "l", "c", "v", "closed"]

    def __init__(self, t, o, h, l, c, v, closed):
        self.t = t
        self.o = float(o); self.h = float(h)
        self.l = float(l); self.c = float(c)
        self.v = float(v); self.closed = bool(closed)


class SymbolData:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.candles: Dict[str, deque] = {
            "1m":  deque(maxlen=120),
            "5m":  deque(maxlen=120),
            "15m": deque(maxlen=120),
        }
        self.last_price:       float = 0.0
        self.price_change_24h: float = 0.0
        self.volume_24h:       float = 0.0
        self.bid:              float = 0.0
        self.ask:              float = 0.0

        # Rolling accumulators — reset every _VOL_RESET_SEC
        # Used as a quick approximation for imbalance direction.
        # VPIN scoring uses agg_trades deque (more accurate).
        self.buy_vol:          float = 0.0
        self.sell_vol:         float = 0.0
        self.vol_reset_at:     float = time.time()

        # Recent individual trades — used by indicators.vpin() and cvd()
        self.agg_trades:       deque = deque(maxlen=500)

        self.updated_at:       float = 0.0

    def maybe_reset_vol(self):
        """Reset rolling buy/sell volume every _VOL_RESET_SEC."""
        if time.time() - self.vol_reset_at >= _VOL_RESET_SEC:
            self.buy_vol      = 0.0
            self.sell_vol     = 0.0
            self.vol_reset_at = time.time()


# ─────────────────────────────────────────────────────────────────────────────
class ExchangeMonitor:

    def __init__(self):
        # All known symbols (full 534 for price tracking via miniTicker)
        self.symbols:       Dict[str, SymbolData] = {}
        # All active perpetuals from Binance
        self.active_pairs:  Set[str]              = set()
        # Top N by volume — these are the ones we open WS streams for
        self.scan_pairs:    List[str]             = []

        self._session:      Optional[aiohttp.ClientSession] = None
        self._ws_tasks:     List[asyncio.Task]    = []
        self._running       = False
        self._rest_url      = _REST_URLS[0]

    # ── PUBLIC ────────────────────────────────────────────────────────────

    async def start(self):
        self._running = True
        self._session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=True, limit=60),
            headers=_HEADERS,
        )
        logger.info("ExchangeMonitor: starting...")

        await self._find_rest_endpoint()

        if self.active_pairs:
            await self._seed_klines_rest()
        else:
            logger.error("No pairs loaded at startup — will retry hourly")

        asyncio.create_task(self._mini_ticker_ws())
        asyncio.create_task(self._ws_manager())
        asyncio.create_task(self._exchange_info_loop())
        asyncio.create_task(self._vol_reset_loop())

        logger.info(
            f"ExchangeMonitor: {len(self.active_pairs)} active pairs | "
            f"Scanning top {len(self.scan_pairs)} by volume | "
            f"REST: {self._rest_url} | "
            f"WS connections: ~{max(1, len(self.scan_pairs) // _SYMBOLS_PER_WS)}"
        )

    async def stop(self):
        self._running = False
        for t in self._ws_tasks:
            t.cancel()
        if self._session:
            await self._session.close()

    def get_symbol_data(self, symbol: str) -> Optional[SymbolData]:
        return self.symbols.get(symbol)

    def get_all_symbols(self) -> List[str]:
        """Returns top scan_pairs only — these have live WS data."""
        return list(self.scan_pairs)

    # ── VOL RESET LOOP ───────────────────────────────────────────────────
    # Resets buy_vol/sell_vol on all symbols every 30 minutes.
    # This prevents VPIN drifting to 0 as cumulative volumes balance out.

    async def _vol_reset_loop(self):
        while self._running:
            await asyncio.sleep(_VOL_RESET_SEC)
            reset_count = 0
            for sd in self.symbols.values():
                sd.buy_vol      = 0.0
                sd.sell_vol     = 0.0
                sd.vol_reset_at = time.time()
                reset_count    += 1
            logger.info(
                f"Vol reset: cleared buy/sell accumulators "
                f"for {reset_count} symbols (VPIN refresh)"
            )

    # ── REST: FIND WORKING ENDPOINT ───────────────────────────────────────

    async def _find_rest_endpoint(self):
        for url in _REST_URLS:
            logger.info(f"Trying REST: {url}")
            pairs = await self._fetch_exchange_info(url)
            if pairs:
                self._rest_url    = url
                self.active_pairs = pairs
                for s in pairs:
                    if s not in self.symbols:
                        self.symbols[s] = SymbolData(s)
                logger.info(f"REST OK: {url} — {len(pairs)} USDT-M pairs")
                return
        logger.error("All REST endpoints failed — will retry hourly")

    async def _fetch_exchange_info(self, base: str) -> Set[str]:
        url = f"{base}/fapi/v1/exchangeInfo"
        try:
            async with self._session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=True,
            ) as r:
                if r.status == 451:
                    logger.warning(f"{base}: geo-blocked (451)")
                    return set()
                if r.status not in (200, 202):
                    logger.warning(f"{base}: HTTP {r.status}")
                    return set()
                try:
                    data = json.loads(await r.text())
                except json.JSONDecodeError:
                    return set()
                if not isinstance(data, dict):
                    return set()
                if data.get("code", 0) not in (0, None, ""):
                    logger.warning(f"{base}: error {data.get('code')}")
                    return set()
                found: Set[str] = set()
                for sym in data.get("symbols", []):
                    if (isinstance(sym, dict)
                            and sym.get("status") == "TRADING"
                            and sym.get("contractType") == "PERPETUAL"
                            and sym.get("quoteAsset") == "USDT"):
                        found.add(sym["symbol"])
                logger.info(f"{base}: {len(found)} USDT-M pairs")
                return found
        except asyncio.TimeoutError:
            logger.warning(f"{base}: timeout")
            return set()
        except Exception as e:
            logger.warning(f"{base}: {e}")
            return set()

    # ── SELECT TOP PAIRS BY VOLUME ────────────────────────────────────────

    def _update_scan_pairs(self):
        """
        Sort all symbols by 24h USDT volume descending.
        Keep top MAX_SCAN_PAIRS. These are the only ones we open WS for.
        Called after miniTicker has populated volume_24h values.
        """
        candidates = [
            (sym, sd.volume_24h)
            for sym, sd in self.symbols.items()
            if sym in self.active_pairs and sd.volume_24h > 0
        ]
        if not candidates:
            # Fallback: use all active pairs if volume not yet known
            self.scan_pairs = list(self.active_pairs)[:MAX_SCAN_PAIRS]
            return

        candidates.sort(key=lambda x: x[1], reverse=True)
        self.scan_pairs = [sym for sym, _ in candidates[:MAX_SCAN_PAIRS]]

        top5 = [(s, f"${v/1e9:.1f}B") for s, v in candidates[:5]]
        logger.info(
            f"Scan pairs updated: top {len(self.scan_pairs)} by volume | "
            f"Top 5: {top5}"
        )

    # ── REST: ONE-TIME KLINE SEED ─────────────────────────────────────────

    async def _seed_klines_rest(self, symbols: Optional[List[str]] = None):
        # If scan_pairs not yet populated, seed top pairs from active_pairs
        targets = symbols or (
            self.scan_pairs if self.scan_pairs
            else list(self.active_pairs)[:MAX_SCAN_PAIRS]
        )
        if not targets:
            return
        logger.info(
            f"Seeding {len(targets)} symbols with kline history "
            f"(REST, one-time at startup)..."
        )
        sem = asyncio.Semaphore(20)

        async def fetch(symbol: str, interval: str):
            async with sem:
                url    = f"{self._rest_url}/fapi/v1/klines"
                params = {"symbol": symbol, "interval": interval, "limit": 100}
                try:
                    async with self._session.get(
                        url, params=params,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as r:
                        if r.status not in (200, 202):
                            return
                        rows = await r.json(content_type=None)
                        if not isinstance(rows, list):
                            return
                        sd = self.symbols.get(symbol)
                        if not sd:
                            return
                        for row in rows:
                            if isinstance(row, list) and len(row) >= 6:
                                sd.candles[interval].append(
                                    CandleBar(
                                        row[0], row[1], row[2],
                                        row[3], row[4], row[5], True
                                    )
                                )
                except Exception as e:
                    logger.debug(f"Kline seed {symbol}/{interval}: {e}")

        await asyncio.gather(*[
            fetch(s, iv) for s in targets for iv in config.KLINE_INTERVALS
        ])
        logger.info("Kline seed complete — all live data now via WebSocket")

    # ── EXCHANGE INFO LOOP (hourly) ───────────────────────────────────────

    async def _exchange_info_loop(self):
        while self._running:
            await asyncio.sleep(config.EXCHANGE_INFO_TTL_SEC)
            try:
                if not self.active_pairs:
                    await self._find_rest_endpoint()
                    if self.active_pairs:
                        await self._seed_klines_rest()
                    continue

                new_pairs = await self._fetch_exchange_info(self._rest_url)
                if not new_pairs:
                    logger.warning("Exchange info refresh failed — re-probing")
                    await self._find_rest_endpoint()
                    continue

                added   = new_pairs - self.active_pairs
                removed = self.active_pairs - new_pairs
                self.active_pairs = new_pairs

                for s in new_pairs:
                    if s not in self.symbols:
                        self.symbols[s] = SymbolData(s)

                if added:
                    logger.info(f"New listings detected: {added}")
                    await self._seed_klines_rest(list(added))
                if removed:
                    logger.info(f"Delisted: {removed}")

                # Re-rank scan pairs by current volume
                self._update_scan_pairs()

                logger.info(
                    f"Exchange info refreshed — {len(self.active_pairs)} pairs | "
                    f"Scanning top {len(self.scan_pairs)}"
                )
            except Exception as e:
                logger.error(f"Exchange info loop: {e}")

    # ── WS: !miniTicker@arr ───────────────────────────────────────────────
    # Delivers 24h stats for ALL symbols every second.
    # After first update, we rank pairs by volume to select scan_pairs.

    async def _mini_ticker_ws(self):
        attempt        = 0
        ranked_once    = False

        while self._running:
            if attempt > 0:
                delay = _backoff(attempt)
                logger.info(f"miniTicker reconnecting in {delay:.1f}s")
                await asyncio.sleep(delay)
            try:
                async with websockets.connect(
                    _MINI_TICKER,
                    ping_interval=None,   # Binance server-led keepalive
                    open_timeout=20,
                    close_timeout=5,
                    max_size=50_000_000,
                    extra_headers={"User-Agent": "Mozilla/5.0 ApexEDS/4.0"},
                ) as ws:
                    logger.info("miniTicker WS connected")
                    attempt = 0
                    async for raw in ws:
                        if not self._running:
                            return
                        try:
                            payload = json.loads(raw)

                            if isinstance(payload, dict):
                                if payload.get("e") == "ping":
                                    await ws.send(json.dumps({"e": "pong"}))
                                continue

                            if not isinstance(payload, list):
                                continue

                            for t in payload:
                                if not isinstance(t, dict):
                                    continue
                                sym = t.get("s", "")
                                if sym not in self.symbols:
                                    continue
                                sd = self.symbols[sym]
                                try:
                                    price = float(t.get("c", 0) or 0)
                                    if price > 0:
                                        sd.last_price       = price
                                        sd.price_change_24h = float(t.get("P", 0) or 0)
                                        sd.volume_24h       = float(t.get("q", 0) or 0)
                                        sd.updated_at       = time.time()
                                except (ValueError, TypeError):
                                    pass

                            # After first full update, rank pairs by volume
                            # and seed klines for top pairs
                            if not ranked_once and len(self.active_pairs) > 0:
                                self._update_scan_pairs()
                                if self.scan_pairs:
                                    ranked_once = True
                                    # Seed klines for top pairs
                                    asyncio.create_task(
                                        self._seed_klines_rest(self.scan_pairs)
                                    )

                        except Exception:
                            pass

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(
                    f"miniTicker WS: {type(e).__name__} "
                    f"(attempt {attempt + 1})"
                )
                attempt += 1

    # ── WS MANAGER ───────────────────────────────────────────────────────

    async def _ws_manager(self):
        """Open combined-stream connections for scan_pairs (top N by volume)."""
        # Wait for miniTicker to populate volume and rank pairs
        await asyncio.sleep(15)

        while self._running:
            for t in self._ws_tasks:
                t.cancel()
            self._ws_tasks.clear()

            pairs = list(self.scan_pairs) if self.scan_pairs else list(self.active_pairs)[:MAX_SCAN_PAIRS]

            if not pairs:
                logger.warning("WS manager: no pairs — waiting 30s")
                await asyncio.sleep(30)
                continue

            chunks = [
                pairs[i:i + _SYMBOLS_PER_WS]
                for i in range(0, len(pairs), _SYMBOLS_PER_WS)
            ]
            logger.info(
                f"WS manager: {len(pairs)} pairs → {len(chunks)} connections "
                f"({_SYMBOLS_PER_WS} symbols × 5 streams = "
                f"{_SYMBOLS_PER_WS * 5} streams each)"
            )
            for idx, chunk in enumerate(chunks):
                self._ws_tasks.append(
                    asyncio.create_task(self._ws_connection(chunk, conn_id=idx))
                )

            await asyncio.sleep(config.EXCHANGE_INFO_TTL_SEC)

    # ── WS CONNECTION ─────────────────────────────────────────────────────

    async def _ws_connection(self, symbols: List[str], conn_id: int = 0):
        streams = []
        for s in symbols:
            sl = s.lower()
            for iv in config.KLINE_INTERVALS:
                streams.append(f"{sl}@kline_{iv}")
            streams.append(f"{sl}@bookTicker")
            streams.append(f"{sl}@aggTrade")

        url     = f"{_COMBINED_WS}?streams=" + "/".join(streams)
        attempt = 0

        # Stagger startup: 0.2s per connection
        await asyncio.sleep(conn_id * 0.2)

        while True:
            if attempt > 0:
                delay = _backoff(attempt)
                logger.debug(
                    f"[conn-{conn_id}] reconnect in {delay:.1f}s "
                    f"(attempt {attempt})"
                )
                await asyncio.sleep(delay)

            try:
                async with websockets.connect(
                    url,
                    ping_interval=None,   # Binance server-led keepalive
                    open_timeout=20,
                    close_timeout=5,
                    max_size=10_000_000,
                    extra_headers={"User-Agent": "Mozilla/5.0 ApexEDS/4.0"},
                ) as ws:
                    logger.debug(
                        f"[conn-{conn_id}] connected: {len(symbols)} symbols, "
                        f"{len(streams)} streams"
                    )
                    attempt = 0

                    async for raw in ws:
                        if not self._running:
                            return
                        try:
                            msg = json.loads(raw)
                            if isinstance(msg, dict) and msg.get("e") == "ping":
                                await ws.send(json.dumps({"e": "pong"}))
                                continue
                            self._dispatch(msg)
                        except Exception:
                            pass

            except asyncio.CancelledError:
                return
            except Exception as e:
                log_fn = logger.debug if attempt == 0 else logger.warning
                log_fn(
                    f"[conn-{conn_id}] {type(e).__name__} "
                    f"(attempt {attempt + 1}) — reconnecting"
                )
                attempt += 1

    # ── DISPATCH ─────────────────────────────────────────────────────────

    def _dispatch(self, msg: dict):
        if not isinstance(msg, dict):
            return
        data   = msg.get("data", msg)
        stream = msg.get("stream", "")
        if not isinstance(data, dict):
            return
        if "@kline_" in stream:
            self._on_kline(data)
        elif "@bookTicker" in stream:
            self._on_book(data)
        elif "@aggTrade" in stream:
            self._on_trade(data)

    def _on_kline(self, data: dict):
        k = data.get("k", {})
        if not isinstance(k, dict):
            return
        sym = k.get("s", "")
        iv  = k.get("i", "")
        if sym not in self.symbols or iv not in config.KLINE_INTERVALS:
            return
        sd = self.symbols[sym]
        try:
            bar = CandleBar(
                k["t"], k["o"], k["h"],
                k["l"], k["c"], k["v"], k["x"]
            )
        except (KeyError, ValueError):
            return
        q = sd.candles[iv]
        if q and not q[-1].closed:
            q[-1] = bar
        else:
            q.append(bar)
        sd.updated_at = time.time()

    def _on_book(self, data: dict):
        sym = data.get("s", "")
        if sym in self.symbols:
            sd = self.symbols[sym]
            try:
                bid = float(data.get("b", 0) or 0)
                ask = float(data.get("a", 0) or 0)
                if bid > 0 and ask > 0:
                    sd.bid = bid
                    sd.ask = ask
            except (ValueError, TypeError):
                pass

    def _on_trade(self, data: dict):
        sym = data.get("s", "")
        if sym not in self.symbols:
            return
        sd = self.symbols[sym]
        try:
            price = float(data.get("p", 0) or 0)
            qty   = float(data.get("q", 0) or 0)
            maker = bool(data.get("m", False))
            usdt  = price * qty

            # Reset stale accumulators before adding new trade
            sd.maybe_reset_vol()

            if maker:
                sd.sell_vol += usdt
            else:
                sd.buy_vol  += usdt

            sd.agg_trades.append({"p": price, "q": qty, "m": maker})

            if price > 0:
                sd.last_price = price
                sd.updated_at = time.time()

        except (ValueError, TypeError):
            pass
