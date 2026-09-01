"""Stage 71 — the Trade Opportunity Matrix.

The load-bearing test is `test_a_thin_horizon_cannot_beat_a_broad_one_on_the
_same_agreement`: it is the entire reason the score is a Wilson lower bound
rather than raw agreement, and if it ever passes trivially the ranking has
stopped meaning anything.
"""

import pytest

from mios_v5 import opportunity as OP
from mios_v5.horizon_owner import (DEGRADED, HORIZONS, HTF_TIMEFRAME,
                                   NATIVE_LABEL, OWNED, Horizon, owners_of)


# ── fixtures ────────────────────────────────────────────────────────────

def _fr(**over):
    """A final read with stable, non-shifting foundations."""
    fr = {
        "preferred_bias": "BEAR", "confidence_tempered": 71,
        "stability": "STABLE",
        "flow_shift": {"freeze_entries": False, "score": 8},
        "transition": {"state": "STABLE", "label": "stable"},
        "memory_read": {"state": "EXPANSION", "state_duration_min": 42,
                        "state_mature": True, "state_transition_risk": 18},
        "engine_bias": {}, "htf": {"reads": {}},
    }
    fr.update(over)
    return fr


def _fill(horizon, bias, n=None):
    """`native_reads` filling n of a horizon's owned producers with `bias`."""
    owned = owners_of(horizon)
    picked = owned if n is None else owned[:n]
    return {p: {"bias": bias, "confidence": 80, "label": p} for p in picked}


def _engine_bias(mapping):
    return {pid: {"bias": b, "confidence": 80, "status": "OK", "headline": pid}
            for pid, b in mapping.items()}


# ── the shape of the thing ──────────────────────────────────────────────

def test_matrix_has_one_row_per_horizon_in_order():
    m = OP.build_matrix(_fr())
    assert [r["horizon"] for r in m["rows"]] == [h.value for h in HORIZONS]


def test_empty_input_never_raises():
    for arg in (None, {}, {"engine_bias": None}):
        m = OP.build_matrix(arg)
        assert len(m["rows"]) == len(HORIZONS)
        assert m["best"] is None


def test_matrix_is_advisory_only():
    m = OP.build_matrix(_fr())
    assert m["advisory_only"] is True
    assert all(r["advisory_only"] is True for r in m["rows"])


def test_module_exposes_no_mutators():
    """Stage 71 orchestrates. It may never decide, apply or promote."""
    for banned in ("decide", "apply", "promote", "deploy", "set_weight",
                   "set_threshold", "enter", "exit_trade"):
        assert not hasattr(OP, banned), f"opportunity.{banned}"


def test_stage_71_is_not_a_registered_engine():
    """Like Stage 70: numbered for humans, absent from the pipeline."""
    from mios_v5.engines import ALL_ENGINES
    names = {c().name for c in ALL_ENGINES}
    assert not any("opportunity" in n or n.startswith("stage71") for n in names)


# ── the Wilson ranking — the reason this design exists ──────────────────

def test_a_thin_horizon_cannot_beat_a_broad_one_on_the_same_agreement():
    """swing owns 5 producers, scalp owns 22. At the SAME agreement fraction
    the broad horizon must score higher, or the matrix is just rewarding
    whichever horizon happens to have most reporters."""
    native = {}
    native.update(_fill(Horizon.SCALP, "BULL"))          # all 22 agree
    m = OP.build_matrix(_fr(), native)
    scalp = next(r for r in m["rows"] if r["horizon"] == "scalp")

    native2 = _fill(Horizon.SWING, "BULL")               # all 5 agree
    m2 = OP.build_matrix(_fr(), native2)
    swing = next(r for r in m2["rows"] if r["horizon"] == "swing")

    assert scalp["confidence"] == swing["confidence"] == 100.0
    assert scalp["score"] > swing["score"], (
        f"scalp {scalp['score']} must beat swing {swing['score']} at equal "
        "agreement — Wilson must penalise the small sample")


