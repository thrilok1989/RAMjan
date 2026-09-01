"""Where each index's option legs live in Dhan's scrip master.

Pure lookup — no fetching, no Streamlit — so the rules that decide which rows
belong to which instrument are testable on their own. `vob_minimal` imports
this and applies it to the scrip-master frame.

The prefix rule is the part that matters. Both exchanges list a *second*
instrument whose name contains the first:

    NSE   NIFTY      and BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50
    BSE   SENSEX     and SENSEX50

A substring match ("does the symbol contain SENSEX?") takes both, so the leg
map ends up holding two instruments' strikes and the ATM lookup picks whichever
happens to sit nearest the spot. Matching the symbol *up to the first hyphen*
is exact, and Dhan's trading symbols are shaped `SENSEX-Sep2026-68000-CE`, so
the head of that split is the instrument and nothing else.
"""

from __future__ import annotations

from typing import Dict


#: Per instrument: the scrip master's SEM_EXM_EXCH_ID, the exact
#: SEM_TRADING_SYMBOL head, and the Dhan exchangeSegment its options quote on.
#:
#: Index OPTIONS trade on the exchange's F&O segment — NSE_FNO / BSE_FNO — not
#: on IDX_I. IDX_I carries the spot index only, so quoting a leg against it
#: returns nothing.
INDEX_OPTION_SPECS: Dict[str, Dict[str, str]] = {
    "NIFTY":  {"exchange": "NSE", "prefix": "NIFTY",  "segment": "NSE_FNO"},
    "SENSEX": {"exchange": "BSE", "prefix": "SENSEX", "segment": "BSE_FNO"},
}

DEFAULT_SYMBOL = "NIFTY"


def option_spec(symbol) -> Dict[str, str]:
    """The scrip-master spec for `symbol`, falling back to NIFTY."""
    return INDEX_OPTION_SPECS.get(str(symbol).upper()) or INDEX_OPTION_SPECS[DEFAULT_SYMBOL]


def index_option_segment(symbol) -> str:
    """The Dhan exchangeSegment this index's option legs quote on."""
    return option_spec(symbol)["segment"]


def symbol_head(trading_symbol) -> str:
    """The instrument part of a Dhan option trading symbol.

    `SENSEX-Sep2026-68000-CE` -> `SENSEX`
    """
    return str(trading_symbol).upper().strip().split("-")[0].strip()


def belongs_to(trading_symbol, symbol) -> bool:
    """True when this scrip-master row is `symbol`'s option, exactly.

    Deliberately an equality on the symbol head, never a substring test —
    see the module docstring for what a substring test silently mixes in.
    """
    return symbol_head(trading_symbol) == option_spec(symbol)["prefix"]
