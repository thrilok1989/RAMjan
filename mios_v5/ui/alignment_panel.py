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
/* ⚠️ border-box, on everything in the namespace.
   Streamlit does not set it for us, and the default content-box makes every
   percentage flex-basis a lie: `flex:1 1 46%` sizes the CONTENT to 46% and
   then ADDS 22px of padding and 2px of border, so two 46% cards plus a
   divider overflow by a pixel and wrap onto separate lines. The CE/PE battle
   silently stacked on desktop for exactly this. */
.{_NS}, .{_NS} * {{ box-sizing:border-box; }}
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

/* ── the dashboard ───────────────────────────────────────────────── */
.{_NS} .verdict {{ text-align:center; padding:6px 0 10px; }}
.{_NS} .verdict .big {{ font-size:30px; font-weight:800; line-height:1.15; }}
.{_NS} .verdict .conv {{ font-size:13px; font-weight:700; margin-top:2px; }}
.{_NS} .verdict .spot {{ font-size:15px; color:{BRIGHT}; margin-bottom:4px; }}

/* four headline levels */
.{_NS} .heads {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }}
.{_NS} .head {{
  flex:1 1 22%; min-width:78px; text-align:center; padding:7px 4px;
  border:1px solid {CARD_BORDER}; border-radius:8px;
}}
.{_NS} .head .k {{ font-size:10px; color:{FAINT}; letter-spacing:.05em; }}
.{_NS} .head .v {{ font-size:17px; font-weight:700; color:{BRIGHT}; }}

/* the price ladder */
.{_NS} .rung {{
  display:flex; align-items:center; gap:8px; padding:5px 8px;
  border-left:3px solid transparent; font-size:13px;
}}
.{_NS} .rung.is-spot {{
  background:rgba(255,255,255,.06); border-radius:6px;
  border-left-color:{BRIGHT}; font-weight:800; font-size:16px;
}}
.{_NS} .rung .px {{ min-width:74px; font-weight:700; font-variant-numeric:tabular-nums; }}
.{_NS} .rung .lb {{ flex:1 1 auto; color:{MUTED}; font-size:12px; }}
.{_NS} .rung .dz {{ color:{FAINT}; font-size:11px; font-variant-numeric:tabular-nums; }}

/* three-column alignment + pressure lists */
.{_NS} .cols {{ display:flex; gap:8px; flex-wrap:wrap; }}
.{_NS} .col {{
  flex:1 1 30%; min-width:150px; padding:8px 10px;
  border:1px solid {CARD_BORDER}; border-radius:8px;
}}
.{_NS} .col h4 {{ margin:0 0 5px; font-size:11px; color:{FAINT};
                 letter-spacing:.07em; font-weight:700; }}
.{_NS} .col .verd {{ font-size:15px; font-weight:800; margin-bottom:4px; }}
.{_NS} .col li {{ font-size:12px; color:{MUTED}; margin:3px 0; list-style:none; }}
.{_NS} .col ul {{ margin:0; padding:0; }}

/* energy bars */
.{_NS} .bar {{ display:flex; align-items:center; gap:7px; margin:4px 0;
              font-size:13px; }}
.{_NS} .bar .nm {{ min-width:44px; font-weight:700; }}
.{_NS} .bar .tr {{ flex:1 1 auto; height:11px; background:rgba(255,255,255,.07);
                  border-radius:6px; overflow:hidden; }}
/* ⚠️ `display:block`. The fill is a <span>, and height:100% on an inline box
   does nothing — the bars rendered as empty grey tracks with the colour
   nowhere, which is the one thing a bar chart has to get right. */
.{_NS} .bar .fl {{ display:block; height:100%; border-radius:6px;
                  min-width:2px; }}
.{_NS} .bar .vl {{ min-width:34px; text-align:right; font-weight:700;
                  font-variant-numeric:tabular-nums; }}

/* the CE vs PE battle */
.{_NS} .legs {{ display:flex; gap:8px; flex-wrap:wrap; align-items:flex-start; }}
.{_NS} .leg {{
  flex:1 1 46%; min-width:210px; padding:9px 11px;
  border:1px solid {CARD_BORDER}; border-radius:9px;
}}
.{_NS} .leg h4 {{ margin:0 0 3px; font-size:12px; letter-spacing:.05em;
                 font-weight:800; }}
