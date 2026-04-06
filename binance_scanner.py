"""
BINANCE SCANNER  v5  —  TP-State + SL-State Signal Management
══════════════════════════════════════════════════════════════
Connects to Binance Futures !miniTicker@arr WebSocket.
Scores all T3 (≥10%) and T4 (≥20%) movers through APEX AI.

SIGNAL FIRING RULES — NO TIMERS, PURE PRICE STATE:

  Step 1 — Has this coin+tier been signalled before?
    NO  → Fire immediately  (reason: new_coin)

  Step 2 — Has the direction changed?
    YES → Fire immediately  (reason: reversal)

  Step 3 — Same direction. Are the TP/SL targets resolved?
    All 3 TPs hit → Fire immediately  (reason: all_tp_hit)
    Stop Loss hit → Fire immediately  (reason: sl_hit)
    Neither       → BLOCKED (same trade still active)

TP/SL hit tracking runs silently on EVERY tick for every coin
that has an active memory — even when the coin is below T3/T4
threshold. This ensures no hit is ever missed.
"""
import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Awaitable

import websockets

from apex_engine import ApexEngine, TickData, Signal, fmt_vol
from exchange_monitor import ExchangeMonitor
from config import (
    BINANCE_WS_URL, VOLUME_MIN_USD, HISTORY_TICKS,
    SIGNAL_HISTORY_MAX, ENABLE_PUMPS, ENABLE_DUMPS,
    RECONNECT_DELAY_SEC, MAX_RECONNECT_TRIES,
)

logger = logging.getLogger("apex.scanner")
SignalCallback = Callable[[Signal], Awaitable[None]]


# ══════════════════════════════════════════════════════════════
#  SIGNAL MEMORY — one per coin+tier
# ══════════════════════════════════════════════════════════════

@dataclass
class SignalMemory:
    """
    Complete state of the last fired signal for one coin+tier.
    Hit flags are updated on every price tick.
    """
    direction  : str    # "PUMP" | "DUMP"
    entry_low  : float
    entry_high : float
    entry_ref  : float  # midpoint of entry zone
    tp1        : float
    tp2        : float
    tp3        : float
    sl         : float

    # Milestone flags — once True they stay True
    tp1_hit : bool = False
    tp2_hit : bool = False
    tp3_hit : bool = False
    sl_hit  : bool = False

    @property
    def all_tps_hit(self) -> bool:
        return self.tp1_hit and self.tp2_hit and self.tp3_hit

    def update(self, price: float):
        """
        Called on every tick for this coin.
        Checks if price has crossed TP1/TP2/TP3/SL since the signal.
        Once a flag is True it never resets (hit = permanent).
        """
        if self.direction == "PUMP":
            if not self.tp1_hit and price >= self.tp1: self.tp1_hit = True
            if not self.tp2_hit and price >= self.tp2: self.tp2_hit = True
            if not self.tp3_hit and price >= self.tp3: self.tp3_hit = True
            if not self.sl_hit  and price <= self.sl:  self.sl_hit  = True
        else:   # DUMP / SHORT
            if not self.tp1_hit and price <= self.tp1: self.tp1_hit = True
            if not self.tp2_hit and price <= self.tp2: self.tp2_hit = True
            if not self.tp3_hit and price <= self.tp3: self.tp3_hit = True
            if not self.sl_hit  and price >= self.sl:  self.sl_hit  = True

    def status(self) -> str:
        """Human-readable state for logging."""
        return (
            f"TP1={'✓' if self.tp1_hit else '✗'}  "
            f"TP2={'✓' if self.tp2_hit else '✗'}  "
            f"TP3={'✓' if self.tp3_hit else '✗'}  "
            f"SL={'✓'  if self.sl_hit  else '✗'}"
        )


# ══════════════════════════════════════════════════════════════
#  SCANNER
# ══════════════════════════════════════════════════════════════

