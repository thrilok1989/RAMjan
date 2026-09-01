"""⚔️ Level Confluence, as a table below the charts.

A thin renderer over `level_confluence.evaluate_leg`. It formats; it decides
nothing. Every number here was published by an engine that ran earlier in the
cycle, and the verdicts come from the pure module.

Observational only — this reaches no gate, no verdict and no order.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..level_confluence import (
    COMPONENTS,
    CONFIRMED,
    CONTRADICTED,
    DELTA_LABEL,
    HIGH,
    INSUFFICIENT,
    LOW,
    MIXED,
    MODERATE,
    NOT_REPORTED,
)

#: Column heading per component. `Δ proxy` names the estimate as an estimate:
#: the split is inferred from 1-minute OHLC, not measured from tick data.
HEADINGS = {
    "structure": "Structure",
    "mfp": "MFP",
    "hvn": "HVN",
    "vob": "VOB",
    "oi": "OI",
    "depth": "Depth",
    "delta": DELTA_LABEL,
    "cvd": "CVD",
}

#: Quality → colour. Explanatory shades, not the red/green of a trade signal —
#: this layer describes evidence and must not read as advice.
QUALITY_TONE = {
    HIGH: "#4da6ff",
    MODERATE: "#7fb4e0",
    MIXED: "#d9c15a",
    LOW: "#9aa7b4",
    INSUFFICIENT: "#8c9bad",
}

VERDICT_TONE = {
    CONFIRMED: "#4da6ff",
    CONTRADICTED: "#c98b8b",
    NOT_REPORTED: "#6b7a8f",
}

_CHROME = {
    "dark": {"head_bg": "#0e1420", "head_fg": "#ffffff", "row_bg": "#141c28",
             "row_fg": "#e8eef5", "border": "#223", "title": "#dbe4ee",
             "muted": "#8c9bad"},
    "light": {"head_bg": "#eef2f7", "head_fg": "#1c2530", "row_bg": "#ffffff",
              "row_fg": "#1c2530", "border": "#d8dee7", "title": "#2b3644",
              "muted": "#5a6b7d"},
}


def chrome(theme: Any = None) -> Dict[str, str]:
    """Table chrome for the viewer's theme; unknown falls back to dark."""
    return _CHROME["light"] if str(theme or "dark").strip().lower() == "light" \
        else _CHROME["dark"]


def _reason_text(reason: Any) -> str:
    """Why this level is blank, in the words the S/R table already uses.

    Taken from `leg_sr_table`, which owns these strings — a second set of
    wordings for the same four situations is how two tables start describing
    the same state differently.
    """
    try:
        from .leg_sr_table import _NO_LEVEL_REASONS
        text = _NO_LEVEL_REASONS.get(str(reason or ""))
        if text:
            return f"Not reported — {text[0].lower()}{text[1:]}" \
                if not text.lower().startswith("not ") else text
    except Exception:
        pass
    return "Not reported — no valid level"


def side_label(row: Mapping[str, Any]) -> str:
    """`CE RES` / `PE SUP` — compact enough for a narrow column."""
    leg = str(row.get("label") or row.get("chart") or "")
    kind = "RES" if str(row.get("side") or "").lower() == "resistance" else "SUP"
    return f"{leg} {kind}".strip()


def _cell(text: str, t: Dict[str, str], colour: Optional[str] = None,
          align: str = "left", bold: bool = False) -> str:
    style = (f"padding:5px 8px;border:1px solid {t['border']};"
             f"text-align:{align};")
    if colour:
        style += f"color:{colour};"
    if bold:
        style += "font-weight:700;"
    return f"<td style='{style}'>{text}</td>"


