"""📊 Per-strike Call vs Put OI / ΔOI for ATM±2 — accumulated, then charted.

⚠️ The reference layout reads `st.session_state.oi_history` / `.chgoi_history` /
`.oi_current_strikes`. **None of those exist in this repo.** What exists is
`df_summary`, rebuilt every cycle, so the series had to be ACCUMULATED — same
`cache_resource` pattern as the IV store, for the same reason.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from mios_v5 import strike_history as SH
from mios_v5.ui import strike_oi_series as SC

_ROOT = pathlib.Path(__file__).resolve().parents[2]
NOW = 1_775_000_000.0
pd = pytest.importorskip("pandas")


def _chain(spot=24610.0, ce_oi=8e6, pe_oi=7e6, ce_chg=2e5, pe_chg=3e5,
           ce_ltp=120.0, pe_ltp=95.0):
    return pd.DataFrame([
        # the names `analyze_option_chain` really merges — vob_minimal.py:3723
        {"Strike": float(k), "openInterest_CE": ce_oi, "openInterest_PE": pe_oi,
         "changeinOpenInterest_CE": ce_chg, "changeinOpenInterest_PE": pe_chg,
         "lastPrice_CE": ce_ltp, "lastPrice_PE": pe_ltp}
        for k in range(24450, 24801, 50)]), spot


def _store(n=3, **kw):
    s = {"snaps": []}
    df, spot = _chain(**kw)
    for i in range(n):
        SH.record(s, df, spot, now=NOW + i * SH.MIN_GAP_S)
    return s


# ── the window ────────────────────────────────────────────────────────

def test_the_window_is_atm_plus_minus_two_by_distance_not_index():
    """⚠️ By distance from spot. The chain does not always start on a round
    strike, and an index-based window slides silently."""
    got = SH.atm_window([24450, 24500, 24550, 24600, 24650, 24700, 24750],
                        24610.0)
    assert got == [24500.0, 24550.0, 24600.0, 24650.0, 24700.0]
    assert len(got) == SH.WINGS * 2 + 1


def test_the_window_truncates_at_the_edge_of_the_chain():
    got = SH.atm_window([24600, 24650, 24700], 24610.0)
    assert got == [24600.0, 24650.0, 24700.0]


def test_labels_are_centred_on_the_window_given():
    lab = SH.labels(["24500", "24550", "24600", "24650", "24700"])
    assert lab["24600"] == "ATM"
    assert lab["24500"] == "ATM-2" and lab["24700"] == "ATM+2"
    # a truncated window is labelled from ITS centre, not a fixed list
    assert SH.labels(["24600", "24650", "24700"])["24650"] == "ATM"


def test_labels_never_claim_moneyness():
    """⚠️ Distance from ATM, NOT ITM/OTM. The first version said "ITM-2" for the
    strike two below spot — true of the call, FALSE of the put, on a chart that
    draws both on one axis. The render showed all five headings taking the call's
    side of a two-sided picture."""
    lab = SH.labels(["24500", "24550", "24600", "24650", "24700"])
    assert not {"ITM", "OTM"} & {v[:3] for v in lab.values()}
    assert set(lab.values()) == {"ATM-2", "ATM-1", "ATM", "ATM+1", "ATM+2"}


# ── accumulation ──────────────────────────────────────────────────────

def test_a_snapshot_is_recorded_per_cycle():
    s = _store(3)
    assert len(s["snaps"]) == 3
    assert SH.read(s)["reporting"] is True


def test_a_rerun_inside_min_gap_does_not_duplicate_the_point():
    """⚠️ A stalled feed must not draw a flat line that looks like a settled
    market — that is the failure the IV store had."""
    s = {"snaps": []}
    df, spot = _chain()
    assert SH.record(s, df, spot, now=NOW) is True
    assert SH.record(s, df, spot, now=NOW + 2) is False
    assert len(s["snaps"]) == 1


def test_one_snapshot_is_not_enough_to_plot():
    s = {"snaps": []}
    df, spot = _chain()
    SH.record(s, df, spot, now=NOW)
    assert SH.read(s)["reporting"] is False
    assert SC.figures(s, "oi") == [] or len(s["snaps"]) == 1


def test_absolute_oi_is_stored_and_units_are_the_panels_business():
    """Dividing in the store would bake a display choice into the data."""
    s = _store(2, ce_oi=8_000_000.0)
    assert SH.series(s, 24600, "ce_oi")["v"][0] == 8_000_000.0
    src = (_ROOT / "mios_v5" / "strike_history.py").read_text()
    assert "100_000" not in src and "100000" not in src


def test_the_latest_window_is_used_not_the_union():
    """⚠️ ATM drifts. The union would offer strikes that left hours ago, whose
    lines stop mid-chart."""
    s = {"snaps": []}
    df1, _ = _chain(spot=24610.0)
    SH.record(s, df1, 24610.0, now=NOW)
    SH.record(s, df1, 24760.0, now=NOW + SH.MIN_GAP_S)
    # the chain stops at 24800, so the window truncates on the high side
    assert SH.strikes(s) == ["24650", "24700", "24750", "24800"]
    assert "24600" not in SH.strikes(s), "a strike that left the window persisted"


def test_a_missing_strike_is_skipped_not_zero_filled():
    """A zero is a real OI reading; inventing one draws a collapse that never
    happened."""
    s = _store(2)
    s["snaps"][-1]["rows"].pop("24600", None)
    ser = SH.series(s, 24600, "ce_oi")
    assert len(ser["v"]) == 1


def test_the_chain_columns_the_store_needs_really_exist():
    """⚠️ Derived from the app. A renamed chain column would silently produce
    empty charts — the `fii_net` failure again."""
    app = (_ROOT / "vob_minimal.py").read_text()
    for field, cands in SH.FIELDS.items():
        assert any(f"'{c}'" in app or f'"{c}"' in app for c in cands), (
            f"{field}: none of {cands} appears in the app — a guessed column "
            f"name is the fii_net bug, a lookup that always misses")


@pytest.mark.parametrize("store", [None, "x", 7, [], ()])
def test_a_junk_store_never_raises(store):
    df, spot = _chain()
    assert SH.record(store, df, spot, NOW) is False
    assert SH.strikes(store) == []
    assert SH.series(store, 24600, "ce_oi") == {"t": [], "v": []}
    assert SH.read(store)["reporting"] is False


def test_an_empty_or_missing_frame_records_nothing():
    s = {"snaps": []}
    assert SH.record(s, None, 24610.0, NOW) is False
    assert SH.record(s, pd.DataFrame(), 24610.0, NOW) is False
    assert SH.record(s, *_chain(), now=NOW) in (True, False)  # spot present


def test_an_unknown_field_returns_empty():
    assert SH.series(_store(2), 24600, "nope") == {"t": [], "v": []}


# ── the reads under each chart ────────────────────────────────────────

@pytest.mark.parametrize("d_oi,d_ltp,state", [
    (1, 1, "LONG BUILDING"), (1, -1, "SHORT BUILDING"),
    (-1, 1, "SHORT COVERING"), (-1, -1, "LONG UNWINDING"),
])
def test_the_oi_price_quadrant_is_stated_once(d_oi, d_ltp, state):
    """One map, so the four cases cannot drift apart between CE and PE."""
    assert SC.POSITION_READ[(d_oi, d_ltp)] == state
    oi = [100.0, 100.0 + 10 * d_oi]
    ltp = [50.0, 50.0 + 5 * d_ltp]
    assert SC.side_read(oi, ltp, "ce")["state"] == state


def test_ce_writing_is_resistance_and_pe_writing_is_support():
    """⚠️ The flip lives in one place. CE writing caps price; PE writing supports
    it — reversing that would invert every level on the panel."""
    oi, ltp = [100.0, 130.0], [50.0, 40.0]          # OI up, price down
    assert "resistance building" == SC.side_read(oi, ltp, "ce")["means"]
    assert "support building" == SC.side_read(oi, ltp, "pe")["means"]


def test_covering_reads_as_the_level_weakening():
    oi, ltp = [130.0, 100.0], [40.0, 50.0]          # OI down, price up
    assert SC.side_read(oi, ltp, "ce")["means"] == "resistance weakening"


def test_a_long_build_makes_no_claim_about_the_index():
    """A long build in an option is not a statement about the index level."""
    oi, ltp = [100.0, 130.0], [40.0, 50.0]
    assert SC.side_read(oi, ltp, "ce")["means"] is None


# ── building-vs-covering is the RECENT trend, not the session drift ──

def test_direction_is_the_recent_trend_not_the_session_drift():
    """⭐ The bug: the panel could only ever say BUILDING.

    OI accumulates through a session, so `oi_last - oi_first` (and the
    day-cumulative ΔOI) net positive almost always — pinning the read to a
    BUILDING row. What tells writers-adding from writers-covering is which way OI
    is moving NOW. Here OI climbed for most of the window but has turned DOWN over
    the recent lookback while premium rises: SHORT COVERING, not building — even
    though the session net change in OI is still up.
    """
    # OI rises 10→59 then falls back over the last ~18 points; premium rising late
    oi = list(range(10, 60)) + list(range(58, 40, -1))
    assert oi[-1] > oi[0], "session drift is still net-up — the old read said building"
    ltp = [100.0] * 50 + [100.0 + i for i in range(1, 19)]
    r = SC.side_read(oi, ltp, "ce")
    assert r["state"] == "SHORT COVERING"
    assert r["means"] == "resistance weakening"


def test_recent_downtrend_with_falling_premium_is_long_unwinding():
    oi = list(range(10, 60)) + list(range(58, 40, -1))     # OI turning down
    ltp = [100.0] * 50 + [100.0 - i for i in range(1, 19)]  # premium falling
    assert SC.side_read(oi, ltp, "pe")["state"] == "LONG UNWINDING"


def test_a_two_point_before_after_pair_is_unchanged():
    """The window on two points is those two points, so a caller that passes a
    plain before/after pair still gets the standard quadrant."""
    assert SC.side_read([100.0, 130.0], [50.0, 40.0], "ce")["state"] == "SHORT BUILDING"
    assert SC.side_read([130.0, 100.0], [40.0, 50.0], "ce")["state"] == "SHORT COVERING"


def test_strike_read_surfaces_covering_from_a_recent_oi_downturn():
    """End to end through the store: OI accumulates for the first half of the
    session, then turns down — the panel now says SHORT COVERING where before it
    was pinned to a BUILDING row."""
    s = {"snaps": []}
    ce_oi_path = ([9e6 + i * 1e5 for i in range(20)]        # rising
                  + [11e6 - i * 1e5 for i in range(1, 21)])  # then falling
    for i, oi in enumerate(ce_oi_path):
        df, spot = _chain(ce_oi=oi, ce_ltp=100.0 + i)       # premium rising
        SH.record(s, df, spot, now=NOW + i * SH.MIN_GAP_S)
    r = SC.strike_read(s, 24600)
    assert r["ce"]["state"] == "SHORT COVERING"
    assert r["ce"]["means"] == "resistance weakening"


def test_one_sample_reads_nothing():
    assert SC.side_read([100.0], [50.0], "ce")["state"] is None
    assert SC.side_read([], [], "pe")["state"] is None


def test_the_heavier_side_names_the_level_and_its_strength():
    s = _store(3, ce_oi=4e6, pe_oi=9e6)
    r = SC.strike_read(s, 24600)
    assert r["heavier"] == "PE" and r["level"] == "support"
    assert r["strength"] == "STRONG" and r["ratio"] >= 2.0

    s2 = _store(3, ce_oi=9e6, pe_oi=8e6)
    r2 = SC.strike_read(s2, 24600)
    assert r2["heavier"] == "CE" and r2["level"] == "resistance"
    assert r2["strength"] == "WEAK"


def _rising(field_oi, field_ltp, k=24600, **base):
    """A store where one side's OI AND premium both rise → LONG BUILDING."""
    s = {"snaps": []}
    for i in range(4):
        df, spot = _chain(**{**base, field_oi: 9e6 + i * 3e5,
                             field_ltp: 100.0 + i * 6.0})
        SH.record(s, df, spot, now=NOW + i * SH.MIN_GAP_S)
    return s


