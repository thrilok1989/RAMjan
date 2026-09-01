"""Stage 71.7 — Premium Energy Flow & Spike Probability.

Answers one question: **which premium currently has real participation, is that
participation growing or fading, is energy rotating, and which side has the
highest probability of explosive expansion?**

This is an orchestrator. It generates no market intelligence — it fuses reads
that Stages 11–52 and the native leg engines already published. Advisory only:
nothing here reaches the Entry Gate, Stage 52, the Trade Card or any alert, and
it never says "buy" or "sell".

## Energy is not Spike

The two are measured separately and must never be collapsed into one number:

* **Energy** — participation *now*. Is this premium being traded into?
* **Spike** — expansion *probability*. Is it coiled such that a small trigger
  produces a violent move?

A premium grinding steadily higher is high Energy, low Spike. A premium pinned
and compressed under a dealer wall is moderate Energy, high Spike. Reporting one
number would erase exactly the distinction a trader needs.

## Each side is scored on its own

CALL and PUT are scored independently, 0–100 each, and **never by subtraction**.
`call = 70, put = 65` is two live premiums; `call - put = 5` says "no edge",
which is false and is the specific error this module is built to avoid. Dominance
and Balance are *presentations* of the two independent scores, not sources of
them.

## The three mandatory inputs

**CBV · CSV · CVD**, per side, as numbers — not as the leg table's 🟢/🔴/⚪
glyphs. `flow_from_leg_totals()` sums `indicators/order_flow.totals()` across
each side's legs; the caller extracts, this module interprets. A glyph says
*which way*; CBV and CSV say *how much*, and a premium with 18.4M of buying is a
different fact from one with 0.4M pointing the same way.

The store behind them (`_atm_leg_ltf_delta`) lost its writer in the V6 reduction
and was restored in `vob_minimal._publish_atm_legs` for this stage.

## Stage 50 is the same question, so it is read rather than re-derived

Stage 50 already classifies each option side as **building · distribution ·
squeeze · unwinding**, and each pressure side as **absorbing · exhausted ·
building · weakening**. Deriving "premium accumulation" here from CVD would be a
second answer to a question that already has one — the failure Stage 53 exists
to fix, one level up. Stage 50 is read; nothing about it is recomputed.

## What it deliberately does NOT recompute

Stability is Stage 71's, built from Stages 44/47/54, and is passed through with
**Stage 44's own vocabulary** (`Stable · Unstable · Shock · Recovery`) rather
than translated into a second set of words.

## Stage 44 touches Stability and nothing else

Earlier this module also capped Spike when Stage 44 froze entries. Stage 71's
`stability()` already consumes `freeze_entries`, so the veto was being counted
twice — once as a band, once as a cap. The binding rule says Stability only, and
Spike now reacts solely to the participation and structure inputs below.

## What consumes this

**Stage 71.8** (Strike Validation) reads `out["bridge"]` and grades the strike
the trader picked on the side this stage named. It absorbed the Premium S/R
Analyzer that an earlier draft numbered 71.9, because "is this premium holding
its own levels" is one of the questions "is this strike worth trading" is made
of, and splitting them would have given two stages a claim on the same leg.

**Stage 72** (Entry) does not exist. It is named in `MISSING_INPUTS` rather than
assumed, because a bridge nobody consumes is a contract with one signature.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .decision import _grade

#: Inputs and consumers the spec asks for that no producer publishes yet.
#: Named, never zeroed.
MISSING_INPUTS: Tuple[str, ...] = (
    "entry_engine",             # Stage 72 — not built
)

#: The native spike engines the spec assumed. Removed by the V6 reduction
#: because no V6 stage read them; recorded so the absence is explainable rather
#: than mysterious when someone greps for them.
RETIRED_INPUTS: Dict[str, str] = {
    "compute_spike_probability": "removed in the V6 reduction — no V6 stage read it",
    "compute_ignition_score": "removed in the V6 reduction — no V6 stage read it",
    "compute_accum_dist_score": "removed in the V6 reduction — no V6 stage read it",
}

ADVISORY_ONLY = True

BULLISH, BEARISH, FLAT = "bull", "bear", "flat"

#: leg-row emoji → direction. The app renders `_em(dir)` as these three glyphs;
#: this is the only place that vocabulary is decoded.
_EMOJI_DIR = {"🟢": BULLISH, "🔴": BEARISH, "⚪": FLAT}

#: VOB zone status words the leg table publishes.
_VOB_BUILD = "BUILD"
_VOB_BREAK = "BREAK"
_VOB_FADE = "FADE"

#: Spike bands.
_SPIKE_BANDS = ((20, "Very Low"), (40, "Low"), (60, "Moderate"),
                (80, "High"), (100, "Extreme"))

#: Energy bands — the specification's five words, on its own edges.
#: `Dead` and `Healthy` exist because "a premium nobody is trading" and "a
#: premium being traded normally" are different findings, and a four-band scale
#: that starts at `Weak` cannot say the first one.
_ENERGY_BANDS = ((20, "Dead"), (40, "Weak"), (60, "Healthy"),
                 (80, "Strong"), (100, "Explosive"))

#: Energy components from the leg glyph table — direction of participation.
#: (row key, weight)
_ENERGY_SIGNALS: Tuple[Tuple[str, float], ...] = (
    ("CVD", 2.0),        # who is actually buying this premium
    ("MFP", 1.5),        # money-flow profile position
    ("VWAP", 1.5),
    ("VIDYA", 1.0),
    ("OIvel", 1.5),      # OI velocity on this strike
    ("S/R", 1.0),
)

#: Spike components — expansion probability. Deliberately a DIFFERENT set and
#: weighting from Energy; sharing them is how the two numbers become one.
_SPIKE_SIGNALS: Tuple[Tuple[str, float], ...] = (
    ("Ign", 2.5),        # ignition — the squeeze release read
    ("Div", 2.0),        # divergence — coiled disagreement
    ("Absorb", 2.0),     # absorption, whose RELEASE is the trigger
    ("VOB", 1.5),
    ("CVD", 1.0),
)

# ══════════════════════════════════════════════════════════════════════
#  vocabularies — one word per fact, reused from its owner
# ══════════════════════════════════════════════════════════════════════

#: Stage 44's own four words. Stage 71 bands stability numerically for its
#: ranking; this stage reports the word Stage 44 published, untranslated.
_STABILITY_WORDS = ("STABLE", "UNSTABLE", "SHOCK", "RECOVERY")

DOM_CALL, DOM_PUT = "CALL Dominant", "PUT Dominant"
DOM_BALANCED, DOM_NONE = "Balanced", "No Energy"

PREFER_CALL, PREFER_PUT = "Prefer CALL", "Prefer PUT"
PREFER_NONE, PREFER_AVOID = "No Edge", "Avoid Both"

#: Energy Shift — **seven** states.
#:
#: `Holding` is not a fallback, it is a reading. Energy that exists and is not
#: changing is a different fact from energy that is coiling: compression is a
#: measurable structure Stage 37 reports, and "nothing moved" is not evidence of
#: one. Mapping a flat cycle onto `Compressing` would assert a coil nobody
#: measured; onto `Decreasing`, a fall that did not happen.
SHIFT_EXPLODING = "Exploding"
SHIFT_INCREASING = "Increasing"
SHIFT_DECREASING = "Decreasing"
SHIFT_BUILDING = "Building"
SHIFT_DISTRIBUTING = "Distributing"
SHIFT_COMPRESSING = "Compressing"
SHIFT_HOLDING = "Holding"
SHIFT_UNKNOWN = "UNKNOWN"

#: The seven, in the order a trader reads them: fastest rise to fastest fall,
#: with the two structural states and the flat reading between.
SHIFT_STATES: Tuple[str, ...] = (
    SHIFT_EXPLODING, SHIFT_INCREASING, SHIFT_BUILDING, SHIFT_HOLDING,
    SHIFT_COMPRESSING, SHIFT_DISTRIBUTING, SHIFT_DECREASING,
)

#: Stage 50 option-side state → the Shift word it justifies. Read, not derived.
_S50_SHIFT = {"building": SHIFT_BUILDING, "distribution": SHIFT_DISTRIBUTING}

#: Top Trigger priority, most decisive first. **Exactly one is reported.**
#: A list of three reads as three findings; the trader needs to know which one
#: is carrying the setup.
TRIGGER_PRIORITY: Tuple[str, ...] = (
    "Dealer Wall",
    "Gamma Flip",
    "Absorption Release",
    "Acceptance Breakout",
    "VOB Breakout",
    "Money Flow Explosion",
    "OI Explosion",
    "Volume Explosion",
)
_TRIGGER_RANK = {name: i for i, name in enumerate(TRIGGER_PRIORITY)}

#: Stage 42 states that raise expansion probability, and by how much.
#: A confirmed break is executed evidence; a trap is the violent reversal that
#: expands the OTHER premium, which `_side_favoured` already routes.
_ACCEPTANCE_SPIKE = {
    "CONFIRMED_BREAKOUT": (85.0, "Acceptance Breakout"),
    "CONFIRMED_BREAKDOWN": (85.0, "Acceptance Breakout"),
    "ACCEPTANCE": (70.0, "Acceptance Breakout"),
    "BREAK": (60.0, "Acceptance Breakout"),
    "SWEEP_BUY": (75.0, "Absorption Release"),
    "SWEEP_SELL": (75.0, "Absorption Release"),
    "BULL_TRAP": (80.0, "Absorption Release"),
    "BEAR_TRAP": (80.0, "Absorption Release"),
    "FAILED_BREAKOUT": (65.0, "Absorption Release"),
    "FAILED_BREAKDOWN": (65.0, "Absorption Release"),
}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _band(pct: float, bands) -> str:
    for edge, word in bands:
        if pct <= edge:
            return word
    return bands[-1][1]


def spike_band(pct) -> str:
    """0–20 Very Low · 21–40 Low · 41–60 Moderate · 61–80 High · 81–100 Extreme."""
    p = _f(pct)
    return "Unknown" if p is None else _band(_clamp(p), _SPIKE_BANDS)


def energy_band(pct) -> str:
    """0–20 Dead · 21–40 Weak · 41–60 Healthy · 61–80 Strong · 81–100 Explosive."""
    p = _f(pct)
    return "Unknown" if p is None else _band(_clamp(p), _ENERGY_BANDS)


#: kept as the old public name so nothing that imported it breaks
strength_band = energy_band


# ══════════════════════════════════════════════════════════════════════
#  bridge 1 — the app's per-leg glyph rows → per-side directional reads
# ══════════════════════════════════════════════════════════════════════

def sides_from_leg_rows(rows: Optional[List[Dict[str, Any]]]
                        ) -> Dict[str, Dict[str, Any]]:
    """Split `_leg_bias_cache` rows into `{'CALL': {...}, 'PUT': {...}}`.

    The app publishes one row per ATM±1 leg, keyed `'Leg': 'ATM CE 24250'`, with
    each signal rendered as 🟢/🔴/⚪ *in the leg's own direction* — a rising CE
    and a rising PE are both 🟢 for their own premium. That is exactly what this
    engine wants: each premium's own participation, not a NIFTY translation.

    A row whose side cannot be read is **skipped, not guessed**. Counting an
    unparseable leg as flat would dilute a real read toward neutral.
    """
    out: Dict[str, Dict[str, Any]] = {
        "CALL": {"legs": 0, "signals": {}, "vob": []},
        "PUT": {"legs": 0, "signals": {}, "vob": []},
    }
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        side = side_of(row.get("Leg"))
        if side is None:
            continue
        bucket = out[side]
        bucket["legs"] += 1
        for key, val in row.items():
            d = _EMOJI_DIR.get(str(val).strip()[:1]) if val else None
            if d is None:
                continue
            bucket["signals"].setdefault(key, []).append(d)
        for zone in ("Sup VOB", "Res VOB"):
            txt = str(row.get(zone) or "")
            for word in (_VOB_BUILD, _VOB_BREAK, _VOB_FADE):
                if word in txt:
                    bucket["vob"].append(word)
                    break
    return out


def side_of(tag) -> Optional[str]:
    """`'ATM CE 24250'` → `'CALL'`. `None` when the side cannot be read.

    One decoder, used by both bridges, so the glyph rows and the flow totals can
    never disagree about which legs belong to which premium.
    """
    t = str(tag or "")
    if " CE " in f" {t} " or t.endswith("CE"):
        return "CALL"
    if " PE " in f" {t} " or t.endswith("PE"):
        return "PUT"
    return None


# ══════════════════════════════════════════════════════════════════════
#  bridge 2 — per-leg buyer/seller totals → Premium CBV · CSV · CVD
# ══════════════════════════════════════════════════════════════════════

def flow_from_leg_totals(items: Optional[Iterable[Tuple[Any, Dict[str, Any]]]]
                         ) -> Dict[str, Dict[str, Any]]:
    """`(leg_tag, order_flow.totals(...))` pairs → per-side CBV · CSV · CVD.

    Each side's legs are **summed**, not averaged: CBV is a volume, and the
    question "how much buying went into CALL premium" is answered by the total
    across the strikes a trader would actually use, not by their mean.

    `buy_share` is the derived read — `CBV / (CBV + CSV)`, 0–100. It is the only
    number here that is not a raw sum, and it is the one Energy consumes: a
    premium taking 78% of its volume on the bid is participating, whatever the
    glyph table says about direction.

    A side with no legs reporting returns `None` throughout — never `0`, which
    would read as "measured, and nobody traded it".
    """
    out: Dict[str, Dict[str, Any]] = {
        "CALL": {"cbv": None, "csv": None, "cvd": None, "volume": None,
                 "buy_share": None, "volume_share": None, "legs": 0},
        "PUT": {"cbv": None, "csv": None, "cvd": None, "volume": None,
                "buy_share": None, "volume_share": None, "legs": 0},
    }
    acc: Dict[str, List[float]] = {"CALL": [0.0, 0.0], "PUT": [0.0, 0.0]}
    for tag, tot in (items or []):
        side = side_of(tag)
        if side is None or not isinstance(tot, dict):
            continue
        buy, sell = _f(tot.get("buy_total")), _f(tot.get("sell_total"))
        if buy is None or sell is None:
            continue
        acc[side][0] += buy
        acc[side][1] += sell
        out[side]["legs"] += 1

    # `volume_share` is Premium Volume: how much of the pair's traded volume
    # went into this side. It exists because `buy_share` measures the BOOK and
    # not the SIZE — a premium with 0.1M split evenly reads 50%, exactly like a
    # premium with 27M split evenly, and the first one is not being traded at
    # all. Without this, a side nobody touched scored `Healthy`.
    pair = sum(acc[s][0] + acc[s][1] for s in ("CALL", "PUT"))
    for side in ("CALL", "PUT"):
        if not out[side]["legs"]:
            continue
        buy, sell = acc[side]
        total = buy + sell
        out[side].update({
            "cbv": buy, "csv": sell, "cvd": buy - sell, "volume": total,
            "buy_share": (round(100.0 * buy / total, 1) if total > 0 else None),
            "volume_share": (round(100.0 * total / pair, 1) if pair > 0
                             else None),
        })
    return out


# ══════════════════════════════════════════════════════════════════════
#  per-side scores
# ══════════════════════════════════════════════════════════════════════

def _market_context(fr: Dict[str, Any]) -> Dict[str, Any]:
    """The market-level reads both sides share, pulled once.

    Every value is read, never derived. `None` means the stage did not report
    and is propagated as such.
    """
    energy = fr.get("energy_read") or fr.get("energy") or {}
    htf_align = ((fr.get("htf") or {}).get("alignment") or {})
    return {
        "energy_strength": _f(energy.get("strength")),
        "compression": _f(energy.get("compression")),
        "release": _f(energy.get("release_probability")),
        "expansion_readiness": _f(energy.get("expansion_readiness")),
        "energy_state": energy.get("state"),
        "absorption": str((fr.get("absorption") or {}).get("behaviour") or ""),
        # Stage 42 — the reaction verdict, now consumed by Spike rather than
        # extracted and dropped.
        "acceptance": str((fr.get("reaction") or {}).get("state") or "").upper(),
        # Stage 45 — both halves used: the score weights confidence, the bias
        # routes market-level triggers to the side they favour.
        "htf": _f(htf_align.get("score")),
        "htf_bias": str(htf_align.get("bias") or ""),
        "stability_word": _stability_word(fr),
        "liquidity": fr.get("liquidity") or {},
        "dealer": (fr.get("sections") or {}).get("dealer") or {},
        "dealer_levels": fr.get("dealer_levels") or {},
        # Stage 50 — the premium behaviour classification, read whole.
        "ltp": fr.get("ltp_behaviour") or {},
        "spot": _f(fr.get("spot")),
    }


def _stability_word(fr: Dict[str, Any]) -> Optional[str]:
    """Stage 44's own word, or `None`.

    `Stable / Unstable / Shock / Recovery` is Stage 44's vocabulary and this
    stage reports it verbatim. A frozen tape is `Shock` whatever the band says —
    `freeze_entries` is the strongest thing Stage 44 can publish, so it cannot
    render as anything softer.
    """
    if (fr.get("flow_shift") or {}).get("freeze_entries"):
        return "Shock"
    word = str(fr.get("stability") or "").upper()
    return word.title() if word in _STABILITY_WORDS else None


def _behaviour(ctx: Dict[str, Any], side: str) -> Dict[str, Any]:
    """Stage 50's read for THIS premium. Nothing is derived here.

    `calls`/`puts` carry the LTP × OI classification (building · distribution ·
    squeeze · unwinding); `buyers`/`sellers` carry the pressure state, whose
    `absorbing` and `exhausted` values only exist as a comparison across time and
    are the two most valuable words in the whole engine.
    """
    ltp = ctx.get("ltp") or {}
    if not ltp.get("ready"):
        return {"state": None, "label": None, "pressure": None,
                "source": "Stage 50 not ready"}
    node = (ltp.get("calls") if side == "CALL" else ltp.get("puts")) or {}
    # A CALL premium expands on buyer pressure, a PUT on seller pressure.
    press = (ltp.get("buyers") if side == "CALL" else ltp.get("sellers")) or {}
    return {"state": str(node.get("state") or "") or None,
            "label": node.get("label"),
            "pressure": str(press.get("state") or "") or None,
            "pressure_label": press.get("label"),
            "source": "Stage 50 LTP Behaviour"}


def _signal_net(bucket: Dict[str, Any], signals) -> Tuple[float, float, int]:
    """Weighted (bullish_weight, total_weight, reporting_count) for one side.

    Only signals that actually reported are counted in the denominator. A leg
    table that published four of six reads scores out of four — folding the
    silent two in as neutral would understate a genuine read.
    """
    got = 0.0
    total = 0.0
    reported = 0
    for key, weight in signals:
        dirs = (bucket.get("signals") or {}).get(key) or []
        votes = [d for d in dirs if d in (BULLISH, BEARISH)]
        if not votes:
            continue
        reported += 1
        bull = sum(1 for d in votes if d == BULLISH)
        got += weight * (bull / len(votes))
        total += weight
    return got, total, reported


#: Stage 50 states that add to or subtract from participation, and the reason
#: each one publishes. Read from Stage 50's vocabulary, never re-derived.
_BEHAVIOUR_ENERGY = {
    "building": (12.0, "Premium Building"),
    "squeeze": (10.0, "Short Covering"),
    "distribution": (-10.0, "Premium Distribution"),
    "unwinding": (-12.0, "Premium Unwinding"),
}
_PRESSURE_ENERGY = {
    "building": (8.0, "Pressure Building"),
    "absorbing": (5.0, "Institutional Absorption"),
    "exhausted": (-12.0, "Premium Exhaustion"),
    "weakening": (-8.0, "Premium Fading"),
}


def _side_energy(bucket: Dict[str, Any], ctx: Dict[str, Any],
                 flow: Dict[str, Any], beh: Dict[str, Any]) -> Dict[str, Any]:
    """Participation in THIS premium right now, 0–100.

    Three inputs, in order of authority:

    1. **CBV/CSV buy share** — how much volume actually went in, and on which
       side of the book. This is the mandatory input and it carries the most
       weight, because it is a measurement rather than a classification.
    2. **Leg glyph participation** — the direction of the six leg engines.
    3. **Stage 50 behaviour** — a bounded adjustment, not a source. Building and
       squeeze add; distribution, unwinding and exhaustion subtract.

    Market energy only *modulates*. A tape with high Stage 37 energy does not
    make a dead premium alive, so it scales the result rather than adding to it.
    """
    reasons: List[Tuple[float, str]] = []
    parts: List[Tuple[float, float]] = []      # (value, weight)

    share = _f(flow.get("buy_share"))
    if share is not None:
        parts.append((share, 2.0))
        if share >= 60:
            reasons.append((share, "Strong CBV"))
        elif share <= 40:
            reasons.append((100.0 - share, "Strong CSV"))

    got, total, reported = _signal_net(bucket, _ENERGY_SIGNALS)
    leg_pct = (100.0 * got / total) if total else None
    if leg_pct is not None:
        parts.append((leg_pct, 1.5))
        if leg_pct >= 60:
            reasons.append((leg_pct, "Positive CVD"))

    if not parts:
        return {"score": None, "reporting": 0, "reasons": [],
                "reason": "neither CBV/CSV nor the leg table reported for this side"}

    base = sum(v * w for v, w in parts) / sum(w for _, w in parts)

    adj, why = 0.0, []
    for table, key in ((_BEHAVIOUR_ENERGY, beh.get("state")),
                       (_PRESSURE_ENERGY, beh.get("pressure"))):
        hit = table.get(str(key or ""))
        if hit:
            adj += hit[0]
            why.append(hit[1])
            reasons.append((abs(hit[0]) * 4.0, hit[1]))
    score = base + adj

    mkt = ctx.get("energy_strength")
    if mkt is None:
        note = "market energy did not report — leg and flow participation only"
    else:
        score = score * (0.70 + 0.30 * (mkt / 100.0))
        note = f"scaled by market energy {mkt:.0f}%"

    # ── size caps the claim ───────────────────────────────────────────
    # `buy_share` describes the book, not the size. A premium taking 1% of the
    # pair's volume on a 50/50 book scores identically to one taking 60% on the
    # same book, and only the second is being participated in. An even split of
    # almost nothing is not `Healthy`, so relative volume caps Energy rather
    # than being averaged into it — the same shape as Spike's participation cap,
    # and for the same reason.
    vshare = _f(flow.get("volume_share"))
    if vshare is not None:
        cap = 20.0 + 1.6 * vshare        # 50% of the pair → no cap in practice
        if cap < score:
            note += f"; capped at {cap:.0f} on {vshare:.0f}% of pair volume"
        score = min(score, cap)

    src = []
    if share is not None:
        src.append(f"buy share {share:.0f}%")
    if leg_pct is not None:
        src.append(f"leg participation {leg_pct:.0f}%")
    if why:
        src.append(" · ".join(why))
    return {"score": round(_clamp(score)), "reporting": reported,
            "leg_pct": None if leg_pct is None else round(leg_pct),
            "buy_share": share, "reasons": reasons,
            "reason": ", ".join(src) + f" — {note}"}


def _side_favoured(side: str, ctx: Dict[str, Any]) -> bool:
    """Is the tape's own direction the one this premium needs?

    A CALL premium expands when the market goes up. So the market-level triggers
    — a dealer wall breaking, a liquidity vacuum, absorption releasing — only
    name THIS side when the direction behind them points this way.

    Without this, both premiums received an identical trigger list ("Dealer Wall
    Break · Absorption Release · Liquidity Vacuum" on CALL *and* PUT), which is
    a market read printed twice, not per-side intelligence. Direction comes from
    Stage 45's HTF bias and Stage 11's dealer read — both already published, so
    nothing new is measured here.
    """
    want = BULLISH if side == "CALL" else BEARISH
    votes = []
    htf = ctx.get("htf_bias", "").upper()
    if htf in ("BULL", "BEAR"):
        votes.append(BULLISH if htf == "BULL" else BEARISH)
    dealer = str((ctx.get("dealer") or {}).get("bias") or "").upper()
    if dealer in ("BULL", "BEAR"):
        votes.append(BULLISH if dealer == "BULL" else BEARISH)
    if not votes:
        return True          # direction unknown → do not withhold the trigger
    return sum(1 for v in votes if v == want) >= len(votes) / 2.0


def _dealer_trigger(ctx: Dict[str, Any], side: str,
                    favoured: bool) -> List[Tuple[float, str]]:
    """`Dealer Wall` / `Gamma Flip`, from Stage 11's published levels.

    These are the top two entries in the trigger priority and they were the two
    the module could not previously name — the old code labelled a *leg VOB*
    break "Dealer Wall Break", which is a different level entirely. Spot's
    position against `dealer_wall` and `gamma_flip` is the real read, and both
    numbers already exist in `fr["dealer_levels"]`.
    """
    out: List[Tuple[float, str]] = []
    lv = ctx.get("dealer_levels") or {}
    spot = ctx.get("spot")
    if spot is None or not favoured:
        return out
    wall = _f(lv.get("dealer_wall"))
    if wall and ((side == "CALL" and spot > wall) or
                 (side == "PUT" and spot < wall)):
        out.append((95.0, "Dealer Wall"))
    flip = _f(lv.get("gamma_flip"))
    if flip and ((side == "CALL" and spot > flip) or
                 (side == "PUT" and spot < flip)):
        out.append((88.0, "Gamma Flip"))
    return out


def _side_spike(bucket: Dict[str, Any], ctx: Dict[str, Any], side: str,
                flow: Dict[str, Any], beh: Dict[str, Any]) -> Dict[str, Any]:
    """Probability that THIS premium expands violently, 0–100.

    Built from a different substrate than Energy on purpose: ignition,
    divergence and absorption on this side, the reaction Stage 42 measured, and
    the market's compression and release readings. Compression *raises* spike
    probability — a coil is potential energy — which is why a quiet premium can
    score higher here than a trending one.

    **Stage 44 is not an input.** It shapes Stability and only Stability;
    capping here as well counted one veto twice.
    """
    got, total, reported = _signal_net(bucket, _SPIKE_SIGNALS)
    triggers: List[Tuple[float, str]] = []
    parts: List[float] = []

    leg_pct = (100.0 * got / total) if total else None
    if leg_pct is not None:
        parts.append(leg_pct)

    favoured = _side_favoured(side, ctx)
    triggers.extend(_dealer_trigger(ctx, side, favoured))
    parts.extend(v for v, _ in _dealer_trigger(ctx, side, favoured))

    comp = ctx.get("compression")
    if comp is not None:
        parts.append(comp)
    rel = ctx.get("release")
    if rel is not None:
        parts.append(rel)
    ready = ctx.get("expansion_readiness")
    if ready is not None:
        parts.append(ready)

    # ── Stage 42 — executed evidence, routed to the side it favours ────
    hit = _ACCEPTANCE_SPIKE.get(ctx.get("acceptance") or "")
    if hit and favoured:
        triggers.append((hit[0], hit[1]))
        parts.append(hit[0])

    # ── this side's OWN zones — always its own, never gated ────────────
    vob = bucket.get("vob") or []
    if _VOB_BREAK in vob:
        triggers.append((80.0, "VOB Breakout"))
        parts.append(80.0)
    elif _VOB_BUILD in vob:
        triggers.append((60.0, "VOB Breakout"))
        parts.append(60.0)

    # ── flow explosions, from the mandatory numeric inputs ─────────────
    share = _f(flow.get("buy_share"))
    if share is not None and (share >= 70 or share <= 30):
        strength = max(share, 100.0 - share)
        triggers.append((strength, "Money Flow Explosion"))
        parts.append(strength)

    if str(beh.get("state") or "") in ("building", "squeeze"):
        triggers.append((70.0, "OI Explosion"))
        parts.append(70.0)

    vol = ((ctx.get("ltp") or {}).get("volume") or {})
    if str(vol.get("state") or "") in ("surging", "spike", "high"):
        triggers.append((72.0, "Volume Explosion"))
        parts.append(72.0)

    # ── market-level triggers: named only for the side they favour ────
    absorb = str(ctx.get("absorption") or "").upper()
    if "RELEAS" in absorb and favoured:
        triggers.append((85.0, "Absorption Release"))
        parts.append(85.0)

    liq = ctx.get("liquidity") or {}
    if isinstance(liq, dict) and liq.get("vacuum") and favoured:
        triggers.append((75.0, "Absorption Release"))
        parts.append(75.0)

    if ctx.get("energy_state") == "RELEASED" and favoured:
        triggers.append((90.0, "Absorption Release"))
        parts.append(90.0)

    if not parts:
        return {"score": None, "reporting": 0, "triggers": [], "reasons": [],
                "reason": "nothing that measures expansion reported"}

    score = sum(parts) / len(parts)

    # ── the market terms cannot carry a dead premium ──────────────────
    # Compression, release and absorption are TAPE readings: they are identical
    # for CALL and PUT, because they describe the market, not a side. Averaged
    # in without a gate they gave a premium with 0% participation a 62% "High"
    # spike — the market was coiled, so both sides scored as if about to
    # explode. A premium nobody is trading cannot expand explosively; the tape
    # has to act THROUGH a side, and if that side has no participation the
    # tape's potential is not its potential.
    #
    # Participation now comes from the numeric flow first and the glyph table
    # second, so the cap is a measurement rather than a vote count.
    cap_on = share if share is not None else leg_pct
    if cap_on is not None:
        score = min(score, 25.0 + 0.75 * cap_on)

    ranked = sorted(triggers, key=lambda x: -x[0])
    return {"score": round(_clamp(score)), "reporting": reported,
            "triggers": [t for _, t in ranked],
            "reasons": ranked,
            "reason": f"{len(parts)} expansion input(s) reporting"}


# ══════════════════════════════════════════════════════════════════════
#  shift · rotation · dominance
# ══════════════════════════════════════════════════════════════════════

def _accelerating(now: Optional[float], prev: Optional[float]) -> Dict[str, Any]:
    """Is the energy change itself getting bigger?

    `acceleration` answers *how fast* — this cycle's move. Whether that move is
    **speeding up** needs the previous cycle's acceleration, and the previous
    output already carries it, so the second derivative costs nothing to store.
    It is `UNKNOWN` until cycle three, because two points describe a change and
    three are the fewest that can describe a change *in* the change.

    Compared on magnitude, not on sign: a fall accelerating from −4 to −15 is
    speeding up in the sense a trader means, even though the number went down.
    """
    if now is None or prev is None:
        return {"state": "UNKNOWN", "label": "—", "delta": None,
                "source": "needs three cycles to compare two changes"}
    d = abs(now) - abs(prev)
    if d >= 5:
        return {"state": "UP", "label": "speeding up", "delta": round(d),
                "source": f"|{now:+.0f}| against |{prev:+.0f}| last cycle"}
    if d <= -5:
        return {"state": "DOWN", "label": "slowing", "delta": round(d),
                "source": f"|{now:+.0f}| against |{prev:+.0f}| last cycle"}
    return {"state": "STEADY", "label": "steady", "delta": round(d),
            "source": f"|{now:+.0f}| against |{prev:+.0f}| last cycle"}


def _shift(now: Optional[float], prev: Optional[float],
           beh: Dict[str, Any], ctx: Dict[str, Any],
           prev_accel: Optional[float] = None) -> Dict[str, Any]:
    """One of the seven states, and the acceleration behind it.

    **Acceleration is the size of the move; the state is its character.** They
    are reported together because either alone misleads: `Increasing` says
    nothing about whether the rise is 6 points or 26, and `+18` says nothing
    about whether writers or buyers produced it.

    Movement is read first because it is the strongest evidence: a premium whose
    energy jumped 20 points is `Exploding` whatever its OI classification says.
    Where energy is flat, the structural reads decide — Stage 50's own words for
    Building and Distributing, Stage 37's compression for Compressing.

    `UNKNOWN` on the first cycle: a move that was never observed is not a move.
    """
    if now is None or prev is None:
        return {"state": SHIFT_UNKNOWN, "label": "—",
                "acceleration": None, "delta": None,
                "accelerating": _accelerating(None, None),
                "source": "no previous cycle to compare"}
    d = now - prev

    def _out(state: str, label: str, source: str) -> Dict[str, Any]:
        """Every state carries the same acceleration — one measurement, one
        place. `delta` is kept as an alias so nothing that learned the old key
        breaks; `acceleration` is the name the reading is published under."""
        return {"state": state, "label": label,
                "acceleration": round(d), "delta": round(d),
                "accelerating": _accelerating(d, prev_accel),
                "source": source}

    if d >= 20:
        return _out(SHIFT_EXPLODING, "💥 Exploding",
                    f"energy +{d:.0f} in one cycle")

    # Stage 50's word outranks the raw direction when the two agree, because it
    # names the MECHANISM: "Distributing" says writers are selling into this
    # premium, where "Decreasing" only says the number fell. Where they
    # disagree — energy collapsing while Stage 50 still reads `building` — the
    # measured movement wins, since reporting "Building" through a fall would
    # describe a premium that is not there.
    word = _S50_SHIFT.get(str(beh.get("state") or ""))
    if word:
        agrees = (d >= -5.0) if word == SHIFT_BUILDING else (d <= 5.0)
        if agrees:
            return _out(word,
                        "📈 Building" if word == SHIFT_BUILDING
                        else "📉 Distributing",
                        f"{beh.get('label') or 'Stage 50'} (energy {d:+.0f})")

    if d >= 5:
        return _out(SHIFT_INCREASING, "↑ Increasing", f"energy +{d:.0f}")
    if d <= -5:
        return _out(SHIFT_DECREASING, "↓ Decreasing", f"energy {d:.0f}")

    comp = ctx.get("compression")
    if comp is not None and comp >= 55:
        return _out(SHIFT_COMPRESSING, "🪤 Compressing",
                    f"Stage 37 compression {comp:.0f}%")
    return _out(SHIFT_HOLDING, "· Holding",
                "energy flat and no structural state reported")


def _rotation(now: Dict[str, Any], prev: Optional[Dict[str, Any]]
              ) -> Dict[str, Any]:
    """Is energy migrating between the premiums?

    Measured on **energy**, not on which horizon the matrix happens to favour.
    Those are different facts: Stage 71's side can flip on directional evidence
    while both premiums keep exactly the participation they had, and reporting
    that as rotation names a migration that never happened.

    Rotation requires one side to fall and the other to rise, both materially —
    a pair that merely drifted apart is a spread, not a migration.
    """
    if not prev:
        return {"rotation": "UNKNOWN", "label": "—",
                "source": "no previous cycle to compare"}
    prev_sides = (prev.get("sides") or {})
    d: Dict[str, Optional[float]] = {}
    for side in ("CALL", "PUT"):
        a = _f((now.get(side) or {}).get("energy"))
        b = _f((prev_sides.get(side) or {}).get("energy"))
        d[side] = None if a is None or b is None else a - b
    dc, dp = d["CALL"], d["PUT"]
    if dc is None or dp is None:
        return {"rotation": "UNKNOWN", "label": "—",
                "source": "a side did not report in both cycles"}

    move = 8.0
    if dc <= -move and dp >= move:
        return {"rotation": "ROTATION", "label": "CALL → PUT",
                "source": f"CALL {dc:.0f}, PUT +{dp:.0f}"}
    if dp <= -move and dc >= move:
        return {"rotation": "ROTATION", "label": "PUT → CALL",
                "source": f"PUT {dp:.0f}, CALL +{dc:.0f}"}
    if abs(dc) < move and abs(dp) < move:
        return {"rotation": "STABLE", "label": "Stable",
                "source": f"CALL {dc:+.0f}, PUT {dp:+.0f} — neither moved"}
    return {"rotation": "BALANCED", "label": "Balanced",
            "source": f"CALL {dc:+.0f}, PUT {dp:+.0f} — same direction"}


def _dominance(ce: Optional[float], pe: Optional[float]) -> str:
    """Four states. `No Energy` and `Balanced` are different findings.

    Two premiums at 74 and 70 are both live and neither leads. Two premiums that
    never reported, or that both read Dead, are not balanced — there is nothing
    there. Rendering both as "Balanced" told a trader to wait for an edge in the
    first case and hid an empty tape in the second.
    """
    if ce is None and pe is None:
        return DOM_NONE
    lo = 20.0                                  # the top of the `Dead` band
    if (ce or 0) < lo and (pe or 0) < lo:
        return DOM_NONE
    if pe is None or (ce is not None and ce - pe >= 12):
        return DOM_CALL
    if ce is None or (pe is not None and pe - ce >= 12):
        return DOM_PUT
    return DOM_BALANCED


def _preferred(ce: Optional[float], pe: Optional[float],
               cs: Optional[float], ps: Optional[float],
               dominance: str, stability: Optional[str]) -> Dict[str, Any]:
    """`Prefer CALL · Prefer PUT · No Edge · Avoid Both`, with its reason.

    A preference, never an instruction. The engine says which premium it would
    watch; what to do about that belongs to Stage 52 and to the trader.
    """
    if dominance == DOM_NONE:
        return {"preferred": PREFER_AVOID, "side": None,
                "reason": "neither premium has measurable participation"}
    if str(stability or "") in ("Shock", "Unstable"):
        return {"preferred": PREFER_AVOID, "side": None,
                "reason": f"Stage 44 reports {stability} — the read that "
                          f"produced these scores may no longer hold"}
    if dominance == DOM_CALL:
        return {"preferred": PREFER_CALL, "side": "CALL",
                "reason": f"CALL energy {ce:.0f} against PUT {(pe or 0):.0f}"}
    if dominance == DOM_PUT:
        return {"preferred": PREFER_PUT, "side": "PUT",
                "reason": f"PUT energy {pe:.0f} against CALL {(ce or 0):.0f}"}
    # Balanced on energy — spike can still separate them.
    if cs is not None and ps is not None and abs(cs - ps) >= 20:
        side = "CALL" if cs > ps else "PUT"
        return {"preferred": PREFER_CALL if side == "CALL" else PREFER_PUT,
                "side": side,
                "reason": f"energy is balanced but {side} spike "
                          f"{max(cs, ps):.0f}% against {min(cs, ps):.0f}%"}
    return {"preferred": PREFER_NONE, "side": None,
            "reason": "both premiums active, neither leads on energy or spike"}


# ══════════════════════════════════════════════════════════════════════
#  confidence · trigger · reasons
# ══════════════════════════════════════════════════════════════════════

def _confidence(side: Optional[Dict[str, Any]], ctx: Dict[str, Any],
                stability: Optional[str]) -> Dict[str, Any]:
    """`A+ · A · B · C` on Stage 52's bands, or `UNKNOWN`.

    `decision._grade` is imported rather than reproduced, so a band this stage
    prints can never disagree with the one the Decision Engine prints. Each
    component is scored 0–5 and **unknown components are excluded, never scored
    zero** — Stage 63's rule. Fewer than two reporting is `UNKNOWN`: a grade
    resting on one number is a number wearing a letter.
    """
    if not side:
        return {"grade": "UNKNOWN", "components": {},
                "reason": "no premium reported"}
    comp: Dict[str, float] = {}

    en = _f(side.get("energy"))
    if en is not None:
        comp["energy"] = en / 20.0
    sp = _f(side.get("spike"))
    if sp is not None:
        comp["spike"] = sp / 20.0
    share = _f(side.get("buy_share"))
    if share is not None:
        # distance from an even book, either way — conviction, not direction
        comp["flow"] = min(5.0, abs(share - 50.0) / 10.0)
    htf = ctx.get("htf")
    if htf is not None:
        comp["htf"] = _clamp(htf, 0, 100) / 20.0
    if stability:
        comp["stability"] = {"Stable": 5.0, "Recovery": 3.0,
                             "Unstable": 1.5, "Shock": 0.0}.get(stability, 2.5)

    if len(comp) < 2:
        return {"grade": "UNKNOWN", "components": comp,
                "reason": f"only {len(comp)} component reported — "
                          f"too thin to grade"}
    avg = sum(comp.values()) / len(comp)
    return {"grade": _grade(avg), "avg": round(avg, 2), "components":
            {k: round(v, 2) for k, v in comp.items()},
            "reason": f"{len(comp)} components, mean {avg:.2f}/5 "
                      f"(Stage 52 bands)"}


def _top_trigger(triggers: Iterable[str]) -> Optional[str]:
    """Exactly one, by `TRIGGER_PRIORITY`. `None` when nothing fired.

    The priority is causal, not alphabetical: a dealer wall giving way changes
    what every other read means, and a volume spike underneath it is a
    consequence rather than a second finding.
    """
    known = [t for t in triggers if t in _TRIGGER_RANK]
    if not known:
        return None
    return min(known, key=lambda t: _TRIGGER_RANK[t])


def _top_reasons(sides: Dict[str, Dict[str, Any]],
                 scored: Dict[str, List[Tuple[float, str]]]) -> List[Dict[str, Any]]:
    """At most five, strongest first, machine-readable.

    Each entry is `{code, label, side, weight}` — a code a downstream stage can
    branch on, not a sentence it would have to parse. Stage 71.8 needs to know
    *that* CBV was strong, not read that it was.
    """
    pool: List[Tuple[float, str, Optional[str]]] = []
    for side in ("CALL", "PUT"):
        for weight, label in (scored.get(side) or []):
            pool.append((weight, label, side))
    seen: Dict[str, Tuple[float, str, Optional[str]]] = {}
    for weight, label, side in pool:
        cur = seen.get(label)
        if cur is None or weight > cur[0]:
            seen[label] = (weight, label, side)
    ranked = sorted(seen.values(), key=lambda x: -x[0])[:5]
    return [{"code": label.upper().replace(" ", "_"), "label": label,
             "side": side, "weight": round(weight)}
            for weight, label, side in ranked]


def _conclusion(call: Dict[str, Any], put: Dict[str, Any], dominance: str,
                rotation: Dict[str, Any], preferred: Dict[str, Any],
                stability: Optional[str]) -> str:
    """One line, and it is an observation.

    It used to read "🔥 Trade CALL". That is a buy instruction in plain words,
    which this stage is forbidden to produce twice over — by its own binding
    rules, and by Stage 65's rule that actions are quoted from Stage 52 and
    never invented. What a premium is doing is this engine's to say; what to do
    about it is not.
    """
    ce, pe = call.get("energy"), put.get("energy")
    cs, ps = call.get("spike"), put.get("spike")
    if ce is None and pe is None:
        return "⚪ No premium read yet — the leg table has not reported."
    if stability in ("Shock", "Unstable"):
        return f"⚠ Stage 44 reports {stability} — premium energy is unreliable."
    if str(rotation.get("rotation")) == "ROTATION":
        return f"🔄 Energy rotating {rotation.get('label')}."
    if cs is not None and cs >= 81:
        return "🚀 CALL premium is coiled for expansion."
    if ps is not None and ps >= 81:
        return "🚀 PUT premium is coiled for expansion."
    if dominance == DOM_NONE:
        return "❄ Neither premium has participation."
    if dominance == DOM_CALL:
        return ("🔥 CALL leads on energy; PUT has none."
                if (pe or 0) < 20 else "🔥 CALL leads on energy.")
    if dominance == DOM_PUT:
        return ("🐻 PUT leads on energy; CALL has none."
                if (ce or 0) < 20 else "🐻 PUT leads on energy.")
    return f"⚖ Both premiums active — {preferred.get('preferred')}."


#: Swing never names a premium — `horizon_owner.NO_OPTION_SIDE`. A weeks-long
#: read cannot be expressed as a specific option that decays in days, so premium
#: energy is Not Applicable there rather than blank or zero.
_NO_PREMIUM = ("swing",)


def attach_to_horizons(pe: Optional[Dict[str, Any]],
                       matrix: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Join per-side energy/spike onto Stage 71's per-horizon rows.

    Stage 71 answers *which horizon and which side*. Stage 71.7 answers *does
    that premium actually have energy, and could it explode*. Neither answers the
    other, and the join is where they become one decision:

        intraday → CALL   ·  CALL energy 82  spike 91   → agrees
        scalp    → PUT    ·  PUT  energy 21  spike 18   → the premium is dead

    That second line is the whole point. A horizon ranking high on directional
    evidence while its premium has no participation is the case a trader most
    needs flagged, and before this join nothing on the screen could say it.

    Computes nothing. Every number is read from `pe` or `matrix`.
    """
    rows: List[Dict[str, Any]] = []
    m = matrix or {}
    sides = (pe or {}).get("sides") or {}
    for row in (m.get("rows") or []):
        if not isinstance(row, dict):
            continue
        horizon = str(row.get("horizon") or "")
        side = row.get("side")
        out = {"horizon": horizon, "side": side,
               "score": row.get("score"),
               "energy": None, "spike": None, "spike_band": None,
               "agreement": "UNKNOWN", "note": ""}

        if horizon in _NO_PREMIUM:
            out["agreement"] = "N/A"
            out["note"] = ("swing names no premium by design — a weeks-long "
                           "read cannot be a decaying option")
            rows.append(out)
            continue
        if not side:
            out["agreement"] = "NO_SIDE"
            out["note"] = "this horizon has no side to check a premium against"
            rows.append(out)
            continue

        s = sides.get(side) or {}
        en, sp = _f(s.get("energy")), _f(s.get("spike"))
        out.update({"energy": s.get("energy"), "spike": s.get("spike"),
                    "spike_band": s.get("spike_band"),
                    "triggers": s.get("top_triggers") or []})
        if en is None:
            out["agreement"] = "UNKNOWN"
            out["note"] = f"{side} premium did not report — cannot confirm"
        elif en < 35:
            out["agreement"] = "CONTRADICTED"
            out["note"] = (f"{horizon} favours {side} but the {side} premium "
                           f"has almost no participation ({en:.0f}%)")
        elif sp is not None and sp >= 61 and en >= 55:
            out["agreement"] = "CONFIRMED_HOT"
            out["note"] = (f"{side} premium is live ({en:.0f}%) and coiled "
                           f"({sp:.0f}% spike)")
        else:
            out["agreement"] = "CONFIRMED"
            out["note"] = f"{side} premium has participation ({en:.0f}%)"
        rows.append(out)
    return rows


# ══════════════════════════════════════════════════════════════════════
#  the bridge downstream
# ══════════════════════════════════════════════════════════════════════

#: What Stage 71.8 (Strike Validation) and Stage 72 (Entry) consume. Published
#: flat and by name so a downstream stage reads one key rather than walking this
#: module's internal shape — and so neither has any reason to recompute.
BRIDGE_KEYS: Tuple[str, ...] = (
    "preferred_premium", "energy_score", "energy_shift",
    "energy_acceleration", "rotation", "spike_probability", "stability",
    "top_trigger", "top_reasons", "confidence",
)


def _bridge(out: Dict[str, Any]) -> Dict[str, Any]:
    """The nine fields, flat, for 71.8 and 72.

    Neither stage exists yet. The contract is published anyway, because the
    alternative is that whoever builds 71.8 reads `sides['CALL']['energy']` out
    of this module's internals and welds the two together.
    """
    sides = out.get("sides") or {}
    return {
        "preferred_premium": (out.get("preferred") or {}).get("preferred"),
        "energy_score": {s: (sides.get(s) or {}).get("energy")
                         for s in ("CALL", "PUT")},
        "energy_shift": {s: ((out.get("shift") or {}).get(s) or {}).get("state")
                         for s in ("CALL", "PUT")},
        "energy_acceleration": {
            s: ((out.get("shift") or {}).get(s) or {}).get("acceleration")
            for s in ("CALL", "PUT")},
        "rotation": (out.get("rotation") or {}).get("label"),
        "spike_probability": {s: (sides.get(s) or {}).get("spike")
                              for s in ("CALL", "PUT")},
        "stability": (out.get("stability") or {}).get("word"),
        "top_trigger": out.get("top_trigger"),
        "top_reasons": out.get("top_reasons") or [],
        "confidence": (out.get("confidence") or {}).get("grade"),
        "advisory_only": ADVISORY_ONLY,
        "missing_consumers": list(MISSING_INPUTS),
    }


def build(final_read: Optional[Dict[str, Any]] = None,
          leg_rows: Optional[List[Dict[str, Any]]] = None,
          matrix: Optional[Dict[str, Any]] = None,
          previous: Optional[Dict[str, Any]] = None,
          leg_totals: Optional[Iterable[Tuple[Any, Dict[str, Any]]]] = None
          ) -> Dict[str, Any]:
    """Stage 71.7. Always a dict, never raises.

    `leg_rows`    — the app's `_leg_bias_cache` rows (a PARAMETER; this module
                    may not read session_state).
    `leg_totals`  — `(leg_tag, order_flow.totals(frame))` pairs from
                    `_atm_leg_ltf_delta`, the mandatory CBV/CSV/CVD input.
    `matrix`      — Stage 71's output, read for the horizon join.
    `previous`    — the previous cycle's own output, for Shift and Rotation.
    """
    fr = dict(final_read or {})
    ctx = _market_context(fr)
    sides = sides_from_leg_rows(leg_rows)
    flow = flow_from_leg_totals(leg_totals)

    out_sides: Dict[str, Dict[str, Any]] = {}
    scored: Dict[str, List[Tuple[float, str]]] = {}
    for side in ("CALL", "PUT"):
        bucket = sides[side]
        beh = _behaviour(ctx, side)
        en = _side_energy(bucket, ctx, flow[side], beh)
        sp = _side_spike(bucket, ctx, side, flow[side], beh)
        scored[side] = list(en.get("reasons") or []) + list(sp.get("reasons") or [])
        out_sides[side] = {
            "side": side,
            "energy": en.get("score"),
            "energy_reason": en.get("reason"),
            "spike": sp.get("score"),
            "spike_reason": sp.get("reason"),
            "strength": energy_band(en.get("score")),
            "spike_band": spike_band(sp.get("score")),
            "top_triggers": sp.get("triggers") or [],
            "trigger": _top_trigger(sp.get("triggers") or []),
            "behaviour": beh,
            "cbv": flow[side].get("cbv"),
            "csv": flow[side].get("csv"),
            "cvd": flow[side].get("cvd"),
            "buy_share": flow[side].get("buy_share"),
            "legs": bucket.get("legs", 0),
            "reporting": en.get("reporting", 0),
        }

    call, put = out_sides["CALL"], out_sides["PUT"]
    ce, pe = _f(call["energy"]), _f(put["energy"])
    cs, ps = _f(call["spike"]), _f(put["spike"])

    dominance = _dominance(ce, pe)

    # Balance — the same two numbers as shares of the pair. Never a source.
    tot = (ce or 0) + (pe or 0)
    balance = ({"CALL": round(100.0 * (ce or 0) / tot),
                "PUT": round(100.0 * (pe or 0) / tot)} if tot > 0
               else {"CALL": None, "PUT": None})

    prev_sides = ((previous or {}).get("sides") or {})
    prev_shift = ((previous or {}).get("shift") or {})
    shift = {s: _shift(_f(out_sides[s]["energy"]),
                       _f((prev_sides.get(s) or {}).get("energy")),
                       out_sides[s]["behaviour"], ctx,
                       prev_accel=_f((prev_shift.get(s) or {})
                                     .get("acceleration")))
             for s in ("CALL", "PUT")}

    rotation = _rotation(out_sides, previous)

    word = ctx.get("stability_word")
    stability = {"word": word,
                 "band": (matrix or {}).get("stability"),
                 "emoji": (matrix or {}).get("stability_emoji"),
                 "score": (matrix or {}).get("stability_score"),
                 "source": "Stage 44 vocabulary; band from Stage 71 "
                           "stability() over Stages 44/47/54"}

    preferred = _preferred(ce, pe, cs, ps, dominance, word)
    lead = out_sides.get(preferred.get("side")) if preferred.get("side") else None
    confidence = _confidence(lead, ctx, word)

    all_triggers: List[str] = []
    for s in ("CALL", "PUT"):
        for t in out_sides[s]["top_triggers"]:
            if t not in all_triggers:
                all_triggers.append(t)

    out = {
        "stage": "71.7",
        "advisory_only": ADVISORY_ONLY,
        "ready": any(out_sides[s]["energy"] is not None for s in ("CALL", "PUT")),
        "sides": out_sides,
        "call": call,
        "put": put,
        "dominance": dominance,
        "balance": balance,
        "shift": shift,
        "rotation": rotation,
        "stability": stability,
        "preferred": preferred,
        "confidence": confidence,
        "top_trigger": _top_trigger(all_triggers),
        "top_reasons": _top_reasons(out_sides, scored),
        "triggers_seen": all_triggers,
        "conclusion": _conclusion(call, put, dominance, rotation, preferred,
                                  word),
        # per-horizon cross-check: does the premium each horizon names actually
        # have energy? Built last so it can read the finished side scores.
        "horizons": attach_to_horizons({"sides": out_sides}, matrix),
        "missing_inputs": list(MISSING_INPUTS),
        "retired_inputs": dict(RETIRED_INPUTS),
    }
    out["bridge"] = _bridge(out)
    return out
