"""📨 Flow-at-level alerts — a note to the ALTERNATE Telegram bot when one option
side is being TRADED HARD (a volume burst in that leg) while spot sits on the
matching level.

Two events, and only two, both to the second (alert) bot:

    · PUT activity spiking, and spot AT RESISTANCE   → puts being hit hard as the
      index tests overhead resistance
    · CALL activity spiking, and spot AT SUPPORT      → calls being hit hard as the
      index tests support beneath

⚠️ **No put-vs-call comparison.** An earlier version compared the two sides; the
desk corrected it — each leg is judged against ITS OWN recent normal. "Spiking"
means the leg's cumulative buy+sell is accumulating faster over the recent window
than over the window just before it, by `SPIKE_MULT`×. The activity numbers are the
`ATM±1 CALL vs PUT — Cum Buy / Cum Sell` graph's own (cumulative buy + cumulative
sell per side, CLV-weighted from 1m OHLCV), not recomputed here.

⚠️ **This decides nothing about volume or S/R itself.** `vob_minimal` passes in each
side's activity HISTORY and the ranked support/resistance; this says whether a
burst-at-a-level is happening now and, separately, whether that is a fresh crossing
worth sending — the flood the desk saw from the pivot alerts came from re-emitting a
standing condition every cycle, so the latch fires on the RISING EDGE only.

Pure: numbers in, a decision and a message out. No app import, no session, no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

#: How close spot must be to a level to count as "at" it, as a FRACTION of spot.
#: 0.25% — the owner's figure. A fraction, not a point band, so it means the same
#: on NIFTY at 24,000 and on a 77,700 underlying.
BAND_PCT = 0.0025

#: The recent window whose accumulation rate is the "current" burst, in seconds.
SHORT_S = 120.0

#: The window just BEFORE the recent one, whose rate is the "normal" to beat.
LONG_S = 900.0

#: How many times the baseline rate the recent rate must reach to be a spike.
SPIKE_MULT = 2.0

#: Once fired, the same event will not re-fire within this many seconds even if the
#: condition keeps flipping across the threshold — a level the price grinds on can
#: chatter true/false every cycle.
COOLDOWN_S = 300.0

#: The two events. `leg` is the side whose activity must spike; `level` is the S/R
#: the spot must be sitting on.
EVENTS = {
    "put_at_resistance": {"leg": "put", "level": "resistance"},
    "call_at_support": {"leg": "call", "level": "support"},
}


def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def activity(buy: Any, sell: Any) -> Optional[float]:
    """One side's total participation this instant: cumulative buy + cumulative
    sell. `None` when neither is readable."""
    b, s = _f(buy), _f(sell)
    if b is None and s is None:
        return None
    return (b or 0.0) + (s or 0.0)


def at_level(spot: Any, level: Any, band_pct: float = BAND_PCT) -> bool:
    """Is spot within `band_pct` of the level? `False` on any unreadable input."""
    sp, lv = _f(spot), _f(level)
    if sp is None or lv is None or sp <= 0:
        return False
    return abs(sp - lv) <= band_pct * sp


def _value_at(pts: Sequence[Tuple[float, float]], t: float) -> Optional[float]:
    """The cumulative value at the newest sample at or before time `t`; the oldest
    sample if `t` predates all of them. `pts` is (time, value) oldest→newest."""
    prior = [v for (ts, v) in pts if ts <= t]
    if prior:
        return prior[-1]
    return pts[0][1] if pts else None


def activity_spike(series: Sequence[Any], short_s: float = SHORT_S,
                   long_s: float = LONG_S, mult: float = SPIKE_MULT,
                   now: Optional[float] = None) -> Dict[str, Any]:
    """Is this leg's activity accumulating unusually fast RIGHT NOW?

    `series` is (time, cumulative_activity) samples, oldest→newest. Compares the
    per-second accumulation rate over the last `short_s` against the rate over the
    window just before it (`long_s` back to `short_s` back). Spiking when the recent
    rate is at least `mult`× the baseline.

    ⚠️ The baseline is the window BEFORE the recent one, not the whole span — so a
    burst is measured against the leg's own prior normal, not against itself. Resets
    (cumulative going down when the ATM strike rolls) are clamped to a zero delta, so
    a contract change is never read as a spike. `{spiking: False}` with too little
    history — a burst needs a normal to stand out from.
    """
    pts: List[Tuple[float, float]] = []
    for row in (series or ()):
        try:
            t, v = row[0], row[1]
        except (TypeError, IndexError):
            continue
        tf, vf = _f(t), _f(v)
        if tf is not None and vf is not None:
            pts.append((tf, vf))
    out = {"spiking": False, "ratio": None, "short_rate": None,
           "base_rate": None, "reason": None}
    if len(pts) < 3:
        out["reason"] = "insufficient history"
        return out
    pts.sort(key=lambda p: p[0])
    # ⚠️ Drop everything before the last RESET. A cumulative series only rises within
    # one contract; a drop means the ATM strike rolled and the aggregate restarted on
    # a different leg. The pre-reset samples are not comparable, so baseline must be
    # rebuilt from the new contract — and until there is enough of it, this is "not
    # enough history", never a spike. Without this a reset at the window boundary
    # reads as a burst.
    last_reset = 0
    for i in range(1, len(pts)):
        if pts[i][1] < pts[i - 1][1]:
            last_reset = i
    pts = pts[last_reset:]
    if len(pts) < 3:
        out["reason"] = "insufficient history since last reset"
        return out
    t_now = _f(now) if now is not None else pts[-1][0]
    if t_now is None:
        t_now = pts[-1][0]
    if t_now - pts[0][0] < long_s:
        out["reason"] = "history shorter than the baseline window"
        return out

    v_now = _value_at(pts, t_now)
    v_short = _value_at(pts, t_now - short_s)
    v_long = _value_at(pts, t_now - long_s)
    if v_now is None or v_short is None or v_long is None:
        out["reason"] = "gap in history"
        return out

    short_rate = max(0.0, v_now - v_short) / short_s
    base_span = long_s - short_s
    base_rate = max(0.0, v_short - v_long) / base_span if base_span > 0 else 0.0
    out["short_rate"], out["base_rate"] = short_rate, base_rate
    if base_rate <= 0:
        # no baseline activity → a spike only if the recent window itself moved
        out["spiking"] = short_rate > 0
        out["reason"] = "no prior activity to compare"
        return out
    ratio = short_rate / base_rate
    out["ratio"] = ratio
    out["spiking"] = ratio >= mult
    return out


def assess(call_series: Sequence[Any], put_series: Sequence[Any], spot: Any,
           support: Any = None, resistance: Any = None,
           band_pct: float = BAND_PCT, short_s: float = SHORT_S,
           long_s: float = LONG_S, mult: float = SPIKE_MULT,
           now: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """For each event, is it active THIS cycle, and the facts behind it.

    Active = the leg's activity is spiking AND spot is on the matching level. Each
    leg is judged against its own history; there is no cross-leg comparison.
    """
    spikes = {
        "call": activity_spike(call_series, short_s, long_s, mult, now),
        "put": activity_spike(put_series, short_s, long_s, mult, now),
    }
    sp = _f(spot)
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in EVENTS.items():
        level = resistance if spec["level"] == "resistance" else support
        lv = _f(level)
        on_level = at_level(sp, lv, band_pct)
        spike = spikes[spec["leg"]]
        out[name] = {
            "active": bool(on_level and spike["spiking"]),
            "on_level": on_level,
            "spiking": bool(spike["spiking"]),
            "ratio": spike.get("ratio"),
            "level": lv,
            "spot": sp,
        }
    return out


def latch(active: bool, prev: Optional[Mapping[str, Any]],
          now: float, cooldown_s: float = COOLDOWN_S
          ) -> Tuple[bool, Dict[str, Any]]:
    """Rising-edge latch with a cooldown. `(fire, new_state)`.

    Fires when `active` goes False→True, provided the cooldown since the last fire
    has elapsed. Re-arms whenever `active` is False. This is what stops the standing
    condition from re-alerting every cycle — the exact failure the pivot alerts had.
    """
    st = dict(prev or {})
    was = bool(st.get("active"))
    last = _f(st.get("last_fire")) or 0.0
    fire = False
    if active and not was and (now - last) >= cooldown_s:
        fire = True
        st["last_fire"] = now
    st["active"] = bool(active)
    return fire, st


def message(event: str, info: Mapping[str, Any],
            call_label: str = "ATM Call", put_label: str = "ATM Put") -> str:
    """The alert text for one fired event. HTML, for Telegram."""
    spec = EVENTS.get(event) or {}
    leg = spec.get("leg")
    level_kind = spec.get("level")
    sp = _f(info.get("spot"))
    lv = _f(info.get("level"))
    ratio = _f(info.get("ratio"))
    leg_label = put_label if leg == "put" else call_label
    icon = "🧱" if level_kind == "resistance" else "🛡"
    ball = "🔴" if leg == "put" else "🟢"
    sp_s = "—" if sp is None else f"₹{sp:,.0f}"
    lv_s = "—" if lv is None else f"₹{lv:,.0f}"
    burst = f" ({ratio:.1f}× its recent average)" if ratio is not None else ""
    return (
        f"{ball} {icon} <b>{leg_label} traded hard at {level_kind}</b>\n"
        f"Spot {sp_s} is at {level_kind} {lv_s}, and {leg_label} buy+sell "
        f"volume is spiking{burst}."
    )