def test_score_is_never_above_raw_confidence():
    """A lower bound that exceeded the point estimate would be a sign error."""
    native = _fill(Horizon.SCALP, "BEAR")
    m = OP.build_matrix(_fr(), native)
    for r in m["rows"]:
        if r.get("score"):
            assert r["score"] <= r["confidence"] + 1e-9


def test_partial_coverage_lowers_the_score():
    full = OP.build_matrix(_fr(), _fill(Horizon.SCALP, "BULL"))
    half = OP.build_matrix(_fr(), _fill(Horizon.SCALP, "BULL", n=11))
    a = next(r for r in full["rows"] if r["horizon"] == "scalp")
    b = next(r for r in half["rows"] if r["horizon"] == "scalp")
    assert b["score"] < a["score"]
    assert b["coverage"] < a["coverage"]


def test_split_evidence_scores_below_unanimous():
    owned = owners_of(Horizon.SCALP)
    split = {p: {"bias": "BULL" if i % 2 else "BEAR", "confidence": 80}
             for i, p in enumerate(owned)}
    m = OP.build_matrix(_fr(), split)
    r = next(x for x in m["rows"] if x["horizon"] == "scalp")
    assert r["confidence"] < 60
    assert any("split evidence" in s for s in r["lost_because"])


# ── the swing rule ──────────────────────────────────────────────────────

def test_swing_never_returns_a_side():
    """Not `None` — ABSENT, so no renderer can print it by accident."""
    for bias in ("BULL", "BEAR"):
        m = OP.build_matrix(_fr(), _fill(Horizon.SWING, bias))
        swing = next(r for r in m["rows"] if r["horizon"] == "swing")
        assert "side" not in swing
        assert "Structure" in swing["verdict"]
        assert swing["no_option_side"]


def test_swing_is_never_ranked():
    m = OP.build_matrix(_fr(), _fill(Horizon.SWING, "BULL"))
    assert "swing" not in m["ranked"]
    assert m["best"] != "swing"


def test_swing_still_reports_a_direction():
    """No side is not no opinion — structure still leans."""
    m = OP.build_matrix(_fr(), _fill(Horizon.SWING, "BEAR"))
    swing = next(r for r in m["rows"] if r["horizon"] == "swing")
    assert swing["bias"] == "BEAR"
    assert swing["verdict"] == "Bearish Structure"


def test_positional_declares_it_is_degraded():
    m = OP.build_matrix(_fr(), _fill(Horizon.POSITIONAL, "BULL"))
    pos = next(r for r in m["rows"] if r["horizon"] == "positional")
    assert pos["degraded"] == DEGRADED[Horizon.POSITIONAL]


# ── Stage 44, per horizon ───────────────────────────────────────────────

def _shifted():
    return _fr(flow_shift={"freeze_entries": True, "score": 88},
               stability="SHOCK")


def test_flow_shift_vetoes_scalp_and_midday():
    for h in (Horizon.SCALP, Horizon.MIDDAY):
        m = OP.build_matrix(_shifted(), _fill(h, "BULL"))
        row = next(r for r in m["rows"] if r["horizon"] == h.value)
        assert row["veto"] is True
        assert row["score"] == 0.0
        assert any("veto" in s for s in row["lost_because"])


def test_flow_shift_only_discounts_intraday():
    calm = OP.build_matrix(_fr(), _fill(Horizon.INTRADAY, "BULL"))
    shk = OP.build_matrix(_shifted(), _fill(Horizon.INTRADAY, "BULL"))
    a = next(r for r in calm["rows"] if r["horizon"] == "intraday")
    b = next(r for r in shk["rows"] if r["horizon"] == "intraday")
    assert b["veto"] is False
    assert 0 < b["score"] < a["score"]


def test_flow_shift_leaves_positional_and_swing_alone():
    """A shift can BE the swing thesis — it must not veto the slow horizons."""
    for h in (Horizon.POSITIONAL, Horizon.SWING):
        m = OP.build_matrix(_shifted(), _fill(h, "BEAR"))
        row = next(r for r in m["rows"] if r["horizon"] == h.value)
        assert row["veto"] is False
        assert row["flow_shift_effect"] is None


