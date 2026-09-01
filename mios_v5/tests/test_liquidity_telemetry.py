"""Stage 74 telemetry — measuring the calibration before anything depends on it.

The verdict logic is what these guard hardest, and for a specific reason: this
module's own simulation returned `HEALTHY` for a distribution with 44% in
`20-40` and 54% in `40-60`. No single bucket crossed the peak threshold, so a
peak-share test called it discriminating — while 98% of clusters sat inside a
40-point band separating almost nothing. Flatness is about spread, and spread
has to be measured directly.
"""

import ast
import pathlib

import pytest

from mios_v5 import liquidity as LQ
from mios_v5 import liquidity_context as LC
from mios_v5 import liquidity_telemetry as LT

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _hist(**kw):
    h = {k: 0 for k in LT.BUCKET_LABELS}
    h.update(kw)
    return h


def _rows(hist, engines=None, n=1, day="2026-08-03"):
    eng = engines or {"3": sum(hist.values())}
    return [{"confidence_hist": hist, "engines_hist": eng,
             "trading_day": day, "clusters": sum(hist.values()),
             "confidence_unscored": 0} for _ in range(n)]


# ══════════════════════════════════════════════════════════════════════
#  the verdict — every miscalibration shape
# ══════════════════════════════════════════════════════════════════════

def test_two_adjacent_buckets_holding_everything_is_flat():
    """The bug this module's own simulation caught. Neither bucket crosses the
    peak threshold, and 98% of clusters sit inside a 40-point band."""
    got = LT._verdict(_hist(**{"0-20": 65, "20-40": 4087, "40-60": 5029,
                               "60-80": 116}), {"3": 9297})
    assert got["verdict"] == LT.TOO_FLAT
    assert got["buckets_reached"] == 2
    assert got["peak_share"] < LT._FLAT_SHARE, "no single bucket is dominant"


def test_one_dominant_bucket_is_flat():
    got = LT._verdict(_hist(**{"40-60": 9000, "20-40": 500, "60-80": 500}),
                      {"3": 10000})
    assert got["verdict"] == LT.TOO_FLAT


def test_everything_high_is_too_generous():
    """Calling almost everything high-confidence is the same as calling nothing
    high-confidence."""
    got = LT._verdict(_hist(**{"80-100": 8000, "60-80": 2000}), {"5": 10000})
    assert got["verdict"] == LT.TOO_GENEROUS
    assert "lower the diversity anchors" in got["advice"]


def test_everything_low_is_too_harsh():
    """A consumer gating at 70 would never fire."""
    got = LT._verdict(_hist(**{"0-20": 5000, "20-40": 4000, "40-60": 1000}),
                      {"2": 10000})
    assert got["verdict"] == LT.TOO_HARSH
    assert "raise the diversity anchors" in got["advice"]


def test_a_genuine_spread_is_healthy():
    got = LT._verdict(_hist(**{"0-20": 900, "20-40": 2200, "40-60": 3000,
                               "60-80": 2400, "80-100": 1500}), {"3": 10000})
    assert got["verdict"] == LT.HEALTHY
    assert got["buckets_reached"] == 5
    assert "freeze it" in got["advice"]


def test_a_skew_is_diagnosed_before_flatness():
    """Generous and harsh are specific diagnoses with specific fixes. A pile at
    one end is flat AND skewed, and naming only the flatness sends someone to
    the wrong constant."""
    got = LT._verdict(_hist(**{"80-100": 9500, "60-80": 500}), {"6+": 10000})
    assert got["verdict"] == LT.TOO_GENEROUS


def test_too_few_clusters_is_insufficient_not_a_guess():
    got = LT._verdict(_hist(**{"40-60": 10}), {"2": 10})
    assert got["verdict"] == LT.INSUFFICIENT
    assert got["confident"] is False
    assert str(LT.MIN_CLUSTERS) in got["why"]


def test_thin_clusters_redirect_the_advice_upstream():
    """If almost every cluster has two engines, the ceiling curve decides very
    little and a steeper curve is the wrong fix."""
    got = LT._verdict(_hist(**{"20-40": 5000, "40-60": 5000}),
                      {"1": 4000, "2": 5000, "3": 1000})
    assert got["thin_clusters"] is True
    assert "Wire more level sources" in got["advice"]


