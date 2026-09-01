"""Stage 71.8 — Premium Strike Selection, S/R & Strike Validation.

Answers one question: **is the premium the trader wants to trade actually a
good premium?**

It does not answer *CALL or PUT* — Stage 71.7 answered that, and this stage
reads the answer rather than re-deriving it. It does not answer *enter now* —
that is Stage 72. Advisory only, and it never says buy, sell, enter or exit.

```
71.7   which side has energy?          → Preferred Premium
71.8   is this strike worth trading?   → Overall Strike Score  ← here
72     can I enter now?                → not built
```

## The trader picks the strike; this stage grades it

`selected` is a **parameter**, and where it disagrees with what the chain is
actually trading, that disagreement is **reported, never corrected**. The stage
has no mechanism to switch a strike and is not permitted one: a validator that
silently moves the thing it is validating is not a validator.

`most_traded_agreement` is the whole of that report — `Agree` when the trader is
on the busiest strike, `Partially Agree` within one step of it, `Disagree`
beyond. A selected strike can be perfectly reasonable and still disagree; the
number that matters is liquidity, and it is measured separately.

## Eleven checks, one score

Each check is `AGREE · PARTIAL · DISAGREE`, or `UNKNOWN` when its producer was
silent. **Unknown checks are excluded from the score, never counted as zero** —
Stage 63's rule. A strike graded on three reporting checks says so, and carries
the count, rather than presenting a thin read as a full one.

## What it must never do

No BUY · SELL · ENTER · EXIT — asserted by tests, not documented. No mutators,
absent from `ALL_ENGINES`, `advisory_only` throughout: the Stage 70 standing
that the whole Stage 71 stack holds.

## Named absences

Per-strike **Greeks-based validation** and **Premium VPFR** are listed in the
spec and have no per-strike producer in the reduced app; **Stage 72** does not
exist. All are named in `MISSING_INPUTS` rather than scored as zero, because an
unmeasured fact is not a zero and a zero looks like an answer.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import premium_energy as PE

#: Inputs and consumers the spec names that no producer publishes yet.
MISSING_INPUTS: Tuple[str, ...] = (
    "per_strike_greeks_validation",   # chain carries greeks; no validator owns them
    "premium_vpfr",                   # ATM±1 only — wing strikes have no profile
    "entry_engine",                   # Stage 72 — not built
)

ADVISORY_ONLY = True

AGREE, PARTIAL, DISAGREE, UNKNOWN = "Agree", "Partially Agree", "Disagree", "UNKNOWN"

#: agreement → the fraction of a check's weight it earns.
_CREDIT = {AGREE: 1.0, PARTIAL: 0.5, DISAGREE: 0.0}

VALID, WEAK, INVALID = "VALID", "WEAK", "INVALID"

#: score → stars. `Avoid` is not the bottom band — it is a separate verdict a
#: hard failure produces regardless of score (see `_stars`).
_STAR_BANDS: Tuple[Tuple[float, str], ...] = (
    (80.0, "★★★★★"), (65.0, "★★★★☆"), (50.0, "★★★☆☆"),
    (35.0, "★★☆☆☆"), (20.0, "★☆☆☆☆"),
)
AVOID = "Avoid"

#: The eleven checks and what each is worth.
#:
#: Liquidity leads because it is the only one that can make a correct read
#: untradeable: a premium nobody is quoting cannot be exited at the price the
#: screen shows, and every other check is an opinion about a fill you may not
#: get. Premium health is second — it is Stage 71.7's whole finding, carried in.
WEIGHTS: Dict[str, float] = {
    "premium_liquidity": 2.5,
    "premium_health": 2.0,
    "premium_sr_strength": 1.5,
    "most_traded_agreement": 1.5,
    "dealer_agreement": 1.5,
    "premium_behaviour": 1.0,
    "acceptance_agreement": 1.0,
    "htf_agreement": 1.0,
    "reaction_zone_agreement": 1.0,
    "absorption_agreement": 1.0,
}

#: Checks whose DISAGREE is disqualifying rather than merely costly. Both are
#: about being able to trade the thing at all, not about whether it will work.
_HARD = ("premium_liquidity",)


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _check(state: str, why: str, source: str,
           value: Any = None) -> Dict[str, Any]:
    """One check. Always carries why it reads the way it does, and who said so.

    A bare `Disagree` is an accusation without evidence; every check names the
    producer behind it so a trader can go and look."""
    return {"state": state, "why": why, "source": source, "value": value}


def _unknown(what: str, source: str) -> Dict[str, Any]:
    return _check(UNKNOWN, f"{what} did not report", source)


# ══════════════════════════════════════════════════════════════════════
#  the chain — most traded, liquidity
# ══════════════════════════════════════════════════════════════════════

def strikes_from_chain(rows: Optional[Iterable[Dict[str, Any]]]
                       ) -> List[Dict[str, Any]]:
    """The option chain's per-strike volume, OI and quoted depth.

    `df_summary` is a DataFrame in the app and a list of dicts here, because
    this module may not depend on pandas any more than it may reach into
    session_state. The caller converts.

    A row without a readable strike is skipped rather than defaulted — a strike
    of `0` would sort to the front of every ladder.
    """
    out: List[Dict[str, Any]] = []
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        strike = _f(row.get("Strike") or row.get("strike"))
        if strike is None:
            continue
        out.append({
            "strike": strike,
            "CALL": {
                "volume": _f(row.get("totalTradedVolume_CE")),
                "oi": _f(row.get("openInterest_CE") or row.get("CE_OI")),
                "doi": _f(row.get("changeinOpenInterest_CE")),
                "bid_qty": _f(row.get("bidQty_CE")),
                "ask_qty": _f(row.get("askQty_CE")),
            },
            "PUT": {
                "volume": _f(row.get("totalTradedVolume_PE")),
                "oi": _f(row.get("openInterest_PE") or row.get("PE_OI")),
                "doi": _f(row.get("changeinOpenInterest_PE")),
                "bid_qty": _f(row.get("bidQty_PE")),
                "ask_qty": _f(row.get("askQty_PE")),
            },
        })
    out.sort(key=lambda r: r["strike"])
    return out


def most_traded(ladder: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """The busiest strike per side, by **volume**, falling back to OI.

    Volume and OI answer different questions and the difference matters here:
    OI is what is *held*, volume is what is being *traded today*. A strike can
    carry enormous OI from a position opened last week and trade nothing this
    morning, and it is this morning's liquidity a trader needs. So volume leads,
    and when the chain does not publish it the fallback is **labelled**, not
    silently substituted.
    """
    out: Dict[str, Any] = {"CALL": None, "PUT": None,
                           "source": None, "by_side": {}}
    if not ladder:
        return out
    for side in ("CALL", "PUT"):
        best_vol = max(
            (r for r in ladder if _f((r[side] or {}).get("volume"))),
            key=lambda r: _f(r[side]["volume"]) or 0.0, default=None)
        if best_vol is not None and (_f(best_vol[side]["volume"]) or 0) > 0:
            out[side] = best_vol["strike"]
            out["by_side"][side] = {"strike": best_vol["strike"],
                                    "basis": "volume",
                                    "value": _f(best_vol[side]["volume"])}
            continue
        best_oi = max(
            (r for r in ladder if _f((r[side] or {}).get("oi"))),
            key=lambda r: _f(r[side]["oi"]) or 0.0, default=None)
        if best_oi is not None and (_f(best_oi[side]["oi"]) or 0) > 0:
            out[side] = best_oi["strike"]
            out["by_side"][side] = {"strike": best_oi["strike"],
                                    "basis": "open interest",
                                    "value": _f(best_oi[side]["oi"])}
    bases = {v.get("basis") for v in out["by_side"].values()}
    out["source"] = ("volume" if bases == {"volume"} else
                     "open interest" if bases == {"open interest"} else
                     "mixed" if bases else None)
    return out


def _row_for(ladder: Optional[List[Dict[str, Any]]],
             strike: Optional[float]) -> Optional[Dict[str, Any]]:
    if strike is None or not ladder:
        return None
    s = _f(strike)
    return next((r for r in ladder if abs(r["strike"] - s) < 0.5), None)


def _step(ladder: Optional[List[Dict[str, Any]]]) -> Optional[float]:
    """The ladder's own strike interval, measured rather than assumed 50."""
    if not ladder or len(ladder) < 2:
        return None
    gaps = [b["strike"] - a["strike"] for a, b in zip(ladder, ladder[1:])
            if b["strike"] > a["strike"]]
    return min(gaps) if gaps else None


