"""MIOS V6 — the Support & Resistance Intelligence panel (Dashboard 2).

A level rendered as an object, not a line. Ranked, so the most important one is
unmistakably first.

    🥇 Support 23,650  ACTIVE   ★★★★★ 96/100   🟢 Building   92%
       Origin      ✓ Daily POC  ✓ Weekly VAH  ✓ Order Block
       Defended by Institutions · 3/4 groups building
       Bias        Bullish · Strengthening
       Reaction    🛡 Rejection      Absorption 🔁 Buyer Reloading
       Trap risk   Low (31%)        HTF ✓1H ✓4H ✓Daily ✗Monthly
       Entry       23,644–23,650    Stop 23,632 (dynamic)  Trail normal
       Target      Weekly POC 23,780
       🤖 Support is being defended by institutions.
          Buyer reloading continues. Bounce probability remains high.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_SIDE_COL = {"SUPPORT": "#00ff88", "RESISTANCE": "#ff4444"}
_LIFE_COL = {"building": "#00ff88", "recovered": "#00ff88", "holding": "#4da6ff",
             "untested": "#cfd9e6", "created": "#cfd9e6", "retest": "#ffcc33",
             "under-attack": "#ffcc33", "breaking": "#ff9500",
             "fading": "#ff4444", "broken": "#ff4444", "retired": "#666"}


def _row(label: str, value: str) -> str:
    return (f"<div style='display:flex;gap:8px;margin-top:2px'>"
            f"<span style='width:86px;font-size:11px;color:#b3c2d4;"
            f"flex-shrink:0'>{label}</span>"
            f"<span style='font-size:12.5px;color:#edf3f9'>{value}</span></div>")


def _flip_badge(i: Dict[str, Any]) -> str:
    """Marks a level the market has crossed since it was named.

    Shown rather than silently corrected: a flipped level is a level that has
    just been broken, which is information in its own right — and it explains
    why the card now says the opposite of what it said an hour ago.
    """
    if not i.get("flipped"):
        return ""
    was = str(i.get("labelled_side") or "").title()
    return ("<span style='background:#ffd00022;color:#ffd000;font-size:9.5px;"
            "padding:1px 6px;border-radius:4px;margin-left:6px' "
            f"title='Price crossed it — was {was}'>FLIPPED</span>")


def level_html(i: Optional[Dict[str, Any]]) -> str:
    if not i:
        return ""
    side = str(i.get("side") or "")
    col = _SIDE_COL.get(side, "#cfd9e6")
    war = i.get("type") == "War Zone"
    if war:
        col = "#a78bfa"
    lcol = _LIFE_COL.get(i.get("lifecycle"), "#cfd9e6")
    active = ("<span style='background:#00ff8822;color:#00ff88;font-size:9.5px;"
              "padding:1px 6px;border-radius:4px;margin-left:6px'>ACTIVE</span>"
              if i.get("active") else "")

    out = [
        f"<div style='background:#0b0f16;border:2px solid {col};border-radius:11px;"
        f"padding:10px 12px;margin-bottom:8px'>",
        # ── header: medal · type · price · confluence · lifecycle · confidence
        f"<div style='display:flex;align-items:baseline;gap:8px;flex-wrap:wrap'>"
        f"<span style='font-size:17px'>{i.get('medal', '')}</span>"
        f"<span style='font-size:18px;font-weight:900;color:{col}'>"
        f"{i.get('type', side.title())} {float(i.get('price') or 0):,.0f}</span>"
        f"{active}{_flip_badge(i)}"
        f"<span style='color:#ffd000;font-size:13px'>"
        f"{i.get('confluence_stars', '')}</span>"
        f"<span style='font-size:11.5px;color:#cfd9e6'>"
        f"{i.get('confluence_score', 0)}/100</span>"
        f"<span style='font-size:13px;font-weight:800;color:{lcol}'>"
        f"{i.get('lifecycle_label', '')}</span>"
        f"<span style='margin-left:auto;font-size:15px;font-weight:900;"
        f"color:{col}'>{i.get('confidence', 0)}%</span></div>",
    ]

    org = i.get("origin") or {}
    if org.get("families"):
        out.append(_row("Origin", " ".join(f"✓ {f.upper()}" for f in
                                           org["families"][:5])))
    st = i.get("strength") or {}
    hl = i.get("health") or {}
    out.append(_row("Strength", f"{st.get('score', 0)}/100 · "
                                f"{st.get('touches', 0)} tests "
                                f"({st.get('touch_note', '')}) · health "
                                f"{hl.get('pct', 0)}% · freshness "
                                f"{i.get('freshness', '—')}"))
    d = i.get("defended_by") or {}
    out.append(_row("Defended by", f"<b style='color:#ffffff'>{d.get('who', '—')}"
                                   f"</b> <span style='color:#cfd9e6'>"
                                   f"{d.get('detail', '')}</span>"))
    b = i.get("bias") or {}
    out.append(_row("Bias", f"<b style='color:{b.get('colour', '#fff')}'>"
                            f"{b.get('bias', '—')}</b> · {b.get('trend', '')}"))
    if i.get("acceptance") or i.get("absorption"):
        out.append(_row("Reaction", f"{i.get('acceptance') or '—'}"
                                    f" &nbsp;·&nbsp; {i.get('absorption') or '—'}"))
    tr = i.get("trap") or {}
    htf = i.get("htf") or {}
    htf_txt = " ".join(f"✓{m.split()[0]}" for m in (htf.get("matches") or [])[:4]) \
        or "none"
    out.append(_row("Risk", f"<span style='color:{tr.get('colour')}'>Trap "
                            f"{tr.get('label')}</span>"
                            f" ({tr.get('pct', '—')}%) &nbsp;·&nbsp; HTF "
                            f"{htf.get('stars', '')} {htf_txt}"))
    probs = i.get("probabilities") or {}
    out.append(_row("Odds", f"<span style='color:#ff4444'>break "
                            f"{probs.get('break', 0)}%</span> · "
                            f"<span style='color:#00ff88'>reject "
                            f"{probs.get('rejection', 0)}%</span>"))
    ez = i.get("entry_zone") or (None, None)
    if ez[0]:
        stop_txt = (f"{float(i['stop']):,.0f}"
                    f"{' (dynamic)' if i.get('stop_is_dynamic') else ''}"
                    if i.get("stop") else "—")
        trail = (i.get("trail") or {}).get("mode")
        out.append(_row("Trade", f"Entry <b style='color:#ffffff'>"
                                 f"{ez[0]:,.0f}–{ez[1]:,.0f}</b> · Stop "
                                 f"<span style='color:#ff9d9d'>{stop_txt}</span>"
                                 + (f" · Trail <span style='color:#9fd3ff'>"
                                    f"{trail}</span>" if trail else "")))
    if i.get("next_target"):
        out.append(_row("Target", f"{i.get('target_label') or 'Next'} "
                                  f"<b style='color:#ffffff'>"
                                  f"{float(i['next_target']):,.0f}</b>"))
    if i.get("expected"):
        out.append(_row("Expected", str(i["expected"])))
    for line in (i.get("summary") or []):
        out.append(f"<div style='font-size:12px;margin-top:2px;color:#dfe7f0'>"
                   f"🤖 {line}</div>")
    out.append("</div>")
    return "".join(out)


def render_sr_panel(levels: Optional[List[Dict[str, Any]]]) -> None:
    """Render the ranked S/R intelligence list."""
    import streamlit as st
    lv = [l for l in (levels or []) if l]
    st.markdown("**🎯 Support & Resistance Intelligence** "
                "<span style='color:#b3c2d4;font-size:11px'>"
                "(ranked — most important first)</span>",
                unsafe_allow_html=True)
    if not lv:
        st.caption("No scored levels yet — the canonical Reaction-Zone object is "
                   "still warming up.")
        return
    st.markdown("".join(level_html(l) for l in lv), unsafe_allow_html=True)
