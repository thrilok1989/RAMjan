"""MIOS — the Market Alignment Checklist. One table, one question.

> **Where is spot now, which levels and forces are active, and does each one
> point BULL or BEAR?**

The app answers that in twenty places. The walls live in the option chain,
dealer posture in the Greeks panel, premium in the energy card, leg structure in
the cockpit — each correct, each in its own box, and nobody can see at a glance
what agrees with what. This module puts every one of those reads on one line
each, in a single table, and counts the vote.

## What it deliberately does NOT carry

**No general context.** News, FII/DII, sector rotation, global indices and the
commodity regime were on this table and are gone, along with the FLOW and GLOBAL
buckets that existed only for them.

They were removed because of what they did to the tally rather than what they
are worth: every row is one equal vote, so five slow, once-a-day context reads
outvoted the level interactions the table exists to show — a summary could read
BEARISH on FII/DII and commodities while STRUCTURE, the levels themselves, read
BULLISH. Those panels still exist and are still right; this table is now only
about where price is and what it is doing at the levels in front of it.

## It is not an engine, and this is the rule that keeps it honest

**Every value here was produced somewhere else and published before this module
runs.** Nothing is fetched, nothing is derived from candles, no threshold is
re-picked. If a fact is not already on `session_state`, this module reports it as
`❓ not available` — it never computes a replacement.

That is not modesty, it is the whole point: a second implementation of any of
these reads would let the checklist disagree with the panel it is summarising,
which is precisely the failure `docs/ARCHITECTURE_PRINCIPLES.md` §1-2 exists to
prevent. The checklist is a *view*, and a view that recalculates is a fork.

Two consequences worth stating, because they are where this would decay:

* **The interaction column is a lookup, not a classifier.** "Rejecting",
  "Testing", "Accepted above" come from `level_acceptance`'s observed vocabulary
  — the strip already runs Stage 42's follow-through logic against the dealer
  magnet, gamma flip, S/R, OI walls and POC/VAH/VAL, and publishes the verdict on
  `_la_zones_latest`. This module matches a level to that zone list and maps the
  word. Where a level has no observed read (an HVP line, say), it falls back to
  the plain positional statement — *above / below / near* — and says so, rather
  than inventing a behavioural claim the app never made.
* **The direction column is `bias_ball`.** The one rule that actually needs care
  — an option leg inverts, so PUT support is bearish for NIFTY — is written once,
  in `mios_v5/bias_ball.py`, and every leg row funnels through it. This module
  adds exactly one rule of its own, stated in `_level_align`: a level that is
  *holding* reads its natural direction, and a level that has *broken* reads the
  opposite. That is the assembly rule the checklist exists to apply.

## Three states, plus the two that keep the count honest

Every row lands on `bull` · `bear` · `neutral` · `na` · `info`.

`na` is a first-class answer (principle 9). A row whose producer did not report
is ❓, never a quiet 0 or a neutral that pads the count — the summary's
denominator is *active* checks only, so an unavailable read cannot dilute the
vote in either direction.

`info` is the row that reported perfectly well and still has no direction to
give: spot itself, and each leg's raw premium. They belong on the table because
every other row is measured against them, and they belong outside the tally
because a price is not a vote. Keeping them apart from `na` is what stops a
healthy cycle from being reported as three checks short.

Pure: a mapping in, a dict out. No pandas, no Streamlit, no session writes, no
network. `build()` takes any `Mapping` — the tests hand it a plain dict.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import bias_ball as _bb
from . import leg_keys as _leg_keys
from .bias_ball import BEAR, BULL, NEUTRAL

#: the fourth state — the producer did not report. Never 0, never neutral.
NA = "na"

#: the fifth, and it is NOT a weaker `na`: the check reported a value and
#: deliberately does not vote. Spot is the reference every other row measures
#: against, and a raw premium is a price, not a direction — scoring either would
#: put a number in the tally that means nothing directionally.
#:
#: Kept apart from `na` because the summary's ❓ count answers "how much of the
#: picture is missing right now?", and folding three healthy rows into it would
#: make a fully-reporting cycle look degraded.
INFO = "info"

#: display sections, in table order.
STRUCTURE = "NIFTY STRUCTURE"
PREMIUM = "OPTION PREMIUM / LTP"
FINAL = "FINAL INTERACTION"

#: summary buckets — the verdicts under the table. A row's bucket is independent
#: of the section it is DISPLAYED in: the war zone is shown under FINAL
#: INTERACTION and votes with structure, because that is what it describes.
#:
#: There is no FLOW or GLOBAL bucket. They existed only for the general-context
#: rows — News, FII/DII, Sector, Global, Commodity — and a bucket with no
#: possible producer would render as a permanent "not reporting" chip, which
#: says nothing and looks like a fault.
B_STRUCTURE = "STRUCTURE"
B_OPTIONS = "OPTIONS"
B_DEALERS = "DEALERS"
BUCKETS = (B_STRUCTURE, B_OPTIONS, B_DEALERS)

#: alignment → the ball shown in the table. `bias_ball` owns the first three;
#: ❓ is this module's, because "not reported" is not a bias.
BALLS = {BULL: "🟢", BEAR: "🔴", NEUTRAL: "⚪", NA: "❓", INFO: "·"}

#: alignment → the word beside the ball.
WORDS = {BULL: "Bull", BEAR: "Bear", NEUTRAL: "Neutral", NA: "n/a",
         INFO: "reference"}

#: within this many index points spot is "at" a level rather than merely near
#: it. Matches `level_acceptance.INTERACTION_BAND` so the checklist and the
#: acceptance strip cannot disagree about what counts as a touch.
AT_BAND = 5.0

#: beyond this, a level is not in play at all — "far from level".
NEAR_BAND = 25.0

#: how a verdict is expressed. The distinction is the whole correctness of the
#: alignment column, so it is named rather than left implicit:
#:
#: `HELD`  — a statement about the LEVEL, true whatever its role. "Price was
#:           rejected here" means the level did its job whether it is support or
#:           resistance.
#: `ABOVE` — a statement about PRICE's side of the level, which means opposite
#:           things for the two roles. Price above a support is that support
#:           holding; price above a resistance is that resistance BROKEN.
#: `FAR`  — price is nowhere near the level. Not a hold and not a break; the
#:           level is simply not in the way. For a BARRIER that is a direction
#:           of its own (see `_room_align`), and for a value anchor it is
#:           nothing at all.
HELD = "held"
ABOVE = "above"
FAR = "far"

#: `level_acceptance` observed state → (icon, phrase, (kind, value)).
#:
#: ⚠️ `ACCEPTED_ABOVE` is not "the level held". It is "price settled above the
#: level", and what that means depends entirely on which side the level was
#: acting from. Recording both families as one boolean is what made every
#: resistance row vote backwards.
_OBSERVED = {
    "ACCEPTED_ABOVE": ("🟢", "Accepted above", (ABOVE, True)),
    "ACCEPTED_BELOW": ("🔴", "Accepted below", (ABOVE, False)),
    "REJECTED": ("🔴", "Rejecting", (HELD, True)),
    "BREAK_ATTEMPT": ("🟠", "Breaking", (HELD, False)),
    "TESTING": ("🟡", "Testing", (None, None)),
    "FAILED_BREAK_WAIT": ("🟡", "Failed break", (None, None)),
}


def _is_support(role: Optional[str]) -> bool:
    """Whether a role acts from below. `bias_ball` accepts the VOB spellings
    too, so they are normalised the same way here."""
    r = str(role or "").lower()
    return r in ("support", "bullish")


def _holding(role: Optional[str], verdict: Tuple[Optional[str], Optional[bool]]
             ) -> Optional[bool]:
    """Did the level hold, given a verdict and the role it was acting in?

    ⚠️ This is the fix for every resistance row voting backwards.

    A `HELD` verdict is already role-independent and passes through. An `ABOVE`
    verdict has to be resolved against the role, because the two are mirrors: a
    support holds while price is above it, a resistance holds while price is
    below. Treating `above` as `holding` — which every call site did — is right
    for supports and exactly inverted for resistances, so a resistance price had
    just broken to the upside reported as bearish, and one price was respectfully
    sitting under reported as bullish.
    """
    kind, value = verdict
    if kind is None or value is None:
        return None
    if kind == HELD:
        return value
    if kind == FAR:                     # neither held nor broken — see _resolve
        return None
    return value if _is_support(role) else (not value)


# ── small readers ────────────────────────────────────────────────────────────
# Every one returns None rather than a default. A missing number must reach the
# row builders as None so the row can be marked ❓ — a 0.0 fallback here would
# be the exact "invented market data" principle 9 forbids, and the caller could
# not tell the difference.

def _f(v: Any) -> Optional[float]:
    """`v` as a float, or None — including for NaN, which is not a reading."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _map(v: Any) -> Mapping[str, Any]:
    """`v` if it is a mapping, else an empty one.

    ⚠️ Not the same as `v or {}`, and the difference is the bug it fixes: a
    producer that publishes a string, a list or a sentinel where a dict was
    expected passes `or {}` intact and then raises `.get` on a str deep inside a
    row builder — taking down the whole checklist over one malformed publish.
    Every session read goes through here so a bad value degrades that row to ❓
    and leaves the other thirty standing.
    """
    return v if isinstance(v, Mapping) else {}


