"""📊 Per-strike Call vs Put OI and ΔOI — one figure per ATM±2 strike.

Five strikes × two measures, each figure showing CE against PE over the session,
plus the verdict the reference layout puts under each chart: which side is heavier
(support vs resistance) and, from OI direction against LTP direction, whether that
is building or covering.

⚠️ **Every conclusion here is arithmetic on the stored series** — no engine is
consulted and none is second-guessed. The OI/LTP quadrant rule is the standard
one, stated once in `POSITION_READ` rather than as four scattered branches:

    OI ↑ + price ↑   long building
    OI ↑ + price ↓   short building (writing)
    OI ↓ + price ↑   short covering
    OI ↓ + price ↓   long unwinding

⚠️ The "OI ↑/↓" here is the **recent trend** — the change over the last
`TREND_LOOKBACK` snapshots — NOT the drift since snapshotting began, and NOT the
day-cumulative ΔOI. Both of those net positive through a normal session (OI
accumulates), so they can only ever surface the two BUILDING rows; only the
recent direction turns negative when writers are covering *now*, which is what
lets the covering/unwinding rows appear — see `side_read`.

For a CE leg, writing is resistance; for a PE leg, writing is support. The flip is
applied in one place, `side_read`, for the same reason.

Figures in, figures out — `plotly.graph_objects` only. Streamlit renders them.

⚠️ Named `*_series`, not `*_charts`: `test_no_second_chart_was_created` globs
`ui/*chart*.py` to keep `terminal_chart.py` the ONLY price chart in the app, and
that guard is worth more than the filename. These are OI time series, not a second
price chart, and renaming kept the guard exactly as strict.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .. import strike_history as SH

CE_COLOUR, PE_COLOUR = "#ff4444", "#00cc66"

#: OI direction × price direction → what the position is doing. One map, so the
#: four cases cannot drift apart across CE and PE.
POSITION_READ = {
    (1, 1): "LONG BUILDING", (1, -1): "SHORT BUILDING",
    (-1, 1): "SHORT COVERING", (-1, -1): "LONG UNWINDING",
}

#: Which side's writing creates which level. CE writing caps price (resistance);
#: PE writing supports it.
WRITING_MEANS = {"ce": "resistance", "pe": "support"}


def _sign(x: Any, eps: float = 0.0) -> int:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0
    return 1 if v > eps else (-1 if v < -eps else 0)


#: how many snapshots back "recent" spans for the building-vs-covering read. At
#: the ~18s snapshot cadence this is roughly the last 5 minutes — long enough not
#: to flip on one noisy print, short enough to show the CURRENT phase.
TREND_LOOKBACK = 15


def _window(vals: Sequence[Any],
            lookback: int) -> Tuple[Optional[float], Optional[float]]:
    """`(earlier, latest)` over the last `lookback` snapshots — or the whole
    series when it is shorter. `(None, None)` with fewer than two points."""
    nums = [v for v in vals if isinstance(v, (int, float))]
    if len(nums) < 2:
        return None, None
    earlier = nums[max(0, len(nums) - 1 - int(lookback))]
    return earlier, nums[-1]


def side_read(oi: Sequence[Any], ltp: Sequence[Any], side: str,
              lookback: int = TREND_LOOKBACK) -> Dict[str, Any]:
    """`{state, oi_pct, ltp_pct, means}` for one side of one strike.

    `means` is what the state implies for price — resistance or support — and is
    only set for the two WRITING/COVERING cases, because a long build in an option
    is not a statement about the index level.

    ⚠️ **Direction is the RECENT trend, over the last `lookback` snapshots — not
    the drift since collection began, and not the day-cumulative ΔOI.** Both of
    those net *positive* through a normal session (OI accumulates), so the panel
    could only ever say BUILDING — which is exactly the bug reported: every strike
    stuck on LONG/SHORT BUILDING, never covering. What separates writers *adding*
    from writers *covering* is which way OI is moving **now**, so a strike whose
    OI has turned down in the last few minutes reads as covering even while the
    day is still net-long OI. On a series of two points the window is those two,
    so the quadrant rule is unchanged for callers that pass a before/after pair.
    """
    o_a, o_b = _window(oi, lookback)
    l_a, l_b = _window(ltp, lookback)
    if o_a is None or l_a is None:
        return {"state": None, "oi_pct": None, "ltp_pct": None, "means": None}
    d_oi, d_ltp = _sign(o_b - o_a), _sign(l_b - l_a)
    state = POSITION_READ.get((d_oi, d_ltp))
    means = None
    if state == "SHORT BUILDING":
        means = f"{WRITING_MEANS.get(side, '')} building"
    elif state == "SHORT COVERING":
        means = f"{WRITING_MEANS.get(side, '')} weakening"
    return {"state": state,
            "oi_pct": (o_b - o_a) / o_a * 100 if o_a else None,
            "ltp_pct": (l_b - l_a) / l_a * 100 if l_a else None,
            "means": means}


def strike_read(store: Any, strike: Any) -> Dict[str, Any]:
    """Both sides of one strike, plus which is heavier right now."""
    out: Dict[str, Any] = {}
    for side, oi_f, ltp_f in (("ce", "ce_oi", "ce_ltp"),
                              ("pe", "pe_oi", "pe_ltp")):
        oi = SH.series(store, strike, oi_f)["v"]
        ltp = SH.series(store, strike, ltp_f)["v"]
        # the RECENT trend of OI drives building-vs-covering; see `side_read`.
        out[side] = side_read(oi, ltp, side)
        out[f"{side}_oi"] = oi[-1] if oi else None
    ce, pe = out.get("ce_oi"), out.get("pe_oi")
    if isinstance(ce, (int, float)) and isinstance(pe, (int, float)) and ce > 0 and pe > 0:
        ratio = pe / ce
        out["heavier"] = "PE" if pe > ce else ("CE" if ce > pe else None)
        out["ratio"] = ratio if pe > ce else (ce / pe if ce > pe else 1.0)
        # ⚠️ The same two thresholds the reference layout used, stated once.
        out["strength"] = ("STRONG" if out["ratio"] >= 2.0 else
                           "MODERATE" if out["ratio"] >= 1.3 else "WEAK")
        # ⚠️ Only when one side really IS heavier. `"support" if heavier == "PE"
        # else "resistance"` sent the None case — CE and PE exactly equal — down the
        # else branch, and the render showed "WEAK RESISTANCE · 1.0×" on a strike
        # with 9.0L against 9.0L. Equal OI is neither; a balanced strike says so.
        if out["heavier"]:
            out["level"] = "support" if out["heavier"] == "PE" else "resistance"
        else:
            out["level"], out["strength"] = None, None
            out["balanced"] = True
        # ⚠️ A level is made by WRITERS. The ratio only says which side is heavier,
        # and the render showed "STRONG RESISTANCE · 6.0×" sitting directly above
        # "CE: LONG BUILDING" — 6× the call OI, but accumulated by BUYERS, which is
        # the opposite of a ceiling. The ratio is not silently rewritten; the
        # contradiction is stated, so the two lines stop disagreeing.
        heavy = (out.get((out["heavier"] or "").lower()) or {}).get("state")
        out["level_state"] = heavy
        if heavy in ("LONG BUILDING", "LONG UNWINDING"):
            out["level_note"] = (
                f"weight only — the heavy {out['heavier']} side is buyers, "
                f"not writers")
    return out


def figures(store: Any, measure: str = "oi"):
    """`[(strike, label, figure)]` — one CE-vs-PE chart per strike.

    `measure` is `"oi"` or `"chg"`. Returns `[]` when there is nothing to plot,
    so a caller draws no empty axes.
    """
    try:
        import plotly.graph_objects as go
    except Exception:
        return []
    if measure not in ("oi", "chg"):
        return []
    window = SH.strikes(store)
    if not window:
        return []
    lab = SH.labels(window)
    ce_f, pe_f = (("ce_oi", "pe_oi") if measure == "oi"
                  else ("ce_chg", "pe_chg"))
    # OI reads naturally in lakhs, ΔOI in thousands — the units the reference
    # charts used, and applied HERE rather than in the store.
    div, unit = (100_000.0, "OI (L)") if measure == "oi" else (1_000.0, "ΔOI (K)")

    out = []
    for k in window:
        ce, pe = SH.series(store, k, ce_f), SH.series(store, k, pe_f)
        if not ce["v"] and not pe["v"]:
            continue
        # ⚠️ A single stored point needs a marker you can SEE and no time axis. At
        # size 3 the first snapshot rendered as a speck, under four x-ticks all
        # reading the same minute — which looked like an empty chart with clutter
        # rather than one honest observation.
        lone = max(len(ce["v"]), len(pe["v"])) < 2
        fig = go.Figure()
        for s, name, colour in ((ce, "Call", CE_COLOUR), (pe, "Put", PE_COLOUR)):
            if s["v"]:
                fig.add_trace(go.Scatter(
                    x=[_ts(t) for t in s["t"]],
                    y=[v / div for v in s["v"]],
                    mode="markers" if lone else "lines+markers", name=name,
                    line=dict(color=colour, width=2),
                    marker=dict(size=11 if lone else 3, color=colour)))
        if measure == "chg":
            fig.add_hline(y=0, line_dash="dash", line_color="white",
                          line_width=0.5)
        last_ce = (ce["v"][-1] / div) if ce["v"] else 0.0
        last_pe = (pe["v"][-1] / div) if pe["v"] else 0.0
        suffix = "L" if measure == "oi" else "K"
        sign = "+" if (measure == "chg" and last_ce >= 0) else ""
        sign_pe = "+" if (measure == "chg" and last_pe >= 0) else ""
        # ⚠️ The latest values are COLOURED IN THE TITLE and the legend is off.
        # With a legend at y=1.02 and a three-line title, the two drew on top of
        # each other and the render showed "ATM ₹24600 CE: 4…" clipped behind the
        # key — five times over. Colouring the numbers makes the key redundant
        # instead of just moving the collision somewhere else.
        fig.update_layout(
            title=dict(
                text=(f"<b>{lab.get(k, '')}</b> · ₹{k}<br>"
                      f"<span style='color:{CE_COLOUR}'>CE "
                      f"{sign}{last_ce:.1f}{suffix}</span>"
                      f"<span style='color:#7c8798'>  ·  </span>"
                      f"<span style='color:{PE_COLOUR}'>PE "
                      f"{sign_pe}{last_pe:.1f}{suffix}</span>"),
                font=dict(size=12), x=0.5, xanchor="center"),
            template="plotly_dark", height=280, showlegend=False,
            margin=dict(l=10, r=10, t=54, b=30),
            xaxis=dict(tickformat="%H:%M", title="",
                       showticklabels=not lone),
            yaxis=dict(title=unit),
            plot_bgcolor="#1e1e1e", paper_bgcolor="#1e1e1e")
        out.append((k, lab.get(k, ""), fig))
    return out


def _ts(t: Any):
    """Epoch seconds → an IST datetime, so the axis reads in market time."""
    try:
        from datetime import datetime

        import pytz
        return datetime.fromtimestamp(float(t), pytz.timezone("Asia/Kolkata"))
    except Exception:
        return t


def caption(store: Any) -> str:
    """How much history there is — never a bare chart with no provenance.

    ⚠️ Three states, because the render showed the middle one wrong twice. First it
    read "1 snapshot(s) · ATM±2 · OI in lakhs, ΔOI in thousands" — repeating the
    ATM±2 the heading already carried and quoting units for charts that were not
    drawn. Then it said a series needs two points and nothing was plotted, which
    was true of the code and wrong as a design: one snapshot IS the current level at
    each strike. Now it says what one snapshot can and cannot tell you.
    """
    r = SH.read(store)
    n = r["n"]
    if not n:
        return "no snapshots yet — the series builds as the chain refreshes"
    if n < 2:
        return ("first snapshot — current levels only, the build direction needs "
                "a second · OI in lakhs, ΔOI in thousands")
    span = (f" over {r['span_s'] / 60:.0f} min" if r.get("span_s") else "")
    return f"{n} snapshots{span} · OI in lakhs, ΔOI in thousands"
