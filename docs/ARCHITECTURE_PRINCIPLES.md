# MIOS Architecture Principles

**Binding. These outrank convenience, and they outrank "helpful" refactors.**

The one that governs the rest:

> **MIOS V5 is the computation layer. MIOS V6 is the intelligence layer.**
> V6 must never become a second analytics engine. It interprets, correlates and
> explains the canonical outputs V5 produces — it never recomputes them.

The failure this prevents is not waste. It is **two implementations of the same
market logic disagreeing**, in a system that still looks coherent from outside.

---

## 1 · Single source of truth

Every market fact has exactly one owner.

| Fact | Owner |
|---|---|
| Buy/sell split, CVD, CBV, CSV | `indicators/order_flow.py` |
| Money Flow Profile | `indicators/money_flow_profile.py::calculate_money_flow_profile` |
| Candle Delta Volume | `indicators/volume_delta.py::calculate_volume_delta` |
| VPFR | `vob_minimal.py::compute_vpfr` |
| VOB | `vob_minimal.py::analyze_vob_volume` |

`mios_v5/order_flow_snapshot.py::OWNERS` is the machine-readable version.
No stage may recreate any of these.

## 2 · Never recalculate existing data

If V5 computes it, V6 consumes it. These must never exist:

```
calculate_cvd_v6()   money_flow_v6()   vpfr_v6()   vob_v6()
```

Enforced by `test_no_duplicate_order_flow_engine_exists`
(`mios_v5/tests/test_order_flow.py`), which fails the build on any
`def <indicator>_v6(`.

## 3 · One calculation → many consumers

```
Calculation → published once → shared object → unlimited consumers
```

Never four parallel calculations. If two places need the same number, one of
them publishes and the other reads.

## 4 · No hidden logic

An engine that needs Money Flow, CVD, VPFR, Volume or VOB **receives them as
parameters**.

```python
Stage43.run(order_flow_snapshot)        # good
Stage43.run()                            # bad — reaches into session_state
```

Hidden inputs cannot be tested, replayed, or explained. An engine whose inputs
are invisible will eventually be wrong in a way nobody can reconstruct.

## 5 · Engines never own indicators

Indicators describe markets. Engines interpret indicators.

```
Indicator → Engine        ✅
Engine → Indicator        ❌
```

## 6 · Preserve the observational rule

No refactor may change Entry, Guardian, Decision, Alerts or Confidence.
**Only duplication is removed. Behaviour stays identical.**

Prove it, don't assert it: transcribe the original formula, run both against the
same input, assert equality. See `test_the_primitive_reproduces_every_original_site`.

## 7 · Backward compatibility

Every dashboard, Telegram message, API and alert keeps working. Internal
architecture may change; the outside may not notice.

## 8 · Publish everything once

One `OrderFlowSnapshot` carrying Money Flow · CVD · CSV · CBV · Delta ·
Buy Volume · Sell Volume · Volume · VPFR · VOB. Engines read only this object.

## 9 · Fail fast — never invent market data

An unmeasured fact is `MISSING`, never `0`.

Zero is a **market fact** — perfectly balanced flow. Asserting one that was
never observed is fabricating data, and the consumer cannot tell the difference.
`MISSING` is falsy and never equal to `0`, so a caller that forgets to check
gets a sentinel rather than a plausible lie.

```python
from indicators.order_flow import MISSING, is_missing
assert MISSING != 0      # the whole point
assert not MISSING       # falsy, so `if not x:` still guards
```

## 10 · Performance

A refactor must **reduce** calculations, session lookups, duplicated formulas
and CPU. Never increase them. Measure before and after.

## 11 · Deliver the audit

Every consolidation ships with a before/after count. See
`docs/AUDIT_ORDER_FLOW_V5.md` and the refactor audit in the PR body.

## 12 · Every computed decision must be inspectable

> If any engine influences a **score, recommendation, timing, risk, trail or
> execution state**, the trader must be able to see the originating engine,
> its inputs, and its current output. **Hidden influence is prohibited.**

This is broader than a display convention. An engine whose effect is felt but
whose read is invisible cannot be distrusted at the moment it is wrong — the
trader sees a number move and has no way to ask *which engine did that*.

The failure that produced this rule: Stage 37 Market Energy was shaping the
Opportunity Matrix's lifetime estimate and feeding its risk drivers on every
cycle, while the panel cell labelled "Energy" showed something else entirely
(the rotation read). The engine was acting on the screen and absent from it.
Nothing was miscomputed; the trader simply could not see what was moving the
answer.

It applies equally to Stage 44's flow-shift veto, Stage 47 and 54's stability
modifiers, Stage 69's session modifiers, Stage 71's opportunity scoring, and
anything added after them.

Two corollaries worth stating, because they are where this gets violated:

* **A modifier is an influence.** Multiplying a confidence by 0.8 is as much
  a decision as producing a bias, and the ×0.8 needs a visible owner.
* **Consumed-but-unpublished is the smell.** If a value is read inside a
  computation and appears in no panel, either surface it or stop reading it.

## 12a · One bridge, not thirty reads

*Added with Stage 71.95.*

A decision stage must consume **one object**, not the stages behind it.

```
Market  →  TradingContext  →  Stage 72  →  Trade Manager  →  Telegram
```

Reading stages directly produces four failures, and only the first is visible:
duplicated reads, versions that drift *inside a single cycle*, ordering
dependencies nobody wrote down, and a decision whose inputs cannot be
enumerated — which puts principle 12 out of reach, because you cannot show a
trader a list you cannot produce.

`mios_v5/trading_context.py` is that bridge. Three rules make it one:

1. **Every field declares `owner · stage · source`,** and `source` is the live
   dotted path the value was read from — not a comment. A stale path yields
   `UNKNOWN` instead of a wrong number.
2. **No two fields read the same path.** Two names for one fact drift. Where the
   spec wants a field that *is* another field's value, the context records a
   pointer (`ALIAS`), not a copy.
3. **Immutable, deep.** Frozen mappings and tuples all the way down, so two
   consumers in one cycle cannot see different values, and mutating a source
   after the build changes nothing.

The context calculates nothing, infers nothing, averages nothing. It transports.

---

## 13 · Non-negotiable

Restated because it is the one that decays quietest:

> V5 computes. V6 interprets. A year from now there must still be exactly one
> implementation of every piece of market logic in this system.

---

## Honest limits of the enforcement

The guard tests catch the *named* failure modes — a `*_v6()` function, an
`import requests` inside `mios_v5`, a reserved word in a migration. They cannot
catch someone reimplementing CVD inline under a different variable name inside a
render block. That is exactly how the six copies arose in the first place.

The durable defence is principle 3: if a number is worth computing, publish it,
and the next person will find it rather than rewrite it.
