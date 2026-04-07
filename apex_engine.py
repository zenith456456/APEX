"""
APEX ENGINE  v4 — Futures 24H miniTicker Native Scoring
════════════════════════════════════════════════════════
Designed specifically for Binance Futures !miniTicker@arr data.

WHAT THIS STREAM PROVIDES PER TICK:
  c  = current price
  o  = 24H open price
  pct = (c - o) / o * 100   ← primary signal driver
  q  = 24H cumulative USD volume (absolute value is meaningful)
  h/l = 24H high/low (too wide to be useful for intra-signal scoring)

THREE-COMPONENT SCORING (max 100 pts):

  MOVE  (0-50 pts)
  ─────────────────
  How far has the coin moved beyond the T3/T4 threshold?
  T3 (10-20%): score = (abs_pct - 10) * 5   → 0 at 10%, 50 at 20%
  T4 (≥ 20%):  score = (abs_pct / 20) * 40  → 40 at 20%, 50 at 25%+

  VOL  (0-35 pts)
  ───────────────
  Absolute 24H USD volume. Bigger volume = more conviction.
  9 tiers from $500K (3 pts) to $500M+ (35 pts).

  MOM  (0-15 pts)
  ───────────────
  Momentum — are recent ticks confirming the move direction?
  Ratio of ticks strengthening in the signal direction × 15.

GATES (both must pass to fire a signal):
  1. vol_usd ≥ $500K          (absolute liquidity floor)
  2. APEX ≥ tier["apex_gate"] (T3 ≥ 82,  T4 ≥ 78)

EXAMPLE SCORES:
  T3  18%  $200M  good MOM  → MOVE=40  VOL=30  MOM=12  APEX=82 ✅
  T3  12%  $500M  good MOM  → MOVE=10  VOL=35  MOM=13  APEX=58 ❌
  T4  25%  $50M   good MOM  → MOVE=50  VOL=26  MOM=12  APEX=88 ✅
  T4  22%  $10M   weak MOM  → MOVE=44  VOL=16  MOM=5   APEX=65 ❌
  T4  67%  $3.6B  any MOM   → MOVE=50  VOL=35  MOM=8+  APEX=93+✅
"""
import math
from dataclasses import dataclass
from typing import Optional
from config import TIERS, HIST_WR, TRADE_PRESETS


# ── Data classes ──────────────────────────────────────────────

@dataclass
class TickData:
    symbol : str
    price  : float
    open24 : float
    high   : float
    low    : float
    vol_usd: float
    pct    : float
    ts     : float

@dataclass
class LayerScores:
    FMT         : int   = 0   # MOVE score  (0-50)
    LVI         : int   = 0   # VOL  score  (0-35)
    WAS         : int   = 0   # MOM  score  (0-15)
    SEC         : int   = 0   # reserved
    NRF         : int   = 0   # reserved
    APEX        : int   = 0   # total
    vol_ratio   : float = 0.0 # vol in $M (display)
    hurst_proxy : float = 0.0 # mom ratio (display)
    gates_passed: int   = 0
    all_gates   : bool  = False
    failed_gate : str   = ""

@dataclass
class TradeParams:
    position  : str
    style     : str
    leverage  : int
    entry_low : float
    entry_high: float
    sl        : float
    tp1       : float
    tp2       : float
    tp3       : float
    sl_pct    : float
    rr        : float
    expected_min: int
    hist_wr   : int

@dataclass
class Signal:
    symbol       : str
    price        : float
    vol_usd      : float
    pct          : float
    direction    : str      # "PUMP" | "DUMP"
    tier         : str      # "T3"  | "T4"
    layers       : LayerScores
    apex_score   : int
    ts_epoch     : float
    trade        : Optional[TradeParams] = None
    is_new_listing: bool = False
    signal_reason : str  = "new_coin"

    def coin(self)      -> str:  return self.symbol.replace("USDT", "")
    def tier_meta(self) -> dict: return TIERS.get(self.tier, {})


# ── Helpers ───────────────────────────────────────────────────

def _clamp(v, lo, hi): return max(lo, min(hi, v))

