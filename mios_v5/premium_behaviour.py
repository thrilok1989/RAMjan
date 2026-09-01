"""Stage 71.85 — Premium LTP Behaviour.

One question, and only one:

    **What is the selected premium's LTP doing right now at its own
    Support / Resistance?**

Not *where* the levels are — Stage 71.8 owns that. Not *whether to act* —
Stage 72 owns that. This stage sits between them and describes the interaction:
a level being defended, a level giving way, a premium that has left the fight
altogether, or not enough evidence to say.

## It computes five things

`behaviour · strength · confidence · momentum · reason ranking`. Everything
else in the output is transported from a finished stage, and `CONSUMED` names
the owner of each one. `docs/AUDIT_STAGE_71_85_PREMIUM_BEHAVIOUR.md` checked all
of them against the codebase before this file existed: **every input already
existed**, which is why this module reads thirty-odd values and measures none.

## One ledger, one axis, one behaviour

The evidence does not vote for four behaviours. It votes on a single axis —
pressure on **this** premium, up or down — and the engaged level turns that into
a behaviour:

| engaged level | pressure UP | pressure DOWN |
|---|---|---|
| support | Support Building | Support Fading |
| resistance | Resistance Fading | Resistance Building |

That is why a blend is impossible here rather than merely forbidden: there is
one winner on one axis, and the level decides what to call it. Nothing is
averaged, and no side is subtracted from another — this module receives **one**
premium and never sees the other.

## Neutral is a verdict, UNKNOWN is an absence

`Neutral` means the evidence reported and did not agree enough to name a fight.
It is one of the six states and it is emitted with reasons. Where the evidence
did not report at all, `strength`, `confidence` and `momentum` are `UNKNOWN` —
a premium nobody is trading has no behaviour strength, and printing one star
would claim a measurement that was never taken.

## Confidence is Stage 0's grade

`decision._grade` is imported, not reimplemented. A second A+/A/B/C ladder in
the codebase would drift from the first one within a month, and a trader
comparing a decision grade against a behaviour grade would be comparing two
different meanings of the same letter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .decision import _grade

ADVISORY_ONLY = True

UNKNOWN = "UNKNOWN"

VERSION = "71.85.0"

# ══════════════════════════════════════════════════════════════════════
#  vocabulary — fixed, and the only words this stage may emit
# ══════════════════════════════════════════════════════════════════════

SUPPORT_BUILDING = "Support Building"
SUPPORT_FADING = "Support Fading"
RESISTANCE_BUILDING = "Resistance Building"
RESISTANCE_FADING = "Resistance Fading"
ACCEPTANCE = "Acceptance"
NEUTRAL = "Neutral"

#: Exactly six. `analyse()` returns one of these and never a seventh.
BEHAVIOUR_STATES: Tuple[str, ...] = (
    SUPPORT_BUILDING, SUPPORT_FADING,
    RESISTANCE_BUILDING, RESISTANCE_FADING,
    ACCEPTANCE, NEUTRAL,
)

ACCELERATING = "Accelerating"
BUILDING = "Building"
HOLDING = "Holding"
FADING = "Fading"
EXHAUSTING = "Exhausting"

#: Exactly five, ordered fastest to most spent.
MOMENTUM_STATES: Tuple[str, ...] = (
    ACCELERATING, BUILDING, HOLDING, FADING, EXHAUSTING,
)

#: Five rungs. `UNKNOWN` is emitted instead when nothing reported — see the
#: module docstring.
STRENGTH_BANDS: Tuple[str, ...] = (
    "★☆☆☆☆", "★★☆☆☆", "★★★☆☆", "★★★★☆", "★★★★★",
)

#: `decision._grade`'s ladder, restated for the reader — this module does not
#: own it and cannot change it.
CONFIDENCE_GRADES: Tuple[str, ...] = ("A+", "A", "B", "C", UNKNOWN)

#: The pressure axis. Not a direction on NIFTY — a direction on **this
#: premium**, which is the only thing a holder of it experiences.
UP, DOWN = "UP", "DOWN"

# ══════════════════════════════════════════════════════════════════════
#  ownership
# ══════════════════════════════════════════════════════════════════════

#: The five things with no other owner. Anything not in this tuple that appears
#: in the output arrived from `CONSUMED` and was not measured here.
COMPUTED_HERE: Tuple[str, ...] = (
    "behaviour", "strength", "confidence", "momentum", "top_reasons",
)

#: Every consumed fact, and the one stage that owns it. Three of these correct
#: the specification's table — RVOL and Volume are **Stage 71.8's**, not 71.7's,
#: and the CBV/CSV/CVD totals are 71.8's numeric read rather than 71.7's per-side
#: glyph (audit §1). Reading flow from one stage and volume from another would
#: give one leg's tape two owners, which is the failure the whole stack avoids.
CONSUMED: Dict[str, str] = {
    # ── Stage 71.8 · Premium Structure ──
    "premium_ltp": "Stage 71.8 — Premium Structure",
    "support": "Stage 71.8 — Premium Structure",
    "resistance": "Stage 71.8 — Premium Structure",
    "structure_state": "Stage 71.8 — Premium Structure",
    "structure_score": "Stage 71.8 — Premium Structure",
    "break_probability": "Stage 71.8 — Premium Structure",
    "fakeout_probability": "Stage 71.8 — Premium Structure",
    "hvn": "Stage 71.8 — Premium Structure",
    "lvn": "Stage 71.8 — Premium Structure",
    "premium_acceptance": "Stage 71.8 — Premium Structure",
    "premium_value_area": "Stage 71.8 — Premium Structure (compute_vpfr)",
    "trend": "Stage 71.8 — Premium Structure (VIDYA)",
    "vidya_momentum": "Stage 71.8 — Premium Structure (VIDYA)",
    "cbv": "Stage 71.8 — Premium Structure (order_flow.totals)",
    "csv": "Stage 71.8 — Premium Structure (order_flow.totals)",
    "cvd": "Stage 71.8 — Premium Structure (order_flow.totals)",
    "volume": "Stage 71.8 — Premium Structure (order_flow.totals)",
    "rvol": "Stage 71.8 — Premium Structure",
    "volume_climax": "Stage 71.8 — Premium Structure",
    "ignition": "Stage 71.8 — Premium Structure (detect_ignition)",
    "premium_sr_strength": "Stage 71.8 — Strike Validation",
    # ── Stage 71.7 · Premium Energy ──
    "energy": "Stage 71.7 — Premium Energy",
    "energy_shift": "Stage 71.7 — Premium Energy",
    "energy_acceleration": "Stage 71.7 — Premium Energy",
    "rotation": "Stage 71.7 — Premium Energy",
    "dominance": "Stage 71.7 — Premium Energy",
    "spike_probability": "Stage 71.7 — Premium Energy",
    # ── the market stages, each reached through its existing reader ──
    "absorption": "Stage 43 — Absorption (leg Absorb block)",
    "leg_state": "Stage 50 — LTP Behaviour",
    "leg_pressure": "Stage 50 — LTP Behaviour",
    "reaction": "Stage 42 — Acceptance / Rejection / Trap",
    "dealer_levels": "Stage 11 — Dealer Positioning",
    "charm_pin": "Stage 11 — Dealer Positioning",
    "stability": "Stage 44 — Sudden Flow Shift + Stability",
    "htf_bias": "Stage 45 — Higher-Timeframe VPFR",
}

# ══════════════════════════════════════════════════════════════════════
#  thresholds — the few numbers this stage chooses, each with its reason
# ══════════════════════════════════════════════════════════════════════

#: How close the LTP must be to a level, as a percentage of the LTP, for that
#: level to be *in play*. Premiums move several percent in a minute, so a band
#: tight enough for a NIFTY level would report "no battle" during the fight.
_ENGAGED_PCT = 4.0

#: Below this many reporting signals the ledger cannot name a fight. Two agreeing
#: reads is the minimum that is not a single opinion.
_MIN_EVIDENCE = 2

#: The count at which coverage stops adding confidence. Chosen as the number of
#: signals a healthy cycle reports, not as a fraction of the ledger's size — a
#: ledger that grows should not silently make every past grade look thin.
_FULL_EVIDENCE = 8

#: A share of the evidence at or above this is a decisive read. Below the first
#: rung the ledger is close to a coin toss and the behaviour is `Neutral`.
_STRENGTH_BANDS: Tuple[Tuple[float, str], ...] = (
    (0.85, STRENGTH_BANDS[4]),
    (0.72, STRENGTH_BANDS[3]),
    (0.62, STRENGTH_BANDS[2]),
    (0.55, STRENGTH_BANDS[1]),
    (0.00, STRENGTH_BANDS[0]),
)

#: Stage 71.7's shift vocabulary → this stage's momentum word. `Compressing` is
#: `Holding` on purpose: coiled energy is stored, not spent, and calling it
#: `Fading` would report the opposite of what it means.
_SHIFT_MOMENTUM: Dict[str, str] = {
    "Exploding": ACCELERATING,
    "Increasing": BUILDING,
    "Building": BUILDING,
    "Holding": HOLDING,
    "Compressing": HOLDING,
    "Distributing": FADING,
    "Decreasing": FADING,
}

#: Stage 50's per-leg classification → the pressure it puts on this premium.
_LEG_STATE_PRESSURE: Dict[str, str] = {
    "building": UP, "squeeze": UP,
    "distribution": DOWN, "unwinding": DOWN,
}

#: Stage 50's pressure read for the side that expands this premium.
_LEG_PRESSURE: Dict[str, str] = {
    "absorbing": UP, "building": UP,
    "exhausted": DOWN, "weakening": DOWN,
}


# ══════════════════════════════════════════════════════════════════════
#  helpers
# ══════════════════════════════════════════════════════════════════════

def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _d(v) -> Dict[str, Any]:
    """A dict, whatever arrived.

    `analyse()` promises it never raises and its inputs come from caches a
    degraded cycle can leave holding a string or a sentinel. Junk should read as
    `UNKNOWN`, not as a traceback through an advisory panel."""
    return dict(v) if isinstance(v, Mapping) else {}


def _s(v) -> str:
    return "" if v is None else str(v).strip()


@dataclass(frozen=True)
class Reason:
    """One piece of evidence, traceable to the stage that measured it.

    Never a plain string: a reason a trader cannot trace to an owner is an
    assertion, and this stage asserts nothing of its own.
    """
    code: str
    label: str
    owner: str
    weight: float
    source: str
    direction: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "label": self.label, "owner": self.owner,
                "weight": self.weight, "source": self.source,
                "direction": self.direction}


def _vote(ledger: List[Reason], direction: str, weight: float, code: str,
          label: str, key: str) -> None:
    """Record one signal on the pressure axis, carrying its owner from
    `CONSUMED` so a reason can never name a stage that does not own it."""
    ledger.append(Reason(code=code, label=label,
                         owner=CONSUMED.get(key, UNKNOWN),
                         weight=round(float(weight), 2),
                         source=key, direction=direction))


# ══════════════════════════════════════════════════════════════════════
#  engagement — which level is in play
# ══════════════════════════════════════════════════════════════════════

def engagement(structure: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Which of the premium's own levels the LTP is currently at.

    Reads Stage 71.8's `support`, `resistance` and `ltp` and measures the
    distance between them. The levels are **not** recomputed — the distance
    between a published level and a published price is the interaction this
    stage exists to describe.
    """
    st = _d(structure)
    ltp = _f(st.get("ltp"))
    lv = _d(st.get("levels"))
    sup = _f(st.get("support")) if st.get("support") is not None else _f(lv.get("support"))
    res = _f(st.get("resistance")) if st.get("resistance") is not None else _f(lv.get("resistance"))

    if ltp is None or ltp <= 0:
        return {"level": None, "kind": None, "distance_pct": None,
                "why": "Stage 71.8 published no premium LTP"}

    d_sup = (abs(ltp - sup) / ltp * 100.0) if sup is not None else None
    d_res = (abs(res - ltp) / ltp * 100.0) if res is not None else None

    near: List[Tuple[float, str, float]] = []
    if d_sup is not None and d_sup <= _ENGAGED_PCT:
        near.append((d_sup, "support", sup))
    if d_res is not None and d_res <= _ENGAGED_PCT:
        near.append((d_res, "resistance", res))

    if not near:
        return {"level": None, "kind": None,
                "distance_pct": None, "support_pct": d_sup,
                "resistance_pct": d_res,
                "why": (f"neither level is within {_ENGAGED_PCT:.0f}% of "
                        f"the premium — no active battle")}

    near.sort(key=lambda t: t[0])
    dist, kind, level = near[0]
    return {"level": level, "kind": kind, "distance_pct": round(dist, 2),
            "support_pct": d_sup, "resistance_pct": d_res,
            "why": f"the premium is {dist:.1f}% from its {kind}"}


