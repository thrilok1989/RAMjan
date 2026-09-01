"""MIOS V6 — the expiry-day charm pin, as one shared read.

On expiry day the option chain stops being a forecast and becomes a force.
Dealers who are short gamma around the max-pain / max-OI strike must hedge into
every move, and charm — the decay of delta as time runs out — drags their hedge
back toward that strike all day. The practical consequence for a trader is
narrow and specific:

    **breakouts fade, and small dips near the pin are noise, not signal.**

This is *context*, never a vote. It does not change the Guardian verdict, it
does not change the MIOS bias, and it must never be allowed to. A pin says
where price is being pulled; it says nothing about who is winning. The moment
this becomes an input to a directional read, every expiry day starts producing
a fabricated edge.

The read used to live inline in the Guardian panel only, so the Trade Card —
the one view a trader actually glances at — never showed it. Extracting it here
means both render the same numbers from the same rule, and neither can drift.

Pure module.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

#: how close spot must be for the pin to actually be exerting force. Beyond
#: this the dealer hedge is not meaningfully anchored to the strike, and
#: showing "pinned" would be superstition.
NEAR_POINTS = 120.0

#: net charm (in lakhs/day) below which the drag is too weak to call a pin
MIN_ABS_CHARM = 0.0


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def read(is_expiry_day: bool, spot: Any, pin: Any = None,
         net_charm: Any = None, pin_label: Optional[str] = None,
         near_points: float = NEAR_POINTS) -> Dict[str, Any]:
    """The charm-pin read, or `{"active": False}` with the reason it is not.

    `pin` is the magnet strike — max-OI pin first, max pain as a fallback.
    `net_charm` is the chain's net charm exposure in lakhs/day; it is optional
    because the drag exists whether or not the greek is computable, and
    withholding the whole read for a missing number would be worse than showing
    it without one.
    """
    sp, pn = _f(spot), _f(pin)
    if not is_expiry_day:
        return {"active": False, "reason": "not expiry day"}
    if sp is None or pn is None:
        return {"active": False, "reason": "no pin strike available"}
    dist = pn - sp
    if abs(dist) > near_points:
        return {"active": False, "reason": f"pin ₹{pn:,.0f} is "
                                           f"{abs(dist):.0f} pts away",
                "pin": pn, "distance": round(dist, 1)}

    chm = _f(net_charm)
    drift = ("above spot — upward drag" if dist > 0 else
             "below spot — downward drag" if dist < 0 else "at spot")
    return {
        "active": True,
        "pin": pn,
        "pin_label": pin_label,
        "distance": round(dist, 1),
        "drift": drift,
        "net_charm": chm,
        # the two consequences, stated as instructions rather than theory
        "expect": "Breakouts likely to fade; small dips are noise near the pin.",
        "context_only": True,
        "sentence": (
            f"Dealer hedging drags price toward the magnet ₹{pn:,.0f} ({drift})"
            + (f" · net charm {chm:+.1f}L/day" if chm is not None else "")
            + "."),
    }


def from_market_picture(is_expiry_day: bool, spot: Any,
                        market_picture: Optional[Dict[str, Any]] = None,
                        max_pain: Any = None) -> Dict[str, Any]:
    """Convenience wrapper over the app's `_market_picture` shape.

    Prefers the OI pin (where dealers are actually positioned) over max pain
    (where the chain says pain is minimised) — they usually agree, and when
    they don't, the OI wall is the one price reacts to.
    """
    mp = market_picture or {}
    pin, label = None, None
    op: Optional[Sequence[Any]] = mp.get("oi_pin")
    if op:
        try:
            pin, label = _f(op[0]), (op[1] if len(op) > 1 else None)
        except (TypeError, IndexError):
            pin, label = None, None
    if pin is None:
        pin = _f(max_pain)
        label = "max pain" if pin is not None else None
    return read(is_expiry_day, spot, pin,
                (mp.get("vc_exp") or {}).get("net_charm"), pin_label=label)
