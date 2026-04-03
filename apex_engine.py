"""
APEX ENGINE  v4  —  Futures 24H miniTicker Native
══════════════════════════════════════════════════
Complete redesign. Only uses metrics that are reliable
with Binance Futures !miniTicker@arr data.

WHAT THE STREAM GIVES US PER TICK:
  pct     = 24H % change from open   ← primary signal
  vol_usd = 24H cumulative USD vol   ← absolute value meaningful
  history = rolling window of pct values per coin  ← trend check

WHAT DOESN'T WORK WITH THIS DATA:
  vol_ratio    = cumulative vol barely changes → always ≈ 1.0
  H/L spread   = 24H spread huge on any mover → useless for SEC
  p99_flow     = grows indefinitely → WAS always 0 after warmup
  Hurst/accel  = pct barely changes frame-to-frame → noise

APEX v4 SCORING (0–100):
  MOVE  40 pts  How large the 24H move is beyond the T3/T4 threshold
  VOL   35 pts  Absolute 24H USD volume (bigger = more conviction)
  MOM   25 pts  Momentum — is the move accelerating or holding steady?

Two hard gates only:
  vol_usd ≥ 500K    (minimum liquidity)
  APEX ≥ threshold  (composite quality gate)
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
    FMT: int = 0   # now = MOVE score
    LVI: int = 0   # now = VOL  score
    WAS: int = 0   # now = MOM  score (momentum)
    SEC: int = 0   # reserved / unused
    NRF: int = 0   # reserved / unused
    APEX: int = 0
    vol_ratio: float = 1.0
    hurst_proxy: float = 0.0
    gates_passed: int = 0
    all_gates: bool = False
    failed_gate: str = ""

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
    trade: Optional[TradeParams] = None
    is_new_listing: bool = False
    signal_reason: str = "initial"

    def coin(self): return self.symbol.replace("USDT", "")
    def tier_meta(self): return TIERS.get(self.tier, {})


# ── Helpers ───────────────────────────────────────────────────

def _clamp(v, lo, hi): return max(lo, min(hi, v))

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
    if apex >= 85: return "S   ELITE"
    if apex >= 75: return "A+  STRONG"
    if apex >= 65: return "A   SOLID"
    if apex >= 55: return "B+  PASS"
    return              "B   PASS"

def conviction_label(apex):
    if apex >= 85: return "HIGH CONVICTION ██████████░░"
    if apex >= 75: return "STRONG SIGNAL   ████████░░░░"
    if apex >= 65: return "STANDARD SIGNAL ██████░░░░░░"
    return              "STANDARD SIGNAL ████░░░░░░░░"

def hold_str(minutes):
    if minutes < 60: return f"~{minutes} min"
    h = minutes // 60; m = minutes % 60
    return f"~{h}h {m:02d}m" if m else f"~{h}h"


# ── Trade calculator ──────────────────────────────────────────

class TradeCalculator:
    HOLD_TIMES = {"scalp": 7, "day": 60, "swing": 240}

    def calculate(self, tick, layers, tier, direction):
        apex  = layers.APEX
        price = tick.price
        abs_pct = abs(tick.pct)

        # Style based on tier + APEX
        if tier == "T4":
            style = "swing" if apex >= 80 else "day"
        else:
            style = "day" if apex >= 70 else "scalp"

        base_lev, base_sl, rr_t = TRADE_PRESETS.get((tier, style), (10, 3.0, 2.5))

        # SL: use 30% of the 24H move as ATR proxy
        atr_sl = _clamp(max(abs_pct * 0.30, base_sl), base_sl * 0.8, base_sl * 1.8)
        lev    = max(1, int(base_lev * (0.80 + _clamp((apex - 55) / 30, 0, 1) * 0.20)))
        pos    = "LONG" if direction == "PUMP" else "SHORT"

        if direction == "PUMP":
            el = price * (1 - 0.004); eh = price * (1 + 0.002); er = (el + eh) / 2
            sl = er * (1 - atr_sl / 100); rp = (er - sl) / er * 100
            tp1 = er * (1 + rp / 100)
            tp2 = er * (1 + rp / 100 * rr_t)
            tp3 = er * (1 + rp / 100 * rr_t * 1.6)
        else:
            el = price * (1 - 0.002); eh = price * (1 + 0.004); er = (el + eh) / 2
            sl = er * (1 + atr_sl / 100); rp = (sl - er) / er * 100
            tp1 = er * (1 - rp / 100)
            tp2 = er * (1 - rp / 100 * rr_t)
            tp3 = er * (1 - rp / 100 * rr_t * 1.6)

        actual_rr = abs(tp2 - er) / max(abs(sl - er), 1e-12)
        d_key = "pump" if direction == "PUMP" else "dump"
        wr    = HIST_WR.get(tier, {}).get(style, {}).get(d_key, 75)

        return TradeParams(
            pos, style, lev, el, eh, sl, tp1, tp2, tp3,
            round(atr_sl, 2), round(actual_rr, 2),
            self.HOLD_TIMES[style], wr
        )


# ── APEX Engine v4 ────────────────────────────────────────────

class ApexEngine:
    """
    Three-component scoring, two hard gates.
    All components are reliably computable from 24H miniTicker data.
    """

    # Hard gate thresholds
    VOL_MIN     = 500_000   # absolute 24H USD volume

    def __init__(self):
        self.calculator  = TradeCalculator()
        self.gate_rejects = {"vol": 0, "APEX": 0}

    def update_universe(self, ticks):
        pass   # no longer needed

    def classify_tier(self, abs_pct):
        if abs_pct >= 20.0: return "T4"
        if abs_pct >= 10.0: return "T3"
        return None

    def score(self, tick, history):
        abs_pct   = abs(tick.pct)
        direction = 1 if tick.pct > 0 else -1

        # ── Component 1: MOVE (0–40) ──────────────────────────
        # How far beyond the T3/T4 threshold has the coin moved?
        # T3: 10%+ → 0 pts at 10%, 25 pts at 20%, 40 pts at 26%+
        # T4: 20%+ → 0 pts at 20%, 25 pts at 30%, 40 pts at 36%+
        base = 10.0 if abs_pct < 20.0 else 20.0
        move_score = int(_clamp((abs_pct - base) * 2.0, 0, 40))

        # ── Component 2: VOL (0–35) ───────────────────────────
        # Absolute 24H USD volume tiers
        v = tick.vol_usd
        if   v >= 500_000_000: vol_score = 35
        elif v >= 100_000_000: vol_score = 30
        elif v >=  50_000_000: vol_score = 26
        elif v >=  20_000_000: vol_score = 22
        elif v >=  10_000_000: vol_score = 18
        elif v >=   5_000_000: vol_score = 14
        elif v >=   2_000_000: vol_score = 10
        elif v >=   1_000_000: vol_score = 7
        elif v >=     500_000: vol_score = 4
        else:                  vol_score = 0

        # ── Component 3: MOM — Momentum (0–25) ───────────────
        # Is the 24H % change accelerating in the signal direction?
        # Looks at how pct has evolved over recent history ticks.
        mom_score = 10   # neutral baseline
        if len(history) >= 2:
            recent = [h.pct for h in history[-4:]] + [tick.pct]
            # Count ticks where move strengthened (pct moved further from 0)
            strengthen = sum(
                1 for i in range(1, len(recent))
                if (recent[i] - recent[i-1]) * direction > 0
            )
            ratio = strengthen / max(len(recent) - 1, 1)
            mom_score = int(_clamp(ratio * 25, 0, 25))

        # ── APEX composite ────────────────────────────────────
        APEX = move_score + vol_score + mom_score

        # ── 2-gate filter ─────────────────────────────────────
        tier_id  = self.classify_tier(abs_pct) or "T3"
        apex_min = TIERS[tier_id]["apex_gate"]

        gate_vol  = tick.vol_usd >= self.VOL_MIN
        gate_apex = APEX >= apex_min

        gates = [gate_vol, gate_apex]
        failed = []
        if not gate_vol:  failed.append("vol");  self.gate_rejects["vol"]  += 1
        if not gate_apex: failed.append("APEX"); self.gate_rejects["APEX"] += 1

        # Store components in layer slots for display
        return LayerScores(
            FMT          = move_score,         # MOVE component
            LVI          = vol_score,          # VOL  component
            WAS          = mom_score,          # MOM  component
            SEC          = 0,
            NRF          = 0,
            APEX         = APEX,
            vol_ratio    = round(tick.vol_usd / 1_000_000, 2),   # vol in $M for display
            hurst_proxy  = round(mom_score / 25, 2),
            gates_passed = sum(gates),
            all_gates    = all(gates),
            failed_gate  = ",".join(failed),
        )

    def build_signal(self, tick, layers, is_new_listing=False, signal_reason="initial"):
        tier      = self.classify_tier(abs(tick.pct))
        direction = "PUMP" if tick.pct > 0 else "DUMP"
        trade     = self.calculator.calculate(tick, layers, tier, direction)
        return Signal(
            tick.symbol, tick.price, tick.vol_usd, tick.pct,
            direction, tier, layers, layers.APEX, tick.ts,
            trade, is_new_listing, signal_reason
        )
