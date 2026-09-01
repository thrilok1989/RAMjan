"""Instrument-aware cache invalidation.

When user switches instrument (NIFTY ↔ SENSEX), clear all
instrument-specific cached data to prevent cross-contamination.
"""

import logging

_logger = logging.getLogger(__name__)

# All session state keys that depend on current instrument
INSTRUMENT_DEPENDENT_KEYS = {
    # Live data
    "_nifty_spot_live",
    "_nifty_spot_live_ts",
    "_nifty_futures_data",
    "_nifty_fut_price",
    "_nifty_fut_prev_price",
    "_nifty_fut_prev_oi",
    "_nifty_day_pct",
    "_nifty_day_high",
    "_nifty_day_low",
    "_vwap",
    "_atr",

    # Candles
    "_df_5m",
    "_last_df",
    "_htf_daily_df",

    # Options chain
    "_cached_raw_chain",
    "_cached_raw_chain_latest",
    "_expiry_stale",
    "_atm_leg_api",
    "_atm_leg_dfs",
    "_atm_leg_sids",
    "_atm_leg_ltf_delta",
    "_atm_leg_vidya",
    "_atm_strike",

    # Greeks & indicators
    "_gex_data",
    "_iv_history",
    "_atm_pm1_vpfr",
    "_mp_detail",
    "_poc_series",
    "_poc_shift_prev",
    "_volume_delta_history",

    # Market analysis
    "_full_market_read",
    "_market_picture",
    "_market_structure",
    "_fmr_cache",
    "_pxoi_cache",

    # Futures & OI
    "_futures_oi",
    "_futures_oi_baseline",
    "_futures_oi_status",

    # Entry/Exit gate
    "_entry_gate_active",
    "_entry_gate_armed_sig",
    "_entry_gate_last_sig",
    "_entry_gate_last_result",
    "_gate_armed",

    # Alerts
    "_la_alert_state",
    "_confluence_alert_state",
    "_alert_counts_ts",
    "_alert_side_counts",

    # Levels & zones
    "_la_zones_latest",
    "_la_reset_keys",
    "_level_accept_mem",
    "_zone_rev_last_sig",

    # Dhan API state
    "_dhan_last_intraday_ts",
    "_dhan_last_error",

    # Caches
    "_cross_expiry_cache",
    "_leg_bias_cache",
    "_ms_cache",
    "_htf_profiles",

    # Analysis state
    "_layer_scores",
    "_layer_snap_logged",
    "_story_events_processed",
    "_all_bias_rows",
    "_leg_flow_snap_ts",
}


def invalidate_instrument_cache(session_state, instrument: str):
    """Clear all instrument-specific cached data.

    Call this when user switches from one instrument to another
    to prevent data leakage (e.g., NIFTY chain mixing with SENSEX calcs).
    """
    old_instrument = session_state.get("_selected_instrument")

    if old_instrument == instrument:
        # No change, don't clear
        return

    _logger.info(f"Instrument switch: {old_instrument} → {instrument}. Clearing cache.")

    for key in INSTRUMENT_DEPENDENT_KEYS:
        if key in session_state:
            try:
                del session_state[key]
            except Exception as e:
                _logger.warning(f"Failed to delete {key}: {e}")

    # Update instrument selection
    session_state["_selected_instrument"] = instrument

    _logger.info(f"Cache cleared for instrument switch. Now using: {instrument}")


def mark_instrument_changed(session_state, new_instrument: str):
    """Wrapper that also logs when instrument changes."""
    old = session_state.get("_selected_instrument", "NIFTY")
    if old != new_instrument:
        _logger.info(f"User switched to {new_instrument} (from {old})")
    invalidate_instrument_cache(session_state, new_instrument)


#: The instrument the app lands on before anything is selected. NIFTY, so a
#: fresh session opens on the same index every existing alert and engine
#: refers to; SENSEX is one click away on the sidebar toggle.
DEFAULT_INSTRUMENT = "NIFTY"


def get_current_instrument(session_state) -> str:
    """Get currently selected instrument, defaulting to DEFAULT_INSTRUMENT."""
    return session_state.get("_selected_instrument", DEFAULT_INSTRUMENT)


def instrument_changed_this_render(session_state) -> bool:
    """Check if instrument was switched in this render cycle."""
    old = session_state.get("_prev_selected_instrument")
    new = session_state.get("_selected_instrument", DEFAULT_INSTRUMENT)
    return old != new
