"""
APEX DEEP AI  —  5-LAYER SCORING ENGINE  (v3 — Futures-native)
══════════════════════════════════════════════════════════════
Redesigned for Binance Futures !miniTicker@arr stream data:
  c = current price
  o = 24H open price
  h = 24H high (cumulative)
  l = 24H low  (cumulative)
  q = 24H quote volume USD (cumulative — barely changes tick-to-tick)

KEY INSIGHT: vol_ratio from rolling avg of 24H cumulative volume ≈ 1.0
always. The old LVI and SEC formulas produced ~30 and ~0 respectively
for every T3/T4 candidate — causing 100% rejection.

v3 Fixes:
  LVI: Based purely on absolute 24H USD volume (not ratio)
  SEC: Based on move-to-spread efficiency + tick consistency (not 24H H/L)
  Burst gate: REMOVED (vol_ratio is meaningless with cumulative data)
  FMT, WAS, NRF: Kept — these work correctly with available data
"""
import math
import time
from dataclasses import dataclass, field
from typing import Optional
from config import TIERS, HIST_WR, TRADE_PRESETS


# ── Data classes ──────────────────────────────────────────────

@dataclass
class TickData:
    symbol: str; price: float; open24: float
    high: float; low: float; vol_usd: float; pct: float; ts: float

@dataclass
class LayerScores:
    FMT: int=0; LVI: int=0; WAS: int=0; SEC: int=0; NRF: int=0; APEX: int=0
    vol_ratio: float=1.0; hurst_proxy: float=0.0
    gates_passed: int=0; all_gates: bool=False
    failed_gate: str=""

@dataclass
class TradeParams:
    position: str; style: str; leverage: int
    entry_low: float; entry_high: float
    sl: float; tp1: float; tp2: float; tp3: float
    sl_pct: float; rr: float; expected_min: int; hist_wr: int

@dataclass
class Signal:
    symbol: str; price: float; vol_usd: float; pct: float
    direction: str; tier: str; layers: LayerScores; apex_score: int; ts_epoch: float
    trade: Optional[TradeParams]=None; is_new_listing: bool=False; signal_reason: str="initial"
    def coin(self): return self.symbol.replace("USDT","")
    def tier_meta(self): return TIERS.get(self.tier,{})


# ── Helpers ───────────────────────────────────────────────────

def _clamp(v, lo, hi): return max(lo, min(hi, v))
def _log2(x): return math.log2(x) if x > 0 else 0.0

def fmt_price(p):
    if p <= 0:      return "0.00"
    if p < 0.00001: return f"{p:.8f}"
    if p < 0.001:   return f"{p:.7f}"
    if p < 0.01:    return f"{p:.6f}"
    if p < 0.1:     return f"{p:.5f}"
    if p < 10:      return f"{p:.4f}"
    if p < 1000:    return f"{p:.3f}"
    if p < 10000:   return f"{p:.2f}"
    return f"{p:.1f}"

def fmt_vol(v):
    if v >= 1e9: return f"${v/1e9:.2f}B"
    if v >= 1e6: return f"${v/1e6:.2f}M"
    if v >= 1e3: return f"${v/1e3:.0f}K"
    return f"${v:.0f}"

def score_bar(score, width=10):
    f = round(_clamp(score, 0, 100) / 100 * width)
    return "█" * f + "░" * (width - f)

def apex_grade(apex):
    if apex >= 95: return "S+  ELITE"
    if apex >= 90: return "S   PRIME"
    if apex >= 85: return "A+  STRONG"
    if apex >= 80: return "A   SOLID"
    return              "B+  PASS"

def conviction_label(apex):
    if apex >= 95: return "MAX CONVICTION  ████████████"
    if apex >= 90: return "HIGH CONVICTION ██████████░░"
    if apex >= 85: return "STRONG SIGNAL   ████████░░░░"
    return              "STANDARD SIGNAL ██████░░░░░░"

def hold_str(minutes):
    if minutes < 60: return f"~{minutes} min"
    h = minutes // 60; m = minutes % 60
    return f"~{h}h {m:02d}m" if m else f"~{h}h"


# ── Universe stats (WAS normalisation) ────────────────────────

class UniverseStats:
    def __init__(self, window=500):
        self._flows = []; self._window = window

    def update(self, ticks):
        flows = [t.vol_usd * abs(t.pct) for t in ticks if abs(t.pct) >= 5.0]
        if flows:
            self._flows.extend(flows)
            if len(self._flows) > self._window:
                self._flows = self._flows[-self._window:]

    @property
    def p99_flow(self):
        if not self._flows: return 1.0
        s = sorted(self._flows)
        return s[max(0, int(len(s) * 0.99) - 1)] or 1.0


