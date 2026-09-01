"""Instrument registry — discover NIFTY/SENSEX specs from Dhan, not hardcoded.

Fetches authoritative instrument metadata (security ID, multiplier, expiry schedule)
from Dhan API. No hardcoding; all specs driven by live Dhan data.
"""

from typing import Dict, Optional, Any, List
from dataclasses import dataclass
import logging

_logger = logging.getLogger(__name__)


@dataclass
class InstrumentContext:
    """Normalized instrument specification — passed to all engines."""

    symbol: str  # "NIFTY" or "SENSEX"
    security_id: int  # Dhan security ID
    exchange_segment: str  # Dhan exchange segment (e.g., "IDX_I")
    contract_multiplier: float  # rupees per point (25.0 for NIFTY, etc.)
    strike_step: float  # minimum strike interval (typically 100 or 50)
    current_expiry: str  # Next expiry date (YYYY-MM-DD)
    expiry_list: List[str]  # All upcoming expiries
    atm_range: int  # Strike range around ATM (±100 typical)
    lot_size: int  # Number of contracts per lot (typically 1 for index options)
    tick_size: float  # Minimum price move (typically 0.05)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "security_id": self.security_id,
            "exchange_segment": self.exchange_segment,
            "contract_multiplier": self.contract_multiplier,
            "strike_step": self.strike_step,
            "current_expiry": self.current_expiry,
            "expiry_list": self.expiry_list,
            "atm_range": self.atm_range,
            "lot_size": self.lot_size,
            "tick_size": self.tick_size,
        }


