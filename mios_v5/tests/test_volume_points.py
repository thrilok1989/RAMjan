"""📍 High-volume pivots, and the dynamic PoC's wiring to all three panels.

Modelled on two reference indicators. The **dynamic PoC** was already ported —
`vob_minimal.compute_dynamic_poc` is an explicit port and `ui/profile_overlay` has
always had the branch to draw it — so nothing here re-derives it; the tests below pin
the WIRING that was missing. The **high-volume pivots** did not exist and are built
in `volume_points`.
"""

from __future__ import annotations

import ast
import pathlib
import random

import pytest

from mios_v5 import volume_points as VP
from mios_v5.ui import volume_points_overlay as VO

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _bars(n=340, start=24600.0, drift=0.000014, seed=9,
          spikes=(40, 95, 150, 215, 280)):
    """⚠️ `drift` is RELATIVE to price. An absolute 0.35/bar is a gentle trend on
    NIFTY and 2.3 sigma on a ₹128 premium, which makes the leg series monotonic — and
    a monotonic series correctly has no pivots, so the fixture, not the code, was
    reporting nothing at the smaller price scales."""
    r = random.Random(seed)
    c = start
    hs, ls, cs, vs = [], [], [], []
    for i in range(n):
        c += r.gauss(drift * start, start * 0.0012)
        w = abs(r.gauss(0, start * 0.0008)) + start * 0.0002
        v = r.randint(30_000, 220_000)
        if i in spikes:
            v *= 5
        hs.append(c + w / 2)
        ls.append(c - w / 2)
        cs.append(c)
        vs.append(v)
    return hs, ls, cs, vs


# ── the pivots ────────────────────────────────────────────────────────

def test_a_pivot_needs_bars_either_side_and_reports_both_indices():
    """The bar it formed ON, and the earliest bar that could KNOW. Claiming the
    pivot was knowable when it formed would be hindsight."""
    hs = [10, 11, 12, 20, 12, 11, 10] * 6
    ls = [9] * 42
    got = VP.pivots(hs, ls, left=3, right=3)
    assert got, "no pivot on an obvious peak"
    p = got[0]
    assert p["side"] == "HIGH" and p["price"] == 20
    assert p["confirmed_at"] == p["index"] + 3


def test_a_clean_trend_has_no_pivots_and_says_so():
    """⚠️ Pivot logic goes blind exactly when a trend is cleanest — the window's
    extreme sits at its edge, never its centre. `market_structure` documents the same
    blind spot. Silence that cannot explain itself reads as a broken feature."""
    hs = [100 + i for i in range(80)]
    ls = [99 + i for i in range(80)]
    assert VP.pivots(hs, ls) == []
    r = VP.read(VP.high_volume_pivots(hs, ls, hs, [1000] * 80))
    assert r["n"] == 0
    assert r["why"] and "no swing pivots" in r["why"]
    assert "no swing pivots" in VO.micro([], 100.0)


def test_volume_is_judged_against_the_series_own_distribution():
    """⚠️ So NIFTY and a ₹90 premium leg can share one threshold honestly. An
    absolute lot count could not: the leg would never qualify and the index always
    would."""
    for start in (24600.0, 128.0, 12.0):
        hs, ls, cs, vs = _bars(start=start)
        kept = VP.high_volume_pivots(hs, ls, cs, vs)
        assert kept, f"nothing kept at price scale {start}"
        assert all(p["norm"] > VP.FILTER_VOL for p in kept)


def test_no_volume_means_no_high_volume_pivots():
    """A "high volume" pivot with no volume behind it is a plain pivot wearing the
    label."""
    hs, ls, cs, _vs = _bars()
    assert VP.pivots(hs, ls), "the fixture has no pivots at all"
    assert VP.high_volume_pivots(hs, ls, cs, None) == []
    assert VP.high_volume_pivots(hs, ls, cs, [0] * len(hs)) == []


def test_the_reference_is_a_percentile_not_the_maximum():
    """⚠️ One opening-auction print would otherwise set the bar for the whole session
    and nothing else would ever qualify."""
    assert VP.REFERENCE_PCT < 100
    hs, ls, cs, vs = _bars()
    vs = list(vs)
    vs[5] = max(vs) * 400                       # one absurd print
    assert VP.high_volume_pivots(hs, ls, cs, vs), "one spike silenced the session"


