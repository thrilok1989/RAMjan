"""Finding one leg's cached engine output, whichever key it was written under.

⭐ The defect this exists for emptied the whole of Premium Structure while
every engine behind it kept working normally.

The app writes every per-leg store under the **offset** form:

    _atm_leg_dfs[ "ATM CE 24550" ]  _atm_leg_sr_behavior[ "ATM-1 PE 24500" ]  …

`_leg_reads_for` is handed a *strike*, not a leg, so the only tag it can build
is `"CE 24550"` — two tokens. `_leg_key_variants` resolves long → short by
dropping the prefix, and there was nothing resolving short → long: two tokens
means no prefix to drop, and `_atm_leg_sids` is keyed by the long form so the
`sid_` fallback missed too.

So every lookup returned `None`, `analyse()` was handed no S/R, no VOB, no
VIDYA, no flow and no frame, and the card rendered:

    Structure —  Confidence UNKNOWN  Support —  Resistance —  POC —
    Acceptance —  Momentum —  RVOL —  Absorption —  Break —  Fakeout —
    ⚪ Premium S/R   premium structure did not report

That panel is the test case below.
"""

import pandas as pd
import pytest

from mios_v5.ui import dashboard_v6 as D6


class _St:
    """Just enough Streamlit for the lookup helpers."""

    def __init__(self, **state):
        self.session_state = dict(state)


#: How the app really writes them — `f"{tag} {side} {strike:.0f}"`.
LONG = "ATM CE 24550"
WING = "ATM-3 PE 24400"

#: What `_leg_reads_for` can build from a strike alone.
SHORT = "CE 24550"


def _frame(n=8):
    return pd.DataFrame({"close": [70.0 + i for i in range(n)],
                         "volume": [100] * n})


# ══════════════════════════════════════════════════════════════════════
#  the direction that was missing
# ══════════════════════════════════════════════════════════════════════

def test_a_strike_only_tag_finds_the_store_written_with_an_offset():
    """⭐ The bug. Every field on the card was `—` because of this one miss."""
    st = _St(_atm_leg_sr_behavior={LONG: {"level": 72.0, "side": "support"}})
    assert D6._leg_store(st, "_atm_leg_sr_behavior", SHORT) == {
        "level": 72.0, "side": "support"}


def test_a_strike_only_tag_finds_the_candles():
    """Without the frame there is no LTP and no candles, so RVOL, the profile,
    the POC and both probabilities are all unreportable at once."""
    st = _St(_atm_leg_dfs={LONG: _frame()})
    got = D6._leg_frame(st, SHORT)
    assert got is not None and len(got) == 8


@pytest.mark.parametrize("store", [
    "_atm_leg_vob_volume", "_atm_leg_vidya", "_atm_leg_ltf_delta",
    "_atm_leg_sr_behavior",
])
def test_every_store_premium_structure_reads_resolves(store):
    """`analyse()` takes four of these. One missing is one blank row; four
    missing is the card the user saw."""
    st = _St(**{store: {LONG: {"x": 1}}})
    assert D6._leg_store(st, store, SHORT) == {"x": 1}


def test_a_wing_strike_resolves_without_knowing_its_offset():
    """The prefix depends on where the strike sits relative to the ATM, which
    the caller does not know. Matching the last two tokens means it never has
    to — a later layout could write `"ATM-7 PE 24400"` and this still works."""
    st = _St(_atm_leg_vidya={WING: {"momentum": -12.0}})
    assert D6._leg_store(st, "_atm_leg_vidya", "PE 24400") == {"momentum": -12.0}


# ══════════════════════════════════════════════════════════════════════
#  it must not match the wrong contract
# ══════════════════════════════════════════════════════════════════════

def test_the_other_side_of_the_same_strike_is_a_different_leg():
    """Side and strike together identify one contract. Matching on the strike
    alone would grade the call with the put's structure."""
    st = _St(_atm_leg_sr_behavior={"ATM CE 24550": {"side": "call"},
                                   "ATM PE 24550": {"side": "put"}})
    assert D6._leg_store(st, "_atm_leg_sr_behavior", "CE 24550") == {"side": "call"}
    assert D6._leg_store(st, "_atm_leg_sr_behavior", "PE 24550") == {"side": "put"}


def test_a_neighbouring_strike_is_not_close_enough():
    st = _St(_atm_leg_vidya={"ATM+1 CE 24600": {"momentum": 5.0}})
    assert D6._leg_store(st, "_atm_leg_vidya", "CE 24550") is None


def test_a_strike_with_nothing_stored_stays_absent():
    """A wing outside the ATM±1 fetch has no leg entry. It must report UNKNOWN
    rather than borrow a neighbour's levels — grading the wrong option with
    nothing on screen to say so is worse than reporting nothing."""
    st = _St(_atm_leg_sr_behavior={LONG: {"level": 72.0}})
    assert D6._leg_store(st, "_atm_leg_sr_behavior", "CE 25000") is None


# ══════════════════════════════════════════════════════════════════════
#  the exact-key path still wins, and nothing regresses
# ══════════════════════════════════════════════════════════════════════

def test_an_exact_key_is_preferred_over_a_suffix_match():
    st = _St(_atm_leg_vidya={"CE 24550": {"which": "exact"},
                             "ATM CE 24550": {"which": "suffix"}})
    assert D6._leg_store(st, "_atm_leg_vidya", "CE 24550") == {"which": "exact"}


def test_the_long_form_still_resolves():
    """`atm_legs()` hands back the offset form and the terminal passes it
    straight through. That path predates this fix and must be untouched."""
    st = _St(_atm_leg_vob_volume={LONG: [{"lower": 60, "upper": 70}]})
    assert D6._leg_store(st, "_atm_leg_vob_volume", LONG)


def test_the_security_id_form_still_resolves():
    st = _St(_atm_leg_sids={LONG: ("65806", "NSE_FNO")},
             _atm_leg_vidya={"sid_65806": {"momentum": 3.0}})
    assert D6._leg_store(st, "_atm_leg_vidya", LONG) == {"momentum": 3.0}


# ══════════════════════════════════════════════════════════════════════
#  it cannot raise
# ══════════════════════════════════════════════════════════════════════

def test_a_dataframe_store_does_not_raise_on_a_truthiness_check():
    """⚠️ `if not val` raises here — a DataFrame refuses `bool()` with "The
    truth value of a DataFrame is ambiguous". The scan asks for emptiness by
    name instead."""
    st = _St(_atm_leg_dfs={LONG: _frame()})
    assert D6._leg_suffix_match(st.session_state["_atm_leg_dfs"], SHORT) is not None


def test_an_empty_frame_is_not_a_match():
    st = _St(_atm_leg_dfs={LONG: pd.DataFrame()})
    assert D6._leg_frame(st, SHORT) is None


@pytest.mark.parametrize("tag", [None, "", "CE", "sid_65806", 24550])
def test_a_tag_that_names_no_leg_returns_nothing(tag):
    st = _St(_atm_leg_vidya={LONG: {"momentum": 1.0}})
    assert D6._leg_store(st, "_atm_leg_vidya", tag) is None


def test_an_absent_store_is_not_an_error():
    st = _St()
    assert D6._leg_store(st, "_atm_leg_vidya", SHORT) is None
    assert D6._leg_frame(st, SHORT) is None


def test_a_store_that_is_not_a_mapping_is_survived():
    assert D6._leg_suffix_match(["not", "a", "mapping"], SHORT) is None
    assert D6._leg_suffix_match(None, SHORT) is None
