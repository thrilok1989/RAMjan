"""MIOS V6 — the Order Flow Family panel.

Three columns, one per instrument, each showing the seven members and the ONE
result they collapse into.

The members are listed so you can see what the family is standing on — and,
just as importantly, what it is missing. A family speaking from two of seven
looks confident until you can see the other five are silent.

Renders values. Calculates nothing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

_DIR_COL = {"BULLISH": "#00ff88", "BEARISH": "#ff4444", "NEUTRAL": "#cfd9e6"}
_CARD = ("background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
         "padding:9px 11px")


def _bar(pct: int, colour: str) -> str:
    pct = max(0, min(100, int(pct or 0)))
    return (f"<div style='background:#161b22;border-radius:3px;height:5px;"
            f"width:100%;margin-top:2px'>"
            f"<div style='background:{colour};height:5px;border-radius:3px;"
            f"width:{pct}%'></div></div>")


def family_html(instrument: str, fam: Optional[Dict[str, Any]]) -> str:
    f = dict(fam or {})
    direction = str(f.get("direction") or "NEUTRAL")
    col = _DIR_COL.get(direction, "#cfd9e6")
    reported, of = f.get("reported", 0), f.get("of", 7)

    from ..order_flow import display_rows
    rows = []
    for r in display_rows(f):
        if not r["reported"]:
            rows.append(f"<div style='display:flex;justify-content:space-between;"
                        f"font-size:11px;color:#6f7d8f;margin-top:1px'>"
                        f"<span>{r['name']}</span><span>—</span></div>")
            continue
        d = r["direction"] or "—"
        c = _DIR_COL.get(d, "#cfd9e6")
        extra = (f" ×{r['multiple']:.2f}" if r.get("multiple") is not None
                 else "")
        rows.append(f"<div style='display:flex;justify-content:space-between;"
                    f"font-size:11px;color:#cfd9e6;margin-top:1px'>"
                    f"<span>{r['name']}</span>"
                    f"<span style='color:{c};font-weight:700'>{d}{extra}</span>"
                    f"</div>")

    return "".join([
        f"<div style='{_CARD}'>",
        f"<div style='font-size:12px;font-weight:800;color:#ffffff'>"
        f"{instrument}</div>",
        f"<div style='font-size:16px;font-weight:900;color:{col};"
        f"margin-top:1px'>{direction}</div>",
        f"<div style='display:flex;gap:10px;margin-top:5px'>",
        f"<div style='flex:1'><div style='font-size:9.5px;color:#9fb0c4'>"
        f"STRENGTH {f.get('strength', 0)}</div>"
        + _bar(f.get("strength", 0), col) + "</div>",
        f"<div style='flex:1'><div style='font-size:9.5px;color:#9fb0c4'>"
        f"RELIABILITY {f.get('reliability', 0)}</div>"
        + _bar(f.get("reliability", 0), "#4da6ff") + "</div>",
        f"<div style='flex:1'><div style='font-size:9.5px;color:#9fb0c4'>"
        f"CONFIDENCE {f.get('confidence', 0)}</div>"
        + _bar(f.get("confidence", 0), "#a78bfa") + "</div>",
        "</div>",
        f"<div style='margin-top:6px;border-top:1px solid #1e2836;"
        f"padding-top:4px'>" + "".join(rows) + "</div>",
        f"<div style='margin-top:5px;font-size:10px;color:#9fb0c4'>"
        f"{reported}/{of} reporting · agreement {f.get('agreement', '0/0')}"
        f"</div>",
        "</div>",
    ])


def render_order_flow(st, families: Optional[Sequence[Dict[str, Any]]]) -> None:
    fams = list(families or [])
    st.markdown("**🌊 Order Flow Family** "
                "<span style='font-size:11px;color:#9fb0c4'>— Money Flow · "
                "Candle Delta · CVD · CSV · CBV · Volume · VOB collapse to ONE "
                "vote. They are seven views of the same tape, so counting them "
                "separately would count that tape seven times.</span>",
                unsafe_allow_html=True)
    if not fams:
        st.caption("Order flow warming up — no member has reported yet.")
        return
    for col, item in zip(st.columns(len(fams)), fams):
        with col:
            st.markdown(family_html(item.get("instrument", "—"),
                                    item.get("family")),
                        unsafe_allow_html=True)
    st.caption("Values are read from the V5 engines that produce them — "
               "nothing here is recalculated. Volume confirms conviction; it "
               "has no direction, so it never votes.")
