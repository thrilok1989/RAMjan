# Stage 71.8 — Premium Structure: what already exists

*Audit taken at `32e155f`, before any Premium Structure code was written. It
answers one question per requirement: **does MIOS already know this, and if so,
who owns it?***

---

## Verdict

**18 of 23 requirements already exist. Three need only a classifier over data
that is already computed. Two are genuinely absent.**

The dominant finding is not absence — it is **discard**. Per-leg intelligence is
computed every cycle and then collapsed into a single 🟢/🔴/⚪ glyph for the leg
table, and the richer read is thrown away. `detect_ignition` runs on every leg
and returns *named* sub-signals including Wyckoff Spring and Wyckoff Upthrust —
false break plus snap-back, which **is** fakeout detection — and the leg table
keeps only `bull`/`bear`/`neu`.

So Premium Structure is overwhelmingly an **orchestration and re-exposure** job.
The new computation it justifies is three classifiers and one score.

---

## 1. The requirement table

Status key: **EXISTS** = published and reachable · **WIRING** = computed, not
exposed · **ORCHESTRATE** = derivable from published data by classification ·
**MISSING** = no producer.

| # | Requirement | Stage | Module | Function | Status | Notes |
|---|---|---|---|---|---|---|
| 1 | Premium Support | native | `vob_minimal.py` | `classify_leg_sr_behavior` → `VolumeOrderBlocks.detect_blocks` bullish blocks below LTP | **EXISTS** | `_atm_leg_sr_behavior`; nearest level published |
| 2 | Premium Resistance | native | `vob_minimal.py` | same, bearish blocks above LTP | **EXISTS** | same store |
| 3 | Premium Acceptance | native | `vob_minimal.py` | `classify_leg_sr_behavior` → state `ACCEPTING` | **EXISTS** | the **leg's own** level. Stage 42 is NIFTY-level and a different fact |
| 4 | Premium Rejection | native | `vob_minimal.py` | same → `REJECTING` | **EXISTS** | also `BREAKING` · `BUILDING` · `NONE` |
| 5 | Premium VOB Zones | native | `vob_minimal.py` | `analyze_vob_volume` | **EXISTS** | `_atm_leg_vob_volume`; per zone: `BUILDING·BREAKING·INTACT·FADING`, bull%/bear%, max print |
| 6 | Premium Volume Profile | native | `vob_minimal.py` | `compute_vpfr(df, n_bars)` → `{poc, vah, val}` | **WIRING** | published for **ATM±1 only** (`_atm_pm1_vpfr`); a selected wing strike has none |
| 7 | Premium HVN | native | `indicators/money_flow_profile.py` | `calculate_money_flow_profile` → `rows[].ratio` | **ORCHESTRATE** | rows exist with per-bin volume ratio; **no HVN classifier anywhere** |
| 8 | Premium LVN | native | same | same | **ORCHESTRATE** | same — the bins are there, the label is not |
| 9 | Premium POC | native | ⚠️ **four owners** | `compute_vpfr.poc` · `money_flow_profile.poc_price` · `TriplePOC.calculate_all_pocs` · `compute_dynamic_poc` | **EXISTS** | see §2 — one must be chosen, not a fifth written |
| 10 | Premium Trend | native | `vob_minimal.py` | `calculate_vidya` → `trend` | **EXISTS** | `_atm_leg_vidya`, per leg |
| 11 | Premium Momentum | native | `vob_minimal.py` | `calculate_vidya(momentum=20)` | **WIRING** | VIDYA's momentum window drives the trend; no momentum **scalar** is published |
| 12 | Premium CBV | native | `indicators/order_flow.py` | `totals().buy_total` | **EXISTS** | wired to 71.7 last commit; `_atm_leg_ltf_delta` |
| 13 | Premium CSV | native | same | `totals().sell_total` | **EXISTS** | same |
| 14 | Premium CVD | native | same | `totals().delta` · `cvd_sum` | **EXISTS** | same |
| 15 | Premium RVOL | — | — | — | **WIRING** | `analyze_vob_volume` computes `avg_vol_1m` (60-bar mean) internally and discards it; `classify_leg_sr_behavior` computes a 20-bar mean for `vol_spike` and discards that too |
| 16 | High Volume Candle | native | `vob_minimal.py` | `classify_leg_sr_behavior` → `vol_spike` (>1.5× 20-bar mean) | **WIRING** | computed per leg, **used internally, never returned** |
| 17 | Volume Dry-up | native | `vob_minimal.py` | `detect_ignition(dryup_bars=6)` | **WIRING** | runs per leg (`vob_minimal.py:9837`); the dry-up→surge sub-signal is named in `signals[]` and the leg table keeps only the net direction |
| 18 | Volume Climax | — | — | — | **MISSING** | nothing measures exhaustion-by-volume on a premium |
| 19 | Buyer Absorption | native | `vob_minimal.py` | inline CLV block at `:9878` (range compression + \|delta\| ≥ 25% of volume) | **EXISTS** | per leg, as the `Absorb` glyph. Stage 43 is the NIFTY-level equivalent |
| 20 | Seller Absorption | native | same | same | **EXISTS** | same block, opposite sign |
| 21 | Breakout Probability | — | — | — | **MISSING** for premium | `seller_perspective.py:5419` has `seller_breakout_probability_index`, but it is for the **underlying** and that module is **not imported by the running app** — see §3 |
| 22 | Fakeout Probability | native | `vob_minimal.py` | `detect_ignition` → **Wyckoff Spring / Wyckoff Upthrust** | **WIRING** | *false break + snap-back* is exactly this requirement, computed per leg and discarded by the glyph collapse |
| 23 | Premium Structure Confidence | — | — | — | **MISSING** | this is the orchestrator's own output — nothing else should own it |

