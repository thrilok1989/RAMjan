"""🏛 Rolling (dynamic) POC per structural window, and the layered read.

Modelled on a multi-timeframe POC indicator whose `pocForTF` approximates each
period's POC as the previous period's `(high + low + close) / 3`. That is a typical
price, not a point of control — it ignores volume entirely, so it lands mid-range
whether the volume traded at the high or the low. These tests pin the difference:
the POC here comes from `htf_vpfr.build_profile`, this repo's ONE POC owner, run
over a sliding window.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from mios_v5 import poc_series as PS
from mios_v5.ui import poc_structure as PC

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _bars(n=300, start=20000.0, drift=0.0004, seed=3):
    """A daily series with a real volume column."""
    import random
    r = random.Random(seed)
    c = start
    hs, ls, vs = [], [], []
    for _ in range(n):
        c *= (1 + r.gauss(drift, 0.009))
        w = c * r.uniform(0.004, 0.016)
        hs.append(c + w / 2)
        ls.append(c - w / 2)
        vs.append(r.randint(150_000, 400_000))
    return hs, ls, vs


# ── the POC is volume-weighted, not a typical price ───────────────────

def test_the_poc_is_the_busiest_price_not_the_mid_range():
    """⚠️ THE difference from the reference. Volume is piled at the LOW of every
    bar, so `(h+l+c)/3` would sit mid-range while the real POC sits at the low."""
    hs = [100.0] * 40
    ls = [90.0] * 40
    # one tall bar concentrated at the bottom of the range, forty times over
    vs = [1_000_000.0] * 40
    line = PS.poc_line(hs, ls, vs, window=20)
    poc = [v for v in line if v is not None][-1]
    # every bar spans 90-100 identically, so the profile is flat and the POC is
    # mid-range HERE — the point of the next test is that volume moves it.
    assert 90.0 <= poc <= 100.0

    # now put the volume in narrow bars sitting at 92, inside wider bars
    hs2 = [100.0, 92.5] * 20
    ls2 = [90.0, 91.5] * 20
    vs2 = [1.0, 5_000_000.0] * 20
    poc2 = [v for v in PS.poc_line(hs2, ls2, vs2, window=20) if v is not None][-1]
    assert 91.0 <= poc2 <= 93.0, poc2
    mid = (max(hs2) + min(ls2)) / 2
    assert abs(poc2 - mid) > 1.5, "a typical price would sit at the mid-range"


def test_the_repo_s_own_profile_builder_is_used():
    """⚠️ Not a fifth POC. The audit found four implementations and chose
    `build_profile`; a rolling POC is that function over a sliding window."""
    src = (_ROOT / "mios_v5" / "poc_series.py").read_text()
    tree = ast.parse(src)
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            imported |= {a.name for a in n.names}
    assert "build_profile" in imported
    # and no private binning of its own
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(tree) if isinstance(c, ast.Call)}
    assert not {"histogram", "digitize", "cut", "value_counts"} & called


# ── dynamic: it moves ─────────────────────────────────────────────────

def test_the_poc_is_a_series_not_one_level():
    """The whole point of "dynamic": a value per bar, not one horizontal line."""
    hs, ls, vs = _bars(300)
    line = PS.poc_line(hs, ls, vs, window=21)
    got = [v for v in line if v is not None]
    assert len(line) == 300
    assert len(set(got)) > 5, "a dynamic POC has to actually move"


def test_the_warm_up_is_none_not_a_forward_filled_price():
    """⚠️ A forward-filled warm-up draws a flat line that never happened."""
    hs, ls, vs = _bars(30)
    line = PS.poc_line(hs, ls, vs, window=21)
    assert line[0] is None and line[1] is None
    assert line[PS.MIN_BARS - 1] is not None


def test_a_window_longer_than_the_history_is_skipped_not_truncated():
    """⚠️ A "Yearly" POC built from 40 days carries a yearly label on a monthly
    measurement."""
    hs, ls, vs = _bars(40)
    got = PS.lines(hs, ls, vs)
    assert "Weekly" in got and "Monthly" in got
    assert "Yearly" not in got and "Quarterly" not in got


def test_every_window_reports_with_enough_history():
    hs, ls, vs = _bars(400)
    got = PS.lines(hs, ls, vs)
    assert set(got) == {label for label, _w in PS.WINDOWS}


def test_the_latest_bar_is_always_freshly_computed():
    """`step` carries a value between recomputes, so the LAST bar must be forced —
    otherwise the newest POC could be up to `step` bars stale."""
    hs, ls, vs = _bars(300)
    stepped = PS.poc_line(hs, ls, vs, window=63, step=10)
    exact = PS.poc_line(hs, ls, vs, window=63, step=1)
    assert stepped[-1] == exact[-1]


# ── the layered read ──────────────────────────────────────────────────

def test_migration_is_measured_over_the_window_not_the_whole_series():
    """⚠️ Caught by running it: drift from the series' FIRST value to its last made
    all four windows say "UP" over five years of index history — true of the market
    and useless as a read. A window's migration is its own POC over its own span."""
    hs, ls, vs = _bars(400, drift=0.0012)          # a long uptrend
    rows = PS.stack(PS.lines(hs, ls, vs), spot=hs[-1])
    assert rows, "nothing to read"
    for r in rows:
        assert r["drift_bars"] <= dict(PS.WINDOWS)[r["label"]]
    # not every window can agree, because they measure different spans
    assert len({r["migrated"] for r in rows}) >= 1
    # and the weekly window looks back a week, not 400 bars
    wk = next(r for r in rows if r["label"] == "Weekly")
    assert wk["drift_bars"] == 5