# ══════════════════════════════════════════════════════════════════════
#  the ledger
# ══════════════════════════════════════════════════════════════════════

def _flow_votes(ledger: List[Reason], st: Mapping[str, Any]) -> None:
    """CBV / CSV / CVD, read from Stage 71.8's totals."""
    fl = _d(st.get("flow"))
    share = _f(fl.get("buy_share"))
    cvd = _f(fl.get("cvd"))
    if share is not None:
        tilt = share - 50.0
        if abs(tilt) >= 8.0:
            w = min(1.0, abs(tilt) / 25.0) * 0.8
            _vote(ledger, UP if tilt > 0 else DOWN, w,
                  "PREMIUM_FLOW",
                  f"{share:.0f}% of the premium's traded volume lifted the offer"
                  if tilt > 0 else
                  f"{100 - share:.0f}% of the premium's traded volume hit the bid",
                  "cbv")
    elif cvd is not None and abs(cvd) > 0:
        _vote(ledger, UP if cvd > 0 else DOWN, 0.5, "PREMIUM_CVD",
              f"premium CVD {cvd:+,.0f}", "cvd")


def _absorption_votes(ledger: List[Reason], st: Mapping[str, Any]) -> None:
    ab = _d(st.get("absorption"))
    if ab.get("buyer"):
        _vote(ledger, UP, 0.9, "BUYER_ABSORPTION", "Buyer Absorption",
              "absorption")
    elif ab.get("seller"):
        _vote(ledger, DOWN, 0.9, "SELLER_ABSORPTION", "Seller Absorption",
              "absorption")


