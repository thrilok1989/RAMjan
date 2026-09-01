"""MIOS V6 — Stage 52 Floor / Ceiling proof (never enter on prediction).

The rule that outranks every other rule in MIOS:

    Never buy because the market looks bullish.
    Never sell because the market looks bearish.

    Enter a CALL only when sellers CANNOT push price lower.
    Enter a PUT  only when buyers  CANNOT push price higher.

The entry happens *after* the market has proven it, never before. "Support is
strong" is a prediction. "Sellers hit this level six times and could not make a
new low, while a buyer absorbed every attempt" is proof — and only the second one
is tradeable.

Eight checks must ALL pass:

    1 location    price is at a scored support/resistance zone
    2 pressure    heavy selling (floor) / buying (ceiling) actually arrived
    3 refusal     despite that pressure, price makes NO new extreme  ← the proof
    4 absorption  Stage 43 sees buyer/seller absorption or reloading
    5 reaction    Stage 42 has not invalidated the level
    6 flow        Stage 44 stability is STABLE, not SHOCK
    7 htf         Stage 45 higher timeframes agree
    8 validity    Stage 51 says VALID

Check 3 is the one that makes this different from every other entry model. It
cannot be evaluated from a snapshot — it needs the sequence of lows (or highs)
made *while price sat at the zone*.

**Entry is the refusal price, not the zone price.** If support is 23,650 and
price ground down to 23,644 and stopped, the floor is 23,644 — that is where the
market proved itself, and entering at 23,650 means entering 6 points before the
proof existed.

Pure module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: how close successive extremes must be to count as "no new extreme" (% of price)
_FLAT_PCT = 0.015
#: how many attempts at the level before refusal is credible
_MIN_ATTEMPTS = 3
#: CVD magnitude that counts as heavy pressure arriving
_HEAVY = 15.0

CHECKS = ("location", "pressure", "refusal", "absorption",
          "reaction", "flow", "htf", "validity")

CHECK_LABEL = {
    "location": "At a scored zone",
    "pressure": "Heavy pressure arrived",
    "refusal": "Price refusing to continue",
    "absorption": "Absorption / reloading",
    "reaction": "Level not invalidated",
    "flow": "Flow stable",
    "htf": "HTF agrees",
    "validity": "Signal valid",
}

# ── Stage-42 states that INVALIDATE a floor (for a CALL) ────────────────
# NOTE ON "REJECTION": at a SUPPORT, rejection means price probed lower and was
# pushed back — that IS the floor proof, so it qualifies. Excluding "rejected"
# wholesale would block this engine's primary entry case. What actually
# invalidates a floor is the support giving way, or a bullish move that has
# already been shown to be a trap.
_FLOOR_INVALIDATORS = ("CONFIRMED_BREAKDOWN", "FAILED_BREAKOUT", "BULL_TRAP",
                       "SWEEP_BUY", "ABSORPTION")
_CEILING_INVALIDATORS = ("CONFIRMED_BREAKOUT", "FAILED_BREAKDOWN", "BEAR_TRAP",
                         "SWEEP_SELL", "ABSORPTION")

_FLOOR_ABSORPTION = ("PASSIVE_BUYING", "BUYER_RELOADING", "SELLER_EXHAUSTION")
_CEILING_ABSORPTION = ("PASSIVE_SELLING", "SELLER_RELOADING", "BUYER_EXHAUSTION")


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "").upper()


def detect_refusal(extremes: Optional[Sequence[float]], floor: bool,
                   flat_pct: float = _FLAT_PCT,
                   min_attempts: int = _MIN_ATTEMPTS) -> Dict[str, Any]:
    """THE proof. Given the lows (floor) or highs (ceiling) made while price sat
    at the zone: did the market stop making new extremes?

    Returns {proven, price, attempts, reason}. `price` is the refusal level —
    the deepest point the market reached and could not exceed. That is the entry,
    not the zone.
    """
    vals = [_f(v) for v in (extremes or [])]
    vals = [v for v in vals if v is not None]
    if len(vals) < min_attempts:
        return {"proven": False, "price": None, "attempts": len(vals),
                "reason": f"only {len(vals)} attempts — need {min_attempts}"}

    extreme = min(vals) if floor else max(vals)
    tol = abs(extreme) * flat_pct / 100.0

    # how many of the recent attempts came within tolerance of the extreme
    # WITHOUT exceeding it — that is the market trying and failing
    recent = vals[-6:]
    touches = 0
    for v in recent:
        if floor and v <= extreme + tol:
            touches += 1
        elif not floor and v >= extreme - tol:
            touches += 1

    # and the decisive part: the LATEST attempt did not make a new extreme
    last = recent[-1]
    no_new = (last > extreme + tol) if floor else (last < extreme - tol)
    held = (last <= extreme + tol) if floor else (last >= extreme - tol)

    proven = touches >= 2 and (no_new or held) and len(vals) >= min_attempts
    # Was the extreme set on the LATEST attempt with nothing re-testing it?
    # Then the market is still making fresh extremes — it has not refused
    # anything. (`held` is trivially true in that case, since the newest low IS
    # the low, so it can't be used to tell the two situations apart.)
    still_extending = (touches < 2 and abs(last - extreme) <= tol)
    if proven:
        reason = (f"{touches} attempts at "
                  f"{'low' if floor else 'high'} {extreme:,.0f} — no new "
                  f"{'low' if floor else 'high'}")
    elif still_extending:
        reason = f"still making new {'lows' if floor else 'highs'}"
    else:
        reason = f"only {touches} attempt(s) at the extreme"
    return {"proven": bool(proven), "price": round(extreme, 2),
            "attempts": len(vals), "touches": touches,
            "still_extending": bool(still_extending), "reason": reason}


def prove(side: str,
          zone: Optional[Dict[str, Any]] = None,
          extremes: Optional[Sequence[float]] = None,
          ltp: Optional[Dict[str, Any]] = None,
          absorption: Optional[Dict[str, Any]] = None,
          reaction: Optional[Dict[str, Any]] = None,
          flow: Optional[Dict[str, Any]] = None,
          htf: Optional[Dict[str, Any]] = None,
          validity: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run the eight checks for a FLOOR (side='CALL') or CEILING (side='PUT').

    Returns {confirmed, entry, checks, passed, failed, reasons, refusal}.
    """
    floor = _s(side) == "CALL"
    z, lb = zone or {}, ltp or {}
    ab, rc = absorption or {}, reaction or {}
    fl, hf, vd = flow or {}, htf or {}, validity or {}

    checks: Dict[str, Optional[bool]] = {}
    reasons: List[str] = []
    fails: List[str] = []

    # ── 1 · LOCATION ──
    zp, zs = _f(z.get("price")), _f(z.get("strength"))
    checks["location"] = bool(zp) and (zs is None or zs >= 40)
    if checks["location"]:
        reasons.append(f"At {'support' if floor else 'resistance'} "
                       f"₹{zp:,.0f}" + (f" ({zs:.0f}%)" if zs else ""))
    else:
        fails.append("no scored zone at price")

    # ── 2 · PRESSURE ARRIVED ──
    # a floor only means something if sellers actually showed up to test it
    cvd = _f(lb.get("cvd"))
    side_state = _s(((lb.get("sellers") if floor else lb.get("buyers")) or {}).get("state"))
    pressure = (side_state in ("BUILDING", "ABSORBING", "EXHAUSTED")
                or (cvd is not None and ((cvd <= -_HEAVY) if floor else (cvd >= _HEAVY))))
    checks["pressure"] = bool(pressure)
    if pressure:
        reasons.append(f"Heavy {'selling' if floor else 'buying'} reached the level")
    else:
        fails.append(f"no real {'selling' if floor else 'buying'} pressure — "
                     f"nothing has been tested")

    # ── 3 · REFUSAL — the proof ──
    ref = detect_refusal(extremes, floor)
    checks["refusal"] = ref["proven"]
    if ref["proven"]:
        reasons.append(f"Price refusing lower levels — {ref['reason']}"
                       if floor else
                       f"Price refusing higher levels — {ref['reason']}")
    else:
        fails.append(f"no refusal yet — {ref['reason']}")

    # ── 4 · ABSORPTION ──
    beh = _s(ab.get("behaviour"))
    checks["absorption"] = beh in (_FLOOR_ABSORPTION if floor else _CEILING_ABSORPTION)
    if checks["absorption"]:
        reasons.append(f"{ab.get('label', beh)} confirmed")
    else:
        fails.append("no absorption / reloading footprint")

    # ── 5 · REACTION not invalidated ──
    rs = _s(rc.get("state"))
    bad = _FLOOR_INVALIDATORS if floor else _CEILING_INVALIDATORS
    checks["reaction"] = rs not in bad
    if checks["reaction"]:
        if rs:
            reasons.append(f"Reaction {rs.replace('_', ' ').title()} — level intact")
    else:
        fails.append(f"{rs.replace('_', ' ').title()} invalidates the "
                     f"{'floor' if floor else 'ceiling'}")

    # ── 6 · FLOW STABLE ──
    stab = _s(fl.get("stability"))
    checks["flow"] = (stab == "STABLE") and not fl.get("freeze_entries")
    if checks["flow"]:
        reasons.append("Flow stable")
    else:
        fails.append(f"flow {stab.lower() or 'unknown'} — tape not settled")

    # ── 7 · HTF ──
    hp = _f(hf.get("pct"))
    checks["htf"] = (hp is not None and hp >= 60) or bool(hf.get("approved"))
    if checks["htf"]:
        reasons.append(f"HTF agrees ({hp:.0f}%)" if hp is not None else "HTF agrees")
    else:
        fails.append(f"higher timeframes disagree"
                     + (f" ({hp:.0f}%)" if hp is not None else ""))

    # ── 8 · VALIDITY ──
    checks["validity"] = bool(vd.get("valid"))
    if checks["validity"]:
        reasons.append(f"Signal valid ({vd.get('pct', 0)}%)")
    else:
        fails.append("signal validity filter says INVALID"
                     + (f" — {(vd.get('reasons') or [''])[0]}" if vd.get("reasons") else ""))

    confirmed = all(checks.get(c) for c in CHECKS)
    return {
        "confirmed": confirmed, "side": _s(side), "floor": floor,
        # THE ENTRY: the price at which the market proved it, not the zone price
        "entry": ref["price"] if ref["proven"] else None,
        "zone_price": zp, "refusal": ref,
        "checks": checks, "passed": [c for c in CHECKS if checks.get(c)],
        "failed": fails, "reasons": reasons,
        "n_passed": sum(1 for c in CHECKS if checks.get(c)),
        "n_checks": len(CHECKS),
        "label": ("FLOOR CONFIRMED" if floor else "CEILING CONFIRMED")
                 if confirmed else None,
    }


