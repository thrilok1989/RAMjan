"""MIOS V6 — Stage 51 Signal Validity Filter (the gatekeeper).

The last filter before the Decision Engine. It never creates a signal; it answers
one question about a signal that already exists:

    "Even though everything looks good — should I actually take this trade?"

Many setups satisfy 80% of the conditions. Professionals ask whether this is
really the *right place* to trade, and refuse things like buying into Daily
resistance, selling into Weekly support, trading against institutions, taking a
trap before it confirms, or entering while the tape is in shock.

Nine weighted checks → a 0-100 score, VALID / INVALID, and — the part that
matters most — **the reason it refused**. A rejection nobody understands is a
rejection nobody trusts.

    Bias 10 · HTF 15 · Dealer 10 · Institutions 15 · Trap 15 ·
    Flow Shift 10 · Energy 10 · Order Flow 10 · Zone 5      = 100

Two rules that keep it honest:

  • **Unknown is not a pass.** A missing input scores nothing and is excluded
    from the denominator, and if too little evidence is available at all the
    verdict is INVALID for *insufficient evidence* — never a confident VALID
    built on two warm engines.
  • **Hard vetoes override the score.** A tape in shock, a live event, or an
    unconfirmed trap is an immediate INVALID no matter how good the rest looks.
    Some conditions are not tradeable at any score.

Pure module: a context dict in, a verdict out.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

#: check → weight (sums to 100)
WEIGHTS = {
    "bias": 10, "htf": 15, "dealer": 10, "institutions": 15, "trap": 15,
    "flow_shift": 10, "energy": 10, "orderflow": 10, "zone": 5,
}

LABELS = {
    "bias": "Bias", "htf": "HTF Alignment", "dealer": "Dealer",
    "institutions": "Institutions", "trap": "Trap Confirmation",
    "flow_shift": "Flow Shift", "energy": "Energy",
    "orderflow": "Order Flow", "zone": "Zone",
}

#: below this fraction of total weight actually available, we cannot judge
_MIN_COVERAGE = 0.60
#: score needed to pass, once there is enough evidence to judge at all
_PASS = 70.0

_BULLISH = ("BULL", "STRONG_BULL")
_BEARISH = ("BEAR", "STRONG_BEAR")


def _want(side: Optional[str]) -> Optional[str]:
    s = str(side or "").upper()
    if s in ("CALL", "BUY", "BULL", "LONG"):
        return "BULL"
    if s in ("PUT", "SELL", "BEAR", "SHORT"):
        return "BEAR"
    return None


def _agrees(bias: Optional[str], want: str) -> Optional[bool]:
    """Does a bias agree with the intended side? None when it's unknown —
    NEUTRAL is a genuine 'no support', which is different from missing."""
    b = str(bias or "").upper()
    if not b or b in ("NONE", "MISSING", "UNKNOWN"):
        return None
    if b in ("NEUTRAL", "SIDEWAYS"):
        return False
    return (b in _BULLISH) if want == "BULL" else (b in _BEARISH)


def _num_ok(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _stars(pct: float) -> str:
    n = max(0, min(5, int(round(pct / 20.0))))
    return "★" * n + "☆" * (5 - n)


def evaluate_validity(side: Optional[str],
                      ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Validate a proposed trade side against the full engine context.

    ctx keys (all optional — missing ones simply cannot be scored):
      bias · bias_transition · htf_validity_pct · dealer_bias · institutions_bias
      · reaction_state · reaction_actionable · flow_stability · flow_freeze
      · energy · orderflow_bias · zone_lifecycle · zone_health_pct
      · event_active · market_state
    """
    c = dict(ctx or {})
    want = _want(side)
    if want is None:
        return {"pct": 0, "valid": False, "verdict": "UNKNOWN",
                "stars": _stars(0), "checks": {}, "passed": [], "failed": [],
                "reasons": ["No side proposed — nothing to validate"],
                "coverage": 0, "vetoes": []}

    checks: Dict[str, Optional[bool]] = {}
    detail: Dict[str, str] = {}

    # ── 1 · BIAS ──
    checks["bias"] = _agrees(c.get("bias"), want)
    detail["bias"] = f"market bias {c.get('bias') or '—'}"
    # a weakening bias should not be traded aggressively in its own direction
    trans = str(c.get("bias_transition") or "").lower()
    if checks["bias"] and trans in ("weakening", "reversing"):
        checks["bias"] = False
        detail["bias"] = f"bias {c.get('bias')} but {trans} — losing conviction"

    # ── 2 · HIGHER TIMEFRAMES ──
    hp = c.get("htf_validity_pct")
    if hp is None:
        checks["htf"] = None
        detail["htf"] = "higher timeframes unavailable"
    else:
        checks["htf"] = float(hp) >= 60.0
        detail["htf"] = f"HTF agreement {float(hp):.0f}%"

    # ── 3 · DEALER ──
    checks["dealer"] = _agrees(c.get("dealer_bias"), want)
    detail["dealer"] = f"dealer {c.get('dealer_bias') or '—'}"

    # ── 4 · INSTITUTIONS ──
    checks["institutions"] = _agrees(c.get("institutions_bias"), want)
    detail["institutions"] = f"institutions {c.get('institutions_bias') or '—'}"

    # ── 5 · TRAP / ACCEPTANCE CONFIRMATION ──
    rs = str(c.get("reaction_state") or "").upper()
    if not rs or rs == "IDLE":
        checks["trap"] = None
        detail["trap"] = "no reaction at a level yet"
    else:
        good_bull = ("CONFIRMED_BREAKOUT", "ACCEPTANCE", "BEAR_TRAP", "SWEEP_SELL")
        good_bear = ("CONFIRMED_BREAKDOWN", "ACCEPTANCE", "BULL_TRAP", "SWEEP_BUY")
        ok = rs in (good_bull if want == "BULL" else good_bear)
        # a failed break that hasn't confirmed is explicitly NOT a trade yet
        if rs in ("FAILED_BREAKOUT", "FAILED_BREAKDOWN"):
            ok = False
            detail["trap"] = f"{rs.replace('_', ' ').lower()} — not confirmed yet"
        else:
            detail["trap"] = rs.replace("_", " ").lower()
        checks["trap"] = ok

    # ── 6 · FLOW SHIFT / STABILITY ──
    stab = str(c.get("flow_stability") or "").upper()
    if not stab:
        checks["flow_shift"] = None
        detail["flow_shift"] = "stability unknown"
    else:
        checks["flow_shift"] = stab == "STABLE"
        detail["flow_shift"] = f"tape {stab.lower()}"

    # ── 7 · ENERGY ──
    # Stage 37 supplies a state as well as a number: DEAD energy fails outright
    # (breakout entries die in a damped market) regardless of the raw strength.
    est = str(c.get("energy_state") or "").upper()
    en = c.get("energy")
    if est:
        checks["energy"] = est not in ("DEAD",)
        detail["energy"] = f"energy {est.lower()}" + (
            f" {float(en):.0f}%" if _num_ok(en) else "")
    elif en is None:
        checks["energy"] = None
        detail["energy"] = "energy unknown"
    else:
        try:
            checks["energy"] = float(en) >= 30.0
            detail["energy"] = f"energy {float(en):.0f}%"
        except (TypeError, ValueError):
            e = str(en).lower()
            checks["energy"] = e not in ("dead", "weak")
            detail["energy"] = f"energy {e}"

    # ── 8 · ORDER FLOW ──
    checks["orderflow"] = _agrees(c.get("orderflow_bias"), want)
    detail["orderflow"] = f"order flow {c.get('orderflow_bias') or '—'}"

    # ── 9 · ZONE ──
    life = str(c.get("zone_lifecycle") or "").lower()
    hpct = c.get("zone_health_pct")
    if not life and hpct is None:
        checks["zone"] = None
        detail["zone"] = "zone unknown"
    else:
        bad = life in ("fading", "broken", "breaking", "under-attack", "retired")
        weak = (float(hpct) < 45.0) if hpct is not None else False
        checks["zone"] = not (bad or weak)
        detail["zone"] = f"zone {life or '—'}" + (
            f" · health {float(hpct):.0f}%" if hpct is not None else "")

    # ── score: unknown earns nothing AND is excluded from the denominator ──
    got = sum(WEIGHTS[k] for k, v in checks.items() if v is True)
    known = sum(WEIGHTS[k] for k, v in checks.items() if v is not None)
    pct = (got / known * 100.0) if known else 0.0
    coverage = round(known / sum(WEIGHTS.values()) * 100)

    passed = [LABELS[k] for k, v in checks.items() if v is True]
    failed = [f"{LABELS[k]} — {detail.get(k, '')}"
              for k, v in checks.items() if v is False]

    # ── hard vetoes — untradeable regardless of how good the score looks ──
    vetoes: List[str] = []
    if c.get("flow_freeze") or stab == "SHOCK":
        vetoes.append("Institutional flow shift in progress — recalculate first")
    if c.get("event_active"):
        vetoes.append("Major event live — no entry until the dust settles")
    if rs in ("FAILED_BREAKOUT", "FAILED_BREAKDOWN"):
        vetoes.append(f"{rs.replace('_', ' ').title()} has not confirmed — "
                      "wait for the flow to reverse")
    if rs == "ABSORPTION":
        vetoes.append("Absorption at the level — wait for the resolution")
    # Stage 54 — a market state that formed moments ago has not proven itself.
    # Institutions don't change their mind every minute; acting on a 2-minute
    # state is acting on noise.
    if c.get("state_fresh") and c.get("state_duration_min") is not None:
        vetoes.append(f"Market state only "
                      f"{float(c['state_duration_min']):.0f} min old — too "
                      f"young to act on")
    # A bias that is about to flip must not be traded in its own direction, even
    # while it is still technically the prevailing bias. Without this, a
    # collapsing bear only cost the 10-point Bias check and a short stayed
    # "valid" right up until the reversal.
    _rp = c.get("reversal_probability")
    try:
        _rp = float(_rp) if _rp is not None else None
    except (TypeError, ValueError):
        _rp = None
    if _rp is not None and _rp >= 65 and _agrees(c.get("bias"), want) is not False:
        vetoes.append(f"Reversal probability {_rp:.0f}% — the prevailing bias is "
                      f"about to turn; do not press it")

    if known == 0:
        verdict, valid = "INVALID", False
        reasons = ["No engine evidence available yet"]
    elif coverage < _MIN_COVERAGE * 100:
        verdict, valid = "INVALID", False
        reasons = [f"Insufficient evidence — only {coverage}% of checks "
                   f"available; cannot validate"] + failed
    elif vetoes:
        verdict, valid = "INVALID", False
        reasons = vetoes + failed
    elif pct >= _PASS:
        verdict, valid = "VALID", True
        reasons = []
    else:
        verdict, valid = "INVALID", False
        reasons = failed or ["Score below the validity threshold"]

    return {"pct": round(pct), "valid": valid, "verdict": verdict,
            "stars": _stars(pct), "checks": checks, "detail": detail,
            "passed": passed, "failed": failed, "reasons": reasons,
            "coverage": coverage, "vetoes": vetoes, "side": side,
            "threshold": _PASS}


