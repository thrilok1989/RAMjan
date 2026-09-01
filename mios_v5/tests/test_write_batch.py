"""`db/write_batch.py` — one round-trip per table instead of one per row.

`_safe_upsert` has always taken a list. The cost was in the call sites handing
it one row at a time inside a loop: Stage 40's grading pass issued one
round-trip per prediction, and predictions come due in clumps because every one
logged in the same window matures in the same window.

Two properties matter more than the saving:

* **it always flushes**, including out of a raising block — queued rows dropped
  because something else failed is data loss with nothing pointing at it
* **it refuses a row missing its conflict key** — an upsert whose conflict
  target is absent inserts a second row instead of updating, and a silent
  duplicate is worse than a loud refusal
"""

import importlib.util
import pathlib
import sys

import pytest


def _load(name, relpath):
    root = pathlib.Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(name, root / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


WB = _load("_write_batch_under_test", "db/write_batch.py")
ROOT = pathlib.Path(__file__).resolve().parents[2]


class FakeDB:
    """Counts round-trips, not rows."""

    def __init__(self, fail_tables=()):
        self.calls = []                 # (table, rows, conflict) per round-trip
        self.fail = set(fail_tables)

    def _safe_upsert(self, table, rows, conflict):
        if table in self.fail:
            raise RuntimeError("upsert exploded")
        self.calls.append((table, list(rows), conflict))

    @property
    def round_trips(self):
        return len(self.calls)

    @property
    def rows(self):
        return sum(len(r) for _, r, _ in self.calls)


def _predictions(n):
    return [{"id": i, "correct": True, "realized_move": 0.5} for i in range(1, n + 1)]


# ══════════════════════════════════════════════════════════════════════
#  the saving
# ══════════════════════════════════════════════════════════════════════

def test_twenty_rows_cost_one_round_trip():
    db = FakeDB()
    WB.upsert_many(db, "bias_predictions", _predictions(20))
    assert db.round_trips == 1
    assert db.rows == 20


def test_one_group_per_table_not_per_row():
    db = FakeDB()
    with WB.batch(db) as b:
        b.extend("bias_predictions", _predictions(10))
        b.extend("trade_events", [{"id": i} for i in range(5)], conflict="id")
    assert db.round_trips == 2
    assert set(t for t, _, _ in db.calls) == {"bias_predictions", "trade_events"}


def test_different_conflict_targets_stay_separate():
    """Rows upserted on different keys cannot share a statement."""
    db = FakeDB()
    with WB.batch(db) as b:
        b.add("t", {"id": 1}, conflict="id")
        b.add("t", {"a": 1, "b": 2}, conflict="a,b")
    assert db.round_trips == 2


def test_nothing_queued_is_nothing_sent():
    db = FakeDB()
    with WB.batch(db):
        pass
    assert db.round_trips == 0


# ══════════════════════════════════════════════════════════════════════
#  it always flushes
# ══════════════════════════════════════════════════════════════════════

def test_the_context_manager_flushes_on_the_way_out():
    db = FakeDB()
    with WB.batch(db) as b:
        b.extend("bias_predictions", _predictions(3))
        assert db.round_trips == 0        # nothing sent yet
    assert db.round_trips == 1


def test_it_flushes_even_when_the_block_raises():
    """Dropping queued rows because something ELSE failed is data loss with
    nothing pointing at it."""
    db = FakeDB()
    with pytest.raises(ValueError):
        with WB.batch(db) as b:
            b.extend("bias_predictions", _predictions(4))
            raise ValueError("something else broke")
    assert db.round_trips == 1
    assert db.rows == 4


def test_it_never_swallows_the_exception():
    db = FakeDB()
    with pytest.raises(KeyError):
        with WB.batch(db) as b:
            b.add("t", {"id": 1})
            raise KeyError("must propagate")


def test_a_failing_flush_does_not_raise():
    """A batch that takes the cycle down has cost more than the rows it was
    carrying."""
    db = FakeDB(fail_tables={"bias_predictions"})
    rep = WB.upsert_many(db, "bias_predictions", _predictions(5))
    assert rep["errors"] and rep["rows"] == 0


def test_one_failing_table_does_not_stop_the_others():
    db = FakeDB(fail_tables={"broken"})
    with WB.batch(db) as b:
        b.add("broken", {"id": 1})
        b.add("fine", {"id": 2})
    assert [t for t, _, _ in db.calls] == ["fine"]


def test_flushing_twice_does_not_resend():
    db = FakeDB()
    b = WB.batch(db)
    b.extend("t", _predictions(3))
    b.flush()
    b.flush()
    assert db.round_trips == 1


# ══════════════════════════════════════════════════════════════════════
#  refusing a row that would duplicate
# ══════════════════════════════════════════════════════════════════════

def test_a_row_without_its_conflict_key_is_refused():
    """An upsert whose conflict target is absent from the row does not update
    anything — it inserts a second row."""
    db = FakeDB()
    b = WB.batch(db)
    assert b.add("bias_predictions", {"correct": True}) is False
    assert b.pending == 0
    assert b.refused and "missing" in b.refused[0]["why"]
    b.flush()
    assert db.round_trips == 0


def test_a_null_key_is_refused_too():
    b = WB.batch(FakeDB())
    assert b.add("t", {"id": None, "x": 1}) is False


def test_a_composite_key_needs_every_column():
    b = WB.batch(FakeDB())
    assert b.add("t", {"a": 1}, conflict="a,b") is False
    assert b.add("t", {"a": 1, "b": 2}, conflict="a,b") is True


def test_a_non_mapping_is_refused_rather_than_sent():
    b = WB.batch(FakeDB())
    for junk in (None, "a string", 42, ["a", "list"]):
        assert b.add("t", junk) is False
    assert len(b.refused) == 4


def test_extend_reports_how_many_it_accepted():
    b = WB.batch(FakeDB())
    got = b.extend("t", [{"id": 1}, {"no_key": 2}, {"id": 3}])
    assert got == 2 and b.pending == 2


def test_extend_tolerates_nothing():
    b = WB.batch(FakeDB())
    assert b.extend("t", None) == 0
    assert b.extend("t", []) == 0


# ══════════════════════════════════════════════════════════════════════
#  what it writes is unchanged
# ══════════════════════════════════════════════════════════════════════

def test_the_rows_arrive_exactly_as_queued():
    db = FakeDB()
    rows = _predictions(3)
    WB.upsert_many(db, "bias_predictions", rows)
    _, sent, conflict = db.calls[0]
    assert sent == rows and conflict == "id"


def test_queued_rows_are_copied_not_referenced():
    """A caller reusing its dict after queuing must not silently rewrite what
    is about to be sent."""
    db = FakeDB()
    row = {"id": 1, "correct": True}
    b = WB.batch(db)
    b.add("t", row)
    row["correct"] = False
    b.flush()
    assert db.calls[0][1][0]["correct"] is True


def test_inspection_reports_what_is_queued():
    b = WB.batch(FakeDB())
    b.extend("a", _predictions(2))
    b.add("b", {"id": 9})
    assert b.pending == 3
    assert b.tables == ("a", "b")
    assert len(b.rows_for("a")) == 2


# ══════════════════════════════════════════════════════════════════════
#  what must NOT be batched
# ══════════════════════════════════════════════════════════════════════

def test_batching_is_opt_in_and_intercepts_nothing():
    """The obvious version defers every insert. That version breaks the
    dispatch claim protocol, which writes the SENT row BEFORE the message goes
    out so a crash leaves a claim rather than a duplicate."""
    src = (ROOT / "db" / "write_batch.py").read_text()
    import ast
    tree = ast.parse(src)
    names = {n.name for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef)}
    assert "__getattr__" not in names, "this must not proxy writes"
    assert "insert" not in names


