"""MIOS V6 — the AI thesis + market controller (Dashboard V6's brain).

Two reads the workstation needs and no engine owned:

  • **THESIS** — why / expect / invalidation. Not a summary of engine output; a
    trader's three questions. WHY did MIOS decide this, WHAT should follow, and
    WHAT would prove it wrong. Invalidation matters most: an idea you cannot
    invalidate is not an idea, it is a hope.

  • **MARKET CONTROLLER** — who is actually driving. Derived from the Stage-53
    evidence families rather than a 46th engine, because "who controls" is a
    reading of evidence we already have, not new evidence. (The admission rule:
    if a field will do, don't build an engine.)

Pure module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_CONTROLLER_LABEL = {
    "dealer": "🏦 Dealers", "institutions": "🏛 Institutions",
    "orderflow": "⚡ Order Flow", "liquidity": "💧 Liquidity",
    "structure": "🏗 Structure", "options": "📊 Options",
    "macro": "🌍 Macro", "retail": "🐟 Retail / nobody",
}

_AUTHORITY = {"dealer": 8.0, "institutions": 7.0, "orderflow": 6.0,
              "liquidity": 5.0, "structure": 4.0, "options": 3.0, "macro": 2.0}


def _s(v) -> str:
    return str(v or "").upper()


def market_controller(families: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """Who is driving this market right now?

    The controller is the highest-authority family that is BOTH directional and
    reliable. When nothing institutional is aligned and reliability is poor
    across the board, nobody is in control — that is a retail tape, and saying so
    is more useful than naming a winner that isn't leading.
    """
    fams = {k: v for k, v in (families or {}).items()
            if v and v.get("status") == "OK"}
    if not fams:
        return {"controller": None, "label": "—", "score": 0,
                "direction": None, "reason": "no family evidence yet"}

    best, best_score = None, 0.0
    for name, f in fams.items():
        if f.get("direction") in (None, "NEUTRAL"):
            continue
        rel = {"HIGH": 1.0, "MEDIUM": 0.7, "LOW": 0.35}.get(f.get("reliability"), 0.5)
        score = (_AUTHORITY.get(name, 1.0) * rel
                 * (float(f.get("strength") or 0) / 100.0))
        if score > best_score:
            best, best_score = name, score

    # nothing authoritative and aligned → nobody is driving
    if best is None or best_score < 1.5:
        return {"controller": "retail", "label": _CONTROLLER_LABEL["retail"],
                "score": round(best_score, 2), "direction": None,
                "reason": "no institutional group is both aligned and reliable"}

    f = fams[best]
    return {"controller": best, "label": _CONTROLLER_LABEL.get(best, best),
            "score": round(best_score, 2), "direction": f.get("direction"),
            "strength": f.get("strength"), "reliability": f.get("reliability"),
            "reason": f"{_CONTROLLER_LABEL.get(best, best)} leading "
                      f"{f.get('direction')} at {f.get('strength')}% "
                      f"({str(f.get('reliability', '')).lower()} reliability)"}


def build_thesis(fr: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The three questions: why · expect · what invalidates it."""
    f = fr or {}
    dec = f.get("decision_v2") or {}
    proof = dec.get("proof") or {}
    react = f.get("reaction") or {}
    ab = f.get("absorption") or {}
    ms = f.get("market_state") or {}
    tr = f.get("transition") or {}
    en = f.get("energy_read") or {}
    mem = f.get("memory_read") or {}
    htf = f.get("htf_alignment") or {}
    val = f.get("validity") or {}

    # ── WHY ──
    why: List[str] = []
    if proof.get("confirmed"):
        why.append(proof.get("label") or "Level proven")
    why.extend((dec.get("reasons") or [])[:4])
    if ab.get("behaviour") and ab["behaviour"] != "NONE":
        why.append(ab.get("label", ab["behaviour"]))
    if ms.get("label"):
        why.append(f"Market state {ms['label']}")
    if mem.get("state_duration_min"):
        why.append(f"Held {float(mem['state_duration_min']):.0f} min")
    if val.get("verdict") == "VALID":
        why.append(f"Signal valid {val.get('pct', 0)}%")
    if not why:
        why.append("No confirmed edge — MIOS is standing aside")

    # ── EXPECT ──
    expect: List[str] = []
    if ms.get("next_state") and int(ms.get("next_probability") or 0) >= 50:
        expect.append(f"{ms['next_label']} next ({ms['next_probability']}%)")
    if en.get("state") == "COMPRESSION":
        expect.append(f"Directional expansion — release probability "
                      f"{en.get('release_probability', 0)}%")
    if ab.get("expectation"):
        expect.append(ab["expectation"])
    if dec.get("entry") and dec.get("state") == "ENTER":
        expect.append("Move away from the proven level in the traded direction")
    if not expect:
        expect.append("No directional expectation with the current evidence")

    # ── INVALIDATION — the most important section ──
    inval: List[str] = []
    if dec.get("stop"):
        side = _s(dec.get("side"))
        inval.append(f"Acceptance {'below' if side == 'CALL' else 'above'} "
                     f"{float(dec['stop']):,.0f} (the stop)")
    if proof.get("zone_price"):
        inval.append(f"Level {float(proof['zone_price']):,.0f} giving way on "
                     f"volume")
    inval.append("Dealer flip against the position")
    if f.get("stability") and _s(f.get("stability")) != "SHOCK":
        inval.append("Flow shift — tape starts repricing")
    if tr.get("reversal_probability", 0) >= 40:
        inval.append(f"Bias reversal (currently {tr['reversal_probability']}%)")
    if htf.get("bias"):
        inval.append(f"HTF breakdown — {htf.get('label', '')} failing")

    return {"why": why[:6], "expect": expect[:4], "invalidation": inval[:5],
            "has_edge": bool(proof.get("confirmed"))}


def recent_changes(fr: Optional[Dict[str, Any]],
                   evolution_changes: Optional[List[str]] = None) -> List[str]:
    """Only what CHANGED. A dashboard that repeats unchanged values every cycle
    trains the eye to ignore it, which is the opposite of the goal."""
    out = list(evolution_changes or [])
    f = fr or {}
    tr = f.get("transition") or {}
    if _s(tr.get("state")) in ("WEAKENING", "REVERSING", "TRANSITION"):
        out.append(f"Bias {str(tr['state']).lower()}"
                   + (f" — led by {tr['leader']}" if tr.get("leader") else ""))
    fs = f.get("flow_shift") or {}
    if fs.get("detected"):
        out.append(f"Flow shift — {fs.get('reason', '')}")
    ms = f.get("market_state") or {}
    mem = f.get("memory_read") or {}
    if ms.get("state") and mem.get("state_fresh"):
        out.append(f"Market state → {ms.get('label')} (new)")
    ab = f.get("absorption") or {}
    if ab.get("behaviour") and ab["behaviour"] != "NONE":
        out.append(f"Institutional footprint: {ab.get('label')}")
    return out[:8]
