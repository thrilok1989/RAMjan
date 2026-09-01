"""MIOS V6 — the persistent header strip, rendered above the tab bar."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence


def header_html(tiles: Optional[Sequence[Dict[str, Any]]],
                alerts: Optional[Sequence[Dict[str, Any]]] = None) -> str:
    ts = list(tiles or [])
    if not ts:
        return ""
    cells = "".join(
        f"<div style='flex:1 1 0;min-width:82px;padding:4px 6px;"
        f"border-right:1px solid #17202c;opacity:{0.45 if t.get('stale') else 1}'>"
        f"<div style='font-size:8.5px;letter-spacing:.11em;color:#b3c2d4;"
        f"text-transform:uppercase;white-space:nowrap'>{t['label']}</div>"
        f"<div style='font-size:14.5px;font-weight:800;color:{t['colour']};"
        f"line-height:1.2;white-space:nowrap;overflow:hidden;"
        f"text-overflow:ellipsis'>{t['value']}</div>"
        + (f"<div style='font-size:9px;color:#9fb0c4'>{t['sub']}</div>"
           if t.get("sub") else "")
        + "</div>" for t in ts)

    bars = "".join(
        f"<div style='margin-top:4px;padding:5px 9px;background:#1a1206;"
        f"border-left:3px solid {a['colour']};border-radius:5px;"
        f"font-size:12.5px;font-weight:700;color:{a['colour']}'>{a['text']}"
        f"</div>" for a in (alerts or []))

    return (f"<div style='position:sticky;top:0;z-index:99;"
            f"background:#0b0f16;border:1px solid #1e2836;border-radius:10px;"
            f"padding:2px 4px;margin-bottom:8px'>"
            f"<div style='display:flex;align-items:stretch;overflow-x:auto'>"
            f"{cells}</div>{bars}</div>")
