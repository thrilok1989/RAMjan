"""Stage 74 telemetry — measuring the calibration before anything depends on it.

Stage 74's confidence curve, cluster tolerance and POC regime bands were all set
from reasoning. That was the only option: there was nothing to measure. **This
module is how they stop being reasoning and start being calibrated**, and it
exists before the S/R injection on purpose — once Stage 42 consumes these
numbers, changing the scoring changes downstream engine behaviour too, and the
cheap window closes.

## What it measures, and what a bad answer looks like

| Reading | Healthy | What a bad answer means |
|---|---|---|
| confidence distribution | spread across the buckets | one bucket holding everything = the curve is not discriminating |
| engines per cluster | a mix of 2 to 6 | almost all 2 = the ceiling curve is irrelevant, the fix is more level sources |
| POC regime | roughly 25 / 50 / 25 | the quartiles are self-normalising, so a skew means the sampler, not the market |
| cluster count | stable across sessions | swinging wildly = the tolerance is fighting volatility rather than adapting to it |
| acceptance / rejection | Stage 42's own split | context for whether the levels were doing anything |

The engines-per-cluster reading is the one that is easy to miss. If nearly every
cluster is two engines, the difference between a ceiling of 45 and 55 decides
almost nothing, and the useful change is upstream — wire more level sources —
not a steeper curve.

## It never tunes anything

`verdict()` says *too flat*, *too generous*, *too harsh* or *healthy*. It does
not adjust a constant, and nothing here writes to `liquidity.py`. A calibration
that retunes itself from its own output is a feedback loop nobody can audit, and
the whole point of this exercise is an **objective basis for a human to decide**.

## Pure

No database, no Streamlit, no clock. `sample()` takes finished outputs and
returns a row; `summarise()` takes rows and returns distributions. The app
decides when to sample and where to put it — which is what makes this testable
against a week of rows nobody has to collect first.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .liquidity import (BALANCED, POC_REGIMES, SHIFT_STATES, UNKNOWN)

ADVISORY_ONLY = True

VERSION = "74.1-telemetry"

#: Confidence buckets, as specified. Half-open — `[lo, hi)` — except the last,
#: which includes 100 so a perfect cluster lands somewhere.
BUCKETS: Tuple[Tuple[int, int], ...] = (
    (0, 20), (20, 40), (40, 60), (60, 80), (80, 101),
)

BUCKET_LABELS: Tuple[str, ...] = ("0-20", "20-40", "40-60", "60-80", "80-100")

#: Engines-per-cluster buckets. `6+` is one bucket because the ceiling curve is
#: nearly flat above six and splitting further would suggest a precision the
#: calibration does not have.
ENGINE_BUCKETS: Tuple[str, ...] = ("1", "2", "3", "4", "5", "6+")

# ── verdicts ──────────────────────────────────────────────────────────

HEALTHY = "HEALTHY"
TOO_FLAT = "TOO_FLAT"
TOO_GENEROUS = "TOO_GENEROUS"
TOO_HARSH = "TOO_HARSH"
INSUFFICIENT = "INSUFFICIENT"

VERDICTS: Tuple[str, ...] = (HEALTHY, TOO_FLAT, TOO_GENEROUS, TOO_HARSH,
                             INSUFFICIENT)

#: A verdict from a handful of clusters is noise. One trading week at a
#: one-minute sampling cadence is roughly 1,800 samples; this is a floor well
#: below that, so a verdict appears partway through the first day and firms up.
MIN_CLUSTERS = 200

#: One bucket holding this much means the curve is not discriminating —
#: wherever the pile is.
_FLAT_SHARE = 0.65

#: The top bucket holding this much means almost everything is being called
#: high-confidence, which is the same as calling nothing high-confidence.
_GENEROUS_SHARE = 0.60

#: The bottom two buckets holding this much means the curve never rewards
#: agreement, so a consumer gating at 70 would never fire.
_HARSH_SHARE = 0.70

#: A bucket carrying at least this share counts as "reached".
_REACHED_SHARE = 0.05

#: How many buckets a discriminating curve must reach.
#:
#: ⚠️ This is the criterion, not the peak share — and the difference is a bug
#: this module's own simulation caught. A run with 44% in `20-40` and 54% in
#: `40-60` has **no single bucket over 65%**, so a peak-share test calls it
#: healthy; it is 98% of clusters inside a 40-point band and separates almost
#: nothing. Flatness is about spread, and spread has to be measured directly.
_MIN_BUCKETS_REACHED = 3


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _d(v) -> Dict[str, Any]:
    return dict(v) if isinstance(v, Mapping) else {}


def _seq(v) -> List[Any]:
    return list(v) if isinstance(v, (list, tuple)) else []


def bucket_of(confidence: Any) -> Optional[str]:
    """Which confidence bucket, or `None` for `UNKNOWN`.

    `None` rather than a bucket: a cluster whose confidence could not be scored
    is not a low-confidence cluster, and counting it as one would drag the
    distribution toward `TOO_HARSH` for a reason that has nothing to do with the
    curve.
    """
    score = _f(confidence)
    if score is None:
        return None
    for (lo, hi), label in zip(BUCKETS, BUCKET_LABELS):
        if lo <= score < hi:
            return label
    return BUCKET_LABELS[-1] if score >= BUCKETS[-1][0] else BUCKET_LABELS[0]


def _engine_bucket(n: int) -> str:
    return ENGINE_BUCKETS[min(max(1, int(n)), 6) - 1]


# ══════════════════════════════════════════════════════════════════════
#  one sample
# ══════════════════════════════════════════════════════════════════════

def sample(liq: Any = None, reaction: Any = None, atr: Any = None,
           trading_day: Any = None, ts: Any = None,
           cycle: Any = None) -> Dict[str, Any]:
    """One cycle's telemetry row, from Stage 74's finished output.

    `liq`      — `liquidity.analyse()`'s return
    `reaction` — Stage 42's `reaction` block, for the acceptance/rejection split
    `atr`      — Stage 00's ATR, recorded so a tolerance can be explained later

    Never raises and never returns `None`: a degraded cycle should record a thin
    row saying so, because "the engine produced nothing at 14:32" is exactly the
    kind of thing a week of telemetry should show.
    """
    out = _d(liq)
    levels = _d(out.get("levels"))

    every = [l for l in (_seq(levels.get("support"))
                         + _seq(levels.get("resistance"))
                         + _seq(levels.get("at_spot")))]

    hist = {label: 0 for label in BUCKET_LABELS}
    engines_hist = {label: 0 for label in ENGINE_BUCKETS}
    confidences: List[float] = []
    engine_counts: List[int] = []
    unscored = 0

    for level in every:
        conf = getattr(level, "confidence", None)
        diversity = getattr(level, "diversity", None)
        if conf is None and isinstance(level, Mapping):
            conf = level.get("confidence")
            diversity = level.get("diversity")

        label = bucket_of(conf)
        if label is None:
            unscored += 1
        else:
            hist[label] += 1
            confidences.append(float(_f(conf) or 0.0))

        n = int(_f(diversity) or 0)
        if n > 0:
            engines_hist[_engine_bucket(n)] += 1
            engine_counts.append(n)

    poc = _d(out.get("poc_migration"))
    regime = _d(out.get("poc_regime"))
    shift = _d(out.get("liquidity_shift"))
    imb = _d(out.get("liquidity_imbalance"))
    sent = _d(out.get("net_sentiment"))
    div = _d(out.get("money_flow_divergence"))
    react = str(_d(reaction).get("state") or UNKNOWN).upper() or UNKNOWN

    return {
        "version": VERSION,
        "ts": ts, "trading_day": trading_day, "cycle": cycle,
        # ── the calibration readings ──
        "confidence_hist": hist,
        "confidence_scored": len(confidences),
        "confidence_unscored": unscored,
        "confidence_mean": (round(sum(confidences) / len(confidences), 1)
                            if confidences else None),
        "engines_hist": engines_hist,
        "engines_mean": (round(sum(engine_counts) / len(engine_counts), 2)
                         if engine_counts else None),
        "engines_max": (max(engine_counts) if engine_counts else None),
        "clusters": len(every),
        "sources": levels.get("sources"),
        "tolerance_pct": _f(levels.get("tolerance_pct")),
        "atr": _f(atr),
        # ── the context the calibration has to be read against ──
        "poc_regime": str(regime.get("regime") or UNKNOWN),
        "poc_trend": str(poc.get("trend") or UNKNOWN),
        "poc_stability": _f(poc.get("stability")),
        "liquidity_shift": str(shift.get("shift") or UNKNOWN),
        "dominance": str(imb.get("dominance") or UNKNOWN),
        "imbalance_pct": _f(imb.get("pct")),
        "net_sentiment": _f(sent.get("score")),
        "divergence": str(div.get("divergence") or UNKNOWN),
        "reaction": react,
        "ready": bool(out.get("ready")),
    }


# ══════════════════════════════════════════════════════════════════════
#  the week
# ══════════════════════════════════════════════════════════════════════

def _merge(rows: Sequence[Mapping[str, Any]], key: str,
           labels: Sequence[str]) -> Dict[str, int]:
    total = {label: 0 for label in labels}
    for row in rows:
        hist = _d(_d(row).get(key))
        for label in labels:
            total[label] += int(_f(hist.get(label)) or 0)
    return total


def _share(hist: Mapping[str, int]) -> Dict[str, float]:
    n = sum(hist.values())
    return ({k: round(v / n, 4) for k, v in hist.items()} if n
            else {k: 0.0 for k in hist})


def _tally(rows: Sequence[Mapping[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in rows:
        value = str(_d(row).get(key) or UNKNOWN)
        out[value] = out.get(value, 0) + 1
    return out


def _mean(values: Iterable[Any]) -> Optional[float]:
    nums = [x for x in (_f(v) for v in values) if x is not None]
    return round(sum(nums) / len(nums), 2) if nums else None


def summarise(rows: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """A week of samples → the distributions, and a verdict on the curve.

    Reports counts **and** shares. A share alone hides how much was measured,
    and a distribution over eleven clusters looks exactly like one over eleven
    thousand once it is normalised.
    """
    data = [_d(r) for r in _seq(rows)]
    if not data:
        return {"samples": 0, "clusters": 0, "verdict": INSUFFICIENT,
                "why": "no telemetry rows", "confidence": {}, "engines": {}}

    conf_hist = _merge(data, "confidence_hist", BUCKET_LABELS)
    eng_hist = _merge(data, "engines_hist", ENGINE_BUCKETS)
    scored = sum(conf_hist.values())

    verdict = _verdict(conf_hist, eng_hist)

    return {
        "samples": len(data),
        "clusters": scored,
        "unscored": sum(int(_f(r.get("confidence_unscored")) or 0) for r in data),
        "days": len({str(r.get("trading_day")) for r in data
                     if r.get("trading_day")}),
        "confidence": {"counts": conf_hist, "shares": _share(conf_hist),
                       "mean": _mean(r.get("confidence_mean") for r in data)},
        "engines": {"counts": eng_hist, "shares": _share(eng_hist),
                    "mean": _mean(r.get("engines_mean") for r in data),
                    "max": max((int(_f(r.get("engines_max")) or 0)
                                for r in data), default=None)},
        "clusters_per_cycle": _mean(r.get("clusters") for r in data),
        "tolerance_pct": _mean(r.get("tolerance_pct") for r in data),
        "atr": _mean(r.get("atr") for r in data),
        "poc_regime": _tally(data, "poc_regime"),
        "poc_trend": _tally(data, "poc_trend"),
        "liquidity_shift": _tally(data, "liquidity_shift"),
        "dominance": _tally(data, "dominance"),
        "divergence": _tally(data, "divergence"),
        "reaction": _tally(data, "reaction"),
        **verdict,
    }


def _verdict(conf_hist: Mapping[str, int],
             eng_hist: Mapping[str, int]) -> Dict[str, Any]:
    """Is the confidence curve discriminating?

    Order matters. `TOO_GENEROUS` and `TOO_HARSH` are checked before `TOO_FLAT`
    because they are specific diagnoses with specific fixes, and a distribution
    piled at one end is flat *and* skewed — naming only the flatness would send
    someone to the wrong constant.
    """
    total = sum(conf_hist.values())
    if total < MIN_CLUSTERS:
        return {"verdict": INSUFFICIENT, "confident": False,
                "why": f"{total} clusters — a verdict needs at least "
                       f"{MIN_CLUSTERS}",
                "advice": "keep collecting"}

    shares = _share(conf_hist)
    top = shares[BUCKET_LABELS[-1]]
    bottom = shares[BUCKET_LABELS[0]] + shares[BUCKET_LABELS[1]]
    peak_label = max(shares, key=lambda k: shares[k])
    peak = shares[peak_label]
    reached = sum(1 for s in shares.values() if s >= _REACHED_SHARE)

    # The reading that is easy to miss: if almost every cluster has two
    # engines, the ceiling curve decides almost nothing and a steeper curve
    # would be the wrong fix.
    eng_total = sum(eng_hist.values())
    two_or_fewer = ((eng_hist.get("1", 0) + eng_hist.get("2", 0)) / eng_total
                    if eng_total else 0.0)
    thin = two_or_fewer >= 0.80

    if top >= _GENEROUS_SHARE:
        verdict, advice = TOO_GENEROUS, (
            "lower the diversity anchors — almost everything is being called "
            "high-confidence, which is the same as calling nothing "
            "high-confidence")
    elif bottom >= _HARSH_SHARE:
        verdict, advice = TOO_HARSH, (
            "raise the diversity anchors — a consumer gating at 70 would "
            "never fire")
    elif peak >= _FLAT_SHARE:
        verdict, advice = TOO_FLAT, (
            f"steepen the curve around the {peak_label} band — it is holding "
            f"{peak:.0%} of clusters and not separating them")
    elif reached < _MIN_BUCKETS_REACHED:
        # Spread, measured directly. Two adjacent buckets holding everything is
        # flat even when neither one crosses the peak threshold.
        verdict, advice = TOO_FLAT, (
            f"only {reached} of {len(BUCKET_LABELS)} buckets carry a "
            f"meaningful share — the curve is compressing every cluster into a "
            f"narrow band and separating almost nothing")
    else:
        verdict, advice = HEALTHY, "the curve is discriminating — freeze it"

    if thin and verdict != HEALTHY:
        advice = (f"{two_or_fewer:.0%} of clusters have two engines or fewer, "
                  f"so the ceiling curve decides very little. Wire more level "
                  f"sources before retuning it — " + advice)

    return {
        "verdict": verdict, "confident": True, "advice": advice,
        "why": (f"{total:,} clusters · peak {peak:.0%} in {peak_label} · "
                f"{reached} of {len(BUCKET_LABELS)} buckets reached"),
        "peak_bucket": peak_label, "peak_share": round(peak, 4),
        "top_share": round(top, 4), "bottom_share": round(bottom, 4),
        "buckets_reached": reached,
        "thin_clusters": thin,
        "two_or_fewer_share": round(two_or_fewer, 4),
    }


def ready_to_freeze(summary: Optional[Mapping[str, Any]] = None,
                    days: int = 5) -> Dict[str, Any]:
    """Is there enough evidence to freeze the calibration?

    Deliberately strict about **days**, not just samples. A single volatile
    session produces thousands of clusters and tells you how the curve behaves
    on a volatile session; a week tells you whether it survives a quiet Tuesday
    and an expiry Thursday, which is the question.
    """
    s = _d(summary)
    got_days = int(_f(s.get("days")) or 0)
    clusters = int(_f(s.get("clusters")) or 0)
    verdict = str(s.get("verdict") or INSUFFICIENT)

    blockers: List[str] = []
    if got_days < days:
        blockers.append(f"{got_days} of {days} trading days collected")
    if clusters < MIN_CLUSTERS:
        blockers.append(f"{clusters} of {MIN_CLUSTERS} clusters")
    if verdict == INSUFFICIENT:
        blockers.append("no verdict yet")
    elif verdict != HEALTHY:
        blockers.append(f"verdict is {verdict} — retune before freezing")

    return {"ready": not blockers, "blockers": tuple(blockers),
            "days": got_days, "clusters": clusters, "verdict": verdict,
            "why": ("enough evidence across enough sessions — freeze the "
                    "calibration, then inject"
                    if not blockers else "; ".join(blockers))}
