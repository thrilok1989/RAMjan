"""MIOS V6 — Stage 56 Engine Accuracy Tracker.

Forty-five engines vote. Until now, none of them has ever been told whether it
was right. This measures each one independently, over four rolling windows, and
publishes the answer whether or not it is flattering.

**The confusion matrix, stated in trading terms.** For one engine on one graded
trade:

    agreed with the trade + trade won   →  TP   it helped
    agreed with the trade + trade lost  →  FP   it misled  ← the expensive one
    stayed out / opposed  + trade won   →  FN   it missed
    opposed the trade     + trade lost  →  TN   it warned, correctly

From that: accuracy, precision, recall, false-positive rate, false-negative
rate. **Precision is the number that matters most** — it answers "when this
engine says yes, how often is it right?", which is the only question the
Decision Engine ever asks of it. A high-recall, low-precision engine says yes to
everything and is worse than useless because it looks agreeable.

Two deliberate refusals:

1. **NEUTRAL is not a vote.** An engine that declined to lean is scored as
   abstaining, not as opposing. Counting abstentions as correct predictions
   would let a permanently-neutral engine post a great record while
   contributing nothing.
2. **Small samples are labelled, not hidden.** Ten trades is not evidence. The
   number is still shown — with its sample size and an explicit
   `significant: False` — because concealing a weak result is how a learning
   system starts lying to its owner.

Pure module: rows in, metrics out. No IO, no pandas, no promotion, no writes
back into the live path.
"""

from __future__ import annotations

from math import sqrt
from typing import Any, Dict, List, Optional, Sequence

#: rolling windows, newest-first slices of the graded history
WINDOWS = (("last30", 30), ("last100", 100), ("last500", 500),
           ("lifetime", None))

#: below this, a rate is reported but never called significant
MIN_SAMPLE = 20

#: the ranking floor — an engine with fewer than this is unranked, not last
RANK_MIN_SAMPLE = 10


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _rate(num: int, den: int) -> Optional[float]:
    return round(100.0 * num / den, 1) if den else None