def test_a_level_built_by_buyers_is_flagged_not_sold_as_a_wall():
    """⚠️ Rendered defect: "STRONG RESISTANCE · 6.0×" printed directly above
    "CE: LONG BUILDING". A level is made by WRITERS — 6× the call OI accumulated by
    BUYERS is the opposite of a ceiling. The ratio is still reported as measured;
    the contradiction is stated so the two lines stop disagreeing."""
    s = _rising("ce_oi", "ce_ltp", pe_oi=1.5e6, pe_ltp=95.0)
    r = SC.strike_read(s, 24600)
    assert r["heavier"] == "CE" and r["level"] == "resistance"
    assert r["ce"]["state"] == "LONG BUILDING"
    assert r["level_state"] == "LONG BUILDING"
    assert "buyers" in r["level_note"] and "not writers" in r["level_note"]
    # the measured ratio is NOT quietly rewritten to hide the disagreement
    assert r["ratio"] > 2.0 and r["strength"] == "STRONG"


def test_a_wall_the_writers_really_built_carries_no_caveat():
    s = _store(3, ce_oi=9e6, pe_oi=2e6)          # flat series → no state at all
    assert SC.strike_read(s, 24600).get("level_note") is None
    # and a genuine short build is a level, stated plainly
    s2 = {"snaps": []}
    for i in range(4):
        df, spot = _chain(ce_oi=9e6 + i * 4e5, ce_ltp=140.0 - i * 8.0,
                          pe_oi=2e6, pe_ltp=95.0)
        SH.record(s2, df, spot, now=NOW + i * SH.MIN_GAP_S)
    r2 = SC.strike_read(s2, 24600)
    assert r2["ce"]["state"] == "SHORT BUILDING"
    assert r2.get("level_note") is None


