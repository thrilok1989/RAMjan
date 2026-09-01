"""MIOS V6 — the Institutional Participation card (Stage 43)."""

from __future__ import annotations

from typing import Any, Dict, Optional
from .theme import bias_tone



def absorption_panel_html(data: Optional[Dict[str, Any]]) -> str:
    d = data or {}
    b = d.get("behaviour")
    if not b or b == "NONE":
        return ""
    col = bias_tone(d.get("tone"), "#cfd9e6")
    dur = int(d.get("duration_cycles") or 0)
    return (
        f"<div style='background:#0b0f16;border:2px solid {col};border-radius:10px;"
        f"padding:10px 12px;margin-bottom:8px'>"
        f"<div style='font-size:11px;letter-spacing:.12em;color:#cfd9e6;"
        f"text-transform:uppercase'>🏛 Institutional Participation</div>"
        f"<div style='font-size:19px;font-weight:900;color:{col};line-height:1.2'>"
        f"{d.get('label', '')}</div>"
        f"<div style='font-size:12.5px;margin-top:3px;color:#edf3f9'>"
        f"Confidence <b style='color:#fff'>{d.get('confidence', 0)}%</b> · "
        f"<span style='color:#ffd000'>{d.get('stars', '')}</span>"
        + (f" · {dur} cycles" if dur else "") + "</div>"
        + "".join(f"<div style='font-size:12px;margin-top:2px;color:#dfe7f0'>"
                  f"• {r}</div>" for r in (d.get("reasons") or [])[:3])
        + f"<div style='font-size:12.5px;margin-top:4px;font-weight:700;"
          f"color:{col}'>➡️ {d.get('expectation', '')}</div>"
        + (f"<div style='margin-top:6px;padding-top:5px;border-top:1px solid "
           f"#1e2836;font-size:12px;color:#dfe7f0;line-height:1.45'>🤖 "
           f"{d['thesis']}</div>" if d.get("thesis") else "")
        + "</div>")


def render_absorption_panel(data: Optional[Dict[str, Any]]) -> None:
    html = absorption_panel_html(data)
    if not html:
        return
    import streamlit as st
    st.markdown(html, unsafe_allow_html=True)


def absorption_line(data: Optional[Dict[str, Any]]) -> str:
    """Trade Card line — the institutional footprint, when there is one."""
    d = data or {}
    if not d.get("behaviour") or d["behaviour"] == "NONE":
        return ""
    col = bias_tone(d.get("tone"), "#cfd9e6")
    return (f"<div style='text-align:center;font-size:14px;margin-top:4px;"
            f"font-weight:800;color:{col}'>🏛 {d.get('label', '')} "
            f"{d.get('confidence', 0)}%</div>")
