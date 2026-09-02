"""MIOS — the Market Alignment Checklist, drawn.

One table above the Trade Card: every check on its own line, what spot is doing
at it, and which way that points. Then the tally underneath.

Pure presentation. `mios_v5.alignment` assembles the rows from values other
layers already published; this module turns them into HTML and does not read
session state, fetch anything, or decide any direction of its own. The split is
the usual one — if a colour here disagreed with the row's `align`, the fix would
be in the mapping below, never a second opinion about the market.

## It has to survive a phone

Five columns at eleven pixels is a fine desktop table and unreadable on a
handset, which is where this actually gets looked at during a session. So there
are two layouts over ONE set of markup:

* **≥ 700px** — the table, as a table.
* **< 700px** — every row becomes a card. The header row is hidden, the check
  name and its verdict sit on one line, and the level, the interaction and the
  remark stack beneath it at a size you can read one-handed.

The markup is emitted once and CSS decides; a phone branch that built different
HTML would be a second renderer to keep in step, and the two would drift the
first time a column was added.

## Two things the styling has to carry, not just decorate

* **A measured interaction and a positional one are different claims.** The
  third column says "🔴 Rejecting ₹24,400" when the acceptance strip observed
  it, and "🟢 Clear of ₹24,126 (70 away)" when nothing did — the first is
  behaviour, the second is arithmetic on two numbers. The measured ones are
  drawn in full ink and the fallbacks are dimmed, so the trader can see which
  is which without reading the words.
* **❓ is a state, not an empty cell.** A check whose producer went quiet keeps
  its row and prints why. A blank line is indistinguishable from a check nobody
  implemented, and that is exactly the thing the trader needs to be able to ask
  about.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from ..alignment import BALLS, BEAR, BULL, INFO, NA, NEUTRAL, WORDS
from .theme import (BEAR as C_BEAR, BRIGHT, BULL as C_BULL, CARD_BG,
                    CARD_BORDER, FAINT, INK, MICRO, MUTED, WARN)

#: alignment → the colour its ball and word are drawn in.
_COLOUR = {BULL: C_BULL, BEAR: C_BEAR, NEUTRAL: MICRO, NA: FAINT, INFO: FAINT}

#: one root class, so nothing here can restyle another panel's tables.
_NS = "mios-align"

#: below this the table becomes cards. 700px clears a landscape handset and
#: every portrait one; Streamlit's own column padding eats ~2rem of that.
_BREAK = 700

_CSS = f"""<style>
.{_NS} {{
  background:{CARD_BG}; border:1px solid {CARD_BORDER};
  border-radius:10px; padding:12px 14px; margin-bottom:10px;
}}
.{_NS} .hd {{
  font-size:11px; color:{FAINT}; letter-spacing:.08em;
  font-weight:700; margin-bottom:8px;
}}
.{_NS} table {{ width:100%; border-collapse:collapse; }}
.{_NS} th {{
  text-align:left; padding:5px 8px; color:{FAINT}; font-size:10.5px;
  font-weight:600; letter-spacing:.06em; text-transform:uppercase;
  border-bottom:1px solid {CARD_BORDER}; white-space:nowrap;
}}
.{_NS} td {{ padding:5px 8px; font-size:13px; vertical-align:top; color:{MUTED}; }}
.{_NS} .c-check  {{ color:{INK}; font-weight:600; }}
.{_NS} .c-value  {{ white-space:nowrap; color:{BRIGHT}; }}
.{_NS} .c-align  {{ white-space:nowrap; font-weight:700; }}
.{_NS} .c-remark {{ color:{FAINT}; font-size:12px; }}
/* a positional read is arithmetic; a measured one is behaviour */
.{_NS} .obs  {{ color:{BRIGHT}; }}
.{_NS} .calc {{ color:{FAINT}; }}
.{_NS} .grp td {{
  padding:11px 8px 4px; font-size:10.5px; font-weight:700;
  color:{WARN}; letter-spacing:.08em;
}}

