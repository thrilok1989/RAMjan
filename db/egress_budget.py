"""A day-scoped egress ledger with a byte budget. **On by default.**

## Why this exists rather than another query fix

Round 3 removed a five-minute refetch treadmill and turned 78 fetches a day
into one per app lifetime. The mechanism was certain, the round-trip counts were
proven — and the bill did not visibly move. Its own §6 says why:

    > These are counted round-trips, not measured bytes. … If the bill is still
    > high after this, that breakdown is the next place to look, not another
    > query.

`tools/egress_meter.py` measures bytes exactly, but it answers **what did this
one rerun cost**, resets every cycle, and is off unless `MIOS_EGRESS=1`. The
question a 1 GB day actually poses is *what did today cost, and which table
spent it* — and nobody could answer that from a caption that resets every
twenty seconds.

So this is the other instrument: coarse, cumulative, always on, and pointed at
one number.

## The budget

`BUDGET_BYTES` is 100 MB/day. It is a **target, not a limit** — nothing here
throttles, blocks or degrades a read. Exceeding it changes a caption from green
to red, and that is deliberate: an instrument that starts refusing reads to
protect a number would be a worse failure than the bill it was fixing.

## ⚠️ Sampled width, not measured bytes

Measuring exactly means `json.dumps(response.data)` on every response, and on
an 8,000-row read that is real CPU inside a 20-second refresh loop. Paying it
1,100 times a day to observe a cost problem is its own cost problem.

Instead: `len(rows)` is free, so every call records its row count, and the
serialised width of one row is sampled **once per (table, op) per day**. Bytes
are then `rows × sampled_width`.

What that is good for: ranking tables, tracking a day total, and answering
"did the change help?" as a before/after ratio. What it is not: an invoice
figure. Two things move it and are not modelled —

* **gzip.** Supabase compresses responses, and repetitive JSON compresses hard,
  so real egress is materially *below* this figure.
* **row-shape variance.** A table whose JSONB blob varies per row is sampled
  from whichever row came first.

Both are stated rather than corrected, because a number presented as exact
would get reconciled against the invoice and quietly discredit the ranking,
which is the part that is trustworthy.

## What it cannot see

The same two blind spots every round has carried, and neither is reachable from
inside this process:

* egress that is not Database — Storage, Realtime, Auth, Edge Functions
* traffic from another process (`ws_worker.py`, `discord_bot.py`)

And one of its own: the ledger lives in this process, so **an app restart
resets it.** The panel reports how long it has been measuring for exactly that
reason — a 20 MB reading over eleven minutes is not a 20 MB day.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

#: The target, in bytes. 100 MB/day.
BUDGET_BYTES = 100 * 1024 * 1024

#: The refresh window `vob_minimal.py` gates `st_autorefresh` to — 08:30 to
#: 15:45 IST. Used only to project a partial day to a full one, so the
#: projection answers "at this rate, what will today cost?"
SESSION_SECONDS = int((15.75 - 8.5) * 3600)

#: (table, op) → {calls, rows, bytes, width, sampled}
_LEDGER: Dict[Tuple[str, str], Dict[str, float]] = {}

#: The trading day the ledger covers, and when it started measuring.
_DAY: Optional[str] = None
_STARTED: float = 0.0

_installed = False


def _today() -> str:
    """The IST trading day. Imported lazily so this module stays importable
    without pytz in a bare test environment."""
    try:
        import pytz
        from datetime import datetime
        return datetime.now(pytz.timezone("Asia/Kolkata")).date().isoformat()
    except Exception:
        from datetime import date
        return date.today().isoformat()


def _roll(day: Optional[str] = None) -> None:
    """Start a fresh ledger when the trading day turns over."""
    global _DAY, _STARTED
    day = day or _today()
    if _DAY != day:
        _LEDGER.clear()
        _DAY = day
        _STARTED = time.time()


def _row_width(data: Any) -> int:
    """Serialised bytes of ONE row. The only `json.dumps` this module runs, and
    only on the first call for a (table, op) each day."""
    try:
        one = data[0] if isinstance(data, list) and data else data
        return len(json.dumps(one, default=str, separators=(",", ":")))
    except Exception:
        return 0


def _rows_of(data: Any) -> int:
    if data is None:
        return 0
    if isinstance(data, list):
        return len(data)
    return 1


def note(table: str, op: str, data: Any) -> None:
    """Record one response. Cheap: a `len()`, and a width sample once per day.

    Never raises. An instrument that can take the app down is worse than no
    instrument — the same rule `tools/egress_meter.py` follows.
    """
    try:
        _roll()
        key = (str(table or "?"), str(op or "?"))
        slot = _LEDGER.setdefault(
            key, {"calls": 0, "rows": 0, "bytes": 0, "width": 0, "sampled": 0})
        rows = _rows_of(data)
        slot["calls"] += 1
        slot["rows"] += rows
        if not slot["sampled"] and rows:
            slot["width"] = _row_width(data)
            slot["sampled"] = 1
        slot["bytes"] += rows * slot["width"]
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
#  installation
# ══════════════════════════════════════════════════════════════════════

def install(client: Any) -> bool:
    """Wrap `execute()` on the PostgREST builder classes this client uses.

    Patched on the CLASS and once per process, for the reason
    `tools/egress_meter.py` documents: PostgREST returns a **new** builder from
    every chained call, so wrapping the object `table()` hands out would
    instrument a builder that is discarded before anything executes.

    Returns False when it could not install, so a caller can say so rather than
    reporting a confident zero.
    """
    global _installed
    if _installed or client is None:
        return False
    try:
        probe = client.table("_egress_budget_probe_")
    except Exception:
        return False
    seen = set()
    for build in (lambda b: b, lambda b: b.select("*"), lambda b: b.insert({}),
                  lambda b: b.upsert({}), lambda b: b.delete()):
        try:
            cls = type(build(probe))
        except Exception:
            continue
        if cls in seen or not hasattr(cls, "execute"):
            continue
        seen.add(cls)
        _patch(cls)
    _installed = bool(seen)
    if _installed:
        _roll()
    return _installed


def _table_of(builder: Any) -> str:
    cfg = getattr(builder, "request", None) or builder
    got = getattr(cfg, "path", None) or getattr(builder, "url", None)
    if not got:
        return "?"
    return str(got).split("?")[0].rstrip("/").rsplit("/", 1)[-1] or "?"


def _op_of(builder: Any) -> str:
    """Which verb is about to run. `insert` and `upsert` are both POST and are
    told apart only by the `prefer` header, exactly as in the meter."""
    cfg = getattr(builder, "request", None) or builder
    raw = None
    for attr in ("http_method", "method", "_method"):
        raw = getattr(cfg, attr, None)
        if raw:
            break
    if not raw:
        return "?"
    name = str(getattr(raw, "value", raw)).upper()
    if name == "POST":
        try:
            prefer = str((getattr(cfg, "headers", None) or {}).get(
                "prefer", "")).lower()
        except Exception:
            prefer = ""
        return "upsert" if "merge-duplicates" in prefer else "insert"
    return {"GET": "select", "PATCH": "update", "DELETE": "delete",
            "HEAD": "count"}.get(name, name.lower())


def _patch(cls: Any) -> None:
    original = cls.execute
    if getattr(original, "_egress_budget_wrapped", False):
        return

    def execute(self, *args, **kwargs):
        # Read the request BEFORE executing — some builders reset their config
        # once the call has gone out, and attributing to "?" is worse than the
        # microsecond this costs.
        try:
            table, op = _table_of(self), _op_of(self)
        except Exception:
            table, op = "?", "?"
        res = original(self, *args, **kwargs)
        note(table, op, getattr(res, "data", None))
        return res

    execute._egress_budget_wrapped = True       # type: ignore[attr-defined]
    cls.execute = execute


# ══════════════════════════════════════════════════════════════════════
#  reporting
# ══════════════════════════════════════════════════════════════════════

def report() -> Dict[str, Any]:
    """The day so far, biggest table first, with a projection to a full day."""
    rows: List[Dict[str, Any]] = []
    total = 0
    for (table, op), slot in _LEDGER.items():
        total += slot["bytes"]
        rows.append({"table": table, "op": op, "calls": int(slot["calls"]),
                     "rows": int(slot["rows"]), "bytes": int(slot["bytes"]),
                     "width": int(slot["width"])})
    rows.sort(key=lambda r: -r["bytes"])
    elapsed = max(1.0, time.time() - _STARTED) if _STARTED else 1.0
    # Projected only while the sample is long enough to mean anything. Scaling
    # eleven seconds up to seven hours produces a confident fiction.
    projected = (int(total / elapsed * SESSION_SECONDS)
                 if elapsed >= 300 else None)
    return {
        "day": _DAY, "installed": _installed,
        "total_bytes": int(total),
        "calls": sum(r["calls"] for r in rows),
        "elapsed_s": int(elapsed),
        "projected_day_bytes": projected,
        "budget_bytes": BUDGET_BYTES,
        "over_budget": bool(projected and projected > BUDGET_BYTES),
        "pct_of_budget": round(total / BUDGET_BYTES * 100, 1),
        "by_table": rows,
    }


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def reset() -> None:
    """Start the measurement window again — the panel's button.

    Useful for a before/after: reset, let a few minutes run, compare. Does not
    uninstall the instrument.
    """
    global _STARTED
    _LEDGER.clear()
    _STARTED = time.time()


def render(st, db=None) -> None:
    """The sidebar panel. Says what today cost, and whether that is on track.

    Draws even when nothing has been measured, because a silent panel and a
    panel reporting zero are indistinguishable — and this repo has been bitten
    by that three times. Never raises.
    """
    try:
        data = report()
        with st.sidebar.expander("📉 Supabase egress today", expanded=False):
            if not data["installed"]:
                st.caption(
                    "⚪ Not measuring — the PostgREST client could not be "
                    "instrumented. Nothing below would be a real zero.")
                return
            mins = data["elapsed_s"] // 60
            st.caption(
                f"**{human(data['total_bytes'])}** over {data['calls']:,} calls "
                f"· measured for {mins} min "
                f"({data['pct_of_budget']:.1f}% of the {human(BUDGET_BYTES)} "
                f"budget)")

            projected = data["projected_day_bytes"]
            if projected is None:
                st.caption(
                    "Projection needs 5 minutes of measurement — too short a "
                    "window scaled to a full day is a guess with a decimal "
                    "point.")
            elif data["over_budget"]:
                st.caption(
                    f"🔴 At this rate: **{human(projected)}/day** — over the "
                    f"{human(BUDGET_BYTES)} target. The table at the top of the "
                    f"list below is where to look first.")
            else:
                st.caption(
                    f"🟢 At this rate: **{human(projected)}/day** — inside the "
                    f"{human(BUDGET_BYTES)} target.")

            for r in data["by_table"][:8]:
                st.caption(
                    f"`{r['table']}.{r['op']}` — {human(r['bytes'])} · "
                    f"{r['calls']:,} calls · {r['rows']:,} rows "
                    f"(~{r['width']:,} B/row)")

            st.caption(
                "Sampled row width × row count, **pre-gzip** — a ranking and a "
                "before/after ratio, not an invoice figure. Resets when this "
                "app restarts, so a short window is not a day. Database reads "
                "and writes only: Storage, Realtime and other processes are "
                "not visible from here.")
            if st.button("Restart measurement", key="_egress_budget_reset"):
                reset()
    except Exception:
        pass
