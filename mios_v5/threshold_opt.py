"""MIOS V6 — Stage 58 Threshold Optimisation.

Every threshold in Waves 1-4 is a v0 guess I wrote from reasoning, not from
data: `_BEYOND_PCT = 0.02%`, `_MIN_EVIDENCE = 6`, `_TREND_EPS = 0.8`,
`_SWEEP_MAX_CYCLES = 1`. Some are probably right. Some are certainly wrong. This
stage is how we find out which — by sweeping each threshold across the graded
history and asking what *would* have happened.

    "Signals below 72% confidence lost 68% of the time."
    "Entries taken >20 min after the state formed won 2× more often."
    "Requiring 6 evidence families instead of 4 removes 11 losers and 2 winners."

## Why this stage is dangerous, and what stops it

Threshold sweeps overfit. Given enough candidate cut-points and a small sample,
one of them will always look brilliant, and it will always be the sample's noise
rather than the market's structure. Three guards:

1. **`MIN_SAMPLE` per side.** A cut-point that leaves 3 trades above it is not
   evaluated at all — not scored low, *not evaluated*.
2. **Uplift must clear `MIN_UPLIFT`.** A 1.5-point win-rate improvement is
   indistinguishable from luck and is never reported as a finding.
3. **Nothing deploys.** There is no writer in this module. A suggestion carries
   its expected improvement, its sample size on both sides, and what it would
   have cost in missed winners — and then a human decides. Automatic threshold
   movement is the single fastest way to curve-fit a live system into ruin.

The cost side is reported as prominently as the benefit. A filter that removes
11 losers and 2 winners is good; the same filter removing 11 losers and 9
winners is not, and a report showing only the losers removed would sell it just
as hard.

Pure module.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

#: minimum graded trades on EACH side of a candidate cut-point
MIN_SAMPLE = 15

#: win-rate points of improvement below which a finding is noise
MIN_UPLIFT = 5.0

#: default sweep resolution when candidates aren't supplied
_STEPS = 12


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _stats(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0, "win_rate": None, "expectancy": None, "wins": 0,
                "losses": 0}
    wins = sum(1 for r in rows if r.get("won"))
    pnls = [p for p in (_f(r.get("pnl_points")) for r in rows) if p is not None]
    return {
        "n": n, "wins": wins, "losses": n - wins,
        "win_rate": round(100.0 * wins / n, 1),
        "expectancy": round(sum(pnls) / len(pnls), 2) if pnls else None,
        "total_pnl": round(sum(pnls), 1) if pnls else None,
    }


def _candidates(values: Sequence[float], steps: int = _STEPS) -> List[float]:
    """Evenly spaced cut-points across the observed range — not every distinct
    value. Sweeping every value maximises the chance one of them fits noise."""
    vs = sorted(v for v in values if v is not None)
    if len(vs) < 2:
        return []
    lo, hi = vs[0], vs[-1]
    if hi - lo <= 1e-9:
        return []
    step = (hi - lo) / (steps + 1)
    return [round(lo + step * (i + 1), 4) for i in range(steps)]


def sweep(rows: Optional[Sequence[Dict[str, Any]]],
          field: str, current: Any = None,
          direction: str = "min",
          candidates: Optional[Sequence[float]] = None,
          value_of: Optional[Callable[[Dict[str, Any]], Any]] = None,
          ) -> Dict[str, Any]:
    """Sweep one threshold over graded trades.

    `direction="min"` → the rule is "only take trades where value >= threshold"
    `direction="max"` → "only take trades where value <= threshold"

    Returns the current rule's performance, the best candidate, the uplift, and
    — always — what the change would have cost in winners removed.
    """
    getter = value_of or (lambda r: r.get(field))
    rs = [r for r in (rows or [])
          if r.get("outcome") in ("win", "loss") and _f(getter(r)) is not None]
    if not rs:
        return {"field": field, "sample": 0, "suggestion": None,
                "reason": "No graded trades carry this field yet."}

    vals = [_f(getter(r)) for r in rs]
    base = _stats(rs)
    keep = (lambda v, t: v >= t) if direction == "min" else (lambda v, t: v <= t)

    cur = _f(current)
    current_stats = None
    if cur is not None:
        kept = [r for r in rs if keep(_f(getter(r)), cur)]
        current_stats = _stats(kept)
        current_stats["removed"] = _stats([r for r in rs
                                           if not keep(_f(getter(r)), cur)])

    reference = current_stats if (current_stats and current_stats["n"]) else base

    results = []
    for t in (candidates if candidates is not None else _candidates(vals)):
        kept = [r for r in rs if keep(_f(getter(r)), t)]
        dropped = [r for r in rs if not keep(_f(getter(r)), t)]
        if len(kept) < MIN_SAMPLE or len(dropped) < MIN_SAMPLE:
            continue                       # not enough evidence on both sides
        k, d = _stats(kept), _stats(dropped)
        uplift = (round(k["win_rate"] - reference["win_rate"], 1)
                  if (k["win_rate"] is not None
                      and reference["win_rate"] is not None) else None)
        results.append({
            "threshold": t, "kept": k, "removed": d, "uplift": uplift,
            "winners_lost": d["wins"], "losers_avoided": d["losses"],
        })

    if not results:
        return {"field": field, "sample": len(rs), "current": cur,
                "current_stats": current_stats, "baseline": base,
                "candidates": [], "suggestion": None,
                "reason": (f"Not enough data to sweep — every cut-point leaves "
                           f"fewer than {MIN_SAMPLE} trades on one side.")}

    results.sort(key=lambda r: -(r["uplift"] or -999))
    best = results[0]
    good = (best["uplift"] is not None and best["uplift"] >= MIN_UPLIFT
            and best["kept"]["n"] >= MIN_SAMPLE)

    return {
        "field": field, "direction": direction, "sample": len(rs),
        "current": cur, "current_stats": current_stats, "baseline": base,
        "candidates": results[:6],
        "suggestion": ({
            "field": field, "from": cur, "to": best["threshold"],
            "expected_improvement": best["uplift"],
            "kept_sample": best["kept"]["n"],
            "removed_sample": best["removed"]["n"],
            "winners_lost": best["winners_lost"],
            "losers_avoided": best["losers_avoided"],
            "new_win_rate": best["kept"]["win_rate"],
            "new_expectancy": best["kept"]["expectancy"],
            # binding: this is a recommendation, and there is no code that
            # consumes it. A human edits the constant, or nothing changes.
            "action": "REVIEW — human decision required",
            "auto_applied": False,
        } if good else None),
        "reason": (_explain(best) if good else
                   f"Best candidate improves win rate by "
                   f"{best['uplift'] if best['uplift'] is not None else '—'} pts "
                   f"— below the {MIN_UPLIFT}-point noise floor. No change "
                   f"recommended."),
    }


def _explain(best: Dict[str, Any]) -> str:
    k, d = best["kept"], best["removed"]
    return (f"Moving to {best['threshold']} would have kept {k['n']} trades at "
            f"{k['win_rate']}% (from {d['n']} filtered out: "
            f"{best['losers_avoided']} losers avoided, "
            f"{best['winners_lost']} winners lost).")


#: The v0 guesses worth sweeping first — every one of them is a number I chose
#: by reasoning about NIFTY, none by measuring it.
TRACKED_THRESHOLDS = (
    {"field": "confidence", "label": "Signal confidence floor",
     "direction": "min", "current": 70.0, "owner": "stage52_decision"},
    {"field": "evidence_families", "label": "Minimum evidence families",
     "direction": "min", "current": 6.0, "owner": "decision_v2._MIN_EVIDENCE"},
    {"field": "validity_score", "label": "Signal validity score",
     "direction": "min", "current": 60.0, "owner": "stage51_validity"},
    {"field": "rr", "label": "Minimum reward:risk",
     "direction": "min", "current": 1.5, "owner": "stage52_decision"},
    {"field": "state_duration_min", "label": "State maturity before entry",
     "direction": "min", "current": 15.0, "owner": "memory._STRENGTH_STEPS"},
    {"field": "transition_risk", "label": "Maximum transition risk",
     "direction": "max", "current": 60.0, "owner": "memory transition risk"},
)


def optimise(trades: Optional[Sequence[Dict[str, Any]]],
             tracked: Sequence[Dict[str, Any]] = TRACKED_THRESHOLDS,
             ) -> Dict[str, Any]:
    """Sweep every tracked threshold. Returns findings + suggestions, and an
    explicit statement that nothing was deployed."""
    findings = []
    for spec in tracked:
        res = sweep(trades, spec["field"], current=spec.get("current"),
                    direction=spec.get("direction", "min"))
        res["label"], res["owner"] = spec.get("label"), spec.get("owner")
        findings.append(res)
    suggested = [f["suggestion"] for f in findings if f.get("suggestion")]
    suggested.sort(key=lambda s: -(_f(s.get("expected_improvement")) or 0.0))
    return {
        "findings": findings,
        "suggestions": suggested,
        "auto_deployed": False,
        "note": ("Suggestions only. MIOS does not move its own thresholds — "
                 "a human edits the constant after reviewing the sample size "
                 "and the winners the change would have cost."),
    }