def test_the_dispatch_registry_still_writes_immediately():
    """`reserve()` must reach the database before the message does. If it ever
    starts batching, the claim protocol is decoration."""
    src = (ROOT / "db" / "dispatch_registry.py").read_text()
    assert "write_batch" not in src
    assert "batch(" not in src


def test_the_grading_loop_uses_it_and_keeps_a_fallback():
    """Applied where it was needed, with the per-row path kept — a grading pass
    that writes nothing loses predictions that have already matured and will
    never be re-read as open."""
    src = (ROOT / "mios_v5" / "engines" / "stage40_learning.py").read_text()
    assert "from db.write_batch import upsert_many" in src
    assert "update_bias_prediction" in src, "the per-row fallback is gone"


def test_a_batch_that_fails_falls_back_to_one_row_at_a_time():
    """The shortfall path. A grading pass that writes nothing loses predictions
    that have already matured: read as open, graded, dropped — and still open
    next cycle with a `due_at` further in the past. Measured, then forgotten."""
    from mios_v5.engines.stage40_learning import _write_graded

    class NoBatch:
        """A client without `_safe_upsert` — the batch cannot work here."""
        def __init__(self): self.updated = []
        def update_bias_prediction(self, row_id, fields):
            self.updated.append((row_id, fields)); return True

    db = NoBatch()
    assert _write_graded(db, _predictions(4)) == 4
    assert [i for i, _ in db.updated] == [1, 2, 3, 4]
    assert "id" not in db.updated[0][1], "the key must not be sent as a field"


