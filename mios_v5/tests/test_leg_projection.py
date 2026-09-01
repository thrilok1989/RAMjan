"""`leg_projection` — a NIFTY level read off a premium axis.

The property under test is a refusal as much as a calculation. This module is
allowed to put a spot-derived level on an option panel *only* because it never
converts one: it reports what the leg actually traded at when the index was
near the level, and reports nothing when the index has not been.

So the tests that matter most are the ones that assert **no line is drawn**.
"""

import pandas as pd
import pytest

from mios_v5.ui import leg_projection as LP


def _frames(spot, prem):
    """One matched pair of frames, on the shared timeline the terminal builds."""
    return (pd.DataFrame({"close": spot}), pd.DataFrame({"close": prem}))


# ══════════════════════════════════════════════════════════════════════
#  it measures — it does not model
# ══════════════════════════════════════════════════════════════════════

def test_the_premium_is_the_one_the_leg_actually_traded():
    """NIFTY was at 24,600 on the bars where this leg printed ₹120."""
    nifty, leg = _frames([24500, 24600, 24600, 24700],
                         [80.0, 120.0, 120.0, 170.0])
    got = LP.project(nifty, leg, 24600)
    assert got["premium"] == 120.0
    assert got["matched"] == 2


def test_a_level_the_session_never_reached_draws_nothing():
    """⭐ The refusal.

    NIFTY topped at 24,610. The honest answer to "what is this leg worth at
    25,000?" is that nobody knows, and `None` is how that is said. A projection
    extrapolated to there would look exactly as confident as a measured one.
    """
    nifty, leg = _frames([24500, 24550, 24610], [80.0, 100.0, 130.0])
    assert LP.project(nifty, leg, 25000) is None


def test_one_visit_is_not_enough():
    """A single bar near a level is an anecdote. The line it would draw looks
    identical to one backed by fifty bars, which is the problem."""
    nifty, leg = _frames([24000, 24600, 24000], [40.0, 120.0, 40.0])
    assert LP.project(nifty, leg, 24600, min_sample=2) is None
    assert LP.project(nifty, leg, 24600, min_sample=1) is not None


def test_the_tolerance_is_the_one_the_repo_already_uses():
    """`AUDIT_STAGE_42_5_LEVEL_INTERACTION.md` counted fourteen proximity
    thresholds in three units. This must not be the fifteenth."""
    assert LP.TOLERANCE == 25.0


def test_bars_outside_the_tolerance_do_not_count():
    nifty, leg = _frames([24500, 24560, 24600, 24601], [50, 90, 120.0, 121.0])
    got = LP.project(nifty, leg, 24600, tolerance=5)
    assert got["matched"] == 2
    assert got["premium"] == pytest.approx(120.5)


# ══════════════════════════════════════════════════════════════════════
#  theta — the same index level is not the same premium all day
# ══════════════════════════════════════════════════════════════════════

def test_the_recent_visit_wins_over_the_morning_one():
    """⭐ The same spot pays less at 15:10 than at 09:30.

    NIFTY visits 24,600 twice: early, when the leg was worth ₹200, and late,
    when decay has left it at ₹100. Averaging both would report ₹150 — a
    premium that was true at neither moment, and one a trader sizing a position
    at 15:10 would act on.
    """
    nifty, leg = _frames([24600, 24600, 24000, 24600, 24600],
                         [200.0, 200.0, 30.0, 100.0, 100.0])
    got = LP.project(nifty, leg, 24600, sample=2)
    assert got["premium"] == 100.0


def test_a_single_bad_print_does_not_move_the_line():
    """The median, not the mean — one thin minute should not relocate a level."""
    nifty, leg = _frames([24600] * 5, [120.0, 121.0, 119.0, 900.0, 120.0])
    assert LP.project(nifty, leg, 24600, sample=5)["premium"] == 120.0


# ══════════════════════════════════════════════════════════════════════
#  the pairing, which is the whole basis
# ══════════════════════════════════════════════════════════════════════

