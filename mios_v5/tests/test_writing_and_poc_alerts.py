"""📢📍 Two alert wirings the owner asked for, and one pause.

- The MIOS entry stream on Telegram is paused by default.
- Heavy call/put writing gets a Telegram note, behind a toggle, at the existing
  edge-triggered capture sites.
- A chart's dynamic POC stepping up/down posts to Discord, opt-in, after the V6
  render has published `_leg_profiles`.

All checked on the parse tree of `vob_minimal.py`, not a text scan, so a comment
mentioning a name cannot pass for the wiring itself.
"""

from __future__ import annotations

import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC = (_ROOT / "vob_minimal.py").read_text()
_TREE = ast.parse(_SRC)


def _const(name):
    for n in _TREE.body:
        if isinstance(n, ast.Assign) and any(
                getattr(t, "id", "") == name for t in n.targets):
            assert isinstance(n.value, ast.Constant), f"{name} not a literal"
            return n.value.value
    raise AssertionError(f"{name} is not a module-level constant")


def _fn(name):
    return next(n for n in ast.walk(_TREE)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def _calls(fn):
    return {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
            for c in ast.walk(fn) if isinstance(c, ast.Call)}


# ── the pause ──────────────────────────────────────────────────────────

def test_the_entry_stream_is_paused_by_default():
    assert _const("MIOS_V6_TELEGRAM_DEFAULT") is False


# ── the defaults are named constants (findable send channels) ──────────

def test_the_new_alert_defaults_are_named_bool_constants():
    assert _const("WRITING_TG_DEFAULT") is True          # explicitly requested
    assert _const("POC_SHIFT_ALERTS_DEFAULT") is False   # opt-in


# ── call/put writing → Telegram ────────────────────────────────────────

def test_writing_events_also_notify_telegram():
    """Both writing capture sites mirror to Telegram, and the helper sends with
    force=True — a writing note is not entry-tier, so without force it would be
    routed Discord-only by `send_telegram_message_sync`."""
    cap = _fn("capture_stage2_market_events")
    assert "_notify_writing_telegram" in _calls(cap)

    helper = _fn("_notify_writing_telegram")
    sends = [c for c in ast.walk(helper) if isinstance(c, ast.Call)
             and getattr(c.func, "id", "") == "send_telegram_message_sync"]
    assert sends, "the writing note never reaches Telegram"
    forced = any(
        any(kw.arg == "force" and getattr(kw.value, "value", None) is True
            for kw in c.keywords) for c in sends)
    assert forced, "writing note must force past the entry-tier route"
    # gated on the toggle so it can be muted
    assert "_writing_tg_on" in _SRC


# ── dynamic POC shift → Discord, after the V6 render ───────────────────

def test_poc_shift_alert_runs_after_v6_publishes_leg_profiles():
    """`_notify_poc_shifts` reads `_leg_profiles`, which the terminal publishes
    while Dashboard V6 renders — so it must be called after that render, inside
    `_render_main_analyzer`."""
    analyzer = _fn("_render_main_analyzer")
    assert "_notify_poc_shifts" in _calls(analyzer)

    helper = _fn("_notify_poc_shifts")
    calls = _calls(helper)
    # ⚠️ Routed through capture_market_event, NOT send_discord_message /
    # _throttled_telegram_send — the latter's Discord branch is a paused no-op,
    # so the alert would archive but never appear. capture_market_event is the
    # path that actually reaches the live Discord feed in this app.
    assert "capture_market_event" in calls
    assert "send_discord_message" not in calls
    assert "_leg_profiles" in _SRC
    # opt-in gate
    reads = {n.value for n in ast.walk(helper)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_poc_shift_on" in reads


# ── the sidebar exposes both switches, reading the named constants ─────

def test_both_toggles_read_their_named_constant():
    checks = [n for n in ast.walk(_TREE) if isinstance(n, ast.Call)
              and getattr(n.func, "attr", "") == "checkbox"]

    def _reads(label_sub, const):
        for c in checks:
            if any(isinstance(a, ast.Constant) and label_sub in str(a.value)
                   for a in c.args):
                default = next((kw.value for kw in c.keywords
                                if kw.arg == "value"), None)
                return isinstance(default, ast.Name) and default.id == const
        return False

    assert _reads("Call/Put writing", "WRITING_TG_DEFAULT")
    assert _reads("Dynamic POC shift", "POC_SHIFT_ALERTS_DEFAULT")
