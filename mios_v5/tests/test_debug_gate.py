"""🔧 The debug / audit gate — hiding telemetry without switching anything off.

The property under test is one sentence from `docs/AUDIT_FOCUS_MODE.md`:

    Focus Mode may suppress presentation. It may not suppress computation
    required by MIOS state, the decision stages, or Telegram alerts.

Everything here exists to make that checkable rather than remembered, because
the failure it prevents is specific and this repo has already had it: three of
the header's own inputs are produced *inside* `dashboard_v6`'s render path, and
one of them is what the alert chain reads. A "hide the diagnostics" feature
implemented as *stop calling them* takes Telegram down with nothing on screen to
say so.
"""

import ast
import pathlib

import pytest

from mios_v5.ui import debug_gate as G

ROOT = pathlib.Path(__file__).resolve().parents[2]


class FakeSt:
    """The smallest Streamlit that answers what the gate asks of it."""

    def __init__(self, flag=None):
        self.session_state = {} if flag is None else {G.FLAG: flag}
        self.captions = []
        self.expanders = []
        self.markdowns = []

    def caption(self, text):
        self.captions.append(str(text))

    def markdown(self, text, **kw):
        self.markdowns.append(str(text))

    def checkbox(self, label, value=False, key=None, help=None):
        return value

    def button(self, *a, **k):
        return False

    def expander(self, title, expanded=False):
        self.expanders.append((title, expanded))
        return _Box()


class _Box:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ══════════════════════════════════════════════════════════════════════
#  1 · the switch
# ══════════════════════════════════════════════════════════════════════

def test_diagnostics_are_off_unless_asked_for():
    """The trader's screen is the market, not the engine room."""
    assert G.enabled(FakeSt()) is False
    assert G.enabled(FakeSt(False)) is False
    assert G.enabled(FakeSt(True)) is True


def test_enabled_survives_an_object_with_no_session():
    class Bare:
        pass
    assert G.enabled(Bare()) is False


def test_the_switch_writes_the_flag():
    st = FakeSt()
    st.checkbox = lambda *a, **k: True
    assert G.render_switch(st) is True
    assert st.session_state[G.FLAG] is True


# ══════════════════════════════════════════════════════════════════════
#  2 · ⚠️ it never stops a call
# ══════════════════════════════════════════════════════════════════════

def test_a_gated_section_is_an_expander_and_the_body_still_runs():
    """⚠️ THE test. A Streamlit expander body executes on every rerun whether or
    not it is open — normally the trap that made everything run twice, and here
    the property that makes collapsing safe.

    If this ever becomes an `if`, a producer inside a collapsed section stops
    running and the header goes quiet.
    """
    st = FakeSt()
    ran = []
    with G.section(st, "🔬 diagnostics"):
        ran.append(True)
    assert ran == [True], "the body did not run inside a collapsed section"
    assert st.expanders == [("🔬 diagnostics", False)]


def test_the_body_runs_when_diagnostics_are_on_too():
    st = FakeSt(True)
    ran = []
    with G.section(st, "🔬 diagnostics"):
        ran.append(True)
    assert ran == [True]
    assert st.expanders[0][1] is True, "should open when debugging"


def test_the_body_still_runs_when_there_is_no_expander_at_all():
    """A stub Streamlit, or a future version without expanders. The body running
    is the invariant; the frame around it is not."""
    class NoExpander(FakeSt):
        def expander(self, *a, **k):
            raise RuntimeError("no expanders here")

    st = NoExpander()
    ran = []
    with G.section(st, "x"):
        ran.append(True)
    assert ran == [True]


