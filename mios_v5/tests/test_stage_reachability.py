"""🔗 Every stage module has to be reachable from production code.

## The failure this catches

A stage can stop reporting in a way no status field shows: **nothing calls it.**
That is how a whole Adaptive Greeks layer shipped defined-and-never-called and
rendered nothing on four surfaces. An engine class at least appears in
`ALL_ENGINES`; a stage implemented as a plain module (55–67, 70–74) has no
registry, so it goes dead silently.

## ⚠️ Two scanner bugs this test exists to avoid repeating

An earlier pass of this audit reported `calibration` and `dispatch_validation` as
dead. Both were false positives:

* **`from . import calibration`** has `node.module is None`, so keying only on
  `node.module` misses it entirely. `learning_report.py:66` really does call
  `calibration.by_engine`.
* `setdefault` both reads AND writes, so counting it as a read alone made 25 live
  keys look write-only.

Any future check here must handle `from . import X`. The rule below is asserted
against a hand-verified list rather than a clever heuristic, for that reason.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Stage modules that are NOT engine classes — stages 55–67 and 70–74 plus the
#: 71.x family. These have no registry, so nothing structurally guarantees they
#: are called.
STAGE_MODULES = (
    "entry_engine", "dispatcher", "profile_shape", "liquidity_context",
    "futures_oi_store", "checklist", "narrator", "daily_summary",
    "contribution", "calibration", "false_signal", "learning_report",
    "explain_decision", "risk_explain", "opportunity", "premium_energy",
    "strike_validation", "engine_accuracy",
)

#: Modules reachable ONLY from tests, with the reason that is correct for them.
TEST_ONLY = {
    "dispatch_validation": "a fault-injection validation harness — it proves the "
                           "dispatch gates under simulated load and must not run "
                           "in production. `test_dispatcher.py` exercises it.",
}

#: Modules nothing imports at all, with the reason each is knowingly dead.
KNOWN_DEAD = {
    "dispatch_registry": "db/dispatch_registry.py — `SupabaseDispatchRegistry` is "
                         "never constructed. Recorded in docs/AUDIT_EGRESS_4.md "
                         "§5: it was the prime suspect for the 1 GB egress day "
                         "and was DISPROVED precisely because nothing builds it.",
}


def _importers():
    """`{module_stem: {files importing it}}`.

    ⚠️ Handles all three forms. `from . import X` is the one an earlier scan
    missed, and missing it produced two false "dead module" reports:

        import mios_v5.calibration          → ast.Import
        from mios_v5.calibration import f   → ast.ImportFrom, module set
        from . import calibration           → ast.ImportFrom, module is None
    """
    out = {}
    for f in _ROOT.rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        try:
            tree = ast.parse(f.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    names.append(node.module.split(".")[-1])
                names += [a.name.split(".")[-1] for a in node.names]
            elif isinstance(node, ast.Import):
                names += [a.name.split(".")[-1] for a in node.names]
            for n in names:
                out.setdefault(n, set()).add(f)
    return out


@pytest.fixture(scope="module")
def importers():
    return _importers()


def _split(users, stem):
    users = {u for u in users if u.stem != stem}
    prod = {u for u in users if "tests" not in u.parts}
    return prod, users - prod


@pytest.mark.parametrize("stem", STAGE_MODULES)
def test_every_stage_module_is_reached_from_production(stem, importers):
    """A stage module nothing imports reports nothing, and no status field says
    so — the one failure mode that looks exactly like a quiet market."""
    prod, tests = _split(importers.get(stem, set()), stem)
    assert prod, (
        f"{stem} is imported by no production module"
        + (f" (only tests: {sorted(t.name for t in tests)})" if tests else "")
        + " — it computes nothing and nothing shows it")


def test_the_from_dot_import_form_is_actually_detected(importers):
    """⚠️ Guards the scanner, not the app. `calibration` is imported ONLY as
    `from . import calibration` (learning_report.py), so if this fixture ever
    stops seeing that form, every test above starts passing vacuously — or
    failing falsely, which is what happened the first time."""
    users = {u.name for u in importers.get("calibration", set())}
    assert "learning_report.py" in users, (
        "the `from . import X` form is no longer being detected")

    src = (_ROOT / "mios_v5" / "learning_report.py").read_text()
    assert "from . import calibration" in src or "calibration." in src


def test_test_only_modules_are_the_expected_ones(importers):
    """A validation harness belongs in tests. Anything NEW landing here is a
    stage that quietly stopped being wired."""
    for stem, why in TEST_ONLY.items():
        prod, tests = _split(importers.get(stem, set()), stem)
        assert not prod, f"{stem} is now used in production — remove it here"
        assert tests, f"{stem} is not even reached by a test: {why}"


def test_known_dead_modules_are_still_dead_and_still_listed(importers):
    """Two-way, so the list can neither grow silently nor go stale."""
    for stem, why in KNOWN_DEAD.items():
        prod, tests = _split(importers.get(stem, set()), stem)
        assert not prod and not tests, (
            f"{stem} is imported again — remove it from KNOWN_DEAD. Reason it "
            f"was listed: {why}")


def test_the_dead_list_has_not_swallowed_a_live_stage():
    """`KNOWN_DEAD` and `STAGE_MODULES` must not overlap — a stage cannot be both
    required and excused."""
    assert not (set(KNOWN_DEAD) & set(STAGE_MODULES))
    assert not (set(TEST_ONLY) & set(STAGE_MODULES))


# ══════════════════════════════════════════════════════════════════════
#  the engine classes in the same range
# ══════════════════════════════════════════════════════════════════════

def test_every_engine_class_is_registered():
    """The engine half of the same question. A class with a `name` that never
    reaches `ALL_ENGINES` never runs, and nothing reports its absence."""
    from mios_v5.engines import ALL_ENGINES

    registered = {c.name for c in ALL_ENGINES}
    defined = set()
    for f in sorted((_ROOT / "mios_v5" / "engines").glob("stage*.py")):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.ClassDef):
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign):
                        for t in stmt.targets:
                            if (isinstance(t, ast.Name) and t.id == "name"
                                    and isinstance(stmt.value, ast.Constant)):
                                defined.add(stmt.value.value)
    assert defined - registered == set(), (
        f"defined but never registered: {sorted(defined - registered)}")
    assert registered - defined == set(), (
        f"registered but not found: {sorted(registered - defined)}")


def test_the_stages_above_50_all_have_a_home():
    """Stages 50–74 split across two mechanisms, and it is not obvious which
    owns which. Pinned so a new stage cannot be added with neither."""
    from mios_v5.engines import ALL_ENGINES

    engine_stages = {c.stage for c in ALL_ENGINES if c.stage >= 50}
    assert engine_stages == {50, 51, 52, 53, 54, 68, 69}, engine_stages
    # everything else in the range is a plain module, covered above
    assert len(STAGE_MODULES) >= 18
