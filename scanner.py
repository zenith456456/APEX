"""
scanner.py ─ APEX-QUANT core scanner

BUG FIXES in this version:
  1. REMOVED the incorrect first evaluate("LONG") call before direction
     is known — this was blocking all SHORT signals when a LONG was active.
  2. Added per-candle INFO log so Northflank shows real-time scanning.
  3. Added startup test message to Telegram + Discord so you can verify
     the bot is connected before any signals fire.
  4. MIN_CANDLES_NEEDED reduced to 25 (was 30).
  5. Candle buffer now tracked so we can log "waiting for candles" once.
"""
import asyncio
import time
from collections import defaultdict, deque
from typing import Optional

from config import cfg
from logger_setup import get_logger
from binance_rest import get_top_usdt_pairs, get_klines, get_all_usdt_trading_symbols
from binance_ws   import BinanceWS
from signal_engine import generate
from memory_engine import MemoryEngine
from stats_tracker import StatsTracker
from formatter import (tg_signal, tg_resolution, tg_new_listing,
                       dc_signal, dc_resolution, dc_new_listing)
from notifier import broadcast, send_telegram, send_discord

log = get_logger("scanner")


class Scanner:

    def __init__(self):
        self.mem:    MemoryEngine = MemoryEngine()
        self.stats:  StatsTracker = StatsTracker()
        self.ws:     BinanceWS   = BinanceWS()
        # (pair, tf) → deque[dict]
        self.buf:    dict         = defaultdict(lambda: deque(maxlen=cfg.CANDLE_LIMIT))
        self.pairs:  list[str]   = []
        self.known_symbols: set[str] = set()

        # pair:tf → last signal unix timestamp
        self._cooldown: dict[str, float] = {}
        self._trade_no: int = 0

        # Track pairs that haven't logged "waiting for candles" yet
        self._warned_thin: set = set()

        # Candle close counter (for periodic status log)
        self._candle_closes: int = 0

    # ── Boot ──────────────────────────────────────────────────────

    async def start(self):
        log.info("APEX-QUANT scanner starting…")

        # 1. Select top pairs by 24h USDT volume
        self.pairs = await get_top_usdt_pairs(cfg.MIN_VOLUME_USDT, cfg.MAX_PAIRS)
        if not self.pairs:
            log.error("No pairs returned — check REST connectivity")
            return
        log.info(f"Tracking pairs: {', '.join(self.pairs[:10])}{'…' if len(self.pairs)>10 else ''}")

        # 2. Seed candle buffers via REST
        await self._seed_buffers()

        # 3. Record known symbols for new-listing detection
        self.known_symbols = await get_all_usdt_trading_symbols()
        log.info(f"Known USDT symbols: {len(self.known_symbols)}")

        # 4. Send startup notification so we know the bot is live
        await self._send_startup()

        # 5. Wire WebSocket callbacks
        self.ws.on_candle_close = self._on_candle
        self.ws.on_ticker       = self._on_ticker

        # 6. Launch all long-running tasks
        await asyncio.gather(
            self.ws.run(self.pairs, cfg.SCAN_TIMEFRAMES),
            self._listing_watcher(),
            self._maintenance_loop(),
        )

    # ── Startup message ───────────────────────────────────────────

    async def _send_startup(self):
        sep  = "━" * 30
        text = (
            f"✅ APEX-QUANT BOT ONLINE\n"
            f"{sep}\n"
            f"Scanning  : {len(self.pairs)} pairs\n"
            f"Timeframes: {', '.join(cfg.SCAN_TIMEFRAMES)}\n"
            f"Min CSS   : {cfg.MIN_CSS_SCORE}\n"
            f"Min Vol   : ${cfg.MIN_VOLUME_USDT:,.0f}\n"
            f"Top pairs : {', '.join(self.pairs[:8])}\n"
            f"{sep}\n"
            f"Signals will appear here automatically.\n"
            f"⚠️  Not financial advice  |  APEX-QUANT"
        )
        dc_payload = {"embeds": [{
            "title":       "✅ APEX-QUANT BOT ONLINE",
            "description": (
                f"**Scanning** {len(self.pairs)} pairs · "
                f"`{', '.join(cfg.SCAN_TIMEFRAMES)}`\n"
                f"**Min CSS** `{cfg.MIN_CSS_SCORE}` · "
                f"**Min Vol** `${cfg.MIN_VOLUME_USDT/1e6:.0f}M`"
            ),
            "color": 0x00FF88,
            "fields": [{"name": "Top Pairs",
                         "value": " · ".join(self.pairs[:10])}],
            "footer": {"text": "APEX-QUANT · Not financial advice"},
        }]}
        await broadcast(text, dc_payload)
        log.info("Startup notification sent ✓")

    # ── Candle seed (REST) ────────────────────────────────────────

    async def _seed_buffers(self):
        log.info(f"Seeding {len(self.pairs)}×{len(cfg.SCAN_TIMEFRAMES)} candle buffers…")
        await asyncio.gather(*[
            self._seed_one(pair, tf)
            for pair in self.pairs
            for tf   in cfg.SCAN_TIMEFRAMES
        ])
        log.info("Candle buffers seeded ✓")

    async def _seed_one(self, pair: str, tf: str):
        raw = await get_klines(pair, tf, cfg.CANDLE_LIMIT)
        for k in raw:
            self.buf[(pair, tf)].append({
                "open_time":  k[0],
                "open":       float(k[1]),
                "high":       float(k[2]),
                "low":        float(k[3]),
                "close":      float(k[4]),
                "volume":     float(k[5]),
                "close_time": k[6],
            })

    # ── WebSocket: closed candle ──────────────────────────────────

    async def _on_candle(self, symbol: str, interval: str, candle: dict):
        """
        Called by BinanceWS on every CLOSED candle.
        This is where signal generation happens.
        """
        key = (symbol, interval)
        self.buf[key].append(candle)

        # Only process pairs we track
        if symbol not in self.pairs:
            return

        self._candle_closes += 1

        # Log a heartbeat every 100 closed candles
        if self._candle_closes % 100 == 0:
            log.info(f"[SCAN] {self._candle_closes} candles processed | "
                     f"signals emitted: {self._trade_no} | "
                     f"active pairs: {len(self.mem.active_pairs())}")

        buf = self.buf[key]

        # Need minimum candles for indicators to be reliable
        min_needed = getattr(cfg, "MIN_CANDLES_NEEDED", 25)
        if len(buf) < min_needed:
            if key not in self._warned_thin:
                log.info(f"[SCAN] {symbol} {interval}: waiting for candles "
                         f"({len(buf)}/{min_needed})")
                self._warned_thin.add(key)
            return

        # Per-pair-tf cooldown check
        cd_key = f"{symbol}:{interval}"
        last   = self._cooldown.get(cd_key, 0)
        if time.time() - last < cfg.SIGNAL_COOLDOWN * 60:
            return

        # Build kline list for signal engine
        klines = [
            [c["open_time"], c["open"], c["high"], c["low"],
             c["close"], c["volume"], c["close_time"], 0, 0, 0, 0, 0]
            for c in buf
        ]

        # ── Generate signal (includes all indicator + filter logic) ──
        sig = generate(symbol, interval, klines, self._trade_no + 1)
        if sig is None:
            return  # filter rejections already logged inside generate()

        # ── BUG FIX: evaluate AFTER direction is known ────────────
        # Old code incorrectly pre-evaluated with hardcoded "LONG"
        # which blocked all SHORT signals when a LONG was in memory.
        allow, reason = self.mem.evaluate(symbol, sig["direction"])
        if not allow:
            log.info(f"[DEDUP] {symbol} {interval} {sig['direction']} blocked: {reason}")
            return

        # ── EMIT ──────────────────────────────────────────────────
        self._trade_no         += 1
        sig["trade_no"]         = self._trade_no
        self._cooldown[cd_key]  = time.time()
        self.stats.signal_emitted()
        self.mem.commit(sig)

        log.info(
            f"⚡ SIGNAL #{self._trade_no}  {symbol} {sig['direction']} {interval}  "
            f"CSS={sig['css']}  RR={sig['rrs'][-1]}  {sig['market_label']}"
        )

        await broadcast(
            tg_signal(sig, self.stats),
            dc_signal(sig, self.stats),
        )

    # ── WebSocket: ticker (TP/SL monitoring) ─────────────────────

    async def _on_ticker(self, tickers: list):
        """
        Called on every miniTicker update.
        Used solely for TP/SL auto-resolution.
        """
        active = set(self.mem.active_pairs())
        for t in tickers:
            pair  = t.get("s", "")
            price = float(t.get("c") or 0)
            if not pair or price == 0 or pair not in active:
                continue

            event = self.mem.check_price(pair, price)
            if event is None:
                continue

            # ── Record result in stats ────────────────────────────
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
                     f"(trade #{event['trade_no']})")

            await broadcast(
                tg_resolution(event, self.stats),
                dc_resolution(event, self.stats),
            )

    # ── New-listing watcher ───────────────────────────────────────

    async def _listing_watcher(self):
        """Polls exchangeInfo every LISTING_POLL_SECS; detects new coins."""
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

                    # Refresh pair list and re-subscribe WebSocket
                    self.pairs = await get_top_usdt_pairs(
                        cfg.MIN_VOLUME_USDT, cfg.MAX_PAIRS)
                    self.ws.set_pairs(self.pairs, cfg.SCAN_TIMEFRAMES)
                    await self._seed_buffers()
                    log.info(f"Subscription updated: {len(self.pairs)} pairs")
            except Exception as exc:
                log.error(f"Listing watcher error: {exc}")

    # ── Maintenance ───────────────────────────────────────────────

    async def _maintenance_loop(self):
        """Hourly housekeeping: purge stale memory + log stats."""
        while True:
            await asyncio.sleep(3600)
            self.mem.purge_old(max_age_s=7200)
            st = self.stats.snapshot()
            log.info(
                f"[HEARTBEAT] Signals={st['trade_count']} | "
                f"WR={st['total']['wr']}% | "
                f"PNL={st['total']['pnl_str']} | "
                f"Active={len(self.mem.active_pairs())} pairs | "
                f"Candles={self._candle_closes}"
            )