def _trend_votes(ledger: List[Reason], st: Mapping[str, Any]) -> None:
    tr = _d(st.get("trend_read"))
    word = _s(st.get("trend") or tr.get("trend")).lower()
    mom = _f(tr.get("momentum"))
    if word and word != UNKNOWN.lower():
        if any(k in word for k in ("up", "bull", "rising")):
            _vote(ledger, UP, 0.7, "PREMIUM_TREND",
                  f"VIDYA trend {_s(st.get('trend'))}", "trend")
        elif any(k in word for k in ("down", "bear", "falling")):
            _vote(ledger, DOWN, 0.7, "PREMIUM_TREND",
                  f"VIDYA trend {_s(st.get('trend'))}", "trend")
    if mom is not None and abs(mom) >= 0.5:
        _vote(ledger, UP if mom > 0 else DOWN, min(1.0, abs(mom) / 3.0) * 0.6,
              "PREMIUM_MOMENTUM", f"VIDYA delta {mom:+.2f}%", "vidya_momentum")


def _energy_votes(ledger: List[Reason], side_read: Mapping[str, Any],
                  shift: Mapping[str, Any], rotation: Mapping[str, Any],
                  dominance: Mapping[str, Any], side: str) -> None:
    state = _s(shift.get("state"))
    if state in _SHIFT_MOMENTUM and state != "Holding":
        direction = UP if _SHIFT_MOMENTUM[state] in (ACCELERATING, BUILDING) else DOWN
        accel = shift.get("accelerating") is True
        _vote(ledger, direction, 0.85 if accel else 0.7, "ENERGY_SHIFT",
              f"Premium Energy {state}" + (" and accelerating" if accel else ""),
              "energy_shift")

    label = _s(rotation.get("label"))
    if _s(rotation.get("rotation")).upper() == "ROTATION" and label:
        if label.endswith(side):
            _vote(ledger, UP, 0.6, "ROTATION_IN",
                  f"energy rotating {label}", "rotation")
        elif label.startswith(side):
            _vote(ledger, DOWN, 0.6, "ROTATION_OUT",
                  f"energy rotating {label}", "rotation")

    dom = _s(_d(dominance).get("side") or dominance.get("dominant")
             if isinstance(dominance, Mapping) else dominance)
    if dom and dom.upper() in ("CALL", "PUT"):
        _vote(ledger, UP if dom.upper() == side else DOWN, 0.45,
              "DOMINANCE", f"{dom.upper()} premium dominant", "dominance")

    spike = _f(_d(side_read).get("spike"))
    if spike is not None and spike >= 60:
        _vote(ledger, UP, min(1.0, spike / 100.0) * 0.55, "SPIKE_PRESSURE",
              f"spike probability {spike:.0f}%", "spike_probability")


