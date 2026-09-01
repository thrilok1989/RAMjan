"""MIOS V5 — Decision Engine v0 (the gate stack).

Every other engine answers *what / why / who / where*. This one answers the only
question that matters at the moment of action: **do I act now, or wait?** — and
WAIT / STAND ASIDE are first-class decisions, not failed signals. That's why it's
a Decision Engine, not a "signal generator".

It never recalculates anything. It only asks: *are all required conditions
satisfied?* — a GATE STACK (confluence), not a weighted vote:

    LOCATION → DIRECTION → ZONE HEALTH → CONFIRMATION → RISK → EVENT/VETO → QUALITY

The first six gates decide CALL / PUT / WAIT / STAND ASIDE. The QUALITY gate then
grades HOW GOOD the setup is (A+ / A / B / C) from each gate's ★ score — same
direction can be an A+ or a C.

v0 is OBSERVATIONAL: it mirrors the live Entry Gate's state and overlays the MIOS
gates as pass/warn — it does NOT drive alerts. Produce the decision, log it
(including every REJECTION and why), compare to the Entry Gate over weeks, and
only promote it to the live path if the evidence says so. Design → observe →
measure → promote.

`build_decision(final_read, reaction_sr, gate)` is pure/testable. `gate` is
normalized by the app from the Entry Gate.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

_RR_MIN = 1.2


def grade_trade(side, entry, target, stop, bars) -> str:
    """Would the hypothetical option-direction trade have hit target before stop?
    CALL profits as spot rises (target above entry, stop below); PUT the reverse.
    `bars` = iterable of (high, low) after the decision. Returns 'win'/'loss'/
    'open'. Same-bar both-hit resolves conservatively to 'loss' (stop first).
    Pure (no pandas) so it's testable and reusable by the performance read."""
    try:
        entry = float(entry); target = float(target); stop = float(stop)
    except Exception:
        return "open"
    if side not in ("CALL", "PUT") or not bars:
        return "open"
    up = (side == "CALL")
    for bar in bars:
        try:
            hi, lo = float(bar[0]), float(bar[1])
        except Exception:
            continue
        hit_t = (hi >= target) if up else (lo <= target)
        hit_s = (lo <= stop) if up else (hi >= stop)
        if hit_t and hit_s:
            return "loss"
        if hit_t:
            return "win"
        if hit_s:
            return "loss"
    return "open"


def _stars(score: float) -> str:
    n = max(1, min(5, int(round(score))))
    return "★" * n + "☆" * (5 - n)


def _grade(avg: float) -> str:
    return "A+" if avg >= 4.5 else "A" if avg >= 3.8 else "B" if avg >= 3.0 else "C"