def _first(seq: Any) -> Any:
    """The head of a (strike, size) pair, or None. The OI walls are published as
    tuples and every consumer wants the strike."""
    if isinstance(seq, (list, tuple)) and seq:
        return seq[0]
    return None


def _label(v: Any) -> Optional[str]:
    """A bias that may be published as a dict or a bare string → its label."""
    if isinstance(v, Mapping):
        for k in ("label", "regime", "rotation", "verdict"):
            if v.get(k):
                return str(v[k])
        return None
    return str(v) if v else None


#: at or above this, a price is an index level and whole rupees are the right
#: precision; below it, it is an option premium and the paise matter.
_INDEX_SCALE = 1000.0


def _rupees(v: Optional[float]) -> str:
    """A price, at the precision its magnitude deserves.

    ⚠️ One formatter for every column, deliberately. Whole rupees are right for
    ₹24,050 and destroy a premium: a leg trading at ₹0.05 with its high-volume
    lines at ₹0.03 and ₹0.04 rendered as "₹0 · ₹0" — three different numbers,
    all displayed as zero, on an expiry afternoon when those are exactly the
    prices being decided.

    The mixed case is worse than either. The value column formatted a pivot as
    `₹31` while the position column beside it called the same pivot `₹30.90`,
    because the two were rounded by different call sites. Routing both through
    here is what stops that.
    """
    if v is None:
        return "—"
    return f"₹{v:,.0f}" if abs(v) >= _INDEX_SCALE else f"₹{v:,.2f}"


def _levels_text(prices: Sequence[float], limit: int = 3) -> str:
    """`₹24,350 · ₹24,400 · ₹24,450` — the side-by-side form the checklist asks
    for wherever a row carries several levels at once."""
    got = [p for p in prices if p is not None][:limit]
    return " · ".join(_rupees(p) for p in got) if got else "—"


# ── the interaction column ───────────────────────────────────────────────────

def _zone_for(level: Optional[float], zones: Sequence[Mapping[str, Any]],
              tol: float = AT_BAND) -> Optional[Mapping[str, Any]]:
    """The published acceptance zone sitting on `level`, if the strip observed
    one. Nearest within `tol`; None means this level has no observed read and
    the caller must fall back to a positional statement."""
    if level is None or not zones:
        return None
    best, best_d = None, None
    for z in zones:
        p = _f(z.get("price"))
        if p is None:
            continue
        d = abs(p - level)
        if d <= tol and (best_d is None or d < best_d):
            best, best_d = z, d
    return best


def _positional(level: Optional[float], spot: Optional[float]
                ) -> Tuple[str, Tuple[Optional[str], Optional[bool]]]:
    """Where spot sits relative to a level, when nothing observed its behaviour.

    Deliberately weaker language than `_OBSERVED`: this says where price *is*,
    never what it *did* — so the verdict it returns is an `ABOVE`, and only the
    caller, which knows the level's role, can turn that into "holding".

    The verdict is empty for the at-band and the far case. A level price is
    sitting exactly on is not yet decided, and one it is nowhere near is neither
    held nor broken; reporting either as a direction would be the invented claim
    this module refuses to make.
    """
    if level is None or spot is None:
        return "—", (None, None)
    d = spot - level
    if abs(d) <= AT_BAND:
        return f"🟡 At {_rupees(level)}", (None, None)
    if abs(d) > NEAR_BAND:
        return f"⚪ Far from {_rupees(level)} ({d:+,.0f})", (FAR, None)
    return ((f"🟢 Above {_rupees(level)} ({d:+,.0f})", (ABOVE, True)) if d > 0
            else (f"🔴 Below {_rupees(level)} ({d:+,.0f})", (ABOVE, False)))


def _interaction(level: Optional[float], spot: Optional[float],
                 zones: Sequence[Mapping[str, Any]], role: Optional[str] = None
                 ) -> Tuple[str, Tuple[Optional[str], Optional[bool]], bool]:
    """The third column: `(text, verdict, observed)`.

    ⚠️ The VERDICT is returned, not a resolved boolean. Collapsing it here threw
    away the difference between "price is sitting on this level, undecided" and
    "price is nowhere near it" — both arrived as None, and a barrier price is
    clear of has a direction while a level price is testing does not. Only
    `_resolve` gets to flatten it, because only the caller knows whether the
    level is a barrier.

    `observed` says which of the two sources answered — True when
    `level_acceptance` had a verdict for this level, False when this is the
    plain positional fallback. The panel greys the fallback rows so the trader
    can see at a glance which interactions are measured behaviour and which are
    just geometry.
    """
    z = _zone_for(level, zones)
    if z is not None:
        icon, phrase, verdict = _OBSERVED.get(
            str(z.get("observed") or ""), ("", "", (None, None)))
        if phrase:
            war = " · in war zone" if z.get("is_battle_zone") else ""
            return f"{icon} {phrase} {_rupees(level)}{war}", verdict, True
    text, verdict = _positional(level, spot)
    return text, verdict, False


# ── the alignment column ─────────────────────────────────────────────────────

def _room_align(chart: str, role: str) -> str:
    """A BARRIER that is nowhere near price — what the absence of it means.

    The same rule the OI walls use, on whatever axis the level lives:

        a cap far away        → room to run      → the leg (or index) is free
        a floor far away      → nothing beneath  → it is unsupported

    which is exactly the inverse of that level constraining price, so it is
    `_level_align(..., holding=False)` — and `bias_ball` still owns the last
    step, so a PUT leg inverts on the way out. A CALL whose resistance is far
    has room for its premium to rise, which is bullish for NIFTY; a PUT whose
    resistance is far has room for ITS premium to rise, which is bearish.

    ⚠️ Side-independent, and that is not an oversight. A resistance far ABOVE
    the price is headroom and a resistance far BELOW it has already been broken
    through — both say the same thing about where the price is free to go.

    Only for barriers. A value anchor (POC) or a regime line (the gamma flip)
    is not something price is "clear of" — being far above value is bullish and
    far below it bearish, which is the position rule, not this one.
    """
    return _level_align(chart, role, False)


def _level_align(chart: str, role: str, holding: Optional[bool]) -> str:
    """A level's direction for NIFTY, given what price did to it.

    Two inputs, both already owned elsewhere: `bias_ball.leg_level_bias` supplies
    the natural direction of a support/resistance on this chart (and the PUT
    inversion), and `holding` comes from the acceptance strip's observed state.

    The one rule this module adds: **a level that broke reads the opposite of the
    level that held.** Support holding is bullish; the same support broken is
    bearish. Unsettled (`None`) is neutral — not a weak bull, not a weak bear.
    """
    natural = _bb.leg_level_bias(chart, role)
    if holding is None or natural == NEUTRAL:
        return NEUTRAL
    if holding:
        return natural
    return BEAR if natural == BULL else BULL


def _room_text(level: Optional[float], price: Optional[float],
               role: str) -> str:
    """How a barrier price is clear of should read.

    "🟢 Far from ₹84.36" states the geometry and hides the reason — a green ball
    beside "far from" tells the reader nothing about why it is green. The walls
    already say what they ARE from here ("Cap clear", "Floor distant"); every
    other barrier now does too.
    """
    gap = abs((level or 0.0) - (price or 0.0))
    if _is_support(role):
        return f"Unsupported · ₹{level:,.2f} is {gap:,.2f} away" \
            if (level or 0) < _INDEX_SCALE else \
            f"Unsupported · {_rupees(level)} is {gap:,.0f} away"
    return f"Clear of {_rupees(level)} ({gap:,.2f} away)" \
        if (level or 0) < _INDEX_SCALE else \
        f"Clear of {_rupees(level)} ({gap:,.0f} away)"


