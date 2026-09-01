"""MIOS V6 — Stage 69 Market Session Intelligence.

A 09:20 breakout is not a 13:00 breakout. The same evidence means different
things depending on where in the session it appears, and until now MIOS read
every signal the same way at every hour.

This engine answers *where in the day we are, and what this session is actually
doing* — then publishes a set of **contextual modifiers** that make the other
engines session-aware.

    Pre-Open · Opening Auction · Opening Drive · Morning Trend ·
    Midday Balance · Afternoon Trend · Closing · Closed

## Why this is not Stage 6

Stage 6 is a **pure clock** — its own docstring says "no market data". It maps
the time to a phase and a conviction weight, and `confidence_tempered` has
depended on that weight since V5. This engine measures what the session is
*doing*: strength, momentum, volatility, liquidity, trend quality, and who is
participating.

They use different window boundaries, and two engines naming the session
differently would be a genuine defect — the header saying "Institutional Entry /
ORB" while the panel says "Morning Trend". So: **Stage 69 owns the session
name** (the finer 8-window split), and **reads Stage 6's conviction** rather than
recomputing it. One name, one conviction, no drift.

## The modifiers are published, not applied

This is the part that needed care. Making Stage 51 demand a higher score at
midday, or Stage 44 ignore small spikes at the open, is a much stronger
intervention than a context engine normally makes — it changes what MIOS
trades.

The standing rule outranks the feature: *"Every engine ships observational-only
and logged. Nothing influences a decision until it has proven itself."* So the
modifiers are computed, published and logged every cycle, and `SESSION_AWARE`
gates whether any consumer applies them. It is **False** until live data shows
the session-adjusted stack beats the flat one. Flipping one constant turns it
on; the panel shows what it *would* have done either way, which is exactly the
evidence needed to decide.

Everything measured here is read from an engine that already computed it. This
module classifies and modulates; it calculates no market quantity of its own,
and it never emits a direction.

Pure module.
"""

from __future__ import annotations

from datetime import time as dtime
from typing import Any, Dict, List, Optional, Tuple

#: ⛔ The master switch. Consumers apply Stage 69's modifiers only when this is
#: True. Left False deliberately: the session-adjusted stack has not been shown
#: to beat the flat one on live data, and promoting it on reasoning alone is the
#: exact mistake the observational rule exists to prevent.
SESSION_AWARE = False

#: (key, start, end, label) — IST. Boundaries are the spec's, which are finer
#: than Stage 6's and match how a desk actually talks about the day.
WINDOWS: Tuple[Tuple[str, dtime, dtime, str], ...] = (
    ("PRE_OPEN",         dtime(9, 0),  dtime(9, 15),  "🌅 Pre-Open"),
    ("OPENING_AUCTION",  dtime(9, 15), dtime(9, 20),  "🔔 Opening Auction"),
    ("OPENING_DRIVE",    dtime(9, 20), dtime(9, 45),  "🚀 Opening Drive"),
    ("MORNING_TREND",    dtime(9, 45), dtime(11, 30), "📈 Morning Trend"),
    ("MIDDAY_BALANCE",   dtime(11, 30), dtime(13, 30), "😴 Midday Balance"),
    ("AFTERNOON_TREND",  dtime(13, 30), dtime(15, 0),  "🏛 Afternoon Trend"),
    ("CLOSING",          dtime(15, 0), dtime(15, 30), "🔚 Closing Session"),
)

CLOSED = ("CLOSED", "🌙 Market Closed")

#: what each session is FOR, and what typically happens in it
PURPOSE = {
    "PRE_OPEN": ["Opening imbalance", "Overnight gap analysis",
                 "Dealer positioning", "Global market influence"],
    "OPENING_AUCTION": ["Highest uncertainty", "Wide spreads",
                        "Initial positioning"],
    "OPENING_DRIVE": ["Strong directional moves", "Highest volatility",
                      "Institutional execution", "False breakouts common"],
    "MORNING_TREND": ["Trend development", "Genuine accumulation/distribution",
                      "Dealer adjustments"],
    "MIDDAY_BALANCE": ["Low volume", "Sideways movement", "Compression",
                       "Mean reversion", "Choppy conditions"],
    "AFTERNOON_TREND": ["Fresh institutional participation",
                        "Breakout continuation", "Option repositioning"],
    "CLOSING": ["Position squaring", "Expiry effects", "Dealer hedging",
                "Large institutional orders"],
    "CLOSED": ["Learning", "Replay", "Analytics", "Dashboard summaries"],
}

