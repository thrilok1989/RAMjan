"""Data retention — the policies the migrations declared, finally executed.

Every `sql/*.sql` migration that creates a growing table ends the same way:

```sql
-- optional purge (keep ~30 days)
-- DELETE FROM engine_errors WHERE trading_day < CURRENT_DATE - INTERVAL '30 days';
```

Ten tables carry a policy like that. **All ten are commented out**, and
`SupabaseDB.delete_rows` — written for exactly this — has never had a caller. So
nothing has ever purged anything, and every table has been growing since the day
it was created.

This module executes those policies. It does not invent them: where a migration
declared a retention period, that number is used verbatim and `Policy.source`
names the file it came from. The tables with no declared policy get one here,
and those are marked `source="this module"` so the distinction stays visible.

## Deleting is not cacheable, reversible, or undoable ⚠️ BINDING

`ENABLED = False`, and a human flips it — the same promotion gate
`advisory_only` uses everywhere else in this codebase.

Until then `preview()` is fully functional and `run()` refuses. That is not
timidity: the first purge on a two-year-old table removes rows nobody has looked
at in months, and *"how many would go?"* has a right answer that costs nothing
to ask. A trader should see the number before the rows stop existing.

`PROTECTED` names the tables no policy may ever touch, enabled or not.
`my_analysis` is the clearest case — a trader's own written notes, which no
retention window has any business expiring.

## How a purge runs

Forward from the oldest row, in bounded windows, oldest first:

* one `DELETE` across two years of a busy table is how a statement timeout
  happens, and a timeout leaves the table exactly as big as it was
* windowed, a timeout costs one window; the next run resumes from the new
  oldest row
* oldest-first means an interrupted purge still shrinks the table

Every run appends to `retention_log` — table, policy, cutoff, rows before,
rows removed, and whether it was a preview. A deletion with no record of what
it deleted is indistinguishable from data loss.

## This module is the preview; `pg_cron` is the job

`sql/034_retention_cron.sql` carries the same policies into the database, where
a scheduled purge runs without the app being open and deletes next to the rows
rather than over HTTP. **The seed there is generated from `POLICIES` below**,
and a test asserts the two match exactly — so change a window here and
regenerate; hand-editing the SQL fails the build.

Once cron is scheduled, `ENABLED` stays `False` and this module's job is the
preview panel. See `docs/AUDIT_SUPABASE_STORAGE.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

#: ⚠️ Flip this to let `run()` delete. Nothing else in this module needs
#: changing, and `preview()` works either way.
#:
#: Before flipping it: run a preview, read the `rows_over` column, and satisfy
#: yourself that every number is one you are willing to lose. There is no undo.
#:
#: **Leave it False if you have scheduled the `pg_cron` job** in
#: `sql/034_retention_cron.sql`. That is the better home for this work — it runs
#: whether or not anyone has the dashboard open, and it deletes next to the rows
#: instead of over HTTP. Two schedulers purging the same tables is not twice as
#: safe; it is two processes racing on the same rows. The preview below keeps
#: working either way.
ENABLED = False

#: Rows are removed in windows this wide, oldest first.
WINDOW_DAYS = 30

#: A purge stops after this many windows in one run, so a first purge on a
#: years-old table cannot hold a page open indefinitely. The next run resumes.
MAX_WINDOWS = 24

#: Tables no policy may touch, whatever `ENABLED` says.
#:
#: Two kinds: things a human wrote (`my_analysis`), and bounded state tables
#: that do not grow at all because every write is an upsert on a fixed key
#: (`dhan_ticks` has one row per subscribed instrument, `trade_config` has one
#: row, full stop). Purging by age would delete live state, not history.
PROTECTED: frozenset = frozenset({
    "my_analysis",
    "trade_config", "user_preferences", "vob_app_state",
    "backfill_progress", "story_stats", "dhan_ticks",
})


@dataclass(frozen=True)
class Policy:
    """One table's retention window, and where the number came from."""
    table: str
    keep_days: int
    day_col: str
    source: str
    why: str = ""

    @property
    def declared(self) -> bool:
        """Did a migration specify this, or did this module choose it?"""
        return self.source.startswith("sql/")


def _p(table, keep, col, source, why=""):
    return Policy(table, keep, col, source, why)


