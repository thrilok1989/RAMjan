"""MIOS — Level Acceptance / Rejection observation strip (context-only).

It answers one question the predictive breakout/rejection % cannot: **after price
interacted with a level, did the market ACCEPT the new area or REJECT it?** —
observed, not predicted.

## It computes no state machine of its own

The temporal follow-through logic already exists and is tested: `mios_v5.
acceptance.evaluate_reaction` (Stage 42). This module **reuses** it and does only
the three presentation jobs the trader asked for:

1. **Maps** that engine's rich verdict (TOUCH · WATCHING · BREAK · ACCEPTANCE ·
   REJECTION · ABSORPTION · TRAP · SWEEP · CONFIRMED/FAILED …) onto ONE compact
   six-word vocabulary — `TESTING`, `BREAK_ATTEMPT`, `ACCEPTED_ABOVE`,
   `ACCEPTED_BELOW`, `FAILED_BREAK_WAIT`, `REJECTED`.
2. **Runs it per level** across the full level set (dealer magnet, gamma flip,
   S/R, POC, VAH/VAL, OI walls …), each carrying its own memory. A level's
   "side" is inferred from spot: a price overhead acts as resistance, below as
   support — exactly how the level behaves.
3. **Clusters** levels sitting within tolerance into one *battle zone*, so four
   numbers a point apart read as one event, not four.

## Non-negotiables (mirrors the engine it wraps)

* `context_only` is always True. It emits no BUY/SELL, never feeds Guardian, and
  the predictive breakout/rejection % is untouched — this reports separately what
  price actually DID.
* **TESTING is not rejection**, and a break that fails is `FAILED_BREAK_WAIT`
  (never a premature "fakeout"/REJECTED) until the engine confirms the reversal.
* A metric that was not measured is dropped, never invented — the confirmation
  score is `passed / known`, so an unavailable check lowers neither.

Pure module: numbers/dicts in, dicts out. No pandas, no session, no I/O. The
reaction function is injected (default the real one) so the mapping and
clustering are testable without the heavy engine.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

#: the observed vocabulary — the ONLY states this strip ever shows.
TESTING = "TESTING"
BREAK_ATTEMPT = "BREAK_ATTEMPT"
ACCEPTED_ABOVE = "ACCEPTED_ABOVE"
ACCEPTED_BELOW = "ACCEPTED_BELOW"
FAILED_BREAK_WAIT = "FAILED_BREAK_WAIT"
REJECTED = "REJECTED"

#: within this many index points, two levels are the same battle zone. Matches
#: the ±5 the level-touch alerts already use, so the two agree on "at a level".
CLUSTER_TOLERANCE = 5.0

#: how close (index points) price must be to a level to be "interacting" with it
#: — the TESTING/contested band. Deliberately SEPARATE from CLUSTER_TOLERANCE:
#: this gates whether a level is shown as being tested at all, so a level ~28 pts
#: away (inside the reused engine's wider internal at-zone) is NOT called TESTING.
#: BREAK_ATTEMPT and the resolved states are NOT gated — once price is genuinely
#: beyond the level the existing break logic owns the read, wherever price sits.
INTERACTION_BAND = 5.0

#: the resolved outcomes — the only states worth a Telegram alert. TESTING /
#: BREAK_ATTEMPT / FAILED_BREAK_WAIT are in-progress and must NOT alert (they'd
#: spam and, worse, call a move before the market settled it).
RESOLVED = (ACCEPTED_ABOVE, ACCEPTED_BELOW, REJECTED)

#: a remembered level whose price moves more than this is a NEW level — its
#: reaction memory resets rather than carrying a stale reference point.
RESET_EPS = 3.0

#: how far the observed states have progressed — used to pick the headline state
#: of a battle zone (the most-resolved member wins the label).
_PRECEDENCE = {
    None: 0, TESTING: 1, BREAK_ATTEMPT: 2, FAILED_BREAK_WAIT: 3,
    ACCEPTED_ABOVE: 4, ACCEPTED_BELOW: 4, REJECTED: 4,
}

#: raw Stage-42 state → observed vocabulary. ACCEPTANCE resolves by side; the
#: FAILED/ABSORPTION family is the deliberate "wait" bucket so a failed break is
#: never called a rejection before the engine confirms the reversal.
_DIRECT = {
    "TOUCH": TESTING, "WATCHING": TESTING,
    "CONFIRMED_BREAKOUT": ACCEPTED_ABOVE, "CONFIRMED_BREAKDOWN": ACCEPTED_BELOW,
    "FAILED_BREAKOUT": FAILED_BREAK_WAIT, "FAILED_BREAKDOWN": FAILED_BREAK_WAIT,
    "ABSORPTION": FAILED_BREAK_WAIT,
    "REJECTION": REJECTED, "BULL_TRAP": REJECTED, "BEAR_TRAP": REJECTED,
    "SWEEP_BUY": REJECTED, "SWEEP_SELL": REJECTED,
}

#: Stage-42 confirmation keys → the short labels the strip shows, in display
#: order. Only these are surfaced; the engine owns what each means.
_CHECK_LABELS = [
    ("price_held", "Hold"),
    ("cvd_continued", "CVD"),
    ("volume_expanded", "Volume"),
    ("oi_unwound", "OI"),
    ("dealers_flipped", "Dealers"),
    ("mf_continued", "Flow"),
]


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def infer_side(level: Any, spot: Any) -> Optional[str]:
    """How the level currently acts: overhead → RESISTANCE, below → SUPPORT.

    This is what lets one engine judge a magnet, a POC or a gamma flip the same
    way it judges S/R — the level's role is just its position relative to price.
    Returns None when either number is unreadable.
    """
    lv, sp = _f(level), _f(spot)
    if lv is None or sp is None:
        return None
    return "SUPPORT" if lv <= sp else "RESISTANCE"


def map_observed(state: Any, side: Any) -> Dict[str, Optional[str]]:
    """Stage-42 state + side → one observed word and its direction.

    `IDLE`/unknown → `{"observed": None}` (the level is not being contested, so
    the strip omits it). Direction is `ABOVE`/`BELOW`/None.
    """
    s = str(state or "").upper()
    sd = str(side or "").upper()
    if s in ("", "IDLE"):
        return {"observed": None, "direction": None}
    if s == "BREAK":
        return {"observed": BREAK_ATTEMPT,
                "direction": "ABOVE" if sd == "RESISTANCE" else "BELOW"}
    if s == "ACCEPTANCE":
        return ({"observed": ACCEPTED_ABOVE, "direction": "ABOVE"}
                if sd == "RESISTANCE"
                else {"observed": ACCEPTED_BELOW, "direction": "BELOW"})
    observed = _DIRECT.get(s)
    if observed is None:
        return {"observed": None, "direction": None}
    direction = ("ABOVE" if observed in (ACCEPTED_ABOVE,) or s == "FAILED_BREAKOUT"
                 else "BELOW" if observed in (ACCEPTED_BELOW,) or s == "FAILED_BREAKDOWN"
                 else None)
    return {"observed": observed, "direction": direction}


def retest_status(prev_observed: Any, observed: Any) -> Dict[str, Any]:
    """Derive the retest read from the observed-state *transition* — reusing the
    engine's own return/reversal logic, computing nothing new.

    A retest is price coming back to a level it broke, to see if the level now
    holds (acceptance) or fails (rejection):

    * `REJECTED` → the break was pushed back at the level: **retest failed**.
    * was `FAILED_BREAK_WAIT`, now `ACCEPTED_*` → price dipped back and reclaimed:
      **retest passed**.
    * `FAILED_BREAK_WAIT` (and not yet resolved) → price returned inside but the
      outcome is still open: retest **underway** (never called pass/fail early).

    Returns `{detected, passed, failed, text}`; `detected` is False otherwise.
    """
    prev = str(prev_observed or "")
    cur = str(observed or "")
    accepted = (ACCEPTED_ABOVE, ACCEPTED_BELOW)
    if cur == REJECTED:
        return {"detected": True, "passed": False, "failed": True,
                "text": "Retest failed"}
    if cur in accepted and prev == FAILED_BREAK_WAIT:
        return {"detected": True, "passed": True, "failed": False,
                "text": "Retest held"}
    if cur == FAILED_BREAK_WAIT:
        return {"detected": True, "passed": False, "failed": False,
                "text": "Retest underway"}
    return {"detected": False, "passed": False, "failed": False, "text": None}


def _confirmations(checks: Mapping[str, Any]) -> Dict[str, Any]:
    """The confirmation checks that actually reported, as `{label: bool}`, plus
    `passed`/`known`. A check the engine could not evaluate (None) is dropped —
    an unavailable metric is never counted as a failure or invented as a pass."""
    shown: Dict[str, bool] = {}
    for key, label in _CHECK_LABELS:
        v = checks.get(key)
        if v is True or v is False:
            shown[label] = bool(v)
    passed = sum(1 for v in shown.values() if v)
    return {"checks": shown, "passed": passed, "known": len(shown)}


def observe_one(level: Mapping[str, Any], spot: Any, metrics: Mapping[str, Any],
                prev: Optional[Mapping[str, Any]],
                reaction_fn: Callable[..., Dict[str, Any]],
                reset_eps: float = RESET_EPS,
                interaction_band: float = INTERACTION_BAND,
                now: Any = None) -> Dict[str, Any]:
    """Advance ONE level's observed read by reusing the Stage-42 engine.

    `level` is `{label, price, [source]}`; `metrics` is the shared follow-through
    dict (cvd_pct, volume, mf_net, oi_ce_chg, oi_pe_chg, dealer_dir);
    `reaction_fn` is `acceptance.evaluate_reaction` (injected for tests). Returns
    the observation plus `memory` to carry forward. When the level's price has
    moved more than `reset_eps` from the remembered one, memory is dropped first
    — a new level starts its own reaction rather than inheriting a stale
    reference point.
    """
    price = _f(level.get("price"))
    label = str(level.get("label") or "level")
    sp = _f(spot)
    side = infer_side(price, sp)
    if price is None or sp is None or side is None:
        return {"label": label, "price": price, "observed": None,
                "direction": None, "checks": {}, "passed": 0, "known": 0,
                "confidence": 0, "raw_state": None, "side": side,
                "timestamp": None, "memory": dict(prev or {})}

    mem = dict(prev or {})
    remembered = _f(mem.get("_price"))
    reset = remembered is not None and abs(remembered - price) > reset_eps
    if reset:
        mem = {}                        # a new level — reset the reaction
    # the prior observed word (for the retest transition); a reset drops it too
    prev_observed = None if reset else (prev or {}).get("_observed")
    prev_ts = None if reset else (prev or {}).get("_ts")

    zone = {"side": side, "price": price,
            "strength": level.get("strength"), "lifecycle": level.get("lifecycle")}
    r = reaction_fn(zone, sp, dict(metrics or {}), mem or None) or {}
    new_mem = dict(r.get("memory") or {})
    new_mem["_price"] = price

    mapped = map_observed(r.get("state"), side)
    observed = mapped["observed"]
    # interaction band: a level is only TESTING when price is genuinely at it
    # (±interaction_band). Beyond that the engine's TOUCH is too wide, so the
    # level is not shown as tested. BREAK_ATTEMPT / resolved states are never
    # gated — price is meant to be away from the level once it has broken.
    if observed == TESTING and abs(sp - price) > interaction_band:
        observed = None
    new_mem["_observed"] = observed
    conf = _confirmations(r.get("checks") or {})
    retest = retest_status(prev_observed, observed)
    # edge trigger: a resolution the market just reached (not one it has been
    # sitting in). This is what an alert fires on — once, on the transition.
    newly_resolved = observed in RESOLVED and observed != prev_observed
    # timestamp of the CURRENT state — stamped when it last changed, carried
    # while it holds. Uses the market/session clock the caller passes in.
    changed = observed != prev_observed
    timestamp = now if (changed or prev_ts is None) else prev_ts
    new_mem["_ts"] = timestamp
    return {
        "label": label, "price": price, "side": side,
        "observed": observed, "direction": mapped["direction"],
        "checks": conf["checks"], "passed": conf["passed"], "known": conf["known"],
        "retest": retest, "newly_resolved": newly_resolved,
        "timestamp": timestamp,
        "confidence": int(_f(r.get("confidence")) or 0),
        "reasons": list(r.get("reasons") or [])[:3],
        "raw_state": r.get("state"),
        "memory": new_mem,
    }


def cluster(observations: Sequence[Mapping[str, Any]],
            tolerance: float = CLUSTER_TOLERANCE) -> List[Dict[str, Any]]:
    """Collapse observations whose prices sit within `tolerance` into battle
    zones. Each zone takes the price of its dealer-magnet member if present (the
    trader's anchor), else the mean, and the **most-resolved** member's observed
    state as the zone headline. Members are kept for the detail line.

    Levels not being contested (`observed is None`) still cluster so the zone's
    price/label reflect every nearby level, but a zone with no contested member
    reports `observed=None` and the strip omits it.
    """
    priced = [dict(o) for o in observations if _f(o.get("price")) is not None]
    priced.sort(key=lambda o: _f(o.get("price")))
    zones: List[Dict[str, Any]] = []
    for o in priced:
        p = _f(o.get("price"))
        if zones and (p - _f(zones[-1]["_max_price"])) <= tolerance:
            z = zones[-1]
            z["members"].append(o)
            z["_max_price"] = p
        else:
            zones.append({"members": [o], "_max_price": p})

    out: List[Dict[str, Any]] = []
    for z in zones:
        members = z["members"]
        magnet = next((m for m in members
                       if "magnet" in str(m.get("label", "")).lower()), None)
        price = (_f(magnet.get("price")) if magnet else
                 sum(_f(m["price"]) for m in members) / len(members))
        headline = max(members, key=lambda m: _PRECEDENCE.get(m.get("observed"), 0))
        is_zone = len(members) > 1
        out.append({
            "price": round(price, 1),
            "labels": [str(m.get("label")) for m in members],
            "is_battle_zone": is_zone,
            "observed": headline.get("observed"),
            "direction": headline.get("direction"),
            "checks": headline.get("checks", {}),
            "passed": headline.get("passed", 0),
            "known": headline.get("known", 0),
            "retest": headline.get("retest"),
            "newly_resolved": headline.get("newly_resolved", False),
            "timestamp": headline.get("timestamp"),
            "confidence": headline.get("confidence", 0),
            "members": members,
        })
    return out


#: word → (icon, phrasing) for the alert headline.
_ALERT_WORDS = {
    ACCEPTED_ABOVE: ("🟢", "ACCEPTED ABOVE"),
    ACCEPTED_BELOW: ("🟢", "ACCEPTED BELOW"),
    REJECTED: ("🔴", "REJECTED"),
}


def alert_text(zone: Mapping[str, Any]) -> Optional[str]:
    """The Telegram body for a resolved zone, or None if it is not a resolved
    state. Pure — the app owns *when* to send (edge + cooldown); this only words
    it. Reports what price DID; carries no BUY/SELL and no prediction.
    """
    observed = zone.get("observed")
    if observed not in RESOLVED:
        return None
    icon, word = _ALERT_WORDS.get(observed, ("⚔️", str(observed)))
    arrow = {"ABOVE": " ↑", "BELOW": " ↓"}.get(zone.get("direction") or "", "")
    price = _f(zone.get("price"))
    name = ("BATTLE ZONE" if zone.get("is_battle_zone")
            else (list(zone.get("labels") or ["level"]) or ["level"])[0])
    lines = [f"{icon} <b>₹{price:,.0f} · {word}{arrow}</b>",
             f"⚔️ Level {name.lower() if not zone.get('is_battle_zone') else 'battle zone'}"
             f" — {' · '.join(zone.get('labels') or [])}"]
    checks = zone.get("checks") or {}
    ck = [f"{lbl} {'✓' if ok else '✗'}" for lbl, ok in checks.items()]
    rt = zone.get("retest") or {}
    if rt.get("detected"):
        ck.append("Retest " + ("✓" if rt.get("passed")
                               else "✗" if rt.get("failed") else "…"))
    if ck:
        lines.append(" · ".join(ck)
                     + (f"  {zone.get('passed', 0)}/{zone.get('known', 0)}"
                        if checks else ""))
    lines.append("Observed, not predicted — context only.")
    return "\n".join(lines)


def observe_levels(levels: Sequence[Mapping[str, Any]], spot: Any,
                   metrics: Mapping[str, Any],
                   memory_store: Optional[Dict[str, Any]],
                   reaction_fn: Callable[..., Dict[str, Any]],
                   tolerance: float = CLUSTER_TOLERANCE,
                   interaction_band: float = INTERACTION_BAND,
                   now: Any = None) -> Dict[str, Any]:
    """The whole strip, context-only. Runs the reused engine over every level,
    updates `memory_store` in place (keyed by level label), clusters the results
    into battle zones, and returns `{zones, context_only}`.

    `memory_store` is the app's persistent dict (session state); each level's
    memory is read and written under its label so state survives reruns without
    this module owning any storage.
    """
    store = memory_store if memory_store is not None else {}
    obs: List[Dict[str, Any]] = []
    for lv in levels:
        label = str(lv.get("label") or "level")
        res = observe_one(lv, spot, metrics, store.get(label), reaction_fn,
                          reset_eps=RESET_EPS, interaction_band=interaction_band,
                          now=now)
        store[label] = res.pop("memory")
        obs.append(res)
    zones = [z for z in cluster(obs, tolerance) if z.get("observed") is not None]
    return {"zones": zones, "context_only": True}
