"""MIOS — the Market Alignment Checklist. One table, one question.

> **Where is spot now, which levels and forces are active, and does each one
> point BULL or BEAR?**

The app answers that in twenty places. Regime lives in the Market Picture, the
walls in the option chain, dealer posture in the Greeks panel, premium in the
energy card, leg structure in the cockpit — each correct, each in its own box,
and nobody can see at a glance what agrees with what. This module puts every one
of those reads on one line each, in a single table, and counts the vote.

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
GENERAL = "GENERAL CONTEXT"
STRUCTURE = "NIFTY STRUCTURE"
PREMIUM = "OPTION PREMIUM / LTP"
FINAL = "FINAL INTERACTION"

#: summary buckets — the five verdicts under the table. A row's bucket is
#: independent of the section it is DISPLAYED in: regime is shown under general
#: context but votes with structure, because that is what it describes.
B_STRUCTURE = "STRUCTURE"
B_OPTIONS = "OPTIONS"
B_FLOW = "FLOW"
B_DEALERS = "DEALERS"
B_GLOBAL = "GLOBAL"
BUCKETS = (B_STRUCTURE, B_OPTIONS, B_FLOW, B_DEALERS, B_GLOBAL)

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
HELD = "held"
ABOVE = "above"

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
        return f"⚪ Far from {_rupees(level)} ({d:+,.0f})", (None, None)
    return ((f"🟢 Above {_rupees(level)} ({d:+,.0f})", (ABOVE, True)) if d > 0
            else (f"🔴 Below {_rupees(level)} ({d:+,.0f})", (ABOVE, False)))


def _interaction(level: Optional[float], spot: Optional[float],
                 zones: Sequence[Mapping[str, Any]], role: Optional[str] = None
                 ) -> Tuple[str, Optional[bool], bool]:
    """The third column: `(text, holding, observed)`.

    `role` is what the level is acting as — a support or a resistance — and is
    required to answer "did it hold": both sources report which SIDE of the
    level price is on, and that means opposite things for the two roles.

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
            return (f"{icon} {phrase} {_rupees(level)}{war}",
                    _holding(role, verdict), True)
    text, verdict = _positional(level, spot)
    return text, _holding(role, verdict), False


# ── the alignment column ─────────────────────────────────────────────────────

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


def _row(group: str, bucket: str, check: str, value: str, position: str,
         align: str, remark: str = "", observed: bool = True) -> Dict[str, Any]:
    return {"group": group, "bucket": bucket, "check": check, "value": value,
            "position": position, "align": align, "remark": remark,
            "observed": bool(observed)}


def _na_row(group: str, bucket: str, check: str, why: str) -> Dict[str, Any]:
    """A check whose producer did not report. It still occupies a line — a
    silently dropped row is indistinguishable from a check nobody thought of,
    and the trader cannot ask why a number is missing that is not on screen."""
    return _row(group, bucket, check, "—", "—", NA, why, observed=False)


def _level_row(group: str, bucket: str, check: str, level: Optional[float],
               spot: Optional[float], zones: Sequence[Mapping[str, Any]],
               chart: str, role: str, remark: str = "",
               missing: str = "not published this cycle") -> Dict[str, Any]:
    """One S/R-shaped row: a price, what spot is doing at it, what that means."""
    if level is None:
        return _na_row(group, bucket, check, missing)
    text, holding, observed = _interaction(level, spot, zones, role)
    return _row(group, bucket, check, _rupees(level), text,
                _level_align(chart, role, holding), remark, observed)


# ── the sections ─────────────────────────────────────────────────────────────

