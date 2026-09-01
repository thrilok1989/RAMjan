"""Stage 71 — the tests that keep the Horizon Ownership Registry honest.

These are the contract. Everything in `opportunity.py` depends on them holding,
so they are written first and must be green before a line of orchestration
exists.

The load-bearing one is `test_every_producer_has_exactly_one_home`: it walks
the LIVE `ALL_ENGINES` roster and the LIVE `_BIAS_CATEGORY` table and fails the
build if any producer is missing from the registry. That is what stops Stage 71
drifting out of sync the first time somebody adds an engine — the failure mode
`ARCHITECTURE_PRINCIPLES.md` says a rule in someone's head will not survive.
"""

import re
from pathlib import Path

import pytest

from mios_v5 import horizon_owner as HO
from mios_v5.horizon_owner import (AGGREGATE, CATEGORIES, EXCLUDED, HOLD,
                                   HORIZONS, NATIVE_LABEL, NON_DIRECTIONAL,
                                   OWNED, STABILITY, Horizon)

_REPO = Path(__file__).resolve().parents[2]


def _live_engine_names():
    """Engine ids exactly as the orchestrator keys them in MarketState."""
    from mios_v5.engines import ALL_ENGINES
    return {cls().name for cls in ALL_ENGINES}


def _live_bias_category():
    """`_BIAS_CATEGORY` parsed out of vob_minimal.py without importing it —
    importing pulls in Streamlit and the whole app boot."""
    src = (_REPO / "vob_minimal.py").read_text(encoding="utf-8")
    body = re.search(r"_BIAS_CATEGORY = \{(.*?)\n\}", src, re.S).group(1)
    return dict(re.findall(r'"([^"]+)":\s*\'(\w+)\'', body))


# ── the core rule: one producer, one home ───────────────────────────────

def test_every_producer_has_exactly_one_home():
    """No producer may appear in two categories."""
    seen = {}
    for cat, table in CATEGORIES.items():
        for pid in table:
            assert pid not in seen, (
                f"{pid!r} is in both {seen[pid]} and {cat} — a producer has "
                f"exactly one home")
            seen[pid] = cat


def test_no_aggregate_may_own_a_horizon():
    """The whole point: a composite voting would re-count its members."""
    for pid in AGGREGATE:
        assert pid not in OWNED, f"aggregate {pid!r} may never own a horizon"


def test_no_stability_producer_may_own_a_horizon():
    """44/47/54 shape Stability and the veto. Letting them also vote
    directionally is the double-count v6_bias already refused."""
    for pid in STABILITY:
        assert pid not in OWNED, f"stability producer {pid!r} may not vote"


def test_no_excluded_producer_may_own_a_horizon():
    for pid in EXCLUDED:
        assert pid not in OWNED, f"excluded {pid!r} may never own a horizon"


def test_every_registered_horizon_is_a_real_horizon():
    for pid, h in OWNED.items():
        assert isinstance(h, Horizon), f"{pid!r} maps to {h!r}, not a Horizon"


def test_every_horizon_owns_at_least_one_producer():
    """A horizon with no owners would render an empty row forever."""
    for h in HORIZONS:
        assert HO.owners_of(h), f"{h.value} owns nothing"


# ── coverage against the LIVE system ────────────────────────────────────

def test_every_engine_is_registered():
    """Adding an engine without declaring a horizon fails the build."""
    missing = sorted(n for n in _live_engine_names() if not HO.category_of(n))
    assert not missing, (
        "engines with no horizon ownership: " + ", ".join(missing) +
        " — add each to OWNED, STABILITY, AGGREGATE, EXCLUDED or "
        "NON_DIRECTIONAL in horizon_owner.py")


def test_every_native_signal_is_registered():
    """Same rule for vob_minimal's `_BIAS_CATEGORY` signals."""
    labels = set(_live_bias_category())
    mapped = set(NATIVE_LABEL.values())
    missing = sorted(labels - mapped)
    assert not missing, (
        "native signals with no id in NATIVE_LABEL: " + ", ".join(missing))


def test_every_native_label_still_exists():
    """A renamed label must break the build, not silently orphan its id."""
    labels = set(_live_bias_category())
    stale = sorted(lbl for lbl in NATIVE_LABEL.values() if lbl not in labels)
    assert not stale, (
        "NATIVE_LABEL points at labels no longer in _BIAS_CATEGORY: "
        + ", ".join(stale))


def test_every_native_id_has_a_category():
    missing = sorted(pid for pid in NATIVE_LABEL if not HO.category_of(pid))
    assert not missing, "native ids with no category: " + ", ".join(missing)


def test_native_ids_and_labels_are_both_unique():
    assert len(set(NATIVE_LABEL.values())) == len(NATIVE_LABEL), \
        "two ids map to the same label"