#: ── Declared by a migration. The number is theirs; this executes it. ──
_DECLARED: Tuple[Policy, ...] = (
    _p("telegram_sent_log", 1, "sent_at", "sql/003_telegram_cooldown.sql",
       "a send cooldown is meaningless once the cooldown has passed"),
    _p("alert_log", 14, "trading_day", "sql/005_alert_log.sql"),
    _p("engine_errors", 30, "trading_day", "sql/009_engine_errors.sql"),
    _p("leg_entry_signals", 30, "trading_day", "sql/004_leg_entry_signals.sql"),
    _p("leg_flow_snapshots", 60, "trading_day", "sql/006_leg_flow_snapshots.sql"),
    _p("signal_outcomes", 365, "trading_day", "sql/008_signal_outcomes.sql"),
    _p("bias_predictions", 365, "trading_day", "sql/011_bias_predictions.sql"),
    _p("entry_gate_signals", 365, "trading_day", "sql/012_entry_gate_signals.sql"),
    _p("iv_history", 730, "trading_day", "sql/007_iv_history.sql"),
    _p("engine_state", 730, "trading_day", "sql/018_engine_state.sql"),
)

#: ── No migration declared one. These numbers are this module's, and the
#: reasoning for each is stated rather than assumed. ──
_CHOSEN: Tuple[Policy, ...] = (
    # The per-tick and per-cycle market microstructure. The highest-volume
    # tables in the schema and the least useful after the day they describe —
    # every read of them is same-day or same-week.
    _p("option_chain_data", 30, "trading_day", "this module",
       "a chain snapshot is a same-day artefact"),
    _p("orderbook_data", 30, "trading_day", "this module"),
    _p("bid_ask_history", 30, "trading_day", "this module"),
    _p("volume_delta_history", 30, "trading_day", "this module"),
    _p("detected_patterns", 30, "trading_day", "this module"),
    _p("pcr_history", 90, "trading_day", "this module"),
    _p("gex_history", 90, "trading_day", "this module"),
    _p("max_pain_history", 90, "trading_day", "this module"),
    _p("atm_strike_data", 90, "trading_day", "this module"),
    _p("nifty_spot_data", 90, "trading_day", "this module",
       "the day-open print is read same-day; history comes from candles"),
    _p("oc_signal_history", 90, "trading_day", "this module"),
    _p("alerts_history", 90, "trading_day", "this module"),
    _p("master_signals", 90, "trading_day", "this module"),
    _p("dhan_sweeps", 30, "created_at", "this module"),

    # Candles. Deliberately long: `compute_prev_day_value` reads yesterday's
    # bars, the backfill walks the whole collected range, and market memory is
    # built from it. `clear_old_candles(days_old=7)` exists in the client and
    # has never been called — seven days would break the backfill, which is
    # very likely why nobody ever called it.
    _p("candles_data", 400, "trading_day", "this module",
       "the backfill and market memory read the full collected range"),

    # The learning corpus. These ARE the measurement — Stages 55-60 grade the
    # system on them — so they are kept longest of anything.
    _p("engine_attribution", 730, "trading_day", "this module"),
    _p("trade_attribution", 730, "trading_day", "this module"),
    _p("trade_events", 730, "trading_day", "this module"),
    _p("trade_results", 730, "trading_day", "this module"),
    _p("learning_snapshots", 730, "trading_day", "this module"),
    _p("session_log", 730, "trading_day", "this module"),
    _p("session_recommendations", 730, "trading_day", "this module"),
    _p("session_validation_log", 730, "trading_day", "this module"),
    _p("day_type_log", 730, "trading_day", "this module"),

    # Decisions and their audit trail.
    _p("mios_decisions", 365, "trading_day", "this module"),
    _p("trade_signals", 365, "trading_day", "this module"),
    _p("dispatch_history", 365, "created_at", "this module",
       "the duplicate-suppression index only looks at recent hashes"),
    _p("auto_trades", 365, "trading_day", "this module"),
    _p("market_events", 365, "created_at", "this module"),
    _p("market_stories", 365, "created_at", "this module"),
    _p("story_validations", 365, "created_at", "this module"),
    _p("event_impact_log", 365, "trading_day", "this module"),
    _p("opening_auction_log", 365, "trading_day", "this module"),

    # Stage 74 calibration evidence, sampled once a minute. Long enough to
    # compare this quarter's calibration against last quarter's, short enough
    # that a per-minute sample never becomes the storage problem every other
    # table in this schema became.
    _p("liquidity_telemetry", 180, "trading_day", "this module",
       "calibration evidence — kept across quarters, not forever"),
    # One row per trading day per futures contract. A year is nothing in
    # storage terms and lets this expiry cycle be compared with the last.
    _p("futures_oi_baseline", 365, "trading_day", "this module",
       "the day's futures OI anchor — one row per day"),
)

