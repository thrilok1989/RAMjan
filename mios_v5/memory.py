"""MIOS V6 — Stage 54 Market Memory (how long, and how committed?).

Every other engine answers *what* the market is doing. This answers **how long it
has been doing it, and whether that commitment is growing or decaying**.

Institutions do not change their mind every minute. A market that has held
DISTRIBUTION for 43 minutes with rising seller strength is a different animal
from one that flickered into distribution 90 seconds ago — and every engine
downstream should treat them differently:

    Distribution · 2 min  · ★★☆☆☆  →  WAIT
    Distribution · 45 min · ★★★★★  →  act on it

It tracks every engine that emits a state — Market State (48), Bias Transition
(47), Energy (37), Acceptance (42), Flow Stability (44), Zone Lifecycle (35) —
and for each stores: current · previous · started · duration · strength ·
confidence · trend · transition risk.

**Decay detection is the subtle half.** A state whose duration is long but whose
underlying strength is falling is not "still strong" — it is *tiring*, and that
is precisely when it flips. Reporting duration alone would make MIOS most
confident immediately before a reversal.

Pure module: observations + prior memory in, updated memory out. The caller owns
persistence and supplies the clock.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

#: minutes → star rating. Commitment is earned by lasting, not by arriving.
_STRENGTH_STEPS = ((55.0, 5), (30.0, 4), (15.0, 3), (5.0, 2), (0.0, 1))

#: how many samples of the owning engine's confidence we keep per state
_KEEP = 10

#: confidence drift per cycle that counts as a real trend
_TREND_EPS = 0.8

TRACKED = ("market_state", "bias_transition", "energy", "acceptance",
           "flow_stability", "zone_lifecycle")

LABEL = {"market_state": "Market State", "bias_transition": "Bias",
         "energy": "Energy", "acceptance": "Reaction",
         "flow_stability": "Flow", "zone_lifecycle": "Zone"}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def strength_stars(minutes: float) -> int:
    m = max(0.0, float(minutes or 0))
    for threshold, stars in _STRENGTH_STEPS:
        if m >= threshold:
            return stars
    return 1


def stars_str(n: int) -> str:
    n = max(0, min(5, int(n)))
    return "★" * n + "☆" * (5 - n)


def _slope(s: List[float]) -> float:
    n = len(s)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2.0
    my = sum(s) / n
    num = sum((i - mx) * (s[i] - my) for i in range(n))
    den = sum((i - mx) ** 2 for i in range(n))
    return (num / den) if den else 0.0


def track(prior: Optional[Dict[str, Any]],
          observations: Optional[Dict[str, Any]],
          now_ts: float = 0.0) -> Dict[str, Any]:
    """Advance memory by one cycle.

    `observations`: {key: {"state": str, "confidence": float}} — one entry per
    tracked engine. A state that repeats accrues duration and strength; a state
    that changes resets the clock and records what it came from.
    """
    mem = {k: dict(v) for k, v in (prior or {}).items()}
    obs = observations or {}

    for key, o in obs.items():
        st = o.get("state")
        if not st:
            continue
        conf = _f(o.get("confidence")) or 0.0
        e = mem.get(key)

        if e and e.get("state") == st:
            # same state — it is earning its commitment
            e["last_ts"] = now_ts
            e["cycles"] = int(e.get("cycles", 0)) + 1
            e["duration_min"] = round(max(0.0, (now_ts - e.get("started_ts", now_ts))
                                          ) / 60.0, 1)
            hist = list(e.get("conf_history") or [])
            hist.append(conf)
            e["conf_history"] = hist[-_KEEP:]
        else:
            # transition — remember what it came FROM, then restart the clock
            mem[key] = {
                "state": st, "previous": (e or {}).get("state"),
                "previous_duration_min": (e or {}).get("duration_min", 0.0),
                "started_ts": now_ts, "last_ts": now_ts,
                "cycles": 1, "duration_min": 0.0,
                "conf_history": [conf],
            }
            e = mem[key]

        e.update(_assess(e))
    return mem


def _assess(e: Dict[str, Any]) -> Dict[str, Any]:
    """Strength, trend and transition risk for one tracked state."""
    dur = float(e.get("duration_min") or 0.0)
    stars = strength_stars(dur)
    hist = [h for h in (e.get("conf_history") or []) if h is not None]
    slope = _slope(hist[-6:]) if len(hist) >= 3 else 0.0

    # 0.8 points/cycle ≈ 5 points across the 6-sample window — meaningful drift
    # on a 0-100 confidence scale. A 1.5 threshold missed a steady drain that
    # collapsed conviction by 60 points, reporting "steady" the whole way down.
    if slope > _TREND_EPS:
        trend = "increasing"
    elif slope < -_TREND_EPS:
        trend = "decreasing"
    else:
        trend = "steady"

    # persistence: how established this state is (duration-driven, capped)
    persistence = int(min(100.0, dur / 55.0 * 100.0)) if dur else 0

    # ── decay: long duration + falling conviction = tiring, not strong ──
    # Without this, memory would report maximum confidence in the minutes
    # immediately before a flip, which is the worst possible time to be sure.
    risk = 0.0
    if trend == "decreasing":
        risk = 35.0 + min(40.0, abs(slope) * 6.0)
        if dur >= 30:
            risk += 15.0                     # an old, tiring state is ripe
    elif dur >= 55 and trend == "steady":
        risk = 25.0                          # even healthy states age out
    transition_risk = int(max(0, min(95, round(risk))))

    return {"stars": stars, "stars_str": stars_str(stars), "trend": trend,
            "conf_slope": round(slope, 2), "persistence": persistence,
            "transition_risk": transition_risk,
            "mature": dur >= 15.0,
            "fresh": dur < 5.0}


def get(mem: Optional[Dict[str, Any]], key: str) -> Dict[str, Any]:
    return dict((mem or {}).get(key) or {})


def describe(mem: Optional[Dict[str, Any]], key: str = "market_state") -> str:
    """The sentence that turns a label into a judgement."""
    e = get(mem, key)
    if not e.get("state"):
        return "No memory yet."
    st = str(e["state"]).replace("_", " ").title()
    dur = e.get("duration_min", 0.0)
    if e.get("fresh"):
        return (f"{st} has only just formed ({dur:.0f} min) — too young to "
                f"act on with conviction.")
    trend = e.get("trend")
    if trend == "decreasing":
        return (f"{st} has held {dur:.0f} min but its conviction is fading — "
                f"transition risk {e.get('transition_risk', 0)}%.")
    if trend == "increasing":
        return (f"{st} has held {dur:.0f} min with strength increasing "
                f"throughout — institutional participation, not an intraday "
                f"flicker.")
    return f"{st} has held steady for {dur:.0f} min."


def summary(mem: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dashboard rows, most-established first."""
    rows = []
    for key in TRACKED:
        e = get(mem, key)
        if not e.get("state"):
            continue
        rows.append({"key": key, "label": LABEL.get(key, key), **e})
    return sorted(rows, key=lambda r: -float(r.get("duration_min") or 0))


def for_validity(mem: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What Stage 51 and the Decision Engine consume: is the state old enough
    and committed enough to be worth acting on?"""
    ms = get(mem, "market_state")
    bs = get(mem, "bias_transition")
    return {
        "state": ms.get("state"),
        "state_duration_min": ms.get("duration_min", 0.0),
        "state_stars": ms.get("stars", 0),
        "state_trend": ms.get("trend"),
        "state_mature": bool(ms.get("mature")),
        "state_fresh": bool(ms.get("fresh")),
        "state_transition_risk": ms.get("transition_risk", 0),
        "bias_duration_min": bs.get("duration_min", 0.0),
        "bias_state": bs.get("state"),
    }
