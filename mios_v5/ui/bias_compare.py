"""MIOS V6 — the V5 ‖ V6 bias comparison strip for the Trade Card.

Two reads, side by side, at the same size. Neither is labelled "the answer",
because that is the honest state of things: V6 has not been validated against
enough live sessions to earn promotion, and V5 has known correlation defects
V6 was built to fix. Showing both, including on the days they disagree, is what
generates the evidence to eventually pick one.

The disagreement is styled *louder* than the agreement. A day when V5 says BULL
and V6 says NEUTRAL is more informative than a hundred days they match, and a
strip that quietly renders both without flagging the split would waste it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _chip(tag: str, d: Dict[str, Any], sub: str) -> str:
    conf = d.get("confidence")
    conf_txt = f" {int(conf)}%" if conf else ""
    return (
        f"<div style='flex:1 1 0;min-width:0;text-align:center;padding:6px 4px;"
        f"background:#0f1622;border:2px solid {d.get('colour', '#cfd9e6')};"
        f"border-radius:9px;'>"
        f"<div style='font-size:11px;font-weight:800;color:#cfd9e6;"
        f"letter-spacing:.08em;'>{tag}</div>"
        f"<div style='font-size:19px;font-weight:900;line-height:1.15;"
        f"color:{d.get('colour', '#cfd9e6')};'>"
        f"{d.get('emoji', '')} {d.get('label', '—')}"
        f"<span style='font-size:14px;'>{conf_txt}</span></div>"
        f"<div style='font-size:10.5px;color:#c4d0de;'>{sub}</div></div>")


def bias_compare_html(cmp: Optional[Dict[str, Any]]) -> str:
    """The two-chip strip. Returns "" when there is nothing honest to show."""
    c = cmp or {}
    v5, v6 = c.get("v5") or {}, c.get("v6") or {}
    if not v5.get("label") and not v6.get("label"):
        return ""
    read = c.get("read") or {}
    cov = (f"{read.get('coverage', 0)}/{read.get('coverage_of', 4)} voters"
           if read.get("coverage") else "warming up")

    agrees = c.get("agrees")
    if agrees is True:
        verdict = ("<span style='color:#00ff88;font-weight:800;'>✓ V5 and V6 "
                   "agree</span>")
    elif agrees is False:
        verdict = ("<span style='color:#ffcc33;font-weight:900;'>⚠️ V5 and V6 "
                   "DISAGREE</span>")
    else:
        verdict = "<span style='color:#c4d0de;'>V6 has no read yet</span>"

    div = c.get("divergence")
    div_html = (f"<div style='text-align:center;font-size:12.5px;margin-top:2px;"
                f"color:#ffd9a0;font-weight:600;'>{div}</div>" if div else "")

    frozen = ("<div style='text-align:center;font-size:12px;margin-top:2px;"
              "color:#ffab3d;font-weight:800;'>❄️ V6 frozen — flow shifted</div>"
              if read.get("frozen") else "")

    return (
        f"<div style='margin-top:8px;'>"
        f"<div style='display:flex;gap:6px;align-items:stretch;'>"
        + _chip("MIOS V5", v5, "conflict-arbitrated")
        + _chip("MIOS V6", v6, cov)
        + "</div>"
        f"<div style='text-align:center;font-size:12.5px;margin-top:3px;'>"
        f"{verdict}"
        f"<span style='color:#b3c2d4;'> · V6 is observational — it does not "
        f"drive the decision</span></div>"
        + div_html + frozen + "</div>")


def v6_detail_html(read: Optional[Dict[str, Any]]) -> str:
    """The voters and modifiers behind the V6 number — for the V6 dashboard,
    not the card. Every discount is shown with its reason, so a low V6
    confidence can always be traced to the engine that caused it."""
    r = read or {}
    voters = r.get("voters") or []
    if not voters:
        return (f"<div style='font-size:12.5px;color:#cfd9e6;'>"
                f"{r.get('sentence', 'No V6 read yet.')}</div>")
    out = [f"<div style='background:#0d1117;border:1px solid #1e2836;"
           f"border-radius:10px;padding:10px 12px;margin-bottom:8px'>",
           f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
           f"margin-bottom:4px'>🧬 MIOS V6 bias — how it was built</div>"]
    for v in voters:
        col = "#00ff88" if v.get("sign", 0) > 0 else "#ff4444"
        out.append(
            f"<div style='display:flex;gap:8px;align-items:baseline;margin-top:3px'>"
            f"<span style='width:26px;font-size:10.5px;color:#b3c2d4'>"
            f"S{v.get('stage')}</span>"
            f"<span style='width:132px;font-size:12px;font-weight:700;"
            f"color:#edf3f9'>{v.get('label')}</span>"
            f"<span style='width:58px;font-size:12.5px;font-weight:800;"
            f"color:{col}'>{v.get('bias')}</span>"
            f"<span style='width:44px;font-size:11px;color:#cfd9e6'>"
            f"×{v.get('weight', 0)}</span>"
            f"<span style='font-size:11.5px;color:#cfd9e6'>{v.get('detail', '')}"
            f"</span></div>")
    for m in (r.get("modifiers") or []):
        mc = "#ff9500" if m.get("mult", 1) < 1 else "#66ff9d"
        out.append(
            f"<div style='margin-top:3px;font-size:11.5px;color:{mc}'>"
            f"↳ S{m.get('stage')} ×{m.get('mult')} — {m.get('reason')}</div>")
    for n in ((r.get("gates") or {}).get("notes") or []):
        out.append(f"<div style='margin-top:3px;font-size:11.5px;color:#ffcc33'>"
                   f"⛔ cap — {n}</div>")
    out.append(f"<div style='margin-top:7px;padding-top:6px;border-top:1px solid "
               f"#1e2836;font-size:12.5px;color:#dfe7f0;'>"
               f"{r.get('sentence', '')}</div></div>")
    return "".join(out)