def build_decision(final_read: Optional[Dict[str, Any]],
                   reaction_sr: Optional[Dict[str, Any]],
                   gate: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    fr = final_read or {}
    g = gate or {}
    rsr = reaction_sr or {}

    state = g.get("state") or "WAIT"
    side = g.get("side")
    zone = g.get("zone")
    entry = g.get("level")
    target = g.get("target")
    stop = g.get("stop")
    rr = g.get("rr")

    passed, warnings, reasons, blocked_by = [], [], [], None
    q: Dict[str, float] = {}          # per-gate quality score (1-5)

    # ── gate 1: LOCATION ──
    at_zone = state not in ("WAIT", "PINNED", None) or bool(fr.get("battle_zone"))
    if at_zone:
        passed.append("location"); q["location"] = 5.0
        reasons.append("At zone")
    else:
        blocked_by = "location: spot mid-range — no active zone"
        q["location"] = 1.0

    # ── gate 2: DIRECTION (MIOS bias vs the side) ──
    pb = str(fr.get("preferred_bias") or "").upper()
    if side:
        want = "BULL" if side == "CALL" else "BEAR"
        if "STRONG_" + want in pb:
            passed.append("direction"); q["direction"] = 5.0; reasons.append("Direction aligned (strong)")
        elif want in pb:
            passed.append("direction"); q["direction"] = 4.0; reasons.append("Direction aligned")
        elif pb in ("NEUTRAL", "NONE", ""):
            warnings.append("MIOS bias neutral — no directional edge"); q["direction"] = 2.5
        else:
            warnings.append(f"MIOS bias {pb} disagrees with {side}"); q["direction"] = 1.0
    else:
        q["direction"] = 3.0

    # ── gate 3: ZONE HEALTH ──
    zc = (rsr.get("support") if zone == "SUPPORT"
          else rsr.get("resistance") if zone == "RESISTANCE" else None) or {}
    life = zc.get("lifecycle")
    if life:
        q["zone"] = {"building": 5.0, "holding": 4.0, "stable": 4.0,
                     "under-attack": 2.0, "fading": 1.5, "broken": 1.0}.get(life, 3.0)
        if life in ("fading", "broken", "under-attack"):
            warnings.append(f"zone {life} — defense weakening")
        else:
            passed.append("zone-health"); reasons.append(f"Zone {life}")
    else:
        q["zone"] = 3.0

    # ── gate 4: CONFIRMATION ──
    q["confirmation"] = {"CONFIRMED": 5.0, "IN_TRADE": 5.0,
                         "ARMED": 3.0}.get(state, 1.5)
    if state in ("CONFIRMED", "IN_TRADE"):
        passed.append("confirmation"); reasons.append("Confirmed")
    elif state == "ARMED":
        warnings.append("armed — needs a confirmation candle")

    # ── gate 5: RISK ──
    if rr is not None:
        try:
            rrf = float(rr)
            q["risk"] = 5.0 if rrf >= 3 else 4.0 if rrf >= 2 else 3.0 if rrf >= _RR_MIN else 1.5
            if rrf >= _RR_MIN:
                passed.append(f"risk R:R {rrf:.1f}"); reasons.append(f"R:R {rrf:.1f}")
            else:
                blocked_by = blocked_by or f"risk: R:R {rrf:.1f} too tight"
        except Exception:
            q["risk"] = 3.0
    else:
        q["risk"] = 3.0

    # ── gate 6: EVENT / VETO ──
    veto = False
    # 🚦 Stage 51 — the gatekeeper. This runs AFTER every other engine has had
    # its say and asks the last question: should this trade be taken at all?
    # Its rejection reasons are surfaced verbatim so a refusal is explainable.
    _val = fr.get("validity") or {}
    if _val.get("verdict") == "INVALID":
        _why = (_val.get("reasons") or [""])[0]
        warnings.append(f"🚦 validity {_val.get('pct', 0)}% — {_why}")
        veto = True
    # Stage 44 interrupt — institutional flow just shifted, so every read above
    # was computed on a tape that no longer exists. Freeze, don't lean.
    _fs = fr.get("flow_shift") or {}
    if _fs.get("freeze_entries"):
        warnings.append(f"⚠️ flow shift — {_fs.get('reason', 'tape repricing')}; "
                        "freeze entries, recalculate")
        veto = True
    elif fr.get("stability") == "RECOVERY":
        warnings.append("tape still settling after a flow shift — size down")
    if fr.get("event"):
        warnings.append("🚨 shock in progress — wait for the dust to settle"); veto = True
    if (fr.get("preparation") or {}).get("level") == "HIGH":
        warnings.append("⚠️ preparation — size down into the coil"); veto = True
    if fr.get("conflict_severity") == "HIGH":
        warnings.append("signals conflict sharply — lower conviction"); veto = True
    q["event"] = 2.0 if veto else 5.0
    if not veto:
        passed.append("no-veto"); reasons.append("Event clear")

    # ── final decision ──
    if state == "IN_TRADE":
        decision, dstate = "MANAGE", "IN_TRADE"
    elif blocked_by:
        decision, dstate = "WAIT", "WAIT"
    elif veto and state != "CONFIRMED":
        decision, dstate = "STAND ASIDE", "WAIT"
    elif state == "CONFIRMED":
        decision, dstate = (side or "WAIT"), "CONFIRMED"
    elif state == "ARMED":
        decision, dstate = "ARM " + (side or ""), "ARMED"
        blocked_by = "waiting for confirmation candle"
    else:
        decision, dstate = "WAIT", "WAIT"
        blocked_by = blocked_by or "waiting for zone touch / confirmation"

    # ── QUALITY gate — grade HOW GOOD, from the per-gate ★ scores ──
    _num = {k: (v if isinstance(v, (int, float)) else 3.0) for k, v in q.items()}
    avg = sum(_num.values()) / len(_num) if _num else 0.0
    quality = _grade(avg) if dstate in ("CONFIRMED", "ARMED", "IN_TRADE") else None
    stars = {k: _stars(v) for k, v in _num.items()}

    # ── a REJECTION = we were AT a zone (could have traded) but a gate blocked ──
    rejected = bool(at_zone and side and dstate == "WAIT")

    conf = fr.get("confidence_tempered", fr.get("confidence"))
    _e = f" @ ₹{entry:,.0f}" if isinstance(entry, (int, float)) and entry else ""
    if dstate == "CONFIRMED":
        headline = f"✅ {decision} · Quality {quality} · {conf}%{_e}"
    elif dstate == "ARMED":
        headline = f"⏳ {decision}{_e} — waiting for confirmation (Quality {quality})"
    elif dstate == "IN_TRADE":
        headline = f"📡 In {side} — manage"
    else:
        headline = f"⏳ {decision} — {blocked_by}"

    return {
        "decision": decision, "state": dstate, "side": side,
        "quality": quality, "quality_avg": round(avg, 2),
        "entry": entry, "target": target, "stop": stop, "rr": rr,
        "confidence": conf,
        "zone": {"price": entry, "side": zone, "lifecycle": life},
        "passed": passed, "warnings": warnings, "reasons": reasons,
        "gate_stars": stars, "blocked_by": blocked_by, "rejected": rejected,
        "validity": {"pct": _val.get("pct"), "verdict": _val.get("verdict"),
                     "stars": _val.get("stars"),
                     "reasons": (_val.get("reasons") or [])[:4]} if _val else None,
        "headline": headline,
    }
