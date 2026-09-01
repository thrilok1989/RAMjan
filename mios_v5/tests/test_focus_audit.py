"""Stage 1 of Focus Mode — the audit that decides what may be skipped.

The rule it enforces: *Focus Mode may suppress presentation, but may not
suppress computation required by MIOS state, the decision stages, or Telegram
alerts.* These tests are about the audit not quietly losing that rule.
"""

import pathlib

from tools import focus_audit as F

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_alert_chains_context_is_protected():
    """⚠️ `_trading_context` is the single key that would take Telegram down.

    Stage 72 reads it, 73 and 72.9 follow, Telegram is the far end. It is
    written inside `_strike_validation` — a RENDER function — which is the
    whole reason this audit exists.
    """
    assert "_trading_context" in F.PROTECTED
    for key in ("_entry_decision", "_lifecycle_decision", "_dispatch_decision",
                "_mios_transport"):
        assert key in F.PROTECTED, key


def test_the_headers_own_inputs_are_protected():
    for key in ("_cached_option_data", "_mios_state", "_reaction_sr",
                "_premium_energy", "_sr_levels"):
        assert key in F.PROTECTED, key


def test_strike_validation_is_critical():
    """If this ever reports DRAW-ONLY, Focus Mode would skip it and the alert
    chain would go silent with nothing on screen to say so."""
    panels = {r["panel"]: r for r in F.build()["panels"]}
    row = panels.get("_strike_validation")
    assert row, "_strike_validation is no longer reachable from a render entry"
    assert row["verdict"] == "CRITICAL"
    assert "_trading_context" in row["protected"]


def test_the_other_header_producers_are_critical():
    panels = {r["panel"]: r for r in F.build()["panels"]}
    for name, key in (("_opportunity", "_premium_energy"),
                      ("_sr_intelligence", "_sr_levels"),
                      ("_terminal_chart", "_leg_profiles")):
        row = panels.get(name)
        assert row and row["verdict"] == "CRITICAL", name
        assert key in row["protected"], (name, key)


def test_most_panels_really_are_skippable():
    """The feature is only worth building if the skippable set is large. It is
    127 of 153 — but this asserts the shape, not the exact number, so a new
    panel does not fail the suite."""
    tally = F.build()["tally"]
    assert tally["DRAW-ONLY"] > 50
    assert tally["CRITICAL"] < 20, "too many critical panels to skip anything"


def test_a_draw_only_panel_writes_nothing_anyone_reads():
    """The definition, checked rather than trusted."""
    for row in F.build()["panels"]:
        if row["verdict"] == "DRAW-ONLY":
            assert not row["read_by_others"], row["panel"]
            assert not row["protected"], row["panel"]


def test_the_audit_errs_toward_keeping_things_alive():
    """Name-matched call graph merges same-named functions, which can only make
    a panel look like it writes MORE. A false PRODUCER costs a panel that keeps
    running; a false DRAW-ONLY costs the Telegram chain."""
    src = (ROOT / "tools" / "focus_audit.py").read_text()
    assert "by name" in src
    assert "DRAW-ONLY" in src and "CRITICAL" in src


def test_it_reports_without_touching_the_app():
    """Stage 1 changes no behaviour: the tool only parses."""
    import ast
    tree = ast.parse((ROOT / "tools" / "focus_audit.py").read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imported.add((n.module or "").split(".")[0])
    assert not (imported & {"streamlit", "requests", "supabase", "db"})


# ══════════════════════════════════════════════════════════════════════
#  orphan producers — a key nobody publishes
# ══════════════════════════════════════════════════════════════════════

def test_no_producer_in_dashboard_v6_is_defined_and_never_called():
    """⚠️ The bug class, in the exact shape it shipped in.

    `_adaptive_greeks` was defined, wrote a session key, and three surfaces read
    that key. Nothing called it — so the key was never published and all three
    drew nothing, each failing in the one way that looks like "no signal".

    The tests at the time checked EXISTENCE: the panel was called directly, and
    the wiring test asserted the write statement appeared in the file. It did,
    inside a function nobody invoked.
    """
    orphans = F.orphan_producers()
    assert not orphans, (
        "these write a key somebody reads and are never called from "
        "render_dashboard_v6: "
        + "; ".join(f"{fn} → {keys}" for fn, keys in orphans.items()))


def test_the_orphan_check_would_have_caught_the_greeks_bug():
    """A guard nobody can trip is not a guard.

    ⚠️ The probe edits the REAL file and restores it in a `finally`. A first
    attempt wrote a broken COPY into the repo instead, and it reported nothing:
    the call graph is keyed by function NAME across the whole repo, so
    `render_dashboard_v6` in the untouched original still reached
    `_adaptive_greeks` and the copy looked fine. Two files defining one name are
    indistinguishable to a name-based graph — worth knowing before trusting this
    tool on a repo with duplicate function names.
    """
    import pathlib
    import pytest
    root = pathlib.Path(F.__file__).resolve().parents[1]
    target = root / "mios_v5" / "ui" / "dashboard_v6.py"
    original = target.read_text()
    if "_ag = _adaptive_greeks(st, fr)" not in original:
        pytest.skip("the call site moved — update this test with it")
    try:
        target.write_text(original.replace("_ag = _adaptive_greeks(st, fr)",
                                           "_ag = None"))
        got = F.orphan_producers()
        assert "_adaptive_greeks" in got, got
    finally:
        target.write_text(original)
    assert target.read_text() == original, "the probe did not restore the file"


def test_the_scope_is_stated_rather_than_silently_narrow():
    """Run repo-wide this check is 90% false positives, and a noisy check gets
    relaxed until it catches nothing. The docstring has to say why it is scoped,
    so the next reader does not widen it and delete the value."""
    doc = F.orphan_producers.__doc__ or ""
    assert "ast.Call" in doc and "ENTRIES" in doc
