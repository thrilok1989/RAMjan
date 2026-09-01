"""Stage 71.86 — Profile Shape.

**The one fact in the Liquidity & Sentiment specification that had no owner.**

`docs/AUDIT_STAGE_71_86_LIQUIDITY_SENTIMENT.md` checked all ten blocks of that
spec against the tree. Eight were already owned — HVN/LVN/POC/VAH/VAL three
times over, per-level sentiment by `calculate_money_flow_profile`, the dynamic
POC series by `compute_dynamic_poc`, liquidity and volume behaviour by Stage
71.7's `SHIFT_*` vocabulary, the premium profile by Stage 71.8, the S/R
behaviour axis by Stage 71.85. One was a missing *input* to Stage 45 rather than
a missing engine.

This is the remaining one.

## It computes nothing about price

Every number here is derived from **bins another module already published**.
This module does not open a candle series, does not bin volume, does not locate
a POC and does not classify HVN/LVN. It reads a finished profile and names its
*shape* — which is a statement about the distribution, not about the market.

```
calculate_money_flow_profile  →  rows  →  Stage 71.86  →  shape
compute_vpfr                  →  poc · vah · val  ↗
```

A fifth POC implementation is forbidden by audit 71.8 and a test asserts it.
Nothing here would trip that test, because nothing here computes one.

## The shapes, and what each one is a claim about

Classical market profile — Steidlmayer, decades older than any charting
platform, and described here from the distribution rather than ported from
anyone's implementation.

| Shape | The distribution | What a trader reads from it |
|---|---|---|
| `P` | mass high in the range, thin tail below | buying drove up then balanced — short covering |
| `b` | mass low in the range, thin tail above | selling drove down then balanced — long liquidation |
| `D` | mass central and tight | balance; the middle is fair value |
| `Double Distribution` | two separated peaks, a valley between | two areas of acceptance, one rejection band between them |
| `Trend` | mass spread evenly, no dominant node | price kept moving; nothing was accepted long enough to build |
| `Balanced` | mass central but wide | balance across a broad area — rotation, not conviction |
| `Thin` | most levels barely traded | little participation; the levels are weakly held |
| `Neutral` | nothing agreed | **an absence of a read, not a weak one** |

## `Neutral` is an absence, and it says so

When no signature wins by a clear margin the shape is `Neutral` and the
confidence is `UNKNOWN` — not a low number. This follows Stage 71.85 exactly,
where `Neutral` maps to `None` in Stage 72's scales so it leaves the denominator
instead of scoring 50. "We could not tell" must never hold a score up.

## Advisory

`ADVISORY_ONLY = True`. Nothing consumes this to make a decision yet. It is
published, rendered on the three charts, and left to be watched — the same
posture Stage 74 is in while its calibration week runs.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass, field as _dc_field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

UNKNOWN = "UNKNOWN"

VERSION = "71.86.0"

ADVISORY_ONLY = True

#: The facts this module owns. Nothing else in MIOS publishes any of them.
COMPUTED_HERE: Tuple[str, ...] = (
    "shape", "shape_confidence", "poc_position", "concentration",
    "bimodality", "participation", "skew",
)

#: Every consumed fact and the one thing that owns it. A name here that this
#: module starts *computing* is a regression, and a test asserts it.
CONSUMED: Mapping[str, str] = MappingProxyType({
    "rows": "calculate_money_flow_profile (indicators/money_flow_profile)",
    "total_volume": "calculate_money_flow_profile — per-bin volume",
    "node_type": "calculate_money_flow_profile — HVN/LVN already classified",
    "sentiment": "calculate_money_flow_profile — per-bin bull/bear split",
    "poc": "compute_vpfr — the ONE POC owner (audit 71.8)",
    "value_area": "compute_vpfr",
})

# ══════════════════════════════════════════════════════════════════════
#  the shapes
# ══════════════════════════════════════════════════════════════════════

P_SHAPE = "P"
B_SHAPE = "b"
D_SHAPE = "D"
DOUBLE = "Double Distribution"
TREND = "Trend"
BALANCED = "Balanced"
THIN = "Thin"
NEUTRAL = "Neutral"

SHAPES: Tuple[str, ...] = (P_SHAPE, B_SHAPE, D_SHAPE, DOUBLE, TREND,
                           BALANCED, THIN, NEUTRAL)

LABEL: Mapping[str, str] = MappingProxyType({
    P_SHAPE: "🅿 P — short covering",
    B_SHAPE: "🅑 b — long liquidation",
    D_SHAPE: "🅓 D — balance",
    DOUBLE: "⚌ Double Distribution",
    TREND: "➔ Trend",
    BALANCED: "⚖ Balanced",
    THIN: "░ Thin",
    NEUTRAL: "· Neutral",
})

#: A profile needs enough bins for "where the mass sits" to mean anything. Ten
#: is the floor `calculate_money_flow_profile` itself allows; below it the
#: position of the heaviest bin is too coarse to separate P from D.
MIN_BINS = 10

#: A bin carrying less than this share of the heaviest bin is a thin level.
#: `calculate_money_flow_profile` uses the same idea for its own LVN cut, and
#: this is deliberately the same number so "thin" means one thing in MIOS.
_LVN_RATIO = 0.21

#: …and this much of the heaviest bin makes a peak worth calling a peak.
_PEAK_RATIO = 0.70

#: For a valley between two peaks to count as a rejection band it must fall
#: this far below the *lower* of the two. A shallow dip between two humps is
#: one distribution with texture, not two distributions.
_VALLEY_RATIO = 0.55

#: Where the heaviest bin sits in the range, as a fraction from low to high.
#: Outside these bounds the mass is at one end rather than in the middle.
_HIGH_POC = 0.62
_LOW_POC = 0.38

#: Normalised entropy above this means the volume is spread evenly enough that
#: no level was held — the signature of a trend rather than a balance.
_TREND_ENTROPY = 0.93

#: …and below this the mass is concentrated enough to call it tight.
_TIGHT_ENTROPY = 0.82

#: How fast an end signature (P · b) decays once the POC leaves its band. Small
#: on purpose: just outside the threshold is the central band's territory, and
#: an end shape claiming the mass is at an end must not half-agree at dead
#: centre.
_END_SPAN = 0.08

#: The central signatures decay more gently — "near the middle" is a genuinely
#: fuzzier claim than "at the top".
_CENTRE_SPAN = 0.14

#: What a unimodal signature keeps when the profile has two separated peaks.
#: Not zero: a double distribution with a dominant half is still partly the
#: shape of that half, and the margin gate should see that rather than have it
#: erased.
_MULTIMODAL_PENALTY = 0.20

#: A shape must beat the runner-up by this much of the winning score before it
#: is named. Below it the answer is `Neutral` with `UNKNOWN` confidence.
_MARGIN = 0.12

#: Most levels barely traded → Thin, whatever else the distribution looks like.
_THIN_SHARE = 0.70


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def shape_hash(shape_id: str, version: str, shape: str, confidence: Any,
               created_at: str) -> str:
    """SHA-256 over identity plus verdict, matching every other stage."""
    parts = [str(shape_id), str(version), str(shape), str(confidence),
             str(created_at)]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


@dataclass(frozen=True)
class ProfileShape:
    """One profile's shape, with the measurements that named it.

    Frozen, and every measurement it used is on the object. A shape a reader
    cannot check against `poc_position` and `concentration` is a label.
    """
    shape: str
    confidence: Any
    poc_position: Any
    concentration: Any
    bimodality: Any
    participation: Any
    skew: Any
    why: str
    top_reasons: Tuple[str, ...]
    scores: Mapping[str, Any]
    reporting: int
    of: int
    id: str = ""
    version: str = VERSION
    created_at: str = ""
    hash: str = ""
    advisory_only: bool = ADVISORY_ONLY
    metadata: Mapping[str, Any] = _dc_field(
        default_factory=lambda: MappingProxyType({}))

    @property
    def label(self) -> str:
        return LABEL.get(self.shape, self.shape)

    def verify(self) -> bool:
        return self.hash == shape_hash(self.id, self.version, self.shape,
                                       self.confidence, self.created_at)

    def identity(self) -> Dict[str, Any]:
        return {"id": self.id, "version": self.version,
                "created_at": self.created_at, "hash": self.hash}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "version": self.version,
            "created_at": self.created_at, "hash": self.hash,
            "shape": self.shape, "label": self.label,
            "confidence": self.confidence,
            "poc_position": self.poc_position,
            "concentration": self.concentration,
            "bimodality": self.bimodality,
            "participation": self.participation,
            "skew": self.skew,
            "why": self.why, "top_reasons": list(self.top_reasons),
            "scores": dict(self.scores),
            "reporting": self.reporting, "of": self.of,
            "advisory_only": self.advisory_only,
            "metadata": dict(self.metadata),
        }


def _weights(rows: Sequence[Mapping[str, Any]]) -> List[float]:
    """Per-bin volume, low price first. Missing volume is 0, never guessed."""
    out: List[float] = []
    for r in rows:
        v = _f(r.get("total_volume"))
        if v is None:
            v = _f(r.get("volume")) or 0.0
        out.append(max(0.0, v))
    return out


def _ordered(rows: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """Rows sorted low price → high price.

    The producer's order is not guaranteed, and every measurement below is
    positional. Sorting on the price the row already carries is cheaper than
    trusting a convention that no test enforces.
    """
    keyed = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        price = _f(r.get("price_level"))
        if price is None:
            lo, hi = _f(r.get("bin_low")), _f(r.get("bin_high"))
            price = None if lo is None or hi is None else (lo + hi) / 2.0
        if price is not None:
            keyed.append((price, r))
    keyed.sort(key=lambda kr: kr[0])
    return [r for _, r in keyed]


def _entropy(w: Sequence[float]) -> Optional[float]:
    """Normalised Shannon entropy of the volume distribution, 0…1.

    1.0 = every level traded equally (nothing was held). 0.0 = all of it in one
    level. This is the single measurement that separates a trend profile from a
    balance, and it needs no thresholds of its own to compute.
    """
    total = sum(w)
    if total <= 0 or len(w) < 2:
        return None
    h = 0.0
    for v in w:
        if v > 0:
            p = v / total
            h -= p * math.log(p)
    return h / math.log(len(w))


def _peaks(w: Sequence[float]) -> Tuple[int, Optional[float]]:
    """How many separated peaks, and how deep the deepest valley between them.

    A peak is a bin at or above `_PEAK_RATIO` of the heaviest. Two peaks are
    *separated* only if some bin between them drops below `_VALLEY_RATIO` of
    the lower peak — otherwise it is one distribution with a rough top.
    """
    top = max(w) if w else 0.0
    if top <= 0:
        return 0, None
    idx = [i for i, v in enumerate(w) if v >= _PEAK_RATIO * top]
    if not idx:
        return 0, None

    groups: List[List[int]] = [[idx[0]]]
    for i in idx[1:]:
        if i == groups[-1][-1] + 1:
            groups[-1].append(i)
        else:
            groups.append([i])

    if len(groups) < 2:
        return 1, None

    deepest = None
    for a, b in zip(groups, groups[1:]):
        lo_peak = min(max(w[i] for i in a), max(w[i] for i in b))
        valley = min(w[a[-1] + 1:b[0]] or [lo_peak])
        depth = 1.0 - (valley / lo_peak if lo_peak > 0 else 1.0)
        if deepest is None or depth > deepest:
            deepest = depth

    separated = sum(
        1 for a, b in zip(groups, groups[1:])
        if min(w[a[-1] + 1:b[0]] or [1.0])
        < _VALLEY_RATIO * min(max(w[i] for i in a), max(w[i] for i in b)))
    return (len(groups) if separated else 1), deepest


def measure(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The five measurements, before any shape is named.

    Exposed separately so a reader can check the shape against the numbers that
    produced it, and so the classifier can be tested without a profile.
    """
    ordered = _ordered(rows or [])
    n = len(ordered)
    if n < MIN_BINS:
        return {"n": n, "enough": False,
                "why": f"{n} bins reported, {MIN_BINS} needed"}

    w = _weights(ordered)
    total = sum(w)
    if total <= 0:
        return {"n": n, "enough": False, "why": "no bin carried volume"}

    top = max(w)
    poc_idx = w.index(top)
    poc_position = poc_idx / (n - 1)

    # centre of mass, same 0…1 axis as the POC — the two disagree when a long
    # tail pulls the average away from the peak, which is what skew measures.
    com = sum(i * v for i, v in enumerate(w)) / total / (n - 1)

    entropy = _entropy(w)
    peaks, valley = _peaks(w)
    thin_share = sum(1 for v in w if v < _LVN_RATIO * top) / n

    return {
        "n": n, "enough": True,
        "poc_position": round(poc_position, 3),
        "centre_of_mass": round(com, 3),
        "skew": round(poc_position - com, 3),
        "concentration": None if entropy is None else round(1.0 - entropy, 3),
        "entropy": None if entropy is None else round(entropy, 3),
        "peaks": peaks,
        "bimodality": None if valley is None else round(valley, 3),
        "participation": round(1.0 - thin_share, 3),
        "thin_share": round(thin_share, 3),
    }


