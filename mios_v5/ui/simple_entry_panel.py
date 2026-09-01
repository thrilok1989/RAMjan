"""The simple entry system's status, in one line.

`run_simple_entry` evaluates five rules every cycle and stores the result — and
until this existed, **nothing read it**. The record of *why a signal did not
fire* sat in `session_state` where no trader could see it, which is the same
writer-without-a-reader pattern this codebase has been bitten by three times.

One line, refreshed every cycle, answering the only two questions worth asking
between signals:

    ⚡ Simple entry · not firing — CALL premium building (Support Fading)
    ⚡ Simple entry · 🟢 FIRING — BUY CALL at support 24,450

## It names ONE rule, not all five

The blocker is the first failure in rule order, and rule order is deliberate:
spot must be at a level before anything else matters, and the premium's
behaviour is the last confirmation. So the named rule is the one furthest up
the chain — *"price isn't at a level"* is more useful than *"and also the
behaviour is wrong"*, which is true of most of the day.

The remaining count is shown so a near-miss reads differently from a
standing-aside: `4/5` at a level is worth glancing at the chart for; `1/5` is
not.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from .theme import BULL, FAINT, MICRO, MUTED, WARN

#: How many rules must pass before the line is worth drawing the eye to. Below
#: this the system is standing aside, which is the normal state and should look
#: like it.
NEAR_MISS = 4


def _get(signal: Any, name: str, default: Any = None) -> Any:
    """One field, from a frozen verdict or a stored dict.

    Reading only SOME fields through a dict fallback is how a replayed signal
    came out shorter than the live one — it kept the side and lost the level.
    Everything goes through here.
    """
    got = getattr(signal, name, None)
    if got is None and isinstance(signal, dict):
        got = signal.get(name)
    return default if got is None else got


def _rules(signal: Any) -> Tuple[Tuple[str, bool, str], ...]:
    got = getattr(signal, "rules", None)
    if got is None and isinstance(signal, dict):
        got = [(r.get("rule"), r.get("ok"), r.get("detail"))
               for r in (signal.get("rules") or [])]
    return tuple(got or ())


def status_line(signal: Any = None) -> str:
    """Plain text: what the five rules are doing right now."""
    if signal is None:
        return "⚡ Simple entry · waiting for the first cycle"

    rules = _rules(signal)
    fired = _get(signal, "fired", False)

    if fired:
        side = _get(signal, "side", "")
        kind = str(_get(signal, "level_kind", "") or "")
        level = _get(signal, "level")
        where = ""
        try:
            where = f" at {kind} {float(level):,.0f}" if level else ""
        except (TypeError, ValueError):
            where = ""
        return f"⚡ Simple entry · 🟢 FIRING — BUY {side}{where}"

    if not rules:
        why = str(_get(signal, "why", "") or "")
        return f"⚡ Simple entry · not firing — {why or 'no market read yet'}"

    passed = sum(1 for _n, ok, _d in rules if ok)
    blocker = next(((n, d) for n, ok, d in rules if not ok), None)
    if blocker is None:
        return f"⚡ Simple entry · {passed}/{len(rules)} rules"
    name, detail = blocker
    detail = f" ({detail})" if detail else ""
    return (f"⚡ Simple entry · {passed}/{len(rules)} — blocked on "
            f"{name}{detail}")


def status_tone(signal: Any = None) -> str:
    """The colour for that line.

    Amber only for a near miss. A system standing aside is the normal state and
    a coloured line every cycle is a line nobody reads by Wednesday.
    """
    if signal is None:
        return FAINT
    if _get(signal, "fired", False):
        return BULL
    rules = _rules(signal)
    if not rules:
        return MICRO
    passed = sum(1 for _n, ok, _d in rules if ok)
    # ⚠️ A near miss requires price to BE at the level. Four rules passing
    # while spot is 450 points away is not "almost" — the other four are
    # measured against a level price is nowhere near, and colouring that amber
    # would put a warning tone on the market's normal state all day.
    at_level = next((ok for name, ok, _d in rules
                     if name.startswith("spot at")), False)
    return WARN if (at_level and passed >= NEAR_MISS) else MICRO


def render_status(slot, signal: Any = None) -> None:
    """Draw into a Streamlit placeholder, or do nothing.

    A placeholder rather than a direct write because the sidebar is built near
    the top of the script and the rules are evaluated near the bottom — writing
    directly would show the PREVIOUS cycle's answer, which for a status line is
    worse than showing none.
    """
    if slot is None:
        return
    try:
        tone = status_tone(signal)
        slot.markdown(
            f"<div style='font-size:11px;color:{tone};line-height:1.35'>"
            f"{status_line(signal)}</div>", unsafe_allow_html=True)
    except Exception:
        pass
