"""The Supabase-backed dispatch registry — Stage 72.9's source of truth.

Lives in `db/` because `mios_v5` may not import a database client, the same
rule that keeps the Telegram transport out of it. The dispatcher receives this
object; it never constructs one.

## The claim is a unique index

`sql/031_dispatch_history.sql` carries:

```sql
CREATE UNIQUE INDEX uniq_dispatch_sent_hash
    ON dispatch_history (decision_hash) WHERE status = 'SENT';
```

`reserve()` inserts a `SENT` row **before** the message goes out. If a second
instance is racing, its insert violates that index and it loses the claim — so
the duplicate guarantee is enforced by Postgres rather than by two processes
agreeing to be careful.

`release()` demotes the row to `FAILED` when the send did not happen, so a
retry is not blocked by a message that never existed.

**Reserving before sending is deliberate.** The alternative — send, then record
— leaves a window where a crash produces a delivered message with no history
row, and the next cycle sends it again. A spurious `FAILED` row is recoverable;
a duplicate alert is not.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from mios_v5.dispatcher import DELIVERED, DELIVERY_FAILED, DispatchRecord

TABLE = "dispatch_history"


class SupabaseDispatchRegistry:
    """Satisfies the registry protocol Stage 72.9 expects.

    Every method degrades to a safe answer rather than raising: a registry that
    cannot answer must never be read as "go ahead", and the dispatcher's
    `_reserve` already treats an exception as a lost claim.
    """

    def __init__(self, db: Any, chat_id: Optional[str] = None) -> None:
        self.db = db
        self.chat_id = chat_id
        self.connected = False
        self._last_error: Optional[str] = None

    # ── the claim ─────────────────────────────────────────────────────
    def reserve(self, decision_hash: str) -> bool:
        """Insert the SENT row first. A unique-index violation means we lost."""
        if not decision_hash:
            return False
        try:
            self.db.client.table(TABLE).insert({
                "decision_id": "", "decision_hash": decision_hash,
                "dispatch_id": "", "dispatch_state": "READY",
                "status": DELIVERED, "chat_id": self.chat_id,
            }).execute()
            self.connected = True
            return True
        except Exception as err:
            # Either the index rejected us — somebody else holds the claim —
            # or the database is unreachable. Both mean: do not send.
            self._last_error = str(err)
            return False

    def confirm(self, decision_hash: str) -> None:
        """Nothing to do — the reserved row already says SENT."""
        return None

    def release(self, decision_hash: str) -> None:
        """The send failed. Demote so the unique index frees the hash."""
        try:
            (self.db.client.table(TABLE)
             .update({"status": DELIVERY_FAILED})
             .eq("decision_hash", decision_hash)
             .eq("status", DELIVERED)
             .is_("telegram_message_id", "null")
             .execute())
        except Exception as err:
            self._last_error = str(err)

    # ── history ───────────────────────────────────────────────────────
    def record(self, row: DispatchRecord) -> None:
        """Append. A row is never updated in place except by `release`."""
        try:
            payload = row.to_dict()
            payload["chat_id"] = payload.get("chat_id") or self.chat_id
            if row.status == DELIVERED and row.telegram_message_id:
                # attach the message id to the row `reserve` already inserted
                (self.db.client.table(TABLE)
                 .update({"telegram_message_id": row.telegram_message_id,
                          "decision_id": row.decision_id,
                          "dispatch_state": row.dispatch_state,
                          "chat_id": payload["chat_id"]})
                 .eq("decision_hash", row.decision_hash)
                 .eq("status", DELIVERED)
                 .is_("telegram_message_id", "null").execute())
            else:
                self.db.client.table(TABLE).insert({
                    "decision_id": row.decision_id,
                    "decision_hash": row.decision_hash,
                    "dispatch_id": "", "dispatch_state": row.dispatch_state,
                    "status": row.status, "chat_id": payload["chat_id"],
                    "telegram_message_id": row.telegram_message_id,
                }).execute()
            self.connected = True
        except Exception as err:
            self.connected = False
            self._last_error = str(err)

    def rows(self, limit: int = 500) -> Tuple[DispatchRecord, ...]:
        try:
            res = (self.db.client.table(TABLE).select("*")
                   .order("created_at", desc=True).limit(limit).execute())
            self.connected = True
        except Exception as err:
            self.connected = False
            self._last_error = str(err)
            return ()
        out: List[DispatchRecord] = []
        for r in reversed(getattr(res, "data", None) or []):
            out.append(DispatchRecord(
                decision_id=r.get("decision_id") or "",
                decision_hash=r.get("decision_hash") or "",
                dispatch_state=r.get("dispatch_state") or "",
                created_at=str(r.get("created_at") or ""),
                telegram_message_id=r.get("telegram_message_id"),
                chat_id=r.get("chat_id"),
                status=r.get("status") or "NOT_SENT"))
        return tuple(out)

    def sent_hashes(self) -> Tuple[str, ...]:
        return tuple(r.decision_hash for r in self.rows()
                     if r.status == DELIVERED)

    # ── the Phase 10 cache, derived from the rows ─────────────────────
    def _last_sent(self) -> Optional[DispatchRecord]:
        sent = [r for r in self.rows() if r.status == DELIVERED]
        return sent[-1] if sent else None

    @property
    def last_dispatched_hash(self) -> Optional[str]:
        row = self._last_sent()
        return row.decision_hash if row else None

    @property
    def last_dispatched_id(self) -> Optional[str]:
        row = self._last_sent()
        return row.decision_id if row else None

    @property
    def last_dispatch_time(self) -> Optional[str]:
        row = self._last_sent()
        return row.created_at if row else None

    def live_message(self, decision_id: str) -> Optional[DispatchRecord]:
        for row in reversed(self.rows()):
            if (row.decision_id == decision_id and row.status == DELIVERED
                    and row.telegram_message_id):
                return row
        return None

    def health(self) -> Dict[str, Any]:
        return {"connected": self.connected, "last_error": self._last_error,
                "table": TABLE}
