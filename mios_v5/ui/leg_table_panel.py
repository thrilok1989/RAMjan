"""🧮 The ATM±1 leg tabulation — 6 legs, 19 signals, one table.

## Why this exists

`build_leg_bias_table` computes this every cycle and **nothing ever drew it**. The
rows reached `_leg_bias_cache`, which feeds Stage 14's order-flow read, three
alert paths and a gate check — every one of them consuming the *verdicts* and
discarding the per-signal detail that produced them.

So the trader could be told "Leg Fast Verdict: BEARISH" with no way to see which
of VOB / S/R / Div / Ign / Absorb / CVD actually voted that way. That is the same
consumed-but-unpublished gap as the FII/DII row and the Adaptive Greeks layer.

## The columns are grouped, because the builder already grades them

`build_leg_bias_table._SPEED_GROUPS` splits the 19 signals three ways, and
`overall['by_speed']` scores each group separately — so the flat 19-column table
was hiding the one structural fact about itself:

    ⚡ FAST        VOB · S/R · Div · Ign · Absorb · CVD
    🐢 LAGGING     VWAP · VWAP50 · VWAP20 · VIDYA · VIDYA50 · VIDYA20
    🎭 MISGUIDING  MFP · MFP50 · MFP20 · OIvel

Fast signals lead, lagging ones confirm, and the third group is named
"misguiding" by the engine itself — a trader reading `MFP20 🟢` needs to know
which bucket it sits in. The group headers carry each bucket's own verdict from
`by_speed`, so the detail and the summary cannot disagree.

⚠️ **Nothing is re-scored here.** The glyphs, the per-leg verdict, the → NIFTY
flip and the three speed verdicts are all `build_leg_bias_table`'s. This file
lays them out. `Sup VOB` / `Res VOB` are status words, not votes, and are shown
outside the groups for that reason — they are excluded from `_SPEED_GROUPS` too.

Pure module — rows in, HTML out.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .nifty_cockpit import _card, _esc
from .theme import (BEAR, BRIGHT, BULL, CARD_BORDER, INFO, INK, MICRO,
                    MUTED, VIOLET, WARN, bias_tone)

#: The three speed buckets, in the order they should be read: what is happening
#: now, what confirms it, what misleads. Mirrors `_SPEED_GROUPS` in
#: `build_leg_bias_table` — the signal names must stay in step with it, which
#: `test_leg_table_panel.py` asserts against the app source.
GROUPS = (
    ("fast", "⚡ FAST", ("VOB", "S/R", "Div", "Ign", "Absorb", "CVD")),
    ("lag", "🐢 LAGGING", ("VWAP", "VWAP50", "VWAP20",
                           "VIDYA", "VIDYA50", "VIDYA20")),
    ("mis", "🎭 MISGUIDING", ("MFP", "MFP50", "MFP20", "OIvel")),
)

#: Shown before the groups: not votes, but the nearest zone's behaviour.
STATUS_COLS = ("Sup VOB", "Res VOB")

#: Tone per group, so a column's bucket is legible without reading the header.
GROUP_TONE = {"fast": BULL, "lag": INFO, "mis": VIOLET}

# ⚠️ No local bias map. `theme.bias_tone()` is the one owner — a fourth copy of
# BULL/BEAR/NEUTRAL colours is how "neutral" ends up meaning two things on one
# screen, which `test_theme_shared_maps.py` exists to prevent.


def _tone_of_cell(text: str) -> str:
    """Colour a glyph cell from the glyph itself — the builder's own encoding."""
    if "🟢" in text:
        return BULL
    if "🔴" in text:
        return BEAR
    if "🚀" in text:
        return BULL
    if "⚠️" in text:
        return BEAR
    if "🌫️" in text:
        return WARN
    return MUTED


def _verdict_chip(v: Any) -> str:
    """One speed bucket's verdict, from `overall['by_speed'][k]`."""
    d = v if isinstance(v, Mapping) else {}
    word = str(d.get("dir") or "").upper()
    if not word:
        return ""
    tone = bias_tone(word, MUTED)
    net = d.get("net")
    tail = f" {int(net):+d}" if isinstance(net, (int, float)) else ""
    return (f"<span style='font-size:9px;font-weight:800;color:{tone};"
            f"margin-left:5px'>{_esc(word)}{tail}</span>")


