"""MIOS V6.5 — Stage 65 Trade Narrator panel.

A timeline, newest last, so it reads the way the trade happened. Action beats
(the ones quoted from the Decision Engine) are marked, so a trader can tell at a
glance which lines were MIOS *deciding* and which were MIOS *observing*.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

_CARD = ("background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
         "padding:10px 12px;margin-bottom:8px")


def narrator_html(beats: Optional[Sequence[Dict[str, Any]]],
                  limit: int = 24, title: str = "🎙 Trade narration") -> str:
    bs = list(beats or [])
    if not bs:
        return (f"<div style='{_CARD}'>"
                f"<div style='font-size:13px;font-weight:800;color:#ffffff'>"
                f"{title}</div>"
                f"<div style='font-size:12.5px;color:#cfd9e6;margin-top:3px'>"
                f"Nothing has changed yet — the narrator writes on "
                f"transitions, not on every cycle.</div></div>")
    out = [f"<div style='{_CARD}'>",
           f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
           f"margin-bottom:4px'>{title}</div>"]
    for b in bs[-limit:]:
        col = b.get("colour", "#cfd9e6")
        mark = "▸" if b.get("action") else "·"
        weight = "800" if b.get("action") else "600"
        out.append(
            f"<div style='display:flex;gap:8px;align-items:baseline;"
            f"margin-top:3px'>"
            f"<span style='width:40px;font-size:11px;color:#9fb0c4;"
            f"font-variant-numeric:tabular-nums'>{b.get('time', '')}</span>"
            f"<span style='color:{col};font-size:11px'>{mark}</span>"
            f"<span style='flex:1;min-width:0;font-size:12.5px;color:{col};"
            f"font-weight:{weight}'>{b.get('text', '')}</span>"
            + (f"<span style='font-size:10px;color:#9fb0c4;white-space:nowrap'>"
               f"{b.get('engine')}</span>" if b.get("engine") else "")
            + "</div>")
    out.append(f"<div style='margin-top:6px;font-size:10.5px;color:#9fb0c4'>"
               f"▸ marks a Decision-Engine action. Unmarked lines are "
               f"observations — the narrator never prescribes.</div></div>")
    return "".join(out)


def narrator_line(beats: Optional[Sequence[Dict[str, Any]]]) -> str:
    """The last beat only — for the Trade Card."""
    bs = list(beats or [])
    if not bs:
        return ""
    b = bs[-1]
    return (f"<div style='text-align:center;font-size:13px;margin-top:4px;"
            f"color:{b.get('colour', '#cfd9e6')};font-weight:600'>"
            f"🎙 {b.get('time', '')} {b.get('text', '')}</div>")
