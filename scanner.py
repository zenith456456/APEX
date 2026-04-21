"""APEX-EDS v4.0 | scanner.py — 24x7 scan loop with memory + stats."""
import asyncio, logging, time
from typing import Callable, Coroutine, List, Optional
import config
from apex_engine import APEXEngine
from exchange_monitor import ExchangeMonitor
from models import SignalResult, TradeState
from signal_memory import SignalMemory
from stats_tracker import StatsTracker
logger = logging.getLogger("Scanner")

class Scanner:
    def __init__(self, monitor: ExchangeMonitor):
        self._monitor=monitor; self._engine=APEXEngine()
        self._memory=SignalMemory(); self._stats=StatsTracker()
        self._hour_ts: List[float]=[]; self._running=False; self._cbs: List[Callable]=[]

    def on_signal(self, cb: Callable[[SignalResult, dict], Coroutine]):
        self._cbs.append(cb)

    @property
    def memory(self): return self._memory

    @property
    def stats(self): return self._stats

    async def start(self):
        self._running=True; logger.info("Scanner: 24x7 loop starting")
        asyncio.create_task(self._scan_loop())
        asyncio.create_task(self._price_feed())
        asyncio.create_task(self._cleanup_loop())

    async def stop(self): self._running=False

    async def _scan_loop(self):
        while self._running:
            t0=time.time()
            try: await self._scan_all()
            except Exception as e: logger.error(f"Scan: {e}", exc_info=True)
            await asyncio.sleep(max(0.0, config.SCAN_INTERVAL_SEC-(time.time()-t0)))

    async def _scan_all(self):
        symbols=self._monitor.get_all_symbols(); now=time.time()
        self._hour_ts=[t for t in self._hour_ts if now-t<3600]
        if len(self._hour_ts)>=config.MAX_SIGNALS_PER_HOUR: return
        fired=0
        for sym in symbols:
            if not self._running: break
            sd=self._monitor.get_symbol_data(sym)
            if not sd: continue
            try: result: Optional[SignalResult]=self._engine.score(sd)
            except Exception as e: logger.debug(f"Score {sym}: {e}"); continue
            if not result: continue
            dec=self._memory.check(result)
            if not dec.allow: logger.debug(f"BLOCKED {sym}: {dec.reason}"); continue
            self._memory.record(result, prev=dec.prev)
            tn=self._stats.record_signal(result.symbol,result.direction.value,result.entry_price,result.rr_ratio,result.score.total)
            snap=self._stats.snapshot(tn)
            logger.info(f"SIGNAL #{tn} {result.symbol} {result.direction.value} Score={result.score.total:.1f} RR={result.rr_ratio:.2f} | AllWR={snap['win_rate']:.1f}% DayWR={snap['daily_win_rate']:.1f}% MonWR={snap['monthly_win_rate']:.1f}%")
            self._hour_ts.append(now); fired+=1
            for cb in self._cbs:
                try: await cb(result, snap)
                except Exception as e: logger.error(f"Callback: {e}")
            await asyncio.sleep(0.01)
            if len(self._hour_ts)>=config.MAX_SIGNALS_PER_HOUR: break
        if fired: logger.info(f"Scan done — {fired} signal(s)")

    async def _price_feed(self):
        while self._running:
            try:
                watch={sym for sym,m in self._memory.get_all().items()
                       if m.state not in (TradeState.ALL_TP_HIT,TradeState.SL_HIT,TradeState.CLOSED)}
                for sym in watch:
                    sd=self._monitor.get_symbol_data(sym)
                    if sd and sd.last_price>0:
                        mem=self._memory.get_state(sym)
                        old=mem.state if mem else None
                        self._memory.update_price(sym,sd.last_price)
                        if mem and old!=mem.state:
                            if mem.state==TradeState.ALL_TP_HIT:
                                pnl=abs(mem.tp3-mem.entry)/max(abs(mem.entry-mem.stop_loss),0.0001)
                                self._stats.record_win(sym,pnl_r=round(pnl,2))
                            elif mem.state==TradeState.SL_HIT:
                                self._stats.record_loss(sym,pnl_r=-1.0)
            except Exception as e: logger.error(f"Price feed: {e}")
            await asyncio.sleep(1.0)

    async def _cleanup_loop(self):
        while self._running:
            await asyncio.sleep(21600)
            self._memory.cleanup(max_age_hours=12)
            st=self._stats
            logger.info(f"Stats: {st.total_trades} trades | AllWR={st.win_rate:.1f}% DayWR={st.daily_stats.win_rate:.1f}% MonWR={st.monthly_stats.win_rate:.1f}% PNL={st.total_pnl_r:+.2f}R")
