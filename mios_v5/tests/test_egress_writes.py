"""Egress: a write must not pay to receive a copy of itself.

PostgREST echoes every written row back unless told otherwise, and Supabase
bills that echo. `docs/AUDIT_EGRESS_2.md` found 29 of 30 write methods
discarding a response they were paying for — including the whole option chain,
every cycle, all session.

These are structural tests against the parse tree. There is no Supabase here to
measure bytes against, but "did the author remember `returning='minimal'`" is
exactly the kind of thing a test can hold.
"""

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "db" / "supabase_client.py"

#: The one write that genuinely needs its row back: it reads `.data` for the
#: id the database generated. Listed by name so adding a second exception is a
#: deliberate edit rather than a silent drift.
_MAY_ECHO = {"upsert_auto_trade"}

#: The three PostgREST write verbs.
#:
#: ⚠️ `update` belongs here and was absent, which is why this suite stayed
#: green while five `update_*` methods echoed their rows through two rounds of
#: egress work. PostgREST echoes an UPDATE exactly as it echoes an INSERT; a
#: test that knew only two of the three verbs could not see the third, and
#: `entry_gate_signals` is 37 columns wide.
#:
#: The lookbehind excludes `self.cache.update(...)` — `db/cache_manager.py` is
#: an in-process dict and reaches no network. Without it `_safe_query`, which
#: is a READ, reports as an echoing write.
_WRITE_VERB = re.compile(r"\.insert\(|\.upsert\(|(?<!cache)\.update\(")


def _write_methods():
    src = SRC.read_text()
    lines = src.splitlines()
    cls = next(n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.ClassDef) and n.name == "SupabaseDB")
    for fn in cls.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        body = "\n".join(lines[fn.lineno - 1:(fn.end_lineno or fn.lineno)])
        if _WRITE_VERB.search(body):
            yield fn.name, body


def test_every_write_that_discards_its_response_asks_for_minimal():
    """⭐ The fix, held in place."""
    echoing = [name for name, body in _write_methods()
               if "returning" not in body and name not in _MAY_ECHO]
    assert not echoing, (
        "these writes still pay for an echo nobody reads: " + ", ".join(echoing))


def test_the_central_upsert_helper_is_minimal():
    """Nineteen write paths route through `_safe_upsert`, including
    `save_option_chain`. It is the single highest-value line in the file."""
    body = dict(_write_methods())["_safe_upsert"]
    assert "returning=" in body


def test_the_one_exception_is_the_one_that_reads_the_row():
    """A write may echo only when something actually consumes the echo."""
    bodies = dict(_write_methods())
    for name in _MAY_ECHO:
        assert name in bodies, f"{name} no longer exists — drop the exemption"
        assert ".data" in bodies[name], (
            f"{name} no longer reads its response, so it should be minimal too")


def _read_methods():
    """Every method on `SupabaseDB` that issues a SELECT, with its source."""
    src = SRC.read_text()
    lines = src.splitlines()
    cls = next(n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.ClassDef) and n.name == "SupabaseDB")
    for fn in cls.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        body = "\n".join(lines[fn.lineno - 1:(fn.end_lineno or fn.lineno)])
        if ".select(" in body:
            yield fn.name, body


#: Reads whose row count is bounded by a filter rather than by `.limit()` —
#: one trading day, one strike, one job. Named, so that an unbounded read of a
#: table that grows forever cannot join them by accident.
_BOUNDED_BY_FILTER = {
    "get_alert_side_counts", "get_alerts_history", "get_bid_ask_history",
    "get_detected_patterns",
    "get_gex_history", "get_leg_flow_snapshots", "get_market_analytics",
    "get_master_signals", "get_max_pain_history", "get_my_analysis",
    "get_option_chain_history", "get_pcr_history", "get_spot_history",
    "get_trade_config", "get_user_preferences", "get_volume_delta_history",
    "count_trade_signals_today", "count_rows_older_than", "oldest_day",
    "_health_check", "_learning_rows",
}


def test_no_read_of_the_candle_table_is_unbounded():
    """⭐ The 1 GB day's other half.

    `candles_data` is the largest table in the app, and two reads scanned it
    whole: `get_available_candle_series` took three columns of **every candle
    ever stored** with no filter at all, and `get_candle_trading_days` took one
    column of every row of a series — both to derive a handful of distinct
    values that were then thrown away except for a single date.
    """
    for name, body in _read_methods():
        if "'candles_data'" not in body and '"candles_data"' not in body:
            continue
        assert ".limit(" in body or ".range(" in body, (
            f"{name} scans candles_data without a bound")


def test_the_previous_session_is_found_in_one_row():
    """The replacement for those two scans: filtered in the database, ordered,
    one row. It must not be quietly widened back into a scan."""
    body = dict(_read_methods())["latest_candle_day_before"]
    assert ".lt(" in body, "the day filter belongs in the query, not in Python"
    assert ".limit(1)" in body
    assert "select('*')" not in body


def test_every_read_is_bounded_by_a_limit_or_a_named_filter():
    """A read with neither a `.limit()` nor a place on the list above returns
    however many rows the table has grown to. On a table this app appends to
    every cycle, that is a query whose cost rises all day."""
    unbounded = [name for name, body in _read_methods()
                 if ".limit(" not in body and ".range(" not in body
                 and name not in _BOUNDED_BY_FILTER]
    assert not unbounded, (
        "these reads have no row bound: " + ", ".join(sorted(unbounded)))


def test_the_day_list_does_not_scan_the_table():
    """`get_leg_flow_days` pulled 15,000 rows to derive at most thirty values
    from a table written many times a minute and kept for sixty days."""
    src = SRC.read_text()
    lines = src.splitlines()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "get_leg_flow_days")
    body = "\n".join(lines[fn.lineno - 1:(fn.end_lineno or fn.lineno)])
    assert "15000" not in body
    # it must stop early rather than page forever
    assert "break" in body or "while" in body
