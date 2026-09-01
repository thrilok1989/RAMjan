"""🔧 The debug / audit gate — hide telemetry without switching anything off.

## The one rule, from `docs/AUDIT_FOCUS_MODE.md`

> **Focus Mode may suppress presentation. It may not suppress computation
> required by MIOS state, the decision stages, or Telegram alerts.**

That audit found the reason this is not a formality: **three of the header's own
inputs are produced inside `dashboard_v6`'s render path, and one of them is what
the alert chain reads.** `_strike_validation` publishes `_trading_context` and
`_premium_structures`; `_opportunity` publishes `_premium_energy`;
`_sr_intelligence` publishes `_sr_levels`; `_terminal_chart` publishes
`_leg_profiles`. A "hide the diagnostics" feature implemented as *stop calling
them* would take Telegram down with nothing on screen to say so.

## So this gate never stops a call

Two mechanisms, both presentation-only:

* **`expanded=False`** on a diagnostic expander. ⚠️ A Streamlit expander body
  **executes on every rerun whether or not it is open** — that is normally the
  trap that made everything run twice, and here it is the property that makes
  collapsing safe. The producer still runs; the trader just does not have to
  scroll past it.
* **`note()`** for diagnostic TEXT. A failure caption is collected into a
  bounded list and rendered on the Debug tab instead of interrupting the read.
  The message is not discarded — a swallowed failure that looks like a feature
  was never built is a specific bug this repo has hit three times.

`PROTECTED` names the panels that must never be gated, and
`assert_not_protected` raises rather than warns, so a future edit that tries to
hide a producer fails loudly at the call site.

## The switch

Off by default: the trader's screen is the market, not the engine room. When it
is on, everything the gate hid renders inline again, so debugging does not mean
reading a different app.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

#: Session key for the switch.
FLAG = "_mios_debug_view"

#: Session key for the collected diagnostic notes.
NOTES = "_mios_debug_notes"

#: How many notes to keep. A cycle produces a handful; a hundred is a session's
#: worth without letting a repeating failure grow without bound.
NOTES_CAP = 100

#: ⚠️ Panels that publish keys the header, the alert chain or the charts read.
#: From `docs/AUDIT_FOCUS_MODE.md`'s CRITICAL set. Hiding one of these is not a
#: display change — it is an outage with no message.
#: ⚠️ Kept in step with the audit by
#: `test_the_protected_list_covers_every_critical_panel`, which re-derives the
#: CRITICAL set from `tools/focus_audit.py`. A panel that becomes critical later
#: — as `_charts_screen` did the moment the charts moved to their own tab — fails
#: that test instead of quietly becoming gate-able.
PROTECTED: Tuple[str, ...] = (
    "_strike_validation",     # _trading_context · _premium_structures → Stage 72
    "_opportunity",           # _premium_energy → the header's ⚡ chip
    "_sr_intelligence",       # _sr_levels → header chips AND the simple entry
    "_terminal_chart",        # _leg_profiles → the charts and the heatmaps
    "_charts_screen",         # the only caller of _terminal_chart, so it owns
                              # _leg_profiles by inheritance — hiding it would
                              # leave the Trading tab's heatmaps a cycle behind
    "_run_execution_chain",   # Stages 72 → 73 → 72.9, the alert chain itself
    "_trading_screen",        # entry point
    "render_dashboard_v6",    # entry point
    "_render_main_analyzer",  # entry point
)


def enabled(st) -> bool:
    """Is the trader asking to see the engine room? Off unless they said so."""
    try:
        return bool(st.session_state.get(FLAG, False))
    except Exception:
        return False


def assert_not_protected(name: str) -> None:
    """Refuse to gate a panel that produces something.

    Raises rather than warns. A warning in a 20-second refresh loop scrolls past
    unread, and the failure it would be warning about is silent Telegram.
    """
    if name in PROTECTED:
        raise ValueError(
            f"{name} is CRITICAL — it publishes a key the header, the alert "
            f"chain or the charts read (docs/AUDIT_FOCUS_MODE.md). Presentation "
            f"may be gated; this panel's execution may not.")


def note(st, source: str, message: Any) -> None:
    """Collect a diagnostic instead of printing it into the trader's read.

    ⚠️ Collected, never dropped. "A swallowed failure looks exactly like the
    feature was never built" is the report that produced this repo's loud-chrome
    rule, and a gate that quietly ate error text would reintroduce it one layer
    up.

    Deduplicated on `(source, message)` with a count, because a failure inside a
    20-second loop otherwise produces 1,100 identical lines a day and the Debug
    tab becomes as unreadable as the screen it was fixing.
    """
    text = str(message or "").strip()
    if not text:
        return
    try:
        notes: List[Dict[str, Any]] = st.session_state.setdefault(NOTES, [])
    except Exception:
        return
    for row in notes:
        if row.get("source") == source and row.get("message") == text:
            row["count"] = int(row.get("count", 1)) + 1
            return
    if len(notes) >= NOTES_CAP:
        notes.pop(0)
    notes.append({"source": str(source), "message": text, "count": 1})


def notes(st) -> List[Dict[str, Any]]:
    try:
        return list(st.session_state.get(NOTES) or [])
    except Exception:
        return []


def clear(st) -> None:
    try:
        st.session_state[NOTES] = []
    except Exception:
        pass


def caption(st, source: str, message: Any) -> None:
    """A diagnostic line: inline when debugging, collected when not.

    The replacement for `st.caption(f"... unavailable: {err}")`. In normal use
    the trader sees a count on the Debug tab; with the switch on they see the
    text exactly where it used to be.
    """
    if enabled(st):
        try:
            st.caption(str(message))
        except Exception:
            pass
        return
    note(st, source, message)


@contextmanager
def section(st, title: str, panel: Optional[str] = None) -> Iterator[Any]:
    """A diagnostic block: collapsed when not debugging, open when debugging.

    ⚠️ It is always an expander, never an `if`. The body runs either way — which
    is what keeps a producer inside it alive — and `expanded` is the only thing
    the switch changes.

    `panel` names the function for `assert_not_protected`, so an attempt to gate
    a CRITICAL producer fails at the call site rather than in production.
    """
    if panel:
        assert_not_protected(panel)
    try:
        with st.expander(title, expanded=enabled(st)) as box:
            yield box
    except Exception:
        # No expander available (a stub in a test). Yield the module so the body
        # still runs — the whole point is that it must.
        yield st


def render_switch(st) -> bool:
    """The toggle. Returns the new state.

    Deliberately a checkbox rather than a sidebar-only control: the Debug tab is
    where someone goes when the screen is not saying what they expect, and the
    switch has to be findable from there.
    """
    try:
        val = st.checkbox(
            "Show diagnostics inline", value=enabled(st), key="_dbg_inline",
            help="Off: telemetry stays collapsed and failure text is collected "
                 "here. On: everything renders where it used to. Nothing is "
                 "switched off either way — every engine still runs.")
        st.session_state[FLAG] = bool(val)
        return bool(val)
    except Exception:
        return enabled(st)


def render_panel(st, db: Any = None) -> None:
    """The 🔧 Debug / Audit tab.

    Four things, in the order somebody debugging actually wants them: the
    switch, what failed this session, which panels may not be hidden, and the
    two cost meters.

    ⚠️ Never raises. The same rule every other panel here follows — a display
    panel may not take a tab down — and it applies with particular force to this
    one: the tab you open when the app is misbehaving is the worst possible tab
    to have crash.
    """
    try:
        _render_panel(st, db)
    except Exception as err:            # pragma: no cover - guarded fallback
        try:
            st.caption(f"Debug panel unavailable: {err}")
        except Exception:
            pass


def _render_panel(st, db: Any = None) -> None:
    st.markdown("#### 🔧 Debug / audit")
    st.caption("Everything here is presentation. No engine is switched off by "
               "any control on this tab — see `docs/AUDIT_FOCUS_MODE.md`.")
    render_switch(st)

    # ── what failed ──────────────────────────────────────────────────
    st.markdown("##### ⚠️ Diagnostics collected this session")
    rows = notes(st)
    if not rows:
        st.caption("Nothing reported. Panels that could not draw would be "
                   "listed here with a count.")
    else:
        for row in sorted(rows, key=lambda r: -int(r.get("count", 1))):
            n = int(row.get("count", 1))
            st.caption(f"`{row.get('source')}` — {row.get('message')}"
                       + (f"  ·  ×{n}" if n > 1 else ""))
        if st.button("Clear", key="_dbg_clear"):
            clear(st)

    # ── what may not be hidden ───────────────────────────────────────
    st.markdown("##### 🛡 Protected panels")
    st.caption("These publish keys the header, the alert chain or the charts "
               "read. They may never be gated — `assert_not_protected` raises "
               "if a future edit tries.")
    for name in PROTECTED:
        st.caption(f"`{name}`")

    # ── the cost meters, already built ───────────────────────────────
    st.markdown("##### 📉 Cost")
    try:
        from db.egress_budget import human, report
        data = report()
        if data.get("installed"):
            st.caption(f"Egress today: **{human(data['total_bytes'])}** over "
                       f"{data['calls']:,} calls "
                       f"({data['pct_of_budget']:.1f}% of the "
                       f"{human(data['budget_bytes'])} target)")
        else:
            st.caption("Egress meter not installed this session.")
    except Exception:
        st.caption("Egress meter unavailable.")
    try:
        from db.read_cache import stats as _cache_stats
        s = _cache_stats()
        if s.get("calls"):
            served = max(0, s["calls"] - s["fetches"])
            st.caption(f"Read cache: {s['calls']:,} asked · {s['fetches']:,} "
                       f"reached Supabase · {served:,} served from cache")
    except Exception:
        pass
