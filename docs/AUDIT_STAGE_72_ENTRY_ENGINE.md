# Stage 72 — Entry Engine: what the context supplies, and what it does not

*Audit taken at `eef9822`, before any Entry Engine code was written. One
question per requirement: **can Stage 72 answer this from `TradingContext`
alone?***

---

## Verdict

**Three conflicts must be resolved before building, and one of them changes
TradingContext rather than Stage 72.**

1. The spec's state machine and Stage 52's **do not match** — three states in
   the spec do not exist, five of Stage 52's are not in the spec.
2. `TradingContext` as built **cannot answer Phases 3, 6 or 7**. Stage 42's
   reaction, Stage 71.5's timing and Stage 35's levels are not in it.
3. **`target2` and `target3` have no producer anywhere in MIOS.**

The fix for (2) is to extend the context, not to let Stage 72 reach around it.
That is what the bridge is for: a gap in the analysis authority is a gap to
fill, not a licence to bypass.

---

## 1. ⚠️ The state machine conflict

The instruction is *"reuse the existing Stage 52 state machine, do not invent
new states."* The spec then lists ten states, and Stage 52 implements twelve —
overlapping in seven.

| Spec asks for | Stage 52 (`decision_v2.STATES`) |
|---|---|
| WAIT | ✅ `WAIT` |
| **WATCH** | ❌ **does not exist** |
| ENTRY_READY | ✅ `ENTRY_READY` |
| ENTER | ✅ `ENTER` |
| SCALE_IN | ✅ `SCALE_IN` |
| HOLD | ✅ `HOLD` |
| TRAIL | ✅ `TRAIL` |
| **PARTIAL_EXIT** | ❌ — Stage 52 calls it `SCALE_OUT` |
| **FULL_EXIT** | ❌ — Stage 52 calls it `EXIT` |
| ABORT | ✅ `ABORT` |
| — | `FLOOR_CONFIRMED` · `CEILING_CONFIRMED` · `COMPLETE` |

`ROADMAP_V6.md` describes Stage 52 using the *spec's* vocabulary
(`… PARTIAL EXIT · FULL EXIT …`); the implementation used different words. The
drift is in the roadmap, not in this spec.

### Decision

**Stage 72 imports `decision_v2.STATES` and uses it verbatim.** "Do not invent
new states" is the binding half of the instruction, and inventing `WATCH`,
`PARTIAL_EXIT` and `FULL_EXIT` is exactly what adopting the spec's list would
be.

The spec's vocabulary stays reachable through a documented alias map
(`SPEC_ALIAS`), so a reader looking for `FULL_EXIT` finds `EXIT` rather than
nothing. `WATCH` maps to `WAIT` — Stage 52 has one pre-entry state and splitting
it here would give the two engines different machines.

---

## 2. ⛔ TradingContext cannot answer three phases

The Entry Engine may read nothing else, so a phase whose inputs are absent from
the context cannot be built at all.

| Phase | Needs | In context? |
|---|---|---|
| **3 · Entry Zone** | Stage 42 reaction · timing · premium behaviour · premium structure | ❌ **reaction absent** · ❌ **timing absent** · ✅ · ✅ |
| **5 · Reward** | quality · risk · structure | ❌ **quality absent** · ✅ `risk.risk` · ✅ |
| **6 · Entry Type** | existing structure — Momentum · Pullback · Breakout · Reversal · Continuation · Mean Reversion | ❌ **Stage 71.5 `opportunity_type` absent** |
| **7 · Trade Package** | entry · stop · targets · lifetime | ⚠️ entry/stop derivable from structure levels · ❌ **`next_target` absent** · ❌ **lifetime absent** |
| **9 · Explainability** | invalidations | ❌ **`invalidation` absent** |

Every one of these **exists in MIOS** and is simply not carried across the
bridge:

| Missing field | Real owner | Path |
|---|---|---|
| acceptance / reaction state | **Stage 42** | `fr.reaction.state` |
| reaction level | **Stage 42** | `fr.reaction_level` |
| timing | **Stage 71.5** | `matrix.best_trade.intel.timing.timing` |
| entry type | **Stage 71.5** | `matrix.best_trade.intel.type` |
| trade quality | **Stage 71.5** | `matrix.best_trade.intel.quality.grade` |
| trade risk | **Stage 71.5** | `matrix.best_trade.intel.risk.level` |
| lifetime | **Stage 71.5** | `matrix.best_trade.intel.lifetime.label` |
| next target | **Stage 35** | `fr.next_target` |
| invalidation | **Stage 35** | `fr.invalidation` |
| session conviction | **Stage 6** | `fr.session_conviction` |