class BinanceScanner:

    def __init__(self):
        self.engine  = ApexEngine()
        self.monitor = ExchangeMonitor()

        # Tick history per symbol (for MOM scoring)
        self.history: dict[str, deque[TickData]] = defaultdict(
            lambda: deque(maxlen=HISTORY_TICKS)
        )

        # Signal memory: "BTCUSDT_T4" → SignalMemory
        self._memory: dict[str, SignalMemory] = {}

        # Symbols seen for the first time (internal [NEW] tag only)
        self._new_syms: set[str] = set()

        # Signal delivery callbacks (Telegram + Discord)
        self._sig_cbs: list[SignalCallback] = []

        self.signal_history: deque[Signal] = deque(maxlen=SIGNAL_HISTORY_MAX)
        self._running = False

        self.stats: dict = {
            "pairs_live"       : 0,
            "frames_total"     : 0,
            "t3_raw"           : 0,
            "t4_raw"           : 0,
            "t3_fired"         : 0,
            "t4_fired"         : 0,
            "t3_rejected"      : 0,
            "t4_rejected"      : 0,
            "all_tp_reentries" : 0,
            "sl_reentries"     : 0,
            "reversals"        : 0,
            "new_listings_seen": 0,
            "ws_reconnects"    : 0,
            "last_signal_ts"   : None,
            "connected_at"     : None,
        }

    # ── Public API ────────────────────────────────────────────

    def add_signal_callback(self, cb: SignalCallback):
        self._sig_cbs.append(cb)

    def add_new_listing_callback(self, cb):
        pass   # external alerts disabled

    async def run(self):
        self._running = True
        await asyncio.gather(self.monitor.run(), self._ws_loop())

    def stop(self):
        self._running = False
        self.monitor.stop()

    # ── Signal decision (no timers) ───────────────────────────

    def _decide(self, sym: str, tier: str,
                direction: str, price: float) -> tuple[bool, str]:
        """
        Core logic. Returns (should_fire, reason).

        reason values:
          "new_coin"   — first ever signal for this coin+tier
          "reversal"   — direction has flipped since last signal
          "all_tp_hit" — all 3 TPs achieved → clean re-entry
          "sl_hit"     — stop loss was hit   → fresh setup
          "blocked"    — same direction, position still active
        """
        key = f"{sym}_{tier}"
        mem = self._memory.get(key)

        # ── Never signalled before ────────────────────────────
        if mem is None:
            return True, "new_coin"

        # ── Direction reversed ────────────────────────────────
        if direction != mem.direction:
            return True, "reversal"

        # ── Same direction — position must be fully resolved ──
        if mem.all_tps_hit:
            return True, "all_tp_hit"

        if mem.sl_hit:
            return True, "sl_hit"

        # ── Still active — block ──────────────────────────────
        return False, "blocked"

    def _save(self, sym: str, tier: str, sig: Signal):
        """Store signal targets in memory after firing."""
        tr  = sig.trade
        ref = (tr.entry_low + tr.entry_high) / 2
        self._memory[f"{sym}_{tier}"] = SignalMemory(
            direction  = sig.direction,
            entry_low  = tr.entry_low,
            entry_high = tr.entry_high,
            entry_ref  = ref,
            tp1        = tr.tp1,
            tp2        = tr.tp2,
            tp3        = tr.tp3,
            sl         = tr.sl,
        )

    # ── WebSocket reconnect loop ──────────────────────────────

    async def _ws_loop(self):
        tries = 0
        while self._running and tries < MAX_RECONNECT_TRIES:
            try:
                logger.info(f"WS connecting (attempt {tries + 1})...")
                await self._stream()
                tries = 0
            except Exception as exc:
                tries += 1
                self.stats["ws_reconnects"] += 1
                logger.warning(
                    f"WS error: {exc!r}  —  "
                    f"reconnect #{self.stats['ws_reconnects']} "
                    f"in {RECONNECT_DELAY_SEC}s"
                )
                await asyncio.sleep(RECONNECT_DELAY_SEC)

    async def _stream(self):
        async with websockets.connect(
            BINANCE_WS_URL,
            ping_interval = 20,
            ping_timeout  = 30,
            close_timeout = 10,
            max_size      = 10 * 1024 * 1024,
        ) as ws:
            self.stats["connected_at"] = time.time()
            logger.info("WebSocket connected — Binance Futures !miniTicker@arr")
            async for raw in ws:
                if not self._running:
                    break
                try:
                    await self._process_frame(json.loads(raw))
                except json.JSONDecodeError:
                    pass
                except Exception as exc:
                    logger.debug(f"Frame error: {exc!r}")

    # ── Frame processing ──────────────────────────────────────

    async def _process_frame(self, data):
        if not isinstance(data, list):
            return

        self.stats["frames_total"] += 1
        valid      : list[TickData] = []
        frame_syms : set[str]       = set()

        # ── Parse every miniTicker ─────────────────────────────
        for item in data:
            sym = item.get("s", "")
            if not sym.endswith("USDT"):
                continue
            try:
                price  = float(item["c"])
                open24 = float(item["o"])
                high   = float(item["h"])
                low    = float(item.get("l") or price * 0.99)
                vol    = float(item.get("q", 0) or item.get("v", 0))
            except (KeyError, ValueError, TypeError):
                continue

            if price <= 0 or vol < VOLUME_MIN_USD:
                continue

            pct  = (price - open24) / open24 * 100 if open24 > 0 else 0.0
            tick = TickData(sym, price, open24, high, low, vol, pct, time.time())
            valid.append(tick)
            frame_syms.add(sym)
            self.history[sym].append(tick)

            # ── Silent TP/SL tracking for ALL active memories ──
            # Runs on every coin every frame — ensures no hit is missed
            for tier_key in ("T3", "T4"):
                key = f"{sym}_{tier_key}"
                mem = self._memory.get(key)
                if mem is None:
                    continue

                was_all_tp = mem.all_tps_hit
                was_sl     = mem.sl_hit
                mem.update(price)

                if not was_all_tp and mem.all_tps_hit:
                    logger.info(
                        f"ALL TPs HIT  {sym} {tier_key}  "
                        f"{mem.direction}  entry={mem.entry_ref:.6g}  "
                        f"→ re-entry unlocked on next qualifying signal"
                    )
                elif not was_sl and mem.sl_hit:
                    logger.info(
                        f"STOP LOSS HIT  {sym} {tier_key}  "
                        f"{mem.direction}  sl={mem.sl:.6g}  "
                        f"[{mem.status()}]  "
                        f"→ re-entry unlocked on next qualifying signal"
                    )

        self.stats["pairs_live"] = len(valid)

        # ── Exchange monitor (new listing tracking) ────────────
        if frame_syms:
            first_time = self.monitor.update_from_ws(frame_syms)
            if first_time:
                self._new_syms.update(first_time)
                self.stats["new_listings_seen"] += len(first_time)

        self.engine.update_universe(valid)

        # ── Score T3/T4 movers ────────────────────────────────
        for tick in valid:
            abs_pct   = abs(tick.pct)
            tier      = self.engine.classify_tier(abs_pct)
            if not tier:
                continue

            direction = "PUMP" if tick.pct > 0 else "DUMP"
            if direction == "PUMP" and not ENABLE_PUMPS: continue
            if direction == "DUMP" and not ENABLE_DUMPS: continue

            if tier == "T3": self.stats["t3_raw"] += 1
            else:             self.stats["t4_raw"] += 1

            # ── APEX scoring ───────────────────────────────────
            hist   = list(self.history[tick.symbol])[:-1]
            layers = self.engine.score(tick, hist)

            if not layers.all_gates:
                if tier == "T3": self.stats["t3_rejected"] += 1
                else:             self.stats["t4_rejected"] += 1
                logger.debug(
                    f"REJECT  {tick.symbol:12s} {tier}  "
                    f"APEX={layers.APEX}  fail=[{layers.failed_gate}]  "
                    f"MOVE={layers.FMT}  VOL={layers.LVI}  MOM={layers.WAS}  "
                    f"pct={tick.pct:+.2f}%"
                )
                continue

            # ── TP-state + SL-state decision (NO timers) ───────
            should_fire, reason = self._decide(
                tick.symbol, tier, direction, tick.price
            )

            if not should_fire:
                continue

            # ── Fire ───────────────────────────────────────────
            is_new = tick.symbol in self._new_syms
            signal = self.engine.build_signal(
                tick, layers,
                is_new_listing = is_new,
                signal_reason  = reason,
            )

            # Save memory immediately after firing
            self._save(tick.symbol, tier, signal)

            self.stats["last_signal_ts"] = time.time()
            if tier == "T3": self.stats["t3_fired"] += 1
            else:             self.stats["t4_fired"] += 1

            if reason == "all_tp_hit": self.stats["all_tp_reentries"] += 1
            elif reason == "sl_hit":   self.stats["sl_reentries"]     += 1
            elif reason == "reversal": self.stats["reversals"]         += 1

            self.signal_history.appendleft(signal)

            REASON_LOG = {
                "new_coin"  : "",
                "reversal"  : "[🔄 REVERSAL] ",
                "all_tp_hit": "[🎯 ALL TP → RE-ENTRY] ",
                "sl_hit"    : "[🛑 SL HIT → RE-ENTRY] ",
            }
            logger.info(
                f"{'[NEW] ' if is_new else ''}"
                f"{REASON_LOG.get(reason, '')}"
                f"SIGNAL {signal.coin():10s} {tier} {direction}  "
                f"{tick.pct:+.2f}%  APEX={layers.APEX}  "
                f"(MOVE={layers.FMT} VOL={layers.LVI} MOM={layers.WAS})  "
                f"Vol={fmt_vol(tick.vol_usd)}  "
                f"→ {signal.trade.style.upper()} {signal.trade.position}  "
                f"x{signal.trade.leverage}  R:R 1:{signal.trade.rr:.1f}"
            )

            results = await asyncio.gather(
                *[cb(signal) for cb in self._sig_cbs],
                return_exceptions=True,
            )
            for exc in results:
                if isinstance(exc, Exception):
                    logger.warning(f"Signal callback error: {exc!r}")
