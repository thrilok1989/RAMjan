# Stage 72 — Output Contract

*What `EntryEngine(ctx).run()` returns, and what every field is allowed to be.*

```python
from mios_v5.trading_context import build as build_context
from mios_v5.entry_engine import EntryEngine

ctx      = build_context(fr=…, matrix=…, premium=…, validation=…, structure=…,
                         behaviour=…)          # behaviour: Stage 71.85
decision = EntryEngine(ctx).run()
```

One argument in, one frozen object out. **No consumer of this contract needs to
inspect Stage 71 again.**

---

## 1 · `EntryDecision`

Immutable (`@dataclass(frozen=True)`); nested mappings are `MappingProxyType`.
Every field is either a real value or `UNKNOWN` — **never `0`, never `None`, and
never a default standing in for a measurement that did not happen.**

| Field | Type | Values | Source |
|---|---|---|---|
| `state` | `str` | one of `decision_v2.STATES` — **imported, never restated** | Stage 52 vocabulary |
| `label` | `str` | Stage 52's emoji label for `state` | derived from `state` |
| `readiness` | `str` | `READY` · `NOT_READY` · `UNKNOWN` | Phase 1 |
| `score` | `int \| UNKNOWN` | 0–100 | Phase 2 |
| `confidence` | any | Stage 71's number | `opportunity.confidence` |
| `quality` | any | `A+ · A · B · C · AVOID` | `opportunity.trade_quality` |
| `entry_type` | `str` | one of `ENTRY_TYPES`, or `UNKNOWN` | `opportunity.entry_type` |
| `side` | `str` | `CALL` · `PUT` · `UNKNOWN` | `opportunity.best_side` |
| `strike` | number | the trader's selected strike for `side` | `premium.selected_*` |
| `horizon` | `str` | scalp…swing | `opportunity.best_horizon` |
| `timing` | `str` | Stage 71.5's word | `opportunity.timing` |
| `risk` | `str` | `Very Low · Low · Medium · High · Extreme · UNKNOWN` | Phase 4 |
| `reward` | `str` | `Poor · Average · Good · Excellent · UNKNOWN` | Phase 5 |
| `entry_zone` | `str` | `Early · Optimal · Late · Missed · UNKNOWN` | Phase 3 |
| `entry` | number \| `UNKNOWN` | premium price | Premium Structure / Stage 42 level |
| `stop` | number \| `UNKNOWN` | premium price | Premium Structure support |
| `targets` | mapping | `{target1, target2, target3}` | Stage 35 · **see §3** |
| `risk_reward` | number \| `UNKNOWN` | only when entry, stop *and* target1 are known | Phase 7 |
| `lifetime` | `str` | Stage 71.5's hold band | `opportunity.lifetime` |
| `reason_codes` | tuple[`Reason`] | ≤ 5 after `top_reasons` | Phase 9 |
| `top_trigger` | `str` | the strongest reason's label | Phase 9 |
| `warnings` | tuple[`str`] | de-duplicated, ordered | Phase 9 |
| `invalidations` | tuple[`str`] | what would kill the trade | Stage 35 · 42 · 47 |
| `telegram` | mapping | **prepared, never sent** | Phase 8 |
| `metadata` | mapping | reasons for every phase verdict, weights, context version/cycle/coverage | — |
| `behaviour` | mapping | Stage 71.85's ten published facts for `side`, **read from the context** — added at `72.1` | `premium.behaviour*` |
| `advisory_only` | `True` | always | — |

### `Reason`

```python
Reason(code="VALIDATION_VALID", label="Validation VALID", weight=100,
       owner="Stage 71.8 — Strike Validation",
       source="validation.bridge.premium_validation")
```

`owner` and `source` are **copied from the context field**, not written here.
Every reason therefore traces to a stage and a dotted path, and a reason this
stage could not attribute cannot be produced.

---

## 2 · The state machine

`decision_v2.STATES`, imported:

