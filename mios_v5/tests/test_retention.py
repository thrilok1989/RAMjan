"""`db/retention.py` — executing the purge policies the migrations declared.

Ten `sql/*.sql` migrations end with a commented-out `DELETE`, and
`SupabaseDB.delete_rows` was written for exactly that and never called once. So
nothing has ever purged and every table has grown since the day it was created.

**These tests are mostly about what must NOT happen.** A read cache that
misbehaves serves a stale number; a retention pass that misbehaves destroys
history that cannot be recovered. So the gates, the protected tables and the
"unknown is not zero" rule get more coverage here than the purge itself.
"""

import importlib.util
import pathlib
import sys

import pytest


def _load(name, relpath):
    """Load a `db/` module by path — `db/__init__.py` imports `supabase`, which
    is not installed here.

    Registered in `sys.modules` *before* execution: `@dataclass` resolves field
    types through `sys.modules[cls.__module__]`, and a module that is not there
    yet raises during the decorator rather than at first use.
    """
    root = pathlib.Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(name, root / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


RT = _load("_retention_under_test", "db/retention.py")
ROOT = pathlib.Path(__file__).resolve().parents[2]


class FakeDB:
    """Counts rows by day and records every purge window it is asked for."""

    def __init__(self, counts=None, oldest=None, fail=()):
        self.counts = dict(counts or {})
        self._oldest = dict(oldest or {})
        self.fail = set(fail)
        self.purges = []
        self.logged = []

    def cutoff_day(self, days):
        from datetime import date, timedelta
        return (date.today() - timedelta(days=int(days))).isoformat()

    def count_rows_older_than(self, table, days, day_col="trading_day"):
        if table in self.fail:
            raise RuntimeError("count exploded")
        return self.counts.get(table)

    def oldest_day(self, table, day_col="trading_day"):
        return self._oldest.get(table)

    def purge_window(self, table, day_col, lo, hi):
        self.purges.append((table, day_col, lo, hi))
        self.counts[table] = 0
        return True

    def _safe_upsert(self, table, rows, conflict):
        self.logged.append((table, rows, conflict))


# ══════════════════════════════════════════════════════════════════════
#  the gates — nothing deletes without both
# ══════════════════════════════════════════════════════════════════════

def test_it_ships_disabled():
    """A module that deletes data and arrives switched on is a mistake waiting
    for its first deploy."""
    assert RT.ENABLED is False


def test_run_refuses_while_disabled():
    db = FakeDB({"engine_errors": 5000})
    rep = RT.run(db, confirm=True, enabled=False)
    assert rep["ran"] is False
    assert "not enabled" in rep["blocked"]
    assert db.purges == []


def test_run_refuses_without_confirm_even_when_enabled():
    """Two gates, because one is enough to be safe and not enough to be
    obvious."""
    db = FakeDB({"engine_errors": 5000})
    rep = RT.run(db, confirm=False, enabled=True)
    assert rep["ran"] is False
    assert "confirm=True" in rep["blocked"]
    assert db.purges == []


def test_run_daily_stays_shut_while_disabled(monkeypatch):
    monkeypatch.setattr(RT, "ENABLED", False)
    db = FakeDB({"engine_errors": 5000})
    assert RT.run_daily(db) is None
    assert db.purges == []


def test_a_blocked_run_still_reports_rather_than_raising():
    rep = RT.run(FakeDB(), confirm=True, enabled=False)
    assert rep["rows_removed"] == 0 and rep["tables"] == []


# ══════════════════════════════════════════════════════════════════════
#  protected tables
# ══════════════════════════════════════════════════════════════════════

def test_a_traders_own_notes_are_never_purged():
    """`my_analysis` is written by a human. No retention window has any
    business expiring it."""
    assert "my_analysis" in RT.PROTECTED
    assert "my_analysis" not in RT.POLICIES


@pytest.mark.parametrize("table", sorted(RT.PROTECTED))
def test_no_protected_table_has_a_policy(table):
    assert table not in RT.POLICIES


def test_bounded_state_tables_are_protected_not_policed():
    """`dhan_ticks` and `trade_config` are upserted on a fixed key — they do not
    grow. Purging them by age would delete live state, not history."""
    for t in ("dhan_ticks", "trade_config", "user_preferences",
              "vob_app_state", "backfill_progress", "story_stats"):
        assert t in RT.PROTECTED


def test_the_audit_log_is_never_itself_purged():
    """The record of what was removed must outlive the data it describes."""
    assert RT.LOG_TABLE not in RT.POLICIES


def test_a_protected_table_cannot_be_purged_by_naming_it():
    db = FakeDB({"my_analysis": 9999})
    rep = RT.run(db, tables=("my_analysis",), confirm=True, enabled=True)
    assert rep["tables"] == []
    assert db.purges == []


# ══════════════════════════════════════════════════════════════════════
#  the policies
# ══════════════════════════════════════════════════════════════════════

def test_every_declared_policy_matches_its_migration():
    """The migration authors already chose these numbers. This module executes
    them; it does not get to revise them."""
    import re
    for policy in RT.POLICIES.values():
        if not policy.declared:
            continue
        text = (ROOT / policy.source).read_text()
        m = re.search(r"INTERVAL '(\d+)\s*(day|hour)", text)
        assert m, f"{policy.source} declares no interval"
        n, unit = int(m.group(1)), m.group(2)
        expected = n if unit == "day" else max(1, n // 24)
        assert policy.keep_days == expected, (
            f"{policy.table}: module says {policy.keep_days}d, "
            f"{policy.source} says {n} {unit}s")


def test_every_declared_source_file_exists():
    for policy in RT.POLICIES.values():
        if policy.declared:
            assert (ROOT / policy.source).exists(), policy.source


def test_policies_chosen_here_are_named_as_such():
    """The numbers this module invented must stay arguable, not blend in with
    the ones a migration declared."""
    chosen = RT.undeclared()
    assert chosen
    for table in chosen:
        assert RT.POLICIES[table].source == "this module"
        assert not RT.POLICIES[table].declared


def test_the_learning_corpus_is_kept_longest():
    """Stages 55-60 grade the system on these. They are the measurement."""
    for table in ("engine_attribution", "trade_attribution", "trade_events",
                  "trade_results", "learning_snapshots"):
        assert RT.POLICIES[table].keep_days >= 730


def test_candles_outlive_the_backfill_window():
    """`clear_old_candles(days_old=7)` exists in the client and has never been
    called — seven days would break the backfill, which is very likely why."""
    assert RT.POLICIES["candles_data"].keep_days >= 365


def test_the_microstructure_tables_are_the_short_ones():
    """Highest volume, least useful after the day they describe."""
    for table in ("option_chain_data", "orderbook_data", "bid_ask_history",
                  "volume_delta_history", "detected_patterns"):
        assert RT.POLICIES[table].keep_days <= 30


def test_every_policy_is_positive_and_names_a_column():
    for policy in RT.POLICIES.values():
        assert policy.keep_days > 0
        assert policy.day_col in ("trading_day", "created_at", "ts", "sent_at")
        assert policy.source


def test_no_table_is_policed_twice():
    tables = [p.table for p in RT._DECLARED + RT._CHOSEN]
    assert len(tables) == len(set(tables))


def test_every_policed_table_exists_in_a_migration():
    """A policy for a table nothing creates would delete from nowhere, forever
    silently."""
    schema = "\n".join(p.read_text().lower()
                       for p in list((ROOT / "sql").glob("*.sql"))
                       + [ROOT / "db" / "schema.sql"])
    for table in RT.POLICIES:
        assert f"table if not exists {table}" in schema or \
               f"table {table}" in schema, table


def test_policies_are_ordered_longest_first():
    days = [p.keep_days for p in RT.policies()]
    assert days == sorted(days, reverse=True)


# ══════════════════════════════════════════════════════════════════════
#  preview — always safe, and honest about what it cannot see
# ══════════════════════════════════════════════════════════════════════

def test_preview_never_deletes():
    db = FakeDB({"engine_errors": 5000, "alert_log": 200})
    rows = RT.preview(db)
    assert db.purges == []
    assert len(rows) == len(RT.POLICIES)


def test_preview_works_while_retention_is_disabled():
    """The number has a right answer and asking for it costs nothing."""
    assert RT.ENABLED is False
    rows = RT.preview(FakeDB({"alert_log": 12}))
    assert any(r["rows_over"] == 12 for r in rows)


def test_an_uncountable_table_is_unknown_not_zero():
    """"I could not tell" and "nothing to remove" must not render the same."""
    db = FakeDB({"alert_log": 5}, fail={"engine_errors"})
    rows = {r["table"]: r for r in RT.preview(db)}
    assert rows["engine_errors"]["rows_over"] is None
    assert rows["engine_errors"]["known"] is False
    assert rows["alert_log"]["known"] is True


def test_the_summary_counts_unknowns_separately():
    db = FakeDB({"alert_log": 10, "engine_errors": 20}, fail={"iv_history"})
    total = RT.total_over_retention(RT.preview(db))
    assert total["rows_over"] == 30
    assert total["tables_unknown"] >= 1
    assert total["tables_counted"] + total["tables_unknown"] == total["tables"]


def test_preview_can_be_narrowed_to_one_table():
    rows = RT.preview(FakeDB({"alert_log": 3}), tables=("alert_log",))
    assert len(rows) == 1 and rows[0]["table"] == "alert_log"


def test_the_cutoff_is_the_same_one_the_purge_will_use():
    db = FakeDB({"alert_log": 3})
    row = RT.preview(db, tables=("alert_log",))[0]
    assert row["cutoff"] == db.cutoff_day(RT.POLICIES["alert_log"].keep_days)


# ══════════════════════════════════════════════════════════════════════
#  purging
# ══════════════════════════════════════════════════════════════════════

def test_a_purge_walks_forward_in_bounded_windows():
    """One DELETE across two years of a busy table is how a statement timeout
    happens, and a timeout leaves the table exactly as big as it was."""
    db = FakeDB({"alert_log": 100_000}, oldest={"alert_log": "2024-01-01"})
    RT.run(db, tables=("alert_log",), confirm=True, enabled=True, log=False)
    assert db.purges
    assert all(t == "alert_log" for t, _, _, _ in db.purges)
    from datetime import date
    for _, _, lo, hi in db.purges:
        span = (date.fromisoformat(hi) - date.fromisoformat(lo)).days
        assert 0 < span <= RT.WINDOW_DAYS


def test_a_purge_starts_at_the_oldest_row():
    """Oldest-first means an interrupted purge still shrinks the table."""
    db = FakeDB({"alert_log": 5000}, oldest={"alert_log": "2024-03-05"})
    RT.run(db, tables=("alert_log",), confirm=True, enabled=True, log=False)
    assert db.purges[0][2] == "2024-03-05"


def test_a_long_purge_stops_and_says_it_is_incomplete():
    db = FakeDB({"alert_log": 9_000_000}, oldest={"alert_log": "1990-01-01"})
    rep = RT.run(db, tables=("alert_log",), confirm=True, enabled=True, log=False)
    row = rep["tables"][0]
    assert row["windows"] == RT.MAX_WINDOWS
    assert row["complete"] is False


def test_a_table_with_nothing_over_retention_is_not_touched():
    db = FakeDB({"alert_log": 0}, oldest={"alert_log": "2024-01-01"})
    rep = RT.run(db, tables=("alert_log",), confirm=True, enabled=True, log=False)
    assert db.purges == []
    assert rep["tables"][0]["complete"] is True


def test_a_table_whose_count_failed_is_not_purged_blind():
    """No count means no idea how much would go. That is not a licence."""
    db = FakeDB(fail={"alert_log"})
    rep = RT.run(db, tables=("alert_log",), confirm=True, enabled=True, log=False)
    assert db.purges == []
    assert "count failed" in rep["tables"][0]["error"]


def test_a_failing_window_stops_that_table_and_records_why():
    db = FakeDB({"alert_log": 5000}, oldest={"alert_log": "2024-01-01"})
    db.purge_window = lambda *a: False
    rep = RT.run(db, tables=("alert_log",), confirm=True, enabled=True, log=False)
    row = rep["tables"][0]
    assert row["complete"] is False and row["error"]


def test_one_bad_table_does_not_stop_the_others():
    db = FakeDB({"alert_log": 100, "engine_errors": 100},
                oldest={"alert_log": "2024-01-01", "engine_errors": "2024-01-01"},
                fail={"iv_history"})
    rep = RT.run(db, confirm=True, enabled=True, log=False)
    assert len(rep["tables"]) == len(RT.POLICIES)


def test_run_never_raises_whatever_the_client_does():
    class Broken:
        def __getattr__(self, name):
            def boom(*a, **k):
                raise RuntimeError("everything is on fire")
            return boom
    rep = RT.run(Broken(), confirm=True, enabled=True, log=False)
    assert rep["ran"] is True
    assert all(t["error"] for t in rep["tables"])


# ══════════════════════════════════════════════════════════════════════
#  the audit trail
# ══════════════════════════════════════════════════════════════════════

def test_every_purge_is_logged():
    """A deletion with no record of what it deleted is indistinguishable from
    data loss."""
    db = FakeDB({"alert_log": 500}, oldest={"alert_log": "2024-01-01"})
    RT.run(db, tables=("alert_log",), confirm=True, enabled=True, log=True)
    assert db.logged
    table, rows, _ = db.logged[0]
    assert table == RT.LOG_TABLE
    row = rows[0]
    for field in ("table_name", "keep_days", "cutoff", "rows_before",
                  "rows_removed", "complete", "policy_source"):
        assert field in row


def test_the_log_records_the_policy_source():
    db = FakeDB({"alert_log": 500}, oldest={"alert_log": "2024-01-01"})
    RT.run(db, tables=("alert_log",), confirm=True, enabled=True, log=True)
    assert db.logged[0][1][0]["policy_source"] == "sql/005_alert_log.sql"


def test_a_failing_log_does_not_fail_the_purge():
    db = FakeDB({"alert_log": 500}, oldest={"alert_log": "2024-01-01"})
    db._safe_upsert = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no"))
    rep = RT.run(db, tables=("alert_log",), confirm=True, enabled=True, log=True)
    assert rep["ran"] is True


def test_the_log_migration_exists_and_protects_itself():
    sql = (ROOT / "sql" / "032_retention_log.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS retention_log" in sql
    assert "policy_source" in sql and "rows_removed" in sql
    assert "uniq_retention_log_ts_table" in sql


# ══════════════════════════════════════════════════════════════════════
#  scheduling
# ══════════════════════════════════════════════════════════════════════

def test_a_daily_pass_runs_once_not_once_every_twenty_seconds():
    """The app reruns every 20s. Without this, a scheduled purge would fire
    180 times an hour."""
    state = {}
    assert RT.due(state) is True
    RT._mark_run(state)
    assert RT.due(state) is False


def test_not_due_is_distinguishable_from_ran_and_removed_nothing(monkeypatch):
    monkeypatch.setattr(RT, "ENABLED", True)
    monkeypatch.setattr(RT, "due", lambda *a: False)
    assert RT.run_daily(FakeDB()) is None


def test_run_daily_is_a_no_op_without_a_database(monkeypatch):
    monkeypatch.setattr(RT, "ENABLED", True)
    assert RT.run_daily(None) is None


# ══════════════════════════════════════════════════════════════════════
#  the migrations point at their executor
# ══════════════════════════════════════════════════════════════════════

def test_every_declared_migration_names_the_module_that_executes_it():
    """A future reader finding a commented-out DELETE must not conclude that
    nothing purges — that was true for two years and is no longer."""
    for policy in RT.POLICIES.values():
        if policy.declared:
            text = (ROOT / policy.source).read_text()
            assert "db/retention.py" in text, policy.source


def test_the_app_offers_a_preview_and_gates_the_purge():
    src = (ROOT / "vob_minimal.py").read_text()
    assert "_render_retention_panel" in src
    assert "from db import retention" in src
    assert "run_daily" in src


# ══════════════════════════════════════════════════════════════════════
#  date parsing
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("value,expected", [
    ("2026-03-04", "2026-03-04"),
    ("2026-03-04T09:15:00+05:30", "2026-03-04"),   # created_at / sent_at
    ("2026-03-04 09:15:00", "2026-03-04"),
    (None, None), ("", None), ("nonsense", None),
])
def test_a_day_is_read_from_a_date_or_a_timestamp(value, expected):
    """`trading_day` is a DATE, but `created_at` and `sent_at` are timestamps.
    Both arrive as strings and both must give a date."""
    got = RT._as_date(value)
    assert (got.isoformat() if got else None) == expected