.{_NS} .leg .sub2 {{ font-size:10.5px; color:{FAINT}; margin-bottom:6px; }}
.{_NS} .leg .ltp {{ font-size:24px; font-weight:800; color:{BRIGHT};
                   line-height:1.1; }}
.{_NS} .leg .st {{ font-size:12px; font-weight:700; margin:3px 0 7px; }}
.{_NS} .lrung {{
  display:flex; align-items:center; gap:7px; padding:2px 0; font-size:12px;
  border-left:3px solid transparent; padding-left:6px;
}}
.{_NS} .lrung.is-ltp {{
  background:rgba(255,255,255,.07); border-radius:5px;
  border-left-color:{BRIGHT}; font-weight:800; font-size:14px;
}}
.{_NS} .lrung .px {{ min-width:60px; font-weight:700;
                    font-variant-numeric:tabular-nums; }}
.{_NS} .lrung .lb {{ flex:1 1 auto; color:{MUTED}; font-size:11px; }}
.{_NS} .vs {{ align-self:center; font-size:20px; padding:0 2px; }}

/* the spot → CE → PE chain */
.{_NS} .chain {{ display:flex; flex-direction:column; gap:3px; }}
.{_NS} .link {{ padding:6px 9px; border-radius:7px;
               border:1px solid {CARD_BORDER}; font-size:13px; }}
.{_NS} .link b {{ font-size:11px; color:{FAINT}; letter-spacing:.06em;
                 display:block; }}
.{_NS} .arrow {{ text-align:center; color:{FAINT}; font-size:13px; }}

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
  .{_NS} .verdict .big {{ font-size:26px; }}
  .{_NS} .head {{ flex:1 1 45%; }}          /* two per line, not four squeezed */
  .{_NS} .col {{ flex:1 1 100%; }}          /* the three columns stack */
  .{_NS} .rung {{ font-size:14px; }}
  .{_NS} .rung.is-spot {{ font-size:18px; }}
  .{_NS} .rung .lb {{ font-size:12.5px; }}
  .{_NS} .leg {{ flex:1 1 100%; }}        /* the two legs stack, not squeeze */
  .{_NS} .vs {{ align-self:center; }}
  .{_NS} .lrung {{ font-size:13px; }}
  .{_NS} .lrung.is-ltp {{ font-size:15px; }}
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


# ── the dashboard ───────────────────────────────────────────────────────────
#
# Everything below draws `alignment.dashboard(read)` — the same rows the table
# beneath it uses, grouped and sorted. Nothing here reads session state or
# scores anything, so the ten-second view and the twenty-one-row view cannot
# tell the trader two different things.

_NET_WORD = {BULL: "BULLISH", BEAR: "BEARISH"}
_CONV_TONE = {"HIGH": C_BULL, "MODERATE": WARN, "LOW": WARN}


def verdict_html(d: Mapping[str, Any]) -> str:
    """The headline: bias, and how much of the vote actually carries it.

    ⚠️ The conviction is not decoration. "🔴 BEARISH" over 7 of 21 checks and
    the same words over 19 of 21 are completely different trades, and the old
    summary printed them identically. A lean is labelled a lean.
    """
    net = d.get("net") or NEUTRAL
    word = _NET_WORD.get(net, "MIXED / NO EDGE")
    conv = str(d.get("conviction") or "LOW")
    pct = int(d.get("conviction_pct") or 0)
    lean = " LEAN" if net in (BULL, BEAR) and conv == "LOW" else ""
    spot = d.get("spot")
    c = d.get("counts") or {}
    return (
        "<div class='verdict'>"
        + (f"<div class='spot'>🎯 NIFTY SPOT <b>₹{spot:,.0f}</b></div>"
           if isinstance(spot, (int, float)) else "")
        + f"<div class='big' style='color:{_COLOUR.get(net, MICRO)}'>"
          f"{BALLS.get(net, '⚪')} {word}{lean}</div>"
        + f"<div class='conv' style='color:{_CONV_TONE.get(conv, WARN)}'>"
          f"{'⚠️ ' if conv == 'LOW' else ''}{conv} CONVICTION · "
          f"{d.get('agreement', 0)} of {d.get('active', 0)} active checks "
          f"({pct}%)</div>"
        + (f"<div class='conv' style='color:{WARN}'>⚔️ CONFLICTED</div>"
           if d.get("conflicted") else "")
        + f"<div class='sub' style='margin-top:5px'>"
          f"<span style='color:{C_BULL}'>🟢 {c.get('bull', 0)}</span> · "
          f"<span style='color:{C_BEAR}'>🔴 {c.get('bear', 0)}</span> · "
          f"<span style='color:{MICRO}'>⚪ {c.get('neutral', 0)}</span> · "
          f"❓ {c.get('na', 0)}</div>"
        + "</div>")