def test_a_vetoed_horizon_cannot_be_ranked_best():
    native = {}
    native.update(_fill(Horizon.SCALP, "BULL"))
    native.update(_fill(Horizon.INTRADAY, "BEAR"))
    m = OP.build_matrix(_shifted(), native)
    assert m["best"] != "scalp"


# ── stability, explained rather than asserted ───────────────────────────

def test_stability_names_the_stage_behind_every_part():
    s = OP.stability(_fr())
    assert {p["stage"] for p in s["parts"]} <= {44, 47, 54}
    assert all(p["label"] and str(p["value"]) for p in s["parts"])


def test_stability_reports_held_minutes_and_transition_risk():
    s = OP.stability(_fr())
    joined = s["sentence"]
    assert "42 min" in joined and "18%" in joined


def test_a_frozen_tape_is_low_stability():
    assert OP.stability(_shifted())["band"] == "Low"


def test_reversing_bias_costs_more_than_weakening():
    weak = OP.stability(_fr(transition={"state": "WEAKENING"}))
    rev = OP.stability(_fr(transition={"state": "REVERSING"}))
    assert rev["score"] < weak["score"]


def test_a_fresh_state_scores_below_a_mature_one():
    fresh = OP.stability(_fr(memory_read={"state_fresh": True,
                                          "state_duration_min": 2,
                                          "state_transition_risk": 20}))
    mature = OP.stability(_fr())
    assert fresh["score"] < mature["score"]


def test_stability_never_carries_a_direction():
    """44/47/54 shape trust, never side. A bias key here would be the
    double-count v6_bias already refused."""
    s = OP.stability(_fr())
    assert "bias" not in s and "side" not in s


# ── abstention is not a vote ────────────────────────────────────────────

def test_a_horizon_with_nothing_reporting_says_so():
    m = OP.build_matrix(_fr())
    for r in m["rows"]:
        assert r["verdict"] == "NO READ"
        assert r["score"] == 0.0
        assert r["lost_because"]


def test_all_neutral_is_reported_as_no_read_not_as_a_side():
    m = OP.build_matrix(_fr(), _fill(Horizon.SCALP, "NEUTRAL"))
    r = next(x for x in m["rows"] if x["horizon"] == "scalp")
    assert r["verdict"] == "NO READ"
    assert "side" not in r


def test_a_disabled_or_errored_engine_does_not_count_as_reporting():
    fr = _fr(engine_bias=_engine_bias({"stage42_acceptance": "BULL"}))
    fr["engine_bias"]["stage43_absorption"] = {
        "bias": "BULL", "confidence": 90, "status": "DISABLED"}
    m = OP.build_matrix(fr)
    r = next(x for x in m["rows"] if x["horizon"] == "scalp")
    assert r["reporting"] == 1


def test_non_owned_native_reads_are_ignored():
    """An excluded or aggregate id handed in must not sneak into a vote."""
    m = OP.build_matrix(_fr(), {"native_news_bias": {"bias": "BULL"},
                                "native_master_signal": {"bias": "BULL"}})
    assert all(r["reporting"] == 0 for r in m["rows"])


# ── sources wire up to the real final_read shape ────────────────────────

def test_engine_bias_map_is_read():
    fr = _fr(engine_bias=_engine_bias({"stage42_acceptance": "BEAR",
                                       "stage50_ltp_behaviour": "BEAR"}))
    m = OP.build_matrix(fr)
    r = next(x for x in m["rows"] if x["horizon"] == "scalp")
    assert r["reporting"] == 2 and r["side"] == "PUT"


