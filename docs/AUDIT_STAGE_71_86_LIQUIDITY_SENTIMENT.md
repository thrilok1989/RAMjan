# Audit — Stage 71.86, Institutional Liquidity & Sentiment Profile Engine

*The spec's own first rule: "Never duplicate existing calculations. Only compute
what MIOS does not already own." This audit applies that rule to the spec.*

## Verdict

**Do not build Stage 71.86 as specified.** Of the ten concept blocks, **eight
already have an owner**, one is a missing *input* rather than a missing engine,
and one is genuinely new and small.

There is also a timing problem: **Stage 74 — Liquidity Intelligence is already
the liquidity-and-sentiment engine**, it was built last week, and it is sitting
behind a calibration week that this repo's owner explicitly froze:

> *"I would not touch the calibration anymore until the live week completes."*

Building a second liquidity engine while the first is still being calibrated
would mean two liquidity owners disagreeing, with no evidence yet on whether the
first one's numbers discriminate.

| # | Spec block | Owner today | Verdict |
|---|---|---|---|
| 1 | Liquidity Profile — HVN/LVN/POC/VAH/VAL | `compute_vpfr` · `calculate_money_flow_profile` · Stage 45 | **owned ×3** |
| 2 | Sentiment Profile at each level | `calculate_money_flow_profile` rows · Stage 42 · 43 · 14 | **owned** |
| 3 | Dynamic POC | `compute_dynamic_poc` · Stage 74 `poc_migration` · Stage 45 value migration | **owned**, 4 sub-facts new |
| 4 | Liquidity Zones | Stage 17 pools/walls · Stage 74 levels · `zone_intel` | **owned**, 1 sub-fact undeliverable |
| 5 | Liquidity Behaviour | Stage 71.7 `SHIFT_*` · Stage 71.85 · Stage 43 · Stage 74 | **owned** |
| 6 | Volume Behaviour | Stage 71.7 `SHIFT_*` · `premium_structure` `rvol`/`volume_climax` | **owned** |
| 7 | **Profile Shape** | **none** | ⭐ **genuinely new** |
| 8 | Premium Profile | Stage 71.8 `premium_structure` | **already built** |
| 9 | Multi-timeframe 1m/5m/15m/60m/D | Stage 45 owns 1H→Yearly | **missing input**, not engine |
| 10 | Engine Outputs | restatement of 1–9 | — |
| + | New S/R analysis | Stage 71.85 · `zone_intel` · `sr_intel` | **owned** |

---

## Block 1 · Liquidity Profile — owned three times, and a fifth is forbidden

| Producer | Publishes |
|---|---|
| `compute_vpfr` (`vob_minimal.py:1701`) | POC, VAH, VAL — **the one chosen POC owner** |
| `calculate_money_flow_profile` (`indicators/money_flow_profile.py`) | per-bin rows with `node_type` (HVN/LVN already classified), `poc_price`, `value_area_high/low` |
| Stage 45 — HTF VPFR | six independent profiles, each with its own value area and volume nodes |

`premium_structure.py` (Stage 71.8) records the ruling:

> *"The audit found **four** POC implementations. `compute_vpfr` is the chosen
> one… **A fifth is forbidden**, and a test asserts it."*

A Stage 71.86 that computes HVN/LVN/POC/VAH/VAL would be that fifth, and the
existing test would fail — correctly.

## Block 2 · Sentiment Profile — already per-row, already published

`calculate_money_flow_profile` returns, **for every bin**:

```
bull_volume · bear_volume · delta · volume_pct · ratio
node_type · sentiment · sentiment_strength · is_poc
```

plus `highest_sentiment_price` and `highest_sentiment_direction`. That is the
spec's "buyer dominance / seller dominance / balanced participation / delta
imbalance / volume imbalance", at every profile level, today.

The remaining four map to owners as well:

| Spec | Owner |
|---|---|
| Absorption | **Stage 43** — Absorption |
| Acceptance | **Stage 42** — Acceptance / Rejection / Trap |
| Rejection | **Stage 42** |
| Buying / selling exhaustion | Stage 14 order flow (CVD slope + delta divergence) — the closest existing read |

