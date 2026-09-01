"""MIOS V6 — the Greek-behaviour strip.

One compact violet section (the dealer/gamma house colour) that renders the read
from `mios_v5.greek_behaviour.interpret` — pull, gamma regime, time pressure, vol
pressure, expansion risk, and a one-line behaviour headline. NOT eleven raw
Greek cards (rule 15); NOT extra header height (rule 14): five small rows and a
footer, from data the app already computed.

Pure presentation — it renders what the layer decided and adds no number of its
own. Empty string when there is nothing to say, so a permanently-present strip
does not train the eye to ignore it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..greek_behaviour import CONTEXTUAL_GREEKS, NOT_REPORTED

_WRAP = ("margin:6px 0;padding:8px 12px;background:#241a2e;"
         "border-left:3px solid #a78bfa;border-radius:6px;"
         "font-size:12.5px;color:#c9b6ec;text-align:left;")
_ROW = "margin-top:2px;"
_LABEL = "color:#8a7bb0;font-weight:700;"
_MUTED = "color:#7a6b95;"


def _row(label: str, value: Any) -> str:
    v = "—" if value in (None, "") else value
    tone = _MUTED if v == NOT_REPORTED else "color:#d9c9f5;"
    return (f"<div style='{_ROW}'><span style='{_LABEL}'>{label}</span> "
            f"<span style='{tone}'>{v}</span></div>")


def behaviour_html(read: Optional[Dict[str, Any]]) -> str:
    """The strip. `""` when there is no dealer/greek read at all.

    Preserves the Dealer-Magnet semantics and the mandatory context-only footer;
    a stale snapshot is labelled, and Greeks with no producer read `Not reported`
    rather than a fabricated zero.
    """
    r = read or {}
    if not r:
        return ""
    pull = r.get("pull") or {}
    gamma = r.get("gamma") or {}
    time = r.get("time") or {}
    vol = r.get("vol") or {}
    exp = r.get("expansion") or {}

    # nothing worth a strip if every core read is absent
    core = [pull.get("text"), gamma.get("text"), time.get("text"),
            vol.get("text"), exp.get("text")]
    if all(t in (None, NOT_REPORTED) for t in core):
        return ""

    stale = ("<span style='color:#e0a030;font-weight:700;'> · ⚠ STALE</span>"
             if r.get("stale") else "")
    head = (f"<div><span style='color:#d9c9f5;font-weight:800;'>🧲 Greek "
            f"behaviour</span>{stale}</div>")

    rows = [
        _row("Dealer magnet", pull.get("text")),
        _row("Gamma regime", gamma.get("text")),
        _row("Time pressure", time.get("text")),
        _row("Vol pressure", vol.get("text")),
        _row("Expansion risk", exp.get("text")),
    ]

    # Vega → vol sensitivity, shown ONLY when materially significant (spec §5),
    # so a LOW/absent read does not add a row on a space-constrained card.
    vsens = r.get("vol_sensitivity") or {}
    if vsens.get("strength") in ("MODERATE", "HIGH"):
        rows.append(_row("Vol sensitivity", vsens.get("text")))

    # The "other 5" third-order reads — one small row each, shown ONLY when the
    # magnitude is material (MODERATE/HIGH). A LOW or absent read adds no row, so
    # the strip stays compact and never trains the eye to ignore it.
    for _g in CONTEXTUAL_GREEKS:
        cr = (r.get("contextual") or {}).get(_g) or {}
        if cr.get("strength") in ("MODERATE", "HIGH"):
            rows.append(_row(cr.get("label", _g.capitalize()), cr.get("text")))

    synth = r.get("synthesis")
    if synth and synth != NOT_REPORTED:
        rows.append(f"<div style='{_ROW}margin-top:4px;'>"
                    f"<span style='{_LABEL}'>Behaviour</span> "
                    f"<span style='color:#e6dbff;font-weight:800;'>{synth}"
                    f"</span></div>")

    # contextual Greeks with no producer — named once, compactly, never as zero
    greeks = r.get("greeks") or {}
    missing = [g.capitalize() for g in CONTEXTUAL_GREEKS
               if greeks.get(g) == NOT_REPORTED]
    if missing:
        rows.append(f"<div style='{_ROW}{_MUTED}font-size:11px;'>"
                    f"Not reported: {' · '.join(missing)}</div>")

    footer = ("<div style='margin-top:4px;color:#8a7bb0;font-size:11px;'>"
              "Context only — does NOT change the Guardian verdict.</div>")
    return f"<div style='{_WRAP}'>{head}{''.join(rows)}{footer}</div>"
