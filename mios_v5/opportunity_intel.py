"""MIOS Stage 71.5 — Trade Opportunity Intelligence.

Stage 71 says *which side, how strong, over what horizon*. This says **what
kind of trade it is** — and every field is read off an engine that already
computed it. No new analytics, no registration, `advisory_only` throughout.

## The rule that governs every field here

Nine derived labels sit on top of a five-producer sample. A screen reading
*Quality A+ · Risk LOW · Timing NOW* projects far more certainty than that
sample supports, so the discipline from Stage 63 applies to all of it:

> **three states, not two** — a value, or `UNKNOWN` with the reason. Never a
> default.

`Risk: —  (dealer, session and acceptance all silent)` is honest.
`Risk: LOW` computed from nothing is not, and it is the more dangerous of the
two because it looks like an answer. Every classifier here returns
`(value, source)` or `(UNKNOWN, why)`, and the panel renders the why.

## Quality reuses Decision v0's bands, deliberately

`decision.py::_grade` is `A+ >= 4.5 · A >= 3.8 · B >= 3.0 · C`. Two "Quality
A" badges on one screen that mean different things is the same class of defect
as two engines computing CVD differently — so the thresholds are imported in
spirit, not re-picked. `AVOID` is added below C for vetoed or unreadable rows;
`B+` is deliberately not added, because a band v0 cannot express would make the
two vocabularies diverge on the first screenshot someone compares.

## Lifetime is a modulated band, never a forecast

The horizon already carries an honest base (`HOLD[scalp] == "5-15 min"`). This
narrows or widens that band from energy, session position and stability — and
says which. It never emits a free-floating "20-40 min", because that number
would be a prediction wearing an estimate's clothes, and nothing in this system
is allowed to predict.

## Rotation needs the previous cycle

`previous` is a PARAMETER — the caller holds the last matrix. This module stays
pure, and rotation degrades to UNKNOWN on the first cycle rather than inventing
a transition that was never observed.

Pure module: reads in, labels out. No IO, no Streamlit, no pandas, no state.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .horizon_owner import HOLD, Horizon, owners_of

UNKNOWN = "UNKNOWN"

# ── Opportunity types, and the engine state that names each ─────────────
#: Stage 42's reaction state → the trade it describes. Executed evidence, so
#: it outranks every other classifier below.
_TYPE_FROM_REACTION = {
    "CONFIRMED_BREAKOUT": ("BREAKOUT", "Stage 42 confirmed breakout"),
    "CONFIRMED_BREAKDOWN": ("BREAKDOWN", "Stage 42 confirmed breakdown"),
    "ACCEPTANCE": ("TREND_CONTINUATION", "Stage 42 acceptance beyond the level"),
    "REJECTION": ("REVERSAL", "Stage 42 rejection at the level"),
    "ABSORPTION": ("ABSORPTION_BOUNCE", "Stage 42 absorption at the level"),
    "BULL_TRAP": ("REVERSAL", "Stage 42 bull trap"),
    "BEAR_TRAP": ("REVERSAL", "Stage 42 bear trap"),
    "SWEEP_BUY": ("LIQUIDITY_SWEEP", "Stage 42 buy-side sweep"),
    "SWEEP_SELL": ("LIQUIDITY_SWEEP", "Stage 42 sell-side sweep"),
}

#: Stage 48's market state → the trade it describes, when no reaction fired
_TYPE_FROM_STATE = {
    "TREND_UP": ("MOMENTUM", "Stage 48 trend up"),
    "TREND_DOWN": ("MOMENTUM", "Stage 48 trend down"),
    "MARK_UP": ("MOMENTUM", "Stage 48 mark up"),
    "MARK_DOWN": ("MOMENTUM", "Stage 48 mark down"),
    "PULLBACK": ("PULLBACK", "Stage 48 pullback"),
    "ACCUMULATION": ("ACCUMULATION_LONG", "Stage 48 accumulation"),
    "DISTRIBUTION": ("DISTRIBUTION_SHORT", "Stage 48 distribution"),
    "RANGE": ("RANGE_FADE", "Stage 48 range"),
    "ROTATION": ("MEAN_REVERSION", "Stage 48 rotation"),
    "COMPRESSION": ("NO_OPPORTUNITY", "Stage 48 compression — no edge yet"),
    "EXPANSION": ("MOMENTUM", "Stage 48 expansion"),
    "EXHAUSTION": ("REVERSAL", "Stage 48 exhaustion"),
    "REVERSAL_BUILDING": ("REVERSAL", "Stage 48 reversal building"),
    "TRAP_ACTIVE": ("REVERSAL", "Stage 48 trap active"),
    "WAR_ZONE": ("NO_OPPORTUNITY", "Stage 48 war zone — both sides committed"),
}

#: types that carry their own direction. A row whose side opposes one of these
#: is taking the trade AGAINST the named structure, and saying so matters: a
#: CALL row labelled plainly "Breakdown" reads as a contradiction, and a trader
#: cannot tell whether the label or the side is the mistake.
_TYPE_DIRECTION = {"BREAKOUT": 1, "ACCUMULATION_LONG": 1,
                   "BREAKDOWN": -1, "DISTRIBUTION_SHORT": -1}

TYPE_LABEL = {
    "MOMENTUM": "Momentum", "PULLBACK": "Pullback", "BREAKOUT": "Breakout",
    "BREAKDOWN": "Breakdown", "TREND_CONTINUATION": "Trend Continuation",
    "REVERSAL": "Reversal", "MEAN_REVERSION": "Mean Reversion",
    "LIQUIDITY_SWEEP": "Liquidity Sweep",
    "ABSORPTION_BOUNCE": "Absorption Bounce", "RANGE_FADE": "Range Fade",
    "EXPIRY_PIN": "Expiry Pin", "DEALER_MOVE": "Dealer Move",
    "DISTRIBUTION_SHORT": "Distribution Short",
    "ACCUMULATION_LONG": "Accumulation Long",
    "NO_OPPORTUNITY": "No Opportunity", UNKNOWN: "—",
}

# ── Quality: Decision v0's bands, not new ones ──────────────────────────
_GRADE_BANDS = ((4.5, "A+"), (3.8, "A"), (3.0, "B"), (0.0, "C"))

#: quality components → the stage that scores each, 1-5
_QUALITY_COMPONENTS = (
    ("validity", 51, "Stage 51 gatekeeper"),
    ("reaction", 42, "Stage 42 reaction"),
    ("absorption", 43, "Stage 43 footprint"),
    ("htf", 45, "Stage 45 higher timeframes"),
    ("state", 48, "Stage 48 market state"),
    ("day", 68, "Stage 68 day type"),
    ("session", 69, "Stage 69 session"),
    ("flow", 44, "Stage 44 flow stability"),
)

_RISK_BANDS = ((75.0, "EXTREME"), (55.0, "HIGH"), (30.0, "MEDIUM"), (0.0, "LOW"))

MATURITY = ("FRESH", "DEVELOPING", "MATURE", "EXHAUSTED")
TIMING = ("NOW", "PREPARE", "WAIT", "LATE", "MISSED")


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _stars(pct: Optional[float]) -> str:
    if pct is None:
        return "—"
    n = max(0, min(5, int(round(pct / 20.0))))
    return "★" * n + "☆" * (5 - n)


def _up(v) -> str:
    return str(v or "").upper().replace(" ", "_").replace("-", "_")


# ══════════════════════════════════════════════════════════════════════
#  1 · Opportunity type
# ══════════════════════════════════════════════════════════════════════

def opportunity_type(fr: Dict[str, Any]) -> Dict[str, Any]:
    """What KIND of trade this is — executed evidence first.

    Stage 42 wins where it has fired, because a confirmed breakdown is a thing
    that happened; Stage 48's state is a description of the tape. Same tier
    rule the whole system is built on.

    **Market-level by construction.** Every branch reads `fr` alone: a Reversal
    is a property of the tape, not of a holding period, so all five horizons
    share one type. This used to take a `Horizon` it never referenced, which
    implied a per-horizon read that was not happening — the parameter is gone
    rather than left to mislead. The Type column repeating down the table is
    therefore correct, not a bug; `MARKET_LEVEL_FIELDS` records it.
    """
    dc = _up((fr.get("day_classification") or {}).get("type"))
    # Two day types are facts rather than votes (Stage 68's own rule), and both
    # describe the trade more precisely than any state read would.
    if dc == "EXPIRY_PIN":
        return _typed("EXPIRY_PIN", "Stage 68 expiry pin day")

    rs = _up((fr.get("reaction") or {}).get("state"))
    if rs in _TYPE_FROM_REACTION:
        t, why = _TYPE_FROM_REACTION[rs]
        return _typed(t, why)

    ms = _up((fr.get("market_state") or {}).get("state"))
    if ms in _TYPE_FROM_STATE:
        t, why = _TYPE_FROM_STATE[ms]
        return _typed(t, why)

    # dealer positioning is the last resort — it describes who is moving it,
    # not what the move is, so it only names a type when nothing else did
    dealer = (fr.get("sections") or {}).get("dealer") or {}
    if str(dealer.get("bias") or "NONE").upper() not in ("NONE", "NEUTRAL"):
        return _typed("DEALER_MOVE", "Stage 11 dealer positioning")

    return _typed(UNKNOWN, "no reaction, market state or dealer read available")


#: Fields that are one market read shown on every horizon row. Repetition down
#: the table is correct for these — a Reversal is a property of the tape, not of
#: a holding period. Recorded so "all five rows say the same thing" can be
#: checked against intent instead of assumed to be a bug.
MARKET_LEVEL_FIELDS = ("type",)


def _typed(t: str, source: str) -> Dict[str, Any]:
    return {"type": t, "label": TYPE_LABEL.get(t, t), "source": source,
            "known": t != UNKNOWN}


# ══════════════════════════════════════════════════════════════════════
#  2 · Quality — graded, with the components visible
# ══════════════════════════════════════════════════════════════════════

def quality(fr: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    """A+ / A / B / C / AVOID over the components that reported.

    Unknown components are EXCLUDED from the average, never scored 0 — a
    silent engine is not a bad one, and averaging it in as zero would grade a
    thin read as a bad read. Below `_MIN_KNOWN` components the grade itself is
    UNKNOWN.
    """
    scored: List[Dict[str, Any]] = []
    for key, stage, label in _QUALITY_COMPONENTS:
        val = _component_score(fr, key)
        scored.append({"key": key, "stage": stage, "label": label,
                       "score": val, "stars": _stars(None if val is None
                                                     else val * 20.0)})
    known = [c for c in scored if c["score"] is not None]

    if row.get("veto"):
        return {"grade": "AVOID", "avg": 0.0, "components": scored,
                "known": len(known), "reason": "flow-shift veto on this horizon"}
    if len(known) < 3:
        return {"grade": UNKNOWN, "avg": None, "components": scored,
                "known": len(known),
                "reason": f"only {len(known)} of {len(_QUALITY_COMPONENTS)} "
                          f"quality components reported"}

    avg = sum(c["score"] for c in known) / len(known)
    grade = next(g for cut, g in _GRADE_BANDS if avg >= cut)
    return {"grade": grade, "avg": round(avg, 2), "components": scored,
            "known": len(known),
            "reason": f"{len(known)} components averaged {avg:.2f}"}


def _component_score(fr: Dict[str, Any], key: str) -> Optional[float]:
    """One quality component, 1-5, or None when its engine did not report."""
    if key == "validity":
        v = fr.get("validity") or {}
        pct = _f(v.get("pct"))
        return None if pct is None else 1.0 + 4.0 * min(1.0, pct / 100.0)
    if key == "reaction":
        rc = fr.get("reaction") or {}
        if not rc.get("state"):
            return None
        conf = _f(rc.get("confidence"))
        return None if conf is None else 1.0 + 4.0 * min(1.0, conf / 100.0)
    if key == "absorption":
        ab = fr.get("absorption") or {}
        if not ab.get("behaviour") or ab.get("behaviour") == "NONE":
            return None
        conf = _f(ab.get("confidence")) or 0.0
        return 1.0 + 4.0 * min(1.0, conf / 100.0)
    if key == "htf":
        al = (fr.get("htf") or {}).get("alignment") or {}
        sc = _f(al.get("score"))
        return None if sc is None else 1.0 + 4.0 * min(1.0, sc / 100.0)
    if key == "state":
        ms = fr.get("market_state") or {}
        conf = _f(ms.get("confidence"))
        return None if conf is None else 1.0 + 4.0 * min(1.0, conf / 100.0)
    if key == "day":
        dc = fr.get("day_classification") or {}
        conf = _f(dc.get("confidence"))
        if conf is None:
            return None
        # a choppy or low-participation day caps quality however confident
        if _up(dc.get("type")) in ("CHOPPY", "LOW_PARTICIPATION"):
            return 1.5
        return 1.0 + 4.0 * min(1.0, conf / 100.0)
    if key == "session":
        si = fr.get("session_intel") or {}
        if not si.get("session"):
            return None
        return 1.5 if _up(si.get("session")) == "CLOSED" else 4.0
    if key == "flow":
        fs = fr.get("flow_shift") or {}
        stab = _up(fr.get("stability"))
        if not stab and not fs:
            return None
        if fs.get("freeze_entries"):
            return 1.0
        return {"STABLE": 5.0, "RECOVERY": 3.0,
                "UNSTABLE": 2.0, "SHOCK": 1.0}.get(stab, 3.0)
    return None


# ══════════════════════════════════════════════════════════════════════
#  3 · Lifetime — the horizon's own band, narrowed or widened
# ══════════════════════════════════════════════════════════════════════

def lifetime(fr: Dict[str, Any], h: Horizon) -> Dict[str, Any]:
    """Expected hold, as a MODULATION of the horizon's base band.

    Never a free-floating number. The base is what the horizon means; this
    only says whether conditions shorten or extend it, and why.
    """
    base = HOLD[h]
    notes, adj = [], "as expected"

    en = fr.get("energy_read") or {}
    rel = _f(en.get("release_probability"))
    if rel is not None and rel >= 65:
        adj = "shorter"
        notes.append(f"Stage 37 release probability {rel:.0f}% — moves fast")
    elif _up(en.get("state")) == "COMPRESSION":
        adj = "longer"
        notes.append("Stage 37 compression — slower to resolve")

    si = fr.get("session_intel") or {}
    rem = _f(si.get("minutes_remaining"))
    if rem is not None and h in (Horizon.SCALP, Horizon.MIDDAY, Horizon.INTRADAY):
        if rem <= 30:
            adj = "shorter"
            notes.append(f"Stage 69 — {rem:.0f} min left in the session")

    if (fr.get("flow_shift") or {}).get("freeze_entries"):
        adj = "shorter"
        notes.append("Stage 44 flow shift — the tape changed under it")

    return {"base": base, "adjustment": adj, "notes": notes,
            "label": base if adj == "as expected" else f"{base} ({adj})"}


# ══════════════════════════════════════════════════════════════════════
#  4 · Risk
# ══════════════════════════════════════════════════════════════════════

def risk(fr: Dict[str, Any], h: Horizon) -> Dict[str, Any]:
    """LOW / MEDIUM / HIGH / EXTREME, with every driver named."""
    drivers: List[str] = []
    score, known = 0.0, 0

    fs = fr.get("flow_shift") or {}
    stab = _up(fr.get("stability"))
    if fs or stab:
        known += 1
        if fs.get("freeze_entries"):
            # 55, not 40: a freeze is the single most severe signal in the
            # system — it hard-vetoes the fast horizons elsewhere. It must
            # reach HIGH on its own, or a frozen tape could read MEDIUM
            # whenever nothing else happened to be elevated.
            score += 55
            drivers.append("Stage 44 flow shift — tape repriced")
        elif stab in ("UNSTABLE", "SHOCK"):
            score += 25
            drivers.append(f"Stage 44 {stab.lower()}")
        elif stab == "RECOVERY":
            score += 12
            drivers.append("Stage 44 still settling")

    dc = fr.get("day_classification") or {}
    if dc.get("type"):
        known += 1
        dt = _up(dc["type"])
        if dt in ("CHOPPY", "HIGH_VOLATILITY"):
            score += 25
            drivers.append(f"Stage 68 {dc.get('label', dt)}")
        elif dt in ("NEWS_EVENT",):
            score += 20
            drivers.append("Stage 68 news-event day")
        elif dt == "LOW_PARTICIPATION":
            score += 15
            drivers.append("Stage 68 low participation — thin book")
        elif dt == "EXPIRY_PIN" and h in (Horizon.POSITIONAL, Horizon.SWING):
            score += 20
            drivers.append("Stage 68 expiry pin — poor fit for a slow horizon")

    rc = fr.get("reaction") or {}
    if rc.get("state"):
        known += 1
        if _up(rc["state"]) in ("BULL_TRAP", "BEAR_TRAP"):
            score += 25
            drivers.append("Stage 42 trap active")
        elif _up(rc["state"]) in ("WATCHING", "TOUCH", "BREAK"):
            score += 12
            drivers.append("Stage 42 level unresolved")

    en = fr.get("energy_read") or {}
    if en.get("state"):
        known += 1
        if _f(en.get("breakout_risk")) and _f(en["breakout_risk"]) >= 65:
            score += 15
            drivers.append(f"Stage 37 breakout risk {_f(en['breakout_risk']):.0f}%")

    v = fr.get("validity") or {}
    if v.get("verdict"):
        known += 1
        if not v.get("valid"):
            score += 20
            drivers.append(f"Stage 51 {v.get('verdict')}")

    if known < 2:
        return {"level": UNKNOWN, "score": None, "drivers": [],
                "reason": f"only {known} risk inputs reported"}

    level = next(l for cut, l in _RISK_BANDS if score >= cut)
    return {"level": level, "score": round(min(100.0, score), 1),
            "drivers": drivers, "known": known,
            "reason": "no elevated risk driver reported" if not drivers else ""}


# ══════════════════════════════════════════════════════════════════════
#  5 · Maturity
# ══════════════════════════════════════════════════════════════════════

def maturity(fr: Dict[str, Any]) -> Dict[str, Any]:
    """FRESH → DEVELOPING → MATURE → EXHAUSTED, from Stages 54/47/48."""
    mem = fr.get("memory_read") or {}
    tr = fr.get("transition") or {}
    ms = _up((fr.get("market_state") or {}).get("state"))
    held = _f(mem.get("state_duration_min"))
    tstate = _up(tr.get("state"))

    if ms in ("EXHAUSTION", "REVERSAL_BUILDING") or tstate == "REVERSING":
        return _mat("EXHAUSTED", "Stage 48 exhaustion / Stage 47 reversing")
    if tstate == "WEAKENING":
        return _mat("MATURE", "Stage 47 weakening — the move is late")
    if mem.get("state_fresh") or (held is not None and held <= 5):
        return _mat("FRESH", f"Stage 54 state {held:.0f} min old"
                    if held is not None else "Stage 54 state is fresh")
    if mem.get("state_mature"):
        return _mat("MATURE", f"Stage 54 state held {held:.0f} min"
                    if held is not None else "Stage 54 state is mature")
    if held is not None:
        return _mat("DEVELOPING", f"Stage 54 state held {held:.0f} min")
    return _mat(UNKNOWN, "Stage 54 reported no state duration")


def _mat(v: str, why: str) -> Dict[str, Any]:
    return {"maturity": v, "source": why, "known": v != UNKNOWN}


# ══════════════════════════════════════════════════════════════════════
#  6 · Rotation — needs the previous cycle
# ══════════════════════════════════════════════════════════════════════

def rotation(row: Dict[str, Any],
             previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Is the energy staying on this side, moving to the other, or leaving?

    UNKNOWN on the first cycle — a transition that was never observed is not
    a transition.
    """
    now = row.get("side")
    if previous is None:
        return {"rotation": UNKNOWN, "label": "—",
                "source": "no previous cycle to compare"}
    prev_row = next((r for r in (previous.get("rows") or [])
                     if r.get("horizon") == row.get("horizon")), None)
    if prev_row is None:
        return {"rotation": UNKNOWN, "label": "—",
                "source": "horizon absent from the previous matrix"}
    was = prev_row.get("side")

    if was and now and was == now:
        # The label carries the SIDES; the panel prefixes an arrow for the KIND
        # (`_ROTATION_ARROW["CONTINUATION"] = "→"`). Returning "CALL → CALL" made
        # the row read "→ CALL → CALL" — the arrow printed twice, and nothing
        # having rotated dressed up as a movement. One side, once.
        return {"rotation": "CONTINUATION", "label": f"{now}",
                "source": "same side as the previous cycle"}
    if was and now and was != now:
        return {"rotation": "ROTATION", "label": f"{was} → {now}",
                "source": "side flipped since the previous cycle"}
    if was and not now:
        return {"rotation": "FADING", "label": f"{was} → none",
                "source": "the side that led last cycle has gone"}
    if now and not was:
        return {"rotation": "BUILDING", "label": f"none → {now}",
                "source": "a side has appeared where there was none"}
    return {"rotation": "NONE", "label": "—", "source": "no side either cycle"}