def heads_html(d: Mapping[str, Any]) -> str:
    """Spot and the three levels that decide the next move, as four tiles."""
    h = d.get("heads") or {}
    tiles = (("🎯 SPOT", h.get("spot"), BRIGHT),
             ("🟢 SUPPORT", h.get("support"), C_BULL),
             ("🔴 RESISTANCE", h.get("resistance"), C_BEAR),
             ("🧲 MAGNET", h.get("magnet"), WARN))
    cells = "".join(
        f"<div class='head'><div class='k'>{_esc(k)}</div>"
        f"<div class='v' style='color:{col}'>{_esc(v)}</div></div>"
        for k, v, col in tiles)
    return f"<div class='heads'>{cells}</div>"


def ladder_html(d: Mapping[str, Any]) -> str:
    """The price map — every level in order, spot in its place.

    The single most useful thing on the panel: it answers "what is above me,
    what is below me, and how far" without reading a word.
    """
    rungs = d.get("ladder") or []
    if not rungs:
        return ""
    out = ["<div class='hd'>🗺️ PRICE MAP</div>"]
    for r in rungs:
        align = r.get("align") or NA
        cls = "rung is-spot" if r.get("spot") else "rung"
        dist = r.get("distance")
        gap = ("" if dist in (None, 0)
               else f"<span class='dz'>{dist:+,.0f}</span>")
        out.append(
            f"<div class='{cls}' style='border-left-color:"
            f"{_COLOUR.get(align, FAINT)}'>"
            f"<span>{BALLS.get(align, '⚪')}</span>"
            f"<span class='px' style='color:{_COLOUR.get(align, MUTED)}'>"
            f"₹{r['price']:,.0f}</span>"
            f"<span class='lb'>{_esc(' · '.join(r.get('labels') or []))}</span>"
            f"{gap}</div>")
    return "".join(out)


def groups_html(d: Mapping[str, Any]) -> str:
    """Structure · Options · Dealers side by side, each with what drives it."""
    groups = d.get("groups") or {}
    if not groups:
        return ""
    pressure = d.get("pressure") or {}
    icons = {"STRUCTURE": "🏗️", "OPTIONS": "⚡", "DEALERS": "🏦"}
    cols = []
    for name, verdict in groups.items():
        label = {BULL: "BULLISH", BEAR: "BEARISH",
                 NEUTRAL: "MIXED", NA: "NOT REPORTING"}.get(verdict, "—")
        # The rows from THIS bucket, so a column names its own drivers rather
        # than the market's. A MIXED bucket lists BOTH sides — "mixed" with an
        # empty list is the one verdict that tells the reader nothing, and the
        # reason it is mixed is exactly what they are looking for.
        def _own(kind):
            return [p for p in (pressure.get(kind) or [])
                    if p.get("bucket") == name]
        drivers = ([(verdict, p) for p in _own(verdict)][:3] if verdict in (BULL, BEAR)
                   else [(BULL, p) for p in _own(BULL)][:2]
                   + [(BEAR, p) for p in _own(BEAR)][:2])
        items = "".join(f"<li>{BALLS.get(k, '⚪')} {_esc(p['check'])}</li>"
                        for k, p in drivers)
        cols.append(
            f"<div class='col'><h4>{icons.get(name, '')} {_esc(name)}</h4>"
            f"<div class='verd' style='color:{_COLOUR.get(verdict, FAINT)}'>"
            f"{BALLS.get(verdict, '❓')} {label}</div>"
            f"<ul>{items}</ul></div>")
    return f"<div class='cols'>{''.join(cols)}</div>"