#: recommended style per session — what to do, and what NOT to
STYLE = {
    "PRE_OPEN": (["Plan, do not trade", "Mark the gap and yesterday's levels"],
                 ["Pre-positioning on the gap"]),
    "OPENING_AUCTION": (["Stand aside", "Let the spread settle"],
                        ["Any entry — the book is not price discovery yet"]),
    "OPENING_DRIVE": (["Wait for the first level to be PROVEN, not touched",
                       "Half size if you must act"],
                      ["Chasing the first breakout", "Trusting a 5-minute trend"]),
    "MORNING_TREND": (["Trend-following setups preferred",
                       "Pullback entries", "Normal size"],
                      ["Fading a confirmed trend"]),
    "MIDDAY_BALANCE": (["Fade the extremes of the range", "Smaller targets",
                        "Require multiple confirmations"],
                       ["Breakout trades", "Expecting follow-through"]),
    "AFTERNOON_TREND": (["Breakout continuation", "Normal thresholds",
                         "Trail rather than fixed targets"],
                        ["Assuming the morning range still holds"]),
    "CLOSING": (["High-confidence setups only", "Require dealer agreement",
                 "Reduce size into the close"],
                ["New positions on thin evidence", "Holding through the auction"]),
    "CLOSED": (["Review, replay, learn"], ["Trading"]),
}

BEHAVIOURS = ("TRENDING", "SIDEWAYS", "CHOPPY", "EXPANDING", "COMPRESSING",
              "EXPIRY", "RANGE_BUILDING", "TREND_BUILDING",
              "TREND_EXHAUSTION", "UNKNOWN")

BEHAVIOUR_LABEL = {
    "TRENDING": "📈 Trending Session", "SIDEWAYS": "↔ Sideways Session",
    "CHOPPY": "🔪 Choppy Session", "EXPANDING": "💥 Expanding Session",
    "COMPRESSING": "🪤 Compressing Session", "EXPIRY": "🧲 Expiry Behaviour",
    "RANGE_BUILDING": "🏗 Range Building", "TREND_BUILDING": "🏗 Trend Building",
    "TREND_EXHAUSTION": "🥵 Trend Exhaustion", "UNKNOWN": "❔ Not yet readable",
}

#: the nine session measures, in display order
MEASURES = ("strength", "momentum", "volatility", "liquidity", "trend_quality",
            "institutional", "dealer", "orderflow", "options")

MEASURE_LABEL = {
    "strength": "Session Strength", "momentum": "Session Momentum",
    "volatility": "Session Volatility", "liquidity": "Session Liquidity",
    "trend_quality": "Trend Quality", "institutional": "Institutional Activity",
    "dealer": "Dealer Activity", "orderflow": "Order Flow Quality",
    "options": "Options Activity",
}

_LEVEL = ("None", "Low", "Medium", "High", "Very High")


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "").upper()


