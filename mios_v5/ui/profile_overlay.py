"""The liquidity & sentiment profile, drawn on a price panel.

Pure presentation. Every value here was computed by somebody else — the bins by
`calculate_money_flow_profile`, the POC and value area by `compute_vpfr` (the
one POC owner, audit 71.8), the shape by Stage 71.86. This file decides where
things sit and what colour they are, and nothing else.

## Why the bins are drawn as a band, not a histogram

A Plotly price panel has one x-axis and it is time. A volume-profile histogram
needs a second, and faking one with a bar trace puts volume bars *in the
timeline*, where they read as trades that happened at those moments. So the
profile is drawn as **full-width horizontal bands whose opacity carries the
volume** — a heavy level is a strong band, a thin level is nearly invisible.

Opacity rather than width keeps every level anchored to its own price, which is
the only thing a trader reads off a profile in the first place.

## Sentiment colours the band, volume sets its strength

Two facts on one mark, and they are independent: `sentiment` (which side traded
there) picks the hue, `ratio` (how much traded there) picks the opacity. A
heavy bullish node and a thin bullish node are the same colour at different
strengths, which is what makes the heavy one findable at a glance.

`Neutral` sentiment is grey rather than a blend — a bin where buyers and
sellers were even is not a weak bull bin.

## Nothing is drawn that was not reported

A missing POC draws no line. A bin with no volume draws no band. There is no
placeholder mark anywhere in this file, because a placeholder on a price chart
is a level that does not exist rendered at a price that does.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .theme import FAINT, MICRO

UNKNOWN = "UNKNOWN"

#: sentiment → the band's hue. Matched to the candle colours already used by
#: `terminal_chart`, so a bullish node and a bullish candle are the same green.
_SENTIMENT = {
    "BULLISH": "38, 166, 154",     # #26a69a
    "BEARISH": "239, 83, 80",      # #ef5350
    "NEUTRAL": "120, 123, 134",    # #787b86
}

#: node_type → how much the band is allowed to assert itself. High-volume nodes
#: are where price is likely to pause; low-volume nodes are where it travels.
#: Drawing both at one strength would hide the distinction the profile exists
#: to show.
_NODE_GAIN = {"HIGH": 1.0, "AVERAGE": 0.62, "LOW": 0.34}

#: The heaviest band never reaches full opacity — candles must stay readable
#: through it. A profile that hides the price is a worse chart, not a richer one.
MAX_OPACITY = 0.30
MIN_OPACITY = 0.02

#: POC · VAH · VAL — the three lines from the one POC owner.
LEVEL_STYLE = {
    "poc": ("#ff5252", "solid", 1.6, "POC"),
    "vah": ("#00bcd4", "dot", 1.1, "VAH"),
    "val": ("#00bcd4", "dot", 1.1, "VAL"),
    # ⚠️ THICK and BRIGHT, and thicker than the static POC on purpose. Asked for,
    # and it is the right weight: this is the line that MOVES, so it carries the
    # session's story while POC/VAH/VAL are one frozen reading each. At 1.3px dashdot
    # amber it was the faintest thing on a panel full of thin dotted levels.
    "dynamic_poc": ("#ffbf00", "solid", 3.0, "Dyn PoC"),
}

#: Stage 71.86's shapes → the badge tone. `Neutral` is deliberately the faintest:
#: it means the read was absent, and it must not draw the eye like a verdict.
#:
#: `FAINT` comes from the theme rather than being written out here. The obvious
#: grey for "faintest" is one of the palette's RETIRED greys, which sit near
#: 4:1 on a card and which a test already forbids in every panel — faint is not
#: the same as unreadable.
SHAPE_TONE = {
    "P": "#26a69a", "b": "#ef5350", "D": "#00bcd4",
    "Double Distribution": "#ffb300", "Trend": "#a78bfa",
    "Balanced": MICRO, "Thin": FAINT, "Neutral": FAINT,
}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "").strip().upper()


def bands(rows: Optional[Sequence[Mapping[str, Any]]] = None,
          max_opacity: float = MAX_OPACITY) -> List[Dict[str, Any]]:
    """One band spec per bin: `{y0, y1, colour, opacity, why}`.

    Returned as plain dicts rather than drawn directly so the mapping from a
    profile row to a mark is testable without Plotly, and so a caller that is
    not a Plotly chart (a Telegram render, an export) can use the same
    decisions.
    """
    out: List[Dict[str, Any]] = []
    for r in rows or ():
        if not isinstance(r, Mapping):
            continue
        lo, hi = _f(r.get("bin_low")), _f(r.get("bin_high"))
        if lo is None or hi is None or hi <= lo:
            continue

        ratio = _f(r.get("ratio"))
        if ratio is None:
            # `ratio` is the producer's own volume/max — without it there is
            # nothing to scale by, and inventing a scale would make a thin
            # level look heavy.
            continue
        ratio = max(0.0, min(1.0, ratio))
        if ratio <= 0:
            continue

        rgb = _SENTIMENT.get(_s(r.get("sentiment")), _SENTIMENT["NEUTRAL"])
        gain = _NODE_GAIN.get(_s(r.get("node_type")), _NODE_GAIN["AVERAGE"])
        opacity = max(MIN_OPACITY, min(max_opacity, max_opacity * ratio * gain))

        out.append({
            "y0": lo, "y1": hi,
            "colour": f"rgba({rgb}, {opacity:.3f})",
            "opacity": round(opacity, 3),
            "node_type": r.get("node_type", UNKNOWN),
            "sentiment": r.get("sentiment", UNKNOWN),
            "ratio": round(ratio, 4),
            "is_poc": bool(r.get("is_poc")),
        })
    return out


def levels(profile: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """POC · VAH · VAL specs, skipping anything the producer did not report."""
    p = profile or {}
    pairs = (("poc", p.get("poc_price", p.get("poc"))),
             ("vah", p.get("value_area_high", p.get("vah"))),
             ("val", p.get("value_area_low", p.get("val"))),
             ("dynamic_poc", p.get("dynamic_poc")))
    out: List[Dict[str, Any]] = []
    for key, raw in pairs:
        v = _f(raw)
        if v is None:
            continue
        colour, dash, width, label = LEVEL_STYLE[key]
        out.append({"key": key, "y": v, "colour": colour, "dash": dash,
                    "width": width, "label": label})
    return out


def shape_badge(shape: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Stage 71.86's verdict as a corner annotation, or `None`.

    Reads a `ProfileShape` or a stored dict identically, so a replayed profile
    annotates like a live one.
    """
    if shape is None:
        return None
    name = getattr(shape, "shape", None)
    if name is None and isinstance(shape, Mapping):
        name = shape.get("shape")
    if not name:
        return None

    conf = getattr(shape, "confidence", None)
    if conf is None and isinstance(shape, Mapping):
        conf = shape.get("confidence")
    conf_txt = "" if conf in (None, UNKNOWN) else f" · {_f(conf):.0f}%"

    why = getattr(shape, "why", None)
    if why is None and isinstance(shape, Mapping):
        why = shape.get("why")

    return {"text": f"{name}{conf_txt}",
            "colour": SHAPE_TONE.get(str(name), SHAPE_TONE["Neutral"]),
            "why": str(why or "")}