def test_a_level_breaks_on_a_close_not_a_wick():
    """⚠️ A level a single wick poked through is still a level. Breaking on the wick
    retires every level on the first stop-run of the session."""
    hs = [10, 11, 12, 20, 12, 11, 10, 10, 10, 10]
    ls = [9] * 10
    # closes stay under 20 the whole way, but one HIGH pokes above
    cs = [10, 11, 12, 15, 12, 11, 10, 10, 10, 10]
    pts = VP.pivots(hs, ls, left=3, right=3)
    hi = next(p for p in pts if p["side"] == "HIGH")
    assert VP._broken_at(cs, hi["index"], hi["price"], "HIGH") is None
    # …and a close through it does break it
    cs2 = list(cs)
    cs2[7] = 21.0
    assert VP._broken_at(cs2, hi["index"], hi["price"], "HIGH") == 7


def test_broken_levels_are_kept_not_deleted():
    hs, ls, cs, vs = _bars()
    kept = VP.high_volume_pivots(hs, ls, cs, vs)
    r = VP.read(kept, cs[-1])
    assert r["broken"] > 0, "the fixture never broke a level"
    assert r["n"] == r["live"] + r["broken"]
    assert len(VP.live_levels(kept)) == r["live"]


def test_the_read_names_the_next_level_each_side_and_no_side():
    hs, ls, cs, vs = _bars()
    kept = VP.high_volume_pivots(hs, ls, cs, vs)
    r = VP.read(kept, cs[-1])
    for key in ("nearest_above", "nearest_below"):
        p = r.get(key)
        if p is not None:
            assert (p["price"] > cs[-1]) is (key == "nearest_above")
            assert p["broken_at"] is None, "a broken level is not still in the way"
    line = VO.micro(kept, cs[-1])
    assert "live HV level" in line
    for banned in ("BUY", "SELL", "LONG", "SHORT", "ENTER"):
        assert banned not in line.upper()


# ── the overlay geometry ──────────────────────────────────────────────

def test_a_pandas_index_does_not_silently_draw_nothing():
    """⚠️ THE bug rendering caught. `if x else None` on a pandas DatetimeIndex raises
    "The truth value of a DatetimeIndex is ambiguous" — and `draw`'s own except
    swallowed it, so every panel drew no pivots at all while these tests, which hand
    in plain lists, passed. `len(x)`, never truthiness."""
    pd = pytest.importorskip("pandas")
    hs, ls, cs, vs = _bars()
    kept = VP.high_volume_pivots(hs, ls, cs, vs)
    assert kept
    idx = pd.to_datetime(pd.Series(range(len(hs)), name="t"), unit="m")
    for axis in (idx, pd.DatetimeIndex(idx), list(idx), idx.to_numpy()):
        sp = VO.specs(kept, axis)
        assert len(sp) == len(kept), type(axis).__name__


def test_a_level_starts_at_its_pivot_and_ends_where_it_broke():
    """⚠️ `add_hline` spans the whole panel, which would claim the level existed
    before the pivot that made it."""
    hs, ls, cs, vs = _bars()
    kept = VP.high_volume_pivots(hs, ls, cs, vs)
    x = list(range(len(hs)))
    for p, s in zip(kept, VO.specs(kept, x)):
        assert s["x0"] == p["index"]
        if p["broken_at"] is not None:
            assert s["x1"] == p["broken_at"] and s["dash"] == VO.BROKEN_DASH
        else:
            assert s["x1"] == len(x) - 1 and s["dash"] == VO.LIVE_DASH


def test_a_pivot_off_the_shared_axis_is_dropped_not_clamped():
    """⚠️ Points come from the panel's own frame; the figure's axis is the SHARED
    timeline. A leg that started late has fewer x values, and a clamped index puts
    the marker on the wrong minute."""
    pts = [{"index": 5, "price": 100.0, "side": "HIGH", "weight": 3},
           {"index": 500, "price": 101.0, "side": "LOW", "weight": 3}]
    sp = VO.specs(pts, list(range(20)))
    assert len(sp) == 1 and sp[0]["y"] == 100.0


def test_thickness_and_size_carry_volume_and_nothing_else():
    a = VO.specs([{"index": 1, "price": 10.0, "side": "HIGH", "weight": 1}], [0, 1, 2])
    e = VO.specs([{"index": 1, "price": 10.0, "side": "HIGH", "weight": 5}], [0, 1, 2])
    assert e[0]["width"] > a[0]["width"] and e[0]["size"] > a[0]["size"]
    # …and the colour is the SIDE, so thickness never implies direction
    lo = VO.specs([{"index": 1, "price": 10.0, "side": "LOW", "weight": 1}], [0, 1, 2])
    assert a[0]["colour"] != lo[0]["colour"]
    assert a[0]["colour"] == e[0]["colour"]


