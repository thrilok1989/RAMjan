"""Refresh one thing per cycle instead of all of them at once.

Pure scheduling — no fetching, no Streamlit — so the rule can be tested on its
own.

The cross-expiry read needs three option chains. Fetching all three the moment
its cache expired put three requests into an endpoint Dhan caps at one per
three seconds, which is what tripped the limiter. Spacing them stopped the
429s but spent seconds of the render asleep.

Rotating is the third option: refresh the single stalest entry each cycle and
compute from whatever is held. Three entries at ~20s per render come round in
about a minute, well inside the two minutes each is allowed to live — the same
work, spread rather than burst.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence


def next_to_refresh(keys: Sequence[Any], freshness: Dict[Any, float],
                    now: float, ttl: float) -> Optional[Any]:
    """The one key to refresh now, or None when everything is fresh enough.

    `freshness` maps a key to the time it was last refreshed; a key missing
    from it has never been fetched and counts as infinitely stale.

    Always the oldest of the stale keys, so nothing can starve behind an entry
    that keeps being chosen ahead of it.

    The "never fetched" default is -inf rather than 0, so it does not depend on
    `now` being a large number. With 0 it only reads as stale because epoch
    seconds happen to be big — on any other time base (a test clock, a
    monotonic counter) an unfetched key would look perfectly fresh.
    """
    never = float("-inf")
    stale = [k for k in keys if (now - freshness.get(k, never)) > ttl]
    if not stale:
        return None
    return min(stale, key=lambda k: freshness.get(k, never))


def drop_missing(store: Dict[Any, Any], keys: Sequence[Any]) -> Dict[Any, Any]:
    """Forget entries whose key is no longer wanted, in place.

    Expiries roll off. Without this, yesterday's expiry would sit in the store
    for the life of the session and keep being counted in the verdict.
    """
    for gone in [k for k in store if k not in set(keys)]:
        store.pop(gone, None)
    return store
