"""MIOS V6 — Stage 50 LTP Behaviour (what price is TRYING to do).

Every other read describes what happened. This one describes intent-in-progress:
not "CVD is −40" but **"sellers building while buyers weaken"**.

Eight dimensions, each a state rather than a number:

    Price     rising · falling · flat · compressing · exploding
    Buyers    building · weakening · exhausted · absorbing
    Sellers   building · weakening · exhausted · absorbing
    Calls     building · distribution · unwinding · squeeze
    Puts      building · distribution · unwinding · squeeze
    Flow      entering · leaving · neutral
    Volume    healthy · dry · explosive
    → Overall ONE sentence

The distinctions that carry the value are the ones a level-reading misses:

  • **Absorbing** — pressure is high and price is NOT responding. Someone large
    is taking the other side. This looks identical to "building" in any snapshot
    and only exists as a comparison between pressure and price response.
  • **Exhausted** — pressure was high and is now collapsing after an extended
    move. The move is out of fuel, which is not the same as the other side
    taking control.

Both need history, so this is a trace-based engine like Stage 44 and 47.

Pure module: plain numbers in, states out.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# ── thresholds (v0, observational — tune from logs) ─────────────────────
_PRICE_MOVE = 0.06      # % move per cycle to count as directional
_EXPLODE = 0.30         # % move per cycle = expansion
_COMPRESS_RANGE = 0.10  # recent range % below this = compression
_PRESSURE_MOVE = 6.0    # CVD/delta points per cycle to count as changing
_VOL_DRY = 0.55         # volume below this × recent mean = dry
_VOL_EXPLODE = 1.9      # above this × mean = explosive
_OI_MOVE = 1.0          # % OI change to count as a build/unwind

_PRICE_STATES = ("rising", "falling", "flat", "compressing", "exploding")
_SIDE_STATES = ("building", "weakening", "exhausted", "absorbing", "neutral")
_OPT_STATES = ("building", "distribution", "unwinding", "squeeze", "flat")


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _series(trace: Sequence[Dict[str, Any]], key: str) -> List[float]:
    out = []
    for h in trace or []:
        v = _f((h or {}).get(key))
        if v is not None:
            out.append(v)
    return out


def _slope(s: Sequence[float]) -> float:
    n = len(s)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2.0
    my = sum(s) / n
    num = sum((i - mx) * (s[i] - my) for i in range(n))
    den = sum((i - mx) ** 2 for i in range(n))
    return (num / den) if den else 0.0


def trace_push(trace: Optional[List[Dict[str, Any]]], metrics: Dict[str, Any],
               keep: int = 12) -> List[Dict[str, Any]]:
    t = list(trace or [])
    t.append(dict(metrics or {}))
    return t[-keep:]


# ── 1 · PRICE ───────────────────────────────────────────────────────────
def classify_price(trace: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    px = _series(trace, "spot")
    if len(px) < 3:
        return {"state": "flat", "pct": 0.0, "label": "→ Flat"}
    last, prev = px[-1], px[-2]
    step = (last - prev) / prev * 100.0 if prev else 0.0
    hi, lo = max(px[-6:]), min(px[-6:])
    rng = (hi - lo) / lo * 100.0 if lo else 0.0

    if abs(step) >= _EXPLODE:
        st, lbl = "exploding", ("💥 Exploding " + ("up" if step > 0 else "down"))
    elif rng <= _COMPRESS_RANGE:
        st, lbl = "compressing", "🪤 Compressing"
    elif step >= _PRICE_MOVE:
        st, lbl = "rising", "⬆ Rising"
    elif step <= -_PRICE_MOVE:
        st, lbl = "falling", "⬇ Falling"
    else:
        st, lbl = "flat", "→ Flat"
    return {"state": st, "pct": round(step, 3), "range_pct": round(rng, 3),
            "label": lbl}


# ── 2-3 · BUYERS / SELLERS ──────────────────────────────────────────────
def classify_side(trace: Sequence[Dict[str, Any]], side: str) -> Dict[str, Any]:
    """`side` = 'buyers' or 'sellers'. Pressure comes from signed CVD: positive
    favours buyers, negative sellers.

    The two states that matter most are only visible by comparing pressure
    against PRICE RESPONSE:
      absorbing — pressure rising, price refusing to follow (someone is filling)
      exhausted — pressure was high, now collapsing after an extended move
    """
    cvd = _series(trace, "cvd")
    px = _series(trace, "spot")
    if len(cvd) < 3 or len(px) < 3:
        return {"state": "neutral", "label": "— unknown", "pressure": None}

    sign = 1.0 if side == "buyers" else -1.0
    # this side's pressure, always as a positive "how hard are they pushing"
    press = [max(0.0, sign * v) for v in cvd]
    now = press[-1]
    peak = max(press) or 1.0
    # Direction must be measured on a SHORT window. A 5-cycle slope across a
    # rise-then-fall stays positive (the ramp dominates) and reports "building"
    # at the exact moment pressure is collapsing — which is the reading this
    # engine exists to catch.
    slope = _slope(press[-3:])
    px_slope = _slope(px[-5:]) / (px[-1] or 1) * 100.0 * len(px[-5:])
    helps = px_slope * sign          # >0 = price moving this side's way

    if now <= peak * 0.15 and peak > 5:
        st, lbl = "weakening", "↓↓ Weakening"
    elif slope > _PRESSURE_MOVE and helps < _PRICE_MOVE / 2:
        # pushing hard, price not responding → the other side is filling them
        st, lbl = "absorbing", "🧱 Absorbing"
    elif peak >= 40 and now < peak * 0.85 and slope < -_PRESSURE_MOVE:
        # was genuinely strong, now coming off the peak — out of fuel
        st, lbl = "exhausted", "🥵 Exhausted"
    elif slope > _PRESSURE_MOVE:
        st, lbl = "building", "↑↑ Building"
    elif slope < -_PRESSURE_MOVE:
        st, lbl = "weakening", "↓ Weakening"
    else:
        st, lbl = "neutral", "→ Steady"
    return {"state": st, "label": lbl, "pressure": round(now, 1),
            "peak": round(peak, 1), "slope": round(slope, 2)}


# ── 4-5 · OPTION SIDES ──────────────────────────────────────────────────
def classify_option_side(ltp_slope: Optional[float],
                         oi_change_pct: Optional[float]) -> Dict[str, Any]:
    """The classic LTP × OI matrix, which says who is doing the trading:

        OI↑ LTP↑  long buildup      → buyers accumulating   (building)
        OI↑ LTP↓  short buildup     → writers selling it    (distribution)
        OI↓ LTP↓  long unwinding    → holders leaving       (unwinding)
        OI↓ LTP↑  short covering    → writers trapped       (squeeze)
    """
    l, o = _f(ltp_slope), _f(oi_change_pct)
    if l is None or o is None:
        return {"state": "flat", "label": "—"}
    if abs(o) < _OI_MOVE:
        return {"state": "flat", "label": "→ Flat"}
    if o > 0:
        return ({"state": "building", "label": "📈 Building (long buildup)"}
                if l > 0 else
                {"state": "distribution", "label": "📉 Distribution (writing)"})
    return ({"state": "squeeze", "label": "🔥 Squeeze (short covering)"}
            if l > 0 else
            {"state": "unwinding", "label": "🚪 Unwinding"})


# ── 6 · MONEY FLOW ──────────────────────────────────────────────────────
def classify_money_flow(trace: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    mf = _series(trace, "mf_net")
    if len(mf) < 2:
        return {"state": "neutral", "label": "→ Neutral"}
    s = _slope(mf[-5:])
    cur = mf[-1]
    if s > 0 and cur > 0:
        return {"state": "entering", "label": "💰 Entering", "slope": round(s, 1)}
    if s < 0 and cur < 0:
        return {"state": "leaving", "label": "🏃 Leaving", "slope": round(s, 1)}
    return {"state": "neutral", "label": "→ Neutral", "slope": round(s, 1)}


# ── 7 · VOLUME ──────────────────────────────────────────────────────────
def classify_volume(trace: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    v = _series(trace, "volume")
    if len(v) < 3:
        return {"state": "healthy", "label": "→ Normal", "mult": None}
    ref = sum(v[:-1]) / max(1, len(v) - 1)
    if ref <= 0:
        return {"state": "healthy", "label": "→ Normal", "mult": None}
    m = v[-1] / ref
    if m >= _VOL_EXPLODE:
        st, lbl = "explosive", "💥 Explosive"
    elif m <= _VOL_DRY:
        st, lbl = "dry", "🏜 Dry"
    else:
        st, lbl = "healthy", "✅ Healthy"
    return {"state": st, "label": lbl, "mult": round(m, 2)}


# ── 8 · THE ONE SENTENCE ────────────────────────────────────────────────
def describe(price: Dict[str, Any], buyers: Dict[str, Any],
             sellers: Dict[str, Any], flow: Dict[str, Any],
             vol: Dict[str, Any]) -> Dict[str, Any]:
    """One sentence. A trader glancing at this has two seconds."""
    b, s = buyers.get("state"), sellers.get("state")
    p, v = price.get("state"), vol.get("state")

    # absorption outranks everything — it is the least obvious and most useful
    if b == "absorbing":
        return {"text": "Buyers absorbing selling — supply being filled quietly.",
                "tone": "bull"}
    if s == "absorbing":
        return {"text": "Sellers absorbing buying — demand being capped quietly.",
                "tone": "bear"}
    if b == "exhausted" and s in ("building", "neutral"):
        return {"text": "Buyers exhausted — the advance is out of fuel.",
                "tone": "bear"}
    if s == "exhausted" and b in ("building", "neutral"):
        return {"text": "Sellers exhausted — the decline is out of fuel.",
                "tone": "bull"}
    if p == "compressing" and v == "dry":
        return {"text": "Compression before expansion — coiling on dry volume.",
                "tone": "neutral"}
    if p == "exploding":
        return {"text": f"Expansion underway — price {price.get('label', '').lower()} "
                        f"on {vol.get('state')} volume.", "tone":
                "bull" if price.get("pct", 0) > 0 else "bear"}
    if s == "building" and b == "weakening":
        return {"text": "Sellers building while buyers weaken — sellers gaining "
                        "control.", "tone": "bear"}
    if b == "building" and s == "weakening":
        return {"text": "Buyers building while sellers weaken — buyers gaining "
                        "control.", "tone": "bull"}
    if b == "building" and s == "building":
        return {"text": "Both sides committing — a genuine battle, no edge yet.",
                "tone": "neutral"}
    if flow.get("state") == "leaving" and p == "falling":
        return {"text": "Money leaving as price falls — distribution.", "tone": "bear"}
    if flow.get("state") == "entering" and p == "rising":
        return {"text": "Money entering as price rises — accumulation.", "tone": "bull"}
    return {"text": "Neutral battle — no side has committed.", "tone": "neutral"}


def analyse(trace: Optional[Sequence[Dict[str, Any]]],
            current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Full LTP behaviour read from the rolling metric trace."""
    tr = [dict(h) for h in (trace or [])]
    if current:
        tr = tr + [dict(current)]
    if len(tr) < 2:
        return {"ready": False, "overall": {"text": "Warming up — not enough "
                                                    "history to read intent.",
                                            "tone": "neutral"},
                "price": {"state": "flat", "label": "→ Flat"},
                "buyers": {"state": "neutral", "label": "—"},
                "sellers": {"state": "neutral", "label": "—"},
                "calls": {"state": "flat", "label": "—"},
                "puts": {"state": "flat", "label": "—"},
                "flow": {"state": "neutral", "label": "—"},
                "volume": {"state": "healthy", "label": "—"}, "n": len(tr)}

    price = classify_price(tr)
    buyers = classify_side(tr, "buyers")
    sellers = classify_side(tr, "sellers")
    flow = classify_money_flow(tr)
    vol = classify_volume(tr)
    calls = classify_option_side(_slope(_series(tr, "ce_ltp")[-5:]),
                                 (tr[-1] or {}).get("ce_oi_chg_pct"))
    puts = classify_option_side(_slope(_series(tr, "pe_ltp")[-5:]),
                                (tr[-1] or {}).get("pe_oi_chg_pct"))
    overall = describe(price, buyers, sellers, flow, vol)
    return {"ready": True, "price": price, "buyers": buyers, "sellers": sellers,
            "calls": calls, "puts": puts, "flow": flow, "volume": vol,
            "overall": overall, "n": len(tr)}
