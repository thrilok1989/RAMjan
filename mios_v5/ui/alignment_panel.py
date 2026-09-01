"""MIOS — the Market Alignment Checklist, drawn.

One table above the Trade Card: every check on its own line, what spot is doing
at it, and which way that points. Then the tally underneath.

Pure presentation. `mios_v5.alignment` assembles the rows from values other
layers already published; this module turns them into HTML and does not read
session state, fetch anything, or decide any direction of its own. The split is
the usual one — if a colour here disagreed with the row's `align`, the fix would
be in the mapping below, never a second opinion about the market.

## Two things the styling has to carry, not just decorate

* **A measured interaction and a positional one are different claims.** The
  third column says "🔴 Rejecting ₹24,400" when the acceptance strip observed
  it, and "🟢 Above ₹24,360 (+20)" when nothing did — the first is behaviour,
  the second is arithmetic on two numbers. The measured ones are drawn in full
  ink and the fallbacks are dimmed, so the trader can see which is which without
  reading the words.
* **❓ is a state, not an empty cell.** A check whose producer went quiet keeps
  its row and prints why. A blank line is indistinguishable from a check nobody
  implemented, and that is exactly the thing the trader needs to be able to ask
  about.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from ..alignment import (BALLS, BEAR, BULL, INFO, NA, NEUTRAL, WORDS)
from .theme import (BEAR as C_BEAR, BRIGHT, BULL as C_BULL, CARD_BG,
                    CARD_BORDER, FAINT, INK, MICRO, MUTED, WARN)

#: alignment → the colour its ball and word are drawn in.
_COLOUR = {BULL: C_BULL, BEAR: C_BEAR, NEUTRAL: MICRO, NA: FAINT, INFO: FAINT}

_CARD = (f"background:{CARD_BG};border:1px solid {CARD_BORDER};"
         f"border-radius:10px;padding:10px 13px;margin-bottom:10px")

_TH = (f"text-align:left;padding:4px 8px;color:{FAINT};font-size:10px;"
       "font-weight:600;letter-spacing:.06em;text-transform:uppercase;"
       f"border-bottom:1px solid {CARD_BORDER}")

_TD = f"padding:3px 8px;font-size:11.5px;vertical-align:top;color:{MUTED}"

#: the group header row inside the table.
_GROUP = (f"padding:7px 8px 3px;font-size:10px;font-weight:700;color:{WARN};"
          "letter-spacing:.08em")


def _esc(v: Any) -> str:
    """Minimal escaping. Every string reaching this panel is app-generated, but
    the table is emitted with `unsafe_allow_html` and a stray `<` in a label
    would silently eat the rest of the row."""
    return (str(v if v is not None else "—")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _row_html(row: Mapping[str, Any]) -> str:
    align = row.get("align") or NA
    colour = _COLOUR.get(align, FAINT)
    ball = BALLS.get(align, "❓")
    word = WORDS.get(align, "n/a")
    # A fallback interaction is arithmetic, not an observation — dimmed so the
    # measured rows read as the stronger claim they are.
    pos_colour = BRIGHT if row.get("observed") else FAINT
    return (
        "<tr>"
        f"<td style='{_TD};color:{INK};white-space:nowrap'>{_esc(row.get('check'))}</td>"
        f"<td style='{_TD};white-space:nowrap'>{_esc(row.get('value'))}</td>"
        f"<td style='{_TD};color:{pos_colour}'>{_esc(row.get('position'))}</td>"
        f"<td style='{_TD};color:{colour};white-space:nowrap;font-weight:600'>"
        f"{ball} {word}</td>"
        f"<td style='{_TD};color:{FAINT};font-size:10.5px'>{_esc(row.get('remark'))}</td>"
        "</tr>")


def table_html(rows: Sequence[Mapping[str, Any]]) -> str:
    """The checklist itself, grouped by section in the order the rows arrive."""
    if not rows:
        return ""
    out = ["<table style='width:100%;border-collapse:collapse'>",
           "<thead><tr>",
           f"<th style='{_TH}'>Check</th>",
           f"<th style='{_TH}'>Current value / level</th>",
           f"<th style='{_TH}'>Spot position</th>",
           f"<th style='{_TH}'>Alignment</th>",
           f"<th style='{_TH}'>Remarks</th>",
           "</tr></thead><tbody>"]
    group = None
    for r in rows:
        g = r.get("group")
        if g != group:
            group = g
            out.append(f"<tr><td colspan='5' style='{_GROUP}'>{_esc(g)}</td></tr>")
        out.append(_row_html(r))
    out.append("</tbody></table>")
    return "".join(out)


def summary_html(summary: Mapping[str, Any]) -> str:
    """The tally: counts, the five bucket verdicts, the net read, and — the part
    that earns the block — what agrees and what does not.

    A net verdict with no conflict line is a different trade from the same
    verdict with three rows pointing the other way, and the counts alone do not
    say which one this is.
    """
    if not summary:
        return ""
    net = summary.get("net") or NEUTRAL
    net_colour = _COLOUR.get(net, MICRO)
    net_word = {BULL: "BULLISH", BEAR: "BEARISH"}.get(net, "MIXED / NO EDGE")

    counts = (
        f"<span style='color:{C_BULL}'>🟢 {summary.get('bull', 0)}</span>"
        f"<span style='color:{FAINT}'> · </span>"
        f"<span style='color:{C_BEAR}'>🔴 {summary.get('bear', 0)}</span>"
        f"<span style='color:{FAINT}'> · </span>"
        f"<span style='color:{MICRO}'>⚪ {summary.get('neutral', 0)}</span>"
        f"<span style='color:{FAINT}'> · ❓ {summary.get('na', 0)}</span>")

    groups = summary.get("groups") or {}
    chips = []
    for name, verdict in groups.items():
        c = _COLOUR.get(verdict, FAINT)
        label = {BULL: "BULLISH", BEAR: "BEARISH",
                 NEUTRAL: "mixed", NA: "not reporting"}.get(verdict, "—")
        chips.append(
            f"<span style='display:inline-block;margin:2px 6px 2px 0;padding:2px 7px;"
            f"border:1px solid {CARD_BORDER};border-radius:6px;font-size:10.5px;"
            f"color:{c}'>{BALLS.get(verdict, '❓')} {_esc(name)} "
            f"<b>{label}</b></span>")

    active = summary.get("active", 0)
    agree = summary.get("agreement", 0)
    parts = [
        f"<div style='{_CARD}'>",
        f"<div style='font-size:10px;color:{FAINT};letter-spacing:.08em;"
        "font-weight:700;margin-bottom:5px'>🧩 ALIGNMENT SUMMARY</div>",
        f"<div style='font-size:12px;margin-bottom:6px'>{counts}</div>",
        f"<div style='margin-bottom:7px'>{''.join(chips)}</div>",
        f"<div style='font-size:15px;font-weight:700;color:{net_colour};"
        f"margin-bottom:3px'>⚖️ NET MARKET ALIGNMENT: "
        f"{BALLS.get(net, '⚪')} {net_word}</div>",
        f"<div style='font-size:10.5px;color:{FAINT};margin-bottom:6px'>"
        f"Agreement: {agree} / {active} active checks"
        + (f" · ❓ {summary['na']} not available" if summary.get("na") else "")
        + "</div>",
    ]
    why = summary.get("why") or []
    if why:
        parts.append(
            f"<div style='font-size:11px;color:{MUTED};margin-bottom:4px'>"
            f"<b style='color:{BRIGHT}'>WHY:</b> " + _esc(" · ".join(why)) + "</div>")
    conflicts = summary.get("conflicts") or []
    if conflicts:
        parts.append(
            f"<div style='font-size:11px;color:{WARN}'>"
            "<b>⚠️ CONFLICT:</b> " + _esc(" · ".join(conflicts))
            + f"<div style='color:{FAINT};font-size:10px;margin-top:2px'>"
            "these point against the net read — the move is not clean until "
            "they resolve or roll over.</div></div>")
    parts.append("</div>")
    return "".join(parts)


def render(st, read: Optional[Mapping[str, Any]], slot=None) -> None:
    """Draw the checklist into `slot` (or straight onto the page).

    Never raises: the checklist is a view over other layers, and a formatting
    fault in it must not take down the cycle that produced the numbers.
    """
    target = slot if slot is not None else st
    try:
        rows = (read or {}).get("rows") or []
        if not rows:
            target.info("🧭 **Market Alignment** standing by — no checks have "
                        "reported yet this cycle.")
            return
        summary = (read or {}).get("summary") or {}
        spot = (read or {}).get("spot")
        head = (f"<div style='font-size:10px;color:{FAINT};letter-spacing:.08em;"
                "font-weight:700;margin-bottom:6px'>🧭 MIOS MARKET ALIGNMENT "
                "CHECKLIST"
                + (f" · spot ₹{spot:,.0f}" if isinstance(spot, (int, float)) else "")
                + "</div>")
        body = (f"<div style='{_CARD}'>" + head + table_html(rows) + "</div>"
                + summary_html(summary))
        with target.container():
            st.markdown(body, unsafe_allow_html=True)
    except Exception as err:                       # pragma: no cover - display guard
        try:
            target.caption(f"Market Alignment unavailable: {err}")
        except Exception:
            pass
