"""
APEX ENGINE  v6  —  Corrected Gates + Crash-Market Aware Scoring
═══════════════════════════════════════════════════════════════════
FIXES vs v5:
  1. Style selection thresholds recalibrated to new APEX range
       Old: T3 power ≥70, swing ≥60, day <60
            T4 ultra ≥40%, swing ≥75, day <75
       Problem: APEX realistic range is 15–85 for T3, 55–100 for T4.
       Old T4 threshold of ≥75 means apex must be ≥75/100 = elite tier,
       rejecting most T4 signals as "day" style when they deserve "swing".
       New thresholds split the ACTUAL range evenly.

  2. Gate logic unified with config.py
       Old engine had its own hardcoded gates (T3≥82, T4≥78) in the
       docstring that contradicted config.py (T3=38, T4=62).
       Now uses config.TIERS["T3"]["apex_gate"] everywhere.

  3. MOM score verified correct for crash markets
       In a sustained dump every tick makes 24h-pct more negative →
       consecutive delta is negative × direction(-1) = positive →
       ratio→1.0 → mom=10. This is correct and intended.
       No change needed here.

  4. VOL score: added $150K bracket so coins just above VOLUME_MIN
       don't all score vol=0. Now vol=1 starts at $150K.
       (VOLUME_MIN stays 300K — the new bracket just improves scoring.)
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
    FMT         : int   = 0
    LVI         : int   = 0
    WAS         : int   = 0
    SEC         : int   = 0
    NRF         : int   = 0
    APEX        : int   = 0
    vol_ratio   : float = 0.0
    hurst_proxy : float = 0.0
    gates_passed: int   = 0
    all_gates   : bool  = False
    failed_gate : str   = ""

@dataclass
class TradeParams:
    position    : str
    style       : str
    leverage    : int
    entry_low   : float
    entry_high  : float
    sl          : float
    tp1         : float
    tp2         : float
    tp3         : float
    tp4         : float
    tp5         : float
    sl_pct      : float
    rr_max      : float
    expected_min: int
    hist_wr     : int

@dataclass
class Signal:
    symbol          : str
    price           : float
    vol_usd         : float
    pct             : float
    direction       : str
    tier            : str
    layers          : LayerScores
    apex_score      : int
    ts_epoch        : float
    trade           : Optional[TradeParams] = None
    is_new_listing  : bool = False
    signal_reason   : str  = "new_coin"
    market_condition: str  = ""

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
    # Recalibrated for new APEX range (15–100):
    if apex >= 75: return "S+  ELITE"
    if apex >= 60: return "S   PRIME"
    if apex >= 45: return "A+  STRONG"
    if apex >= 32: return "A   SOLID"
    return              "B+  PASS"

def hold_str(minutes: int) -> str:
    if minutes < 60: return f"~{minutes} min"
    h = minutes // 60; m = minutes % 60
    return f"~{h}h {m:02d}m" if m else f"~{h}h"


# ── Trade calculator ──────────────────────────────────────────

class TradeCalculator:
    HOLD = {
        "day"  : 60,
        "swing": 240,
        "power": 360,
        "ultra": 480,
    }

    def calculate(self, tick: TickData, layers: LayerScores,
                  tier: str, direction: str) -> TradeParams:
        apex    = layers.APEX
        price   = tick.price
        abs_pct = abs(tick.pct)

        # ── Style selection ───────────────────────────────────
        #
        # FIX: Old thresholds were calibrated for the 0-100 "ideal" APEX.
        # Actual APEX range from scoring formula:
        #   T3: move(10–55) + vol(0–20) + mom(0–10) → real range ~15–85
        #   T4: move(55–70) + vol(0–20) + mom(0–10) → real range ~55–100
        #
        # T3 splits (thirds of 15–85 range: 15, 38, 62, 85):
        #   day   = APEX 15–37  (weak move, low vol)
        #   swing = APEX 38–61  (solid move, decent vol)
        #   power = APEX 62+    (strong move, high vol)
        #
        # T4 splits (thirds of 55–100 range: 55, 70, 85, 100):
        #   day   = APEX 55–69  (just crossed 20%, low vol)
        #   swing = APEX 70–84  (solid mega move)
        #   ultra = 40%+ move   (always ultra regardless of APEX)
        #
        if tier == "T4":
            if abs_pct >= 40.0: style = "ultra"
            elif apex >= 70:    style = "swing"
            else:               style = "day"
        else:  # T3
            if apex >= 62:   style = "power"
            elif apex >= 38: style = "swing"
            else:            style = "day"

        base_lev, sl_pct = TRADE_PRESETS.get((tier, style), (7, 4.0))

        # ── Leverage: scale with APEX relative to tier floor ─
        # T3 floor=22, T4 floor=52 → scale from floor to 100
        tier_floor = TIERS[tier]["apex_gate"]
        apex_norm  = _clamp((apex - tier_floor) / (100 - tier_floor), 0, 1)
        lev        = max(1, int(base_lev * (0.80 + apex_norm * 0.20)))

        # ── Entry at current price ────────────────────────────
        pos = "LONG" if direction == "PUMP" else "SHORT"

        if direction == "PUMP":
            el = price * (1 - 0.002)
            eh = price * (1 + 0.001)
            er = (el + eh) / 2
            sl = er * (1 - sl_pct / 100)
            rp = sl_pct
            tp1 = er * (1 + rp / 100 * 1.0)
            tp2 = er * (1 + rp / 100 * 2.0)
            tp3 = er * (1 + rp / 100 * 3.0)
        else:
            el = price * (1 - 0.001)
            eh = price * (1 + 0.002)
            er = (el + eh) / 2
            sl = er * (1 + sl_pct / 100)
            rp = sl_pct
            tp1 = er * (1 - rp / 100 * 1.0)
            tp2 = er * (1 - rp / 100 * 2.0)
            tp3 = er * (1 - rp / 100 * 3.0)

        # ── Dynamic uncapped R:R ──────────────────────────────
        rr_max = max(6.0, (abs_pct / sl_pct) * 0.7)

        if direction == "PUMP":
            tp4 = er * (1 + rp / 100 * rr_max * 0.6)
            tp5 = er * (1 + rp / 100 * rr_max)
        else:
            tp4 = er * (1 - rp / 100 * rr_max * 0.6)
            tp5 = er * (1 - rp / 100 * rr_max)

        d_key = "pump" if direction == "PUMP" else "dump"
        wr    = HIST_WR.get(tier, {}).get(style, {}).get(d_key, 75)

        return TradeParams(
            pos, style, lev,
            el, eh, sl,
            tp1, tp2, tp3, tp4, tp5,
            round(sl_pct, 2),
            round(rr_max, 1),
            self.HOLD.get(style, 120),
            wr,
        )


# ── APEX Engine ───────────────────────────────────────────────

class ApexEngine:

    def __init__(self):
        self.calculator   = TradeCalculator()
        self.gate_rejects = {"vol": 0, "APEX": 0}

    def update_universe(self, ticks):
        pass

    def classify_tier(self, abs_pct: float) -> Optional[str]:
        if abs_pct >= 20.0: return "T4"
        if abs_pct >= 10.0: return "T3"
        return None

    def score(self, tick: TickData, history: list) -> LayerScores:
        abs_pct   = abs(tick.pct)
        direction = 1 if tick.pct > 0 else -1

        # ── MOVE score (10–70) ────────────────────────────────
        #
        # Range design:
        #   10%  → move=10   (T3 floor — gives APEX=~16 at min vol)
        #   15%  → move=33   (mid T3)
        #   20%  → move=55   (T4 floor — gives APEX=~61 at min vol)
        #   30%  → move=70   (strong T4, capped)
        #
        # Why 10 floor: ensures 10% moves can pass the new gate=22
        # when combined with vol≥2 and mom≥5.
        #
        if abs_pct < 20.0:
            move = int(_clamp(10.0 + (abs_pct - 10.0) * 4.5, 10, 55))
        else:
            move = int(_clamp(55.0 + (abs_pct - 20.0) * 1.5, 55, 70))

        # ── VOL score (0–20) ──────────────────────────────────
        #
        # FIX: Added $150K bracket so coins just above VOLUME_MIN
        # ($300K) correctly score vol=1 instead of vol=0.
        # The $150K bracket is for scoring only — VOLUME_MIN filter
        # still hard-rejects anything below $300K before scoring.
        #
        v = tick.vol_usd
        if   v >= 500_000_000: vol = 20
        elif v >= 200_000_000: vol = 18
        elif v >= 100_000_000: vol = 16
        elif v >=  50_000_000: vol = 14
        elif v >=  20_000_000: vol = 12
        elif v >=  10_000_000: vol = 10
        elif v >=   5_000_000: vol = 8
        elif v >=   2_000_000: vol = 6
        elif v >=   1_000_000: vol = 4
        elif v >=     500_000: vol = 2
        elif v >=     150_000: vol = 1   # NEW bracket (was missing)
        else:                  vol = 0

        # ── MOM score (0–10) ──────────────────────────────────
        #
        # Measures directional acceleration of the 24h-pct across ticks.
        # In a sustained crash dump: each tick the 24h-pct grows more
        # negative → delta negative × direction(-1) = positive →
        # strengthening=1 per tick → ratio→1 → mom→10.
        # This is correct: crash dumps DO have strong momentum.
        #
        mom = 5  # neutral default when history too short
        if len(history) >= 2:
            recent = [h.pct for h in history[-5:]] + [tick.pct]
            strengthening = sum(
                1 for i in range(1, len(recent))
                if (recent[i] - recent[i - 1]) * direction > 0
            )
            ratio = strengthening / max(len(recent) - 1, 1)
            mom   = int(_clamp(ratio * 10, 0, 10))

        # ── APEX composite ────────────────────────────────────
        apex = move + vol + mom

        # ── Gate filter ───────────────────────────────────────
        #
        # Uses gates from config.TIERS — single source of truth.
        # T3 gate=22: passes 11%+ moves with $500K vol (APEX≈26)
        # T4 gate=52: passes all 20%+ moves with $300K vol (APEX≈61)
        #
        tier_id  = self.classify_tier(abs_pct) or "T3"
        apex_min = TIERS[tier_id]["apex_gate"]

        gate_vol  = tick.vol_usd >= 300_000
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
            hurst_proxy  = round(mom / 10, 2),
            gates_passed = 2 - len(failed),
            all_gates    = len(failed) == 0,
            failed_gate  = ",".join(failed),
        )

    def build_signal(self, tick: TickData, layers: LayerScores,
                     is_new_listing: bool = False,
                     signal_reason: str = "new_coin",
                     market_condition: str = "") -> Signal:
        tier      = self.classify_tier(abs(tick.pct))
        direction = "PUMP" if tick.pct > 0 else "DUMP"
        trade     = self.calculator.calculate(tick, layers, tier, direction)
        return Signal(
            tick.symbol, tick.price, tick.vol_usd, tick.pct,
            direction, tier, layers, layers.APEX, tick.ts,
            trade, is_new_listing, signal_reason, market_condition,
        )
