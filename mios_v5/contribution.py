"""MIOS V6 — Stage 59 Engine Contribution.

Stage 56 asks *was this engine right?* This asks the harder and more useful
question: **did it matter?**

An engine can be right constantly and contribute nothing, because it only ever
agrees with what four other engines already said. Another can be right less
often and be indispensable, because it is the only voice in the room on the
trades that go wrong. Correlation with the outcome cannot separate those two —
it rewards the redundant engine and punishes the contrarian one, which is
exactly backwards for deciding what to keep.

So this uses **Shapley values**, the one attribution method with the property
that matters here: an engine's credit is its *marginal* effect averaged over
every possible subset of the other engines. A redundant engine gets little
credit because the room reaches the same conclusion without it. A pivotal one
gets a lot because removing it changes the answer.

    v(S)  =  weighted agreement of subset S, in [-1, +1]
    φ_i   =  average over all orderings of  v(S ∪ {i}) − v(S)
    credit=  φ_i signed by whether the trade actually won

Exact for ≤ `_EXACT_MAX` engines (subset enumeration), seeded Monte Carlo above
it. **Seeded, not random** — a learning report that changes on refresh is not a
measurement, and would let anyone re-roll until they liked the answer.

Pure module. Measures and explains; changes no weight.
"""

from __future__ import annotations

import random
from itertools import permutations
from typing import Any, Dict, List, Optional, Sequence

#: exact Shapley below this many voting engines; sampled above it
_EXACT_MAX = 7

#: permutation samples when exact enumeration is too expensive
_SAMPLES = 400

#: |φ| below which an engine is judged to have made no difference
_NEUTRAL_EPS = 0.02

#: fixed seed — the same history must always produce the same report
_SEED = 20260728


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _vote(row: Dict[str, Any]) -> int:
    if row.get("agreement"):
        return 1
    if row.get("conflict"):
        return -1
    return 0


def _weight(row: Dict[str, Any]) -> float:
    """Weight × confidence. An engine that leaned hard gets more credit — and
    more blame."""
    w = _f(row.get("weight"))
    if w is None or w <= 0:
        w = 1.0
    conf = _f(row.get("confidence"))
    return w * max(0.25, (conf if conf is not None else 50.0) / 100.0)


def _value(subset: Sequence[int], votes: Sequence[int],
           weights: Sequence[float]) -> float:
    """Weighted agreement of a subset, in [-1, +1]. Empty subset = no opinion."""
    tw = sum(weights[i] for i in subset)
    if tw <= 0:
        return 0.0
    return sum(weights[i] * votes[i] for i in subset) / tw


def shapley(votes: Sequence[int], weights: Sequence[float],
            samples: int = _SAMPLES) -> List[float]:
    """Shapley value per engine for one trade's vote configuration."""
    n = len(votes)
    if n == 0:
        return []
    if n == 1:
        return [float(votes[0])]

    idx = list(range(n))
    phi = [0.0] * n
    if n <= _EXACT_MAX:
        orders = list(permutations(idx))
    else:
        rng = random.Random(_SEED)
        orders = [rng.sample(idx, n) for _ in range(samples)]

    for order in orders:
        seen: List[int] = []
        prev = 0.0
        for i in order:
            seen.append(i)
            cur = _value(seen, votes, weights)
            phi[i] += cur - prev
            prev = cur
    return [p / len(orders) for p in phi]


