"""Instrument-aware adapters for all data fetching functions.

These wrap the existing vob_minimal functions, accepting InstrumentContext
instead of raw security_id/segment parameters. Single source of truth for
which parameter to pass for each instrument.

This allows gradual migration: new code uses adapters, old code uses
direct functions until fully transitioned.
"""

from typing import Optional, Any, Dict, List
from mios_v5.instrument_registry import InstrumentContext
import logging

_logger = logging.getLogger(__name__)


def get_spot_price(
    context: InstrumentContext,
    get_index_spot_ltp_fn: callable,
) -> Optional[float]:
    """Get live spot price for the instrument.

    Args:
        context: InstrumentContext with security_id and exchange_segment
        get_index_spot_ltp_fn: Reference to vob_minimal's get_index_spot_ltp function

    Returns:
        Float spot price or None on failure
    """
    try:
        return get_index_spot_ltp_fn(
            scrip=context.security_id,
            seg=context.exchange_segment
        )
    except Exception as e:
        _logger.error(f"Failed to fetch {context.symbol} spot: {e}")
        return None


def get_option_chain(
    context: InstrumentContext,
    get_dhan_option_chain_fn: callable,
    expiry: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Get option chain for the instrument.

    Args:
        context: InstrumentContext with security_id, exchange_segment, current_expiry
        get_dhan_option_chain_fn: Reference to vob_minimal's get_dhan_option_chain
        expiry: Specific expiry date; defaults to context.current_expiry

    Returns:
        Option chain response dict or None on failure
    """
    try:
        if not expiry:
            expiry = context.current_expiry

        return get_dhan_option_chain_fn(
            underlying_scrip=context.security_id,
            underlying_seg=context.exchange_segment,
            expiry=expiry
        )
    except Exception as e:
        _logger.error(
            f"Failed to fetch {context.symbol} option chain ({expiry}): {e}"
        )
        return None


def get_expiry_list(
    context: InstrumentContext,
    get_dhan_expiry_list_cached_fn: callable,
) -> List[str]:
    """Get available expiry dates for the instrument.

    Args:
        context: InstrumentContext with security_id and exchange_segment
        get_dhan_expiry_list_cached_fn: Reference to vob_minimal's get_dhan_expiry_list_cached

    Returns:
        List of expiry date strings; empty list on failure
    """
    try:
        response = get_dhan_expiry_list_cached_fn(
            underlying_scrip=context.security_id,
            underlying_seg=context.exchange_segment
        )
        if isinstance(response, list):
            return response
        return []
    except Exception as e:
        _logger.error(f"Failed to fetch {context.symbol} expiry list: {e}")
        return []


def format_instrument_message(
    context: InstrumentContext,
    message: str,
    include_symbol: bool = True,
) -> str:
    """Prepend instrument name to message for clarity.

    When sending Telegram alerts, messages should clearly state which instrument
    they refer to, especially when toggling between NIFTY and SENSEX.

    Args:
        context: InstrumentContext with symbol
        message: Message text
        include_symbol: If True, prepend "[NIFTY]" or "[SENSEX]" to message

    Returns:
        Message with instrument prefix if requested
    """
    if not include_symbol:
        return message

    prefix = f"[{context.symbol}] "
    if message.startswith(prefix):
        return message  # Already prefixed

    return prefix + message


def get_atm_strike(
    context: InstrumentContext,
    spot: float,
) -> int:
    """Calculate ATM strike for the instrument.

    Args:
        context: InstrumentContext with strike_step
        spot: Current spot price

    Returns:
        Nearest strike to spot (rounded by strike_step)
    """
    try:
        if not spot or spot <= 0:
            return None

        # Round to nearest strike_step
        atm = round(spot / context.strike_step) * context.strike_step
        return int(atm)
    except Exception as e:
        _logger.error(f"Failed to calculate ATM for {context.symbol}: {e}")
        return None


def get_strike_range(
    context: InstrumentContext,
    spot: float,
) -> tuple:
    """Get upper and lower strike range for ATM legs.

    Args:
        context: InstrumentContext with atm_range and strike_step
        spot: Current spot price

    Returns:
        Tuple of (lower_strike, upper_strike) for ATM±range legs
    """
    try:
        atm = get_atm_strike(context, spot)
        if not atm:
            return None, None

        lower = atm - context.atm_range
        upper = atm + context.atm_range

        return int(lower), int(upper)
    except Exception as e:
        _logger.error(
            f"Failed to calculate strike range for {context.symbol}: {e}"
        )
        return None, None


def instrument_symbol_for_message(context: InstrumentContext) -> str:
    """Get emoji + symbol for use in messages.

    Returns a formatted string suitable for Telegram/Discord messages.

    Args:
        context: InstrumentContext with symbol

    Returns:
        Formatted string like "📊 NIFTY" or "📊 SENSEX"
    """
    emoji = "📊"  # Could be different per instrument
    return f"{emoji} {context.symbol}"
