"""Self-calibrating magnitude buckets for the third-order Greek nets.

The five `net_*` exposures (vomma/speed/zomma/veta/color) span orders of
magnitude and drift across expiries, so no fixed threshold fits them. A raw
Speed of 4.7e-6 and a raw Veta of 1.2e4 cannot be compared against one shared
band. Instead each is bucketed against its **own recent history**: HIGH means
"large *for this Greek right now*", not "above a guessed constant".

Pure & stateless — the caller (the app) owns the rolling window in session state
and hands it in; this only reads it. It classifies a magnitude, never a
direction, so the bucket alone is the whole read.

Design (answers the reviewer's "normalize each against its typical magnitude,
but add a small floor so a dead-flat window doesn't over-fire"):

* **Noise floor** — below `floor` the value is treated as noise and reads LOW,
  no matter what the window says. This is the ONE per-Greek constant, and it is
  reused from the existing (provisional) MODERATE band — so the firing frequency
  never rises above what shipped in #92; only the HIGH/MODERATE *split* becomes
  self-calibrating.
* **Warm-up** — until `min_samples` history points exist, there is no
  distribution to calibrate against, so it falls back to the absolute
  `high_band` (the #92 behaviour) rather than guessing from thin data.
* **Flat window** — if the recent high percentile is not meaningfully above the
  median, nothing stands out, so a value above the floor reads MODERATE (real,
  but not a standout) and never HIGH.
* Otherwise: at/above the window's high percentile → HIGH; above the median →
  MODERATE; above the floor but quiet within its own range → MODERATE.
"""

from __future__ import annotations

from typing import Iterable, List

#: history points needed before the rolling distribution is trusted over the
#: absolute fallback (≈ a few minutes of ~20s reruns).
MIN_SAMPLES = 8
#: percentiles that split the window: at/above HI → HIGH, above MOD → MODERATE.
HI_PCTL = 0.85
MOD_PCTL = 0.50
#: the window must have this much spread (high ÷ median) to call anything a
#: standout; a flatter window means nothing is unusual.
SPREAD_RATIO = 1.2


def _finite_abs(history: Iterable) -> List[float]:
    out: List[float] = []
    for x in history or ():
        try:
            v = abs(float(x))
        except (TypeError, ValueError):
            continue
        if v == v and v != float("inf"):
            out.append(v)
    return out


def _percentile(sorted_vals: List[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def classify(current, history, *, floor: float, high_band: float,
             min_samples: int = MIN_SAMPLES) -> str:
    """Bucket `|current|` against `|history|`. Returns `"LOW"`, `"MODERATE"` or
    `"HIGH"` — a magnitude only, never a direction.

    `floor` is the noise gate (reuse the Greek's MODERATE band); `high_band` is
    the warm-up absolute cutoff (reuse its HIGH band). A non-finite or missing
    `current` reads LOW.
    """
    try:
        a = abs(float(current))
    except (TypeError, ValueError):
        return "LOW"
    if a != a or a == float("inf"):
        return "LOW"
    # noise gate — below the floor it is not material, whatever the window says
    if a < floor:
        return "LOW"

    vals = sorted(_finite_abs(history))
    if len(vals) < min_samples:
        # warm-up: no trustworthy distribution yet → fall back to the absolute
        # cutoff that shipped in #92 rather than calibrate on thin data
        return "HIGH" if a >= high_band else "MODERATE"

    med = _percentile(vals, MOD_PCTL)
    hi = _percentile(vals, HI_PCTL)
    # flat window: nothing stands out, so a material value is MODERATE at most
    if hi <= med * SPREAD_RATIO:
        return "MODERATE"
    if a >= hi:
        return "HIGH"
    return "MODERATE"
