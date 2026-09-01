# Dashboard 2 Overlays — Phase 2 audit

**Phase 1 is complete.** Every overlay with a producing engine is wired,
tagged with its source, and independently toggleable.

This report lists what remains, per the Phase 2 brief. **No placeholders were
created.** An invented level looks exactly like a real one at a glance, which
makes it worse than a missing one.

---

## Phase 1 — wired (23 overlays from 9 producers)

| Overlay | Group | Producing engine |
|---|---|---|
| Support · Resistance · Major S/R | `sr` | Stage 35 Reaction Zone |
| War Zone | `sr` | Battle Zone |
| POC · VAH · VAL | `poc` | Money Flow Profile |
| 1H · 4H · Daily · Weekly · Monthly POC | `poc` | Stage 45 HTF Profiles |
| Entry · Stop | `trade` | Stage 52 Decision Engine |
| Dynamic Trail | `trade` | Dynamic Trail |
| Target | `targets` | Stage 35 Reaction Zone (`next_target`) |
| **Call Wall** | `dealer` | Market Picture · `oi_ceiling` |
| **Put Wall** | `dealer` | Market Picture · `oi_floor` |
| **OI Pin** | `dealer` | Market Picture · `oi_pin` |
| **Gamma Flip** | `gamma` | GEX · `gamma_flip_level` |
| **Charm Pin** | `charm` | Charm Pin engine (drawn only when `active`) |
| VWAP | `vwap` | Market Picture |
| Liquidity Pools (both sides) | `liquidity` | Liquidity Pool detector |
| Order Blocks | `orderblk` | Order Block detector |
| VOB Zones (per leg) | `vob` | `analyze_vob_volume` |

A note on the dealer walls: `oi_ceiling` / `oi_floor` **are** the call and put
walls — the strikes where open interest is heavy enough to cap or floor price.
They are labelled by what they do on the chart rather than by how they were
derived.

Market State, Overall Bias, Flow Shift, Dealer Bias and Institutional Bias are
wired, but as **Command Center cards**, not chart lines — they are states, not
prices, and drawing a horizontal line for "TRENDING" would be meaningless.

---

## Phase 2 — still missing a producer

### 1 · Fair Value Gap (FVG)

| | |
|---|---|
| **Required engine** | FVG detector — three-bar imbalance scan with mitigation tracking |
| **Partial data exists?** | **No.** The only occurrences of "FVG" in the repo are in `generate_analysis_pdf.py:294,311-312`, which *describes* a LuxAlgo FVG feature in a documentation table. **No implementation exists.** |
| **Complexity** | **Medium.** The detection itself is simple — `low[i] > high[i-2]` (bullish) or `high[i] < low[i-2]` (bearish). The real work is lifecycle: an FVG must be tracked until mitigated, and "active vs filled" is the entire value of the overlay. That needs per-gap state across cycles, which is where every naive implementation goes wrong. |
| **Should own it** | A new stage in the structure family, alongside Stage 2. It is a price-structure fact, not an order-flow one. |

### 2 · Acceptance / Rejection Zones (as drawable boxes)

| | |
|---|---|
| **Required engine** | Zone extractor over Stage 42's acceptance verdicts |
| **Partial data exists?** | **Yes, substantially.** Stage 42 (`stage42_acceptance.py`) already classifies acceptance and rejection at a level, and `fr["reaction"]` carries the verdict. What does **not** exist is the *geometry* — a price band with a start and end time that can be shaded. Today the answer is a label about one level, not an area. |
| **Complexity** | **Low-to-medium.** Stage 42 already knows *what*; this needs *where and when*. Mostly bookkeeping: record the band and the bar range each time acceptance is asserted, and expire it when the verdict flips. |
| **Should own it** | Stage 42 itself — extend its output rather than add an engine. The verdict and its geometry are the same fact. |

### 3 · Target Ladder (T1 / T2 / T3)

| | |
|---|---|
| **Required engine** | Multi-target projector |
| **Partial data exists?** | **Partially.** `fr["next_target"]` (`final_read.py:239`) provides exactly **one** target from the Reaction Zone engine. There is no second or third. HTF POCs and liquidity pools are natural T2/T3 candidates and are already available — but selecting and ordering them is a decision, and the system does not currently make it. |
| **Complexity** | **Low.** The candidates already exist. The engine is ranking logic: nearest opposing structure → next HTF level → liquidity pool, filtered for R:R. |
| **Should own it** | Stage 52 Decision Engine. Targets belong with entry and stop — they are the same trade plan, and splitting them across engines invites the three to disagree. |

---

## Not requested, but worth flagging

**Per-leg OI and ΔOI as chart overlays** are also unproduced *per leg over time*.
The chain gives current OI per strike (`total_ce_change` / `total_pe_change`),
but nothing stores a per-leg OI **series**, so there is no line to plot against
the premium candles. This needs a time-series store, not a new calculation —
the values are already fetched every cycle and discarded.

---

## Summary

| Overlay | Producer | Partial data | Complexity | Suggested owner |
|---|---|---|---|---|
| Fair Value Gap | ❌ none | ❌ none | Medium | New structure-family stage |
| Acceptance / Rejection zones | ❌ none | ✅ verdicts exist, geometry does not | Low-Medium | Extend Stage 42 |
| Target Ladder T1/T2/T3 | ❌ none | ✅ one target exists | Low | Stage 52 |
| Per-leg OI / ΔOI series | ❌ none | ✅ values fetched, not stored | Low | Leg cache, not an engine |

**Recommended order:** Target Ladder first (lowest cost, highest daily use, and
Stage 52 already owns the trade plan), then Acceptance/Rejection zones
(extends an engine that already knows the answer), then FVG (genuinely new
logic with real lifecycle state), then the per-leg OI series.

Per the Phase 3 brief, each should ship as its own engine with independent
logic, tests, validation and logging — and be wired into `mios_v5/overlays.py`
by adding one `collect()` entry. The chart stays a renderer.
