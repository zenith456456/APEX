"""
Signal deduplication state machine — no timer, pure state.

Decision:
  1. No prior state        → FIRE   (FIRST)
  2. Prior RESOLVED        → FIRE   (SL_HIT | ALL_TP)
  3. Prior ACTIVE + flip   → FIRE   (FLIP)
  4. Prior ACTIVE + same   → SUPPRESS
"""
import json, os
from datetime import datetime, timezone
import config
from logger import log


def _now(): return datetime.now(timezone.utc).isoformat()


class SignalState:
    __slots__ = ("signal_id","pair","direction","entry","sl",
                 "tps","tps_hit","final_result","status","fired_at","resolved_at")

    def __init__(self, signal_id, pair, direction, entry, sl, tps):
        self.signal_id    = signal_id
        self.pair         = pair
        self.direction    = direction
        self.entry        = entry
        self.sl           = sl
        self.tps          = list(tps)
        self.tps_hit      = [False] * 5
        self.final_result = None
        self.status       = "ACTIVE"
        self.fired_at     = _now()
        self.resolved_at  = None

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    @classmethod
    def from_dict(cls, d):
        obj = cls.__new__(cls)
        for k in cls.__slots__: setattr(obj, k, d.get(k))
        return obj


class StateEngine:
    def __init__(self):
        self._memory = {}
        self._id_seq = 0
        self._load()

    def ingest(self, pair, direction, entry, sl, tps):
        ex = self._memory.get(pair)
        if ex is None:
            decision, reason = "FIRE", "FIRST"
        elif ex.status == "RESOLVED":
            decision, reason = "FIRE", "SL_HIT" if ex.final_result == "SL" else "ALL_TP"
        elif ex.direction != direction:
            decision, reason = "FIRE", "FLIP"
        else:
            decision, reason = "SUPPRESS", "SUPPRESS"

        if decision == "FIRE":
            self._id_seq += 1
            self._memory[pair] = SignalState(self._id_seq, pair, direction, entry, sl, tps)
            self._save()
            log.debug(f"STATE FIRE  {pair} {direction}  reason={reason}")
        else:
            log.debug(f"STATE SUPP  {pair} {direction}  still active")
        return decision, reason

    def hit_tp(self, pair, tp_index):
        s = self._memory.get(pair)
        if not s or s.status != "ACTIVE": return False
        s.tps_hit[tp_index] = True
        highest = max(i for i, v in enumerate(s.tps_hit) if v)
        s.final_result = f"TP{highest+1}"
        if all(s.tps_hit):
            s.status = "RESOLVED"; s.resolved_at = _now()
            log.info(f"CLOSED {pair} — all TPs hit")
        self._save()
        return all(s.tps_hit)

    def hit_sl(self, pair):
        s = self._memory.get(pair)
        if not s or s.status != "ACTIVE": return
        s.status = "RESOLVED"; s.final_result = "SL"; s.resolved_at = _now()
        log.info(f"CLOSED {pair} — SL hit")
        self._save()

    def get(self, pair): return self._memory.get(pair)

    def _save(self):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        try:
            with open(config.STATE_FILE, "w") as f:
                json.dump({"id_seq": self._id_seq,
                           "memory": {k: v.to_dict() for k,v in self._memory.items()}}, f, indent=2)
        except Exception as e: log.error(f"State save: {e}")

    def _load(self):
        if not os.path.exists(config.STATE_FILE): return
        try:
            with open(config.STATE_FILE) as f: p = json.load(f)
            self._id_seq = p.get("id_seq", 0)
            self._memory = {k: SignalState.from_dict(v) for k,v in p.get("memory",{}).items()}
            log.info(f"State loaded — {len(self._memory)} coins tracked")
        except Exception as e: log.error(f"State load: {e}")
