"""🏛 The layered POC picture — four rolling POCs on a daily axis, no candles.

One figure: price on y, daily dates on x, and one curve per structural window. The
visual hierarchy is the reference indicator's — slower windows thicker and calmer,
faster ones thinner — because the ORDER of the curves is the read, and a hierarchy
makes that order legible at a glance.

⚠️ **No candles, by request and by design.** With bars drawn, the eye follows the
bars and the POCs become decoration. Without them the picture is the one thing it is
for: where value sits at four scales, and which way it is migrating.

⚠️ **No price series is invented to fill the gap either.** A close line would be a
price chart by another name, and `terminal_chart` is this app's one price chart —
`test_no_second_chart_was_created` enforces that, and this module is named
`poc_structure` rather than `*_chart` so the guard stays exactly as strict.
The current spot is drawn as a single horizontal marker, which is all the reference
price these curves need.

Figures in, figures out — `plotly.graph_objects` only. Streamlit renders them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .. import poc_series as PS

SPOT_COLOUR = "#ffffff"

#: Which side of a window price sits on → tone. Above value reads constructive,
#: below reads heavy; `AT` is neither and takes the neutral tone.
SIDE_TONE = {"ABOVE": "#00cc66", "BELOW": "#ff4444", "AT": "#ffd000"}

#: Migration direction → glyph. One map, so the table and any caption agree.
MIGRATE_GLYPH = {"UP": "↑", "DOWN": "↓", "FLAT": "→"}


def _esc(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def figure(dates: Sequence[Any], series: Mapping[str, Sequence[Any]],
           spot: Any = None, subdaily: Optional[Mapping[str, Any]] = None):
    """One figure, or `None` when there is nothing to draw.

    ⚠️ `subdaily` is accepted and deliberately NOT drawn here — see `subdaily_line`.
    The first version put the 1H and 4H POCs on as dashed `hline`s, and because both
    sit within a few points of spot on a three-year axis, their annotations and the
    spot annotation piled into one unreadable smear at the right edge. Three intraday
    levels rendered against 1,250 daily bars carry no visual information anyway; they
    are a sentence, so they are printed as one. The parameter stays so callers do not
    have to change and so this note has somewhere to live.
    """
    try:
        import plotly.graph_objects as go
    except Exception:
        return None
    if not series or not dates:
        return None

    fig = go.Figure()
    drew = False
    # slowest first, so the thick anchor is painted under the faster curves
    order = [label for label, _w in PS.WINDOWS][::-1]
    for label in order + [k for k in series if k not in order]:
        vals = series.get(label)
        if not vals:
            continue
        colour, width = PS.STYLE.get(label, ("#8f9bab", 2.0))
        fig.add_trace(go.Scatter(
            x=list(dates)[:len(vals)], y=list(vals), mode="lines",
            name=f"{label} POC", connectgaps=False,
            # ⚠️ STEPPED, not straight. A POC is a MODAL statistic — the busiest
            # price bin — so it holds a level and then relocates; measured over a
            # year it jumps thousands of points when a new level takes over as
            # most-traded. That is not a resolution artefact: quadrupling the bin
            # count leaves the jumps identical (5 moves over ₹1,000 either way).
            # A straight segment between two modes would draw a ramp through prices
            # that were never the mode. `hv` says "held, then moved", which is what
            # happened.
            line=dict(color=colour, width=width, shape="hv"),
            hovertemplate=f"{label} POC %{{y:,.0f}}<extra></extra>"))
        drew = True
    if not drew:
        return None

    sp = PS._f(spot)
    if sp is not None:
        fig.add_hline(y=sp, line_width=1.4, line_color=SPOT_COLOUR,
                      annotation_text=f"spot {sp:,.0f}",
                      annotation_position="left",
                      annotation_font=dict(size=10, color=SPOT_COLOUR))

    fig.update_layout(
        template="plotly_dark", height=420, hovermode="x unified",
        margin=dict(l=10, r=70, t=30, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.01,
                    xanchor="left", x=0, font=dict(size=10)),
        xaxis=dict(title="", showgrid=False),
        yaxis=dict(title="POC (₹)", gridcolor="#232a35"),
        plot_bgcolor="#12161d", paper_bgcolor="#12161d")
    return fig


def table_html(rows: Sequence[Mapping[str, Any]],
               align: Optional[Mapping[str, Any]] = None) -> str:
    """The structure table: window · what it means · POC · side · distance · drift.

    ⚠️ The `side` column says ABOVE / BELOW — it does **not** say ACCEPTED. The
    reference indicator's table conflates the two, and acceptance needs consecutive
    closes, which Stage 42 already owns. Printing "✓ ABOVE" here would be a second
    verdict on a question that has an answer elsewhere.
    """
    if not rows or isinstance(rows, str):
        return ""
    cells: List[str] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        label = _esc(r.get("label"))
        colour, _w = PS.STYLE.get(str(r.get("label")), ("#cfd9e6", 2.0))
        side = str(r.get("side") or "")
        tone = SIDE_TONE.get(side, "#8f9bab")
        dist = r.get("distance")
        pct = r.get("distance_pct")
        mig = str(r.get("migrated") or "")
        cells.append(
            f"<tr>"
            f"<td style='padding:5px 9px;color:{colour};font-weight:800'>{label}</td>"
            f"<td style='padding:5px 9px;color:#8f9bab;font-size:11px'>"
            f"{_esc(r.get('means'))}</td>"
            f"<td style='padding:5px 9px;color:#e8eef7;font-weight:700;"
            f"text-align:right'>₹{PS._f(r.get('poc')) or 0:,.0f}</td>"
            f"<td style='padding:5px 9px;color:{tone};font-weight:800'>"
            f"{_esc(side) or '—'}</td>"
            f"<td style='padding:5px 9px;color:#cfd9e6;text-align:right'>"
            + (f"{dist:+,.0f} pts" if isinstance(dist, (int, float)) else "—")
            + (f" <span style='color:#8f9bab;font-size:11px'>({pct:.2f}%)</span>"
               if isinstance(pct, (int, float)) else "")
            + f"</td>"
            f"<td style='padding:5px 9px;color:#cfd9e6'>"
            f"{MIGRATE_GLYPH.get(mig, '·')} {_esc(mig.title())}</td>"
            f"</tr>")
    if not cells:
        return ""
    head = "".join(
        f"<th style='padding:5px 9px;text-align:left;color:#8f9bab;"
        f"font-size:10px;letter-spacing:.08em;font-weight:700'>{h}</th>"
        for h in ("WINDOW", "IS", "POC", "PRICE", "DISTANCE", "VALUE MOVED"))
    foot = ""
    if isinstance(align, Mapping) and align.get("label"):
        foot = (f"<div style='padding:6px 9px;color:#e8eef7;font-size:12px;"
                f"font-weight:700'>{_esc(align['label'])}</div>"
                f"<div style='padding:0 9px 7px;color:#8f9bab;font-size:10px'>"
                f"Where price sits in the stack — context, not a signal. "
                f"No side is produced here.</div>")
    return (f"<div style='background:#12161d;border:1px solid #232a35;"
            f"border-radius:8px;overflow:hidden;margin-top:6px'>"
            f"<table style='width:100%;border-collapse:collapse'>"
            f"<tr>{head}</tr>{''.join(cells)}</table>{foot}</div>")


def subdaily_line(subdaily: Optional[Mapping[str, Any]] = None,
                  spot: Any = None) -> str:
    """The 1H / 4H current POCs as one sentence, with which side of each price is.

    They are levels, not curves: four hours is finer than a daily bar, so there is
    nothing to roll. Saying that in words costs one line and keeps three intraday
    levels from being drawn across three years of daily bars.
    """
    sp = PS._f(spot)
    bits: List[str] = []
    for label in PS.SUBDAILY:
        p = PS._f((subdaily or {}).get(label))
        if p is None:
            continue
        side = ""
        if sp is not None:
            tone = SIDE_TONE["ABOVE" if sp > p else "BELOW" if sp < p else "AT"]
            word = "above" if sp > p else "below" if sp < p else "at"
            side = (f" <span style='color:{tone}'>({word} "
                    f"{abs(sp - p):,.0f})</span>")
        bits.append(f"<b>{_esc(label)}</b> ₹{p:,.0f}{side}")
    if not bits:
        return ""
    return (f"<div style='margin-top:5px;color:#8f9bab;font-size:11px'>"
            f"intraday POC — a level, not a curve: {' · '.join(bits)}</div>")


def micro(rows: Sequence[Mapping[str, Any]],
          align: Optional[Mapping[str, Any]] = None) -> str:
    """One line for the chrome strip."""
    if isinstance(align, Mapping) and align.get("reporting"):
        top = next((r for r in (rows or ())
                    if str(r.get("label")) == "Yearly"), None)
        anchor = (f" · anchor ₹{PS._f(top.get('poc')) or 0:,.0f}"
                  if isinstance(top, Mapping) else "")
        return f"🏛 {align.get('label')}{anchor}"
    return ""