def table_html(rows: Sequence[Mapping[str, Any]], theme: Any = None) -> str:
    """The confluence rows as a table. `""` when there is nothing to show."""
    rows = list(rows or [])
    if not rows:
        return ""
    t = chrome(theme)
    head = (
        f"<div style='margin:10px 0 4px;font-weight:800;color:{t['title']};"
        f"font-size:13px;'>⚔️ Level Confluence "
        f"<span style='font-weight:400;color:{t['muted']};'>— observational: "
        f"how many published engines corroborate each level. An evidence "
        f"tally, not a probability, and not a trade call.</span></div>"
        "<div style='overflow-x:auto'><table style='width:100%;"
        "border-collapse:collapse;font-size:12px;'>"
        f"<tr style='background:{t['head_bg']};color:{t['head_fg']};'>"
        f"<th style='padding:5px 8px;border:1px solid {t['border']};"
        f"text-align:left;'>Level</th>"
        f"<th style='padding:5px 8px;border:1px solid {t['border']};"
        f"text-align:left;'>State</th>")
    for key in COMPONENTS:
        head += (f"<th style='padding:5px 8px;border:1px solid {t['border']};"
                 f"text-align:center;'>{HEADINGS[key]}</th>")
    head += (f"<th style='padding:5px 8px;border:1px solid {t['border']};"
             f"text-align:center;'>Confluence</th>"
             f"<th style='padding:5px 8px;border:1px solid {t['border']};"
             f"text-align:left;'>Quality</th></tr>")

    body = ""
    for r in rows:
        name = side_label(r)
        if not r.get("reported"):
            # Never a zero score — no level is a different statement from a
            # level nothing agreed with. And SAY WHICH kind of nothing: four
            # blank rows that cannot explain themselves are indistinguishable
            # from a broken table, which is exactly how this looked.
            why = _reason_text(r.get("reason"))
            body += (f"<tr style='background:{t['row_bg']};color:{t['row_fg']};'>"
                     + _cell(name, t)
                     + _cell(f"<i>{why}</i>", t, t["muted"])
                     + "".join(_cell("—", t, t["muted"], align="center")
                               for _ in COMPONENTS)
                     + _cell("—", t, t["muted"], align="center")
                     + _cell("—", t, t["muted"])
                     + "</tr>")
            continue

        level = r.get("level")
        dist = r.get("distance")
        state = str(r.get("state") or "")
        head_cell = f"{name} ₹{level:,.2f}" if level is not None else name
        state_cell = state + (f" · {dist:+,.2f}" if dist is not None else "")

        body += f"<tr style='background:{t['row_bg']};color:{t['row_fg']};'>"
        body += _cell(head_cell, t)
        body += _cell(state_cell, t, bold=True)
        for key in COMPONENTS:
            comp = (r.get("components") or {}).get(key) or {}
            verdict = comp.get("verdict", NOT_REPORTED)
            glyph = comp.get("glyph", "?")
            note = comp.get("note") or ""
            body += _cell(f"<span title='{note}'>{glyph}</span>", t,
                          VERDICT_TONE.get(verdict), align="center")
        body += _cell(r.get("score") or "—", t, align="center", bold=True)
        qual = str(r.get("quality") or INSUFFICIENT)
        body += _cell(qual, t, QUALITY_TONE.get(qual))
        body += "</tr>"

    return head + body + "</table></div>"


def build_table(legs: Sequence[Mapping[str, Any]], theme: Any = None) -> str:
    """`legs` is a sequence of
    `{sr, ltp, label, mfp, hvn, lvn, zones, delta, oi, depth}`.

    Evaluates both sides of each leg through the pure module and renders them.
    Computes nothing itself.
    """
    from ..level_confluence import evaluate_leg

    try:
        from .leg_sr_table import no_level_reason
    except Exception:                                   # pragma: no cover
        no_level_reason = None

    rows: List[Dict[str, Any]] = []
    for leg in legs or []:
        sr, zones = leg.get("sr"), leg.get("zones")
        # The reason comes from the owner that already computes it for the S/R
        # table, so both tables explain a blank with the same words.
        reason = no_level_reason(sr, zones) if no_level_reason else None
        rows.extend(evaluate_leg(
            sr, leg.get("ltp"), label=leg.get("label"), reason=reason,
            mfp=leg.get("mfp"), hvn=leg.get("hvn"), lvn=leg.get("lvn"),
            zones=zones, delta=leg.get("delta"),
            oi=leg.get("oi"), depth=leg.get("depth")))
    return table_html(rows, theme=theme)
