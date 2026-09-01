"""MIOS V6 — the Decision hero panel (Stage 52)."""

from __future__ import annotations

from typing import Any, Dict, Optional

_COL = {"ENTER": "#00ff88", "FLOOR_CONFIRMED": "#00ff88",
        "CEILING_CONFIRMED": "#ff4444", "ABORT": "#ff2d55",
        "ENTRY_READY": "#ffcc33", "WAIT": "#cfd9e6", "HOLD": "#4da6ff",
        "SCALE_IN": "#00ff88", "SCALE_OUT": "#ff9500", "TRAIL": "#4da6ff",
        "EXIT": "#ff9500", "COMPLETE": "#a78bfa"}


def decision_panel_html(data: Optional[Dict[str, Any]]) -> str:
    d = data or {}
    st = d.get("state")
    if not st:
        return ""
    col = _COL.get(st, "#cfd9e6")
    side = f" {d['side']}" if d.get("side") else ""
    head = (f"<div style='font-size:27px;font-weight:900;color:{col};"
            f"line-height:1.1'>{d.get('label', st)}{side}</div>")
    bits = []
    if d.get("confidence"):
        bits.append(f"Confidence <b style='color:#fff'>{d['confidence']}%</b>")
    if d.get("quality"):
        bits.append(f"Quality <b style='color:#ffd000'>{d['quality']}</b>")
    if d.get("proof_state"):
        bits.append(f"<b style='color:{col}'>{d['proof_state'].replace('_', ' ')}</b>")
    sub = (f"<div style='font-size:12.5px;margin-top:3px;color:#edf3f9'>"
           f"{' · '.join(bits)}</div>" if bits else "")

    levels = []
    if d.get("entry"):
        levels.append(f"<span style='color:#ffffff'>Entry <b>"
                      f"{float(d['entry']):,.0f}</b></span>")
    if d.get("stop"):
        levels.append(f"<span style='color:#ff9d9d'>Stop <b>"
                      f"{float(d['stop']):,.0f}</b></span>")
    tr = d.get("trail") or {}
    if tr.get("mode"):
        levels.append(f"<span style='color:#9fd3ff'>Trail <b>{tr['mode']}</b></span>")
    lvl = (f"<div style='font-size:15px;margin-top:5px;font-weight:800'>"
           f"{' &nbsp;·&nbsp; '.join(levels)}</div>" if levels else "")

    rows = "".join(f"<div style='font-size:12.5px;margin-top:2px;color:#7fe8b0'>"
                   f"✓ {r}</div>" for r in (d.get("reasons") or [])[:6])
    warns = "".join(f"<div style='font-size:12.5px;margin-top:2px;color:#ffcc66'>"
                    f"⚠ {w}</div>" for w in (d.get("warnings") or [])[:3])
    act = (f"<div style='margin-top:7px;padding:7px 10px;background:{col}22;"
           f"border:1px solid {col};border-radius:7px;text-align:center;"
           f"font-size:15px;font-weight:900;color:{col}'>{d['action']}</div>"
           if d.get("action") else "")

    return (f"<div style='background:#0b0f16;border:3px solid {col};"
            f"border-radius:12px;padding:12px 14px;margin-bottom:8px'>"
            f"<div style='font-size:11px;letter-spacing:.14em;color:#cfd9e6;"
            f"text-transform:uppercase'>Decision</div>"
            + head + sub + lvl + rows + warns + act + "</div>")


def render_decision_panel(data: Optional[Dict[str, Any]]) -> None:
    html = decision_panel_html(data)
    if not html:
        return
    import streamlit as st
    st.markdown(html, unsafe_allow_html=True)


def decision_line(data: Optional[Dict[str, Any]]) -> str:
    """Trade Card line — only when the decision is actionable news."""
    d = data or {}
    st = d.get("state")
    if st in (None, "WAIT"):
        return ""
    col = _COL.get(st, "#cfd9e6")
    tail = ""
    if d.get("entry"):
        tail = f" @ {float(d['entry']):,.0f}"
        if d.get("stop"):
            tail += f" · stop {float(d['stop']):,.0f}"
    return (f"<div style='text-align:center;font-size:16px;margin-top:5px;"
            f"font-weight:900;color:{col}'>{d.get('label', st)}"
            f"{(' ' + d['side']) if d.get('side') else ''}{tail}</div>")
