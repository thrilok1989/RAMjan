"""MIOS V6.5 — Stage 61 Decision Explainability + Stage 62 WAIT Analysis.

Why BUY · why SELL · why WAIT · why EXIT · why TRAIL · why ABORT — and when the
answer is WAIT, exactly what is missing and how close it is.

The two stages are one module because they are one question asked twice. "Why
did you act?" and "why didn't you?" have the same answer shape — the conditions
that hold, the conditions that don't — and splitting them would let the two
drift until MIOS could justify an entry with evidence it had just called
insufficient.

## The rule that shapes the code: no generic explanations

Every line MIOS emits is constructed *from* an engine read and carries that
engine's name and its actual output:

    ✓ Acceptance — 🟢 Rejection at support (78%)        Stage 42
    ✗ Dealer — 🏦 Dealers bearish                       Stage 11

If the engine did not report, no line is produced. There is deliberately no
fallback prose, no "market conditions look favourable", no template that fills
in when evidence is thin — because a confident-sounding sentence with nothing
behind it is worse than silence. Thin evidence renders as a short explanation,
which is the correct signal.

The ✓/✗ lines come straight from Stage 63's checklist rather than being
re-derived here. That is not just deduplication: it guarantees the explanation
and the checklist can never disagree about what MIOS believes.

## Boundary

This layer explains. It does not decide. It never changes a confidence, a
threshold, an engine weight, or a decision — it reads what has already been
decided and puts it into words. Nothing in the live path imports this module.

Pure module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .checklist import build as build_checklist
from .checklist import missing
from .thesis import build_thesis

#: decision_v2 state → the plain-language action a trader recognises
ACTION = {
    "ENTER": "BUY", "WAIT": "WAIT", "ENTRY_READY": "GET READY",
    "FLOOR_CONFIRMED": "GET READY", "CEILING_CONFIRMED": "GET READY",
    "HOLD": "HOLD", "SCALE_IN": "SCALE IN", "SCALE_OUT": "SCALE OUT",
    "TRAIL": "TRAIL", "EXIT": "EXIT", "ABORT": "ABORT", "COMPLETE": "COMPLETE",
}

EMOJI = {"BUY": "🟢", "SELL": "🔴", "WAIT": "⏳", "GET READY": "🟡",
         "HOLD": "🤝", "SCALE IN": "➕", "SCALE OUT": "➖", "TRAIL": "📈",
         "EXIT": "🚪", "ABORT": "🛑", "COMPLETE": "🏁"}

COLOUR = {"BUY": "#00ff88", "SELL": "#ff4444", "WAIT": "#cfd9e6",
          "GET READY": "#ffcc33", "HOLD": "#4da6ff", "SCALE IN": "#00ff88",
          "SCALE OUT": "#ffcc33", "TRAIL": "#a78bfa", "EXIT": "#ff9500",
          "ABORT": "#ff2d55", "COMPLETE": "#b3c2d4"}

RISK_LEVELS = ("Low", "Moderate", "Elevated", "High")


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "").upper()


def _action(dec: Dict[str, Any]) -> str:
    state = _s(dec.get("state")) or "WAIT"
    act = ACTION.get(state, state.replace("_", " "))
    if act == "BUY" and _s(dec.get("side")) == "PUT":
        return "SELL"
    return act


def _line(row: Dict[str, Any], mark: str) -> Dict[str, Any]:
    """One ✓/✗ line, always carrying the engine and its actual output."""
    return {"mark": mark, "label": row.get("label"),
            "actual": row.get("actual"), "engine": row.get("engine"),
            "weight": row.get("weight"),
            "text": f"{mark} {row.get('label')} — {row.get('actual')}"}


def risk(final_read: Optional[Dict[str, Any]],
         checklist: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Current risk, with the specific reads that raised it.

    Escalation is driven by named engine conditions rather than by a confidence
    number, so "Elevated" always comes with something a trader can look at.
    """
    fr, cl = dict(final_read or {}), dict(checklist or {})
    score, why = 0, []

    fs = fr.get("flow_shift") or {}
    if fs.get("freeze_entries"):
        score += 3
        why.append(f"Flow shift active ({fs.get('score', 0)}%) — Stage 44")
    elif _s(fr.get("stability")) == "RECOVERY":
        score += 1
        why.append("Tape still settling after a shift — Stage 44")

    tr = fr.get("transition") or {}
    rev = _f(tr.get("reversal_probability")) or 0.0
    if rev >= 60:
        score += 2
        why.append(f"Bias reversal probability {rev:.0f}% — Stage 47")
    elif rev >= 40:
        score += 1
        why.append(f"Bias reversal probability {rev:.0f}% — Stage 47")

    mem = fr.get("memory_read") or {}
    trisk = _f(mem.get("state_transition_risk")) or 0.0
    if trisk >= 60:
        score += 1
        why.append(f"State transition risk {trisk:.0f}% — Stage 54")
    if mem.get("state_fresh"):
        score += 1
        why.append(f"State only {_f(mem.get('state_duration_min')) or 0:.0f} "
                   f"min old — Stage 54")

    rc = fr.get("reaction") or {}
    if "TRAP" in _s(rc.get("state")):
        score += 2
        why.append(f"{rc.get('label')} at the level — Stage 42")

    v = fr.get("validity") or {}
    if v.get("verdict") == "INVALID":
        score += 1
        why.append(f"Validity INVALID ({v.get('pct', 0)}%) — Stage 51")

    ev = fr.get("event") or {}
    if ev.get("event_detected"):
        score += 2
        why.append(f"Live event reaction ({ev.get('event_score', 0)}%) — Stage 28")

    if cl.get("failed"):
        heavy = [r for r in cl["failed"] if r.get("weight", 0) >= 12]
        if heavy:
            score += 1
            why.append("Heavyweight conditions unmet: "
                       + ", ".join(r["label"] for r in heavy))

    level = RISK_LEVELS[min(score, 3)] if score else RISK_LEVELS[0]
    return {"level": level, "score": score, "reasons": why,
            "elevated": score >= 2}


