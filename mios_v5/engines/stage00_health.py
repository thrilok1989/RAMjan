"""MIOS V5 — Stage 0: System Health & Diagnostics Engine.

Purpose (spec): ensure the entire MIOS system is healthy before market
analysis begins, and keep scoring health on every cycle.

Inputs (from MarketState.raw, supplied by the host app):
    api_ok          bool | None   — Dhan API reachable this cycle
    db_ok           bool | None   — Supabase reachable
    last_data_ts    ISO str | None — timestamp of freshest market data
    token_expired   bool          — Dhan token flag
    rate_limited    bool          — Dhan 429 back-off active
    _run_report     RunReport     — injected by the orchestrator (previous
                                    engines this pass; Stage 0 runs FIRST so
                                    it scores the PREVIOUS pass stored in
                                    raw['prev_report'] as well)

Output:
    data = {
        health_score: 0–100,
        api: OK|DOWN|UNKNOWN, db: ..., data_freshness_s: float|None,
        engine_report: {ok, degraded, neutral, errors, disabled} | None,
        active_errors: [error rows],
    }
Also persists new error rows to Supabase (engine_errors table, migration
009) through the db handle in raw['db'], throttled per engine+reason.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ..core.contract import (
    Bias, Engine, EngineError, EngineResult, ErrorType, IST, MarketState,
    Provenance, Severity, Status, Tier,
)


class HealthEngine(Engine):
    name = "stage00_health"
    stage = 0
    deps: List[str] = []          # runs first

    #: seconds after which market data is considered stale during hours
    STALE_AFTER_S = 120

    def compute(self, state: MarketState) -> EngineResult:
        raw = state.raw
        now = datetime.now(IST)
        evidence: List[str] = []
        errors: List[EngineError] = []
        score = 100.0

        # ── API / token / rate-limit ─────────────────────────────────
        api_ok: Optional[bool] = raw.get("api_ok")
        if raw.get("token_expired"):
            api_state = "DOWN"
            score -= 40
            errors.append(EngineError(
                engine=self.name, error_type=ErrorType.MISSING_API,
                reason="Dhan access token expired", severity=Severity.CRITICAL,
                data_source="dhan:auth"))
            evidence.append("🔑 Dhan token expired — all live feeds down")
        elif raw.get("rate_limited"):
            api_state = "THROTTLED"
            score -= 15
            errors.append(EngineError(
                engine=self.name, error_type=ErrorType.TIMEOUT,
                reason="Dhan 429 back-off active (DH-904)",
                severity=Severity.WARNING, data_source="dhan:ratelimit",
                recovery="retrying"))
            evidence.append("⏳ Dhan rate-limited — serving cached data")
        elif api_ok is False:
            api_state = "DOWN"
            score -= 35
            errors.append(EngineError(
                engine=self.name, error_type=ErrorType.MISSING_API,
                reason="Dhan API unreachable", severity=Severity.CRITICAL,
                data_source="dhan:api"))
            evidence.append("🔌 Dhan API unreachable")
        elif api_ok is True:
            api_state = "OK"
            evidence.append("✅ Dhan API reachable")
        else:
            api_state = "UNKNOWN"
            score -= 5
            evidence.append("❔ API status not reported this cycle")

        # ── Database ─────────────────────────────────────────────────
        db_ok: Optional[bool] = raw.get("db_ok")
        if db_ok is False:
            db_state = "DOWN"
            score -= 20
            errors.append(EngineError(
                engine=self.name, error_type=ErrorType.MISSING_API,
                reason="Supabase unreachable — persistence/logging offline",
                severity=Severity.ERROR, data_source="supabase"))
            evidence.append("🗄️ Supabase DOWN — nothing is being persisted")
        elif db_ok is True:
            db_state = "OK"
            evidence.append("✅ Supabase connected")
        else:
            db_state = "UNKNOWN"
            evidence.append("❔ Supabase status not reported")

        # ── Data freshness ───────────────────────────────────────────
        fresh_s: Optional[float] = None
        last_ts = raw.get("last_data_ts")
        if last_ts:
            try:
                dt = datetime.fromisoformat(str(last_ts))
                if dt.tzinfo is None:
                    dt = IST.localize(dt)
                fresh_s = (now - dt).total_seconds()
                if fresh_s > self.STALE_AFTER_S:
                    score -= 20
                    errors.append(EngineError(
                        engine=self.name, error_type=ErrorType.STALE_DATA,
                        reason=f"market data {fresh_s:.0f}s old "
                               f"(> {self.STALE_AFTER_S}s)",
                        severity=Severity.WARNING, data_source="dhan:feed"))
                    evidence.append(f"🕒 Data stale: {fresh_s:.0f}s old")
                else:
                    evidence.append(f"✅ Data fresh ({fresh_s:.0f}s)")
            except Exception:
                evidence.append("❔ Could not parse last_data_ts")

        # ── Previous pipeline pass (engine execution health) ─────────
        engine_report: Optional[Dict[str, Any]] = None
        prev = raw.get("prev_report")
        if prev is not None:
            try:
                engine_report = {
                    "ok": prev.ok, "degraded": prev.degraded,
                    "neutral": prev.neutral, "errors": prev.errors,
                    "disabled": prev.disabled,
                    "health_pct": prev.health_pct,
                    "total_runtime_ms": prev.total_runtime_ms,
                }
                if prev.errors:
                    score -= min(prev.errors * 8, 25)
                    evidence.append(
                        f"⚠️ {prev.errors} engine error(s) last pass")
                else:
                    evidence.append(
                        f"✅ engines last pass: {prev.ok} OK / "
                        f"{prev.neutral} neutral / {prev.disabled} disabled")
            except Exception:
                pass

        score = max(0.0, min(100.0, score))

        # ── Persist NEW error rows (throttled) to Supabase ───────────
        self._persist_errors(raw, errors)

        risks = [e.reason for e in errors
                 if e.severity in (Severity.ERROR, Severity.CRITICAL)]
        return EngineResult(
            engine=self.name,
            status=Status.OK if score >= 60 else Status.DEGRADED,
            bias=Bias.NONE,
            confidence=score,
            evidence=evidence,
            risks=risks,
            data={
                "health_score": round(score, 1),
                "api": api_state,
                "db": db_state,
                "data_freshness_s": fresh_s,
                "engine_report": engine_report,
                "active_errors": [e.to_row() for e in errors],
            },
            provenance=Provenance(source="mios:self", tier=Tier.DERIVED,
                                  freshness_ts=now.isoformat()),
            errors=errors,
        )

    # -- persistence -----------------------------------------------------
    @staticmethod
    def _persist_errors(raw: Dict[str, Any],
                        errors: List[EngineError]) -> None:
        """Write error rows via the host's SupabaseDB handle. Throttled per
        (engine, reason) with a small in-memory cache in raw so repeated
        cycles don't spam identical rows. Failures are swallowed — the
        health engine must never take down the pipeline."""
        db = raw.get("db")
        if db is None or not errors:
            return
        seen: Dict[str, float] = raw.setdefault("_err_log_seen", {})
        import time as _t
        now_s = _t.time()
        for e in errors:
            key = f"{e.engine}|{e.error_type.value}|{e.reason[:80]}"
            if now_s - seen.get(key, 0) < 300:      # 5-min per-error throttle
                continue
            try:
                if getattr(db, "insert_engine_error", None):
                    db.insert_engine_error(e.to_row())
                    seen[key] = now_s
            except Exception:
                pass
