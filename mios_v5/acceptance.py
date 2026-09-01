"""MIOS V6 — Stage 42 Acceptance / Rejection / Trap (the timing engine).

Every other engine answers *where* the market is likely to go. This one answers
**when the probability has shifted enough to act** — by watching what happens
*after* price reaches an institutional level.

Price touching a level means nothing. **The reaction is the signal.**

    TOUCH → BREAK → (did volume/CVD/flow/OI/dealers follow it through?)
                      ├─ yes → ACCEPTANCE → CONFIRMED BREAKOUT/BREAKDOWN
                      └─ no  → price returns → FAILED BREAK → TRAP → entry

The distinction that makes this worth its own engine: it is the only read that is
**inherently temporal**. Everything else describes a snapshot; this compares
*now* against the moment the level broke. That reference point is why a fake
breakout is detectable at all — you cannot see "the move didn't follow through"
without remembering what follow-through was supposed to look like.

It calculates NOTHING of its own — no S/R, no CVD, no dealer bias. It consumes
finished engine output and answers one question: **after price reached an
important level, who actually won?**

States: TOUCH · WATCHING · BREAK · ACCEPTANCE · REJECTION · ABSORPTION ·
BULL_TRAP · BEAR_TRAP · SWEEP_BUY · SWEEP_SELL · CONFIRMED_BREAKOUT ·
CONFIRMED_BREAKDOWN · FAILED_BREAKOUT · FAILED_BREAKDOWN · IDLE.

Pure module — plain numbers in, verdict out — so the thresholds are testable and
tunable from logged reactions rather than by feel.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ── geometry ────────────────────────────────────────────────────────────
_AT_PCT = 0.12        # within this % of the level → "at" it (~28 pts on NIFTY)
# Past the level by this % → genuinely through. Sized for NIFTY: 0.02% ≈ 5 pts,
# so a 23,700 resistance is "broken" at 23,705 — which is how a trader reads it.
# 0.05% (~12 pts) was too wide and silently swallowed real breaks.
_BEYOND_PCT = 0.02
# A sweep is a SINGLE-bar spike that immediately reverses. Allowing two cycles
# misclassified genuine multi-cycle failed breakouts as stop-hunts.
_SWEEP_MAX_CYCLES = 1

# ── follow-through thresholds ───────────────────────────────────────────
_VOL_EXPAND = 1.15    # volume must be this × the break-moment volume
_ABSORB_VOL = 1.5     # heavy volume …
_ABSORB_MOVE = 0.06   # … with less than this % progress = absorption

#: each confirmation check and what it's worth
_CHECK_WEIGHT = {
    "volume_expanded": 1.0,
    "cvd_continued": 1.3,
    "mf_continued": 1.0,
    "oi_unwound": 1.1,
    "dealers_flipped": 1.1,
    "price_held": 1.5,
}

#: verdicts that are final — the battle is over, the trap/sweep already happened
_STICKY = ("BULL_TRAP", "BEAR_TRAP", "SWEEP_BUY", "SWEEP_SELL")
#: a confirmed break is only confirmed WHILE price holds the level. The moment it
#: loses it, the verdict must be re-opened — a "confirmed" breakout that reverses
#: is precisely what a bull trap IS, so this may never be treated as final.
_REVOCABLE = ("CONFIRMED_BREAKOUT", "CONFIRMED_BREAKDOWN")
_TERMINAL = _STICKY + _REVOCABLE

_LABEL = {
    "IDLE": "—", "TOUCH": "👆 Touch", "WATCHING": "👀 Watching",
    "BREAK": "🚪 Break — unconfirmed", "ACCEPTANCE": "✅ Acceptance",
    "REJECTION": "🛡 Rejection", "ABSORPTION": "🧱 Absorption",
    "BULL_TRAP": "🪤 BULL TRAP", "BEAR_TRAP": "🪤 BEAR TRAP",
    "SWEEP_BUY": "⚡ Buy-side Sweep", "SWEEP_SELL": "⚡ Sell-side Sweep",
    "CONFIRMED_BREAKOUT": "🚀 Confirmed Breakout",
    "CONFIRMED_BREAKDOWN": "🔻 Confirmed Breakdown",
    "FAILED_BREAKOUT": "⚠️ Failed Breakout",
    "FAILED_BREAKDOWN": "⚠️ Failed Breakdown",
}


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def label_for(state: Optional[str]) -> str:
    return _LABEL.get(str(state or ""), "—")


def is_actionable(state: Optional[str]) -> bool:
    """States where the battle has actually resolved and a trade is implied."""
    return str(state or "") in _TERMINAL


def _checks(up: bool, cur: Dict[str, Any], ref: Dict[str, Any],
            beyond: bool) -> Dict[str, Optional[bool]]:
    """The six follow-through questions, measured against the BREAK moment.

    `up` = the break was upward (through a resistance). A None answer means the
    input is missing — unknown is never scored as agreement.
    """
    out: Dict[str, Optional[bool]] = {}

    v, vref = _f(cur.get("volume")), _f(ref.get("volume"))
    out["volume_expanded"] = (v >= vref * _VOL_EXPAND) if (v and vref) else None

    c, cref = _f(cur.get("cvd_pct")), _f(ref.get("cvd_pct"))
    out["cvd_continued"] = ((c >= cref) if up else (c <= cref)) \
        if (c is not None and cref is not None) else None

    m, mref = _f(cur.get("mf_net")), _f(ref.get("mf_net"))
    out["mf_continued"] = ((m >= mref) if up else (m <= mref)) \
        if (m is not None and mref is not None) else None

    # through a resistance, CALL writers capitulating (CE OI falling) confirms;
    # through a support it's the PUT side that must give way
    oi = _f(cur.get("oi_ce_chg")) if up else _f(cur.get("oi_pe_chg"))
    out["oi_unwound"] = (oi < 0) if oi is not None else None

    d = str(cur.get("dealer_dir") or "").lower()
    out["dealers_flipped"] = (d == ("bull" if up else "bear")) if d else None

    out["price_held"] = bool(beyond)
    return out


def _score(checks: Dict[str, Optional[bool]]) -> Dict[str, Any]:
    got = sum(_CHECK_WEIGHT[k] for k, v in checks.items() if v is True)
    known = sum(_CHECK_WEIGHT[k] for k, v in checks.items() if v is not None)
    pct = (got / known * 100.0) if known else 0.0
    return {"passed": got, "known": known, "pct": round(pct),
            "n_pass": sum(1 for v in checks.values() if v is True),
            "n_fail": sum(1 for v in checks.values() if v is False),
            "n_unknown": sum(1 for v in checks.values() if v is None)}


def evaluate_reaction(zone: Optional[Dict[str, Any]], spot: Optional[float],
                      metrics: Optional[Dict[str, Any]] = None,
                      prev: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Advance the reaction state machine for ONE level.

    zone    — {side: SUPPORT|RESISTANCE, price, strength, lifecycle}
    spot    — current price
    metrics — finished reads from other engines: volume · cvd_pct · mf_net ·
              oi_ce_chg · oi_pe_chg · dealer_dir
    prev    — this level's memory from last cycle (returned as `memory`)

    Returns {state, label, confidence, side, action, winner, checks, reasons,
    memory, actionable}.
    """
    z = zone or {}
    cur = dict(metrics or {})
    p = dict(prev or {})
    price, s = _f(z.get("price")), _f(spot)
    side = str(z.get("side") or "").upper()
    if price is None or s is None or side not in ("SUPPORT", "RESISTANCE"):
        return {"state": "IDLE", "label": _LABEL["IDLE"], "confidence": 0,
                "side": side or None, "action": None, "winner": None,
                "checks": {}, "reasons": [], "memory": p, "actionable": False}

    up_break = (side == "RESISTANCE")     # breaking a resistance is an UP move
    dist_pct = (s - price) / price * 100.0
    at_zone = abs(dist_pct) <= _AT_PCT
    beyond = (dist_pct > _BEYOND_PCT) if up_break else (dist_pct < -_BEYOND_PCT)
    back_inside = not beyond

    state = p.get("state") or "IDLE"
    cycles_beyond = int(p.get("cycles_beyond") or 0)
    ref = dict(p.get("ref_metrics") or {})
    max_beyond = _f(p.get("max_beyond")) or 0.0
    reasons: List[str] = []

    # ── a resolved verdict stays put until price leaves the level's orbit.
    # ONLY traps/sweeps short-circuit here. A CONFIRMED break must keep flowing
    # through so its bookkeeping (cycles beyond, max excursion) stays live and it
    # can be revoked the moment price loses the level — that revocation is the
    # trap. Early-returning on it froze the counters and made a genuine failed
    # break look like a shallow sweep.
    if state in _STICKY and (at_zone or beyond):
        return {**_render(state, p.get("confidence", 0), side,
                          p.get("checks") or {}, p.get("reasons") or []),
                "memory": p}

    if not at_zone and not beyond:
        # price has left — reset, the reaction is over
        return {"state": "IDLE", "label": _LABEL["IDLE"], "confidence": 0,
                "side": side, "action": None, "winner": None, "checks": {},
                "reasons": [], "actionable": False,
                "memory": {"state": "IDLE", "cycles_beyond": 0,
                           "ref_metrics": {}, "touch_metrics": {},
                           "max_beyond": 0.0}}

    touch_ref = dict(p.get("touch_metrics") or {})
    # ── first contact — capture the arrival baseline. Absorption is measured
    # against THIS (volume rising while price stalls), not against a break that
    # may never happen.
    entered_touch_now = False
    if state in ("IDLE", "") and at_zone and not beyond:
        state = "TOUCH"
        touch_ref = dict(cur)
        entered_touch_now = True
        reasons.append(f"Price reached {side.title()} ₹{price:,.0f}")

    # ── the break: capture the reference the follow-through is judged against ──
    if beyond:
        cycles_beyond += 1
        max_beyond = max(max_beyond, abs(dist_pct))
        if state in ("IDLE", "TOUCH", "WATCHING", "REJECTION", ""):
            state = "BREAK"
            ref = dict(cur)          # the moment of the break IS the baseline
            reasons.append(f"Broke {side.lower()} ₹{price:,.0f} "
                           f"({dist_pct:+.2f}%)")
    elif at_zone and state == "TOUCH" and not entered_touch_now:
        # only after a full cycle has passed — TOUCH must be observable, not a
        # state the machine skips through on the same tick it enters it
        state = "WATCHING"

    checks = _checks(up_break, cur, ref, beyond) if ref else {}
    sc = _score(checks) if checks else {"pct": 0, "n_pass": 0, "n_fail": 0}

    # ── absorption: heavy volume at the level with no progress ──
    v, vref = _f(cur.get("volume")), _f(touch_ref.get("volume"))
    if state in ("TOUCH", "WATCHING") and v and vref and vref > 0:
        if v >= vref * _ABSORB_VOL and abs(dist_pct) < _ABSORB_MOVE:
            state = "ABSORPTION"
            reasons.append("Heavy volume, no progress — someone is absorbing")

    # ── resolution while beyond the level ──
    # Never on the break cycle itself: the reference IS this cycle's data, so
    # "did CVD continue?" would compare a value to itself and pass trivially.
    # Follow-through needs elapsed time — judge from the second cycle beyond.
    if beyond and state in ("BREAK", "ACCEPTANCE") and cycles_beyond >= 2:
        if sc["pct"] >= 70 and sc["n_pass"] >= 4:
            state = ("CONFIRMED_BREAKOUT" if up_break else "CONFIRMED_BREAKDOWN") \
                if cycles_beyond >= 3 else "ACCEPTANCE"
            reasons.append("Follow-through confirmed "
                           f"({sc['n_pass']}/{len(checks)} checks)")
        elif sc["pct"] < 40:
            reasons.append("Break not supported by flow — fake-break risk")

    # ── the reversal: price came back inside after having been through ──
    if back_inside and cycles_beyond > 0 and state in (
            "BREAK", "ACCEPTANCE", "CONFIRMED_BREAKOUT", "CONFIRMED_BREAKDOWN"):
        if cycles_beyond <= _SWEEP_MAX_CYCLES and max_beyond < 0.25:
            # in and out fast, shallow → stop-hunt, not a real attempt
            state = "SWEEP_BUY" if up_break else "SWEEP_SELL"
            reasons.append(f"Spiked {max_beyond:.2f}% beyond and returned in "
                           f"{cycles_beyond} cycle(s) — liquidity grab")
        else:
            state = "FAILED_BREAKOUT" if up_break else "FAILED_BREAKDOWN"
            reasons.append(f"Returned back inside after {cycles_beyond} "
                           f"cycles beyond — breakout failed")
        cycles_beyond = 0

    # ── trap confirmation: a failed break plus flow actually reversing ──
    if state in ("FAILED_BREAKOUT", "FAILED_BREAKDOWN"):
        rev = _reversal_evidence(up_break, cur, ref)
        reasons.extend(rev["reasons"])
        if rev["score"] >= 60:
            state = "BULL_TRAP" if up_break else "BEAR_TRAP"
            reasons.append("Flow reversed — trap confirmed")

    # ── a probe that never really got through ──
    if at_zone and state == "WATCHING" and cycles_beyond == 0 and ref:
        if sc["pct"] < 35:
            state = "REJECTION"
            reasons.append("Probed and pushed back — level defended")

    confidence = _confidence(state, sc, checks, cur, ref, up_break)
    memory = {"state": state, "cycles_beyond": cycles_beyond,
              "ref_metrics": ref, "touch_metrics": touch_ref,
              "max_beyond": round(max_beyond, 3),
              "confidence": confidence, "checks": checks, "reasons": reasons}
    return {**_render(state, confidence, side, checks, reasons), "memory": memory}