POLICIES: Dict[str, Policy] = {
    p.table: p for p in _DECLARED + _CHOSEN if p.table not in PROTECTED
}

#: Where a run records what it did.
LOG_TABLE = "retention_log"

#: Session key for "already run today", so a 20-second rerun loop cannot
#: re-issue a purge 180 times an hour.
_LAST_RUN_KEY = "_retention_last_run"


def _today() -> str:
    return date.today().isoformat()


def _session() -> Any:
    try:
        import streamlit as st
        return st.session_state
    except Exception:
        return None


def policies() -> Tuple[Policy, ...]:
    """Every policy, longest-retained first — so the shortest windows, which
    delete the most, are the ones a reader ends on."""
    return tuple(sorted(POLICIES.values(),
                        key=lambda p: (-p.keep_days, p.table)))


def undeclared() -> Tuple[str, ...]:
    """Tables whose retention this module chose rather than read from a
    migration. Surfaced so those numbers stay arguable."""
    return tuple(sorted(p.table for p in POLICIES.values() if not p.declared))


# ══════════════════════════════════════════════════════════════════════
#  preview — always available, never deletes
# ══════════════════════════════════════════════════════════════════════

def preview(db: Any, tables: Optional[Tuple[str, ...]] = None) -> List[Dict[str, Any]]:
    """How many rows each policy would remove, right now.

    Never deletes, and works whether or not `ENABLED` is set — the number has a
    right answer and asking for it costs nothing.

    `rows_over = None` means the count could not be read (a table that does not
    exist yet, a permissions error). That is reported as `UNKNOWN`, not as zero:
    "I could not tell" and "nothing to remove" must not render the same.
    """
    out: List[Dict[str, Any]] = []
    for p in policies():
        if tables and p.table not in tables:
            continue
        cutoff = _cutoff(db, p)
        rows = None
        try:
            rows = db.count_rows_older_than(p.table, p.keep_days, p.day_col)
        except Exception:
            rows = None
        out.append({
            "table": p.table, "keep_days": p.keep_days, "day_col": p.day_col,
            "cutoff": cutoff, "rows_over": rows,
            "source": p.source, "declared": p.declared, "why": p.why,
            "known": rows is not None,
        })
    return out


def _cutoff(db: Any, policy: Policy) -> Optional[str]:
    try:
        return db.cutoff_day(policy.keep_days)
    except Exception:
        return (date.today() - timedelta(days=policy.keep_days)).isoformat()


