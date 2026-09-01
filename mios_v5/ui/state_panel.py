"""MIOS V6 — the Market State card (Stage 48)."""

from __future__ import annotations

from typing import Any, Dict, Optional
from .theme import bias_tone

_URGENT = {"TRAP_ACTIVE": "#ff2d55", "WAR_ZONE": "#a78bfa",
           "REVERSAL_BUILDING": "#ff9500", "COMPRESSION": "#ffcc33",
           "WAIT": "#cfd9e6"}


def _col(d: Dict[str, Any]) -> str:
    return _URGENT.get(d.get("state"), bias_tone(d.get("tone"), "#ffd000"))


def state_panel_html(data: Optional[Dict[str, Any]]) -> str:
    d = data or {}
    if not d.get("state"):
        return ""
    col = _col(d)
    rows = [
        f"<div style='background:#0b0f16;border:2px solid {col};border-radius:10px;"
        f"padding:10px 12px;margin-bottom:8px'>",
        f"<div style='font-size:11px;letter-spacing:.12em;color:#cfd9e6;"
        f"text-transform:uppercase'>Market State</div>",
        f"<div style='font-size:23px;font-weight:900;color:{col};line-height:1.15'>"
        f"{d.get('label', '')}</div>",
        f"<div style='font-size:12px;color:#cfd9e6;margin-top:1px'>"
        f"confidence {d.get('confidence', 0)}%</div>",
    ]
    for r in (d.get("reasons") or [])[:4]:
        rows.append(f"<div style='font-size:12.5px;margin-top:2px;color:#edf3f9'>"
                    f"• {r}</div>")
    if d.get("next_state"):
        np_ = int(d.get("next_probability") or 0)
        ncol = "#ff9500" if np_ >= 70 else "#cfd9e6"
        rows.append(
            f"<div style='margin-top:7px;padding-top:6px;border-top:1px solid #1e2836;"
            f"font-size:13px;color:#edf3f9'>➡️ Next likely: "
            f"<b style='color:{ncol}'>{d.get('next_label')}</b> "
            f"<span style='color:{ncol}'>{np_}%</span></div>")
    rows.append("</div>")
    return "".join(rows)


def render_state_panel(data: Optional[Dict[str, Any]]) -> None:
    html = state_panel_html(data)
    if not html:
        return
    import streamlit as st
    st.markdown(html, unsafe_allow_html=True)


def state_line(data: Optional[Dict[str, Any]]) -> str:
    """Trade Card line — the personality plus what's coming."""
    d = data or {}
    if not d.get("state") or d.get("state") == "WAIT":
        return ""
    col = _col(d)
    nxt = ""
    if d.get("next_state") and int(d.get("next_probability") or 0) >= 60:
        nxt = (f" <span style='color:#dfe7f0;font-weight:600'>→ "
               f"{d.get('next_label')} {d.get('next_probability')}%</span>")
    return (f"<div style='text-align:center;font-size:15px;margin-top:4px;"
            f"font-weight:900;color:{col}'>🎭 {d.get('label', '')}{nxt}</div>")