def _band(pct: Optional[float]) -> str:
    p = _f(pct)
    if p is None:
        return "—"
    return _LEVEL[max(0, min(4, int(p // 25)))]


# ── where in the day are we ─────────────────────────────────────────────
def classify(now: Any = None) -> Dict[str, Any]:
    """The current session window, how far through it we are, and what's next."""
    from .clock import now as clock_now
    from .clock import to_ist

    d = to_ist(now) or clock_now()
    t = d.time()

    for i, (key, start, end, label) in enumerate(WINDOWS):
        if start <= t < end:
            elapsed = (d.hour * 60 + d.minute) - (start.hour * 60 + start.minute)
            total = ((end.hour * 60 + end.minute)
                     - (start.hour * 60 + start.minute))
            nxt = WINDOWS[i + 1] if i + 1 < len(WINDOWS) else None
            return {
                "session": key, "label": label,
                "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M"),
                "minutes_elapsed": max(0, elapsed),
                "minutes_remaining": max(0, total - elapsed),
                "minutes_total": total,
                "pct_through": round(100.0 * max(0, elapsed) / total)
                               if total else 0,
                "next_session": (nxt[0] if nxt else CLOSED[0]),
                "next_label": (nxt[3] if nxt else CLOSED[1]),
                "open": True, "purpose": PURPOSE.get(key, []),
                "recommended": STYLE.get(key, ([], []))[0],
                "avoid": STYLE.get(key, ([], []))[1],
                "time": d.strftime("%H:%M"),
            }

    after = t >= dtime(15, 30)
    return {
        "session": CLOSED[0], "label": CLOSED[1],
        "start": "15:30" if after else "00:00",
        "end": "09:00", "minutes_elapsed": None,
        "minutes_remaining": None, "minutes_total": None, "pct_through": None,
        "next_session": "PRE_OPEN", "next_label": "🌅 Pre-Open",
        "open": False, "purpose": PURPOSE["CLOSED"],
        "recommended": STYLE["CLOSED"][0], "avoid": STYLE["CLOSED"][1],
        "time": d.strftime("%H:%M"),
    }


# ── what is this session actually doing ─────────────────────────────────
def intelligence(final_read: Optional[Dict[str, Any]] = None,
                 price: Optional[Dict[str, Any]] = None
                 ) -> Dict[str, Dict[str, Any]]:
    """The nine measures, each read from the engine that owns it.

    Nothing is computed here. A measure whose owning engine has not reported is
    returned as unavailable rather than defaulted — a session panel showing
    "Liquidity: Medium" because nothing answered would be worse than a dash.
    """
    from .final_read import section
    fr, p = dict(final_read or {}), dict(price or {})

    def m(key, value, level, engine, detail=""):
        return {"key": key, "label": MEASURE_LABEL[key], "value": value,
                "level": level, "engine": engine, "detail": detail,
                "available": value is not None}

    tr = fr.get("transition") or {}
    ltp = fr.get("ltp_behaviour") or {}
    en = fr.get("energy_read") or {}
    ms = fr.get("market_state") or {}
    mem = fr.get("memory_read") or {}
    fam = fr.get("families") or {}

    strength = _f(tr.get("strength"))
    stab = _s(fr.get("stability"))
    price_state = _s((ltp.get("price") or {}).get("state"))
    vol_state = _s((ltp.get("volume") or {}).get("state"))
    energy = _s(en.get("state"))
    atr = _f(p.get("atr_pct"))
    liq = section(fr, "liquidity")
    inst = fam.get("institutions") or {}
    dealer_fam = fam.get("dealer") or {}
    of = section(fr, "orderflow")
    opt = section(fr, "options")
    dur = _f(mem.get("state_duration_min"))

    momentum = ({"RISING": 80.0, "FALLING": 80.0, "EXPLODING": 95.0,
                 "COMPRESSING": 25.0, "FLAT": 15.0}.get(price_state)
                if price_state else None)
    volatility = (atr * 60.0 if atr is not None else
                  {"EXPANSION": 80.0, "RELEASED": 90.0, "BUILDING": 55.0,
                   "COMPRESSION": 25.0, "DEAD": 10.0}.get(energy))
    liquidity = ({"EXPLOSIVE": 95.0, "HEALTHY": 70.0, "DRY": 15.0}.get(vol_state)
                 if vol_state else _f(liq.get("confidence")))
    quality = None
    if ms.get("state"):
        quality = min(100.0, (dur or 0.0) * 1.8 + (30.0 if stab == "STABLE"
                                                   else 0.0))

    return {x["key"]: x for x in (
        m("strength", strength, _band(strength), "Stage 47 Bias Transition",
          str(tr.get("label") or "")),
        m("momentum", momentum, _band(momentum), "Stage 50 LTP Behaviour",
          str((ltp.get("price") or {}).get("label") or "")),
        m("volatility", volatility, _band(volatility),
          "Stage 37 Energy" + (" · ATR" if atr is not None else ""),
          f"ATR {atr:.2f}% of spot" if atr is not None else str(energy or "")),
        m("liquidity", liquidity, _band(liquidity), "Stage 50 Volume",
          str((ltp.get("volume") or {}).get("label") or "")),
        m("trend_quality", quality, _band(quality),
          "Stage 48 State × Stage 54 Memory",
          f"{ms.get('label', '')} held {dur:.0f} min" if dur else ""),
        m("institutional", _f(inst.get("strength")),
          _band(_f(inst.get("strength"))), "Stage 53 Evidence",
          f"{inst.get('direction', '')} ({str(inst.get('reliability', '')).lower()})"),
        m("dealer", _f(dealer_fam.get("strength")),
          _band(_f(dealer_fam.get("strength"))), "Stage 11 Dealer",
          str(dealer_fam.get("direction") or "")),
        m("orderflow", _f(of.get("confidence")) or None,
          _band(_f(of.get("confidence"))), "Stage 14 Order Flow",
          str(of.get("headline") or "")),
        m("options", _f(opt.get("confidence")) or None,
          _band(_f(opt.get("confidence"))), "Stage 12 Options",
          str(opt.get("headline") or "")),
    )}


def behaviour(final_read: Optional[Dict[str, Any]] = None,
              measures: Optional[Dict[str, Dict[str, Any]]] = None,
              session: Optional[str] = None) -> Dict[str, Any]:
    """One session behaviour, with the reads that produced it."""
    fr = dict(final_read or {})
    ms = fr.get("market_state") or {}
    en = _s((fr.get("energy_read") or {}).get("state"))
    tr = fr.get("transition") or {}
    ab = _s((fr.get("absorption") or {}).get("behaviour"))
    stab = _s(fr.get("stability"))
    state = _s(ms.get("state"))
    reasons: List[str] = []

    def pick(key, why):
        reasons.append(why)
        return key

    if fr.get("is_expiry"):
        b = pick("EXPIRY", "expiry day — dealer hedging dominates")
    elif stab in ("SHOCK", "UNSTABLE") or _s(tr.get("state")) == "REVERSING":
        b = pick("CHOPPY", f"tape {stab.lower() or 'reversing'}")
    elif ab.endswith("EXHAUSTION"):
        b = pick("TREND_EXHAUSTION", "absorption reports exhaustion")
    elif en in ("EXPANSION", "RELEASED"):
        b = pick("EXPANDING", f"energy {en.lower()}")
    elif en == "COMPRESSION":
        b = pick("COMPRESSING", "energy compressing")
    elif state in ("TREND_UP", "TREND_DOWN", "MARKUP", "MARKDOWN"):
        b = (pick("TREND_BUILDING", "trend state, still young")
             if _s(tr.get("state")) == "STRENGTHENING"
             else pick("TRENDING", f"market state {ms.get('label', state)}"))
    elif state in ("ACCUMULATION", "DISTRIBUTION"):
        b = pick("RANGE_BUILDING", f"market state {ms.get('label', state)}")
    elif state in ("ROTATION", "RANGE"):
        b = pick("SIDEWAYS", f"market state {ms.get('label', state)}")
    elif state:
        b = pick("SIDEWAYS", f"market state {ms.get('label', state)}")
    else:
        b = pick("UNKNOWN", "no market state reported yet")

    return {"behaviour": b, "label": BEHAVIOUR_LABEL[b], "reasons": reasons}


# ── the contextual modifiers ────────────────────────────────────────────
#: session → per-engine modifier. Every value is bounded and every one carries
#: the reason a human can argue with. Nothing here is applied while
#: `SESSION_AWARE` is False.
_MODIFIERS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "PRE_OPEN": {
        "stage52_decision": {"stance": "NO_TRADE",
                             "reason": "pre-open — no price discovery yet"},
    },
    "OPENING_AUCTION": {
        "stage52_decision": {"stance": "NO_TRADE",
                             "reason": "auction — the book is not price yet"},
        "stage44_flow_shift": {"sensitivity": 0.4,
                               "reason": "auction prints are not flow"},
    },
    "OPENING_DRIVE": {
        "stage42_acceptance": {"breakout_confidence": -15,
                               "require_extra_confirmation": True,
                               "reason": "false breakouts are common in the "
                                         "opening drive"},
        "stage44_flow_shift": {"sensitivity": 0.6,
                               "reason": "opening spikes are normal — ignore "
                                         "small ones"},
        "stage51_validity": {"threshold_delta": 10,
                             "reason": "require stronger confirmation before "
                                       "the trend is established"},
        "stage52_decision": {"stance": "WAIT",
                             "reason": "trend not established"},
    },
    "MORNING_TREND": {
        "stage52_decision": {"stance": "NORMAL",
                             "reason": "genuine trend development window"},
    },
    "MIDDAY_BALANCE": {
        "stage42_acceptance": {"rejection_confidence": 10,
                               "breakout_confidence": -10,
                               "require_extra_confirmation": True,
                               "reason": "midday breakouts usually fail"},
        "stage44_flow_shift": {"sensitivity": 1.4,
                               "reason": "a small spike in a quiet tape is "
                                         "meaningful"},
        "stage50_ltp_behaviour": {"significance": 1.3,
                                  "reason": "buying into midday compression "
                                            "means more than buying at the open"},
        "stage51_validity": {"threshold_delta": 12,
                             "reason": "require multiple confirmations"},
        "stage52_decision": {"stance": "WAIT",
                             "reason": "poor reward-to-risk in balance"},
    },
    "AFTERNOON_TREND": {
        "stage52_decision": {"stance": "NORMAL",
                             "reason": "fresh institutional participation"},
    },
    "CLOSING": {
        "stage42_acceptance": {"reason": "watch for dealer-driven reversals",
                               "require_extra_confirmation": True},
        "stage44_flow_shift": {"sensitivity": 1.2, "institutional_weight": 1.3,
                               "reason": "closing flow is institutional"},
        "stage51_validity": {"threshold_delta": 8, "require_dealer": True,
                             "reason": "require dealer agreement into the close"},
        "stage52_decision": {"stance": "HIGH_CONFIDENCE_ONLY",
                             "reason": "square-off flows distort the tape"},
    },
    "CLOSED": {
        "stage52_decision": {"stance": "NO_TRADE", "reason": "market closed"},
    },
}

#: behaviour → an extra modifier layered on top of the session's
_BEHAVIOUR_MODIFIERS = {
    "CHOPPY": {"stage51_validity": {"threshold_delta": 10,
                                    "reason": "choppy session"},
               "stage52_decision": {"stance": "WAIT",
                                    "reason": "choppy session"}},
    "TREND_EXHAUSTION": {"stage52_decision": {"stance": "HIGH_CONFIDENCE_ONLY",
                                              "reason": "trend exhausting"}},
    "EXPIRY": {"stage42_acceptance": {"breakout_confidence": -12,
                                      "reason": "expiry pin fades breakouts"}},
}

#: decision stances, weakest constraint first
_STANCE_RANK = {"NORMAL": 0, "WAIT": 1, "HIGH_CONFIDENCE_ONLY": 2,
                "NO_TRADE": 3}


def modifiers(session: str,
              behaviour_key: Optional[str] = None) -> Dict[str, Any]:
    """Per-engine contextual modifiers for this session and behaviour.

    Layered, not replaced: a choppy Midday Balance is stricter than either
    alone. Where two layers set the same decision stance the **more
    conservative** one wins — a session that says WAIT and a behaviour that
    says NORMAL must not resolve to NORMAL.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for layer in (_MODIFIERS.get(session, {}),
                  _BEHAVIOUR_MODIFIERS.get(behaviour_key or "", {})):
        for engine, mod in layer.items():
            cur = out.setdefault(engine, {})
            for k, v in mod.items():
                if k == "stance":
                    if _STANCE_RANK.get(v, 0) >= _STANCE_RANK.get(
                            cur.get("stance", "NORMAL"), 0):
                        cur["stance"] = v
                elif k == "reason":
                    cur["reason"] = (f"{cur['reason']}; {v}"
                                     if cur.get("reason") else v)
                elif k == "threshold_delta":
                    cur[k] = max(cur.get(k, 0), v)
                elif isinstance(v, bool):
                    cur[k] = cur.get(k, False) or v
                else:
                    cur[k] = v
    return {"applies_to": out, "applied": SESSION_AWARE,
            "note": ("APPLIED — session-aware engines are live."
                     if SESSION_AWARE else
                     "PUBLISHED, NOT APPLIED — observational until live data "
                     "shows the session-adjusted stack beats the flat one. "
                     "Set session.SESSION_AWARE = True to promote.")}


def modifier_for(mods: Optional[Dict[str, Any]], engine: str
                 ) -> Dict[str, Any]:
    """What `engine` should apply — **empty while `SESSION_AWARE` is False**.

    Consumers call this rather than reading `applies_to` directly, so the gate
    cannot be bypassed by accident.
    """
    m = dict(mods or {})
    if not m.get("applied"):
        return {}
    return dict((m.get("applies_to") or {}).get(engine) or {})


# ── the whole read ──────────────────────────────────────────────────────
def read(final_read: Optional[Dict[str, Any]] = None,
         price: Optional[Dict[str, Any]] = None,
         now: Any = None,
         conviction: Any = None) -> Dict[str, Any]:
    """Session + measures + behaviour + modifiers, in one payload."""
    c = classify(now)
    meas = intelligence(final_read, price)
    beh = behaviour(final_read, meas, c["session"])
    mods = modifiers(c["session"], beh["behaviour"])
    conv = _f(conviction)

    return {
        **c,
        "measures": meas,
        "measures_available": sum(1 for m in meas.values() if m["available"]),
        "behaviour": beh["behaviour"], "behaviour_label": beh["label"],
        "behaviour_reasons": beh["reasons"],
        # Stage 6 owns the conviction weight `confidence_tempered` uses; it is
        # carried through rather than recomputed, so the two can never disagree
        "conviction": conv, "conviction_source": "Stage 6 Time Cycle",
        "modifiers": mods,
        "mood": beh["label"],
        "sentence": _sentence(c, beh, meas, conv),
        # binding: context only. No direction, no signal, no override.
        "advisory_only": True,
    }


def _sentence(c: Dict[str, Any], beh: Dict[str, Any],
              meas: Dict[str, Dict[str, Any]], conv: Optional[float]) -> str:
    if not c["open"]:
        return "Market closed — replay, review and learning only."
    rem = c.get("minutes_remaining")
    tail = f" · {rem} min left" if rem is not None else ""
    liq = (meas.get("liquidity") or {}).get("level", "—")
    inst = (meas.get("institutional") or {}).get("level", "—")
    conv_txt = f" · conviction {conv:.0f}/100" if conv is not None else ""
    return (f"{c['label']}{tail} — {beh['label']}. "
            f"Liquidity {liq}, institutional activity {inst}{conv_txt}.")


def log_row(read_out: Optional[Dict[str, Any]],
            trading_day: Optional[str] = None) -> Dict[str, Any]:
    """The append-only row — every output logged for the Learning Engine, so
    "which sessions actually produce wins" becomes answerable."""
    r = dict(read_out or {})
    meas = r.get("measures") or {}
    return {
        "trading_day": trading_day,
        "session": r.get("session"), "behaviour": r.get("behaviour"),
        "conviction": r.get("conviction"),
        "minutes_remaining": r.get("minutes_remaining"),
        "measures": {k: v.get("value") for k, v in meas.items()},
        "measures_available": r.get("measures_available"),
        "modifiers": (r.get("modifiers") or {}).get("applies_to") or {},
        "modifiers_applied": bool((r.get("modifiers") or {}).get("applied")),
    }


# ── the Learning Engine's payoff ────────────────────────────────────────
def performance_by_session(session_log: Optional[List[Dict[str, Any]]],
                           results: Optional[List[Dict[str, Any]]],
                           min_trades: int = 10) -> List[Dict[str, Any]]:
    """Which sessions actually produce results.

    A trade is attributed to the session in force **when it was taken** — the
    last logged row on that day at or before the trade. Attributing by the
    day's final session would credit every morning trade to the close.

    Sessions below `min_trades` are marked `thin` rather than dropped: a window
    you have only traded four times is unproven, which is different from bad.
    """
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for row in (session_log or []):
        d = str(row.get("trading_day") or "")
        if d:
            by_day.setdefault(d, []).append(row)
    for rows in by_day.values():
        rows.sort(key=lambda r: str(r.get("ts") or ""))

    buckets: Dict[str, Dict[str, Any]] = {}
    for res in (results or []):
        if res.get("outcome") not in ("win", "loss"):
            continue
        day = str(res.get("trading_day") or "")
        when = str(res.get("exit_at") or res.get("created_at") or "")
        active = None
        for row in by_day.get(day) or []:
            if not when or str(row.get("ts") or "") <= when:
                active = row.get("session")
            else:
                break
        if not active:
            continue
        b = buckets.setdefault(active, {"session": active, "trades": 0,
                                        "wins": 0, "pnl": 0.0})
        b["trades"] += 1
        b["wins"] += 1 if res["outcome"] == "win" else 0
        try:
            b["pnl"] += float(res.get("pnl_points") or 0.0)
        except (TypeError, ValueError):
            pass

    label = {k: lbl for k, _, _, lbl in WINDOWS}
    label[CLOSED[0]] = CLOSED[1]
    order = {k: i for i, (k, _, _, _) in enumerate(WINDOWS)}

    out = []
    for k, b in buckets.items():
        n = max(1, b["trades"])
        out.append({
            "session": k, "label": label.get(k, k),
            "trades": b["trades"], "wins": b["wins"],
            "losses": b["trades"] - b["wins"],
            "win_rate": round(100.0 * b["wins"] / n, 1),
            "total_pnl": round(b["pnl"], 1),
            "expectancy": round(b["pnl"] / n, 2),
            "thin": b["trades"] < min_trades,
        })
    # chronological, not by win rate — reading the day in order is what makes
    # "we lose money at midday" visible
    out.sort(key=lambda r: order.get(r["session"], 99))
    return out
