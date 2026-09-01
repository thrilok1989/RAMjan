"""The egress meter — measure before narrowing another query.

`docs/AUDIT_EGRESS_2.md` fixed the writes on a proven mechanism but sized the
saving from row shapes, and deliberately left 54 `select('*')` calls alone until
there was a ranking. This is that instrument, so these tests are mostly about it
being honest: attributing to the right table, telling insert from upsert, and
never claiming to measure billed bytes.
"""

import ast
import json
import pathlib

import pytest

from tools import egress_meter as E

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean():
    E._STATS.clear()
    yield
    E._STATS.clear()


def test_it_is_off_unless_asked():
    """Production carries one env lookup and no wrapper."""
    src = (ROOT / "tools" / "egress_meter.py").read_text()
    assert 'os.environ.get("MIOS_EGRESS"' in src
    assert E.install(object()) is False or not E.ENABLED


def test_bytes_are_attributed_per_table_and_op():
    E.record("option_chain_data", "upsert", [{"strike": 24000, "oi": 1}] * 100)
    E.record("session_log", "select", [{"a": "x" * 40}] * 2000)
    rep = E.report()
    assert rep["calls"] == 2
    # biggest first — the whole point is a ranking
    assert rep["by_table"][0]["table"] == "session_log"
    assert rep["by_table"][0]["bytes"] > rep["by_table"][1]["bytes"]
    assert rep["by_table"][0]["rows"] == 2000


def test_an_empty_response_costs_nothing():
    """A write that returned nothing is the fix working, not a missing sample."""
    E.record("nifty_spot_data", "upsert", None)
    assert E.report()["total_bytes"] == 0
    assert E.report()["calls"] == 1


def test_a_write_still_echoing_is_named():
    """⭐ The direct check on the audit's fix, measured in flight rather than
    inferred from source."""
    E.record("auto_trades", "upsert", [{"id": 7}], echoing=True)
    E.record("option_chain_data", "upsert", None, echoing=False)
    rep = E.report()
    assert rep["still_echoing"] == ["auto_trades.upsert"]
    assert "still echoing" in E.summary_line(rep)


def test_nothing_echoing_says_nothing():
    E.record("option_chain_data", "upsert", None)
    assert not E.report()["still_echoing"]
    assert "still echoing" not in E.summary_line(E.report())


def test_the_summary_says_the_number_is_pre_gzip():
    """It is `len(json.dumps(...))` — not headers, not compression. Presenting
    it as billed bytes would invite reconciling it against the invoice and
    concluding the meter is broken."""
    E.record("t", "select", [{"a": 1}])
    assert "pre-gzip" in E.summary_line(E.report())


def test_flush_resets_because_the_question_is_one_cycle(tmp_path):
    E.record("t", "select", [{"a": 1}] * 10)
    out = E.flush(tmp_path / "e.json")
    assert out["total_bytes"] > 0
    assert json.loads((tmp_path / "e.json").read_text())["total_bytes"] > 0
    assert E.report()["total_bytes"] == 0


def test_it_never_raises_on_anything():
    class Boom:
        def __repr__(self): raise RuntimeError("no")
    E.record("t", "select", Boom())
    E.record(None, None, object())
    for junk in (None, object(), "x", 42):
        E._table_of(junk); E._op_of(junk); E.echoes(junk)


# ══════════════════════════════════════════════════════════════════════
#  against the real PostgREST client
# ══════════════════════════════════════════════════════════════════════

def _client():
    """A real PostgREST client, or skip.

    ⚠️ `pytest.importorskip` is not enough. `test_incremental_candles` installs
    a stub `supabase` module into `sys.modules` — legitimately, so it can import
    `db/supabase_client.py` without the real dependency — and never removes it.
    Whichever module runs first wins for the whole session, so importing
    successfully says nothing about what came back.

    The check is therefore on the object: a client that cannot build a query is
    a stub, and these tests have nothing to measure against it.
    """
    supabase = pytest.importorskip("supabase")
    client = supabase.create_client("https://example.supabase.co", "x" * 40)
    if not hasattr(client, "table"):
        pytest.skip("`supabase` is stubbed by another test module in this run")
    return client


def test_it_reads_the_table_and_verb_off_a_real_builder():
    """Guessed from the class name this is impossible: PostgREST reuses builder
    classes across verbs, and the composed request is the only source."""
    c = _client()
    assert E._table_of(c.table("option_chain_data").select("*")) == "option_chain_data"
    assert E._op_of(c.table("t").select("*")) == "select"
    assert E._op_of(c.table("t").delete()) == "delete"


def test_insert_and_upsert_are_both_post_and_still_told_apart():
    """The `prefer` header carrying `resolution=merge-duplicates` is the only
    thing that distinguishes them on the wire."""
    c = _client()
    assert E._op_of(c.table("t").insert({"a": 1})) == "insert"
    assert E._op_of(c.table("t").upsert({"a": 1})) == "upsert"


def test_returning_minimal_reads_as_not_echoing():
    """⭐ The audit's fix, verified against the real client rather than the
    source: `returning='minimal'` must actually clear `return=representation`."""
    c = _client()
    assert E.echoes(c.table("t").upsert({"a": 1})) is True
    assert E.echoes(c.table("t").upsert({"a": 1}, returning="minimal")) is False
    assert E.echoes(c.table("t").select("*")) is False, "a read never echoes"


# ══════════════════════════════════════════════════════════════════════
#  wiring
# ══════════════════════════════════════════════════════════════════════

def test_it_meters_the_raw_client_not_the_cached_wrapper():
    """A read served from `st.cache_data` never reaches PostgREST and must not
    be counted as though it had — so the meter installs on `db.client`, inside
    the wrapper, not on the `CachedDB` proxy."""
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    installs = [c for c in ast.walk(tree) if isinstance(c, ast.Call)
                and getattr(c.func, "attr", "") == "install"
                and getattr(getattr(c.func, "value", None), "id", "") == "_egress"]
    assert installs, "the meter is never installed"
    arg = installs[0].args[0]
    assert getattr(arg, "attr", "") == "client", (
        "meter the raw PostgREST client, not the cache-wrapped object")


def test_the_report_carries_the_cache_hit_rate():
    """The other half of the picture.

    A cache hit by definition leaves no trace in this meter — the request never
    reaches PostgREST — so bytes alone cannot tell "the cache is working" from
    "nothing asked". The hit rate comes from `read_cache`'s own counters rather
    than being re-counted here.
    """
    E.record("t", "select", [{"a": 1}])
    rep = E.report()
    assert "cache" in rep
    assert set(rep["cache"]) >= {"calls", "fetches", "hits", "hit_pct"}


def test_the_summary_reports_the_hit_rate_when_there_were_calls(monkeypatch):
    monkeypatch.setattr(E, "cache_stats", lambda: {
        "calls": 100, "fetches": 7, "hits": 93, "hit_pct": 93})
    E.record("t", "select", [{"a": 1}])
    line = E.summary_line(E.report())
    assert "cache 93% hit" in line
    assert "93/100 served without a request" in line


def test_no_cache_activity_says_nothing_rather_than_zero_percent():
    """0% hit with zero calls would read as a broken cache, not an idle one."""
    E.record("t", "select", [{"a": 1}])
    rep = E.report()
    rep["cache"] = {"calls": 0, "fetches": 0, "hits": 0, "hit_pct": 0}
    assert "cache" not in E.summary_line(rep)
