"""The hot-path profiler — off by default, and honest about what it proves.

The duplication survey refused to claim a cost it had not profiled:

    Call sites are not executions. This is a place to measure, not a proven
    cost.

These tests hold that line. The profiler must be a no-op in production, and
its headline number must be *repeated work*, not total work — a slow function
called once with a fresh frame is a profiling question, not a caching one.
"""

import ast
import importlib
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "tools" / "hotpath_profiler.py"


def _fresh(monkeypatch, enabled):
    """Re-import the module with MIOS_PROFILE set, since ENABLED is read once
    at import — which is the point: production pays one env lookup."""
    monkeypatch.setenv("MIOS_PROFILE", "1" if enabled else "")
    sys.modules.pop("tools.hotpath_profiler", None)
    sys.path.insert(0, str(ROOT))
    return importlib.import_module("tools.hotpath_profiler")


# ══════════════════════════════════════════════════════════════════════
#  ⛔ off by default
# ══════════════════════════════════════════════════════════════════════

def test_disabled_wrap_returns_the_function_unchanged(monkeypatch):
    """Not a wrapper that checks a flag per call — the *same object*, so a
    disabled profiler cannot cost anything at all."""
    P = _fresh(monkeypatch, False)
    def f(x):
        return x
    assert P.wrap(f) is f
    assert P.install({"compute_vpfr": f}) == []


def test_enabled_is_read_once_at_import(monkeypatch):
    P = _fresh(monkeypatch, False)
    assert P.ENABLED is False
    monkeypatch.setenv("MIOS_PROFILE", "1")
    assert P.ENABLED is False, "the flag must not be re-read per call"


def test_the_app_hook_is_guarded(monkeypatch):
    """A profiler that runs unasked in production is a performance bug wearing
    a performance tool's clothes."""
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "main")
    body = ast.dump(fn)
    assert "hotpath_profiler" in body
    assert "ENABLED" in body, "install() must be behind the flag"


# ══════════════════════════════════════════════════════════════════════
#  what it measures
# ══════════════════════════════════════════════════════════════════════

def test_it_counts_calls_and_time(monkeypatch):
    P = _fresh(monkeypatch, True)
    ns = {"compute_vpfr": lambda df, n: df}
    assert P.install(ns, ["compute_vpfr"]) == ["compute_vpfr"]
    for _ in range(3):
        ns["compute_vpfr"]("frame", 60)
    rep = P.report()
    assert rep["compute_vpfr"]["calls"] == 3
    assert rep["compute_vpfr"]["seconds"] >= 0


def test_repeated_work_is_the_headline_not_total_work(monkeypatch):
    """`wasted_calls` is calls minus distinct inputs — the only number in the
    report that is evidence for caching."""
    P = _fresh(monkeypatch, True)
    ns = {"compute_vpfr": lambda df: df}
    P.install(ns, ["compute_vpfr"])
    for _ in range(5):
        ns["compute_vpfr"]("same-frame")
    rep = P.report()["compute_vpfr"]
    assert rep["calls"] == 5
    assert rep["distinct_inputs"] == 1
    assert rep["wasted_calls"] == 4


def test_distinct_inputs_are_not_counted_as_waste(monkeypatch):
    """Five calls with five different frames is real work. A profiler that
    called that waste would argue for a cache that changes answers."""
    P = _fresh(monkeypatch, True)
    ns = {"compute_vpfr": lambda df: df}
    P.install(ns, ["compute_vpfr"])
    for i in range(5):
        ns["compute_vpfr"](f"frame-{i}")
    rep = P.report()["compute_vpfr"]
    assert rep["distinct_inputs"] == 5
    assert rep["wasted_calls"] == 0


def test_a_raising_function_is_still_counted(monkeypatch):
    """Timing in a `finally`: a function that throws still consumed the time,
    and losing it would understate the cycle."""
    P = _fresh(monkeypatch, True)
    def boom(_):
        raise ValueError("x")
    ns = {"compute_vpfr": boom}
    P.install(ns, ["compute_vpfr"])
    with pytest.raises(ValueError):
        ns["compute_vpfr"]("f")
    assert P.report()["compute_vpfr"]["calls"] == 1


def test_installing_twice_does_not_nest_wrappers(monkeypatch):
    """Streamlit re-executes the module top to bottom on every rerun."""
    P = _fresh(monkeypatch, True)
    ns = {"compute_vpfr": lambda df: df}
    P.install(ns, ["compute_vpfr"])
    first = ns["compute_vpfr"]
    assert P.install(ns, ["compute_vpfr"]) == []
    assert ns["compute_vpfr"] is first


def test_flush_clears_so_each_cycle_is_measured_alone(monkeypatch, tmp_path):
    P = _fresh(monkeypatch, True)
    ns = {"compute_vpfr": lambda df: df}
    P.install(ns, ["compute_vpfr"])
    ns["compute_vpfr"]("a")
    P.flush(tmp_path / "p.json")
    assert P.report() == {}


def test_the_shape_key_does_not_hash_the_data(monkeypatch):
    """Hashing a 400-row frame per call would make the profiler the thing
    being measured."""
    tree = ast.parse(SRC.read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_shape")
    names = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
             for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert not (names & {"hash", "sha1", "sha256", "md5", "to_json"})


def test_the_summary_says_repeated_not_slow(monkeypatch):
    P = _fresh(monkeypatch, True)
    line = P.summary_line({"f": {"calls": 5, "seconds": 0.1,
                                 "wasted_calls": 4, "distinct_inputs": 1,
                                 "ms_per_call": 20}})
    assert "repeated" in line
