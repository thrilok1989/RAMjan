"""MIOS V6 — the Market Energy card (Stage 37)."""

from __future__ import annotations

from typing import Any, Dict, Optional

_COL = {"DEAD": "#666666", "COMPRESSION": "#ffcc33", "BUILDING": "#4da6ff",
        "EXPANSION": "#ff2d55", "RELEASED": "#cfd9e6"}


def _bar(label: str, pct: float, col: str) -> str:
    return (f"<div style='display:flex;align-items:center;gap:6px;margin-top:3px'>"
            f"<span style='width:112px;color:#cfd9e6;font-size:11px'>{label}</span>"
            f"<div style='flex:1;height:7px;background:#1e2836;border-radius:4px;"
            f"overflow:hidden'><div style='width:{max(2, pct)}%;height:100%;"
            f"background:{col}'></div></div>"
            f"<span style='width:36px;text-align:right;font-size:11px;"
            f"color:{col}'>{pct:.0f}%</span></div>")


def energy_panel_html(data: Optional[Dict[str, Any]]) -> str:
    d = data or {}
    if not d.get("ready"):
        return ""
    col = _COL.get(d.get("state"), "#cfd9e6")
    dur = int(d.get("duration_cycles") or 0)
    dur_txt = (f" · held {dur} cycle{'s' if dur != 1 else ''}" if dur else "")
    return (
        f"<div style='background:#0d1117;border:1px solid {col};border-radius:10px;"
        f"padding:10px 12px;margin-bottom:8px'>"
        f"<div style='font-size:11px;letter-spacing:.10em;color:#cfd9e6;"
        f"text-transform:uppercase'>⚡ Market Energy</div>"
        f"<div style='font-size:17px;font-weight:900;color:{col};line-height:1.2'>"
        f"{d.get('label', '')}</div>"
        f"<div style='font-size:12.5px;margin-top:2px;color:#edf3f9'>"
        f"Strength <b style='color:#fff'>{d.get('strength', 0)}%</b> "
        f"<span style='color:#ffd000'>{d.get('stars', '')}</span> · "
        f"breakout risk <b style='color:{col}'>{d.get('risk_label', '')}</b>"
        f"{dur_txt}</div>"
        + _bar("Compression", float(d.get("compression") or 0), "#ffcc33")
        + _bar("Expansion ready", float(d.get("expansion_readiness") or 0), "#4da6ff")
        + _bar("Release probability", float(d.get("release_probability") or 0), col)
        + f"<div style='font-size:12px;margin-top:5px;color:#dfe7f0;line-height:1.45'>"
          f"🤖 {d.get('advice', '')}</div></div>")


def render_energy_panel(data: Optional[Dict[str, Any]]) -> None:
    html = energy_panel_html(data)
    if not html:
        return
    import streamlit as st
    st.markdown(html, unsafe_allow_html=True)


def energy_line(data: Optional[Dict[str, Any]]) -> str:
    """Trade Card line — only when energy is actionable news."""
    d = data or {}
    if not d.get("ready") or d.get("state") in ("BUILDING", "RELEASED", None):
        return ""
    col = _COL.get(d.get("state"), "#cfd9e6")
    extra = ""
    if d.get("state") == "COMPRESSION":
        extra = f" · release {d.get('release_probability', 0)}%"
    return (f"<div style='text-align:center;font-size:14px;margin-top:4px;"
            f"font-weight:800;color:{col}'>{d.get('label', '')}{extra}</div>")
