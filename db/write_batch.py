"""Batch writes — one round-trip per table instead of one per row.

`_safe_upsert` has always taken a **list**. The cost is not in the client, it is
in the call sites that hand it one row at a time inside a loop:

```python
for p in db.get_open_bias_predictions():        # Stage 40, grading
    db.update_bias_prediction(p["id"], {...})   # one round-trip. each.
```

Twenty predictions coming due together is twenty round-trips to write twenty
small rows. Batched, it is one.

## Why this is opt-in and not automatic

The obvious version of this intercepts every `insert_*` and defers it. That
version is wrong, and specifically it breaks the dispatch claim protocol:
`SupabaseDispatchRegistry.reserve()` writes the `SENT` row **before** the
Telegram message goes out, precisely so a crash between the two leaves a
recorded claim rather than a silent duplicate. A deferred reserve is not a
claim — it is an intention, and the next cycle would send the message again.

So batching is something a call site asks for, at a site where the author has
decided that a row landing a few milliseconds later is fine. Anything that has
not asked keeps writing immediately.

## Updates batch too

An update by primary key is an upsert: `upsert([{id: 1, …}, {id: 2, …}])`
updates both rows in one statement, because the conflict target is the key they
already collide on. That is what makes the Stage 40 grading loop batchable
without changing what it writes.

The row must carry its key. `add()` refuses a row missing any conflict column
rather than sending it and letting PostgREST insert a duplicate — a silent
extra row is worse than a loud refusal.

## It always flushes

The context manager flushes on the way out, including when the block raises.
A batch that is dropped because something else failed is data loss with no
error message pointing at it. If the flush itself fails, `_safe_upsert` queues
the rows in the existing `CacheManager` pending-writes path, so `sync_pending()`
retries them next cycle — the same recovery every other write in this client
already has.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


class WriteBatch:
    """Accumulate rows per (table, conflict target); flush once per group.

    Not thread-safe and not meant to be: one batch belongs to one block of one
    cycle, and its whole purpose is to be short-lived.
    """

    def __init__(self, db: Any) -> None:
        self._db = db
        self._groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self.flushed: List[Dict[str, Any]] = []
        self.refused: List[Dict[str, Any]] = []

    # ── collecting ───────────────────────────────────────────────────
    def add(self, table: str, row: Any, conflict: str = "id") -> bool:
        """Queue one row. `conflict` is the upsert key, comma-separated.

        Returns False — and records why in `refused` — when the row is not a
        mapping or is missing a conflict column. An upsert whose conflict target
        is absent from the row does not update anything; it inserts a second
        row. Refusing loudly beats writing a duplicate quietly.
        """
        if not isinstance(row, dict):
            self.refused.append({"table": table, "why": "not a mapping",
                                 "row": repr(row)[:200]})
            return False
        keys = [k.strip() for k in str(conflict).split(",") if k.strip()]
        missing = [k for k in keys if row.get(k) is None]
        if missing:
            self.refused.append({"table": table, "why": f"missing {missing}",
                                 "row": repr(row)[:200]})
            return False
        self._groups.setdefault((table, conflict), []).append(dict(row))
        return True

    def extend(self, table: str, rows: Iterable[Any],
               conflict: str = "id") -> int:
        """Queue many. Returns how many were accepted."""
        return sum(1 for r in (rows or ()) if self.add(table, r, conflict))

    # ── inspecting ───────────────────────────────────────────────────
    @property
    def pending(self) -> int:
        return sum(len(v) for v in self._groups.values())

    @property
    def tables(self) -> Tuple[str, ...]:
        return tuple(sorted({t for t, _ in self._groups}))

    def rows_for(self, table: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for (t, _), rows in self._groups.items():
            if t == table:
                out.extend(rows)
        return out

    # ── flushing ─────────────────────────────────────────────────────
    def flush(self) -> Dict[str, Any]:
        """Send everything queued: one upsert per (table, conflict) group.

        Never raises. A batch that takes the cycle down has cost more than the
        rows it was carrying.
        """
        report: Dict[str, Any] = {"groups": 0, "rows": 0, "tables": [],
                                  "errors": []}
        for (table, conflict), rows in list(self._groups.items()):
            if not rows:
                continue
            try:
                self._db._safe_upsert(table, rows, conflict)
                report["groups"] += 1
                report["rows"] += len(rows)
                report["tables"].append(table)
            except Exception as err:
                report["errors"].append({"table": table, "error": str(err)})
        self._groups.clear()
        report["refused"] = len(self.refused)
        self.flushed.append(report)
        return report

    # ── context manager ──────────────────────────────────────────────
    def __enter__(self) -> "WriteBatch":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # Flush even when the block raised. Dropping queued rows because
        # something *else* failed is data loss with nothing pointing at it.
        self.flush()
        return False        # never swallow the exception


def batch(db: Any) -> WriteBatch:
    """`with batch(db) as b: b.add(...)` — flushes on exit, always."""
    return WriteBatch(db)


def upsert_many(db: Any, table: str, rows: Sequence[Any],
                conflict: str = "id") -> Dict[str, Any]:
    """One table, one round-trip, no context manager.

    The short form for the common case: a loop that has already built its rows
    and only needs them written together.
    """
    b = WriteBatch(db)
    b.extend(table, rows, conflict)
    return b.flush()