# ══════════════════════════════════════════════════════════════════════
#  7 · Timing
# ══════════════════════════════════════════════════════════════════════

#: Stage 42 fires on a 1-5 minute timescale. It is a real entry trigger for
#: the fast horizons and NOT one for the slow ones — a confirmed breakdown is
#: not the moment to open a multi-week structural position. Without this scope
#: every row inherits the scalp's trigger and swing reads NOW off a one-minute
#: event, which is the horizon leakage the registry exists to prevent.
_REACTION_TRIGGERS = (Horizon.SCALP, Horizon.MIDDAY, Horizon.INTRADAY)


def timing(fr: Dict[str, Any], row: Dict[str, Any],
           mat: Dict[str, Any]) -> Dict[str, Any]:
    """NOW / PREPARE / WAIT / LATE / MISSED, scoped to the horizon.

    Fast horizons are triggered by Stage 42's reaction at a level. Slow ones
    are triggered by higher-timeframe alignment, because that is the timescale
    they actually trade.
    """
    if row.get("veto"):
        return _tm("WAIT", "flow-shift veto — the tape changed")
    if not row.get("side") and "bias" not in row:
        return _tm("WAIT", "no directional read on this horizon")

    h = Horizon(row["horizon"])
    m = mat.get("maturity")
    if h not in _REACTION_TRIGGERS:
        return _slow_timing(fr, m)
    rs = _up((fr.get("reaction") or {}).get("state"))
    v = fr.get("validity") or {}

    # Exhaustion overrides even a fired reaction: a breakout printing into an
    # exhausted move is the trap case, not the entry.
    if m == "EXHAUSTED":
        return _tm("MISSED", "Stage 48/47 — the move is exhausted")

    # A FIRED reaction outranks state maturity. Timing is about the entry
    # trigger, and Stage 42 is executed evidence while maturity is derived —
    # the same tier rule the rest of the system runs on. A confirmed breakdown
    # inside a 40-minute downtrend is a continuation entry happening NOW; that
    # it is late-cycle belongs in `weakness`, not in the timing verdict.
    if rs in ("CONFIRMED_BREAKOUT", "CONFIRMED_BREAKDOWN", "ACCEPTANCE",
              "REJECTION", "SWEEP_BUY", "SWEEP_SELL"):
        if v.get("verdict") and not v.get("valid"):
            return _tm("PREPARE", f"reaction fired but Stage 51 says "
                                  f"{v.get('verdict')}")
        return _tm("NOW", f"Stage 42 {rs.replace('_', ' ').lower()} has fired")

    if m == "MATURE":
        return _tm("LATE", "Stage 47/54 — the move is late-cycle")
    if rs in ("TOUCH", "WATCHING", "BREAK"):
        return _tm("PREPARE", "Stage 42 at the level, unresolved")
    if m == "FRESH":
        return _tm("PREPARE", "Stage 54 — the state has just formed")
    return _tm("WAIT", "no reaction at a level yet")


