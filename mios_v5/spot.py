"""📍 NIFTY spot — one owner, one precedence, everywhere.

## The problem this fixes

Two different numbers were both called "spot", and four different rules decided
which one a panel used:

    `_nifty_spot_live`                 the live index LTP, refreshed every cycle
    `_cached_option_data["underlying"]` the option chain's `last_price`, on the
                                       chain's slower cadence

`mios_v5/runner.py` already carried the diagnosis in a comment:

> The chain is re-fetched on its own cadence, so its `underlying` is a snapshot
> from whenever that fetch last ran. … Taking the chain's value alone is why spot
> sat still on every V5/V6 panel while the foundation header ticked.

It fixed that for the MIOS pass and nowhere else. The result was four precedences
in three files:

    runner.py                live → chain                    (correct)
    dashboard_v6.py:138      chain ONLY                      (the header — stale)
    the three cockpits       chain → live                    (backwards)
    _mios_market_read        chain ONLY                      (the chrome — stale)

Backwards is worse than wrong-only-sometimes: the chain almost always HAS a
value, so `chain → live` never reaches the live read at all. Those panels showed
a price that moved on the chain's cadence while the header beside them ticked.

## The rule, stated once

    1. the live index LTP, if it is fresh
    2. the option chain's underlying
    3. the last close of today's candle frame

Freshness is bounded by `MAX_AGE`: a live quote nobody refreshed is not "live",
and preferring a stale LTP over a chain price fetched since would make this worse
than the bug it replaces. When the LTP has aged out the chain wins, and `source`
says so rather than pretending.

Pure and read-only — session state arrives as a parameter, nothing is computed,
nothing is written. `price` is `None` when nothing reported, never `0`.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

#: How old a live LTP may be and still outrank the chain, in seconds.
#:
#: ⚠️ Bounded on purpose. `_nifty_spot_live` is written once per cycle, so at a
#: 20-second refresh a healthy quote is ≤20s old. Beyond ~2 cycles the Dhan call
#: has been failing or the app has stalled, and at that point the chain's price —
#: which came from a different endpoint — is the better read. Preferring a stale
#: LTP unconditionally would trade one desync for another.
MAX_AGE = 45.0

#: The keys this reads. Named so a test can assert nothing else is touched.
LIVE_KEY, LIVE_TS_KEY = "_nifty_spot_live", "_nifty_spot_live_ts"
CHAIN_KEY, FRAME_KEY = "_cached_option_data", "_nifty_df_live"


def _f(v: Any) -> Optional[float]:
    """A positive float, or None. A spot of `0` is not a price."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x <= 0 else x


def _get(state: Any, key: str) -> Any:
    """One key, tolerant of a dict, a Mapping or Streamlit's session proxy."""
    try:
        if hasattr(state, "get"):
            return state.get(key)
    except Exception:
        return None
    return None


def read(state: Any, now: Optional[float] = None) -> Dict[str, Any]:
    """The freshest spot, and where it came from.

    Returns `{price, source, age_s, stale, candidates}`. `price` is `None` when
    nothing reported — never `0`, because zero is not a price and a panel that
    cannot tell the difference will draw a chart through the floor.

    `now` is injectable so the age logic is testable without a clock.
    """
    import time
    at = time.time() if now is None else float(now)

    live = _f(_get(state, LIVE_KEY))
    live_ts = _f(_get(state, LIVE_TS_KEY))
    age = (at - live_ts) if (live is not None and live_ts is not None) else None

    chain = _f(_get((_get(state, CHAIN_KEY) or {}), "underlying"))

    close = None
    try:
        df = _get(state, FRAME_KEY)
        if df is not None and not getattr(df, "empty", True):
            close = _f(df["close"].iloc[-1])
    except Exception:
        close = None

    candidates = {"live": live, "live_age_s": (round(age, 1) if age is not None
                                               else None),
                  "chain": chain, "close": close}

    # 1 · a live LTP that is actually live
    if live is not None and (age is None or age <= MAX_AGE):
        return {"price": live, "source": "live LTP",
                "age_s": (round(age, 1) if age is not None else None),
                "stale": False, "candidates": candidates}
    # 2 · the chain — a different endpoint, so still a real quote
    if chain is not None:
        return {"price": chain, "source": "option chain",
                "age_s": (round(age, 1) if age is not None else None),
                # Stale only in the sense that the LIVE read aged out; the chain
                # price itself is whatever the last chain fetch returned.
                "stale": live is not None, "candidates": candidates}
    # 3 · an aged live quote beats nothing at all, and says it is old
    if live is not None:
        return {"price": live, "source": "live LTP (stale)",
                "age_s": (round(age, 1) if age is not None else None),
                "stale": True, "candidates": candidates}
    # 4 · the candle frame
    if close is not None:
        return {"price": close, "source": "last candle close",
                "age_s": None, "stale": True, "candidates": candidates}
    return {"price": None, "source": None, "age_s": None, "stale": True,
            "candidates": candidates}


def price(state: Any, now: Optional[float] = None) -> Optional[float]:
    """Just the number, for the many call sites that want only that."""
    return read(state, now)["price"]
