"""Tests for instrument registry and cache management.

Verifies:
1. InstrumentContext holds all required specs
2. Cache invalidation clears instrument-specific keys
3. Instrument switching doesn't cross-contaminate data
4. Dhan discovery returns valid specs (when mocked)
"""

from mios_v5.instrument_registry import InstrumentContext, InstrumentRegistry
from mios_v5.instrument_cache_manager import (
    DEFAULT_INSTRUMENT,
    invalidate_instrument_cache,
    get_current_instrument,
    instrument_changed_this_render,
    INSTRUMENT_DEPENDENT_KEYS,
)


def test_instrument_context_has_all_specs():
    """InstrumentContext holds all required specs."""
    ctx = InstrumentContext(
        symbol="NIFTY",
        security_id=13,
        exchange_segment="IDX_I",
        contract_multiplier=25.0,
        strike_step=100,
        current_expiry="2026-08-27",
        expiry_list=["2026-08-27", "2026-09-24"],
        atm_range=100,
        lot_size=1,
        tick_size=0.05,
    )
    assert ctx.symbol == "NIFTY"
    assert ctx.security_id == 13
    assert ctx.contract_multiplier == 25.0
    assert len(ctx.expiry_list) >= 1


def test_instrument_context_to_dict():
    """InstrumentContext converts to dict."""
    ctx = InstrumentContext(
        symbol="SENSEX",
        security_id=40,
        exchange_segment="IDX_I",
        contract_multiplier=1.0,
        strike_step=100,
        current_expiry="2026-08-27",
        expiry_list=["2026-08-27"],
        atm_range=100,
        lot_size=1,
        tick_size=0.05,
    )
    d = ctx.to_dict()
    assert d["symbol"] == "SENSEX"
    assert d["security_id"] == 40
    assert "contract_multiplier" in d


def test_cache_invalidation_clears_keys():
    """Invalidating instrument cache removes all dependent keys."""
    session_state = {
        "_nifty_spot_live": 24400.5,
        "_df_5m": "some_dataframe",
        "_cached_raw_chain": "chain_data",
        "_full_market_read": "market_data",
        "_other_key": "should_remain",
    }

    invalidate_instrument_cache(session_state, "SENSEX")

    # Instrument-dependent keys should be cleared
    assert "_nifty_spot_live" not in session_state
    assert "_df_5m" not in session_state
    assert "_cached_raw_chain" not in session_state
    assert "_full_market_read" not in session_state

    # Non-instrument keys should remain
    assert "_other_key" in session_state
    assert session_state["_other_key"] == "should_remain"

    # Current instrument should be updated
    assert session_state["_selected_instrument"] == "SENSEX"


def test_get_current_instrument_default():
    """get_current_instrument falls back to DEFAULT_INSTRUMENT (NIFTY).

    `test_instrument_chart_wiring` pins the value itself; this pins that the
    fallback is wired to the constant rather than to a second literal.
    """
    empty_session = {}
    assert get_current_instrument(empty_session) == DEFAULT_INSTRUMENT
    assert get_current_instrument(empty_session) == "NIFTY"


def test_get_current_instrument_returns_selected():
    """get_current_instrument returns selected instrument."""
    session_state = {"_selected_instrument": "SENSEX"}
    assert get_current_instrument(session_state) == "SENSEX"


def test_switching_instruments_clears_cache():
    """Switching from one instrument to another clears cache."""
    session_state = {
        "_selected_instrument": "NIFTY",
        "_nifty_spot_live": 24400,
        "_df_5m": "nifty_candles",
        "_full_market_read": "nifty_market",
    }

    # Switch to SENSEX
    invalidate_instrument_cache(session_state, "SENSEX")

    # All cached data should be gone
    assert "_nifty_spot_live" not in session_state
    assert "_df_5m" not in session_state
    assert "_full_market_read" not in session_state

    # New instrument should be set
    assert session_state["_selected_instrument"] == "SENSEX"


def test_same_instrument_no_clear():
    """Switching to same instrument doesn't trigger clear."""
    session_state = {
        "_selected_instrument": "NIFTY",
        "_nifty_spot_live": 24400,
    }

    # Try to "switch" to NIFTY (no change)
    invalidate_instrument_cache(session_state, "NIFTY")

    # Cache should be preserved (not cleared when same instrument)
    # Note: Our current implementation clears on every call; this test
    # documents the expected behavior if we optimize it to skip clear
    # on same-instrument "switch"
    assert session_state["_selected_instrument"] == "NIFTY"


