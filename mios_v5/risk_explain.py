"""MIOS V6.5 — Stage 64 AI Risk Analysis.

Every number on a trade ticket, justified: why *this* entry, why *this* stop,
why *this* target, why *this* trail, why *this* reward:risk — and what would
invalidate the whole idea.

An entry price with no reason behind it is a guess with a decimal point. The
value of this stage is not the numbers, which already exist; it is that a
trader can check MIOS's arithmetic against its reasoning, and notice when the
two have come apart — a stop "below institutional support" that is in fact
above it is a bug you can only see once the justification is written down.

**Invalidation is the section that matters most.** An idea you cannot invalidate
is not an idea, it is a hope. So invalidation is never left empty: when no
engine-specific invalidator can be derived, the stop level itself is stated as
the invalidator rather than the section being silently dropped.

Where the reasoning is derived rather than proven, it says so — `"derived"`
versus `"proven"` — because a target inferred from the next level up is a
weaker claim than an entry the market actually refused, and presenting them in
the same voice would flatten the difference.

Pure module. Explains only; it does not size, place, or move anything.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .final_read import section

#: R:R below this is called out as thin regardless of how good the setup looks
_MIN_RR = 1.5


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "").upper()


def _fmt(v) -> str:
    x = _f(v)
    return "—" if x is None else f"₹{x:,.0f}"


def _levels(final_read: Dict[str, Any],
            levels: Optional[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    lv = dict(levels or {})
    sup = _f(lv.get("support"))
    res = _f(lv.get("resistance"))
    z = final_read.get("battle_zone") or {}
    if sup is None:
        sup = _f(z.get("support"))
    if res is None:
        res = _f(z.get("resistance"))
    return {"support": sup, "resistance": res}


def analyse(final_read: Optional[Dict[str, Any]],
            spot: Any = None,
            levels: Optional[Dict[str, Any]] = None,
            target: Any = None) -> Dict[str, Any]:
    """Risk analysis for whatever the Decision Engine is currently proposing.

    Returns `{"available": False}` — with the reason — when there is no trade
    to analyse, rather than inventing a hypothetical one.
    """
    fr = dict(final_read or {})
    dec = fr.get("decision_v2") or {}
    side = _s(dec.get("side"))
    entry = _f(dec.get("entry"))
    stop = _f(dec.get("stop"))

    if not side or entry is None:
        return {"available": False,
                "reason": "No trade proposed — nothing to analyse.",
                "advisory_only": True}

    lv = _levels(fr, levels)
    proof = dec.get("proof") or {}
    floor = side == "CALL"
    tgt = _f(target)
    if tgt is None:
        tgt = _f(dec.get("target"))
    tgt_derived = tgt is None
    if tgt_derived:
        tgt = lv["resistance"] if floor else lv["support"]

    risk_pts = abs(entry - stop) if stop is not None else None
    reward_pts = abs(tgt - entry) if tgt is not None else None
    rr = (round(reward_pts / risk_pts, 2)
          if (risk_pts and reward_pts and risk_pts > 0) else _f(dec.get("rr")))

    return {
        "available": True,
        "side": side, "spot": _f(spot),
        "entry": _entry_block(entry, proof, dec),
        "stop": _stop_block(stop, entry, risk_pts, floor, proof, fr),
        "target": _target_block(tgt, reward_pts, floor, lv, tgt_derived, fr),
        "trail": _trail_block(dec.get("trail"), fr),
        "rr": _rr_block(rr, risk_pts, reward_pts),
        "invalidation": invalidation(fr, dec, stop, floor),
        "advisory_only": True,
    }


def _entry_block(entry: float, proof: Dict[str, Any],
                 dec: Dict[str, Any]) -> Dict[str, Any]:
    ref = proof.get("refusal") or {}
    if proof.get("confirmed") and ref.get("proven"):
        why = (f"{proof.get('label')} — the market refused this price, it was "
               f"not chosen from the zone edge.")
        basis = "proven"
    elif proof.get("zone_price"):
        why = (f"Zone at {_fmt(proof['zone_price'])}; entry set where the "
               f"refusal was measured.")
        basis = "proven" if ref.get("proven") else "derived"
    else:
        why = "Entry taken from the Decision Engine's proposed level."
        basis = "derived"
    return {"price": entry, "display": _fmt(entry), "why": why,
            "basis": basis,
            "proof_state": dec.get("proof_state"),
            "checks_passed": proof.get("n_passed"),
            "checks_total": proof.get("n_checks")}


def _stop_block(stop: Optional[float], entry: float, risk_pts: Optional[float],
                floor: bool, proof: Dict[str, Any],
                fr: Dict[str, Any]) -> Dict[str, Any]:
    if stop is None:
        return {"price": None, "display": "—",
                "why": "No stop set — the trade is not tradable without one.",
                "basis": "missing"}
    zp = _f(proof.get("zone_price"))
    side_word = "below" if floor else "above"
    if zp is not None:
        beyond = abs(stop - zp)
        why = (f"{side_word.title()} the institutional level {_fmt(zp)} by "
               f"{beyond:.0f} pts — the level has to actually fail, not just "
               f"be touched.")
        basis = "proven"
    else:
        why = (f"{side_word.title()} the entry by {risk_pts:.0f} pts "
               f"(volatility-scaled).") if risk_pts else "Adaptive stop."
        basis = "derived"
    en = fr.get("energy_read") or {}
    if _s(en.get("state")) in ("EXPANSION", "RELEASED"):
        why += f" Widened for {str(en.get('state')).lower()} conditions."
    return {"price": stop, "display": _fmt(stop), "why": why, "basis": basis,
            "distance": round(risk_pts, 1) if risk_pts else None,
            "distance_pct": (round(100.0 * risk_pts / entry, 2)
                             if (risk_pts and entry) else None)}


def _target_block(tgt: Optional[float], reward: Optional[float], floor: bool,
                  lv: Dict[str, Optional[float]], derived: bool,
                  fr: Dict[str, Any]) -> Dict[str, Any]:
    if tgt is None:
        return {"price": None, "display": "—",
                "why": "No opposing level mapped yet — target undefined.",
                "basis": "missing"}
    opp = "resistance" if floor else "support"
    why = (f"Next {opp} at {_fmt(tgt)} — the first place the move is likely "
           f"to be met.") if derived else \
          f"Target supplied by the Decision Engine."
    htf = ((fr.get("htf") or {}).get("alignment")) or {}
    if htf.get("bias"):
        why += f" Higher timeframes read {htf.get('label', htf['bias'])}."
    return {"price": tgt, "display": _fmt(tgt), "why": why,
            "basis": "derived" if derived else "proven",
            "distance": round(reward, 1) if reward else None}


def _trail_block(trail: Optional[Dict[str, Any]],
                 fr: Dict[str, Any]) -> Dict[str, Any]:
    t = dict(trail or {})
    if not t:
        return {"spec": None, "why": "No trail active — the trade is not open "
                                     "yet.", "basis": "n/a"}
    ms = fr.get("market_state") or {}
    en = fr.get("energy_read") or {}
    why = t.get("reason") or (
        f"Distance scaled to {str(ms.get('label') or 'the current state')}"
        + (f" with energy {str(en.get('state')).lower()}"
           if en.get("state") else "") + ".")
    return {"spec": t, "mode": t.get("mode"), "stop": t.get("stop"),
            "why": why, "basis": "derived"}


def _rr_block(rr: Optional[float], risk: Optional[float],
              reward: Optional[float]) -> Dict[str, Any]:
    if rr is None:
        return {"value": None, "display": "—",
                "why": "Cannot compute — stop or target missing.",
                "acceptable": False}
    why = (f"{reward:.0f} pts of reward against {risk:.0f} pts of risk."
           if (risk and reward) else "Supplied by the Decision Engine.")
    if rr < _MIN_RR:
        why += (f" Below the {_MIN_RR:g} floor — the setup has to be "
                f"exceptional to justify it.")
    return {"value": rr, "display": f"{rr:.1f}", "why": why,
            "acceptable": rr >= _MIN_RR, "risk_pts": risk,
            "reward_pts": reward}


def invalidation(final_read: Optional[Dict[str, Any]],
                 decision: Optional[Dict[str, Any]] = None,
                 stop: Any = None, floor: bool = True) -> List[Dict[str, Any]]:
    """What would prove this trade wrong, each tied to the engine that would
    say so. Never returns empty while a stop exists."""
    fr = dict(final_read or {})
    dec = dict(decision or fr.get("decision_v2") or {})
    stop = _f(stop) if stop is not None else _f(dec.get("stop"))
    out: List[Dict[str, Any]] = []

    rc = fr.get("reaction") or {}
    if rc.get("state"):
        out.append({"what": "Acceptance fails",
                    "detail": f"currently {rc.get('label')}",
                    "engine": "Stage 42 Acceptance"})
    d = section(fr, "dealer")
    out.append({"what": "Dealer flips against the position",
                "detail": str(d.get("label") or "dealer read"),
                "engine": "Stage 11 Dealer"})
    if _s(fr.get("stability")) != "SHOCK":
        out.append({"what": "Flow shift appears",
                    "detail": f"currently {fr.get('stability') or 'unknown'}",
                    "engine": "Stage 44 Flow Shift"})
    proof = dec.get("proof") or {}
    zp = _f(proof.get("zone_price"))
    if zp is not None:
        out.append({"what": f"{'Support' if floor else 'Resistance'} "
                            f"{_fmt(zp)} breaks on volume",
                    "detail": "acceptance beyond the level, not a wick",
                    "engine": "Stage 35 Reaction Zone"})
    tr = fr.get("transition") or {}
    rev = _f(tr.get("reversal_probability")) or 0.0
    if rev >= 40:
        out.append({"what": "Bias reverses",
                    "detail": f"reversal probability {rev:.0f}%",
                    "engine": "Stage 47 Bias Transition"})
    if stop is not None:
        out.append({"what": f"Price accepts "
                            f"{'below' if floor else 'above'} {_fmt(stop)}",
                    "detail": "the stop — the arithmetic invalidator",
                    "engine": "Stage 52 Decision Engine"})
    return out[:6]