def context_from_final_read(fr: Optional[Dict[str, Any]],
                            side: Optional[str] = None) -> Dict[str, Any]:
    """Build the validity context from a Stage-41 final read. Kept here so the
    mapping lives beside the checks that consume it."""
    f = dict(fr or {})
    fam = f.get("families") or {}

    def _fam(name):
        v = fam.get(name) or {}
        return v.get("direction") if v.get("status") == "OK" else None

    htf_pct = None
    try:
        from .htf_vpfr import signal_validity
        reads = ((f.get("htf") or {}).get("reads")) or {}
        if reads and side:
            htf_pct = signal_validity(side, reads).get("pct")
    except Exception:
        htf_pct = None

    reaction = f.get("reaction") or {}
    zone = (reaction.get("side") or "").lower()
    zsrc = (f.get("zone_health") or {})
    return {
        "bias": f.get("preferred_bias"),
        "bias_transition": f.get("bias_transition"),
        "reversal_probability": (f.get("transition") or {}).get("reversal_probability"),
        "htf_validity_pct": htf_pct,
        "dealer_bias": _fam("dealer") or ((f.get("sections") or {}).get("dealer") or {}).get("bias"),
        "institutions_bias": _fam("institutions"),
        "orderflow_bias": _fam("orderflow") or ((f.get("sections") or {}).get("orderflow") or {}).get("bias"),
        "reaction_state": reaction.get("state"),
        "reaction_actionable": f.get("reaction_actionable"),
        "flow_stability": f.get("stability"),
        "flow_freeze": bool((f.get("flow_shift") or {}).get("freeze_entries")),
        "energy": (f.get("energy_read") or {}).get("strength", f.get("energy")),
        "energy_state": (f.get("energy_read") or {}).get("state"),
        "zone_lifecycle": zsrc.get("lifecycle") or reaction.get("lifecycle"),
        "zone_health_pct": zsrc.get("pct"),
        "event_active": bool(f.get("event")),
        "market_state": f.get("day_type"),
        "state_fresh": (f.get("memory_read") or {}).get("state_fresh"),
        "state_duration_min": (f.get("memory_read") or {}).get("state_duration_min"),
    }
