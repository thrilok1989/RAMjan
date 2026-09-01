"""Which key in the ATM leg stores is *the* Call, and which is *the* Put.

`_publish_atm_legs` fills six legs per cycle — ATM-1 / ATM / ATM+1 on both
sides — under keys shaped `"ATM CE 24400"` / `"ATM+1 PE 24450"`. Anything that
wants "the ATM call" has to pick one, and the rule is not quite trivial: exact
`ATM` wins, and the nearest offset is a fallback so a panel still has something
to show on a day the exact ATM leg failed to load.

That rule lived in `ui/terminal_chart.atm_legs`, which takes a dict of pandas
frames — so a consumer that only wants the *name* had to hand it frames it did
not have, or re-type the parsing. The Alignment Checklist did the latter by
reading `_leg_profiles["call_label"]`, and inherited that panel's publish order:
when the charts tab had not yet run, every option row reported ❓ while the
premiums sat in `_atm_leg_ltp` the whole time.

So the rule lives here, on the keys alone, and `atm_legs` calls it. One owner,
and no consumer needs a DataFrame to learn a name.

Pure: strings in, strings out. No pandas, no session, no I/O.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Tuple

#: an offset we could not parse sorts last, behind every real leg.
_UNKNOWN = 99


def offset(tag: Any) -> int:
    """The strike offset encoded in a leg key: `ATM` → 0, `ATM+1` → 1,
    `ATM-2` → -2. Anything unparseable sorts last rather than raising."""
    head = str(tag).split(" ")[0]
    if head == "ATM":
        return 0
    try:
        return int(head.replace("ATM", ""))
    except ValueError:
        return _UNKNOWN


def pick(keys: Iterable[Any], side: str) -> Optional[str]:
    """The key for one side (`"CE"` / `"PE"`), or None if the store has none.

    Exact `ATM` first; otherwise the smallest absolute offset. `sid_…` mirror
    entries are skipped — several stores hold each leg twice, once by name and
    once by security id, and a security id is not a leg name.
    """
    named = [str(k) for k in (keys or ()) if not str(k).startswith("sid_")]
    token = f" {side} "
    candidates = [k for k in named if token in k]
    if not candidates:
        return None
    exact = [k for k in candidates if k.startswith("ATM ")]
    if exact:
        return exact[0]
    return sorted(candidates, key=lambda k: abs(offset(k)))[0]


def call_put(keys: Iterable[Any]) -> Tuple[Optional[str], Optional[str]]:
    """`(call_key, put_key)` from one store's keys."""
    keys = list(keys or ())
    return pick(keys, "CE"), pick(keys, "PE")