def test_nothing_to_draw_draws_nothing():
    assert VO.specs([], [1, 2]) == [] and VO.specs(None, [1, 2]) == []
    assert VO.specs([{"index": 1, "price": 10.0}], None) == []
    assert VO.draw(None, 1, 1, points=[{"index": 1, "price": 10.0}]) == {
        "levels": 0, "dots": 0, "note": 0}


@pytest.mark.parametrize("junk", [None, "x", 7, [], (), {}, [None], [7]])
def test_junk_never_raises(junk):
    VP.pivots(junk, junk)
    assert VP.high_volume_pivots(junk, junk, junk, junk) == []
    assert VP.rolling_sum(junk, 5) == [] or isinstance(VP.rolling_sum(junk, 5), list)
    assert VP.read(junk)["n"] == 0
    assert isinstance(VO.specs(junk, junk), list)
    assert isinstance(VO.micro(junk, junk), str)


# ── purity ────────────────────────────────────────────────────────────

def test_both_modules_are_pure_and_the_overlay_imports_no_plotly():
    """⚠️ The overlay only ever calls methods on the figure it was handed —
    `add_shape`, `add_scatter` — which is why it is testable without plotly and why
    `profile_overlay`'s existing guard can stay strict."""
    for rel, banned in (
            (("mios_v5", "volume_points.py"),
             {"streamlit", "vob_minimal", "pandas", "plotly", "numpy"}),
            (("mios_v5", "ui", "volume_points_overlay.py"),
             {"streamlit", "vob_minimal", "pandas", "plotly", "numpy"})):
        src = _ROOT.joinpath(*rel).read_text()
        names = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                names.add(n.module.split(".")[0])
        assert not names & banned, (rel, names & banned)


def test_no_second_dynamic_poc_was_written():
    """⚠️ An earlier draft of `volume_points` had its own `developing_poc`. It was
    deleted on finding `compute_dynamic_poc` — an explicit port of the same reference
    indicator, already in the app and already feeding three other consumers. A second
    implementation of a number the app computes is what the one-owner rule exists to
    prevent."""
    assert not hasattr(VP, "developing_poc")
    src = (_ROOT / "mios_v5" / "volume_points.py").read_text()
    fns = {n.name for n in ast.walk(ast.parse(src))
           if isinstance(n, ast.FunctionDef)}
    assert not {"developing_poc", "dynamic_poc", "poc_line"} & fns


# ── the wiring, which is what was actually broken ─────────────────────

def test_the_dynamic_poc_finally_has_a_writer():
    """⚠️ `profile_overlay.levels` has read `dynamic_poc` since it was written —
    colour, dash, "Dyn POC" label and all — and NOTHING EVER SET THE KEY.
    `compute_dynamic_poc` fed the liquidity context, a bias push and the daily read,
    but never the profile dicts the chart draws, so the line had never appeared on any
    panel. A reader with no writer."""
    d6 = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(d6))
              if isinstance(n, ast.FunctionDef) and n.name == "_panel_profile")
    keys = {n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "dynamic_poc" in keys and "dynamic_poc_series" in keys
    assert "hv_points" in keys
    # …through the app's builder bridge, not by importing the app
    assert "_premium_builders" in keys
    app = (_ROOT / "vob_minimal.py").read_text()
    assert "'dynamic_poc': lambda f:" in app
    assert "'hv_points': _hv_points," in app


def test_the_scalar_and_the_series_are_both_published():
    """⚠️ `profile_overlay.levels` runs `_f()` over `dynamic_poc`, and `_f(a_list)` is
    None — so even had anything set the key, handing it the series would still have
    drawn nothing. The scalar is the labelled current level; the series is the curve
    that makes it dynamic."""
    from mios_v5.ui import profile_overlay as PO
    assert PO.levels({"dynamic_poc": [1.0, 2.0, 3.0]}) == []
    got = PO.levels({"dynamic_poc": 24600.0})
    assert [g["key"] for g in got] == ["dynamic_poc"]


def test_the_poc_stepline_is_stepped_and_needs_an_axis():
    pytest.importorskip("plotly")
    import plotly.graph_objects as go
    from mios_v5.ui import profile_overlay as PO
    # ⚠️ `make_subplots`, not a bare Figure: `add_scatter(row=, col=)` on a figure
    # with no subplot grid raises, which `draw`'s except would swallow — the test
    # would then pass for the wrong reason on a real chart and fail here.
    from plotly.subplots import make_subplots
    fig = make_subplots(rows=1, cols=1)
    prof = {"dynamic_poc_series": [None, 10.0, 10.0, 12.0]}
    assert PO.draw(fig, 1, 1, profile=prof, x=[0, 1, 2, 3])["dyn_poc"] == 1
    tr = next(t for t in fig.data if t.name == "Dyn PoC")
    assert tr.line.shape == "hv", "a PoC relocates a bin at a time, it does not ramp"
    # no axis → nothing drawn rather than a trace against bar numbers
    fig2 = make_subplots(rows=1, cols=1)
    assert PO.draw(fig2, 1, 1, profile=prof)["dyn_poc"] == 0


def test_all_three_panels_get_both_overlays():
    """⚠️ "add this two indicator in all there charts nifty and ltps". Per panel and
    on the panel's own series — an index PoC on a premium axis marks a price that leg
    cannot trade."""
    tc = (_ROOT / "mios_v5" / "ui" / "terminal_chart.py").read_text()
    tree = ast.parse(tc)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_profile_overlay")
    names = set()
    for a in ast.walk(fn):
        if isinstance(a, ast.ImportFrom):
            names |= {x.name for x in a.names} | {x.asname for x in a.names}
    assert "volume_points_overlay" in (
        {a.module for a in ast.walk(fn) if isinstance(a, ast.ImportFrom)})
    assert "_hv_draw" in names
    # …and the caller hands every panel its own x axis
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "terminal_chart")
    body = ast.get_source_segment(tc, main) or ""
    assert "_profile_overlay(fig, prof, r, c," in body and "x=" in body


