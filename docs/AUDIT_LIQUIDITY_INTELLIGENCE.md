# Audit — Liquidity Intelligence Engine

*Phase 1, before a line of it is written. Taken at `1903a72`.*

The spec asks for 13 outputs across 3 charts, injected into ~20 stages. This
checks each one against the codebase first, because the same discipline that
produced Stages 71.7–71.85 applies here: **one fact, one owner; consume, never
duplicate.**

---

## Verdict

**Roughly 70% of the requested engine already exists**, spread across four
owners that do not know about each other. The genuinely missing work is not the
profiles — it is the **unification**, the **cross-cycle tracking**, and the
**aggregates**.

Building `LiquidityProfileBuilder`, `MoneyFlowProfileBuilder`,
`SentimentProfileBuilder`, `POCEngine` and `ValueAreaEngine` as the spec's
module list suggests would create a **fifth, sixth and seventh** implementation
of things this repo already computes — and `AUDIT_STAGE_71_8_PREMIUM_STRUCTURE.md`
already settled the POC question and wrote *"a fifth is forbidden"*.

---

## ⚠️ There are already FIVE point-of-control implementations

| # | Where | What it does |
|---|---|---|
| 1 | `vob_minimal.compute_vpfr` | **The chosen owner** (audit 71.8). Range-overlap binning, POC + VAH/VAL at 70% |
| 2 | `vob_minimal.compute_dynamic_poc` | POC recomputed bar-by-bar so it migrates intraday |
| 3 | `indicators/triple_poc.py` `TriplePOC` | Three lookback periods, upper/lower POC |
| 4 | `indicators/money_flow_profile.py` | `poc_price` from the money-flow bins |
| 5 | `market_depth_advanced.analyze_volume_profile` | POC + value area from L2 depth |

The 71.8 audit chose **`compute_vpfr`** and a test asserts `premium_structure`
imports no profile builder at all. A `POCEngine` would be number six.

