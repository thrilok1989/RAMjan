"""Stage 40 — Prediction Validation & Learning Engine.

In pure decision-support mode MIOS makes no trades, so it validates itself:
each pass it (1) grades any open predictions whose horizon has elapsed against
the realised spot move, (2) logs a fresh prediction of the current final read
(throttled, market hours, healthy, non-neutral), and (3) summarises accuracy
by confidence band. Persists to `bias_predictions` (migration 011).

Move thresholds (as % over the horizon):
    BULL correct  → move >= +0.08%      BEAR correct  → move <= -0.08%
    NEUTRAL/SIDE  → |move| < 0.15%
"""

from __future__ import annotations

import time as _time
from datetime import datetime, timedelta

from ..core.contract import (
    Bias, Engine, EngineResult, IST, MarketState, Status, Tier,
)
from ..final_read import build_final_read
from . import _adapters as A

_UP = 0.08
_FLAT = 0.15
_LOG_EVERY_S = 600          # log at most one prediction / 10 min
_HORIZON_MIN = 15


def _parse(ts):
    try:
        dt = datetime.fromisoformat(str(ts))
        return dt if dt.tzinfo else IST.localize(dt)
    except Exception:
        return None


def _grade(bias: str, move: float) -> bool:
    if bias in ("BULL", "STRONG_BULL"):
        return move >= _UP
    if bias in ("BEAR", "STRONG_BEAR"):
        return move <= -_UP
    return abs(move) < _FLAT      # NEUTRAL / SIDEWAYS


def _write_graded(db, graded) -> int:
    """Write the graded predictions, and return how many actually landed.

    One batched upsert first — predictions come due in clumps, so this is
    usually one round-trip instead of twenty. **Any shortfall falls back to one
    row at a time**, which is the behaviour this replaced.

    The fallback is not defensive padding. A grading pass that writes nothing
    loses predictions that have already matured: they were read as open,
    graded, and if the write is dropped they are still open next cycle with a
    `due_at` further in the past — measured, then forgotten, forever. The count
    returned is what reached the database, never what was attempted.
    """
    try:
        from db.write_batch import upsert_many
        report = upsert_many(db, "bias_predictions", graded, conflict="id")
        if not report.get("errors") and report.get("rows"):
            return int(report["rows"])
    except Exception:
        pass

    written = 0
    for row in graded:
        try:
            fields = dict(row)
            row_id = fields.pop("id", None)
            if row_id is not None and db.update_bias_prediction(row_id, fields):
                written += 1
        except Exception:
            pass
    return written