def _score(m: Mapping[str, Any]) -> Dict[str, float]:
    """Every shape's signature, scored 0…1 from the measurements.

    Scored rather than branched so the margin between first and second place is
    available — that margin is what decides whether the answer is a shape or an
    honest `Neutral`.
    """
    pos = m["poc_position"]
    ent = m["entropy"] if m["entropy"] is not None else 0.5
    thin = m["thin_share"]
    peaks = m["peaks"]
    valley = m["bimodality"] or 0.0

    def band(v: float, lo: float, hi: float, span: float) -> float:
        """1.0 inside [lo, hi], decaying to 0 over `span` outside it.

        `span` is per-signature and not derived from the band's own width. A
        band derived from its width made the *end* signatures forgiving in
        exactly the region where they must not be: with a half-width fall-off,
        a POC at 45% of the range — dead centre, and inside the central band —
        still scored 0.6 as "mass at the bottom".
        """
        if lo <= v <= hi:
            return 1.0
        d = (lo - v) if v < lo else (v - hi)
        return max(0.0, 1.0 - d / span)

    # An end signature is a claim that the mass is AT an end, so it decays
    # fast: just outside the threshold is already the central band's territory.
    high_end = band(pos, _HIGH_POC, 1.0, _END_SPAN)
    low_end = band(pos, 0.0, _LOW_POC, _END_SPAN)
    centre = band(pos, _LOW_POC, _HIGH_POC, _CENTRE_SPAN)

    # P, b, D and Balanced all describe ONE mass. Two separated peaks is a
    # different claim about the same profile, and the strongest one available —
    # a double distribution whose upper peak is heaviest looks exactly like a P
    # until this is applied, and reading it as a P hides the rejection band
    # that makes it tradeable.
    unimodal = 1.0 if peaks < 2 else _MULTIMODAL_PENALTY
    tight = max(0.0, min(1.0, (_TIGHT_ENTROPY - ent) / 0.25 + 0.5))
    spread = max(0.0, min(1.0, (ent - _TREND_ENTROPY) / 0.07 + 0.5))

    return {
        # mass at one end with the rest of the range thin behind it
        P_SHAPE: unimodal * high_end * (0.55 + 0.45 * min(1.0, thin / 0.45)),
        B_SHAPE: unimodal * low_end * (0.55 + 0.45 * min(1.0, thin / 0.45)),
        # two accepted areas with a rejection band between them
        DOUBLE: (1.0 if peaks >= 2 else 0.0) * (0.5 + 0.5 * valley),
        # everything traded, nothing held
        TREND: spread * (1.0 - 0.5 * tight),
        # mass in the middle and tight
        D_SHAPE: unimodal * centre * tight,
        # mass in the middle but broad
        BALANCED: unimodal * centre * (1.0 - tight) * (1.0 - 0.6 * spread),
        # most levels barely traded at all
        THIN: max(0.0, min(1.0, (thin - _THIN_SHARE) / 0.20 + 0.5))
        if thin >= _THIN_SHARE else 0.0,
    }


