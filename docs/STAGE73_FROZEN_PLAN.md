# Stage 73 — Freeze Plan

*Stage 73 is **built, not yet frozen**. This is what has to be true before it
is, and what changes are legitimate until then.*

---

## Why it is not frozen yet

Stage 72 was frozen the moment its contract was complete, because every input it
needs exists. Stage 73 is different: **its first phase has no producer.**

`position_known` is `UNKNOWN` unconditionally, because nothing in MIOS reports
whether an order was filled. Freezing now would freeze a contract whose most
important question is unanswerable, and the freeze would have to be broken the
day a position store arrives.

So the shape is frozen in intent and the module is stable — but the version
stays at `73.0` and the door stays open for exactly one change.

---

## The one change that is expected

**A third input: a position record.**

```python
TradeLifecycle(decision, ctx, position=...)   # not yet
```

When it lands:

* `position_known` starts reporting instead of returning `UNKNOWN`.
* `MISSING_PRODUCERS` empties.
* `intent` stays exactly as it is — it reports what Stage 72 decided, which is
  a different fact and remains worth carrying.
* **No other phase changes.** Health, trail, scale and exit all read the tape
  and the levels, neither of which the fill affects.

That last line is the design goal, and it is testable today: if adding a
position input requires touching Phase 2, 4, 5 or 6, this stage was built wrong.

---

## Freeze criteria

Stage 73 is frozen when all of these hold:

| # | Criterion | Status |
|---|---|---|
| 1 | Two-input rule enforced by test | ✅ |
| 2 | Output immutable, deep | ✅ |
| 3 | Identity fields present, hash deterministic | ✅ |
| 4 | `EntryDecision` provably unmutated | ✅ |
| 5 | Lifecycle states distinct from entry states | ✅ |
| 6 | Every reason traces to a context field | ✅ |
| 7 | Telegram prepared, never sent | ✅ |
| 8 | Owns no position, PnL, sizing or broker concept | ✅ |
| 9 | **A position producer exists**, or the absence is accepted permanently | ❌ **blocking** |
| 10 | Two weeks of logged lifecycle decisions, per the observational rule | ❌ **blocking** |

Criterion 10 is the same rule that governs every other promotion in this
codebase: *nothing influences a decision until it has proven itself.* A
lifecycle engine that has never managed a logged trade has not proven anything,
however green its tests are.

---

## Until then — what may change

**May change** (bug fixes and the position input only):

* the health weights, if live data shows one input dominating wrongly
* the exit-trigger order, if a real sequence proves it wrong
* the trail bands' thresholds
* adding the position input as described above

**May not change**, now or after the freeze:

* the two-input rule
* the state or action vocabularies
* identity, hashing or immutability
* `EntryDecision` — it is frozen upstream and this stage may not touch it
* anything belonging to Stage 71 or 72

---

## What comes after, and where it goes

| Want | Stage |
|---|---|
| Position sizing, lot count | a later stage, once capital is an input |
| PnL, realised and unrealised | a later stage |
| Broker integration, order placement | outside MIOS |
| Outcome attribution per lifecycle row | **74 Learning**, joining on `decision_id` |
| Aggregates across trades | **75 Analytics** |
| Re-running a stored context and comparing hashes | **76 Replay** |
| Actually sending a payload | downstream, behind a human-flipped switch |

Stage 74+ consume `lifecycle.identity()` and join on `decision_id`. They never
reach around Stage 73, exactly as Stage 73 never reaches around Stage 72.

---

## The rule this stage inherits

> Every engine ships observational-only and logged. Nothing influences a
> decision until it has proven itself.

Stage 73 is `advisory_only`, sends nothing, and moves no money. It stays that
way until criteria 9 and 10 are met and a human flips a constant.