# ── Trade calculator ──────────────────────────────────────────

class TradeCalculator:
    HOLD_TIMES = {"scalp": 7, "day": 60, "swing": 240}

    def calculate(self, tick, layers, tier, direction):
        apex = layers.APEX; price = tick.price
        style = ("swing" if tier == "T4" and apex >= 91
                 else "day" if (tier == "T4" or apex >= 88)
                 else "scalp")
        base_lev, base_sl, rr_t = TRADE_PRESETS.get((tier, style), (10, 3.0, 2.5))
        # Use % range from 24H open as ATR proxy
        range_pct = abs(tick.pct) * 0.3   # 30% of the 24H move as SL basis
        atr_sl = _clamp(max(range_pct, base_sl), base_sl * 0.8, base_sl * 1.6)
        lev = max(1, int(base_lev * (0.80 + _clamp((apex - 80) / 20, 0, 1) * 0.20)))
        pos = "LONG" if direction == "PUMP" else "SHORT"
        if direction == "PUMP":
            el = price * (1 - 0.004); eh = price * (1 + 0.002); er = (el + eh) / 2
            sl = er * (1 - atr_sl / 100); rp = (er - sl) / er * 100
            tp1 = er * (1 + rp / 100); tp2 = er * (1 + rp / 100 * rr_t)
            tp3 = er * (1 + rp / 100 * rr_t * 1.6)
        else:
            el = price * (1 - 0.002); eh = price * (1 + 0.004); er = (el + eh) / 2
            sl = er * (1 + atr_sl / 100); rp = (sl - er) / er * 100
            tp1 = er * (1 - rp / 100); tp2 = er * (1 - rp / 100 * rr_t)
            tp3 = er * (1 - rp / 100 * rr_t * 1.6)
        actual_rr = abs(tp2 - er) / max(abs(sl - er), 1e-12)
        d_key = "pump" if direction == "PUMP" else "dump"
        wr = HIST_WR.get(tier, {}).get(style, {}).get(d_key, 80)
        return TradeParams(pos, style, lev, el, eh, sl, tp1, tp2, tp3,
                           round(atr_sl, 2), round(actual_rr, 2),
                           self.HOLD_TIMES[style], wr)


# ── APEX Engine v3 ────────────────────────────────────────────

