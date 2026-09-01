"""🎯 Alert when spot reaches a key level (war zone / OI wall / S&R) within ±5.

The property that matters is the latch: price can sit inside the band for many
20-second reruns, and the alert must fire once — on arrival — not on every one.
`evaluate` is the pure heart of that and is tested directly; the wiring that
gathers the levels is checked on the parse tree.
"""

from __future__ import annotations

import ast
import pathlib

from mios_v5 import level_touch as LT

_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── the latch ──────────────────────────────────────────────────────────

def test_a_touch_fires_once_then_stays_quiet_while_price_loiters():
    st = None
    alert, st = LT.evaluate(24330, 24326, st)      # 4 pts away → touch
    assert alert is True
    # still inside the band on the next rerun — must NOT re-alert
    alert, st = LT.evaluate(24330, 24327, st)
    assert alert is False
    alert, st = LT.evaluate(24330, 24332, st)      # still within ±5
    assert alert is False


def test_outside_the_band_never_alerts():
    alert, st = LT.evaluate(24330, 24320, None)     # 10 pts away
    assert alert is False


def test_it_re_arms_only_after_price_leaves_and_then_a_new_touch_fires():
    _, st = LT.evaluate(24330, 24326, None)         # touch, disarm
    _, st = LT.evaluate(24330, 24345, st)           # 15 pts away ≥ REARM → re-arm
    alert, st = LT.evaluate(24330, 24331, st)       # comes back → fires again
    assert alert is True


def test_a_wobble_at_the_edge_does_not_re_arm():
    _, st = LT.evaluate(24330, 24325, None)         # touch at exactly 5, disarm
    # drifts to 8 pts (past BAND but short of REARM=10) then back — no re-alert
    _, st = LT.evaluate(24330, 24338, st)
    alert, st = LT.evaluate(24330, 24327, st)
    assert alert is False


def test_a_new_level_re_arms_immediately():
    _, st = LT.evaluate(24330, 24328, None)         # touch level A, disarm
    # the war zone moves to a new price and spot is already on it → must alert
    alert, st = LT.evaluate(24500, 24498, st)
    assert alert is True


def test_a_re_entry_within_the_cooldown_is_suppressed():
    """The latch stops a loiter; the cooldown stops CHOP. Price touches, leaves
    past REARM, and comes back — but within the cooldown, so no second alert."""
    t = 1_000_000.0
    a1, st = LT.evaluate(24330, 24327, None, now=t)          # touch, alert
    assert a1 is True
    _, st = LT.evaluate(24330, 24345, st, now=t + 60)        # leaves → re-arm
    a2, st = LT.evaluate(24330, 24331, st, now=t + 120)      # back in 2 min
    assert a2 is False, "re-entry inside the cooldown must not re-alert"


def test_after_the_cooldown_a_fresh_touch_alerts_again():
    t = 1_000_000.0
    _, st = LT.evaluate(24330, 24327, None, now=t)           # alert
    _, st = LT.evaluate(24330, 24345, st, now=t + 60)        # leaves → re-arm
    a, st = LT.evaluate(24330, 24331, st, now=t + LT.COOLDOWN_S + 1)
    assert a is True, "past the cooldown a genuine re-touch should alert"


def test_a_new_level_starts_its_own_cooldown():
    """A different level is a different alert — the previous level's cooldown
    must not silence it."""
    t = 1_000_000.0
    _, st = LT.evaluate(24330, 24328, None, now=t)           # alert level A
    a, st = LT.evaluate(24500, 24498, st, now=t + 30)        # level B, seconds later
    assert a is True


def test_without_now_only_the_latch_applies():
    """Callers (and older tests) that pass no clock keep the pure-latch
    behaviour — the cooldown simply does not engage."""
    a1, st = LT.evaluate(24330, 24327, None)                 # no now
    _, st = LT.evaluate(24330, 24345, st)                    # re-arm
    a2, _ = LT.evaluate(24330, 24331, st)                    # back → alerts
    assert a1 is True and a2 is True


def test_a_missing_level_or_spot_is_not_a_touch():
    alert, st = LT.evaluate(None, 24330, None)
    assert alert is False and st == {}
    alert, st = LT.evaluate(24330, None, {"level": 24330, "armed": True})
    assert alert is False


