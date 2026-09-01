"""📐 Alerts when structure forms on a chart — a new high-volume pivot or a new
Volume Order Block.

The property that matters most is the seed rule: the structure already on the
chart when the app loads must NOT be announced — only what forms afterwards, and
each thing once. `diff` is the pure heart of that, so it is tested directly; the
wiring that feeds it is checked on the parse tree.
"""

from __future__ import annotations

import ast
import pathlib

from mios_v5 import formation_alerts as FA

_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── the seed-or-diff rule ──────────────────────────────────────────────

def test_first_observation_seeds_and_announces_nothing():
    """The pivots/zones already there at load are remembered, never sent."""
    to_alert, updated = FA.diff(["a", "b", "c"], None)
    assert to_alert == []
    assert updated == {"a", "b", "c"}


def test_after_seeding_only_the_new_ones_alert():
    _, known = FA.diff(["a", "b"], None)          # seed
    to_alert, updated = FA.diff(["a", "b", "c", "d"], known)
    assert to_alert == ["c", "d"]                 # order preserved
    assert updated == {"a", "b", "c", "d"}


def test_a_thing_alerts_once_then_never_again():
    _, k = FA.diff(["a"], None)
    new1, k = FA.diff(["a", "b"], k)
    new2, k = FA.diff(["a", "b"], k)              # b already alerted
    assert new1 == ["b"] and new2 == []


def test_a_duplicate_within_one_batch_collapses():
    _, k = FA.diff([], None)
    to_alert, _ = FA.diff(["x", "x"], k)
    assert to_alert == ["x"]


# ── high-volume pivot ──────────────────────────────────────────────────

def test_the_pivot_signature_is_stable_and_identifiable():
    p = {"side": "HIGH", "price": 24512.0, "confirmed_at": 88, "norm": 3.1}
    assert FA.hvp_signature(p) == ("HIGH", 24512, 88)
    # a leg keeps paise so two nearby premium pivots stay distinct
    assert FA.hvp_signature({"side": "LOW", "price": 118.25, "confirmed_at": 5},
                            decimals=2) == ("LOW", 118.25, 5)
    # unidentifiable → None, never a blank alert
    assert FA.hvp_signature({"price": 100}) is None
    assert FA.hvp_signature({"side": "HIGH"}) is None


def test_the_pivot_message_names_the_chart_price_and_volume():
    p = {"side": "LOW", "price": 118.25, "confirmed_at": 5, "norm": 3.4}
    msg = FA.hvp_message("PUT", "ATM PE 24450", p, decimals=2)
    assert "ATM PE 24450" in msg and "118.25" in msg
    assert "low" in msg.lower() and "3.4" in msg


# ── volume order block ─────────────────────────────────────────────────

def test_the_vob_signature_ignores_status_so_a_block_is_not_re_announced():
    """A block going INTACT → BUILDING is the same block, not a new one — so
    status must not be part of its identity, or every status flip would alert."""
    intact = {"role": "support", "lower": 118.0, "upper": 124.0, "status": "INTACT"}
    building = dict(intact, status="BUILDING")
    assert FA.vob_signature(intact) == FA.vob_signature(building)
    assert FA.vob_signature({"role": "support"}) is None   # no band → None


def test_the_vob_message_names_the_role_band_and_status():
    z = {"role": "resistance", "lower": 130.0, "upper": 138.5, "status": "BUILDING"}
    msg = FA.vob_message("CALL", "ATM CE 24450", z)
    assert "ATM CE 24450" in msg and "resistance" in msg
    assert "130" in msg and "138.5" in msg and "BUILDING" in msg


# ── purity ─────────────────────────────────────────────────────────────

def test_the_module_reads_no_app_state_and_recomputes_nothing():
    tree = ast.parse((_ROOT / "mios_v5" / "formation_alerts.py").read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
        elif isinstance(n, ast.Import):
            imported |= {a.name for a in n.names}
    assert not any("vob_minimal" in m or "streamlit" in m for m in imported)
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "session_state" not in attrs
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(tree) if isinstance(c, ast.Call)}
    assert not ({"high_volume_pivots", "analyze_vob_volume"} & called)


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
                 and any(getattr(t, "id", "") == "FORMATION_ALERTS_DEFAULT"
                         for t in n.targets))
    assert isinstance(const.value, ast.Constant) and const.value.value is True


def test_it_runs_after_v6_and_sends_to_telegram_seeding_first():
    assert "_notify_chart_formations" in _calls(_fn("_render_main_analyzer"))
    helper = _fn("_notify_chart_formations")
    calls = _calls(helper)
    assert "send_telegram_message_sync" in calls      # → Telegram, as asked
    assert "diff" in calls                             # seed-or-diff rule used
    reads = {n.value for n in ast.walk(helper)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_formation_alerts_on" in reads and "_formation_seen" in reads


def test_the_sidebar_toggle_reads_the_named_constant():
    checks = [n for n in ast.walk(_TREE) if isinstance(n, ast.Call)
              and getattr(n.func, "attr", "") == "checkbox"
              and any(isinstance(a, ast.Constant) and "HVP / VOB" in str(a.value)
                      for a in n.args)]
    assert checks, "no formation-alerts toggle"
    default = next((kw.value for kw in checks[0].keywords if kw.arg == "value"),
                   None)
    assert isinstance(default, ast.Name) and default.id == "FORMATION_ALERTS_DEFAULT"


def test_vob_formation_is_paused_by_default_but_gated_not_removed():
    """The owner paused the VOB formation alert — off by default, gated on a
    session flag so it can be re-enabled. HVP formation is NOT gated by it."""
    const = next(n for n in _TREE.body if isinstance(n, ast.Assign)
                 and any(getattr(t, "id", "") == "VOB_FORMATION_ALERTS_DEFAULT"
                         for t in n.targets))
    assert isinstance(const.value, ast.Constant) and const.value.value is False
    helper = _fn("_notify_chart_formations")
    consts = {n.value for n in ast.walk(helper)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_vob_formation_on" in consts
    # both emits still present in source (hvp always, vob gated)
    seg = ast.get_source_segment(_SRC, helper) or ""
    assert "'hvp'" in seg and "'vob'" in seg
