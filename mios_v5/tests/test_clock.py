"""MIOS — IST clock tests.

The bugs these lock out were all invisible: values that were right, rendered
wrong, on a server whose local zone is UTC.
"""

from datetime import datetime, timedelta

import pytz

from mios_v5 import clock

UTC = pytz.UTC
IST = clock.IST


def test_now_is_ist():
    assert clock.now().tzinfo is not None
    assert clock.now().utcoffset() == timedelta(hours=5, minutes=30)


def test_an_epoch_renders_in_ist_not_the_containers_zone():
    """`datetime.fromtimestamp(x)` with no tzinfo returns the CONTAINER's local
    time. This app runs on UTC servers, so every beat was 5½ hours early."""
    moment = IST.localize(datetime(2026, 7, 28, 14, 5))
    assert clock.hhmm(moment.timestamp()) == "14:05"


def test_a_utc_iso_string_renders_in_ist():
    """Slicing the ISO string gave whatever offset the row carried — a
    `+00:00` row and a `+05:30` row showed different times for one instant."""
    assert clock.hhmm("2026-07-28T08:35:00+00:00") == "14:05"
    assert clock.hhmm("2026-07-28T14:05:00+05:30") == "14:05"
    assert clock.hhmm("2026-07-28T08:35:00Z") == "14:05"


def test_the_two_forms_of_the_same_instant_agree():
    utc = "2026-07-28T08:35:00+00:00"
    ist = "2026-07-28T14:05:00+05:30"
    assert clock.hhmm(utc) == clock.hhmm(ist)
    assert clock.trading_day(utc) == clock.trading_day(ist)


def test_a_naive_timestamp_is_read_as_ist():
    """Every naive timestamp in this codebase comes from the leg dataframes,
    which are built in IST — reading them as UTC would shift them 5½ hours."""
    assert clock.hhmm(datetime(2026, 7, 28, 14, 5)) == "14:05"


def test_the_trading_day_does_not_roll_at_0530_ist():
    """A UTC-derived date rolls over at 05:30 IST, splitting a session across
    two dates and mis-bucketing every per-day join."""
    pre_open = IST.localize(datetime(2026, 7, 28, 9, 14))
    assert clock.trading_day(pre_open) == "2026-07-28"
    # the same instant expressed in UTC is 03:44 the same day — a UTC .date()
    # would still say the 28th here, but the boundary case is the point:
    just_after_utc_midnight = IST.localize(datetime(2026, 7, 28, 5, 45))
    assert clock.trading_day(just_after_utc_midnight) == "2026-07-28"
    assert just_after_utc_midnight.astimezone(UTC).date().isoformat() \
        == "2026-07-28"
    late = IST.localize(datetime(2026, 7, 28, 3, 0))
    assert clock.trading_day(late) == "2026-07-28"
    assert late.astimezone(UTC).date().isoformat() == "2026-07-27"   # ← the bug


def test_iso_carries_the_ist_offset():
    out = clock.iso(IST.localize(datetime(2026, 7, 28, 14, 5)))
    assert out.startswith("2026-07-28T14:05:00")
    assert out.endswith("+05:30")


def test_iso_of_a_utc_instant_is_the_same_moment_written_in_ist():
    """TIMESTAMPTZ stores the instant either way — this only changes what a
    human reads."""
    a = clock.iso("2026-07-28T08:35:00+00:00")
    assert a.startswith("2026-07-28T14:05:00") and a.endswith("+05:30")
    assert clock.to_ist(a) == clock.to_ist("2026-07-28T08:35:00+00:00")


def test_an_already_formatted_time_is_echoed_not_reinvented():
    """It carries no date or offset to convert — re-deriving one would either
    fail or invent a day."""
    assert clock.hhmm("09:36") == "09:36"
    assert clock.hhmm(" 14:05 ") == "14:05"
    assert clock.hhmm("25:99") == ""          # not a clock string


def test_bad_input_never_raises():
    for bad in (None, "", "banana", [], {}, float("nan")):
        assert clock.to_ist(bad) is None or clock.to_ist(bad).tzinfo
        assert isinstance(clock.hhmm(bad), str)
    assert clock.hhmm(None) == ""