def draw(fig, row: int, col: int,
         rows: Optional[Sequence[Mapping[str, Any]]] = None,
         profile: Optional[Mapping[str, Any]] = None,
         shape: Optional[Any] = None,
         max_opacity: float = MAX_OPACITY,
         labels_inside: bool = False,
         x: Optional[Sequence[Any]] = None) -> Dict[str, int]:
    """Add the profile to one panel. Returns what was drawn.

    `labels_inside` turns the POC/VAH/VAL text back into the panel instead of
    letting it run off the right-hand edge.

    ⚠️ It exists because Plotly's `annotation_position="right"` means *outside*:
    it resolves to `x=1, xanchor="left"`, so the label starts at the right edge
    and continues past it. On the index panel that overhang lands in the gap
    between columns and reads fine. On the two option panels — the rightmost
    column, against an 8px figure margin — it was being **cut off**, so those
    charts have been drawing a POC line whose label the reader could not see.
    Callers pass True for any panel with nothing to its right.

    Advisory in the strongest sense: it is wrapped so a malformed profile can
    never take the chart down. A terminal that fails to render because one
    overlay was wrong is worse than a terminal with no overlay.
    """
    drawn = {"bands": 0, "levels": 0, "badge": 0, "dyn_poc": 0}
    if fig is None:
        return drawn
    try:
        for band in bands(rows, max_opacity=max_opacity):
            fig.add_hrect(y0=band["y0"], y1=band["y1"], row=row, col=col,
                          layer="below", line_width=0,
                          fillcolor=band["colour"])
            drawn["bands"] += 1

        for lv in levels(profile):
            fig.add_hline(y=lv["y"], row=row, col=col,
                          line_width=lv["width"], line_dash=lv["dash"],
                          line_color=lv["colour"],
                          annotation_text=lv["label"],
                          annotation_position="right",
                          annotation=(dict(xanchor="right") if labels_inside
                                      else None),
                          annotation_font=dict(size=8, color=lv["colour"]))
            drawn["levels"] += 1

        # 📈 The dynamic PoC as a STEPLINE, when the caller supplied an x axis.
        #
        # ⚠️ A stepline, not a smooth line: the PoC is the busiest price BIN, so it
        # holds a level and then relocates a whole bin at a time. Interpolating
        # between two bins draws prices that were never the point of control. This is
        # the same reason the daily multi-window curves use `shape="hv"`.
        #
        # The horizontal `dynamic_poc` level above marks where it is NOW and is
        # labelled; this shows how it got there. Both come from the one
        # `compute_dynamic_poc`.
        series = (profile or {}).get("dynamic_poc_series")
        if x is not None and series:
            n = min(len(x), len(series))
            ys = [_f(v) for v in series[:n]]
            if any(v is not None for v in ys):
                colour, dash, width, _lbl = LEVEL_STYLE["dynamic_poc"]
                # ⚠️ `fig.add_scatter`, NOT `go.Scatter` — this module imports no
                # plotly at all (a guard test enforces it) and only ever calls
                # methods on the figure it was handed. `add_scatter` is the same
                # trace with no import, which is why the guard can stay strict.
                fig.add_scatter(
                    x=list(x)[:n], y=ys, mode="lines", name="Dyn PoC",
                    showlegend=False, connectgaps=False,
                    hovertemplate="Dyn PoC %{y:,.2f}<extra></extra>",
                    # width and dash from LEVEL_STYLE, so the stepline and the
                    # labelled level it ends at cannot drift apart
                    line=dict(color=colour, width=width, shape="hv", dash=dash),
                    row=row, col=col)
                drawn["dyn_poc"] = 1

        badge = shape_badge(shape)
        if badge:
            fig.add_annotation(row=row, col=col, xref="x domain",
                               yref="y domain", x=0.02, y=0.97,
                               showarrow=False, text=badge["text"],
                               font=dict(size=9, color=badge["colour"]),
                               align="left")
            drawn["badge"] = 1
    except Exception:
        # Deliberately silent: `terminal_chart` already reports undrawable
        # series through `notes`, and a traceback in a chart helper reaches
        # the user as a broken panel rather than as information.
        pass
    return drawn