def _leg_votes(ledger: List[Reason], side_read: Mapping[str, Any]) -> None:
    """Stage 50's classification, read through Stage 71.7's per-side block."""
    beh = _d(side_read.get("behaviour"))
    state = _s(beh.get("state")).lower()
    press = _s(beh.get("pressure")).lower()
    if state in _LEG_STATE_PRESSURE:
        _vote(ledger, _LEG_STATE_PRESSURE[state], 0.75, f"LEG_{state.upper()}",
              _s(beh.get("label")) or state.title(), "leg_state")
    if press in _LEG_PRESSURE:
        _vote(ledger, _LEG_PRESSURE[press], 0.65, f"PRESSURE_{press.upper()}",
              _s(beh.get("pressure_label")) or press.title(), "leg_pressure")


def _dealer_votes(ledger: List[Reason], fr: Mapping[str, Any]) -> None:
    """Stage 11 pins the **index**, and a pinned index is a premium that decays.

    The dealer levels are NIFTY levels, so they cannot vote on where the
    premium's own support is. What they can say is whether the underlying is
    being held still, and a premium under a live pin loses value whichever
    level it is sitting at.
    """
    pin = _d(fr.get("charm_pin"))
    if pin.get("active") or pin.get("pinned") or _s(pin.get("state")).upper() == "PINNED":
        _vote(ledger, DOWN, 0.5, "CHARM_PIN",
              _s(pin.get("label")) or "charm pin holding the index", "charm_pin")
    dl = _d(fr.get("dealer_levels"))
    flip = _f(dl.get("gamma_flip"))
    spot = _f(fr.get("spot"))
    if flip is not None and spot is not None and spot > 0:
        gap = abs(spot - flip) / spot * 100.0
        if gap <= 0.15:
            _vote(ledger, DOWN, 0.4, "GAMMA_FLIP",
                  f"spot is {gap:.2f}% from the gamma flip — dealers damping",
                  "dealer_levels")