def test_session_bounds_are_nse_hours():
    o, c = clock.session_bounds(IST.localize(datetime(2026, 7, 28, 12, 0)))
    assert (o.hour, o.minute) == (9, 15)
    assert (c.hour, c.minute) == (15, 30)


def test_stamp_includes_the_zone():
    assert clock.stamp(IST.localize(datetime(2026, 7, 28, 14, 5))) \
        == "28 Jul 14:05 IST"


# ── today_slice: the charts and the day metrics ─────────────────────────
class _DateVec(list):
    """`==` is element-wise, the way a pandas `.dt.date` accessor behaves."""

    def __eq__(self, other):
        return [d == other for d in self]

    def __ne__(self, other):
        return [d != other for d in self]

    __hash__ = None

    @property
    def iloc(self):
        """`.iloc` positional access, the way a pandas accessor has it.

        Its absence is why this fake reported a PASS for the old whole-frame
        fallback after the fallback had been changed: `today_slice` reached for
        `day.iloc[-1]`, the fake raised AttributeError, the `except` returned the
        frame whole, and the assertion matched for entirely the wrong reason. A
        fake that is missing the attribute under test cannot fail.
        """
        return list(self)


class _FakeDT:
    def __init__(self, dates):
        self.date = _DateVec(dates)


class _FakeSeries:
    def __init__(self, values):
        self._v = values
        self.dt = _FakeDT([v.date() for v in values])


class _FakeDF:
    """Minimal stand-in so the slice logic is testable without pandas."""

    def __init__(self, rows, col="datetime"):
        self._rows = rows
        self._col = col
        self.columns = [col, "close"]

    @property
    def empty(self):
        return not self._rows

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, key):
        if isinstance(key, str):
            return _FakeSeries([r[self._col] for r in self._rows])
        return _FakeDF([r for r, keep in zip(self._rows, key) if keep],
                       self._col)


def _frame(days):
    now = clock.now()
    rows = []
    for d in days:
        stamp = now - timedelta(days=d)
        rows.append({"datetime": stamp.replace(tzinfo=None), "close": 100 + d})
    return _FakeDF(rows)


def test_today_slice_drops_previous_sessions():
    """The API is asked for a `days_back` WINDOW, not a session count, so every
    frame arrives carrying part of the previous day."""
    df = _frame([2, 1, 0, 0, 0])
    out = clock.today_slice(df)
    assert len(out) == 3


def test_today_slice_falls_back_to_the_last_session_not_the_whole_window():
    """Pre-open, on a holiday, or against a stale cache, wall-clock today matches
    nothing. Returning the frame WHOLE is what made the terminal draw three days
    of candles — and it also let a three-day high/low be reported as today's
    range, the exact error this function exists to prevent.

    One real session satisfies the same "never blank" intent without lying.
    """
    df = _frame([2, 1])                      # nothing for today
    out = clock.today_slice(df)
    assert len(out) == 1, "must narrow to the most recent session present"
    assert out[df._col].dt.date[0] == (clock.now() - timedelta(days=1)).date()


def test_today_slice_is_safe_on_junk():
    assert clock.today_slice(None) is None
    empty = _FakeDF([])
    assert clock.today_slice(empty) is empty


def test_today_slice_returns_the_frame_when_no_date_column_exists():
    df = _FakeDF([{"datetime": clock.now().replace(tzinfo=None), "close": 1}])
    df.columns = ["close"]
    assert clock.today_slice(df) is df


# ── the callers ─────────────────────────────────────────────────────────
def test_the_chart_slices_to_today():
    import inspect

    from mios_v5.ui import terminal_chart
    src = inspect.getsource(terminal_chart.terminal_chart)
    assert "today_slice" in src
    assert src.count("today_slice(") == 3      # NIFTY + both legs


def test_the_day_metrics_slice_to_today():
    """A day range computed over a multi-day frame reports a two-day range as
    today's, and the 'opening range' becomes the PREVIOUS session's."""
    import inspect

    from mios_v5 import runner
    src = inspect.getsource(runner._price_metrics)
    assert "today_slice" in src