# ── the figures ───────────────────────────────────────────────────────

def test_one_figure_per_strike_for_each_measure():
    pytest.importorskip("plotly")
    s = _store(4)
    for measure in ("oi", "chg"):
        figs = SC.figures(s, measure)
        assert len(figs) == 5, measure
        assert [k for k, _l, _f in figs] == SH.strikes(s)


def test_each_figure_plots_call_against_put():
    pytest.importorskip("plotly")
    _k, _lab, fig = SC.figures(_store(4), "oi")[2]
    names = {t.name for t in fig.data}
    assert names == {"Call", "Put"}


def test_the_title_carries_the_label_strike_and_both_latest_values():
    pytest.importorskip("plotly")
    _k, _lab, fig = SC.figures(_store(4, ce_oi=8e6, pe_oi=7e6), "oi")[2]
    t = fig.layout.title.text
    assert "ATM" in t and "24600" in t
    assert "CE 80.0L" in t and "PE 70.0L" in t


def test_the_title_colours_the_values_and_the_legend_is_off():
    """⚠️ Rendered defect: a three-line title and a legend at y=1.02 drew ON TOP of
    each other — five charts each showing "ATM ₹24600 CE: 4…" clipped behind the
    key. Colouring the two numbers in the title makes the key redundant rather than
    relocating the collision."""
    pytest.importorskip("plotly")
    _k, _lab, fig = SC.figures(_store(4), "oi")[2]
    t = fig.layout.title.text
    assert SC.CE_COLOUR in t and SC.PE_COLOUR in t
    assert fig.layout.showlegend is False
    # the trace names survive for the hover tooltip
    assert {tr.name for tr in fig.data} == {"Call", "Put"}