def fmt_price(p: float) -> str:
    if p <= 0:       return "0.00"
    if p < 0.00001:  return f"{p:.8f}"
    if p < 0.001:    return f"{p:.7f}"
    if p < 0.01:     return f"{p:.6f}"
    if p < 0.1:      return f"{p:.5f}"
    if p < 10:       return f"{p:.4f}"
    if p < 1_000:    return f"{p:.3f}"
    if p < 10_000:   return f"{p:.2f}"
    return f"{p:.1f}"

def fmt_vol(v: float) -> str:
    if v >= 1e9: return f"${v/1e9:.2f}B"
    if v >= 1e6: return f"${v/1e6:.2f}M"
    if v >= 1e3: return f"${v/1e3:.0f}K"
    return f"${v:.0f}"

def score_bar(score: int, width: int = 10) -> str:
    f = round(_clamp(score, 0, 100) / 100 * width)
    return "█" * f + "░" * (width - f)

def apex_grade(apex: int) -> str:
    if apex >= 95: return "S+  ELITE"
    if apex >= 90: return "S   PRIME"
    if apex >= 85: return "A+  STRONG"
    if apex >= 82: return "A   SOLID"
    return              "B+  PASS"

def conviction_label(apex: int) -> str:
    if apex >= 95: return "ELITE CONVICTION  ██████████"
    if apex >= 90: return "HIGH CONVICTION   ████████░░"
    if apex >= 85: return "STRONG SIGNAL     ██████░░░░"
    return              "STANDARD SIGNAL   █████░░░░░"

def hold_str(minutes: int) -> str:
    if minutes < 60: return f"~{minutes} min"
    h = minutes // 60; m = minutes % 60
    return f"~{h}h {m:02d}m" if m else f"~{h}h"


# ── Trade calculator ──────────────────────────────────────────

class TradeCalculator:
    HOLD = {"scalp": 7, "day": 60, "swing": 240, "power": 300, "ultra": 360}

    def calculate(self, tick: TickData, layers: LayerScores,
                  tier: str, direction: str) -> TradeParams:
        apex    = layers.APEX
        price   = tick.price
        abs_pct = abs(tick.pct)

        # Tiered style selection — R:R scales with APEX score + move size
        # Minimum R:R = 1:3  |  Maximum R:R = 1:6
        if tier == "T4":
            if abs_pct >= 40.0:
                style = "ultra"   # extreme move ≥40% → R:R 1:6
            elif apex >= 95:
                style = "power"   # elite APEX        → R:R 1:5
            elif apex >= 85:
                style = "swing"   # strong APEX       → R:R 1:4
            else:
                style = "day"     # standard T4       → R:R 1:3.5
        else:  # T3
            if apex >= 95:
                style = "power"   # elite APEX        → R:R 1:5
            elif apex >= 88:
                style = "swing"   # strong APEX       → R:R 1:4
            else:
                style = "day"     # standard T3       → R:R 1:3

        base_lev, base_sl, rr_t = TRADE_PRESETS.get((tier, style), (10, 3.0, 2.5))

        # SL: 30% of the 24H move gives a realistic stop distance
        atr_sl = _clamp(abs_pct * 0.30, base_sl * 0.8, base_sl * 1.8)
        lev    = max(1, int(base_lev * (0.80 + _clamp((apex - 78) / 22, 0, 1) * 0.20)))
        pos    = "LONG" if direction == "PUMP" else "SHORT"

        if direction == "PUMP":
            el = price * (1 - 0.004); eh = price * (1 + 0.002); er = (el + eh) / 2
            sl = er * (1 - atr_sl / 100)
            rp = (er - sl) / er * 100
            tp1 = er * (1 + rp / 100)
            tp2 = er * (1 + rp / 100 * rr_t)
            tp3 = er * (1 + rp / 100 * rr_t * 1.6)
        else:
            el = price * (1 - 0.002); eh = price * (1 + 0.004); er = (el + eh) / 2
            sl = er * (1 + atr_sl / 100)
            rp = (sl - er) / er * 100
            tp1 = er * (1 - rp / 100)
            tp2 = er * (1 - rp / 100 * rr_t)
            tp3 = er * (1 - rp / 100 * rr_t * 1.6)

        actual_rr = abs(tp2 - er) / max(abs(sl - er), 1e-12)
        d_key = "pump" if direction == "PUMP" else "dump"
        wr    = HIST_WR.get(tier, {}).get(style, {}).get(d_key, 75)

        return TradeParams(
            pos, style, lev, el, eh, sl, tp1, tp2, tp3,
            round(atr_sl, 2), round(actual_rr, 2),
            self.HOLD[style], wr,
        )


