"""MIOS V6 — Dashboard 2's terminal chart: NIFTY ‖ ATM Call ‖ ATM Put.

    ┌──────────────────────────┬──────────────────┐
    │                          │    ATM CALL      │
    │        NIFTY  (60%)      ├──────────────────┤
    │                          │    ATM PUT       │
    └──────────────────────────┴──────────────────┘

**One figure, not three.** This is the decision that makes the layout work.
Streamlit columns would give three independent Plotly figures, and Plotly can
only synchronise axes *within* a figure — so three figures means three
independently-scrolling charts, which is precisely what the terminal must not
be. A single figure with a `rowspan` cell and `matches="x"` on every axis gives
the requested proportions **and** real synchronised zoom, pan and crosshair.

`matches="x"` rather than `shared_xaxes=True`: the latter only links subplots
within a column, and NIFTY is in a different column from the option legs.

Each panel's levels belong to its own axis. Overlaying a spot-derived stop on
an option's price series would put a line at a price that series can never
trade — authoritative-looking and meaningless. So the option panels draw the
legs' own levels, from the legs' own engines, in premium.

The one exception is `⇢` projected levels, and it is an exception only in
appearance: `leg_projection` reports what a leg **actually traded at** the last
few times NIFTY was near the level. That number is measured off the shared
timeline, not converted from index points, so it belongs to the premium axis
like every other line on the panel. It is drawn `longdashdot` and labelled with
an arrow so it is never mistaken for the leg's own structure.

Tinting is applied as a below-layer rectangle rather than a plot background so
the candles keep their own colours. A chart whose body colour competes with its
candles is harder to read, not easier.

Not a pure module — it builds a Plotly figure. It computes no market logic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

_UP, _DOWN = "#26a69a", "#ef5350"

#: level → (colour, dash, width). Drawn on the NIFTY panel only.
LEVELS = {
    "entry":       ("#00ff88", "solid",   1.6),
    "stop":        ("#ff4444", "dash",    1.5),
    "trail":       ("#a78bfa", "dot",     1.5),
    "target":      ("#7fe8b0", "dashdot", 1.3),
    "support":     ("#17c98b", "dot",     1.2),
    "resistance":  ("#ff8c8c", "dot",     1.2),
    "war_zone":    ("#ffcc33", "dash",    1.4),
    "liquidity":   ("#4da6ff", "dot",     1.1),
    "vwap":        ("#c9b6ec", "solid",   1.2),
    # ── dealer hedging: the levels someone is obliged to defend ──
    # Violet is the house colour for dealer/gamma/charm, so these read as one
    # family and never compete with entry/stop, which are the trader's own.
    "gamma_flip":  ("#a78bfa", "longdash", 1.5),
    "dealer_wall": ("#8b5cf6", "solid",   1.4),
    "charm_pin":   ("#c4b5fd", "dot",     1.4),
    # ⭐ Stage 42 — the price a reaction actually happened at
    "reaction":    ("#7fe8b0", "dashdot", 1.4),
    "poc":         ("#ffe066", "dash",    1.3),
    "vah":         ("#7dffb0", "dot",     1.1),
    "val":         ("#ff8c8c", "dot",     1.1),
    # Premium Structure's volume nodes. Dimmer than the POC on purpose: they
    # are where price has spent time, not the single level it spent most of it
    # at, and drawing them at equal weight buries the POC among its own bins.
    "hvn":         ("#d9c15a", "dot",     1.0),
    "lvn":         ("#6b7a8f", "dot",     1.0),
    # ── ⇢ projected: a NIFTY level read off the premium axis ──
    # These are the ONLY spot-derived levels allowed on a premium panel, and
    # they are allowed because they are not spot-derived by the time they get
    # here: `leg_projection` reports what the leg actually traded at the last
    # few times NIFTY was near the level. Measured, not modelled.
    #
    # Every one is `longdashdot` — a dash pattern used by nothing else — so
    # "this line came from the other chart" is legible without reading the
    # label. Each keeps its family's colour so it still reads as a war zone or
    # a gamma flip.
    "proj_war_zone":   ("#ffcc33", "longdashdot", 1.2),
    "proj_gamma_flip": ("#a78bfa", "longdashdot", 1.2),
    "proj_liquidity":  ("#4da6ff", "longdashdot", 1.1),
    "proj_support":    ("#17c98b", "longdashdot", 1.1),
    "proj_resistance": ("#ff8c8c", "longdashdot", 1.1),
    "proj_poc":        ("#ffe066", "longdashdot", 1.1),
    "proj_vwap":       ("#c9b6ec", "longdashdot", 1.1),
}

LEVEL_LABEL = {
    "entry": "Entry", "stop": "Stop", "trail": "Trail", "target": "Target",
    "support": "Support", "resistance": "Resistance", "war_zone": "War Zone",
    "liquidity": "Liquidity", "vwap": "VWAP", "poc": "POC", "vah": "VAH",
    "val": "VAL", "gamma_flip": "Gamma Flip", "dealer_wall": "Dealer Wall",
    "charm_pin": "Charm Pin", "reaction": "Reaction",
    "hvn": "HVN", "lvn": "LVN",
    # ⇢ marks a level measured off the index panel rather than computed from
    # this leg's own structure. The arrow is the whole disclosure: a trader
    # must never have to remember which of two lines is the borrowed one.
    "proj_war_zone": "⇢ War Zone", "proj_gamma_flip": "⇢ Gamma Flip",
    "proj_liquidity": "⇢ Liquidity", "proj_support": "⇢ Support",
    "proj_resistance": "⇢ Resistance", "proj_poc": "⇢ POC",
    "proj_vwap": "⇢ VWAP",
}

#: Which subplot column the two option legs occupy. They are the rightmost
#: thing in the figure, which is what makes a right-positioned annotation on
#: them overhang the margin instead of the next panel.
LEG_COL = 2

#: higher-timeframe POCs get their own dimmer treatment so they never compete
#: with today's actionable levels
HTF_COLOUR = "#9fb0c4"

#: decision state → the marker drawn on the NIFTY panel at the current bar
SIGNAL_MARKER = {
    "ENTER": ("▲ ENTER", "#00ff88", "triangle-up"),
    "ENTRY_READY": ("◆ READY", "#ffcc33", "diamond"),
    "FLOOR_CONFIRMED": ("▲ FLOOR", "#00ff88", "triangle-up"),
    "CEILING_CONFIRMED": ("▼ CEILING", "#ff4444", "triangle-down"),
    "EXIT": ("■ EXIT", "#ff9500", "square"),
    "ABORT": ("✕ ABORT", "#ff2d55", "x"),
    "TRAIL": ("↗ TRAIL", "#a78bfa", "arrow-up"),
    "SCALE_IN": ("＋ SCALE IN", "#00ff88", "cross"),
    "SCALE_OUT": ("－ SCALE OUT", "#ffcc33", "cross"),
}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _ohlc(df) -> Optional[Dict[str, Any]]:
    """OHLC + a time axis, whatever the frame calls its columns. `None` when
    the frame cannot be charted, so the caller reports it instead of drawing an
    empty axis."""
    if df is None or getattr(df, "empty", True):
        return None
    cols = {str(c).lower(): c for c in df.columns}

    def col(*names):
        for n in names:
            if n in cols:
                return df[cols[n]]
        return None

    close = col("close", "ltp", "price")
    if close is None:
        return None

    # ── datetime BEFORE timestamp. The NIFTY frame carries both: `timestamp`
    # is raw epoch seconds, `datetime` is the tz-aware IST column. Preferring
    # `timestamp` plotted NIFTY against integers while the option legs — which
    # only have `datetime` — plotted against datetimes, so `matches="x"` linked
    # two incompatible axis types and the shared timeline silently broke. The
    # shared axis is the entire point of this chart.
    x = col("datetime", "time", "date", "timestamp")
    if x is None:
        x = df.index
    x = _as_time(x)

    o, h, l = col("open"), col("high"), col("low")
    out = {"x": x, "open": o, "high": h, "low": l, "close": close,
           "volume": col("volume", "vol"),
           "line_only": o is None or h is None or l is None}
    # ── who was buying, per bar — read from the single owner ──
    # `indicators/order_flow.py` owns the buy/sell split (principle 1), and
    # `all_views` derives every view from ONE split (principle 8). Nothing is
    # computed here; the panel only renders what the owner already returns.
    out.update(_flow_views(df))
    return out


def _flow_views(df) -> Dict[str, Any]:
    """Per-bar delta and the CVD line, or empty when the owner cannot split.

    Empty rather than zero: a frame with no volume column has an UNKNOWN
    flow, and colouring its bars neutral-grey says that, while colouring them
    balanced-green would assert a split nobody measured (principle 9).
    """
    try:
        from indicators import order_flow as _of
        views = _of.all_views(df)
        if _of.is_missing(views):
            return {}
        return {"delta": views.get("delta"), "cvd": views.get("cum_delta")}
    except Exception:
        return {}


def _as_time(x):
    """Whatever the frame carries → tz-NAIVE IST datetimes.

    Two separate problems, one function.

    **Epoch seconds.** A frame that only carries `timestamp` would draw on a
    numeric axis that cannot line up with the datetime axis on the panel beside
    it, so `matches="x"` silently fails to link them.

    **The timezone.** Plotly.js has no timezone support: plotly.py serialises a
    tz-aware timestamp by converting it to UTC and dropping the offset, so an
    IST series renders 5½ hours early. That is why the axis read 04:00–11:00
    while the market was at 09:48 — the data was right and the label was UTC.
    Converting to IST and *then* dropping the tz makes the wall-clock number
    itself IST, which is the only thing Plotly will render faithfully.
    """
    try:
        import pandas as pd

        kind = getattr(getattr(x, "dtype", None), "kind", "")
        if kind in ("i", "u", "f"):
            first = float(x.iloc[0]) if hasattr(x, "iloc") else float(list(x)[0])
            # plausible epoch seconds (1970-2100), not a row index
            if not 1e8 < first < 4e9:
                return x
            x = pd.to_datetime(x, unit="s", utc=True)
        elif kind != "M" and not hasattr(x, "dt"):
            x = pd.to_datetime(pd.Series(list(x)), errors="coerce")

        s = x if hasattr(x, "dt") else pd.Series(x)
        if getattr(s.dt, "tz", None) is not None:
            s = s.dt.tz_convert("Asia/Kolkata")
        else:
            # naive values off the wire are already IST — say so before
            # converting, or the conversion shifts them a second time
            s = s.dt.tz_localize("Asia/Kolkata", ambiguous="NaT",
                                 nonexistent="NaT")
        return s.dt.tz_localize(None)
    except Exception:
        return x


def terminal_chart(nifty_df=None, call_df=None, put_df=None,
                   levels: Optional[Dict[str, Any]] = None,
                   htf_levels: Optional[Dict[str, Any]] = None,
                   call_label: str = "ATM Call", put_label: str = "ATM Put",
                   tint: Optional[str] = None,
                   dominance: str = "neutral",
                   signal: Optional[Dict[str, Any]] = None,
                   height: int = 660,
                   window_minutes: Optional[int] = None,
                   call_levels: Optional[Dict[str, Any]] = None,
                   put_levels: Optional[Dict[str, Any]] = None,
                   call_zones: Optional[Sequence[Dict[str, Any]]] = None,
                   put_zones: Optional[Sequence[Dict[str, Any]]] = None,
                   nifty_profile: Optional[Dict[str, Any]] = None,
                   call_profile: Optional[Dict[str, Any]] = None,
                   put_profile: Optional[Dict[str, Any]] = None):
    """The three-panel terminal. Returns `(figure, notes)`; `notes` names any
    series that could not be drawn."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    # ── today's session only. The API is asked for a `days_back` WINDOW, not
    # a session count, so every frame arrives carrying part of the previous
    # day — which squeezes the live session into a sliver at the right edge and
    # makes the previous close look like an intraday level.
    from ..clock import today_slice
    panels = [("NIFTY", today_slice(nifty_df)),
              (call_label, today_slice(call_df)),
              (put_label, today_slice(put_df))]
    parsed = [(name, _ohlc(df)) for name, df in panels]
    notes = [name for name, p in parsed if p is None]

    # ── one clock for all three panels. Every chart is reindexed onto the
    # union of their timestamps, so candle *n* is the same minute everywhere
    # and a minute a leg did not trade shows as a gap rather than sliding
    # every later candle one slot left.
    timeline = master_timeline(parsed)
    parsed = [(name, align(p, timeline)) for name, p in parsed]

    fig = make_subplots(
        rows=2, cols=2,
        specs=[[{"rowspan": 2}, {}], [None, {}]],
        column_widths=[0.60, 0.40], row_heights=[0.5, 0.5],
        horizontal_spacing=0.045, vertical_spacing=0.05,
        subplot_titles=[n for n, _ in parsed])

    positions = [(1, 1), (1, 2), (2, 2)]

    for (name, p), (r, c) in zip(parsed, positions):
        if p is None:
            continue
        _add_series(go, fig, name, p, r, c)

    # ── the liquidity & sentiment profile, AFTER the candles ──
    #
    # ⚠️ The order is load-bearing, and it used to be the other way round.
    # `add_hline`/`add_hrect` with `row=`/`col=` are **silently dropped by
    # Plotly when that subplot holds no trace yet** — no error, no warning, the
    # shape simply never reaches the figure. The profile ran before
    # `_add_series`, so every panel's POC, VAH and VAL line and every liquidity
    # band was discarded on the way in. The three profiles were computed each
    # cycle and drawn nowhere.
    #
    # The original reason for going first — "so the bands sit under the price
    # series" — is handled by `layer="below"` on the rects, which is what
    # actually controls stacking. Order controls whether they exist at all.
    #
    # Each panel gets its OWN profile — the premium legs are not a projection of
    # the index one. Stage 71.8's audit settled that: a premium profile is
    # computed natively per leg, and drawing the index's POC on a premium panel
    # would mark a price that series can never trade.
    # The panel's own x axis goes with it, so the dynamic-PoC stepline is drawn
    # against the same timeline as that panel's candles. `parsed` is already
    # aligned onto `timeline`, so all three share one clock.
    for prof, (r, c), (_nm, _p) in zip(
            (nifty_profile, call_profile, put_profile), positions, parsed):
        if prof:
            _profile_overlay(fig, prof, r, c,
                             x=(_p or {}).get("x") if _p else None)

    # ── levels: NIFTY panel only ──
    for key, price in (levels or {}).items():
        v = _f(price)
        if v is None or key not in LEVELS:
            continue
        colour, dash, width = LEVELS[key]
        fig.add_hline(y=v, row=1, col=1, line_width=width, line_dash=dash,
                      line_color=colour,
                      annotation_text=f"{LEVEL_LABEL[key]} {v:,.0f}",
                      annotation_position="right",
                      annotation_font=dict(size=9, color=colour))

    # higher-timeframe POCs — dimmer, so they never compete with today's
    for label, price in sorted((htf_levels or {}).items(),
                               key=lambda kv: -(_f(kv[1]) or 0))[:8]:
        v = _f(price)
        if v is None:
            continue
        fig.add_hline(y=v, row=1, col=1, line_width=1, line_dash="dot",
                      line_color=HTF_COLOUR,
                      annotation_text=f"{label} {v:,.0f}",
                      annotation_position="left",
                      annotation_font=dict(size=8, color=HTF_COLOUR))

    # ── the option panels get their OWN levels and VOB zones, in premium.
    # A spot-derived stop drawn on a premium series marks a price that series
    # can never trade — authoritative-looking and meaningless. These come from
    # the legs' own engines, so the number belongs to the axis it sits on.
    _leg_overlay(fig, call_levels, call_zones, 1, 2)
    _leg_overlay(fig, put_levels, put_zones, 2, 2)

    _add_signal(go, fig, parsed[0][1], signal)
    _tint(fig, tint, dominance)

    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=26, b=8),
        paper_bgcolor="#0b0f16", plot_bgcolor="#0b0f16",
        font=dict(color="#edf3f9", size=10), showlegend=False,
        hovermode="x unified", dragmode="pan",
        # ── the view survives the rerun. Streamlit rebuilds the whole figure
        # every cycle, which resets zoom, pan and crosshair to default — so a
        # trader who zoomed into 10:15–11:20 was thrown back out to the full
        # session a second later. A constant `uirevision` tells Plotly to keep
        # the user's view across redraws. It is keyed on the zoom level so the
        # ➕/➖ buttons still take effect: only a deliberate change moves it.
        uirevision=f"terminal:{window_minutes}")
    # ── the shared crosshair readout. `hovermode="x unified"` alone gathers
    # traces within ONE subplot; `hoversubplots="axis"` extends the same hover
    # across every panel on the linked axis, so hovering 10:48 reads 10:48 on
    # NIFTY, CALL and PUT at once. Older Plotly ignores the key rather than
    # raising, so the chart degrades to per-panel hover instead of failing.
    try:
        fig.update_layout(hoversubplots="axis")
    except Exception:
        pass
    # ── the synchronisation. `matches` links every panel to NIFTY's axis, so
    # zoom / pan / scroll on any of them moves all three together. Independent
    # scrolling is the one thing this layout must not allow.
    fig.update_xaxes(matches="x", rangeslider_visible=False,
                     gridcolor="#161b22", showspikes=True,
                     spikecolor="#3a4757", spikethickness=1,
                     spikemode="across", spikesnap="cursor")
    fig.update_yaxes(gridcolor="#161b22", side="right", showspikes=False)

    # ── the zoom window, set by the buttons. Applied to the master axis only:
    # every other panel carries `matches="x"`, so they follow. The y-axes are
    # left to autorange so a zoomed-in window rescales to the prices actually
    # in it rather than staying flat inside the whole session's range.
    rng = x_range(_last_x(parsed), window_minutes)
    if rng:
        fig.update_xaxes(range=rng, row=1, col=1)

    # ── each panel's price axis, fitted to the bars on screen. Plotly's
    # autorange fits the whole trace rather than the visible window, so without
    # this a zoomed-in view kept the full session's height and the candles
    # stayed flat — the zoom moved time and nothing else.
    for (_name, p), (r, c) in zip(parsed, positions):
        if p is None:
            continue
        lo_hi = price_range(p.get("low") if p.get("low") is not None
                            else p["close"],
                            p.get("high") if p.get("high") is not None
                            else p["close"],
                            p["x"], rng)
        if lo_hi:
            fig.update_yaxes(range=lo_hi, row=r, col=c)

    for a in fig.layout.annotations:
        if a.text in [n for n, _ in parsed]:
            a.font.size = 11.5
            a.font.color = "#cfd9e6"
            a.xanchor = "left"
    return fig, notes