def per_trade(rows: Optional[Sequence[Dict[str, Any]]],
              won: Optional[bool] = None) -> List[Dict[str, Any]]:
    """Every engine's contribution to ONE trade.

    `credit` is the Shapley value signed by the outcome: positive means the
    engine pushed the room toward the answer that turned out right, negative
    means it pushed toward the wrong one. An abstaining engine gets 0 — it
    neither helped nor hurt, and scoring abstention either way would let a
    permanently-silent engine accumulate a record.
    """
    rs = [r for r in (rows or []) if _vote(r) != 0]
    if not rs:
        return []
    votes = [_vote(r) for r in rs]
    weights = [_weight(r) for r in rs]
    phis = shapley(votes, weights)

    if won is None:
        won = bool(rs[0].get("won"))
    sgn = 1.0 if won else -1.0

    out = []
    for r, v, w, p in zip(rs, votes, weights, phis):
        credit = round(p * sgn, 4)
        out.append({
            "engine": r.get("engine"),
            "signal_id": r.get("signal_id"),
            "vote": v, "weight": round(w, 3),
            "shapley": round(p, 4),
            "credit": credit,
            "verdict": ("positive" if credit > _NEUTRAL_EPS else
                        "negative" if credit < -_NEUTRAL_EPS else "neutral"),
        })
    return out


def by_engine(joined: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    """Aggregate contribution across the graded history.

    `joined` is `attribution.join_outcomes()` output. Rows are regrouped by
    trade first, because a Shapley value is only meaningful relative to the
    other engines that voted **on that same trade**.
    """
    trades: Dict[str, List[Dict[str, Any]]] = {}
    for r in joined or []:
        sid = r.get("signal_id")
        if sid:
            trades.setdefault(str(sid), []).append(r)

    acc: Dict[str, Dict[str, Any]] = {}
    for sid, rows in trades.items():
        won = bool(rows[0].get("won"))
        for c in per_trade(rows, won=won):
            e = acc.setdefault(str(c["engine"]), {
                "engine": c["engine"], "trades": 0, "positive": 0,
                "negative": 0, "neutral": 0, "total_credit": 0.0,
                "total_influence": 0.0})
            e["trades"] += 1
            e[c["verdict"]] += 1
            e["total_credit"] += c["credit"]
            e["total_influence"] += abs(c["shapley"])

    out = []
    for e in acc.values():
        n = max(1, e["trades"])
        out.append({
            **e,
            "avg_credit": round(e["total_credit"] / n, 4),
            "avg_influence": round(e["total_influence"] / n, 4),
            "positive_rate": round(100.0 * e["positive"] / n, 1),
            "total_credit": round(e["total_credit"], 3),
            "total_influence": round(e["total_influence"], 3),
        })
    out.sort(key=lambda r: -r["avg_credit"])

    ranked = [r for r in out if r["trades"] >= 5]
    influential = sorted(ranked, key=lambda r: -r["avg_influence"])
    # "least useful" is about INFLUENCE, not correctness — an engine nobody
    # needs is a maintenance cost whether or not it happens to be right.
    return {
        "engines": out,
        "top": ranked[:5],
        "weakest": list(reversed(ranked[-5:])) if ranked else [],
        "most_reliable": sorted(ranked, key=lambda r: -r["positive_rate"])[:5],
        "most_influential": influential[:5],
        "least_useful": [r for r in reversed(influential)
                         if r["avg_influence"] < _NEUTRAL_EPS * 2][:5],
        "trades": len(trades),
        "note": ("Shapley credit — marginal effect averaged over every subset "
                 "of the other engines. A redundant engine scores low even "
                 "when it is right."),
    }


def explain(report: Optional[Dict[str, Any]]) -> List[str]:
    """The three or four sentences worth reading off a dashboard."""
    r = report or {}
    n = int(r.get("trades") or 0)
    if not n:
        return ["No graded trades yet — nothing to attribute."]
    out = [f"{n} graded trades attributed."]
    if r.get("top"):
        t = r["top"][0]
        out.append(f"Most valuable: {t['engine']} "
                   f"(+{t['avg_credit']:.3f} avg credit over {t['trades']}).")
    if r.get("weakest"):
        w = r["weakest"][0]
        if w["avg_credit"] < 0:
            out.append(f"Actively harmful: {w['engine']} "
                       f"({w['avg_credit']:+.3f} avg credit) — it moves the "
                       f"room toward the wrong answer more often than not.")
    if r.get("least_useful"):
        names = ", ".join(e["engine"] for e in r["least_useful"][:3])
        out.append(f"Making no difference: {names} — the conclusion is the "
                   f"same with or without them.")
    return out