def test_the_rows_run_slowest_first():
    """The anchor leads: it is the permission, and the faster windows are read
    against it."""
    hs, ls, vs = _bars(400)
    rows = PS.stack(PS.lines(hs, ls, vs), spot=hs[-1])
    assert [r["label"] for r in rows] == ["Yearly", "Quarterly", "Monthly", "Weekly"]


def test_side_and_distance_come_from_spot():
    hs, ls, vs = _bars(400)
    series = PS.lines(hs, ls, vs)
    poc = [v for v in series["Weekly"] if v is not None][-1]
    hi = PS.stack(series, spot=poc + 500)
    lo = PS.stack(series, spot=poc - 500)
    assert next(r for r in hi if r["label"] == "Weekly")["side"] == "ABOVE"
    assert next(r for r in lo if r["label"] == "Weekly")["side"] == "BELOW"
    assert next(r for r in hi if r["label"] == "Weekly")["distance"] == 500.0


def test_no_spot_means_no_side_rather_than_a_guessed_one():
    hs, ls, vs = _bars(400)
    rows = PS.stack(PS.lines(hs, ls, vs), spot=None)
    assert rows and all("side" not in r for r in rows)


# ── it produces no signal ─────────────────────────────────────────────

def test_nothing_here_produces_a_side_or_an_entry():
    """⚠️ The reference indicator emits LONG/SHORT entries from stacked acceptance.
    This layer is context: it says where price sits, and the decision has an owner.
    A module that turned "above all four" into BUY would be minting a signal from a
    row count."""
    src = (_ROOT / "mios_v5" / "poc_series.py").read_text()
    consts = {n.value for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    banned = {"BUY", "SELL", "LONG", "SHORT", "ENTER", "ENTRY", "CALL", "PUT"}
    assert not banned & {c.upper() for c in consts}, banned & {c.upper() for c in consts}


def test_the_table_says_above_not_accepted():
    """⚠️ Acceptance needs consecutive closes and Stage 42 owns it. The reference's
    table prints "✓ ABOVE" for acceptance; conflating one bar's position with
    acceptance would be a second verdict on an answered question."""
    # ⚠️ DOCSTRINGS EXCLUDED. `ast.Constant` includes them, so the note explaining
    # why this panel must not say ACCEPTED matched the assertion that it doesn't —
    # the same self-match that has bitten the raw-text version of this check nine
    # times. Only strings that can reach the screen count.
    src = (_ROOT / "mios_v5" / "ui" / "poc_structure.py").read_text()
    tree = ast.parse(src)
    # ⚠️ By NODE IDENTITY, not by value: `ast.get_docstring` returns the cleaned,
    # dedented text, which never equals the raw `Constant.value`, so subtracting
    # the strings removed nothing and the docstrings matched anyway.
    doc_ids = set()
    for n in ast.walk(tree):
        body = getattr(n, "body", None)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and body:
            first = body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                doc_ids.add(id(first.value))
    consts = {n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)
              and id(n) not in doc_ids}
    assert not any("ACCEPT" in c.upper() for c in consts), \
        [c for c in consts if "ACCEPT" in c.upper()]
    hs, ls, vs = _bars(400)
    rows = PS.stack(PS.lines(hs, ls, vs), spot=hs[-1])
    html = PC.table_html(rows, PS.alignment(rows))
    assert "ACCEPTED" not in html.upper()
    assert "ABOVE" in html or "BELOW" in html


def test_alignment_counts_and_refuses_to_conclude():
    hs, ls, vs = _bars(400)
    rows = PS.stack(PS.lines(hs, ls, vs), spot=hs[-1])
    al = PS.alignment(rows)
    assert al["n"] == len(rows) and al["above"] + al["below"] <= al["n"]
    assert al["label"] and "BUY" not in al["label"].upper()
    assert PS.alignment([])["reporting"] is False


# ── the figure ────────────────────────────────────────────────────────

