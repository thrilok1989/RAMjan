"""MIOS V6 — Dashboard 2 trading-terminal tests.

The property under test beyond correctness: **the terminal creates nothing.**
Every value it shows must trace to an engine that already computed it, and the
two places where no engine has the answer (option-premium levels without a leg
setup, per-leg strength without a leg-bias row) must say so rather than
producing a confident number.
"""

from mios_v5 import terminal


def _bias_row(tag, bulls=10, bears=3, ltp=124.8):
    row = {"Leg": tag, "LTP": f"₹{ltp:.1f}"}
    sigs = list(terminal.BIAS_SIGNALS)
    for i, k in enumerate(sigs):
        row[k] = "🟢" if i < bulls else ("🔴" if i < bulls + bears else "⚪")
    row["Leg Verdict"] = f"{'🟢' if bulls >= bears else '🔴'} BULL (+{bulls - bears})"
    return row


def _fr(**kw):
    base = {
        "preferred_bias": "BULL", "confidence": 74, "stability": "STABLE",
        "decision_v2": {"state": "ENTER", "label": "✅ ENTER", "side": "CALL",
                        "confidence": 88, "quality": "A+", "entry": 23900.0,
                        "stop": 23850.0, "trail": {"stop": 23870.0},
                        "reasons": ["Floor proven"],
                        "proof": {"confirmed": True, "zone_price": 23880.0,
                                  "refusal": {"proven": True}, "reasons": []}},
        "next_target": 24050.0,
        "market_state": {"state": "MARK_UP", "label": "📈 Mark Up"},
        "memory_read": {"state_duration_min": 40.0, "state_mature": True},
        "transition": {"state": "STRENGTHENING", "label": "↑ Strengthening",
                       "bias": "BULL"},
        "reaction": {"state": "REJECTION", "label": "🟢 Rejection",
                     "winner": "Buyers", "confidence": 80},
        "absorption": {"behaviour": "PASSIVE_BUYING", "tone": "bull",
                       "label": "🟢 Passive Buying", "confidence": 70,
                       "expectation": "Accumulation continues"},
        "validity": {"verdict": "VALID", "valid": True, "pct": 80},
        "htf": {"alignment": {"bias": "BULL", "score": 76, "label": "5/6 Bull"}},
        "battle_zone": {"lifecycle": "stable", "health_pct": 70},
        "families_read": {"dominant": "BULL", "agreement_pct": 82,
                          "severity": "LOW"},
        "families": {"institutions": {"direction": "BULL", "strength": 76,
                                      "reliability": "HIGH"}},
        "ltp_behaviour": {"calls": {"state": "building",
                                    "label": "📈 Building (long buildup)"},
                          "puts": {"state": "distribution",
                                   "label": "📉 Distribution (writing)"},
                          "flow": {"state": "entering", "label": "💰 Entering"}},
        "sections": {"dealer": {"bias": "BULL", "headline": "positive gamma"},
                     "orderflow": {"bias": "BULL", "headline": "CVD rising"}},
        "flow_shift": {},
    }
    base.update(kw)
    return base


def _call(**kw):
    args = dict(side="CE", tag="ATM CE 24000",
                ltp_side={"state": "building",
                          "label": "📈 Building (long buildup)"},
                bias_row=_bias_row("ATM CE 24000", bulls=11, bears=2),
                vob_zones=[{"status": "BUILDING", "zone_type": "bullish",
                            "buy_vol": 1200.0, "bull_pct": 71}],
                money_flow={"state": "entering", "label": "💰 Entering"})
    args.update(kw)
    return terminal.leg_read(**args)


def _put(**kw):
    args = dict(side="PE", tag="ATM PE 24000",
                ltp_side={"state": "distribution",
                          "label": "📉 Distribution (writing)"},
                bias_row=_bias_row("ATM PE 24000", bulls=4, bears=8),
                vob_zones=[{"status": "FADING", "zone_type": "bullish"}])
    args.update(kw)
    return terminal.leg_read(**args)


# ── one leg ─────────────────────────────────────────────────────────────
def test_badges_rename_stage_50s_state_per_side():
    """The LTP × OI matrix already decides this — the badge only renames it."""
    assert any(b["text"] == "CALL BUILDING" for b in _call()["badges"])
    assert any(b["text"] == "PUT WRITING" for b in _put()["badges"])
    for b in _call()["badges"]:
        assert b["engine"]