def _level_votes(ledger: List[Reason], st: Mapping[str, Any],
                 eng: Mapping[str, Any]) -> None:
    """The signals whose meaning depends on which level is engaged.

    A high break probability is not bullish or bearish on its own — it says the
    engaged level gives way, and at support that is DOWN while at resistance it
    is UP. Same number, opposite pressure, which is exactly why it cannot be
    read without the engagement.
    """
    kind = eng.get("kind")
    if kind not in ("support", "resistance"):
        return
    through = UP if kind == "resistance" else DOWN     # the level giving way
    holds = DOWN if kind == "resistance" else UP       # the level defended

    brk = _f(st.get("break_probability"))
    fake = _f(st.get("fakeout_probability"))
    if brk is not None and brk >= 55:
        _vote(ledger, through, min(1.0, brk / 100.0) * 0.9, "BREAK_PROBABILITY",
              f"break probability {brk:.0f}% at the {kind}", "break_probability")
    if fake is not None and fake >= 55:
        _vote(ledger, holds, min(1.0, fake / 100.0) * 0.9, "FAKEOUT_PROBABILITY",
              f"fakeout probability {fake:.0f}% at the {kind}",
              "fakeout_probability")

    acc = _d(st.get("acceptance_read"))
    state = _s(acc.get("state")).upper()
    if state == "REJECTING":
        _vote(ledger, holds, 0.8, "PREMIUM_REJECTION",
              f"the premium is rejecting its {kind}", "premium_acceptance")
    elif state == "BREAKING":
        _vote(ledger, through, 0.8, "PREMIUM_BREAK",
              f"the premium is breaking its {kind}", "premium_acceptance")

    level = _f(eng.get("level"))
    ltp = _f(st.get("ltp"))
    if level is not None and ltp is not None and ltp > 0:
        band = ltp * 0.01
        for key, direction, word in (("hvn", holds, "high-volume node"),
                                     ("lvn", through, "low-volume node")):
            for node in st.get(key) or ():
                px = _f(node.get("price") if isinstance(node, Mapping) else node)
                if px is not None and abs(px - level) <= band:
                    _vote(ledger, direction, 0.6, key.upper(),
                          f"{word} at the {kind}", key)
                    break

    ig = _d(st.get("ignition"))
    if ig.get("wyckoff"):
        _vote(ledger, holds, 0.85, "WYCKOFF",
              " · ".join(ig["wyckoff"]) + " — false break at the level",
              "ignition")


