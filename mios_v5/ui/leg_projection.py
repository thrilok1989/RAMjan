"""Where a NIFTY level sits on a premium chart — observed, not modelled.

The terminal draws NIFTY beside the ATM call and the ATM put, and the levels
that matter most — the war zone, the gamma flip, the liquidity pool — exist
only in **index points**. `terminal_chart` has always refused to draw them on a
premium panel, and the reason is written into that module:

> Overlaying a spot-derived stop on an option's price series would put a line
> at a price that series can never trade — authoritative-looking and
> meaningless.

That is still true of drawing 24,558 on a chart whose axis runs from ₹60 to
₹180. It is **not** true of the question behind it, which is a fair one:

> *What was this leg worth the last time NIFTY was at the war zone?*

That has an answer, and the answer is already on the screen. The three panels
share one timeline — `terminal_chart.master_timeline` guarantees candle *n* is
the same minute everywhere — so every bar is a matched pair of *(index price,
premium)*. Finding the bars where NIFTY was nearest a level and reading the
leg's own close there is a **measurement of what happened**, not a model of
what should.

## Why this is not Black-Scholes

Nothing here prices an option. There is no volatility input, no rate, no time
to expiry, and deliberately so: a projection built from a pricing model would
be a second opinion about the premium, competing with the market's. This one
cannot disagree with the tape, because it *is* the tape.

The cost is that it only answers where the day has actually been. A level
NIFTY has not approached today has no projection, and `project` returns `None`
rather than extrapolating. **A missing line is the correct output** — the
honest answer to "what is this leg worth at 24,700?" when NIFTY topped out at
24,610 is that nobody knows.

## Theta, and why the most RECENT bars are used

A premium is not a function of spot alone. The same index level pays less at
15:10 than it did at 09:30, because the option has less life left. Averaging
every visit to a level across the day would blend a morning premium into an
afternoon one and produce a number that was true at neither.

So the matched bars are taken **most-recent-first** and the median of the last
few is returned. On expiry day, where the decay is steepest, that is the
difference between a projection a trader can use and one that is quietly
half an hour stale.

The median rather than the mean: one bad print at a thin minute should not
move the line.

## advisory_only

Every value this module produces is drawn and nothing else. No stage consumes
it, no gate reads it, and the labels carry `⇢` so a projected level is never
mistaken for one the leg computed from its own structure.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

#: How near NIFTY must have come, in index points, for a bar to count as a
#: visit to the level.
#:
#: 25 points is not a new constant — it is the proximity `classify_sr_behavior`
#: already uses to call a level BUILDING, the threshold that feeds the fresh
#: entry alert. The audit in `AUDIT_STAGE_42_5_LEVEL_INTERACTION.md` counted
#: **fourteen** proximity thresholds across three units in this repo, and
#: inventing a fifteenth for the sake of this file would be the same mistake
#: one more time.
TOLERANCE = 25.0

#: How many matched bars the median is taken over. Enough to survive one bad
#: print, few enough that they are all from the same part of the session.
SAMPLE = 5

#: Below this many matched bars the projection is not reported at all. One
#: visit to a level is an anecdote, and a line drawn from it looks exactly as
#: confident as a line drawn from fifty.
MIN_SAMPLE = 2


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _closes(df) -> List[Optional[float]]:
    """A frame's close series as plain floats, whatever the column is called.

    Mirrors `terminal_chart._ohlc`'s column search rather than assuming
    `close`: the leg frames and the index frame come from different fetches and
    have historically disagreed about it.
    """
    if df is None or getattr(df, "empty", True):
        return []
    cols = {str(c).lower(): c for c in df.columns}
    for name in ("close", "ltp", "price"):
        if name in cols:
            try:
                return [_f(v) for v in df[cols[name]].tolist()]
            except Exception:
                return []
    return []


def pairs(index_df, leg_df) -> List[Tuple[float, float]]:
    """`(index price, premium)` for every bar both series have.

    Positional, because the caller is `terminal_chart`, which has already
    reindexed all three panels onto one timeline — bar *n* is the same minute
    in each. Zipping is therefore the alignment, not a shortcut past it.

    ⚠️ If that ever stops being true the pairing silently becomes wrong rather
    than failing, so `matched` is reported alongside every projection and
    `test_leg_projection` pins the timeline assumption.
    """
    spot, prem = _closes(index_df), _closes(leg_df)
    n = min(len(spot), len(prem))
    return [(spot[i], prem[i]) for i in range(n)
            if spot[i] is not None and prem[i] is not None and prem[i] > 0]


def project(index_df, leg_df, level: Any,
            tolerance: float = TOLERANCE,
            sample: int = SAMPLE,
            min_sample: int = MIN_SAMPLE) -> Optional[Dict[str, Any]]:
    """What this leg traded at, the last few times NIFTY was near `level`.

    Returns `{"premium", "matched", "nearest", "level"}`, or `None` when the
    index has not been within `tolerance` of the level often enough today.

    `None` is a real answer and the caller must draw nothing for it. Guessing a
    premium for a level the session never reached is exactly the fabrication
    this module exists to avoid.
    """
    target = _f(level)
    if target is None or target <= 0:
        return None
    matched = [(abs(s - target), p) for s, p in pairs(index_df, leg_df)
               if abs(s - target) <= tolerance]
    if len(matched) < max(1, min_sample):
        return None
    # Most recent first — `pairs` is chronological, so the tail is now. Theta
    # makes a morning premium the wrong answer to an afternoon question.
    recent = matched[-max(1, sample):]
    prices = sorted(p for _, p in recent)
    mid = len(prices) // 2
    premium = (prices[mid] if len(prices) % 2
               else (prices[mid - 1] + prices[mid]) / 2.0)
    return {"premium": round(premium, 2), "matched": len(matched),
            "nearest": round(min(d for d, _ in matched), 1), "level": target}


#: Spot-space levels worth projecting onto a premium panel, and the key each
#: becomes. The `proj_` prefix is what keeps a projected level distinguishable
#: from one the leg computed itself — both can appear on the same panel, and
#: whether they agree is a genuinely useful thing to be able to see.
PROJECTED: Dict[str, str] = {
    "war_zone": "proj_war_zone",
    "gamma_flip": "proj_gamma_flip",
    "liquidity": "proj_liquidity",
    "support": "proj_support",
    "resistance": "proj_resistance",
    "poc": "proj_poc",
    "vwap": "proj_vwap",
}


def project_levels(index_df, leg_df,
                   levels: Optional[Dict[str, Any]] = None,
                   keys: Optional[Sequence[str]] = None,
                   **kw) -> Dict[str, float]:
    """Every projectable level in `levels`, as premium, keyed `proj_*`.

    Levels the session has not visited are absent rather than zero — the caller
    iterates what it gets and draws only that.
    """
    out: Dict[str, float] = {}
    wanted = tuple(keys) if keys is not None else tuple(PROJECTED)
    for key in wanted:
        target = PROJECTED.get(key)
        if not target:
            continue
        got = project(index_df, leg_df, (levels or {}).get(key), **kw)
        if got:
            out[target] = got["premium"]
    return out


def caption(projected: Optional[Dict[str, Any]] = None) -> str:
    """One line under the terminal saying what the ⇢ lines are.

    Empty when nothing projected, because a legend for lines that are not on
    the chart is noise.
    """
    if not projected:
        return ""
    names = ", ".join(sorted(
        k[len("proj_"):].replace("_", " ") for k in projected))
    return ("⇢ **Projected levels** — where the ATM legs actually traded the "
            f"last few times NIFTY was within {TOLERANCE:.0f} points of "
            f"{names}. Measured off today's bars, not priced from a model, so "
            "a level the session has not reached draws no line.")