def test_a_negative_delta_is_not_labelled_with_a_plus():
    pytest.importorskip("plotly")
    _k, _lab, fig = SC.figures(_store(4, ce_chg=-4e5), "chg")[2]
    assert "CE -400.0K" in fig.layout.title.text
    assert "CE +" not in fig.layout.title.text


def test_oi_is_lakhs_and_delta_oi_is_thousands():
    """The units the reference charts used, applied in the panel not the store."""
    pytest.importorskip("plotly")
    oi = SC.figures(_store(4, ce_oi=8e6), "oi")[2][2]
    assert oi.layout.yaxis.title.text == "OI (L)"
    assert max(oi.data[0].y) == pytest.approx(80.0)
    chg = SC.figures(_store(4, ce_chg=2e5), "chg")[2][2]
    assert chg.layout.yaxis.title.text == "ΔOI (K)"
    assert max(chg.data[0].y) == pytest.approx(200.0)


def test_the_delta_chart_carries_a_zero_line():
    """ΔOI is signed — without the axis the sign is guesswork."""
    pytest.importorskip("plotly")
    chg = SC.figures(_store(4), "chg")[2][2]
    assert any(getattr(sh, "y0", None) == 0 for sh in (chg.layout.shapes or ()))
    oi = SC.figures(_store(4), "oi")[2][2]
    assert not (oi.layout.shapes or ())