def _reversal_evidence(up_break: bool, cur: Dict[str, Any],
                       ref: Dict[str, Any]) -> Dict[str, Any]:
    """After a failed break, did the flow that drove it actually reverse?
    A failed break with flow still supporting it is a pullback, not a trap."""
    got = total = 0.0
    reasons: List[str] = []
    c, cref = _f(cur.get("cvd_pct")), _f(ref.get("cvd_pct"))
    if c is not None and cref is not None:
        total += 1.3
        if (c < cref) if up_break else (c > cref):
            got += 1.3
            reasons.append("✓ CVD reversed")
    m, mref = _f(cur.get("mf_net")), _f(ref.get("mf_net"))
    if m is not None and mref is not None:
        total += 1.0
        if (m < mref) if up_break else (m > mref):
            got += 1.0
            reasons.append("✓ Money flow reversed")
    # writers coming BACK is the defenders re-taking the level
    oi = _f(cur.get("oi_ce_chg")) if up_break else _f(cur.get("oi_pe_chg"))
    if oi is not None:
        total += 1.1
        if oi > 0:
            got += 1.1
            reasons.append("✓ " + ("Call" if up_break else "Put") + " writing increased")
    d = str(cur.get("dealer_dir") or "").lower()
    if d:
        total += 1.1
        if d == ("bear" if up_break else "bull"):
            got += 1.1
            reasons.append("✓ Dealers on the other side")
    v, vref = _f(cur.get("volume")), _f(ref.get("volume"))
    if v and vref:
        total += 1.0
        if v < vref:
            got += 1.0
            reasons.append("✓ Volume faded")
    return {"score": round(got / total * 100) if total else 0, "reasons": reasons}


