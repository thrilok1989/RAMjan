"""MIOS V6.5 — Stage 63 AI Entry Checklist.

The live list of every condition an entry requires, each one either met, not
met, or not measurable — updated every market cycle.

This is the *data structure* behind Stage 62's "what is missing" answer, which
is why it is built first and consumed by the explainer rather than duplicated
inside it.

## Three states, not two

    ✅ met          the engine reported and the condition holds
    ❌ not met      the engine reported and the condition fails
    ⚪ unknown      the engine could not report at all

The third state is the one that makes the checklist honest. A tick-or-cross
display has to guess when an engine is silent, and every such guess is a lie in
one direction or the other: call it met and the trader sees a readiness score
built on nothing; call it failed and MIOS blocks trades for conditions it never
actually evaluated. Unknown conditions are shown, excluded from the readiness
denominator, and counted separately as `coverage`.

**Readiness is weighted, not a count.** Nine ticks where the two heaviest are
missing is not 78% ready. The weights mirror `validity.WEIGHTS` deliberately —
the checklist must not disagree with the gatekeeper about what matters, or a
trader reading both sees two different systems.

Every row carries `actual` — the engine output that produced the verdict.
A checklist that says "Acceptance ❌" without saying *what the acceptance
engine actually read* is a status light, not an explanation.

Pure module. Explains only: it produces no signal and gates nothing.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from .final_read import section

#: condition → (label, weight, owning engine). Weights sum to 100 and mirror
#: `validity.WEIGHTS` where the concepts overlap.
CONDITIONS: Dict[str, Tuple[str, int, str]] = {
    "zone":         ("Support / Resistance Holding", 12, "Stage 35 Reaction Zone"),
    "acceptance":   ("Acceptance", 15, "Stage 42 Acceptance/Rejection/Trap"),
    "dealer":       ("Dealer", 10, "Stage 11 Dealer"),
    "bias":         ("Bias", 10, "Stage 27 Conflict"),
    "absorption":   ("Absorption", 10, "Stage 43 Absorption"),
    "flow_shift":   ("Flow Shift", 10, "Stage 44 Flow Shift"),
    "market_state": ("Market State", 8, "Stage 48 Market State"),
    "htf":          ("HTF Alignment", 12, "Stage 45 Higher-Timeframe VPFR"),
    "validity":     ("Signal Validity", 13, "Stage 51 Validity Filter"),
}

ORDER = ("zone", "acceptance", "dealer", "bias", "absorption", "flow_shift",
         "market_state", "htf", "validity")

ICON = {True: "✅", False: "❌", None: "⚪"}

_BULLISH = ("BULL", "STRONG_BULL")
_BEARISH = ("BEAR", "STRONG_BEAR")

#: acceptance states that are hostile to an entry whichever way you are facing
_HOSTILE = ("BULL_TRAP", "BEAR_TRAP", "FAILED_BREAKOUT", "FAILED_BREAKDOWN",
            "SWEEP_BUY", "SWEEP_SELL")

#: market states that do not support a directional entry
_UNSUPPORTIVE = ("ROTATION", "COMPRESSION", "RANGE", "CHOP", "UNKNOWN")


def _s(v) -> str:
    return str(v or "").upper()


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _want(side: Optional[str]) -> Optional[str]:
    s = _s(side)
    if s in ("CALL", "BUY", "BULL", "LONG"):
        return "BULL"
    if s in ("PUT", "SELL", "BEAR", "SHORT"):
        return "BEAR"
    return None


def _agrees(bias: Any, want: Optional[str]) -> Optional[bool]:
    b = _s(bias)
    if not b or b in ("NONE", "UNKNOWN", "MISSING") or want is None:
        return None
    if b in ("NEUTRAL", "SIDEWAYS"):
        return False
    return (b in _BULLISH) if want == "BULL" else (b in _BEARISH)


# ── one reader per condition. Each returns (state, actual). ─────────────
def _c_zone(fr: Dict[str, Any], want) -> Tuple[Optional[bool], str]:
    z = fr.get("battle_zone") or fr.get("zone") or {}
    life = str(z.get("lifecycle") or "").lower()
    health = _f(z.get("health_pct") or z.get("strength"))
    if not life and health is None:
        return None, "no zone read"
    bad = life in ("broken", "fading", "under-attack")
    weak = health is not None and health < 45
    actual = (f"{life or 'unknown'}"
              + (f" · {health:.0f}% health" if health is not None else ""))
    return (not (bad or weak)), actual


def _c_acceptance(fr: Dict[str, Any], want) -> Tuple[Optional[bool], str]:
    rc = fr.get("reaction") or {}
    state = _s(rc.get("state"))
    if not state or state == "IDLE":
        return None, "no reaction at a level yet"
    actual = f"{rc.get('label', state)} ({rc.get('confidence', 0)}%)"
    if state in _HOSTILE:
        return False, actual
    winner = str(rc.get("winner") or "")
    if want and winner:
        ok = (winner == "Buyers") if want == "BULL" else (winner == "Sellers")
        return ok, actual
    return bool(rc.get("actionable")), actual


def _c_dealer(fr: Dict[str, Any], want) -> Tuple[Optional[bool], str]:
    d = section(fr, "dealer")
    bias = d.get("bias") or (fr.get("families") or {}).get("dealer", {}).get("direction")
    if not bias:
        return None, "no dealer read"
    st = _agrees(bias, want)
    # a NEUTRAL dealer does not oppose the trade — for the checklist that is
    # good enough, and calling it a failure would block most valid entries
    if st is False and _s(bias) in ("NEUTRAL", "SIDEWAYS"):
        return True, f"{bias} (not opposing)"
    return st, str(d.get("label") or bias)


def _c_bias(fr: Dict[str, Any], want) -> Tuple[Optional[bool], str]:
    b = fr.get("preferred_bias")
    if not b:
        return None, "no arbitrated bias"
    tr = fr.get("transition") or {}
    st = _agrees(b, want)
    actual = f"{b} {tr.get('label', '')}".strip()
    if st and _s(tr.get("state")) in ("WEAKENING", "REVERSING"):
        return False, f"{actual} — conviction decaying"
    return st, actual


def _c_absorption(fr: Dict[str, Any], want) -> Tuple[Optional[bool], str]:
    ab = fr.get("absorption") or {}
    b = ab.get("behaviour")
    if not b or b == "NONE":
        return None, "no clear institutional footprint"
    tone = str(ab.get("tone") or "")
    actual = f"{ab.get('label', b)} ({ab.get('confidence', 0)}%)"
    if want is None or tone not in ("bull", "bear"):
        return None, actual
    return ((tone == "bull") if want == "BULL" else (tone == "bear")), actual


def _c_flow_shift(fr: Dict[str, Any], want) -> Tuple[Optional[bool], str]:
    fs = fr.get("flow_shift") or {}
    stab = _s(fr.get("stability"))
    if not stab and not fs:
        return None, "no stability read"
    if fs.get("freeze_entries"):
        return False, f"SHIFT {fs.get('score', 0)}% — {fs.get('reason', '')}"
    return stab == "STABLE", stab or "unknown"


def _c_market_state(fr: Dict[str, Any], want) -> Tuple[Optional[bool], str]:
    ms = fr.get("market_state") or {}
    state = _s(ms.get("state"))
    if not state:
        return None, "no market state"
    mem = fr.get("memory_read") or {}
    dur = _f(mem.get("state_duration_min"))
    actual = (f"{ms.get('label', state)}"
              + (f" · {dur:.0f} min" if dur is not None else ""))
    if state in _UNSUPPORTIVE:
        return False, actual
    if mem.get("state_fresh"):
        return False, f"{actual} — too young to act on"
    return True, actual


def _c_htf(fr: Dict[str, Any], want) -> Tuple[Optional[bool], str]:
    al = ((fr.get("htf") or {}).get("alignment")) or fr.get("htf_alignment") or {}
    b = _s(al.get("bias"))
    if not b or b == "NEUTRAL":
        return None, str(al.get("label") or "no higher-timeframe consensus")
    actual = f"{al.get('label', b)} {al.get('stars', '')}".strip()
    return _agrees(b, want), actual


def _c_validity(fr: Dict[str, Any], want) -> Tuple[Optional[bool], str]:
    v = fr.get("validity") or {}
    if not v.get("verdict") or v.get("verdict") == "UNKNOWN":
        return None, "not enough coverage to validate"
    return bool(v.get("valid")), f"{v.get('verdict')} {v.get('pct', 0)}%"


_READERS: Dict[str, Callable[[Dict[str, Any], Optional[str]],
                             Tuple[Optional[bool], str]]] = {
    "zone": _c_zone, "acceptance": _c_acceptance, "dealer": _c_dealer,
    "bias": _c_bias, "absorption": _c_absorption, "flow_shift": _c_flow_shift,
    "market_state": _c_market_state, "htf": _c_htf, "validity": _c_validity,
}


def build(final_read: Optional[Dict[str, Any]],
          side: Optional[str] = None) -> Dict[str, Any]:
    """The live checklist. `side` defaults to whatever the Decision Engine is
    currently proposing; without one, direction-dependent rows read ⚪ rather
    than being scored against an assumed direction."""
    fr = dict(final_read or {})
    dec = fr.get("decision_v2") or {}
    side = side or dec.get("side")
    want = _want(side)

    rows: List[Dict[str, Any]] = []
    for key in ORDER:
        label, weight, engine = CONDITIONS[key]
        try:
            state, actual = _READERS[key](fr, want)
        except Exception:
            state, actual = None, "engine read failed"
        rows.append({"key": key, "label": label, "weight": weight,
                     "engine": engine, "state": state, "icon": ICON[state],
                     "actual": actual})

    got = sum(r["weight"] for r in rows if r["state"] is True)
    known = sum(r["weight"] for r in rows if r["state"] is not None)
    total = sum(w for _, w, _ in CONDITIONS.values())

    return {
        "side": side, "want": want, "rows": rows,
        "passed": [r for r in rows if r["state"] is True],
        "failed": [r for r in rows if r["state"] is False],
        "unknown": [r for r in rows if r["state"] is None],
        "readiness": round(100.0 * got / known) if known else 0,
        "coverage": round(100.0 * known / total),
        "decision": dec.get("state") or "WAIT",
        "decision_label": dec.get("label"),
        # the heaviest unmet condition — the one thing to watch for
        "blocking": max((r for r in rows if r["state"] is False),
                        key=lambda r: r["weight"], default=None),
        "advisory_only": True,
    }


def missing(cl: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What still has to happen, heaviest first — Stage 62's `Need` list."""
    return sorted((cl or {}).get("failed") or [],
                  key=lambda r: -r["weight"])


def summary_line(cl: Optional[Dict[str, Any]]) -> str:
    c = cl or {}
    rows = c.get("rows") or []
    if not rows:
        return "Checklist not available yet."
    p, f, u = len(c.get("passed") or []), len(c.get("failed") or []), \
        len(c.get("unknown") or [])
    tail = f" · {u} not measurable" if u else ""
    return (f"{p}/{len(rows)} conditions met · readiness "
            f"{c.get('readiness', 0)}%{tail}")
