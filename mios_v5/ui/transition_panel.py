"""MIOS V6 — the Bias Transition panel (Stage 47).

    OVERALL BIAS  🔴 Bear 80%   ↓ Weakening
    Radar   Dealer ↓↓ · Order Flow ↓ · Options → · Institutions ↓
    Transition  Stable ■■■□□□□□□  Reversal ■■■■■■□□□  49%
    🤖 Bear bias remains, but Dealer positioning and Order Flow are weakening…
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from .theme import bias_tone

_STATE_COLOR = {"STABLE": "#cfd9e6", "STRENGTHENING": "#00ff88",
                "WEAKENING": "#ff9500", "TRANSITION": "#ffcc33",
                "REVERSING": "#ff4444"}
_NICE = {"dealer": "Dealer", "orderflow": "Order Flow", "options": "Options",
         "institutions": "Institutions", "liquidity": "Liquidity",
         "structure": "Structure", "macro": "Macro"}


def _meter(label: str, pct: float, col: str) -> str:
    filled = max(0, min(9, int(round(pct / 100.0 * 9))))
    return (f"<div style='display:flex;align-items:center;gap:6px;margin-top:2px'>"
            f"<span style='width:74px;font-size:11px;color:#cfd9e6'>{label}</span>"
            f"<span style='font-family:monospace;font-size:12px;color:{col}'>"
            f"{'■' * filled}{'□' * (9 - filled)}</span>"
            f"<span style='font-size:11px;color:{col}'>{pct:.0f}%</span></div>")


def transition_panel_html(data: Optional[Dict[str, Any]]) -> str:
    d = data or {}
    if not d.get("state"):
        return ""
    scol = _STATE_COLOR.get(d["state"], "#cfd9e6")
    bcol = bias_tone(d.get("bias"), "#ffffff")
    rows = [
        f"<div style='background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
        f"padding:10px 12px;margin-bottom:8px'>",
        f"<div style='font-size:11px;letter-spacing:.10em;color:#cfd9e6;"
        f"text-transform:uppercase'>Overall Bias</div>",
        f"<div style='font-size:20px;font-weight:900;color:{bcol};line-height:1.2'>"
        f"{d.get('bias', '—')} <span style='font-size:17px'>{d.get('strength', 0)}%</span>"
        f" &nbsp;<span style='color:{scol};font-size:16px'>{d.get('label', '')}</span>"
        f"<span style='color:#cfd9e6;font-size:12px;font-weight:600'> · "
        f"{d.get('velocity_label', '')}</span></div>",
    ]
    fams = d.get("families") or {}
    if fams:
        bits = " &nbsp;·&nbsp; ".join(
            f"<span style='color:#ffffff'>{_NICE.get(n, n)}</span> "
            f"<span style='color:"
            f"{'#ff9500' if f['state'] == 'weakening' else '#00ff88' if f['state'] == 'strengthening' else '#cfd9e6'}"
            f"'>{f['arrow']}</span>"
            for n, f in sorted(fams.items(), key=lambda kv: -abs(kv[1]["change"])))
        rows.append(f"<div style='font-size:12.5px;margin-top:5px'>📡 {bits}</div>")

    rp = float(d.get("reversal_probability") or 0)
    rows.append(_meter("Stability", max(0.0, 100.0 - rp), "#4da6ff"))
    rows.append(_meter("Reversal", rp,
                       "#ff4444" if rp >= 65 else "#ffcc33" if rp >= 40 else "#cfd9e6"))
    if d.get("leader"):
        rows.append(f"<div style='font-size:12px;margin-top:4px;color:#edf3f9'>"
                    f"🔎 Led by <b>{_NICE.get(d['leader'], d['leader'])}</b> "
                    f"— it moved first</div>")
    if d.get("thesis"):
        rows.append(f"<div style='font-size:12px;margin-top:4px;color:#dfe7f0;"
                    f"line-height:1.45'>🤖 {d['thesis']}</div>")
    rows.append("</div>")
    return "".join(rows)


def render_transition_panel(data: Optional[Dict[str, Any]]) -> None:
    html = transition_panel_html(data)
    if not html:
        return
    import streamlit as st
    st.markdown(html, unsafe_allow_html=True)


def transition_line(data: Optional[Dict[str, Any]]) -> str:
    """Compact Trade Card line — only when the bias is actually changing."""
    d = data or {}
    if d.get("state") in (None, "STABLE"):
        return ""
    scol = _STATE_COLOR.get(d["state"], "#cfd9e6")
    rp = int(d.get("reversal_probability") or 0)
    lead = (f" · led by {_NICE.get(d['leader'], d['leader'])}"
            if d.get("leader") else "")
    return (f"<div style='text-align:center;font-size:14px;margin-top:4px;"
            f"font-weight:800;color:{scol}'>{d.get('label', '')} "
            f"<span style='color:#dfe7f0;font-weight:600'>· reversal {rp}%"
            f"{lead}</span></div>")
