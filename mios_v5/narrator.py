"""MIOS V6.5 — Stage 65 AI Trade Narrator.

A running commentary on a live trade, so the trader can see *how the decision
evolved* rather than only where it started and where it ended.

    09:20   Buyer absorption increasing — holding.
    09:28   Acceptance confirmed — 🟢 Rejection at support (81%).
    09:36   Dealers weakening — 🏦 Dealers now NEUTRAL.
    09:48   Flow shift detected (74%) — CVD swing.
    10:05   Decision Engine moved to EXIT.

## Only changes get a line

Every beat is emitted on a **transition**, never on a state. A narrator that
prints the current reading each cycle produces four hundred lines a session,
and a trader learns within a day to stop reading it — which destroys the one
thing it was built for. The watched values are hashed into a signature; a beat
is written only when a watched value differs from the last one recorded.

## The narrator does not prescribe

This is the boundary that took care. The natural thing to write is
"Dealer weakening → move your trail tighter", and it reads well. But that is
the narrator inventing an instruction, and the moment it does that it is a
second decision engine giving advice that nothing validated.

So: **observations are the narrator's; actions are quoted from the Decision
Engine.** When Stage 52 moves to TRAIL, the beat says so and marks itself as an
action. When it doesn't, the narrator reports what it sees and stops there. If
those two ever disagree, the trader sees the disagreement instead of a
confident sentence hiding it.

Pure module: prior beats + a final read in, updated beats out. The caller owns
persistence and supplies the clock.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .final_read import section

#: how many beats to retain — one session's worth of transitions
KEEP = 60

TONE = {"bull": "#00ff88", "bear": "#ff4444", "warn": "#ffcc33",
        "action": "#a78bfa", "info": "#cfd9e6"}

#: decision states worth announcing as actions when Stage 52 enters them
_ACTION_STATES = ("ENTER", "SCALE_IN", "SCALE_OUT", "TRAIL", "EXIT", "ABORT",
                  "COMPLETE", "HOLD")

#: MFE/MAE milestones, in points, that earn a beat
_EXCURSION_STEPS = (10, 20, 30, 50, 75, 100)


def _s(v) -> str:
    return str(v or "").upper()


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def signature(final_read: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The watched values. A beat fires when one of these changes."""
    fr = dict(final_read or {})
    dec = fr.get("decision_v2") or {}
    return {
        "absorption": (fr.get("absorption") or {}).get("behaviour"),
        "acceptance": (fr.get("reaction") or {}).get("state"),
        "dealer": section(fr, "dealer").get("bias"),
        "stability": fr.get("stability"),
        "flow_freeze": bool((fr.get("flow_shift") or {}).get("freeze_entries")),
        "transition": (fr.get("transition") or {}).get("state"),
        "market_state": (fr.get("market_state") or {}).get("state"),
        "validity": (fr.get("validity") or {}).get("verdict"),
        "bias": fr.get("preferred_bias"),
        "decision": dec.get("state"),
    }


def _beat(ts, text, tone="info", action=False, engine=None, key=None):
    return {"ts": ts, "time": _clock(ts), "text": text, "tone": tone,
            "colour": TONE.get(tone, TONE["info"]), "action": bool(action),
            "engine": engine, "key": key}


def _clock(ts) -> str:
    """HH:MM in IST.

    `datetime.fromtimestamp(x)` with no tzinfo returns the *container's* local
    time, and this app runs on UTC servers — every beat was rendered 5½ hours
    early.
    """
    from .clock import hhmm
    return hhmm(ts)


