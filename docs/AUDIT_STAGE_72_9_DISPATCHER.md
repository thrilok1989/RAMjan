# Stage 72.9 — Decision Dispatcher: audit before build

*Taken at `19a4be6`. One question per phase: **can this be built without
breaking a rule already in force?***

---

## Verdict

**Three conflicts, and the first one changes the design.**

1. **"Own the Telegram client" collides with a standing architecture rule.**
   `import requests` inside `mios_v5` is a *named* forbidden failure mode
   (`ARCHITECTURE_PRINCIPLES.md` §"Honest limits"). The dispatcher owns the
   **gateway**, not the socket — the transport is injected.
2. **Stage 73 already exists.** The spec says it is not started. It is, so the
   optional `TradeLifecycleDecision` input is available *now* — which is what
   makes the recommended message-edit feature buildable rather than theoretical.
3. **Supersession needs a registry, not a comparison.** "Is there a newer
   decision?" cannot be answered from one decision; it needs dispatch history.

---

## 1. ⛔ The Telegram client cannot live inside `mios_v5`

> *The guard tests catch the named failure modes — a `*_v6()` function, an
> `import requests` inside `mios_v5`, a reserved word in a migration.*

Stage 72.9 is in `mios_v5`. Importing a network client there breaks a rule that
three existing stages are tested against.

### Decision

**Stage 72.9 owns the gateway; the app owns the socket.**

| Owns | Who |
|---|---|
| *Whether* a decision may leave MIOS | **Stage 72.9** |
| The dispatch state machine, duplicate and supersession rules | **Stage 72.9** |
| The payload, and the history row | **Stage 72.9** |
| The actual HTTP call | the **app**, injected as `transport` |

```python
Dispatcher(decision, ctx, registry=..., transport=app_sender).run()
```

`transport` is any callable taking the payload and returning a delivery result.
The dispatcher never learns what is behind it.

This is *stronger* than owning the client, not weaker: the send is impossible
without going through the dispatcher's gates, and the dispatcher stays unit
testable with no network at all. **The "exactly one gateway" guarantee holds by
construction**, and a test asserts no other `mios_v5` module names a transport.

---

## 2. Stage 73 exists — the optional input is available

The spec lists `TradeLifecycleDecision` as available "in future". It is
available now, and that matters for the recommendation in §4: editing a live
message when a trade goes `HOLD → EXIT` needs the lifecycle verdict and the
original `telegram_message_id` in the same place.

The dispatcher therefore accepts it as an optional third input, and where it is
present the payload carries the lifecycle action alongside the entry decision.
**Stage 73 does not change.** It prepares a payload and marks it `sent: False`,
exactly as before.

---

## 3. Supersession and duplicates need a registry

Neither question is answerable from a single decision:

| Question | Needs |
|---|---|
| "Have I sent this before?" | every hash previously dispatched |
| "Is there a newer decision?" | the newest `created_at` dispatched for this context |

### Decision

A `DispatchRegistry` protocol with two implementations:

* **`MemoryRegistry`** — the default, holds the Phase 10 cache
  (`last_dispatched_hash · last_dispatched_id · last_dispatch_time`). Enough for
  a single session, and what the tests run against.
* **Supabase** — `sql/031_dispatch_history.sql`, append-only, injected by the
  app.

The registry is an **input**, not an import. `mios_v5` does not reach a
database any more than it reaches a network.

---

## 4. The Telegram Message Registry ✅ recommended and taken

The recommendation is right and the audit adopts it. `dispatch_history` carries
`telegram_message_id` and `chat_id`, so a later stage can **edit** a live
message rather than posting a second one.

`DispatchDecision.edits` names the `telegram_message_id` to edit when the
registry already holds a live message for this `decision_id`. The dispatcher
**decides** the edit; the transport performs it.

Without this, a trade going `ENTER → TRAIL → EXIT` produces three messages that
each look like a new signal. With it, one message updates in place.

⚠️ **Editing is a decision, not a default.** A `SENT` message whose content has
not materially changed is not re-sent *or* edited — a message that rewrites
itself every cycle is as ignorable as one that repeats, which is the same
reasoning Stage 65's narrator uses for writing on transitions only.

---

## 5. What the dispatcher may never do

| Never | Why |
|---|---|
| Modify the payload's wording | Stage 72 wrote it; enrichment is identity fields only |
| Re-derive a decision | it is not an execution stage |
| Send when `dispatch_state != READY` | the gates are the whole product |
| Overwrite a history row | history is append-only |
| Decide *what* to trade | that is two stages upstream |

---

## 6. Rules this audit forces

1. **No network client imported.** Transport injected; asserted on the import
   graph.
2. **No database client imported.** Registry injected.
3. **Payload wording is copied, never rewritten** — only identity is added.
4. **History is append-only**; a new state is a new row.
5. **`SENT` is terminal for a hash.** The same hash never dispatches twice.
6. **Stage 72 and Stage 73 stay untouched**, and tests assert neither can send.