def ledger(structure: Optional[Mapping[str, Any]] = None,
           side_read: Optional[Mapping[str, Any]] = None,
           shift: Optional[Mapping[str, Any]] = None,
           rotation: Optional[Mapping[str, Any]] = None,
           dominance: Any = None,
           fr: Optional[Mapping[str, Any]] = None,
           side: str = "",
           eng: Optional[Mapping[str, Any]] = None) -> Tuple[Reason, ...]:
    """Every signal that reported, on one axis. Order is collection order;
    ranking happens once, in `_rank`."""
    st, sr = _d(structure), _d(side_read)
    out: List[Reason] = []
    _flow_votes(out, st)
    _absorption_votes(out, st)
    _trend_votes(out, st)
    _energy_votes(out, sr, _d(shift), _d(rotation), dominance, side)
    _leg_votes(out, sr)
    _dealer_votes(out, _d(fr))
    _level_votes(out, st, _d(eng))
    return tuple(out)


def _rank(votes: Sequence[Reason], keep: str) -> Tuple[Reason, ...]:
    """At most five, strongest first.

    Reasons for the winning direction lead; the losing direction follows so the
    output shows what argued against the verdict rather than hiding it.
    """
    agree = sorted((r for r in votes if r.direction == keep),
                   key=lambda r: -r.weight)
    against = sorted((r for r in votes if r.direction != keep),
                     key=lambda r: -r.weight)
    return tuple((agree + against)[:5])


# ══════════════════════════════════════════════════════════════════════
#  the four verdicts
# ══════════════════════════════════════════════════════════════════════

def _behaviour(eng: Mapping[str, Any], up: float, down: float,
               reporting: int, accepted: Optional[bool]) -> Dict[str, Any]:
    """One state, chosen once.

    Order matters and is the specification's: insufficient evidence is `Neutral`
    before anything else is considered, no engaged level makes `Acceptance`
    available, and only then does the winning direction name a fight.
    """
    if reporting < _MIN_EVIDENCE or (up + down) <= 0:
        return {"behaviour": NEUTRAL,
                "why": f"only {reporting} signals reported — not enough to "
                       f"name a behaviour"}

    kind = eng.get("kind")
    if kind not in ("support", "resistance"):
        if accepted:
            return {"behaviour": ACCEPTANCE,
                    "why": "no level is engaged and the premium is holding "
                           "its value area"}
        return {"behaviour": NEUTRAL,
                "why": _s(eng.get("why")) or "no level is engaged"}

    if up == down:
        return {"behaviour": NEUTRAL,
                "why": f"the evidence at the {kind} is evenly split"}

    winner = UP if up > down else DOWN
    if kind == "support":
        state = SUPPORT_BUILDING if winner == UP else SUPPORT_FADING
    else:
        state = RESISTANCE_FADING if winner == UP else RESISTANCE_BUILDING
    return {"behaviour": state, "direction": winner,
            "why": f"{max(up, down):.2f} of {up + down:.2f} weighted evidence "
                   f"reads {winner} at the {kind}"}


def _strength(share: Optional[float]) -> Any:
    if share is None:
        return UNKNOWN
    for floor, stars in _STRENGTH_BANDS:
        if share >= floor:
            return stars
    return STRENGTH_BANDS[0]