def leg_table_html(rows: Optional[Sequence[Mapping[str, Any]]] = None,
                   overall: Any = None) -> str:
    """The tabulation. `""` when no leg reported — never an empty grid.

    `rows` and `overall` are `build_leg_bias_table`'s return value, unchanged.
    """
    # ⚠️ `isinstance(rows, Sequence)` first: a bare int reached here in testing and
    # `for r in (7 or ())` raises TypeError. A str IS a Sequence, hence the
    # explicit exclusion — iterating one yields characters, not rows.
    if isinstance(rows, str) or not isinstance(rows, (list, tuple)):
        return ""
    live = [r for r in rows if isinstance(r, Mapping) and r.get("Leg")]
    if not live:
        return ""
    ov = overall if isinstance(overall, Mapping) else {}
    by_speed = ov.get("by_speed") if isinstance(ov.get("by_speed"), Mapping) else {}

    # ── header: Leg · LTP · status · the three groups · verdicts ──────
    head = [_th("LEG", "left"), _th("LTP", "right")]
    head += [_th(c.replace(" VOB", ""), "center", MUTED) for c in STATUS_COLS]
    for key, label, cols in GROUPS:
        tone = GROUP_TONE.get(key, MUTED)
        for i, c in enumerate(cols):
            head.append(_th(c, "center", tone,
                            border_left=(i == 0)))
    # ⚠️ "VERDICT", not "LEG" — it read "LEG" and duplicated the first column's
    # header, so the row's own conclusion looked like a second leg name.
    head += [_th("VERDICT", "left", MUTED), _th("→ NIFTY", "left", MUTED)]

    # ── the group banner above it, carrying each bucket's own verdict ──
    banner = [f"<th colspan='{2 + len(STATUS_COLS)}'></th>"]
    for key, label, cols in GROUPS:
        banner.append(
            f"<th colspan='{len(cols)}' style='text-align:center;"
            f"font-size:9px;letter-spacing:.08em;padding:2px 4px;"
            f"color:{GROUP_TONE.get(key, MUTED)};font-weight:700;"
            f"border-left:1px solid {CARD_BORDER}'>{_esc(label)}"
            f"{_verdict_chip(by_speed.get(key))}</th>")
    banner.append("<th colspan='2'></th>")

    body = []
    for r in live:
        cells = [
            f"<td style='text-align:left;padding:3px 5px;color:{BRIGHT};"
            f"font-size:11px;white-space:nowrap'>{_esc(r.get('Leg'))}</td>",
            f"<td style='text-align:right;padding:3px 5px;color:{INK};"
            f"font-size:11px;font-weight:700'>{_esc(r.get('LTP'))}</td>",
        ]
        for c in STATUS_COLS:
            val = str(r.get(c) or "—")
            cells.append(f"<td style='text-align:center;padding:3px 4px;"
                         f"font-size:9.5px;white-space:nowrap;"
                         f"color:{_tone_of_cell(val)}'>{_esc(val)}</td>")
        for key, _label, cols in GROUPS:
            for i, c in enumerate(cols):
                val = str(r.get(c) or "⚪")
                bl = (f"border-left:1px solid {CARD_BORDER};" if i == 0 else "")
                cells.append(f"<td style='text-align:center;padding:3px 4px;"
                             f"font-size:11px;{bl}'>{_esc(val)}</td>")
        for c in ("Leg Verdict", "→ NIFTY"):
            val = str(r.get(c) or "—")
            cells.append(f"<td style='text-align:left;padding:3px 6px;"
                         f"font-size:10px;font-weight:700;white-space:nowrap;"
                         f"color:{_tone_of_cell(val)}'>{_esc(val)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")

    # ⚠️ 19 signal columns will not fit a phone or a narrow pane, and a table
    # that forces the PAGE to scroll sideways makes every other panel unusable.
    # Scrolls inside its own box.
    table = (f"<div style='overflow-x:auto'>"
             f"<table style='width:100%;border-collapse:collapse'>"
             f"<thead><tr>{''.join(banner)}</tr>"
             f"<tr>{''.join(head)}</tr></thead>"
             f"<tbody>{''.join(body)}</tbody></table></div>")

    return _card("🧮 ATM±1 leg tabulation", table + _footer(ov, len(live)))


def _th(text: str, align: str, tone: str = MICRO,
        border_left: bool = False) -> str:
    bl = f"border-left:1px solid {CARD_BORDER};" if border_left else ""
    return (f"<th style='text-align:{align};font-size:8.5px;"
            f"letter-spacing:.06em;color:{tone};font-weight:600;"
            f"padding:3px 4px;{bl}border-bottom:1px solid {CARD_BORDER};"
            f"white-space:nowrap'>{_esc(text)}</th>")


def _footer(ov: Mapping[str, Any], n_legs: int) -> str:
    """The overall verdict, plus what the glyphs mean.

    The overall line is `build_leg_bias_table`'s own aggregate — it is NOT
    re-derived from the rows above, because two answers to "what is the net
    read?" on one card is exactly the disagreement this file must not create.
    """
    word = str(ov.get("label") or "").upper()
    out = ""
    if word:
        tone = bias_tone(ov.get("dir"), MUTED)
        bull, bear = ov.get("bull"), ov.get("bear")
        counts = (f" · {bull} bull / {bear} bear leg(s)"
                  if isinstance(bull, int) and isinstance(bear, int) else "")
        out += (f"<div style='margin-top:6px;padding-top:5px;"
                f"border-top:1px solid {CARD_BORDER};font-size:11.5px;"
                f"font-weight:800;color:{tone}'>{_esc(ov.get('em') or '')} "
                f"{_esc(word)}"
                f"<span style='font-size:10px;font-weight:600;color:{MICRO}'>"
                f"{_esc(counts)}</span></div>")
    out += (f"<div style='font-size:9px;color:{MICRO};margin-top:4px'>"
            f"{n_legs} leg(s) · each signal in the LEG's own direction; "
            f"→ NIFTY flips for PE legs. 🟢 bull · 🔴 bear · ⚪ neutral. "
            f"Zone status: 🚀 building · 🌫️ fading · ⚠️ breaking · • intact."
            f"</div>")
    return out


def micro(rows: Optional[Sequence[Mapping[str, Any]]] = None,
          overall: Any = None) -> str:
    """One line — the three speed verdicts, which is the actionable summary.

    Fast disagreeing with lagging is the read a trader wants at a glance: the
    move is turning, or it is confirmed.
    """
    ov = overall if isinstance(overall, Mapping) else {}
    by = ov.get("by_speed") if isinstance(ov.get("by_speed"), Mapping) else {}
    bits = []
    for key, label, _cols in GROUPS:
        d = by.get(key)
        word = str((d or {}).get("dir") or "").upper() if isinstance(d, Mapping) else ""
        if word:
            bits.append(f"{label.split(' ')[0]} {word.lower()}")
    return "🧮 " + " · ".join(bits) if bits else ""