def energy_html(d: Mapping[str, Any]) -> str:
    """CALL vs PUT participation as two bars — which side is being paid for."""
    e = d.get("energy") or {}
    ce, pe = e.get("CALL"), e.get("PUT")
    if ce is None and pe is None:
        return ""
    top = max(float(ce or 0), float(pe or 0), 1.0)
    bars = []
    for name, val, col in (("CALL", ce, C_BULL), ("PUT", pe, C_BEAR)):
        v = float(val or 0)
        hot = " 🔥" if e.get("winner") == name else ""
        bars.append(
            f"<div class='bar'><span class='nm' style='color:{col}'>{name}</span>"
            f"<span class='tr'><span class='fl' style='width:{v / top * 100:.0f}%;"
            f"background:{col}'></span></span>"
            f"<span class='vl'>{v:.0f}{hot}</span></div>")
    winner = e.get("winner")
    tail = (f"<div class='sub'>{BALLS.get(BULL if winner == 'CALL' else BEAR)} "
            f"{_esc(e.get('preferred') or (winner + ' side carrying it'))}</div>"
            if winner else
            f"<div class='sub'>{_esc(e.get('preferred') or 'balanced')}</div>")
    return "<div class='hd'>⚡ PREMIUM ENERGY</div>" + "".join(bars) + tail


#: energy band → the tone it is drawn in. The words are Stage 71.7's.
_BAND_TONE = {"Explosive": C_BULL, "Strong": C_BULL, "Healthy": WARN,
              "Weak": C_BEAR, "Dead": C_BEAR}
_BAND_ICON = {"Explosive": "🔥", "Strong": "🔥", "Healthy": "⚡",
              "Weak": "🪫", "Dead": "💀"}


def legs_html(d: Mapping[str, Any]) -> str:
    """The CE vs PE battle — each leg's premium, energy and its OWN price map.

    This is the layer the first dashboard dropped, and dropping it was the
    mistake: the index levels say where price is, and only the premiums say
    whether the option market is confirming it. A call sitting under its own
    high-volume pivot while the put sits on top of its own is the whole story
    on a day the index looks fine.

    Each leg gets its own ladder because a ₹107 premium and a 24,050 index
    level share no axis — plotting them together would be meaningless.
    """
    legs = d.get("legs") or []
    if not any(l.get("premium") for l in legs):
        return ""
    cards = []
    for leg in legs:
        chart = leg.get("chart") or ""
        tint = C_BULL if chart == "CALL" else C_BEAR
        band = leg.get("state")
        rungs = "".join(
            f"<div class='lrung{' is-ltp' if r.get('ltp') else ''}' "
            f"style='border-left-color:{_COLOUR.get(r.get('align'), FAINT)}'>"
            f"<span>{BALLS.get(r.get('align'), '⚪')}</span>"
            f"<span class='px' style='color:"
            f"{BRIGHT if r.get('ltp') else _COLOUR.get(r.get('align'), MUTED)}'>"
            f"{r['price']:,.2f}</span>"
            f"<span class='lb'>{_esc(' · '.join(r.get('labels') or []))}</span>"
            "</div>"
            for r in (leg.get("ladder") or []))
        bits = []
        if leg.get("energy") is not None:
            bits.append(f"energy {leg['energy']:.0f}")
        if leg.get("buy_pct") is not None:
            bits.append(f"{leg['buy_pct']:.0f}% buy volume")
        cards.append(
            f"<div class='leg'>"
            f"<h4 style='color:{tint}'>{'🟦' if chart == 'CALL' else '🟥'} "
            f"{chart} SIDE</h4>"
            f"<div class='sub2'>{_esc(leg.get('leg') or '')}</div>"
            f"<div class='ltp'>{_esc(leg.get('premium'))}</div>"
            + (f"<div class='st' style='color:{_BAND_TONE.get(band, FAINT)}'>"
               f"{_BAND_ICON.get(band, '·')} PREMIUM {_esc(band).upper()}"
               + (f" · {' · '.join(bits)}" if bits else "") + "</div>"
               if band else
               f"<div class='st' style='color:{FAINT}'>"
               + (" · ".join(bits) or "energy not reported") + "</div>")
            + rungs + "</div>")
    return ("<div class='hd'>⚔️ CE vs PE — OPTION LTP BATTLE</div>"
            f"<div class='legs'>{cards[0]}<div class='vs'>⚔️</div>{cards[1]}</div>"
            if len(cards) == 2 else
            "<div class='hd'>⚔️ OPTION LTP</div>"
            f"<div class='legs'>{''.join(cards)}</div>")