def test_every_mis_tier_signal_is_excluded_not_owned():
    """vob_minimal calls these 'flips on single bars'. That judgement must
    survive into the matrix rather than being quietly re-admitted."""
    label_to_id = {v: k for k, v in NATIVE_LABEL.items()}
    for label, bucket in _live_bias_category().items():
        if bucket != "mis":
            continue
        pid = label_to_id[label]
        assert pid not in OWNED, (
            f"{label!r} is mis-tier (unstable) and may not own a horizon")


def test_htf_ids_match_the_real_timeframes():
    from mios_v5.htf_vpfr import TIMEFRAMES
    assert set(HO.HTF_TIMEFRAME.values()) == set(TIMEFRAMES), \
        "HTF_TIMEFRAME has drifted from htf_vpfr.TIMEFRAMES"
    for pid in HO.HTF_TIMEFRAME:
        assert pid in OWNED, f"{pid!r} must own exactly one horizon"


# ── the swing rule ──────────────────────────────────────────────────────

def test_swing_never_recommends_a_side():
    """Today's option chain cannot support a multi-week CALL/PUT call. Swing
    reports structure and levels — asserted here so no future change can
    quietly start emitting a side."""
    assert Horizon.SWING in HO.NO_OPTION_SIDE


def test_only_swing_is_side_free():
    for h in HORIZONS:
        if h is not Horizon.SWING:
            assert h not in HO.NO_OPTION_SIDE


def test_positional_declares_its_reach():
    """A degraded horizon must say so, not imply full confidence."""
    assert Horizon.POSITIONAL in HO.DEGRADED
    assert HO.DEGRADED[Horizon.POSITIONAL].strip()


# ── the per-horizon veto ────────────────────────────────────────────────

def test_flow_shift_effect_covers_every_horizon():
    assert set(HO.FLOW_SHIFT_EFFECT) == set(HORIZONS)


def test_flow_shift_vetoes_short_horizons_and_spares_long_ones():
    """A shift destroys a scalp; it can be the swing thesis."""
    assert HO.FLOW_SHIFT_EFFECT[Horizon.SCALP] == "veto"
    assert HO.FLOW_SHIFT_EFFECT[Horizon.MIDDAY] == "veto"
    assert HO.FLOW_SHIFT_EFFECT[Horizon.INTRADAY] == "discount"
    assert HO.FLOW_SHIFT_EFFECT[Horizon.POSITIONAL] is None
    assert HO.FLOW_SHIFT_EFFECT[Horizon.SWING] is None


def test_flow_shift_discount_is_a_real_discount():
    assert 0.0 < HO.FLOW_SHIFT_DISCOUNT < 1.0


# ── every category is explained, not just listed ────────────────────────

@pytest.mark.parametrize("table,name", [
    (STABILITY, "STABILITY"), (AGGREGATE, "AGGREGATE"),
    (EXCLUDED, "EXCLUDED"), (NON_DIRECTIONAL, "NON_DIRECTIONAL")])
def test_every_non_voting_producer_carries_a_reason(table, name):
    """The Excluded panel renders these reasons. An empty one would show a
    producer removed for no stated cause."""
    for pid, reason in table.items():
        assert reason and reason.strip(), f"{name}[{pid!r}] has no reason"


def test_every_horizon_has_a_hold_time():
    assert set(HOLD) == set(HORIZONS)


# ── helpers behave ──────────────────────────────────────────────────────

def test_may_vote_is_true_only_for_owned():
    assert HO.may_vote("stage42_acceptance")
    assert not HO.may_vote("stage27_conflict")     # aggregate
    assert not HO.may_vote("stage44_flow_shift")   # stability
    assert not HO.may_vote("native_news_bias")     # excluded
    assert not HO.may_vote("no_such_producer")


def test_horizon_of_returns_none_for_non_voters():
    assert HO.horizon_of("stage42_acceptance") is Horizon.SCALP
    assert HO.horizon_of("stage27_conflict") is None
    assert HO.horizon_of("unknown") is None


def test_category_of_is_empty_for_unregistered():
    assert HO.category_of("stage42_acceptance") == "OWNED"
    assert HO.category_of("stage44_flow_shift") == "STABILITY"
    assert HO.category_of("totally_made_up") == ""


def test_owners_of_is_sorted_and_scoped():
    scalp = HO.owners_of(Horizon.SCALP)
    assert scalp == tuple(sorted(scalp))
    assert all(OWNED[p] is Horizon.SCALP for p in scalp)


def test_registry_is_pure_data():
    """No IO, no Streamlit, no app import — the module must stay importable
    from a test process with nothing else loaded."""
    src = (_REPO / "mios_v5" / "horizon_owner.py").read_text(encoding="utf-8")
    for banned in ("import streamlit", "import requests", "session_state",
                   "import pandas", "from vob_minimal"):
        assert banned not in src, f"horizon_owner.py must not contain {banned!r}"


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        if not hasattr(fn, "pytestmark"):
            fn()
    print(f"horizon ownership registry tests passed ({len(fns)})")
