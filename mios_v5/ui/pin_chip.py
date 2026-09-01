"""🧲 The PIN veto, in its shortest form — the header's chip.

## What a pin is

`compute_market_picture` looks for the strike where the heaviest CE wall and the
heaviest PE wall **coincide** — within one strike gap of each other, and sitting
on spot within half a gap. That is not support and not resistance. It is a
magnet, and price around it chops.

The consequence is a veto, not a lean: the entry gate returns `PINNED` and skips
the directional logic outright. No CALL, no PUT, whatever else agrees.

## Why it needed to reach the header

It was computed, it was decided, and it was visible only in the Market Picture
panel far down the page. Principle 12 names that exactly — *consumed but
unpublished* — and the cost is specific rather than tidiness: the frozen header
strip carries the S/R odds and the war-zone winner right next to each other, and
both describe a directional contest. Read without the veto beside them, they
invite a trade the gate has already refused.

So the pin goes **first** in the extras row, ahead of the chips it contradicts.

## This module words the chip; it does not decide anything

`micro()` takes the entry gate the Market Picture already published. It adds the
glyph and answers "is there a pin to show?" — the same division of labour as
`zone_card.zone_micro`, `war_zone.micro` and `premium_energy_panel.micro`.

⚠️ **The sentence is the owner's, taken verbatim.** `compute_market_picture`
writes `entry_gate['why']`, and re-phrasing it here would be a second
implementation of one judgement — the header saying "pinned" while the panel
below says something subtly different about the same strike. Anything this file
adds beyond the glyph is a bug.

`mios_v5` may not import `vob_minimal`, and does not need to: the gate arrives
as a parameter, which is also what makes this testable without a market.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

#: The state `compute_market_picture` sets when price is pinned at a magnet.
PINNED = "PINNED"

#: Prefix, so the chip is findable on a crowded strip at a glance. Chosen to
#: match the other chips' one-glyph convention — 🛡 support, 🧱 resistance,
#: ⚔️ war zone, ⚡ premium energy.
GLYPH = "🧲"


def is_pinned(entry_gate: Optional[Any]) -> bool:
    """Did the gate return PINNED this cycle?

    Tolerant of the shapes this dict really arrives in — absent, `None`, a plain
    dict, or a frozen `MappingProxyType` — because a header may not raise, and
    `isinstance(x, dict)` is False for a `MappingProxyType`, which this repo has
    now been caught by three times.
    """
    if not isinstance(entry_gate, Mapping):
        return False
    return str(entry_gate.get("state") or "").strip().upper() == PINNED


def micro(entry_gate: Optional[Any]) -> str:
    """The one-line chip, or `""` when there is no pin to report.

    `""` rather than a placeholder: the strip is frozen at the top of every
    screen for the whole session, so a chip that says "not pinned" would cost
    that space permanently to report the normal case.
    """
    if not is_pinned(entry_gate):
        return ""
    for why in (entry_gate.get("why") or ()):
        text = str(why).strip()
        if text:
            return f"{GLYPH} {text}"
    # PINNED with nothing said about why. Still worth a chip — the veto is real
    # and a trader acting on the S/R odds beside it needs to know it is in
    # force — so fall back to the level, which the gate always carries.
    level = entry_gate.get("level")
    try:
        return (f"{GLYPH} pinned at ₹{float(level):.0f} — no directional edge, "
                f"WAIT")
    except (TypeError, ValueError):
        return f"{GLYPH} pinned — no directional edge, WAIT"