def test_no_module_renders_time_through_the_containers_local_zone():
    """`datetime.fromtimestamp(x)` without a tzinfo argument is the defect."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    bad = []
    for path in list(root.glob("*.py")) + list(root.glob("ui/*.py")):
        if path.name == "clock.py":
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        # AST, not regex — the defect is a CALL with one argument, and prose
        # in a docstring describing the defect must not trip the check
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "fromtimestamp"
                    and len(node.args) < 2 and not node.keywords):
                bad.append(f"{path.name}:{node.lineno}")
    assert not bad, bad


def test_the_app_and_db_client_write_ist():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    db = (root / "db" / "supabase_client.py").read_text()
    assert "datetime.now(pytz.UTC)" not in db
    assert "datetime.now(IST)" in db
    # The signal lifecycle (which owned `ist_iso` and the entered_at/exit_at
    # stamps) was removed with the v0/v2 decision layer — no V6 stage read it.
    # The rule it existed to enforce still binds every timestamp the app writes:
    # IST, never UTC, never a naive local clock.
    app = (root / "vob_minimal.py").read_text()
    assert "datetime.now(pytz.UTC)" not in app
    assert "pytz.timezone('Asia/Kolkata')" in app


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"clock tests passed ({len(fns)})")


# ── today_slice against REAL pandas ─────────────────────────────────────
# The `_FakeDF` above is convenient but it is a fake: it once reported a pass
# for a fallback that had already been changed, because it lacked the attribute
# the new code path reached for. These drive the real thing.

def _real(days, bars=5):
    import pandas as pd
    frames = []
    for d in days:
        idx = pd.date_range(f"{d} 09:15", periods=bars, freq="5min",
                            tz="Asia/Kolkata")
        frames.append(pd.DataFrame({"datetime": idx, "close": 100.0}))
    return pd.concat(frames, ignore_index=True)


def test_real_frame_with_no_rows_for_today_yields_exactly_one_session():
    """The reported bug: the terminal drew three days. `days_back` fetches a
    window, wall-clock today matched nothing, and the whole window came back."""
    df = _real(["2026-07-27", "2026-07-28", "2026-07-29"])
    out = clock.today_slice(df)
    assert out["datetime"].dt.date.nunique() == 1
    assert len(out) == 5


def test_real_frame_keeps_the_most_recent_session_not_the_oldest():
    df = _real(["2026-07-27", "2026-07-29"])
    out = clock.today_slice(df)
    assert str(out["datetime"].iloc[0].date()) == "2026-07-29"


def test_a_real_frame_that_does_contain_today_is_narrowed_to_today():
    import pandas as pd
    today = clock.now().date()
    yday = today - timedelta(days=1)
    df = _real([str(yday), str(today)])
    out = clock.today_slice(df)
    assert out["datetime"].dt.date.nunique() == 1
    assert out["datetime"].iloc[0].date() == today


def test_a_real_single_session_frame_is_unchanged():
    df = _real(["2026-07-29"])
    assert len(clock.today_slice(df)) == len(df)


def test_the_terminal_chart_draws_one_session_from_a_three_day_frame():
    """End to end — `terminal_chart` applies `today_slice` to all three panels,
    so the x-axis span is the real regression surface."""
    import pandas as pd
    from mios_v5.ui.terminal_chart import terminal_chart
    days = ["2026-07-27", "2026-07-28", "2026-07-29"]
    frames = []
    for d in days:
        idx = pd.date_range(f"{d} 09:15", periods=40, freq="5min",
                            tz="Asia/Kolkata")
        frames.append(pd.DataFrame({
            "datetime": idx, "open": 100.0, "high": 105.0,
            "low": 95.0, "close": 100.0, "volume": 1000}))
    multi = pd.concat(frames, ignore_index=True)
    fig, _notes = terminal_chart(multi, multi, multi)
    xs = []
    for tr in fig.data:
        x = getattr(tr, "x", None)
        if x is not None and len(x):
            xs.extend(pd.Timestamp(v) for v in x if v is not None)
    assert xs, "the figure drew no x values"
    assert len({v.date() for v in xs}) == 1, \
        f"chart spans {len({v.date() for v in xs})} sessions"