def test_nothing_stored_draws_no_axes():
    assert SC.figures({"snaps": []}, "oi") == []
    assert SC.figures(None, "oi") == []


def test_equal_oi_is_not_a_level():
    """⚠️ Rendered defect: `"support" if heavier == "PE" else "resistance"` sent the
    None case — CE and PE exactly equal — down the else branch, so a strike at 9.0L
    against 9.0L printed "WEAK RESISTANCE · 1.0×". Equal OI is neither."""
    r = SC.strike_read(_store(2, ce_oi=9e6, pe_oi=9e6), 24600)
    assert r["heavier"] is None
    assert r["level"] is None and r["strength"] is None
    assert r["balanced"] is True


def test_a_balanced_strike_says_so_on_screen():
    src = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_strike_verdict")
    consts = {n.value for n in ast.walk(fn)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "balanced" in consts
    assert any("BALANCED" in c for c in consts)


def test_a_lone_point_is_visible_and_carries_no_time_axis():
    """⚠️ Rendered defect: at marker size 3 the first snapshot was a speck, under
    four x-ticks all reading the same minute — an empty-looking chart with clutter
    instead of one honest observation."""
    pytest.importorskip("plotly")
    _k, _l, one = SC.figures(_store(1), "oi")[2]
    assert all(tr.mode == "markers" for tr in one.data)
    assert all(tr.marker.size >= 8 for tr in one.data)
    assert one.layout.xaxis.showticklabels is False
    # …and a real series keeps its line and its axis
    _k2, _l2, many = SC.figures(_store(4), "oi")[2]
    assert all(tr.mode == "lines+markers" for tr in many.data)
    assert many.layout.xaxis.showticklabels is True


def test_one_snapshot_already_draws_the_current_levels():
    """⚠️ Reported as "not visible", and it was: the panel waited for TWO snapshots
    and the store starts empty at every app restart, so opening the app showed one
    line of caption where ten charts belonged. One snapshot is a real observation —
    the CE-vs-PE level at each strike — and only the build direction needs two."""
    pytest.importorskip("plotly")
    for measure in ("oi", "chg"):
        figs = SC.figures(_store(1), measure)
        assert len(figs) == 5, measure
        assert all(len(tr.x) == 1 for _k, _l, f in figs for tr in f.data)
    # …and the level read works off it, while the build direction stays silent
    r = SC.strike_read(_store(1, ce_oi=9e6, pe_oi=2e6), 24600)
    assert r["level"] == "resistance" and r["strength"] == "STRONG"
    assert r["ce"]["state"] is None and r["pe"]["state"] is None
    assert SC.figures(_store(3), "nope") == []


def test_the_caption_reports_how_much_history_there_is():
    assert "no snapshots yet" in SC.caption({"snaps": []})
    cap = SC.caption(_store(4))
    assert "4 snapshots" in cap and "OI in lakhs" in cap


def test_one_snapshot_says_what_it_can_and_cannot_tell_you():
    """⚠️ Two rendered defects in one line. It first read "1 snapshot(s) · ATM±2 ·
    OI in lakhs, ΔOI in thousands" — duplicating the heading and quoting units for
    charts that were not drawn. The fix then said a series needs two points and
    nothing was plotted, which was true of the code and wrong as a design: one
    snapshot IS the current level at each strike."""
    cap = SC.caption(_store(1))
    assert "current levels only" in cap and "needs a second" in cap
    assert "ATM±" not in cap
    # the units apply now, because one snapshot DOES draw
    assert "lakhs" in cap


def test_the_caption_does_not_repeat_the_heading():
    """The section heading already says ATM±2; saying it twice is noise."""
    assert "ATM±" not in SC.caption(_store(4))


# ── purity and wiring ─────────────────────────────────────────────────

def test_the_store_module_is_pure():
    src = (_ROOT / "mios_v5" / "strike_history.py").read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "plotly"}
    attrs = {n.attr for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Attribute)}
    assert "session_state" not in attrs