def _resolve(chart: str, role: str,
             verdict: Tuple[Optional[str], Optional[bool]],
             barrier: bool) -> str:
    """Verdict → alignment. The one place the three cases meet.

    * held / broken / above / below → `_level_align`, the hold-or-break rule
    * FAR on a **barrier**         → `_room_align`, the not-in-the-way rule
    * FAR on anything else, or an unsettled verdict → NEUTRAL

    `barrier` is the caller saying "this level is something price can be
    clear of": the OI walls, S/R, the VOB zones, the high-volume pivots.
    A value anchor is not — being far above POC is bullish and far below it
    bearish, which is the position rule, and running the room rule over it
    would report "no POC nearby" as a direction.
    """
    kind, _ = verdict
    if kind == FAR:
        return _room_align(chart, role) if barrier else NEUTRAL
    return _level_align(chart, role, _holding(role, verdict))


def _row(group: str, bucket: str, check: str, value: str, position: str,
         align: str, remark: str = "", observed: bool = True,
         level: Optional[float] = None,
         levels: Optional[Sequence[float]] = None) -> Dict[str, Any]:
    """One line of the checklist.

    `level` is the row's price as a NUMBER, and only index-axis rows carry it:
    the ladder is built by sorting rows on it, so one source feeds both the
    table and the map. A leg row leaves it None — a premium of ₹5.75 sorted
    into a ladder of index levels would place the call between the gamma flip
    and nothing at all.
    """
    return {"group": group, "bucket": bucket, "check": check, "value": value,
            "position": position, "align": align, "remark": remark,
            "observed": bool(observed), "level": _f(level),
            # every number behind `value`, on the row's OWN axis. The leg
            # ladders are built from these, so the map under a premium and the
            # text beside it cannot name different prices.
            "levels": [x for x in (_f(v) for v in (levels or ())) if x is not None]}


def _na_row(group: str, bucket: str, check: str, why: str) -> Dict[str, Any]:
    """A check whose producer did not report. It still occupies a line — a
    silently dropped row is indistinguishable from a check nobody thought of,
    and the trader cannot ask why a number is missing that is not on screen."""
    return _row(group, bucket, check, "—", "—", NA, why, observed=False)


def _level_row(group: str, bucket: str, check: str, level: Optional[float],
               spot: Optional[float], zones: Sequence[Mapping[str, Any]],
               chart: str, role: str, remark: str = "",
               missing: str = "not published this cycle",
               barrier: bool = True) -> Dict[str, Any]:
    """One S/R-shaped row: a price, what spot is doing at it, what that means.

    `barrier` says whether the level is something price can be *clear of* — see
    `_resolve`. True for S/R and pivots; False for a value anchor like the POC,
    where distance means nothing and only the side matters.
    """
    if level is None:
        return _na_row(group, bucket, check, missing)
    text, verdict, observed = _interaction(level, spot, zones, role)
    align = _resolve(chart, role, verdict, barrier)
    if barrier and verdict[0] == FAR:
        text = f"{BALLS.get(align, '⚪')} {_room_text(level, spot, role)}"
    return _row(group, bucket, check, _rupees(level), text, align, remark,
                observed, level=level if chart == "NIFTY" else None)


def _wall_row(check: str, level: Optional[float], spot: Optional[float],
              is_call: bool, missing: str) -> Dict[str, Any]:
    """An OI wall, read as ROOM rather than as a level price is interacting with.

    ⚠️ This is deliberately not the S/R rule, and the difference is the point.

    Every other row asks "did this level hold or break". A wall asks something
    else: **how much room is there before the writers are in the way.** The
    strike itself barely moves — it is where the open interest sat down — so
    what changes through the day is the distance to it, and that distance is
    the read:

        CALL wall (the cap)     close overhead → 🔴 capped, no room to run
                                far away       → 🟢 headroom
        PUT wall (the floor)    close below    → 🟢 supported, writers defending
                                far away       → 🔴 air beneath, nothing to catch a fall

    Note both directions invert against the naive reading, which is why this
    needed saying out loud: a cap far away is BULLISH (there is space), and a
    floor far away is BEARISH (there is nothing under the market). Scoring a
    wall by which side of it price sits — the previous rule — gets the near
    cases exactly backwards.

    `AT` and `NEAR` collapse to one answer here on purpose. Price sitting on a
    cap and price twenty points under it are the same trading fact — the cap is
    in the way — and splitting them would only produce a neutral row at the one
    distance the wall matters most.
    """
    if level is None or spot is None:
        return _na_row(STRUCTURE, B_STRUCTURE, check, missing)
    gap = abs(spot - level)
    active = gap <= NEAR_BAND          # at OR near — the wall is in play
    align = (BEAR if active else BULL) if is_call else (BULL if active else BEAR)
    if is_call:
        word = ("Cap in the way" if active else "Cap clear")
        why = ("CE writers overhead — little room to run"
               if active else "no CE wall nearby — headroom above")
    else:
        word = ("Floor underfoot" if active else "Floor distant")
        why = ("PE writers defending just below — supported"
               if active else "no PE wall nearby — air beneath the market")
    side = "above" if level > spot else "below"
    return _row(STRUCTURE, B_STRUCTURE, check, _rupees(level),
                f"{BALLS[align]} {word} {_rupees(level)} "
                f"({gap:,.0f} pts {side})", align, why, level=level)


# ── the sections ─────────────────────────────────────────────────────────────