#: the three panels of the split terminal, in draw order, each keyed so the
#: caller can address one figure. NIFTY carries the spot-axis levels; the two
#: legs carry their own premium levels and the dominance tint.
SPLIT_KEYS = ("NIFTY", "CALL", "PUT")


def terminal_charts_split(nifty_df=None, call_df=None, put_df=None,
                          levels: Optional[Dict[str, Any]] = None,
                          htf_levels: Optional[Dict[str, Any]] = None,
                          call_label: str = "ATM Call",
                          put_label: str = "ATM Put",
                          tint: Optional[str] = None,
                          dominance: str = "neutral",
                          signal: Optional[Dict[str, Any]] = None,
                          height: int = 660,
                          window_minutes: Optional[int] = None,
                          call_levels: Optional[Dict[str, Any]] = None,
                          put_levels: Optional[Dict[str, Any]] = None,
                          call_zones: Optional[Sequence[Dict[str, Any]]] = None,
                          put_zones: Optional[Sequence[Dict[str, Any]]] = None,
                          nifty_profile: Optional[Dict[str, Any]] = None,
                          call_profile: Optional[Dict[str, Any]] = None,
                          put_profile: Optional[Dict[str, Any]] = None,
                          price_action: bool = False,
                          index_label: str = "NIFTY",
                          theme: Optional[Dict[str, str]] = None,
                          call_sr: Optional[Dict[str, Any]] = None,
                          put_sr: Optional[Dict[str, Any]] = None):
    """NIFTY, ATM Call and ATM Put as THREE independent figures.

    `terminal_chart` above draws one figure so Streamlit's single Fullscreen
    button enlarges all three locked panels together. A trader asked to enlarge
    each chart on its own, and Streamlit injects the Fullscreen button per
    `st.plotly_chart` call — so each chart has to be its own figure to get its
    own button.

    The cost of splitting is the live cross-panel crosshair: Plotly can
    synchronise hover only *within* a figure, so hovering NIFTY can no longer
    light up the same minute on the legs. Everything that does NOT need a shared
    figure is kept: all three are reindexed onto one `master_timeline`, so
    candle *n* is the same minute on every chart, and one zoom window
    (`window_minutes`, anchored at the newest bar across all three) is applied
    to each — so they still line up and zoom to the same span, they simply no
    longer share a cursor.

    Returns `(figs, notes)`. `figs` maps each of `SPLIT_KEYS` to its figure, or
    to `None` when that series could not be drawn; `notes` names the missing
    series, exactly as `terminal_chart` does.
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    from ..clock import today_slice
    from .chart_theme import palette as _palette
    # Chrome only — candles, levels and zones keep their semantic colours,
    # which are chosen to read on either background.
    _c = dict(theme) if theme else _palette(None)
    # `index_label` names the panel; SPLIT_KEYS still keys it as "NIFTY" so
    # every profile/height/figure lookup below is untouched. Without this the
    # index panel read "NIFTY" even when the frame held SENSEX candles — the
    # chart had switched and there was no way to see that it had.
    panels = [(index_label, today_slice(nifty_df)),
              (call_label, today_slice(call_df)),
              (put_label, today_slice(put_df))]
    # the today-sliced frames per chart key, for the opt-in price-action overlay
    sliced = {k: df for k, (_n, df) in zip(SPLIT_KEYS, panels)}
    parsed = [(name, _ohlc(df)) for name, df in panels]
    notes = [name for name, p in parsed if p is None]

    # ── one clock for all three, exactly as the combined chart uses ──
    # Reindexing each panel onto the union of timestamps is what keeps candle
    # *n* the same minute everywhere now that the axes are no longer `matches`-
    # linked inside a single figure.
    timeline = master_timeline(parsed)
    parsed = [(name, align(p, timeline)) for name, p in parsed]

    # ── one zoom window for all three, anchored at the newest bar across every
    # panel — the same range the combined chart pins on its master axis, applied
    # to each figure independently so they still show the same span.
    rng = x_range(_last_x(parsed), window_minutes)

    leg_over = {"CALL": (call_levels, call_zones, call_sr),
                "PUT": (put_levels, put_zones, put_sr)}
    profiles = {"NIFTY": nifty_profile, "CALL": call_profile,
                "PUT": put_profile}
    # NIFTY spans the full height in the combined layout; the two legs share it
    # stacked, so each is ~half. Preserving that keeps the split page reading
    # like the terminal it replaces.
    heights = {"NIFTY": height, "CALL": max(int(height / 2), 240),
               "PUT": max(int(height / 2), 240)}

    figs: Dict[str, Any] = {}
    for key, (name, p) in zip(SPLIT_KEYS, parsed):
        if p is None:
            figs[key] = None
            continue
        fig = make_subplots(rows=1, cols=1, subplot_titles=[name])
        _add_series(go, fig, name, p, 1, 1)

        # opt-in Advanced Price-Action overlay (BOS/CHoCH/Fib/patterns) — default
        # OFF, drawn on ALL three charts when the trader enables it. Silent on any
        # failure so the candles always render.
        if price_action:
            try:
                from .price_action_overlay import draw as _pa_draw
                _pa_draw(fig, sliced.get(key), 1, 1)
            except Exception:
                pass

        prof = profiles.get(key)
        if prof:
            # Each leg is now a full-width panel, so its POC/VAH/VAL labels
            # overhang the 8px right margin the same way the combined legs did —
            # keep them inside regardless of column.
            _profile_overlay(fig, prof, 1, 1, x=p.get("x"),
                             labels_inside=(key != "NIFTY"))

        if key == "NIFTY":
            for lkey, price in (levels or {}).items():
                v = _f(price)
                if v is None or lkey not in LEVELS:
                    continue
                colour, dash, width = LEVELS[lkey]
                fig.add_hline(y=v, row=1, col=1, line_width=width,
                              line_dash=dash, line_color=colour,
                              annotation_text=f"{LEVEL_LABEL[lkey]} {v:,.0f}",
                              annotation_position="right",
                              annotation_font=dict(size=9, color=colour))
            for label, price in sorted((htf_levels or {}).items(),
                                       key=lambda kv: -(_f(kv[1]) or 0))[:8]:
                v = _f(price)
                if v is None:
                    continue
                fig.add_hline(y=v, row=1, col=1, line_width=1, line_dash="dot",
                              line_color=_c["htf"],
                              annotation_text=f"{label} {v:,.0f}",
                              annotation_position="left",
                              annotation_font=dict(size=8, color=HTF_COLOUR))
            _add_signal(go, fig, p, signal, edge=_c["marker_edge"])
        else:
            _lv, _zn, _sr = leg_over[key]
            _leg_overlay(fig, _lv, _zn, 1, 1, sr=_sr)
            _tint_single(fig, tint, dominance)

        fig.update_layout(
            height=heights[key], margin=dict(l=8, r=8, t=26, b=8),
            paper_bgcolor=_c["paper"], plot_bgcolor=_c["plot"],
            font=dict(color=_c["font"], size=10), showlegend=False,
            hovermode="x unified", dragmode="pan",
            # Keyed per chart so each figure keeps its OWN zoom across the 20s
            # rerun, and re-keyed on the window so the ➕/➖ buttons still move it.
            uirevision=f"terminal-split:{key}:{window_minutes}")
        fig.update_xaxes(rangeslider_visible=False, gridcolor=_c["grid"],
                         showspikes=True, spikecolor=_c["spike"],
                         spikethickness=1, spikemode="across",
                         spikesnap="cursor")
        fig.update_yaxes(gridcolor=_c["grid"], side="right", showspikes=False)
        if rng:
            fig.update_xaxes(range=rng, row=1, col=1)
        lo_hi = price_range(p.get("low") if p.get("low") is not None
                            else p["close"],
                            p.get("high") if p.get("high") is not None
                            else p["close"],
                            p["x"], rng)
        if lo_hi:
            fig.update_yaxes(range=lo_hi, row=1, col=1)
        for a in fig.layout.annotations:
            if a.text == name:
                a.font.size = 11.5
                a.font.color = _c["title"]
                a.xanchor = "left"
        figs[key] = fig

    return figs, notes


#: VOB zone status → (fill, edge). Building zones read loudest; a faded zone
#: is drawn but must not compete with one that is still being defended.
ZONE_TONE = {
    "BUILDING": ("rgba(38,166,154,.16)", "#26a69a"),
    "INTACT":   ("rgba(77,166,255,.11)", "#4da6ff"),
    "FADING":   ("rgba(159,176,196,.08)", "#7d8b9c"),
    "BREAKING": ("rgba(239,83,80,.14)", "#ef5350"),
}


def _profile_overlay(fig, profile: Dict[str, Any], row: int, col: int,
                     x: Optional[Sequence[Any]] = None,
                     labels_inside: Optional[bool] = None) -> None:
    """One panel's liquidity & sentiment profile.

    `profile` is whatever `calculate_money_flow_profile` returned, optionally
    carrying a `shape` from Stage 71.86 and a `dynamic_poc` from
    `compute_dynamic_poc`. Nothing is computed here or in the overlay module —
    both only decide where a value already published is drawn.

    The option panels are the rightmost column, so their POC/VAH/VAL labels are
    kept inside the panel; a right-positioned label there overhangs an 8px
    margin and is cut off. The index panel has the column gap to spill into and
    keeps the wider placement.

    `labels_inside` defaults to that column rule, but the split terminal draws
    each leg as its OWN full-width figure — where the label overhangs the same
    8px right margin regardless of which column it was in — so it passes the
    flag explicitly rather than relying on `col`.
    """
    if labels_inside is None:
        labels_inside = (col == LEG_COL)
    from .profile_overlay import draw
    draw(fig, row, col, rows=profile.get("rows"), profile=profile,
         shape=profile.get("shape"), labels_inside=labels_inside, x=x)

    # 📍 High-volume pivots and their levels, on the same panel and the same axis.
    # A separate module because it draws per-bar geometry rather than horizontal
    # profile levels, and mixing the two would put bar indices into a function whose
    # whole contract is prices.
    try:
        from .volume_points_overlay import draw as _hv_draw
        # `hv_why` travels with the points so a panel with none can say why —
        # reported as the PUT panel "not displaying", which is what a trending leg
        # correctly looks like and could not explain.
        _hv_draw(fig, row, col, points=profile.get("hv_points"), x=x,
                 why=profile.get("hv_why"))
    except Exception:
        pass


#: A leg's S/R state → (label, colour). Same vocabulary `classify_sr_behavior`
#: uses for the index, so one word means one thing on every panel. Colour is by
#: what the state means for the LEG's own price, which is what its axis shows —
#: a call leg breaking its own resistance is bullish for that call, whatever
#: NIFTY is doing.
SR_STATE_TONE = {
    "BREAKING":  ("BREAKING",  "#00ff88"),
    "BUILDING":  ("BUILDING",  "#4da6ff"),
    "ACCEPTING": ("ACCEPTING", "#7fe8b0"),
    "REJECTING": ("REJECTING", "#ff8c8c"),
}


def _sr_decoration(sr):
    """(level key, (label, colour)) for a leg's S/R read, or (None, None).

    `_leg_levels` files the behaviour level under "support" or "resistance"
    by its side, so the key is derived the same way here — otherwise the state
    would be written onto whichever line happened to sort first.
    """
    state = _s((sr or {}).get("state"))
    tone = SR_STATE_TONE.get(state)
    if not tone or _f((sr or {}).get("level")) is None:
        return None, None
    side = str((sr or {}).get("side") or "").lower()
    return ("support" if side == "support" else "resistance"), tone


def _leg_overlay(fig, levels, zones, row: int, col: int, sr=None) -> None:
    """One option panel's own levels and VOB zones, in premium terms.

    Labels sit on the **right**, which is where the trader reads them: the
    right-hand edge is *now*, so the price a line marks is next to the candle
    that is testing it. They used to be on the left, at the oldest bar on the
    panel — the one place on the chart nothing is happening.

    ⚠️ `xanchor` is set explicitly, and that is not a detail. Plotly's
    `annotation_position="right"` means *outside* the panel: it resolves to
    `x=1, xanchor="left"`, so the text starts at the right edge and runs on
    past it. These two panels are the rightmost column and the figure's right
    margin is 8px, so the label would be cut off — a level drawn with its price
    invisible is worse than one drawn on the wrong side. `xanchor="right"`
    turns the text back into the panel, over the empty space beside the last
    candle, and costs no chart width.
    """
    # Which of these lines, if any, IS the S/R behaviour level. `_leg_levels`
    # already publishes that level as "support" or "resistance" — so the state
    # is written onto the line that is already there rather than drawn as a
    # second line at the same price. One level, one line, one label.
    _sr_key, _sr_tone = _sr_decoration(sr)

    for key, price in (levels or {}).items():
        v = _f(price)
        if v is None or key not in LEVELS:
            continue
        colour, dash, width = LEVELS[key]
        label = f"{LEVEL_LABEL[key]} ₹{v:,.2f}"
        if _sr_tone and key == _sr_key and _f((sr or {}).get("level")) == v:
            # BREAKING / REJECTING / ACCEPTING / BUILDING — the verdict the
            # engine already reached, on the level it reached it about.
            state_label, state_colour = _sr_tone
            label = f"{label} · {state_label}"
            colour = state_colour
            width = max(width, 1.6)
        fig.add_hline(y=v, row=row, col=col, line_width=width, line_dash=dash,
                      line_color=colour,
                      annotation_text=label,
                      annotation_position="right",
                      annotation=dict(xanchor="right"),
                      annotation_font=dict(size=8, color=colour))

    for z in list(zones or [])[:6]:
        lo, hi = _f(z.get("lower")), _f(z.get("upper"))
        if lo is None or hi is None or hi <= lo:
            continue
        fill, edge = ZONE_TONE.get(_s(z.get("status")),
                                   ZONE_TONE["INTACT"])
        fig.add_hrect(y0=lo, y1=hi, row=row, col=col, layer="below",
                      fillcolor=fill, line_width=1, line_color=edge,
                      opacity=1.0)


def _s(v) -> str:
    return str(v or "").strip().upper()


def _last_x(parsed) -> Any:
    """The newest bar across every panel that drew.

    Not NIFTY's alone — on a day the index frame is missing, the option legs
    still define a timeline, and the zoom buttons should still work.
    """
    latest = None
    for _name, p in (parsed or []):
        if not p:
            continue
        try:
            v = list(p["x"])[-1]
        except Exception:
            continue
        if v is None:
            continue
        try:
            if latest is None or v > latest:
                latest = v
        except TypeError:            # mixed axis types — take the first we saw
            continue
    return latest


def _add_series(go, fig, name: str, p: Dict[str, Any], row: int, col: int):
    """Candles (or a line when OHLC is unavailable), with volume and the
    hover payload the crosshair reads."""
    hover = ("<b>%{x|%H:%M}</b><br>"
             + f"{name} %{{y:,.2f}}"
             + ("<br>Vol %{customdata:,.0f}" if p.get("volume") is not None
                else "") + "<extra></extra>")
    custom = p["volume"] if p.get("volume") is not None else None

    if p["line_only"]:
        fig.add_trace(go.Scatter(x=p["x"], y=p["close"], name=name,
                                 mode="lines", customdata=custom,
                                 hovertemplate=hover,
                                 line=dict(color="#7fb4ff", width=1.4)),
                      row=row, col=col)
        return

    fig.add_trace(go.Candlestick(
        x=p["x"], open=p["open"], high=p["high"], low=p["low"],
        close=p["close"], name=name, showlegend=False,
        customdata=custom,
        increasing_line_color=_UP, decreasing_line_color=_DOWN,
        increasing_fillcolor=_UP, decreasing_fillcolor=_DOWN),
        row=row, col=col)

    if p.get("volume") is not None:
        # volume as a faint overlay on its own scale — present for the
        # crosshair readout without stealing the price axis. Bar HEIGHT is
        # volume; bar COLOUR is who was buying. Same footprint as before,
        # strictly more information, and both numbers come from an owner.
        bars = volume_bars(p["volume"], p["low"], p["high"])
        if bars is not None:
            base, heights = bars
            colours = flow_colours(p.get("delta"), len(heights))
            fig.add_trace(go.Bar(x=p["x"], y=heights, base=base, name="vol",
                                 marker_color=(colours if colours is not None
                                               else FLOW_FLAT),
                                 hoverinfo="skip", showlegend=False),
                          row=row, col=col)

    # ── the CVD line: is the premium still being accumulated? ──
    # Rising means buyers are still adding, falling means they have stopped —
    # the read a trader previously had to get from a text badge beside the
    # chart. Scaled into the panel, so it never touches autorange.
    scaled = cvd_line(p.get("cvd"), p.get("low"), p.get("high"))
    if scaled is not None:
        fig.add_trace(go.Scatter(
            x=p["x"], y=scaled, name="CVD", mode="lines",
            line=dict(color=CVD_LINE, width=1.3),
            hoverinfo="skip", showlegend=False), row=row, col=col)


#: minutes of session visible at each zoom step; `None` is the whole session.
#: Ordered widest-last so "contract" walks right and "expand" walks left.
ZOOM_STEPS = (15, 30, 60, 120, 240, None)


def zoom_step(current: Optional[int], direction: int) -> Optional[int]:
    """The next zoom level in `direction` (+1 expands, -1 contracts).

    Clamped at both ends rather than wrapping — a button that silently jumps
    from the tightest view to the whole session looks like a misclick.
    """
    try:
        i = ZOOM_STEPS.index(current)
    except ValueError:
        i = len(ZOOM_STEPS) - 1          # unknown value → the full session
    i = max(0, min(len(ZOOM_STEPS) - 1, i - int(direction)))
    return ZOOM_STEPS[i]


def zoom_label(current: Optional[int]) -> str:
    if current is None:
        return "Full session"
    if current % 60 == 0:
        return f"Last {current // 60}h"
    return f"Last {current}m"


def x_range(last_x, minutes: Optional[int]):
    """`[start, end]` for the shared time axis, anchored at the newest bar.

    Anchored at the right edge, not the left: zooming in on a live chart should
    keep the price that is trading now on screen. `None` when the window cannot
    be computed, so the caller leaves the axis to autorange rather than pinning
    it to a bogus range.
    """
    if minutes is None or last_x is None:
        return None
    try:
        from datetime import datetime, timedelta
        end = last_x
        if not isinstance(end, datetime):
            try:
                import pandas as pd
                end = pd.Timestamp(end).to_pydatetime()
            except Exception:
                return None
        return [end - timedelta(minutes=int(minutes)), end]
    except Exception:
        return None


def master_timeline(parsed) -> List[Any]:
    """The union of every panel's timestamps, sorted — one clock for all three.

    Without this each panel plots its own x series, and three series of
    different lengths put candle *n* at a different minute on each panel. The
    axes would still be linked, so nothing would look broken; the CALL panel
    would simply be showing 10:47 while NIFTY showed 10:48. That is the failure
    mode a trader cannot see and cannot recover from.
    """
    stamps = set()
    for _name, p in (parsed or []):
        if not p:
            continue
        try:
            stamps.update(x for x in list(p["x"]) if x is not None and x == x)
        except Exception:
            continue
    try:
        return sorted(stamps)
    except TypeError:                      # mixed axis types — refuse to guess
        return []


def align(p: Optional[Dict[str, Any]], timeline: Sequence[Any]):
    """One panel's OHLCV reindexed onto the master timeline.

    A minute the leg did not trade becomes NaN, which Plotly renders as a gap.
    The alternative — letting the series keep its own shorter index — slides
    every later candle one slot left and silently misaligns the panels.
    """
    if p is None or not timeline:
        return p
    try:
        import pandas as pd

        idx = pd.Index(list(timeline))
        out = dict(p)
        base = pd.Index(list(p["x"]))
        for key in ("open", "high", "low", "close", "volume",
                    "delta", "cvd"):
            series = p.get(key)
            if series is None:
                continue
            s = pd.Series(list(series), index=base)
            s = s[~s.index.duplicated(keep="last")]
            out[key] = s.reindex(idx)
        out["x"] = idx
        return out
    except Exception:
        return p


#: breathing room above and below the visible extremes, as a share of the span
Y_PAD = 0.06


def price_range(low, high, x=None, window=None, pad: float = Y_PAD):
    """`[lo, hi]` for a price axis, fitted to the bars actually on screen.

    Plotly's autorange fits the whole *trace*, not the visible x-window, so a
    zoomed-in view kept the full session's height and the candles stayed flat —
    the zoom moved the time axis and nothing else. Computing the range from the
    rows inside the window is the only way to make the y-axis follow the
    movement, which is what a price chart is for.

    Each panel gets its own range: NIFTY's ~24,000 and a ₹120 premium share a
    time axis, never a price axis.

    `None` when there is nothing to fit, so the caller leaves autorange alone
    rather than pinning a bogus range.
    """
    # A zero or negative price is not a trade — no index prints one. A single
    # such bar in the series used to define the whole axis: one `low = 0`
    # against SENSEX at ~81,000 stretched the range to [-4860, 85865], so the
    # candles collapsed into a thread at the top and the axis read 0 upward.
    # NaN was already tolerated here; zero was not, and that is the shape a
    # gap in the feed actually arrives in. Treat both as missing.
    def _price(v):
        """`None` unless this is a real traded price."""
        f = _f(v)
        return f if (f is not None and f > 0) else None

    # Positions are preserved, never filtered out: the window filter below
    # zips these against `x` by index, so dropping elements would silently
    # misalign every bar with its timestamp.
    lows = [_price(v) for v in _seq(low)]
    highs = [_price(v) for v in _seq(high)]
    if not lows or not highs:
        return None

    xs = _seq(x)
    if window and xs and len(xs) == len(lows):
        lo_hi = [(lows[i], highs[i]) for i in range(len(xs))
                 if _within(xs[i], window)]
        if lo_hi:
            lows = [a for a, _ in lo_hi]
            highs = [b for _, b in lo_hi]

    lo = min((v for v in lows if v is not None), default=None)
    hi = max((v for v in highs if v is not None), default=None)
    if lo is None or hi is None:
        return None
    span = hi - lo
    if span <= 0:
        # a dead-flat series still needs a visible band, or it renders as a
        # single line with no context at all
        band = abs(hi) * 0.001 or 1.0
        return [lo - band, hi + band]
    return [lo - span * pad, hi + span * pad]


def _within(v, window) -> bool:
    try:
        return window[0] <= v <= window[1]
    except (TypeError, IndexError):
        return True


#: how much of the price span the volume overlay is allowed to occupy
VOLUME_SHARE = 0.18


def _seq(v) -> List[Any]:
    """A plain list from a Series, array, list or `None`.

    Never `v or []`: a pandas Series has no unambiguous truth value and raises
    rather than falling back.
    """
    if v is None:
        return []
    try:
        return list(v)
    except TypeError:
        return []


def volume_bars(volume, low, high, share: float = VOLUME_SHARE):
    """`(base, heights)` for the volume overlay, or `None` if it can't be drawn.

    A Plotly bar spans `base` → `base + y`. `y` is the bar's **length**, not the
    coordinate of its top. Passing the absolute top as `y` while also passing
    `base` made every bar reach `2 × low`, so the NIFTY panel auto-ranged to
    ~48,000 on a 24,000 index and the candles collapsed into a flat line at the
    bottom. The option legs flattened the same way, less visibly, because
    doubling a ₹120 premium's range is a smaller number but the same mistake.

    Heights are lengths measured up from `low.min()`, capped at `share` of the
    candle range, so the overlay always sits inside the price extent the candles
    already occupy and cannot influence autorange at all.
    """
    # NOT `volume or []`: these arrive as pandas Series, and `Series or []`
    # evaluates the Series for truthiness — "The truth value of a Series is
    # ambiguous" — which took the whole chart down, not just the overlay.
    vols = [_f(v) for v in _seq(volume)]
    lows = [_f(v) for v in _seq(low)]
    highs = [_f(v) for v in _seq(high)]
    finite_v = [v for v in vols if v is not None]
    finite_l = [v for v in lows if v is not None]
    finite_h = [v for v in highs if v is not None]
    if not finite_v or not finite_l or not finite_h:
        return None

    vmax = max(finite_v)
    if not vmax or vmax <= 0:
        return None
    base = min(finite_l)
    span = max(finite_h) - base
    if span <= 0:
        return None
    room = span * share
    return base, [0.0 if v is None else max(0.0, v) / vmax * room for v in vols]


#: per-bar flow tint. Deliberately softer than the candle colours — the bars
#: answer "who was buying this minute", the candles answer "where did price
#: go", and the second question must stay the louder one.
FLOW_BUY = "rgba(0,255,136,.40)"
FLOW_SELL = "rgba(255,68,68,.40)"
FLOW_FLAT = "rgba(120,140,170,.22)"
#: the accumulation line — violet, the house colour for "dealer/flow", and
#: distinct from every candle and level colour on the panel
CVD_LINE = "rgba(167,139,250,.85)"


def flow_colours(delta, n: int) -> Optional[List[str]]:
    """One colour per bar from the owner's delta, or `None` to keep it plain.

    Green where buyers dominated that bar, red where sellers did, grey where
    the bar is unmeasured. `None` (rather than an all-grey list) when there is
    no delta at all, so the caller falls back to the plain volume overlay
    instead of drawing a flow read that was never taken.
    """
    if delta is None:
        return None
    vals = _seq(delta)
    if not vals:
        return None
    out = []
    for i in range(n):
        d = _f(vals[i]) if i < len(vals) else None
        out.append(FLOW_FLAT if d is None or d == 0 else
                   (FLOW_BUY if d > 0 else FLOW_SELL))
    return out


def cvd_line(cvd, low, high, share: float = 0.55):
    """The CVD series scaled into the panel, or `None`.

    Premium charts have no room for a second axis — the layout is already a
    rowspan grid with `matches="x"` on every panel, and a secondary y would
    have to be added per panel and kept out of the shared zoom. Scaling into
    the existing price extent keeps one axis and cannot influence autorange,
    the same discipline `volume_bars` uses.

    The SHAPE is the signal: rising means buyers are still adding, falling
    means they have stopped. The absolute value is meaningless once scaled,
    so it is never labelled with a number.
    """
    vals = [_f(v) for v in _seq(cvd)]
    finite = [v for v in vals if v is not None]
    lows = [_f(v) for v in _seq(low)]
    highs = [_f(v) for v in _seq(high)]
    fl = [v for v in lows if v is not None]
    fh = [v for v in highs if v is not None]
    if len(finite) < 2 or not fl or not fh:
        return None
    lo, hi = min(finite), max(finite)
    span = hi - lo
    if span <= 0:
        return None
    base = min(fl)
    room = (max(fh) - base) * share
    if room <= 0:
        return None
    return [None if v is None else base + (v - lo) / span * room for v in vals]


def _add_signal(go, fig, nifty: Optional[Dict[str, Any]],
                signal: Optional[Dict[str, Any]], edge: Optional[str] = None):
    """The decision state, pinned at the latest bar on the NIFTY panel."""
    s = dict(signal or {})
    state = str(s.get("state") or "").upper()
    mark = SIGNAL_MARKER.get(state)
    if not mark or nifty is None:
        return
    try:
        x = list(nifty["x"])[-1]
        y = float(list(nifty["close"])[-1])
    except Exception:
        return
    text, colour, symbol = mark
    fig.add_trace(go.Scatter(
        x=[x], y=[y], mode="markers+text", showlegend=False,
        text=[text], textposition="top center",
        textfont=dict(size=10, color=colour),
        marker=dict(size=13, symbol=symbol, color=colour,
                    line=dict(width=1, color=edge or "#0b0f16")),
        hovertemplate=f"{text}<extra></extra>"), row=1, col=1)


def _tint(fig, tint: Optional[str], dominance: str):
    """A below-layer wash on the option panels only.

    Deliberately not `plot_bgcolor`: the candles have to stay readable, and a
    body colour that competes with them makes the chart harder to read rather
    than faster.
    """
    if not tint or dominance == "neutral":
        return
    for axis, yaxis in (("x2", "y2"), ("x3", "y3")):
        fig.add_shape(type="rect", xref=f"{axis} domain", yref=f"{yaxis} domain",
                      x0=0, x1=1, y0=0, y1=1, layer="below",
                      fillcolor=tint, line_width=0)


def _tint_single(fig, tint: Optional[str], dominance: str):
    """The dominance wash for a split leg — one figure, so one panel.

    Same below-layer rectangle as `_tint`, but a single-panel figure's option
    leg lives on the primary `x`/`y` axes rather than the combined chart's
    `x2`/`x3`, so it addresses the panel's own domain.
    """
    if not tint or dominance == "neutral":
        return
    fig.add_shape(type="rect", xref="x domain", yref="y domain",
                  x0=0, x1=1, y0=0, y1=1, layer="below",
                  fillcolor=tint, line_width=0)


def atm_legs(leg_dfs: Optional[Dict[str, Any]]):
    """Find the ATM Call and ATM Put frames in the app's `_atm_leg_dfs` store.

    Keys look like `"ATM CE 23900"` / `"ATM+1 PE 24000"`. Exactly `ATM` wins;
    the nearest offset is a fallback so the terminal still draws something on a
    day the exact ATM leg failed to load.
    """
    legs = dict(leg_dfs or {})
    if not legs:
        return None, None, None, None

    def pick(side):
        exact = [k for k in legs if k.startswith("ATM ") and f" {side} " in k]
        if exact:
            return exact[0]
        near = sorted((k for k in legs if f" {side} " in k),
                      key=lambda k: abs(_offset(k)))
        return near[0] if near else None

    ce, pe = pick("CE"), pick("PE")
    return (legs.get(ce) if ce else None, legs.get(pe) if pe else None, ce, pe)


def _offset(tag: str) -> int:
    head = str(tag).split(" ")[0]
    if head == "ATM":
        return 0
    try:
        return int(head.replace("ATM", ""))
    except ValueError:
        return 99