# ══════════════════════════════════════════════════════════════════════
#  the eleven checks
# ══════════════════════════════════════════════════════════════════════

def _liquidity(row: Optional[Dict[str, Any]], side: str,
               ladder: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Can this premium actually be traded?

    Measured **relative to the ladder**, not against a fixed threshold: what
    counts as thin depends on the expiry, the day and the underlying, and a
    hardcoded lot count would be wrong on all three. The selected strike's share
    of the busiest strike's volume is the reading.
    """
    if row is None:
        return _unknown("the option chain", "Stage 12 chain")
    node = row.get(side) or {}
    vol, oi = _f(node.get("volume")), _f(node.get("oi"))
    if vol is None and oi is None:
        return _unknown(f"{side} volume and OI", "Stage 12 chain")

    peak = 0.0
    basis = "volume"
    if vol is not None:
        peak = max((_f((r[side] or {}).get("volume")) or 0.0)
                   for r in (ladder or [row]))
        mine = vol
    else:
        basis = "open interest"
        peak = max((_f((r[side] or {}).get("oi")) or 0.0)
                   for r in (ladder or [row]))
        mine = oi or 0.0
    if peak <= 0:
        return _unknown(f"{side} {basis}", "Stage 12 chain")

    share = 100.0 * mine / peak
    if share >= 25:
        state, word = AGREE, "liquid"
    elif share >= 8:
        state, word = PARTIAL, "thin"
    else:
        state, word = DISAGREE, "illiquid"
    return _check(state,
                  f"{share:.0f}% of the busiest {side} strike's {basis} — {word}",
                  "Stage 12 chain", round(share, 1))


def _most_traded_agreement(selected: Optional[float], busiest: Optional[float],
                           step: Optional[float],
                           detail: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Agree · Partially Agree · Disagree. **Never a correction.**

    Within one strike step is `Partially Agree` rather than `Disagree`, because
    the adjacent strike is routinely the right choice for delta reasons and
    calling that a disagreement would train a trader to ignore the check.
    """
    if selected is None:
        return _unknown("no strike selected", "trader selection")
    if busiest is None:
        return _unknown("the chain's busiest strike", "Stage 12 chain")
    gap = abs(selected - busiest)
    basis = (detail or {}).get("basis") or "volume"
    if gap < 0.5:
        return _check(AGREE, f"this is the busiest {basis} strike",
                      "Stage 12 chain", 0)
    if step and gap <= step + 0.5:
        return _check(PARTIAL,
                      f"one strike from the busiest by {basis} "
                      f"({busiest:.0f})", "Stage 12 chain", gap)
    steps = f"{gap / step:.0f} strikes" if step else f"{gap:.0f} points"
    return _check(DISAGREE,
                  f"{steps} from the busiest by {basis} ({busiest:.0f}) — "
                  f"the trader's choice stands, this is the report",
                  "Stage 12 chain", gap)


def _health(premium: Dict[str, Any], side: str) -> Dict[str, Any]:
    """Stage 71.7's finding for this side, carried in and never re-derived."""
    node = ((premium or {}).get("sides") or {}).get(side) or {}
    energy = _f(node.get("energy"))
    if energy is None:
        return _unknown("Stage 71.7 premium energy", "Stage 71.7")
    band = node.get("strength") or PE.energy_band(energy)
    shift = ((premium or {}).get("shift") or {}).get(side) or {}
    state = shift.get("state")
    if energy >= 55:
        agree = AGREE
    elif energy >= 30:
        agree = PARTIAL
    else:
        agree = DISAGREE
    tail = "" if not state or state == PE.SHIFT_UNKNOWN else f", {state.lower()}"
    return _check(agree, f"{band.lower()} energy {energy:.0f}{tail}",
                  "Stage 71.7", energy)


def _sr_strength(leg: Optional[Dict[str, Any]], side: str) -> Dict[str, Any]:
    """The selected leg's premium structure, from `premium_structure.analyse`.

    This stage used to read `sr["state"]` and grade it here. That made two
    modules owners of "what is this premium's structure doing" — Premium
    Structure exists precisely so there is one, so 71.8 now **converts** its
    finished score into an agreement rather than deriving one.

    The conversion is the whole of this function: score and confidence in,
    `Agree · Partially Agree · Disagree` out. No premium fact is computed.
    """
    st = (leg or {}).get("structure") or {}
    score = _f(st.get("structure_score"))
    if score is None:
        return _unknown("premium structure", "Premium Structure")
    conf = str(st.get("confidence") or "")
    reasons = [r.get("label") for r in (st.get("top_reasons") or [])[:2]]
    why = f"structure {score:.0f}/100 ({conf.lower()} confidence)"
    if reasons:
        why += " — " + " · ".join(str(r) for r in reasons if r)

    # LOW confidence means the structure was barely measured. A strong score on
    # two components is not a strong structure, so it cannot read `Agree`.
    if conf == "LOW":
        return _check(PARTIAL, why + " — too little measured to confirm",
                      "Premium Structure", score)
    if score >= 65:
        state = AGREE
    elif score >= 40:
        state = PARTIAL
    else:
        state = DISAGREE
    return _check(state, why, "Premium Structure", score)


def _behaviour(premium: Dict[str, Any], side: str) -> Dict[str, Any]:
    """Stage 50's classification for this side, read through Stage 71.7."""
    beh = (((premium or {}).get("sides") or {}).get(side) or {}).get("behaviour") or {}
    state = str(beh.get("state") or "")
    if not state:
        return _unknown("Stage 50 premium behaviour", "Stage 50")
    good = {"building": AGREE, "squeeze": AGREE,
            "distribution": DISAGREE, "unwinding": DISAGREE}.get(state, PARTIAL)
    return _check(good, beh.get("label") or state, "Stage 50", state)


def _dealer(fr: Dict[str, Any], side: str, strike: Optional[float],
            spot: Optional[float]) -> Dict[str, Any]:
    """Is this strike on the side of the dealer levels this premium needs?

    A CALL wants spot above the wall and the gamma flip; a PUT wants it below.
    The **charm pin** is read separately and always counts against, whichever
    side: a strike pinned to expiry is one dealers are defending, and defending
    it means neither premium runs.
    """
    lv = fr.get("dealer_levels") or {}
    wall, flip = _f(lv.get("dealer_wall")), _f(lv.get("gamma_flip"))
    s = _f(spot)
    if s is None or (wall is None and flip is None):
        return _unknown("Stage 11 dealer levels", "Stage 11")
    votes: List[bool] = []
    notes: List[str] = []
    for name, level in (("wall", wall), ("gamma flip", flip)):
        if level is None:
            continue
        ok = (s > level) if side == "CALL" else (s < level)
        votes.append(ok)
        notes.append(f"spot {'above' if s > level else 'below'} {name} "
                     f"{level:.0f}")
    if not votes:
        return _unknown("Stage 11 dealer levels", "Stage 11")

    pinned = False
    pin = _f((fr.get("charm_pin") or {}).get("pin"))
    if pin is not None and strike is not None and abs(strike - pin) < 0.5:
        pinned = True
        notes.append(f"pinned at {pin:.0f}")

    if pinned:
        return _check(DISAGREE, " · ".join(notes) + " — dealers defend a pin",
                      "Stage 11", pin)
    if all(votes):
        return _check(AGREE, " · ".join(notes), "Stage 11")
    if any(votes):
        return _check(PARTIAL, " · ".join(notes), "Stage 11")
    return _check(DISAGREE, " · ".join(notes), "Stage 11")


def _directional(fr: Dict[str, Any], side: str, key: str, source: str,
                 bias_of) -> Dict[str, Any]:
    """The shared shape of the four bias checks — HTF · reaction · acceptance ·
    absorption. Each asks the same question of a different engine: does what
    this engine sees point the way this premium needs?

    Written once because four near-identical blocks would drift, and a drifted
    copy is how `Agree` starts meaning something different in two rows of the
    same table.
    """
    got = bias_of(fr)
    if got is None:
        return _unknown(source, source)
    want = "bull" if side == "CALL" else "bear"
    lean, why = got
    if lean is None:
        return _check(PARTIAL, f"{why} — no direction", source, lean)
    return _check(AGREE if lean == want else DISAGREE, why, source, lean)


def _htf_bias(fr: Dict[str, Any]):
    align = ((fr.get("htf") or {}).get("alignment") or {})
    b = str(align.get("bias") or "").upper()
    score = _f(align.get("score"))
    if not b and score is None:
        return None
    lean = "bull" if b == "BULL" else "bear" if b == "BEAR" else None
    tail = "" if score is None else f" ({score:.0f}% aligned)"
    return lean, f"HTF {b.title() or 'flat'}{tail}"


def _reaction_bias(fr: Dict[str, Any]):
    rz = fr.get("reaction_zone") or fr.get("zone") or {}
    lean_raw = str(rz.get("bias") or rz.get("direction") or "").upper()
    label = rz.get("label") or rz.get("state")
    if not lean_raw and not label:
        return None
    lean = ("bull" if lean_raw.startswith("BULL") else
            "bear" if lean_raw.startswith("BEAR") else None)
    return lean, f"reaction zone {label or lean_raw or '—'}"


#: Stage 42 states and the premium each one favours. A confirmed breakdown and
#: a bull trap both favour PUT premium — one by continuation, one by reversal.
_ACCEPT_LEAN = {
    "CONFIRMED_BREAKOUT": "bull", "ACCEPTANCE": "bull", "BREAK": "bull",
    "SWEEP_BUY": "bull", "BEAR_TRAP": "bull", "FAILED_BREAKDOWN": "bull",
    "CONFIRMED_BREAKDOWN": "bear", "REJECTION": "bear", "SWEEP_SELL": "bear",
    "BULL_TRAP": "bear", "FAILED_BREAKOUT": "bear",
}


def _acceptance_bias(fr: Dict[str, Any]):
    state = str((fr.get("reaction") or {}).get("state") or "").upper()
    if not state or state in ("IDLE", ""):
        return None
    return _ACCEPT_LEAN.get(state), f"Stage 42 {state.replace('_', ' ').title()}"


def _absorption_bias(fr: Dict[str, Any]):
    ab = fr.get("absorption") or {}
    beh = str(ab.get("behaviour") or "").upper()
    if not beh or beh in ("NONE", "—"):
        return None
    lean = ("bull" if "BUY" in beh or "ACCUM" in beh else
            "bear" if "SELL" in beh or "DISTRIB" in beh else None)
    return lean, f"Stage 43 {beh.title()}"


# ══════════════════════════════════════════════════════════════════════
#  scoring
# ══════════════════════════════════════════════════════════════════════

def _score(checks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Weighted mean over the checks that **reported**.

    Unknown checks leave the denominator rather than scoring zero. A strike
    graded on three of ten checks is not a bad strike, it is a barely-measured
    one, and the two must not render as the same number — so `reporting` travels
    with the score everywhere it goes.
    """
    got = 0.0
    total = 0.0
    reporting: List[str] = []
    for key, weight in WEIGHTS.items():
        state = (checks.get(key) or {}).get("state")
        if state not in _CREDIT:
            continue
        reporting.append(key)
        got += weight * _CREDIT[state]
        total += weight
    if not total:
        return {"score": None, "reporting": 0, "of": len(WEIGHTS),
                "reason": "no check reported"}
    return {"score": round(_clamp(100.0 * got / total)),
            "reporting": len(reporting), "of": len(WEIGHTS),
            "reported": reporting,
            "reason": f"{len(reporting)} of {len(WEIGHTS)} checks reporting"}


def _stars(score: Optional[float], checks: Dict[str, Dict[str, Any]],
           reporting: int) -> Dict[str, Any]:
    """Five stars down to one, or `Avoid`.

    `Avoid` is a verdict, not the bottom band. Three things produce it and none
    of them is a low score on its own:

    * a **hard check** disagreeing — an illiquid premium cannot be rescued by
      ten agreeing opinions about direction;
    * **fewer than three checks reporting** — there is not enough here to grade,
      and a confident star rating on two inputs is the failure this whole stack
      is built to avoid;
    * a score below the lowest band.
    """
    for key in _HARD:
        if (checks.get(key) or {}).get("state") == DISAGREE:
            return {"stars": AVOID, "reason": (checks[key] or {}).get("why"),
                    "hard_fail": key}
    if reporting < 3:
        return {"stars": AVOID,
                "reason": f"only {reporting} check(s) reported — not enough to "
                          f"grade this strike",
                "hard_fail": None}
    if score is None:
        return {"stars": AVOID, "reason": "nothing scored", "hard_fail": None}
    for cut, glyph in _STAR_BANDS:
        if score >= cut:
            return {"stars": glyph, "reason": f"score {score:.0f}",
                    "hard_fail": None}
    return {"stars": AVOID, "reason": f"score {score:.0f} — below every band",
            "hard_fail": None}


def _validation(score: Optional[float], stars: Dict[str, Any]) -> str:
    """`VALID · WEAK · INVALID` — the word, where the score is the number."""
    if stars.get("stars") == AVOID:
        return INVALID
    if score is None:
        return UNKNOWN
    return VALID if score >= 65 else WEAK if score >= 40 else INVALID


def _side_report(side: str, fr: Dict[str, Any], premium: Dict[str, Any],
                 ladder: List[Dict[str, Any]], selected: Optional[float],
                 leg: Optional[Dict[str, Any]], busiest: Dict[str, Any],
                 spot: Optional[float]) -> Dict[str, Any]:
    """One side's ten checks, its score and the structure behind them."""
    row = _row_for(ladder, selected)
    step = _step(ladder)
    checks = {
        "premium_liquidity": _liquidity(row, side, ladder),
        "premium_health": _health(premium, side),
        "premium_sr_strength": _sr_strength(leg, side),
        "most_traded_agreement": _most_traded_agreement(
            selected, busiest.get(side), step,
            (busiest.get("by_side") or {}).get(side)),
        "dealer_agreement": _dealer(fr, side, selected, spot),
        "premium_behaviour": _behaviour(premium, side),
        "acceptance_agreement": _directional(fr, side, "acceptance",
                                             "Stage 42", _acceptance_bias),
        "htf_agreement": _directional(fr, side, "htf", "Stage 45", _htf_bias),
        "reaction_zone_agreement": _directional(fr, side, "reaction_zone",
                                                "Stage 35", _reaction_bias),
        "absorption_agreement": _directional(fr, side, "absorption",
                                             "Stage 43", _absorption_bias),
    }
    scored = _score(checks)
    stars = _stars(scored.get("score"), checks, scored.get("reporting", 0))
    node = ((premium or {}).get("sides") or {}).get(side) or {}
    return {
        "side": side,
        "strike": selected,
        "checks": checks,
        "overall_strike_score": scored.get("score"),
        "reporting": scored.get("reporting", 0),
        "of": scored.get("of", len(WEIGHTS)),
        "score_reason": scored.get("reason"),
        "stars": stars.get("stars"),
        "stars_reason": stars.get("reason"),
        "hard_fail": stars.get("hard_fail"),
        "premium_validation": _validation(scored.get("score"), stars),
        # carried from 71.7 so the panel need not read two objects
        "energy": node.get("energy"),
        "spike": node.get("spike"),
        # carried, not copied: the panel renders Premium Structure's own read
        # rather than this stage re-describing it in a second vocabulary
        "structure": (leg or {}).get("structure") or {},
        "liquidity_share": (checks["premium_liquidity"] or {}).get("value"),
        "advisory_only": ADVISORY_ONLY,
    }


def _headline(sides: Dict[str, Dict[str, Any]],
              premium: Dict[str, Any]) -> str:
    """One line, and it is an observation about a strike — never an action.

    It deliberately does not name a trade even when both the preferred premium
    and its strike grade well. "Prefer CALL, and the 24250 CALL is a five-star
    strike" is the honest sentence; "buy the 24250 CALL" is Stage 72's, and
    Stage 72 does not exist yet.
    """
    pref = ((premium or {}).get("preferred") or {}).get("side")
    if pref and pref in sides:
        row = sides[pref]
        if row.get("stars") == AVOID:
            return (f"⚠ Stage 71.7 prefers {pref}, but the selected "
                    f"{pref} strike does not validate — {row.get('stars_reason')}.")
        return (f"{row.get('stars')} the {row['strike']:.0f} {pref} validates "
                f"at {row.get('overall_strike_score')}/100 "
                f"({row.get('reporting')}/{row.get('of')} checks).")
    graded = [r for r in sides.values() if r.get("overall_strike_score") is not None]
    if not graded:
        return "⚪ No strike validated yet — the chain has not reported."
    best = max(graded, key=lambda r: r["overall_strike_score"])
    return (f"{best.get('stars')} the {best['strike']:.0f} {best['side']} is the "
            f"better-validated of the two at "
            f"{best.get('overall_strike_score')}/100.")


#: What Stage 72 (Entry) would consume. Published flat for the same reason
#: 71.7's bridge is: so whoever builds 72 reads one key per fact instead of
#: walking this module's internals and welding the two together.
BRIDGE_KEYS: Tuple[str, ...] = (
    "selected_strike", "overall_strike_score", "stars", "premium_validation",
    "most_traded_agreement", "premium_liquidity", "checks_reporting",
    "preferred_premium",
)


def _bridge(out: Dict[str, Any], premium: Dict[str, Any]) -> Dict[str, Any]:
    sides = out.get("sides") or {}
    def _per(fn):
        return {s: fn(sides.get(s) or {}) for s in ("CALL", "PUT")}
    return {
        "selected_strike": _per(lambda r: r.get("strike")),
        "overall_strike_score": _per(lambda r: r.get("overall_strike_score")),
        "stars": _per(lambda r: r.get("stars")),
        "premium_validation": _per(lambda r: r.get("premium_validation")),
        "most_traded_agreement": _per(
            lambda r: ((r.get("checks") or {})
                       .get("most_traded_agreement") or {}).get("state")),
        "premium_liquidity": _per(
            lambda r: ((r.get("checks") or {})
                       .get("premium_liquidity") or {}).get("state")),
        "checks_reporting": _per(lambda r: r.get("reporting")),
        # read from 71.7, never re-decided
        "preferred_premium": ((premium or {}).get("preferred") or {}).get("preferred"),
        "advisory_only": ADVISORY_ONLY,
        "missing_consumers": list(MISSING_INPUTS),
    }


def build(final_read: Optional[Dict[str, Any]] = None,
          premium: Optional[Dict[str, Any]] = None,
          chain_rows: Optional[Iterable[Dict[str, Any]]] = None,
          selected: Optional[Dict[str, Any]] = None,
          leg_reads: Optional[Dict[str, Dict[str, Any]]] = None,
          spot: Optional[float] = None) -> Dict[str, Any]:
    """Stage 71.8. Always a dict, never raises.

    `premium`    — Stage 71.7's output. Read, never recomputed.
    `chain_rows` — `df_summary` as a list of dicts (the caller converts).
    `selected`   — `{"CALL": 24250.0, "PUT": 24250.0}` — the trader's choice.
    `leg_reads`  — `{("CALL", 24250.0): {"structure": premium_structure.analyse(…)}}`.
    `spot`       — for the dealer-level comparisons.
    """
    fr = dict(final_read or {})
    pe = dict(premium or {})
    ladder = strikes_from_chain(chain_rows)
    busiest = most_traded(ladder)
    sel = dict(selected or {})
    legs = dict(leg_reads or {})
    s = _f(spot) if spot is not None else _f(fr.get("spot"))

    sides: Dict[str, Dict[str, Any]] = {}
    for side in ("CALL", "PUT"):
        strike = _f(sel.get(side))
        sides[side] = _side_report(
            side, fr, pe, ladder, strike,
            legs.get((side, strike)) or legs.get(f"{side}:{strike}"),
            busiest, s)

    out = {
        "stage": "71.8",
        "advisory_only": ADVISORY_ONLY,
        "ready": any(r.get("overall_strike_score") is not None
                     for r in sides.values()),
        "sides": sides,
        "call": sides["CALL"],
        "put": sides["PUT"],
        "selected": {k: _f(v) for k, v in sel.items()},
        "most_traded": busiest,
        "ladder_size": len(ladder),
        "weights": dict(WEIGHTS),
        "headline": _headline(sides, pe),
        "missing_inputs": list(MISSING_INPUTS),
    }
    out["bridge"] = _bridge(out, pe)
    return out