def _slow_timing(fr: Dict[str, Any], m: Optional[str]) -> Dict[str, Any]:
    """Positional and swing: HTF alignment is the trigger, not a level touch.

    Stage 45 is the only read on these horizons' own timescale. A strong,
    agreeing higher-timeframe structure is the entry condition; a weak or
    contested one means wait, however lively the tape looks right now.
    """
    if m == "EXHAUSTED":
        return _tm("MISSED", "Stage 48/47 — the structure is exhausted")
    al = (fr.get("htf") or {}).get("alignment") or {}
    score = _f(al.get("score"))
    if score is None:
        return _tm("WAIT", "Stage 45 reported no higher-timeframe alignment")
    disagree = al.get("disagree") or []
    if score >= 70 and not disagree:
        if m == "MATURE":
            return _tm("LATE", f"Stage 45 aligned {score:.0f}% but the move "
                               f"is late-cycle")
        return _tm("NOW", f"Stage 45 higher timeframes aligned {score:.0f}%")
    if score >= 50:
        return _tm("PREPARE", f"Stage 45 alignment {score:.0f}%"
                   + (f" — {', '.join(disagree)} disagree" if disagree else ""))
    return _tm("WAIT", f"Stage 45 alignment only {score:.0f}%")


def _tm(v: str, why: str) -> Dict[str, Any]:
    return {"timing": v, "source": why}