def test_the_store_is_cache_resource():
    """⚠️ `cache_data` returns a COPY — appends would be silently discarded."""
    src = (_ROOT / "vob_minimal.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "strike_store")
    decs = [getattr(d.func if isinstance(d, ast.Call) else d, "attr", "")
            for d in fn.decorator_list]
    assert "cache_resource" in decs and "cache_data" not in decs


def test_the_recorder_runs_in_the_analyzer():
    """Bounded by the next section, not by a character count — a fixed-length
    window fails the moment anything is inserted ahead of it, which is exactly how
    the sibling IV test broke when this recorder went in."""
    src = (_ROOT / "vob_minimal.py").read_text()
    i = src.index("_atm_row = df_summary.iloc[")
    j = src.index("# ── 7 · the ATM legs", i)
    block = src[i:j]
    assert "strike_store()" in block and "strike_history" in block


def test_the_charts_are_drawn_below_the_leg_tabulation():
    """⚠️ A renderer nothing calls is the bug this session keeps finding."""
    src = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_charts_screen")
    body = ast.get_source_segment(src, fn) or ""
    called = {c.func.id for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "_strike_oi_charts" in called
    assert body.index("leg_table_html") < body.index("_strike_oi_charts")


def test_the_buyers_caveat_reaches_the_screen():
    """⚠️ A caveat computed and never drawn is the same bug as a renderer nothing
    calls — the contradiction would still be on screen, just unexplained."""
    src = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_strike_verdict")
    keys = {n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "level_note" in keys


def _panel_fn():
    src = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_strike_oi_charts")
    return src, fn


def test_the_basis_is_captioned_before_the_verdicts():
    """⚠️ Rendered defect: the "60 snapshot(s) over 59 min" line sat UNDER both
    sections, so "STRONG SUPPORT · 4.7×" was read with no idea whether it came from
    four snapshots or four hundred."""
    src, fn = _panel_fn()
    body = ast.get_source_segment(src, fn) or ""
    assert body.index("SC.caption(store)") < body.index("_strike_verdict")


def test_the_basis_line_is_not_inside_the_drawing_loop():
    """⚠️ The fix that moved the caption up put it INSIDE `for measure`, so when
    `figures()` returned nothing the entire panel vanished with no explanation —
    the swallowed failure the loud-chrome rule exists to prevent, reintroduced by
    the fix for the previous defect. On the AST: the caption call must not be a
    descendant of any loop."""
    _src, fn = _panel_fn()

    def captions(node):
        return [c for c in ast.walk(node) if isinstance(c, ast.Call)
                and getattr(c.func, "attr", "") == "caption"
                and getattr(getattr(c.func, "value", None), "id", "") == "st"]

    assert captions(fn), "the basis caption is gone entirely"
    for loop in ast.walk(fn):
        if isinstance(loop, (ast.For, ast.While)):
            assert not captions(loop), (
                "an st.caption() inside the drawing loop is skipped whenever the "
                "loop body is skipped — that is how the panel went silent")


def test_snapshots_that_plot_nothing_still_say_so():
    """A heading-less gap reads as "never built". If there are snapshots but no
    figures, the panel must name the reason."""
    src, fn = _panel_fn()
    body = ast.get_source_segment(src, fn) or ""
    assert "if not drew" in body
    assert body.index("drew = True") < body.index("if not drew")


def test_both_column_spellings_are_accepted():
    """⚠️ The catch. `CE_OI_Change` was assumed and does not exist; the chain
    merges `changeinOpenInterest_CE`. Panels elsewhere use `CE_OI` aliases, so
    both work and the first present wins."""
    for oi, chg, ltp in (("openInterest_CE", "changeinOpenInterest_CE",
                          "lastPrice_CE"),
                         ("CE_OI", "CE_OI_Change", "CE_LTP")):
        df = pd.DataFrame([{"Strike": float(k), oi: 8e6, chg: 2e5, ltp: 120.0}
                           for k in range(24500, 24751, 50)])
        s = {"snaps": []}
        assert SH.record(s, df, 24610.0, now=NOW) is True
        assert SH.series(s, 24600, "ce_oi")["v"] == [8e6], (oi, chg)
        assert SH.series(s, 24600, "ce_chg")["v"] == [2e5]
