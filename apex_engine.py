"""
APEX ENGINE  v5  —  Pullback Entry + Dynamic Uncapped R:R
═══════════════════════════════════════════════════════════
KEY INSIGHT: Signals fire when a coin has ALREADY moved 10–70%+.
Entering at that extended price means:
  • SL must be 20%+ wide to avoid noise → TP3 needs 80%+ → unrealistic
  • The move is partially over → higher reversal risk

FIX: PULLBACK ENTRY STRATEGY
  Instead of entering at the current extended price, we set the
  limit order at a slight RETRACEMENT into the trend:
    DUMP (SHORT): entry = 2.5% ABOVE current (wait for small bounce)
    PUMP (LONG) : entry = 2.5% BELOW current (wait for small dip)

  This catches the coin at a BETTER price after the big move,
  with a TIGHT stop-loss (3–5%) close to the entry.
  TP3 (R:R 1:3) becomes 9–15% away — fully achievable on
  a coin that has already moved 20–70%.

DYNAMIC UNCAPPED R:R:
  rr_max = max(6.0, abs_pct / sl_pct × 0.7)
  
  Examples:
    T3  15%  sl=3%  →  rr_max = max(6, 15/3×0.7) = max(6, 3.5) = 6.0
    T4  25%  sl=4%  →  rr_max = max(6, 25/4×0.7) = max(6, 4.4) = 6.0
    T4  40%  sl=5%  →  rr_max = max(6, 40/5×0.7) = max(6, 5.6) = 6.0
    T4  67%  sl=4%  →  rr_max = max(6, 67/4×0.7) = max(6,11.7) = 11.7
    T4  90%  sl=5%  →  rr_max = max(6, 90/5×0.7) = max(6,12.6) = 12.6

5 TAKE PROFIT LEVELS (always shown):
  TP1  R:R 1:1   close 15%  (quick scalp confirmation)
  TP2  R:R 1:2   close 20%  (partial profit)
  TP3  R:R 1:3   close 25%  ← user's main target
  TP4  R:R 1:(rr_max×0.6)  close 20%
  TP5  R:R 1:rr_max         close 20%  ← maximum, no cap

T3 gate ≥ 82  |  T4 gate ≥ 78  (unchanged)
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
    FMT         : int   = 0   # MOVE score (0-50)
    LVI         : int   = 0   # VOL  score (0-35)
    WAS         : int   = 0   # MOM  score (0-15)
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
    tp1         : float   # R:R 1:1    close 15%
    tp2         : float   # R:R 1:2    close 20%
    tp3         : float   # R:R 1:3    close 25%  ← main target
    tp4         : float   # R:R 1:rr×0.6  close 20%
    tp5         : float   # R:R 1:rr_max  close 20%  (no cap)
    sl_pct      : float
    rr_max      : float   # dynamic, uncapped
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
    if apex >= 95: return "S+  ELITE"
    if apex >= 90: return "S   PRIME"
    if apex >= 85: return "A+  STRONG"
    if apex >= 82: return "A   SOLID"
    return              "B+  PASS"

def hold_str(minutes: int) -> str:
    if minutes < 60: return f"~{minutes} min"
    h = minutes // 60; m = minutes % 60
    return f"~{h}h {m:02d}m" if m else f"~{h}h"


# ── Trade calculator ──────────────────────────────────────────

class TradeCalculator:
    # Hold times per style (minutes)
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
        if tier == "T4":
            if abs_pct >= 40.0: style = "ultra"
            elif apex >= 85:    style = "swing"
            else:               style = "day"
        else:  # T3
            if apex >= 95:   style = "power"
            elif apex >= 88: style = "swing"
            else:            style = "day"

        base_lev, sl_pct = TRADE_PRESETS.get((tier, style), (7, 4.0))

        # ── Leverage scales with APEX ─────────────────────────
        lev = max(1, int(base_lev * (0.80 + _clamp((apex - 78) / 22, 0, 1) * 0.20)))

        # ── ENTRY AT CURRENT PRICE (near bottom/top of move) ─
        # We enter as close to the current market price as possible.
        # This is near the BOTTOM of a dump (for SHORT) or TOP of a
        # pump (for LONG) — the best entry point after the big move.
        # A tight limit band of ±0.15% around spot to ensure fill.
        pos = "LONG" if direction == "PUMP" else "SHORT"

        if direction == "PUMP":
            # LONG: enter near current price, SL below entry
            el = price * (1 - 0.002)       # limit low  (0.2% below spot)
            eh = price * (1 + 0.001)       # limit high (0.1% above spot)
            er = (el + eh) / 2             # reference  ≈ spot
            sl = er * (1 - sl_pct / 100)   # SL below entry (tight)
            rp = sl_pct                    # risk % = sl_pct
            # TPs: above entry — coin continues pumping
            tp1 = er * (1 + rp / 100 * 1.0)
            tp2 = er * (1 + rp / 100 * 2.0)
            tp3 = er * (1 + rp / 100 * 3.0)
        else:
            # SHORT: enter near current price, SL above entry
            el = price * (1 - 0.001)       # limit low  (0.1% below spot)
            eh = price * (1 + 0.002)       # limit high (0.2% above spot)
            er = (el + eh) / 2             # reference  ≈ spot
            sl = er * (1 + sl_pct / 100)   # SL above entry (tight)
            rp = sl_pct                    # risk % = sl_pct
            # TPs: below entry — coin continues dumping
            tp1 = er * (1 - rp / 100 * 1.0)
            tp2 = er * (1 - rp / 100 * 2.0)
            tp3 = er * (1 - rp / 100 * 3.0)

        # ── Dynamic uncapped R:R ──────────────────────────────
        # Larger the move already made → more room to continue.
        # rr_max = max(6, move_pct / sl_pct × 0.7) — no hard cap.
        # T4 -67%: rr_max = max(6, 67/4×0.7) = 11.7  → TP5 = 47% away
        # T4 -90%: rr_max = max(6, 90/5×0.7) = 12.6  → TP5 = 63% away
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

        # ── MOVE (0-50) ───────────────────────────────────────
        if abs_pct < 20.0:
            move = int(_clamp((abs_pct - 10.0) * 5.0, 0, 50))
        else:
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
        mom = 8
        if len(history) >= 2:
            recent = [h.pct for h in history[-5:]] + [tick.pct]
            strengthening = sum(
                1 for i in range(1, len(recent))
                if (recent[i] - recent[i-1]) * direction > 0
            )
            ratio = strengthening / max(len(recent) - 1, 1)
            mom   = int(_clamp(ratio * 15, 0, 15))

        # ── APEX composite ─────────────────────────────────────
        apex = move + vol + mom

        # ── 2-gate filter  (T3 ≥ 82, T4 ≥ 78 — DO NOT CHANGE) ─
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
