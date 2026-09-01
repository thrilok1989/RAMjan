"""🧲 The dealer magnet, on every day — not only on expiry.

## Why this module exists rather than an edit

`charm_pin.py` opens with `if not is_expiry_day: return {"active": False}`. That
gate was right about the physics and wrong about the usefulness:

* **Right about the physics.** Charm is the decay of delta as time runs out, so
  the hedging drag it produces is strongest in the last hours of an expiry and
  much weaker with days left. Reporting an expiry-strength pin on a Monday would
  be a fabricated edge.
* **Wrong about the usefulness.** The magnet itself — the heaviest CE+PE strike,
  or max pain — is a real level on *every* day. Dealers are positioned there all
  week. Price gravitates toward it, just less violently.

So the read is wanted on normal days, with wording that does not overclaim.

`charm_pin.py` is deliberately left **exactly as it was**. This module does not
copy its arithmetic: it calls `charm_pin.read()` with the expiry gate satisfied so
that module still owns the pin strike, the distance, the drift word, the `near`
threshold and the net-charm handling — then re-words the *consequence* for a
non-expiry day. One implementation of the rule, two ways of saying what it means.

⚠️ On an expiry day the return value is `charm_pin.read()`'s output **unchanged**,
so nothing about expiry behaviour moves. A test asserts byte equality.

## What changes off expiry

    expiry day     "Breakouts likely to fade; small dips are noise near the pin."
    normal day     "A level dealers defend, not a ceiling — the pull is weaker
                    than on expiry."

The magnet, the distance, the drift and the charm figure are identical. Only the
instruction differs, because only the strength differs.

Context only, on both days. `context_only` stays `True` and this never touches a
Guardian verdict — the same promise `charm_pin` makes.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from .charm_pin import NEAR_POINTS, from_market_picture as _cp_from_mp
from .charm_pin import read as _cp_read

#: What a normal-day magnet means, as an instruction rather than theory.
#:
#: Deliberately weaker than the expiry sentence. A magnet 4 days out is a level
#: dealers defend; it is not the ceiling it becomes on expiry afternoon, and
#: saying otherwise would invent an edge out of a calendar.
NORMAL_EXPECT = ("A level dealers defend, not a ceiling — the pull is weaker "
                 "than on expiry.")

#: The heading each day gets.
TITLE_EXPIRY = "Expiry charm-pin"
TITLE_NORMAL = "Dealer magnet"


def read(is_expiry_day: bool, spot: Any, pin: Any = None,
         net_charm: Any = None, pin_label: Optional[str] = None,
         near_points: float = NEAR_POINTS,
         days_to_expiry: Any = None) -> Dict[str, Any]:
    """The magnet read, active on any day. `charm_pin` does the measuring.

    ⚠️ `_cp_read` is called with `True` for the expiry flag on purpose, and it is
    the only liberty taken: that argument is a *gate*, not an input to any
    calculation inside it, so satisfying it yields the same distance, drift and
    `near` decision it would give on expiry. Everything that depends on the day
    is re-worded here, where it can be read.
    """
    out = dict(_cp_read(True, spot, pin, net_charm, pin_label, near_points))
    out["expiry"] = bool(is_expiry_day)
    if not out.get("active"):
        return out

    if is_expiry_day:
        # Byte-identical to `charm_pin` on expiry day, plus the two new labels.
        out["title"] = TITLE_EXPIRY
        out["strength"] = "STRONG"
        return out

    out["title"] = TITLE_NORMAL
    out["strength"] = "MODERATE"
    out["expect"] = NORMAL_EXPECT
    # The sentence keeps `charm_pin`'s facts and drops the word "drags", which
    # overclaims off expiry. Same numbers, calmer verb.
    out["sentence"] = out["sentence"].replace(
        "Dealer hedging drags price toward the magnet",
        "Price tends to gravitate toward the dealer magnet")
    days = _days(days_to_expiry)
    if days is not None:
        out["days_to_expiry"] = days
        out["sentence"] = out["sentence"].rstrip(".") + (
            f" · {days:.0f} day{'s' if days >= 2 else ''} to expiry.")
    return out


def _days(v: Any) -> Optional[float]:
    try:
        d = float(v)
    except (TypeError, ValueError):
        return None
    return None if d != d or d < 0 else d


def from_market_picture(is_expiry_day: bool, spot: Any,
                        market_picture: Optional[Dict[str, Any]] = None,
                        max_pain: Any = None,
                        days_to_expiry: Any = None) -> Dict[str, Any]:
    """The app-shaped entry point, mirroring `charm_pin.from_market_picture`.

    ⚠️ Delegates the pin CHOICE to `charm_pin` — OI pin first, max pain second —
    rather than repeating that preference here. Two modules disagreeing about
    which strike is the magnet would be worse than not showing one.
    """
    out = dict(_cp_from_mp(True, spot, market_picture, max_pain))
    out["expiry"] = bool(is_expiry_day)
    if not out.get("active"):
        return out
    if is_expiry_day:
        out["title"] = TITLE_EXPIRY
        out["strength"] = "STRONG"
        return out
    # Re-word through `read` so the normal-day text lives in exactly one place.
    return read(False, spot, out.get("pin"), out.get("net_charm"),
                out.get("pin_label"), days_to_expiry=days_to_expiry)