**Totals: 12 EXISTS · 6 WIRING · 2 ORCHESTRATE · 3 MISSING.**

---

## 2. ⚠️ Premium POC has four implementations

| Owner | Method | Used by |
|---|---|---|
| `compute_vpfr` | fixed-range bins, volume distributed by range overlap | `_atm_pm1_vpfr`, HTF profiles |
| `calculate_money_flow_profile` | bins with buy/sell sentiment split | leg `MFP` glyph, `_atm_pm1_vpfr.mfp` |
| `TriplePOC` | three lookback periods (10/25/70) | not reachable from the reduced app |
| `compute_dynamic_poc` | rolling POC series | the removed alert path |

**Premium Structure must pick one and name it.** Writing a fifth is the exact
failure principle 1 exists to prevent, and picking silently is nearly as bad —
two panels would report different POCs for the same leg with nothing on screen
to explain it.

**Chosen: `compute_vpfr`.** It is the only one already published per leg, it
returns VAH/VAL alongside the POC (which HVN/LVN need as reference), and the
HTF stack already uses it — so the premium POC and the index POC are computed
the same way.

---

## 3. What the audit found that must NOT be reused

**`seller_perspective.py`** (394 KB) contains `seller_breakout_probability_index`
and a large body of related analytics. It is **not imported by any live module**
— `seller_features.py` mentions it only in a docstring, and `seller_features`
itself is not imported by `vob_minimal.py`. It is dead relative to the running
app.

Reusing it would mean either importing a 394 KB module for one function, or
copying that function — and the function computes a breakout index for the
**underlying**, not for a premium. Neither is reuse; both are new coupling.
**Recorded here so the next audit does not rediscover it as a "missing" feature
that already exists.**

---

## 4. The glyph collapse — the real finding

`build_leg_bias_table` (`vob_minimal.py:9721`) runs the per-leg engines and then
reduces each to one of `bull`/`bear`/`neu` for display:

```python
ig = detect_ignition(df_l)
v['Ign'] = ig.get('direction') if ig.get('fired') ... else 'neu'
```

`detect_ignition` returned `{signals: [{name, direction, detail, time}, …],
fired, direction, bull_count, bear_count}`. Four named sub-signals — including
**Wyckoff Spring** and **Wyckoff Upthrust**, which are false-break-plus-snap-back
— become one glyph. The same happens to `vol_spike` inside
`classify_leg_sr_behavior`, and to `avg_vol_1m` inside `analyze_vob_volume`.

This is why six requirements read **WIRING** rather than **MISSING**. The
intelligence is there, it runs every cycle on every leg, and the only consumer
throws away everything except the sign.

> **Premium Structure's main job is to read these engines directly instead of
> reading their glyphs.** That is orchestration, not computation.

---

## 5. What Premium Structure is justified in computing

Everything else is consumption. These four are the only new computation, and
each is a **classifier over published data**, not a new measurement:

| New | Why it is justified | Input it classifies |
|---|---|---|
| **HVN / LVN** | The bins and their volume ratios exist; nothing labels which are high- or low-volume nodes. A threshold over `rows[].ratio` is the classifier, and no other module wants to own it. | `calculate_money_flow_profile.rows` |
| **RVOL** | `avg_vol_1m` is computed twice and discarded twice. Dividing current volume by it is one line, and publishing it stops a third module computing a third average. | leg candles |
| **Volume Climax** | Genuinely missing (#18). Defined as RVOL extreme **and** a wide-range bar **and** a close rejecting its extreme — all three already available once RVOL exists. | RVOL + leg candles |
| **Breakout / Fakeout probability** | Missing for premium (#21) and discarded for premium (#22). Both are **weighted reads over existing evidence** — acceptance state, VOB zone status, RVOL, absorption, Wyckoff signals — not new market measurement. | the reads above |

`structure_score` and `confidence` are the orchestrator's own output (#23) and
have no other owner by definition.

**Everything else in `premium_structure.py` must be a read.** A test asserts it:
the module may not import `VolumeOrderBlocks`, `calculate_vidya` or
`compute_vpfr` — it receives their finished output.

---

## 6. Input contract

Per side, `analyse()` takes what the caller has already extracted:

```
sr        _atm_leg_sr_behavior[leg]     state · side · level · direction
vob       _atm_leg_vob_volume[leg]      zones + status + bull%/bear%
vidya     _atm_leg_vidya[leg]           trend · delta_pct · buy/sell vol
flow      _atm_leg_ltf_delta[leg]       buy_total · sell_total · delta
vpfr      compute_vpfr(leg_df)          poc · vah · val
mfp       calculate_money_flow_profile  rows[] · poc_price · value area
ignition  detect_ignition(leg_df)       signals[] — NAMED, not collapsed
candles   the leg's own frame           volume series for RVOL
```

The last one is the only raw input, and only because RVOL and Volume Climax need
a volume series that no engine publishes.

---

## 7. Decisions this audit forces

1. **One POC owner** — `compute_vpfr` (§2).
2. **Read `detect_ignition` directly**, not the `Ign` glyph — the glyph has
   already discarded the fakeout evidence (§4).
3. **Do not touch `seller_perspective.py`** (§3).
4. **VPFR for wing strikes must be computed by the caller**, since
   `_atm_pm1_vpfr` covers ATM±1 only and Stage 71.8's picker offers ATM±3. Where
   it is absent, the profile reads `UNKNOWN` rather than borrowing the ATM's.
5. **Stage 71.8 stops computing Premium S/R itself** and consumes
   `premium_structure.analyse()` instead — one owner for the premium's structure,
   which is the whole point.
