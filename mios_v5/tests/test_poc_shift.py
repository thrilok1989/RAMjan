"""📍 Dynamic-POC shift detection and wording.

The module is pure — it compares two readings and formats a message; the app
owns the channels and the per-cycle memory. These tests pin the two things a
shift alert must get right: a warm-up (a level that did not exist last cycle) is
not a move, and jitter under one bin width is not a step.
"""

from __future__ import annotations

import ast
import pathlib

from mios_v5 import poc_shift as PS

_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── detection ──────────────────────────────────────────────────────────

def test_a_step_up_and_down_is_reported_with_direction():
    shifts = PS.detect({"NIFTY": 24050.0}, {"NIFTY": 24000.0})
    assert len(shifts) == 1
    s = shifts[0]
    assert s["chart"] == "NIFTY" and s["direction"] == "UP"
    assert s["prev"] == 24000.0 and s["cur"] == 24050.0
    assert round(s["delta"], 2) == 50.0

    down = PS.detect({"CALL": 118.0}, {"CALL": 124.0})
    assert down[0]["direction"] == "DOWN"
    assert round(down[0]["delta"], 2) == -6.0


def test_a_warm_up_is_not_a_move():
    """A chart with no POC last cycle (or none this cycle) has not *shifted* —
    MISSING → 24,000 is the panel warming up, not a step. Fail-fast §9."""
    assert PS.detect({"NIFTY": 24000.0}, {}) == []
    assert PS.detect({"NIFTY": 24000.0}, {"NIFTY": None}) == []
    assert PS.detect({"NIFTY": None}, {"NIFTY": 24000.0}) == []
    assert PS.detect({"NIFTY": float("nan")}, {"NIFTY": 24000.0}) == []


def test_sub_bin_jitter_is_not_a_step():
    """0.01% wobble a redraw can introduce must not fire; a real bin step does."""
    assert PS.detect({"NIFTY": 24000.5}, {"NIFTY": 24000.0}) == []
    assert PS.detect({"NIFTY": 24020.0}, {"NIFTY": 24000.0}) != []


def test_each_chart_is_judged_independently():
    shifts = PS.detect(
        {"NIFTY": 24050.0, "CALL": 120.0, "PUT": 88.0},
        {"NIFTY": 24000.0, "CALL": 120.0, "PUT": 95.0})
    moved = {s["chart"] for s in shifts}
    assert moved == {"NIFTY", "PUT"}          # CALL unchanged → no alert


# ── wording ────────────────────────────────────────────────────────────

def test_the_index_reads_in_whole_points_the_leg_in_paise():
    s = PS.detect({"NIFTY": 24050.0}, {"NIFTY": 24000.0})[0]
    head = PS.headline(s)
    assert "UP — NIFTY" in head
    assert "24,000" in head and "24,050" in head and "(+50)" in head

    leg = PS.detect({"CALL": 118.25}, {"CALL": 124.75})[0]
    lhead = PS.headline(leg, label="ATM CE 24450")
    assert "ATM CE 24450" in lhead
    assert "124.75" in lhead and "118.25" in lhead and "(-6.50)" in lhead
    assert "down" in PS.detail(leg, label="ATM CE 24450").lower()


# ── purity ─────────────────────────────────────────────────────────────

def test_the_module_computes_no_poc_and_reads_no_app_state():
    """It may not import the app, touch session_state, or recompute a POC —
    §1/§4: one owner (`compute_dynamic_poc`), and inputs arrive as arguments."""
    tree = ast.parse((_ROOT / "mios_v5" / "poc_shift.py").read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
        elif isinstance(n, ast.Import):
            imported |= {a.name for a in n.names}
    assert not any("vob_minimal" in m or "streamlit" in m for m in imported)
    # AST, not text — the docstring names both on purpose to explain the rule.
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "session_state" not in attrs
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(tree) if isinstance(c, ast.Call)}
    assert "compute_dynamic_poc" not in called
