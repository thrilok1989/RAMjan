"""📍 High-volume pivots — swing highs and lows that formed on unusual volume.

⚠️ **The developing PoC is NOT here.** The reference footprint indicator's dynamic
PoC is already ported: `vob_minimal.compute_dynamic_poc` is an explicit port of it,
and `ui/profile_overlay` has always had the branch to draw it. What was broken was
the wiring — nothing ever set `profile["dynamic_poc"]`, so the line had never
appeared on any panel. That is fixed at the wiring, not by a second port. An earlier
draft of this module had its own `developing_poc`; it was deleted on finding the
existing one, because a second implementation of a number the app already computes is
the exact problem this repo's one-owner rule exists to prevent.

## High-volume pivots

Swing highs and lows that formed on unusual volume, and the levels they leave
behind. Volume is judged against the session's own distribution rather than an
absolute figure: the rolling sum over the pivot's formation window, divided by a high
percentile of that same rolling sum. A NIFTY level and a ₹90 option leg then use one
threshold honestly, which an absolute lot count could not.

A level stays live until price closes through it; after that it is `broken` and the
index where that happened is recorded. Levels are not deleted on a break — where
support failed is information, and the reference indicator keeps them too (dotted).

⚠️ **Pivot LOCATIONS, which `htf_vpfr.market_structure` does not provide.** That
function finds pivots and keeps only their values, because its question is "what is
the trend" — it returns HH/HL/LH/LL counts and a label. This one needs the bar each
pivot formed on, so the level can start there. Unifying them would mean editing a
Stage 45 module to return more than its own answer needs, and Stage 45's logic is not
to be changed; `market_structure` remains the sole owner of the TREND read, which
nothing here re-derives.

Pure module: sequences in, dicts out. No pandas, no plotly, no session, no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .poc_series import _f, _seq

#: Bars either side of a candidate for it to count as a pivot. Five one-minute
#: bars, set by the desk: a pivot confirms five minutes after it prints rather
#: than a quarter of an hour, which is what makes it usable intraday. The
#: reference implementation used 15 on both sides; that is a slower chart's
#: setting and it surfaced too few pivots, too late, to trade from.
#:
#: `RIGHT` is the one that costs latency — a pivot cannot be confirmed until
#: that many bars have printed after it — so it is the number to revisit if
#: pivots start reading as noise.
LEFT = 5
RIGHT = 5

#: A pivot's volume must exceed this on the normalised scale to be kept. The scale
#: is `rolling sum ÷ high percentile × 5`, so 2.0 means "clearly above the session's
#: ordinary participation" rather than any absolute lot count.
FILTER_VOL = 2.0

#: Percentile of the rolling volume sum used as the reference. 95 rather than the
#: maximum: one opening-auction print would otherwise set the bar for the whole
#: session and nothing else would ever qualify.
REFERENCE_PCT = 95.0

#: The normalised scale's top. Only the ratio to `REFERENCE_PCT` matters; this fixes
#: the units so `FILTER_VOL` means the same thing everywhere.
NORM_SCALE = 5.0

#: Minimum bars before pivots are looked for at all.
MIN_BARS = LEFT + RIGHT + 2


def defaults() -> Dict[str, Any]:
    """The settings a caller may override, and their values — in ONE place.

    ⚠️ Returned as a fresh dict each call so a caller's `update()` cannot mutate the
    module's own numbers. The UI offers exactly these keys, and `_hv_points` fills any
    the user has not set from here — so the control panel and the computation cannot
    disagree about what "default" means.
    """
    return {"left": LEFT, "right": RIGHT, "filter_vol": FILTER_VOL}


def _percentile(vals: Sequence[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile — no interpolation, no numpy.

    ⚠️ Nearest-rank on purpose: an interpolated percentile invents a volume figure
    between two real prints, and the reference is used as a divisor for every pivot.
    """
    nums = sorted(v for v in vals if isinstance(v, (int, float)))
    if not nums:
        return None
    k = int(round(pct / 100.0 * (len(nums) - 1)))
    return float(nums[max(0, min(len(nums) - 1, k))])


def rolling_sum(volumes: Sequence[Any], window: int) -> List[Optional[float]]:
    """Trailing sum, `None` until the window is full.

    `None`, not a partial sum: a half-filled window compares a 15-bar total against
    a 30-bar reference and makes the session's open look quiet.
    """
    vs = [_f(v) for v in _seq(volumes)]
    w = max(1, int(window))
    out: List[Optional[float]] = []
    run = 0.0
    for i, v in enumerate(vs):
        run += (v or 0.0)
        if i >= w:
            run -= (vs[i - w] or 0.0)
        out.append(run if i >= w - 1 else None)
    return out