# ── asked for: thick and bright, a reason, and settings ────────────────

def test_the_dynamic_poc_is_thicker_and_brighter_than_the_frozen_levels():
    """⚠️ Asked for, and it is the right weight: this is the line that MOVES, so it
    carries the session's story while POC/VAH/VAL are one frozen reading each. At
    1.3px dashdot it was the faintest thing on a panel full of thin dotted levels."""
    from mios_v5.ui import profile_overlay as PO
    colour, dash, width, label = PO.LEVEL_STYLE["dynamic_poc"]
    assert width >= 2.5, width
    assert dash == "solid"
    assert all(width > PO.LEVEL_STYLE[k][2] for k in ("poc", "vah", "val"))
    # bright: every channel high, not a muted grey
    r, g = int(colour[1:3], 16), int(colour[3:5], 16)
    assert r > 200 and g > 150, colour


def test_the_stepline_takes_its_width_from_the_one_style_map():
    """The stepline and the labelled level it ends at must not drift apart."""
    pytest.importorskip("plotly")
    from plotly.subplots import make_subplots

    from mios_v5.ui import profile_overlay as PO
    fig = make_subplots(rows=1, cols=1)
    PO.draw(fig, 1, 1, profile={"dynamic_poc_series": [None, 1.0, 2.0]},
            x=[0, 1, 2])
    tr = next(t for t in fig.data if t.name == "Dyn PoC")
    assert tr.line.width == PO.LEVEL_STYLE["dynamic_poc"][2]
    assert tr.line.color == PO.LEVEL_STYLE["dynamic_poc"][0]


def test_a_panel_with_no_pivots_says_why_on_the_panel():
    """⚠️ Reported as "not displaying in the put ltp". A strongly trending leg has no
    swing pivots — which is exactly what a put does while the index falls — so the
    overlay was right to draw nothing and wrong to say nothing. An empty panel and a
    broken panel look identical."""
    pytest.importorskip("plotly")
    from plotly.subplots import make_subplots
    fig = make_subplots(rows=1, cols=1)
    why = VP.read([])["why"]
    got = VO.draw(fig, 1, 1, points=[], x=[0, 1, 2], why=why)
    assert got["note"] == 1 and got["dots"] == 0
    note = next(a for a in fig.layout.annotations if "swing pivots" in a.text)
    assert note.text.startswith("📍")
    # …and no note when there is nothing to explain
    fig2 = make_subplots(rows=1, cols=1)
    assert VO.draw(fig2, 1, 1, points=[], x=[0, 1, 2])["note"] == 0


def test_the_note_escapes_what_it_is_given():
    pytest.importorskip("plotly")
    from plotly.subplots import make_subplots
    fig = make_subplots(rows=1, cols=1)
    VO.draw(fig, 1, 1, points=[], x=[0], why="<script>x</script>")
    txt = " ".join(a.text for a in fig.layout.annotations)
    assert "<script>" not in txt and "&lt;script&gt;" in txt