def test_the_same_state_means_opposite_things_on_the_two_sides():
    """PUT WRITING is bullish for NIFTY; CALL WRITING is bearish. A shared
    table would get this backwards on one side."""
    call_writing = terminal.leg_read("CE", ltp_side={"state": "distribution"})
    put_writing = terminal.leg_read("PE", ltp_side={"state": "distribution"})
    assert call_writing["badges"][0]["tone"] == "bear"
    assert put_writing["badges"][0]["tone"] == "bull"


def test_only_active_badges_appear():
    quiet = terminal.leg_read("CE", ltp_side={"state": "flat"})
    assert quiet["badges"] == []


def test_exhaustion_comes_from_stage_43_not_a_new_calculation():
    c = _call(absorption={"behaviour": "BUYER_EXHAUSTION", "tone": "bear"})
    b = next(b for b in c["badges"] if b["text"] == "CALL EXHAUSTION")
    assert b["engine"] == "Stage 43 Absorption"


def test_strength_is_the_leg_bias_tally_not_an_invented_metric():
    c = _call()
    assert c["strength"] == round(100.0 * 11 / 13, 1)
    assert "leg signals agree" in c["strength_source"]
    assert c["stars"].count("★") >= 4


def test_strength_is_absent_when_there_is_no_leg_bias_row():
    c = terminal.leg_read("CE", bias_row={})
    assert c["strength"] is None
    assert c["stars"] == "☆☆☆☆☆"
    assert "no leg-bias row" in c["strength_source"]


def test_vob_state_is_summarised_from_the_zone_store():
    assert _call()["vob"] == "Rising"
    assert _call()["vob_buy_volume"] == 1200.0
    assert _put()["vob"] == "Falling"
    assert terminal.leg_read("CE")["vob"] is None


def test_premium_levels_appear_only_when_the_leg_gate_armed_one():
    """The Decision Engine works in NIFTY points; converting a spot stop to an
    option stop needs delta, which no engine produces."""
    bare = _call()
    assert bare["entry"] is None and bare["stop"] is None
    assert "not derivable without delta" in bare["entry_note"]

    armed = _call(setup={"entry": 124.8, "sl": 118.2, "t1": 165.0,
                         "confidence": 82})
    assert armed["entry"] == 124.8 and armed["stop"] == 118.2
    assert armed["target"] == 165.0
    assert armed["entry_state"] == "ARMED"
    assert armed["entry_note"] is None


def test_a_live_leg_signal_outranks_an_armed_setup():
    both = _call(setup={"entry": 100.0, "sl": 90.0},
                 open_sig={"entry": 124.8, "sl": 118.2, "trail": 121.0,
                           "trail_state": "Tightening"})
    assert both["entry"] == 124.8
    assert both["entry_state"] == "LIVE"
    assert both["trail"] == 121.0 and both["trail_state"] == "Tightening"


def test_the_leg_sentence_is_specific_not_generic():
    s = _call()["sentence"]
    assert "Call buyers accumulating" in s
    assert "VOB building" in s and "leg signals agree" in s
    assert "Put writers defending aggressively" in _put()["sentence"]
    assert "flat" in terminal.leg_read("CE")["sentence"]


def test_a_leg_with_nothing_never_raises():
    c = terminal.leg_read("CE")
    assert c["side"] == "CE" and c["badges"] == []
    assert c["bias"] == "neutral"


# ── CALL vs PUT ─────────────────────────────────────────────────────────
def test_the_ribbon_marks_the_stronger_side():
    r = terminal.compare_ribbon(_call(), _put())
    assert r["winner"] == "CALL"
    assert "vs" in r["why"]
    metrics = {row["metric"] for row in r["rows"]}
    assert {"Bias", "Strength", "Money Flow", "VOB", "Accumulation",
            "Distribution", "Entry", "Trail"} <= metrics


def test_the_ribbon_declines_to_pick_a_winner_when_it_cannot():
    r = terminal.compare_ribbon(terminal.leg_read("CE"),
                                terminal.leg_read("PE"))
    assert r["winner"] is None
    assert "neither leg" in r["why"]