def test_the_count_returned_is_what_landed_not_what_was_attempted():
    from mios_v5.engines.stage40_learning import _write_graded

    class HalfBroken:
        def update_bias_prediction(self, row_id, fields):
            return row_id % 2 == 0          # odd ids silently fail

    assert _write_graded(HalfBroken(), _predictions(4)) == 2


def test_the_batch_path_is_preferred_when_it_works(monkeypatch):
    """`db/__init__.py` imports `supabase`, which is not installed here, so the
    real import inside `_write_graded` always fails in tests and the fallback
    always runs. This stands the module in so the batch path is exercised —
    otherwise nothing here would ever prove it is the one used in production."""
    import types
    from mios_v5.engines.stage40_learning import _write_graded

    pkg = types.ModuleType("db")
    pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "db", pkg)
    monkeypatch.setitem(sys.modules, "db.write_batch", WB)

    class Batching(FakeDB):
        def update_bias_prediction(self, *a, **k):
            raise AssertionError("must not fall back when the batch works")

    db = Batching()
    assert _write_graded(db, _predictions(6)) == 6
    assert db.round_trips == 1, "six rows, one round-trip"


def test_the_grading_loop_no_longer_writes_inside_the_loop():
    """The point of the change: rows are graded in memory, then written once."""
    import ast
    src = (ROOT / "mios_v5" / "engines" / "stage40_learning.py").read_text()
    tree = ast.parse(src)
    for loop in (n for n in ast.walk(tree) if isinstance(n, ast.For)):
        body = ast.dump(loop)
        if "get_open_bias_predictions" in ast.dump(loop.iter):
            assert "update_bias_prediction" not in body


# ══════════════════════════════════════════════════════════════════════
#  the index migration
# ══════════════════════════════════════════════════════════════════════

def test_the_index_migration_covers_the_heaviest_read():
    """`get_engine_attribution(8000)` sorts by created_at with no filter, and
    engine_attribution had no index on created_at at all."""
    sql = (ROOT / "sql" / "033_query_indexes.sql").read_text()
    assert "idx_eng_attr_created" in sql
    assert "engine_attribution (created_at DESC)" in sql


@pytest.mark.parametrize("index", [
    "idx_eng_attr_created", "idx_trade_attr_created", "idx_trade_results_created",
    "idx_candles_series_day", "idx_oc_expiry_day_ts",
    "idx_trade_signals_status_created", "idx_spot_sec_day_ts",
])
def test_each_audited_index_is_declared(index):
    assert index in (ROOT / "sql" / "033_query_indexes.sql").read_text()


def test_the_migration_warns_about_locking():
    """A plain CREATE INDEX blocks writes. On option_chain_data that is
    minutes, and this app writes every 20 seconds."""
    sql = (ROOT / "sql" / "033_query_indexes.sql").read_text()
    assert "CONCURRENTLY" in sql
    assert "OUTSIDE MARKET HOURS" in sql


def test_every_index_names_a_table_that_exists():
    import re
    sql = (ROOT / "sql" / "033_query_indexes.sql").read_text()
    schema = "\n".join(p.read_text().lower() for p in (ROOT / "sql").glob("*.sql"))
    schema += (ROOT / "db" / "schema.sql").read_text().lower()
    for line in sql.splitlines():
        m = re.match(r"\s*CREATE INDEX IF NOT EXISTS \w+\s*$", line)
    for m in re.finditer(r"CREATE INDEX IF NOT EXISTS \w+\s*\n?\s*ON (\w+)", sql):
        assert f"table if not exists {m.group(1)}" in schema or \
               f"table {m.group(1)}" in schema, m.group(1)
