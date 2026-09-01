"""MIOS — one clock, and it is IST.

NSE trades in IST. Every date this system reasons about — the trading day, the
session's opening range, "today's" candles, when a signal was born — is an IST
concept. Anything computed in another zone is wrong in a way that is invisible
until it isn't.

## Where it actually bit

**`datetime.fromtimestamp(x)` with no tzinfo returns the *container's* local
time.** This app runs on servers set to UTC, so every timestamp rendered that
way was 5½ hours early: a beat logged at 14:05 IST displayed as 08:35, and a
replay frame at 10:42 read as 05:12. The values were right; the rendering was
silently wrong.

**Slicing an ISO string to get the time** (`s[11:16]`) reads whatever offset the
string carries. A row written with `+00:00` renders as UTC and a row written
with `+05:30` renders as IST — from the same table, in the same list.

**A trading day derived in UTC rolls over at 05:30 IST**, splitting a single
session across two dates. Every per-day join — day-type performance, daily
summary, engine attribution — would silently mis-bucket the morning.

## What this does and does not fix in Supabase

`TIMESTAMPTZ` stores an absolute instant. Writing `+05:30` instead of `+00:00`
for the same moment does **not** change what is stored — it is the same point in
time either way. What changes is what a human sees in the Supabase table editor,
in a CSV export, and in any raw JSON: IST, which is the only zone this desk
thinks in. The genuine correctness fixes are the *derived* values above — dates,
session slices and rendered times — not the instants.

Pure module. No IO.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Optional

import pytz

IST = pytz.timezone("Asia/Kolkata")

#: NSE cash/derivatives session, IST
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)


def now() -> datetime:
    """The current moment, in IST. The only `now` this system should use."""
    return datetime.now(IST)


def iso(ts: Any = None) -> str:
    """IST ISO-8601 with the `+05:30` offset — what gets written to Supabase.

    The instant is unchanged versus a UTC-offset string; the offset is what
    makes a raw row readable without mental arithmetic.
    """
    d = to_ist(ts) if ts is not None else now()
    return (d or now()).isoformat()


def to_ist(ts: Any) -> Optional[datetime]:
    """Anything time-like → an IST-aware datetime, or None.

    Accepts epoch seconds, ISO strings (with or without an offset), and
    datetimes. **A naive input is assumed to be IST**, not UTC — every naive
    timestamp in this codebase comes from the leg dataframes, which are built
    in IST.
    """
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.astimezone(IST) if ts.tzinfo else IST.localize(ts)
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), IST)
        except (ValueError, OSError, OverflowError):
            return None
    s = str(ts).strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.astimezone(IST) if d.tzinfo else IST.localize(d)
    except ValueError:
        pass
    # pandas Timestamp and anything else exposing tz_convert / to_pydatetime
    for attr in ("tz_convert", "to_pydatetime"):
        fn = getattr(ts, attr, None)
        if callable(fn):
            try:
                out = fn(IST) if attr == "tz_convert" else fn()
                return to_ist(out)
            except Exception:
                continue
    return None


#: an already-formatted wall-clock string, e.g. "09:36"
_HHMM = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


def hhmm(ts: Any) -> str:
    """`14:05` in IST — the only time format shown on any panel.

    A value that is *already* an `HH:MM` string is echoed unchanged: it carries
    no date or offset to convert, and re-deriving one would either fail or
    invent a day. Everything else is normalised to IST first.
    """
    if isinstance(ts, str) and _HHMM.match(ts.strip()):
        return ts.strip()
    d = to_ist(ts)
    return d.strftime("%H:%M") if d else ""


def stamp(ts: Any = None) -> str:
    """`28 Jul 14:05 IST` — for anything that spans more than one day."""
    d = to_ist(ts) or now()
    return d.strftime("%d %b %H:%M IST")


def trading_day(ts: Any = None) -> str:
    """The IST calendar date, `YYYY-MM-DD`.

    Every per-day bucket in the system keys on this. Deriving it in UTC would
    roll the date at 05:30 IST and split a session in half.
    """
    d = to_ist(ts) or now()
    return d.date().isoformat()


def epoch(ts: Any = None) -> float:
    d = to_ist(ts) or now()
    return d.timestamp()


def session_bounds(day: Any = None):
    """`(open, close)` as IST datetimes for the given day (default today)."""
    d = to_ist(day) or now()
    o = d.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0,
                  microsecond=0)
    c = d.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0,
                  microsecond=0)
    return o, c


def is_today(ts: Any) -> bool:
    d = to_ist(ts)
    return bool(d and d.date() == now().date())


def minutes_since(ts: Any) -> Optional[float]:
    d = to_ist(ts)
    return None if d is None else round((now() - d).total_seconds() / 60.0, 1)


def today_slice(df, column: Optional[str] = None):
    """A candle frame narrowed to **today's IST session**.

    The API is asked for a `days_back` window, not a session count, so every
    frame arrives carrying part of the previous day. Charting that makes the
    live session a sliver at the right edge; computing a day range over it is
    simply wrong — it would report a two-day range as today's.

    Returns the frame unchanged when no date column can be found, since a
    silently empty chart is worse than one showing too much.

    When today has no rows at all — pre-open, a holiday, a stale cache — this
    falls back to **the most recent session present**, not to the whole window.
    Falling back to the whole frame is what made the terminal draw three days of
    candles: at 09:00, or on a Saturday, `now().date()` matched nothing and every
    caller silently got the full `days_back` window back. Handing back one real
    session satisfies the same "never blank" intent without lying about the
    range, which matters most for the callers that compute a day range off this
    — a three-day high/low reported as today's is the error this function exists
    to prevent.
    """
    if df is None or getattr(df, "empty", True):
        return df
    col = column
    if col is None:
        lower = {str(c).lower(): c for c in getattr(df, "columns", [])}
        for name in ("datetime", "timestamp", "time", "date"):
            if name in lower:
                col = lower[name]
                break
    today = now().date()
    try:
        if col is None:
            idx = getattr(df, "index", None)
            dates = getattr(idx, "date", None)
            if dates is None:
                return df
            dates = list(dates)
            out = df[[d == today for d in dates]]
            if getattr(out, "empty", True) and dates:
                last = max(dates)
                out = df[[d == last for d in dates]]
        else:
            series = df[col]
            dt = getattr(series, "dt", None)
            if dt is None:
                return df
            day = dt.date
            out = df[day == today]
            if getattr(out, "empty", True):
                out = df[day == day.iloc[-1]]
    except Exception:
        return df
    # Still nothing (a frame of NaT, say) — whole is better than blank.
    return out if not getattr(out, "empty", True) else df
