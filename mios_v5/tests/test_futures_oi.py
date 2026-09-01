"""The day-anchored futures OI producer.

The bug it replaces is subtle and silent:

    prev = st.session_state.get('_nifty_fut_prev_oi')
    chg_oi = (oi - prev) if (prev is not None and oi) else 0.0

That is the delta since the previous ~20-second refresh, held in
`session_state`. After a restart `prev` is gone and it reports `0.0` — which
reads exactly like *open interest did not move*. Most of the tests below are
about the ways this module must refuse to answer rather than answer wrongly.
"""

import ast
import importlib.util
import pathlib
import sys

import pytest

from mios_v5 import futures_oi as F

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "mios_v5" / "futures_oi.py"


def _load(name, relpath):
    """Load a `db/` module by path — `db/__init__.py` imports `supabase`,
    which is not installed here. Same shim `test_retention.py` uses."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


STORE = _load("_futures_oi_store_under_test", "db/futures_oi_store.py")


def _quote(price=24500.0, oi=1_000_000.0, symbol="NIFTY-Aug2026-FUT", **kw):
    q = {"symbol": symbol, "expiry": "2026-08-27", "price": price,
         "volume": 500000.0, "oi": oi, "basis": 12.0, "stance": "Premium"}
    q.update(kw)
    return q


def _base(open_oi=1_000_000.0, open_price=24500.0,
          symbol="NIFTY-Aug2026-FUT"):
    return {"trading_day": "2026-08-05", "symbol": symbol,
            "open_oi": open_oi, "open_price": open_price, "open_basis": 10.0}


# ══════════════════════════════════════════════════════════════════════
#  the four states
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("price,oi,expected", [
    (24600.0, 1_100_000.0, F.LONG_BUILDUP),     # price ↑ OI ↑
    (24400.0, 1_100_000.0, F.SHORT_BUILDUP),    # price ↓ OI ↑
    (24600.0, 900_000.0, F.SHORT_COVERING),     # price ↑ OI ↓
    (24400.0, 900_000.0, F.LONG_UNWINDING),     # price ↓ OI ↓
])
def test_the_price_oi_quadrant(price, oi, expected):
    out = F.read(_quote(price=price, oi=oi), _base())
    assert out.futures_oi_state == expected


def test_a_small_move_is_flat_not_a_state():
    """OI ticks constantly. Without a band every cycle names a state and the
    reading is never stable enough to act on."""
    out = F.read(_quote(price=24502.0, oi=1_000_500.0), _base())
    assert out.futures_oi_state == F.FLAT


def test_the_state_is_measured_from_the_day_not_the_last_refresh():
    """The whole point. A quote carrying a *falling* 20-second `chg_oi` while
    the day is still up must read as OI up."""
    out = F.read(_quote(price=24600.0, oi=1_100_000.0, chg_oi=-5000.0),
                 _base())
    assert out.oi_direction == F.UP
    assert out.futures_oi_state == F.LONG_BUILDUP


def test_chg_oi_is_never_read():
    """`chg_oi` is the broken quantity; consuming it would reintroduce the bug.
    Checked on the AST because the docstring discusses it at length."""
    tree = ast.parse(SRC.read_text())
    consts = {n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    calls = {n.args[0].value for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", "") == "get"
             and n.args and isinstance(n.args[0], ast.Constant)}
    assert "chg_oi" not in calls, "the 20-second delta must not be consumed"
    assert "chg_oi" not in (consts & {"chg_oi"}) or "chg_oi" not in calls


# ══════════════════════════════════════════════════════════════════════
#  ⛔ the refusals — UNKNOWN, never zero
# ══════════════════════════════════════════════════════════════════════

def test_no_baseline_reports_unknown_not_flat():
    """Before the day's first quote is stored there is no anchor. Reporting
    Flat would claim OI had not moved."""
    out = F.read(_quote(), None)
    assert out.futures_oi_state == F.UNKNOWN
    assert out.day_oi_change == F.UNKNOWN
    assert "baseline" in out.why


def test_a_different_contract_refuses_to_compare():
    """After rollover the near-month symbol changes and its OI is a different
    series. Comparing across it reads a contract switch as an OI collapse."""
    out = F.read(_quote(symbol="NIFTY-Sep2026-FUT", oi=400_000.0),
                 _base(symbol="NIFTY-Aug2026-FUT"))
    assert out.futures_oi_state == F.UNKNOWN
    assert "different contract" in out.why


def test_zero_oi_is_an_absent_reading_not_no_open_interest():
    """Dhan returns 0 when the quote carries no OI field at all."""
    out = F.read(_quote(oi=0.0), _base())
    assert out.futures_oi_state == F.UNKNOWN
    assert out.day_oi_pct == F.UNKNOWN


def test_a_missing_price_cannot_name_a_state():
    out = F.read(_quote(price=None), _base())
    assert out.futures_oi_state == F.UNKNOWN
    assert out.reporting < out.of


def test_no_quote_at_all():
    out = F.read(None, _base())
    assert out.futures_oi_state == F.UNKNOWN


def test_reporting_travels_with_every_reading():
    for q, b in ((_quote(), _base()), (_quote(), None), (None, None)):
        out = F.read(q, b)
        assert isinstance(out.reporting, int) and isinstance(out.of, int)
        assert out.reporting <= out.of


# ══════════════════════════════════════════════════════════════════════
#  the anchor
# ══════════════════════════════════════════════════════════════════════

def test_a_quote_with_no_oi_is_not_an_anchor():
    """Storing it would fix open_oi at zero for the whole day and make every
    later reading a division by nothing."""
    assert F.anchor_from(_quote(oi=0.0), "2026-08-05") is None
    assert F.anchor_from(_quote(oi=None), "2026-08-05") is None


def test_an_anchor_carries_the_contract_it_belongs_to():
    row = F.anchor_from(_quote(), "2026-08-05")
    assert row["symbol"] == "NIFTY-Aug2026-FUT"
    assert row["open_oi"] == 1_000_000.0
    assert row["trading_day"] == "2026-08-05"


def test_no_anchor_without_a_trading_day():
    assert F.anchor_from(_quote(), None) is None


# ══════════════════════════════════════════════════════════════════════
#  ownership · identity · immutability
# ══════════════════════════════════════════════════════════════════════

def test_it_holds_no_client_and_no_session_state():
    """A producer that reached for its own inputs would be a second futures
    owner, and a database client here is a named forbidden failure mode."""
    tree = ast.parse(SRC.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"requests", "httpx", "supabase", "streamlit", "db"})


def test_every_consumed_fact_names_its_owner():
    for name, owner in F.CONSUMED.items():
        assert owner and owner != F.UNKNOWN
        assert name not in F.COMPUTED_HERE


def test_the_state_names_are_prefixed_so_stage_13_is_not_contradicted():
    """Stage 13 publishes option-chain positioning modes with similar names.
    Different instrument, different fact — the field says which."""
    out = F.read(_quote(price=24600.0, oi=1_100_000.0), _base())
    assert "futures_oi_state" in out.to_dict()
    assert "futures_oi_state" in F.COMPUTED_HERE


def test_identity_and_integrity():
    out = F.read(_quote(), _base())
    assert out.verify() is True
    assert set(out.identity()) == {"id", "version", "created_at", "hash"}
    assert F.read(_quote(), _base()).id != out.id


def test_the_reading_is_frozen():
    out = F.read(_quote(), _base())
    with pytest.raises(Exception):
        out.futures_oi_state = F.LONG_BUILDUP


def test_the_measurements_are_on_the_object():
    """A state a reader cannot check against the numbers is a label."""
    out = F.read(_quote(price=24600.0, oi=1_100_000.0), _base())
    for field in ("day_oi_change", "day_oi_pct", "day_price_change",
                  "open_oi", "current_oi"):
        assert getattr(out, field) != F.UNKNOWN
    assert out.why


# ══════════════════════════════════════════════════════════════════════
#  the store — one write per day, and a missing table is loud
# ══════════════════════════════════════════════════════════════════════

class _FakeTable:
    def __init__(self, rows, log):
        self._rows, self._log = rows, log

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def upsert(self, row, **kw):
        self._log.append(("upsert", row, kw))
        return self

    def execute(self):
        class R:
            data = self._rows
        return R()


class _FakeDB:
    def __init__(self, rows=()):
        self.log = []
        self._rows = list(rows)

    @property
    def client(self):
        outer = self

        class C:
            def table(self, _name):
                return _FakeTable(outer._rows, outer.log)
        return C()


def test_an_existing_anchor_is_never_rewritten():
    """A baseline that moves is not a baseline."""
    db = _FakeDB([_base()])
    out = STORE.ensure(db, _quote(oi=1_400_000.0), "2026-08-05")
    assert out["created"] is False
    assert not [c for c in db.log if c[0] == "upsert"]


def test_the_cached_anchor_costs_no_round_trip():
    """The terminal reruns every ~20s; a read per rerun is the shape of the
    problem that made egress 0.59 GB/day."""
    db = _FakeDB([])
    cached = dict(_base(), trading_day="2026-08-05")
    out = STORE.ensure(db, _quote(), "2026-08-05", cached=cached)
    assert out["baseline"]["open_oi"] == cached["open_oi"]
    assert db.log == []


def test_a_cached_anchor_from_another_day_is_not_reused():
    db = _FakeDB([])
    cached = dict(_base(), trading_day="2026-08-04")
    STORE.ensure(db, _quote(), "2026-08-05", cached=cached)
    assert [c for c in db.log if c[0] == "upsert"], "a new day needs a new anchor"


def test_the_write_refuses_to_overwrite_on_conflict():
    """`ignore_duplicates` is the contract: an upsert that REPLACED the row
    would move the baseline every cycle and turn the day's OI change back into
    the last twenty seconds' change."""
    db = _FakeDB([])
    STORE.ensure(db, _quote(), "2026-08-05")
    kw = [c[2] for c in db.log if c[0] == "upsert"][0]
    assert kw.get("ignore_duplicates") is True
    assert kw.get("on_conflict") == "trading_day,symbol"


