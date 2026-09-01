"""MIOS V6 — the LTP Behaviour panel (Stage 50)."""

from __future__ import annotations

from typing import Any, Dict, Optional
from .theme import bias_tone

_STATE_COLOR = {
    "building": "#00ff88", "absorbing": "#a78bfa", "exhausted": "#ff9500",
    "weakening": "#ff4444", "neutral": "#cfd9e6", "rising": "#00ff88",
    "falling": "#ff4444", "flat": "#cfd9e6", "compressing": "#ffcc33",
    "exploding": "#ff2d55", "distribution": "#ff9500", "unwinding": "#cfd9e6",
    "squeeze": "#ff2d55", "entering": "#00ff88", "leaving": "#ff4444",
    "healthy": "#4da6ff", "dry": "#cfd9e6", "explosive": "#ff2d55",
}


def _row(label: str, item: Optional[Dict[str, Any]]) -> str:
    d = item or {}
    col = _STATE_COLOR.get(d.get("state"), "#edf3f9")
    return (f"<div style='display:flex;align-items:center;gap:8px;margin-top:3px'>"
            f"<span style='width:82px;font-size:12px;color:#cfd9e6'>{label}</span>"
            f"<span style='font-size:13px;font-weight:800;color:{col}'>"
            f"{d.get('label', '—')}</span></div>")


def ltp_panel_html(data: Optional[Dict[str, Any]]) -> str:
    d = data or {}
    if not d.get("ready"):
        return ""
    ov = d.get("overall") or {}
    tone = bias_tone(ov.get("tone"), "#ffd000")
    rows = [
        f"<div style='background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
        f"padding:10px 12px;margin-bottom:8px'>",
        f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
        f"margin-bottom:2px'>📖 LTP Behaviour</div>",
        _row("Price", d.get("price")),
        _row("Buyers", d.get("buyers")),
        _row("Sellers", d.get("sellers")),
        _row("Calls", d.get("calls")),
        _row("Puts", d.get("puts")),
        _row("Money Flow", d.get("flow")),
        _row("Volume", d.get("volume")),
        f"<div style='margin-top:7px;padding-top:6px;border-top:1px solid #1e2836;"
        f"font-size:14px;font-weight:800;color:{tone}'>{ov.get('text', '')}</div>",
        "</div>",
    ]
    return "".join(rows)


def render_ltp_panel(data: Optional[Dict[str, Any]]) -> None:
    html = ltp_panel_html(data)
    if not html:
        return
    import streamlit as st
    st.markdown(html, unsafe_allow_html=True)


def ltp_line(data: Optional[Dict[str, Any]]) -> str:
    """Compact Trade Card line — the one sentence."""
    d = data or {}
    if not d.get("ready"):
        return ""
    ov = d.get("overall") or {}
    return (f"<div style='text-align:center;font-size:14px;margin-top:4px;"
            f"font-weight:700;color:{bias_tone(ov.get('tone'), '#ffd000')}'>"
            f"📖 {ov.get('text', '')}</div>")
