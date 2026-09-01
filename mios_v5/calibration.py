"""MIOS V6 — Stage 57 Confidence Calibration.

An engine that says "85% confident" and wins 52% of the time is not slightly
optimistic — it is **lying in a way that compounds**, because the Decision
Engine sizes and gates on that number. Every downstream stage inherits the
error. This stage measures the gap and reports it.

Calibration is not accuracy. An engine can be accurate and badly calibrated
(right 70% of the time but always claiming 95%), or poorly performing yet
perfectly calibrated (right 40% of the time and honestly saying 40% — which is
*useful*, because you can fade it). What is measured here is only:

    when this engine claims X% confidence, how often is it actually right?

**Brier score** grades each individual claim: `(claimed − outcome)²` averaged.
Lower is better; 0.25 is what you get by always saying 50%. An engine that
cannot beat 0.25 is contributing noise dressed as conviction.

## The binding constraints, enforced in code, not in comments

* `suggested_confidence` is a **suggestion**. Nothing here mutates a live
  confidence, a weight, or a threshold. There is no apply function in this
  module — deliberately. The only way a suggestion reaches production is a
  human editing the engine.
* No suggestion is marked `promotable` without `MIN_BUCKET` observations **and**
  a Wilson interval that excludes the claimed rate. A 12-trade bucket suggesting
  "drop confidence by 30 points" is noise, and acting on it would make MIOS
  worse while looking like learning.
* Under-confidence is reported as loudly as over-confidence. Hiding "this engine
  is better than it claims" is the same failure as hiding the reverse.

Pure module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .engine_accuracy import WINDOWS, wilson

#: confidence bands. Coarse on purpose — finer bands look precise and fill up
#: with two-trade samples that say nothing.
BUCKETS = ((0, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 101))

#: observations needed before a bucket's gap is allowed to mean anything
MIN_BUCKET = 20

#: percentage points of claimed-vs-actual gap that count as miscalibration
GAP_EPS = 7.0


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def bucket_of(conf: Any) -> Optional[str]:
    c = _f(conf)
    if c is None:
        return None
    for lo, hi in BUCKETS:
        if lo <= c < hi:
            return f"{lo}-{min(hi, 100)}"
    return None


def _label(lo: int, hi: int) -> str:
    return f"{lo}-{min(hi, 100)}"


def buckets(rows: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Claimed vs observed, per confidence band.

    Only rows where the engine actually took a side are counted. A NEUTRAL read
    carries no claim, so it cannot be miscalibrated.
    """
    voting = [r for r in (rows or []) if r.get("agreement") or r.get("conflict")]
    out = []
    for lo, hi in BUCKETS:
        band = [r for r in voting
                if (c := _f(r.get("confidence"))) is not None and lo <= c < hi]
        n = len(band)
        if not n:
            continue
        # "right" = agreed and won, or opposed and lost
        right = sum(1 for r in band
                    if bool(r.get("won")) == bool(r.get("agreement")))
        claimed = round(sum(_f(r.get("confidence")) or 0.0 for r in band) / n, 1)
        actual = round(100.0 * right / n, 1)
        iv = wilson(right, n) or {}
        # miscalibrated only if the honest interval EXCLUDES the claim
        outside = bool(iv) and not (iv["low"] <= claimed <= iv["high"])
        out.append({
            "bucket": _label(lo, hi), "sample": n,
            "claimed": claimed, "actual": actual,
            "gap": round(actual - claimed, 1),
            "interval": iv or None,
            "significant": n >= MIN_BUCKET and outside,
            "direction": ("overconfident" if actual < claimed - GAP_EPS else
                          "underconfident" if actual > claimed + GAP_EPS
                          else "calibrated"),
        })
    return out


def brier(rows: Optional[Sequence[Dict[str, Any]]]) -> Optional[float]:
    """Mean squared error of the confidence claims. 0.25 = the always-say-50%
    baseline; anything above it is worse than having no opinion."""
    voting = [r for r in (rows or []) if r.get("agreement") or r.get("conflict")]
    scored = []
    for r in voting:
        c = _f(r.get("confidence"))
        if c is None:
            continue
        p = max(0.0, min(1.0, c / 100.0))
        hit = 1.0 if bool(r.get("won")) == bool(r.get("agreement")) else 0.0
        scored.append((p - hit) ** 2)
    return round(sum(scored) / len(scored), 4) if scored else None


