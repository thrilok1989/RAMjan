"""MIOS V6 — the Adaptive Greeks layer. Context and confirmation, never a call.

## What this answers

> What is price doing, what are traders doing, what are dealers likely to do
> next, is volatility confirming the move, and does all of that **support or
> weaken** the Guardian verdict?

Not *"which greek predicts the next candle"*. The distinction is the whole
module: greeks describe the terrain a move has to cross. They do not name the
direction of travel.

## The hierarchy, and why the order is the design

    1. PRICE + OI/ΔOI + CVD      what is actually happening        PRIMARY
    2. GEX + DEX                 how dealer hedging will react
    3. VANNA + CHARM             is hedging adding pressure, or a magnet
    4. IV + SKEW                 is volatility confirming the move
    5. GUARDIAN                  the decision — made elsewhere

Layer 1 is measured. Layers 2–4 are *conditions*. A condition can raise or lower
confidence in what layer 1 saw; it can never replace it. So:

* `dealer_posture` is **relative to a flow direction handed in** — it answers
  "does hedging help or hurt THIS move", never "which way is the market going".
* `charm` and `vanna` produce a pressure sign and a magnet distance. Neither
  returns a bias.
* `volatility` returns *confirming · diverging · silent* against a price
  direction, never a direction of its own.

## ⚠️ It emits no recommendation. Ever.

`read()` returns no `side`, no `action`, no `entry`. `assert_no_recommendation`
enforces that on the output, and a test calls it on every regime. The Guardian
consumes this; this does not pre-empt the Guardian.

What it *does* return are **modifiers**: a confidence delta and five
probabilities (breakout · fade · pin · continuation · reversal), each with the
evidence that produced it. Rule 15 of the specification — every conclusion
carries its evidence — is why every scorer returns `(score, evidence)` rather
than a bare number.

## It computes no market data

Every input is already owned and published:

    GEX · gamma flip · magnet     `calculate_dealer_gex`      → gex_disp
    DEX · net delta · tilt        `calculate_dealer_dex`      → dex_bias
    net vanna · net charm         `calculate_vanna_charm_exposure` → vc_exp
    IV skew · put/call IV         `calculate_iv_skew`         → skew_bias
    ATM IV series                 the chain                   → _iv_history
    regime · pin · ΔOI · flow     `compute_market_picture`    → _market_picture
    the expiry charm pin          `mios_v5.charm_pin.read`

⚠️ In particular the expiry pin is **consumed from `charm_pin`**, not re-derived.
That module already owns the rule, its wording and its `context_only` flag, and a
second implementation would let the Trade Card and this layer disagree about
whether the day is pinned.

Pure and deterministic: same inputs, same output, no clock, no network, no
`session_state`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

#: Advisory, always. Mirrors `charm_pin.context_only` so a consumer can check one
#: flag across both modules.
ADVISORY_ONLY = True

#: The regimes weights are chosen by.
REGIMES: Tuple[str, ...] = (
    "RANGE", "TREND_UP", "TREND_DOWN", "EXPIRY", "HIGH_VOLATILITY",
    "PINNED", "BREAKOUT", "FAKEOUT",
)

#: The six layer scores, in hierarchy order.
LAYERS: Tuple[str, ...] = (
    "price_flow", "oi_positioning", "dealer", "vanna", "charm", "volatility",
)

#: Regime → layer → weight.
#:
#: ⚠️ Read the columns, not the numbers: `price_flow` is never below 3.0 in any
#: regime, and `charm` never above it except on EXPIRY. That is the specification's
#: rule 2 and rule 10 expressed as data — *price and real-time order flow remain
#: primary*, and *normal days stay driven by price + OI/ΔOI + CVD*.
#:
#: TREND_UP/TREND_DOWN deliberately DROP charm (1.0). Rule 6: a strong trend must
#: not be faded just because a magnet exists overhead. EXPIRY raises charm and
#: gamma to match price flow, because on expiry day the chain stops being a
#: forecast and becomes a force.
WEIGHTS: Dict[str, Dict[str, float]] = {
    "RANGE":           {"price_flow": 3.0, "oi_positioning": 3.0, "dealer": 3.0,
                        "vanna": 2.0, "charm": 2.0, "volatility": 2.0},
    "TREND_UP":        {"price_flow": 4.0, "oi_positioning": 4.0, "dealer": 3.0,
                        "vanna": 2.5, "charm": 1.0, "volatility": 2.5},
    "TREND_DOWN":      {"price_flow": 4.0, "oi_positioning": 4.0, "dealer": 3.0,
                        "vanna": 2.5, "charm": 1.0, "volatility": 2.5},
    "EXPIRY":          {"price_flow": 4.0, "oi_positioning": 3.0, "dealer": 4.0,
                        "vanna": 3.0, "charm": 4.0, "volatility": 3.0},
    "HIGH_VOLATILITY": {"price_flow": 4.0, "oi_positioning": 3.0, "dealer": 3.5,
                        "vanna": 3.0, "charm": 1.5, "volatility": 3.5},
    # ⚠️ `price_flow` is 3.5 here, not 3.0. The first draft had charm and dealer
    # at 3.5 ABOVE a price_flow of 3.0, and `test_price_flow_outweighs_every_greek_in_every_regime`
    # caught it: that inversion is rule 2 broken — the one regime where a greek
    # became the primary predictor. A pin may MATCH price flow in importance; it
    # may not outrank it.
    "PINNED":          {"price_flow": 3.5, "oi_positioning": 2.5, "dealer": 3.5,
                        "vanna": 2.0, "charm": 3.5, "volatility": 2.0},
    "BREAKOUT":        {"price_flow": 4.0, "oi_positioning": 3.5, "dealer": 3.5,
                        "vanna": 2.5, "charm": 1.5, "volatility": 3.0},
    "FAKEOUT":         {"price_flow": 3.5, "oi_positioning": 3.0, "dealer": 3.5,
                        "vanna": 2.0, "charm": 3.0, "volatility": 2.5},
}

#: IV move (in vol points) that counts as expansion rather than noise.
IV_MOVE = 0.35

#: How close spot must be to a dealer magnet for it to be exerting force. The
#: same number `charm_pin.NEAR_POINTS` uses, imported rather than re-chosen so
#: the two modules cannot disagree about what "near" means.
try:                                            # pragma: no cover - import glue
    from .charm_pin import NEAR_POINTS
except Exception:                               # pragma: no cover
    NEAR_POINTS = 120.0


# ══════════════════════════════════════════════════════════════════════
#  helpers — nothing invents a number
# ══════════════════════════════════════════════════════════════════════

def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _m(v: Any) -> Mapping[str, Any]:
    """⚠️ `Mapping`, not `dict` — MIOS freezes payloads as `MappingProxyType`,
    which is not a dict subclass."""
    return v if isinstance(v, Mapping) else {}


def _word(v: Any) -> str:
    return str(v or "").strip().upper()


def _sign_of(label: Any) -> int:
    """+1 bullish · -1 bearish · 0 neither, from a published bias word."""
    t = _word(label)
    if any(w in t for w in ("BULL", "UP", "BUY", "POSITIVE")):
        return 1
    if any(w in t for w in ("BEAR", "DOWN", "SELL", "NEGATIVE")):
        return -1
    return 0


def _clamp(x: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# ══════════════════════════════════════════════════════════════════════
#  1 · the regime
# ══════════════════════════════════════════════════════════════════════

def regime(market_picture: Any = None, is_expiry: bool = False,
           pin: Any = None, iv_state: Any = None,
           reaction: Any = None) -> Tuple[str, List[str]]:
    """Which regime the weights should come from, and the evidence for it.

    A **classification of published reads**, not a new measurement: the trend
    comes from `compute_market_picture`'s own regime, the pin from `charm_pin`,
    expiry from the chain, volatility from the IV state built below.

    Order matters and is deliberate. EXPIRY outranks everything because on
    expiry day the hedging mechanics dominate whatever else is true; PINNED
    outranks a trend because a live pin is the nearer constraint; a trend
    outranks RANGE.
    """
    ev: List[str] = []
    mp = _m(market_picture)
    mp_regime = _word(mp.get("regime"))

    if is_expiry:
        ev.append("expiry day — hedging mechanics dominate")
        return "EXPIRY", ev

    if _m(pin).get("active"):
        d = _f(_m(pin).get("distance"))
        ev.append(f"charm pin active{f' · {abs(d):.0f} pts away' if d is not None else ''}")
        return "PINNED", ev

    vol = _word(_m(iv_state).get("state"))
    if vol == "EXPANDING" and mp_regime in ("UP", "DOWN"):
        ev.append(f"IV expanding into a {mp_regime.lower()} regime")
        return "HIGH_VOLATILITY", ev

    # A break that is not being accepted is the specification's FAKEOUT, and
    # Stage 42 already publishes that judgement — it is read, not re-derived.
    react = _word(_m(reaction).get("state") or reaction)
    if "BREAK" in react and "ACCEPT" not in react:
        ev.append(f"reaction read: {react.title()}")
        return "FAKEOUT" if "FAIL" in react or "REJECT" in react else "BREAKOUT", ev

    if mp_regime == "UP":
        ev.append("Market Picture regime: UP")
        return "TREND_UP", ev
    if mp_regime == "DOWN":
        ev.append("Market Picture regime: DOWN")
        return "TREND_DOWN", ev

    ev.append("Market Picture regime: sideways" if mp_regime
              else "no regime published — defaulting to range weights")
    return "RANGE", ev


# ══════════════════════════════════════════════════════════════════════
#  2 · layer 1 — what is actually happening (PRIMARY)
# ══════════════════════════════════════════════════════════════════════

def price_flow_score(flow: Any = None) -> Tuple[Optional[float], List[str]]:
    """Signed −100..+100 from price direction and real order flow.

    The primary layer, and the only one allowed to carry a direction on its own.
    `flow` is read from what the app already published: the regime word, the
    order-flow imbalance label and the CVD sign.
    """
    f = _m(flow)
    ev: List[str] = []
    parts: List[float] = []

    for key, label, weight in (("regime", "price", 40.0),
                               ("order_flow", "order flow", 35.0),
                               ("cvd", "CVD", 25.0)):
        raw = f.get(key)
        sign = _sign_of(raw) if not isinstance(raw, (int, float)) else (
            1 if raw > 0 else -1 if raw < 0 else 0)
        if isinstance(raw, bool) or raw is None or raw == "":
            continue
        if sign:
            parts.append(sign * weight)
            ev.append(f"{label} {'bullish' if sign > 0 else 'bearish'}")
        else:
            ev.append(f"{label} flat")
    if not parts and not ev:
        return None, ["no price or flow read published"]
    return _clamp(sum(parts)), ev


def oi_score(doi: Any = None) -> Tuple[Optional[float], List[str]]:
    """Signed −100..+100 from where fresh positions are building.

    `compute_market_picture` already words this — *"Bullish (PE writers building
    support)"* — so the word is read and the label is carried into the evidence
    verbatim rather than re-phrased.
    """
    node = _m(doi)
    label = node.get("label") if node else doi
    if not str(label or "").strip():
        return None, ["no ΔOI read published"]
    sign = _sign_of(label)
    if not sign:
        return 0.0, [f"ΔOI: {label}"]
    return (60.0 * sign), [f"ΔOI: {label}"]


# ══════════════════════════════════════════════════════════════════════
#  3 · layer 2 — dealer positioning (posture, never direction)
# ══════════════════════════════════════════════════════════════════════

def dealer_posture(gex: Any = None, dex: Any = None, spot: Any = None,
                   flow_sign: int = 0) -> Dict[str, Any]:
    """Does dealer hedging **help or hurt** the move layer 1 saw?

    ⚠️ Returns a posture relative to `flow_sign`, never a bias. That is rule 4 of
    the specification — never convert GEX/DEX into BUY/SELL — expressed as an API
    that structurally cannot: there is no direction in the return value, only
    SUPPORTIVE / OPPOSING / NEUTRAL and an amplification word.

    * positive total GEX → dealers hedge *against* movement → stabilising, and
      **opposing whichever way flow is pushing**
    * negative total GEX → hedging amplifies movement → supportive of a move,
      in either direction
    * DEX tilt agreeing with flow adds support; against it, opposition
    """
    g, d = _m(gex), _m(dex)
    ev: List[str] = []
    total = _f(g.get("total"))
    flip = _f(g.get("flip"))
    sp = _f(spot)

    gamma = None
    if total is not None:
        gamma = "POSITIVE" if total > 0 else "NEGATIVE" if total < 0 else "FLAT"
        ev.append(f"total GEX {total:+,.0f}L → {gamma.lower()} gamma")

    support = 0.0
    if gamma == "NEGATIVE":
        support += 1.0
        ev.append("negative gamma amplifies movement")
    elif gamma == "POSITIVE":
        support -= 1.0
        ev.append("positive gamma dampens movement — stabilising/pinning")

    dex_sign = _sign_of(d.get("bias") or d.get("label"))
    if dex_sign and flow_sign:
        if dex_sign == flow_sign:
            support += 1.0
            ev.append("dealer delta tilt agrees with flow")
        else:
            support -= 1.0
            ev.append("dealer delta tilt opposes flow")
    elif dex_sign:
        ev.append(f"dealer delta tilt {'bullish' if dex_sign > 0 else 'bearish'}"
                  " — no flow direction to compare")

    if flip is not None and sp is not None:
        side = "above" if sp > flip else "below"
        ev.append(f"spot {side} gamma flip {flip:,.0f}")

    posture = ("SUPPORTIVE" if support > 0 else
               "OPPOSING" if support < 0 else "NEUTRAL")
    if gamma is None and not dex_sign:
        posture = "UNKNOWN"
        ev = ["no dealer positioning published"]

    return {"posture": posture, "gamma": gamma, "gamma_flip": flip,
            "amplification": ("AMPLIFYING" if gamma == "NEGATIVE" else
                              "STABILISING" if gamma == "POSITIVE" else None),
            # ── what the posture is relative TO ──────────────────────────
            #
            # ⚠️ Added because "SUPPORTIVE" alone was read as "dealers back the
            # UP regime" in review. It never means that: `regime` is computed
            # after this and is not an input here. The posture is measured
            # against `flow_sign`, and with negative gamma "supportive" means
            # hedging amplifies movement — in EITHER direction.
            #
            # `None` when there is no flow direction to be supportive OF. The
            # posture word and `score` are deliberately left exactly as they
            # were — they feed `_modifiers`, and changing them would move a
            # decision when the defect was in the label. A display that finds
            # `relative_to is None` should say what dealers are doing to
            # movement instead of asserting support for nothing.
            "relative_to": ("flow" if flow_sign else None),
            "flow_sign": int(flow_sign or 0),
            "score": _clamp(support * 40.0), "evidence": ev}


# ══════════════════════════════════════════════════════════════════════
#  4 · layer 3 — vanna and charm (pressure and magnets)
# ══════════════════════════════════════════════════════════════════════

def hedging_pressure(vc: Any = None, magnet: Any = None, spot: Any = None,
                     pin: Any = None) -> Dict[str, Any]:
    """Hedging pressure and the nearest dealer magnet.

    ⚠️ A magnet is a **pull**, not a forecast. The specification is explicit
    about the wording and so is this: the output says *"₹24,450 is a dealer
    magnet — price may be pulled toward it, raising pin/fade risk"* and never
    *"price will reach 24,450"*.

    `magnet` is `gex_magnet`, which `calculate_dealer_gex` owns. No charm magnet
    is derived here: the per-strike charm frame is not published, and inventing a
    magnet strike from a net figure would be exactly the fabricated precision
    this layer exists to avoid. Net charm supplies the pressure SIGN; the strike
    comes from the owner.
    """
    node = _m(vc)
    ev: List[str] = []
    vanna = _f(node.get("net_vanna"))
    charm = _f(node.get("net_charm"))
    sp, mg = _f(spot), _f(magnet)

    if vanna is not None:
        ev.append(f"net vanna {vanna:+,.0f}")
    if charm is not None:
        ev.append(f"net charm {charm:+,.0f}")

    # ⚠️ `direction` is measured two different ways, and a single arrow on screen
    # hid which one produced it. `basis` names it, so a panel can say "magnet pull
    # ↓ ₹24,400" rather than the bare "hedging pressure ↓ downward" that was read
    # in review as an immediate dealer-flow measurement. It is not one: in the
    # magnet branch it is one subtraction, `magnet − spot`.
    direction, basis = "NEUTRAL", None
    if mg is not None and sp is not None:
        gap = mg - sp
        direction = ("UPWARD" if gap > 5 else "DOWNWARD" if gap < -5
                     else "NEUTRAL")
        basis = "magnet"
        ev.append(f"dealer magnet {mg:,.0f} · {gap:+.0f} pts from spot")
    elif charm is not None and charm != 0:
        # No magnet strike published — the sign still says which way the drag
        # runs, and saying so beats saying nothing.
        direction = "UPWARD" if charm > 0 else "DOWNWARD"
        basis = "net_charm"
        ev.append("magnet strike not published — direction from net charm only")

    near = (mg is not None and sp is not None
            and abs(mg - sp) <= NEAR_POINTS)
    pin_node = _m(pin)
    if pin_node.get("active"):
        ev.append("expiry charm pin active (charm_pin)")

    return {
        "direction": direction,
        #: Which measurement produced `direction` — `"magnet"` (magnet minus
        #: spot), `"net_charm"` (the sign only, no strike published), or `None`
        #: when nothing did. A panel must not word these two the same way: one
        #: names a level, the other names a drag with no level behind it.
        "basis": basis,
        "magnet": mg,
        "distance": (round(mg - sp, 1) if mg is not None and sp is not None
                     else None),
        "near": bool(near or pin_node.get("active")),
        "net_vanna": vanna, "net_charm": charm,
        # The sentence a panel prints, worded here so every surface says it the
        # same way. Never a prediction.
        "sentence": (
            f"₹{mg:,.0f} is a dealer magnet — price may be pulled toward it, "
            f"raising pin/fade risk." if mg is not None else
            "No dealer magnet published."),
        "score": _clamp((1.0 if near else 0.0) * -40.0),
        "evidence": ev,
    }


# ══════════════════════════════════════════════════════════════════════
#  5 · layer 4 — volatility confirmation
# ══════════════════════════════════════════════════════════════════════

def volatility_state(iv_series: Optional[Sequence[Any]] = None,
                     skew: Any = None,
                     price_sign: int = 0) -> Dict[str, Any]:
    """Is volatility CONFIRMING the move, diverging from it, or silent?

    ⚠️ Never a direction. Rule 5 — do not use IV alone to predict direction — so
    this returns `confirmation` against a price sign handed in, and the only
    directional word in the output is the caller's own.

        price ↑ + IV ↑   → expansion confirms
        price ↑ + IV ↓   → weak / mean-reverting
        price ↓ + put IV ↑ → downside fear confirms
        move with no IV response → confidence reduced
    """
    vals = [_f(v) for v in (iv_series or ())]
    vals = [v for v in vals if v is not None]
    ev: List[str] = []
    state, change = None, None
    if len(vals) >= 2:
        change = vals[-1] - vals[0]
        state = ("EXPANDING" if change >= IV_MOVE else
                 "CONTRACTING" if change <= -IV_MOVE else "FLAT")
        ev.append(f"ATM IV {vals[-1]:.2f} ({change:+.2f} over "
                  f"{len(vals)} samples) → {state.lower()}")
    elif vals:
        ev.append(f"ATM IV {vals[-1]:.2f} — no history to compare")
    else:
        ev.append("no IV history published")

    sk = _m(skew)
    skew_sign = _sign_of(sk.get("bias") or sk.get("label"))
    if sk.get("ratio") is not None:
        ev.append(f"put/call IV skew {sk.get('ratio')}"
                  + (f" · {sk.get('label')}" if sk.get("label") else ""))

    confirmation = "SILENT"
    if state and price_sign:
        if state == "EXPANDING":
            confirmation = "CONFIRMING"
            ev.append("IV expansion confirms the move")
        elif state == "CONTRACTING":
            confirmation = "DIVERGING"
            ev.append("IV contracting against the move — may be mean-reverting")
        else:
            ev.append("IV flat — no volatility confirmation either way")
    if price_sign < 0 and skew_sign < 0:
        confirmation = "CONFIRMING"
        ev.append("put skew confirms downside fear")

    score = {"CONFIRMING": 40.0, "DIVERGING": -40.0}.get(confirmation, 0.0)
    return {"state": state, "iv_change": (round(change, 2)
                                          if change is not None else None),
            "confirmation": confirmation, "skew_ratio": sk.get("ratio"),
            # ── ⚪ could not report, vs measured and quiet ─────────────────
            #
            # ⚠️ `confirmation` STARTS at "SILENT" and only moves off it when
            # `state and price_sign`. So with no IV history published, SILENT
            # means "nothing was measured" — and the card printed it as though it
            # were a reading. It was read in review as "IV isn't giving strong
            # confirmation", which is a conclusion about the market drawn from an
            # absence of data. Principle 9: MISSING is not 0.
            #
            # `confirmation` and `score` are unchanged — `conflicts()` already
            # guards this correctly by requiring `state` truthy before firing
            # NO_VOLATILITY_RESPONSE, so only the display was wrong.
            "reporting": state is not None,
            "why_silent": (None if state is not None else
                           ("no IV history published" if not vals else
                            "only one IV sample — no history to compare")),
            "score": score, "evidence": ev}


# ══════════════════════════════════════════════════════════════════════
#  6 · conflicts
# ══════════════════════════════════════════════════════════════════════

#: Conflict severity, worst first.
#:
#: ⚠️ Order matters because the panels lead their reason line with the FIRST
#: conflict. Found by rendering: a cycle that detected both FLOW_UNCONFIRMED and
#: FLOW_INTO_PIN displayed "high fade/pin risk" and never mentioned that nothing
#: confirmed the flow at all — the more serious of the two, and the one that
#: should decide whether to trade. Code order is not severity order, so severity
#: is written down.
CONFLICT_SEVERITY: Tuple[str, ...] = (
    "FLOW_UNCONFIRMED",            # nothing agrees — the strongest stand-aside
    "FLOW_INTO_PIN",               # a real setup with a real cap
    "FLOW_WITH_NEGATIVE_GAMMA",    # a real setup with real acceleration
    "NO_VOLATILITY_RESPONSE",      # a soft confidence trim
)


def conflicts(flow_sign: int, dealer: Any, pressure: Any,
              vol: Any) -> List[Dict[str, str]]:
    """The named disagreements the specification asks for, each with its verdict.

    A conflict is the most useful thing this layer produces: bullish flow into
    positive gamma with a magnet overhead is a real setup with a real risk, and
    collapsing it to one number would hide exactly the part a trader needs.
    """
    d, p, v = _m(dealer), _m(pressure), _m(vol)
    out: List[Dict[str, str]] = []

    if flow_sign and d.get("gamma") == "POSITIVE" and p.get("near"):
        out.append({
            "name": "FLOW_INTO_PIN",
            "verdict": "HIGH FADE / PIN RISK",
            "why": (f"{'Bullish' if flow_sign > 0 else 'Bearish'} flow, but "
                    f"positive gamma and a dealer magnet nearby cap the move.")})
    if flow_sign and d.get("gamma") == "NEGATIVE" and \
            v.get("confirmation") == "CONFIRMING":
        out.append({
            "name": "FLOW_WITH_NEGATIVE_GAMMA",
            "verdict": "MOMENTUM EXPANSION RISK HIGH",
            "why": (f"{'Bullish' if flow_sign > 0 else 'Bearish'} flow, "
                    f"negative gamma amplifies it, and IV confirms.")})
    if flow_sign and d.get("posture") == "OPPOSING" and \
            v.get("confirmation") == "DIVERGING":
        out.append({
            "name": "FLOW_UNCONFIRMED",
            "verdict": "HIGH FAKEOUT RISK",
            "why": "Flow has a direction but neither dealers nor IV confirm it."})
    if flow_sign and v.get("confirmation") == "SILENT" and v.get("state"):
        out.append({
            "name": "NO_VOLATILITY_RESPONSE",
            "verdict": "CONFIDENCE REDUCED",
            "why": "The move produced no volatility response."})
    # Worst first, so a panel leading with `conflicts[0]` leads with the reading
    # that should decide whether to trade rather than whichever check ran first.
    order = {name: i for i, name in enumerate(CONFLICT_SEVERITY)}
    out.sort(key=lambda c: order.get(c.get("name", ""), len(order)))
    return out


# ══════════════════════════════════════════════════════════════════════
#  7 · the read
# ══════════════════════════════════════════════════════════════════════

#: Keys that must NEVER appear in the output. Rule 14.
FORBIDDEN_KEYS = ("side", "action", "recommendation", "entry", "stop", "target",
                  "buy", "sell", "verdict")


def assert_no_recommendation(out: Mapping[str, Any]) -> None:
    """⚠️ Rule 14, enforced rather than intended.

    The Greeks layer may not create a trade recommendation. Checked on the output
    dict, because a docstring promising it would be worth nothing the first time
    somebody added a convenient `side` field.
    """
    for key in FORBIDDEN_KEYS:
        if key in out:
            raise ValueError(
                f"adaptive_greeks must not emit '{key}' — it modifies the "
                f"Guardian's confidence, it does not make the call (rule 14).")


def read(flow: Any = None, doi: Any = None, gex: Any = None, dex: Any = None,
         vc: Any = None, skew: Any = None, iv_series: Optional[Sequence] = None,
         spot: Any = None, magnet: Any = None, is_expiry: bool = False,
         pin: Any = None, market_picture: Any = None,
         reaction: Any = None) -> Dict[str, Any]:
    """The whole layer, in one deterministic pass.

    Returns layer scores, the regime and its weights, the adaptive score,
    conflicts, and the modifiers a Guardian consumer applies — plus the evidence
    behind each. **No side, no action, no recommendation.**
    """
    pf, pf_ev = price_flow_score(flow)
    oi, oi_ev = oi_score(doi)
    flow_sign = 0 if pf is None else (1 if pf > 10 else -1 if pf < -10 else 0)

    dealer = dealer_posture(gex, dex, spot, flow_sign)
    pressure = hedging_pressure(vc, magnet, spot, pin)
    vol = volatility_state(iv_series, skew, flow_sign)

    iv_state = {"state": vol.get("state")}
    reg, reg_ev = regime(market_picture, is_expiry, pin, iv_state, reaction)
    weights = dict(WEIGHTS.get(reg, WEIGHTS["RANGE"]))

    scores: Dict[str, Optional[float]] = {
        "price_flow": pf,
        "oi_positioning": oi,
        "dealer": dealer.get("score"),
        # vanna carries no independent direction; it shares the pressure score,
        # which is a RISK magnitude rather than a bias.
        "vanna": pressure.get("score"),
        "charm": pressure.get("score"),
        "volatility": vol.get("score"),
    }

    # Weighted only over layers that actually reported. A layer that said nothing
    # must not be averaged in as a zero — that is the `MISSING is not 0` rule,
    # and here it would quietly drag the score toward neutral.
    live = {k: v for k, v in scores.items() if v is not None}
    total_w = sum(weights[k] for k in live) or 1.0
    adaptive = _clamp(sum(live[k] * weights[k] for k in live) / total_w)

    cfl = conflicts(flow_sign, dealer, pressure, vol)
    mods = _modifiers(adaptive, flow_sign, dealer, pressure, vol, cfl, reg)

    out = {
        "stage": "Adaptive Greeks",
        "advisory_only": ADVISORY_ONLY,
        "context_only": True,
        "regime": reg,
        "regime_evidence": reg_ev,
        "weights": weights,
        "scores": scores,
        "missing": sorted(k for k, v in scores.items() if v is None),
        "adaptive_score": round(adaptive, 1),
        "flow_sign": flow_sign,
        "dealer": dealer,
        "pressure": pressure,
        "volatility": vol,
        "conflicts": cfl,
        "modifiers": mods,
        "evidence": list(pf_ev) + list(oi_ev) + list(dealer["evidence"])
                    + list(pressure["evidence"]) + list(vol["evidence"]),
    }
    assert_no_recommendation(out)
    return out


def _modifiers(adaptive: float, flow_sign: int, dealer: Mapping[str, Any],
               pressure: Mapping[str, Any], vol: Mapping[str, Any],
               cfl: Sequence[Mapping[str, str]], reg: str) -> Dict[str, Any]:
    """What a Guardian consumer applies: a confidence delta and five odds.

    Every number here is bounded and reversible. `confidence_delta` is capped at
    ±20 deliberately — the greeks layer may lean on a verdict, and may never
    swamp it (rule 1).
    """
    names = {c.get("name") for c in cfl}
    delta = 0.0
    why: List[str] = []

    # ⚠️ "movement, not an entry". These read "supports/opposes the move", which
    # was reported as the confusing part of the card: beneath a GUARDIAN WAIT it
    # looked like the greeks endorsing a trade the Guardian had refused.
    #
    # What the posture actually says is whether dealer hedging AMPLIFIES or DAMPS
    # movement (relative to flow — see `dealer_posture.relative_to`). It says
    # nothing about whether there is a valid entry, and with negative gamma it
    # amplifies in EITHER direction. The delta is unchanged; only the sentence is
    # more precise about its own scope.
    if dealer.get("posture") == "SUPPORTIVE":
        delta += 6.0
        why.append("dealer hedging supports movement, not an entry")
    elif dealer.get("posture") == "OPPOSING":
        delta -= 6.0
        why.append("dealer hedging damps movement")
    if vol.get("confirmation") == "CONFIRMING":
        delta += 6.0
        why.append("volatility confirms")
    elif vol.get("confirmation") == "DIVERGING":
        delta -= 8.0
        why.append("volatility diverges")
    if "FLOW_INTO_PIN" in names:
        delta -= 8.0
        why.append("magnet overhead caps the move")
    if "FLOW_UNCONFIRMED" in names:
        delta -= 6.0
        why.append("nothing confirms the flow")

    pin_risk = 70 if pressure.get("near") else 25
    if dealer.get("gamma") == "POSITIVE":
        pin_risk = min(90, pin_risk + 15)
    if reg in ("EXPIRY", "PINNED"):
        pin_risk = min(95, pin_risk + 10)

    fade = pin_risk if flow_sign else max(30, pin_risk - 15)
    breakout = 100 - fade
    if dealer.get("gamma") == "NEGATIVE":
        breakout = min(90, breakout + 15)
        fade = 100 - breakout
    continuation = int(_clamp(50 + adaptive * 0.35, 5, 95))
    reversal = 100 - continuation

    risk = ("HIGH" if fade >= 60 or "FLOW_UNCONFIRMED" in names else
            "MEDIUM" if fade >= 40 else "LOW")

    return {
        "confidence_delta": round(_clamp(delta, -20.0, 20.0), 1),
        "confidence_why": why,
        "pin_probability": int(pin_risk),
        "fade_probability": int(_clamp(fade, 5, 95)),
        "breakout_probability": int(_clamp(breakout, 5, 95)),
        "continuation_probability": continuation,
        "reversal_probability": reversal,
        "risk_level": risk,
    }


def apply_to(confidence: Any, out: Mapping[str, Any]) -> Optional[int]:
    """A Guardian confidence with this layer's delta applied, bounded 0–100.

    Offered as a helper so a consumer does not re-implement the clamp, and so the
    direction of the arithmetic is written down once. It takes a confidence and
    returns a confidence — it never takes or returns a side.
    """
    base = _f(confidence)
    if base is None:
        return None
    delta = _f(_m(out.get("modifiers")).get("confidence_delta")) or 0.0
    return int(max(0.0, min(100.0, base + delta)))