def test_equal_strength_is_reported_as_no_edge():
    r = terminal.compare_ribbon(_call(), _call(side="PE"))
    assert r["winner"] is None and "no edge" in r["why"]


def test_booleans_render_as_yes_no_not_true_false():
    r = terminal.compare_ribbon(_call(), _put())
    acc = next(row for row in r["rows"] if row["metric"] == "Accumulation")
    assert acc["call"] in ("Yes", "No") and acc["put"] in ("Yes", "No")


# ── tinting ─────────────────────────────────────────────────────────────
def test_tinting_needs_a_real_gap():
    """Tinting the screen green on a 51/49 split would read as a signal where
    there is none."""
    close = terminal.dominance({"strength": 52.0}, {"strength": 48.0})
    assert close["side"] == "neutral"
    clear = terminal.dominance({"strength": 78.0}, {"strength": 40.0})
    assert clear["side"] == "call" and clear["gap"] == 38.0
    bear = terminal.dominance({"strength": 40.0}, {"strength": 78.0})
    assert bear["side"] == "put"


def test_tinting_is_neutral_when_a_side_cannot_report():
    assert terminal.dominance({"strength": 80.0}, {})["side"] == "neutral"
    assert terminal.dominance(None, None)["side"] == "neutral"


# ── the ribbon above the chart ──────────────────────────────────────────
def test_market_ribbon_reads_the_engines():
    r = terminal.market_ribbon(_fr())
    assert "Mark Up" in r["state"]
    assert r["bias"] == "BULL"
    assert "Strengthening" in r["transition"]
    assert r["confidence"] == 88
    assert r["quality"] in ("EXCELLENT", "GOOD", "FAIR", "POOR",
                            "UNTRADEABLE", "—")


def test_market_ribbon_falls_back_to_the_market_read_when_not_trading():
    fr = _fr(decision_v2={"state": "WAIT", "label": "⏳ WAIT"},
             confidence_tempered=61)
    assert terminal.market_ribbon(fr)["confidence"] == 61


# ── the mini intelligence panel ─────────────────────────────────────────
def test_intelligence_rows_each_quote_their_engine():
    rows = terminal.option_intelligence(_fr(), _call(), _put())
    assert rows
    for r in rows:
        assert r["label"] and r["value"] and r["engine"]
    labels = {r["label"] for r in rows}
    assert "Calls" in labels and "Puts" in labels and "Writers" in labels


def test_writers_read_comes_from_the_ltp_oi_matrix():
    rows = {r["label"]: r for r in
            terminal.option_intelligence(_fr(), _call(), _put())}
    assert rows["Writers"]["value"] == "Dominating"
    assert "Stage 50" in rows["Writers"]["engine"]


def test_intelligence_omits_rows_it_cannot_fill():
    rows = terminal.option_intelligence({}, {}, {})
    assert rows == []


# ── the recommendation banner ───────────────────────────────────────────
def test_the_banner_quotes_the_decision_engine_in_nifty_points():
    r = terminal.recommendation(_fr(), _call(), _put())
    assert r["trading"] is True
    assert r["action"] == "BUY CALL"
    assert r["entry"] == 23900.0 and r["stop"] == 23850.0
    assert r["trail"] == 23870.0 and r["target"] == 24050.0
    assert r["units"] == "NIFTY points"
    assert r["reasons"]


def test_the_banner_attaches_leg_premium_only_when_the_gate_armed_it():
    without = terminal.recommendation(_fr(), _call(), _put())
    assert without["leg_entry"] is None
    assert "not derivable without delta" in without["leg_note"]

    with_leg = terminal.recommendation(
        _fr(), _call(open_sig={"entry": 126.0, "sl": 118.0, "trail": 121.0}),
        _put())
    assert with_leg["leg_entry"] == 126.0 and with_leg["leg_trail"] == 121.0
    assert with_leg["leg_tag"] == "ATM CE 24000"


def test_the_banner_picks_the_leg_matching_the_decisions_side():
    fr = _fr()
    fr["decision_v2"]["side"] = "PUT"
    r = terminal.recommendation(
        fr, _call(open_sig={"entry": 999.0}),
        _put(open_sig={"entry": 55.5, "sl": 50.0}))
    assert r["leg_entry"] == 55.5