def test_the_settings_are_one_map_and_a_caller_cannot_mutate_them():
    d = VP.defaults()
    assert set(d) == {"left", "right", "filter_vol"}
    d["left"] = 999
    assert VP.defaults()["left"] == VP.LEFT, "defaults() handed out its own dict"


def test_the_settings_actually_change_what_is_kept():
    hs, ls, cs, vs = _bars()
    loose = VP.high_volume_pivots(hs, ls, cs, vs, filter_vol=0.5)
    tight = VP.high_volume_pivots(hs, ls, cs, vs, filter_vol=5.5)
    assert len(loose) > len(tight), "the volume filter does nothing"
    wide = VP.high_volume_pivots(hs, ls, cs, vs, left=40, right=40)
    narrow = VP.high_volume_pivots(hs, ls, cs, vs, left=4, right=4)
    assert len(narrow) > len(wide), "the bar windows do nothing"


def test_the_computation_reads_the_settings_and_falls_back_to_defaults():
    """⚠️ `defaults()` is the ONE place the fallbacks live, so a key the user has not
    set cannot mean a different threshold here than in the panel offering it."""
    src = (_ROOT / "vob_minimal.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_hv_points")
    keys = {n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    names = set()
    for a in ast.walk(fn):
        if isinstance(a, ast.ImportFrom):
            names |= {x.name for x in a.names}
    assert "_hv_settings" in keys
    assert "defaults" in names
    assert {"left", "right", "filter_vol"} <= keys


def test_changing_a_setting_takes_effect_now_not_at_the_next_bar_close():
    """⚠️ `_panel_profiles` keys on BAR COUNT, which does not change when a setting
    does — so a new threshold would sit unused until the next bar closed."""
    d6 = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(d6))
              if isinstance(n, ast.FunctionDef) and n.name == "_hv_settings")
    keys = {n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_hv_settings" in keys and "_panel_profiles" in keys
    calls = {getattr(c.func, "attr", "") for c in ast.walk(fn)
             if isinstance(c, ast.Call)}
    assert "pop" in calls, "the stale cached profiles are never cleared"
    # the control offers exactly the three knobs and computes nothing
    assert "number_input" in calls
    assert not {"high_volume_pivots", "pivots"} & calls


def test_the_setting_is_written_only_behind_the_apply_button():
    """⚠️ The staged inputs must not commit on the 20-second autorefresh — a
    trader dialling 15 → 22 would otherwise redraw every chart on each
    intermediate value. `_hv_settings` is assigned, `_panel_profiles` is dropped
    and the page is rerun ONLY inside the `if apply_clicked:` branch, so a value
    becomes live only when Apply is pressed."""
    d6 = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(d6))
              if isinstance(n, ast.FunctionDef) and n.name == "_hv_settings")

    # a button is offered, and the page reruns so the charts (drawn above this
    # control) pick up the new pivots in the same interaction.
    calls = {getattr(c.func, "attr", "") for c in ast.walk(fn)
             if isinstance(c, ast.Call)}
    assert "button" in calls, "no Apply button"
    assert "rerun" in calls, "Apply does not redraw the charts"

    # find the `if apply_clicked:` guard and prove the write + cache-drop live
    # inside it, not at function top level where every rerun would run them.
    guard = None
    for node in ast.walk(fn):
        if (isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id == "apply_clicked"):
            guard = node
            break
    assert guard is not None, "the write is not gated on the button"

    def _hv_settings_writes(scope):
        return [n for n in ast.walk(scope)
                if isinstance(n, ast.Subscript)
                and isinstance(n.ctx, ast.Store)
                and isinstance(n.slice, ast.Constant)
                and n.slice.value == "_hv_settings"]

    guarded_calls = {getattr(c.func, "attr", "") for c in ast.walk(guard)
                     if isinstance(c, ast.Call)}
    assert "pop" in guarded_calls, "the cache is dropped outside Apply"
    assert "rerun" in guarded_calls, "the rerun is outside Apply"

    # every write to `_hv_settings` lives inside the Apply branch — nowhere else
    # in the function commits the staged value.
    writes_in_guard = {id(n) for n in _hv_settings_writes(guard)}
    all_writes = _hv_settings_writes(fn)
    assert all_writes, "the setting is never written"
    assert all(id(n) in writes_in_guard for n in all_writes), \
        "_hv_settings is committed outside the Apply branch"
