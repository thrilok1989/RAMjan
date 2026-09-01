"""Alert when price reaches a key level — the war zone, an OI wall, or a ranked
support/resistance — within a small band.

Pure: it decides whether *this* reading of one level should fire, and words the
message. `vob_minimal` owns the memory (the armed/level state per level, which
survives between refreshes), gathers the levels from the reads that own them,
and sends.

Not spamming has two guards. The app reruns every ~20 seconds and price can sit
inside the ±band for many of them, so `evaluate` **latches**: it alerts once on
entry, disarms, and only re-arms after price has moved clear of the level by
`REARM` (wider than `BAND`, so a wobble at the boundary does not re-trigger).
The latch stops a continuous loiter from repeating — but price that keeps
leaving and re-entering the level (chopping across it) would clear the re-arm
each time and alert on every return. So a second guard, a **per-level cooldown**
(`COOLDOWN_S`), suppresses another alert for the same level within that window
however many times price re-enters. When the level itself moves (a new war-zone
price, a new OI wall) both guards reset, so the new level's first touch alerts.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

#: how close (in index points) counts as "at" a level. The owner asked for ±5.
BAND = 5.0

#: how far price must travel back OUT before another touch of the same level can
#: alert — wider than BAND so a wobble around the edge does not re-fire.
REARM = 10.0

#: two prices this close are treated as the same level (they arrive as whole
#: points, so anything under a point is the same level).
LEVEL_EPS = 0.5

#: minimum seconds between two alerts for the SAME level, even across separate
#: re-entries — the "sleep time" for a level price keeps chopping across. 15 min
#: matches the app's other repeat-alert throttle.
COOLDOWN_S = 900.0


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def evaluate(level: Any, spot: Any, state: Optional[Mapping[str, Any]],
             band: float = BAND, rearm: float = REARM,
             cooldown_s: float = COOLDOWN_S, now: Optional[float] = None
             ) -> Tuple[bool, Dict[str, Any]]:
    """Should this reading of ONE level fire, and what state carries forward?

    `state` is the previous `{'level', 'armed', 'alerted_at'}` for this level key
    (or None / {} the first time). Returns `(alert, new_state)`:

    * price within `band` of the level AND armed AND the cooldown has elapsed
      since the last alert for this level → alert once, then disarm and stamp
      the time;
    * price at least `rearm` from the level → re-arm (ready for the next touch);
    * a level that differs from the remembered one re-arms immediately AND clears
      the cooldown stamp, so the new level's first touch is never swallowed.

    `now` is epoch seconds; when it (or `cooldown_s`) is not supplied the
    cooldown is skipped and only the latch applies. Returns `(False, state)`
    unchanged when either number is unreadable — a missing level or spot is not
    a touch.
    """
    lv = _f(level)
    sp = _f(spot)
    if lv is None or sp is None:
        return False, dict(state or {})

    prev = state or {}
    prev_lv = _f(prev.get("level"))
    same_level = prev_lv is not None and abs(prev_lv - lv) <= LEVEL_EPS
    armed = bool(prev.get("armed", True)) if same_level else True
    # the last-alert stamp only carries forward for the SAME level — a moved
    # level starts its own cooldown.
    alerted_at = _f(prev.get("alerted_at")) if same_level else None

    dist = abs(sp - lv)
    alert = False
    if dist <= band and armed:
        cooling = (now is not None and alerted_at is not None
                   and (now - alerted_at) < cooldown_s)
        if cooling:
            # inside the sleep window: disarm so it stops checking every cycle,
            # but do NOT alert. It re-arms normally once price leaves by `rearm`.
            armed = False
        else:
            alert = True
            armed = False        # latch: no re-alert while price loiters here
            if now is not None:
                alerted_at = float(now)
    elif dist >= rearm:
        armed = True             # price has left — ready for the next touch

    out: Dict[str, Any] = {"level": lv, "armed": armed}
    if alerted_at is not None:
        out["alerted_at"] = alerted_at
    return alert, out


def message(label: str, price: float, spot: float, icon: str = "🎯",
            extra_lines: Optional[Sequence[Optional[str]]] = None) -> str:
    """The touch alert text: which level, and how far spot is from it.

    `extra_lines` carries whatever the level type wants to add at the moment of
    the touch — the war zone appends its expected winner and odds, an OI wall its
    open-interest size. `None`s are dropped so a caller need not filter them.
    """
    lines = [f"{icon} <b>Price at {label} ₹{price:,.0f}</b>",
             f"📍 Spot ₹{spot:,.1f} ({spot - price:+.0f} pts)"]
    lines += [ln for ln in (extra_lines or ()) if ln]
    return "\n".join(lines)


def dedupe(hits: Sequence[Tuple[str, float, str]]) -> list:
    """Collapse hits that fired at the SAME price this cycle, keeping the first.

    `hits` is `(label, price, message)` in priority order. When the war zone and
    a ranked support are the same number, the trader wants one alert, not three
    saying the same price — so a later hit whose price rounds to an earlier one
    is dropped. Returns the kept hits, order preserved.
    """
    kept = []
    seen = set()
    for label, price, msg in hits:
        p = _f(price)
        key = round(p) if p is not None else label
        if key in seen:
            continue
        seen.add(key)
        kept.append((label, price, msg))
    return kept