def _confidence(state: str, sc: Dict[str, Any], checks: Dict[str, Optional[bool]],
                cur: Dict[str, Any], ref: Dict[str, Any], up: bool) -> int:
    if state in ("IDLE", "TOUCH"):
        return 0
    if state in ("WATCHING", "BREAK"):
        return int(min(60, sc.get("pct", 0)))
    if state in ("ACCEPTANCE", "CONFIRMED_BREAKOUT", "CONFIRMED_BREAKDOWN"):
        return int(min(97, 55 + sc.get("pct", 0) * 0.42))
    if state in ("FAILED_BREAKOUT", "FAILED_BREAKDOWN", "BULL_TRAP", "BEAR_TRAP"):
        rev = _reversal_evidence(up, cur, ref)["score"]
        base = 55 if state.startswith("FAILED") else 70
        return int(min(97, base + rev * 0.3))
    if state in ("SWEEP_BUY", "SWEEP_SELL"):
        return 70
    if state == "REJECTION":
        return int(min(90, 55 + (100 - sc.get("pct", 0)) * 0.3))
    if state == "ABSORPTION":
        return 65
    return 0


def _render(state: str, confidence: Any, side: str,
            checks: Dict[str, Optional[bool]], reasons: List[str]) -> Dict[str, Any]:
    """Attach the human-facing verdict: who won, and what it implies."""
    winner = action = None
    if state in ("CONFIRMED_BREAKOUT", "ACCEPTANCE") and side == "RESISTANCE":
        winner, action = "Buyers", "ENTER CALL"
    elif state in ("CONFIRMED_BREAKDOWN", "ACCEPTANCE") and side == "SUPPORT":
        winner, action = "Sellers", "ENTER PUT"
    elif state in ("BULL_TRAP", "FAILED_BREAKOUT"):
        winner = "Sellers"
        action = "ENTER PUT" if state == "BULL_TRAP" else None
    elif state in ("BEAR_TRAP", "FAILED_BREAKDOWN"):
        winner = "Buyers"
        action = "ENTER CALL" if state == "BEAR_TRAP" else None
    elif state == "REJECTION":
        winner = "Sellers" if side == "RESISTANCE" else "Buyers"
    elif state == "SWEEP_BUY":
        winner = "Sellers"
    elif state == "SWEEP_SELL":
        winner = "Buyers"
    return {"state": state, "label": _LABEL.get(state, state),
            "confidence": int(confidence or 0), "side": side,
            "action": action, "winner": winner, "checks": checks,
            "reasons": reasons, "actionable": is_actionable(state)}