/* ── the tally ───────────────────────────────────────────────────── */
.{_NS} .counts {{ font-size:14px; margin-bottom:8px; font-weight:600; }}
.{_NS} .chip {{
  display:inline-block; margin:3px 6px 3px 0; padding:4px 9px;
  border:1px solid {CARD_BORDER}; border-radius:7px; font-size:12px;
}}
.{_NS} .net {{ font-size:17px; font-weight:800; margin:8px 0 3px; }}
.{_NS} .sub {{ font-size:12px; color:{FAINT}; margin-bottom:8px; }}
.{_NS} .why {{ font-size:13px; color:{MUTED}; margin-bottom:5px; }}
.{_NS} .why b {{ color:{BRIGHT}; }}
.{_NS} .conflict {{ font-size:13px; color:{WARN}; }}
.{_NS} .conflict .note {{ color:{FAINT}; font-size:11.5px; margin-top:3px; }}

/* ── phone: one card per check ───────────────────────────────────── */
@media (max-width:{_BREAK}px) {{
  .{_NS} {{ padding:10px; }}
  .{_NS} thead {{ display:none; }}
  .{_NS} table, .{_NS} tbody {{ display:block; width:100%; }}
  /* ⚠️ FLEX, not float. The cells are emitted in table order — check, value,
     position, alignment, remark — and the verdict has to sit beside the NAME
     on a phone, three cells earlier. Floating it right made it drop past the
     value and land beside whatever happened to be tall, which is why the ball
     appeared under the wrong line. `order` reorders the display without a
     second set of markup for the phone to drift out of step with. */
  .{_NS} tr {{
    display:flex; flex-wrap:wrap; align-items:baseline;
    border:1px solid {CARD_BORDER}; border-radius:9px;
    padding:9px 11px; margin-bottom:8px;
  }}
  .{_NS} td {{ display:block; padding:1px 0; font-size:15px; }}
  .{_NS} .c-check  {{ order:1; flex:1 1 auto; font-size:15px; }}
  .{_NS} .c-align  {{ order:2; flex:0 0 auto; margin-left:auto;
                     text-align:right; font-size:15px; }}
  .{_NS} .c-value  {{ order:3; flex:1 1 100%; padding-top:5px;
                     font-size:22px; font-weight:700; white-space:normal; }}
  /* A label is not a price. "Balanced delta positioning" at 22px swamps the
     card it sits in, while ₹24,050 at 22px is the point of the card. */
  .{_NS} .c-value.long {{ font-size:16px; font-weight:600; }}
  .{_NS} .c-pos    {{ order:4; flex:1 1 100%; font-size:15px; padding-top:3px; }}
  .{_NS} .c-remark {{ order:5; flex:1 1 100%; font-size:12.5px; padding-top:4px; }}
  /* a cell the row does not carry must not leave a blank line */
  .{_NS} .c-value.none, .{_NS} .c-pos.none, .{_NS} .c-remark:empty {{ display:none; }}
  .{_NS} .grp {{ display:block; border:0; padding:12px 0 2px; margin:0; }}
  .{_NS} .grp td {{ font-size:12px; padding:0; }}
  .{_NS} .net {{ font-size:19px; }}
  .{_NS} .counts {{ font-size:15px; }}
  .{_NS} .chip {{ font-size:12.5px; padding:5px 10px; }}
  .{_NS} .why, .{_NS} .conflict {{ font-size:13.5px; }}
}}
</style>"""


def _esc(v: Any) -> str:
    """Minimal escaping. Every string reaching this panel is app-generated, but
    the table is emitted with `unsafe_allow_html` and a stray `<` in a label
    would silently eat the rest of the row."""
    return (str(v if v is not None else "—")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _blank(v: Any) -> bool:
    """Whether a cell carries nothing worth a line of its own on a phone."""
    return str(v or "").strip() in ("", "—")


def _row_html(row: Mapping[str, Any]) -> str:
    align = row.get("align") or NA
    colour = _COLOUR.get(align, FAINT)
    ball = BALLS.get(align, "❓")
    word = WORDS.get(align, "n/a")
    # A fallback interaction is arithmetic, not an observation — dimmed so the
    # measured rows read as the stronger claim they are.
    pos_cls = "obs" if row.get("observed") else "calc"
    val = str(row.get("value") or "")
    # A price is short and wants to dominate the card; a label like "Balanced
    # delta positioning" is prose and must not be set at price size.
    val_cls = ("c-value" + (" none" if _blank(val) else "")
               + (" long" if len(val) > 14 else ""))
    pos_cls += " none" if _blank(row.get("position")) else ""
    return (
        "<tr>"
        f"<td class='c-check'>{_esc(row.get('check'))}</td>"
        f"<td class='{val_cls}'>{_esc(row.get('value'))}</td>"
        f"<td class='c-pos {pos_cls}'>{_esc(row.get('position'))}</td>"
        f"<td class='c-align' style='color:{colour}'>{ball} {word}</td>"
        f"<td class='c-remark'>{_esc(row.get('remark'))}</td>"
        "</tr>")


def table_html(rows: Sequence[Mapping[str, Any]]) -> str:
    """The checklist itself, grouped by section in the order the rows arrive."""
    if not rows:
        return ""
    out = ["<table><thead><tr>",
           "<th>Check</th><th>Current value / level</th>",
           "<th>Spot position</th><th>Alignment</th><th>Remarks</th>",
           "</tr></thead><tbody>"]
    group = None
    for r in rows:
        g = r.get("group")
        if g != group:
            group = g
            out.append(f"<tr class='grp'><td colspan='5'>{_esc(g)}</td></tr>")
        out.append(_row_html(r))
    out.append("</tbody></table>")
    return "".join(out)


def summary_html(summary: Mapping[str, Any]) -> str:
    """The tally: counts, the bucket verdicts, the net read, and — the part that
    earns the block — what agrees and what does not.

    A net verdict with no conflict line is a different trade from the same
    verdict with three rows pointing the other way, and the counts alone do not
    say which one this is.
    """
    if not summary:
        return ""
    net = summary.get("net") or NEUTRAL
    net_word = {BULL: "BULLISH", BEAR: "BEARISH"}.get(net, "MIXED / NO EDGE")

    counts = (
        f"<span style='color:{C_BULL}'>🟢 {summary.get('bull', 0)}</span>"
        f"<span style='color:{FAINT}'> · </span>"
        f"<span style='color:{C_BEAR}'>🔴 {summary.get('bear', 0)}</span>"
        f"<span style='color:{FAINT}'> · </span>"
        f"<span style='color:{MICRO}'>⚪ {summary.get('neutral', 0)}</span>"
        f"<span style='color:{FAINT}'> · ❓ {summary.get('na', 0)}</span>")

    chips = []
    for name, verdict in (summary.get("groups") or {}).items():
        label = {BULL: "BULLISH", BEAR: "BEARISH",
                 NEUTRAL: "mixed", NA: "not reporting"}.get(verdict, "—")
        chips.append(
            f"<span class='chip' style='color:{_COLOUR.get(verdict, FAINT)}'>"
            f"{BALLS.get(verdict, '❓')} {_esc(name)} <b>{label}</b></span>")

    parts = [
        f"<div class='{_NS}'>",
        "<div class='hd'>🧩 ALIGNMENT SUMMARY</div>",
        f"<div class='counts'>{counts}</div>",
        f"<div>{''.join(chips)}</div>",
        f"<div class='net' style='color:{_COLOUR.get(net, MICRO)}'>"
        f"⚖️ NET: {BALLS.get(net, '⚪')} {net_word}</div>",
        f"<div class='sub'>Agreement: {summary.get('agreement', 0)} / "
        f"{summary.get('active', 0)} active checks"
        + (f" · ❓ {summary['na']} not available" if summary.get("na") else "")
        + "</div>",
    ]
    why = summary.get("why") or []
    if why:
        parts.append("<div class='why'><b>WHY:</b> "
                     + _esc(" · ".join(why)) + "</div>")
    conflicts = summary.get("conflicts") or []
    if conflicts:
        parts.append(
            "<div class='conflict'><b>⚠️ CONFLICT:</b> "
            + _esc(" · ".join(conflicts))
            + "<div class='note'>these point against the net read — the move "
              "is not clean until they resolve or roll over.</div></div>")
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
        spot = (read or {}).get("spot")
        head = ("<div class='hd'>🧭 MIOS MARKET ALIGNMENT CHECKLIST"
                + (f" · spot ₹{spot:,.0f}" if isinstance(spot, (int, float))
                   else "") + "</div>")
        body = (_CSS + f"<div class='{_NS}'>" + head + table_html(rows)
                + "</div>" + summary_html((read or {}).get("summary") or {}))
        with target.container():
            st.markdown(body, unsafe_allow_html=True)
    except Exception as err:                       # pragma: no cover - display guard
        try:
            target.caption(f"Market Alignment unavailable: {err}")
        except Exception:
            pass
