# Audit — the V6 Execution Layer roadmap, against the tree

*Audit before build. This document is the gate, not the plan.*

The roadmap proposes five stages: 72 (Entry), 72.9 (Dispatch), 73 (Lifecycle),
73.5 (Intelligence Export), plus a Telegram Alert Engine and an AI Analyst. The
ownership split — *72 decides, 72.9 distributes, 73 manages, 73.5 exports, AI
only reads* — is correct and is already the shape of the tree.

What follows is what each proposal costs, given what is on disk today.

| Proposal | Verdict |
|---|---|
| Stage 72 — Entry Engine | **Built.** `72.1`, frozen + Amendment 1 |
| Stage 72.9 — Dispatch Engine | **Built.** `72.9`, `VALIDATED_SIMULATED`. Spec differs in 4 places |
| Stage 73 — Trade Lifecycle | **Built.** `73.0`. Spec asks for 6 fields that **cannot** exist yet |
| Stage 73.5 — Intelligence Export | **Genuinely new.** 3 of its 12 export blocks have no owner |
| Telegram Alert Engine | **Partly new.** The sample alert renders 5 values that do not exist |
| AI Analyst | **New, and correctly scoped.** Blocked on 73.5 |

**Build count justified by this audit: two** — Stage 73.5, and the alert
renderer. Everything else is an amendment to an existing owner, or a producer.

---

## 1 · Stage 72.9 — built. Four spec deltas.

`mios_v5/dispatcher.py`, `VERSION = "72.9"`, `CONTRACT_VERSION = "72.9.0"`,
`STATUS = "VALIDATED_SIMULATED"`.

Every ownership line in the proposal already holds: it owns the queue, duplicate
detection, supersession, delivery status, message version and history metadata;
it owns no entry, stop, target, confidence, risk or direction. It consumes
`EntryDecision` + `TradingContext` (+ optional `TradeLifecycleDecision`). The
transport is **injected**, so `import requests` never appears inside `mios_v5`.

### Delta 1 — the status list is shorter than the built one

| Spec | Built |
|---|---|
| `READY` | `READY` |
| `PENDING` | `WAIT` |
| `SENT` | `SENT` |
| `UPDATED` | *not a state* — see delta 2 |
| `SUPERSEDED` | `SUPERSEDED` |
| `FAILED` | `FAILED` |
| — | **`BLOCKED`** · **`DUPLICATE`** · **`EXPIRED`** |

The three the spec omits are **the gates, and the gates are the product**:
`BLOCKED` for a decision whose hash does not verify, `DUPLICATE` because `SENT`
is terminal, `EXPIRED` past `MAX_AGE_SECONDS = 300`. Adopting the spec's list
verbatim would delete them. It should not be adopted; `SPEC_ALIAS` the two
renames instead, exactly as Stage 72 did.

There is also a **second, separate axis** the spec collapses: delivery state
(`NOT_SENT · SENT · FAILED · RETRY · RATE_LIMIT`). *Should this leave MIOS* and
*did it arrive* are different questions, and one field cannot answer both.

### Delta 2 — "edit previous message" is built as a field, not a state

`DispatchDecision.edits` names the message to update, so `ENTER → TRAIL → EXIT`
edits one message instead of posting three. `UPDATED` as a *state* would lose
the distinction between "this dispatch edits message X" and "this dispatch is an
edit". Keep the field.

### Delta 3 — `DispatchPackage` triples the payload; that is 73.5's job

Spec asks for `telegram_payload` + `dashboard_payload` + `ai_payload` in one
object. Built: **one** `payload`, plus `record`, `edits`, `metadata`.

The dashboard does not need a payload — `ui/execution_panel.py` reads the
decision object directly. And `ai_payload` inside the dispatcher would put
export shaping inside the gateway, duplicating the stage the same roadmap
creates two boxes later. **One fact, one owner:** the dispatcher owns *may this
leave*; Stage 73.5 owns *what shape it leaves in*.

### Delta 4 — `dispatch_id` exists under another name

`DispatchDecision.id` (UUID4) + `decision_id` (the join key) + `hash` + `version`
+ `created_at`. Renaming to `dispatch_id` would be a contract break for no gain.

> **Recommendation:** no rebuild. If the spec's vocabulary matters, add a
> `SPEC_ALIAS` mapping and a section to `STAGE72_9_FROZEN.md`. The live
> validation gate (`freeze_ready: False`) is unaffected and still governs.

---

## 2 · Stage 73 — built, and the spec asks for six impossible fields

`mios_v5/trade_lifecycle.py`, `VERSION = "73.0"`.

### The states are built, under different names

| Spec | Built |
|---|---|
| Waiting | `WAIT_ENTRY` |
| Open | `ENTERED` / `HOLD` |
| Scale In | `ADD` |
| Trail | `TRAIL` |
| Partial Exit | `SCALE_OUT` |
| Full Exit | `EXIT` |
| Expired · Cancelled | `COMPLETE` · `ABORT` |

The spec omits `HOLD` and `ADD`, which exist and are used. Same treatment as
Stage 72: alias the names, do not restate the machine.

### ⛔ The blocker: `pnl · mfe · mae · drawdown · r_multiple · remaining_size`

**None of these exist, and none of them can be computed today.**

```python
MISSING_PRODUCERS = ("position_state", "fill_price")
```

