"""🏛 Rolling (dynamic) POC per structural window — the multi-TF POC picture.

## What "dynamic POC" means here

A **static** POC is one number for a finished period: last week's POC, drawn as a
horizontal line until the week rolls over. It only moves on the period boundary, so
for four days out of five it tells you where value *was*.

A **dynamic** POC is recomputed on every bar over a trailing window, so it is a
LINE that moves with the market. `poc_line(..., window=5)` gives the weekly POC as
it looked on each day, which is the picture the layered-structure read is actually
about: not four horizontal lines, but four curves whose ORDER tells you which way
structure is migrating.

⚠️ **The POC itself is not computed here.** `htf_vpfr.build_profile` is this repo's
one POC owner — the audit found four implementations and picked it — and a rolling
POC is that same function over a sliding window. A fifth implementation, however
convenient, would put this module in the business of deciding what a POC is.

The reference indicator this was modelled on approximates each period's POC as the
previous period's `(high + low + close) / 3`. That is a typical price, not a point
of control: it ignores volume entirely, so it lands in the middle of a bar's range
whether the volume was transacted at the high or the low. `build_profile` bins real
volume across the prices each bar spanned. The lines here are therefore not the
same lines — they are the ones the reference was reaching for.

## Windows, and why they are named in days

On a **1-day** axis a "4H POC" cannot be a series — four hours is finer than one
bar, so there is nothing to roll. Rather than mislabel a 5-day window as "4H", the
windows here are named for what they are, and `SUBDAILY` records which of the
reference's timeframes are levels rather than curves.

Pure module: sequences in, dicts out. No pandas, no plotly, no session, no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .htf_vpfr import build_profile

#: Trailing windows, in daily bars, fastest → slowest. The label is what the
#: window IS; the reference's timeframe names are in `MEANS`.
#:
#: ⚠️ 5 / 21 / 63 / 252 are the session counts of a week, month, quarter and year
#: on the NSE calendar — stated once here so no caller reinvents them.
WINDOWS: Tuple[Tuple[str, int], ...] = (
    ("Weekly", 5),
    ("Monthly", 21),
    ("Quarterly", 63),
    ("Yearly", 252),
)

#: What each window is the structural analogue of, for the reader who came from the
#: reference indicator's vocabulary.
MEANS = {
    "Weekly": "short-term control",
    "Monthly": "swing control",
    "Quarterly": "institutional context",
    "Yearly": "the anchor",
}

#: Timeframes finer than one daily bar. They have a current POC but cannot have a
#: daily series, and saying so is the whole point of listing them.
SUBDAILY = ("1H", "4H")

#: Visual hierarchy: slower = thicker and calmer. Taken from the reference's own
#: scheme so the picture is recognisable.
STYLE = {
    "Weekly": ("#FF9800", 1.6),
    "Monthly": ("#4CAF50", 2.2),
    "Quarterly": ("#42A5F5", 2.8),
    "Yearly": ("#1565C0", 3.6),
}

#: A POC must move this fraction of price to count as migrated, matching
#: `htf_vpfr._MIGRATE_PCT` rather than inventing a second threshold.
MIGRATE_PCT = 0.10

#: Minimum bars before a window reports at all. `build_profile` needs 3; below
#: this a "rolling" POC is one bar restated, which is not a trend.
MIN_BARS = 3


def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def _seq(v: Any) -> Sequence[Any]:
    """⚠️ `v or ()` does NOT make a non-sequence safe: `7 or ()` is `7`, and the
    comprehension then raises TypeError. A string is excluded too — iterating it
    yields characters, which would silently become a 6-bar series out of "24600"."""
    if v is None or isinstance(v, (str, bytes, int, float, bool)):
        return ()
    try:
        return list(v)
    except TypeError:
        return ()


def _clean(highs: Sequence[Any], lows: Sequence[Any],
           volumes: Optional[Sequence[Any]]) -> Tuple[List[Optional[float]],
                                                      List[Optional[float]],
                                                      List[float]]:
    hs = [_f(h) for h in _seq(highs)]
    ls = [_f(l) for l in _seq(lows)]
    n = min(len(hs), len(ls))
    vs = [(_f(v) or 0.0) for v in _seq(volumes)]
    vs += [0.0] * max(0, n - len(vs))
    return hs[:n], ls[:n], vs[:n]


def poc_line(highs: Sequence[Any], lows: Sequence[Any],
             volumes: Optional[Sequence[Any]] = None,
             window: int = 5, step: int = 1) -> List[Optional[float]]:
    """The rolling POC, one value per input bar, oldest first.

    `None` for bars before the window has `MIN_BARS` behind it — a warm-up is not a
    price, and forward-filling one would draw a flat line that never happened.

    `step` recomputes only every Nth bar and carries the value between, because
    `build_profile` over 252 bars is not free and a yearly POC does not move
    meaningfully in one session. The carried value is the last real one, never an
    interpolation.
    """
    hs, ls, vs = _clean(highs, lows, volumes)
    n = len(hs)
    w = max(MIN_BARS, int(window or 0))
    st = max(1, int(step or 1))
    out: List[Optional[float]] = []
    last: Optional[float] = None
    for i in range(n):
        avail = i + 1
        if avail < MIN_BARS:
            out.append(None)
            continue
        # recompute on the step grid, and always on the final bar so the latest
        # POC is real rather than up to `step` bars old
        if (i % st == 0) or (i == n - 1) or last is None:
            lo = max(0, avail - w)
            prof = build_profile(hs[lo:avail], ls[lo:avail], vs[lo:avail])
            p = _f((prof or {}).get("poc"))
            if p is not None:
                last = p
        out.append(last)
    return out


def lines(highs: Sequence[Any], lows: Sequence[Any],
          volumes: Optional[Sequence[Any]] = None,
          windows: Sequence[Tuple[str, int]] = WINDOWS,
          ) -> Dict[str, List[Optional[float]]]:
    """`{label: rolling POC}` for each window that has enough history.

    A window longer than the series is SKIPPED, not truncated: a "Yearly" POC built
    from 40 days would carry a yearly label on a monthly measurement.
    """
    hs, ls, vs = _clean(highs, lows, volumes)
    out: Dict[str, List[Optional[float]]] = {}
    for label, w in (windows or ()):
        w = int(w)
        if len(hs) < max(MIN_BARS, w):
            continue
        # a yearly POC recomputed daily is waste; step scales with the window
        out[str(label)] = poc_line(hs, ls, vs, window=w,
                                   step=max(1, w // 10))
    return out


def stack(series: Dict[str, List[Optional[float]]],
          spot: Any = None) -> List[Dict[str, Any]]:
    """The layered read, slowest window first — one row per window.

    Per window: the latest POC, which side of it price is on, the distance, and
    whether value has MIGRATED up or down **over that window's own span**.

    ⚠️ Migration was first measured from the series' first value to its last, and
    running it over five years of daily bars made all four windows say "UP" — true
    of the index since 2021 and useless as a read. A window's migration is the move
    of its OWN POC over its OWN length: the weekly POC against where the weekly POC
    was a week ago. Anything else measures the market, not the window.

    ⚠️ `side` is a fact about price and a number. It is NOT an acceptance verdict —
    acceptance needs consecutive closes and belongs to Stage 42, which already owns
    it. Calling one bar's position "ACCEPTED" here would be a second answer to a
    question that has an owner.
    """
    sp = _f(spot)
    order = {label: i for i, (label, _w) in enumerate(WINDOWS)}
    span = {label: w for label, w in WINDOWS}
    rows: List[Dict[str, Any]] = []
    if not isinstance(series, dict):
        return []
    for label in sorted(series, key=lambda k: -order.get(k, 0)):
        vals = [v for v in (series.get(label) or []) if v is not None]
        if not vals:
            continue
        poc = vals[-1]
        back = span.get(label, 5)
        then = vals[-min(len(vals), back + 1)]
        drift = poc - then
        row: Dict[str, Any] = {
            "label": label,
            "means": MEANS.get(label, ""),
            "poc": round(poc, 2),
            "migrated": ("UP" if drift > then * MIGRATE_PCT / 100.0 else
                         "DOWN" if drift < -then * MIGRATE_PCT / 100.0
                         else "FLAT"),
            "drift": round(drift, 2),
            "drift_bars": min(len(vals) - 1, back),
        }
        if sp is not None and poc:
            row["side"] = "ABOVE" if sp > poc else "BELOW" if sp < poc else "AT"
            row["distance"] = round(sp - poc, 2)
            row["distance_pct"] = round(abs(sp - poc) / poc * 100.0, 2)
        rows.append(row)
    return rows


def alignment(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """How many windows price sits above, and what that stack means.

    ⚠️ Counting only. This produces **no side and no entry** — it says where price
    is relative to structure, which is context. The decision has an owner, and a
    module that turned "above all four" into BUY would be minting a signal from a
    row count.
    """
    # ⚠️ `isinstance` first. A list carrying a None row raised AttributeError on
    # `.get` — and the caller most likely to hand one over is a partially-built
    # `stack()` result, which is exactly when this must not take the panel down.
    have = [r for r in _seq(rows) if isinstance(r, dict)
            and r.get("side") in ("ABOVE", "BELOW", "AT")]
    n = len(have)
    above = sum(1 for r in have if r["side"] == "ABOVE")
    below = sum(1 for r in have if r["side"] == "BELOW")
    if not n:
        return {"n": 0, "above": 0, "below": 0, "label": None, "reporting": False}
    if above == n:
        label = "above every window — value is beneath price"
    elif below == n:
        label = "below every window — value is above price"
    else:
        label = f"inside structure — above {above} of {n}"
    return {"n": n, "above": above, "below": below, "label": label,
            "reporting": True}