# ══════════════════════════════════════════════════════════════════════
#  8 · Confidence breakdown — this horizon's OWN producers only
# ══════════════════════════════════════════════════════════════════════

def breakdown(row: Dict[str, Any], reads: Dict[str, Dict]) -> List[Dict]:
    """Per-producer stars for the horizon that OWNS them.

    Scoped to owned producers on purpose: showing Dealer on the scalp row
    would imply evidence scalp does not have, which is the cross-horizon
    leakage the registry exists to stop.
    """
    h = Horizon(row["horizon"])
    out = []
    for pid in owners_of(h):
        node = (reads or {}).get(pid)
        if not node:
            continue
        conf = _f(node.get("confidence"))
        out.append({"id": pid, "label": node.get("label") or pid,
                    "bias": node.get("bias"),
                    "confidence": conf, "stars": _stars(conf)})
    out.sort(key=lambda x: -(x["confidence"] or 0))
    return out


# ══════════════════════════════════════════════════════════════════════
#  9 · Weakness — how this trade fails
# ══════════════════════════════════════════════════════════════════════

def weakness(fr: Dict[str, Any], row: Dict[str, Any],
             q: Dict[str, Any], rk: Dict[str, Any],
             mat: Dict[str, Any]) -> List[str]:
    """Why it can fail — distinct from `lost_because`, which is why it did
    not win the ranking. A winning trade still has a way to lose."""
    out: List[str] = []
    for c in q.get("components", []):
        if c["score"] is not None and c["score"] <= 2.0:
            out.append(f"{c['label']} weak ({c['stars']})")
    out += list(rk.get("drivers") or [])
    if mat.get("maturity") in ("MATURE", "EXHAUSTED"):
        out.append(mat["source"])
    tr = fr.get("transition") or {}
    if _up(tr.get("state")) in ("WEAKENING", "REVERSING", "TRANSITION"):
        out.append(f"Stage 47 {tr.get('label') or tr.get('state')}")
    cal = (fr.get("calendar") or {}).get("next_event") or {}
    if cal.get("name") and (_f(cal.get("days_away")) or 9) <= 1:
        out.append(f"Stage 30 — {cal['name']} within a day")
    if row.get("coverage") is not None and row["coverage"] < 0.6:
        out.append(f"thin evidence — {row.get('evidence')}")
    # dedupe, order preserved
    seen, uniq = set(), []
    for w in out:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq


# ══════════════════════════════════════════════════════════════════════
#  The enrichment pass
# ══════════════════════════════════════════════════════════════════════

def enrich(matrix: Dict[str, Any], final_read: Optional[Dict[str, Any]] = None,
           reads: Optional[Dict[str, Dict]] = None,
           previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Add Stage 71.5 intelligence to a Stage 71 matrix, in place-safe form.

    Returns the same matrix shape with an `intel` block on every row plus a
    `best_trade`, `second_choice` and — when there is nothing worth taking —
    a `no_trade` explanation that says WHY rather than only "wait".
    """
    m = dict(matrix or {})
    fr = dict(final_read or {})
    rows = [dict(r) for r in (m.get("rows") or [])]

    for row in rows:
        h = Horizon(row["horizon"])
        mat = maturity(fr)
        q = quality(fr, row)
        rk = risk(fr, h)
        typ = _mark_counter_trend(opportunity_type(fr), row)
        row["intel"] = {
            "type": typ,
            "quality": q,
            "lifetime": lifetime(fr, h),
            "risk": rk,
            "maturity": mat,
            "rotation": rotation(row, previous),
            "timing": timing(fr, row, mat),
            "breakdown": breakdown(row, reads or {}),
            "weakness": weakness(fr, row, q, rk, mat),
            "advisory_only": True,
        }

    m["rows"] = rows
    by = {r["horizon"]: r for r in rows}
    ranked = m.get("ranked") or []

    m["best_trade"] = by.get(ranked[0]) if ranked else None
    m["second_choice"] = by.get(ranked[1]) if len(ranked) > 1 else None
    m["no_trade"] = None if ranked else _no_trade(fr, rows)
    # Stage 37's market energy, published so the panel can SHOW it. It was
    # already consumed here — silently, by `lifetime()` and `risk()` — while
    # the header cell labelled "Energy" was really the rotation read. Passing
    # it through costs nothing and stops the panel naming three different
    # things after the same word.
    m["energy"] = dict(fr.get("energy_read") or {})
    m["advisory_only"] = True
    return m


def _mark_counter_trend(typ: Dict[str, Any],
                        row: Dict[str, Any]) -> Dict[str, Any]:
    """Flag a row whose side opposes the structure its type names.

    The type is a MARKET fact — one confirmed breakdown, shared by every row.
    A horizon can still lean the other way, and rendering that row as plain
    "Breakdown / CALL" reads as a contradiction rather than as the counter-
    trend trade it is.
    """
    out = dict(typ)
    want = _TYPE_DIRECTION.get(out.get("type"))
    side = row.get("side") or ("CALL" if row.get("bias") in ("BULL",
                                                             "STRONG_BULL")
                               else "PUT" if row.get("bias") else None)
    if not want or not side:
        out["counter_trend"] = False
        return out
    have = 1 if side == "CALL" else -1
    if have != want:
        out["counter_trend"] = True
        out["label"] = f"Counter-trend ({out['label']})"
        out["source"] = (f"{out.get('source', '')} — this horizon leans "
                         f"{side}, against it")
    else:
        out["counter_trend"] = False
    return out


def _no_trade(fr: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Never just "WAIT". The reason a day has no trade is itself a read.

    Stage 67's rule, applied at the matrix level: what MIOS refused is half
    the report, and "the day was spent blocked on Acceptance" is a fact about
    the session that no bare WAIT can recover later.
    """
    reasons: List[str] = []
    for r in rows:
        for s in (r.get("lost_because") or [])[:1]:
            reasons.append(f"{r['horizon']}: {s}")

    dc = fr.get("day_classification") or {}
    if _up(dc.get("type")) in ("CHOPPY", "LOW_PARTICIPATION", "RANGE"):
        reasons.append(f"Stage 68 {dc.get('label')}")
    ms = _up((fr.get("market_state") or {}).get("state"))
    if ms == "COMPRESSION":
        reasons.append("Stage 48 compression — market coiled, no edge yet")
    if (fr.get("flow_shift") or {}).get("freeze_entries"):
        reasons.append("Stage 44 flow shift — every fast horizon is vetoed")
    v = fr.get("validity") or {}
    if v.get("verdict") and not v.get("valid"):
        reasons.append(f"Stage 51 {v.get('verdict')}")

    return {"headline": "No high-quality opportunity",
            "reasons": reasons[:6],
            "recommendation": "Stay flat",
            "advisory_only": True}
