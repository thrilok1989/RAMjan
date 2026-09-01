"""MIOS — the Stage 52 cockpit.

**A view over an existing state machine. No new logic.**

`decision_v2.STATES` already runs the full trade life:

    WAIT → ENTRY READY → FLOOR/CEILING CONFIRMED → ENTER → HOLD
         → SCALE IN → TRAIL → SCALE OUT → EXIT → COMPLETE
    ABORT overrides all of them, at any point.

Every one of those states is produced on every cycle and shown as a single
badge. A badge tells a trader where they are; it does not tell them **how far
along** they are, what has already been satisfied, or what is left. A pilot's
checklist does, which is the whole reason this panel exists.

## What it may and may not do

It reads `decision_v2` and renders it. It never decides which state applies,
never re-derives a condition, and never writes anything back. The one piece of
judgement here is *presentation*: which steps count as "behind you" — and that
is a table (`_PROGRESSION`), not a computation.

## ABORT is not a step

ABORT can arrive at any point and is checked before everything else, so it has
no position in the sequence. Rendering it as "step 11 of 12" would suggest a
trade nearly complete when the correct read is *stop now*. It replaces the
progression instead of advancing it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .theme import (ALERT, BEAR, BRIGHT, BULL, CARD_BG, CARD_BORDER, DANGER,
                    FAINT, INFO, MICRO, MUTED, VIOLET, WARN)

_CARD = (f"background:{CARD_BG};border:1px solid {CARD_BORDER};"
         f"border-radius:10px;padding:9px 12px;margin-bottom:8px")

#: the two phases a trader actually thinks in, and the states inside each.
#: FLOOR/CEILING_CONFIRMED collapse to one step: they are the same rung of the
#: ladder reached from opposite sides, and showing both would always leave one
#: permanently unreachable.
_PROGRESSION = (
    ("Getting in", (
        ("WAIT", "Waiting — no setup"),
        ("ENTRY_READY", "Setup identified"),
        (("FLOOR_CONFIRMED", "CEILING_CONFIRMED"), "Level confirmed"),
        ("ENTER", "Entry taken"),
    )),
    ("Managing it", (
        ("HOLD", "Holding"),
        ("SCALE_IN", "Scaled in", True),
        ("TRAIL", "Trail active"),
        ("SCALE_OUT", "Partial exit", True),
        ("EXIT", "Exited"),
        ("COMPLETE", "Complete"),
    )),
)

#: steps a trade can legitimately skip. Stage 52 publishes only the CURRENT
#: state, so once price is past one of these there is no way to know whether
#: it happened — and a tick would assert a scale-in nobody took. They render
#: as "not on the path" instead, which is the honest reading of an unknown.
_OPTIONAL = {"SCALE_IN", "SCALE_OUT"}

#: flattened once, so "is this step behind us" is an index comparison rather
#: than a search
_ORDER: List[Any] = [st[0] for _, steps in _PROGRESSION for st in steps]

_DONE, _NOW, _TODO, _SKIP = "✓", "◆", "·", "–"
_TONE = {_DONE: BULL, _NOW: WARN, _TODO: FAINT, _SKIP: MICRO}


def _states(entry) -> tuple:
    return entry if isinstance(entry, tuple) else (entry,)


def _position(state: str) -> Optional[int]:
    """Index of `state` in the progression, or None when it is not a step."""
    for i, entry in enumerate(_ORDER):
        if state in _states(entry):
            return i
    return None


def steps(decision: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The checklist: every step marked done, current, or still ahead.

    An unknown or absent state yields every step as still-ahead rather than
    guessing a position — the same three-state discipline the rest of Stage 71
    uses. A cockpit that invents progress is worse than one that admits it does
    not know where it is.
    """
    d = decision or {}
    state = str(d.get("state") or "").upper()
    here = _position(state)
    out: List[Dict[str, Any]] = []
    i = 0
    for phase, phase_steps in _PROGRESSION:
        for step in phase_steps:
            entry, label = step[0], step[1]
            optional = _states(entry)[0] in _OPTIONAL
            if here is None:
                mark = _TODO
            elif i < here:
                # passed — but an optional step that is behind us may simply
                # never have happened, and Stage 52 cannot tell us which
                mark = _SKIP if optional else _DONE
            elif i == here:
                mark = _NOW
            else:
                mark = _TODO
            out.append({"phase": phase, "label": label, "mark": mark,
                        "colour": _TONE[mark], "current": mark == _NOW,
                        "optional": optional, "state": _states(entry)[0]})
            i += 1
    return out