def test_one_trace_per_window_and_no_candles():
    """⚠️ No candles by request AND by design: with bars drawn the eye follows the
    bars and the POCs become decoration. No close line either — that would make this
    a second price chart."""
    pytest.importorskip("plotly")
    hs, ls, vs = _bars(400)
    series = PS.lines(hs, ls, vs)
    fig = PC.figure(list(range(len(hs))), series, spot=hs[-1])
    assert fig is not None
    assert len(fig.data) == len(series)
    kinds = {type(t).__name__ for t in fig.data}
    assert kinds == {"Scatter"}, kinds
    assert all(t.mode == "lines" for t in fig.data)


def test_the_poc_lines_are_stepped_not_ramped():
    """⚠️ A POC is a MODAL statistic — it holds a level then relocates. Measured over
    a year it jumps thousands of points, and quadrupling the bin count leaves the
    jumps identical, so it is not a resolution artefact. A straight segment between
    two modes draws a ramp through prices that were never the mode."""
    pytest.importorskip("plotly")
    hs, ls, vs = _bars(400)
    fig = PC.figure(list(range(len(hs))), PS.lines(hs, ls, vs), spot=hs[-1])
    assert all(t.line.shape == "hv" for t in fig.data)


def test_the_intraday_pocs_are_a_sentence_not_lines_on_a_daily_axis():
    """⚠️ Rendered defect: drawn as `hline`s, the 1H and 4H annotations and the spot
    annotation piled into one unreadable smear at the right edge — they sit within a
    few points of each other on a 1,250-bar axis."""
    pytest.importorskip("plotly")
    hs, ls, vs = _bars(400)
    fig = PC.figure(list(range(len(hs))), PS.lines(hs, ls, vs), spot=24600.0,
                    subdaily={"1H": 24640.0, "4H": 24515.0})
    # plotly's Shape is not a dict — `.get` raises. Attribute access.
    ys = {round(float(s.y0), 1) for s in (fig.layout.shapes or ())
          if s.y0 is not None}
    assert 24640.0 not in ys and 24515.0 not in ys
    assert 24600.0 in ys, "spot is the one reference line kept"
    # …and they are stated in words instead, with the side
    line = PC.subdaily_line({"1H": 24640.0, "4H": 24515.0}, 24600.0)
    assert "1H" in line and "4H" in line
    assert "below 40" in line and "above 85" in line
    assert "not a curve" in line


def test_nothing_to_draw_draws_nothing():
    assert PC.figure([], {}, 24600.0) is None
    assert PC.figure([1, 2], {}, None) is None
    assert PC.table_html([]) == "" and PC.table_html("junk") == ""
    assert PC.subdaily_line(None, None) == ""


# ── purity and junk ───────────────────────────────────────────────────

def test_both_modules_are_pure():
    for rel in (("mios_v5", "poc_series.py"), ("mios_v5", "ui", "poc_structure.py")):
        src = (_ROOT.joinpath(*rel)).read_text()
        names = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                names.add(n.module.split(".")[0])
        assert not names & {"streamlit", "vob_minimal", "pandas", "requests"}, rel
        attrs = {a.attr for a in ast.walk(ast.parse(src))
                 if isinstance(a, ast.Attribute)}
        assert "session_state" not in attrs, rel


@pytest.mark.parametrize("junk", [None, "x", 7, [], (), {}, [None, None]])
def test_junk_never_raises(junk):
    assert PS.poc_line(junk, junk, junk) == [] or isinstance(
        PS.poc_line(junk, junk, junk), list)
    assert PS.lines(junk, junk, junk) == {}
    assert PS.stack(junk if isinstance(junk, dict) else {}, junk) == []
    assert PS.alignment(junk if isinstance(junk, (list, tuple)) else [])["n"] == 0
    assert isinstance(PC.table_html(junk if isinstance(junk, (list, tuple)) else []),
                      str)


def test_a_flat_series_does_not_raise_or_invent_a_move():
    hs = [100.0] * 60
    ls = [100.0] * 60
    got = PS.poc_line(hs, ls, [1.0] * 60, window=21)
    vals = [v for v in got if v is not None]
    assert vals and len(set(vals)) == 1


def test_the_html_escapes_what_it_is_given():
    html = PC.table_html([{"label": "<script>x</script>", "means": "y",
                           "poc": 100.0, "side": "ABOVE", "migrated": "UP"}])
    assert "<script>" not in html and "&lt;script&gt;" in html


# ── wiring ────────────────────────────────────────────────────────────

def test_the_curves_are_built_off_the_daily_history_stage_45_already_fetches():
    """⚠️ No second daily fetch. Stage 45 pulls 5 years of daily bars for its own
    profiles; a separate download for this panel would be a second source of truth
    for the same series, and a second network call per session."""
    src = (_ROOT / "vob_minimal.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_publish_poc_series")
    body = ast.get_source_segment(src, fn) or ""
    assert "_htf_daily_df" in body
    assert "yfinance" not in body and "download" not in body