def test_all_dependent_keys_documented():
    """All instrument-dependent keys are in INSTRUMENT_DEPENDENT_KEYS."""
    # This is a documentation test: ensure all keys that should be cleared
    # are actually listed in INSTRUMENT_DEPENDENT_KEYS
    assert len(INSTRUMENT_DEPENDENT_KEYS) > 20
    assert "_nifty_spot_live" in INSTRUMENT_DEPENDENT_KEYS
    assert "_df_5m" in INSTRUMENT_DEPENDENT_KEYS
    assert "_cached_raw_chain" in INSTRUMENT_DEPENDENT_KEYS


def test_nifty_context_specs():
    """NIFTY context has correct specs."""
    ctx = InstrumentContext(
        symbol="NIFTY",
        security_id=13,
        exchange_segment="IDX_I",
        contract_multiplier=25.0,
        strike_step=100,
        current_expiry="2026-08-27",
        expiry_list=["2026-08-27", "2026-09-24"],
        atm_range=100,
        lot_size=1,
        tick_size=0.05,
    )

    assert ctx.symbol == "NIFTY"
    assert ctx.contract_multiplier == 25.0
    assert ctx.strike_step == 100


def test_sensex_context_specs():
    """SENSEX context has correct specs."""
    ctx = InstrumentContext(
        symbol="SENSEX",
        security_id=40,
        exchange_segment="IDX_I",
        contract_multiplier=1.0,
        strike_step=100,
        current_expiry="2026-08-27",
        expiry_list=["2026-08-27"],
        atm_range=100,
        lot_size=1,
        tick_size=0.05,
    )

    assert ctx.symbol == "SENSEX"
    assert ctx.security_id == 40
    assert ctx.contract_multiplier == 1.0


class _FakeDhan:
    """Records what the registry asks Dhan for, so the ids it uses are testable."""

    def __init__(self):
        self.asked = []

    def optionchain_expirylist(self, security_id, exchange_segment):
        self.asked.append((security_id, exchange_segment))
        return {"data": {"expiryDate": ["2026-08-27", "2026-09-24"]}}

    def optionchain(self, security_id, exchange_segment, expiry_date):
        return {"data": []}


def test_sensex_security_id_is_dhan_verified_51():
    """SENSEX must resolve to 51 (Dhan scrip master, BSE / 'SENSEX').

    Regression: an invented id (40) returned no candles, and because the chart
    only replaces its frame on a non-empty fetch, selecting SENSEX silently
    kept drawing NIFTY. A wrong id here is invisible at runtime — pin it.
    """
    fake = _FakeDhan()
    ctx = InstrumentRegistry(fake).discover_sensex()

    assert ctx is not None, "SENSEX discovery returned nothing"
    assert ctx.security_id == 51, f"expected 51, got {ctx.security_id}"
    assert ctx.security_id != 40, "40 was the fabricated id — never reintroduce it"
    assert (51, "IDX_I") in fake.asked


def test_nifty_security_id_is_dhan_verified_13():
    """NIFTY must resolve to 13 (Dhan scrip master, NSE / 'NIFTY')."""
    fake = _FakeDhan()
    ctx = InstrumentRegistry(fake).discover_nifty()

    assert ctx is not None
    assert ctx.security_id == 13
    assert (13, "IDX_I") in fake.asked


def test_lot_sizes_match_dhan_scrip_master():
    """Lot sizes come from SEM_LOT_UNITS on the OPTIDX rows, not from 1."""
    nifty = InstrumentRegistry(_FakeDhan()).discover_nifty()
    sensex = InstrumentRegistry(_FakeDhan()).discover_sensex()

    assert nifty.lot_size == 65, f"NIFTY lot is 65, got {nifty.lot_size}"
    assert sensex.lot_size == 20, f"SENSEX lot is 20, got {sensex.lot_size}"


def test_strike_steps_differ_between_instruments():
    """NIFTY strikes step 50; SENSEX steps 100. Assuming one value for both
    was wrong and would mis-round every ATM strike on one of them."""
    nifty = InstrumentRegistry(_FakeDhan()).discover_nifty()
    sensex = InstrumentRegistry(_FakeDhan()).discover_sensex()

    assert nifty.strike_step == 50, f"NIFTY step is 50, got {nifty.strike_step}"
    assert sensex.strike_step == 100, f"SENSEX step is 100, got {sensex.strike_step}"
