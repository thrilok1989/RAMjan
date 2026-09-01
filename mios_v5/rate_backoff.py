"""Escalating rate-limit back-off for the Dhan data API.

A single 429 (DH-904) used to trip a flat 90-second global pause, during which
EVERY data pull — NIFTY candles and the spot quote alike — is skipped. So one
transient rate-limit blip froze the chart and price for a fixed 90s ("the chart
isn't updating regularly").

This makes the pause **escalating** instead: the first trip is short, so a
transient blip recovers the chart fast; consecutive trips double up to the same
90s cap, so sustained limiting still relieves. A success resets the ladder, so an
isolated 429 always gets only the short first pause.

Pure: one number in, one number out. The app owns the counter (session state)
and the clock.
"""

from __future__ import annotations

#: first-trip pause (seconds) — short, so the chart/price come back quickly.
BASE_S = 20.0
#: hard cap (seconds) — the historical flat window; escalation never exceeds it.
CAP_S = 90.0


def backoff_seconds(consecutive: int, base: float = BASE_S,
                    cap: float = CAP_S) -> float:
    """Seconds to pause after the `consecutive`-th 429 in a row (1-based).

    `base` on the first trip, doubling each further consecutive trip, capped at
    `cap`. `consecutive <= 1` (or junk) is treated as the first trip.
    """
    try:
        n = int(consecutive)
    except (TypeError, ValueError):
        n = 1
    if n < 1:
        n = 1
    secs = base * (2.0 ** (n - 1))
    return float(min(secs, cap))
