# Stage 72 — FROZEN

*Version `72.1`. The execution contract is closed. Future work extends around
this stage, not inside it — and where it cannot, the version moves and the
change is recorded. See [Amendment 1](#amendment-1--720--721-stage-7185).*

---

## Purpose

Stage 72 answers one question and stops:

> **Is there an executable trade right now?**

It converts analysis into an execution decision. It does not decide direction
(Stage 71), which strike (Stage 71.8), or which premium has energy (Stage 71.7)
— it reads those verdicts. It does not manage anything after the decision.

```
Market → TradingContext → Stage 72 → Trade Manager → Telegram
                          ↑ frozen here
```

---

## Owners

| Concern | Owner |
|---|---|
| Analysis, all of it | Stages 0–71.8 |
| Consolidating analysis | **Stage 71.95** — `TradingContext` |
| **The execution decision** | **Stage 72** — this stage |
| Position · PnL · trailing · scaling · exit | **Stage 73+** — not built |
| Learning · analytics | Stages 55–60, reading stored decisions |
| Sending a message | downstream, behind a switch a human flipped |

Stage 72 owns **the execution decision only**. Every field it publishes is
either its own verdict or a value carried from the context with the context's
owner attached.

---

## Inputs

Exactly one:

```python
decision = EntryEngine(ctx).run()      # ctx: TradingContext
```

The module imports **two** local modules — `trading_context` and `decision_v2` —
and a test asserts that set exactly. It cannot reach Stage 42, the Opportunity
Matrix, Premium Structure or any engine directly. No network client is
importable. It never touches `session_state`.

---

## Outputs

`EntryDecision`, frozen. Full field table in
[`STAGE72_OUTPUT_CONTRACT.md`](STAGE72_OUTPUT_CONTRACT.md).

Every field is a real value or `UNKNOWN` — never `0`, never `None`, never a
default standing in for a measurement that did not happen.

Three views:

| Call | For |
|---|---|
| `decision.to_dict()` | storage · replay · audit |
| `decision.summary()` | a human — carries `why` **and** `why_not` on every decision |
| `decision.telegram` | a prepared payload, `sent: False` |

---

## State Machine

`decision_v2.STATES`, **imported, never restated**:

```
WAIT · ENTRY_READY · FLOOR_CONFIRMED · CEILING_CONFIRMED · ENTER · HOLD
SCALE_IN · SCALE_OUT · TRAIL · EXIT · COMPLETE · ABORT
```

`_checked()` raises if Stage 72 emits anything outside that tuple.

**Stage 72 emits only the four pre-entry states**: `WAIT · ENTRY_READY · ENTER ·
ABORT`. The rest describe a position already open, which this stage has no input
for — they belong to Stage 73.

The spec that produced this stage named three states Stage 52 does not
implement. `SPEC_ALIAS` maps them rather than inventing them:

| Spec name | Actual |
|---|---|
| `WATCH` | `WAIT` |
| `PARTIAL_EXIT` | `SCALE_OUT` |
| `FULL_EXIT` | `EXIT` |

---

## Scoring

Ten weights, every one reading a **different** context field:

| Field | Weight |
|---|---|
| `strike.validation` | 2.5 |
| `energy.energy` | 2.0 |
| `opportunity.opportunity_score` | 2.0 |
| `premium.premium_score` | 1.5 |
| `opportunity.confidence` | 1.5 |
| `strike.liquidity` | 1.5 |
| `energy.spike_probability` | 1.0 |
| `risk.validity` | 1.0 |
| `htf.alignment` | 1.0 |
| `market.stability` | 1.0 |

Strike validation leads because a correct read on an unvalidated strike is the
one failure being right cannot fix. Opportunity score is third — it is the
strongest *analysis* input, and this is not an analysis stage.

**Unknown inputs leave the denominator.** A decision resting on three of ten
inputs is not a weak decision, it is a barely-informed one, and the two must not
render as the same number. Fewer than four reporting → `WAIT`.

**Gates are checked before the score**, and cannot be outvoted: entries frozen,
tape shocked, strike invalid, strike illiquid, Stage 51 rejection.

---

## Telegram Contract

```python
decision.telegram
# {"id", "version", "created_at", "hash",
#  "ready": bool, "state", "side", "strike", "horizon", "timing",
#  "entry", "stop", "targets", "risk", "reward", "confidence", "quality",
#  "reasons": (...), "warnings": (...),
#  "advisory_only": True, "sent": False,
#  "note": "prepared by Stage 72 — sending belongs downstream"}
```

* Every field is **copied from the decision** — the message cannot contain a
  value the decision did not make.
* `ready` means *the payload is well formed*, not *this should go out*.
* Identity comes first so a message can always be joined back to its decision.
* **Stage 72 sends nothing.** No network client is importable.

---

## Decision Contract

Four identity fields, minted once per decision and never rewritten:

| Field | Value |
|---|---|
| `id` | UUID4, unique per decision |
| `version` | `"72.0"` — the frozen contract |
| `created_at` | UTC ISO 8601, seconds, single timestamp |
| `hash` | SHA-256 over `HASH_FIELDS` |

```python
HASH_FIELDS = ("id", "version", "state", "confidence", "score", "created_at")
```

The hash covers **identity plus verdict**, deliberately not the whole object: a
digest that changed when a reason's wording changed would make the integrity
check cry wolf until someone stopped reading it. Values are stringified first,
so a score stored as `83` and one stored as `"83"` hash the same — they are the
same decision.

```python
decision.verify()    # True → the record is as it was made
decision.identity()  # the join key Stage 73+ carry forward
```

**Stage 73+ never mint their own id and never restate the timestamp.** They
extend a decision by reference.

---

## Immutability Rules

1. `EntryDecision` is `@dataclass(frozen=True)`. Assigning any field raises.
2. Immutability is **deep** — nested mappings are `MappingProxyType`, sequences
   are tuples, all the way down. `targets`, `telegram`, `metadata` and
   `metadata["components"]` all reject writes.
3. `Reason` is frozen too.
4. The `TradingContext` behind the decision is itself deep-frozen, so mutating a
   source after the fact changes nothing.
5. **A decision represents history.** A consumer that could edit one could
   rewrite what was decided, and every replay, audit and learning row built on
   it would describe something that never happened.

---

## Versioning

`VERSION = "72.0"`.

**Bump only for a breaking change to `EntryDecision`** — a removed field, a
changed type, a redefined value. Never for a fix inside a phase.

A consumer replaying a stored decision reads `version` to know which shape it
was written against. `decision.version` and `metadata["version"]` are the same
value, and a test asserts it.

---

## Known limitations

| Limitation | Why |
|---|---|
| `target2` and `target3` are permanently `UNKNOWN` | Stage 35 publishes one `next_target`. A ladder is new computation, and deriving one from R-multiples would be fabricating levels. Listed in `MISSING_PRODUCERS` |
| Only four states are ever emitted | The other eight describe an open position; Stage 72 has no position input |
| `risk_reward` is often `UNKNOWN` | It needs entry, stop **and** target1, with both legs positive |
| Entry and stop are premium levels from Premium Structure | There is no delta-based conversion from NIFTY points anywhere in MIOS, and inventing one would be a new market computation |
| The entry-zone table is coarse | It reads two context fields against a lookup. Anything finer would mean measuring price behaviour, which is another stage's job |
| No sizing, no lot count | Position sizing needs capital and risk-per-trade, neither of which is in the context. Stage 73 |

---

## Future extension points

Everything below extends Stage 72 **from outside**. None of it modifies it.

| Want | Where it goes |
|---|---|
| Hold · trail · scale · partial and full exit | **Stage 73** — Trade Manager, consuming `decision.identity()` |
| Position and PnL tracking | Stage 73 |
| Position sizing | Stage 73, once capital is in the context |
| Actually sending a message | downstream of the payload, behind a human-flipped switch |
| Outcome attribution | Stages 55–60, joining on `decision.id` |
| Replay | rebuild a `TradingContext`, re-run, compare `hash` |
| A richer target ladder | give Stage 35 a producer for T2/T3 — then this stage reads them, unchanged |
| New execution evidence | add the field to `TradingContext`, then add a weight |

> ⛔ **Frozen.** Do not change entry scoring, weights, gates, recommendation
> logic, the Telegram decision, trading logic, Stage 71 outputs or
> `TradingContext` ownership inside this stage. Bug fixes only. Everything else
> is Stage 73+.

---

## Amendment 1 — `72.0` → `72.1` (Stage 71.85)

*The freeze is not broken by this; it is exercised by it.*

Stage 71.85 — Premium LTP Behaviour — publishes what the selected premium is
doing at its own support/resistance, and the specification for it says: *"Do NOT
modify Stage 72 scoring philosophy. Simply add one more evaluation component."*

That is exactly the path this document's own extension table already named:

> New execution evidence → add the field to `TradingContext`, then add a weight.

But the line above it says **do not change weights**, and adding one is a change
to them. Both cannot be true at once, so the version moves.

### What changed

| | |
|---|---|
| `VERSION` | `72.0` → **`72.1`** |
| `WEIGHTS` | +1 entry — `premium.behaviour`, weight `1.5`. Ten became eleven; no existing weight moved |
| `_SCALES` | +1 entry — the six behaviours mapped to 0–100, with `Neutral` → `None` |
| `EntryDecision` | +1 field — `behaviour`, a mapping, defaulting to empty |
| `telegram()` | +7 keys, all copied from that mapping |
| dispatcher | `SUPPORTED_DECISION_VERSIONS` = `("72.0", "72.1")` |

### What did not change

The scoring **philosophy** is untouched: the same weighted mean, the same
unknown-excluded denominator, the same gates, the same Stage 52 states, the same
hash fields, the same identity. Eleven components report into the arithmetic
that ten reported into. `premium.premium_score` still weighs `1.5` — Stage
71.8's contribution was not reduced to make room.

`Neutral` maps to `None` rather than to 50. Stage 71.85 emits `Neutral` when the
evidence did not agree enough to name a fight, which is an *absence* of a read —
so it leaves the denominator exactly as an unreported input does. Scoring it 50
would let "we could not tell" quietly hold the score up.

### Why a bump rather than an edit

A stored `72.0` decision must keep replaying against the shape it was written
for, and a consumer must be able to tell which shape it is holding. The
dispatcher therefore accepts both: the new payload keys are additive, so a
`72.0` payload simply does not have them rather than having them wrong.

> A freeze that can be edited without a version bump is not a freeze; a freeze
> that can never change is a museum. The bump is the difference.

The rule for the next amendment is the same one: **the contract version moves,
the previous version stays supported, and this section gains an entry.** An
un-versioned edit to Stage 72 is still forbidden.
