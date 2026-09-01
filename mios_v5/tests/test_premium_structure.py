"""Premium Structure — the single premium-analysis orchestrator.

The audit (`docs/AUDIT_STAGE_71_8_PREMIUM_STRUCTURE.md`) found 18 of 23
requirements already existing, so most of these tests guard **reuse** rather
than arithmetic:

1. It computes nothing that already has an owner.
2. Everything it *does* compute is named in `COMPUTED_HERE` and justified by the
   audit.
3. It reads `detect_ignition`'s named sub-signals, not the leg table's glyph —
   the discard the audit called its headline finding.
"""

import ast
import pathlib

import pytest

from mios_v5 import premium_structure as PS


# ── fixtures ────────────────────────────────────────────────────────────

def _candles(n=40, vol=1000.0, last=None, wide_last=False, reject=False):
    out = []
    for i in range(n):
        base = 100.0 + i * 0.2
        hi, lo, cl = base + 1.0, base - 1.0, base + 0.4
        v = vol
        if i == n - 1:
            if last is not None:
                v = last
            if wide_last:
                hi, lo = base + 5.0, base - 5.0
            if reject:
                cl = lo + (hi - lo) * 0.1        # closed near the low
        out.append({"open": base, "high": hi, "low": lo, "close": cl,
                    "volume": v})
    return out


def _mfp(n=10, peak_at=3):
    rows = []
    for i in range(n):
        rows.append({"bin_low": 100.0 + i, "bin_high": 101.0 + i,
                     "total_volume": (5000.0 if i == peak_at else
                                      50.0 if i == n - 1 else 500.0)})
    return {"rows": rows, "poc_price": 100.0 + peak_at + 0.5}


def _analyse(**over):
    kw = dict(
        sr={"state": "BREAKING", "direction": "bull", "level": 118.0},
        vob=[{"mid": 112.0, "status": "BUILDING", "bull_pct": 70.0},
             {"mid": 124.0, "status": "INTACT", "bear_pct": 55.0}],
        vidya={"trend": "Uptrend", "delta_pct": 22.0, "cross_up": True},
        flow={"buy_total": 18.4e6, "sell_total": 8.6e6, "delta": 9.8e6},
        vpfr={"poc": 115.0, "vah": 122.0, "val": 108.0},
        mfp=_mfp(),
        ignition={"fired": True, "direction": "bull",
                  "signals": [{"name": "Accumulation Breakout",
                               "direction": "bull", "detail": "coiling"}],
                  "bull_count": 1, "bear_count": 0},
        candles=_candles(), absorb="bull", ltp=118.0)
    kw.update(over)
    return PS.analyse(**kw)


