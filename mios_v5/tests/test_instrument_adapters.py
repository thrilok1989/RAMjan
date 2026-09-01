"""Tests for instrument-aware data adapters.

Verifies that adapters correctly map instrument context to data fetching
functions without modifying the original functions.
"""

from mios_v5.instrument_registry import InstrumentContext
from mios_v5.instrument_adapters import (
    format_instrument_message,
    get_atm_strike,
    get_strike_range,
    instrument_symbol_for_message,
)


def test_format_instrument_message_nifty():
    """Format message with NIFTY instrument prefix."""
    ctx = InstrumentContext(
        symbol="NIFTY",
        security_id=13,
        exchange_segment="IDX_I",
        contract_multiplier=25.0,
        strike_step=100,
        current_expiry="2026-08-27",
        expiry_list=["2026-08-27"],
        atm_range=100,
        lot_size=1,
        tick_size=0.05,
    )

    msg = format_instrument_message(ctx, "Entry at support")
    assert msg == "[NIFTY] Entry at support"


def test_format_instrument_message_sensex():
    """Format message with SENSEX instrument prefix."""
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

    msg = format_instrument_message(ctx, "Exit signal")
    assert msg == "[SENSEX] Exit signal"


def test_format_instrument_message_no_duplicate_prefix():
    """Don't add prefix if already present."""
    ctx = InstrumentContext(
        symbol="NIFTY",
        security_id=13,
        exchange_segment="IDX_I",
        contract_multiplier=25.0,
        strike_step=100,
        current_expiry="2026-08-27",
        expiry_list=["2026-08-27"],
        atm_range=100,
        lot_size=1,
        tick_size=0.05,
    )

    msg = "[NIFTY] Already prefixed"
    result = format_instrument_message(ctx, msg)
    assert result == msg  # No duplicate


def test_format_instrument_message_no_prefix():
    """Skip prefix if include_symbol=False."""
    ctx = InstrumentContext(
        symbol="NIFTY",
        security_id=13,
        exchange_segment="IDX_I",
        contract_multiplier=25.0,
        strike_step=100,
        current_expiry="2026-08-27",
        expiry_list=["2026-08-27"],
        atm_range=100,
        lot_size=1,
        tick_size=0.05,
    )

    msg = format_instrument_message(ctx, "Raw message", include_symbol=False)
    assert msg == "Raw message"


def test_get_atm_strike_nifty():
    """Calculate ATM strike for NIFTY (100-point steps)."""
    ctx = InstrumentContext(
        symbol="NIFTY",
        security_id=13,
        exchange_segment="IDX_I",
        contract_multiplier=25.0,
        strike_step=100,
        current_expiry="2026-08-27",
        expiry_list=["2026-08-27"],
        atm_range=100,
        lot_size=1,
        tick_size=0.05,
    )

    spot = 24400.5
    atm = get_atm_strike(ctx, spot)
    # 24400.5 / 100 = 244.005 → round to 244 → 24400
    assert atm == 24400


def test_get_atm_strike_sensex():
    """Calculate ATM strike for SENSEX."""
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

    spot = 79500.0
    atm = get_atm_strike(ctx, spot)
    assert atm == 79500


def test_get_atm_strike_rounding():
    """ATM strike rounds to nearest strike_step."""
    ctx = InstrumentContext(
        symbol="NIFTY",
        security_id=13,
        exchange_segment="IDX_I",
        contract_multiplier=25.0,
        strike_step=100,
        current_expiry="2026-08-27",
        expiry_list=["2026-08-27"],
        atm_range=100,
        lot_size=1,
        tick_size=0.05,
    )

    # Test rounding up
    atm_up = get_atm_strike(ctx, 24451)
    assert atm_up == 24500

    # Test rounding down
    atm_down = get_atm_strike(ctx, 24449)
    assert atm_down == 24400


def test_get_strike_range():
    """Get strike range around ATM."""
    ctx = InstrumentContext(
        symbol="NIFTY",
        security_id=13,
        exchange_segment="IDX_I",
        contract_multiplier=25.0,
        strike_step=100,
        current_expiry="2026-08-27",
        expiry_list=["2026-08-27"],
        atm_range=100,  # ±100
        lot_size=1,
        tick_size=0.05,
    )

    spot = 24400.0
    lower, upper = get_strike_range(ctx, spot)

    # ATM = 24400, ±100 range = [24300, 24500]
    assert lower == 24300
    assert upper == 24500


def test_get_strike_range_larger_range():
    """Get wider strike range for more legs."""
    ctx = InstrumentContext(
        symbol="NIFTY",
        security_id=13,
        exchange_segment="IDX_I",
        contract_multiplier=25.0,
        strike_step=100,
        current_expiry="2026-08-27",
        expiry_list=["2026-08-27"],
        atm_range=200,  # ±200 (wider)
        lot_size=1,
        tick_size=0.05,
    )

    spot = 24500.0
    lower, upper = get_strike_range(ctx, spot)

    # ATM = 24500, ±200 range = [24300, 24700]
    assert lower == 24300
    assert upper == 24700


def test_instrument_symbol_for_message():
    """Format symbol for message display."""
    ctx_nifty = InstrumentContext(
        symbol="NIFTY",
        security_id=13,
        exchange_segment="IDX_I",
        contract_multiplier=25.0,
        strike_step=100,
        current_expiry="2026-08-27",
        expiry_list=["2026-08-27"],
        atm_range=100,
        lot_size=1,
        tick_size=0.05,
    )

    result = instrument_symbol_for_message(ctx_nifty)
    assert "NIFTY" in result
    assert "📊" in result


def test_get_atm_strike_invalid_spot():
    """ATM calculation handles invalid spot."""
    ctx = InstrumentContext(
        symbol="NIFTY",
        security_id=13,
        exchange_segment="IDX_I",
        contract_multiplier=25.0,
        strike_step=100,
        current_expiry="2026-08-27",
        expiry_list=["2026-08-27"],
        atm_range=100,
        lot_size=1,
        tick_size=0.05,
    )

    # None spot
    assert get_atm_strike(ctx, None) is None

    # Zero or negative spot
    assert get_atm_strike(ctx, 0) is None
    assert get_atm_strike(ctx, -100) is None
