"""`db/egress_budget.py` — the day ledger and the 100 MB target.

Round 3 proved a large reduction in round-trips and the bill did not visibly
move. Its §6 named the reason: nobody could see bytes per day, only counted
round-trips. This module is that missing number, so the property under test is
narrow — **does it attribute the right bytes to the right table, cheaply, and
does it refuse to state a projection it cannot support?**

The last one matters most. An instrument that answers confidently from an
eleven-second sample is worse than one that says "not yet".

`db/` is not importable here — `db/__init__.py` imports `supabase`, which is
not installed — so the module is loaded from its path directly, the same
approach `test_read_cache` uses.
"""

import ast
import importlib.util
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load():
    if "streamlit" not in sys.modules:
        sys.modules["streamlit"] = types.ModuleType("streamlit")
    spec = importlib.util.spec_from_file_location(
        "_egress_budget_under_test", ROOT / "db" / "egress_budget.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: The day every test pretends it is.
#:
#: ⚠️ `_today` is STUBBED rather than the ledger merely being rolled to a fixed
#: date. `note()` calls `_roll()` with no argument on every response, so the real
#: wall clock decides whether that roll clears the ledger — and a test that
#: seeded "2026-08-10" then rolled to "2026-08-11" passed on every day of the
#: year except the one the machine's clock actually read 2026-08-11, when the
#: second roll became a no-op and the ledger kept its rows. A ledger test may not
#: depend on the date it runs on.
_FAKE_DAY = "2026-08-10"


@pytest.fixture
def eb(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "_today", lambda: _FAKE_DAY)
    mod._roll(_FAKE_DAY)
    return mod


# ══════════════════════════════════════════════════════════════════════
#  attribution
# ══════════════════════════════════════════════════════════════════════

def test_bytes_are_attributed_per_table_and_op(eb):
    eb.note("engine_attribution", "select", [{"a": 1, "b": "xx"}] * 10)
    eb.note("trade_signals", "select", [{"a": 1}] * 4)
    data = eb.report()
    got = {(r["table"], r["op"]): r for r in data["by_table"]}
    assert got[("engine_attribution", "select")]["rows"] == 10
    assert got[("trade_signals", "select")]["rows"] == 4
    assert data["calls"] == 2


def test_the_biggest_table_sorts_first(eb):
    """The panel's whole job is to point at one table, so the order is the
    product, not a presentation detail."""
    eb.note("small", "select", [{"a": 1}])
    eb.note("huge", "select", [{"padding": "x" * 400}] * 50)
    assert eb.report()["by_table"][0]["table"] == "huge"


def test_a_write_and_a_read_of_one_table_are_counted_apart(eb):
    """`option_chain_data` is written every cycle and read by nothing. Merging
    the two would hide which half is spending."""
    eb.note("option_chain_data", "upsert", [{"a": 1}] * 100)
    eb.note("option_chain_data", "select", [{"a": 1}] * 2)
    ops = {r["op"] for r in eb.report()["by_table"]}
    assert ops == {"upsert", "select"}


def test_a_single_row_response_counts_as_one_row(eb):
    """PostgREST returns a dict rather than a list for some single-row reads,
    and `len()` of a dict is its key count — which would be a silent
    over-count."""
    eb.note("nifty_spot_data", "select", {"ltp": 24000, "a": 1, "b": 2, "c": 3})
    assert eb.report()["by_table"][0]["rows"] == 1


def test_an_empty_response_adds_nothing(eb):
    eb.note("engine_attribution", "select", [])
    eb.note("engine_attribution", "select", None)
    assert eb.report()["total_bytes"] == 0


# ══════════════════════════════════════════════════════════════════════
#  the sampling, which is the reason this can be always-on
# ══════════════════════════════════════════════════════════════════════

def test_the_row_width_is_serialised_once_per_table_per_day(eb, monkeypatch):
    """⚠️ The design constraint. Measuring exactly means `json.dumps` on every
    response, and on an 8,000-row read inside a 20-second refresh loop that is
    real CPU spent to observe a cost problem.

    One sample per (table, op) per day, then `rows × width`. If this ever
    becomes per-call, the instrument starts costing what it measures.
    """
    calls = {"n": 0}
    real = eb.json.dumps

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(eb.json, "dumps", counting)
    for _ in range(50):
        eb.note("engine_attribution", "select", [{"a": 1, "b": 2}] * 100)
    assert calls["n"] == 1, "row width should be sampled once, not per call"
    assert eb.report()["by_table"][0]["rows"] == 5000


def test_bytes_scale_with_rows_at_the_sampled_width(eb):
    eb.note("t", "select", [{"aaaa": "bbbb"}] * 1)
    width = eb.report()["by_table"][0]["width"]
    assert width > 0
    eb.note("t", "select", [{"aaaa": "bbbb"}] * 9)
    row = eb.report()["by_table"][0]
    assert row["rows"] == 10
    assert row["bytes"] == 10 * width


def test_an_empty_first_response_does_not_freeze_the_width_at_zero(eb):
    """Most MIOS analytics tables are empty for most of a session. Sampling the
    width from the first EMPTY response would peg the table at 0 B/row for the
    rest of the day and hide it completely once it filled."""
    eb.note("story_validations", "select", [])
    eb.note("story_validations", "select", [{"a": 1, "b": "text"}] * 20)
    row = eb.report()["by_table"][0]
    assert row["width"] > 0
    assert row["bytes"] > 0


# ══════════════════════════════════════════════════════════════════════
#  the projection, and its refusal to guess
# ══════════════════════════════════════════════════════════════════════

def test_no_projection_from_too_short_a_window(eb):
    """A confident fiction with a decimal point is the failure mode here."""
    eb.note("t", "select", [{"a": 1}] * 10)
    data = eb.report()
    assert data["projected_day_bytes"] is None
    assert data["over_budget"] is False


def test_a_projection_appears_once_the_window_is_long_enough(eb):
    eb.note("t", "select", [{"a": 1}] * 10)
    eb._STARTED = eb.time.time() - 3600        # measured for an hour
    data = eb.report()
    assert data["projected_day_bytes"] is not None
    # an hour's traffic scaled to the 7.25h refresh window
    assert data["projected_day_bytes"] > data["total_bytes"]


def test_over_budget_is_decided_on_the_projection_not_the_total(eb):
    """The total crosses 100 MB near the end of a bad day, which is far too
    late to be told. The projection is what makes it actionable at 10am."""
    eb.note("t", "select", [{"padding": "x" * 500}] * 60000)
    eb._STARTED = eb.time.time() - 1800
    data = eb.report()
    assert data["total_bytes"] < eb.BUDGET_BYTES
    assert data["projected_day_bytes"] > eb.BUDGET_BYTES
    assert data["over_budget"] is True


def test_the_budget_is_the_hundred_megabytes_that_was_asked_for(eb):
    assert eb.BUDGET_BYTES == 100 * 1024 * 1024


def test_the_ledger_starts_over_on_a_new_trading_day(eb, monkeypatch):
    """A day total that carries yesterday's rows over is not a day total.

    The clock is moved, not the ledger: `note()` re-rolls on every response, so
    this checks the mechanism the running app actually relies on at midnight
    rather than a manual reset nothing calls.
    """
    eb.note("t", "select", [{"a": 1}] * 10)
    assert eb.report()["total_bytes"] > 0
    monkeypatch.setattr(eb, "_today", lambda: "2026-08-11")
    eb.note("t", "select", [{"a": 1}])       # the first response of the new day
    data = eb.report()
    assert data["day"] == "2026-08-11"
    assert data["by_table"][0]["rows"] == 1, \
        "yesterday's rows survived the roll-over"


# ══════════════════════════════════════════════════════════════════════
#  it never takes the app down
# ══════════════════════════════════════════════════════════════════════

def test_note_survives_anything_handed_to_it(eb):
    class Hostile:
        def __len__(self):
            raise RuntimeError("no")

    for junk in (Hostile(), object(), 3, "text", {1: 2}):
        eb.note("t", "select", junk)          # must not raise


def test_install_on_a_client_that_cannot_be_probed_reports_false(eb):
    class Broken:
        def table(self, _):
            raise RuntimeError("no PostgREST here")

    assert eb.install(Broken()) is False
    assert eb.report()["installed"] is False


def test_the_panel_reports_that_it_is_not_measuring_rather_than_zero(eb):
    """⚪ could not measure is a report. A panel showing 0 B when the instrument
    never installed reads as 'no egress', which is the opposite of the truth."""
    said = []

    class FakeSidebar:
        def expander(self, *a, **k):
            return FakeCtx()

    class FakeCtx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class FakeSt:
        sidebar = FakeSidebar()

        def caption(self, text):
            said.append(text)

        def button(self, *a, **k):
            return False

    eb._installed = False
    eb.render(FakeSt())
    assert any("Not measuring" in s for s in said)


# ══════════════════════════════════════════════════════════════════════
#  wiring — a meter nothing installs measures nothing
# ══════════════════════════════════════════════════════════════════════

def test_the_app_installs_the_ledger_on_the_raw_client():
    """⚠️ Installed on `db.client` — the RAW client, before the read-cache
    wrapper. A read served from `st.cache_data` never reaches PostgREST, and
    counting it as if it had would report egress the app did not spend.
    """
    src = (ROOT / "vob_minimal.py").read_text()
    assert "from db import egress_budget as _budget" in src
    assert "_budget.install(db.client)" in src


def test_the_app_renders_the_panel():
    src = (ROOT / "vob_minimal.py").read_text()
    assert "from db.egress_budget import render as _render_egress" in src
    assert "_render_egress(st, db)" in src


def test_the_ledger_is_not_gated_behind_an_environment_variable():
    """`tools/egress_meter.py` is opt-in because it `json.dumps` every response.
    This one is sampled specifically so it can be always on — if a future edit
    adds an `ENABLED` gate, the number goes back to being invisible, which is
    the whole problem it was built for."""
    src = (ROOT / "db" / "egress_budget.py").read_text()
    tree = ast.parse(src)
    names = {t.id for n in tree.body if isinstance(n, ast.Assign)
             for t in n.targets if isinstance(t, ast.Name)}
    assert "ENABLED" not in names
    assert "os.environ" not in src