def _structure(ss: Mapping[str, Any], mp: Mapping[str, Any], spot: Optional[float],
               zones: Sequence[Mapping[str, Any]],
               fr: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Spot, the walls, S/R, the war zone, POC, the HVP lines and dealer
    posture — everything measured on the index's own axis."""
    rows: List[Dict[str, Any]] = []

    rows.append(_row(STRUCTURE, B_STRUCTURE, "Spot Price",
                     _rupees(spot) if spot is not None else "—",
                     "AT" if spot is not None else "—", INFO,
                     "live index — the reference every other row measures against",
                     level=spot)
                if spot is not None else
                _na_row(STRUCTURE, B_STRUCTURE, "Spot Price", "no live spot"))

    # OI walls — their own rule. See `_wall_row`: a wall is read as ROOM
    # (is the cap in the way? is there a floor underfoot?), not as a level
    # price is holding or breaking, so it does not go through `_level_row`.
    rows.append(_wall_row("PUT Wall OI", _f(_first(mp.get("oi_floor"))), spot,
                          is_call=False, missing="no PE wall ranked"))
    rows.append(_wall_row("CALL Wall OI", _f(_first(mp.get("oi_ceiling"))), spot,
                          is_call=True, missing="no CE wall ranked"))

    # Canonical S/R — the one support and one resistance every screen shares.
    rsr = _map(ss.get("_reaction_sr"))
    sup = _map(rsr.get("support"))
    res = _map(rsr.get("resistance"))
    sup_p = _f(sup.get("price"))
    res_p = _f(res.get("price"))
    if sup_p is None:
        sup_p = _f(fr.get("strong_support"))
    if res_p is None:
        res_p = _f(fr.get("strong_resistance"))
    rows.append(_level_row(
        STRUCTURE, B_STRUCTURE, "NIFTY Support", sup_p, spot, zones,
        "NIFTY", "support",
        f"strength {_f(sup.get('strength')) or _f(fr.get('support_strength')) or 0:.0f}%",
        "no support zone built"))
    rows.append(_level_row(
        STRUCTURE, B_STRUCTURE, "NIFTY Resistance", res_p, spot, zones,
        "NIFTY", "resistance",
        f"strength {_f(res.get('strength')) or _f(fr.get('resistance_strength')) or 0:.0f}%",
        "no resistance zone built"))

    # ⚠️ There is no "War Zone Support" and "War Zone Resistance" row here, and
    # there never should have been. Stage 35 publishes ONE battle zone —
    # `{"type": "SUPPORT"|"RESISTANCE", "price": …}` — a single contested price
    # whose side is decided by the fight, not a band with two edges. There are
    # no `low`/`high` keys on it at all, so the fallback that split one price
    # into two rows fired on every cycle and had the same number voting twice,
    # once as a floor and once as a ceiling, in opposite directions.
    #
    # The single row lives in FINAL INTERACTION, where `_final` reads the
    # zone's own `type` for which side it is fighting on and Stage 35's
    # `expected_winner` for who is winning it.

    # POC — acceptance above value is bullish, below bearish. Same level rule.
    mf = _map(ss.get("_money_flow_data"))
    rows.append(_level_row(STRUCTURE, B_STRUCTURE, "NIFTY POC",
                           _f(mf.get("poc_price")), spot, zones,
                           "NIFTY", "support", "session value — acceptance vs rejection",
                           "no session profile", barrier=False))

    # HVP lines, both sides, shown together. A swing HIGH is resistance and a
    # LOW is support — `bias_ball.hvp_bias` owns that mapping; here the nearest
    # line carries the row's direction and the rest are shown for context.
    profiles = _map(ss.get("_leg_profiles"))
    nifty_prof = _map(profiles.get("NIFTY"))
    for side, check, role in (("LOW", "NIFTY HVP LOW", "support"),
                              ("HIGH", "NIFTY HVP HIGH", "resistance")):
        pts = _hv_prices(nifty_prof, side)
        if not pts:
            rows.append(_na_row(STRUCTURE, B_STRUCTURE, check,
                                "no high-volume pivots on the index frame"))
            continue
        nearest = _nearest_to(pts, spot)
        text, verdict, observed = _interaction(nearest, spot, zones, role)
        _al = _resolve("NIFTY", role, verdict, True)
        if verdict[0] == FAR:
            text = f"{BALLS.get(_al, '⚪')} {_room_text(nearest, spot, role)}"
        rows.append(_row(STRUCTURE, B_STRUCTURE, check, _levels_text(_by_distance(pts, spot)),
                         text, _al,
                         f"{len(pts)} pivot line(s) · nearest {_rupees(nearest)}",
                         observed, level=nearest))

    # ── dealer posture ──
    gx = _map(ss.get("_gex_data"))
    rows.append(_level_row(STRUCTURE, B_DEALERS, "Gamma Flip",
                           _f(gx.get("gamma_flip_level")), spot, zones,
                           "NIFTY", "support",
                           "above flip = dealers dampen, below = they amplify",
                           "no gamma flip published", barrier=False))

    tg = _f(gx.get("total_gex"))
    if tg is not None:
        # Positive GEX pins (neutral for direction, hostile to trend); negative
        # accelerates whatever is already moving — so it is read as neutral here
        # rather than given a direction it does not have on its own.
        rows.append(_row(STRUCTURE, B_DEALERS, "Dealer GEX", f"{tg:+,.0f}L", "—",
                         NEUTRAL,
                         f"{gx.get('gex_signal') or ('pin / mean-revert' if tg > 0 else 'expansion / trend')}"))
    else:
        rows.append(_na_row(STRUCTURE, B_DEALERS, "Dealer GEX", "GEX not computed"))

    dx = mp.get("dex_bias")
    dx_label = _label(dx)
    if dx_label:
        rows.append(_row(STRUCTURE, B_DEALERS, "Dealer DEX", dx_label, "—",
                         _bb.direction_bias(dx_label),
                         "net delta-weighted dealer positioning"))
    else:
        rows.append(_na_row(STRUCTURE, B_DEALERS, "Dealer DEX", "DEX not computed"))

    # Charm pin / dealer magnet. The pull direction is the read: a magnet above
    # spot drags price up, below drags it down. `_magnet` resolves it from what
    # the Market Picture published, without re-choosing the pin strike.
    rows.append(_magnet_row(mp, ss, spot))
    return rows


def _hv_prices(profile: Mapping[str, Any], side: str) -> List[float]:
    """The published high-volume pivot prices on one side of a panel's profile.
    Owner: `volume_points.high_volume_pivots`; this only filters and floats."""
    out: List[float] = []
    for p in (_map(profile).get("hv_points") or ()):
        if not isinstance(p, Mapping):
            continue
        if str(p.get("side") or "").upper() != side:
            continue
        v = _f(p.get("price"))
        if v is not None:
            out.append(v)
    return out


def _by_distance(prices: Sequence[float], ref: Optional[float]) -> List[float]:
    """Closest first, so a truncated `_levels_text` shows the lines that matter."""
    if ref is None:
        return list(prices)
    return sorted(prices, key=lambda p: abs(p - ref))


def _nearest_to(prices: Sequence[float], ref: Optional[float]) -> Optional[float]:
    ordered = _by_distance(prices, ref)
    return ordered[0] if ordered else None


def _magnet_row(mp: Mapping[str, Any], ss: Mapping[str, Any],
                spot: Optional[float]) -> Dict[str, Any]:
    """Charm pin / dealer magnet, via `dealer_magnet` — which owns the read on
    EVERY day and delegates the pin choice to `charm_pin`.

    ⚠️ Not `charm_pin` directly. That module opens with
    `if not is_expiry_day: return {"active": False, "reason": "not expiry day"}`
    — deliberately, it is the expiry-day charm read — and `dealer_magnet` exists
    precisely because the magnet itself is useful on the other four days too.
    Calling the expiry-only module meant this row reported ❓ for most of every
    week.

    Max pain is read from the option chain, which is the only place it is
    published (`analyze_option_chain` → `max_pain_strike`). The Market Picture
    carries `oi_pin` but has no `max_pain` key, so passing `mp.get("max_pain")`
    silently handed the pin chooser None and left it with one candidate instead
    of two.
    """
    max_pain = _f(_map(ss.get("_cached_option_data")).get("max_pain_strike"))
    try:
        from .dealer_magnet import from_market_picture as _pin
        read = _pin(bool(ss.get("_is_expiry_today")), spot, mp, max_pain) or {}
    except Exception:
        read = {}
    pin = _f(read.get("pin")) or _f(_first(mp.get("oi_pin"))) or max_pain
    if pin is None or spot is None:
        return _na_row(STRUCTURE, B_DEALERS, "Charm Pin / Magnet",
                       str(read.get("reason") or "no pin strike available"))
    dist = pin - spot
    if abs(dist) <= AT_BAND:
        return _row(STRUCTURE, B_DEALERS, "Charm Pin / Magnet", _rupees(pin),
                    f"🧲 At {_rupees(pin)}", NEUTRAL,
                    "price pinned — no directional edge here", level=pin)
    # A magnet is a pull, not a trend: it is directional while price is away
    # from it, and stops meaning anything once price arrives.
    return _row(STRUCTURE, B_DEALERS, "Charm Pin / Magnet", _rupees(pin),
                f"🧲 Pull {'↑' if dist > 0 else '↓'} toward {_rupees(pin)} ({dist:+,.0f})",
                BULL if dist > 0 else BEAR,
                str(read.get("drift") or "dealer hedging drag")
                + (" · expiry" if read.get("expiry") else ""), level=pin)


def _leg_bands(ltp: float) -> Tuple[float, float]:
    """`(at, near)` for a leg, as a fraction of its own premium.

    Index points cannot be reused here: ₹5 is a touch on a ₹300 leg and a
    different world on a ₹20 one. The floor keeps a near-worthless expiry-day
    leg from having a band of nothing.

    ⚠️ The near band is HALF the premium, and that is deliberate rather than
    sloppy. It has been 2% and then 5%, and both were wrong for the same
    reason: they are index-trader intuitions about distance applied to a
    leveraged instrument. An option premium routinely travels tens of per cent
    in a session — a call at ₹5.75 reaching ₹7.50 is a thirty per cent move and
    an ordinary morning — so a 5% band called that pivot "far" and abstained on
    a level sitting right on top of the premium.

    The gate's job is NOT to be a tight interaction band. It exists to exclude
    levels the premium **cannot reach** — the stale zone at ₹84 that the same
    ₹5.75 call was still voting on. Fifty per cent does that job with a wide
    margin (₹84 is 1,361% away) while letting the levels actually in front of
    the premium report.
    """
    at = max(ltp * 0.005, 0.25)
    # `at * 2` keeps the two bands ordered on a leg worth a few paise, where the
    # floor would otherwise put the "at" band outside the "near" one.
    return at, max(ltp * 0.50, at * 2)


def _distance_word(price: float, level: float, at: float, near: float
                   ) -> Tuple[str, str, Tuple[Optional[str], Optional[bool]]]:
    """`(icon, word, verdict)` for a price against a level it may be nowhere
    near.

    The verdict is an `ABOVE` — which side of the level price is on — and is
    empty unless the level is close enough to be in play. Resolving it into
    "holding" needs the role and belongs to `_holding`; returning it as a bare
    boolean is what let a leg's resistance rows read backwards, exactly as the
    index rows did.
    """
    gap = abs(price - level)
    if gap <= at:
        return "🟡", "At", (None, None)
    if gap > near:
        return "⚪", "Far from", (FAR, None)
    return (("🟢", "Above", (ABOVE, True)) if price > level
            else ("🔴", "Below", (ABOVE, False)))


def _prefer_align(preferred: Optional[str], ce_e: Optional[float],
                  pe_e: Optional[float]) -> str:
    """Stage 71.7's premium preference → a NIFTY direction.

    `preferred` is one of `premium_energy`'s four words. CALL and PUT map to
    bull and bear; "No Edge" and "Avoid Both" are a decision not to call it, and
    are honoured as neutral rather than second-guessed by the raw scores.

    With no verdict at all, the two energy scores decide — that is the only
    case where this compares them.
    """
    word = str(preferred or "").upper()
    if "CALL" in word:
        return BULL
    if "PUT" in word:
        return BEAR
    if word:                       # "No Edge" / "Avoid Both" — a real answer
        return NEUTRAL
    if ce_e is None and pe_e is None:
        return NEUTRAL
    ce, pe = (ce_e or 0.0), (pe_e or 0.0)
    return BULL if ce > pe else BEAR if pe > ce else NEUTRAL


def _energy_read(ss: Mapping[str, Any]) -> Dict[str, Any]:
    """CALL / PUT energy as numbers, for the bar pair.

    The Premium Energy row already words this; the dashboard wants to draw it,
    and re-deriving it there would be the same lookup twice with two chances to
    drift. Same source, same fallback (`bridge` then `sides`) as the row.
    """
    pe = _map(ss.get("_premium_energy"))
    bridge = _map(pe.get("bridge"))
    score = _map(bridge.get("energy_score")) or _map(pe.get("energy_score"))
    ce, put = _f(score.get("CALL")), _f(score.get("PUT"))
    if ce is None and put is None:
        sides = _map(pe.get("sides"))
        ce = _f(_map(sides.get("CALL")).get("energy"))
        put = _f(_map(sides.get("PUT")).get("energy"))
    if ce is None and put is None:
        return {}
    preferred = (bridge.get("preferred_premium")
                 or _map(pe.get("preferred")).get("preferred"))
    return {"CALL": ce, "PUT": put,
            "preferred": str(preferred) if preferred else None,
            "winner": ("CALL" if (ce or 0) > (put or 0) else
                       "PUT" if (put or 0) > (ce or 0) else None)}


def _premium(ss: Mapping[str, Any], zones: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The option side: energy, each leg's own S/R and HVP lines, and the two
    premiums themselves — all measured on the LEG's axis, never the index's.

    Every direction here goes through `bias_ball`, so the PUT inversion (a PUT
    holding its support means NIFTY is falling) is applied in exactly one place.
    """
    rows: List[Dict[str, Any]] = []

    pe_energy = _map(ss.get("_premium_energy"))
    # ⚠️ `energy_score` lives on the BRIDGE, not at the top level.
    #
    # Stage 71.7 publishes its nine downstream fields under `["bridge"]`
    # (`premium_energy.BRIDGE_KEYS`) precisely so a consumer reads one flat
    # contract instead of walking `sides["CALL"]["energy"]`. Reading
    # `_premium_energy["energy_score"]` finds nothing on every cycle — which is
    # what made this row report "not published" while the panel beside it drew
    # the numbers. `sides` is the fallback, so a future reshuffle of the bridge
    # degrades this row rather than blanking it.
    bridge = _map(pe_energy.get("bridge"))
    score = _map(bridge.get("energy_score")) or _map(pe_energy.get("energy_score"))
    ce_e, pe_e = _f(score.get("CALL")), _f(score.get("PUT"))
    if ce_e is None and pe_e is None:
        sides = _map(pe_energy.get("sides"))
        ce_e = _f(_map(sides.get("CALL")).get("energy"))
        pe_e = _f(_map(sides.get("PUT")).get("energy"))
    if ce_e is not None or pe_e is not None:
        # The engine's own verdict — "Prefer CALL" / "Prefer PUT" / "No Edge" —
        # which is a preference between premiums, not a NIFTY direction: a
        # preferred CALL is bullish, a preferred PUT bearish.
        bias = (bridge.get("preferred_premium")
                or _map(pe_energy.get("preferred")).get("preferred"))
        bias = str(bias) if bias else None
        rows.append(_row(
            PREMIUM, B_OPTIONS, "Premium Energy",
            f"CE {ce_e:.0f} / PE {pe_e:.0f}" if ce_e is not None and pe_e is not None
            else (f"CE {ce_e:.0f}" if ce_e is not None else f"PE {pe_e:.0f}"),
            ("⚡ CALL loaded" if (ce_e or 0) > (pe_e or 0) else
             "⚡ PUT loaded" if (pe_e or 0) > (ce_e or 0) else "⚖️ balanced"),
            # More energy on the CALL side is participation in upside; on the
            # PUT side, downside. The engine's own `preferred` verdict wins when
            # it is there.
            #
            # ⚠️ NOT `direction_bias`: that reads BULL/BEAR/UP/DOWN words, and
            # Stage 71.7 speaks in "Prefer CALL" / "Prefer PUT" / "No Edge" /
            # "Avoid Both" — none of which it recognises, so every row came back
            # neutral. A preferred CALL premium is bullish for the index and a
            # preferred PUT bearish; "No Edge" and "Avoid Both" are genuinely
            # neither and must stay neutral rather than falling through to the
            # score comparison, which would overrule the engine that just
            # declined to call it.
            _prefer_align(bias, ce_e, pe_e),
            bias or "which side is carrying the participation"))
    else:
        # Two different faults, and they need different people to look at them:
        # the stage never ran (its panel is upstream, on the Trading tab), or it
        # ran and reported no score. One message for both sent me checking the
        # bridge path twice for what was an absent key.
        rows.append(_na_row(
            PREMIUM, B_OPTIONS, "Premium Energy",
            "Stage 71.7 published no energy score for either side"
            if pe_energy else
            "Stage 71.7 has not published — its panel runs on the Trading tab"))

    profiles = _map(ss.get("_leg_profiles"))
    vob = _map(ss.get("_atm_leg_vob_volume"))
    ltps = _map(ss.get("_atm_leg_ltp"))

    # ⚠️ The leg NAME is resolved from the stores that hold the data, not from
    # `_leg_profiles`.
    #
    # This is the bug that emptied the whole section. `_atm_leg_ltp` and
    # `_atm_leg_vob_volume` are filled at step 7, before the MIOS pass;
    # `_leg_profiles` — and with it `call_label` / `put_label` — is published
    # later, by the charts tab inside Dashboard V6. Taking the name from the
    # late producer meant that whenever it had not published, every option row
    # said "not published this cycle" while the premiums and their zones sat in
    # session state the whole time.
    #
    # `leg_keys` owns the "exact ATM wins, nearest offset falls back" rule, so
    # this picks the same leg the terminal charts do. The published labels are
    # still preferred when present — if the charts resolved a leg, this table
    # must describe that leg and not a different one.
    # The union of both stores, because a leg can have a premium without VOB
    # zones (too few bars to form one) and the row set should not shrink for it.
    _keys = set(ltps) | set(vob) | set(_map(ss.get("_atm_leg_dfs")))
    _resolved = dict(zip(("CALL", "PUT"), _leg_keys.call_put(_keys)))
    #: buy-volume share per leg, as `analyze_vob_volume` measured it inside the
    #: zone the premium is actually at. Collected here rather than re-derived
    #: for the battle card, so the card and the row quote one number.
    buy_pct: Dict[str, Optional[float]] = {}

    def _leg_label(chart: str) -> Optional[str]:
        """The published label when it still names a live leg, else the one
        resolved from the stores.

        The `in _keys` test is the point. The ATM strike drifts through the
        session and the stores are rebuilt each cycle around the new one, so a
        label held over from an earlier cycle can name a strike that is no
        longer loaded — and preferring it blindly reproduces the empty section
        it was supposed to fix, only intermittently and around the drift.
        """
        published = profiles.get(f"{chart.lower()}_label")
        if published and str(published) in _keys:
            return str(published)
        return _resolved.get(chart)

    labels = {"PUT": _leg_label("PUT"), "CALL": _leg_label("CALL")}

    for chart in ("PUT", "CALL"):
        name = labels.get(chart)
        ltp = _f(ltps.get(name)) if name else None
        legzones = vob.get(name) if name else None
        legzones = legzones if isinstance(legzones, (list, tuple)) else ()
        # A leg's own S/R comes from ITS VOB zones — bullish = support,
        # bearish = resistance — which `analyze_vob_volume` already attributed
        # and classified. `status` is the behaviour; nothing is re-derived.
        for role, zone_type in (("support", "bullish"), ("resistance", "bearish")):
            check = f"{chart} LTP {role.title()}"
            got = [z for z in (legzones or ())
                   if isinstance(z, Mapping) and z.get("zone_type") == zone_type]
            if not got or ltp is None:
                # ⚠️ "not published" is a plumbing claim, and it was being made
                # about a working engine. `analyze_vob_volume` runs per leg and
                # returns only the zones it finds — a leg with bearish blocks
                # and no bullish ones is a real market state (common near
                # expiry, when nothing has built below the premium), not a
                # missing producer. Saying so sends the reader to the chart
                # instead of to the store.
                if ltp is None:
                    why = "no leg premium published"
                elif legzones:
                    why = (f"the engine found no {role} zone on this leg "
                           f"({len(legzones)} zone(s), none {zone_type})")
                else:
                    why = "no VOB zones published for this leg"
                rows.append(_na_row(PREMIUM, B_OPTIONS, check, why))
                continue
            mids = [m for m in (_f(z.get("mid")) for z in got) if m is not None]
            nearest = min(got, key=lambda z: abs((_f(z.get("mid")) or 0) - ltp))
            mid = _f(nearest.get("mid"))
            status = str(nearest.get("status") or "")
            _at, _near = _leg_bands(ltp)

            # ⚠️ Distance first, status second — and this ordering is the fix
            # for a row that was casting real votes on unreachable levels.
            #
            # `analyze_vob_volume`'s `status` describes what the flow did INSIDE
            # the zone; it is not a claim that price is interacting with it now.
            # On an expiry afternoon a CALL trading at ₹5.75 carried a zone at
            # ₹84 still marked INTACT — "sellers held the majority in there",
            # perfectly true, and fifteen times away from any price the leg can
            # reach. Taken as a live read it voted BEAR into the summary.
            #
            # A zone outside the leg's own near band is not doing anything to
            # the premium, and `_room_align` turns that absence into the read it
            # is: a resistance the premium is clear of is room for it to rise; a
            # support far below it is nothing holding it up. The zone's own
            # `status` is deliberately dropped here — it describes flow INSIDE a
            # zone the price has left, and quoting it as a live verdict is what
            # had a ₹5.75 call voting on an ₹84 level.
            if mid is None or abs(mid - ltp) > _near:
                _, _, _verdict = _distance_word(ltp, mid or 0.0, _at, _near)
                align = _resolve(chart, role, _verdict, True)
                position = f"{BALLS.get(align, '⚪')} {_room_text(mid, ltp, role)}"
                remark = (f"premium is clear of it by "
                          f"{abs((mid or 0) - ltp):,.2f} — "
                          + ("room above" if not _is_support(role)
                             else "nothing beneath"))
            else:
                # BUILDING / INTACT = the zone is doing its job; BREAKING = it
                # failed; FADING = flow turned against it but it has not gone.
                holding = (True if status in ("BUILDING", "INTACT") else
                           False if status == "BREAKING" else None)
                icon = {"BUILDING": "🟢", "INTACT": "🟢",
                        "BREAKING": "🔴", "FADING": "🟠"}.get(status, "🟡")
                position = (f"{icon} {status.title() or 'Unclassified'} "
                            f"{_rupees(mid)}")
                remark = (f"{nearest.get('dominant') or '—'} dominant · "
                          f"{_f(nearest.get('bull_pct')) or 0:.0f}% buy volume")
                align = _level_align(chart, role, holding)
                buy_pct[chart] = _f(nearest.get("bull_pct"))
            rows.append(_row(
                PREMIUM, B_OPTIONS, check, _levels_text(_by_distance(mids, ltp), 2),
                position, align, remark, levels=mids))

        # The premium itself. Reported, never scored: a price is not a
        # direction, and the leg's S/R rows above are where its behaviour votes.
        rows.append(_row(PREMIUM, B_OPTIONS, f"{chart} LTP Price",
                         _rupees(ltp), "—", INFO,
                         f"{name} — current premium" if name else "leg not resolved",
                         levels=[ltp] if ltp is not None else None)
                    if ltp is not None else
                    _na_row(PREMIUM, B_OPTIONS, f"{chart} LTP Price",
                            "leg frame not published this cycle"))

        # The leg's own HVP lines, against its own LTP.
        prof = _map(profiles.get(chart))
        for side, role in (("HIGH", "resistance"), ("LOW", "support")):
            check = f"{chart} HVP {side}"
            pts = _hv_prices(prof, side)
            if not pts or ltp is None:
                # ⚠️ Say which half is missing. Blaming the pivots for an absent
                # premium sent me looking at `volume_points` for a fault that
                # was one store away — and would send the next reader there too.
                rows.append(_na_row(
                    PREMIUM, B_OPTIONS, check,
                    "no high-volume pivots on this leg's frame" if ltp is not None
                    else "no leg premium published — cannot place the lines"))
                continue
            nearest = _nearest_to(pts, ltp)
            _at, _near = _leg_bands(ltp)
            icon, word, _verdict = _distance_word(ltp, nearest or 0.0, _at, _near)
            # `hvp_bias` owns HIGH→resistance / LOW→support plus the PUT
            # inversion; `_resolve` adds the hold/break flip when the premium is
            # at the line, and the room read when it is clear of it.
            align = _resolve(chart, role, _verdict, True)
            _pos = (_room_text(nearest, ltp, role) if _verdict[0] == FAR
                    else f"{word} {_rupees(nearest)}")
            rows.append(_row(
                PREMIUM, B_OPTIONS, check, _levels_text(_by_distance(pts, ltp), 2),
                f"{BALLS.get(align, icon)} {_pos}", align,
                f"LTP {_rupees(ltp)} · {len(pts)} line(s)", observed=False,
                levels=pts))
    # The buy share belongs to the LEG, not to the zone row that measured it —
    # the battle card wants it beside the premium. Attached here so both quote
    # the same number rather than each finding its own.
    for r in rows:
        check = str(r.get("check") or "")
        if check.endswith("LTP Price"):
            r["buy_pct"] = buy_pct.get(check.split()[0])
    return rows


def _final(fr: Mapping[str, Any], mp: Mapping[str, Any], spot: Optional[float],
           zones: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The war zone — ONE row, because there is one war zone.

    Stage 35 publishes a single contested price and the side it is being fought
    from: `battle_zone = {"type": "SUPPORT"|"RESISTANCE", "price": …}`. The
    type is not a property of the price — it is which way the fight is running,
    and it flips when the fight does. That is why this cannot be split into a
    support row and a resistance row: there are not two levels, there is one
    level with a changing role.

    Two reads, in order:

    1. **Who is winning**, from Stage 35's own `expected_winner` — "Buyers
       (bounce)", "Sellers (rejection)", "Contested". This is the engine's
       verdict on the war and it wins outright, including when it says
       Contested: an engine declining to call a fight is an answer, not a gap
       to fill.
    2. **What price is doing at the level**, only when no winner was published
       — the zone's own `type` decides whether holding reads bullish or
       bearish, exactly as any other level would.
    """
    bz = _map(fr.get("battle_zone"))
    price = _f(bz.get("price"))
    winner = fr.get("expected_winner")
    kind = str(bz.get("type") or "").upper()
    if price is None and not winner:
        return [_na_row(FINAL, B_STRUCTURE, "War Zone",
                        "no battle zone — price is not at a contested level")]

    # The role the zone is currently fighting from. Falls back to spot's side
    # of it if Stage 35 did not label it, which is the same inference the
    # acceptance strip makes.
    role = ("support" if kind == "SUPPORT" else
            "resistance" if kind == "RESISTANCE" else
            ("support" if (spot is not None and price is not None
                           and spot >= price) else "resistance"))

    text, verdict, observed = _interaction(price, spot, zones, role)
    if price is not None and spot is not None and abs(spot - price) <= AT_BAND:
        text = f"🟣 Inside war zone {_rupees(price)}"

    align = (_bb.winner_bias(winner) if winner
             else _resolve("NIFTY", role, verdict, True))

    bits = [f"fighting as {role}"]
    if winner:
        bits.append(f"winner: {winner}")
    probs = _map(fr.get("probabilities"))
    if probs:
        bits.append(" · ".join(f"{k} {v}%" for k, v in probs.items()))
    return [_row(FINAL, B_STRUCTURE, "War Zone",
                 _rupees(price) if price is not None else "—", text, align,
                 " · ".join(bits), observed, level=price)]


# ── the summary ──────────────────────────────────────────────────────────────

def _verdict(bull: int, bear: int) -> str:
    if bull > bear:
        return BULL
    if bear > bull:
        return BEAR
    return NEUTRAL


def summarise(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Count the vote, per bucket and overall.

    ⚠️ **`na` rows are counted and then excluded from every denominator.** The
    agreement ratio is *majority / active*, where active means the checks that
    actually reported — so a cycle where half the producers are quiet reads as
    "8 of 11 active checks agree", not as a diluted 8 of 28. Reporting the
    latter would make a confident read look weak for a reason that has nothing
    to do with the market.
    """
    tally = {BULL: 0, BEAR: 0, NEUTRAL: 0, NA: 0, INFO: 0}
    groups: Dict[str, Dict[str, int]] = {b: {BULL: 0, BEAR: 0} for b in BUCKETS}
    for r in rows:
        a = r.get("align")
        if a not in tally:
            continue
        tally[a] += 1
        b = r.get("bucket")
        if a in (BULL, BEAR) and b in groups:
            groups[b][a] += 1

    verdicts = {b: _verdict(g[BULL], g[BEAR]) for b, g in groups.items()}
    # A bucket that reported nothing directional has no verdict at all, rather
    # than a neutral one it did not earn.
    for b, g in groups.items():
        if g[BULL] == 0 and g[BEAR] == 0:
            verdicts[b] = NA

    net = _verdict(tally[BULL], tally[BEAR])
    active = tally[BULL] + tally[BEAR] + tally[NEUTRAL]
    majority = max(tally[BULL], tally[BEAR])

    # The conflict is the minority that is worth naming: the strongest rows
    # pointing against the net read. Shown because a 14-8 split and a 14-0 one
    # are different trades, and the table alone does not say which this is.
    against = BEAR if net == BULL else BULL if net == BEAR else None

    def _phrase(r: Mapping[str, Any]) -> str:
        """How a row reads in one clause.

        A level row's evidence is its interaction ("Rejecting ₹24,400"); a
        context row has no level to be at, so its evidence is its value
        ("BEARISH"). Taking `position` unconditionally is what produced
        "News — —" in the WHY line: a dash quoted as if it were a reason.
        """
        pos = str(r.get("position") or "").strip()
        detail = pos if pos and pos != "—" else str(r.get("value") or "").strip()
        return f"{r.get('check')} — {detail}" if detail and detail != "—" \
            else str(r.get("check"))

    conflicts = [_phrase(r) for r in rows
                 if against and r.get("align") == against][:4]
    supporting = [_phrase(r) for r in rows
                  if net in (BULL, BEAR) and r.get("align") == net][:4]

    return {
        "bull": tally[BULL], "bear": tally[BEAR],
        "neutral": tally[NEUTRAL], "na": tally[NA], "info": tally[INFO],
        "groups": verdicts,
        "net": net,
        "active": active,
        "agreement": majority,
        "why": supporting,
        "conflicts": conflicts,
    }


# ── the dashboard: the same read, arranged to be seen in ten seconds ────────
#
# Twenty-one rows of five columns is a complete answer and a slow one. Every
# figure below is already in `rows` — nothing here reads session state a second
# time or scores anything again. It groups, sorts and counts what the checklist
# already decided, so the dashboard and the table can never disagree.

#: two levels within this many points are one rung on the ladder. The magnet and
#: the PUT wall are routinely the same strike, and drawing them as two lines a
#: pixel apart says "two things" where the market has one.
RUNG_TOLERANCE = 12.0

#: agreement below this is a lean, not an alignment. A net read carried by a
#: third of the active checks is a different trade from one carried by all of
#: them, and printing only "BEARISH" hides which it is.
LOW_CONVICTION = 0.50
HIGH_CONVICTION = 0.70

CONVICTION = ("LOW", "MODERATE", "HIGH")


def conviction(summary: Mapping[str, Any]) -> Tuple[str, int]:
    """`(word, percent)` — how much of the active vote the net read carries.

    ⚠️ This is the number the table was hiding. "🔴 BEARISH" over 7 of 21
    checks and "🔴 BEARISH" over 19 of 21 are the same three words and
    completely different trades. The percent is majority / active, so an
    unavailable check neither helps nor hurts.
    """
    active = int(summary.get("active") or 0)
    if not active:
        return CONVICTION[0], 0
    pct = round(int(summary.get("agreement") or 0) / active * 100)
    word = (CONVICTION[2] if pct >= HIGH_CONVICTION * 100 else
            CONVICTION[1] if pct >= LOW_CONVICTION * 100 else CONVICTION[0])
    return word, pct


def ladder(rows: Sequence[Mapping[str, Any]],
           spot: Optional[float]) -> List[Dict[str, Any]]:
    """Every index level as a price map, highest first, with spot in place.

    Built from the ROWS, not from session state — one source for the table and
    the map, so a level cannot appear on one and not the other. Only index-axis
    rows carry a `level`; a premium sorted into this would land nonsensically
    between two index prices.

    Levels within `RUNG_TOLERANCE` collapse into one rung, because the magnet
    and the PUT wall sitting on the same strike are one thing to trade against,
    not two lines a pixel apart.
    """
    pts = [(r["level"], r) for r in rows
           if _f(r.get("level")) is not None and r.get("check") != "Spot Price"]
    rungs: List[Dict[str, Any]] = []
    for price, row in sorted(pts, key=lambda t: -t[0]):
        if rungs and abs(rungs[-1]["price"] - price) <= RUNG_TOLERANCE:
            rungs[-1]["labels"].append(row.get("check"))
            rungs[-1]["aligns"].append(row.get("align"))
            continue
        rungs.append({"price": price, "labels": [row.get("check")],
                      "aligns": [row.get("align")], "spot": False})
    # One rung per level, then spot slotted in at its own place — it is the
    # reference the whole map is read against, not another level on it.
    if spot is not None:
        at = next((i for i, r in enumerate(rungs) if r["price"] < spot),
                  len(rungs))
        rungs.insert(at, {"price": spot, "labels": ["SPOT"], "aligns": [INFO],
                          "spot": True})
    for r in rungs:
        # The rung's colour is its strongest claim: one direction if its rows
        # agree, neutral if they disagree OR reported neutral, ❓ only when
        # every row on it went quiet. Collapsing "they disagree" and "nobody
        # reported" into one glyph loses the difference between a contested
        # level and an absent one.
        kinds = {a for a in r["aligns"] if a in (BULL, BEAR)}
        if len(kinds) == 1:
            r["align"] = kinds.pop()
        elif kinds or NEUTRAL in r["aligns"]:
            r["align"] = NEUTRAL
        else:
            r["align"] = INFO if r["spot"] else NA
        r["distance"] = (None if spot is None or r["spot"]
                         else round(r["price"] - spot))
    return rungs


#: what a leg's own premium is doing, on its OWN axis.
#:
#: ⚠️ Not the same as the row's alignment, and the difference is the whole
#: point of the battle card. Every leg row is published in NIFTY terms — a PUT
#: holding its support votes BEAR, because a strong put means a falling index.
#: Read back the other way, that same row says the PUT premium is STRONG.
#: Showing "🔴 Bear" in a card headed "PUT SIDE" would have the trader reading
#: it as the put being weak.
STRONG, WEAK = "STRONG", "WEAK"


def _energy_band(score: Optional[float]) -> Optional[str]:
    """Stage 71.7's own word for an energy score. None when it did not report."""
    if score is None:
        return None
    try:
        from .premium_energy import energy_band
        return energy_band(score)
    except Exception:
        return None


def leg_strength(chart: str, nifty_align: str) -> Optional[str]:
    """A leg row's NIFTY direction → what that says about the PREMIUM.

    A CALL reads straight (bullish for NIFTY = the call is strong); a PUT
    inverts, for the same reason `bias_ball` inverts it on the way out. This is
    that mapping run backwards, and it lives here so the battle card cannot
    invent a second one.
    """
    if nifty_align not in (BULL, BEAR):
        return None
    up = nifty_align == BULL
    return (STRONG if up else WEAK) if str(chart).upper() == "CALL" \
        else (WEAK if up else STRONG)


def leg_ladder(rows: Sequence[Mapping[str, Any]], chart: str
               ) -> List[Dict[str, Any]]:
    """One leg's own levels as a price map, with its premium in place.

    The same idea as the index ladder and deliberately a separate map: a ₹107
    call premium and a 24,050 index level share no axis. Built from the rows'
    `levels`, so the ladder and the text beside it cannot name different prices.
    """
    mine = [r for r in rows if str(r.get("check", "")).startswith(chart + " ")]
    ltp = next((r["levels"][0] for r in mine
                if str(r.get("check", "")).endswith("LTP Price") and r["levels"]),
               None)
    pts: List[Tuple[float, Mapping[str, Any]]] = []
    for r in mine:
        if str(r.get("check", "")).endswith("LTP Price"):
            continue
        label = str(r["check"])[len(chart) + 1:]
        for v in r.get("levels") or ():
            pts.append((v, {"label": label, "align": r.get("align")}))
    rungs: List[Dict[str, Any]] = []
    for price, meta in sorted(pts, key=lambda t: -t[0]):
        # a leg's levels cluster proportionally — ₹0.50 apart is one line on a
        # ₹5 premium and two on a ₹300 one
        tol = max(abs(price) * 0.01, 0.05)
        if rungs and abs(rungs[-1]["price"] - price) <= tol:
            rungs[-1]["labels"].append(meta["label"])
            continue
        rungs.append({"price": price, "labels": [meta["label"]],
                      "align": meta["align"], "ltp": False})
    if ltp is not None:
        at = next((i for i, r in enumerate(rungs) if r["price"] < ltp), len(rungs))
        rungs.insert(at, {"price": ltp, "labels": ["LTP NOW"], "align": INFO,
                          "ltp": True})
    return rungs


def _leg_card(rows: Sequence[Mapping[str, Any]], chart: str,
              energy: Mapping[str, Any]) -> Dict[str, Any]:
    """One side of the CE/PE battle: premium, energy, buy share, its own map.

    Every figure is a leg row the table already built. The card's own verdict
    is the majority of what its rows say about the PREMIUM (`leg_strength`),
    which is why it can read "PUT STRONG" while those same rows vote bearish
    for the index — that is the conflict the card exists to show.
    """
    mine = [r for r in rows if str(r.get("check", "")).startswith(chart + " ")]
    price_row = next((r for r in mine
                      if str(r.get("check", "")).endswith("LTP Price")), {})
    fields = [{"name": str(r["check"])[len(chart) + 1:], "value": r.get("value"),
               "align": r.get("align"), "note": r.get("position"),
               "strength": leg_strength(chart, r.get("align"))}
              for r in mine if not str(r["check"]).endswith("LTP Price")]
    return {
        "chart": chart,
        "leg": price_row.get("remark"),
        "premium": price_row.get("value"),
        "buy_pct": price_row.get("buy_pct"),
        "energy": _f(_map(energy).get(chart)),
        # ⚠️ The band is Stage 71.7's, not this module's.
        #
        # The first attempt scored the card by a majority of its own level rows
        # — invented here, and it read STRONG for a call whose energy was 30,
        # because a resistance far overhead and a pivot just below outvoted the
        # one row that mattered. `premium_energy.energy_band` already answers
        # "is this premium strong" on the scale the rest of the app uses
        # (0-20 Dead · 21-40 Weak · 41-60 Healthy · 61-80 Strong), so it is
        # asked rather than second-guessed.
        "state": _energy_band(_f(_map(energy).get(chart))),
        "fields": fields,
        "ladder": leg_ladder(rows, chart),
    }


def dashboard(read: Mapping[str, Any]) -> Dict[str, Any]:
    """The ten-second view over a read `build()` already produced.

    Takes the built read rather than session state, so there is exactly one
    pass over the market per cycle and the dashboard is provably the same data
    as the table beneath it.
    """
    rows = list(read.get("rows") or [])
    summary = _map(read.get("summary"))
    spot = _f(read.get("spot"))
    by_check = {str(r.get("check")): r for r in rows}
    word, pct = conviction(summary)

    def _row_of(name: str) -> Mapping[str, Any]:
        return _map(by_check.get(name))

    # the four headline levels, from the rows that already found them
    heads = {
        "spot": _row_of("Spot Price").get("value"),
        "support": _row_of("NIFTY Support").get("value"),
        "resistance": _row_of("NIFTY Resistance").get("value"),
        "magnet": _row_of("Charm Pin / Magnet").get("value"),
    }

    # what is pushing each way — the directional rows, named, most useful first
    order = ("Charm Pin / Magnet", "PUT Wall OI", "CALL Wall OI",
             "NIFTY Support", "NIFTY Resistance", "War Zone", "NIFTY POC",
             "NIFTY HVP LOW", "NIFTY HVP HIGH", "Gamma Flip", "Dealer GEX",
             "Dealer DEX", "Premium Energy")
    rank = {n: i for i, n in enumerate(order)}
    directional = sorted((r for r in rows if r.get("align") in (BULL, BEAR)),
                         key=lambda r: rank.get(str(r.get("check")), 99))
    # ⚠️ Each entry carries its BUCKET. Without it the three columns below can
    # only be handed the global bull/bear list, and every bearish column shows
    # the same three rows — the dealer magnet appearing under OPTIONS, the PUT
    # wall under DEALERS. A column that names drivers it does not own is worse
    # than a column that names none.
    def _entry(r):
        return {"check": r["check"], "bucket": r.get("bucket"),
                "why": r.get("position") or r.get("value"),
                "remark": r.get("remark")}

    pressure = {BULL: [_entry(r) for r in directional if r["align"] == BULL],
                BEAR: [_entry(r) for r in directional if r["align"] == BEAR]}

    # CALL vs PUT energy, for the bar pair. Straight off the Premium Energy row
    # the table already built — the numbers are Stage 71.7's.
    energy = _map(read.get("energy"))

    return {
        "spot": spot,
        "net": summary.get("net") or NEUTRAL,
        "conviction": word,
        "conviction_pct": pct,
        "counts": {k: summary.get(k, 0)
                   for k in ("bull", "bear", "neutral", "na", "info")},
        "agreement": summary.get("agreement", 0),
        "active": summary.get("active", 0),
        "groups": summary.get("groups") or {},
        # ⚔️ CONFLICTED when the buckets disagree with each other. Not the same
        # as low conviction: a read can be thin because little reported, or
        # thin because structure and options are pulling opposite ways, and
        # only the second is a conflict.
        "conflicted": len({v for v in (summary.get("groups") or {}).values()
                           if v in (BULL, BEAR)}) > 1,
        "heads": heads,
        "ladder": ladder(rows, spot),
        "pressure": pressure,
        "energy": energy,
        "legs": [_leg_card(rows, "CALL", energy),
                 _leg_card(rows, "PUT", energy)],
        "gate": _map(read.get("gate")),
    }


def build(ss: Mapping[str, Any]) -> Dict[str, Any]:
    """The whole checklist: `{'rows': [...], 'summary': {...}, 'spot': float}`.

    `ss` is the app's session state (any Mapping — the tests pass a dict). Every
    key read here was written by a producer earlier in the cycle; see the module
    docstring for why nothing is computed if a key is absent.
    """
    mp = _map(ss.get("_market_picture"))
    spot = _f(ss.get("_nifty_spot_live"))

    # The acceptance strip's published zones — the source of the interaction
    # column wherever a level has an observed read.
    zones = ss.get("_la_zones_latest") or []
    zones = [z for z in zones if isinstance(z, Mapping)]

    # The war zone and the canonical S/R fallbacks come from the Final Read.
    # It is a transport over the pass result `_mios_state`, and `build_final_read`
    # is its owner — so it is CALLED, exactly as `mios_v6_snapshot` calls it,
    # rather than having its fields re-derived here from the stages behind it
    # (principle 12a: one bridge, not thirty reads).
    fr: Mapping[str, Any] = {}
    try:
        from .final_read import build_final_read
        fr = build_final_read(ss.get("_mios_state")) or {}
    except Exception:
        fr = {}
    fr = _map(fr)

    rows: List[Dict[str, Any]] = []
    rows += _structure(ss, mp, spot, zones, fr)
    rows += _premium(ss, zones)
    rows += _final(fr, mp, spot, zones)
    # ⚠️ The gate is TRANSPORTED, not recomputed. `compute_market_picture`
    # already owns the entry decision — its state, target, invalidation and R:R
    # — and a second verdict here would be the one thing this module exists not
    # to be: two answers to "do I trade this", disagreeing on the same screen.
    return {"rows": rows, "summary": summarise(rows), "spot": spot,
            "energy": _energy_read(ss),
            "gate": _map(mp.get("entry_gate"))}
