"""📈 ATM IV history — kept, deduped, and timestamped.

## Why "IV: not reporting" kept appearing

`volatility_state` needs **two or more** samples to say anything, and the history
lived in `st.session_state['_iv_history']`, which is **per browser session**. So:

* every app restart began with an empty list — IV said "not reporting" for the
  first ~40 seconds of every session;
* every new browser tab started its own empty list, so the same running app
  reported different volatility states to two windows;
* samples were appended **once per rerun with no timestamp**, so a stalled chain
  fetch pushed the same number repeatedly and `vals[-1] - vals[0]` compared two
  readings of unknown, possibly identical, age.

Held in a `st.cache_resource` store instead (see `vob_minimal.iv_store`), one
mutable object shared across reruns AND sessions in the process, this module owns
what goes into it.

## The rules

    · a sample is kept only if it MOVED or MIN_GAP_S has passed — a stalled feed
      must not manufacture history out of one number
    · every sample carries its own timestamp, so age is knowable
    · CAP samples, oldest dropped — the read is intraday, and an unbounded list
      is a slow leak across a long session
    · `series()` returns bare floats, because `volatility_state` takes a plain
      sequence and reinterpreting its contract here would be a second owner

Pure module: the store arrives as a parameter. Nothing here imports streamlit.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Most samples retained. At one per ~20s cycle this is over two hours, which is
#: far more than any window `volatility_state` looks at.
CAP = 240

#: Seconds after which an UNCHANGED reading is still worth recording, so a flat
#: but live market builds real history.
#:
#: ⚠️ The dedup exists because the old list appended on every rerun. A chain
#: fetch that returns the same IV for ten cycles is one observation, not ten, and
#: treating it as ten made a stalled feed look like a settled market.
MIN_GAP_S = 55.0

#: Smallest IV move that counts as a change, in IV points. Below this it is
#: rounding, not volatility.
MIN_MOVE = 0.01

#: Plausible ATM IV band. Outside it the value is a parse error, not a market.
IV_MIN, IV_MAX = 0.5, 300.0


def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def valid(iv: Any) -> Optional[float]:
    """A believable ATM IV, or None.

    ⚠️ `0` is the value the chain returns for a strike it has no quote for, and
    the old code guarded `if _iv > 0` — which admits `0.0001` and `9999`. Both
    would wreck a volatility read that works on differences.
    """
    x = _f(iv)
    return x if x is not None and IV_MIN <= x <= IV_MAX else None


def record(store: Any, iv: Any, now: Optional[float] = None) -> bool:
    """Add one sample if it is worth keeping. `True` when stored.

    `store` is any dict-like with a `"samples"` list — a `st.cache_resource`
    dict in production, a plain dict in a test.
    """
    x = valid(iv)
    if x is None or not isinstance(store, dict):
        return False
    import time
    at = time.time() if now is None else float(now)

    samples: List[Tuple[float, float]] = store.setdefault("samples", [])
    if samples:
        last_at, last_iv = samples[-1]
        moved = abs(x - last_iv) >= MIN_MOVE
        aged = (at - last_at) >= MIN_GAP_S
        if not moved and not aged:
            return False
        # ⚠️ A clock that went backwards (a restart, a DST edit) must not let a
        # stale sample sit in front of newer ones — `series()` assumes order.
        if at < last_at:
            at = last_at
    samples.append((at, x))
    if len(samples) > CAP:
        del samples[:len(samples) - CAP]
    return True


def series(store: Any, window_s: Optional[float] = None,
           now: Optional[float] = None) -> List[float]:
    """The IV values, oldest first — the shape `volatility_state` expects.

    `window_s` keeps only samples that recent. Absent, everything is returned.
    """
    if not isinstance(store, dict):
        return []
    samples = store.get("samples")
    if not isinstance(samples, list):
        return []
    if window_s is None:
        return [iv for _at, iv in samples]
    import time
    at = time.time() if now is None else float(now)
    return [iv for t, iv in samples if (at - t) <= float(window_s)]


def read(store: Any, now: Optional[float] = None) -> Dict[str, Any]:
    """`{n, first, last, change, span_s, reporting, why}` — for a debug caption.

    `reporting` answers the question the panel actually asks: does
    `volatility_state` have enough to say anything? It needs two samples, so one
    is honestly "not reporting" and must not be dressed up as a flat market.
    """
    vals = series(store, now=now)
    n = len(vals)
    if n < 2:
        return {"n": n, "first": vals[0] if vals else None,
                "last": vals[-1] if vals else None, "change": None,
                "span_s": None, "reporting": False,
                "why": ("no IV samples yet" if n == 0 else
                        "only one IV sample — no history to compare")}
    samples = store.get("samples") or []
    span = (samples[-1][0] - samples[0][0]) if len(samples) >= 2 else None
    return {"n": n, "first": vals[0], "last": vals[-1],
            "change": round(vals[-1] - vals[0], 3),
            "span_s": (round(span, 1) if span is not None else None),
            "reporting": True, "why": ""}


def adopt(store: Any, existing: Optional[Sequence[Any]] = None,
          now: Optional[float] = None) -> int:
    """Seed an empty store from a legacy bare-float list. Returns samples added.

    ⚠️ One-way and one-time: it runs only while the store is empty, so the old
    `session_state['_iv_history']` is not re-imported every cycle. The legacy
    list has no timestamps, so they are synthesised backwards at `MIN_GAP_S`
    spacing — good enough for ordering, and `span_s` will say it is approximate
    rather than claiming precision the data never had.
    """
    if not isinstance(store, dict) or store.get("samples"):
        return 0
    vals = [valid(v) for v in (existing or ())]
    vals = [v for v in vals if v is not None][-CAP:]
    if not vals:
        return 0
    import time
    at = time.time() if now is None else float(now)
    store["samples"] = [(at - (len(vals) - 1 - i) * MIN_GAP_S, v)
                        for i, v in enumerate(vals)]
    store["seeded"] = True
    return len(vals)
