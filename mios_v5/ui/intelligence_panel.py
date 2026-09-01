"""MIOS V5 — Intelligence panel (Phase-C engines).

Renders the Reaction Zone ⭐, Conflict, Time Cycle and Evolution outputs.
This is a preview of the Stage-41 dashboard sections; the full dashboard
lands in Phase D.
"""

from __future__ import annotations

from typing import Any, Dict

from ._bright import bright_caption as _bc

_BIAS_COLOR = {
    "STRONG_BULL": "#00ff88", "BULL": "#17c98b", "NEUTRAL": "#ffffff",
    "SIDEWAYS": "#f0b429", "BEAR": "#f0455a", "STRONG_BEAR": "#ff4444",
    "NONE": "#ffffff",
}


def render_intelligence_panel(state=None) -> None:
    import streamlit as st

    if state is None or not getattr(state, "results", None):
        _bc("MIOS intelligence warming up — first pipeline pass pending.")
        return

    rz = state.get("stage35_reaction_zone")
    cf = state.get("stage27_conflict")
    tc = state.get("stage06_timecycle")
    ev = state.get("stage29_evolution")

    # ── Reaction Zone ⭐ ─────────────────────────────────────────────
    st.markdown("#### ⚔️ Reaction Zone")
    if rz is None or rz.status.value == "NEUTRAL":
        _bc("Reaction Zone: warming up (needs spot + levels + engines).")
    else:
        d: Dict[str, Any] = rz.data or {}
        bz = d.get("battle_zone")
        col = _BIAS_COLOR.get(rz.bias.value, "#ffffff")
        if bz:
            probs = d.get("probabilities", {})
            _p = " · ".join(f"{k} {v}%" for k, v in probs.items())
            st.markdown(
                f"<div style='background:#0d1117;border:2px solid {col};"
                f"border-radius:10px;padding:10px 14px;margin-bottom:6px'>"
                f"<span style='font-size:16px;font-weight:800;color:{col}'>"
                f"{bz['type']} ₹{bz['price']:.0f} → {d.get('expected_winner')}</span>"
                f"<div style='font-family:monospace;font-size:12px;color:#ffffff'>"
                f"{_p} · buyers {d.get('buyer_strength')}% / "
                f"sellers {d.get('seller_strength')}%</div>"
                + (f"<div style='font-size:12px;color:#ffffff'>🎯 target "
                   f"₹{d.get('next_target'):.0f} · ❌ invalidation "
                   f"₹{d.get('invalidation'):.0f}</div>"
                   if d.get('next_target') and d.get('invalidation') else "")
                + "</div>",
                unsafe_allow_html=True)
        else:
            _bc(f"No active battle zone — spot mid-range "
                       f"(lean {rz.bias.value}).")
        for e in (rz.evidence or [])[:4]:
            _bc(e)

    # ── Conflict ─────────────────────────────────────────────────────
    if cf is not None and cf.status.value == "OK":
        d = cf.data or {}
        col = _BIAS_COLOR.get(cf.bias.value, "#ffffff")
        st.markdown(
            f"**⚖️ Conflict:** <span style='color:{col}'>{d.get('dominant')}</span> · "
            f"agreement {d.get('agreement_pct')}% · {d.get('severity')} conflict",
            unsafe_allow_html=True)
        if d.get("conflicts"):
            _bc("Against dominant: " + " · ".join(d["conflicts"]))

    # ── Time Cycle + Evolution ───────────────────────────────────────
    cols = st.columns(2)
    with cols[0]:
        if tc is not None and tc.data:
            _bc(f"🕒 **{tc.data.get('phase')}** "
                       f"(conviction {tc.data.get('conviction')}/100)")
    with cols[1]:
        if ev is not None and ev.data:
            ch = ev.data.get("changes") or []
            if ch:
                _bc("🔀 **Changed:** " + " · ".join(ch[:3]))
            else:
                _bc("🔀 No change since last pass")
