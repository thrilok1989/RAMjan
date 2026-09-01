# Stage 71.85 — Premium LTP Behaviour · output contract

*`mios_v5/premium_behaviour.py` · version `71.85.0` · `ADVISORY_ONLY = True`*

One question:

> **What is the selected premium's LTP doing right now at its own
> Support / Resistance?**

Not *where* the levels are — Stage 71.8 owns that. Not *whether to act* — Stage
72 owns that.

```
71.7 Premium Energy → 71.8 Premium Structure → 71.85 Behaviour → 71.95 Context → 72 Entry
```

---

## Entry points

```python
from mios_v5.premium_behaviour import analyse, build

one  = analyse(structure, energy, fr, side, validation)   # ONE premium
both = build(structures, energy, fr, validation)          # {"CALL": …, "PUT": …}
```

| Argument | What | Owner |
|---|---|---|
| `structure` | `premium_structure.analyse()` for **this side** | Stage 71.8 |
| `energy` | `premium_energy.build()`, whole | Stage 71.7 |
| `fr` | `final_read` | Stages 11 · 42 · 44 · 45 |
| `side` | `"CALL"` or `"PUT"` | the caller |
| `validation` | `strike_validation.build()` | Stage 71.8 |

Every argument is a **finished output**. Nothing is fetched, nothing is
measured, and `analyse()` never raises — an absent argument yields `Neutral`
with `UNKNOWN` strength.

`build()` calls `analyse()` twice with nothing shared between the calls. The
two sides are never compared, averaged or subtracted.

---

## The five computed fields

`COMPUTED_HERE = ("behaviour", "strength", "confidence", "momentum",
"top_reasons")`. Everything else in the output is transported, and `CONSUMED`
names the owner of each one.

### `behaviour` — exactly one of six

| State | Meaning |
|---|---|
| `Support Building` | the premium's floor is being defended |
| `Support Fading` | the floor is giving way |
| `Resistance Building` | the ceiling is being defended — the premium is capped |
| `Resistance Fading` | the ceiling is giving way |
| `Acceptance` | no level is engaged and the premium is holding its value area |
| `Neutral` | the evidence did not agree enough to name a fight |

Chosen from **one ledger on one axis**. Evidence votes on pressure against this
premium — `UP` or `DOWN` — and the engaged level turns the winner into a
behaviour:

| engaged level | `UP` wins | `DOWN` wins |
|---|---|---|
| support | `Support Building` | `Support Fading` |
| resistance | `Resistance Fading` | `Resistance Building` |

A level is *engaged* when it is within `_ENGAGED_PCT` (4%) of the LTP; the
nearer of the two wins. Order of resolution: insufficient evidence → `Neutral`
first, then no engaged level → `Acceptance` or `Neutral`, then the winner.
A tie is `Neutral`, never a coin toss.

### `strength` — five stars, or `UNKNOWN`

The winner's share of the reported evidence: `≥0.85` → ★★★★★, `≥0.72` → ★★★★☆,
`≥0.62` → ★★★☆☆, `≥0.55` → ★★☆☆☆, else ★☆☆☆☆.

`Neutral` emits `UNKNOWN`, not one star. Neutral is the *absence* of a read;
grading it would grade nothing.

### `confidence` — `decision._grade`, imported

`A+ · A · B · C · UNKNOWN`. Two numbers on the 1–5 scale `_grade` already
speaks, averaged: **agreement** (how one-sided) and **coverage** (how many
signals, saturating at eight). Stage 44 then caps: `SHOCK` → ≤2.0,
`UNSTABLE` → ×0.85.

There is no second grading ladder. `_grade` is imported from `mios_v5.decision`
and a test asserts identity, not equality.

### `momentum` — exactly one of five

`Accelerating · Building · Holding · Fading · Exhausting`, or `UNKNOWN`.

Stage 71.7's shift state maps directly; `accelerating = True` promotes
`Building` → `Accelerating`; `Compressing` maps to `Holding` because coiled
energy is stored, not spent. **Exhaustion outranks everything** — Stage 50's
`exhausted` pressure or a Stage 71.8 volume climax gives `Exhausting` whatever
the shift says. With no shift, VIDYA's delta is the fallback; with neither,
`UNKNOWN`.

### `top_reasons` — at most five, never a plain string

```python
{"code": "BUYER_ABSORPTION", "label": "Buyer Absorption",
 "owner": "Stage 43 — Absorption (leg Absorb block)",
 "weight": 0.9, "source": "absorption", "direction": "UP"}
```

Agreeing reasons lead, dissenting reasons follow — a 55/45 read must not render
as a 100/0 one. `owner` is read out of `CONSUMED` by key, so a signal added
without registering its owner reports `UNKNOWN` loudly rather than inventing a
stage.

---

## The transported fields

| Field | Owner |
|---|---|
| `acceptance` | this stage's label over Stage 71.8's value area |
| `break_probability` · `fakeout_probability` | **Stage 71.8** |
| `structure_state` | **Stage 71.8** — `levels.state` |
| `structure_strength` | **Stage 71.8** — Strike Validation's `premium_sr_strength` |
| `premium_ltp` · `support` · `resistance` | **Stage 71.8** |

Plus `engagement`, `evidence` (the full ledger, both directions), `why`,
`confidence_why`, `momentum_why`, `consumed`, `computed_here`.

### Three ownership corrections

The specification lists these under Stage 71.7. They are **Stage 71.8's**, and
this stage reads them there:

| Input | Spec says | Actually |
|---|---|---|
| CBV · CSV · CVD | 71.7 | 71.7 has the per-side glyph; **71.8 has the numeric totals** |
| RVOL | 71.7 | **71.8** — 71.7 has no RVOL at all |
| Volume | 71.7 | **71.8** |

Reading flow from one stage and volume from another would give one leg's tape
two owners.

### The value area is the premium's, not the index's

Stage 45's VAH/VAL are **NIFTY** levels. A premium accepted above *its own* VAH
is a different fact, and it is the one describing the option a trader holds. So
`structure.profile` drives `Acceptance`; Stage 45 is context on a reason, never
the trigger.

---

## What this stage may never do

`Generate BUY · SELL · ENTER · EXIT · a CALL or PUT recommendation · change the
selected strike · override Stage 72 · calculate Premium Structure · calculate
S/R · calculate break probability · calculate fakeout probability · duplicate
Energy · duplicate Structure.`

Enforced by tests reading the **parse tree**: no producer function may be
defined for anything Stage 71.8 owns, no function name may contain
`decide/recommend/select/trade/order/dispatch`, and no forbidden word may appear
as a whole word in executable code. Docstrings are stripped first — a guard that
cannot tell prose from an implementation teaches people to delete the prose.

---

## Downstream

| Consumer | What it takes |
|---|---|
| **Stage 71.95** | ten `premium.*` fields — four naming 71.85 as owner, six naming 71.8 |
| **Stage 72** (`72.1`) | `premium.behaviour`, weight `1.5`, as an eleventh scoring component |
| **Stage 72.9** | seven payload keys, carried through untouched |
| **Stage 73** | nothing yet — future use |
| **UI** | `mios_v5/ui/premium_behaviour_panel.py`, mandatory under Principle 12 |

Behaviour may raise, lower or withdraw from the entry score. It never generates
one: a perfect behaviour with everything else absent still yields `WAIT`.

---

## Promotion

`ADVISORY_ONLY = True`. Promotion needs 2–4 weeks of live cycles showing the
behaviour read is stable and predictive, and a human flipping the constant. Until
then it is a component in an advisory score, visible everywhere, binding nowhere.
