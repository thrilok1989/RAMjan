"""MIOS V6 — the Market Memory card (Stage 54)."""

from __future__ import annotations

from typing import Any, Dict, Optional

_TREND = {"increasing": ("↑", "#00ff88"), "decreasing": ("↓", "#ff4444"),
          "steady": ("→", "#cfd9e6")}


def memory_panel_html(data: Optional[Dict[str, Any]]) -> str:
    d = data or {}
    rows = d.get("rows") or []
    if not rows:
        return ""
    out = [
        f"<div style='background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
        f"padding:10px 12px;margin-bottom:8px'>",
        f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
        f"margin-bottom:3px'>🧠 Market Memory</div>",
    ]
    for r in rows[:6]:
        arrow, tcol = _TREND.get(r.get("trend"), ("→", "#cfd9e6"))
        risk = int(r.get("transition_risk") or 0)
        rcol = "#ff4444" if risk >= 55 else "#ffcc33" if risk >= 30 else "#b3c2d4"
        out.append(
            f"<div style='display:flex;align-items:center;gap:8px;margin-top:3px'>"
            f"<span style='width:92px;font-size:11.5px;color:#cfd9e6'>"
            f"{r.get('label')}</span>"
            f"<span style='width:120px;font-size:12.5px;font-weight:800;"
            f"color:#ffffff'>{str(r.get('state')).replace('_', ' ').title()}</span>"
            f"<span style='width:52px;font-size:12px;color:#edf3f9'>"
            f"{float(r.get('duration_min') or 0):.0f} min</span>"
            f"<span style='color:#ffd000;font-size:11.5px'>{r.get('stars_str', '')}</span>"
            f"<span style='color:{tcol};font-size:13px'>{arrow}</span>"
            + (f"<span style='color:{rcol};font-size:10.5px'>risk {risk}%</span>"
               if risk >= 30 else "") + "</div>")
    if d.get("thesis"):
        out.append(f"<div style='margin-top:7px;padding-top:6px;border-top:1px "
                   f"solid #1e2836;font-size:12.5px;color:#dfe7f0;"
                   f"line-height:1.45'>🤖 {d['thesis']}</div>")
    out.append("</div>")
    return "".join(out)


def render_memory_panel(data: Optional[Dict[str, Any]]) -> None:
    html = memory_panel_html(data)
    if not html:
        return
    import streamlit as st
    st.markdown(html, unsafe_allow_html=True)


def memory_line(payload: Optional[Dict[str, Any]]) -> str:
    """Trade Card line — how established the current state is."""
    p = payload or {}
    if not p.get("state"):
        return ""
    dur = float(p.get("state_duration_min") or 0)
    stars = "★" * int(p.get("state_stars") or 0)
    col = ("#ff9500" if p.get("state_fresh") else
           "#ff4444" if int(p.get("state_transition_risk") or 0) >= 55 else "#cfd9e6")
    tail = (" — too young to act on" if p.get("state_fresh") else "")
    return (f"<div style='text-align:center;font-size:13.5px;margin-top:3px;"
            f"font-weight:700;color:{col}'>🧠 held {dur:.0f} min "
            f"<span style='color:#ffd000'>{stars}</span>{tail}</div>")