def test_a_healthy_verdict_is_not_second_guessed_by_thin_clusters():
    """If the curve discriminates, it discriminates — the thin-cluster note is
    guidance for retuning, not a reason to withhold a good verdict."""
    got = LT._verdict(_hist(**{"0-20": 900, "20-40": 2200, "40-60": 3000,
                               "60-80": 2400, "80-100": 1500}),
                      {"1": 5000, "2": 5000})
    assert got["verdict"] == LT.HEALTHY
    assert "freeze it" in got["advice"]


# ══════════════════════════════════════════════════════════════════════
#  sampling
# ══════════════════════════════════════════════════════════════════════

def _live_liq(**over):
    prof = {"rows": [{"bin_low": 23900.0, "bin_high": 23920.0,
                      "total_volume": 1000, "bull_volume": 700,
                      "bear_volume": 300, "delta": 400, "ratio": 1.0,
                      "node_type": "High", "sentiment": "Bullish"}],
            "poc_price": 23960.0, "value_area_high": 24000.0,
            "value_area_low": 23920.0, "price_high": 24020.0,
            "price_low": 23880.0}
    kw = dict(profile=prof, vpfr={"poc": 23962.0}, dynamic_poc=[23950, 23960],
              dealer={"gamma_flip": 23961.0}, spot=23900.0, atr=25.0,
              previous=prof)
    kw.update(over)
    return LC.build(**kw).meta["engine_output"]


def test_a_sample_histograms_every_cluster():
    row = LT.sample(liq=_live_liq(), reaction={"state": "ACCEPTANCE"},
                    atr=25.0, trading_day="2026-08-03")
    assert sum(row["confidence_hist"].values()) == row["confidence_scored"]
    assert row["clusters"] >= 1
    assert row["reaction"] == "ACCEPTANCE"


def test_a_sample_records_the_context_the_calibration_is_read_against():
    row = LT.sample(liq=_live_liq(), atr=25.0)
    for field in ("poc_regime", "poc_trend", "liquidity_shift", "dominance",
                  "divergence", "tolerance_pct", "atr", "engines_mean"):
        assert field in row, field


def test_an_unscored_cluster_is_counted_apart_not_as_low_confidence():
    """Folding it in would drag the distribution toward TOO_HARSH for a reason
    that has nothing to do with the curve."""
    fake = {"levels": {"support": ({"confidence": LQ.UNKNOWN, "diversity": 2},),
                       "resistance": ({"confidence": 80, "diversity": 5},)}}
    row = LT.sample(liq=fake)
    assert row["confidence_unscored"] == 1
    assert row["confidence_scored"] == 1
    assert row["confidence_hist"]["80-100"] == 1


def test_sampling_accepts_a_level_object_and_a_stored_dict():
    """A replayed row must histogram the same as a live one."""
    level = LQ.Level(price=1.0, side=LQ.SUPPORT, rank=LQ.MINOR, confidence=82,
                     witness_count=5, engine_sources=("a", "b", "c", "d", "e"),
                     kinds=("POC",), dispersion=0.0, dispersion_pct=0.0,
                     freshness=LQ.UNKNOWN, low=1.0, high=1.0, reporting=2, of=4)
    live = LT.sample(liq={"levels": {"support": (level,)}})
    stored = LT.sample(liq={"levels": {"support": (level.to_dict(),)}})
    assert live["confidence_hist"] == stored["confidence_hist"]
    assert live["engines_hist"] == stored["engines_hist"]


def test_a_degraded_cycle_records_a_thin_row_rather_than_nothing():
    """"The engine produced nothing at 14:32" is exactly what a week of
    telemetry should show."""
    for junk in (None, {}, "a string", [], 0):
        row = LT.sample(liq=junk)
        assert isinstance(row, dict) and row["clusters"] == 0
        assert row["ready"] is False


@pytest.mark.parametrize("value,label", [
    (0, "0-20"), (19.9, "0-20"), (20, "20-40"), (45, "40-60"),
    (79, "60-80"), (80, "80-100"), (100, "80-100"),
])
def test_bucket_boundaries_are_half_open_and_include_one_hundred(value, label):
    assert LT.bucket_of(value) == label


def test_an_unknown_confidence_has_no_bucket():
    assert LT.bucket_of(LQ.UNKNOWN) is None
    assert LT.bucket_of(None) is None


# ══════════════════════════════════════════════════════════════════════
#  the week
# ══════════════════════════════════════════════════════════════════════

