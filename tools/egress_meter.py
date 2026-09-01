"""Measure Supabase response bytes before narrowing another query.

`docs/AUDIT_EGRESS_2.md` fixed the writes on a proven mechanism — PostgREST
echoes every written row and nothing read the echo — but it sized the saving
from **row shapes, not measurement**, and said so. It also left the largest
remaining item alone on purpose:

> 54 of 69 selects are `select('*')` … narrowing a column list is a per-call-site
> decision: each one needs its consumers checked, and getting it wrong renders a
> blank field rather than a slow one.

This is the instrument that turns that from a guess into a ranked list. Measure,
identify the top consumer, reduce it, verify — one query at a time.

## Usage

```bash
MIOS_EGRESS=1 streamlit run vob_minimal.py
```

**Off by default.** Without the variable this module installs nothing and costs
one `os.environ.get` at import. One caption line is drawn at the bottom of the
page and the full report is written to `egress_report.json` every rerun, so the
numbers can be read from a file without watching the screen.

## What it measures

Every `.execute()` on the PostgREST client, attributed to **table** and
**operation**, recording calls and the serialised size of `response.data`.
Reads and writes both — so a write that still echoes shows up next to the reads
it is competing with.

## ⚠️ What the number is, and is not

It is `len(json.dumps(response.data))`: the size of the parsed payload.

That is **not** the billed wire size. It excludes HTTP headers, and it ignores
gzip — Supabase compresses responses, so real egress on a repetitive JSON body
is materially smaller than this figure. Treat it as a **ranking signal and a
before/after ratio**, not as an absolute to reconcile against the invoice.

The ratio is the useful part: if `save_option_chain` measures 40× what
`get_session_log` measures, that ordering survives compression, and it is the
ordering that decides what to fix next.

Two things it cannot see, both recorded in the audit as needing Supabase's own
dashboard instead:

* egress that is not Database — Storage, Realtime, Auth, Edge Functions
* traffic from processes that are not this one, notably `ws_worker.py`
"""

from __future__ import annotations

import json
import os
import pathlib
import time
from typing import Any, Dict, List

ENABLED = os.environ.get("MIOS_EGRESS", "").strip() in ("1", "true", "yes")

REPORT_PATH = pathlib.Path("egress_report.json")

#: table → {op: {calls, bytes, rows}} for the current rerun.
_STATS: Dict[str, Dict[str, Dict[str, float]]] = {}

_installed = False


def _size(data: Any) -> int:
    """Serialised size of a response payload. Never raises — a meter that can
    take the app down is worse than no meter."""
    if data is None:
        return 0
    try:
        return len(json.dumps(data, default=str, separators=(",", ":")))
    except Exception:
        try:
            return len(str(data))
        except Exception:
            return 0


def record(table: str, op: str, data: Any, echoing: bool = False) -> None:
    """Attribute one response. Public so a test can drive it without PostgREST.

    `echoing` marks a write that asked PostgREST to return the row. Counted
    separately because it is the one number that says whether the fix in
    `docs/AUDIT_EGRESS_2.md` is actually live in the running process, rather
    than merely present in the source.
    """
    slot = _STATS.setdefault(str(table or "?"), {}).setdefault(
        str(op or "?"), {"calls": 0, "bytes": 0, "rows": 0, "echoing": 0})
    slot["calls"] += 1
    slot["bytes"] += _size(data)
    if echoing:
        slot["echoing"] = slot.get("echoing", 0) + 1
    try:
        slot["rows"] += len(data) if isinstance(data, list) else (1 if data else 0)
    except Exception:
        pass


def _cfg(builder: Any) -> Any:
    """Where the composed request lives.

    postgrest 2.x hangs it off `builder.request` (a `RequestConfig`); older
    builds put the same fields directly on the builder. Both are checked, so
    the meter keeps working across the `supabase>=1.0.3,<3.0.0` range the app
    is pinned to rather than silently reporting `?` on half of it.
    """
    return getattr(builder, "request", None) or builder


def _op_of(builder: Any) -> str:
    """Which verb this builder is about to run.

    Read from the composed request, never guessed from the class name —
    PostgREST reuses builder classes across verbs.

    ⚠️ `insert` and `upsert` are **both POST**. They are told apart by the
    `prefer` header carrying `resolution=merge-duplicates`, which is the only
    thing that distinguishes them on the wire.
    """
    cfg = _cfg(builder)
    raw = None
    for attr in ("http_method", "method", "_method"):
        raw = getattr(cfg, attr, None)
        if raw:
            break
    if not raw:
        return "?"
    name = str(getattr(raw, "value", raw)).upper()
    if name == "POST":
        return "upsert" if "merge-duplicates" in _prefer(builder) else "insert"
    return {"GET": "select", "PATCH": "update", "DELETE": "delete",
            "HEAD": "count"}.get(name, name.lower())


def _prefer(builder: Any) -> str:
    try:
        headers = getattr(_cfg(builder), "headers", None) or {}
        return str(headers.get("prefer", "") or "").lower()
    except Exception:
        return ""


