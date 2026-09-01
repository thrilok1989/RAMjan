"""MIOS V6 — the seven-family evidence panel (Stage 53).

Replaces a 34-row engine dump with the read a trader can absorb in seconds:

    Market Structure   🔴 88%
    Order Flow         🔴 92%
    Dealer             🔴 85%
    Institutions       🔴 79%
    Options            🟡 55%  ⚠️ split
    Liquidity          🔴 91%
    Macro              🔴 74%

Families are ordered by authority (Dealer first), not by member count. A family
whose members contradict each other is flagged rather than smoothed — that split
is information.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from .theme import bias_emoji, bias_tone

_REL_COLOR = {"HIGH": "#cfd9e6", "MEDIUM": "#ffcc33", "LOW": "#ff9500"}
_FRESH_MARK = {"LIVE": "", "RECENT": "·recent", "OLD": "·old"}


def family_panel_html(corr: Optional[Dict[str, Any]]) -> str:
    """Render the seven-family read. `corr` is Stage 53's data dict."""
    if not corr or not corr.get("order"):
        return ""
    rows = []
    for f in corr["order"]:
        if f.get("status") != "OK":
            rows.append(
                f"<div style='display:flex;align-items:center;gap:8px;margin-top:3px;"
                f"opacity:.45'><span style='width:132px;font-size:12.5px;color:#cfd9e6'>"
                f"{f['label']}</span><span style='font-size:12px;color:#cfd9e6'>"
                f"no data</span></div>")
            continue
        col = bias_tone(f["direction"], "#ffffff")
        strength = int(f.get("strength") or 0)
        rel, fresh = f.get("reliability", "HIGH"), f.get("freshness", "LIVE")
        note = ""
        if rel == "LOW" and f.get("n", 0) > 1:
            note = (f"<span style='color:{_REL_COLOR['LOW']};font-size:11px'>"
                    f"⚠️ split {f.get('agreement', 0)}%</span>")
        elif rel == "MEDIUM":
            note = (f"<span style='color:{_REL_COLOR['MEDIUM']};font-size:11px'>"
                    f"{f.get('agreement', 0)}%</span>")
        fm = _FRESH_MARK.get(fresh, "")
        rows.append(
            f"<div style='display:flex;align-items:center;gap:8px;margin-top:4px'>"
            f"<span style='width:132px;font-size:13px;color:#ffffff;font-weight:700'>"
            f"{f['label']}</span>"
            f"<span style='font-size:14px'>{bias_emoji(f['direction'], '⚪')}</span>"
            f"<div style='flex:1;height:8px;background:#1e2836;border-radius:4px;"
            f"overflow:hidden'><div style='width:{max(2, strength)}%;height:100%;"
            f"background:{col}'></div></div>"
            f"<span style='width:38px;text-align:right;font-size:13px;font-weight:800;"
            f"color:{col}'>{strength}%</span>{note}"
            f"<span style='font-size:10px;color:#b3c2d4'>{fm}</span></div>")

    dom = corr.get("dominant", "—")
    dcol = bias_tone(dom.replace("STRONG_", ""), "#ffffff")
    sev = corr.get("severity", "—")
    sev_em = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(sev, "⚪")
    head = (
        f"<div style='font-size:13px;font-weight:800;color:#ffffff;margin-bottom:2px'>"
        f"🧠 Evidence Families <span style='color:{dcol}'>"
        f"{str(dom).replace('_', ' ')}</span> "
        f"<span style='color:#cfd9e6;font-weight:600'>· agreement "
        f"{corr.get('agreement_pct', 0)}% · {sev_em} {sev} conflict</span></div>")
    foot = ("<div style='font-size:10.5px;color:#b3c2d4;margin-top:5px'>"
            "7 de-duplicated families, not 34 votes — correlated evidence "
            "collapses to one vote per family.</div>")
    return (f"<div style='background:#0d1117;border:1px solid #1e2836;"
            f"border-radius:10px;padding:10px 12px;margin-bottom:8px'>"
            + head + "".join(rows) + foot + "</div>")


def render_family_panel(corr: Optional[Dict[str, Any]]) -> None:
    """Streamlit wrapper."""
    html = family_panel_html(corr)
    if not html:
        return
    import streamlit as st
    st.markdown(html, unsafe_allow_html=True)