def test_a_summary_reports_counts_as_well_as_shares():
    """A share alone hides how much was measured — eleven clusters and eleven
    thousand look identical once normalised."""
    s = LT.summarise(_rows(_hist(**{"40-60": 100}), n=3))
    assert s["confidence"]["counts"]["40-60"] == 300
    assert s["confidence"]["shares"]["40-60"] == 1.0
    assert s["clusters"] == 300


def test_a_summary_counts_distinct_sessions():
    rows = (_rows(_hist(**{"40-60": 50}), n=2, day="2026-08-03")
            + _rows(_hist(**{"60-80": 50}), n=2, day="2026-08-04"))
    assert LT.summarise(rows)["days"] == 2


def test_an_empty_week_is_insufficient():
    s = LT.summarise([])
    assert s["verdict"] == LT.INSUFFICIENT and s["samples"] == 0


def test_the_summary_survives_junk_rows():
    assert LT.summarise(["nonsense", None, 42])["samples"] == 3


# ══════════════════════════════════════════════════════════════════════
#  the freeze gate
# ══════════════════════════════════════════════════════════════════════

def test_a_week_is_required_not_just_a_pile_of_clusters():
    """One volatile session produces thousands of clusters and says how the
    curve behaves on a volatile session. A week says whether it survives a
    quiet Tuesday and an expiry Thursday."""
    one_day = LT.summarise(_rows(_hist(**{"0-20": 900, "20-40": 2200,
                                          "40-60": 3000, "60-80": 2400,
                                          "80-100": 1500}), n=1))
    got = LT.ready_to_freeze(one_day)
    assert got["ready"] is False
    assert any("trading days" in b for b in got["blockers"])


def test_a_bad_verdict_blocks_the_freeze():
    rows = []
    for day in range(5):
        rows += _rows(_hist(**{"40-60": 500}), n=1, day=f"2026-08-0{day + 3}")
    got = LT.ready_to_freeze(LT.summarise(rows))
    assert got["ready"] is False
    assert any("TOO_FLAT" in b for b in got["blockers"])


def test_a_healthy_week_clears_the_gate():
    rows = []
    for day in range(5):
        rows += _rows(_hist(**{"0-20": 90, "20-40": 220, "40-60": 300,
                               "60-80": 240, "80-100": 150}),
                      n=1, day=f"2026-08-0{day + 3}")
    got = LT.ready_to_freeze(LT.summarise(rows))
    assert got["ready"] is True and not got["blockers"]


def test_the_freeze_gate_survives_nothing():
    assert LT.ready_to_freeze(None)["ready"] is False


# ══════════════════════════════════════════════════════════════════════
#  it observes, it never tunes
# ══════════════════════════════════════════════════════════════════════

def test_it_never_writes_a_calibration_constant():
    """A calibration that retunes itself from its own output is a feedback loop
    nobody can audit."""
    src = (ROOT / "mios_v5" / "liquidity_telemetry.py").read_text()
    for constant in ("_DIVERSITY_ANCHORS", "_ATR_MULTIPLE", "_QUALITY_WEIGHTS",
                     "_CLUSTER_FLOOR_POINTS", "_POC_MOVE_PCT"):
        assert constant not in src, constant


def test_it_is_pure_no_database_no_clock_no_streamlit():
    tree = ast.parse((ROOT / "mios_v5" / "liquidity_telemetry.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"streamlit", "db", "datetime", "time", "random",
                            "numpy", "pandas", "requests"})


def test_it_is_advisory_only():
    assert LT.ADVISORY_ONLY is True


def test_the_same_rows_always_give_the_same_verdict():
    rows = _rows(_hist(**{"20-40": 400, "40-60": 400, "60-80": 400}), n=4)
    first = LT.summarise(rows)
    for _ in range(5):
        assert LT.summarise(rows) == first


# ══════════════════════════════════════════════════════════════════════
#  storage, retention and wiring
# ══════════════════════════════════════════════════════════════════════

def test_the_table_exists_and_keeps_the_unscored_count_separate():
    sql = (ROOT / "sql" / "036_liquidity_telemetry.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS liquidity_telemetry" in sql
    assert "confidence_unscored" in sql
    assert "uniq_liq_telemetry_ts" in sql


def test_the_new_table_has_a_retention_policy():
    """Every other table in this schema grew forever because nobody set one."""
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "_rt_for_telemetry", ROOT / "db" / "retention.py")
    rt = importlib.util.module_from_spec(spec)
    sys.modules["_rt_for_telemetry"] = rt
    spec.loader.exec_module(rt)
    assert "liquidity_telemetry" in rt.POLICIES
    assert rt.POLICIES["liquidity_telemetry"].keep_days == 180