## Block 3 · Dynamic POC — the series exists and is already consumed

`compute_dynamic_poc` (`vob_minimal.py:1661`) recomputes the POC cumulatively
bar-by-bar so it steps as control migrates intraday. Stage 74 already consumes
it (`CONSUMED["dynamic_poc_series"]`) and owns `poc_migration`. Stage 45 owns
value migration across six higher timeframes.

**Genuinely unowned:** POC *acceleration*, *flip*, *compression*, *expansion* —
four classifications over a series that already exists. These are four
if-statements on `dynamic_poc_series`, not an engine. They belong as a **Stage
74 amendment** (`74.2`), after the calibration week, not as a new stage.

## Block 4 · Liquidity Zones — owned, minus one that cannot be delivered

Stage 17 owns walls (heaviest OI) and pools (equal highs/lows, PDH/PDL) and
already marks **untouched** pools — the spec's "untested liquidity". Stage 74
owns clustered levels with `rank`, `confidence`, `witness_count`,
`engine_sources`. `zone_intel` owns origin, strength, lifecycle, health and
battle; `sr_intel` assembles twenty scattered facts into one object.

⚠️ **"Institutional liquidity" vs "retail liquidity" has no owner and no
derivation.** Nothing in the available data — OHLCV, the option chain, OI —
identifies who placed an order. Order size is not identity; a large retail order
and a sliced institutional one are indistinguishable in this feed. Naming a
level "institutional" would be a label with no measurement behind it, presented
next to labels that do have one.

The honest form of this fact already exists: Stage 13 — Institutional Position
Engine reads per-side positioning modes (Long Build-up / Writing / Short
Covering / Long Unwinding) and an institution score. That is *inferred
positioning*, correctly named, and it is a different claim from "this price
level is institutional".

## Blocks 5 & 6 · Liquidity and Volume Behaviour — owned by Stage 71.7 and 71.85

`premium_energy.py` (Stage 71.7) already publishes:

```python
SHIFT_EXPLODING · SHIFT_INCREASING · SHIFT_DECREASING · SHIFT_BUILDING
SHIFT_DISTRIBUTING · SHIFT_COMPRESSING · SHIFT_HOLDING
```

That covers building, distributing, holding, compressing, expanding,
contracting and explosive. `premium_structure` computes `rvol` and
`volume_climax` — the spec's climactic and dry.

`premium_behaviour.py` (Stage 71.85) owns being defended / being attacked, in
its own vocabulary and on the axis where it can actually be measured:

```python
SUPPORT_BUILDING · SUPPORT_FADING · RESISTANCE_BUILDING
RESISTANCE_FADING · ACCEPTANCE · NEUTRAL
```

Stage 43 owns absorption. Stage 74 owns `liquidity_shift`.

## Block 7 ⭐ · Profile Shape — the one genuinely new fact

`grep` finds **no** owner for P-shape, b-shape, D-shape, Double Distribution,
Trend / Balanced / Neutral / Thin profile. `day_type.py` classifies the *day*
(`TREND · SWING · RANGE · CHOPPY · HIGH_VOLATILITY`), which is a different fact
measured from different inputs.

This is real, it is classical Steidlmayer market profile, and it is computable
from the bins `calculate_money_flow_profile` already returns — where the volume
mass sits relative to the range, and whether it is unimodal or bimodal.

**It is one classifier over an existing profile, not a new engine.** Its natural
home is `premium_structure` (which already holds the profile facts) or a small
`profile_shape` module consumed by it.

## Block 8 · Premium Profile — already built

The spec says *"Create identical profile engine for Premium. Do NOT project
NIFTY profile. Premium gets its own HVN, LVN, POC, VAH, VAL…"*

Stage 71.8 `premium_structure.py` already does exactly this, computed natively
per leg, with `COMPUTED_HERE = ("hvn", "lvn", "rvol", "volume_climax", …)` and
`vp_poc` / `value_area` consumed from the one POC owner. Nothing to build.