### Decision

**Extend `TradingContext` with these ten fields.** Each has exactly one real
owner and a real path, so the ownership rules hold unchanged, and the
no-duplicate-path test will catch it if any of them collides with a field
already there.

Stage 72 then reads the context only — the success criterion — and the context
remains what it was designed to be: the single analysis authority.

`opportunity.trade_risk` is named apart from `risk.risk` deliberately. They are
**different facts**: Stage 4's is the tape's breakout risk, Stage 71.5's is this
horizon's trade risk. Same word, two owners, so they cannot share a name.

---

## 3. ⛔ `target2` and `target3` have no producer

`MIOS_BIBLE.md` Part 15 already records this:

> *No T1/T2/T3 target ladder — Stage 35 produces one `next_target`; a ladder is
> new computation, not a rendering.*

Nothing has changed. Stage 35 publishes **one** target and one invalidation.

### Decision

`target1` ← Stage 35's `next_target`. **`target2` and `target3` are `UNKNOWN`,
permanently and by name**, listed in `MISSING_PRODUCERS`.

Deriving them — 1.5R, 2R, the next HVN — would be Stage 72 computing market
levels, which is both new computation and outside its remit. The spec's own rule
settles it: *"UNKNOWN where unavailable. Never fabricate."*

The same applies to `risk_reward`: it needs entry, stop **and** target, so it is
computed only when all three are known and is `UNKNOWN` otherwise. That is
arithmetic over three context values, not a market measurement — the one
calculation this stage is justified in doing, and §5 records why.

---

## 4. What each output field traces to

| Output | Source (context field) | Owner |
|---|---|---|
| `state` | readiness + score + `risk.freeze` + `market.stability` | Stage 52 vocabulary |
| `confidence` | `opportunity.confidence` | Stage 71 |
| `quality` | `opportunity.trade_quality` | Stage 71.5 |
| `entry_type` | `opportunity.entry_type` | Stage 71.5 |
| `side` | `opportunity.best_side` | Stage 71 |
| `strike` | `premium.selected_call` / `selected_put` | Stage 71.8 |
| `horizon` | `opportunity.best_horizon` | Stage 71 |
| `timing` | `opportunity.timing` | Stage 71.5 |
| `risk` | `opportunity.trade_risk` + `risk.*` | Stage 71.5 · 44 · 51 |
| `reward` | `opportunity.trade_quality` + `strike.validation` + structure | Stage 71.5 · 71.8 |
| `entry_zone` | `market.acceptance` + `opportunity.timing` | Stage 42 · 71.5 |
| `stop` | `premium.premium_structure[side].support/resistance` | Premium Structure |
| `targets` | `risk.next_target` · then **UNKNOWN ×2** | Stage 35 |
| `lifetime` | `opportunity.lifetime` | Stage 71.5 |
| `reason_codes` | every field above, each carrying its `Field.owner` | — |
| `warnings` | `risk.freeze` · `market.stability` · `strike.liquidity` · `strike.agreement` | Stage 44 · 71.8 |
| `telegram_ready` | assembled from the above; **never sent** | — |

Every reason a decision emits carries the `owner` and `source` string the
context published, so `reason.owner` traces to a stage and `reason.source` to a
dotted path. Nothing in the output is anonymous.

---

## 5. The only calculations Stage 72 performs

Everything else is transport and comparison.

| Calculation | Why it is not a market measurement |
|---|---|
| **Entry score** — a weighted mean over context fields | Weighing existing verdicts is what a decision layer *is*. Every weight is documented in `WEIGHTS`, and unknown inputs leave the denominator rather than scoring zero |
| **Risk : reward** | arithmetic over three context values (`entry`, `stop`, `target1`), computed only when all three are known |
| **Readiness gate** | boolean composition of context fields — no new fact |
| **Entry zone band** | a comparison of two context fields against a table |

No price is derived, no bias is re-decided, no confidence is recomputed.

---

## 6. Rules this audit forces

1. **Import `decision_v2.STATES`** — do not restate the tuple (§1).
2. **Extend TradingContext by ten fields** rather than reaching around it (§2).
3. **`target2` / `target3` stay UNKNOWN by name** (§3).
4. **`opportunity.trade_risk` ≠ `risk.risk`** — two owners, two names (§2).
5. **Prepare the Telegram payload; never send it.** No network client may be
   imported, asserted on the import graph.
6. **Immutable output** — the same deep-freeze the context uses, so a decision
   handed to a future Trade Manager cannot be edited behind the engine's back.
