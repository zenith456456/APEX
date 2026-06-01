"""
scanner.py — APEX-QUANT core scanner

STATS FIX:
  Uses memory_engine resolution types to record stats EXACTLY ONCE per signal:
    TP_PARTIAL   → no stats recorded (signal still active)
    TP_FINAL     → record_win(highest_tp_idx)   [all TPs done]
    SL_CLEAN     → record_loss()                [SL, no prior TP]
    SL_AFTER_TP  → record_win(highest_tp_idx)   [SL after partial TP]

  Invariant enforced: wins + losses == resolved signals <= trade_count
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
        self.mem     = MemoryEngine()
        self.stats   = StatsTracker()
        self.ws      = BinanceWS()
        self.buf     = defaultdict(lambda: deque(maxlen=cfg.CANDLE_LIMIT))
        self.pairs:  list[str] = []
        self.known_symbols: set[str] = set()

        self._cooldown:      dict[str, float] = {}
        self._trade_no:      int = 0
        self._warned_thin:   set = set()
        self._candle_closes: int = 0

    # ── Boot ──────────────────────────────────────────────────────

    async def start(self):
        log.info("Scanner starting…")
        health_module.set_scanner(self)

        self.pairs = await get_top_usdt_pairs(cfg.MIN_VOLUME_USDT, cfg.MAX_PAIRS)
        if not self.pairs:
            log.error("No pairs returned — check Binance REST")
            return

        log.info(
            f"Pairs: {len(self.pairs)} selected "
            f"(min vol ${cfg.MIN_VOLUME_USDT/1e6:.1f}M)\n"
            f"  {', '.join(self.pairs[:15])}{'…' if len(self.pairs)>15 else ''}"
        )

        await self._seed_buffers()
        self.known_symbols = await get_all_usdt_trading_symbols()
        log.info(f"Known symbols: {len(self.known_symbols)}")

        await self._send_startup()

        self.ws.on_candle_close = self._on_candle
        self.ws.on_ticker       = self._on_ticker

        await asyncio.gather(
            self.ws.run(self.pairs, cfg.SCAN_TIMEFRAMES),
            self._listing_watcher(),
            self._maintenance_loop(),
        )

    # ── Startup message ───────────────────────────────────────────

    async def _send_startup(self):
        sep  = "━" * 30
        text = (
            f"✅ APEX-QUANT BOT ONLINE\n{sep}\n"
            f"Scanning  : {len(self.pairs)} pairs\n"
            f"Timeframes: {', '.join(cfg.SCAN_TIMEFRAMES)}\n"
            f"Min CSS   : {cfg.MIN_CSS_SCORE}\n"
            f"Min Vol   : ${cfg.MIN_VOLUME_USDT/1e6:.1f}M\n"
            f"Top pairs : {', '.join(self.pairs[:10])}\n"
            f"{sep}\n"
            f"Signals appear here automatically.\n"
            f"⚠️  Not financial advice  |  APEX-QUANT"
        )
        dc_payload = {"embeds": [{
            "title":       "✅ APEX-QUANT BOT ONLINE",
            "description": (
                f"Scanning **{len(self.pairs)}** pairs · "
                f"`{', '.join(cfg.SCAN_TIMEFRAMES)}`\n"
                f"Min CSS `{cfg.MIN_CSS_SCORE}` · "
                f"Min Vol `${cfg.MIN_VOLUME_USDT/1e6:.1f}M`"
            ),
            "color": 0x00FF88,
            "fields": [{"name": "Top Pairs",
                        "value": " · ".join(self.pairs[:12]), "inline": False}],
            "footer": {"text": "APEX-QUANT v4.0 · Not financial advice"},
        }]}
        await broadcast(text, dc_payload)
        log.info("Startup notification sent ✓")

    # ── Candle buffer seeding (parallel batches) ──────────────────

    async def _seed_buffers(self):
        tasks = [
            self._seed_one(p, tf)
            for p  in self.pairs
            for tf in cfg.SCAN_TIMEFRAMES
        ]
        # Run in batches to avoid hammering the REST API
        w = getattr(cfg, "BATCH_KLINE_WORKERS", 20)
        for i in range(0, len(tasks), w):
            await asyncio.gather(*tasks[i:i+w])
            if i + w < len(tasks):
                await asyncio.sleep(0.1)   # tiny pause between batches
        log.info(
            f"Candle buffers seeded: "
            f"{len(self.pairs)} pairs × {len(cfg.SCAN_TIMEFRAMES)} timeframes"
        )

    async def _seed_one(self, pair: str, tf: str):
        raw = await get_klines(pair, tf, cfg.CANDLE_LIMIT)
        for k in raw:
            self.buf[(pair, tf)].append({
                "open_time": k[0], "open": float(k[1]),
                "high": float(k[2]), "low": float(k[3]),
                "close": float(k[4]), "volume": float(k[5]),
                "close_time": k[6],
            })

    # ── WebSocket: closed candle → signal generation ──────────────

    async def _on_candle(self, symbol: str, interval: str, candle: dict):
        key = (symbol, interval)
        self.buf[key].append(candle)

        if symbol not in self.pairs:
            return

        self._candle_closes += 1
        if self._candle_closes % 500 == 0:
            st = self.stats.snapshot()
            log.info(
                f"[SCAN] candles={self._candle_closes} | "
                f"signals={self._trade_no} | "
                f"resolved={st['resolved']} | "
                f"pending={st['pending']} | "
                f"WR={st['total']['wr']}% | "
                f"PNL={st['total']['pnl_str']}"
            )

        buf = self.buf[key]
        if len(buf) < cfg.MIN_CANDLES_NEEDED:
            if key not in self._warned_thin:
                log.info(f"[SCAN] {symbol} {interval}: "
                         f"buffering ({len(buf)}/{cfg.MIN_CANDLES_NEEDED})")
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

        # Dedup check AFTER direction is known
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

    # ── WebSocket: ticker → TP/SL resolution ─────────────────────

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

            etype = event["type"]

            # ── TP_PARTIAL: no stats change, just notify ──────────
            if etype == "TP_PARTIAL":
                tp_n  = event["tp_num"]
                done  = event["tps_done"]
                total = event["tps_total"]
                log.info(f"📈 TP{tp_n} {pair} @ {price:.6g} "
                         f"({done}/{total} TPs done — signal still active)")
                tg_txt = (
                    f"📈 TP{tp_n} HIT (partial)  #{event['trade_no']}\n"
                    f"  {pair} @ {price:.6g}  ({event['rr']})\n"
                    f"  Progress: {done}/{total} TPs done — position still open\n"
                    f"⚠️  Not financial advice  |  APEX-QUANT"
                )
                dc_pay = {"embeds": [{
                    "title":       f"📈 TP{tp_n} HIT (partial) #{event['trade_no']}",
                    "description": (
                        f"**{pair}** @ `{price:.6g}`\n"
                        f"R:R `{event['rr']}`\n"
                        f"Progress: **{done}/{total}** TPs done — still active"
                    ),
                    "color": 0x00AAFF,
                    "footer": {"text": "APEX-QUANT · Not financial advice"},
                }]}
                await broadcast(tg_txt, dc_pay)
                continue   # ← NO stats recording for partial hits

            # ── TP_FINAL: all TPs hit → record WIN once ───────────
            elif etype == "TP_FINAL":
                self.stats.record_win(event["tp_idx"], event["rr_val"])
                log.info(f"🏆 TP_FINAL {pair} #{event['trade_no']} "
                         f"+{event['rr_val']}R")
                await broadcast(
                    tg_resolution(event, self.stats),
                    dc_resolution(event, self.stats),
                )

            # ── SL_CLEAN: loss — no TP was ever hit ──────────────
            elif etype == "SL_CLEAN":
                self.stats.record_loss()
                log.info(f"🛑 SL_CLEAN {pair} #{event['trade_no']} −1R")
                await broadcast(
                    tg_resolution(event, self.stats),
                    dc_resolution(event, self.stats),
                )

            # ── SL_AFTER_TP: SL hit but TP was reached before ────
            elif etype == "SL_AFTER_TP":
                self.stats.record_win(event["tp_idx"], event["rr_val"])
                log.info(f"✅ SL_AFTER_TP {pair} #{event['trade_no']} "
                         f"WIN at TP{event['tp_idx']+1} +{event['rr_val']}R")
                # Custom message for this case
                tg_txt = (
                    f"✅ WIN (SL hit after TP{event['tp_idx']+1})  "
                    f"#{event['trade_no']}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"  {pair} — highest TP: TP{event['tp_idx']+1} ({event['rr']})\n"
                    f"  SL hit @ {price:.6g} (after partial win)\n"
                    f"  PNL: +{event['rr_val']}R\n"
                    f"⚠️  Not financial advice  |  APEX-QUANT"
                )
                dc_pay = {"embeds": [{
                    "title":       f"✅ WIN #{event['trade_no']} (SL after TP{event['tp_idx']+1})",
                    "description": (
                        f"**{pair}** — TP{event['tp_idx']+1} was hit, then SL.\n"
                        f"Best R:R achieved: `{event['rr']}`\n"
                        f"PNL: `+{event['rr_val']}R`"
                    ),
                    "color": 0x00FF88,
                    "footer": {"text": "APEX-QUANT · Not financial advice"},
                }]}
                await broadcast(tg_txt, dc_pay)

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
                    log.info(f"Subscription updated: {len(self.pairs)} pairs")
            except Exception as exc:
                log.error(f"Listing watcher: {exc}")

    # ── Maintenance ───────────────────────────────────────────────

    async def _maintenance_loop(self):
        while True:
            await asyncio.sleep(3600)
            self.mem.purge_old(max_age_s=7200)
            st = self.stats.snapshot()
            log.info(
                f"[HEARTBEAT] signals={st['trade_count']} | "
                f"resolved={st['resolved']} | pending={st['pending']} | "
                f"WR={st['total']['wr']}% | PNL={st['total']['pnl_str']} | "
                f"active_pairs={len(self.mem.active_pairs())} | "
                f"candles={self._candle_closes}"
            )
