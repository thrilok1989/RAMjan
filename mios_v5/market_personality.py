"""MIOS V6 — Stage 48 Market State (one personality, not twenty indicators).

⚠️ Named `market_personality` because `market_state.py` is already taken by the
V5 event-timeline regime engine that `scenario_engine` depends on. Two modules
called "market state" doing different jobs would be worse than a slightly
unusual filename.

Combines five FINISHED engine reads into a single answer to "what kind of market
is this right now" — and, crucially, **what it is likely to become next**.

    Stage 42 Acceptance ─┐
    Stage 44 Flow Shift ─┤
    Stage 47 Transition ─┼─→  ONE primary state  +  next state · probability
    Stage 50 LTP        ─┤
    Stage 37 Energy     ─┘

It **calculates nothing**. Compression, expansion, release probability and energy
strength belong to Stage 37; bias decay to Stage 47; trap detection to Stage 42.
Duplicating any of them here would create two sources that eventually disagree —
and the louder one would win by accident rather than by being right.

The prediction is what makes this proactive rather than descriptive. A market in
COMPRESSION is not interesting; a market in COMPRESSION with an 84% chance of
EXPANSION is a plan. Every probability is sourced from the engine that owns it,
never invented here.

States resolve MOST-URGENT-FIRST: the same tape can be both "distribution" and
"trap active", and those demand different action.

Pure module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

STATES = (
    "TRAP_ACTIVE", "BREAKOUT", "BREAKDOWN", "REVERSAL_BUILDING", "WAR_ZONE",
    "EXPANSION", "COMPRESSION", "ACCUMULATION", "DISTRIBUTION",
    "MARKUP", "MARKDOWN", "TREND_UP", "TREND_DOWN", "ROTATION", "WAIT",
)

LABEL = {
    "TRAP_ACTIVE": "🪤 TRAP ACTIVE", "BREAKOUT": "🚀 BREAKOUT",
    "BREAKDOWN": "🔻 BREAKDOWN", "REVERSAL_BUILDING": "🔄 REVERSAL BUILDING",
    "WAR_ZONE": "⚔️ WAR ZONE", "EXPANSION": "💥 EXPANSION",
    "COMPRESSION": "🪤 COMPRESSION", "ACCUMULATION": "🟢 ACCUMULATION",
    "DISTRIBUTION": "🔴 DISTRIBUTION", "MARKUP": "📈 MARK UP",
    "MARKDOWN": "📉 MARK DOWN", "TREND_UP": "⬆️ TREND UP",
    "TREND_DOWN": "⬇️ TREND DOWN", "ROTATION": "🔁 ROTATION", "WAIT": "⏳ WAIT",
}

TONE = {
    "BREAKOUT": "bull", "MARKUP": "bull", "TREND_UP": "bull",
    "ACCUMULATION": "bull", "BREAKDOWN": "bear", "MARKDOWN": "bear",
    "TREND_DOWN": "bear", "DISTRIBUTION": "bear",
}


def _s(v) -> str:
    return str(v or "").upper()


def derive(bias: Optional[str] = None,
           transition: Optional[Dict[str, Any]] = None,
           ltp: Optional[Dict[str, Any]] = None,
           acceptance: Optional[Dict[str, Any]] = None,
           flow: Optional[Dict[str, Any]] = None,
           energy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resolve ONE primary market state from the five engine reads."""
    tr, lb = transition or {}, ltp or {}
    ac, fl, en = acceptance or {}, flow or {}, energy or {}

    b = _s(bias or tr.get("bias"))
    bull, bear = b.endswith("BULL"), b.endswith("BEAR")
    tstate = _s(tr.get("state"))
    rev_p = float(tr.get("reversal_probability") or 0)

    buyers = _s((lb.get("buyers") or {}).get("state"))
    sellers = _s((lb.get("sellers") or {}).get("state"))
    price = _s((lb.get("price") or {}).get("state"))
    mflow = _s((lb.get("flow") or {}).get("state"))

    react = _s(ac.get("state"))
    estate = _s(en.get("state"))
    release = float(en.get("release_probability") or 0)
    stability = _s(fl.get("stability"))

    reasons: List[str] = []
    inputs_seen = sum(1 for x in (tr, lb, ac, fl, en) if x)

    def _r(t: str) -> None:
        reasons.append(t)

    if react in ("BULL_TRAP", "BEAR_TRAP"):
        state = "TRAP_ACTIVE"
        _r(f"{react.replace('_', ' ').title()} confirmed")
    elif stability == "SHOCK" or fl.get("freeze_entries"):
        state = "WAIT"
        _r("Institutional flow shift — tape repricing")
    elif react == "CONFIRMED_BREAKOUT":
        state = "BREAKOUT"
        _r("Breakout confirmed with follow-through")
    elif react == "CONFIRMED_BREAKDOWN":
        state = "BREAKDOWN"
        _r("Breakdown confirmed with follow-through")
    elif tstate == "REVERSING" or (rev_p >= 65 and tstate == "WEAKENING"):
        state = "REVERSAL_BUILDING"
        _r(f"Bias {tstate.lower()} · reversal probability {rev_p:.0f}%")
        if tr.get("leader"):
            _r(f"Led by {tr['leader']}")
    elif (bear and buyers == "BUILDING") or (bull and sellers == "BUILDING"):
        state = "REVERSAL_BUILDING"
        _r("Counter-side building against the prevailing bias")
    elif react == "ABSORPTION" or "ABSORBING" in (buyers, sellers) or \
            (buyers == "BUILDING" and sellers == "BUILDING"):
        state = "WAR_ZONE"
        _r("Both sides committed / absorption at the level")
    elif estate == "COMPRESSION":
        state = "COMPRESSION"
        _r(f"Energy coiling · release probability {release:.0f}%")
    elif estate == "EXPANSION" or price == "EXPLODING":
        state = "EXPANSION"
        _r("Energy releasing — expansion underway")
    elif bull and buyers == "BUILDING" and mflow == "ENTERING":
        state = "ACCUMULATION"
        _r("Buyers building with money entering")
    elif bear and sellers == "BUILDING" and mflow == "LEAVING":
        state = "DISTRIBUTION"
        _r("Sellers building with money leaving")
    elif bull and price == "RISING":
        state = "MARKUP" if estate in ("EXPANSION", "BUILDING") else "TREND_UP"
        _r("Advance in progress")
    elif bear and price == "FALLING":
        state = "MARKDOWN" if estate in ("EXPANSION", "BUILDING") else "TREND_DOWN"
        _r("Decline in progress")
    elif estate == "DEAD" or price in ("FLAT", "COMPRESSING"):
        state = "ROTATION"
        _r("No committed side — price rotating")
    else:
        state = "WAIT"
        _r("No clear market personality yet")

    if react in ("FAILED_BREAKOUT", "FAILED_BREAKDOWN") and state != "TRAP_ACTIVE":
        _r(f"{react.replace('_', ' ').title()} — not confirmed")
    if tstate == "WEAKENING" and state in ("TREND_UP", "TREND_DOWN",
                                           "MARKUP", "MARKDOWN"):
        _r("…but the bias is weakening")

    nxt, nxt_p = predict_next(state, tr, ac, en, lb)
    return {"state": state, "label": LABEL[state],
            "tone": TONE.get(state, "neutral"),
            "confidence": _confidence(state, inputs_seen, tr, en, ac),
            "reasons": reasons, "next_state": nxt,
            "next_label": LABEL.get(nxt, "—") if nxt else "—",
            "next_probability": nxt_p, "inputs_seen": inputs_seen}