def classify(rows: Sequence[Mapping[str, Any]] = (),
             poc: Any = None, vah: Any = None, val: Any = None,
             source: str = UNKNOWN) -> ProfileShape:
    """Name the shape of a profile somebody else built.

    `poc`, `vah` and `val` are **carried, not used** — they come from the one
    POC owner and travel on the metadata so a panel can render the shape beside
    the levels without a second lookup. Recomputing any of them here would be
    the fifth POC implementation that audit 71.8 forbade.
    """
    m = measure(rows or ())
    ident_id = str(uuid.uuid4())
    created = _now_iso()
    meta = MappingProxyType({
        "poc": _f(poc), "vah": _f(vah), "val": _f(val),
        "source": source, "consumed": CONSUMED,
        "measurements": MappingProxyType(dict(m)),
    })

    def _build(shape: str, confidence: Any, why: str,
               reasons: Tuple[str, ...], scores: Mapping[str, Any],
               reporting: int, of: int) -> ProfileShape:
        return ProfileShape(
            shape=shape, confidence=confidence,
            poc_position=m.get("poc_position", UNKNOWN),
            concentration=m.get("concentration", UNKNOWN),
            bimodality=m.get("bimodality", UNKNOWN),
            participation=m.get("participation", UNKNOWN),
            skew=m.get("skew", UNKNOWN),
            why=why, top_reasons=reasons,
            scores=MappingProxyType(dict(scores)),
            reporting=reporting, of=of,
            id=ident_id, created_at=created,
            hash=shape_hash(ident_id, VERSION, shape, confidence, created),
            metadata=meta)

    if not m.get("enough"):
        # No profile is not a flat profile. Everything reports UNKNOWN.
        return _build(NEUTRAL, UNKNOWN, m.get("why", "no profile supplied"),
                      (), {}, 0, len(SHAPES) - 1)

    scores = _score(m)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    runner, runner_score = ranked[1]

    if best_score <= 0:
        return _build(NEUTRAL, UNKNOWN,
                      "no shape signature scored above zero", (), scores,
                      m["n"], len(SHAPES) - 1)

    margin = (best_score - runner_score) / best_score
    if margin < _MARGIN:
        # Two shapes fit equally well. That is an absence of a read, and it
        # reports as one — never as a low-confidence guess between them.
        return _build(
            NEUTRAL, UNKNOWN,
            f"{best} and {runner} fit equally well "
            f"({best_score:.2f} vs {runner_score:.2f})",
            (f"{best} {best_score:.2f}", f"{runner} {runner_score:.2f}"),
            scores, m["n"], len(SHAPES) - 1)

    # Confidence is the fit AND the separation: a signature that scores well
    # but only just beats the next one is not a confident read of either.
    confidence = round(100.0 * best_score * (0.55 + 0.45 * min(1.0, margin / 0.5)), 1)

    why = {
        P_SHAPE: f"volume sits high in the range (POC at {m['poc_position']:.0%})"
                 f" with {m['thin_share']:.0%} of levels thin below",
        B_SHAPE: f"volume sits low in the range (POC at {m['poc_position']:.0%})"
                 f" with {m['thin_share']:.0%} of levels thin above",
        DOUBLE: f"{m['peaks']} separated peaks, deepest valley "
                f"{(m['bimodality'] or 0):.0%} below the lower peak",
        TREND: f"volume spread evenly (entropy {m['entropy']:.2f}) — "
               f"no level was held",
        D_SHAPE: f"volume concentrated in the middle "
                 f"(POC at {m['poc_position']:.0%}, entropy {m['entropy']:.2f})",
        BALANCED: f"volume central but broad "
                  f"(POC at {m['poc_position']:.0%}, entropy {m['entropy']:.2f})",
        THIN: f"{m['thin_share']:.0%} of levels traded below the thin cut",
    }.get(best, best)

    reasons = tuple(f"{name} {score:.2f}" for name, score in ranked[:3]
                    if score > 0)
    return _build(best, confidence, why, reasons, scores, m["n"],
                  len(SHAPES) - 1)


def run(rows: Sequence[Mapping[str, Any]] = (), poc: Any = None,
        vah: Any = None, val: Any = None,
        source: str = UNKNOWN) -> ProfileShape:
    """Convenience: `profile_shape.run(rows, poc=…)`. Never raises."""
    try:
        return classify(rows, poc=poc, vah=vah, val=val, source=source)
    except Exception as err:      # a shape must never take a panel down
        ident_id, created = str(uuid.uuid4()), _now_iso()
        return ProfileShape(
            shape=NEUTRAL, confidence=UNKNOWN, poc_position=UNKNOWN,
            concentration=UNKNOWN, bimodality=UNKNOWN,
            participation=UNKNOWN, skew=UNKNOWN,
            why=f"profile could not be read: {err}", top_reasons=(),
            scores=MappingProxyType({}), reporting=0, of=len(SHAPES) - 1,
            id=ident_id, created_at=created,
            hash=shape_hash(ident_id, VERSION, NEUTRAL, UNKNOWN, created))