```
WAIT · ENTRY_READY · FLOOR_CONFIRMED · CEILING_CONFIRMED · ENTER · HOLD
SCALE_IN · SCALE_OUT · TRAIL · EXIT · COMPLETE · ABORT
```

`_checked()` raises if Stage 72 ever emits a state outside that tuple — the
import is enforcement, not decoration.

The Stage 72 specification named three states Stage 52 does not implement.
`SPEC_ALIAS` maps them rather than inventing them:

| Spec | Actual |
|---|---|
| `WATCH` | `WAIT` — Stage 52 has one pre-entry state |
| `PARTIAL_EXIT` | `SCALE_OUT` |
| `FULL_EXIT` | `EXIT` |

### Which states this stage can currently emit

`WAIT` · `ENTRY_READY` · `ENTER` · `ABORT`.

The rest (`HOLD`, `TRAIL`, `SCALE_IN`, `SCALE_OUT`, `EXIT`, `COMPLETE`,
`FLOOR_CONFIRMED`, `CEILING_CONFIRMED`) describe a position **already open**.
Stage 72 answers *is there an executable trade right now* and has no position
input, so emitting them would be asserting a trade it cannot see. They belong to
the Trade Manager.

---

## 3 · ⚠️ `target2` and `target3` are permanently `UNKNOWN`

Stage 35 publishes **one** `next_target`. `MIOS_BIBLE.md` Part 15 records this
and nothing has changed:

> *No T1/T2/T3 target ladder — Stage 35 produces one `next_target`; a ladder is
> new computation, not a rendering.*

Deriving them — 1.5R, 2R, the next volume node — would be Stage 72 inventing
market levels. Both are listed in `MISSING_PRODUCERS` and surface in
`metadata.missing_producers`.

`risk_reward` is computed **only** when entry, stop and target1 are all known,
and both legs are positive. It is arithmetic over three context values, not a
market measurement.

---

## 4 · Telegram payload

```python
decision.telegram
# {"ready": True, "state": "ENTRY_READY", "side": "CALL", …,
#  "advisory_only": True, "sent": False,
#  "note": "prepared by Stage 72 — sending belongs downstream"}
```

Every field is **copied from the decision**, so the message cannot contain a
value the decision did not make. `ready` means *the payload is well-formed*, not
*this should go out*. Stage 72 imports no network client and has no side
effects; sending is a downstream decision behind a switch a human flipped.

---

## 5 · Phase 10 · `summary()`

```python
{"trade": bool, "state", "label", "why": [...], "why_not": [...],
 "confidence", "quality", "risk", "reward", "best_horizon", "side",
 "strike", "timing", "warnings", "advisory_only"}
```

`why` and `why_not` are both present on **every** decision. A stage that
explains itself only when it acts teaches a trader to read the absence of
explanation as permission.

---

## 6 · Guarantees

| Guarantee | Enforced by |
|---|---|
| Consumes `TradingContext` only | import-graph test — no producer, no engine, no network |
| Never sends anything | no network client importable |
| Every output field has one owner | reasons carry the context's `owner`/`source` |
| `UNKNOWN` never becomes `0` | scale tables return `None` → the input leaves the denominator |
| Immutable | frozen dataclasses + `MappingProxyType`, deep |
| State is always valid | `_checked()` raises on a non-Stage-52 state |
| Every recommendation is reconstructable | `metadata` carries weights, components, and the context's version, cycle and coverage |
| Advisory | `advisory_only` on the decision **and** the payload |

---

## 7 · What a downstream consumer may assume

* **The object is complete.** Every field exists on every decision; absence is
  expressed as `UNKNOWN`, never as a missing key.
* **The object is stable.** It is frozen, and the context behind it is frozen,
  so two consumers in one cycle read identical values.
* **The object is self-describing.** `metadata.context_cycle` and
  `context_coverage` say which cycle produced it and how much of the analysis
  was actually available — a decision made on a thin context is visibly thin.
* **The object is not an instruction.** `state` is a reading. Acting on it is
  the consumer's decision to make and to log.