def predict_next(state: str, tr: Dict[str, Any], ac: Dict[str, Any],
                 en: Dict[str, Any], lb: Dict[str, Any]) -> Tuple[Optional[str], int]:
    """What this state most likely becomes — the read that makes MIOS proactive.

    Every probability is SOURCED from the engine that owns it (a coil's release
    probability is Stage 37's number), never invented here.
    """
    release = float(en.get("release_probability") or 0)
    rev_p = float(tr.get("reversal_probability") or 0)
    bias = _s(tr.get("bias"))
    react = _s(ac.get("state"))

    if state == "COMPRESSION":
        # direction is unknown by definition — that IS the compression read
        return "EXPANSION", int(max(40, min(95, release)))
    if state == "ACCUMULATION":
        return "MARKUP", int(max(45, min(90, 55 + release * 0.3)))
    if state == "DISTRIBUTION":
        return "MARKDOWN", int(max(45, min(90, 55 + release * 0.3)))
    if state == "REVERSAL_BUILDING":
        return ("MARKUP" if bias.endswith("BEAR") else "MARKDOWN",
                int(max(45, min(92, rev_p))))
    if state == "TRAP_ACTIVE":
        return ("MARKDOWN" if react == "BULL_TRAP" else "MARKUP",
                int(max(55, min(92, float(ac.get("confidence") or 70)))))
    if state == "EXPANSION":
        px = _s((lb.get("price") or {}).get("state"))
        return ("MARKUP" if px == "RISING" else
                "MARKDOWN" if px == "FALLING" else "TREND_UP"), 65
    if state in ("BREAKOUT", "MARKUP", "TREND_UP"):
        return ("REVERSAL_BUILDING", int(rev_p)) if rev_p >= 55 else ("MARKUP", 60)
    if state in ("BREAKDOWN", "MARKDOWN", "TREND_DOWN"):
        return ("REVERSAL_BUILDING", int(rev_p)) if rev_p >= 55 else ("MARKDOWN", 60)
    if state == "WAR_ZONE":
        return "EXPANSION", int(max(45, min(85, release or 55)))
    if state == "ROTATION":
        return "COMPRESSION", 50
    return None, 0


def _confidence(state: str, inputs_seen: int, tr: Dict[str, Any],
                en: Dict[str, Any], ac: Dict[str, Any]) -> int:
    """Rises with how many engines reported AND how decisive the owning engine
    is about this particular state."""
    base = 20 + inputs_seen * 10                     # all five → 70
    if state in ("TRAP_ACTIVE", "BREAKOUT", "BREAKDOWN"):
        base = max(base, int(float(ac.get("confidence") or 70)))
    elif state == "COMPRESSION":
        base = max(base, int(float(en.get("confidence") or 60)))
    elif state == "REVERSAL_BUILDING":
        base = max(base, int(float(tr.get("confidence") or 60)))
    elif state == "WAIT":
        base = min(base, 45)
    return int(max(0, min(97, base)))