# ── ADAPTIVE STOP ───────────────────────────────────────────────────────
def adaptive_stop(entry: Optional[float], floor: bool,
                  market_state: Optional[str] = None,
                  energy_state: Optional[str] = None,
                  atr: Optional[float] = None,
                  refusal_price: Optional[float] = None) -> Dict[str, Any]:
    """The stop is set by market MOOD, not a fixed number.

    A trend needs room to breathe; a range does not. Compression sits below the
    accumulation zone. Expansion uses ATR. A shocked tape has no valid stop at
    all — the trade should not exist.
    """
    e = _f(entry)
    if e is None:
        return {"stop": None, "mode": None, "reason": "no entry price"}
    ms, es = _s(market_state), _s(energy_state)
    base = _f(refusal_price) or e
    a = _f(atr)

    if ms == "WAIT" or es == "SHOCK":
        return {"stop": None, "mode": "abort",
                "reason": "tape in shock — abort rather than place a stop"}

    if es == "EXPANSION" and a:
        dist, mode = a * 1.2, "atr"
    elif ms in ("TREND_UP", "TREND_DOWN", "MARKUP", "MARKDOWN", "BREAKOUT",
                "BREAKDOWN"):
        dist, mode = (a * 1.5 if a else e * 0.0035), "trend-wide"
    elif es == "COMPRESSION":
        dist, mode = (a * 0.8 if a else e * 0.0018), "below-accumulation"
    elif ms in ("ROTATION", "WAR_ZONE", "COMPRESSION"):
        dist, mode = (a * 0.9 if a else e * 0.0020), "range-tight"
    else:
        dist, mode = (a if a else e * 0.0025), "default"

    stop = base - dist if floor else base + dist
    return {"stop": round(stop, 1), "mode": mode, "distance": round(dist, 1),
            "reason": f"{mode} stop, {dist:.0f} pts beyond the "
                      f"{'floor' if floor else 'ceiling'}"}