def test_wait_states_the_reason_rather_than_showing_an_empty_ticket():
    fr = _fr()
    fr["decision_v2"] = {"state": "WAIT", "label": "⏳ WAIT", "side": "CALL",
                         "blocked_by": "acceptance not confirmed"}
    r = terminal.recommendation(fr)
    assert r["trading"] is False
    assert r["action"] == "WAIT"
    assert "No high-probability setup" in r["headline"]
    assert "acceptance not confirmed" in r["reasons"][0]
    assert r["units"] is None


def test_the_banner_never_raises_on_nothing():
    r = terminal.recommendation(None)
    assert r["trading"] is False and r["action"]


# ── the chart ───────────────────────────────────────────────────────────
def test_the_chart_is_one_figure_so_the_panels_can_be_synchronised():
    """Three Streamlit columns would be three figures, and Plotly can only
    link axes within a figure — which is exactly the independent scrolling the
    terminal must not have."""
    import inspect

    from mios_v5.ui import terminal_chart
    src = inspect.getsource(terminal_chart.terminal_chart)
    assert "rowspan" in src
    assert 'matches="x"' in src
    assert "column_widths=[0.60, 0.40]" in src
    assert 'spikemode="across"' in src


def test_one_master_timeline_keeps_candle_n_the_same_minute_everywhere():
    """Three series of different lengths put candle n at a different minute on
    each panel. The axes stay linked, so nothing LOOKS broken — the CALL panel
    simply shows 10:47 while NIFTY shows 10:48. That is the failure a trader
    cannot see and cannot recover from."""
    import pandas as pd

    from mios_v5.ui.terminal_chart import align, master_timeline

    t = pd.to_datetime(["2026-07-29 09:15", "2026-07-29 09:16",
                        "2026-07-29 09:17", "2026-07-29 09:18"])
    nifty = {"x": t, "open": [1, 2, 3, 4], "high": [1, 2, 3, 4],
             "low": [1, 2, 3, 4], "close": [1, 2, 3, 4],
             "volume": [9, 9, 9, 9]}
    # the leg did not trade at 09:16 or 09:17 at all
    leg = {"x": pd.to_datetime(["2026-07-29 09:15", "2026-07-29 09:18"]),
           "open": [10, 40], "high": [10, 40], "low": [10, 40],
           "close": [10, 40], "volume": [1, 1]}

    tl = master_timeline([("NIFTY", nifty), ("CE", leg)])
    assert len(tl) == 4

    out = align(leg, tl)
    closes = list(out["close"])
    assert len(closes) == len(tl)
    # the 09:18 candle stays at 09:18 — it does NOT slide left into 09:16
    assert closes[3] == 40.0
    assert closes[1] != closes[1]          # NaN: a gap, not a shifted candle
    assert closes[2] != closes[2]


def test_the_timeline_refuses_to_guess_across_incompatible_axes():
    from mios_v5.ui.terminal_chart import align, master_timeline
    assert master_timeline([]) == []
    assert master_timeline([("a", None)]) == []
    # a panel with nothing to align comes back untouched
    assert align(None, [1, 2]) is None
    p = {"x": [1], "close": [1]}
    assert align(p, []) is p


def test_the_view_survives_the_rerun():
    """Streamlit rebuilds the whole figure every cycle. Without `uirevision`
    that resets zoom, pan and crosshair, so a trader who zoomed into
    10:15-11:20 was thrown back to the full session a second later."""
    import inspect

    from mios_v5.ui import terminal_chart
    src = inspect.getsource(terminal_chart.terminal_chart)
    assert "uirevision" in src
    # keyed on the zoom level, so the buttons still take effect
    assert 'uirevision=f"terminal:{window_minutes}"' in src
    # and the hover has to cross panels, not just gather within one
    assert 'hoversubplots="axis"' in src


def test_option_panels_get_their_own_levels_not_spot_derived_ones():
    """A stop computed in NIFTY points drawn on a premium series marks a price
    that series can never trade."""
    import inspect

    from mios_v5.ui import terminal_chart
    src = inspect.getsource(terminal_chart.terminal_chart)
    assert "_leg_overlay(fig, call_levels, call_zones, 1, 2)" in src
    assert "_leg_overlay(fig, put_levels, put_zones, 2, 2)" in src
    # the NIFTY levels still go to the NIFTY panel only
    assert "row=1, col=1" in src


