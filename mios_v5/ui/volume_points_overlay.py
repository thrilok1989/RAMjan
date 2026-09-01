"""📍 High-volume pivots on a panel: the marker, the level, and its fate.

Each kept pivot gets a dot at the bar it formed on and a horizontal level from that
bar to the right edge. Live levels are solid; a level price has closed through is
`dot`, dimmed, and stops at the bar it broke — where support failed is information,
so broken levels are kept rather than deleted.

Line thickness carries the pivot's normalised volume and nothing else, so "thicker"
always means "more participation" and never anything about direction.

⚠️ Imports no plotly. Like `profile_overlay`, everything here is a method call on the
figure it was handed — `add_scatter`, `add_shape` — so the module stays importable and
testable without plotly installed, and a guard test keeps it that way.

⚠️ Advisory in the strongest sense: wrapped so a malformed point list can never take
the chart down. A terminal that fails to render because one overlay was wrong is worse
than a terminal with one overlay missing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: side → (colour, marker). The reference's own two colours, kept because the
#: overlay is recognisable by them.
SIDE_STYLE = {
    "HIGH": ("#fda05e", "circle"),
    "LOW": ("#2fd68e", "circle"),
}

#: A live level is solid; a broken one is dotted and dimmed. Two states, stated once.
LIVE_DASH, BROKEN_DASH = "solid", "dot"
BROKEN_OPACITY = 0.35

#: Marker size floor and the per-weight step. `weight` is 1-5 from the normalised
#: volume, so the dot grows with participation.
DOT_BASE, DOT_STEP = 5.0, 1.6


def _esc(s: str) -> str:
    """Plotly annotations accept a small HTML subset, so `<` must not pass through."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _len(x: Any) -> int:
    """`len(x)`, or 0 for anything without one.

    ⚠️ Never `if x`: the axis arrives as a pandas DatetimeIndex and `if x` on one
    raises "The truth value of a DatetimeIndex is ambiguous". And never a bare
    `len(x)` either — a scalar has none, and this is called on caller-supplied data.
    """
    if x is None:
        return 0
    try:
        return len(x)
    except TypeError:
        return 0


def _at(x: Optional[Sequence[Any]], i: Any) -> Any:
    """The x value at bar `i`, or `None` when the index is off the axis.

    ⚠️ Bounds-checked. The points are computed on the panel's own frame but the
    figure's x axis is the SHARED timeline every panel is aligned onto, so a leg that
    started late has fewer x values than the frame the pivots came from. An unchecked
    index raised; a clamped one would put the marker on the wrong minute.
    """
    try:
        k = int(i)
    except (TypeError, ValueError):
        return None
    if k < 0 or k >= _len(x):
        return None
    return x[k]