def observe(prior: Optional[List[Dict[str, Any]]],
            final_read: Optional[Dict[str, Any]],
            ts: Any = None,
            excursion: Optional[Dict[str, Any]] = None,
            last_signature: Optional[Dict[str, Any]] = None,
            keep: int = KEEP) -> Dict[str, Any]:
    """Advance the narration by one cycle.

    Returns `{beats, signature, new}` — `new` being only the beats added this
    cycle, so a caller can push those to Telegram without re-sending history.
    """
    fr = dict(final_read or {})
    beats = list(prior or [])
    sig = signature(fr)
    prev = dict(last_signature or {})
    new: List[Dict[str, Any]] = []

    def add(*a, **kw):
        b = _beat(ts, *a, **kw)
        new.append(b)
        beats.append(b)

    def changed(key):
        return key in prev and prev.get(key) != sig.get(key)

    first = not prev

    # ── the tape ──
    ab = fr.get("absorption") or {}
    if (changed("absorption") or first) and sig["absorption"] not in (None, "NONE"):
        add(f"{ab.get('label')} — {ab.get('expectation', '')}".strip(" —"),
            tone=str(ab.get("tone") or "info"),
            engine="Stage 43 Absorption", key="absorption")

    rc = fr.get("reaction") or {}
    if changed("acceptance") and sig["acceptance"] not in (None, "IDLE"):
        w = rc.get("winner")
        add(f"Reaction: {rc.get('label')} ({rc.get('confidence', 0)}%)"
            + (f" — {w} won" if w else ""),
            tone=("bull" if w == "Buyers" else "bear" if w == "Sellers"
                  else "info"),
            engine="Stage 42 Acceptance", key="acceptance")

    d = section(fr, "dealer")
    if changed("dealer") and sig["dealer"]:
        add(f"Dealers → {d.get('label') or sig['dealer']}", tone="warn",
            engine="Stage 11 Dealer", key="dealer")

    fs = fr.get("flow_shift") or {}
    if changed("flow_freeze") and sig["flow_freeze"]:
        add(f"Flow shift detected ({fs.get('score', 0)}%) — "
            f"{fs.get('reason', 'tape repricing')}", tone="warn",
            engine="Stage 44 Flow Shift", key="flow_shift")
    elif changed("stability") and sig["stability"]:
        add(f"Tape {str(sig['stability']).lower()}", tone="info",
            engine="Stage 44 Flow Shift", key="stability")

    tr = fr.get("transition") or {}
    if changed("transition") and _s(sig["transition"]) in (
            "WEAKENING", "REVERSING", "TRANSITION"):
        add(f"Bias {str(sig['transition']).lower()}"
            + (f" — led by {tr['leader']}" if tr.get("leader") else "")
            + (f", reversal risk {tr['reversal_probability']}%"
               if tr.get("reversal_probability") else ""),
            tone="warn", engine="Stage 47 Bias Transition", key="transition")

    ms = fr.get("market_state") or {}
    if changed("market_state") and sig["market_state"]:
        add(f"Market state → {ms.get('label') or sig['market_state']}",
            tone="info", engine="Stage 48 Market State", key="market_state")

    v = fr.get("validity") or {}
    if changed("validity") and sig["validity"]:
        add(f"Signal validity → {sig['validity']} ({v.get('pct', 0)}%)",
            tone=("bull" if sig["validity"] == "VALID" else "warn"),
            engine="Stage 51 Validity", key="validity")

    if changed("bias") and sig["bias"]:
        add(f"Arbitrated bias → {sig['bias']}", tone="info",
            engine="Stage 27 Conflict", key="bias")

    # ── the excursion: how the trade is actually doing ──
    for b in _excursion_beats(excursion, prev.get("_mfe"), prev.get("_mae"), ts):
        new.append(b)
        beats.append(b)
    sig["_mfe"] = (excursion or {}).get("mfe", prev.get("_mfe"))
    sig["_mae"] = (excursion or {}).get("mae", prev.get("_mae"))

    # ── the ACTION line, quoted from the Decision Engine, never invented ──
    dec = fr.get("decision_v2") or {}
    if changed("decision") and _s(sig["decision"]) in _ACTION_STATES:
        why = "; ".join((dec.get("reasons") or [])[:2])
        add(f"Decision Engine moved to {dec.get('label') or sig['decision']}"
            + (f" — {why}" if why else ""),
            tone="action", action=True,
            engine="Stage 52 Decision Engine", key="decision")

    return {"beats": beats[-keep:], "signature": sig, "new": new}


def _excursion_beats(excursion, prev_mfe, prev_mae, ts
                     ) -> List[Dict[str, Any]]:
    """A beat when the trade crosses a round-number milestone in either
    direction — not on every tick of drift."""
    ex = excursion or {}
    out = []
    mfe, mae = _f(ex.get("mfe")), _f(ex.get("mae"))
    pm, pa = _f(prev_mfe) or 0.0, _f(prev_mae) or 0.0
    for step in _EXCURSION_STEPS:
        if mfe is not None and pm < step <= mfe:
            out.append(_beat(ts, f"Trade +{step} pts in favour", tone="bull",
                             key=f"mfe{step}"))
        if mae is not None and -pa < step <= -mae:
            out.append(_beat(ts, f"Trade -{step} pts against", tone="bear",
                             key=f"mae{step}"))
    return out


def recap(beats: Optional[List[Dict[str, Any]]], limit: int = 6) -> List[str]:
    """The last few lines, newest last — for a Telegram update or a card."""
    return [f"{b.get('time', '')}  {b.get('text', '')}"
            for b in (beats or [])[-limit:]]


def summarise(beats: Optional[List[Dict[str, Any]]]) -> str:
    """One sentence describing how the trade evolved — used by Stage 66."""
    bs = list(beats or [])
    if not bs:
        return "No narration recorded."
    actions = [b for b in bs if b.get("action")]
    warns = [b for b in bs if b.get("tone") == "warn"]
    parts = [f"{len(bs)} recorded developments"]
    if actions:
        parts.append(f"{len(actions)} decision changes "
                     f"(last: {actions[-1]['text']})")
    if warns:
        parts.append(f"{len(warns)} warnings, first at {warns[0].get('time')}")
    return "; ".join(parts) + "."
