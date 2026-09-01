"""`SupabaseDB.upsert_candles` — write only what moved.

The app calls this every rerun, every 20 seconds, with the whole
`days_back × 24h` frame. Rewriting all of it meant ~500 rows upserted 180 times
an hour to record roughly 180 new bars: 90,000 row-writes an hour, of which
about 0.2% carried new information.

The one thing that must not break in exchange for that saving: **the forming
candle**. The most recent bar's high, low, close and volume all change until it
closes, so it has to be rewritten every cycle. Watermarking on the last bar
instead of the second-to-last would freeze a partial candle in the table and
never correct it — and every profile, VWAP and value area downstream reads it.

`supabase` is not installed here, so a stub stands in for `create_client`. The
method under test is the real one.
"""

import importlib.util
import pathlib
import sys
import types

import pandas as pd
import pytest


def _load_client():
    """Import `db/supabase_client.py` with `supabase` stubbed out."""
    if "supabase" not in sys.modules:
        stub = types.ModuleType("supabase")
        stub.Client = object
        stub.create_client = lambda url, key: types.SimpleNamespace()
        sys.modules["supabase"] = stub
    root = pathlib.Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    name = "_supabase_client_under_test"
    spec = importlib.util.spec_from_file_location(
        name, root / "db" / "supabase_client.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


SC = _load_client()


def _frame(n, start=1_700_000_000, step=180):
    """`n` three-minute candles, oldest first."""
    rows = []
    for i in range(n):
        ts = start + i * step
        dt = pd.Timestamp(ts, unit="s", tz="Asia/Kolkata")
        rows.append({"timestamp": ts, "datetime": dt, "open": 100.0 + i,
                     "high": 101.0 + i, "low": 99.0 + i, "close": 100.5 + i,
                     "volume": 1000 + i})
    return pd.DataFrame(rows)


class Recorder(SC.SupabaseDB):
    """The real `upsert_candles`, with the network and the constructor removed."""

    def __init__(self):
        self.writes = []          # one entry per _safe_upsert, the records sent
        self.is_connected = True

    def _safe_upsert(self, table, records, conflict_cols):
        self.writes.append(list(records))

    @property
    def rows_written(self):
        return sum(len(w) for w in self.writes)

    @property
    def stamps_written(self):
        return [[r["timestamp"] for r in w] for w in self.writes]


@pytest.fixture
def db(monkeypatch):
    # `st.session_state` is a real dict here, so the watermark behaves exactly
    # as it does in the app: it outlives the object and dies with the session.
    import streamlit as st
    try:
        st.session_state.clear()
    except Exception:
        monkeypatch.setattr(st, "session_state", {}, raising=False)
    return Recorder()


ARGS = ("NIFTY50", "IDX_I", "3")


# ══════════════════════════════════════════════════════════════════════
#  the saving
# ══════════════════════════════════════════════════════════════════════

def test_the_first_write_of_a_session_is_complete(db):
    """No watermark means write everything, once. The fallback is the old
    behaviour, not a gap."""
    df = _frame(500)
    db.upsert_candles(*ARGS, df)
    assert db.rows_written == 500


def test_an_unchanged_frame_writes_two_bars_not_five_hundred(db):
    """The forming bar, plus the one that closed just before it.

    Two rather than one is deliberate: re-sending the last closed bar once more
    guarantees its final values land even if it changed on its closing tick.
    Two rows every 20 seconds instead of five hundred is the saving; the extra
    row is what makes it safe."""
    df = _frame(500)
    db.upsert_candles(*ARGS, df)
    db.upsert_candles(*ARGS, df)
    assert len(db.writes) == 2
    assert len(db.writes[1]) == 2
    assert [r["timestamp"] for r in db.writes[1]] == list(df["timestamp"][-2:])


def test_a_market_day_of_reruns_costs_a_fraction_of_the_writes(db):
    """1,125 reruns is a 6.25-hour session at a 20-second refresh."""
    df = _frame(500)
    db.upsert_candles(*ARGS, df)                     # the one full write
    for i in range(1124):
        if i % 9 == 0:                               # a new 3-min bar
            df = _frame(500 + i // 9 + 1)
        db.upsert_candles(*ARGS, df)

    before = 500 * 1125
    assert db.rows_written < before * 0.01, (
        f"{db.rows_written:,} written vs {before:,} before")


def test_a_new_bar_is_written_with_the_one_still_forming(db):
    db.upsert_candles(*ARGS, _frame(10))
    db.writes.clear()
    db.upsert_candles(*ARGS, _frame(11))
    # the bar that closed before the watermark, the previously-forming bar
    # (now closed), and the new forming one
    assert len(db.writes[0]) == 3


def test_several_new_bars_at_once_are_all_written(db):
    """A slow cycle, or a reconnect, can bring back more than one new bar."""
    db.upsert_candles(*ARGS, _frame(10))
    db.writes.clear()
    db.upsert_candles(*ARGS, _frame(15))
    assert len(db.writes[0]) == 7      # 5 new + the forming bar + the watermark bar


# ══════════════════════════════════════════════════════════════════════
#  the forming candle — the thing that must not break
# ══════════════════════════════════════════════════════════════════════

def test_the_forming_candle_is_rewritten_every_single_cycle(db):
    """Its high, low, close and volume change until the bar closes. A watermark
    on the LAST bar would freeze a partial candle in the table forever."""
    df = _frame(20)
    db.upsert_candles(*ARGS, df)
    tail = list(df["timestamp"][-2:])
    for _ in range(30):
        db.writes.clear()
        db.upsert_candles(*ARGS, df)
        # the forming bar is in every single write, cycle after cycle
        assert [r["timestamp"] for r in db.writes[0]] == tail
        assert db.writes[0][-1]["timestamp"] == tail[-1]


def test_a_correction_to_the_forming_bar_reaches_the_table(db):
    df = _frame(20)
    db.upsert_candles(*ARGS, df)
    df.loc[df.index[-1], "close"] = 999.0
    df.loc[df.index[-1], "volume"] = 999_999
    db.writes.clear()
    db.upsert_candles(*ARGS, df)
    sent = db.writes[0][-1]          # the forming bar is written last
    assert sent["timestamp"] == int(df["timestamp"].iloc[-1])
    assert sent["close"] == 999.0 and sent["volume"] == 999_999


def test_a_closed_bar_is_written_at_least_twice_before_it_is_trusted(db):
    """Once while forming, once after it closed — so the final values always
    land even if the bar changed on its last tick."""
    db.upsert_candles(*ARGS, _frame(10))
    written = [ts for w in db.stamps_written for ts in w]
    db.upsert_candles(*ARGS, _frame(11))
    written += [ts for ts in db.stamps_written[-1]]
    ninth = _frame(10)["timestamp"].iloc[-1]
    assert written.count(ninth) >= 2


# ══════════════════════════════════════════════════════════════════════
#  correctness of the records themselves
# ══════════════════════════════════════════════════════════════════════

def test_the_written_rows_are_unchanged_in_shape(db):
    """Incremental changes WHICH rows go, never WHAT a row looks like."""
    db.upsert_candles(*ARGS, _frame(3))
    row = db.writes[0][0]
    assert set(row) == {"symbol", "exchange", "timeframe", "timestamp",
                        "datetime", "trading_day", "open", "high", "low",
                        "close", "volume", "data_source", "update_time"}
    assert row["symbol"] == "NIFTY50" and row["timeframe"] == "3"


def test_every_bar_in_the_frame_reaches_the_table_eventually(db):
    """The saving is worthless if it loses a candle. Across a session, every
    timestamp the app ever saw must have been written at least once."""
    seen = set()
    for n in range(5, 60):
        db.upsert_candles(*ARGS, _frame(n))
    for write in db.writes:
        seen |= {r["timestamp"] for r in write}
    assert seen == set(_frame(59)["timestamp"])


# ══════════════════════════════════════════════════════════════════════
#  the escape hatches
# ══════════════════════════════════════════════════════════════════════

def test_full_forces_a_complete_rewrite(db):
    df = _frame(40)
    db.upsert_candles(*ARGS, df)
    db.writes.clear()
    db.upsert_candles(*ARGS, df, full=True)
    assert len(db.writes[0]) == 40


def test_an_app_reset_writes_everything_again(db):
    """Session state is where the watermark lives, so a reset is a clean slate
    — the safe direction."""
    import streamlit as st
    db.upsert_candles(*ARGS, _frame(40))
    st.session_state.clear()
    db.writes.clear()
    db.upsert_candles(*ARGS, _frame(40))
    assert len(db.writes[0]) == 40


def test_each_series_has_its_own_watermark(db):
    """The sidebar timeframe is user-selectable. A 3-minute write must not
    convince the 15-minute series that it is up to date."""
    db.upsert_candles("NIFTY50", "IDX_I", "3", _frame(30))
    db.writes.clear()
    db.upsert_candles("NIFTY50", "IDX_I", "15", _frame(30))
    assert len(db.writes[0]) == 30


def test_an_empty_or_missing_frame_writes_nothing(db):
    db.upsert_candles(*ARGS, pd.DataFrame())
    db.upsert_candles(*ARGS, None)
    assert db.writes == []


def test_a_frame_with_one_bar_still_works(db):
    db.upsert_candles(*ARGS, _frame(1))
    db.upsert_candles(*ARGS, _frame(1))
    assert db.rows_written == 2       # the single bar is always still forming


def test_an_older_frame_does_not_rewrite_history(db):
    """`days_back` is a sidebar slider. Turning it down hands over a shorter
    frame, which is not a reason to re-upload what is already stored."""
    db.upsert_candles(*ARGS, _frame(100))
    db.writes.clear()
    db.upsert_candles(*ARGS, _frame(100).tail(20).reset_index(drop=True))
    assert len(db.writes[0]) <= 2