#: market-quality grade → colour. UNTRADEABLE is a real grade, not a floor on
#: POOR — some tapes should simply not be traded, and saying "poor" invites a
#: smaller position where the correct answer is no position.
QUALITY_COLOUR = {"EXCELLENT": "#00ff88", "GOOD": "#17c98b", "FAIR": "#ffd000",
                  "POOR": "#ff9500", "UNTRADEABLE": "#ff4444", "—": "#cfd9e6"}


def market_quality(final_read: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """How tradeable is the market *itself*, independent of any setup.

    Derived from engines that already exist rather than built as a 46th one —
    evidence agreement (53), tape stability (44), energy (37) and conflict
    severity (27). A high-quality setup on an untradeable tape is still not a
    trade, and this is the number that says so before the setup gets graded.
    """
    fr = dict(final_read or {})
    fam = fr.get("families_read") or {}
    agree = _f(fam.get("agreement_pct"))
    stab = _s(fr.get("stability"))
    energy = _s((fr.get("energy_read") or {}).get("state"))
    severity = _s(fr.get("conflict_severity"))

    if agree is None and not stab:
        return {"grade": "—", "score": None, "colour": QUALITY_COLOUR["—"],
                "reasons": ["No evidence or stability read yet"]}

    score, reasons = 50.0, []
    if agree is not None:
        score = agree
        reasons.append(f"{agree:.0f}% evidence agreement (Stage 53)")
    if stab == "SHOCK":
        score -= 45
        reasons.append("tape in SHOCK (Stage 44)")
    elif stab == "UNSTABLE":
        score -= 25
        reasons.append("tape UNSTABLE (Stage 44)")
    elif stab == "RECOVERY":
        score -= 12
        reasons.append("tape recovering (Stage 44)")
    if energy == "DEAD":
        score -= 20
        reasons.append("energy DEAD — no fuel (Stage 37)")
    elif energy in ("EXPANSION", "RELEASED"):
        score += 6
        reasons.append(f"energy {energy.title()} (Stage 37)")
    if severity == "HIGH":
        score -= 15
        reasons.append("HIGH conflict (Stage 27)")

    score = max(0.0, min(100.0, score))
    grade = ("EXCELLENT" if score >= 80 else "GOOD" if score >= 65 else
             "FAIR" if score >= 50 else "POOR" if score >= 35
             else "UNTRADEABLE")
    return {"grade": grade, "score": int(round(score)),
            "colour": QUALITY_COLOUR[grade], "reasons": reasons}


def explain(final_read: Optional[Dict[str, Any]],
            checklist: Optional[Dict[str, Any]] = None,
            side: Optional[str] = None) -> Dict[str, Any]:
    """The full explanation of whatever MIOS is currently recommending."""
    fr = dict(final_read or {})
    dec = fr.get("decision_v2") or {}
    cl = checklist or build_checklist(fr, side=side or dec.get("side"))
    act = _action(dec)
    thesis = build_thesis(fr)
    rk = risk(fr, cl)

    reasons = [_line(r, "✓") for r in (cl.get("passed") or [])]
    opposed = [_line(r, "✗") for r in (cl.get("failed") or [])]
    unmeasured = [r.get("label") for r in (cl.get("unknown") or [])]

    # the Decision Engine's own proof reasons come first — they are the thing
    # that actually authorised (or blocked) the trade
    proof = dec.get("proof") or {}
    for r in (proof.get("reasons") or [])[:4]:
        reasons.insert(0, {"mark": "✓", "label": "Proof", "actual": r,
                           "engine": "Stage 52 Decision Engine",
                           "weight": 0, "text": f"✓ {r}"})
    for w in (dec.get("warnings") or [])[:3]:
        opposed.append({"mark": "⚠️", "label": "Warning", "actual": w,
                        "engine": "Stage 52 Decision Engine", "weight": 0,
                        "text": f"⚠️ {w}"})

    out = {
        "action": act, "emoji": EMOJI.get(act, "•"),
        "colour": COLOUR.get(act, "#cfd9e6"),
        "label": dec.get("label") or act,
        "side": dec.get("side"),
        "confidence": int(_f(dec.get("confidence")) or 0),
        "quality": dec.get("quality"),
        "reasons": reasons[:9],
        "opposed": opposed[:6],
        "unmeasured": unmeasured,
        "risk": rk["level"], "risk_score": rk["score"],
        "risk_reasons": rk["reasons"],
        "readiness": cl.get("readiness", 0),
        "checklist": cl,
        # the four things the writing style demands, every time
        "what_happened": _what_happened(fr),
        "why": [r["text"] for r in reasons[:6]],
        "expect": thesis.get("expect") or [],
        "invalidates": thesis.get("invalidation") or [],
        "advisory_only": True,
    }
    out.update(wait_analysis(fr, cl) if act == "WAIT" else {"needs": [],
                                                           "blocked_by": None})
    out["sentence"] = _sentence(out)
    return out


def _what_happened(fr: Dict[str, Any]) -> Optional[str]:
    """The observable event, not the inference. Reaction first, because that is
    the only thing in the system that has *already occurred*."""
    rc = fr.get("reaction") or {}
    if rc.get("state") and _s(rc.get("state")) != "IDLE":
        w = rc.get("winner")
        return (f"{rc.get('label')} at "
                f"{str(rc.get('side', '')).lower() or 'the level'}"
                + (f" — {w} won" if w else ""))
    fs = fr.get("flow_shift") or {}
    if fs.get("detected"):
        return f"Institutional flow shifted — {fs.get('reason', '')}"
    ab = fr.get("absorption") or {}
    if ab.get("behaviour") and ab["behaviour"] != "NONE":
        return str(ab.get("label"))
    ms = fr.get("market_state") or {}
    return str(ms.get("label")) if ms.get("label") else None


# ── Stage 62 · WAIT analysis ────────────────────────────────────────────
def wait_analysis(final_read: Optional[Dict[str, Any]],
                  checklist: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Why MIOS refused, what has to change, and how close it is.

    Readiness is the checklist's weighted score, so it moves for the right
    reasons: clearing a 15-weight blocker moves it far more than clearing a
    5-weight one, which is exactly the priority a trader should have.
    """
    fr = dict(final_read or {})
    cl = checklist or build_checklist(fr)
    dec = fr.get("decision_v2") or {}
    need = missing(cl)

    blocked = None
    if dec.get("blocked_by"):
        blocked = str(dec["blocked_by"])
    elif cl.get("blocking"):
        b = cl["blocking"]
        blocked = f"{b['label']} — {b['actual']}"

    return {
        "needs": [{"label": r["label"], "have": r["actual"],
                   "engine": r["engine"], "weight": r["weight"],
                   "text": f"✓ {r['label']}"} for r in need],
        "blocked_by": blocked,
        "readiness": cl.get("readiness", 0),
        "readiness_label": _readiness_label(cl.get("readiness", 0), need),
    }


def _readiness_label(pct: int, need: List[Dict[str, Any]]) -> str:
    if not need:
        return "All measurable conditions met — waiting on the Decision Engine."
    heaviest = need[0]
    if pct >= 80:
        return f"Close — {heaviest['label']} is the last heavy blocker."
    if pct >= 60:
        return f"Building — {len(need)} conditions still missing."
    if pct >= 40:
        return f"Early — {len(need)} conditions missing, led by {heaviest['label']}."
    return "Not a setup — most conditions are unmet."


def _sentence(e: Dict[str, Any]) -> str:
    """One line a trader can read in a glance without losing the evidence."""
    act = e["action"]
    if act == "WAIT":
        b = e.get("blocked_by")
        return (f"WAIT — {b}. Readiness {e['readiness']}%."
                if b else f"WAIT — readiness {e['readiness']}%.")
    n = len(e.get("reasons") or [])
    tail = (f" Risk {e['risk'].lower()}." if e.get("risk") else "")
    if not n:
        return f"{act} — no engine evidence recorded for this decision.{tail}"
    return (f"{act}"
            + (f" {e['side']}" if e.get("side") else "")
            + f" at {e['confidence']}% — {n} supporting engine reads"
            + (f", {len(e['opposed'])} opposing" if e.get("opposed") else "")
            + f".{tail}")