def cockpit(decision: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The whole panel's view model. Never raises, never decides."""
    d = decision or {}
    state = str(d.get("state") or "").upper()
    aborted = state == "ABORT"
    here = _position(state)
    rows = steps(d)
    done = sum(1 for r in rows if r["mark"] in (_DONE, _SKIP))
    return {
        "state": state or None,
        "label": d.get("label") or ("—" if not state else state),
        "side": d.get("side"),
        "action": d.get("action"),
        "confidence": d.get("confidence"),
        "quality": d.get("quality"),
        "in_trade": bool(d.get("in_trade")),
        "actionable": bool(d.get("actionable")),
        "aborted": aborted,
        "known": here is not None or aborted,
        "steps": rows,
        "done": done, "total": len(rows),
        "reasons": list(d.get("reasons") or []),
        "warnings": list(d.get("warnings") or []),
        "entry": d.get("entry"), "stop": d.get("stop"),
        "trail": (d.get("trail") or {}).get("stop"),
        "advisory_only": True,
    }


def cockpit_html(decision: Optional[Dict[str, Any]]) -> str:
    """Two phases, one row per step. Compact enough to sit under the charts."""
    c = cockpit(decision)
    if c["aborted"]:
        return _abort_html(c)
    if not c["known"]:
        return (f"<div style='{_CARD};border-left:3px solid {CARD_BORDER}'>"
                f"<div style='font-size:9.5px;letter-spacing:.14em;"
                f"color:{MICRO};text-transform:uppercase'>Trade cockpit</div>"
                f"<div style='font-size:12.5px;color:{FAINT};margin-top:3px'>"
                f"Stage 52 has not reported a state this cycle.</div></div>")

    accent = (BULL if c["side"] == "CALL" else
              BEAR if c["side"] == "PUT" else INFO)
    phases: List[str] = []
    for phase, _ in _PROGRESSION:
        items = "".join(
            f"<div style='font-size:12px;display:flex;gap:7px;margin:1px 0;"
            f"color:{r['colour']};"
            f"{'font-weight:800' if r['current'] else ''}'>"
            f"<span style='width:11px'>{r['mark']}</span>"
            f"<span>{r['label']}</span></div>"
            for r in c["steps"] if r["phase"] == phase)
        phases.append(
            f"<div style='flex:1;min-width:140px'>"
            f"<div style='font-size:9px;letter-spacing:.11em;color:{MICRO};"
            f"text-transform:uppercase;margin-bottom:3px'>{phase}</div>"
            f"{items}</div>")

    tail = ""
    if c["action"]:
        tail = (f"<div style='font-size:12.5px;color:{BRIGHT};margin-top:6px;"
                f"font-weight:700'>{c['action']}</div>")
    warn = ""
    if c["warnings"]:
        warn = (f"<div style='font-size:11.5px;color:{WARN};margin-top:3px'>⚠️ "
                + " · ".join(c["warnings"][:2]) + "</div>")

    return (
        f"<div style='{_CARD};border-left:3px solid {accent}'>"
        f"<div style='display:flex;align-items:baseline;gap:9px;"
        f"flex-wrap:wrap;margin-bottom:6px'>"
        f"<span style='font-size:9.5px;letter-spacing:.14em;color:{MICRO};"
        f"text-transform:uppercase'>Trade cockpit</span>"
        f"<span style='font-size:15px;font-weight:900;color:{accent}'>"
        f"{c['label']}</span>"
        + (f"<span style='font-size:12.5px;color:{MUTED}'>{c['side']}</span>"
           if c["side"] else "")
        + f"<span style='margin-left:auto;font-size:11.5px;color:{MICRO}'>"
          f"step {c['done'] + 1} of {c['total']}</span></div>"
          f"<div style='display:flex;gap:16px;flex-wrap:wrap'>"
        + "".join(phases) + f"</div>{tail}{warn}</div>")


def _abort_html(c: Dict[str, Any]) -> str:
    """ABORT replaces the ladder rather than advancing it — it can arrive at
    any point, and "step 11 of 12" would read as a trade nearly done."""
    reasons = " · ".join(c["reasons"][:3]) or "conditions invalidated"
    return (
        f"<div style='{_CARD};border:2px solid {DANGER}'>"
        f"<div style='font-size:9.5px;letter-spacing:.14em;color:{MICRO};"
        f"text-transform:uppercase'>Trade cockpit</div>"
        f"<div style='font-size:19px;font-weight:900;color:{DANGER};"
        f"margin-top:2px'>{c['label']}</div>"
        f"<div style='font-size:12.5px;color:{MUTED};margin-top:3px'>"
        f"{reasons}</div>"
        + (f"<div style='font-size:13px;font-weight:800;color:{ALERT};"
           f"margin-top:4px'>{c['action']}</div>" if c["action"] else "")
        + "</div>")


def render_cockpit(st, final_read: Optional[Dict[str, Any]]) -> None:
    """Render the cockpit from a final read. Advisory; it may never take the
    execution screen down with it."""
    try:
        st.markdown(cockpit_html((final_read or {}).get("decision_v2")),
                    unsafe_allow_html=True)
    except Exception as err:
        st.caption(f"Trade cockpit unavailable: {err}")