def pivots(highs: Sequence[Any], lows: Sequence[Any],
           left: int = LEFT, right: int = RIGHT) -> List[Dict[str, Any]]:
    """Swing highs and lows with the BAR INDEX each formed on.

    A pivot is confirmed only once `right` bars have printed past it, so the index
    returned is `i` while the earliest bar that could know about it is `i + right`.
    Both are reported: drawing a level from `i` is correct, and claiming it was
    knowable at `i` would be hindsight.
    """
    hs = [_f(h) for h in _seq(highs)]
    ls = [_f(l) for l in _seq(lows)]
    n = min(len(hs), len(ls))
    lft, rgt = max(1, int(left)), max(1, int(right))
    if n < lft + rgt + 2:
        return []
    out: List[Dict[str, Any]] = []
    for i in range(lft, n - rgt):
        h = hs[i]
        if h is not None:
            near = [hs[j] for j in range(i - lft, i + rgt + 1)
                    if j != i and hs[j] is not None]
            if near and all(h >= v for v in near):
                out.append({"index": i, "confirmed_at": i + rgt,
                            "price": h, "side": "HIGH"})
        l = ls[i]
        if l is not None:
            near = [ls[j] for j in range(i - lft, i + rgt + 1)
                    if j != i and ls[j] is not None]
            if near and all(l <= v for v in near):
                out.append({"index": i, "confirmed_at": i + rgt,
                            "price": l, "side": "LOW"})
    out.sort(key=lambda p: p["index"])
    return out


def high_volume_pivots(highs: Sequence[Any], lows: Sequence[Any],
                       closes: Optional[Sequence[Any]] = None,
                       volumes: Optional[Sequence[Any]] = None,
                       left: int = LEFT, right: int = RIGHT,
                       filter_vol: float = FILTER_VOL) -> List[Dict[str, Any]]:
    """Pivots that formed on unusual volume, each with its level's fate.

    Per pivot: `index`, `confirmed_at`, `price`, `side`, `volume` (the rolling sum),
    `norm` (the normalised score), `weight` (1-5, for line thickness), and — once
    price has closed through it — `broken_at`.

    Returns `[]` rather than an unfiltered list when volume is missing: a "high
    volume" pivot with no volume behind it would be a plain pivot wearing the label.
    """
    hs, ls = [_f(h) for h in _seq(highs)], [_f(l) for l in _seq(lows)]
    cs = [_f(c) for c in _seq(closes)]
    win = max(2, int(left) * 2)
    sums = rolling_sum(volumes, win)
    have = [s for s in sums if s]
    if not have:
        return []
    ref = _percentile(have, REFERENCE_PCT)
    if not ref:
        return []

    keep: List[Dict[str, Any]] = []
    for p in pivots(hs, ls, left, right):
        i = p["index"]
        s = sums[i] if i < len(sums) else None
        if not s:
            continue
        norm = s / ref * NORM_SCALE
        if norm <= float(filter_vol):
            continue
        p = dict(p, volume=round(s, 2), norm=round(norm, 2),
                 # 1-5, so a thicker line means more volume and nothing else
                 weight=max(1, min(5, int(norm))))
        p["broken_at"] = _broken_at(cs, p["index"], p["price"], p["side"])
        keep.append(p)
    return keep


def _broken_at(closes: Sequence[Optional[float]], start: int, level: float,
               side: str) -> Optional[int]:
    """The first bar after `start` that CLOSED through the level, or `None`.

    ⚠️ On the close, not the wick. A level that a single wick poked through is
    still a level; calling it broken there would retire every level on the first
    stop-run of the session.
    """
    for j in range(start + 1, len(closes)):
        c = closes[j]
        if c is None:
            continue
        if (side == "HIGH" and c > level) or (side == "LOW" and c < level):
            return j
    return None


def live_levels(pts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Only the levels price has not closed through — the ones still in the way."""
    return [p for p in _seq(pts)
            if isinstance(p, dict) and p.get("broken_at") is None]


def read(pts: Sequence[Dict[str, Any]], spot: Any = None) -> Dict[str, Any]:
    """`{n, live, broken, nearest_above, nearest_below}` — the actionable summary.

    Nearest live level each side of price, because "which high-volume level is next"
    is the only question this overlay exists to answer. No side and no entry.
    """
    all_p = [p for p in _seq(pts) if isinstance(p, dict)]
    live = live_levels(all_p)
    out: Dict[str, Any] = {"n": len(all_p), "live": len(live),
                           "broken": len(all_p) - len(live),
                           "nearest_above": None, "nearest_below": None,
                           # ⚠️ Why there is nothing, when there is nothing. A
                           # strongly trending series has NO swing pivots — the
                           # window's extreme sits at its edge, never its centre —
                           # so this overlay goes quiet exactly when the move is
                           # cleanest. `market_structure` documents the same blind
                           # spot. Silence that cannot explain itself reads as a
                           # broken feature, which is the report this repo keeps
                           # getting.
                           "why": (None if all_p else
                                   "no swing pivots — price has not turned inside "
                                   "the window, which is what a clean trend looks "
                                   "like")}
    sp = _f(spot)
    if sp is None or not live:
        return out
    above = [p for p in live if _f(p.get("price")) is not None
             and float(p["price"]) > sp]
    below = [p for p in live if _f(p.get("price")) is not None
             and float(p["price"]) < sp]
    if above:
        out["nearest_above"] = min(above, key=lambda p: float(p["price"]) - sp)
    if below:
        out["nearest_below"] = min(below, key=lambda p: sp - float(p["price"]))
    return out