def test_every_vob_status_has_a_zone_tone():
    from mios_v5.ui.terminal_chart import ZONE_TONE
    for s in ("BUILDING", "INTACT", "FADING", "BREAKING"):
        assert s in ZONE_TONE and len(ZONE_TONE[s]) == 2


def test_every_actionable_level_has_a_style():
    from mios_v5.ui.terminal_chart import LEVELS, LEVEL_LABEL
    for k in ("entry", "stop", "trail", "target", "support", "resistance",
              "war_zone", "liquidity", "vwap", "poc", "vah", "val"):
        assert k in LEVELS and k in LEVEL_LABEL


def test_every_decision_state_a_trader_acts_on_has_a_marker():
    from mios_v5.ui.terminal_chart import SIGNAL_MARKER
    for state in ("ENTER", "ENTRY_READY", "EXIT", "ABORT", "TRAIL",
                  "SCALE_IN", "SCALE_OUT"):
        assert state in SIGNAL_MARKER


def test_the_time_axis_renders_ist_not_utc():
    """The axis read 04:00–11:00 while the market was at 09:48. The data was
    right; the label was UTC. Plotly.js has no timezone support — plotly.py
    serialises a tz-aware timestamp as UTC and drops the offset — so the only
    thing that renders faithfully is a tz-NAIVE series whose wall-clock number
    is already IST."""
    import pandas as pd

    from mios_v5.ui.terminal_chart import _as_time

    # 09:48 IST is 04:18 UTC — the exact 5½-hour error reported
    epoch = int(pd.Timestamp("2026-07-29 04:18:00", tz="UTC").timestamp())
    aware = (pd.Series(pd.to_datetime([epoch], unit="s", utc=True))
             .dt.tz_convert("Asia/Kolkata"))

    for name, series in (
            ("epoch seconds", pd.Series([epoch])),
            ("tz-aware IST", aware),
            ("naive IST", pd.Series(pd.to_datetime(["2026-07-29 09:48:00"]))),
            ("strings", ["2026-07-29 09:48:00"])):
        out = _as_time(series)
        assert getattr(out.dt, "tz", None) is None, f"{name} still carries a tz"
        assert str(out.iloc[0]) == "2026-07-29 09:48:00", name


def test_a_row_index_is_not_mistaken_for_an_epoch():
    import pandas as pd

    from mios_v5.ui.terminal_chart import _as_time
    idx = pd.Series([0, 1, 2, 3])
    assert list(_as_time(idx)) == [0, 1, 2, 3]


def test_zoom_walks_the_steps_and_stops_at_both_ends():
    """Wrapping from the tightest view straight to the whole session reads as
    a misclick, so both ends clamp."""
    from mios_v5.ui.terminal_chart import ZOOM_STEPS, zoom_step

    assert zoom_step(None, +1) == ZOOM_STEPS[-2]     # full session → narrower
    assert zoom_step(60, +1) == 30
    assert zoom_step(60, -1) == 120
    # clamped, not wrapped
    assert zoom_step(ZOOM_STEPS[0], +1) == ZOOM_STEPS[0]
    assert zoom_step(None, -1) is None
    # an unrecognised stored value falls back to the full session
    assert zoom_step(999, +1) == ZOOM_STEPS[-2]


def test_the_zoom_window_is_anchored_at_the_newest_bar():
    """Zooming in on a live chart must keep the price trading now on screen —
    anchoring left would zoom into the open and hide the market."""
    from datetime import datetime

    from mios_v5.ui.terminal_chart import x_range

    end = datetime(2026, 7, 29, 14, 30)
    rng = x_range(end, 60)
    assert rng[1] == end
    assert rng[0] == datetime(2026, 7, 29, 13, 30)
    # full session leaves the axis alone rather than pinning a bogus range
    assert x_range(end, None) is None
    assert x_range(None, 60) is None