def _confidence(share: Optional[float], reporting: int,
                stability: str) -> Dict[str, Any]:
    """`decision._grade` over agreement and coverage, penalised by Stage 44.

    Two numbers on the 1–5 scale `_grade` already speaks: how one-sided the
    evidence was, and how much of it there was. A one-sided read from two
    signals and a one-sided read from ten are not the same claim, and averaging
    the two keeps them apart without inventing a second ladder.
    """
    if share is None or reporting <= 0:
        return {"confidence": UNKNOWN, "score": None,
                "why": "nothing reported"}
    agreement = 1.0 + max(0.0, (share - 0.5) / 0.5) * 4.0
    coverage = 1.0 + min(1.0, reporting / float(_FULL_EVIDENCE)) * 4.0
    score = (agreement + coverage) / 2.0
    word = stability.upper()
    note = ""
    if word == "SHOCK":
        score, note = min(score, 2.0), " — capped by Stage 44 SHOCK"
    elif word == "UNSTABLE":
        score, note = score * 0.85, " — discounted by Stage 44 UNSTABLE"
    return {"confidence": _grade(score), "score": round(score, 2),
            "why": (f"{share * 100:.0f}% agreement across {reporting} "
                    f"signals{note}")}


def _momentum(shift: Mapping[str, Any], st: Mapping[str, Any],
              side_read: Mapping[str, Any]) -> Dict[str, Any]:
    """The *rate*, which is a different question from the behaviour.

    Exhaustion outranks everything: a premium can be accelerating on the shift
    read and still be spent, and the spent reading is the one that costs money.
    """
    beh = _d(side_read.get("behaviour"))
    climax = _d(st.get("volume_climax"))
    if _s(beh.get("pressure")).lower() == "exhausted":
        return {"momentum": EXHAUSTING, "why": "Stage 50 reports exhaustion"}
    if climax.get("climax") is True:
        return {"momentum": EXHAUSTING,
                "why": _s(climax.get("why")) or "volume climax"}

    state = _s(shift.get("state"))
    if state in _SHIFT_MOMENTUM:
        word = _SHIFT_MOMENTUM[state]
        if shift.get("accelerating") is True and word in (BUILDING, ACCELERATING):
            return {"momentum": ACCELERATING,
                    "why": f"Premium Energy {state} and accelerating"}
        return {"momentum": word, "why": f"Premium Energy {state}"}

    mom = _f(_d(st.get("trend_read")).get("momentum"))
    if mom is not None:
        if mom >= 1.0:
            return {"momentum": BUILDING, "why": f"VIDYA delta {mom:+.2f}%"}
        if mom <= -1.0:
            return {"momentum": FADING, "why": f"VIDYA delta {mom:+.2f}%"}
        return {"momentum": HOLDING, "why": f"VIDYA delta {mom:+.2f}%"}
    return {"momentum": UNKNOWN,
            "why": "neither Stage 71.7 nor VIDYA reported a rate"}


def _acceptance_label(st: Mapping[str, Any]) -> Dict[str, Any]:
    """Where the premium sits against **its own** value area.

    Stage 45's VAH/VAL are NIFTY's. A premium accepted above its own value area
    is a different fact from NIFTY accepted above its, and only the first one
    describes the option a trader is holding (audit §3).
    """
    prof = _d(st.get("profile"))
    ltp, vah, val = _f(st.get("ltp")), _f(prof.get("vah")), _f(prof.get("val"))
    if ltp is not None and vah is not None and ltp > vah:
        return {"acceptance": "Accepted Above VAH", "accepted": True,
                "source": CONSUMED["premium_value_area"]}
    if ltp is not None and val is not None and ltp < val:
        return {"acceptance": "Accepted Below VAL", "accepted": True,
                "source": CONSUMED["premium_value_area"]}
    if ltp is not None and vah is not None and val is not None:
        return {"acceptance": "Inside Value", "accepted": False,
                "source": CONSUMED["premium_value_area"]}
    state = _s(_d(st.get("acceptance_read")).get("state"))
    if state:
        return {"acceptance": state.title(), "accepted": None,
                "source": CONSUMED["premium_acceptance"]}
    return {"acceptance": UNKNOWN, "accepted": None,
            "source": CONSUMED["premium_value_area"]}


# ══════════════════════════════════════════════════════════════════════
#  the stage
# ══════════════════════════════════════════════════════════════════════

