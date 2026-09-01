# Stage 72.9 — Output Contract

```python
dispatch = Dispatcher(decision, ctx,
                      lifecycle=None,        # optional, Stage 73
                      registry=MemoryRegistry(),
                      transport=app_sender).run()
```

**The single gateway between MIOS and the outside world.** No other module may
send.

---

## 1 · `DispatchDecision`

Frozen. Nested mappings are `MappingProxyType`.

| Field | Values |
|---|---|
| `id` | UUID4, this dispatch |
| `decision_id` | the `EntryDecision.id` being dispatched |
| `version` | `"72.9"` |
| `created_at` | UTC ISO 8601 |
| `hash` | SHA-256 over `id · decision_id · version · dispatch_state · created_at` |
| `dispatch_state` | one of `DISPATCH_STATES` |
| `dispatch_reason` | why that state, in words |
| `telegram_state` | one of `DELIVERY_STATES` |
| `duplicate` | `bool` |
| `should_send` | `bool` — the gate verdict, before delivery |
| `payload` | Stage 72's payload + identity. **Wording unchanged** — including Stage 71.85's seven keys (`behaviour · behaviour_strength · momentum · break_probability · fakeout_probability · premium_acceptance · top_behaviour_reason`), carried through, never read or branched on |
| `edits` | a `telegram_message_id` to edit, or `None` |
| `record` | the `DispatchRecord` appended to history |
| `metadata` | every phase's reason, the cache, supported versions |

---

## 2 · Dispatch states

```
READY · WAIT · BLOCKED · SUPERSEDED · DUPLICATE · EXPIRED · SENT · FAILED · UNKNOWN
```

| State | Means |
|---|---|
| `READY` | gates opened; a send was attempted |
| `SENT` | the transport confirmed delivery |
| `FAILED` | the transport failed, raised, or returned something unreadable |
| `WAIT` | nothing worth broadcasting — `WAIT` from Stage 72, or confidence `UNKNOWN` |
| `BLOCKED` | incomplete, hash mismatch, or an unsupported decision version |
| `DUPLICATE` | this hash already went out. **`SENT` is terminal** |
| `SUPERSEDED` | a newer decision was already dispatched |
| `EXPIRED` | older than `MAX_AGE_SECONDS` (300s) |

## 3 · Delivery states

```
NOT_SENT · SENT · FAILED · RETRY · RATE_LIMIT · UNKNOWN
```

A transport that raises, returns nothing, or returns something unreadable
yields `UNKNOWN` → `dispatch_state = FAILED`. **Never `SENT`.** A message
assumed delivered is a duplicate waiting to happen: the next cycle would see
the hash recorded and stay quiet.

---

## 4 · The gate ladder

| Rung | Condition | State |
|---|---|---|
| 1 | missing field, bad hash, unsupported version | `BLOCKED` |
| 2 | older than 300s | `EXPIRED` |
| 3 | hash already dispatched | `DUPLICATE` |
| 4 | a newer decision already went out | `SUPERSEDED` |
| 5 | confidence `UNKNOWN` | `WAIT` |
| 6 | entry state not sendable **and** no sendable lifecycle action | `WAIT` |
| 7 | otherwise | `READY` |

`SENDABLE_STATES = ENTER · ENTRY_READY · ABORT`. `WAIT` is the engine working
correctly, and saying so every cycle trains the reader to mute the channel —
the one outcome a signal channel cannot survive.

---

## 5 · Editing beats re-sending

When the registry holds a live message for this `decision_id` **and** a
lifecycle decision is present, `edits` names that `telegram_message_id` and the
transport is called as `transport(payload, edits)`.

A trade going `ENTER → TRAIL → EXIT` updates **one** message instead of posting
three that each look like a new signal.

---

## 6 · The registry

Three methods, one optional:

```python
registry.record(row)      # append-only
registry.rows()           # supersession
registry.sent_hashes()    # duplicates
registry.live_message(decision_id)   # the edit handle
```

Phase 10's cache is **derived**, not stored twice:
`last_dispatched_hash · last_dispatched_id · last_dispatch_time`.

`MemoryRegistry` is the default. Supabase — `sql/031_dispatch_history.sql` — is
injected by the app, because this module reaches no database. That migration
carries a partial unique index on `(decision_hash) WHERE status = 'SENT'`, so
the duplicate guarantee holds even if two app instances race.

---

## 7 · Guarantees

| Guarantee | Enforced by |
|---|---|
| Exactly one gateway | no other `mios_v5` module accepts a transport — asserted |
| No network import | transport injected; import-graph test |
| No database import | registry injected |
| Payload wording unchanged | only identity keys are added — asserted |
| Same decision twice → one message | `DUPLICATE`, and a partial unique index |
| Stale decision never sends | `SUPERSEDED` on the decision's own timestamp |
| Altered record never sends | `verify()` in Phase 1 → `BLOCKED` |
| History append-only | `record()` appends; nothing updates in place |
| Stage 72 and 73 cannot send | asserted for both |
