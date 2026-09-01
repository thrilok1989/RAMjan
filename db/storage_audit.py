"""Storage audit — reading `sql/035_storage_audit.sql` from the app.

Three RPCs, one thin reader each. Nothing is computed here; Postgres already
knows how big its own tables are, and asking it is both exact and free.

## Supabase Storage is not the same thing as Supabase storage

The buckets-and-files product and the size of your database share one word and
nothing else. **This application uses no Storage at all** — no bucket, no
upload, no `.storage` anywhere in the codebase; the only CSV it produces goes to
an in-memory buffer for a browser download. So a storage figure that keeps
climbing is the *database*, and `report()` says which table.

## Why RPCs

PostgREST cannot run arbitrary SQL, so a function is the only way the app can
ask a question the schema does not answer as a table. That gap was recorded in
`docs/AUDIT_QUERY_INDEXES.md` §9; this is the first thing to close it.

## Missing functions are reported, not raised

Every reader returns `[]` when the migration has not been applied, and
`installed()` says which are present. A panel that vanishes because a migration
is pending looks exactly like a panel that says there is nothing to report.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

#: The RPCs, and the migration that creates them.
FUNCTIONS = ("storage_report", "unused_indexes", "retention_pressure")
MIGRATION = "sql/035_storage_audit.sql"


def _rpc(db: Any, name: str) -> List[Dict[str, Any]]:
    """Call one RPC. `[]` on any failure — a maintenance panel may never take
    the app down, and "not installed" is the most likely failure by far."""
    try:
        res = db.client.rpc(name).execute()
        return list(getattr(res, "data", None) or [])
    except Exception:
        return []


def report(db: Any) -> List[Dict[str, Any]]:
    """Every table, biggest first."""
    return _rpc(db, "storage_report")


def unused_indexes(db: Any) -> List[Dict[str, Any]]:
    """Non-constraint indexes nothing has scanned.

    Only meaningful after a full trading day: `idx_scan` counts since the last
    stats reset, so a fresh counter makes every index look unused.
    """
    return _rpc(db, "unused_indexes")


def pressure(db: Any) -> List[Dict[str, Any]]:
    """Table size joined to its retention policy — big *and* purgeable."""
    return _rpc(db, "retention_pressure")


def installed(db: Any) -> Dict[str, bool]:
    """Which RPCs answered. Told plainly so a pending migration reads as a
    pending migration."""
    return {name: bool(_rpc(db, name)) for name in FUNCTIONS}


def _int(v) -> int:
    """A count, whatever arrived. A report that raises on one odd value tells
    you nothing about the other fifty tables."""
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Totals over a `storage_report()`.

    `indexes` is worth reading next to `total`: an index share above about a
    third usually means indexes nothing uses, which `unused_indexes()` names.
    """
    total = sum(_int(r.get("total_bytes")) for r in rows)
    idx = sum(_int(r.get("index_bytes")) for r in rows)
    dead = sum(_int(r.get("dead_rows")) for r in rows)
    return {
        "tables": len(rows),
        "total_bytes": total,
        "index_bytes": idx,
        "dead_rows": dead,
        "index_pct": (round(100.0 * idx / total) if total else 0),
        "total_pretty": human(total),
        "index_pretty": human(idx),
    }


def human(n: Optional[float]) -> str:
    """Bytes, the way the Supabase dashboard writes them.

    `None` is `—`, not `0 B`: a size nobody measured and a table holding nothing
    are different facts, and this codebase does not render them the same.
    """
    if n is None:
        return "—"
    try:
        size = float(n)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if abs(size) < 1024.0 or unit == "TB":
            return f"{size:,.0f} {unit}" if unit == "B" else f"{size:,.1f} {unit}"
        size /= 1024.0
    return f"{size:,.1f} TB"


def unpoliced(rows: List[Dict[str, Any]], top: int = 10) -> List[Dict[str, Any]]:
    """The biggest tables that no retention policy covers — the ones that grow
    forever unless somebody decides otherwise."""
    return [r for r in rows if r.get("verdict") == "no policy — grows forever"][:top]


def dormant(rows: List[Dict[str, Any]], top: int = 10) -> List[Dict[str, Any]]:
    """Big tables with a policy nobody enabled. One `UPDATE` away from being
    handled, which is why they are worth listing separately from the ones that
    need a decision."""
    return [r for r in rows if r.get("verdict") == "policy exists, NOT enabled"][:top]


def render(st, db) -> None:
    """🧮 Storage — sidebar panel. Advisory; it may never take the app down."""
    if db is None:
        return
    try:
        with st.sidebar.expander("🧮 Storage", expanded=False):
            if st.button("Measure", key="_storage_measure"):
                st.session_state["_storage_rows"] = report(db)
                st.session_state["_storage_pressure"] = pressure(db)
                st.session_state["_storage_unused"] = unused_indexes(db)

            rows = st.session_state.get("_storage_rows")
            if not rows:
                st.caption(
                    "Press Measure. If nothing appears, apply "
                    f"`{MIGRATION}` — the report is a Postgres function.")
                st.caption(
                    "Supabase **Storage** (buckets/files) is unused by this "
                    "app. A growing figure is the database.")
                return

            s = summarise(rows)
            st.caption(
                f"**{s['total_pretty']}** across {s['tables']} tables · "
                f"{s['index_pretty']} of it indexes ({s['index_pct']}%)")
            for r in rows[:8]:
                st.caption(f"`{r.get('table_name')}` — {r.get('total_pretty')} "
                           f"({int(r.get('live_rows') or 0):,} rows)")

            press = st.session_state.get("_storage_pressure") or []
            no_policy = unpoliced(press, 5)
            if no_policy:
                st.caption("⚠️ no retention policy: "
                           + ", ".join(f"`{r['table_name']}`" for r in no_policy))
            off = dormant(press, 5)
            if off:
                st.caption("⚪ policy not enabled: "
                           + ", ".join(f"`{r['table_name']}`" for r in off))

            idx = st.session_state.get("_storage_unused") or []
            if idx:
                waste = human(sum(int(i.get("size_bytes") or 0) for i in idx))
                st.caption(f"🗑 {len(idx)} unused indexes holding {waste} — "
                           "only meaningful after a full trading day")
    except Exception as err:
        st.sidebar.caption(f"Storage report unavailable: {err}")