def analyse(structure: Optional[Mapping[str, Any]] = None,
            energy: Optional[Mapping[str, Any]] = None,
            fr: Optional[Mapping[str, Any]] = None,
            side: str = "CALL",
            validation: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """One premium's behaviour. Always a dict, never raises.

    `structure`  — Stage 71.8's `premium_structure.analyse()` for **this side**
    `energy`     — Stage 71.7's `premium_energy.build()`, whole
    `fr`         — `final_read`, for Stages 11 · 42 · 44 · 45
    `validation` — Stage 71.8's `strike_validation.build()`, for S/R strength

    Every argument is a **finished output**. Nothing is fetched, nothing is
    measured, and an absent argument yields `Neutral` with `UNKNOWN` strength
    rather than an error — a degraded cycle should produce a read a trader can
    see through.
    """
    st = _d(structure)
    en = _d(energy)
    side = _s(side).upper() or "CALL"
    side_read = _d(_d(en.get("sides")).get(side))
    shift = _d(_d(en.get("shift")).get(side))
    rotation = _d(en.get("rotation"))
    frd = _d(fr)

    eng = engagement(st)
    votes = ledger(st, side_read, shift, rotation, en.get("dominance"),
                   frd, side, eng)
    up = sum(r.weight for r in votes if r.direction == UP)
    down = sum(r.weight for r in votes if r.direction == DOWN)
    total = up + down

    acc = _acceptance_label(st)
    verdict = _behaviour(eng, up, down, len(votes), acc.get("accepted"))
    state = verdict["behaviour"]

    # `Neutral` is the absence of a read, not a weak one. Grading it would put
    # five stars and an A+ on "the evidence did not agree enough to name a
    # fight", which is the opposite of what the words mean — so strength and
    # confidence both go UNKNOWN, exactly as they do when nothing reported.
    share = (max(up, down) / total) if total > 0 and state != NEUTRAL else None

    conf = _confidence(share, len(votes),
                       _s(frd.get("stability")) or _s(en.get("stability")))
    mom = _momentum(shift, st, side_read)

    keep = verdict.get("direction") or (UP if up >= down else DOWN)
    reasons = _rank(votes, keep)

    sr_strength = _d(_d(_d(_d(validation).get("sides")).get(side)
                        ).get("checks")).get("premium_sr_strength")

    return {
        "advisory_only": ADVISORY_ONLY,
        "version": VERSION,
        "ready": bool(votes),
        "side": side,
        # ── computed here, and only these five ──
        "behaviour": state,
        "strength": _strength(share),
        "confidence": conf["confidence"],
        "momentum": mom["momentum"],
        "top_reasons": tuple(r.to_dict() for r in reasons),
        # ── consumed, every one named in CONSUMED ──
        "acceptance": acc["acceptance"],
        "break_probability": st.get("break_probability", UNKNOWN),
        "fakeout_probability": st.get("fakeout_probability", UNKNOWN),
        "structure_state": (_d(st.get("levels")).get("state") or UNKNOWN),
        "structure_strength": (sr_strength if sr_strength is not None
                               else st.get("structure_score", UNKNOWN)),
        "premium_ltp": st.get("ltp"),
        "support": st.get("support"), "resistance": st.get("resistance"),
        # ── how it was reached ──
        "engagement": eng,
        "evidence": {"up": round(up, 2), "down": round(down, 2),
                     "reporting": len(votes), "share": (round(share, 3)
                                                        if share is not None
                                                        else None),
                     "all": tuple(r.to_dict() for r in votes)},
        "why": verdict["why"],
        "confidence_why": conf["why"],
        "momentum_why": mom["why"],
        "states": BEHAVIOUR_STATES,
        "consumed": dict(CONSUMED),
        "computed_here": list(COMPUTED_HERE),
    }


def build(structure: Optional[Mapping[str, Any]] = None,
          energy: Optional[Mapping[str, Any]] = None,
          fr: Optional[Mapping[str, Any]] = None,
          validation: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Both sides, each analysed **alone**.

    `structure` is `{"CALL": …, "PUT": …}` — Stage 71.8's per-side output. The
    two calls share nothing: no comparison, no subtraction, no preference. A
    premium's behaviour is a fact about that premium, and the stage that picks
    between the two sides is Stage 72.
    """
    per_side = _d(structure)
    return {side: analyse(per_side.get(side), energy, fr, side, validation)
            for side in ("CALL", "PUT")}