def chain_html(d: Mapping[str, Any]) -> str:
    """Spot structure → option premium → dealers, as one chain.

    The question this answers is the one three separate verdicts cannot:
    **is the option market confirming what the index is doing?** "Structure
    bullish, options bearish" states it; this shows it as a sequence, with the
    legs' own premiums as the middle link.
    """
    groups = d.get("groups") or {}
    legs = {l.get("chart"): l for l in (d.get("legs") or [])}
    if not groups:
        return ""

    def _verd(name):
        v = groups.get(name)
        label = {BULL: "BULLISH", BEAR: "BEARISH",
                 NEUTRAL: "MIXED", NA: "NOT REPORTING"}.get(v, "—")
        return (f"<span style='color:{_COLOUR.get(v, FAINT)};font-weight:700'>"
                f"{BALLS.get(v, '❓')} {label}</span>")

    mid = []
    for chart in ("CALL", "PUT"):
        leg = legs.get(chart) or {}
        band = leg.get("state")
        if band:
            mid.append(f"<span style='color:{_BAND_TONE.get(band, FAINT)}'>"
                       f"{_BAND_ICON.get(band, '·')} {chart} {band.upper()}</span>")
    e = d.get("energy") or {}
    if e.get("winner"):
        mid.append(f"<span style='color:{FAINT}'>energy "
                   f"{e.get('CALL', 0):.0f} vs {e.get('PUT', 0):.0f}</span>")
    return ("<div class='hd'>🔄 SPOT → OPTION PREMIUM → DEALERS</div>"
            "<div class='chain'>"
            f"<div class='link'><b>SPOT STRUCTURE</b>{_verd('STRUCTURE')}</div>"
            "<div class='arrow'>↓</div>"
            f"<div class='link'><b>OPTION PREMIUM</b>"
            f"{' · '.join(mid) or _verd('OPTIONS')}</div>"
            "<div class='arrow'>↓</div>"
            f"<div class='link'><b>DEALERS</b>{_verd('DEALERS')}</div>"
            "</div>")


def conflict_html(d: Mapping[str, Any]) -> str:
    """Bullish defence against bearish pressure, side by side.

    The old panel buried this under the counts. When the net read is a lean,
    what is arguing with it is the most useful thing on the screen.
    """
    pressure = d.get("pressure") or {}
    bulls, bears = pressure.get(BULL) or [], pressure.get(BEAR) or []
    if not bulls and not bears:
        return ""
    conv = str(d.get("conviction") or "LOW")
    level = "HIGH" if conv == "LOW" else "MODERATE" if conv == "MODERATE" else "LOW"

    def _side(title, items, colour):
        li = "".join(f"<li>{_esc(p['check'])} — {_esc(p['why'])}</li>"
                     for p in items[:4]) or "<li>—</li>"
        return (f"<div class='col'><h4 style='color:{colour}'>{title}</h4>"
                f"<ul>{li}</ul></div>")

    return ("<div class='hd'>⚔️ CONFLICT: " + level + "</div><div class='cols'>"
            + _side("🟢 BULLISH DEFENCE", bulls, C_BULL)
            + _side("🔴 BEARISH PRESSURE", bears, C_BEAR)
            + "</div>")


