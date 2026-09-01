"""MIOS V6.5 — Stage 66 AI Post-Trade Review.

The moment a trade closes, explain it — while the trader still remembers what
it felt like.

    Outcome        Winner
    Why            Support proven · acceptance confirmed · buyer absorption
    Best engine    Stage 42 Acceptance  (+0.31 credit)
    Weakest        Stage 47 Bias Transition  (−0.12 credit)
    Improvement    Ran +48, captured +30 — the trail gave back 18 points.

## Winners get reviewed too

The temptation is to review only losses. That is how a system spends a year
congratulating itself on trades that were half-managed: a +50 winner out of a
+55 run and a +50 winner out of a +200 run are the same row in a P&L and
completely different pieces of work. `improvement` exists to name the second
one, and it fires on winners specifically.

## Best and weakest engine come from Shapley credit, not from being right

An engine that agreed and happened to win is not thereby the best engine —
four others may have said the same thing, in which case it decided nothing.
Stage 59's marginal credit is what separates *right* from *decisive*, so this
stage reuses it rather than re-deriving a simpler and wronger answer. Same for
losses: Stage 60 already investigates them, and this stage formats that
investigation rather than running a second, competing one.

Pure module. Reviews; never adjusts anything it reviewed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .contribution import per_trade
from .false_signal import CAUSES, investigate
from .narrator import summarise as summarise_beats

#: points left on the table before the exit is called out as improvable
_GIVEBACK_PTS = 8.0

#: fraction of the favourable run that must be captured to count as well traded
_GOOD_EFFICIENCY = 0.60


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _eng(name: Optional[str]) -> str:
    return str(name or "—")


def _credits(engine_rows, won: bool) -> List[Dict[str, Any]]:
    try:
        return per_trade(engine_rows, won=won)
    except Exception:
        return []


def review(trade: Optional[Dict[str, Any]],
           result: Optional[Dict[str, Any]] = None,
           engine_rows: Optional[Sequence[Dict[str, Any]]] = None,
           events: Optional[Sequence[Dict[str, Any]]] = None,
           beats: Optional[Sequence[Dict[str, Any]]] = None,
           ) -> Dict[str, Any]:
    """One closed trade, explained. Works for a winner and for a loser, and
    says which it is doing."""
    t, r = dict(trade or {}), dict(result or {})
    outcome = str(r.get("outcome") or "").lower()
    if outcome not in ("win", "loss"):
        return {"available": False,
                "reason": "Trade is not graded yet — nothing to review.",
                "advisory_only": True}

    won = outcome == "win"
    creds = _credits(engine_rows, won)
    ranked = sorted(creds, key=lambda c: -c["credit"])
    best = ranked[0] if ranked else None
    weakest = ranked[-1] if len(ranked) > 1 else None

    base = {
        "available": True,
        "signal_id": t.get("signal_id") or r.get("signal_id"),
        "trading_day": t.get("trading_day"),
        "direction": t.get("direction"),
        "outcome": "Winner" if won else "Loser",
        "won": won,
        "pnl_points": _f(r.get("pnl_points")),
        "mfe": _f(r.get("mfe")), "mae": _f(r.get("mae")),
        "exit_reason": r.get("exit_reason"),
        "trade_quality": r.get("trade_quality"),
        "holding_min": (round(_f(r.get("holding_secs")) / 60.0, 1)
                        if _f(r.get("holding_secs")) is not None else None),
        "best_engine": _eng(best and best["engine"]),
        "best_credit": best and best["credit"],
        "weakest_engine": _eng(weakest and weakest["engine"]),
        "weakest_credit": weakest and weakest["credit"],
        "engine_credits": ranked[:8],
        "evolution": summarise_beats(beats),
        "advisory_only": True,
    }
    base.update(_win_review(t, r) if won
                else _loss_review(t, r, engine_rows, events))
    base["headline"] = _headline(base)
    return base


def _win_review(t: Dict[str, Any], r: Dict[str, Any]) -> Dict[str, Any]:
    why = [x for x in (
        t.get("acceptance"), t.get("absorption"), t.get("sr_state"),
        t.get("market_state"), t.get("dealer_state"), t.get("htf_alignment"),
    ) if x]
    if not why:
        why = ["No engine reads were recorded for this trade."]

    pnl, mfe = _f(r.get("pnl_points")) or 0.0, _f(r.get("mfe"))
    improvement = None
    if mfe is not None and mfe > 0:
        left = mfe - pnl
        eff = pnl / mfe if mfe else 0.0
        if left >= _GIVEBACK_PTS and eff < _GOOD_EFFICIENCY:
            improvement = (f"Ran +{mfe:.0f}, captured +{pnl:.0f} — the trail "
                           f"gave back {left:.0f} points "
                           f"({eff * 100:.0f}% of the move captured).")
        elif eff >= _GOOD_EFFICIENCY:
            improvement = (f"Captured {eff * 100:.0f}% of a +{mfe:.0f} run — "
                           f"well managed.")
    mae = _f(r.get("mae"))
    heat = (f" Took {abs(mae):.0f} pts of heat before working."
            if mae is not None and mae <= -_GIVEBACK_PTS else "")
    return {"why": why[:6],
            "improvement": (improvement or "No management issue identified.")
                           + heat,
            "primary_cause": None, "secondary_cause": None,
            "false_signal_type": None, "better_alternative": None,
            "lessons": []}


def _loss_review(t: Dict[str, Any], r: Dict[str, Any],
                 engine_rows, events) -> Dict[str, Any]:
    inv = investigate(t, engine_rows, r, events)
    factors = inv.get("contributing") or []
    secondary = factors[1] if len(factors) > 1 else None

    outvoted = inv.get("outvoted")
    better = (f"{outvoted} read the other side correctly and was outvoted — "
              f"its weight may be too low."
              if outvoted else "No engine called the other side.")

    lessons = _lessons(inv, r)
    why = [f"{e['engine']} — {e.get('output') or 'agreed with the trade'}"
           for e in (inv.get("engines_wrong") or [])[:4]]
    return {
        "why": why or ["No engine attribution recorded for this trade."],
        "primary_cause": inv.get("cause_label"),
        "primary_evidence": inv.get("cause_evidence"),
        "secondary_cause": (secondary or {}).get("label"),
        "secondary_evidence": (secondary or {}).get("evidence"),
        "false_signal_type": CAUSES.get(inv.get("cause"), inv.get("cause")),
        "false_signal_key": inv.get("cause"),
        "better_alternative": better,
        "outvoted": outvoted,
        "engines_wrong": inv.get("engines_wrong") or [],
        "engines_right": inv.get("engines_right") or [],
        "lessons": lessons,
        "improvement": lessons[0] if lessons else "—",
    }


def _lessons(inv: Dict[str, Any], r: Dict[str, Any]) -> List[str]:
    """Concrete, cause-specific. A generic 'be more selective' teaches
    nothing and would be produced for every loss ever recorded."""
    cause = inv.get("cause")
    mfe = _f(r.get("mfe"))
    out: List[str] = []
    if cause == "MANAGEMENT_FAILURE":
        out.append(f"The entry was fine — it ran +{mfe:.0f}. Fix the exit, "
                   f"not the filter.")
    elif cause == "FLOW_SHIFT":
        out.append("Stage 44 fired during the trade — treat a live flow shift "
                   "as an exit trigger, not a warning to ride out.")
    elif cause == "TRAP":
        out.append("The level's reaction reversed. Wait for Stage 42 to hold "
                   "its read for more than one cycle before entering.")
    elif cause == "IMMATURE_STATE":
        out.append("Entered on a state minutes old. Stage 54 maturity was the "
                   "missing filter.")
    elif cause == "AGAINST_HTF":
        out.append("Traded against Stage 45. Higher-timeframe disagreement "
                   "cost more than the local setup was worth.")
    elif cause == "WEAK_VALIDITY":
        out.append("Stage 51 was marginal at entry and was right to be.")
    elif cause == "LOW_EVIDENCE":
        out.append("Too few evidence families agreed — the setup was thinner "
                   "than it looked.")
    elif cause == "BAD_SIGNAL":
        out.append("Never went in favour. This is a read problem, not an "
                   "execution problem.")
    if inv.get("outvoted"):
        out.append(f"{inv['outvoted']} was right and lost the vote.")
    return out


def _headline(rev: Dict[str, Any]) -> str:
    pnl = _f(rev.get("pnl_points"))
    p = f"{pnl:+.0f} pts" if pnl is not None else "—"
    head = f"{rev.get('direction', '?')} {rev['outcome'].lower()} · {p}"
    if rev.get("won"):
        return f"{head}. Best: {rev.get('best_engine')}."
    return f"{head}. Cause: {rev.get('primary_cause') or 'unknown'}."


def review_many(trades: Optional[Sequence[Dict[str, Any]]],
                results: Optional[Sequence[Dict[str, Any]]] = None,
                engine_rows: Optional[Sequence[Dict[str, Any]]] = None,
                events: Optional[Sequence[Dict[str, Any]]] = None,
                limit: int = 20) -> List[Dict[str, Any]]:
    """Review a history — newest first, as the caller supplies it."""
    by_id = {str(t.get("signal_id")): t for t in (trades or [])}
    rows: Dict[str, List[Dict[str, Any]]] = {}
    for r in (engine_rows or []):
        rows.setdefault(str(r.get("signal_id")), []).append(r)
    evs: Dict[str, List[Dict[str, Any]]] = {}
    for e in (events or []):
        evs.setdefault(str(e.get("signal_id")), []).append(e)

    out = []
    for res in (results or [])[:limit]:
        sid = str(res.get("signal_id"))
        rv = review(by_id.get(sid) or {"signal_id": sid}, res,
                    rows.get(sid), evs.get(sid))
        if rv.get("available"):
            out.append(rv)
    return out
