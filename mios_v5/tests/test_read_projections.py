"""`db/supabase_client.py::projection` — narrowing a read without blanking it.

`db/read_cache.py` reduced how OFTEN a read reaches Supabase. It cannot reduce
how BIG the read is, and two kinds of fetch survive any cache: the cold-start
pass after a restart, and the refetch every invalidation forces. Those pay the
full row width every time, so the width is the remaining lever.

`tools/egress_meter.py` named it and deferred it, for a reason worth quoting
because it is the failure this file exists to prevent:

    > narrowing a column list is a per-call-site decision: each one needs its
    > consumers checked, and getting it wrong renders a blank field rather than
    > a slow one.

An inclusion list has exactly one dangerous failure mode: a column added to the
table later is silently omitted, and a silently absent column IS that blank
field. So the projection is not trusted as written — every list is re-derived
here from `sql/*.sql`, and a schema change that is not reflected in
`_PROJECTIONS` fails this suite instead of the panel.

`db/` is not importable here — `db/__init__.py` imports `supabase`, which is
not installed — so the module is loaded from its path directly, the same
approach `test_read_cache` already uses.
"""

import ast
import importlib.util
import pathlib
import re
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load():
    """`db/supabase_client.py` with its unavailable imports stubbed out.

    Only module-level constants and `projection()` are exercised, so the stubs
    need to satisfy import time and nothing else.
    """
    for name, attrs in (("streamlit", ()), ("supabase", ("create_client", "Client")),
                        ("db", ()), ("db.cache_manager", ("CacheManager",))):
        if name in sys.modules:
            continue
        mod = types.ModuleType(name)
        for attr in attrs:
            setattr(mod, attr, object)
        sys.modules[name] = mod
    spec = importlib.util.spec_from_file_location(
        "_supabase_client_under_test", ROOT / "db" / "supabase_client.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as err:                      # pragma: no cover
        pytest.skip(f"supabase_client not loadable in this sandbox: {err}")
    return mod


SC = _load()


# ══════════════════════════════════════════════════════════════════════
#  the schema is the source of truth
# ══════════════════════════════════════════════════════════════════════

def _declared_columns(table: str):
    """Columns `sql/*.sql` declares for `table`, in declaration order.

    Read from the migrations rather than from a live database so the check runs
    in CI with no credentials — the schema in git is what deploys.
    """
    for path in sorted((ROOT / "sql").glob("*.sql")) + [ROOT / "db" / "schema.sql"]:
        if not path.exists():
            continue
        text = path.read_text()
        for match in re.finditer(
                r"CREATE TABLE (?:IF NOT EXISTS )?(?:public\.)?"
                + re.escape(table) + r"\s*\((.*?)\n\);", text, re.S | re.I):
            cols = []
            for line in match.group(1).split("\n"):
                line = line.strip().rstrip(",")
                if not line or line.startswith("--"):
                    continue
                if re.match(r"(PRIMARY|UNIQUE|FOREIGN|CONSTRAINT|CHECK)\b",
                            line, re.I):
                    continue
                name = re.match(r"([a-z_][a-z0-9_]*)\s", line)
                if name:
                    cols.append(name.group(1))
            if cols:
                return cols
    return []


@pytest.mark.parametrize("table", sorted(SC._PROJECTIONS))
def test_a_projection_is_exactly_the_schema_minus_its_dropped_blobs(table):
    """⚠️ The headline. This is what stops a new column becoming a blank field.

    Add a column to `sql/*.sql` and forget `_PROJECTIONS`, and the read would
    silently stop returning it — no error, no empty result, just a panel cell
    that renders nothing. Deriving the expected set from the migration turns
    that into a failure here.
    """
    declared = _declared_columns(table)
    assert declared, f"no CREATE TABLE for {table} found in sql/"
    dropped = set(SC._PROJECTION_DROPS.get(table, ()))
    assert set(SC._PROJECTIONS[table]) == set(declared) - dropped, (
        f"{table}: projection has drifted from the schema. Declared "
        f"{sorted(declared)}, dropping {sorted(dropped)}.")


@pytest.mark.parametrize("table", sorted(SC._PROJECTION_DROPS))
def test_a_dropped_column_is_one_the_table_really_has(table):
    """A drop list naming a column that no longer exists is a stale comment
    pretending to be a decision — and it would quietly widen the projection
    back to everything the next time the schema changed."""
    declared = set(_declared_columns(table))
    for col in SC._PROJECTION_DROPS[table]:
        assert col in declared, (
            f"{table}.{col} is listed as dropped but the schema has no such "
            f"column")


#: For each projected table: the read methods that return its rows, and every
#: module those rows are handed to.
#:
#: ⚠️ Scoped rather than repo-wide on purpose. `data` is a generic key name —
#: `vob_minimal.py` alone has fifteen `.get('data')` hits, every one of them a
#: Dhan HTTP payload — so a repo-wide grep for a dropped column reports noise
#: and would end up being relaxed until it caught nothing. This says instead:
#: *these* are the files that ever see a row of this table, so these are the
#: files a dropped column must not appear in. `test_the_consumer_surface_is_complete`
#: keeps the list honest when a new panel starts reading.
_ROW_CONSUMERS = {
    "engine_attribution": {
        "reads": ("get_engine_attribution",),
        # dashboard_v6 fetches; these are every module it forwards the rows to.
        "modules": ("mios_v5/ui/dashboard_v6.py", "mios_v5/ui/learning_panel.py",
                    "mios_v5/ui/review_panel.py", "mios_v5/trade_review.py",
                    "mios_v5/daily_summary.py", "mios_v5/contribution.py",
                    "mios_v5/engine_accuracy.py", "mios_v5/calibration.py",
                    "mios_v5/false_signal.py", "mios_v5/threshold_opt.py",
                    "mios_v5/learning_report.py", "mios_v5/layer_learning.py"),
        # Stage 55 BUILDS this key from a live MarketState in order to write it.
        # Producer, not consumer: `engine_rows(reads, ...)` never reads the DB.
        "producers": ("mios_v5/attribution.py",),
    },
    "trade_signals": {
        "reads": ("get_trade_signals",),
        "modules": ("mios_v5/ui/dashboard_v6.py", "mios_v5/replay.py"),
        "producers": (),
    },
}


@pytest.mark.parametrize("table", sorted(SC._PROJECTIONS))
def test_every_dropped_column_has_no_reader_among_its_consumers(table):
    """The safety argument, checked rather than asserted.

    A blob is only safe to drop if nothing reads it off a row of THIS table.
    Both current drops are written for provenance and never read back —
    `engine_attribution.data` (Stage 55 builds it from a live MarketState) and
    `trade_signals.engine_snapshot` (superseded by per-engine rows).

    A hit here means the projection would render a blank field. Either restore
    the column or stop reading it; do not add the file to `producers` unless it
    genuinely writes rather than reads.
    """
    spec = _ROW_CONSUMERS.get(table)
    assert spec, f"{table} is projected but has no declared consumer surface"
    for col in SC._PROJECTION_DROPS.get(table, ()):
        pattern = re.compile(r"""\.get\(\s*["']%s["']|\[\s*["']%s["']\s*\]"""
                             % (re.escape(col), re.escape(col)))
        for rel in spec["modules"]:
            path = ROOT / rel
            if not path.exists():
                pytest.fail(f"{rel} is a declared consumer but does not exist")
            for num, line in enumerate(path.read_text().split("\n"), 1):
                if pattern.search(line):
                    pytest.fail(
                        f"{table}.{col} is dropped from the projection but "
                        f"{rel}:{num} reads it")


@pytest.mark.parametrize("table", sorted(_ROW_CONSUMERS))
def test_the_consumer_surface_is_complete(table):
    """⚠️ What stops `_ROW_CONSUMERS` rotting into a comment.

    The list above is only a safety argument while it names every file that
    fetches these rows. A new panel calling `get_engine_attribution` would see
    a projected row and could read the dropped blob without any test noticing —
    so the callers are re-derived here and must all be declared.
    """
    spec = _ROW_CONSUMERS[table]
    declared = set(spec["modules"]) | set(spec["producers"])
    searched = [p for p in (ROOT / "mios_v5").rglob("*.py")
                if "/tests/" not in str(p)] + [ROOT / "vob_minimal.py"]
    for read in spec["reads"]:
        pattern = re.compile(r"\." + re.escape(read) + r"\s*\(")
        for path in searched:
            if not pattern.search(path.read_text()):
                continue
            rel = str(path.relative_to(ROOT))
            assert rel in declared, (
                f"{rel} calls {read} but is not in _ROW_CONSUMERS[{table!r}] — "
                f"check whether it reads "
                f"{SC._PROJECTION_DROPS.get(table, ('',))[0]!r}, then add it")


# ══════════════════════════════════════════════════════════════════════
#  projection() itself
# ══════════════════════════════════════════════════════════════════════

def test_an_unprojected_table_still_selects_everything():
    """Narrowing is opt-in. A table whose consumers have not been checked must
    keep `select('*')` — the safe direction, and the reason this is a map
    rather than a blanket rewrite."""
    assert SC.projection("candles_data") == "*"
    assert SC.projection("nope_not_a_table") == "*"


@pytest.mark.parametrize("table", sorted(SC._PROJECTIONS))
def test_a_projection_renders_as_a_postgrest_column_list(table):
    """PostgREST wants `a,b,c` — no spaces, no trailing comma, no star."""
    rendered = SC.projection(table)
    assert "*" not in rendered
    assert " " not in rendered
    assert not rendered.startswith(",") and not rendered.endswith(",")
    assert rendered.split(",") == list(SC._PROJECTIONS[table])


# ══════════════════════════════════════════════════════════════════════
#  the reads actually use it
# ══════════════════════════════════════════════════════════════════════

def test_the_two_narrowed_reads_go_through_projection():
    """The regression this repo has hit twice: a layer that exists and nothing
    calls. A projection map no read consults saves nothing at all."""
    src = (ROOT / "db" / "supabase_client.py").read_text()
    tree = ast.parse(src)
    lines = src.split("\n")
    bodies = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
                "_learning_rows", "get_trade_signals"):
            bodies[node.name] = "\n".join(lines[node.lineno - 1:node.end_lineno])
    assert set(bodies) == {"_learning_rows", "get_trade_signals"}
    for name, body in bodies.items():
        assert "projection(" in body, f"{name} does not use projection()"
        assert ".select('*')" not in body, f"{name} still selects everything"


