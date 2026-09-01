"""⚠️ The entry-reversal alert is paused.

The owner asked for these Telegram messages to stop: the same level came
through five times in a row, only the "Current" price moving. So the alert is
OFF by default — but kept, gated on its session flag, so ticking the sidebar
box brings it back.

Checked on the parse tree, because the wiring lives in `vob_minimal.py`, which
imports streamlit at module scope and cannot be imported here.
"""

from __future__ import annotations

import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC = (_ROOT / "vob_minimal.py").read_text()
_TREE = ast.parse(_SRC)


def _const(name):
    return next(n for n in _TREE.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == name for t in n.targets))


def _fn(name):
    return next(n for n in ast.walk(_TREE)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def test_the_alert_is_off_by_default():
    """The one property the owner asked for: it does not send unasked."""
    const = _const("ENTRY_REVERSED_ALERT_DEFAULT")
    assert isinstance(const.value, ast.Constant)
    assert const.value.value is False


def test_it_is_paused_not_deleted():
    """Still gated on `_entry_reversed_on`, still able to send — so the
    sidebar box is a real opt-in and not a dead switch."""
    fn = _fn("_notify_entry_reversed")
    consts = {n.value for n in ast.walk(fn)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_entry_reversed_on" in consts
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "post" in called                      # requests.post → Telegram


def test_the_gate_reads_the_named_default_so_the_flip_reaches_it():
    """`session_state.get('_entry_reversed_on', ENTRY_REVERSED_ALERT_DEFAULT)`
    — a hard-coded True here would ignore the constant entirely."""
    fn = _fn("_notify_entry_reversed")
    gets = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
            and getattr(c.func, "attr", "") == "get"
            and any(isinstance(a, ast.Constant) and a.value == "_entry_reversed_on"
                    for a in c.args)]
    assert gets, "the alert no longer reads its opt-in flag"
    fallbacks = [a for g in gets for a in g.args[1:]]
    assert any(isinstance(a, ast.Name)
               and a.id == "ENTRY_REVERSED_ALERT_DEFAULT" for a in fallbacks)


def test_the_sidebar_box_defaults_to_the_same_constant():
    checks = [n for n in ast.walk(_TREE) if isinstance(n, ast.Call)
              and getattr(n.func, "attr", "") == "checkbox"
              and any(isinstance(a, ast.Constant) and "Entry reversal" in str(a.value)
                      for a in n.args)]
    assert checks, "no entry-reversal toggle in the sidebar"
    default = next((kw.value for kw in checks[0].keywords if kw.arg == "value"),
                   None)
    assert isinstance(default, ast.Name)
    assert default.id == "ENTRY_REVERSED_ALERT_DEFAULT"
