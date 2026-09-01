"""MIOS V6.5 — Stage 67 AI Daily Market Summary.

The end-of-day report: what MIOS traded, what it refused and why, which engines
carried the day, what kind of market it actually was, and what to watch
tomorrow.

## What it refused is half the report

A daily summary listing only the trades taken describes a fraction of the day's
decisions — most cycles end in WAIT, and the reason MIOS waited is usually more
informative than the two trades it took. `most_common_wait_reason` is built
from a log of the blocking condition on every WAIT cycle, so a day spent
blocked on "Acceptance" reads differently from a day spent blocked on
"Flow Shift", and the trader can see which part of the market was actually
missing.

## Tomorrow is a watch-list, not a forecast

`tomorrow_watch` carries levels — the places where today's evidence would be
confirmed or broken — and `tomorrow_risks` carries the conditions that would
invalidate today's read. Neither predicts a direction. A daily summary that
ends with a directional call trains the trader to arrive tomorrow already
positioned, which is precisely the habit the whole Decision Engine was built to
prevent ("never enter on prediction").

Everything here reuses Stages 56-60 rather than recomputing: the same numbers
that appear on the Learning Dashboard appear here, or the two would eventually
disagree and both would be doubted.

Pure module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .attribution import join_outcomes
from .engine_accuracy import by_engine as accuracy_by_engine
from .engine_accuracy import rank as rank_engines
from .false_signal import analyse as analyse_losses
from .false_signal import investigate
from .final_read import section
from .learning_report import overall

PERSONALITIES = ("Trending", "Range", "Volatile", "Shock", "Quiet", "Unknown")

_TREND_STATES = ("TREND", "MARK_UP", "MARK_DOWN", "EXPANSION", "PULLBACK")
_RANGE_STATES = ("RANGE", "ROTATION", "COMPRESSION", "ACCUMULATION",
                 "DISTRIBUTION")


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "").upper()


def _mean(vals) -> Optional[float]:
    xs = [x for x in (_f(v) for v in vals) if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _tally(items: Sequence[Any]) -> List[Dict[str, Any]]:
    c: Dict[str, int] = {}
    for i in items:
        if i:
            c[str(i)] = c.get(str(i), 0) + 1
    n = sum(c.values())
    return sorted(({"name": k, "count": v,
                    "pct": round(100.0 * v / n, 1) if n else 0.0}
                   for k, v in c.items()), key=lambda r: -r["count"])


def market_personality(final_read: Optional[Dict[str, Any]],
                       state_log: Optional[Sequence[str]] = None
                       ) -> Dict[str, Any]:
    """What kind of market it was — from how the day was *spent*, not from the
    state it happened to end in.

    A day that trended for five hours and closed in a 20-minute rotation was a
    trending day; reading only the closing state would file it as a range and
    teach exactly the wrong lesson.
    """
    fr = dict(final_read or {})

    # Stage 68 owns this question. When it has classified the session, quote
    # it — two modules deciding "what kind of day was this" would eventually
    # disagree, and the louder one would win by accident.
    dc = fr.get("day_classification") or {}
    if dc.get("type"):
        mem = dc.get("memory") or {}
        return {"personality": str(dc["label"]).split(" ", 1)[-1].replace(
                    " Day", ""),
                "label": dc["label"], "type": dc["type"],
                "why": dc.get("confidence_note") or "",
                "confidence": dc.get("confidence"),
                "duration_min": mem.get("duration_min"),
                "changes": mem.get("changes_today", 0),
                "distribution": [], "source": "stage68"}

    log = [s for s in (state_log or []) if s]
    if not log:
        ms = fr.get("market_state") or {}
        log = [ms.get("state")] if ms.get("state") else []

    if not log:
        return {"personality": "Unknown", "why": "no market-state history",
                "distribution": []}

    dist = _tally(log)
    trend = sum(r["count"] for r in dist if _s(r["name"]) in _TREND_STATES)
    rng = sum(r["count"] for r in dist if _s(r["name"]) in _RANGE_STATES)
    total = sum(r["count"] for r in dist)

    shocks = _s(fr.get("stability")) == "SHOCK"
    unstable = _s(fr.get("stability")) in ("UNSTABLE", "SHOCK", "RECOVERY")

    if shocks:
        p, why = "Shock", "flow stability ended the day in SHOCK"
    elif unstable and trend < total * 0.4:
        p, why = "Volatile", "unstable tape without a sustained direction"
    elif trend >= total * 0.5:
        p, why = "Trending", f"{round(100.0 * trend / total)}% of the session in trend states"
    elif rng >= total * 0.5:
        p, why = "Range", f"{round(100.0 * rng / total)}% of the session in rotation or compression"
    else:
        p, why = "Quiet", "no state held the session"
    return {"personality": p, "why": why, "distribution": dist[:5],
            "dominant_state": dist[0]["name"] if dist else None,
            "source": "fallback"}


def summarise(results: Optional[Sequence[Dict[str, Any]]] = None,
              trades: Optional[Sequence[Dict[str, Any]]] = None,
              engine_rows: Optional[Sequence[Dict[str, Any]]] = None,
              events: Optional[Sequence[Dict[str, Any]]] = None,
              wait_log: Optional[Sequence[str]] = None,
              state_log: Optional[Sequence[str]] = None,
              final_read: Optional[Dict[str, Any]] = None,
              levels: Optional[Dict[str, Any]] = None,
              trading_day: Optional[str] = None) -> Dict[str, Any]:
    """The whole end-of-day report."""
    fr = dict(final_read or {})
    res = list(results or [])
    ov = overall(res)
    rr = _mean(t.get("rr") for t in (trades or []))

    joined = join_outcomes(engine_rows, res)
    ranked = rank_engines(accuracy_by_engine(joined), window="lifetime")
    scored = [r for r in ranked if r.get("value") is not None]

    by_id = {str(t.get("signal_id")): t for t in (trades or [])}
    rows: Dict[str, List[Dict[str, Any]]] = {}
    for r in (engine_rows or []):
        rows.setdefault(str(r.get("signal_id")), []).append(r)
    evs: Dict[str, List[Dict[str, Any]]] = {}
    for e in (events or []):
        evs.setdefault(str(e.get("signal_id")), []).append(e)
    losses = [investigate(by_id.get(str(r.get("signal_id"))) or {},
                          rows.get(str(r.get("signal_id"))), r,
                          evs.get(str(r.get("signal_id"))))
              for r in res if r.get("outcome") == "loss"]
    fs = analyse_losses(losses)

    waits = _tally(wait_log or [])
    personality = market_personality(fr, state_log)

    return {
        "trading_day": trading_day,
        # ── performance ──
        "trades": ov["graded"], "wins": ov["wins"], "losses": ov["losses"],
        "win_rate": ov["win_rate"], "avg_rr": rr,
        "avg_holding_min": ov["avg_hold_min"],
        "profit_factor": ov["profit_factor"],
        "expectancy": ov["expectancy"],
        "avg_mfe": ov["avg_mfe"], "avg_mae": ov["avg_mae"],
        # ── engines ──
        "best_engine": scored[0]["engine"] if scored else None,
        "best_engine_precision": scored[0]["value"] if scored else None,
        "weakest_engine": scored[-1]["engine"] if len(scored) > 1 else None,
        "weakest_engine_precision": scored[-1]["value"] if len(scored) > 1 else None,
        "engine_table": scored[:8],
        # ── what MIOS refused ──
        "wait_reasons": waits[:5],
        "most_common_wait_reason": waits[0]["name"] if waits else None,
        "wait_cycles": sum(w["count"] for w in waits),
        # ── what went wrong ──
        "most_common_false_signal": (fs["top_causes"][0]["label"]
                                     if fs.get("top_causes") else None),
        "false_signal_detail": fs,
        # ── the market itself ──
        "market_personality": personality["personality"],
        "market_type_label": personality.get("label"),
        "market_type": personality.get("type"),
        "personality_why": personality["why"],
        "personality_source": personality.get("source"),
        "state_distribution": personality["distribution"],
        "institution_activity": _institutions(fr),
        "dealer_behaviour": _dealers(fr),
        "major_support": _f((levels or {}).get("support")),
        "major_resistance": _f((levels or {}).get("resistance")),
        # ── tomorrow ──
        "tomorrow_watch": _watch(fr, levels),
        "tomorrow_risks": _risks(fr, fs),
        "outlook": _outlook(ov, personality, fr, fs),
        "advisory_only": True,
    }


def _institutions(fr: Dict[str, Any]) -> str:
    ab = fr.get("absorption") or {}
    if ab.get("behaviour") and ab["behaviour"] != "NONE":
        return f"{ab.get('label')} — {ab.get('expectation', '')}".strip(" —")
    fams = fr.get("families") or {}
    inst = fams.get("institutions") or {}
    if inst.get("direction") and inst["direction"] != "NEUTRAL":
        return (f"Institutions {inst['direction']} at "
                f"{inst.get('strength', 0)}% ({inst.get('reliability', '')})")
    return "No clear institutional footprint today."


def _dealers(fr: Dict[str, Any]) -> str:
    d = section(fr, "dealer")
    if d.get("label"):
        return str(d["label"])
    fam = (fr.get("families") or {}).get("dealer") or {}
    if fam.get("direction"):
        return f"Dealers {fam['direction']} at {fam.get('strength', 0)}%"
    return "No dealer read recorded."


def _watch(fr: Dict[str, Any], levels: Optional[Dict[str, Any]]
           ) -> List[Dict[str, Any]]:
    """Levels, each with what a reaction there would mean — not a direction."""
    out: List[Dict[str, Any]] = []
    lv = dict(levels or {})
    z = fr.get("battle_zone") or {}
    sup = _f(lv.get("support")) or _f(z.get("support"))
    res = _f(lv.get("resistance")) or _f(z.get("resistance"))
    if sup is not None:
        out.append({"level": sup, "label": f"Support ₹{sup:,.0f}",
                    "means": "holds → the floor is still being defended; "
                             "accepts below → the floor is gone"})
    if res is not None:
        out.append({"level": res, "label": f"Resistance ₹{res:,.0f}",
                    "means": "rejects → the ceiling holds; accepts above → "
                             "the ceiling is gone"})
    htf = ((fr.get("htf") or {}).get("levels")) or {}
    for name, price in list(htf.items())[:3]:
        p = _f(price)
        if p is not None:
            out.append({"level": p, "label": f"HTF {name} ₹{p:,.0f}",
                        "means": "higher-timeframe reference — reactions here "
                                 "carry more weight"})
    return out[:6]


def _risks(fr: Dict[str, Any], fs: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    tr = fr.get("transition") or {}
    rev = _f(tr.get("reversal_probability")) or 0.0
    if rev >= 40:
        out.append(f"Bias reversal probability closed at {rev:.0f}% "
                   f"(Stage 47) — today's read may not survive the open.")
    mem = fr.get("memory_read") or {}
    risk = _f(mem.get("state_transition_risk")) or 0.0
    if risk >= 50:
        out.append(f"State transition risk {risk:.0f}% (Stage 54).")
    if _s(fr.get("stability")) in ("UNSTABLE", "SHOCK", "RECOVERY"):
        out.append(f"Tape closed {fr.get('stability')} (Stage 44) — "
                   f"expect wider stops until it settles.")
    cal = (fr.get("calendar") or {}).get("next_event") or {}
    if cal.get("name") and int(cal.get("days_away") or 9) <= 1:
        out.append(f"{cal['name']} tomorrow (Stage 30) — position sizing, "
                   f"not conviction.")
    if fs.get("management_share", 0) >= 25:
        out.append(f"{fs['management_share']:.0f}% of today's losses were "
                   f"mismanaged winners — the exits are the weak point, not "
                   f"the entries.")
    if not out:
        out.append("No elevated structural risk recorded at the close.")
    return out[:5]


def _outlook(ov: Dict[str, Any], personality: Dict[str, Any],
             fr: Dict[str, Any], fs: Dict[str, Any]) -> str:
    """Descriptive, never directional."""
    n = ov.get("graded") or 0
    parts = []
    if not n:
        parts.append("No graded trades today.")
    else:
        parts.append(f"{n} graded trade{'s' if n != 1 else ''}, "
                     f"{ov.get('wins', 0)}W/{ov.get('losses', 0)}L "
                     f"({ov.get('win_rate')}%).")
    parts.append(f"The session behaved as a {personality['personality']} "
                 f"market — {personality['why']}.")
    ctl = fr.get("preferred_bias")
    if ctl:
        parts.append(f"MIOS closed reading {ctl}.")
    if fs.get("losses"):
        top = (fs.get("top_causes") or [{}])[0]
        if top.get("label"):
            parts.append(f"Losses were led by: {top['label']}.")
    parts.append("Tomorrow is a watch-list, not a position — wait for the "
                 "level to be tested before acting on any of it.")
    return " ".join(parts)
