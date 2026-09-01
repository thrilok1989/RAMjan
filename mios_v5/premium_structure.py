"""Premium Structure — the single premium-analysis orchestrator.

Answers **"what is this specific premium's structure doing?"** for one option
leg: where its levels are, whether it is accepting or rejecting them, who is
absorbing whom, and how likely a break is to hold.

Not an engine. Not in `ALL_ENGINES`. No Streamlit, no session_state, no
mutators. Every input arrives as a parameter — the caller extracts, this module
interprets.

## It computes almost nothing, and that is the point

`docs/AUDIT_STAGE_71_8_PREMIUM_STRUCTURE.md` audited 23 requirements against the
codebase before a line of this was written: **18 already existed**. The dominant
finding was not absence but *discard* — `build_leg_bias_table` runs the per-leg
engines every cycle and collapses each to one 🟢/🔴/⚪ glyph, throwing the rest
away.

`detect_ignition` is the clearest case. It returns **named** sub-signals
including Wyckoff Spring and Wyckoff Upthrust — false break plus snap-back,
which *is* fakeout evidence — and the leg table keeps only `bull`/`bear`/`neu`.
This module reads the engine, not the glyph.

## The four things it is allowed to compute

Each is a **classifier over published data**, justified individually in §5 of
the audit:

* **HVN / LVN** — the money-flow profile publishes bins with volume ratios and
  nothing labels which are nodes. A threshold is the classifier.
* **RVOL** — `avg_vol_1m` is computed twice elsewhere and discarded twice.
* **Volume Climax** — genuinely missing; needs RVOL, which did not exist.
* **Breakout / Fakeout probability** — weighted reads over the evidence above,
  not new market measurement.

`structure_score` and `confidence` are this module's own output and have no
other owner by definition.

## One POC owner

The audit found **four** POC implementations. `compute_vpfr` is the chosen one:
it is already published per leg, it returns VAH/VAL alongside the POC (which
HVN/LVN need as reference), and the HTF stack already uses it — so a premium POC
and an index POC are computed the same way. **A fifth is forbidden**, and a test
asserts this module imports no profile builder at all.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

ADVISORY_ONLY = True

UNKNOWN = "UNKNOWN"

#: Requirements the audit found genuinely absent, that this module now owns.
#: Recorded so the next reader knows which numbers are new and why.
COMPUTED_HERE: Tuple[str, ...] = (
    "hvn", "lvn", "rvol", "volume_climax",
    "break_probability", "fakeout_probability",
    "structure_score", "confidence",
)

#: Everything else is read from a finished engine output. Named so a future
#: change that starts *computing* one of these is visibly a regression.
CONSUMED: Dict[str, str] = {
    "support": "classify_leg_sr_behavior (native)",
    "resistance": "classify_leg_sr_behavior (native)",
    "acceptance": "classify_leg_sr_behavior (native)",
    "rejection": "classify_leg_sr_behavior (native)",
    "vob": "analyze_vob_volume (native)",
    "trend": "calculate_vidya (native)",
    "momentum": "calculate_vidya (native)",
    "cbv": "indicators.order_flow.totals",
    "csv": "indicators.order_flow.totals",
    "cvd": "indicators.order_flow.totals",
    "vp_poc": "compute_vpfr (native) — the ONE POC owner",
    "value_area": "compute_vpfr (native)",
    "absorption": "leg Absorb block (native) / Stage 43",
    "ignition": "detect_ignition (native) — read NAMED, not as a glyph",
}

#: A high-volume node is a bin carrying materially more than an even share of
#: the profile's volume; a low-volume node materially less. Expressed against
#: the even share so the thresholds do not depend on the bin count.
_HVN_MULT = 1.5
_LVN_MULT = 0.4

#: RVOL bands. `climax` also requires a wide range and a rejected extreme —
#: volume alone is participation, not exhaustion.
_RVOL_CLIMAX = 2.5
_RVOL_HIGH = 1.5
_RVOL_DRY = 0.6

#: Wyckoff sub-signals from `detect_ignition`. These ARE the fakeout evidence:
#: a false break that snaps back is the definition of the thing.
_WYCKOFF = ("wyckoff spring", "wyckoff upthrust")


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _d(v) -> Dict[str, Any]:
    """A dict, whatever arrived.

    `analyse()` promises it never raises, and its inputs come from session-state
    caches that a degraded cycle can leave holding a string or a sentinel. A
    caller handing junk should get `UNKNOWN` reads, not a traceback through an
    advisory panel."""
    return v if isinstance(v, dict) else {}


def _seq(v) -> Sequence[Any]:
    """A sequence of dicts, whatever arrived — same reason as `_d`."""
    if isinstance(v, (list, tuple)):
        return [x for x in v if isinstance(x, dict)]
    return []


def _pct(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    p, w = _f(part), _f(whole)
    if p is None or w is None or w <= 0:
        return None
    return 100.0 * p / w


# ══════════════════════════════════════════════════════════════════════
#  consumed — every one of these is a READ
# ══════════════════════════════════════════════════════════════════════

def _levels(sr: Optional[Dict[str, Any]], vob: Optional[Sequence[Dict[str, Any]]],
            ltp: Optional[float]) -> Dict[str, Any]:
    """Support and resistance, in premium, from the leg's own VOB zones.

    `classify_leg_sr_behavior` already picked the nearest bullish block below
    the LTP and the nearest bearish block above it. Those are premium levels —
    not NIFTY levels converted through a delta no engine publishes — so they are
    taken as they stand.

    The zone list adds the levels the S/R classifier did not name as *nearest*,
    which is what makes a second support visible when the first breaks.
    """
    s = _d(sr)
    out: Dict[str, Any] = {
        "support": None, "resistance": None,
        "state": (str(s.get("state") or "") or None),
        "level": _f(s.get("level")),
        "direction": (str(s.get("direction") or "") or None),
        "source": CONSUMED["support"],
    }
    px = _f(ltp)
    sups, ress = [], []
    for z in _seq(vob):
        mid = _f(z.get("mid")) or _f(z.get("level"))
        if mid is None or px is None:
            continue
        (sups if mid <= px else ress).append(
            {"level": mid, "status": z.get("status"),
             "bull_pct": _f(z.get("bull_pct")), "bear_pct": _f(z.get("bear_pct"))})
    sups.sort(key=lambda z: -z["level"])
    ress.sort(key=lambda z: z["level"])
    out["support"] = sups[0]["level"] if sups else None
    out["resistance"] = ress[0]["level"] if ress else None
    out["supports"] = sups[:3]
    out["resistances"] = ress[:3]
    out["zones"] = len(sups) + len(ress)
    return out


def _acceptance(sr: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Acceptance and rejection, from the leg's own S/R state.

    Stage 42 answers this for NIFTY at an institutional level. This is the
    premium's own chart against the premium's own zone, which is a different
    fact — a CALL can be rejecting its own resistance while NIFTY accepts above
    a level, and a trader holding that CALL needs the first one.
    """
    state = str(_d(sr).get("state") or "").upper()
    if not state or state == "NONE":
        return {"acceptance": UNKNOWN, "rejection": UNKNOWN, "state": None,
                "source": CONSUMED["acceptance"]}
    return {
        "acceptance": state in ("ACCEPTING", "BREAKING"),
        "rejection": state == "REJECTING",
        "building": state == "BUILDING",
        "state": state,
        "source": CONSUMED["acceptance"],
    }