def _mean(vals: Sequence[Optional[float]]) -> Optional[float]:
    xs = [v for v in vals if v is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def wilson(successes: int, n: int, z: float = 1.96) -> Optional[Dict[str, float]]:
    """Wilson score interval — the honest confidence band on a win rate.

    A naive 7/10 = 70% reads as a strong engine. Wilson puts the true rate
    somewhere in 40-90%, which is the correct amount of doubt and the reason
    nothing gets promoted on ten trades.
    """
    if n <= 0:
        return None
    p = successes / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = (z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d
    return {"low": round(100.0 * max(0.0, centre - half), 1),
            "high": round(100.0 * min(1.0, centre + half), 1),
            "centre": round(100.0 * centre, 1)}


def _window(rows: Sequence[Dict[str, Any]], n: Optional[int]
            ) -> List[Dict[str, Any]]:
    """Newest `n` rows. Callers pass history newest-first."""
    return list(rows if n is None else rows[:n])


def engine_metrics(rows: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    """The full metric set for ONE engine over ONE window of graded rows."""
    rs = list(rows or [])
    n = len(rs)
    if not n:
        return {"sample": 0, "significant": False}

    # ── the matrix. Abstentions are excluded outright, not folded into TN. ──
    tp = fp = fn = tn = 0
    for r in rs:
        won = bool(r.get("won"))
        if r.get("agreement"):
            tp, fp = tp + (1 if won else 0), fp + (0 if won else 1)
        elif r.get("conflict"):
            fn, tn = fn + (1 if won else 0), tn + (0 if won else 1)

    voted = tp + fp + fn + tn
    abstained = n - voted
    wins = sum(1 for r in rs if r.get("won"))
    agreed, agreed_wins = tp + fp, tp

    hold = _mean([_f(r.get("holding_secs")) for r in rs])

    return {
        "sample": n,
        "voted": voted,
        "abstained": abstained,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        # accuracy only over the trades where it actually took a side
        "accuracy": _rate(tp + tn, voted),
        "precision": _rate(tp, tp + fp),
        "recall": _rate(tp, tp + fn),
        "win_rate": _rate(agreed_wins, agreed),
        "loss_rate": _rate(agreed - agreed_wins, agreed),
        "false_positive_rate": _rate(fp, fp + tn),
        "false_negative_rate": _rate(fn, fn + tp),
        "overall_win_rate": _rate(wins, n),
        "avg_confidence": _mean([_f(r.get("confidence")) for r in rs]),
        "avg_holding_min": round(hold / 60.0, 1) if hold is not None else None,
        "avg_mfe": _mean([_f(r.get("mfe")) for r in rs]),
        "avg_mae": _mean([_f(r.get("mae")) for r in rs]),
        "avg_pnl": _mean([_f(r.get("pnl_points")) for r in rs]),
        "interval": wilson(agreed_wins, agreed),
        "significant": agreed >= MIN_SAMPLE,
        "voted_share": _rate(voted, n),
    }


def by_engine(joined: Optional[Sequence[Dict[str, Any]]],
              windows: Sequence = WINDOWS) -> Dict[str, Dict[str, Any]]:
    """Every engine × every window. `joined` is `attribution.join_outcomes()`
    output, **newest first**."""
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for r in joined or []:
        buckets.setdefault(str(r.get("engine")), []).append(r)
    return {
        eng: {label: engine_metrics(_window(rs, n)) for label, n in windows}
        for eng, rs in buckets.items()
    }


def rank(report: Optional[Dict[str, Dict[str, Any]]],
         window: str = "last100", metric: str = "precision",
         ) -> List[Dict[str, Any]]:
    """Engines ordered by how much they can be trusted.

    Engines below `RANK_MIN_SAMPLE` are returned with `ranked: False` and sorted
    to the bottom — untested is not the same as bad, and burying a new engine at
    the bottom of a leaderboard is how good ideas get quietly killed.
    """
    out = []
    for eng, w in (report or {}).items():
        m = (w or {}).get(window) or {}
        val = _f(m.get(metric))
        ranked = int(m.get("sample") or 0) >= RANK_MIN_SAMPLE and val is not None
        out.append({"engine": eng, "metric": metric, "value": val,
                    "sample": m.get("sample", 0),
                    "significant": bool(m.get("significant")),
                    "ranked": ranked, "interval": m.get("interval"),
                    "precision": _f(m.get("precision")),
                    "recall": _f(m.get("recall")),
                    "win_rate": _f(m.get("win_rate")),
                    "avg_confidence": _f(m.get("avg_confidence"))})
    out.sort(key=lambda r: (not r["ranked"], -(r["value"] or 0.0)))
    return out


def verdict(m: Optional[Dict[str, Any]]) -> str:
    """One sentence a human can act on. Says 'not enough data' when that is
    the truth, instead of dressing noise up as a finding."""
    d = m or {}
    n = int(d.get("sample") or 0)
    if not n:
        return "No graded trades yet."
    if not d.get("significant"):
        return (f"Only {n} graded trade{'s' if n != 1 else ''} — "
                f"not enough to judge. Reported, not trusted.")
    p, w = _f(d.get("precision")), _f(d.get("win_rate"))
    iv = d.get("interval") or {}
    band = (f" (true rate likely {iv.get('low')}–{iv.get('high')}%)"
            if iv else "")
    if p is None:
        return f"Never took a side in {n} trades — contributes nothing."
    if p >= 65:
        return f"Reliable: {p}% precision over {n} trades{band}."
    if p >= 50:
        return f"Marginal: {p}% precision — barely better than a coin{band}."
    return (f"Underperforming: {p}% precision over {n} trades{band} — "
            f"when it agrees, the trade loses more often than it wins.")
