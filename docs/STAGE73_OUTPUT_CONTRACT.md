# Stage 73 — Output Contract

*What `TradeLifecycle(decision, ctx).run()` returns.*

```python
decision  = EntryEngine(ctx).run()            # Stage 72, frozen
lifecycle = TradeLifecycle(decision, ctx).run()
```

Two objects in, one frozen object out. **The `EntryDecision` is never mutated** —
this stage builds a new record that *references* `decision.id`.

---

## 1 · `TradeLifecycleDecision`

Frozen dataclass; nested mappings are `MappingProxyType`, sequences are tuples.
Every field is a real value or `UNKNOWN` — never `0`, never a default.

| Field | Values | Phase |
|---|---|---|
| `id` | UUID4, this lifecycle record | Identity |
| `decision_id` | the `EntryDecision.id` this manages | Identity |
| `version` | `"73.0"` | Identity |
| `created_at` | UTC ISO 8601, seconds | Identity |
| `hash` | SHA-256 over `HASH_FIELDS` | Identity |
| `state` | one of `STATES` — **Stage 73's own** | 3 |
| `action` | exactly one of `ACTIONS` | 3 |
| `intent` | `ENTERED_INTENT · NO_ENTRY · ABORTED · UNKNOWN` | 1 |
| `position_known` | ⚠️ **always `UNKNOWN`** — see §3 | 1 |
| `health` | `Excellent · Good · Average · Poor · Critical · UNKNOWN` | 2 |
| `trail` | `No · Soft · Normal · Aggressive Trail · UNKNOWN` — a **band** | 4 |
| `scale` | `Add · Reduce · Neither · UNKNOWN` | 5 |
| `exit_reason` | one of `EXIT_REASONS`, `None`, or `UNKNOWN` | 6 |
| `confidence` `quality` `risk` | carried from the `EntryDecision` | — |
| `reason_codes` | tuple[`Reason`], ≤5 via `top_reasons` | 7 |
| `top_trigger` | the exit reason if one fired, else the strongest reason | 7 |
| `warnings` | de-duplicated tuple | 7 |
| `telegram_payload` | prepared, `sent: False` | 8 |
| `metadata` | a reason for every phase verdict, weights, components, the entry's version/state, the context's version/cycle/coverage | — |
| `advisory_only` | `True` | — |

### `Reason`

`{code, label, weight, owner, source}` — `owner` and `source` are **copied from
the context field**, so every reason traces to a stage and a dotted path.

---

## 2 · State machine — Stage 73's own

```
WAIT_ENTRY · ENTERED · HOLD · ADD · SCALE_OUT · TRAIL · EXIT · COMPLETE · ABORT
```

Entry states are **not** reused. Stage 52's machine describes getting *into* a
trade; this one describes being *in* one, and sharing a vocabulary would make
`WAIT` mean two different things one stage apart. `_checked()` and
`_checked_action()` raise on anything outside `STATES` / `ACTIONS`.

`action` is **exactly one** of `HOLD · ADD · SCALE_OUT · TRAIL · EXIT · ABORT`,
chosen by a priority ladder rather than a score: an exit trigger cannot be
outvoted by good health, and a freeze is not something to trail through.

| Rung | Condition | State · Action |
|---|---|---|
| 1 | no entry intent | `WAIT_ENTRY` · `HOLD` |
| 2 | Stage 72 aborted | `ABORT` · `ABORT` |
| 3 | `risk.freeze` | `ABORT` · `ABORT` |
| 4 | an exit trigger fired | `COMPLETE` (stop/target) or `EXIT` · `EXIT` |
| 5 | scale says Reduce | `SCALE_OUT` · `SCALE_OUT` |
| 6 | scale says Add | `ADD` · `ADD` |
| 7 | trail is Normal/Aggressive | `TRAIL` · `TRAIL` |
| 8 | health unknown | `ENTERED` · `HOLD` |
| 9 | otherwise | `HOLD` · `HOLD` |

---

## 3 · ⚠️ `position_known` is always `UNKNOWN`

`EntryDecision.state == "ENTER"` means Stage 72 *concluded* an entry was
executable. It does not mean an order was placed or filled, and nothing in MIOS
reports that yet.

`intent` reports what Stage 72 decided. `position_known` reports whether a
position exists — and the honest answer is `UNKNOWN`, unconditionally.
`position_state` and `fill_price` are listed in `MISSING_PRODUCERS` and named in
the warnings on every decision.

When a position store is added it becomes a third input and this field starts
reporting, **with no other phase changing**: every other phase reads the tape
and the levels, not the fill.

---

## 4 · Trailing returns a band, not a level

`adaptive_trail` belongs to Stage 52 and the stop level is consumed from
`EntryDecision.stop`, which `metadata.stop_consumed` echoes. "Trail
aggressively" is a lifecycle judgement; "trail to 118.4" is a computation with
an owner elsewhere. A consumer wanting a number applies the band to that stop.

---

## 5 · Exit reasons report, never predict

First trigger wins, in this order:

```
Stop Hit · Target Hit · Shock · Illiquidity · Structure Failure ·
Energy Collapse · Expiry · Manual
```

`Stop Hit` outranks `Shock` deliberately: a stop hit during a shock is still a
stop hit, and a learning row that recorded the shock instead would blame the
tape for a level doing its job.

Where no live premium is available, `Stop Hit` and `Target Hit` cannot be
checked and `exit_reason` is `UNKNOWN` rather than `None` — "not checked" and
"checked, nothing fired" are different facts.

---

## 6 · Health scoring

Eight inputs, one context field each, unknowns leaving the denominator:

| Field | Weight |
|---|---|
| `market.stability` | 2.5 |
| `energy.energy` | 2.0 |
| `premium.premium_score` | 2.0 |
| `strike.liquidity` | 1.5 |
| `energy.shift` | 1.0 |
| `opportunity.trade_risk` | 1.0 |
| `opportunity.timing` | 1.0 |
| `risk.validity` | 1.0 |

Stability leads because it is the only input that can invalidate the read the
trade was opened on. A position graded on two of eight is not unhealthy — it is
barely observed, and `reporting` travels with the band to say so.

---

## 7 · Guarantees

| Guarantee | Enforced by |
|---|---|
| Two inputs only | import-graph test — `entry_engine` and `trading_context` |
| `EntryDecision` never mutated | frozen upstream; a test verifies its hash after a lifecycle run |
| Immutable output | frozen dataclasses + `MappingProxyType`, deep |
| Hash deterministic | `lifecycle_hash()` is a pure module function |
| Sends nothing | no network client importable; `sent: False` |
| Every reason traceable | `owner`/`source` copied from the context |
| Reconstructable | `metadata` carries weights, components and both upstream versions |
| Owns no position, PnL or sizing | asserted — no such field may exist on the output |