def echoes(builder: Any) -> bool:
    """Is this write still asking PostgREST to send the row back?

    The direct check on `docs/AUDIT_EGRESS_2.md`'s fix, measured in flight
    rather than inferred from source: `prefer: return=representation` means the
    echo is on. A read has no opinion and reports False.
    """
    if _op_of(builder) in ("select", "count", "?"):
        return False
    return "return=representation" in _prefer(builder)


def _table_of(builder: Any) -> str:
    got = getattr(_cfg(builder), "path", None) or getattr(builder, "url", None)
    if not got:
        return "?"
    # "https://…/rest/v1/option_chain_data?select=*" → option_chain_data
    text = str(got).split("?")[0].rstrip("/")
    return text.rsplit("/", 1)[-1] or "?"


def install(client: Any) -> bool:
    """Wrap `execute()` on whatever builder classes this client actually uses.

    Patched on the CLASS, once, rather than on each builder instance: PostgREST
    returns a new builder from every chained call (`.select().eq().order()`), so
    wrapping the object handed out by `table()` would measure a builder that is
    thrown away before anything executes.
    """
    global _installed
    if _installed or not ENABLED or client is None:
        return False
    seen = set()
    try:
        probe = client.table("_egress_probe_")
    except Exception:
        return False
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
    return _installed


def _patch(cls: Any) -> None:
    original = cls.execute
    if getattr(original, "_egress_wrapped", False):
        return

    def execute(self, *args, **kwargs):
        # Read the request BEFORE executing: some builders reset their config
        # once the call has gone out, and attributing to "?" is worse than the
        # microsecond this costs.
        try:
            table, op, echo = _table_of(self), _op_of(self), echoes(self)
        except Exception:
            table, op, echo = "?", "?", False
        res = original(self, *args, **kwargs)
        try:
            record(table, op, getattr(res, "data", None), echoing=echo)
        except Exception:
            pass
        return res

    execute._egress_wrapped = True          # type: ignore[attr-defined]
    cls.execute = execute


def cache_stats() -> Dict[str, int]:
    """Hits and misses from the read cache, if it is loaded.

    The other half of the picture. This module measures what *reached*
    PostgREST; a cache hit by definition leaves no trace here, so counting the
    bytes alone cannot distinguish "the cache is working" from "nothing asked".
    `read_cache` already tracks calls and fetches — `calls - fetches` is the
    saving — so it is read rather than re-counted.
    """
    try:
        from db import read_cache as _rc
        s = _rc.stats()
        calls, fetches = int(s.get("calls", 0)), int(s.get("fetches", 0))
        return {"calls": calls, "fetches": fetches,
                "hits": max(0, calls - fetches),
                "hit_pct": round((calls - fetches) / calls * 100) if calls else 0}
    except Exception:
        return {}


def report() -> Dict[str, Any]:
    """Per table and op, biggest first."""
    rows: List[Dict[str, Any]] = []
    total = 0
    for table, ops in _STATS.items():
        if table == "_total":
            continue
        for op, s in ops.items():
            total += s["bytes"]
            rows.append({"table": table, "op": op, "calls": int(s["calls"]),
                         "rows": int(s["rows"]), "bytes": int(s["bytes"]),
                         "echoing": int(s.get("echoing", 0)),
                         "bytes_per_call": round(s["bytes"] / max(1, s["calls"]))})
    rows.sort(key=lambda r: -r["bytes"])
    echoing = [r for r in rows if r["echoing"]]
    return {"total_bytes": int(total), "calls": sum(r["calls"] for r in rows),
            "cache": cache_stats(),
            # Writes still returning their row. Should be empty except for
            # `auto_trades`, which reads the generated id — anything else here
            # is a write that slipped past the fix.
            "still_echoing": [f"{r['table']}.{r['op']}" for r in echoing],
            "echoed_bytes": int(sum(r["bytes"] for r in echoing)),
            "by_table": rows}


def flush(path: pathlib.Path = REPORT_PATH) -> Dict[str, Any]:
    """Report, write, and reset — per rerun, because the question is what ONE
    cycle costs. A running total answers a different question."""
    data = report()
    try:
        path.write_text(json.dumps(data, indent=2))
    except Exception:
        pass
    _STATS.clear()
    return data


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} MB"


def summary_line(data: Dict[str, Any]) -> str:
    """One line: the cycle's total and the three tables that dominated it."""
    rows = data.get("by_table") or []
    if not rows:
        return "📉 egress: nothing measured this cycle"
    top = " · ".join(f"{r['table']}.{r['op']} {_human(r['bytes'])}"
                     for r in rows[:3])
    line = (f"📉 egress this cycle: {_human(data['total_bytes'])} over "
            f"{data['calls']} calls — {top}  (parsed size, pre-gzip)")
    c = data.get("cache") or {}
    if c.get("calls"):
        line += (f" | cache {c['hit_pct']}% hit "
                 f"({c['hits']}/{c['calls']} served without a request)")
    echo = data.get("still_echoing") or []
    if echo:
        line += (f"  ⚠️ still echoing: {', '.join(echo[:4])}"
                 f" ({_human(data.get('echoed_bytes', 0))})")
    return line