def _general(ss: Mapping[str, Any], mp: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """News · FII/DII · Sector · Global · Regime — the environment the trade
    happens in. Every value is read off the Market Picture's own published
    bias objects, which is where those panels already deposited them."""
    rows: List[Dict[str, Any]] = []

    nb = mp.get("news_bias")
    if isinstance(nb, Mapping) and nb.get("label"):
        rows.append(_row(GENERAL, B_GLOBAL, "News", str(nb["label"]), "—",
                         _bb.direction_bias(nb.get("label")),
                         f"{nb.get('n', 0)} headlines · net {_f(nb.get('net')) or 0:+.0f}"))
    else:
        rows.append(_na_row(GENERAL, B_GLOBAL, "News", "no headline read published"))

    cash = _map(ss.get("_fii_dii_cash"))
    if cash:
        fii = _f(_map(cash.get("FII")).get("net"))
        dii = _f(_map(cash.get("DII")).get("net"))
        if fii is not None or dii is not None:
            # The institutional vote is FII's; DII is shown because it is the
            # other half of the same print, but it is reported, not scored —
            # netting the two here would be a new formula, and no panel in the
            # app nets them.
            rows.append(_row(
                GENERAL, B_FLOW, "FII / DII",
                f"FII {fii:+,.0f}cr · DII {dii:+,.0f}cr" if fii is not None and dii is not None
                else (f"FII {fii:+,.0f}cr" if fii is not None else f"DII {dii:+,.0f}cr"),
                "—",
                BULL if (fii or 0) > 0 else BEAR if (fii or 0) < 0 else NEUTRAL,
                "FII cash net (EOD) — DII shown, not scored"))
        else:
            rows.append(_na_row(GENERAL, B_FLOW, "FII / DII", "no net values in the feed"))
    else:
        rows.append(_na_row(GENERAL, B_FLOW, "FII / DII", "cash feed not published"))

    sb = mp.get("sector_bias")
    if isinstance(sb, Mapping) and sb.get("rotation"):
        rot = str(sb["rotation"])
        up = "RISK-ON" in rot.upper()
        dn = "RISK-OFF" in rot.upper()
        rows.append(_row(GENERAL, B_GLOBAL, "Sector", rot, "—",
                         BULL if up else BEAR if dn else NEUTRAL,
                         f"breadth {sb.get('breadth')}% advancing"))
    else:
        rows.append(_na_row(GENERAL, B_GLOBAL, "Sector", "rotation snapshot too thin"))

    gb = mp.get("global_bias")
    if isinstance(gb, Mapping) and gb.get("label"):
        rows.append(_row(GENERAL, B_GLOBAL, "Global", str(gb["label"]), "—",
                         _bb.direction_bias(gb.get("label")),
                         f"score {_f(gb.get('score')) or 0:+.1f} across global indices"))
    else:
        rows.append(_na_row(GENERAL, B_GLOBAL, "Global", "global indices not published"))

    cb = mp.get("commodity_bias")
    if isinstance(cb, Mapping) and cb.get("regime"):
        reg = str(cb["regime"])
        rows.append(_row(GENERAL, B_GLOBAL, "Commodity", reg, "—",
                         BULL if "ON" in reg.upper() and "OFF" not in reg.upper()
                         else BEAR if "OFF" in reg.upper() else NEUTRAL,
                         "risk appetite from the commodity complex"))
    else:
        rows.append(_na_row(GENERAL, B_GLOBAL, "Commodity", "commodity read not published"))

    reg = mp.get("regime")
    if reg:
        # The regime is the Market Picture's own confidence-weighted verdict —
        # this row transports it and its probabilities, and votes with structure
        # because that is what a regime describes.
        rows.append(_row(GENERAL, B_STRUCTURE, "Regime", str(reg),
                         f"{mp.get('em', '')} {reg}".strip(),
                         BULL if reg == "UP" else BEAR if reg == "DOWN" else NEUTRAL,
                         f"↑{mp.get('p_up', '—')}% ↓{mp.get('p_down', '—')}% "
                         f"↔{mp.get('p_side', '—')}%"))
    else:
        rows.append(_na_row(GENERAL, B_STRUCTURE, "Regime", "Market Picture has no read yet"))
    return rows


def _structure(ss: Mapping[str, Any], mp: Mapping[str, Any], spot: Optional[float],
               zones: Sequence[Mapping[str, Any]],
               fr: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Spot, the walls, S/R, the war zone, POC, the HVP lines and dealer
    posture — everything measured on the index's own axis."""
    rows: List[Dict[str, Any]] = []

    rows.append(_row(STRUCTURE, B_STRUCTURE, "Spot Price",
                     _rupees(spot) if spot is not None else "—",
                     "AT" if spot is not None else "—", INFO,
                     "live index — the reference every other row measures against")
                if spot is not None else
                _na_row(STRUCTURE, B_STRUCTURE, "Spot Price", "no live spot"))

    # OI walls. `writing_bias` owns the direction — PUT writing builds a floor
    # (bullish), CE writing caps (bearish) — so the wall rows read it through
    # the level rule for consistency with every other level row.
    rows.append(_level_row(STRUCTURE, B_STRUCTURE, "PUT Wall OI",
                           _f(_first(mp.get("oi_floor"))), spot, zones,
                           "NIFTY", "support", "PE writers' floor",
                           "no PE wall ranked"))
    rows.append(_level_row(STRUCTURE, B_STRUCTURE, "CALL Wall OI",
                           _f(_first(mp.get("oi_ceiling"))), spot, zones,
                           "NIFTY", "resistance", "CE writers' cap",
                           "no CE wall ranked"))

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

    # War zone — the contested band. `low`/`high` when the zone carries them,
    # otherwise the single battle price the Final Read published.
    bz = _map(fr.get("battle_zone"))
    bz_p = _f(bz.get("price"))
    lo, hi = _f(bz.get("low")), _f(bz.get("high"))
    if lo is None and hi is None and bz_p is not None:
        lo = hi = bz_p
    if lo is not None:
        rows.append(_level_row(STRUCTURE, B_STRUCTURE, "War Zone Support", lo, spot,
                               zones, "NIFTY", "support", "contested band floor"))
    else:
        rows.append(_na_row(STRUCTURE, B_STRUCTURE, "War Zone Support",
                            "no battle zone in the Final Read"))
    if hi is not None:
        rows.append(_level_row(STRUCTURE, B_STRUCTURE, "War Zone Resistance", hi, spot,
                               zones, "NIFTY", "resistance", "contested band ceiling"))
    else:
        rows.append(_na_row(STRUCTURE, B_STRUCTURE, "War Zone Resistance",
                            "no battle zone in the Final Read"))

    # POC — acceptance above value is bullish, below bearish. Same level rule.
    mf = _map(ss.get("_money_flow_data"))
    rows.append(_level_row(STRUCTURE, B_STRUCTURE, "NIFTY POC",
                           _f(mf.get("poc_price")), spot, zones,
                           "NIFTY", "support", "session value — acceptance vs rejection",
                           "no session profile"))

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
        text, holding, observed = _interaction(nearest, spot, zones, role)
        rows.append(_row(STRUCTURE, B_STRUCTURE, check, _levels_text(_by_distance(pts, spot)),
                         text, _level_align("NIFTY", role, holding),
                         f"{len(pts)} pivot line(s) · nearest {_rupees(nearest)}", observed))

    # ── dealer posture ──
    gx = _map(ss.get("_gex_data"))
    rows.append(_level_row(STRUCTURE, B_DEALERS, "Gamma Flip",
                           _f(gx.get("gamma_flip_level")), spot, zones,
                           "NIFTY", "support",
                           "above flip = dealers dampen, below = they amplify",
                           "no gamma flip published"))

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
                    "price pinned — no directional edge here")
    # A magnet is a pull, not a trend: it is directional while price is away
    # from it, and stops meaning anything once price arrives.
    return _row(STRUCTURE, B_DEALERS, "Charm Pin / Magnet", _rupees(pin),
                f"🧲 Pull {'↑' if dist > 0 else '↓'} toward {_rupees(pin)} ({dist:+,.0f})",
                BULL if dist > 0 else BEAR,
                str(read.get("drift") or "dealer hedging drag")
                + (" · expiry" if read.get("expiry") else ""))


def _leg_bands(ltp: float) -> Tuple[float, float]:
    """`(at, near)` for a leg, as a fraction of its own premium.

    Index points cannot be reused here: ₹5 is a touch on a ₹300 leg and a
    different world on a ₹20 one. The floors keep a near-worthless expiry-day
    leg from having a band of nothing.

    ⚠️ The near band is 5% of the premium, not the 2% it started at. Two per
    cent of an option is about one minute's movement — a ₹100 leg travels ₹2
    without anything happening — so nearly every pivot and zone fell outside it
    and abstained, and the summary filled up with ⚪ from rows that had a
    perfectly good read. Five per cent is still a tight window, and still
    excludes by a wide margin the case this gate exists for: a ₹5.75 leg
    carrying a stale zone at ₹84.
    """
    return max(ltp * 0.005, 0.25), max(ltp * 0.05, 0.5)


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
        return "⚪", "Far from", (None, None)
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
            # So a zone outside the leg's own near band reports its distance and
            # abstains, exactly as the index rows and the leg HVP rows already
            # do. Every other level in this table is gated this way; this one
            # was not, and it was the only one that could vote from that far
            # out.
            if mid is None or abs(mid - ltp) > _near:
                icon, word, _verdict = _distance_word(ltp, mid or 0.0, _at, _near)
                holding = _holding(role, _verdict)
                position = f"{icon} {word} {_rupees(mid)}"
                remark = (f"zone {status.lower() or 'unclassified'}, but "
                          f"{abs((mid or 0) - ltp):,.2f} away — not in play")
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
            rows.append(_row(
                PREMIUM, B_OPTIONS, check, _levels_text(_by_distance(mids, ltp), 2),
                position, _level_align(chart, role, holding), remark))

        # The premium itself. Reported, never scored: a price is not a
        # direction, and the leg's S/R rows above are where its behaviour votes.
        rows.append(_row(PREMIUM, B_OPTIONS, f"{chart} LTP Price",
                         _rupees(ltp), "—", INFO,
                         f"{name} — current premium" if name else "leg not resolved")
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
            holding = _holding(role, _verdict)
            rows.append(_row(
                PREMIUM, B_OPTIONS, check, _levels_text(_by_distance(pts, ltp), 2),
                f"{icon} {word} {_rupees(nearest)}",
                # `hvp_bias` owns HIGH→resistance / LOW→support plus the PUT
                # inversion; the hold/break flip is applied on top of it.
                _level_align(chart, role, holding),
                f"LTP {_rupees(ltp)} · {len(pts)} line(s)", observed=False))
    return rows


def _final(fr: Mapping[str, Any], mp: Mapping[str, Any], spot: Optional[float],
           zones: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Who is winning the contested band — the Final Read's own verdict."""
    bz = _map(fr.get("battle_zone"))
    price = _f(bz.get("price"))
    winner = fr.get("expected_winner")
    if price is None and not winner:
        return [_na_row(FINAL, B_STRUCTURE, "War Zone",
                        "no battle zone — price is not at a contested level")]
    if price is not None and spot is not None:
        d = spot - price
        pos = ("🟣 Inside war zone" if abs(d) <= AT_BAND else
               f"🟢 Above {_rupees(price)} ({d:+,.0f})" if d > 0 else
               f"🔴 Below {_rupees(price)} ({d:+,.0f})")
    else:
        pos = "—"
    return [_row(FINAL, B_STRUCTURE, "War Zone",
                 _rupees(price) if price is not None else "—", pos,
                 _bb.winner_bias(winner),
                 f"expected winner: {winner}" if winner else "contested — no winner called")]


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
    rows += _general(ss, mp)
    rows += _structure(ss, mp, spot, zones, fr)
    rows += _premium(ss, zones)
    rows += _final(fr, mp, spot, zones)
    return {"rows": rows, "summary": summarise(rows), "spot": spot}
