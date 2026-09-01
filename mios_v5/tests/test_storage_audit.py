"""Storage audit and background cleanup — roadmap items 6 and 8.

Two things are being guarded here.

**The policy numbers have one owner.** They live in `db/retention.py`, and
`sql/034_retention_cron.sql` carries a generated copy so a Postgres cron job can
apply them without the app running. Two representations of one fact drift within
a month unless something checks — so the test below parses the SQL seed and
asserts it matches `POLICIES` exactly, table for table and window for window.

**Installing a migration must not start deleting.** Every gate that guards the
Python purge has to guard the SQL one too, or moving the job into the database
quietly removes the protection.
"""

import importlib.util
import pathlib
import re
import sys

import pytest


def _load(name, relpath):
    root = pathlib.Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(name, root / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ROOT = pathlib.Path(__file__).resolve().parents[2]
RT = _load("_retention_for_cron_test", "db/retention.py")
SA = _load("_storage_audit_under_test", "db/storage_audit.py")

CRON_SQL = (ROOT / "sql" / "034_retention_cron.sql").read_text()
AUDIT_SQL = (ROOT / "sql" / "035_storage_audit.sql").read_text()


def _code(sql: str) -> str:
    """The SQL with `--` comment lines stripped.

    The same lesson the Python guards learned five times over: a file that
    *explains* a rule in prose contains the words the rule forbids, and a check
    that cannot tell a comment from a statement fails on the sentence saying why
    the statement is correct."""
    return "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))


CRON_CODE = _code(CRON_SQL)
AUDIT_CODE = _code(AUDIT_SQL)


def _seeded():
    """The policy rows the migration seeds, parsed out of its VALUES list."""
    block = CRON_CODE.split("VALUES", 1)[1].split("ON CONFLICT", 1)[0]
    out = {}
    for m in re.finditer(r"\('(\w+)',\s*(\d+),\s*'(\w+)',\s*'([^']*)'", block):
        table, keep, col, source = m.groups()
        out[table] = {"keep_days": int(keep), "day_col": col, "source": source}
    return out


class FakeRPC:
    """A client whose `rpc(name)` answers only for the functions it was given."""

    def __init__(self, data=None, fail=()):
        self.data = data or {}
        self.fail = set(fail)
        self.called = []

    class _Res:
        def __init__(self, data): self.data = data

    def rpc(self, name):
        self.called.append(name)
        if name in self.fail:
            raise RuntimeError("function does not exist")
        rows = self.data.get(name)
        if rows is None:
            raise RuntimeError(f"no function {name}")
        outer = self

        class _Q:
            def execute(self_inner):
                return FakeRPC._Res(rows)
        return _Q()


class FakeDB:
    def __init__(self, **kw):
        self.client = FakeRPC(**kw)


# ══════════════════════════════════════════════════════════════════════
#  6 · one owner for the policy numbers
# ══════════════════════════════════════════════════════════════════════

def test_the_sql_seed_matches_the_python_policies_exactly():
    """The guard that makes two representations safe. If this fails, someone
    hand-edited the seed instead of regenerating it."""
    seeded = _seeded()
    assert set(seeded) == set(RT.POLICIES), (
        f"only in SQL: {set(seeded) - set(RT.POLICIES)}; "
        f"only in Python: {set(RT.POLICIES) - set(seeded)}")
    for table, row in seeded.items():
        policy = RT.POLICIES[table]
        assert row["keep_days"] == policy.keep_days, table
        assert row["day_col"] == policy.day_col, table
        assert row["source"] == policy.source, table


def test_the_seed_covers_every_policy_and_no_protected_table():
    seeded = _seeded()
    # 44 → 45: `futures_oi_baseline` (the day's futures OI anchor). The literal
    # is deliberate — a new table must be added to BOTH the Python policies and
    # the SQL seed, and bumping this number is the moment that gets noticed.
    assert len(seeded) == len(RT.POLICIES) == 45
    for table in RT.PROTECTED:
        assert table not in seeded, f"{table} is protected and must not be seeded"


def test_the_audit_log_is_not_seeded_as_a_policy():
    """The record of what was removed must outlive the data it describes."""
    assert RT.LOG_TABLE not in _seeded()


# ══════════════════════════════════════════════════════════════════════
#  6 · installing must not delete
# ══════════════════════════════════════════════════════════════════════

def test_every_policy_installs_disabled():
    assert "enabled         BOOLEAN NOT NULL DEFAULT FALSE" in CRON_SQL


def test_the_purge_skips_disabled_policies():
    assert "FROM retention_policy WHERE enabled" in CRON_SQL


def test_re_running_the_migration_cannot_flip_the_switch():
    """ON CONFLICT updates the window but never `enabled` — a re-run must not
    switch a purge on, or off, behind your back."""
    conflict = CRON_CODE.split("ON CONFLICT", 1)[1].split(";", 1)[0]
    assert "keep_days" in conflict
    assert "enabled" not in conflict


def test_the_purge_defaults_to_dry_run():
    assert "p_dry_run   BOOLEAN DEFAULT TRUE" in CRON_SQL


def test_nothing_is_scheduled_by_the_migration():
    """Every cron statement is commented out. Installing the file must not
    start a recurring delete."""
    for line in CRON_SQL.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        assert "cron.schedule" not in stripped, line
        assert "CREATE EXTENSION" not in stripped, line


def test_the_runbook_tells_you_to_preview_before_enabling():
    for step in ("retention_preview()", "p_dry_run => true",
                 "p_dry_run => false", "cron.schedule", "cron.unschedule"):
        assert step in CRON_SQL, step


def test_it_warns_against_two_purgers():
    """The in-process pass and cron must not both run."""
    assert "exactly one purger" in CRON_SQL
    assert "ENABLED = False" in CRON_SQL


def test_the_preview_function_never_deletes():
    preview = CRON_CODE.split("FUNCTION retention_preview", 1)[1]
    assert "DELETE" not in preview.upper().split("COMMENT ON")[0]


def test_an_uncountable_table_stays_null_not_zero():
    """"I could not count" and "nothing to remove" must not render the same."""
    assert "NULL, never 0" in CRON_SQL


# ══════════════════════════════════════════════════════════════════════
#  6 · the purge is safe to interrupt
# ══════════════════════════════════════════════════════════════════════

def test_deletes_are_chunked_not_one_statement_per_table():
    """A single DELETE across two years holds one long transaction and bloats
    WAL. Chunked, an interrupted run has still committed what it removed."""
    assert "ctid IN" in CRON_SQL and "LIMIT %s" in CRON_SQL


def test_there_is_a_cap_and_the_next_run_resumes():
    assert "p_max_rows" in CRON_SQL
    assert "next run resumes" in CRON_SQL


def test_a_missing_table_is_reported_not_raised():
    """One missing table must not abort the other forty-two."""
    assert "no such table" in CRON_SQL
    assert "to_regclass" in CRON_SQL


def test_a_missing_column_is_reported_too():
    assert "no column" in CRON_SQL
    assert "information_schema.columns" in CRON_SQL


def test_dynamic_sql_quotes_its_identifiers():
    """`format` with %I, never string concatenation of a table name."""
    assert "quote_ident" in CRON_SQL
    for m in re.finditer(r"EXECUTE format\('([^']+)'", CRON_CODE):
        assert "%I" in m.group(1), m.group(1)


def test_the_purge_writes_to_the_audit_log():
    assert "INSERT INTO retention_log" in CRON_SQL


def test_it_explains_why_disk_does_not_shrink_after_a_delete():
    """DELETE marks rows dead; the file stays as large as it ever was. A user
    who does not know that reads a working purge as a broken one."""
    assert "VACUUM" in CRON_SQL
    assert "not the purge failing" in CRON_SQL


# ══════════════════════════════════════════════════════════════════════
#  8 · the storage audit
# ══════════════════════════════════════════════════════════════════════

def test_it_says_plainly_that_supabase_storage_is_unused():
    """The finding, not an omission: no bucket, no upload, no `.storage`
    anywhere. A growing figure is the database."""
    # Flatten the comment prose: the `--` markers sit mid-sentence once the
    # text wraps, so stripping whitespace alone leaves them in the middle.
    prose = " ".join(re.sub(r"^\s*--\s?", "", l) for l in AUDIT_SQL.splitlines())
    flat = " ".join(prose.split())
    assert "does not use Storage at all" in flat
    assert "no bucket, no upload" in flat
    assert "uses no Storage at all" in " ".join(SA.__doc__.split())


def test_the_codebase_really_does_not_touch_storage():
    """Asserted against the source, so the claim above cannot quietly go stale
    the day somebody adds an upload."""
    hits = []
    for path in ROOT.rglob("*.py"):
        if "tests" in path.parts or path.name == "storage_audit.py":
            continue
        text = path.read_text(errors="ignore")
        for pattern in (r"\.storage\.from_", r"storage\.from_\(",
                        r"create_bucket", r"\.upload\("):
            if re.search(pattern, text):
                hits.append(f"{path.name}: {pattern}")
    assert not hits, hits


@pytest.mark.parametrize("fn", SA.FUNCTIONS)
def test_each_rpc_is_declared_in_the_migration(fn):
    assert f"CREATE OR REPLACE FUNCTION {fn}(" in AUDIT_SQL


def test_the_readers_return_what_the_rpc_answered():
    rows = [{"table_name": "candles_data", "total_bytes": 1024}]
    db = FakeDB(data={"storage_report": rows})
    assert SA.report(db) == rows


def test_a_missing_migration_reads_as_empty_not_as_a_crash():
    """A panel that vanishes because a migration is pending looks exactly like
    a panel saying there is nothing to report."""
    db = FakeDB(fail={"storage_report", "unused_indexes", "retention_pressure"})
    assert SA.report(db) == []
    assert SA.unused_indexes(db) == []
    assert SA.pressure(db) == []
    assert SA.installed(db) == {f: False for f in SA.FUNCTIONS}


def test_installed_reports_each_function_separately():
    db = FakeDB(data={"storage_report": [{"a": 1}]},
                fail={"unused_indexes", "retention_pressure"})
    got = SA.installed(db)
    assert got["storage_report"] is True
    assert got["unused_indexes"] is False


def test_the_summary_adds_up():
    rows = [
        {"total_bytes": 1000, "index_bytes": 400, "dead_rows": 10},
        {"total_bytes": 3000, "index_bytes": 600, "dead_rows": 5},
    ]
    s = SA.summarise(rows)
    assert s["tables"] == 2
    assert s["total_bytes"] == 4000 and s["index_bytes"] == 1000
    assert s["index_pct"] == 25 and s["dead_rows"] == 15


def test_the_summary_survives_an_empty_report():
    s = SA.summarise([])
    assert s["tables"] == 0 and s["index_pct"] == 0


def test_the_summary_survives_junk_values():
    s = SA.summarise([{"total_bytes": None, "index_bytes": "x"}])
    assert s["total_bytes"] == 0


@pytest.mark.parametrize("value,text", [
    (0, "0 B"), (512, "512 B"), (2048, "2.0 kB"),
    (5 * 1024 ** 2, "5.0 MB"), (3 * 1024 ** 3, "3.0 GB"),
    (None, "—"), ("nonsense", "—"),
])
def test_bytes_are_written_the_way_the_dashboard_writes_them(value, text):
    assert SA.human(value) == text


def test_the_two_verdicts_that_need_action_are_separable():
    """A table with no policy needs a decision; a policy nobody enabled needs
    one line of SQL. Different problems, listed separately."""
    press = [
        {"table_name": "big_one", "verdict": "no policy — grows forever"},
        {"table_name": "off_one", "verdict": "policy exists, NOT enabled"},
        {"table_name": "fine", "verdict": "policed"},
    ]
    assert [r["table_name"] for r in SA.unpoliced(press)] == ["big_one"]
    assert [r["table_name"] for r in SA.dormant(press)] == ["off_one"]


def test_unused_indexes_excludes_constraints():
    """A primary key enforces correctness whether or not a query reads it, and
    every upsert in this client depends on a unique index."""
    assert "NOT i.indisprimary" in AUDIT_SQL
    assert "NOT i.indisunique" in AUDIT_SQL


def test_retention_pressure_joins_size_to_policy():
    assert "LEFT JOIN retention_policy" in AUDIT_SQL
    for verdict in ("no policy — grows forever", "policy exists, NOT enabled",
                    "policed"):
        assert verdict in AUDIT_SQL


def test_the_report_functions_cannot_write():
    """`STABLE` and pure SQL — a maintenance report that could mutate is not a
    report."""
    for fn in SA.FUNCTIONS:
        body = AUDIT_SQL.split(f"CREATE OR REPLACE FUNCTION {fn}(", 1)[1]
        body = body.split("COMMENT ON", 1)[0]
        assert "STABLE" in body, fn
        for word in ("DELETE ", "INSERT ", "UPDATE ", "TRUNCATE"):
            assert word not in body.upper(), (fn, word)


def test_the_panel_is_wired_into_the_app():
    src = (ROOT / "vob_minimal.py").read_text()
    assert "from db.storage_audit import render" in src


def test_the_panel_never_takes_the_app_down():
    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("no")

    class St:
        class sidebar:
            @staticmethod
            def caption(*a, **k): pass

            @staticmethod
            def expander(*a, **k):
                raise RuntimeError("no sidebar")
        session_state = {}
    SA.render(St(), Boom())          # must not raise
    SA.render(St(), None)
