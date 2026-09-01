"""🗺️ MARKET STATE — the gate's verdict and the regime, on the header strip.

## What the two words are

They answer different questions, and putting them together is the point:

    entry_gate['state']   may I trade right now?   WAIT · CHOP_WAIT · NO_ROOM ·
                          AT_ZONE_WAIT · REVERSED · PINNED · ARMED_… · CALL/PUT
    market_picture['regime']  what is price doing?  UP · DOWN · SIDEWAYS

`CHOP_WAIT · regime SIDEWAYS` is a coherent reading — chop in a sideways tape,
stand down. `CHOP_WAIT · regime UP` is the more useful one: the trend is real and
the *entry* is bad, which is a wait for a pullback rather than a reason to fade.
Either word alone loses that.

## Why it belongs in the header

Both were computed every cycle and shown only in the Market Picture panel, far
enough down the page that the frozen strip could be advertising an S/R bounce and
a war-zone winner while the gate had already said no. That is the same
consumed-but-unpublished smell `pin_chip` was built for — principle 12.

⚠️ **`pin_chip` still goes first, and this chip stays quiet when it fires.**
`PINNED` is a veto and it already has its own chip with the strike in it; a second
chip repeating `MARKET STATE PINNED` would spend header space to say it twice.

## This module words the chip. It decides nothing.

The state and the regime arrive as parameters, already decided by
`compute_market_picture`. No thresholds here, no re-derivation, and nothing that
turns two published facts into a third opinion about them.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

#: Prefix, matching the strip's one-glyph convention — 🧲 pin, 🛡 support,
#: 🧱 resistance, ⚔️ war zone, ⚡ premium energy, ⚙️ dealer context.
GLYPH = "🗺️"

#: The state `pin_chip` already owns. Kept as a name rather than a literal so the
#: two modules cannot disagree about the spelling.
PINNED = "PINNED"

#: Gate states that mean "do not enter", so the chip can say so in a word a
#: trader reads faster than the state name.
#:
#: ⚠️ A mapping, not a rule: every value here is `compute_market_picture`'s own
#: vocabulary. Adding a state to this dict changes what the chip *says*, never
#: what the gate *decided*.
STAND_DOWN = {
    "WAIT": "no setup",
    "CHOP_WAIT": "chop — stand down",
    "NO_ROOM": "no room to target",
    "AT_ZONE_WAIT": "at zone, unconfirmed",
    "REVERSED": "zone failed",
}

#: Gate states that mean a setup is live. Armed is not entered — the distinction
#: is the whole of Stage 72's confirmation step, so the words keep it.
LIVE = {
    "ARMED_CALL": "armed CALL — awaiting confirmation",
    "ARMED_PUT": "armed PUT — awaiting confirmation",
    "CALL": "CALL confirmed",
    "PUT": "PUT confirmed",
}

#: Regime → the arrow that carries it without a second word.
REGIME_ARROW = {"UP": "↑", "DOWN": "↓", "SIDEWAYS": "→"}


def _word(src: Any, key: str) -> str:
    """One upper-cased string from a mapping that may be frozen or absent.

    Tolerant of `MappingProxyType`, which is **not** a `dict` subclass — this
    repo has been caught by `isinstance(x, dict)` on one four times now.
    """
    if not isinstance(src, Mapping):
        return ""
    return str(src.get(key) or "").strip().upper()


def read(entry_gate: Optional[Any] = None,
         market_picture: Optional[Any] = None) -> dict:
    """`{state, regime, phrase, live}` — the chip's inputs, resolved once.

    Separate from `micro` so the header chip and any longer panel that wants the
    same reading cannot phrase it two ways. `market_picture` may be passed whole;
    the regime is read off it rather than being asked for separately, so a caller
    cannot pair this cycle's gate with last cycle's regime.
    """
    state = _word(entry_gate, "state")
    regime = _word(market_picture, "regime")
    phrase = STAND_DOWN.get(state) or LIVE.get(state) or ""
    return {"state": state, "regime": regime, "phrase": phrase,
            "live": state in LIVE}


def micro(entry_gate: Optional[Any] = None,
          market_picture: Optional[Any] = None) -> str:
    """The header chip, or `""` when there is nothing to add.

    Silent in three cases, each for a reason:

    * **no state at all** — the Market Picture has not reported this cycle, and a
      `MARKET STATE —` chip would claim the strip permanently to say nothing.
    * **PINNED** — `pin_chip` already carries it, with the strike.
    * **an unrecognised state** — shown as-is rather than dropped, because a
      state the gate invented and this module has not learned is exactly the
      thing a trader should see rather than have quietly filtered out.
    """
    r = read(entry_gate, market_picture)
    state = r["state"]
    if not state or state == PINNED:
        return ""

    bits = [f"MARKET STATE {state}"]
    if r["phrase"]:
        bits.append(r["phrase"])
    if r["regime"]:
        arrow = REGIME_ARROW.get(r["regime"], "")
        bits.append(f"regime {r['regime']}{(' ' + arrow) if arrow else ''}")
    return f"{GLYPH} " + " · ".join(bits)
