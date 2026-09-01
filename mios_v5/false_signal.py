"""MIOS V6 — Stage 60 False Signal Analysis.

Every loss gets investigated. Not summarised — investigated: which engine was
wrong, which engine was right and got outvoted, and what the single most likely
cause was.

**The distinction this stage exists to make** is between a bad signal and a bad
exit, because they have opposite fixes and a win/loss column cannot tell them
apart:

    lost, and never went your way (MFE < 5)      →  the SIGNAL was wrong
    lost after running +25 in your favour        →  the signal was FINE
                                                    the management failed

Tightening entry filters in response to the second kind makes the system worse
while looking like diligence. So `MANAGEMENT_FAILURE` is ranked *above* most
signal causes: a trade that was winning and gave it all back is not evidence
against the engines that called it.

Causes are ranked, not scored, and exactly one is assigned per loss. A loss with
four contributing factors listed is a loss nobody will act on; a loss with one
named primary cause is a bug report.

**The engine that was right and lost the vote is recorded by name.** That is the
most actionable output in Phase 6 — it is a direct pointer at a weight that is
too low, and it is invisible to every other stage.

Pure module. Explains and recommends; changes nothing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: MFE below this and the trade never worked — a signal problem
_NEVER_WORKED = 5.0

#: MFE above this before losing — the signal worked and the exit did not
_MANAGEMENT_MFE = 15.0

CAUSES = {
    "FLOW_SHIFT": "Institutional flow shifted after entry",
    "MANAGEMENT_FAILURE": "Trade ran in profit then gave it all back",
    "TRAP": "Trap at the level — the reaction reversed",
    "BIAS_FLIP": "Market bias flipped under the trade",
    "IMMATURE_STATE": "Entered on a state only minutes old",
    "AGAINST_HTF": "Traded against the higher-timeframe structure",
    "WEAK_VALIDITY": "Gatekeeper score was marginal at entry",
    "LOW_EVIDENCE": "Too few evidence families agreed",
    "BAD_SIGNAL": "Never went in favour — the read was simply wrong",
    "UNKNOWN": "No single cause identifiable",
}

#: evaluated in order; the FIRST match is the primary cause
_ORDER = ("FLOW_SHIFT", "MANAGEMENT_FAILURE", "TRAP", "BIAS_FLIP",
          "IMMATURE_STATE", "AGAINST_HTF", "WEAK_VALIDITY", "LOW_EVIDENCE",
          "BAD_SIGNAL")

_TRAP_STATES = ("BULL_TRAP", "BEAR_TRAP", "FAILED_BREAKOUT",
                "FAILED_BREAKDOWN", "SWEEP_BUY", "SWEEP_SELL")

_EXIT_CAUSE = {"FLOW_SHIFT": "FLOW_SHIFT", "BIAS_CHANGE": "BIAS_FLIP",
               "ACCEPTANCE_FAILED": "TRAP", "DEALER_FLIP": "FLOW_SHIFT"}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "").upper()


def primary_cause(trade: Optional[Dict[str, Any]],
                  result: Optional[Dict[str, Any]] = None,
                  events: Optional[Sequence[Dict[str, Any]]] = None,
                  ) -> Dict[str, Any]:
    """One named cause per loss, with the evidence that selected it."""
    t, r = trade or {}, result or {}
    evs = list(events or [])
    mfe = _f(r.get("mfe"))
    hit: Dict[str, str] = {}

    # the exit reason is the strongest single piece of evidence when it names
    # a mechanism rather than just "stop loss"
    mapped = _EXIT_CAUSE.get(_s(r.get("exit_reason")))
    if mapped:
        hit[mapped] = f"exit reason was {r.get('exit_reason')}"

    for e in evs:
        if _s(e.get("kind")) == "FLOW_SHIFT":
            hit["FLOW_SHIFT"] = "flow-shift event fired during the trade"
        elif _s(e.get("kind")) == "BIAS_CHANGE":
            hit.setdefault("BIAS_FLIP", "bias changed during the trade")

    if mfe is not None and mfe >= _MANAGEMENT_MFE and "FLOW_SHIFT" not in hit:
        hit["MANAGEMENT_FAILURE"] = f"ran +{mfe:.0f} pts before losing"

    if _s(t.get("acceptance")).replace(" ", "_") in _TRAP_STATES or \
            "TRAP" in _s(t.get("acceptance")):
        hit.setdefault("TRAP", f"reaction was {t.get('acceptance')}")

    snap = t.get("snapshot") or {}
    dur = _f(snap.get("state_duration_min"))
    if dur is not None and dur < 5:
        hit["IMMATURE_STATE"] = f"state was {dur:.0f} min old at entry"

    htf = _s(t.get("htf_alignment"))
    direction = _s(t.get("direction"))
    if htf and direction:
        want = "BULL" if direction == "CALL" else "BEAR"
        if ("BULL" in htf or "BEAR" in htf) and want not in htf:
            hit["AGAINST_HTF"] = f"higher timeframes read {t.get('htf_alignment')}"

    vscore = _f(snap.get("validity_score"))
    if vscore is not None and vscore < 70:
        hit["WEAK_VALIDITY"] = f"validity only {vscore:.0f}%"

    fams = _f(snap.get("evidence_families"))
    if fams is not None and fams < 6:
        hit["LOW_EVIDENCE"] = f"only {fams:.0f} evidence families agreed"

    if mfe is not None and mfe < _NEVER_WORKED:
        hit["BAD_SIGNAL"] = f"peak favourable move was only +{mfe:.0f} pts"

    for key in _ORDER:
        if key in hit:
            return {"cause": key, "label": CAUSES[key], "evidence": hit[key],
                    "all_factors": [{"cause": k, "label": CAUSES[k],
                                     "evidence": v}
                                    for k in _ORDER if (v := hit.get(k))]}
    return {"cause": "UNKNOWN", "label": CAUSES["UNKNOWN"], "evidence": "",
            "all_factors": []}


def investigate(trade: Optional[Dict[str, Any]],
                engine_rows: Optional[Sequence[Dict[str, Any]]] = None,
                result: Optional[Dict[str, Any]] = None,
                events: Optional[Sequence[Dict[str, Any]]] = None,
                ) -> Dict[str, Any]:
    """One loss, fully investigated."""
    t, r = trade or {}, result or {}
    rows = list(engine_rows or [])
    wrong = sorted((x for x in rows if x.get("agreement")),
                   key=lambda x: -(_f(x.get("confidence")) or 0))
    right = sorted((x for x in rows if x.get("conflict")),
                   key=lambda x: -(_f(x.get("confidence")) or 0))
    cause = primary_cause(t, r, events)

    return {
        "signal_id": t.get("signal_id") or r.get("signal_id"),
        "trading_day": t.get("trading_day"),
        "direction": t.get("direction"),
        "pnl_points": _f(r.get("pnl_points")),
        "mfe": _f(r.get("mfe")), "mae": _f(r.get("mae")),
        "exit_reason": r.get("exit_reason"),
        "trade_quality": r.get("trade_quality"),
        "cause": cause["cause"], "cause_label": cause["label"],
        "cause_evidence": cause["evidence"],
        "contributing": cause["all_factors"],
        "engines_wrong": [{"engine": x.get("engine"),
                           "confidence": _f(x.get("confidence")),
                           "output": x.get("output")} for x in wrong[:6]],
        "engines_right": [{"engine": x.get("engine"),
                           "confidence": _f(x.get("confidence")),
                           "output": x.get("output")} for x in right[:6]],
        # the single most actionable line in Phase 6: an engine that called it
        # correctly and lost the vote is a weight that is too low
        "outvoted": (right[0].get("engine") if right else None),
        "summary": _summary(t, r, cause, wrong, right),
    }


def _summary(t: Dict[str, Any], r: Dict[str, Any], cause: Dict[str, Any],
             wrong: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> str:
    pnl = _f(r.get("pnl_points"))
    head = (f"{t.get('direction', '?')} lost "
            f"{abs(pnl):.0f} pts" if pnl is not None else
            f"{t.get('direction', '?')} lost")
    out = f"{head} — {cause['label'].lower()}"
    if cause.get("evidence"):
        out += f" ({cause['evidence']})"
    out += "."
    if wrong:
        out += (f" Loudest wrong voice: {wrong[0].get('engine')} at "
                f"{_f(wrong[0].get('confidence')) or 0:.0f}%.")
    if right:
        out += (f" {right[0].get('engine')} called it correctly and was "
                f"outvoted.")
    return out


def analyse(losses: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    """Aggregate the investigations. `losses` is a list of `investigate()`
    outputs."""
    ls = list(losses or [])
    n = len(ls)
    if not n:
        return {"losses": 0, "top_causes": [], "recurring": [],
                "most_common_trap": None, "worst_engines": [],
                "outvoted_leaders": [],
                "summary": "No losses recorded yet."}

    def _tally(key):
        c: Dict[str, int] = {}
        for l in ls:
            v = l.get(key)
            if v:
                c[str(v)] = c.get(str(v), 0) + 1
        return sorted(({"name": k, "count": v,
                        "pct": round(100.0 * v / n, 1)}
                       for k, v in c.items()), key=lambda r: -r["count"])

    causes = _tally("cause")
    for c in causes:
        c["label"] = CAUSES.get(c["name"], c["name"])

    wrong: Dict[str, int] = {}
    for l in ls:
        for e in l.get("engines_wrong") or []:
            k = str(e.get("engine"))
            wrong[k] = wrong.get(k, 0) + 1
    worst = sorted(({"engine": k, "losses": v,
                     "pct": round(100.0 * v / n, 1)}
                    for k, v in wrong.items()), key=lambda r: -r["losses"])

    traps = [l for l in ls if l.get("cause") == "TRAP"]
    trap_kinds: Dict[str, int] = {}
    for l in traps:
        k = str(l.get("cause_evidence") or "")
        if k:
            trap_kinds[k] = trap_kinds.get(k, 0) + 1
    top_trap = (max(trap_kinds.items(), key=lambda kv: kv[1])[0]
                if trap_kinds else None)

    # a cause is a "recurring mistake" only once it has happened enough times
    # to be a pattern rather than three bad days
    recurring = [c for c in causes if c["count"] >= 3]

    mgmt = next((c for c in causes if c["name"] == "MANAGEMENT_FAILURE"), None)
    lead = causes[0] if causes else None
    summary = f"{n} losses investigated. "
    if lead:
        summary += f"Leading cause: {lead['label']} ({lead['count']}/{n}). "
    if mgmt and mgmt["pct"] >= 25:
        summary += (f"{mgmt['pct']:.0f}% were winners that were mismanaged — "
                    f"fix the exits before touching the entry filters. ")
    if worst:
        summary += (f"Most often on the wrong side: {worst[0]['engine']} "
                    f"({worst[0]['losses']}).")

    return {
        "losses": n, "top_causes": causes, "recurring": recurring,
        "most_common_trap": top_trap, "worst_engines": worst[:8],
        "outvoted_leaders": _tally("outvoted")[:5],
        "management_share": (mgmt or {}).get("pct", 0.0),
        "summary": summary.strip(),
    }