# ══════════════════════════════════════════════════════════════════════
#  1 · no duplicated calculations
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_no_calculation_engine():
    """The strongest form of "no duplicated logic": it *cannot* recompute what
    it consumes, because it does not import any of the producers."""
    tree = ast.parse(pathlib.Path(PS.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported |= {a.name for a in node.names}
    banned = {"indicators", "indicators.volume_order_blocks",
              "indicators.money_flow_profile", "indicators.order_flow",
              "indicators.triple_poc", "indicators.volume_delta",
              "VolumeOrderBlocks", "calculate_money_flow_profile",
              "calculate_vidya", "compute_vpfr", "TriplePOC", "numpy", "pandas"}
    assert not (imported & banned), f"imports a producer: {imported & banned}"


def test_it_writes_no_second_poc():
    """The audit found FOUR POC implementations and chose `compute_vpfr`. A
    fifth is the exact failure principle 1 exists to prevent."""
    src = pathlib.Path(PS.__file__).read_text()
    for banned in ("def _poc", "def compute_poc", "def calculate_poc",
                   "poc_price ="):
        assert banned not in src
    out = _analyse()
    assert out["vp_poc"] == 115.0                      # read from compute_vpfr
    assert out["profile"]["source"] == PS.CONSUMED["vp_poc"]


def test_it_writes_no_second_buy_fraction():
    """`indicators/order_flow.py` is the single owner of the CLV split."""
    src = pathlib.Path(PS.__file__).read_text()
    for banned in ("close - low", "(c - l)", "buy_fraction", "clv"):
        assert banned not in src.lower().replace("clv split", "")


def test_every_consumed_field_names_its_owner():
    """A read whose producer is unnamed is one refactor from becoming a
    computation nobody notices."""
    assert len(PS.CONSUMED) >= 12
    for key, owner in PS.CONSUMED.items():
        assert owner and "(" in owner or "." in owner, f"{key}: {owner!r}"


def test_computed_here_is_exactly_what_the_audit_justified():
    """Eight names, each argued for in §5 of the audit. Anything else appearing
    here is new computation that skipped the gate."""
    assert set(PS.COMPUTED_HERE) == {
        "hvn", "lvn", "rvol", "volume_climax",
        "break_probability", "fakeout_probability",
        "structure_score", "confidence"}


def test_the_audit_document_exists_and_covers_every_requirement():
    """Phase 1 was mandatory. If the audit goes, the justification goes."""
    doc = (pathlib.Path(PS.__file__).resolve().parents[1] / "docs" /
           "AUDIT_STAGE_71_8_PREMIUM_STRUCTURE.md")
    assert doc.exists()
    text = doc.read_text()
    for req in ("Premium Support", "Premium Resistance", "Premium HVN",
                "Premium LVN", "Premium POC", "Premium RVOL",
                "Volume Dry-up", "Volume Climax", "Buyer Absorption",
                "Breakout Probability", "Fakeout Probability",
                "Premium Structure Confidence"):
        assert req in text, f"{req} missing from the audit"


# ══════════════════════════════════════════════════════════════════════
#  2 · existing stages are reused
# ══════════════════════════════════════════════════════════════════════

def test_levels_come_from_the_legs_own_zones():
    out = _analyse()
    assert out["support"] == 112.0 and out["resistance"] == 124.0
    assert out["levels"]["source"] == PS.CONSUMED["support"]


def test_acceptance_is_the_legs_own_state_not_stage_42():
    """A CALL can reject its own resistance while NIFTY accepts above a level,
    and a trader holding that CALL needs the first one."""
    assert _analyse()["acceptance"] is True
    assert _analyse(sr={"state": "REJECTING", "direction": "bull"})["rejection"]


def test_trend_and_momentum_are_vidyas():
    out = _analyse()
    assert out["trend"] == "Uptrend"
    assert out["momentum"] == 22.0                      # VIDYA's own delta_pct
    assert out["trend_read"]["source"] == PS.CONSUMED["trend"]


def test_cbv_csv_cvd_are_read_from_order_flow_totals():
    out = _analyse()
    assert out["cbv"] == pytest.approx(18.4e6)
    assert out["csv"] == pytest.approx(8.6e6)
    assert out["cvd"] == pytest.approx(9.8e6)           # the totals' own delta
    assert out["flow"]["source"] == PS.CONSUMED["cbv"]


def test_absorption_is_read_not_re_measured():
    assert _analyse(absorb="bull")["absorption"]["buyer"] is True
    assert _analyse(absorb="bear")["absorption"]["seller"] is True
    assert _analyse(absorb=None)["absorption"]["label"] is None


def test_a_silent_producer_reports_unknown_rather_than_a_default():
    bare = PS.analyse()
    assert bare["trend"] == PS.UNKNOWN
    assert bare["acceptance"] == PS.UNKNOWN
    assert bare["support"] is None and bare["cbv"] is None
    assert bare["structure_score"] is None
    assert bare["ready"] is False


# ══════════════════════════════════════════════════════════════════════
#  3 · the headline finding — the glyph collapse
# ══════════════════════════════════════════════════════════════════════

def test_it_reads_ignitions_named_signals_not_the_glyph():
    """`build_leg_bias_table` reduces four named sub-signals to bull/bear/neu.
    Two of those names ARE the fakeout evidence."""
    out = _analyse(ignition={
        "fired": True, "direction": "bear",
        "signals": [{"name": "Wyckoff Upthrust", "direction": "bear",
                     "detail": "False break ₹124.0 + reject"}],
        "bull_count": 0, "bear_count": 1})
    assert out["ignition"]["wyckoff"] == ["Wyckoff Upthrust"]
    assert "Wyckoff Upthrust" in out["ignition"]["signals"]
    assert out["ignition"]["detail"]


def test_wyckoff_drives_the_fakeout_probability():
    """This is the requirement the audit found *computed and discarded*."""
    clean = _analyse()
    trap = _analyse(ignition={
        "fired": True, "direction": "bear",
        "signals": [{"name": "Wyckoff Spring", "direction": "bull"}],
        "bull_count": 1, "bear_count": 0})
    assert trap["fakeout_probability"] > (clean["fakeout_probability"] or 0)
    assert any("Wyckoff" in r for r in trap["probabilities"]["fakeout_reasons"])


# ══════════════════════════════════════════════════════════════════════
#  4 · the four computations, each justified
# ══════════════════════════════════════════════════════════════════════

def test_hvn_and_lvn_classify_the_profiles_own_bins():
    """The bins and their volumes exist; nothing labelled which are nodes."""
    out = _analyse(mfp=_mfp(n=10, peak_at=3))
    assert out["hvn"] and out["hvn"][0]["price"] == pytest.approx(103.5)
    assert out["lvn"]
    assert out["nodes"]["rows"] == 10


def test_node_thresholds_are_relative_to_the_bin_count():
    """Expressed against the even share, so they do not silently change meaning
    when the profile's resolution changes."""
    coarse = PS.classify_nodes(_mfp(n=5, peak_at=1))
    fine = PS.classify_nodes(_mfp(n=25, peak_at=1))
    assert coarse["even_share"] == pytest.approx(20.0)
    assert fine["even_share"] == pytest.approx(4.0)
    assert coarse["hvn"] and fine["hvn"]


def test_no_profile_gives_no_nodes_rather_than_empty_confidence():
    out = PS.classify_nodes(None)
    assert out["hvn"] == [] and out["lvn"] == []
    assert "no money-flow profile" in out["note"]


def test_rvol_compares_this_bar_against_the_recent_mean():
    out = PS.relative_volume(_candles(vol=1000.0, last=3000.0))
    assert out["rvol"] == pytest.approx(3.0)
    assert out["band"] == "climax"
    assert PS.relative_volume(_candles(vol=1000.0, last=300.0))["band"] == "dry"
    assert PS.relative_volume(_candles(vol=1000.0))["band"] == "normal"


def test_rvol_reports_unknown_rather_than_one_when_it_cannot_measure():
    assert PS.relative_volume(None)["rvol"] is None
    assert PS.relative_volume([])["band"] == PS.UNKNOWN


def test_volume_climax_needs_all_three_conditions():
    """Volume alone is participation — a high bar in a trend is the trend
    working. Climax is high volume PLUS a wide range PLUS a rejected extreme."""
    hot = _candles(vol=1000.0, last=4000.0, wide_last=True, reject=True)
    rv = PS.relative_volume(hot)
    assert PS.volume_climax(hot, rv)["climax"] is True

    # volume only — no wide range, no rejection
    plain = _candles(vol=1000.0, last=4000.0)
    assert PS.volume_climax(plain, PS.relative_volume(plain))["climax"] is False


def test_volume_climax_says_which_condition_was_missing():
    plain = _candles(vol=1000.0, last=4000.0)
    why = PS.volume_climax(plain, PS.relative_volume(plain))["why"]
    assert "missing" in why


def test_break_and_fakeout_are_scored_separately():
    """Both can be high at once: a break on climax volume with a Wyckoff
    upthrust is genuinely likely to go AND genuinely likely to fail."""
    out = _analyse(
        sr={"state": "BREAKING", "direction": "bull", "level": 118.0},
        candles=_candles(vol=1000.0, last=4000.0, wide_last=True, reject=True),
        ignition={"fired": True, "direction": "bear",
                  "signals": [{"name": "Wyckoff Upthrust", "direction": "bear"}],
                  "bull_count": 0, "bear_count": 1})
    assert out["break_probability"] is not None
    assert out["fakeout_probability"] is not None
    assert out["break_probability"] > 40 and out["fakeout_probability"] > 60


def test_a_break_on_dry_volume_raises_the_fakeout_read():
    dry = _analyse(candles=_candles(vol=1000.0, last=200.0))
    wet = _analyse(candles=_candles(vol=1000.0, last=2000.0))
    assert dry["fakeout_probability"] > (wet["fakeout_probability"] or 0)


# ══════════════════════════════════════════════════════════════════════
#  5 · the score
# ══════════════════════════════════════════════════════════════════════

def test_score_and_confidence_are_separate_readings():
    """A premium scoring 80 on two components and one scoring 80 on six are not
    the same finding, and one number cannot say both."""
    full = _analyse()
    thin = PS.analyse(sr={"state": "BREAKING", "direction": "bull"})
    assert full["confidence"] == "HIGH"
    assert thin["confidence"] == "LOW"
    assert full["score_read"]["reporting"] > thin["score_read"]["reporting"]


def test_a_high_fakeout_probability_caps_the_score():
    """Reliability is a statement ABOUT the structure, so it vetoes rather than
    averaging in — the shape Stage 71.7 uses for participation."""
    trap = _analyse(
        candles=_candles(vol=1000.0, last=4000.0, wide_last=True, reject=True),
        ignition={"fired": True, "direction": "bear",
                  "signals": [{"name": "Wyckoff Upthrust", "direction": "bear"}],
                  "bull_count": 0, "bear_count": 1})
    assert trap["score_read"]["capped_at"] is not None
    assert trap["structure_score"] <= trap["score_read"]["capped_at"]


def test_top_reasons_are_machine_readable_and_capped():
    reasons = _analyse()["top_reasons"]
    assert 0 < len(reasons) <= 5
    for r in reasons:
        assert set(r) >= {"code", "label", "weight"}
        assert " " not in r["code"]


# ══════════════════════════════════════════════════════════════════════
#  6 · the architectural standing
# ══════════════════════════════════════════════════════════════════════

def test_it_is_advisory_only_and_not_an_engine():
    from mios_v5.engines import ALL_ENGINES
    assert PS.ADVISORY_ONLY is True
    assert _analyse()["advisory_only"] is True
    names = {c().name for c in ALL_ENGINES} | {c.__name__ for c in ALL_ENGINES}
    assert not any("premium_structure" in str(n).lower() for n in names)


def test_it_touches_no_streamlit_and_no_session_state():
    tree = ast.parse(pathlib.Path(PS.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr != "session_state"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            names = {a.name for a in node.names}
            assert "streamlit" not in mod and "streamlit" not in names


def test_it_exposes_no_mutator():
    for name in dir(PS):
        if name.startswith("_"):
            continue
        assert not name.startswith(("apply", "deploy", "promote", "set_",
                                    "update_", "override"))


def test_it_never_raises_on_junk():
    for junk in ({}, {"sr": "nonsense"}, {"vob": "not a list"},
                 {"candles": [None, 1, "x"]}, {"mfp": {"rows": "bad"}},
                 {"flow": {"buy_total": "x"}}):
        assert isinstance(PS.analyse(**junk), dict)
