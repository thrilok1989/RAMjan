"""MIOS V6 — the Signal Validity panel (Stage 51).

    ──────────────────────────
    SIGNAL VALIDITY
    🟢 VALID  94%   ★★★★★
    ✅ Bias · HTF · Dealer · Institutions · Order Flow · Zone · Trap · Energy
    ──────────────────────────

or, far more usefully:

    🔴 INVALID  41%  ★★☆☆☆
    ❌ HTF Conflict · ❌ Weak Zone · ❌ Flow Shift · ❌ No Trap Confirmation
    Decision: WAIT

Every refusal explains itself — a rejection nobody understands is a rejection
nobody trusts.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def validity_panel_html(data: Optional[Dict[str, Any]]) -> str:
    d = data or {}
    active, proposed = d.get("active"), d.get("proposed")
    if not active:
        both = [f"{k} {(d.get(k) or {}).get('pct', 0)}%" for k in ("CALL", "PUT")
                if d.get(k)]
        if not both:
            return ""
        return (f"<div style='background:#0d1117;border:1px solid #1e2836;"
                f"border-radius:10px;padding:9px 12px;margin-bottom:8px'>"
                f"<div style='font-size:12px;letter-spacing:.10em;color:#cfd9e6;"
                f"text-transform:uppercase'>Signal Validity</div>"
                f"<div style='font-size:13px;color:#dfe7f0;margin-top:2px'>"
                f"No side proposed — {' · '.join(both)}</div></div>")

    ok = active.get("valid")
    col = "#00ff88" if ok else "#ff4444"
    em = "🟢" if ok else "🔴"
    rows = [
        f"<div style='background:#0b0f16;border:2px solid {col};border-radius:10px;"
        f"padding:10px 12px;margin-bottom:8px'>",
        f"<div style='font-size:11px;letter-spacing:.12em;color:#cfd9e6;"
        f"text-transform:uppercase'>Signal Validity · {proposed or ''}</div>",
        f"<div style='font-size:22px;font-weight:900;color:{col};line-height:1.15'>"
        f"{em} {active.get('verdict', '')} "
        f"<span style='font-size:19px'>{active.get('pct', 0)}%</span> "
        f"<span style='color:#ffd000;font-size:16px'>{active.get('stars', '')}</span>"
        f"</div>",
    ]
    if active.get("passed"):
        rows.append(f"<div style='font-size:12.5px;margin-top:4px;color:#7fe8b0'>"
                    f"✅ " + " · ".join(active["passed"]) + "</div>")
    for r in (active.get("reasons") or [])[:5]:
        rows.append(f"<div style='font-size:12.5px;margin-top:2px;color:#ff9d9d'>"
                    f"❌ {r}</div>")
    if not ok:
        rows.append(f"<div style='margin-top:6px;font-size:15px;font-weight:900;"
                    f"color:{col};text-align:center'>WAIT</div>")
    cov = active.get("coverage")
    if cov is not None and cov < 100:
        rows.append(f"<div style='font-size:10.5px;color:#b3c2d4;margin-top:4px'>"
                    f"evidence coverage {cov}% — unavailable checks are not "
                    f"counted as passes</div>")
    rows.append("</div>")
    return "".join(rows)


def render_validity_panel(data: Optional[Dict[str, Any]]) -> None:
    html = validity_panel_html(data)
    if not html:
        return
    import streamlit as st
    st.markdown(html, unsafe_allow_html=True)


def validity_line(active: Optional[Dict[str, Any]]) -> str:
    """Compact Trade Card line."""
    if not active or active.get("verdict") == "UNKNOWN":
        return ""
    ok = active.get("valid")
    col = "#00ff88" if ok else "#ff4444"
    why = ""
    if not ok and active.get("reasons"):
        why = (f" <span style='color:#dfe7f0;font-weight:600'>— "
               f"{active['reasons'][0][:52]}</span>")
    return (f"<div style='text-align:center;font-size:14px;margin-top:4px;"
            f"font-weight:800;color:{col}'>🚦 Validity {active.get('pct', 0)}% "
            f"{active.get('verdict', '')}{why}</div>")