## Block 9 · Multi-timeframe — a missing input, not a missing engine

Stage 45 maintains six independent profiles: 1H · 4H · Daily · Weekly · Monthly
· Yearly. So **60m and Daily are owned**; 1m, 5m and 15m are not.

But the gap is upstream of the engine. Stage 45's own docstring:

> *"The profiles are built by the app (which owns the candle series) and
> forwarded on."*

So intraday profiles are delivered by **feeding three more resampled series to
the owner that already exists** — not by writing a second multi-timeframe
profile engine. Doing the latter would create a second answer for "what is the
1H POC".

⚠️ Cost check before this is picked up: three more profiles per cycle is three
more computations and three more series to hold. The Supabase egress work this
session cut writes by 99.5% and reads by 96.8%; a 1-minute profile recomputed
every 20-second rerun is exactly the shape of the problem that caused it.

## The "New S/R Analysis" section — Stage 71.85 shipped it

The spec asks for Support/Resistance **Building · Weakening · Fading · Defended
· Consumed**, with a confidence score, on both index and premium.

Stage 71.85 — Premium LTP Behaviour publishes exactly this axis for premium,
with `behaviour`, `behaviour_strength`, `behaviour_confidence`, `momentum`,
`break_probability`, `fakeout_probability`, `acceptance` and `top_reason`. It is
already weighted into Stage 72's score at `1.5`, and its `Neutral` deliberately
maps to `None` so an absence of a read leaves the denominator.

For the index, `zone_intel` owns strength / lifecycle / health / battle and
`sr_intel` assembles them. "Defended" and "Consumed" as *named* states are the
only genuinely missing labels, and they belong to those owners.

---

## A correction to the earlier roadmap audit

`docs/AUDIT_V6_EXECUTION_LAYER_ROADMAP.md` lists **Dealer Context** and
**Institutional Intent** as having no owner. That is wrong, and this audit found
it while looking somewhere else:

* `mios_v5/engines/stage11_dealer.py` — Dealer Positioning
* `mios_v5/engines/stage13_institutional.py` — Institutional Position Engine

Both exist. What is missing is not an owner but a **consolidated read** — the
facts are published per-engine and never assembled into one "dealer context" the
way `sr_intel` assembles twenty facts into one level object. That is an
assembler, not a producer, and it is much smaller than a new engine.

**Auction Context remains genuinely unowned** (`opening_auction_log` is a table
with no engine behind it), so roadmap Priority 5 shrinks from three producers to
one producer plus one assembler.

---

## What this audit actually justifies

| Build | Size | Where it goes | When |
|---|---|---|---|
| **Profile Shape classifier** | one module, ~8 shapes | consumed by `premium_structure` | ready now |
| POC acceleration · flip · compression · expansion | 4 classifications | **Stage 74 amendment `74.2`** | ⛔ after the calibration week |
| 1m/5m/15m profiles | resample + forward | feed **Stage 45**, no new engine | after a cost check |
| "Defended" / "Consumed" S/R labels | 2 states | `zone_intel` / `sr_intel` | ready now |
| Dealer/Institutional **assembler** | reads Stages 11 + 13 | new small module | ready now |
| ❌ Institutional vs retail liquidity | — | **not derivable from this data** | never, as specified |

**A new stage is not justified.** Under the rule agreed earlier in this
roadmap —

> A new stage requires a new market dimension. A new producer requires only a
> currently ownerless fact.

— Profile Shape is a *fact* with no owner, not a *dimension* with no engine. It
gets a producer inside an existing owner. Everything else on this spec is either
built, is an amendment to a stage that is mid-calibration, or is a label with no
measurement behind it.

## The UI requirement stands regardless

The spec asks for POC/VAH/VAL/HVN/LVN/zones/dynamic-POC path/sentiment colouring
on all three charts. Principle 12 makes that binding for anything that reaches a
decision — and most of these values **already exist and are already scored**.
Auditing which of them a trader can currently inspect is a smaller, higher-value
piece of work than a new engine, and it is the one thing in this spec that could
start today with no ownership conflict at all.
