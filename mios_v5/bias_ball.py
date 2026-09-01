"""One coloured ball per alert — what the message means for NIFTY direction.

🟢 bullish · 🔴 bearish · 🟡 neutral / undecided. The ball always speaks in
NIFTY terms, even for an alert about an option leg — so a reader glancing at the
Telegram stream reads one consistent thing (which way is this good for NIFTY?)
and never has to translate a premium move in their head.

## The one rule that matters: option legs invert

An alert on a CALL or PUT leg is about the leg's *premium*, and premium points
the opposite way on the two sides:

* **CALL premium up = NIFTY up.** So on a CALL leg, support (premium held) is
  bullish and resistance (premium capped) is bearish.
* **PUT premium up = NIFTY down.** So on a PUT leg it flips: support is bearish,
  resistance is bullish.

Every leg classifier here funnels through `leg_level_bias`, so that inversion is
written once. NIFTY-panel alerts are read straight (support below = bullish).

Pure: strings in, a bias/ball out. No app import, no I/O, no session.
"""

from __future__ import annotations

from typing import Optional

BULL = "bull"
BEAR = "bear"
NEUTRAL = "neutral"

#: bias → the ball drawn at the head of the message.
BALLS = {BULL: "🟢", BEAR: "🔴", NEUTRAL: "🟡"}


def ball(bias: Optional[str]) -> str:
    """The coloured ball for a bias; 🟡 for anything unrecognised."""
    return BALLS.get(str(bias or "").lower(), BALLS[NEUTRAL])


def prefix(bias: Optional[str], message: str) -> str:
    """`message` with its NIFTY-bias ball in front. Empty message is returned
    unchanged, so a caller need not guard it."""
    return f"{ball(bias)} {message}" if message else message


def _leg(chart: Optional[str]) -> str:
    return str(chart or "").strip().upper()


def leg_level_bias(chart: Optional[str], role: Optional[str]) -> str:
    """A support/resistance LEVEL on one chart → NIFTY bias.

    `role` is "support" or "resistance" (bullish/bearish VOB roles are accepted
    too). On NIFTY it reads straight; on an option leg it inverts for PUT. The
    single home of the inversion rule — every other leg helper calls this.
    """
    r = str(role or "").lower()
    if r in ("bullish",):
        r = "support"
    elif r in ("bearish",):
        r = "resistance"
    if r not in ("support", "resistance"):
        return NEUTRAL

    leg = _leg(chart)
    # NIFTY and CALL share the straight reading; PUT flips it.
    straight = BULL if r == "support" else BEAR
    if leg == "PUT":
        return BEAR if straight == BULL else BULL
    return straight


def hvp_bias(chart: Optional[str], side: Optional[str]) -> str:
    """A high-volume pivot → NIFTY bias. A swing HIGH is a resistance level, a
    swing LOW a support level; then the leg rule applies."""
    role = "resistance" if str(side or "").upper() == "HIGH" else "support"
    return leg_level_bias(chart, role)


def vob_bias(chart: Optional[str], role: Optional[str]) -> str:
    """A Volume Order Block → NIFTY bias, via the same level rule."""
    return leg_level_bias(chart, role)


def poc_bias(chart: Optional[str], direction: Optional[str]) -> str:
    """A dynamic-POC step → NIFTY bias. UP is bullish on NIFTY and CALL, bearish
    on PUT (premium rising as the index falls)."""
    up = str(direction or "").upper() == "UP"
    straight = BULL if up else BEAR
    if _leg(chart) == "PUT":
        return BEAR if straight == BULL else BULL
    return straight


def writing_bias(side: Optional[str]) -> str:
    """Heavy option writing → NIFTY bias. CALL writing caps upside (bearish);
    PUT writing builds support (bullish)."""
    return BEAR if _leg(side) == "CALL" else BULL


def winner_bias(winner: Optional[str]) -> str:
    """A war-zone expected winner → NIFTY bias. Buyers bullish, sellers bearish,
    anything else (Contested, unknown) neutral."""
    w = str(winner or "").lower()
    if "buyer" in w:
        return BULL
    if "seller" in w:
        return BEAR
    return NEUTRAL


def direction_bias(direction: Optional[str]) -> str:
    """A plain BULL/BEAR label (e.g. an alignment flip) → NIFTY bias."""
    d = str(direction or "").upper()
    if d in ("BULL", "BULLISH", "UP", "BUY"):
        return BULL
    if d in ("BEAR", "BEARISH", "DOWN", "SELL"):
        return BEAR
    return NEUTRAL