def test_bars_are_paired_positionally_because_the_terminal_shares_a_timeline():
    """`terminal_chart.master_timeline` reindexes all three panels onto one
    clock, so bar n is the same minute everywhere. That is what makes zipping
    the two closes an alignment rather than a shortcut past one."""
    nifty, leg = _frames([1.0, 2.0, 3.0], [10.0, 20.0, 30.0])
    assert LP.pairs(nifty, leg) == [(1.0, 10.0), (2.0, 20.0), (3.0, 30.0)]


def test_a_ragged_pair_of_frames_stops_at_the_shorter_one():
    nifty, leg = _frames([1.0, 2.0, 3.0, 4.0], [10.0, 20.0])
    assert len(LP.pairs(nifty, leg)) == 2


def test_a_bar_the_leg_did_not_trade_is_skipped():
    """An aligned gap is a zero or a NaN, not a premium of nothing."""
    nifty, leg = _frames([24600, 24600, 24600], [120.0, 0.0, None])
    assert LP.pairs(nifty, leg) == [(24600.0, 120.0)]


@pytest.mark.parametrize("column", ["close", "ltp", "price"])
def test_whatever_the_frame_calls_its_close(column):
    """The leg frames and the index frame come from different fetches and have
    historically disagreed about this column."""
    nifty = pd.DataFrame({column: [24600, 24600]})
    leg = pd.DataFrame({column: [120.0, 120.0]})
    assert LP.project(nifty, leg, 24600)["premium"] == 120.0


# ══════════════════════════════════════════════════════════════════════
#  what reaches the chart
# ══════════════════════════════════════════════════════════════════════

def test_projected_keys_never_collide_with_a_legs_own_levels():
    """⭐ Both may sit on one panel, and whether they agree is the useful part.

    A leg's own support and the index support projected onto it are different
    claims. Sharing a key would make one silently overwrite the other.
    """
    from mios_v5.ui.terminal_chart import LEVELS
    for src, dst in LP.PROJECTED.items():
        assert dst != src
        assert dst in LEVELS, f"{dst} has no style — it would not be drawn"


def test_every_projected_key_is_labelled_as_projected():
    """The arrow is the disclosure. A trader must never have to remember which
    of two lines is the borrowed one."""
    from mios_v5.ui.terminal_chart import LEVEL_LABEL
    for dst in LP.PROJECTED.values():
        assert LEVEL_LABEL[dst].startswith("⇢")


def test_projected_levels_are_visually_distinct_from_native_ones():
    from mios_v5.ui.terminal_chart import LEVELS
    native = {k: v for k, v in LEVELS.items() if not k.startswith("proj_")}
    assert all(dash != "longdashdot" for _, dash, _ in native.values())


def test_only_the_levels_that_were_reached_come_back():
    nifty, leg = _frames([24500, 24500, 24500], [80.0, 80.0, 80.0])
    got = LP.project_levels(nifty, leg,
                            {"war_zone": 24500, "gamma_flip": 25500})
    assert got == {"proj_war_zone": 80.0}


def test_no_levels_means_no_keys():
    nifty, leg = _frames([24500, 24500], [80.0, 80.0])
    assert LP.project_levels(nifty, leg, {}) == {}
    assert LP.project_levels(nifty, leg, None) == {}


def test_a_level_of_zero_or_none_is_not_a_level():
    nifty, leg = _frames([24500, 24500], [80.0, 80.0])
    for bad in (None, 0, "", "abc", float("nan")):
        assert LP.project(nifty, leg, bad) is None


def test_the_caption_names_what_was_drawn_and_is_silent_otherwise():
    assert LP.caption({}) == ""
    assert LP.caption(None) == ""
    line = LP.caption({"proj_war_zone": 80.0, "proj_gamma_flip": 90.0})
    assert "war zone" in line and "gamma flip" in line
    assert "25" in line                      # the tolerance is stated
    assert "not priced from a model" in line


def test_an_empty_frame_is_not_an_error():
    """A warming-up terminal must draw, not raise."""
    empty = pd.DataFrame()
    assert LP.project(empty, empty, 24600) is None
    assert LP.pairs(empty, None) == []
    assert LP.project_levels(None, None, {"war_zone": 24600}) == {}
