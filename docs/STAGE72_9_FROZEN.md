# Stage 72.9 — Dispatch Contract

**`STATUS = "VALIDATED_SIMULATED"` · `CONTRACT_VERSION = "72.9.0"`**

> ⚠️ **This document describes the frozen contract. The stage is not yet
> marked `FROZEN`** — one acceptance criterion is outstanding. See
> §Acceptance Criteria and `STAGE72_9_VALIDATION_REPORT.md`. The design is
> final; only the constant is waiting.

---

## Purpose

The **single gateway** between MIOS and the outside world. One question:

> Should this decision leave MIOS?

It never creates a duplicate alert, never loses a valid one, never edits the
wrong message, never fails silently, never assumes success, and never bypasses
the registry.

---

## Architecture

```
Stage 72 → Stage 72.9 → transport → Telegram
Stage 73 ────┘  ↑ the only door
                └── registry (Supabase)
```

It owns the **gateway, not the socket**. `import requests` inside `mios_v5` is
a named forbidden failure mode, so the transport and the registry are both
**injected**. This is stronger than owning the client: a send is impossible
without passing the gates, the stage is unit-testable with no network, and a
test asserts no other `mios_v5` module takes a `transport` parameter.

| Owns | Who |
|---|---|
| Whether a decision may leave | **Stage 72.9** |
| Duplicate, supersession, expiry, validation | **Stage 72.9** |
| Dispatch history | **Stage 72.9** |
| The HTTP call | the app, injected |
| The database call | `db/dispatch_registry.py`, injected |

---

## Registry Flow

```
Decision → hash → registry lookup → gates → reserve → transport → confirm/release → record
```

The registry is the **single source of truth**. Never memory, never
`session_state`, never a cached hash. A restart re-reads it and sends nothing
twice — proven by the `restart` scenario.

---

## Duplicate Protection

Three layers, and the middle one is the important one:

1. **Read** — `sent_hashes()` and `last_dispatched_hash`.
2. **Claim** — `reserve()` before sending. Checking then sending is two
   operations with a gap, and two instances starting together both pass the
   check before either sends. The claim closes the gap.
3. **Database** — `sql/031` carries
   `UNIQUE INDEX ... (decision_hash) WHERE status = 'SENT'`. The Supabase
   registry inserts the `SENT` row *before* the message goes out, so a racing
   instance loses on a unique violation rather than on cooperation.

**Reserving before sending is deliberate.** Send-then-record leaves a window
where a crash produces a delivered message with no history row, and the next
cycle sends it again. A spurious `FAILED` row is recoverable; a duplicate
alert is not.

`release()` demotes the row when the send did not happen, so a retry is not
blocked by a message that never existed.

---

## Transport Rules

**`SENT` only after the transport confirms.** Everything else is not a send.

| Transport behaviour | Result |
|---|---|
| `{"status": "ok", "message_id": …}` | `SENT` |
| raises | `FAILED` |
| times out | `FAILED` |
| returns something unreadable | `UNKNOWN` → `FAILED` |
| `{"status": "RATE_LIMIT"}` | `RATE_LIMIT` |
| `{"status": "RETRY"}` | `RETRY` |
| no transport supplied | `NOT_SENT` — decided, nothing sent |

A message assumed delivered is a duplicate waiting to happen: the next cycle
sees the hash recorded and stays quiet. Proven by the `failures` scenario —
zero silent successes at a 40% fault rate.

---

## Failure Handling

* A failure **releases the claim**. The hash stays sendable.
* A failure still **writes a row** — the history says what happened.
* An **unreachable registry does not send**. A registry that cannot answer is
  never read as "go ahead".
* `RETRY` and `RATE_LIMIT` are *reported*, not looped on: a stage that retried
  inside `run()` would block a render.

---

## Operational Metrics

`dispatcher.metrics(registry, latencies)` → `DispatchMetrics`:

```
dispatch_count · success_count · failed_count · duplicate_block_count
edit_count · retry_count · average_dispatch_latency_ms
average_edit_latency_ms · maximum_dispatch_latency_ms
failure_percentage · duplicate_percentage
```

`dispatcher.health(registry, transport, latencies)` → `DispatchHealth`:

```
status (OK · DEGRADED · DOWN · IDLE) · dispatches_today · duplicates_today
failures_today · average_latency_ms · registry_connected
telegram_connected · last_dispatch_time
```

> ⛔ **Monitoring only.** Nothing here may reach a trading decision, and a test
> asserts the dispatcher never reads its own metrics. A dispatch layer that
> throttled itself because its failure rate looked high would turn an outage
> into a silence — the worse of the two.

Counters are **derived from the history on read**, not accumulated. A counter
incremented alongside the rows is a second source of truth that drifts the
first time a write fails halfway.

---

## Acceptance Criteria

| # | Criterion | Status |
|---|---|---|
| 1 | 500+ dispatches | ⚠️ ~1,250 simulated · **0 live** |
| 2 | Zero duplicate messages | ✅ simulated |
| 3 | Zero wrong edits | ✅ simulated |
| 4 | Zero stale registry entries | ✅ simulated |
| 5 | Zero hash collisions | ✅ simulated |
| 6 | Zero registry corruption | ✅ simulated |
| 7 | Zero silent failures | ✅ simulated |
| 8 | **Live run against Supabase + Telegram** | ❌ **blocking** |

**Criterion 8 is why `STATUS` is not `FROZEN`.** A simulation proves the
decision logic; it cannot prove that Telegram behaves as assumed or that the
Postgres index fires under real concurrency. A dispatcher is the one stage
where a bug is loud and public, so it freezes on live evidence.

---

## Known Limitations

| Limitation | Why |
|---|---|
| `MemoryRegistry` forgets on restart | it is the default, not the destination — Supabase is criterion 8 |
| No retry loop | `RETRY`/`RATE_LIMIT` are reported; scheduling belongs to the caller |
| Edits need a lifecycle decision | without one there is nothing new to say |
| No per-chat routing | one channel today; `chat_id` is recorded so routing needs no migration |
| `MAX_AGE_SECONDS = 300` is reasoned, not measured | a live run is what would calibrate it |

---

## Extension Points

| Want | Where |
|---|---|
| Retry scheduling | the caller, reading `telegram_state` |
| Message deletion on `ABORT` | the transport; `status = 'DELETED'` already in the schema |
| Multi-channel routing | `chat_id` already recorded |
| A different messenger | a second transport; nothing here changes |
| Metrics dashboards | read `metrics()` / `health()`; they are pure functions |

---

## Freezing Rules

Once `STATUS = "FROZEN"`:

**May not change without a `CONTRACT_VERSION` bump:**

* `DispatchDecision`'s shape
* the registry protocol (`reserve · confirm · release · record · rows ·
  sent_hashes · live_message`)
* the gate ladder or its **order** — validation before duplicate before
  supersession. A duplicate check running first would let an altered record
  suppress a legitimate one
* `SENT` being terminal for a hash
* payload wording remaining Stage 72's

**May never change:**

* the injected-transport design
* append-only history
* metrics being monitoring-only

**Bug fixes** are allowed without a bump. A behaviour change is not a bug fix.

---

## Version

| | |
|---|---|
| `CONTRACT_VERSION` | `72.9.0` |
| `STATUS` | `VALIDATED_SIMULATED` |
| Frozen when | criterion 8 passes and `STATUS` is set to `"FROZEN"` |

That constant is the **only** change the freeze requires.