**Decision: no new POC.** `compute_dynamic_poc` (#2) already answers the spec's
"Dynamic Point of Control" — it is the only one that migrates — so the
Liquidity engine *reads* it and derives migration/velocity/stability from the
series it already returns.

---

## 1 · The thirteen outputs

`EXISTS` = computed today · `WIRING` = computed but discarded · `COMPUTED` =
this engine may compute it · `MISSING` = no producer

| # | Output | Status | Owner |
|---|---|---|---|
| 1 | Liquidity Profile | **EXISTS** | `calculate_money_flow_profile` — `rows[]` with `ratio`, `node_type` |
| 2 | Sentiment Profile | **EXISTS** | same — `bull_volume`, `bear_volume`, `delta`, `sentiment`, `sentiment_strength` per row |
| 3 | Money Flow Profile | **EXISTS** | same, `source='Money Flow'` (volume × price) |
| 4 | Dynamic POC | **EXISTS** | `compute_dynamic_poc` — the migrating series |
| 5 | Value Area | **EXISTS** | `compute_vpfr` → VAH/VAL; MFP has its own consolidation band |
| 6 | High Liquidity Nodes | **EXISTS ×2** | MFP `node_type='High'` · `premium_structure.classify_nodes` HVN |
| 7 | Low Liquidity Nodes | **EXISTS ×2** | same two |
| 8 | Bullish Liquidity Zones | **EXISTS** | MFP row `sentiment='Bullish'` · `analyze_vob_volume` bull zones |
| 9 | Bearish Liquidity Zones | **EXISTS** | same |
| 10 | Liquidity Imbalance | **WIRING** | per-row `delta` exists; **no aggregate** is derived |
| 11 | Liquidity Shift | **MISSING** | nothing compares this cycle's profile to the last |
| 12 | Institutional Acceptance | **EXISTS** | Stage 42 `reaction.state` · Stage 71.85 premium acceptance |
| 13 | Institutional Rejection | **EXISTS** | same |

**Two genuinely missing: #11 Liquidity Shift and the aggregate half of #10.**
Everything else is a read.

---

## 2 · The three charts

### NIFTY — EXISTS

`calculate_money_flow_profile` + `compute_vpfr` + `compute_dynamic_poc` +
`analyze_vob_volume` + `_detect_liquidity_pools` already cover profile,
sentiment, POC, value area, bull/bear zones and stop-shelves.

`_detect_liquidity_pools` deserves a mention: it maps equal highs/lows, PDH/PDL
and round numbers as *likely resting stops*, and it is honest about the limit —
its docstring says true resting orders need L2 depth. That is the "liquidity
magnet" the spec asks for, already built and already caveated.

### Premium — EXISTS, all of it

This is **Stage 71.8 `premium_structure.analyse()`**, shipped and frozen:

| Spec asks for | Already published |
|---|---|
| Premium POC | `vp_poc` |
| Premium Liquidity Nodes | `hvn`, `lvn`, `nodes` |
| Premium Acceptance | `acceptance`, `acceptance_read` |
| Premium Rejection | `rejection` |
| Premium Money Flow | `cbv`, `csv`, `cvd`, `flow` |
| Premium Sentiment | Stage 71.85 behaviour ledger |
| Premium Support / Resistance | `support`, `resistance`, `levels` |

**Nothing to build here.** A "Premium Liquidity Profile" module would be
`premium_structure` with a different name.

### Option chain — EXISTS, scattered

| Spec asks for | Where it is today |
|---|---|
| Option Liquidity Wall | `df_summary['OI_Wall']` |
| Money Flow Wall | `df_summary['ChgOI_Wall']` |
| Gamma Liquidity | `gamma_flip_level`, `gamma_flip_direction`, `spot_vs_flip` |
| Dealer Liquidity | `sections.dealer`, `dealer_levels` |
| Support Wall | `support_strength` (PE wall) |
| Resistance Wall | `resistance_strength` (CE wall) |

These are computed and then **collapsed into a glyph or a score**, which is the
same failure mode the 71.8 audit found with `detect_ignition`. This is a
**WIRING** problem, not a build problem.

---

## 3 · Dynamic POC tracking

The spec wants six facts. `compute_dynamic_poc` returns the whole series, so:

| Fact | Status |
|---|---|
| Current POC | **EXISTS** — last element |
| Previous POC | **WIRING** — in the series, never read |
| POC Migration | **COMPUTED** — a difference over the series |
| POC Trend | **COMPUTED** — sign of the migration |
| POC Velocity | **COMPUTED** — migration per bar |
| POC Stability | **COMPUTED** — how often it changed bin |

All four computed facts are **arithmetic over one existing series**. That is a
classifier over published data, not a new measurement — the same justification
`premium_structure` used for HVN/LVN.

---

## 4 · Money Flow Intelligence

| Fact | Status | Note |
|---|---|---|
| Money Flow Strength | **EXISTS** | MFP `total_volume`, per-row `ratio` |
| Money Flow Direction | **EXISTS** | MFP `delta` sign, `highest_sentiment_direction` |
| Money Flow Acceleration | **EXISTS** | Stage 71.7 `energy_acceleration` — built this session |
| Money Flow Exhaustion | **EXISTS** | Stage 50 `exhausted` pressure · Stage 71.8 `volume_climax` |
| Money Flow Divergence | **MISSING** | nothing compares price direction to flow direction |

**One genuinely missing: divergence.**

---

## 5 · Sentiment Profile

| Fact | Status |
|---|---|
| Bull / Bear Dominance | **WIRING** — per-row exists, no aggregate |
| Net Sentiment | **WIRING** — same |
| Sentiment Shift | **MISSING** — no cross-cycle comparison |
| Aggression | **EXISTS** — Stage 43 absorption, Stage 50 pressure |
| Exhaustion | **EXISTS** — Stage 50 |
| Reversal Probability | **EXISTS** — Stage 71.8 `fakeout_probability` |

---

## 6 · Liquidity Heatmap — MISSING

Nothing renders a per-bin intensity band for NIFTY, premium or money flow.
`render_positioning_heatmap` exists but is **options positioning**, a different
thing.

The data is entirely present: MFP rows already carry `ratio` (0–1 of max) and
`sentiment_strength`. A heatmap is a **colour mapping over published numbers**,
so it belongs in a panel, not in an engine.

---

## 7 · S/R engine upgrade

The spec lists ten inputs to cluster. Nine exist:

| Input | Owner |
|---|---|
| Swing High / Low | `_detect_liquidity_pools` |
| Dealer Levels | `dealer_levels` |
| Gamma Levels | `gamma_flip_level` |
| Liquidity Nodes | MFP `node_type` |
| Money Flow Nodes | MFP rows |
| POC | `compute_vpfr` / `compute_dynamic_poc` |
| Value Area | `compute_vpfr` |
| Acceptance Zones | Stage 42 |
| Rejection Zones | Stage 42 |

**The clustering is what is missing** — collapsing ten level sources into
Major/Minor/Dynamic Support and Resistance. That is genuinely new, and it is
the single highest-value item in the whole spec, because it is the one that
turns nine scattered numbers into something a trader reads once.

---

## 8 · What this engine may compute

Everything else is a read, and `CONSUMED` will name the owner of each.

1. **Liquidity Shift** — this cycle's profile against the last
2. **Liquidity Imbalance** — the aggregate of per-row deltas
3. **Net Sentiment / Dominance** — the aggregate of per-row sentiment
4. **Sentiment Shift** — cross-cycle
5. **POC Migration / Trend / Velocity / Stability** — over the existing series
6. **Money Flow Divergence** — price direction against flow direction
7. **Level clustering** — Major/Minor/Dynamic S/R from the nine sources
8. **`LiquidityContext`** — the unifying object

Eight things. Not thirteen outputs, three profile builders and a POC engine.

---

## 9 · Runtime — the spec's own rule, and a caution

> *"Compute liquidity once per refresh. Expose a centralized Liquidity Context
> object. Every stage reads from this object. Do not recompute inside individual
> stages."*

This is exactly `TradingContext` (Stage 71.95), and it is the right instinct.
`LiquidityContext` will follow the same pattern: immutable, every field naming
its owner, `UNKNOWN` over assumption.

**But the profiles are expensive.** `calculate_money_flow_profile` is a Python
loop over every bar × every bin; `compute_dynamic_poc` is O(bars × bins) with a
`np.histogram` per bar. At a 20-second refresh these must not run per stage —
which is the spec's point — and the incremental-update rule it states
("Avoid scanning entire history every cycle") needs the same watermark treatment
`upsert_candles` got this session.

---

## 10 · On the LuxAlgo reference

The spec says to use it as conceptual inspiration and not to port it.
Worth recording: **`indicators/money_flow_profile.py` already describes itself
as "Python port of LuxAlgo Money Flow Profile"** and predates this request.

Volume-at-price binning, splitting a bar's volume by range overlap, a bull/bear
split per bin, POC as the max bin, and value area by expansion are **standard
market-profile technique** — Steidlmayer, decades before Pine Script. They are
not anyone's intellectual property. The published indicator is CC BY-NC-SA,
which covers the *code*, and nothing here transliterates it: the missing pieces
this engine adds — cross-cycle shift, migration velocity, level clustering —
have no counterpart in either script.

---

## 11 · Recommended build order

The spec's own module list, corrected by what exists:

| Spec module | Verdict |
|---|---|
| `LiquidityProfileBuilder` | ❌ `calculate_money_flow_profile` owns this |
| `MoneyFlowProfileBuilder` | ❌ same function, `source='Money Flow'` |
| `SentimentProfileBuilder` | ❌ same function, per-row sentiment |
| `POCEngine` | ❌ would be the sixth POC |
| `ValueAreaEngine` | ❌ `compute_vpfr` is the chosen owner |
| `LiquidityHeatmap` | ➡️ a **panel**, not an engine |
| `LiquidityContext` | ✅ **build** — the unifying object |
| `LiquidityEngine` | ✅ **build** — the eight computations of §8 |
| `LiquidityAnalyzer` | ✅ folded into the engine |
| `LiquidityStageAdapter` | ✅ **build** — but as context fields, like Stage 71.95 |

**Order:**

1. `LiquidityContext` + the engine's reads — the unification, no new maths
2. Shift · migration · imbalance · divergence — the six missing computations
3. Level clustering — the highest-value item
4. Panel + heatmap
5. Stage injection, one stage at a time, each proving it consumes rather than
   recomputes
6. Learning features

---

## 12 · What would go wrong without this audit

Built as specified, MIOS would gain a sixth POC, a third HVN/LVN classifier, a
second premium profile duplicating a frozen stage, and a `SentimentProfileBuilder`
recomputing numbers `calculate_money_flow_profile` already returns per row.

Every one of those would then be a fact with two owners, drifting apart, and the
next audit would have to pick a winner — exactly as the 71.8 audit had to pick
between four POCs.