def specs(points: Sequence[Mapping[str, Any]],
          x: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    """One drawable spec per pivot: `{x0, x1, y, colour, dash, width, size, live}`.

    Separated from the drawing so the geometry is testable without a figure, which is
    how the off-the-axis case above was found.
    """
    out: List[Dict[str, Any]] = []
    # ⚠️ Iterability, not truthiness — `7` is truthy and not iterable, and this is
    # caller-supplied data.
    if isinstance(points, (str, bytes)) or not _len(points):
        return out
    # ⚠️ `len(x)`, NEVER `if x`. The axis arrives as a pandas DatetimeIndex, and
    # `if x` on one raises "The truth value of a DatetimeIndex is ambiguous" —
    # which `draw`'s own except swallowed, so every panel silently drew no pivots
    # while the unit tests, which hand in plain lists, all passed. Found by
    # rendering it.
    n_x = _len(x)
    last = (n_x - 1) if n_x else None
    for p in points:
        if not isinstance(p, Mapping):
            continue
        y = _f(p.get("price"))
        x0 = _at(x, p.get("index"))
        if y is None or x0 is None:
            continue
        broken = p.get("broken_at")
        end = _at(x, broken) if broken is not None else _at(x, last)
        colour, marker = SIDE_STYLE.get(str(p.get("side") or "").upper(),
                                        ("#8f9bab", "circle"))
        w = max(1, min(5, int(_f(p.get("weight")) or 1)))
        out.append({
            "x0": x0, "x1": end if end is not None else x0, "y": y,
            "colour": colour, "marker": marker,
            "dash": BROKEN_DASH if broken is not None else LIVE_DASH,
            "width": 0.8 + w * 0.35,
            "size": DOT_BASE + w * DOT_STEP,
            "opacity": BROKEN_OPACITY if broken is not None else 0.95,
            "live": broken is None,
            "norm": _f(p.get("norm")),
        })
    return out


def draw(fig, row: int, col: int,
         points: Optional[Sequence[Mapping[str, Any]]] = None,
         x: Optional[Sequence[Any]] = None,
         why: Optional[str] = None) -> Dict[str, int]:
    """Add one panel's high-volume pivots. Returns what was drawn.

    `why` is drawn as a corner note when there is nothing to plot. ⚠️ Reported as
    "not displaying in the put ltp", and a strongly trending leg genuinely has NO
    swing pivots — the window's extreme sits at its edge, never its centre, which is
    exactly what a put does while the index falls. The overlay was right to draw
    nothing and wrong to say nothing: an empty panel and a broken panel look
    identical. `volume_points.read()` already produces the sentence.
    """
    drawn = {"levels": 0, "dots": 0, "note": 0}
    if fig is None:
        return drawn
    try:
        sp = specs(points or (), x)
        if not sp:
            if why:
                fig.add_annotation(
                    row=row, col=col, xref="x domain", yref="y domain",
                    x=0.02, y=0.03, showarrow=False, align="left",
                    text=f"📍 {_esc(str(why))}",
                    font=dict(size=8, color="#8f9bab"))
                drawn["note"] = 1
            return drawn
        for s in sp:
            # ⚠️ `add_shape` with explicit x0/x1, not `add_hline`: a level starts at
            # the bar its pivot formed on and ends where it broke. `add_hline` spans
            # the whole panel, which would claim the level existed before the pivot
            # that made it.
            fig.add_shape(type="line", x0=s["x0"], x1=s["x1"],
                          y0=s["y"], y1=s["y"], row=row, col=col,
                          line=dict(color=s["colour"], width=s["width"],
                                    dash=s["dash"]),
                          opacity=s["opacity"], layer="below")
            drawn["levels"] += 1
        fig.add_scatter(
            x=[s["x0"] for s in sp], y=[s["y"] for s in sp],
            mode="markers", name="HV pivot", showlegend=False,
            marker=dict(size=[s["size"] for s in sp],
                        color=[s["colour"] for s in sp],
                        opacity=[s["opacity"] for s in sp],
                        line=dict(width=0)),
            customdata=[[s["norm"]] for s in sp],
            hovertemplate=("HV pivot %{y:,.2f}<br>vol %{customdata[0]:.2f}×"
                           "<extra></extra>"),
            row=row, col=col)
        drawn["dots"] = len(sp)
    except Exception:
        # Silent by design, same as `profile_overlay`: `terminal_chart` reports
        # undrawable series through `notes`, and a traceback in a chart helper
        # reaches the user as a broken panel rather than as information.
        pass
    return drawn


def micro(pts: Sequence[Mapping[str, Any]], spot: Any = None) -> str:
    """`📍 2 live HV levels · next ₹24,680 above` — one line, no side.

    Worded here so the header and the panel cannot describe the same pivots
    differently. Produces no direction: "the next level up" is not a trade.
    """
    from ..volume_points import read as _read
    r = _read(pts, spot)
    if not r["n"]:
        return f"📍 {r['why']}" if r.get("why") else ""
    bits = [f"{r['live']} live HV level" + ("s" if r["live"] != 1 else "")]
    for key, word in (("nearest_above", "above"), ("nearest_below", "below")):
        p = r.get(key)
        if isinstance(p, Mapping) and _f(p.get("price")) is not None:
            bits.append(f"₹{float(p['price']):,.0f} {word}")
    return "📍 " + " · ".join(bits)