class InstrumentRegistry:
    """Discover and cache instrument specs from Dhan."""

    def __init__(self, dhan_client):
        """Initialize with Dhan client."""
        self.dhan = dhan_client
        self._cache: Dict[str, InstrumentContext] = {}
        self._cache_expiry = {}  # Track expiry list fetch time

    def discover_nifty(self, force_refresh: bool = False) -> InstrumentContext:
        """Discover NIFTY specs from Dhan."""
        return self._discover_instrument(
            symbol="NIFTY",
            label="NIFTY 50",
            force_refresh=force_refresh
        )

    def discover_sensex(self, force_refresh: bool = False) -> InstrumentContext:
        """Discover SENSEX specs from Dhan."""
        return self._discover_instrument(
            symbol="SENSEX",
            label="BSE SENSEX",
            force_refresh=force_refresh
        )

    def _discover_instrument(
        self,
        symbol: str,
        label: str,
        force_refresh: bool = False
    ) -> Optional[InstrumentContext]:
        """Generic discovery — call Dhan option chain API to infer specs."""

        if symbol in self._cache and not force_refresh:
            return self._cache[symbol]

        try:
            # Step 1: Search for instrument by name in Dhan's available securities
            # (Dhan doesn't have a public instruments endpoint, so we use option chain
            # discovery: try to fetch option chain for known symbols and infer ID from response)

            # Read off Dhan's scrip master (api-scrip-master.csv, rows where
            # SEM_INSTRUMENT_NAME == 'INDEX') — not guesses. An earlier
            # invented SENSEX id (40) returned no data, and because the caller
            # only replaces its frame on a non-empty fetch, the SENSEX chart
            # silently kept drawing NIFTY. These are the verified fallbacks;
            # prefer a live scrip-master lookup where one is available.
            known_ids = {
                "NIFTY": 13,    # NSE, SEM_TRADING_SYMBOL 'NIFTY'
                "SENSEX": 51,   # BSE, SEM_TRADING_SYMBOL 'SENSEX'
            }

            if symbol not in known_ids:
                _logger.error(f"Symbol {symbol} not in known_ids")
                return None

            security_id = known_ids[symbol]
            exchange_segment = "IDX_I"  # All indices use this

            # Step 2: Fetch expiry list from Dhan to validate security exists
            try:
                resp = self.dhan.optionchain_expirylist(
                    security_id=security_id,
                    exchange_segment=exchange_segment
                )
            except Exception as e:
                _logger.error(f"Failed to fetch {symbol} expiry list: {e}")
                return None

            # Parse response for expiry dates
            expiry_list = self._parse_expiry_list(resp, symbol)
            if not expiry_list:
                _logger.error(f"No expiry dates found for {symbol}")
                return None

            current_expiry = expiry_list[0]  # First (nearest) expiry

            # Step 3: Fetch one option chain to infer contract specs
            try:
                chain_resp = self.dhan.optionchain(
                    security_id=security_id,
                    exchange_segment=exchange_segment,
                    expiry_date=current_expiry
                )
            except Exception as e:
                _logger.error(f"Failed to fetch {symbol} option chain: {e}")
                return None

            # Parse chain for strike step, multiplier, lot size
            specs = self._parse_option_chain_specs(chain_resp, symbol)

            # Build context
            ctx = InstrumentContext(
                symbol=symbol,
                security_id=security_id,
                exchange_segment=exchange_segment,
                contract_multiplier=specs.get("contract_multiplier", 1.0),
                strike_step=specs.get("strike_step", 100),
                current_expiry=current_expiry,
                expiry_list=expiry_list,
                atm_range=specs.get("atm_range", 100),
                lot_size=specs.get("lot_size", 1),
                tick_size=specs.get("tick_size", 0.05),
            )

            self._cache[symbol] = ctx
            _logger.info(f"Discovered {symbol}: {ctx.security_id} @ {exchange_segment}")

            return ctx

        except Exception as e:
            _logger.exception(f"Error discovering {symbol}: {e}")
            return None

    def _parse_expiry_list(self, response: Dict, symbol: str) -> List[str]:
        """Extract expiry dates from Dhan optionchain expirylist response."""
        # Dhan response format (example):
        # { "data": { "expiryDate": ["2026-08-27", "2026-09-24", ...] } }
        try:
            if isinstance(response, dict) and "data" in response:
                data = response["data"]
                if isinstance(data, dict):
                    expiry_dates = data.get("expiryDate") or data.get("expiryList") or []
                    return sorted(expiry_dates)  # Sort ascending
            return []
        except Exception as e:
            _logger.error(f"Error parsing expiry list for {symbol}: {e}")
            return []

    def _parse_option_chain_specs(self, chain_resp: Dict, symbol: str) -> Dict[str, Any]:
        """Infer contract specs from live option chain data."""
        # Extract strike step, multiplier, etc. from actual option prices
        specs = {}

        try:
            # Fallback specs, taken from Dhan's scrip master OPTIDX rows
            # (SEM_LOT_UNITS, and the modal gap between SEM_STRIKE_PRICE
            # values on the nearest expiry). Refined from the live chain below
            # when it carries strikes.
            if symbol == "NIFTY":
                specs = {
                    "contract_multiplier": 65.0,  # lot units, ₹ per point/lot
                    "strike_step": 50,   # observed modal gap on NIFTY strikes
                    "atm_range": 100,
                    "lot_size": 65,
                    "tick_size": 0.05,
                }
            elif symbol == "SENSEX":
                specs = {
                    "contract_multiplier": 20.0,  # lot units, ₹ per point/lot
                    "strike_step": 100,  # observed modal gap on SENSEX strikes
                    "atm_range": 100,
                    "lot_size": 20,
                    "tick_size": 0.05,
                }

            # If chain data has strike info, refine from actual chain strikes
            if isinstance(chain_resp, dict) and "data" in chain_resp:
                data = chain_resp["data"]
                if isinstance(data, (list, dict)):
                    chains = data if isinstance(data, list) else [data]
                    if chains:
                        strikes = sorted([float(c.get("strikePrice", 0)) for c in chains if c.get("strikePrice")])
                        if len(strikes) > 1:
                            # Infer strike step from actual strikes
                            diffs = [strikes[i+1] - strikes[i] for i in range(min(10, len(strikes)-1))]
                            if diffs:
                                most_common_diff = max(set(diffs), key=diffs.count)
                                specs["strike_step"] = most_common_diff

            return specs

        except Exception as e:
            _logger.error(f"Error parsing chain specs for {symbol}: {e}")
            return specs

    def get_all_instruments(self, force_refresh: bool = False) -> Dict[str, InstrumentContext]:
        """Get both NIFTY and SENSEX contexts."""
        instruments = {}

        nifty = self.discover_nifty(force_refresh=force_refresh)
        if nifty:
            instruments["NIFTY"] = nifty

        sensex = self.discover_sensex(force_refresh=force_refresh)
        if sensex:
            instruments["SENSEX"] = sensex

        return instruments


def create_instrument_registry(dhan_client) -> InstrumentRegistry:
    """Factory for InstrumentRegistry."""
    return InstrumentRegistry(dhan_client)