def test_htf_reads_are_read_per_timeframe():
    fr = _fr(htf={"reads": {tf: {"bias": "BULL", "confidence": 70,
                                 "status": "OK"}
                            for tf in HTF_TIMEFRAME.values()}})
    m = OP.build_matrix(fr)
    by = {r["horizon"]: r for r in m["rows"]}
    assert by["midday"]["reporting"] >= 1      # htf_1h
    assert by["swing"]["reporting"] >= 2       # monthly + yearly


def test_final_read_actually_publishes_engine_bias():
    """The one final_read addition this module depends on."""
    import inspect
    from mios_v5 import final_read as FR
    assert '"engine_bias"' in inspect.getsource(FR.build_final_read)


# ── reference and excluded ──────────────────────────────────────────────

def test_reference_shows_the_v5_headline_and_never_votes():
    m = OP.build_matrix(_fr())
    ids = [x["id"] for x in m["reference"]]
    assert "v5_preferred_bias" in ids
    assert all(x["voting"] is False for x in m["reference"])


def test_aggregates_appear_in_reference_not_in_any_horizon():
    fr = _fr(engine_bias=_engine_bias({"stage27_conflict": "BEAR"}))
    m = OP.build_matrix(fr)
    assert any(x["id"] == "stage27_conflict" for x in m["reference"])
    assert all(r["reporting"] == 0 for r in m["rows"])


def test_excluded_lists_every_excluded_and_aggregate_with_a_reason():
    from mios_v5.horizon_owner import AGGREGATE, EXCLUDED
    ex = OP.build_matrix(_fr())["excluded"]
    assert len(ex) == len(EXCLUDED) + len(AGGREGATE)
    assert all(x["reason"].strip() for x in ex)


# ── ranking explains itself ─────────────────────────────────────────────

def test_the_runner_up_is_told_why_it_lost():
    native = {}
    native.update(_fill(Horizon.SCALP, "BULL"))
    native.update(_fill(Horizon.POSITIONAL, "BEAR"))
    m = OP.build_matrix(_fr(), native)
    assert len(m["ranked"]) >= 2
    second = next(r for r in m["rows"] if r["horizon"] == m["ranked"][1])
    assert second["lost_because"]
    assert any(m["ranked"][0] in s for s in second["lost_because"])


def test_ranks_are_dense_and_start_at_one():
    native = {}
    native.update(_fill(Horizon.SCALP, "BULL"))
    native.update(_fill(Horizon.MIDDAY, "BULL"))
    m = OP.build_matrix(_fr(), native)
    ranks = sorted(r["rank"] for r in m["rows"] if "rank" in r)
    assert ranks == list(range(1, len(ranks) + 1))


def test_display_order_is_rank_order_with_swing_last():
    """Rendering `rows` as-is puts 🥉 above 🥈 whenever a slower horizon
    outranks a faster one. `display_order` is the panel's iteration order."""
    native = {}
    native.update(_fill(Horizon.MIDDAY, "BULL", n=7))
    native.update(_fill(Horizon.INTRADAY, "BULL"))       # broader → outranks
    native.update(_fill(Horizon.SWING, "BULL"))
    m = OP.build_matrix(_fr(), native)

    assert set(m["display_order"]) == {h.value for h in HORIZONS}
    assert m["display_order"][-1] == "swing"
    # every ranked horizon appears, in rank order, before the unranked ones
    ranked_positions = [m["display_order"].index(h) for h in m["ranked"]]
    assert ranked_positions == sorted(ranked_positions)
    assert m["display_order"][0] == m["ranked"][0] == m["best"]


def test_display_order_holds_when_nothing_is_ranked():
    m = OP.build_matrix(_fr())
    assert set(m["display_order"]) == {h.value for h in HORIZONS}
    assert m["display_order"][-1] == "swing"


def test_winning_reasons_name_real_producers():
    m = OP.build_matrix(_fr(), _fill(Horizon.SCALP, "BULL"))
    r = next(x for x in m["rows"] if x["horizon"] == "scalp")
    assert r["reasons"]
    assert all(x in OWNED or x in NATIVE_LABEL.values() for x in r["reasons"])


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"opportunity matrix tests passed ({len(fns)})")