def _trend(vidya: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Trend and momentum, from VIDYA. Both read; neither re-derived."""
    v = _d(vidya)
    trend = str(v.get("trend") or "").strip()
    if not trend or trend.lower() == "unknown":
        return {"trend": UNKNOWN, "momentum": None, "source": CONSUMED["trend"]}
    return {
        "trend": trend,
        # VIDYA's own delta_pct is the momentum scalar the leg table dropped.
        "momentum": _f(v.get("delta_pct")),
        "cross_up": bool(v.get("cross_up")),
        "cross_down": bool(v.get("cross_down")),
        "source": CONSUMED["trend"],
    }


def _flow(flow: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """CBV · CSV · CVD, read from `indicators.order_flow.totals`.

    The single owner of the CLV split. This module does not recompute a buy
    fraction, and a test asserts it cannot.
    """
    fl = _d(flow)
    cbv, csv = _f(fl.get("buy_total")), _f(fl.get("sell_total"))
    if cbv is None or csv is None:
        return {"cbv": None, "csv": None, "cvd": None, "buy_share": None,
                "volume": None, "source": CONSUMED["cbv"]}
    total = cbv + csv
    return {
        "cbv": cbv, "csv": csv,
        "cvd": _f(fl.get("delta")) if fl.get("delta") is not None else cbv - csv,
        "buy_share": (round(100.0 * cbv / total, 1) if total > 0 else None),
        "volume": total,
        "source": CONSUMED["cbv"],
    }


def _profile(vpfr: Optional[Dict[str, Any]],
             mfp: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """POC and value area from `compute_vpfr` — the one chosen owner — plus the
    money-flow profile's bins, which are what HVN/LVN classify.

    The audit found four POC implementations. Taking `compute_vpfr`'s and
    ignoring the money-flow profile's `poc_price` is deliberate: two POCs on one
    panel with no explanation is worse than one POC that is occasionally the
    less convenient of the two.
    """
    vp = _d(vpfr)
    poc, vah, val = _f(vp.get("poc")), _f(vp.get("vah")), _f(vp.get("val"))
    out: Dict[str, Any] = {
        "vp_poc": poc, "vah": vah, "val": val,
        "source": CONSUMED["vp_poc"],
        "rows": len(_seq(_d(mfp).get("rows"))),
    }
    if poc is None:
        out["note"] = "no profile for this leg — VPFR covers ATM±1"
    return out


def _absorption(absorb: Optional[str], flow: Dict[str, Any]) -> Dict[str, Any]:
    """Buyer / seller absorption, read from the leg's own `Absorb` verdict.

    The native block measures it as range compression with a large signed delta
    — pressure going in and price refusing to move. That is the measurement;
    this only names which side it favours.
    """
    a = str(absorb or "").strip().lower()
    if a in ("bull", "buy", "buyer"):
        return {"buyer": True, "seller": False, "label": "buyer absorption",
                "source": CONSUMED["absorption"]}
    if a in ("bear", "sell", "seller"):
        return {"buyer": False, "seller": True, "label": "seller absorption",
                "source": CONSUMED["absorption"]}
    return {"buyer": False, "seller": False, "label": None,
            "source": CONSUMED["absorption"]}


def _ignition(ig: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """`detect_ignition`'s NAMED sub-signals — not the collapsed glyph.

    This is the audit's headline. The leg table reduces four named signals to
    `bull`/`bear`/`neu`, and two of those names — Wyckoff Spring and Wyckoff
    Upthrust — are *false break plus snap-back*, which is the fakeout evidence
    the spec asks for. Reading the engine instead of its glyph is the whole
    difference between "fakeout probability is missing" and "it was already
    being computed and thrown away".
    """
    g = _d(ig)
    sigs = list(_seq(g.get("signals")))
    names = [str(s.get("name") or "") for s in sigs]
    wyckoff = [s for s in sigs
               if str(s.get("name") or "").strip().lower() in _WYCKOFF]
    return {
        "fired": bool(g.get("fired")),
        "direction": g.get("direction"),
        "signals": names,
        "detail": [s.get("detail") for s in sigs if s.get("detail")],
        "wyckoff": [str(s.get("name")) for s in wyckoff],
        "wyckoff_direction": (wyckoff[0].get("direction") if wyckoff else None),
        "bull_count": g.get("bull_count"), "bear_count": g.get("bear_count"),
        "source": CONSUMED["ignition"],
    }


# ══════════════════════════════════════════════════════════════════════
#  computed here — the four the audit justified
# ══════════════════════════════════════════════════════════════════════

def classify_nodes(mfp: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """HVN and LVN over the money-flow profile's bins.

    The profile publishes `rows[]` with a per-bin volume `ratio` and nothing
    labels which are nodes. The threshold is expressed against the **even
    share** (`1 / n_rows`) rather than as an absolute, so it does not silently
    change meaning when the bin count does.
    """
    usable = list(_seq(_d(mfp).get("rows")))
    if not usable:
        return {"hvn": [], "lvn": [], "rows": 0,
                "note": "no money-flow profile for this leg"}
    total = sum(_f(r.get("total_volume")) or _f(r.get("volume")) or 0.0
                for r in usable)
    if total <= 0:
        return {"hvn": [], "lvn": [], "rows": len(usable),
                "note": "profile has no volume"}
    even = 1.0 / len(usable)
    hvn, lvn = [], []
    for r in usable:
        vol = _f(r.get("total_volume")) or _f(r.get("volume")) or 0.0
        share = vol / total
        price = (_f(r.get("bin_high")), _f(r.get("bin_low")))
        mid = (None if None in price else (price[0] + price[1]) / 2.0)
        if mid is None:
            continue
        if share >= even * _HVN_MULT:
            hvn.append({"price": round(mid, 2), "share": round(100 * share, 1)})
        elif share <= even * _LVN_MULT:
            lvn.append({"price": round(mid, 2), "share": round(100 * share, 1)})
    hvn.sort(key=lambda n: -n["share"])
    return {"hvn": hvn[:4], "lvn": lvn[:4], "rows": len(usable),
            "even_share": round(100 * even, 2)}


def relative_volume(candles: Optional[Sequence[Dict[str, Any]]],
                    lookback: int = 20) -> Dict[str, Any]:
    """RVOL — this bar's volume against the recent mean.

    Justified by the audit: `analyze_vob_volume` computes a 60-bar mean and
    `classify_leg_sr_behavior` a 20-bar mean, and **both discard it**. Two
    modules already needed this number and neither published it.

    A mean over fewer than `lookback` bars is still reported, with the count, so
    an early-session read is thin rather than absent.
    """
    vols: List[float] = []
    for c in (candles if isinstance(candles, (list, tuple)) else []):
        v = _f(c.get("volume")) if isinstance(c, dict) else _f(c)
        if v is not None:
            vols.append(v)
    if len(vols) < 3:
        return {"rvol": None, "band": UNKNOWN, "bars": len(vols),
                "note": "not enough bars to compare against"}
    now = vols[-1]
    prior = vols[-(lookback + 1):-1] or vols[:-1]
    mean = sum(prior) / len(prior) if prior else 0.0
    if mean <= 0:
        return {"rvol": None, "band": UNKNOWN, "bars": len(vols),
                "note": "no prior volume to compare against"}
    rvol = now / mean
    band = ("climax" if rvol >= _RVOL_CLIMAX else
            "high" if rvol >= _RVOL_HIGH else
            "dry" if rvol <= _RVOL_DRY else "normal")
    return {"rvol": round(rvol, 2), "band": band, "bars": len(prior) + 1,
            "mean": round(mean, 1), "now": round(now, 1)}


def volume_climax(candles: Optional[Sequence[Dict[str, Any]]],
                  rvol: Dict[str, Any]) -> Dict[str, Any]:
    """Exhaustion, not participation.

    The audit found this genuinely missing (#18), and it is the one requirement
    that could not be wired because RVOL did not exist to build it on.

    **Three conditions, all required.** Volume alone is participation — a high
    bar in a trend is the trend working. Climax is high volume *plus* a wide
    range *plus* a close rejecting its own extreme: everyone who wanted in got
    in, and the bar could not hold what it took.
    """
    r = _f(rvol.get("rvol"))
    if r is None:
        return {"climax": UNKNOWN, "why": rvol.get("note") or "no RVOL"}
    bars = list(_seq(candles))
    if len(bars) < 5:
        return {"climax": UNKNOWN, "why": "not enough bars"}
    last = bars[-1]
    hi, lo, cl = _f(last.get("high")), _f(last.get("low")), _f(last.get("close"))
    if None in (hi, lo, cl) or hi <= lo:
        return {"climax": UNKNOWN, "why": "last bar has no range"}
    rng = hi - lo
    prior = [(_f(b.get("high")), _f(b.get("low"))) for b in bars[-21:-1]]
    spans = [h - l for h, l in prior if h is not None and l is not None and h > l]
    wide = bool(spans) and rng >= 1.5 * (sum(spans) / len(spans))
    # how far the close sits from the extreme it reached, as a share of range
    up_reject = (hi - cl) / rng
    dn_reject = (cl - lo) / rng
    rejected = max(up_reject, dn_reject) >= 0.5
    hot = r >= _RVOL_CLIMAX
    if hot and wide and rejected:
        side = "buying" if up_reject > dn_reject else "selling"
        return {"climax": True, "side": side,
                "why": f"RVOL {r:.1f}×, wide range, close rejected "
                       f"{max(up_reject, dn_reject) * 100:.0f}% of it"}
    missing = [n for n, ok in (("RVOL ≥ 2.5×", hot), ("wide range", wide),
                               ("rejected extreme", rejected)) if not ok]
    return {"climax": False, "why": "not climax — missing " + ", ".join(missing)}


def _break_and_fakeout(levels: Dict[str, Any], acceptance: Dict[str, Any],
                       vob: Optional[Sequence[Dict[str, Any]]],
                       rvol: Dict[str, Any], absorption: Dict[str, Any],
                       ignition: Dict[str, Any],
                       climax: Dict[str, Any]) -> Dict[str, Any]:
    """Break probability and fakeout probability, 0–100 each.

    **Not two views of one number.** They are scored from different evidence and
    can both be high: a premium breaking a level on climax volume with a Wyckoff
    upthrust is genuinely likely to break *and* genuinely likely to fail, and
    collapsing that into `break = 70, fake = 30` would hide the exact situation a
    trader most needs to see.

    Break is *is it going*: acceptance, zone status, participation.
    Fakeout is *will it hold*: Wyckoff snap-backs, climax exhaustion, absorption
    against the move, a break on dry volume.
    """
    brk: List[Tuple[float, str]] = []
    fake: List[Tuple[float, str]] = []

    state = str(acceptance.get("state") or "")
    if state == "BREAKING":
        brk.append((80.0, "breaking its own level"))
    elif state == "ACCEPTING":
        brk.append((70.0, "accepting beyond its level"))
    elif state == "BUILDING":
        brk.append((45.0, "building at its level"))
    elif state == "REJECTING":
        brk.append((15.0, "rejecting at its level"))
        fake.append((60.0, "rejected at the level"))

    statuses = [str(z.get("status") or "").upper() for z in _seq(vob)]
    if "BREAKING" in statuses:
        brk.append((75.0, "a VOB zone is breaking"))
    if "BUILDING" in statuses:
        brk.append((60.0, "a VOB zone is building"))
    if "FADING" in statuses:
        fake.append((55.0, "a VOB zone is fading"))

    r = _f(rvol.get("rvol"))
    band = rvol.get("band")
    if r is not None:
        if band in ("high", "climax"):
            brk.append((70.0, f"RVOL {r:.1f}× — participation behind the move"))
        elif band == "dry":
            fake.append((70.0, f"RVOL {r:.1f}× — the move has no volume"))

    # Absorption against a break is the classic failure: pressure going in,
    # price not following, someone filling the other side.
    if absorption.get("seller"):
        fake.append((55.0, "seller absorption into the move"))
    if absorption.get("buyer"):
        brk.append((55.0, "buyer absorption supporting it"))

    if ignition.get("wyckoff"):
        fake.append((85.0, " · ".join(ignition["wyckoff"]) + " — false break"))
    elif ignition.get("fired"):
        brk.append((65.0, "ignition fired"))

    if climax.get("climax") is True:
        fake.append((75.0, climax.get("why") or "volume climax"))

    def _mean(pairs):
        return (round(_clamp(sum(v for v, _ in pairs) / len(pairs)))
                if pairs else None)

    return {
        "break_probability": _mean(brk),
        "fakeout_probability": _mean(fake),
        "break_reasons": [w for _, w in sorted(brk, key=lambda x: -x[0])][:3],
        "fakeout_reasons": [w for _, w in sorted(fake, key=lambda x: -x[0])][:3],
        "break_inputs": len(brk), "fakeout_inputs": len(fake),
    }


# ══════════════════════════════════════════════════════════════════════
#  the score
# ══════════════════════════════════════════════════════════════════════

#: What the structure score is made of. Levels lead because a premium with no
#: readable structure cannot be traded structurally whatever else agrees.
_SCORE_WEIGHTS: Dict[str, float] = {
    "acceptance": 2.5,
    "trend": 2.0,
    "flow": 2.0,
    "levels": 1.5,
    "volume": 1.5,
    "profile": 1.0,
}


def _structure_score(levels, acceptance, trend, flow, rvol, profile,
                     probs) -> Dict[str, Any]:
    """0–100 with its own confidence.

    **Score and confidence are separate.** The score says how constructive the
    structure looks; confidence says how much of it was actually measured.
    A premium scoring 80 on two components and one scoring 80 on six are not the
    same finding, and one number cannot say both — the same reason Stage 71.8
    carries `reporting` beside its own score.
    """
    parts: Dict[str, float] = {}

    st = str(acceptance.get("state") or "")
    if st:
        parts["acceptance"] = {"BREAKING": 85.0, "ACCEPTING": 80.0,
                               "BUILDING": 55.0, "REJECTING": 20.0}.get(st, 50.0)

    tr = str(trend.get("trend") or "")
    if tr and tr != UNKNOWN:
        low = tr.lower()
        parts["trend"] = (80.0 if "up" in low or "bull" in low else
                          20.0 if "down" in low or "bear" in low else 50.0)

    share = _f(flow.get("buy_share"))
    if share is not None:
        parts["flow"] = share

    if levels.get("support") is not None or levels.get("resistance") is not None:
        # readable structure is worth more the more of it there is
        parts["levels"] = _clamp(40.0 + 15.0 * (levels.get("zones") or 0))

    band = rvol.get("band")
    if band and band != UNKNOWN:
        parts["volume"] = {"climax": 60.0, "high": 80.0,
                           "normal": 55.0, "dry": 25.0}.get(band, 50.0)

    if profile.get("vp_poc") is not None:
        parts["profile"] = 60.0

    if not parts:
        return {"structure_score": None, "confidence": UNKNOWN,
                "components": {}, "reporting": 0, "of": len(_SCORE_WEIGHTS),
                "reason": "nothing reported"}

    total_w = sum(_SCORE_WEIGHTS[k] for k in parts)
    score = sum(parts[k] * _SCORE_WEIGHTS[k] for k in parts) / total_w

    # A high fakeout probability is a statement about the structure's
    # reliability, so it caps the score rather than being averaged into it —
    # the same veto shape Stage 71.7 uses for participation.
    fake = _f(probs.get("fakeout_probability"))
    capped = None
    if fake is not None and fake >= 60:
        capped = 100.0 - fake * 0.5
        score = min(score, capped)

    reporting = len(parts)
    conf = ("HIGH" if reporting >= 5 else
            "MEDIUM" if reporting >= 3 else "LOW")
    return {
        "structure_score": round(_clamp(score)),
        "confidence": conf,
        "components": {k: round(v) for k, v in parts.items()},
        "reporting": reporting, "of": len(_SCORE_WEIGHTS),
        "capped_at": None if capped is None else round(capped),
        "reason": f"{reporting} of {len(_SCORE_WEIGHTS)} components"
                  + (f", capped at {capped:.0f} by fakeout risk"
                     if capped is not None else ""),
    }


def _top_reasons(levels, acceptance, trend, flow, rvol, absorption,
                 ignition, probs) -> List[Dict[str, Any]]:
    """At most five, machine-readable, strongest first."""
    pool: List[Tuple[float, str]] = []
    st = str(acceptance.get("state") or "")
    if st:
        pool.append(({"BREAKING": 85.0, "ACCEPTING": 80.0, "BUILDING": 55.0,
                      "REJECTING": 70.0}.get(st, 40.0), st.title()))
    tr = str(trend.get("trend") or "")
    if tr and tr != UNKNOWN:
        pool.append((60.0, f"Trend {tr}"))
    share = _f(flow.get("buy_share"))
    if share is not None and (share >= 60 or share <= 40):
        pool.append((max(share, 100 - share),
                     "Strong CBV" if share >= 60 else "Strong CSV"))
    band = rvol.get("band")
    if band and band not in (UNKNOWN, "normal"):
        pool.append((70.0, f"RVOL {band}"))
    if absorption.get("label"):
        pool.append((65.0, absorption["label"].title()))
    for name in (ignition.get("wyckoff") or []):
        pool.append((90.0, name))
    for why in (probs.get("fakeout_reasons") or [])[:1]:
        pool.append((75.0, f"Fakeout risk: {why}"))

    seen: Dict[str, Tuple[float, str]] = {}
    for weight, label in pool:
        if label not in seen or weight > seen[label][0]:
            seen[label] = (weight, label)
    ranked = sorted(seen.values(), key=lambda x: -x[0])[:5]
    return [{"code": lbl.upper().replace(" ", "_").replace(":", ""),
             "label": lbl, "weight": round(w)} for w, lbl in ranked]


def analyse(sr: Optional[Dict[str, Any]] = None,
            vob: Optional[Sequence[Dict[str, Any]]] = None,
            vidya: Optional[Dict[str, Any]] = None,
            flow: Optional[Dict[str, Any]] = None,
            vpfr: Optional[Dict[str, Any]] = None,
            mfp: Optional[Dict[str, Any]] = None,
            ignition: Optional[Dict[str, Any]] = None,
            candles: Optional[Sequence[Dict[str, Any]]] = None,
            absorb: Optional[str] = None,
            ltp: Optional[float] = None) -> Dict[str, Any]:
    """One premium's structure. Always a dict, never raises.

    Every argument is a **finished engine output** — see `CONSUMED`. `candles`
    is the one raw input, and only because RVOL and Volume Climax need a volume
    series that no engine publishes.
    """
    lv = _levels(sr, vob, ltp)
    acc = _acceptance(sr)
    tr = _trend(vidya)
    fl = _flow(flow)
    prof = _profile(vpfr, mfp)
    nodes = classify_nodes(mfp)
    rv = relative_volume(candles)
    clx = volume_climax(_seq(candles), rv)
    ab = _absorption(absorb, fl)
    ig = _ignition(ignition)
    probs = _break_and_fakeout(lv, acc, vob, rv, ab, ig, clx)
    scored = _structure_score(lv, acc, tr, fl, rv, prof, probs)

    return {
        "advisory_only": ADVISORY_ONLY,
        "ready": scored.get("structure_score") is not None,
        "ltp": _f(ltp),
        # ── consumed ──
        "support": lv.get("support"),
        "resistance": lv.get("resistance"),
        "levels": lv,
        "acceptance": acc.get("acceptance"),
        "rejection": acc.get("rejection"),
        "acceptance_read": acc,
        "trend": tr.get("trend"),
        "momentum": tr.get("momentum"),
        "trend_read": tr,
        "cbv": fl.get("cbv"), "csv": fl.get("csv"), "cvd": fl.get("cvd"),
        "volume": fl.get("volume"),
        "delta": fl.get("cvd"),
        "flow": fl,
        "vp_poc": prof.get("vp_poc"),
        "profile": prof,
        "vob": list(_seq(vob)),
        "absorption": ab,
        "ignition": ig,
        # ── computed here, each justified by the audit ──
        "hvn": nodes.get("hvn"), "lvn": nodes.get("lvn"), "nodes": nodes,
        "rvol": rv.get("rvol"), "rvol_read": rv,
        "volume_climax": clx,
        "break_probability": probs.get("break_probability"),
        "fakeout_probability": probs.get("fakeout_probability"),
        "probabilities": probs,
        "structure_score": scored.get("structure_score"),
        "confidence": scored.get("confidence"),
        "score_read": scored,
        "top_reasons": _top_reasons(lv, acc, tr, fl, rv, ab, ig, probs),
        # ── provenance ──
        "consumed": dict(CONSUMED),
        "computed_here": list(COMPUTED_HERE),
    }
