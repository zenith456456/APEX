"""
scanner.py — APEX-QUANT core scanner
Registers itself with health.py so /health endpoint has live stats.
"""
import asyncio
import time
from collections import defaultdict, deque

from config import cfg
from logger_setup import get_logger
from binance_rest import get_top_usdt_pairs, get_klines, get_all_usdt_trading_symbols
from binance_ws   import BinanceWS
from signal_engine import generate
from memory_engine import MemoryEngine
from stats_tracker import StatsTracker
from formatter import (tg_signal, tg_resolution, tg_new_listing,
                       dc_signal, dc_resolution, dc_new_listing)
from notifier import broadcast
import health as health_module

log = get_logger("scanner")


class Scanner:

    def __init__(self):
        self.mem    = MemoryEngine()
        self.stats  = StatsTracker()
        self.ws     = BinanceWS()
        self.buf    = defaultdict(lambda: deque(maxlen=cfg.CANDLE_LIMIT))
        self.pairs: list[str] = []
        self.known_symbols: set[str] = set()

        self._cooldown:     dict[str, float] = {}
        self._trade_no:     int = 0
        self._warned_thin:  set = set()
        self._candle_closes:int = 0

    async def start(self):
        log.info("Scanner starting…")

        # Register with health module for live stats
        health_module.set_scanner(self)

        self.pairs = await get_top_usdt_pairs(cfg.MIN_VOLUME_USDT, cfg.MAX_PAIRS)
        if not self.pairs:
            log.error("No pairs returned — check Binance REST connectivity")
            return

        log.info(f"Pairs selected ({len(self.pairs)}): "
                 f"{', '.join(self.pairs[:8])}{'…' if len(self.pairs)>8 else ''}")

        await self._seed_buffers()

        self.known_symbols = await get_all_usdt_trading_symbols()
        log.info(f"Known USDT symbols: {len(self.known_symbols)}")

        await self._send_startup()

        self.ws.on_candle_close = self._on_candle
        self.ws.on_ticker       = self._on_ticker

        await asyncio.gather(
            self.ws.run(self.pairs, cfg.SCAN_TIMEFRAMES),
            self._listing_watcher(),
            self._maintenance_loop(),
        )

    # ── Startup notification ──────────────────────────────────────

    async def _send_startup(self):
        from config import cfg as c
        tg_ok = bool(c.TELEGRAM_BOT_TOKEN and c.TELEGRAM_CHAT_ID)
        dc_ok = bool(c.DISCORD_WEBHOOK_URL)

        sep  = "━" * 30
        text = (
            f"✅ APEX-QUANT BOT ONLINE\n{sep}\n"
            f"Scanning  : {len(self.pairs)} pairs\n"
            f"Timeframes: {', '.join(cfg.SCAN_TIMEFRAMES)}\n"
            f"Min CSS   : {cfg.MIN_CSS_SCORE}\n"
            f"Top pairs : {', '.join(self.pairs[:8])}\n"
            f"{sep}\n"
            f"Signals will appear here automatically.\n"
            f"⚠️  Not financial advice  |  APEX-QUANT"
        )
        dc_payload = {"embeds": [{
            "title":       "✅ APEX-QUANT BOT ONLINE",
            "description": (
                f"Scanning **{len(self.pairs)}** pairs · "
                f"`{', '.join(cfg.SCAN_TIMEFRAMES)}`\n"
                f"Min CSS `{cfg.MIN_CSS_SCORE}` · "
                f"Min Vol `${cfg.MIN_VOLUME_USDT/1e6:.0f}M`"
            ),
            "color": 0x00FF88,
            "fields": [
                {"name": "Top Pairs",
                 "value": " · ".join(self.pairs[:10]), "inline": False},
                {"name": "Health Check",
                 "value": f"GET `/health` on port `{cfg.PORT}`", "inline": False},
            ],
            "footer": {"text": "APEX-QUANT v4.0 · Not financial advice"},
        }]}
        await broadcast(text, dc_payload)
        log.info("Startup notification sent ✓")

    # ── Candle seeding ────────────────────────────────────────────

    async def _seed_buffers(self):
        log.info(f"Seeding {len(self.pairs)}×{len(cfg.SCAN_TIMEFRAMES)} buffers…")
        await asyncio.gather(*[
            self._seed_one(p, tf)
            for p  in self.pairs
            for tf in cfg.SCAN_TIMEFRAMES
        ])
        log.info("Candle buffers seeded ✓")

    async def _seed_one(self, pair: str, tf: str):
        raw = await get_klines(pair, tf, cfg.CANDLE_LIMIT)
        for k in raw:
            self.buf[(pair, tf)].append({
                "open_time": k[0], "open": float(k[1]),
                "high": float(k[2]), "low": float(k[3]),
                "close": float(k[4]), "volume": float(k[5]),
                "close_time": k[6],
            })

    # ── WebSocket: closed candle ──────────────────────────────────

    async def _on_candle(self, symbol: str, interval: str, candle: dict):
        key = (symbol, interval)
        self.buf[key].append(candle)

        if symbol not in self.pairs:
            return

        self._candle_closes += 1
        if self._candle_closes % 200 == 0:
            st = self.stats.snapshot()
            log.info(
                f"[SCAN] {self._candle_closes} candles | "
                f"signals={self._trade_no} | "
                f"WR={st['total']['wr']}% | "
                f"PNL={st['total']['pnl_str']} | "
                f"active={len(self.mem.active_pairs())}"
            )

        buf = self.buf[key]
        min_c = getattr(cfg, "MIN_CANDLES_NEEDED", 25)
        if len(buf) < min_c:
            if key not in self._warned_thin:
                log.info(f"[SCAN] {symbol} {interval}: "
                         f"buffering ({len(buf)}/{min_c} candles)")
                self._warned_thin.add(key)
            return

        cd_key = f"{symbol}:{interval}"
        if time.time() - self._cooldown.get(cd_key, 0) < cfg.SIGNAL_COOLDOWN * 60:
            return

        klines = [
            [c["open_time"], c["open"], c["high"], c["low"],
             c["close"], c["volume"], c["close_time"], 0, 0, 0, 0, 0]
            for c in buf
        ]

        sig = generate(symbol, interval, klines, self._trade_no + 1)
        if sig is None:
            return

        # BUG FIX: evaluate AFTER direction is known from generate()
        allow, reason = self.mem.evaluate(symbol, sig["direction"])
        if not allow:
            log.info(f"[DEDUP] {symbol} {interval} {sig['direction']}: {reason}")
            return

        # EMIT
        self._trade_no        += 1
        sig["trade_no"]        = self._trade_no
        self._cooldown[cd_key] = time.time()
        self.stats.signal_emitted()
        self.mem.commit(sig)

        log.info(
            f"⚡ SIGNAL #{self._trade_no}  {symbol} {sig['direction']} "
            f"{interval}  CSS={sig['css']}  RR={sig['rrs'][-1]}  "
            f"{sig['market_label']}"
        )
        await broadcast(tg_signal(sig, self.stats), dc_signal(sig, self.stats))

    # ── WebSocket: ticker (TP/SL monitoring) ─────────────────────

    async def _on_ticker(self, tickers: list):
        active = set(self.mem.active_pairs())
        for t in tickers:
            pair  = t.get("s", "")
            price = float(t.get("c") or 0)
            if not pair or price == 0 or pair not in active:
                continue
            event = self.mem.check_price(pair, price)
            if event is None:
                continue

            if event["type"] == "SL":
                self.stats.record_loss()
            else:
                tp_idx = event.get("tp_idx", 0)
                try:
                    rr_val = float(event.get("rr", "1:1").split(":")[-1])
                except (ValueError, IndexError):
                    rr_val = 1.0
                self.stats.record_win(tp_idx, rr_val)

            icon = "🛑" if event["type"] == "SL" else "✅"
            log.info(f"{icon} {event['type']} {pair} @ {price:.6g} "
                     f"(#{event['trade_no']})")
            await broadcast(
                tg_resolution(event, self.stats),
                dc_resolution(event, self.stats),
            )

    # ── New-listing watcher ───────────────────────────────────────

    async def _listing_watcher(self):
        while True:
            await asyncio.sleep(cfg.LISTING_POLL_SECS)
            try:
                current = await get_all_usdt_trading_symbols()
                new     = current - self.known_symbols
                if new:
                    for sym in sorted(new):
                        log.info(f"🆕 New listing: {sym}")
                        self.known_symbols.add(sym)
                        await broadcast(tg_new_listing(sym), dc_new_listing(sym))
                    self.pairs = await get_top_usdt_pairs(
                        cfg.MIN_VOLUME_USDT, cfg.MAX_PAIRS)
                    self.ws.set_pairs(self.pairs, cfg.SCAN_TIMEFRAMES)
                    await self._seed_buffers()
            except Exception as exc:
                log.error(f"Listing watcher error: {exc}")

    # ── Maintenance ───────────────────────────────────────────────

    async def _maintenance_loop(self):
        while True:
            await asyncio.sleep(3600)
            self.mem.purge_old(max_age_s=7200)
            st = self.stats.snapshot()
            log.info(
                f"[HEARTBEAT] signals={st['trade_count']} | "
                f"WR={st['total']['wr']}% | "
                f"PNL={st['total']['pnl_str']} | "
                f"active={len(self.mem.active_pairs())} | "
                f"candles={self._candle_closes}"
            )