def test_the_zoom_label_says_what_you_are_looking_at():
    from mios_v5.ui.terminal_chart import zoom_label
    assert zoom_label(None) == "Full session"
    assert zoom_label(30) == "Last 30m"
    assert zoom_label(120) == "Last 2h"


def test_the_scroll_wheel_no_longer_zooms():
    """The wheel zoomed the chart whenever anyone scrolled the page past it,
    which is not something a trader can ask for on purpose.

    ⚠️ The config moved to the shared `FS_CHART_CONFIG` when the Fullscreen button
    was added — scrollZoom stays off there, so the intent is unchanged even though
    the literal no longer sits inside `_terminal_chart`."""
    import inspect

    from mios_v5.ui import dashboard_v6
    assert dashboard_v6.FS_CHART_CONFIG["scrollZoom"] is False
    src = inspect.getsource(dashboard_v6._terminal_chart)
    assert "config=FS_CHART_CONFIG" in src
    assert "window_minutes=window" in src


def test_the_price_axis_fits_the_days_range_not_zero():
    """The y-axis has to start at the day's low and end at its high. Anything
    wider — a zero baseline, or a stray series — flattens the candles into a
    line and the chart stops showing movement at all."""
    from mios_v5.ui.terminal_chart import price_range

    low = [23954.6, 24000.0, 23980.0]
    high = [24100.0, 24247.8, 24050.0]
    lo, hi = price_range(low, high)
    assert lo < 23954.6 and hi > 24247.8          # padded, not clipped
    assert lo > 23800.0 and hi < 24400.0          # but only just
    assert lo > 0                                  # never a zero baseline


def test_the_price_axis_follows_the_zoom_window():
    """Plotly autoranges over the whole trace, not the visible window — so
    without this, zooming in moved the time axis and left the candles just as
    flat as before."""
    import pandas as pd
    from datetime import datetime, timedelta

    from mios_v5.ui.terminal_chart import price_range, x_range

    t0 = datetime(2026, 7, 29, 9, 15)
    x = pd.Series([t0 + timedelta(minutes=i) for i in range(180)])
    low = pd.Series([23954.6 + i * 1.5 for i in range(180)])
    high = pd.Series([23990.0 + i * 1.5 for i in range(180)])

    full = price_range(low, high, x, None)
    zoom = price_range(low, high, x, x_range(x.iloc[-1], 30))
    assert (zoom[1] - zoom[0]) < (full[1] - full[0])
    assert zoom[0] > full[0] and zoom[1] <= full[1]


def test_each_panel_gets_its_own_price_axis():
    """NIFTY's 24,000 and a ₹120 premium share a time axis, never a price
    axis."""
    from mios_v5.ui.terminal_chart import price_range
    nifty = price_range([23954.6], [24247.8])
    leg = price_range([118.0], [129.0])
    assert nifty[0] > 20000 and leg[1] < 200


def test_a_flat_series_still_gets_a_visible_band():
    from mios_v5.ui.terminal_chart import price_range
    lo, hi = price_range([100.0, 100.0], [100.0, 100.0])
    assert lo < 100.0 < hi
    assert price_range(None, None) is None
    assert price_range([], []) is None


def test_the_volume_overlay_stays_inside_the_price_range():
    """A Plotly bar spans base → base + y. Passing the absolute top as `y`
    while also passing `base` made every bar reach 2 × low, so a 24,000 index
    auto-ranged to ~48,000 and the candles flattened into a line."""
    from mios_v5.ui.terminal_chart import volume_bars

    low = [24000.0, 24010.0, 23990.0]
    high = [24100.0, 24120.0, 24080.0]
    base, heights = volume_bars([1000, 500, 0], low, high)

    assert base == 23990.0
    span = 24120.0 - 23990.0
    # tops, not lengths — this is the number the y-axis actually sees
    tops = [base + h for h in heights]
    assert max(tops) <= max(high)
    assert max(tops) == base + span * 0.18
    assert min(tops) == base                     # zero volume draws nothing
    assert heights[1] == heights[0] / 2          # proportional to volume


def test_the_volume_overlay_cannot_stretch_an_option_leg_either():
    """Doubling a ₹120 premium's range is a smaller number than doubling
    NIFTY's, but the same mistake — and it flattens the LTP chart the same
    way."""
    from mios_v5.ui.terminal_chart import volume_bars

    base, heights = volume_bars([900, 300], [118.0, 120.0], [126.0, 129.0])
    assert base == 118.0
    assert max(base + h for h in heights) <= 129.0