# ── wording & dedupe ───────────────────────────────────────────────────

def test_the_message_names_the_level_and_the_distance():
    msg = LT.message("war zone — SUPPORT", 24330, 24327.4, "🛡",
                     ["Expected winner: Sellers", "bounce 30% · breakdown 70%"])
    assert "war zone — SUPPORT" in msg and "24,330" in msg
    assert "24,327" in msg and "-3" in msg
    assert "Sellers" in msg and "breakdown 70%" in msg


def test_the_message_drops_empty_extra_lines():
    msg = LT.message("resistance", 24498, 24500, "🧱", [None, ""])
    assert msg.count("\n") == 1          # headline + spot line only


def test_two_levels_at_the_same_price_collapse_to_one():
    """The war zone and a ranked support at the same number should not send two
    near-identical alerts. First (highest-priority) wins."""
    kept = LT.dedupe([
        ("war zone — SUPPORT", 24330, "wz msg"),
        ("support", 24330.4, "sup msg"),          # rounds to the same point
        ("PE OI wall (support)", 24310, "oi msg"),
    ])
    assert [k[0] for k in kept] == ["war zone — SUPPORT", "PE OI wall (support)"]


# ── purity ─────────────────────────────────────────────────────────────

def test_the_module_reads_no_app_state():
    tree = ast.parse((_ROOT / "mios_v5" / "level_touch.py").read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
        elif isinstance(n, ast.Import):
            imported |= {a.name for a in n.names}
    assert not any("vob_minimal" in m or "streamlit" in m for m in imported)
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "session_state" not in attrs


# ── the wiring in vob_minimal ──────────────────────────────────────────

_SRC = (_ROOT / "vob_minimal.py").read_text()
_TREE = ast.parse(_SRC)


def _fn(name):
    return next(n for n in ast.walk(_TREE)
               if isinstance(n, ast.FunctionDef) and n.name == name)


def _calls(fn):
    return {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
            for c in ast.walk(fn) if isinstance(c, ast.Call)}


def test_the_default_is_a_named_bool_constant_on_by_request():
    const = next(n for n in _TREE.body if isinstance(n, ast.Assign)
                 and any(getattr(t, "id", "") == "LEVEL_TOUCH_DEFAULT"
                         for t in n.targets))
    assert isinstance(const.value, ast.Constant) and const.value.value is True


def test_it_runs_after_v6_and_watches_all_three_level_kinds():
    assert "_notify_level_touches" in _calls(_fn("_render_main_analyzer"))
    helper = _fn("_notify_level_touches")
    consts = {n.value for n in ast.walk(helper)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    # war zone, both OI walls, and the ranked S/R are all sourced
    assert "battle_zone" in consts
    assert "oi_ceiling" in consts and "oi_floor" in consts
    assert "strong_support" in consts and "strong_resistance" in consts
    assert "_level_touch_on" in consts
    assert "send_telegram_message_sync" in _calls(helper)


def test_the_sidebar_toggle_reads_the_named_constant():
    checks = [n for n in ast.walk(_TREE) if isinstance(n, ast.Call)
              and getattr(n.func, "attr", "") == "checkbox"
              and any(isinstance(a, ast.Constant) and "Level-touch" in str(a.value)
                      for a in n.args)]
    assert checks, "no level-touch toggle"
    default = next((kw.value for kw in checks[0].keywords if kw.arg == "value"),
                   None)
    assert isinstance(default, ast.Name) and default.id == "LEVEL_TOUCH_DEFAULT"


def test_the_ranked_sr_touch_is_paused_by_default_but_gated_not_removed():
    """The owner paused the ranked S/R touch — off by default, but still gated on
    a session flag so it can be turned back on. War-zone and OI-wall touches are
    NOT gated by it (they remain under the level-touch toggle)."""
    const = next(n for n in _TREE.body if isinstance(n, ast.Assign)
                 and any(getattr(t, "id", "") == "SR_TOUCH_ALERTS_DEFAULT"
                         for t in n.targets))
    assert isinstance(const.value, ast.Constant) and const.value.value is False
    helper = _fn("_notify_level_touches")
    consts = {n.value for n in ast.walk(helper)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_sr_touch_on" in consts
    # the S/R sources are still there (gated, not deleted)
    assert "strong_support" in consts and "strong_resistance" in consts