#: gate state → (icon, headline). The words are the Entry Gate's own states;
#: this only dresses them.
_GATE = {
    "WAIT": ("⏸", "WAIT"), "AT_ZONE_WAIT": ("⏸", "AT ZONE — WAIT"),
    "CHOP_WAIT": ("〰️", "CHOP — WAIT"), "NO_ROOM": ("📏", "NO ROOM — WAIT"),
    "PINNED": ("🧲", "PINNED — NO EDGE"), "REVERSED": ("⚠️", "BIAS AGAINST ZONE"),
    "ARMED_CALL": ("🟢", "ARMED — CALL"), "ARMED_PUT": ("🔴", "ARMED — PUT"),
    "CALL": ("🟢", "CONFIRMED — CALL"), "PUT": ("🔴", "CONFIRMED — PUT"),
}


def gate_html(d: Mapping[str, Any]) -> str:
    """The Entry Gate's verdict, transported.

    ⚠️ This panel does NOT decide whether to trade. `compute_market_picture`
    owns the gate — its state, target, invalidation and R:R — and printing a
    second opinion here would put two answers to "do I take this" on one
    screen. What is shown is what the gate said, worded, and nothing else.
    """
    g = d.get("gate") or {}
    state = str(g.get("state") or "")
    if not state:
        return ""
    icon, word = _GATE.get(state, ("🎯", state.replace("_", " ")))
    tone = (C_BULL if "CALL" in state else C_BEAR if "PUT" in state else WARN)
    bits = []
    for key, label in (("level", "at"), ("target", "target"),
                       ("invalidation", "invalid below/above")):
        v = g.get(key)
        if isinstance(v, (int, float)):
            bits.append(f"{label} ₹{v:,.0f}")
    if isinstance(g.get("rr"), (int, float)):
        bits.append(f"R:R {g['rr']:.1f}")
    why = "; ".join(str(w) for w in (g.get("why") or [])[:2])
    return ("<div class='hd'>🎯 ENTRY GATE</div>"
            f"<div class='net' style='color:{tone}'>{icon} {_esc(word)}</div>"
            + (f"<div class='sub'>{_esc(' · '.join(bits))}</div>" if bits else "")
            + (f"<div class='why'>{_esc(why)}</div>" if why else "")
            + f"<div class='sub' style='color:{FAINT}'>the app's own gate — "
              "this panel reports it, it does not decide it</div>")


def render(st, read: Optional[Mapping[str, Any]], slot=None) -> None:
    """Draw the dashboard into `slot`, with the full checklist behind an expander.

    The layout answers the market in the order a trader asks it:

        verdict → where am I → what is above and below → who is pushing
        → what is arguing → what the gate says → (expand) every check

    The 21-row table is not gone, and that is deliberate. The dashboard is the
    scan; the table is the audit. A summary you cannot check is a summary you
    have to trust, and every number on the dashboard comes from a row in there.

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
        from ..alignment import dashboard as _dash
        d = _dash(read or {})
        head = "<div class='hd'>🧭 MIOS ALIGNMENT DASHBOARD</div>"
        body = (_CSS
                + f"<div class='{_NS}'>" + head + verdict_html(d)
                + heads_html(d) + ladder_html(d) + "</div>"
                + f"<div class='{_NS}'>" + legs_html(d) + "</div>"
                + f"<div class='{_NS}'>" + energy_html(d) + "</div>"
                + f"<div class='{_NS}'>" + chain_html(d) + "</div>"
                + f"<div class='{_NS}'>" + groups_html(d) + "</div>"
                + f"<div class='{_NS}'>" + conflict_html(d) + "</div>"
                + f"<div class='{_NS}'>" + gate_html(d) + "</div>")
        with target.container():
            st.markdown(body, unsafe_allow_html=True)
            # The audit trail, collapsed. Same rows, same numbers — this is
            # where a dashboard figure gets checked, not a second opinion.
            with st.expander("🔍 Detailed alignment — all "
                             f"{len(rows)} checks", expanded=False):
                st.markdown(
                    _CSS + f"<div class='{_NS}'>" + table_html(rows) + "</div>"
                    + summary_html((read or {}).get("summary") or {}),
                    unsafe_allow_html=True)
    except Exception as err:                       # pragma: no cover - display guard
        try:
            target.caption(f"Market Alignment unavailable: {err}")
        except Exception:
            pass