# ── ADAPTIVE TRAIL ──────────────────────────────────────────────────────
def adaptive_trail(floor: bool,
                   market_state: Optional[str] = None,
                   transition: Optional[Dict[str, Any]] = None,
                   absorption: Optional[Dict[str, Any]] = None,
                   flow: Optional[Dict[str, Any]] = None,
                   dealer_flip: bool = False,
                   atr: Optional[float] = None) -> Dict[str, Any]:
    """How tightly to trail, from the market's current mood.

    Strong trend → loose. Weak trend → tight. Exhaustion, a weakening bias, a
    dealer flip or a flow shift all tighten it or lock profit, because each one
    means the move that justified the trade is no longer the move in progress.
    """
    ms = _s(market_state)
    tr, ab, fl = transition or {}, absorption or {}, flow or {}
    a = _f(atr)
    mult, mode, notes = 1.5, "normal", []

    if ms in ("MARKUP", "MARKDOWN", "BREAKOUT", "BREAKDOWN") and \
            _s(tr.get("state")) == "STRENGTHENING":
        mult, mode = 2.5, "loose"
        notes.append("strong trend — give it room")
    elif ms in ("TREND_UP", "TREND_DOWN"):
        mult, mode = 1.8, "normal"

    beh = _s(ab.get("behaviour"))
    exhausted = ("EXHAUSTION" in beh)
    if exhausted:
        mult, mode = min(mult, 0.9), "tight"
        notes.append("exhaustion — tighten")
    if _s(tr.get("state")) in ("WEAKENING", "REVERSING"):
        mult, mode = min(mult, 0.8), "lock-profit"
        notes.append("bias weakening — lock profit")
    if dealer_flip:
        mult, mode = min(mult, 0.7), "tight"
        notes.append("dealer flip — tighten")
    if fl.get("freeze_entries") or _s(fl.get("stability")) == "SHOCK":
        mode = "review"
        notes.append("flow shift — review the position immediately")

    dist = (a * mult) if a else None
    return {"mode": mode, "multiplier": round(mult, 2),
            "distance": round(dist, 1) if dist else None,
            "notes": notes,
            "reason": "; ".join(notes) if notes else "normal trail"}