def calibrate(rows: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    """One engine's calibration over one window — measurement and a suggestion,
    never an action."""
    rs = list(rows or [])
    bk = buckets(rs)
    voting = [r for r in rs if r.get("agreement") or r.get("conflict")]
    n = len(voting)

    claimed = (round(sum(_f(r.get("confidence")) or 0.0 for r in voting) / n, 1)
               if n else None)
    right = sum(1 for r in voting
                if bool(r.get("won")) == bool(r.get("agreement")))
    actual = round(100.0 * right / n, 1) if n else None
    iv = wilson(right, n) if n else None

    gap = round(actual - claimed, 1) if (actual is not None and claimed is not None) else None
    enough = n >= MIN_BUCKET
    # the interval must exclude the claim, not merely differ from it
    proven = bool(enough and iv and not (iv["low"] <= (claimed or 0) <= iv["high"]))

    # Blend rather than replace: a full jump to the observed rate would let one
    # unlucky window rewrite an engine's confidence outright. Half-step, and
    # only when proven.
    suggested = (round(claimed + gap * 0.5, 1)
                 if (proven and gap is not None and abs(gap) >= GAP_EPS)
                 else claimed)

    return {
        "sample": n,
        "claimed_confidence": claimed,
        "historical_accuracy": actual,
        "gap": gap,
        "interval": iv,
        "brier": brier(rs),
        "buckets": bk,
        "significant": enough,
        "proven": proven,
        "suggested_confidence": suggested,
        # nothing in this module applies anything. This flag exists so the UI
        # can never accidentally present a suggestion as a change already made.
        "applied": False,
        "promotable": bool(proven and suggested != claimed),
        "verdict": _verdict(n, claimed, actual, gap, proven),
    }


def _verdict(n: int, claimed, actual, gap, proven: bool) -> str:
    if not n:
        return "No graded votes yet — nothing to calibrate."
    if claimed is None or actual is None:
        return f"{n} votes but no usable confidence values."
    if not proven:
        return (f"Claims {claimed}%, delivers {actual}% over {n} votes — "
                f"within the margin of error. No change recommended.")
    if gap is not None and gap < 0:
        return (f"Overconfident: claims {claimed}%, delivers {actual}% "
                f"({gap:+.1f} pts over {n} votes).")
    return (f"Underconfident: claims {claimed}%, delivers {actual}% "
            f"({gap:+.1f} pts over {n} votes) — it is better than it says.")


def by_engine(joined: Optional[Sequence[Dict[str, Any]]],
              windows: Sequence = WINDOWS) -> Dict[str, Dict[str, Any]]:
    """Every engine × every rolling window. `joined` must be newest-first."""
    b: Dict[str, List[Dict[str, Any]]] = {}
    for r in joined or []:
        b.setdefault(str(r.get("engine")), []).append(r)
    return {eng: {label: calibrate(rs if n is None else rs[:n])
                  for label, n in windows}
            for eng, rs in b.items()}


def suggestions(report: Optional[Dict[str, Dict[str, Any]]],
                window: str = "last100") -> List[Dict[str, Any]]:
    """Only the engines whose miscalibration is actually proven, worst first.

    Returns recommendations. Applying one is a human action — there is no code
    path in MIOS that consumes this list.
    """
    out = []
    for eng, w in (report or {}).items():
        c = (w or {}).get(window) or {}
        if not c.get("promotable"):
            continue
        out.append({"engine": eng, "window": window,
                    "current": c.get("claimed_confidence"),
                    "suggested": c.get("suggested_confidence"),
                    "gap": c.get("gap"), "sample": c.get("sample"),
                    "brier": c.get("brier"),
                    "reason": c.get("verdict"),
                    "action": "REVIEW — human decision required",
                    "auto_applied": False})
    out.sort(key=lambda r: abs(_f(r.get("gap")) or 0.0), reverse=True)
    return out
