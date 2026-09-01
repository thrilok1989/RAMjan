"""Which scrip-master rows belong to which index, and where its legs quote.

The LTP panels are the ATM Call/Put option charts. Pointing them at SENSEX
means resolving SENSEX option security ids and quoting them on the right
segment; both are silent when wrong — you get an empty panel, or worse, a
panel of somebody else's strikes — so both are pinned here.
"""

from __future__ import annotations

import pytest

from mios_v5.index_option_specs import (
    INDEX_OPTION_SPECS,
    belongs_to,
    index_option_segment,
    option_spec,
    symbol_head,
)


# ── the segment legs quote on ──────────────────────────────────────────

def test_sensex_legs_quote_on_bse_fno():
    assert index_option_segment("SENSEX") == "BSE_FNO"


def test_nifty_legs_quote_on_nse_fno():
    assert index_option_segment("NIFTY") == "NSE_FNO"


def test_no_index_quotes_its_options_on_idx_i():
    """IDX_I carries the spot index only. A leg quoted against it returns
    nothing, which renders as an empty LTP panel with no error."""
    for symbol in INDEX_OPTION_SPECS:
        assert index_option_segment(symbol) != "IDX_I"


def test_unknown_symbol_falls_back_to_nifty():
    assert index_option_segment("BANKEX") == "NSE_FNO"
    assert option_spec("nonsense")["prefix"] == "NIFTY"


def test_symbol_lookup_is_case_insensitive():
    assert index_option_segment("sensex") == "BSE_FNO"
    assert option_spec("SeNsEx")["exchange"] == "BSE"


# ── the prefix rule ────────────────────────────────────────────────────

def test_symbol_head_takes_the_instrument_only():
    assert symbol_head("SENSEX-Sep2026-68000-CE") == "SENSEX"
    assert symbol_head("NIFTY-Aug2026-24500-PE") == "NIFTY"


@pytest.mark.parametrize("trading_symbol", [
    "SENSEX-Sep2026-68000-CE",
    "SENSEX-Aug2026-81000-PE",
])
def test_sensex_rows_are_claimed_by_sensex(trading_symbol):
    assert belongs_to(trading_symbol, "SENSEX")


@pytest.mark.parametrize("impostor", [
    "SENSEX50-Sep2026-2400-CE",   # BSE lists this alongside SENSEX
    "BANKEX-Sep2026-58000-CE",
    "FOCIT-Sep2026-12000-CE",
])
def test_sensex_does_not_claim_its_lookalikes(impostor):
    """`contains("SENSEX")` would take SENSEX50 — mixing a ~2,400-point index's
    strikes into an ~81,000-point one, so the "ATM" leg is whichever strike
    happens to sit nearest. An exact head match is the whole guard."""
    assert not belongs_to(impostor, "SENSEX")


@pytest.mark.parametrize("impostor", [
    "BANKNIFTY-Aug2026-55000-CE",
    "FINNIFTY-Aug2026-26000-PE",
    "MIDCPNIFTY-Aug2026-13000-CE",
    "NIFTYNXT50-Aug2026-68000-CE",
])
def test_nifty_does_not_claim_its_lookalikes(impostor):
    assert not belongs_to(impostor, "NIFTY")


def test_the_two_instruments_never_claim_each_other():
    assert not belongs_to("SENSEX-Sep2026-81000-CE", "NIFTY")
    assert not belongs_to("NIFTY-Aug2026-24500-CE", "SENSEX")


def test_every_spec_is_complete():
    for symbol, spec in INDEX_OPTION_SPECS.items():
        assert set(spec) == {"exchange", "prefix", "segment"}, symbol
        assert spec["exchange"] in ("NSE", "BSE"), symbol