class LearningEngine(Engine):
    name = "stage40_learning"
    stage = 40
    deps = ["stage35_reaction_zone", "stage27_conflict", "stage05_regime"]

    def compute(self, state: MarketState) -> EngineResult:
        raw = state.raw
        db = raw.get("db")
        spot = raw.get("spot")
        now = datetime.now(IST)
        inj = raw.get("now_ist_dt")
        if isinstance(inj, datetime):
            now = inj
        if db is None or not spot:
            return EngineResult.neutral(
                self.name, "no db / spot — cannot log or grade predictions",
                data_source="supabase:bias_predictions")

        resolved = 0
        # ── 1) grade due predictions ─────────────────────────────────
        # Batched: predictions come due in clumps — every one logged in the same
        # window matures in the same window — so this loop used to issue one
        # round-trip per prediction to write a handful of small rows. Graded in
        # memory, written once.
        #
        # An update by primary key IS an upsert: the rows carry `id`, so the
        # conflict target is the key they already collide on and each row
        # updates in place. Nothing about what is written changes.
        graded = []
        try:
            for p in (db.get_open_bias_predictions() or []):
                due = _parse(p.get("due_at"))
                if due is None or now < due:
                    continue
                s0 = float(p.get("spot_at") or 0)
                if s0 <= 0:
                    continue
                move = (spot - s0) / s0 * 100
                correct = _grade(str(p.get("preferred_bias", "")), move)
                graded.append({
                    "id": p.get("id"),
                    "spot_then": round(float(spot), 2),
                    "realized_move": round(move, 3),
                    "correct": bool(correct),
                    "resolved_at": now.isoformat()})
        except Exception:
            pass

        if graded:
            resolved = _write_graded(db, graded)

        # ── 2) log a new prediction (throttled, market hours, healthy) ─
        logged = False
        try:
            market_open = now.time() >= now.time().replace(hour=9, minute=15) and \
                now.time() <= now.time().replace(hour=15, minute=30)
            # (robust hour check without replacing on the same object)
            market_open = (9, 15) <= (now.hour, now.minute) <= (15, 30)
            health = state.get("stage00_health")
            healthy = bool(health and (health.data or {}).get("health_score", 0) >= 60)
            thr = raw.get("_mios_pred_state")
            if isinstance(thr, dict):
                last = thr.get("last_pred_ts", 0)
            else:
                thr, last = {}, 0
            fr = build_final_read(state)
            pb = fr.get("preferred_bias")
            if (market_open and healthy and _time.time() - last > _LOG_EVERY_S
                    and pb not in ("NEUTRAL", "NONE")
                    and fr.get("confidence_tempered", 0) >= 40):
                secs = fr.get("sections", {})
                bz = fr.get("battle_zone") or {}
                row = {
                    "trading_day": now.strftime("%Y-%m-%d"),
                    "ts": now.isoformat(),
                    "due_at": (now + timedelta(minutes=_HORIZON_MIN)).isoformat(),
                    "horizon_min": _HORIZON_MIN,
                    "spot_at": round(float(spot), 2),
                    "preferred_bias": pb,
                    "confidence": fr.get("confidence_tempered"),
                    "conflict_severity": fr.get("conflict_severity"),
                    "battle_type": (bz.get("type") if bz else None),
                    "expected_winner": fr.get("expected_winner"),
                    "target": fr.get("next_target"),
                    "invalidation": fr.get("invalidation"),
                    "regime": fr.get("regime"),
                    "session_phase": fr.get("session_phase"),
                    "dealer_bias": secs.get("dealer", {}).get("bias"),
                    "intent_bias": secs.get("intent", {}).get("bias"),
                    "orderflow_bias": secs.get("orderflow", {}).get("bias"),
                }
                if db.insert_bias_prediction(row) is not None:
                    logged = True
                    thr["last_pred_ts"] = _time.time()
        except Exception:
            pass

        # ── 3) accuracy summary ──────────────────────────────────────
        acc = self._accuracy(db)

        evidence = []
        if acc["n"] >= 5:
            evidence.append(f"MIOS accuracy {acc['pct']}% over {acc['n']} graded "
                            f"predictions (avg move {acc['avg_move']:+.2f}%)")
            if acc.get("hi_conf_n", 0) >= 5:
                evidence.append(f"High-confidence (≥70%): {acc['hi_conf_pct']}% "
                                f"over {acc['hi_conf_n']}")
        else:
            evidence.append(f"Learning: {acc['n']} graded predictions so far "
                            "(need ≥5 for accuracy)")
        if resolved:
            evidence.append(f"Graded {resolved} prediction(s) this pass")
        if logged:
            evidence.append("Logged current read as a new prediction")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=float(acc.get("pct", 0) or 0),
            evidence=evidence,
            data={"accuracy": acc, "resolved_this_pass": resolved,
                  "logged_this_pass": logged},
            provenance=A.prov("mios:bias_predictions", Tier.DERIVED),
        )

    @staticmethod
    def _accuracy(db) -> dict:
        out = {"n": 0, "pct": 0, "avg_move": 0.0, "hi_conf_n": 0, "hi_conf_pct": 0}
        try:
            rows = db.get_bias_predictions(resolved_only=True) or []
        except Exception:
            rows = []
        graded = [r for r in rows if r.get("correct") is not None]
        if not graded:
            return out
        n = len(graded)
        wins = sum(1 for r in graded if r.get("correct"))
        moves = [float(r.get("realized_move") or 0) for r in graded]
        out["n"] = n
        out["pct"] = round(wins / n * 100)
        out["avg_move"] = round(sum(moves) / n, 3)
        hi = [r for r in graded if float(r.get("confidence") or 0) >= 70]
        if hi:
            out["hi_conf_n"] = len(hi)
            out["hi_conf_pct"] = round(sum(1 for r in hi if r.get("correct")) / len(hi) * 100)
        return out
