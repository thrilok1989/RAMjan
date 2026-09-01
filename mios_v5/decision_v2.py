"""MIOS V6 — Stage 52 Decision Engine v2 (the final brain).

Every engine supplies evidence. Only this one issues actions — and it issues
them under one rule that outranks everything else in MIOS:

    **MIOS never enters on prediction.**
    A CALL requires proof that sellers CANNOT push price lower.
    A PUT  requires proof that buyers  CANNOT push price higher.

"Bias is bullish and support is strong" is a forecast. It is not permission to
trade. Permission comes only from `floor_ceiling.prove()` returning
FLOOR/CEILING CONFIRMED — the market having demonstrated the level, not an
engine having predicted it.

Twelve states, one at a time:

    WAIT → ENTRY READY → FLOOR/CEILING CONFIRMED → ENTER → HOLD
         → SCALE IN → TRAIL → SCALE OUT → EXIT → COMPLETE
    ABORT overrides all of them, at any point.

ABORT is checked first and unconditionally. A shocked tape, a confirmed trap
against the position, or a bias reversal invalidates a trade regardless of how
good it looked when it was taken — and the cost of exiting a good trade early is
far smaller than the cost of holding through a regime change.

Pure module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

STATES = ("WAIT", "ENTRY_READY", "FLOOR_CONFIRMED", "CEILING_CONFIRMED",
          "ENTER", "HOLD", "SCALE_IN", "SCALE_OUT", "TRAIL", "EXIT",
          "COMPLETE", "ABORT")

LABEL = {
    "WAIT": "⏳ WAIT", "ENTRY_READY": "👀 ENTRY READY",
    "FLOOR_CONFIRMED": "🟢 FLOOR CONFIRMED", "CEILING_CONFIRMED": "🔴 CEILING CONFIRMED",
    "ENTER": "✅ ENTER", "HOLD": "🤝 HOLD", "SCALE_IN": "➕ SCALE IN",
    "SCALE_OUT": "➖ SCALE OUT", "TRAIL": "📈 TRAIL", "EXIT": "🚪 EXIT",
    "COMPLETE": "🏁 COMPLETE", "ABORT": "🛑 ABORT",
}

#: minimum engines that must have reported before any entry is allowed —
#: no single engine may ever produce a trade
_MIN_EVIDENCE = 6

EVIDENCE_ENGINES = ("market_state", "acceptance", "absorption", "flow_shift",
                    "transition", "confluence", "dealer", "orderflow",
                    "htf", "validity", "structure")


def _s(v) -> str:
    return str(v or "").upper()


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def evidence_count(ev: Optional[Dict[str, Any]]) -> int:
    """How many independent engines actually reported. The Decision Engine may
    never generate a trade from one engine, however emphatic that engine is."""
    return sum(1 for k in EVIDENCE_ENGINES if (ev or {}).get(k))


def check_abort(position: Optional[Dict[str, Any]] = None,
                flow: Optional[Dict[str, Any]] = None,
                reaction: Optional[Dict[str, Any]] = None,
                transition: Optional[Dict[str, Any]] = None,
                energy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """ABORT has the highest priority and is evaluated before anything else.

    Exiting a good trade early costs a little. Holding through a shock, a
    confirmed trap against the position, or a bias reversal costs a lot.
    """
    pos, fl = position or {}, flow or {}
    rc, tr, en = reaction or {}, transition or {}, energy or {}
    side = _s(pos.get("side"))
    reasons: List[str] = []

    if fl.get("freeze_entries") or _s(fl.get("stability")) == "SHOCK":
        reasons.append("Institutional flow shift — tape repricing")
    if _s(en.get("state")) == "SHOCK":
        reasons.append("Energy shock")

    rs = _s(rc.get("state"))
    if side == "CALL" and rs in ("BULL_TRAP", "CONFIRMED_BREAKDOWN"):
        reasons.append(f"{rs.replace('_', ' ').title()} against a long")
    if side == "PUT" and rs in ("BEAR_TRAP", "CONFIRMED_BREAKOUT"):
        reasons.append(f"{rs.replace('_', ' ').title()} against a short")

    ts, bias = _s(tr.get("state")), _s(tr.get("bias"))
    if ts == "REVERSING" and side:
        want = "BULL" if side == "CALL" else "BEAR"
        if want not in bias:
            reasons.append("Bias reversed against the position")

    return {"abort": bool(reasons), "reasons": reasons}


def decide(proof: Optional[Dict[str, Any]] = None,
           position: Optional[Dict[str, Any]] = None,
           evidence: Optional[Dict[str, Any]] = None,
           flow: Optional[Dict[str, Any]] = None,
           reaction: Optional[Dict[str, Any]] = None,
           transition: Optional[Dict[str, Any]] = None,
           energy: Optional[Dict[str, Any]] = None,
           market_state: Optional[Dict[str, Any]] = None,
           absorption: Optional[Dict[str, Any]] = None,
           spot: Optional[float] = None,
           stop: Optional[Dict[str, Any]] = None,
           trail: Optional[Dict[str, Any]] = None,
           quality: Optional[str] = None) -> Dict[str, Any]:
    """Resolve the single current decision state."""
    pf, pos = proof or {}, position or {}
    reasons: List[str] = []
    warnings: List[str] = []

    # ── ABORT — first, always ──
    ab = check_abort(pos, flow, reaction, transition, energy)
    if ab["abort"]:
        return _out("ABORT", side=pos.get("side"), reasons=ab["reasons"],
                    confidence=95, in_trade=bool(pos.get("side")),
                    action=("Close the position now" if pos.get("side")
                            else "Stand aside — do not enter"))

    n_ev = evidence_count(evidence)
    side = _s(pf.get("side")) or _s(pos.get("side"))

    # ── IN A POSITION → manage it ──
    if pos.get("side"):
        return _manage(pos, spot, transition, absorption, market_state,
                       trail, reaction)

    # ── FLAT → is there proof yet? ──
    if n_ev < _MIN_EVIDENCE:
        return _out("WAIT", side=side,
                    reasons=[f"Only {n_ev}/{_MIN_EVIDENCE} engines reporting — "
                             "no trade may come from thin evidence"],
                    confidence=0)

    if pf.get("confirmed"):
        state = "FLOOR_CONFIRMED" if pf.get("floor") else "CEILING_CONFIRMED"
        reasons = list(pf.get("reasons") or [])
        entry = pf.get("entry")
        s = (stop or {})
        if s.get("mode") == "abort" or s.get("stop") is None:
            warnings.append("No valid stop for this mood — standing aside")
            return _out("WAIT", side=side, reasons=reasons,
                        warnings=warnings, confidence=40)
        # proof + a valid stop = the only path to ENTER in this engine
        return _out("ENTER", side=side, reasons=reasons, confidence=
                    int(min(97, 60 + pf.get("n_passed", 0) * 4)),
                    entry=entry, stop=s.get("stop"), trail=trail,
                    quality=quality, proof_state=state,
                    action=f"ENTER {side} at {entry:,.0f}" if entry else None)

    # close but unproven → ENTRY READY (watch, do not act)
    n_pass = int(pf.get("n_passed") or 0)
    if n_pass >= 5:
        return _out("ENTRY_READY", side=side,
                    reasons=list(pf.get("reasons") or []),
                    warnings=[f"Not proven yet: {f}" for f in
                              (pf.get("failed") or [])[:3]],
                    confidence=int(40 + n_pass * 4))

    return _out("WAIT", side=side or None,
                reasons=list(pf.get("reasons") or [])[:2],
                warnings=[f for f in (pf.get("failed") or [])[:3]],
                confidence=int(n_pass * 5))


def _manage(pos: Dict[str, Any], spot: Optional[float],
            transition: Optional[Dict[str, Any]],
            absorption: Optional[Dict[str, Any]],
            market_state: Optional[Dict[str, Any]],
            trail: Optional[Dict[str, Any]],
            reaction: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Position management: HOLD · SCALE IN · TRAIL · SCALE OUT · EXIT."""
    side = _s(pos.get("side"))
    entry, tgt = _f(pos.get("entry")), _f(pos.get("target"))
    st = _f(spot)
    up = side == "CALL"
    tr, ab = transition or {}, absorption or {}
    ms = _s((market_state or {}).get("state"))
    gain = ((st - entry) if up else (entry - st)) if (st and entry) else None

    reasons: List[str] = []
    if gain is not None:
        reasons.append(f"{gain:+.0f} pts from entry")

    # target reached → COMPLETE
    if tgt and st and ((st >= tgt) if up else (st <= tgt)):
        return _out("COMPLETE", side=side, reasons=reasons + ["Target reached"],
                    confidence=90, in_trade=True, action="Book the trade")

    beh = _s(ab.get("behaviour"))
    ts = _s(tr.get("state"))
    exhausted = "EXHAUSTION" in beh and (beh.startswith("BUYER") == up)

    # the move that justified the trade is ending → take some off
    if exhausted or ts == "WEAKENING":
        reasons.append("Exhaustion / bias weakening — reduce exposure")
        return _out("SCALE_OUT", side=side, reasons=reasons, confidence=75,
                    in_trade=True, trail=trail,
                    action="Reduce size and tighten the trail")

    # strong continuation with room → add
    if ts == "STRENGTHENING" and ms in ("MARKUP", "MARKDOWN", "BREAKOUT",
                                        "BREAKDOWN") and (gain or 0) > 0:
        reasons.append("Trend strengthening with the position")
        return _out("SCALE_IN", side=side, reasons=reasons, confidence=80,
                    in_trade=True, trail=trail, action="Add on strength")

    # in profit and trending → trail it
    if gain is not None and gain > 0 and ms in ("TREND_UP", "TREND_DOWN",
                                                "MARKUP", "MARKDOWN"):
        return _out("TRAIL", side=side, reasons=reasons, confidence=78,
                    in_trade=True, trail=trail,
                    action=f"Trail ({(trail or {}).get('mode', 'normal')})")

    return _out("HOLD", side=side, reasons=reasons, confidence=70,
                in_trade=True, trail=trail, action="Hold — thesis intact")


def _out(state: str, side: Optional[str] = None,
         reasons: Optional[List[str]] = None,
         warnings: Optional[List[str]] = None,
         confidence: int = 0, entry: Optional[float] = None,
         stop: Optional[float] = None, trail: Optional[Dict[str, Any]] = None,
         quality: Optional[str] = None, in_trade: bool = False,
         action: Optional[str] = None,
         proof_state: Optional[str] = None) -> Dict[str, Any]:
    return {"state": state, "label": LABEL.get(state, state),
            "side": side or None, "confidence": int(confidence),
            "entry": entry, "stop": stop, "trail": trail, "quality": quality,
            "reasons": reasons or [], "warnings": warnings or [],
            "in_trade": in_trade, "action": action,
            "proof_state": proof_state,
            "actionable": state in ("ENTER", "SCALE_IN", "SCALE_OUT",
                                    "EXIT", "ABORT", "COMPLETE")}
