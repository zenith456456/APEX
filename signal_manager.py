# ─── signal_manager.py ─────────────────────────────────────────────────────
# APEX Signal Bot — Orchestration Layer
# Wires together: Scanner → MTCS Engine → Dedup Memory → Stats → Broadcaster

import asyncio
import logging
from typing import Optional

from engines import MTCSEngine
from apex_signal_memory import SignalMemoryEngine
from stats_engine import StatsEngine

logger = logging.getLogger("APEX.Manager")


class SignalManager:
    """
    Central coordinator. Registered as the on_signal_ready callback
    for BinanceScanner. Runs the full pipeline on every closed candle.
    """

    def __init__(self, config, broadcaster):
        self.cfg          = config
        self.broadcaster  = broadcaster
        self.mtcs_engine  = MTCSEngine(config)
        self.memory       = SignalMemoryEngine(base_risk=config.BASE_RISK_PCT)
        self.stats_engine = StatsEngine()
        self._lock        = asyncio.Lock()
        self._eval_count  = 0

    # ── Called by BinanceScanner on every closed candle ────────────────────
    async def on_signal_ready(self, pair: str, tf: str, store):
        """Triggered on every closed candle for any monitored pair/TF."""
        async with self._lock:
            self._eval_count += 1

            # 1) Update price-based TP/SL tracking for ALL active signals
            candles = store.get_candles(pair, tf, n=1)
            if candles:
                last_price = candles[-1]["c"]
                self.memory.on_price_update(pair, last_price)

            # 2) Only run full MTCS evaluation on the higher-weight TFs
            #    to reduce compute load (still scans every closed candle)
            if tf not in ("1m", "3m", "5m", "15m"):
                return

            try:
                signal = self.mtcs_engine.evaluate(pair, store)
            except Exception as e:
                logger.error(f"MTCS evaluate error {pair} {tf}: {e}")
                return

            if not signal:
                return

            # 3) Run through deduplication engine
            result = self.memory.evaluate(signal)

            if result["action"] != "EMIT":
                logger.debug(f"BLOCK {pair}: {result.get('message','')}")
                return

            # 4) Compute live stats snapshot
            stats = self.stats_engine.snapshot(self.memory.all_states)

            # 5) Broadcast
            state = result["state"]
            await self.broadcaster.send_signal(state, stats, reason=result["reason"])

    # ── Periodic heartbeat / health log ─────────────────────────────────────
    async def heartbeat_loop(self, interval_sec: int = 300):
        while True:
            await asyncio.sleep(interval_sec)
            active = self.memory.active_count
            total  = len(self.memory.all_states)
            logger.info(
                f"❤️ Heartbeat | evals={self._eval_count} | "
                f"active_signals={active} | total_signals={total}"
            )