def test_the_gate_never_uses_an_if_to_hide_a_section():
    """Held on the source, because this is the one mistake that turns a display
    feature into an outage. `section` must always enter an expander."""
    src = (ROOT / "mios_v5" / "ui" / "debug_gate.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "section")
    body = ast.dump(fn)
    assert "expander" in body
    # a bare `if enabled(...)` that skips the yield would mean a skipped body
    yields = [n for n in ast.walk(fn) if isinstance(n, ast.Yield)]
    assert len(yields) == 2, "both paths must yield, so the body always runs"


# ══════════════════════════════════════════════════════════════════════
#  3 · protection, and it cannot drift from the audit
# ══════════════════════════════════════════════════════════════════════

def test_gating_a_protected_panel_raises():
    """Raises rather than warns. A warning inside a 20-second refresh loop
    scrolls past unread, and the failure it warns about is silent Telegram."""
    for name in G.PROTECTED:
        with pytest.raises(ValueError):
            G.assert_not_protected(name)


def test_an_ordinary_panel_is_gate_able():
    G.assert_not_protected("_learning")
    G.assert_not_protected("_daily_summary")


def test_a_gated_section_refuses_a_protected_panel():
    st = FakeSt()
    with pytest.raises(ValueError):
        with G.section(st, "🔬 x", panel="_strike_validation"):
            pass


def test_the_protected_list_covers_every_critical_panel():
    """⚠️ What stops `PROTECTED` rotting into a stale comment.

    The CRITICAL set is re-derived from `tools/focus_audit.py`. A panel that
    becomes critical later — as `_charts_screen` did the moment the charts moved
    to their own tab — fails here instead of quietly becoming gate-able.
    """
    import sys
    sys.path.insert(0, str(ROOT))
    from tools import focus_audit as F
    critical = {r["panel"] for r in F.build()["panels"]
                if r["verdict"] == "CRITICAL"}
    missing = critical - set(G.PROTECTED)
    assert not missing, (
        f"these panels are CRITICAL but not in debug_gate.PROTECTED: "
        f"{sorted(missing)}")


# ══════════════════════════════════════════════════════════════════════
#  4 · diagnostics are collected, never dropped
# ══════════════════════════════════════════════════════════════════════

def test_a_failure_is_collected_when_diagnostics_are_off():
    """⚠️ NOT silenced. "A swallowed failure looks exactly like the feature was
    never built" is the report that produced this repo's loud-chrome rule."""
    st = FakeSt()
    G.caption(st, "opportunity", "Trade Opportunity Matrix unavailable: boom")
    assert st.captions == [], "should not interrupt the read"
    got = G.notes(st)
    assert len(got) == 1
    assert got[0]["source"] == "opportunity"
    assert "boom" in got[0]["message"]


def test_a_failure_prints_inline_when_diagnostics_are_on():
    st = FakeSt(True)
    G.caption(st, "opportunity", "unavailable: boom")
    assert any("boom" in c for c in st.captions)


def test_a_repeating_failure_is_counted_not_repeated():
    """A failure inside a 20-second loop otherwise produces 1,100 identical lines
    a day, and the Debug tab becomes as unreadable as the screen it fixed."""
    st = FakeSt()
    for _ in range(50):
        G.caption(st, "chart", "Terminal chart unavailable: boom")
    got = G.notes(st)
    assert len(got) == 1
    assert got[0]["count"] == 50


def test_two_different_failures_are_kept_apart():
    st = FakeSt()
    G.caption(st, "chart", "a")
    G.caption(st, "energy", "b")
    assert len(G.notes(st)) == 2


def test_the_note_list_is_bounded():
    st = FakeSt()
    for i in range(G.NOTES_CAP + 40):
        G.note(st, f"src{i}", f"msg{i}")
    assert len(G.notes(st)) == G.NOTES_CAP


def test_an_empty_message_is_not_a_note():
    st = FakeSt()
    for junk in (None, "", "   "):
        G.note(st, "x", junk)
    assert G.notes(st) == []


def test_notes_can_be_cleared():
    st = FakeSt()
    G.note(st, "x", "y")
    G.clear(st)
    assert G.notes(st) == []


def test_nothing_here_raises_on_junk():
    class Bare:
        pass
    for st in (Bare(), FakeSt()):
        G.note(st, "x", "y")
        G.notes(st)
        G.clear(st)
        G.caption(st, "x", "y")


# ══════════════════════════════════════════════════════════════════════
#  5 · the panel
# ══════════════════════════════════════════════════════════════════════

def test_the_panel_says_nothing_is_switched_off():
    """The claim a reader needs in order to trust the switch."""
    st = FakeSt()
    G.render_panel(st)
    said = " ".join(st.captions + st.markdowns)
    assert "No engine is switched off" in said
    assert "AUDIT_FOCUS_MODE" in said


def test_the_panel_lists_the_protected_panels():
    st = FakeSt()
    G.render_panel(st)
    said = " ".join(st.captions)
    for name in ("_strike_validation", "_terminal_chart", "_opportunity"):
        assert name in said


def test_the_panel_reports_an_empty_note_list_rather_than_drawing_nothing():
    st = FakeSt()
    G.render_panel(st)
    assert any("Nothing reported" in c for c in st.captions)


def test_the_panel_shows_collected_failures_worst_first():
    st = FakeSt()
    G.note(st, "rare", "once")
    for _ in range(9):
        G.caption(st, "common", "nine times")
    G.render_panel(st)
    said = "\n".join(st.captions)
    assert said.index("common") < said.index("rare")
    assert "×9" in said


def test_the_panel_never_raises():
    class Bare:
        session_state = {}

        def markdown(self, *a, **k):
            raise RuntimeError("no")

    G.render_panel(Bare())        # must not propagate


# ══════════════════════════════════════════════════════════════════════
#  6 · the wiring
# ══════════════════════════════════════════════════════════════════════

def _v6_src():
    return (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()


def test_the_debug_tab_is_wired_last():
    from mios_v5.ui.dashboard_v6 import _TABS
    assert _TABS[-1] == "🔧 Debug"
    block = _v6_src()
    block = block[block.index("tabs = st.tabs(_TABS)"):
                  block.index("# ── 0 · CHARTS")]
    assert "_debug_panel(st, db)" in block


def test_the_intelligence_diagnostics_are_collapsed_by_default():
    """The Intelligence tab had four expanders open on arrival, which is what
    made it read as a wall. They follow the switch now."""
    src = _v6_src()
    body = src[src.index("def _intelligence("):src.index("def _sections(")]
    assert "expanded=True" not in body
    assert body.count("expanded=enabled(st)") == 4


def test_the_error_captions_route_through_the_gate():
    src = _v6_src()
    assert "_dbg_caption(st," in src
    for gone in ("Command Center unavailable: {err}\")",
                 "Terminal chart unavailable: {err}\")"):
        assert f"st.caption(f\"{gone}" not in src


def test_the_strike_validation_failure_stays_on_the_screen():
    """⚠️ Deliberately NOT gated. `_strike_validation` publishes what Stage 72
    reads, so a trader who cannot see that the alert chain is down needs it on
    the screen they are looking at — not on a tab they are not."""
    src = _v6_src()
    assert 'st.caption(f"Strike Validation unavailable: {err}")' in src


def test_the_gate_imports_no_engine_and_no_streamlit():
    src = (ROOT / "mios_v5" / "ui" / "debug_gate.py").read_text()
    tree = ast.parse(src)
    top = {a.name.split(".")[0] for n in tree.body
           if isinstance(n, ast.Import) for a in n.names}
    top |= {n.module.split(".")[0] for n in tree.body
            if isinstance(n, ast.ImportFrom) and n.module}
    for banned in ("streamlit", "requests", "supabase", "pandas"):
        assert banned not in top, banned