`EntryDecision.state == "ENTER"` means *Stage 72 concluded an entry was
executable*. It does not mean an order was placed, or filled, or at what price.
Nothing in MIOS reports a fill.

Computing PnL from `EntryDecision.entry` would assume a fill at the advisory
entry price. That single assumption then propagates into MFE, MAE, drawdown,
R-multiple and remaining size — six numbers that would look completely normal
while describing a position that may not exist. It is the precise failure mode
the architecture exists to prevent, and it would be invisible in the UI because
every field would be populated.

`remaining_size` needs a seventh thing that does not exist either: a lot count,
which needs capital and risk-per-trade.

> **This is not a Stage 73 amendment. It is a missing producer.**
>
> The unlock is a **position store** — a small table recording *order placed ·
> filled · fill price · quantity · closed*, written by whatever actually places
> orders. Stage 73's docstring already anticipates it: *"When a position store
> is added it becomes a third input and `position_known` starts reporting, with
> no other phase changing."*
>
> Until then, these six fields stay `UNKNOWN` **by name**. The correct next
> build here is the producer, not the consumer.

---

## 3 · Stage 73.5 — genuinely new, and the only clean greenfield

Nothing exports. `grep` finds no export module; `db/` writes rows for the app's
own use. Read-only, never calculates, mandatory schema version — all consistent
with existing rules, and `STAGE74_LEVEL_CONTRACT.md` is the pattern to copy.

### Three of the twelve export blocks have no owner

| Block | Owner |
|---|---|
| Market Snapshot · Trading Context | `trading_context` (`71.95.2`) |
| Entry Decision | `entry_engine` (`72.1`) |
| Trade Lifecycle | `trade_lifecycle` (`73.0`) |
| Liquidity Context | `liquidity` (`74.1.0`) — ⚠️ calibrating |
| Evidence · Explainability | `evidence.py`, `explain_decision.py` |
| Metadata · Conflict | `trading_context.coverage()`, `checklist.py` |
| **Dealer Context** | **none** — spread across `charm_pin`, `absorption`, `acceptance` |
| **Institutional Intent** | **none** |
| **Auction Context** | **none** |

An export layer can only export what has an owner. Those three either get a
named owner first, or they are exported as `UNKNOWN` with the gap recorded —
never assembled inside the exporter, which would make 73.5 a computation stage
and break its own first rule.

**Formats:** JSON and Markdown need nothing. CSV is fine. **Parquet needs a new
dependency** (`pyarrow`, tens of MB) — worth confirming before it goes in, since
nothing else in the tree needs it.

---

## 4 · Telegram Alert Engine — the sample alert quotes five values that do not exist

The renderer itself is a good idea and correctly scoped (no calculations,
`DispatchPackage` only). The sample is the problem:

| In the sample | Reality |
|---|---|
| `Targets 185.0 / 188.0 / 191.0` | **`MISSING_PRODUCERS = ("target2", "target3")`.** Stage 35 publishes one `next_target`. Rendering three would be fabricating levels in the one artifact a human acts on |
| `✓ Liquidity Acceptance` | Stage 74 is behind its calibration week and is **not** in `TradingContext` |
| `✓ Institutional Bias Bullish` | no owner |
| `✓ Dealer Support` | no owner |
| `PnL +2.8R` · `Remaining 50%` (exit alert) | no fills — see §2 |

A template renders whatever it is given; a template with a hard-coded three-line
target block renders three targets whether or not two of them are real. The
renderer must print `—` for `UNKNOWN` and **collapse the row**, and a test must
assert that an `UNKNOWN` never reaches a rendered alert as a number.

Everything else in the format — status, direction, strike, entry, stop, risk,
confidence, lifetime, the WHY list, warnings, dispatch id, version — maps to
fields that exist today.

---

## 5 · AI Analyst — correctly scoped, blocked on 73.5

Read-only, never calculates, never recommends, always quotes MIOS outputs. This
is the right contract and it needs no new guarantees from MIOS beyond what 73.5
provides. It cannot start before the export layer exists, and it should read
**exported files**, never the live objects — a reader with live access is one
refactor away from being a writer.

---

## 6 · On freezing the architecture

Agreed, with one amendment to the reasoning.

The roadmap says future work should *"improve the internals of existing stages
rather than adding new stages, unless they introduce a genuinely new market
dimension."* This audit found that the most valuable next thing is neither: it
is a **producer** — the position store. It adds no stage and no market
dimension; it makes six fields in an existing stage stop being `UNKNOWN`.

So the freeze rule is better stated as:

> New **stages** need a new market dimension.
> New **producers** need only a fact that currently has no writer.

That distinction is what keeps `MISSING_PRODUCERS` from being a permanent
excuse. Every entry in it is a producer waiting to be built, not a limitation.

---

## Order of work this audit supports

1. **Position store** — unblocks 6 fields in Stage 73 and every PnL figure in
   the UI and the alerts. Highest value, no new stage.
2. **Stage 73.5 export layer** — with `UNKNOWN` for the three unowned blocks.
3. **Telegram alert renderer** — after 73.5, so it renders exported shapes.
4. **AI Analyst** — reads exported files only.
5. **Owners for Dealer Context · Institutional Intent · Auction Context** —
   each a genuine new market dimension, each its own audit.

Two gates from earlier work still bind and are unchanged by this roadmap:
Stage 74's calibration week must complete before injection, and Stage 72.9 stays
`transport=None` until its live validation moves `freeze_ready` to `True`.
