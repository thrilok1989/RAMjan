"""The day's futures open interest, measured from the day's own anchor.

**A producer, not an engine.** It publishes one fact nothing else in MIOS
publishes — how far today's NIFTY futures open interest has moved from where it
started — and the classical reading of that move against price.

## Why this exists

`get_nifty_futures_data()` already computes an OI change:

```python
prev = st.session_state.get('_nifty_fut_prev_oi')
chg_oi = (oi - prev) if (prev is not None and oi) else 0.0
```

That is the delta since the previous ~20-second refresh, held in
`session_state`. It is the wrong quantity for the question, and it fails
silently: when the app restarts, `prev` is gone and `chg_oi` reports `0.0` —
which is indistinguishable from *open interest did not move*.

Short Covering (*"futures up, OI falling"*) and Long Unwinding (*"price down,
OI down"*) are claims about **the day**. This module answers them against a
stored anchor that survives a restart.

## The four states are futures states, and Stage 13 is not their owner

Stage 13 — Institutional Position — publishes per-side **option-chain**
positioning modes with similar names. These are not the same fact:

| | Stage 13 | here |
|---|---|---|
| instrument | option chain, per strike side | **NIFTY futures**, one contract |
| basis | OI by strike | day OI vs the day's anchor |

The names are classical and belong to neither module — so this one prefixes
its field `futures_oi_state`, and a consumer reading both sees two instruments
rather than one contradiction.

## It computes nothing it can get

Price, OI, basis and the symbol all arrive from the caller. There is no fetch,
no database client and no `session_state` here — the anchor is *passed in*. A
producer that reached for its own inputs would be a second futures owner.

## UNKNOWN, never zero

A missing anchor, a missing OI, a zero OI (which Dhan returns when the quote
carries no open-interest field at all) and a contract that does not match the
anchor's symbol each report `UNKNOWN`. **The last one matters most**: after
rollover the near-month symbol changes and its OI is a different series, so
comparing across that boundary would read a contract switch as a collapse in
open interest.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

UNKNOWN = "UNKNOWN"

VERSION = "71.90.0"

ADVISORY_ONLY = True

#: The facts this module owns. Nothing else in MIOS publishes any of them.
COMPUTED_HERE: Tuple[str, ...] = (
    "day_oi_change", "day_oi_pct", "day_price_change",
    "futures_oi_state", "oi_direction", "price_direction",
)

#: Every consumed fact and the one thing that owns it.
CONSUMED: Mapping[str, str] = MappingProxyType({
    "oi": "get_nifty_futures_data (vob_minimal) — the Dhan futures quote",
    "price": "get_nifty_futures_data",
    "basis": "get_nifty_futures_data — price minus spot",
    "symbol": "get_nifty_futures_security_id — the near-month FUTIDX",
    "open_oi": "db/futures_oi_store — the day's stored anchor",
})

# ══════════════════════════════════════════════════════════════════════
#  the four classical states
# ══════════════════════════════════════════════════════════════════════

LONG_BUILDUP = "Long Build-up"        # price ↑  OI ↑ — new longs
SHORT_BUILDUP = "Short Build-up"      # price ↓  OI ↑ — new shorts
SHORT_COVERING = "Short Covering"     # price ↑  OI ↓ — shorts closing
LONG_UNWINDING = "Long Unwinding"     # price ↓  OI ↓ — longs closing
FLAT = "Flat"                         # neither moved enough to say

STATES: Tuple[str, ...] = (LONG_BUILDUP, SHORT_BUILDUP, SHORT_COVERING,
                           LONG_UNWINDING, FLAT)

LABEL: Mapping[str, str] = MappingProxyType({
    LONG_BUILDUP: "🟢 Long Build-up", SHORT_BUILDUP: "🔴 Short Build-up",
    SHORT_COVERING: "🟡 Short Covering", LONG_UNWINDING: "🟠 Long Unwinding",
    FLAT: "⚪ Flat",
})

UP, DOWN, UNCHANGED = "Up", "Down", "Unchanged"

#: How much of the day's opening OI must have moved before the direction is
#: called. Open interest ticks constantly; without a band every cycle would
#: report a state and the reading would never be stable enough to act on.
_OI_BAND_PCT = 0.005          # 0.5% of the day's opening OI

#: …and the price band, in index points. NIFTY futures move a few points on
#: noise alone, and a state named from a 2-point drift is not a state.
_PRICE_BAND_POINTS = 10.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def reading_hash(reading_id: str, version: str, state: str,
                 created_at: str) -> str:
    return hashlib.sha256(
        "\x1f".join([str(reading_id), str(version), str(state),
                     str(created_at)]).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FuturesOI:
    """One cycle's day-anchored futures OI reading.

    Frozen, and every measurement that named the state is on the object — a
    state a reader cannot check against `day_oi_pct` and `day_price_change` is
    a label.
    """
    futures_oi_state: str
    oi_direction: Any
    price_direction: Any
    day_oi_change: Any
    day_oi_pct: Any
    day_price_change: Any
    open_oi: Any
    current_oi: Any
    open_price: Any
    current_price: Any
    basis: Any
    symbol: Any
    why: str
    reporting: int
    of: int
    id: str = ""
    version: str = VERSION
    created_at: str = ""
    hash: str = ""
    advisory_only: bool = ADVISORY_ONLY

    @property
    def label(self) -> str:
        return LABEL.get(self.futures_oi_state, self.futures_oi_state)

    def verify(self) -> bool:
        return self.hash == reading_hash(self.id, self.version,
                                         self.futures_oi_state,
                                         self.created_at)

    def identity(self) -> Dict[str, Any]:
        return {"id": self.id, "version": self.version,
                "created_at": self.created_at, "hash": self.hash}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "version": self.version,
            "created_at": self.created_at, "hash": self.hash,
            "futures_oi_state": self.futures_oi_state, "label": self.label,
            "oi_direction": self.oi_direction,
            "price_direction": self.price_direction,
            "day_oi_change": self.day_oi_change, "day_oi_pct": self.day_oi_pct,
            "day_price_change": self.day_price_change,
            "open_oi": self.open_oi, "current_oi": self.current_oi,
            "open_price": self.open_price, "current_price": self.current_price,
            "basis": self.basis, "symbol": self.symbol,
            "why": self.why, "reporting": self.reporting, "of": self.of,
            "advisory_only": self.advisory_only,
        }


def _blank(why: str, **known) -> FuturesOI:
    ident, created = str(uuid.uuid4()), _now_iso()
    fields = dict(
        futures_oi_state=UNKNOWN, oi_direction=UNKNOWN,
        price_direction=UNKNOWN, day_oi_change=UNKNOWN, day_oi_pct=UNKNOWN,
        day_price_change=UNKNOWN, open_oi=UNKNOWN, current_oi=UNKNOWN,
        open_price=UNKNOWN, current_price=UNKNOWN, basis=UNKNOWN,
        symbol=UNKNOWN)
    fields.update({k: v for k, v in known.items() if v is not None})
    return FuturesOI(why=why, reporting=0, of=2, id=ident, created_at=created,
                     hash=reading_hash(ident, VERSION, UNKNOWN, created),
                     **fields)


def read(quote: Optional[Mapping[str, Any]] = None,
         baseline: Optional[Mapping[str, Any]] = None) -> FuturesOI:
    """Today's futures OI against today's anchor.

    `quote` is `get_nifty_futures_data()`'s dict; `baseline` is the stored row
    for this trading day. Either missing, or disagreeing about the contract,
    reports `UNKNOWN` rather than a state.
    """
    q = dict(quote or {})
    b = dict(baseline or {})

    price = _f(q.get("price"))
    oi = _f(q.get("oi"))
    basis = _f(q.get("basis"))
    symbol = q.get("symbol")

    if not q:
        return _blank("no futures quote supplied")
    if not b:
        return _blank(
            "no baseline stored for today — the day's first futures quote "
            "has not been recorded yet",
            current_oi=oi, current_price=price, basis=basis, symbol=symbol)

    open_oi = _f(b.get("open_oi"))
    open_price = _f(b.get("open_price"))
    base_symbol = b.get("symbol")

    # Rollover: the anchor belongs to a contract, and near-month OI after a
    # roll is a different series. Comparing across it would read a contract
    # switch as a collapse in open interest.
    if symbol and base_symbol and str(symbol) != str(base_symbol):
        return _blank(
            f"the baseline is for {base_symbol} and the quote is for "
            f"{symbol} — a different contract, so the day's OI change is not "
            f"defined across it",
            current_oi=oi, current_price=price, basis=basis, symbol=symbol,
            open_oi=open_oi, open_price=open_price)

    # Dhan returns 0 when the quote carries no open-interest field at all, so
    # a zero is an absent reading rather than "no open interest".
    if not oi or not open_oi:
        return _blank(
            "open interest was not reported (the quote carries no OI field)",
            current_price=price, basis=basis, symbol=symbol,
            open_price=open_price)

    day_oi_change = oi - open_oi
    day_oi_pct = (day_oi_change / open_oi) if open_oi else None
    day_price_change = (price - open_price
                        if price is not None and open_price is not None
                        else None)

    oi_dir = (UP if day_oi_pct > _OI_BAND_PCT
              else DOWN if day_oi_pct < -_OI_BAND_PCT else UNCHANGED)

    if day_price_change is None:
        price_dir: Any = UNKNOWN
    elif day_price_change > _PRICE_BAND_POINTS:
        price_dir = UP
    elif day_price_change < -_PRICE_BAND_POINTS:
        price_dir = DOWN
    else:
        price_dir = UNCHANGED

    reporting = 2 - int(price_dir is UNKNOWN)

    if price_dir is UNKNOWN:
        state = UNKNOWN
        why = "the futures price change is unavailable, so the OI move alone " \
              "cannot name a state"
    elif oi_dir == UNCHANGED or price_dir == UNCHANGED:
        state = FLAT
        why = (f"OI {day_oi_pct:+.2%} and price {day_price_change:+.0f} — "
               f"neither moved enough from the day's open to name a state")
    else:
        state = {
            (UP, UP): LONG_BUILDUP, (DOWN, UP): SHORT_BUILDUP,
            (UP, DOWN): SHORT_COVERING, (DOWN, DOWN): LONG_UNWINDING,
        }[(price_dir, oi_dir)]
        why = (f"price {day_price_change:+.0f} with open interest "
               f"{day_oi_pct:+.2%} from the day's open")

    ident, created = str(uuid.uuid4()), _now_iso()
    return FuturesOI(
        futures_oi_state=state, oi_direction=oi_dir, price_direction=price_dir,
        day_oi_change=round(day_oi_change, 2),
        day_oi_pct=round(day_oi_pct * 100.0, 3),
        day_price_change=(round(day_price_change, 2)
                          if day_price_change is not None else UNKNOWN),
        open_oi=open_oi, current_oi=oi, open_price=open_price,
        current_price=price if price is not None else UNKNOWN,
        basis=basis if basis is not None else UNKNOWN,
        symbol=symbol or UNKNOWN, why=why, reporting=reporting, of=2,
        id=ident, created_at=created,
        hash=reading_hash(ident, VERSION, state, created))


def anchor_from(quote: Optional[Mapping[str, Any]] = None,
                trading_day: Any = None) -> Optional[Dict[str, Any]]:
    """The row to store as today's anchor, or `None` if this quote cannot be one.

    A quote with no OI is not an anchor. Storing one would fix `open_oi` at
    zero for the whole day and make every later reading a division by nothing.
    """
    q = dict(quote or {})
    oi = _f(q.get("oi"))
    if not oi or not q.get("symbol") or not trading_day:
        return None
    return {
        "trading_day": str(trading_day),
        "symbol": str(q.get("symbol")),
        "expiry": (str(q.get("expiry")) if q.get("expiry") else None),
        "open_oi": oi,
        "open_price": _f(q.get("price")),
        "open_basis": _f(q.get("basis")),
    }