def test_the_rolling_build_is_cached_not_run_every_rerun():
    """1,250 daily bars costs ~420 ms. At a 20 s refresh that is a permanent tax on
    every cycle for a series that changes once a day."""
    src = (_ROOT / "vob_minimal.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_poc_lines_cached")
    decs = []
    for d in fn.decorator_list:
        f = d.func if isinstance(d, ast.Call) else d
        decs.append(getattr(f, "attr", "") or getattr(f, "id", ""))
    assert "cache_data" in decs, decs


def test_the_spot_comes_from_the_one_owner():
    """⚠️ Four conflicting spot precedences across three files is what `spot.py` was
    built to end. A fifth read here would reopen it."""
    src = (_ROOT / "vob_minimal.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_publish_poc_series")
    body = ast.get_source_segment(src, fn) or ""
    assert "spot" in body and ".price(" in body


def test_the_panel_is_drawn_on_the_charts_tab():
    """⚠️ A renderer nothing calls is the bug this session keeps finding."""
    src = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_charts_screen")
    called = {c.func.id for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "_poc_structure" in called
    body = ast.get_source_segment(src, fn) or ""
    assert body.index("_strike_oi_charts") < body.index("_poc_structure")


def test_the_module_is_not_a_second_price_chart():
    """⚠️ `test_no_second_chart_was_created` globs `ui/*chart*.py` to keep
    `terminal_chart.py` the only price chart. This one is named `poc_structure` so
    that guard stays exactly as strict — and it draws no price series at all."""
    assert not list((_ROOT / "mios_v5" / "ui").glob("poc*chart*.py"))
    src = (_ROOT / "mios_v5" / "ui" / "poc_structure.py").read_text()
    assert "Candlestick" not in src and "add_candlestick" not in src


# ── the daily frame, which had one silent source ───────────────────────

def test_the_daily_history_has_two_sources_and_records_which_failed():
    """⚠️ REPORTED AS "not displayed in chart", and this was why. The daily frame
    came from ONE `yfinance` download inside `except Exception: pass`. When it
    failed there was no error, no caption and no frame — so Stage 45's Daily /
    Weekly / Monthly / Yearly profiles were never built, the stage still reported
    OK on its 1H and 4H profiles alone, and nothing on any screen said so. A silent
    single point of failure under the whole higher-timeframe layer.
    """
    src = (_ROOT / "vob_minimal.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "build_htf_profiles")
    body = ast.get_source_segment(src, fn) or ""
    assert "get_daily_data" in body, "Dhan is not tried for daily bars"
    assert "yfinance" in body, "the yfinance fallback was removed rather than kept"
    assert body.index("get_daily_data") < body.index("import yfinance"), \
        "Dhan should be tried first — the app is already authenticated with it"
    assert "_htf_daily_error" in body, "a failure must be recorded, not swallowed"


def test_dhan_owns_a_daily_endpoint_alongside_its_intraday_one():
    src = (_ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
               and n.name == "get_daily_data"), None)
    assert fn is not None, "no daily endpoint on the Dhan client"
    body = ast.get_source_segment(src, fn) or ""
    assert "charts/historical" in body
    # the daily sibling of the intraday call, framed the same way
    assert "fromDate" in body and "toDate" in body


def test_no_heading_or_provenance_caption_rides_above_the_curves():
    """⚠️ Both were removed on request. The chart legend names all four windows and
    the table carries its own column headers, so "Multi-window POC · daily · rolling"
    and "1242 daily bars · rolling POC per window (…)" restated what the picture
    already said. Asserted so neither creeps back, and so the `caption()` builder
    stays deleted rather than computed for nobody."""
    src = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_poc_structure")
    body = ast.get_source_segment(src, fn) or ""
    assert "Multi-window POC · daily · rolling" not in body
    assert 'd.get("caption")' not in body
    assert not hasattr(PS, "caption"), "the unused builder is still there"
    # the app must not compute it either
    app = (_ROOT / "vob_minimal.py").read_text()
    pub = next(n for n in ast.walk(ast.parse(app))
               if isinstance(n, ast.FunctionDef) and n.name == "_publish_poc_series")
    assert "caption" not in (ast.get_source_segment(app, pub) or "")


def test_the_absence_names_the_source_that_failed():
    """⚠️ "daily history not fetched yet" is the honest truth about the data and
    tells the reader nothing they can act on. The panel now names what each source
    said, and says the same frame is what Stage 45's slow profiles need."""
    src = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_poc_structure")
    body = ast.get_source_segment(src, fn) or ""
    assert "_htf_daily_error" in body
    # loud, not a caption: an absent higher-timeframe layer is not a footnote
    assert "st.warning" in body
    assert "Stage 45" in body