def test_the_app_samples_once_a_minute_not_once_per_rerun():
    """A distribution needs coverage across sessions, not three samples of the
    same cluster set."""
    src = (ROOT / "vob_minimal.py").read_text()
    assert "_liq_telemetry_ts" in src
    assert "> 60" in src
    assert "insert_liquidity_telemetry" in src


def test_the_read_is_cached_and_a_write_invalidates_it():
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "_rc_for_telemetry", ROOT / "db" / "read_cache.py")
    rc = importlib.util.module_from_spec(spec)
    sys.modules["_rc_for_telemetry"] = rc
    spec.loader.exec_module(rc)
    assert "get_liquidity_telemetry" in rc._READS
    assert "get_liquidity_telemetry" in rc._INVALIDATES["insert_liquidity_telemetry"]


def test_the_engine_output_is_carried_so_nothing_recomputes_it():
    """The telemetry histograms every cluster, not the handful the contract
    exposes — and running the engine twice to get the same answer is what the
    context exists to prevent."""
    ctx = LC.build(profile={"rows": [], "poc_price": 1.0}, spot=1.0)
    assert "engine_output" in ctx.meta


def test_the_verdict_is_on_screen():
    panel = (ROOT / "mios_v5" / "ui" / "liquidity_panel.py").read_text()
    assert "def calibration_html" in panel
    dash = (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    assert "render_calibration" in dash


def test_the_panel_draws_the_distribution_not_just_the_word():
    """A verdict word is an opinion; the shape underneath it is the evidence."""
    from mios_v5.ui import liquidity_panel as P
    s = LT.summarise(_rows(_hist(**{"0-20": 90, "20-40": 220, "40-60": 300,
                                    "60-80": 240, "80-100": 150}), n=5))
    html = P.calibration_html(s)
    for label in LT.BUCKET_LABELS:
        assert label in html
    assert "HEALTHY" in html


def test_the_calibration_panel_says_nothing_before_there_is_anything_to_say():
    from mios_v5.ui import liquidity_panel as P
    assert P.calibration_html(None) == ""
    assert P.calibration_html({}) == ""


# ══════════════════════════════════════════════════════════════════════
#  collection status — the failure that is otherwise invisible
# ══════════════════════════════════════════════════════════════════════

def test_a_missing_migration_is_loud_not_silent():
    """The write is per-minute and best-effort, so a missing sql/036 means it
    fails silently every cycle and a week of "collecting" produces zero rows —
    discoverable only by going to look, a week later, having lost the week."""
    from mios_v5.ui import liquidity_panel as P
    html = P.collection_html({
        "ok": False, "wrote": 0,
        "error": 'relation "liquidity_telemetry" does not exist'})
    assert "NOT being collected" in html
    assert "sql/036_liquidity_telemetry.sql" in html


def test_a_write_failure_that_is_not_a_missing_table_still_reports():
    from mios_v5.ui import liquidity_panel as P
    html = P.collection_html({"ok": False, "wrote": 0,
                              "error": "connection reset by peer"})
    assert "NOT being collected" in html
    assert "connection reset" in html


def test_never_having_written_is_flagged_rather_than_assumed_fine():
    from mios_v5.ui import liquidity_panel as P
    html = P.collection_html(None)
    assert "has not written yet" in html


def test_healthy_collection_confirms_briefly_then_goes_quiet():
    """Loud about the broken case, absent otherwise — a permanent green badge
    is noise a reader learns to skip past."""
    from mios_v5.ui import liquidity_panel as P
    assert "Collecting" in P.collection_html({"ok": True, "wrote": 1})
    assert P.collection_html({"ok": True, "wrote": 40}) == ""


def test_the_write_failure_is_captured_not_swallowed():
    src = (ROOT / "vob_minimal.py").read_text()
    # Anchor on the section, not on a key that appears twice inside it.
    block = (src.split("Stage 74 telemetry")[1]
                .split("except Exception as _liq_err")[0])
    assert "_liq_telemetry_status" in block, "the outcome is not recorded"
    assert "except Exception as _tel_err" in block, "the error is swallowed"


def test_the_status_reaches_the_dashboard():
    src = (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    assert "render_collection" in src
    assert "_liq_telemetry_status" in src


def test_the_status_panel_never_raises():
    from mios_v5.ui import liquidity_panel as P
    for junk in (None, {}, "a string", 42, {"ok": "maybe"}, {"error": None}):
        P.collection_html(junk)
