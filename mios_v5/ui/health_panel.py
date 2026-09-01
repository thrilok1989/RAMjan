"""MIOS V5 — Error Monitor / System Health panel (Stage 41 §System Monitor).

Renders the Stage-0 health result + engine status report + active errors.
Import-safe: streamlit/pandas are imported lazily so the core package stays
usable in tests without the app runtime.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..core.contract import EngineResult, Severity, Status
from ._bright import bright_caption as _bc


_SEV_EMOJI = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "🔴", "CRITICAL": "🚨"}
_STATUS_EMOJI = {"OK": "🟢", "DEGRADED": "🟡", "NEUTRAL": "⚪",
                 "ERROR": "🔴", "DISABLED": "⛔"}


def render_health_panel(state=None, db=None) -> None:
    """Render System Health + Error Monitor.

    state — MarketState from the last orchestrator pass (optional)
    db    — SupabaseDB handle for persisted error history (optional)
    """
    import streamlit as st
    import pandas as pd

    st.markdown("#### ⚙️ MIOS V5 — System Health")

    health: Optional[EngineResult] = None
    if state is not None:
        health = state.get("stage00_health")

    if health is None:
        _bc("Health engine has not run yet this session.")
    else:
        d: Dict[str, Any] = health.data or {}
        score = d.get("health_score", 0)
        _col = "#00ff88" if score >= 80 else ("#ffd000" if score >= 60 else "#ff4444")
        st.markdown(
            f"<div style='background:#0d1117;border:2px solid {_col};"
            f"border-radius:10px;padding:10px 16px;margin-bottom:8px'>"
            f"<span style='font-size:20px;font-weight:800;color:{_col}'>"
            f"Health {score:.0f}/100</span>"
            f"<span style='color:#ffffff;font-size:12px'> · API {d.get('api', '—')}"
            f" · DB {d.get('db', '—')}"
            + (f" · data {d.get('data_freshness_s'):.0f}s old"
               if d.get("data_freshness_s") is not None else "")
            + "</span></div>",
            unsafe_allow_html=True,
        )
        for ev in (health.evidence or [])[:8]:
            _bc(ev)

        rep = d.get("engine_report")
        if rep:
            _bc(
                f"🧩 Engines last pass: {rep.get('ok', 0)} OK · "
                f"{rep.get('degraded', 0)} degraded · {rep.get('neutral', 0)} neutral · "
                f"{rep.get('errors', 0)} errors · {rep.get('disabled', 0)} disabled "
                f"(pipeline {rep.get('health_pct', 0)}% · "
                f"{rep.get('total_runtime_ms', 0):.0f}ms)")

    # per-engine status table from the last pass
    if state is not None and state.results:
        rows: List[Dict[str, Any]] = []
        for name, r in state.results.items():
            rows.append({
                "Engine": name,
                "Stage": r.stage if r.stage >= 0 else "-",
                "Status": f"{_STATUS_EMOJI.get(r.status.value, '·')} {r.status.value}",
                "Bias": r.bias.value,
                "Conf": f"{r.confidence:.0f}",
                "Tier": getattr(r.provenance.tier, "value", "-"),
                "ms": r.runtime_ms,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True)

    # ── Error Monitor ────────────────────────────────────────────────
    st.markdown("#### 🚨 Error Monitor")
    live_errs: List[Dict[str, Any]] = []
    if state is not None:
        for e in state.all_errors():
            live_errs.append(e.to_row())
    if live_errs:
        alarms = [e for e in live_errs if e["severity"] in ("ERROR", "CRITICAL")]
        warns = [e for e in live_errs if e["severity"] == "WARNING"]
        infos = [e for e in live_errs if e["severity"] == "INFO"]
        if alarms:
            st.error(f"{len(alarms)} active error(s)")
        for e in alarms + warns:
            _bc(f"{_SEV_EMOJI.get(e['severity'], '·')} "
                       f"**{e['engine']}** · {e['error_type']} · {e['reason']}")
        if infos:
            _bc(f"ℹ️ {len(infos)} known data-limit(s) "
                       "(structural — not failures): "
                       + " · ".join(sorted({e['engine'] for e in infos})))
    else:
        _bc("No live errors this pass. ✅")

    # persisted history (Supabase)
    if db is not None:
        try:
            hist = db.get_engine_errors() or []
            hist = [h for h in hist if h.get("severity") != "INFO"]
            if hist:
                _bc(f"🗄️ Today's persisted errors ({len(hist)}):")
                import pandas as pd  # noqa: F811 (lazy)
                cols = ["ts", "engine", "error_type", "severity", "reason",
                        "recovery"]
                df = pd.DataFrame(hist)
                df = df[[c for c in cols if c in df.columns]].head(20)
                st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception:
            pass
