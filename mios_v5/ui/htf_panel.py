"""MIOS V6 — the six-timeframe institutional panel (Stage 45).

    1H     🟢 BULL   above VAH   VAH 23760 · POC 23700 · VAL 23640
    4H     🟢 BULL   upper value …
    Daily  🔴 BEAR   below VAL   …
    ─────────────────────────────────────────────
    Institutional Alignment ★★★★☆  4/6 Bear
    Value Migration  short ↑ · medium ↓ · long →

Tells you at a glance whether today's move sits inside or against the larger
structure — a short-term rally inside a long-term bearish market reads
immediately instead of having to be inferred.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from .theme import bias_emoji, bias_tone

_TF_ORDER = ("1H", "4H", "Daily", "Weekly", "Monthly", "Yearly")


def htf_panel_html(data: Optional[Dict[str, Any]]) -> str:
    reads = (data or {}).get("reads") or {}
    if not reads:
        return ""
    rows = []
    for tf in _TF_ORDER:
        r = reads.get(tf)
        if not r or r.get("status") != "OK":
            continue
        col = bias_tone(r["bias"], "#ffffff")
        prof = r.get("profile") or {}
        lv = ""
        if prof.get("vah") and prof.get("val"):
            lv = (f"<span style='color:#cfd9e6;font-size:11px'>"
                  f"VAH {prof['vah']:,.0f} · POC {prof.get('poc', 0):,.0f} · "
                  f"VAL {prof['val']:,.0f}</span>")
        mig = (r.get("migration") or {}).get("arrow", "")
        rows.append(
            f"<div style='display:flex;align-items:center;gap:8px;margin-top:4px'>"
            f"<span style='width:56px;font-size:12.5px;font-weight:800;color:#ffffff'>"
            f"{tf}</span>"
            f"<span style='font-size:13px'>{bias_emoji(r['bias'], '⚪')}</span>"
            f"<span style='width:62px;font-size:12.5px;font-weight:800;color:{col}'>"
            f"{r['bias']}</span>"
            f"<span style='width:88px;font-size:11.5px;color:#dfe7f0'>"
            f"{r.get('location') or ''}</span>"
            f"<span style='font-size:12px;color:{col}'>{mig}</span> {lv}</div>")

    al = (data or {}).get("alignment") or {}
    mg = (data or {}).get("migration") or {}
    acol = bias_tone(al.get("bias"), "#ffffff")
    dis = (f" <span style='color:#ff9500;font-size:11px'>"
           f"({', '.join(al['disagree'][:3])} disagree)</span>"
           if al.get("disagree") else "")
    foot = (
        f"<div style='margin-top:7px;padding-top:6px;border-top:1px solid #1e2836'>"
        f"<div style='font-size:13px;font-weight:800;color:#ffffff'>"
        f"Institutional Alignment <span style='color:#ffd000'>"
        f"{al.get('stars', '')}</span> "
        f"<span style='color:{acol}'>{al.get('label', '')}</span>{dis}</div>"
        f"<div style='font-size:12px;color:#dfe7f0;margin-top:2px'>"
        f"Value migration &nbsp; short <b style='color:#ffffff'>{mg.get('short', '?')}</b>"
        f" &nbsp;·&nbsp; medium <b style='color:#ffffff'>{mg.get('medium', '?')}</b>"
        f" &nbsp;·&nbsp; long <b style='color:#ffffff'>{mg.get('long', '?')}</b></div></div>")

    return (f"<div style='background:#0d1117;border:1px solid #1e2836;"
            f"border-radius:10px;padding:10px 12px;margin-bottom:8px'>"
            f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
            f"margin-bottom:2px'>🏛 Higher-Timeframe Structure</div>"
            + "".join(rows) + foot + "</div>")


def render_htf_panel(data: Optional[Dict[str, Any]]) -> None:
    html = htf_panel_html(data)
    if not html:
        return
    import streamlit as st
    st.markdown(html, unsafe_allow_html=True)
