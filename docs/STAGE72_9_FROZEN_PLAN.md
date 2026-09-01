# Stage 72.9 — Freeze Plan

*Built, not frozen. This is what has to be true before it is.*

---

## Why not yet

Every gate in this stage is testable today and all of them pass. What is not
proven is the thing that matters most: **that the gates behave correctly against
a real Telegram endpoint over real sessions.**

A dispatcher is the one stage where a bug is loud and public. A duplicate storm,
a contradictory pair of alerts, or a silent channel during a live move are all
failures a trader sees before any test does. So this stage freezes on evidence,
not on green tests.

---

## Freeze criteria

| # | Criterion | Status |
|---|---|---|
| 1 | Transport injected; no network import | ✅ |
| 2 | Registry injected; no database import | ✅ |
| 3 | Output immutable, identity + hash present | ✅ |
| 4 | Duplicate suppression proven in test | ✅ |
| 5 | Supersession proven in test | ✅ |
| 6 | Hash mismatch blocks | ✅ |
| 7 | Failure and retry paths return, never assume `SENT` | ✅ |
| 8 | History append-only | ✅ |
| 9 | Payload wording provably unmodified | ✅ |
| 10 | No other stage can send | ✅ |
| 11 | **`sql/031` applied and the Supabase registry wired** | ❌ **blocking** |
| 12 | **Two weeks of live dispatch with zero duplicates** | ❌ **blocking** |

---

## What may change until then

**May change** (and is expected to):

* `MAX_AGE_SECONDS` — 300s is a reasoned guess, not a measurement
* `SENDABLE_STATES` / `SENDABLE_ACTIONS`, if live use shows the channel too
  quiet or too noisy
* the transport result vocabulary, as a real client's shapes become known
* adding a Supabase-backed registry alongside `MemoryRegistry`

**May not change**, now or after:

* the injected-transport design — it is what keeps `mios_v5` off the network
* append-only history
* the gate ladder's *order*: validation before duplicate before supersession.
  A duplicate check that ran first would let an altered record suppress a
  legitimate one
* `SENT` being terminal for a hash
* payload wording remaining Stage 72's

---

## Known limitations

| Limitation | Why |
|---|---|
| `MemoryRegistry` forgets on restart | it is a default, not the destination — Supabase is criterion 11 |
| No retry loop | `RETRY` and `RATE_LIMIT` are *reported*; scheduling a retry is the caller's, because a stage that retries inside `run()` blocks a render |
| Edits need a lifecycle decision | without one there is nothing new to say, so there is nothing to edit |
| No per-chat routing | one channel today; `chat_id` is recorded so routing can be added without a migration |

---

## Where the next work goes

| Want | Where |
|---|---|
| Supabase registry | `db/`, injected — this module stays unchanged |
| Retry scheduling | the caller, reading `telegram_state == RETRY` |
| Editing on lifecycle transitions | already supported; needs Stage 73 wired into the caller |
| Message deletion on `ABORT` | a transport concern; `status = 'DELETED'` already exists in the schema |
| Multi-channel routing | `chat_id` is already recorded |

> ⛔ Nothing else in `mios_v5` may import a transport or write dispatch history.
> That is the whole point of this stage, and it is asserted rather than
> documented.
