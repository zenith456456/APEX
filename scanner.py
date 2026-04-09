"""
APEX-EDS v4.0 | scanner.py
24x7 scan loop with SignalMemory deduplication.
"""

import asyncio
import logging
import time
from typing import Callable, Coroutine, List, Optional

import config
from apex_engine import APEXEngine
from exchange_monitor import ExchangeMonitor
from models import SignalResult, TradeState
from signal_memory import SignalMemory

logger = logging.getLogger("Scanner")


class Scanner:
    def __init__(self, monitor: ExchangeMonitor):
        self._monitor  = monitor
        self._engine   = APEXEngine()
        self._memory   = SignalMemory()
        self._hour_ts: List[float] = []
        self._running  = False
        self._cbs:     List[Callable] = []

    def on_signal(self, cb: Callable[[SignalResult], Coroutine]):
        self._cbs.append(cb)

    @property
    def memory(self) -> SignalMemory:
        return self._memory

    async def start(self):
        self._running = True
        logger.info("Scanner: starting 24x7 loop")
        asyncio.create_task(self._scan_loop())
        asyncio.create_task(self._price_feed())
        asyncio.create_task(self._cleanup_loop())

    async def stop(self):
        self._running = False

    # ── SCAN ──────────────────────────────────────────────────────────────

    async def _scan_loop(self):
        while self._running:
            t0 = time.time()
            try:
                await self._scan_all()
            except Exception as e:
                logger.error(f"Scan error: {e}", exc_info=True)
            elapsed = time.time() - t0
            await asyncio.sleep(max(0.0, config.SCAN_INTERVAL_SEC - elapsed))

    async def _scan_all(self):
        symbols = self._monitor.get_all_symbols()
        now     = time.time()
        self._hour_ts = [t for t in self._hour_ts if now - t < 3600]

        if len(self._hour_ts) >= config.MAX_SIGNALS_PER_HOUR:
            return

        fired = 0
        for sym in symbols:
            if not self._running:
                break

            sd = self._monitor.get_symbol_data(sym)
            if sd is None:
                continue

            try:
                result: Optional[SignalResult] = self._engine.score(sd)
            except Exception as e:
                logger.debug(f"Score {sym}: {e}")
                continue

            if result is None:
                continue

            decision = self._memory.check(result)
            if not decision.allow:
                logger.debug(f"BLOCKED [{sym}]: {decision.reason}")
                continue

            # ── APPROVED ───────────────────────────────────────────────
            logger.info(
                f"★ SIGNAL [{decision.reason[:55]}] "
                f"{result.symbol} {result.direction.value} "
                f"Score={result.score.total:.1f} RR={result.rr_ratio:.2f} "
                f"Regime={result.regime.value}"
            )
            self._memory.record(result, prev=decision.prev)
            self._hour_ts.append(now)
            fired += 1

            for cb in self._cbs:
                try:
                    await cb(result)
                except Exception as e:
                    logger.error(f"Callback: {e}")

            await asyncio.sleep(0.01)

            if len(self._hour_ts) >= config.MAX_SIGNALS_PER_HOUR:
                break

        if fired:
            logger.info(f"Scan done — {fired} signal(s)")

    # ── PRICE FEED (keeps TP/SL state fresh between scans) ────────────────

    async def _price_feed(self):
        while self._running:
            try:
                watch = {
                    sym for sym, m in self._memory.get_all().items()
                    if m.state not in (TradeState.ALL_TP_HIT,
                                       TradeState.SL_HIT,
                                       TradeState.CLOSED)
                }
                for sym in watch:
                    sd = self._monitor.get_symbol_data(sym)
                    if sd and sd.last_price > 0:
                        self._memory.update_price(sym, sd.last_price)
            except Exception as e:
                logger.error(f"Price feed: {e}")
            await asyncio.sleep(1.0)

    # ── CLEANUP ───────────────────────────────────────────────────────────

    async def _cleanup_loop(self):
        while self._running:
            await asyncio.sleep(21_600)   # every 6 h
            self._memory.cleanup(max_age_hours=12)
            logger.info(
                f"Memory cleanup — {self._memory.active_count()} active signals"
            )