def test_the_volume_overlay_takes_pandas_series():
    """These arrive as Series, never lists. `volume or []` evaluates a Series
    for truthiness — "The truth value of a Series is ambiguous" — and because
    the raise happened while building the figure it took the WHOLE chart down,
    not just the overlay."""
    import pandas as pd

    from mios_v5.ui.terminal_chart import volume_bars

    base, heights = volume_bars(pd.Series([1000, 500]),
                                pd.Series([24000.0, 24010.0]),
                                pd.Series([24100.0, 24120.0]))
    assert base == 24000.0
    assert max(base + h for h in heights) <= 24120.0


def test_the_volume_overlay_declines_rather_than_drawing_nonsense():
    from mios_v5.ui.terminal_chart import volume_bars
    assert volume_bars(None, [1.0], [2.0]) is None
    assert volume_bars([0, 0], [1.0], [2.0]) is None       # no volume at all
    assert volume_bars([5], [24000.0], [24000.0]) is None  # flat bar, no span
    assert volume_bars([5], [], []) is None
    # a NaN volume must not poison the whole overlay
    base, heights = volume_bars([float("nan"), 10], [1.0, 1.0], [2.0, 2.0])
    assert heights[0] == 0.0 and heights[1] > 0


def test_the_leg_picker_prefers_the_exact_atm_strike():
    from mios_v5.ui.terminal_chart import atm_legs
    ce, pe, ce_tag, pe_tag = atm_legs(
        {"ATM+1 CE 24050": "a", "ATM CE 24000": "b", "ATM PE 24000": "c"})
    assert ce == "b" and ce_tag == "ATM CE 24000"
    assert pe == "c" and pe_tag == "ATM PE 24000"
    assert atm_legs(None) == (None, None, None, None)


# ── panels ──────────────────────────────────────────────────────────────
def test_panels_render_and_stay_quiet_when_empty():
    from mios_v5.ui import terminal_panel as tp

    call, put = _call(open_sig={"entry": 126.0, "sl": 118.0, "trail": 121.0,
                                "trail_state": "Tightening"}), _put()
    card = tp.leg_card_html(call, "ATM CALL")
    assert "ATM CALL" in card and "CALL BUILDING" in card
    assert "₹126.00" in card and "Tightening" in card
    assert "leg signals agree" in card

    ribbon = tp.compare_ribbon_html(terminal.compare_ribbon(call, put))
    assert "CALL vs PUT" in ribbon and "👑" in ribbon

    mr = tp.market_ribbon_html(terminal.market_ribbon(_fr()))
    assert "Confidence" in mr and "88%" in mr

    intel = tp.intelligence_html(terminal.option_intelligence(_fr(), call, put))
    assert "Option intelligence" in intel

    banner = tp.recommendation_html(terminal.recommendation(_fr(), call, put))
    assert "BUY CALL" in banner and "NIFTY points" in banner
    assert "Leg entry" in banner

    for fn in (tp.leg_card_html, tp.compare_ribbon_html, tp.intelligence_html,
               tp.recommendation_html):
        try:
            assert fn(None, "x") == "" if fn is tp.leg_card_html else fn(None) == ""
        except TypeError:
            assert fn(None) == ""


def test_the_wait_banner_shows_readiness_not_an_empty_ticket():
    from mios_v5.ui.terminal_panel import recommendation_html
    fr = _fr()
    fr["decision_v2"] = {"state": "WAIT", "label": "⏳ WAIT", "side": "CALL",
                         "blocked_by": "flow shift active"}
    html = recommendation_html(terminal.recommendation(fr))
    assert "WAIT" in html and "readiness" in html
    assert "flow shift active" in html
    assert "Entry" not in html            # no ticket on a non-trade


def test_the_leg_card_states_why_premium_levels_are_missing():
    from mios_v5.ui.terminal_panel import leg_card_html
    html = leg_card_html(_call(), "ATM CALL")
    assert "not derivable without delta" in html


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"terminal tests passed ({len(fns)})")