# ── APEX Engine ───────────────────────────────────────────────

class ApexEngine:

    def __init__(self):
        self.calculator   = TradeCalculator()
        self.gate_rejects = {"vol": 0, "APEX": 0}

    def update_universe(self, ticks):
        pass   # not needed in v4

    def classify_tier(self, abs_pct: float) -> Optional[str]:
        if abs_pct >= 20.0: return "T4"
        if abs_pct >= 10.0: return "T3"
        return None

    def score(self, tick: TickData, history: list) -> LayerScores:
        abs_pct   = abs(tick.pct)
        direction = 1 if tick.pct > 0 else -1

        # ── MOVE (0-50) ───────────────────────────────────────
        if abs_pct < 20.0:
            # T3: linear 0→50 over the 10-20% range
            move = int(_clamp((abs_pct - 10.0) * 5.0, 0, 50))
        else:
            # T4: starts at 40 (earned by reaching 20%), climbs to 50 at 25%+
            move = int(_clamp((abs_pct / 20.0) * 40.0, 40, 50))

        # ── VOL (0-35) ────────────────────────────────────────
        v = tick.vol_usd
        if   v >= 500_000_000: vol = 35
        elif v >= 200_000_000: vol = 32
        elif v >= 100_000_000: vol = 28
        elif v >=  50_000_000: vol = 24
        elif v >=  20_000_000: vol = 20
        elif v >=  10_000_000: vol = 16
        elif v >=   5_000_000: vol = 12
        elif v >=   2_000_000: vol = 8
        elif v >=   1_000_000: vol = 5
        elif v >=     500_000: vol = 3
        else:                  vol = 0

        # ── MOM (0-15) ────────────────────────────────────────
        # Count how many of the last N ticks had % moving further
        # in the signal direction (strengthening the move)
        mom = 8   # neutral baseline when no history
        if len(history) >= 2:
            recent = [h.pct for h in history[-5:]] + [tick.pct]
            strengthening = sum(
                1 for i in range(1, len(recent))
                if (recent[i] - recent[i - 1]) * direction > 0
            )
            ratio = strengthening / max(len(recent) - 1, 1)
            mom   = int(_clamp(ratio * 15, 0, 15))

        # ── APEX composite ─────────────────────────────────────
        apex = move + vol + mom

        # ── 2-gate filter ─────────────────────────────────────
        tier_id  = self.classify_tier(abs_pct) or "T3"
        apex_min = TIERS[tier_id]["apex_gate"]

        gate_vol  = tick.vol_usd >= 500_000
        gate_apex = apex >= apex_min

        failed = []
        if not gate_vol:  failed.append("vol");  self.gate_rejects["vol"]  += 1
        if not gate_apex: failed.append("APEX"); self.gate_rejects["APEX"] += 1

        return LayerScores(
            FMT          = move,
            LVI          = vol,
            WAS          = mom,
            APEX         = apex,
            vol_ratio    = round(tick.vol_usd / 1_000_000, 2),
            hurst_proxy  = round(mom / 15, 2),
            gates_passed = 2 - len(failed),
            all_gates    = len(failed) == 0,
            failed_gate  = ",".join(failed),
        )

    def build_signal(self, tick: TickData, layers: LayerScores,
                     is_new_listing: bool = False,
                     signal_reason: str = "new_coin") -> Signal:
        tier      = self.classify_tier(abs(tick.pct))
        direction = "PUMP" if tick.pct > 0 else "DUMP"
        trade     = self.calculator.calculate(tick, layers, tier, direction)
        return Signal(
            tick.symbol, tick.price, tick.vol_usd, tick.pct,
            direction, tier, layers, layers.APEX, tick.ts,
            trade, is_new_listing, signal_reason,
        )