def test_no_database_is_reported_not_swallowed():
    assert STORE.ensure(None, _quote(), "2026-08-05")["status"] == STORE.NO_DB


def test_a_missing_migration_is_named():
    """Otherwise Short Covering reports UNKNOWN for a week with nothing to say
    why — how the Stage 74 telemetry gap nearly went unnoticed."""

    class Boom(_FakeDB):
        @property
        def client(self):
            class C:
                def table(self, _n):
                    raise RuntimeError(
                        "PGRST205 Could not find the table 'futures_oi_baseline'")
            return C()

    assert STORE.put_baseline(Boom(), _base()) == STORE.MISSING_TABLE


# ══════════════════════════════════════════════════════════════════════
#  it actually runs
# ══════════════════════════════════════════════════════════════════════

def test_the_producer_has_a_caller():
    """Futures were already fetched and read by nothing — the third
    writer-without-a-reader in this repo. A producer with no caller would be
    the fourth."""
    src = (ROOT / "vob_minimal.py").read_text()
    assert "futures_oi_store" in src
    assert "_futures_oi_baseline" in src
    assert "_futures_oi'" in src or '_futures_oi"' in src


def test_the_caller_passes_the_cached_anchor():
    src = (ROOT / "vob_minimal.py").read_text()
    i = src.index("futures_oi_store")
    assert "cached=" in src[i:i + 900]
