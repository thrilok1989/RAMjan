"""The published OrderFlowSnapshot — one object, read by every V6 engine.

## The contract

    Calculation (V5)  →  published once  →  shared object  →  many consumers

Not:

    Calculation · Calculation · Calculation · Calculation

Every order-flow fact has exactly one owner. The owner computes it; this module
carries it; engines read it as a **parameter**. No engine reaches into
`session_state` for a market fact — an engine that does has hidden inputs, and
hidden inputs cannot be tested, replayed or explained.

## Missing is not zero

A member that was not measured is `MISSING`, never `0.0`. Zero is a market fact
— perfectly balanced flow — and asserting one that was never observed is
inventing data. Engines check and degrade; they never receive a fabricated
number they cannot distinguish from a real one.

## What this module does NOT do

It does not calculate. Every value arrives already computed by V5. There is no
`cvd_v6()`, `money_flow_v6()`, `vpfr_v6()` or `vob_v6()` here or anywhere —
`test_no_duplicate_order_flow_engine_exists` fails the build if one appears.

See `docs/ARCHITECTURE_PRINCIPLES.md`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from indicators.order_flow import MISSING, is_missing

#: every fact the snapshot carries, and who owns it in V5.
OWNERS: Dict[str, str] = {
    "money_flow": "indicators/money_flow_profile.py::calculate_money_flow_profile",
    "candle_delta": "indicators/volume_delta.py::calculate_volume_delta",
    "cvd": "indicators/order_flow.py::cvd_sum",
    "cvd_sign": "indicators/order_flow.py::cvd_sign",
    "cbv": "indicators/order_flow.py::cumulative(kind='buy')",
    "csv": "indicators/order_flow.py::cumulative(kind='sell')",
    "buy_volume": "indicators/order_flow.py::totals",
    "sell_volume": "indicators/order_flow.py::totals",
    "volume": "candle frame `volume` column",
    "vpfr": "vob_minimal.py::compute_vpfr",
    "vob": "vob_minimal.py::analyze_vob_volume",
}

FIELDS = tuple(OWNERS)


def empty(instrument: str = "NIFTY") -> Dict[str, Any]:
    """A snapshot in which nothing has been measured.

    Every field is `MISSING` — deliberately, so a consumer that forgets to
    check gets a falsy sentinel rather than a plausible zero.
    """
    snap: Dict[str, Any] = {name: MISSING for name in FIELDS}
    snap["instrument"] = instrument
    snap["complete"] = False
    snap["missing"] = list(FIELDS)
    return snap


def build(instrument: str = "NIFTY", **values: Any) -> Dict[str, Any]:
    """Assemble a snapshot from values V5 already computed.

    Unknown keyword names are rejected rather than silently carried: a typo'd
    field would otherwise read as `MISSING` forever, and the engine consuming
    it would degrade quietly and permanently — the failure mode this whole
    module exists to prevent.
    """
    unknown = set(values) - set(FIELDS)
    if unknown:
        raise KeyError(f"unknown order-flow field(s): {sorted(unknown)}. "
                       f"Known: {sorted(FIELDS)}")

    snap: Dict[str, Any] = {}
    missing = []
    for name in FIELDS:
        v = values.get(name, MISSING)
        if v is None:
            v = MISSING
        snap[name] = v
        if is_missing(v):
            missing.append(name)

    snap["instrument"] = instrument
    snap["missing"] = missing
    snap["complete"] = not missing
    return snap


def get(snapshot: Optional[Dict[str, Any]], field: str, default: Any = MISSING):
    """Read one field. Returns `MISSING` — never `0` — when unmeasured."""
    if field not in FIELDS:
        raise KeyError(f"unknown order-flow field: {field}")
    if not snapshot:
        return default
    v = snapshot.get(field, default)
    return default if v is None else v


def present(snapshot: Optional[Dict[str, Any]]) -> int:
    """How many of the facts were actually measured."""
    if not snapshot:
        return 0
    return sum(1 for f in FIELDS if not is_missing(snapshot.get(f, MISSING)))


def owner_of(field: str) -> str:
    """Who computes this fact. One answer, by construction."""
    if field not in OWNERS:
        raise KeyError(f"unknown order-flow field: {field}")
    return OWNERS[field]


def describe(snapshot: Optional[Dict[str, Any]]) -> str:
    n = present(snapshot)
    inst = (snapshot or {}).get("instrument", "—")
    if not n:
        return f"{inst}: no order-flow fact measured yet."
    miss = (snapshot or {}).get("missing") or []
    tail = f" · missing: {', '.join(miss)}" if miss else " · complete"
    return f"{inst}: {n}/{len(FIELDS)} order-flow facts measured{tail}."
