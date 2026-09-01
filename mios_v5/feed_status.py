"""📡 Why is there no data? — one answer, for every panel that has to say so.

## The problem this fixes

Three panels stand by when the option chain is missing, and each said something
different and unhelpful:

    Trade Card       "no option chain — chain fetch returned nothing"
    Options cockpit  "Those land once the chain and the ATM legs are both in"
    NIFTY cockpit    "it reads the Market Picture … those land once the option
                      chain and candles are both in"

None of them answer the only question a trader has at that moment: **is this
broken, or is the market simply not open yet?** At 08:25 IST all three appear on a
perfectly healthy app, because NSE does not publish an option chain until the
open — and "chain fetch returned nothing" reads like a fault.

Worse, the app already knew more than it was saying. `_dhan_token_expired` and
`_dhan_429_until` are set at the moment the fetch fails, and no standing-by
message consulted either.

## The rule

Most actionable cause first:

    1. token expired      → they must paste a new one; nothing else will help
    2. rate-limited       → it clears itself, and we know when
    3. a recorded error   → the real reason, verbatim
    4. the clock          → the data is STATIC, not absent
    5. nothing recorded   → say THAT, rather than implying a fetch happened

## ⚠️ The clock is ranked BELOW a recorded error, on purpose

An earlier version of this module put the clock third and said *"Market not open
yet … Nothing is wrong."* That was wrong, and wrong in the dangerous direction.

**Dhan serves the option chain outside market hours.** It returns the last
settled state — the figures are frozen, not missing. There is no market-hours
gate on the fetch either: `analyze_option_chain` runs pre-open exactly as it does
at noon. So an *empty* chain at 08:25 is a genuine failure, and excusing it as
"nothing is wrong, the market is shut" would hide a token expiry or a broken
endpoint behind the calendar.

The clock therefore explains why data is not *ticking*. It never explains why
data is *absent*.

Pure module — the clock and session state arrive as parameters, so a test can
place the app at 08:25 without waiting for 08:25.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

#: NSE equity/derivative session, IST. The chain is not published before this.
#:
#: ⚠️ `OPEN` is 09:15, NOT the app's own 08:30 refresh window. `vob_minimal`
#: starts polling at 08:30 so pre-open data and the gap read are ready in time,
#: which means there is a 45-minute stretch every morning where the app is
#: working perfectly and the chain is legitimately empty. That gap is exactly
#: when "chain fetch returned nothing" gets misread as a bug.
OPEN_H, OPEN_M = 9, 15
CLOSE_H, CLOSE_M = 15, 30

#: The pre-open call auction, when Dhan may return a partial or empty chain.
PREOPEN_H, PREOPEN_M = 9, 0

#: Reason codes, so a caller can branch without matching on prose.
TOKEN, RATE_LIMIT, PREMARKET, POSTMARKET, WEEKEND, ERROR, UNKNOWN = (
    "TOKEN_EXPIRED", "RATE_LIMITED", "PRE_MARKET", "POST_MARKET", "WEEKEND",
    "ERROR", "UNKNOWN")

#: Codes where the data would legitimately be FROZEN — not where it would be
#: absent. Dhan still answers in all three, so a panel reaching one of these with
#: nothing to draw has a fetch problem regardless of the clock.
#:
#: ⚠️ Named `STATIC`, not `BENIGN`. It was `BENIGN` and `is_benign()` picked a calm
#: 🕒 over a ⚠️ for exactly these codes — which would have shown a reassuring clock
#: face on a genuinely broken pre-open feed.
STATIC = (PREMARKET, POSTMARKET, WEEKEND)


def _get(state: Any, key: str) -> Any:
    try:
        if hasattr(state, "get"):
            return state.get(key)
    except Exception:
        return None
    return None


def _mins(h: int, m: int) -> int:
    return h * 60 + m


def read(state: Any = None, now: Any = None) -> Tuple[str, str]:
    """`(code, sentence)` — why there is no data, and what to do about it.

    `now` is a datetime (IST). Injectable so the pre-open case is testable.
    """
    # ── 1 · a token expiry stops everything and only a human fixes it ──
    if _get(state, "_dhan_token_expired"):
        return (TOKEN, "Dhan token expired — open **Refresh Dhan Token** in the "
                       "sidebar and paste a new one. Nothing will load until "
                       "you do.")

    # ── 2 · a rate-limit back-off clears itself, and we know when ──
    until = _get(state, "_dhan_429_until")
    if until is not None:
        try:
            if now is not None and until > now:
                return (RATE_LIMIT,
                        f"Rate-limited by Dhan until {until.strftime('%H:%M:%S')} "
                        f"IST — it clears itself, the app is serving the last "
                        f"good data meanwhile.")
        except (TypeError, AttributeError):
            pass

    # ── 3 · whatever the fetch actually recorded — ABOVE the clock ──
    #
    # ⚠️ Ranked here, not below the clock. Dhan answers outside market hours, so a
    # real error at 08:25 must not be dressed up as "the market is shut".
    err = _get(state, "_dhan_last_error")
    if err:
        return (ERROR, f"Dhan fetch failed — {str(err)[:160]}")

    # ── 4 · the clock. The data is STATIC, not absent ──
    if now is not None:
        try:
            if now.weekday() >= 5:
                return (WEEKEND, "Weekend — Dhan serves the last settled chain, "
                                 "so every figure is Friday's close and nothing "
                                 "will move until Monday 09:15 IST.")
            cur = _mins(now.hour, now.minute)
            if cur < _mins(OPEN_H, OPEN_M):
                pre = cur >= _mins(PREOPEN_H, PREOPEN_M)
                return (PREMARKET,
                        ("Pre-open auction — prices are forming and the chain is "
                         "partial until 09:15 IST."
                         if pre else
                         f"Before the open — Dhan serves the last settled "
                         f"chain, so the figures are static until "
                         f"{OPEN_H:02d}:{OPEN_M:02d} IST. If they are missing "
                         f"rather than frozen, that is a fetch problem, not the "
                         f"clock."))
            if cur > _mins(CLOSE_H, CLOSE_M):
                return (POSTMARKET, "After the close — the chain is the 15:30 "
                                    "settle and will not move until tomorrow.")
        except (TypeError, AttributeError):
            pass

    # ── 5 · nothing recorded. Say so; do not imply a fetch was made ──
    #
    # ⚠️ This is the honest version of the old "chain fetch returned nothing".
    # Several failure paths return None WITHOUT recording a reason, so that
    # sentence was frequently a guess dressed as a diagnosis.
    return (UNKNOWN, "No option chain, and no error was recorded — the fetch "
                     "either has not run yet this session or failed silently.")


def sentence(state: Any = None, now: Any = None) -> str:
    """Just the sentence, for a caller that does not branch on the code."""
    return read(state, now)[1]


def would_be_static(state: Any = None, now: Any = None) -> bool:
    """Would the data be FROZEN right now if it were arriving at all?

    ⚠️ This is not "the absence is fine". Every caller consults this while it has
    nothing to draw, and Dhan answers outside market hours — so absent data is a
    fetch problem in all three clock states, and a panel must not soften its tone
    on the strength of the calendar.

    Use it to say *"these figures are the 15:30 settle"* next to numbers you DO
    have, never to explain numbers you do not.
    """
    return read(state, now)[0] in STATIC