def total_over_retention(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Sum of a preview, with the unknowns counted separately rather than as
    zero — a summary that hides how much it could not see is worse than none."""
    known = [r for r in rows if r["known"]]
    return {
        "tables": len(rows),
        "tables_counted": len(known),
        "tables_unknown": len(rows) - len(known),
        "rows_over": sum(int(r["rows_over"] or 0) for r in known),
        "tables_over": sum(1 for r in known if (r["rows_over"] or 0) > 0),
    }


# ══════════════════════════════════════════════════════════════════════
#  run — refuses unless a human enabled it
# ══════════════════════════════════════════════════════════════════════

def run(db: Any, tables: Optional[Tuple[str, ...]] = None,
        confirm: bool = False, enabled: Optional[bool] = None,
        log: bool = True) -> Dict[str, Any]:
    """Execute the policies. **Deletes rows. There is no undo.**

    Two independent gates, and both must be open:

    * `ENABLED` — the module constant a human edits, once, deliberately
    * `confirm=True` — the caller saying *this call, now*

    One gate would be enough to be safe and not enough to be obvious. A
    constant alone lets an unrelated call site delete years of history the day
    somebody flips it; a parameter alone means one typo at a call site is the
    only thing between a preview and a purge.

    Returns a report whether or not it ran, and `blocked` says which gate
    stopped it. It never raises: a retention pass that takes the app down has
    done more damage than the rows it was going to remove.
    """
    on = ENABLED if enabled is None else bool(enabled)
    report: Dict[str, Any] = {
        "ran": False, "at": datetime.now().isoformat(timespec="seconds"),
        "enabled": on, "confirmed": bool(confirm),
        "tables": [], "rows_removed": 0, "blocked": None,
    }

    if not on:
        report["blocked"] = ("retention is not enabled — set ENABLED = True in "
                             "db/retention.py after reading a preview")
        return report
    if not confirm:
        report["blocked"] = "run(confirm=True) is required to delete"
        return report

    report["ran"] = True
    for p in policies():
        if tables and p.table not in tables:
            continue
        report["tables"].append(_purge(db, p, log=log))
    report["rows_removed"] = sum(int(t.get("removed") or 0)
                                 for t in report["tables"])
    _mark_run()
    return report


def _purge(db: Any, policy: Policy, log: bool = True) -> Dict[str, Any]:
    """One table, oldest first, in bounded windows."""
    result: Dict[str, Any] = {
        "table": policy.table, "keep_days": policy.keep_days,
        "cutoff": _cutoff(db, policy), "before": None, "removed": 0,
        "windows": 0, "complete": True, "error": None,
    }
    try:
        before = db.count_rows_older_than(policy.table, policy.keep_days,
                                          policy.day_col)
    except Exception as err:
        result["error"] = f"count failed: {err}"
        return result

    result["before"] = before
    if not before:
        # None (unreadable) or 0 (nothing over) — neither is a purge, and the
        # difference is already recorded in `before`.
        result["complete"] = before is not None
        return result

    cutoff = result["cutoff"]
    try:
        oldest = db.oldest_day(policy.table, policy.day_col)
    except Exception:
        oldest = None
    lo = _as_date(oldest) or (_as_date(cutoff) - timedelta(days=365 * 20))

    end = _as_date(cutoff)
    windows = 0
    while lo < end and windows < MAX_WINDOWS:
        hi = min(lo + timedelta(days=WINDOW_DAYS), end)
        ok = False
        try:
            ok = db.purge_window(policy.table, policy.day_col,
                                 lo.isoformat(), hi.isoformat())
        except Exception as err:
            result["error"] = str(err)
        if not ok:
            result["complete"] = False
            result["error"] = result["error"] or "purge window failed"
            break
        windows += 1
        lo = hi

    result["windows"] = windows
    if lo < end and result["error"] is None:
        # Ran out of windows rather than out of rows — the next run resumes.
        result["complete"] = False

    try:
        after = db.count_rows_older_than(policy.table, policy.keep_days,
                                         policy.day_col)
        if after is not None and before is not None:
            result["removed"] = max(0, before - after)
        result["after"] = after
    except Exception:
        result["after"] = None

    if log:
        _log(db, policy, result)
    return result


def _as_date(value: Any) -> Optional[date]:
    """A date from whatever the column held — `trading_day` is a DATE, but
    `created_at` and `sent_at` are timestamps, and both arrive as strings."""
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


# ══════════════════════════════════════════════════════════════════════
#  the audit trail
# ══════════════════════════════════════════════════════════════════════

def _log(db: Any, policy: Policy, result: Dict[str, Any]) -> None:
    """Append what happened. Best effort — a failed log must not fail a purge,
    but a purge with no log is why this is attempted at all."""
    row = {
        "ts": datetime.now().isoformat(),
        "table_name": policy.table,
        "keep_days": policy.keep_days,
        "day_col": policy.day_col,
        "cutoff": result.get("cutoff"),
        "rows_before": result.get("before"),
        "rows_removed": result.get("removed"),
        "windows": result.get("windows"),
        "complete": result.get("complete"),
        "policy_source": policy.source,
        "error": result.get("error"),
    }
    try:
        db._safe_upsert(LOG_TABLE, [row], "ts,table_name")
    except Exception:
        pass


def history(db: Any, limit: int = 200) -> List[Dict[str, Any]]:
    """Past runs, newest first. Empty when the log table does not exist yet."""
    try:
        res = (db.client.table(LOG_TABLE).select("*")
               .order("ts", desc=True).limit(limit).execute())
        return list(res.data or [])
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════
#  scheduling
# ══════════════════════════════════════════════════════════════════════

def due(session: Any = None) -> bool:
    """Has today's pass already run in this session?

    The app reruns every 20 seconds. Without this a scheduled purge would fire
    180 times an hour, and each one would issue the same twenty-odd counts.
    """
    state = session if session is not None else _session()
    if state is None:
        return True
    try:
        return state.get(_LAST_RUN_KEY) != _today()
    except Exception:
        return True


def _mark_run(session: Any = None) -> None:
    state = session if session is not None else _session()
    if state is None:
        return
    try:
        state[_LAST_RUN_KEY] = _today()
    except Exception:
        pass


def run_daily(db: Any, confirm: bool = True) -> Optional[Dict[str, Any]]:
    """The scheduled entry point: run once per day, or not at all.

    Still gated on `ENABLED`. Returns `None` when today's pass has already
    happened, so a caller can tell "not due" from "ran and removed nothing".
    """
    if db is None or not ENABLED:
        return None
    if not due():
        return None
    return run(db, confirm=confirm)