def test_the_widest_read_in_the_app_is_the_one_that_got_narrowed():
    """`engine_attribution` is read at 8,000 rows — the largest single read
    anywhere. If a future change moves that crown, the projection should move
    with it, and this asserts the current claim rather than leaving it in prose.
    """
    assert "engine_attribution" in SC._PROJECTIONS
    assert "data" in SC._PROJECTION_DROPS["engine_attribution"]


# ══════════════════════════════════════════════════════════════════════
#  one limit per read — round 3's rule, applied to the four it missed
# ══════════════════════════════════════════════════════════════════════

_ONE_LIMIT_READS = ("get_engine_attribution", "get_trade_events",
                    "get_trade_results", "get_trade_attribution",
                    "get_session_log", "get_trade_signals")


@pytest.mark.parametrize("read", _ONE_LIMIT_READS)
def test_a_read_is_asked_at_exactly_one_limit(read):
    """⚠️ The read cache keys on the arguments, so two limits are two entries
    and two round-trips over overlapping rows — and every panel body runs on
    every rerun whether or not its tab is open.

    Round 3 fixed this for `get_session_log` and `get_trade_signals` and left
    the four learning reads asking at three limits each: `get_engine_attribution`
    at 2,000 · 8,000 · 3,000 alone was 13,000 rows to serve 8,000. A panel that
    wants fewer rows slices the shared result — the reads return newest-first,
    so a slice is the same rows a narrower query would have returned.
    """
    src = (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    literals = re.findall(re.escape(read) + r"\(limit=(\d+)\)", src)
    assert not literals, (
        f"{read} is called with a bare limit {literals} — use the shared "
        f"module constant and slice the result instead")
