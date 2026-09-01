"""MIOS V6 — Stage 47 Bias Transition (is the bias changing?).

The Bias Engine says *Bear 82%*. But traders rarely lose money because the bias
was wrong — they lose because **the bias was changing before they noticed**.

This engine reads the same seven evidence families as Stage 53, but across time:

    Dealer      92 → 84   ↓ weakening
    Order Flow  82 → 45   ↓↓ fast weakening
    Options     91 → 90   → stable

Bear still exists. Bear strength is collapsing. Those are different trades.

It answers five questions:
  • is the bias strengthening, weakening, or transitioning?
  • how FAST (velocity) and is the change itself accelerating?
  • how likely is an outright reversal?
  • **which family moved first** — the explanation for why the bias is turning;
  • how confident is any of that.

Signed strength is the unit throughout: `+strength` for BULL, `−strength` for
BEAR, `0` for NEUTRAL. That makes weakening (magnitude falling toward zero) and
reversal (sign flip) the same measurement at different stages, instead of two
special cases that can disagree.

Pure module: a trace of past family snapshots in, a verdict out.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: family → how much its move matters to the overall bias (mirrors Stage 53)
FAMILY_WEIGHT = {
    "dealer": 8.0, "institutions": 7.0, "orderflow": 6.0, "liquidity": 5.0,
    "structure": 4.0, "options": 3.0, "macro": 2.0,
}

#: a family must move this much (signed strength points) to count as changing
_MOVE = 8.0
#: overall magnitude change per cycle → velocity label
_FAST, _MODERATE = 6.0, 2.5
#: |signed bias| below this is effectively no conviction
_NEUTRAL_BAND = 15.0

_STATES = ("STABLE", "STRENGTHENING", "WEAKENING", "TRANSITION", "REVERSING")


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def signed_strength(direction: Optional[str], strength: Optional[float]) -> float:
    """BULL → +s, BEAR → −s, NEUTRAL → 0. One number that carries both the side
    and the conviction, so weakening and reversal are one continuum."""
    s = _f(strength) or 0.0
    d = str(direction or "").upper()
    if d.endswith("BULL"):
        return s
    if d.endswith("BEAR"):
        return -s
    return 0.0


def snapshot(families: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, float]:
    """One cycle's signed strength per family, from Stage 53's output."""
    out: Dict[str, float] = {}
    for name, f in (families or {}).items():
        if not f or f.get("status") != "OK":
            continue
        out[name] = round(signed_strength(f.get("direction"), f.get("strength")), 2)
    return out


def overall(snap: Optional[Dict[str, float]]) -> float:
    """Weighted signed bias for one cycle, in the same −100..+100 units."""
    num = den = 0.0
    for name, v in (snap or {}).items():
        w = FAMILY_WEIGHT.get(name, 1.0)
        num += w * v
        den += w
    return round(num / den, 2) if den else 0.0


def trace_push(trace: Optional[List[Dict[str, float]]], snap: Dict[str, float],
               keep: int = 15) -> List[Dict[str, float]]:
    t = list(trace or [])
    t.append(dict(snap or {}))
    return t[-keep:]


def _slope(series: Sequence[float]) -> float:
    """Average change per step over the series (least-squares slope)."""
    n = len(series)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2.0
    my = sum(series) / n
    num = sum((i - mx) * (series[i] - my) for i in range(n))
    den = sum((i - mx) ** 2 for i in range(n))
    return (num / den) if den else 0.0


def _velocity_label(v: float) -> str:
    a = abs(v)
    return "fast" if a >= _FAST else "moderate" if a >= _MODERATE else "slow"


def analyse(trace: Optional[Sequence[Dict[str, float]]],
            current: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Compare the current family snapshot against its recent history.

    Returns {state, label, bias, strength, velocity, velocity_label,
    acceleration, reversal_probability, leader, families, confidence, thesis}.
    """
    hist = [dict(h) for h in (trace or [])]
    if current:
        hist = hist + [dict(current)]
    if len(hist) < 2:
        cur = overall(hist[-1]) if hist else 0.0
        return {"state": "STABLE", "label": "→ Stable (no history yet)",
                "bias": _bias_word(cur), "strength": round(abs(cur)),
                "signed": cur, "velocity": 0.0, "velocity_label": "slow",
                "acceleration": 0.0, "reversal_probability": 0,
                "leader": None, "families": {}, "confidence": 0,
                "thesis": "Not enough history to judge whether the bias is changing.",
                "n_cycles": len(hist)}

    series = [overall(h) for h in hist]
    cur, prev = series[-1], series[-2]

    # velocity over the recent window; acceleration = is the change speeding up
    win = series[-5:] if len(series) >= 5 else series
    vel = _slope(win)
    half = max(2, len(win) // 2)
    accel = _slope(win[-half:]) - _slope(win[:half]) if len(win) >= 4 else 0.0

    # ── per-family change ──
    fams: Dict[str, Any] = {}
    for name in set().union(*[set(h) for h in hist[-6:]]) if hist else set():
        vals = [h.get(name) for h in hist[-6:] if name in h]
        vals = [v for v in vals if v is not None]
        if len(vals) < 2:
            continue
        d = vals[-1] - vals[0]
        fv = _slope(vals)
        # is the family reinforcing the current bias, or leaving it?
        toward = (d > 0) == (cur >= 0)
        moved = abs(d) >= _MOVE
        fams[name] = {
            "current": round(vals[-1], 1), "previous": round(vals[0], 1),
            "change": round(d, 1), "velocity": round(fv, 2),
            "velocity_label": _velocity_label(fv),
            "state": ("stable" if not moved else
                      "strengthening" if toward else "weakening"),
            # The arrow reads as CONVICTION, not raw sign: a bear family moving
            # −82 → −45 has a positive delta but is *losing* conviction, so it
            # must render ↓. Showing the signed direction here inverted the whole
            # radar exactly when a bias was decaying.
            "arrow": ("→" if not moved else
                      ("↑↑" if abs(fv) > _FAST else "↑") if toward else
                      ("↓↓" if abs(fv) > _FAST else "↓")),
        }

    # ── the LEADER: which family moved against the bias first? ──
    leader = None
    lead_cycle = 10 ** 6
    for name, f in fams.items():
        if f["state"] != "weakening":
            continue
        vals = [h.get(name) for h in hist[-6:] if name in h]
        vals = [v for v in vals if v is not None]
        base = vals[0]
        for i, v in enumerate(vals):
            if abs(v - base) >= _MOVE and (v - base > 0) != (cur >= 0):
                # earlier move wins; ties break toward the higher-authority family
                if i < lead_cycle or (i == lead_cycle and FAMILY_WEIGHT.get(name, 0)
                                      > FAMILY_WEIGHT.get(leader or "", 0)):
                    leader, lead_cycle = name, i
                break

    # ── state machine ──
    mag_now, mag_prev = abs(cur), abs(prev)
    flipped = (cur > 0) != (prev > 0) and min(mag_now, mag_prev) > 2
    toward_zero = mag_now < mag_prev
    delta_mag = mag_now - mag_prev

    if flipped and mag_now >= _NEUTRAL_BAND:
        state = "REVERSING"
    elif mag_now < _NEUTRAL_BAND and mag_prev >= _NEUTRAL_BAND:
        state = "TRANSITION"
    elif mag_now < _NEUTRAL_BAND:
        state = "TRANSITION" if abs(vel) >= _MODERATE else "STABLE"
    elif toward_zero and abs(delta_mag) >= 1.5:
        state = "WEAKENING"
    elif not toward_zero and abs(delta_mag) >= 1.5:
        state = "STRENGTHENING"
    else:
        state = "STABLE"

    # ── reversal probability ──
    # decay toward zero + speed + how many weighted families have left the bias
    left_w = sum(FAMILY_WEIGHT.get(n, 1.0) for n, f in fams.items()
                 if f["state"] == "weakening")
    tot_w = sum(FAMILY_WEIGHT.get(n, 1.0) for n in fams) or 1.0
    closeness = max(0.0, 1.0 - mag_now / 60.0)          # near zero = closer to flip
    speed = min(1.0, abs(vel) / (_FAST * 1.5))
    defect = left_w / tot_w
    rp = 100.0 * (0.40 * defect + 0.35 * closeness + 0.25 * speed)
    if state == "REVERSING":
        rp = max(rp, 80.0)
    elif state == "STRENGTHENING":
        rp *= 0.4
    reversal = int(max(0, min(99, round(rp))))

    conf = int(min(95, 30 + len(hist) * 6 + len(fams) * 4))
    lbl = {"STABLE": "→ Stable", "STRENGTHENING": "↑ Strengthening",
           "WEAKENING": "↓ Weakening", "TRANSITION": "🟡 Transition",
           "REVERSING": "🔄 Reversing"}[state]
    return {"state": state, "label": lbl, "bias": _bias_word(cur),
            "strength": round(mag_now), "signed": cur,
            "velocity": round(vel, 2), "velocity_label": _velocity_label(vel),
            "acceleration": round(accel, 2), "reversal_probability": reversal,
            "leader": leader, "families": fams, "confidence": conf,
            "n_cycles": len(hist),
            "thesis": build_thesis(state, _bias_word(cur), fams, leader,
                                   reversal, _velocity_label(vel))}


def _bias_word(signed: float) -> str:
    if signed > _NEUTRAL_BAND:
        return "BULL"
    if signed < -_NEUTRAL_BAND:
        return "BEAR"
    return "NEUTRAL"


def build_thesis(state: str, bias: str, fams: Dict[str, Any],
                 leader: Optional[str], reversal: int, vel: str) -> str:
    """The plain-language 'why' — what is changing and what to watch for."""
    nice = {"dealer": "Dealer positioning", "orderflow": "Order flow",
            "options": "Options positioning", "institutions": "Institutions",
            "liquidity": "Liquidity", "structure": "Structure", "macro": "Macro"}
    weak = [nice.get(n, n) for n, f in fams.items() if f["state"] == "weakening"]
    if state == "STABLE":
        return f"{bias.title()} bias holding — no material change across the families."
    if state == "STRENGTHENING":
        return f"{bias.title()} bias strengthening ({vel}) — families reinforcing."
    if state == "REVERSING":
        return (f"Bias has flipped to {bias.title()}"
                + (f", led by {nice.get(leader, leader)}" if leader else "")
                + " — treat prior-direction setups as invalid.")
    if state == "TRANSITION":
        return ("Bias has lost conviction and is in transition — "
                "no directional edge until it re-forms.")
    lead_txt = f", starting with {nice.get(leader, leader)}" if leader else ""
    watch = ("failed breakdown or liquidity reclaim" if bias == "BEAR"
             else "failed breakout or liquidity sweep")
    return (f"{bias.title()} bias remains, but "
            + (", ".join(weak[:3]) if weak else "conviction")
            + f" {'are' if len(weak) != 1 else 'is'} weakening{lead_txt} "
              f"({vel}). Reversal risk {reversal}%. Watch for {watch}.")


def for_validity(analysis: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The compact payload Stage 51 consumes — note `transition` is lower-case
    because the validity filter matches on 'weakening' / 'reversing'."""
    a = analysis or {}
    return {"bias": a.get("bias"), "strength": a.get("strength"),
            "transition": str(a.get("state") or "").lower(),
            "velocity": a.get("velocity_label"),
            "reversal_probability": a.get("reversal_probability"),
            "leader": a.get("leader"), "confidence": a.get("confidence")}