class ApexEngine:
    """
    Gates redesigned for 24H Futures miniTicker data.

    Removed gates:
      burst_min  — vol_ratio ≈ 1.0 always with 24H cumulative volume

    Active gates (6 gates, all must pass):
      vol_min    — absolute 24H USD volume floor
      FMT_min    — fractal momentum
      WAS_min    — whale accumulation (flow-based)
      NRF_min    — neural resonance (acceleration + consistency)
      dir_min    — directional consistency across ticks
      APEX_min   — composite score (from TIERS config)

    LVI and SEC are scored and included in APEX composite
    but NOT used as hard gates (they were always failing).
    """

    # Hard gates — ALL must pass
    GATES = {
        "vol_min": 500_000,   # absolute 24H USD volume
        "fmt_min": 60,        # fractal momentum
        "was_min": 50,        # whale accumulation
        "nrf_min": 50,        # neural resonance
        "dir_min": 0.30,      # directional tick consistency
        # APEX_min comes from TIERS[tier]["apex_gate"]
    }

    def __init__(self):
        self.universe   = UniverseStats()
        self.calculator = TradeCalculator()
        self.gate_rejects = {
            "vol": 0, "FMT": 0, "WAS": 0,
            "NRF": 0, "dir": 0, "APEX": 0,
        }

    def update_universe(self, ticks):
        self.universe.update(ticks)

    def classify_tier(self, abs_pct):
        if abs_pct >= 20.0: return "T4"
        if abs_pct >= 10.0: return "T3"
        return None

    def score(self, tick, history):
        if len(history) < 3:
            return None

        abs_pct   = abs(tick.pct)
        direction = 1 if tick.pct > 0 else -1
        prev4     = history[-4:] if len(history) >= 4 else history

        # ── FMT — Fractal Momentum Tensor ────────────────────
        # Measures velocity + tick-to-tick directional consistency
        pv = [h.pct for h in prev4] + [tick.pct]
        deltas   = [pv[i] - pv[i-1] for i in range(1, len(pv))]
        same_dir = sum(1 for d in deltas if d * direction > 0) / max(len(deltas), 1)
        vel_sc   = _clamp(abs_pct * 3.5, 0, 65)
        FMT      = int(_clamp(vel_sc + same_dir * 35, 0, 100))

        # ── LVI — Liquidity Vacuum Index ─────────────────────
        # v3: Based on ABSOLUTE 24H USD volume, not ratio.
        # Tiers: $500K=30, $2M=50, $5M=65, $20M=80, $100M=95
        vol_usd = tick.vol_usd
        if vol_usd >= 100_000_000:  lvi_base = 95
        elif vol_usd >= 50_000_000: lvi_base = 88
        elif vol_usd >= 20_000_000: lvi_base = 80
        elif vol_usd >= 10_000_000: lvi_base = 72
        elif vol_usd >= 5_000_000:  lvi_base = 65
        elif vol_usd >= 2_000_000:  lvi_base = 55
        elif vol_usd >= 1_000_000:  lvi_base = 45
        elif vol_usd >= 500_000:    lvi_base = 35
        else:                       lvi_base = 20
        # Bonus for large moves (higher % = more conviction)
        lvi_bonus = _clamp((abs_pct - 10) * 1.5, 0, 15)
        LVI = int(_clamp(lvi_base + lvi_bonus, 0, 100))
        # vol_ratio stored for display (still computed but not gated)
        rv = [h.vol_usd for h in history[-20:]] or [vol_usd]
        vol_ratio = vol_usd / max(sum(rv) / len(rv), 1.0)

        # ── WAS — Whale Accumulation Signature ────────────────
        # Flow = vol_usd × abs_pct, normalized against universe p99
        flow      = vol_usd * abs_pct
        flow_norm = flow / max(self.universe.p99_flow, 1.0)
        vb = 20 if vol_usd > 5_000_000 else 12 if vol_usd > 1_000_000 else 5
        pb = 15 if abs_pct >= 15 else 10 if abs_pct >= 10 else 5
        WAS = int(_clamp(_clamp(flow_norm * 55, 0, 55) + vb + pb, 0, 100))

        # ── SEC — Spectral Entropy Collapse ───────────────────
        # v3: Measures move clarity — large pct with high tick consistency
        # (24H H/L spread NOT used — it's always huge for T3/T4 movers)
        clarity = same_dir * 60                          # 0-60: tick direction clean
        magn    = _clamp((abs_pct - 10) * 2.5, 0, 35)   # 0-35: move magnitude bonus
        SEC     = int(_clamp(clarity + magn, 0, 100))

        # ── NRF — Neural Resonance Field ──────────────────────
        prev_pct = history[-1].pct if history else 0.0
        accel    = tick.pct - prev_pct
        accel_sc = _clamp(abs(accel) * 7 * (1.0 if accel * direction > 0 else -0.5), -15, 45)
        consist  = sum(1 for h in prev4 if h.pct * direction > 0) / max(len(prev4), 1)
        NRF      = int(_clamp(accel_sc + consist * 40 + (10 if abs_pct >= 12 else 5), 0, 100))

        # ── APEX composite ────────────────────────────────────
        APEX = int(round(
            FMT * 0.22 + LVI * 0.24 + WAS * 0.20 + SEC * 0.18 + NRF * 0.16
        ))

        # ── 6-gate filter ─────────────────────────────────────
        tier_id  = self.classify_tier(abs_pct) or "T3"
        apex_min = TIERS[tier_id]["apex_gate"]
        g        = self.GATES

        gate_map = [
            ("vol",  tick.vol_usd >= g["vol_min"]),
            ("FMT",  FMT          >= g["fmt_min"]),
            ("WAS",  WAS          >= g["was_min"]),
            ("NRF",  NRF          >= g["nrf_min"]),
            ("dir",  same_dir     >= g["dir_min"]),
            ("APEX", APEX         >= apex_min),
        ]

        passed       = [ok for _, ok in gate_map]
        failed_names = [name for name, ok in gate_map if not ok]

        for name in failed_names:
            self.gate_rejects[name] = self.gate_rejects.get(name, 0) + 1

        return LayerScores(
            FMT=FMT, LVI=LVI, WAS=WAS, SEC=SEC, NRF=NRF, APEX=APEX,
            vol_ratio    = round(vol_ratio, 2),
            hurst_proxy  = round(same_dir,  2),
            gates_passed = sum(passed),
            all_gates    = all(passed),
            failed_gate  = ",".join(failed_names[:3]),
        )

    def build_signal(self, tick, layers, is_new_listing=False, signal_reason='initial'):
        tier      = self.classify_tier(abs(tick.pct))
        direction = "PUMP" if tick.pct > 0 else "DUMP"
        trade     = self.calculator.calculate(tick, layers, tier, direction)
        return Signal(tick.symbol, tick.price, tick.vol_usd, tick.pct,
                      direction, tier, layers, layers.APEX, tick.ts,
                      trade, is_new_listing, signal_reason)
