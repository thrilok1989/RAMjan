"""Storing and reading the day's futures OI anchor.

The I/O half of `mios_v5/futures_oi.py`, kept out of `mios_v5` because a
database client inside that package is a named forbidden failure mode. Same
three-piece split as the Stage 74 telemetry: pure contract · injected store ·
migration.

## One write and one read per day

The anchor is written **once**, when the day's first futures quote arrives, and
never rewritten — a baseline that moves is not a baseline. It is read once and
cached by the caller for the rest of the session.

That restraint is the point. The terminal reruns every ~20 seconds; a store
that wrote per cycle would add ~1,100 writes a day for a value that changes
once, and unbounded per-cycle writes are what took Supabase egress to
0.59 GB/day before the retention and batching work.

## A missing table is reported, never swallowed

`ensure()` returns a status string rather than raising or passing silently. The
migration is applied by a human, and a store that fails quietly leaves Short
Covering and Long Unwinding reporting `UNKNOWN` for a week with nothing to say
why — which is exactly how the Stage 74 telemetry gap nearly went unnoticed.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

TABLE = "futures_oi_baseline"

#: Reported by `ensure()`. `MISSING_TABLE` means the migration has not been
#: applied; everything downstream reports UNKNOWN until it is.
OK, MISSING_TABLE, NO_DB, FAILED = "OK", "MISSING_TABLE", "NO_DB", "FAILED"


def _client(db):
    """The PostgREST client, or `None`. Never raises — a store that takes the
    app down is worse than one that reports nothing."""
    if db is None:
        return None
    return getattr(db, "client", None)


def get_baseline(db, trading_day: Any,
                 symbol: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Today's stored anchor, or `None` when there is not one yet.

    `symbol` narrows to a contract. On rollover day the near-month symbol
    changes, and the previous contract's anchor must not answer for the new
    one — `futures_oi.read()` refuses that comparison, and this filter means it
    usually never has to.
    """
    client = _client(db)
    if client is None or not trading_day:
        return None
    try:
        q = (client.table(TABLE).select("*")
             .eq("trading_day", str(trading_day)))
        if symbol:
            q = q.eq("symbol", str(symbol))
        res = q.order("first_seen_at", desc=False).limit(1).execute()
        rows = getattr(res, "data", None) or []
        return dict(rows[0]) if rows else None
    except Exception:
        return None


def put_baseline(db, row: Optional[Mapping[str, Any]]) -> str:
    """Store the anchor if today has none. Returns a status.

    Uses `on_conflict` so a second writer — a reload racing the first cycle —
    cannot overwrite an anchor that is already set. **`ignore_duplicates` is
    the whole contract here**: an upsert that replaced the row would move the
    baseline every cycle and silently turn the day's OI change into the last
    twenty seconds' change, which is the bug this module exists to fix.
    """
    client = _client(db)
    if client is None:
        return NO_DB
    if not row:
        return FAILED
    try:
        (client.table(TABLE)
         .upsert(dict(row), on_conflict="trading_day,symbol",
                 ignore_duplicates=True, returning="minimal")
         .execute())
        return OK
    except Exception as err:
        text = str(err).lower()
        if "does not exist" in text or "could not find" in text or \
                "pgrst205" in text:
            return MISSING_TABLE
        return FAILED


def ensure(db, quote: Optional[Mapping[str, Any]], trading_day: Any,
           cached: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Read today's anchor, creating it from `quote` if there is none.

    Returns `{"baseline", "status", "created"}`. `cached` short-circuits the
    read: the caller holds the anchor for the session, so this costs one round
    trip per day rather than one per rerun.
    """
    from mios_v5.futures_oi import anchor_from

    symbol = (quote or {}).get("symbol")
    if cached and str(cached.get("trading_day") or "") == str(trading_day) \
            and (not symbol or str(cached.get("symbol")) == str(symbol)):
        return {"baseline": dict(cached), "status": OK, "created": False}

    existing = get_baseline(db, trading_day, symbol)
    if existing:
        return {"baseline": existing, "status": OK, "created": False}

    row = anchor_from(quote, trading_day)
    if row is None:
        # No OI in the quote — not an anchor. Storing it would fix open_oi at
        # zero for the whole day.
        return {"baseline": None, "status": OK, "created": False}

    status = put_baseline(db, row)
    return {"baseline": (row if status == OK else None),
            "status": status, "created": status == OK}
