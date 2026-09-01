"""The option legs' S/R read, as a table BELOW the charts.

`classify_leg_sr_behavior` classifies each leg's own VOB structure against its
own LTP every cycle — BREAKING / REJECTING / ACCEPTING / BUILDING — and the
chart marks the level it is about. This is the same read in numbers: which
level, how far the leg is from it, and which way the verdict points for that
leg's own premium.

Pure: reads the analysis and returns rows / HTML. No `st`, no I/O — the same
shape `price_action_table` uses for the geometric patterns beneath the same
charts.

Direction is from the LEG'S OWN perspective, which is the axis the panel above
shows. A call breaking its own resistance is bullish for that call; what that
implies for the index is a separate read and is deliberately not restated here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: state → (what it means for this leg's premium, emoji). The vocabulary is
#: `classify_leg_sr_behavior`'s, unchanged — one word means one thing on the
#: chart above and in this table.
_MEANING = {
    "BREAKING": ("Broke through — level gave way", "🟢"),
    "BUILDING": ("Building at the level", "🔵"),
    "ACCEPTING": ("Accepted above/below — holding", "🟢"),
    "REJECTING": ("Rejected — level held", "🔴"),
    "NONE": ("No level in range", "⚪"),
}

#: The block detector needs `sensitivity + 13 + 10` bars before it can return
#: anything — 28 on the sensitivity=5 the leg read uses. Leg frames are today
#: only, at one minute, so no block can exist before roughly 09:43 IST however
#: healthy the data is.
MIN_BARS_FOR_BLOCKS = 28

#: Why a leg has no state. "NONE" alone was ambiguous in a way that mattered:
#: it read as "the engine looked and found nothing" whether the engine had run
#: or not, so a leg whose frame was too short to analyse looked identical to a
#: leg trading in clear air.
_NO_LEVEL_REASONS = {
    "unmeasured": "Not measured — no read published for this leg",
    "no_blocks": f"No order blocks yet — needs {MIN_BARS_FOR_BLOCKS}+ 1m bars",
    "wrong_side": "Blocks exist, but none on the tested side of the LTP",
    "side_none": "No level on this side",
    "none": "No level in range",
}

#: No parallel colour map. A state's colour is the chart's colour, taken from
#: the chart — keeping a second copy here is how ACCEPTING ended up mint on the
#: panel and plain green in the table, which made it indistinguishable from
#: BREAKING at a glance. `SR_STATE_TONE` is a plain dict and `terminal_chart`
#: imports nothing heavy at module level, so this costs nothing.
_NO_STATE_COLOUR = "#8c9bad"


def state_colour(state: Any) -> str:
    """The colour this state is drawn in on the chart above."""
    try:
        from .terminal_chart import SR_STATE_TONE
        return SR_STATE_TONE[str(state).upper()][1]
    except Exception:
        return _NO_STATE_COLOUR


CHARTS = ("CALL", "PUT")


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def no_level_reason(sr: Optional[Mapping[str, Any]],
                    zones: Optional[Sequence[Any]] = None) -> str:
    """Why this leg has no state — one of `_NO_LEVEL_REASONS`' keys.

    `sr is None` means nothing was published: `_publish_atm_legs` only stores a
    read that is truthy, and `classify_leg_sr_behavior` returns None outright
    when the frame is too short or the LTP is not positive. A stored
    `state: NONE` is the opposite case — the engine ran and found nothing.

    `zones` is the leg's VOB store, which the chart already draws. Both come
    from the same detector at the same sensitivity, so blocks in that store and
    no S/R level means the blocks are all on the wrong side of the LTP: support
    is only counted at or below it, resistance only at or above.
    """
    if not sr:
        return "unmeasured"
    if str(sr.get("state") or "").strip().upper() != "NONE":
        return "none"
    return "wrong_side" if zones else "no_blocks"


def row_for(chart: str, sr: Optional[Mapping[str, Any]],
            ltp: Any = None, label: Any = None,
            zones: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
    """One leg's row: `{chart, label, state, meaning, emoji, side, level, ltp,
    distance, reason}`.

    Always returns a row, even with nothing measured — a leg with no structure
    in range is a fact worth showing. Leaving it out would make an empty table
    look like a broken one. `reason` says WHICH kind of nothing it is.
    """
    state = str((sr or {}).get("state") or "NONE").strip().upper()
    if state not in _MEANING:
        state = "NONE"
    meaning, emoji = _MEANING[state]
    reason = no_level_reason(sr, zones)
    if state == "NONE":
        meaning = _NO_LEVEL_REASONS[reason]
    level = _f((sr or {}).get("level"))
    price = _f(ltp)
    distance = (price - level) if (level is not None and price is not None) else None
    return {
        "chart": chart,
        "label": str(label or chart),
        "state": state,
        "meaning": meaning,
        "emoji": emoji,
        "side": str((sr or {}).get("side") or "").lower() or None,
        "level": level,
        "ltp": price,
        "distance": distance,
        "reason": reason,
    }


#: Both sides, in the order a price ladder reads: resistance above, support
#: below. A leg sits BETWEEN them, so showing only the winning one hid half
#: the picture — and which one won could come down to a tie broken by
#: iteration order.
SIDES = ("resistance", "support")


def rows_for_leg(chart: str, sr: Optional[Mapping[str, Any]],
                 ltp: Any = None, label: Any = None,
                 zones: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    """One row per side for a single leg — resistance first, then support.

    `sr["sides"]` carries each side's own best read. When it is absent (an
    older cached read, or nothing published), the headline read is placed on
    the side it belongs to and the other side reports having no level, so the
    table keeps its shape rather than losing a row.
    """
    per_side = dict((sr or {}).get("sides") or {})
    if not per_side and (sr or {}).get("side"):
        per_side = {str(sr["side"]).lower(): sr}

    measured = bool(sr)
    # Did the engine find a level anywhere on this leg? Distinguishes "nothing
    # on this side" from "nothing at all", which have different explanations.
    has_any_level = bool(per_side) or _f((sr or {}).get("level")) is not None
    leg_reason = no_level_reason(sr, zones)
    out: List[Dict[str, Any]] = []
    for side in SIDES:
        read = per_side.get(side)
        row = row_for(chart, read, ltp, label, zones)
        # Name the side even when there is no read for it, or the row would
        # read as "no level" with no indication of WHICH level is missing.
        row["side"] = side
        # A measured leg with nothing on THIS side is not an unmeasured leg.
        # Without this the put's resistance row claimed "no read published"
        # while its support row on the same leg showed a live state — the same
        # ambiguity, one column over.
        #
        # Only when the leg HAS a level somewhere, though. A leg whose own
        # state is NONE found nothing on either side, and the reason for that
        # — no blocks yet, or blocks all on the wrong side — is the useful
        # answer. Overwriting it with "no level on this side" would throw away
        # the diagnosis and say the same empty thing twice.
        if read is None:
            if measured and has_any_level:
                row["reason"] = "side_none"
                row["meaning"] = f"No {side} level in range"
            else:
                # Nothing on either side: the LEG's reason is the useful one,
                # and it has to be computed from the leg's own read — the
                # per-side lookup is None here, which on its own would always
                # answer "unmeasured".
                row["reason"] = leg_reason
                row["meaning"] = _NO_LEVEL_REASONS[leg_reason]
        out.append(row)
    return out


def rows(call_sr=None, put_sr=None, call_ltp=None, put_ltp=None,
         call_label=None, put_label=None,
         call_zones=None, put_zones=None) -> List[Dict[str, Any]]:
    """Every leg's every side — call first, the order the panels are stacked."""
    return (rows_for_leg("CALL", call_sr, call_ltp, call_label, call_zones)
            + rows_for_leg("PUT", put_sr, put_ltp, put_label, put_zones))


def _cell(text: str, colour: Optional[str] = None, align: str = "left",
          bold: bool = False, border: str = "#223") -> str:
    style = f"padding:5px 8px;border:1px solid {border};text-align:{align};"
    if colour:
        style += f"color:{colour};"
    if bold:
        style += "font-weight:700;"
    return f"<td style='{style}'>{text}</td>"


#: Table chrome per theme. The chart above follows the viewer's theme, so a
#: dark-only table underneath it would be the same mismatch in miniature —
#: a black block sitting under a white chart.
_CHROME = {
    "dark": {"head_bg": "#0e1420", "head_fg": "#ffffff", "row_bg": "#141c28",
             "row_fg": "#e8eef5", "border": "#223", "title": "#dbe4ee",
             "muted": "#8c9bad"},
    "light": {"head_bg": "#eef2f7", "head_fg": "#1c2530", "row_bg": "#ffffff",
              "row_fg": "#1c2530", "border": "#d8dee7", "title": "#2b3644",
              "muted": "#5a6b7d"},
}


def chrome(theme: Any = None) -> Dict[str, str]:
    """Table chrome for `theme`; anything unrecognised falls back to dark,
    which is what the app shipped with."""
    return _CHROME["light"] if str(theme or "dark").strip().lower() == "light" \
        else _CHROME["dark"]


def table_html(leg_rows: Sequence[Mapping[str, Any]], theme: Any = None) -> str:
    """The rows as a compact table. `""` when there is nothing to show."""
    leg_rows = list(leg_rows or [])
    if not leg_rows:
        return ""
    _t = chrome(theme)
    head = (
        f"<div style='margin:6px 0 4px;font-weight:800;color:{_t['title']};"
        f"font-size:13px;'>🧱 Option legs · S/R behaviour "
        f"<span style='font-weight:400;color:{_t['muted']};'>(each leg's own "
        f"levels, in premium)</span></div>"
        "<div style='overflow-x:auto'><table style='width:100%;"
        "border-collapse:collapse;font-size:12px;'>"
        f"<tr style='background:{_t['head_bg']};color:{_t['head_fg']};'>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:left;'>Leg</th>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:left;'>State</th>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:left;'>What it means</th>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:left;'>Side</th>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:right;'>Level</th>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:right;'>LTP</th>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:right;'>Distance</th></tr>")
    body = ""
    for r in leg_rows:
        col = state_colour(r.get("state"))
        level, ltp, dist = r.get("level"), r.get("ltp"), r.get("distance")
        body += (
            f"<tr style='background:{_t['row_bg']};color:{_t['row_fg']};'>"
            + _cell(str(r.get("label") or r.get("chart")), border=_t["border"])
            + _cell(f"{r.get('emoji')} {r.get('state')}", col, bold=True,
                    border=_t["border"])
            + _cell(str(r.get("meaning") or "—"), border=_t["border"])
            + _cell(str(r.get("side") or "—"), border=_t["border"])
            + _cell("—" if level is None else f"₹{level:,.2f}", align="right",
                    border=_t["border"])
            + _cell("—" if ltp is None else f"₹{ltp:,.2f}", align="right",
                    border=_t["border"])
            # Signed on purpose: +2.10 reads as "above the level" at a glance,
            # which is the half of the answer the state word does not carry.
            + _cell("—" if dist is None else f"{dist:+,.2f}", col, align="right",
                    border=_t["border"])
            + "</tr>")
    return head + body + "</table></div>"


def build_table(call_sr=None, put_sr=None, call_ltp=None, put_ltp=None,
                call_label=None, put_label=None, theme: Any = None,
                call_zones=None, put_zones=None) -> str:
    """Convenience: rows → HTML in one call. Computes nothing beyond formatting."""
    return table_html(rows(call_sr, put_sr, call_ltp, put_ltp,
                           call_label, put_label, call_zones, put_zones),
                      theme=theme)
