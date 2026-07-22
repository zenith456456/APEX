"""
state.py — Signal deduplication state machine (Step 2).

Decision tree — NO TIMER, pure state:
  1. No prior state for coin         → FIRE   (reason: FIRST)
  2. Prior state exists, RESOLVED    → FIRE   (reason: SL_HIT | ALL_TP)
  3. Prior state ACTIVE, dir flipped → FIRE   (reason: FLIP)
  4. Prior state ACTIVE, same dir    → SUPPRESS

Persisted to JSON so state survives container restarts.
"""
import json
import os
from datetime import datetime, timezone

from src.config import STATE_FILE, DATA_DIR
from src.logger import log


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SignalState:
    __slots__ = (
        "signal_id", "pair", "direction", "entry", "sl",
        "tps", "tps_hit", "final_result", "status",
        "fired_at", "resolved_at",
    )

    def __init__(self, signal_id, pair, direction, entry, sl, tps):
        self.signal_id    = signal_id
        self.pair         = pair
        self.direction    = direction   # "LONG" | "SHORT"
        self.entry        = entry
        self.sl           = sl
        self.tps          = list(tps)
        self.tps_hit      = [False] * 5
        self.final_result = None        # None | "TP1".."TP5" | "SL"
        self.status       = "ACTIVE"    # "ACTIVE" | "RESOLVED"
        self.fired_at     = _now()
        self.resolved_at  = None

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}

    @classmethod
    def from_dict(cls, d: dict) -> "SignalState":
        obj = cls.__new__(cls)
        for k in cls.__slots__:
            setattr(obj, k, d.get(k))
        return obj


class StateEngine:
    def __init__(self):
        self._memory: dict[str, SignalState] = {}
        self._id_seq: int = 0
        self._load()

    # ── Core decision ──────────────────────────────────────────────────────────

    def ingest(self, pair: str, direction: str,
               entry: float, sl: float, tps: list) -> tuple[str, str]:
        """
        Evaluate an incoming raw signal.
        Returns (decision, reason):
          decision : "FIRE" | "SUPPRESS"
          reason   : "FIRST" | "SL_HIT" | "ALL_TP" | "FLIP" | "SUPPRESS"
        """
        existing = self._memory.get(pair)

        if existing is None:
            decision, reason = "FIRE", "FIRST"

        elif existing.status == "RESOLVED":
            reason   = "SL_HIT" if existing.final_result == "SL" else "ALL_TP"
            decision = "FIRE"

        elif existing.direction != direction:
            decision, reason = "FIRE", "FLIP"

        else:
            decision, reason = "SUPPRESS", "SUPPRESS"

        if decision == "FIRE":
            self._id_seq += 1
            self._memory[pair] = SignalState(
                self._id_seq, pair, direction, entry, sl, tps
            )
            self._save()
            log.debug(f"STATE FIRE   {pair} {direction}  reason={reason}")
        else:
            log.debug(f"STATE SUPP   {pair} {direction}  (still active, same direction)")

        return decision, reason

    # ── Outcome tracking ───────────────────────────────────────────────────────

    def hit_tp(self, pair: str, tp_index: int) -> bool:
        """Mark tp_index (0-based) as hit. Returns True when ALL TPs are hit."""
        s = self._memory.get(pair)
        if not s or s.status != "ACTIVE":
            return False
        s.tps_hit[tp_index] = True
        highest = max(i for i, v in enumerate(s.tps_hit) if v)
        s.final_result = f"TP{highest + 1}"
        all_done = all(s.tps_hit)
        if all_done:
            s.status      = "RESOLVED"
            s.resolved_at = _now()
            log.info(f"TRADE CLOSED {pair} — all TPs hit")
        self._save()
        return all_done

    def hit_sl(self, pair: str):
        s = self._memory.get(pair)
        if not s or s.status != "ACTIVE":
            return
        s.status       = "RESOLVED"
        s.final_result = "SL"
        s.resolved_at  = _now()
        log.info(f"TRADE CLOSED {pair} — SL hit")
        self._save()

    def get(self, pair: str) -> SignalState | None:
        return self._memory.get(pair)

    # ── Persistence ────────────────────────────────────────────────────────────

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(
                    {"id_seq": self._id_seq,
                     "memory": {k: v.to_dict() for k, v in self._memory.items()}},
                    f, indent=2,
                )
        except Exception as e:
            log.error(f"State save failed: {e}")

    def _load(self):
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE) as f:
                p = json.load(f)
            self._id_seq = p.get("id_seq", 0)
            self._memory = {
                k: SignalState.from_dict(v)
                for k, v in p.get("memory", {}).items()
            }
            log.info(f"State loaded — {len(self._memory)} coins tracked")
        except Exception as e:
            log.error(f"State load failed: {e}")
