# Audit — Stage 42.5 · Level Interaction Framework

**Status:** audit only. No code written.
**Question asked:** build one canonical source of truth for level behaviour, standardise
twelve states, remove the 25-point rule entirely, expose `interaction_distance`,
`interaction_strength`, `interaction_type`, `interaction_confidence` — then freeze it.

**Short answer:** the framework is justified, and the audit found more duplication than
the brief assumed — **seven** state machines describing level behaviour, not three, and
**fourteen** separate "price is at a level" thresholds in **three different units**.

⚠️ **The finding that changes the priority:** the 25-point rule is not confined to the
simple entry system and a bias vote. It gates **three live Telegram entry alerts**,
including the one the code calls *"the only alert on the main Telegram bot"* — see §3.2.
Removing it is not a refactor of an advisory path.

But the biggest structural finding is the opposite of what a duplication audit usually
turns up:

> **Stage 42 and Zone Intel are not duplicates.** They are one concept accidentally split
> in half. Stage 42 answers *what is happening at this level right now*; Zone Intel answers
> *what has this level been through*. They only look like rivals because both write the
> word `lifecycle` into the same dict key.

That reframes the open question from "who wins when they disagree" to "why were they ever
compared". Section 4 answers it.

---

## 1 · Every owner of level behaviour today

| # | Owner | Where | States | "At level" band | Has memory? |
|---|---|---|---|---|---|
| **A** | Stage 42 · Acceptance | `mios_v5/acceptance.py` | **15** | `_AT_PCT = 0.12%` ≈ 29 pts | ✅ per level, per cycle |
| **B** | Zone Intel · lifecycle | `mios_v5/zone_intel.py:127` | **10** | `0.35%` ≈ 86 pts (`:385`) | ✅ via `_zone_memory` |
| **B2** | Zone Intel · acceptance | `mios_v5/zone_intel.py:231` | **5** | `tol_pct = 0.12%` | ❌ stateless |
| **C** | `annotate_sr_trend` | `vob_minimal.py:6097` | **5** | — (uses health, not distance) | ✅ strength EMA |
| **D** | `classify_sr_behavior` | `vob_minimal.py:6613` | **5** | **`25` pts hardcoded** (`:6684`) | ❌ stateless |
| **E** | `entry_gate` | `vob_minimal.py:7404` | **8** | **`_prox = 25.0`** (`:7408`) | ✅ `_gate_armed` |
| **F** | `_candle_sweep_reclaim` / `_zone_confirmed` | `vob_minimal.py:6866` / `:6884` | booleans | `wick_min=5.0` / `band=15.0` | ❌ reads last 3 bars |
| **G** | `simple_entry` | `mios_v5/simple_entry.py:57` | pass/fail | **`NEAR_POINTS = 25.0`** | ❌ stateless |

Seven owners. Between them: **48 state names** for what the brief describes as twelve.

### The fourteen proximity thresholds

| Value | Unit | ≈ pts @ 24,450 | Where | What it decides |
|---|---|---|---|---|
| `0.02%` | % | **5** | `acceptance.py:40` `_BEYOND_PCT` | past the level = broken |
| `5.0` | pts | **5** | `vob_minimal.py:6866` `wick_min` | a wick counts as a sweep |
| `15.0` | pts | **15** | `vob_minimal.py:6884` `band` | a candle "tested" the zone |
| `25.0` | pts | **25** | `simple_entry.py:57` | rule 1 of the simple entry |
| `25.0` | pts | **25** | `vob_minimal.py:6684` | `BUILDING` → a bias vote **and a live Telegram alert** |
| `25.0` | pts | **25** | `vob_minimal.py:7408` | the entry gate arms |
| `25.0` | pts | **25** | `vob_minimal.py:8377` | swept-zone reversal watch |
| `25.0` | pts | **25** | `vob_minimal.py:10797` | OI-wall pin proximity |
| `25` | pts | **25** | `vob_minimal.py:11792` `proximity_pts` | 🔔 `send_atm_wall_vob_entry_alert` |
| `25` | pts | **25** | `vob_minimal.py:11950` `proximity_pts` | 🔔 `send_spot_sr_legs_confluence_alert` |
| `0.12%` | % | **29** | `acceptance.py:36` `_AT_PCT` | Stage 42 says TOUCH |
| `0.12%` | % | **29** | `zone_intel.py:234` `tol_pct` | Zone Intel says beyond |
| `0.35%` | % | **86** | `zone_intel.py:385`, `vob_minimal.py:6389` | Zone Intel says at_zone |
| `0.35%` | % | **86** | `vob_minimal.py:10612` (also `backfill.py:105`, since archived) | `near_support` / `near_resistance` |

**Three of these disagree by 3×.** A NIFTY spot 40 points below resistance is
simultaneously *at* the level (Zone Intel, 86-pt band), *not at* the level (Stage 42,
29-pt band), and *not at* the level (simple entry, 25-pt band). All three publish to the
UI. That is the concrete form of the problem the brief describes.

---

## 2 · The twelve requested states, mapped to what already exists

| Requested | Existing owner(s) | Verdict |
|---|---|---|
| `APPROACHING` | **nobody** | 🆕 genuinely new — no owner has "closing in, not yet arrived" |
| `TOUCHING` | A `TOUCH` + A `WATCHING` | exists, split in two; `WATCHING` is duration, not a state |
| `ABSORBING` | A `ABSORPTION` | exists, single owner ✅ |
| `REJECTING` | A `REJECTION` · B2 `rejected` · D `REJECTING` | **3 owners** |
| `ACCEPTING` | A `ACCEPTANCE` + `CONFIRMED_BREAKOUT` + `CONFIRMED_BREAKDOWN` · B2 `accepted` · D `ACCEPTING` | **5 names, 3 owners** |
| `BREAKING` | A `BREAK` · B `breaking` + `broken` · D `BREAKING` | **4 names, 3 owners** |
| `FAILED_BREAKOUT` | A `FAILED_BREAKOUT` + `FAILED_BREAKDOWN` | exists, direction-split |
| `BULL_TRAP` | A `BULL_TRAP` · B2 `trap` | 2 owners |
| `BEAR_TRAP` | A `BEAR_TRAP` · B2 `trap` | 2 owners |
| `RECLAIMING` | B `recovered` · F `_candle_sweep_reclaim` · `_zone_memory['reclaimed']` · E `REVERSED` | **4 owners, no shared definition** |
| `RETESTING` | B `retest` | single owner ✅ |
| `LEAVING` | **nobody** | 🆕 Stage 42 resets straight to `IDLE`; "was at a level, now walking away" is unrepresentable |

**Ten of twelve already exist.** Two are new, and both are about *movement relative to the
level over time* — which is exactly the axis the 25-point rule was standing in for.

### States that exist today and have no home in the twelve

| Orphan | Owner | Recommendation |
|---|---|---|
| `SWEEP_BUY` / `SWEEP_SELL` | A | **Not a state — a `interaction_type`.** A sweep is a `FAILED_BREAKOUT` that lasted ≤1 cycle and went <0.25% deep. Stage 42 already computes exactly that (`_SWEEP_MAX_CYCLES`, `max_beyond`). Moving it to `interaction_type` is what the new field is *for*. |
| `IDLE` | A | **Keep as a null sentinel.** Without it, every cycle must claim an interaction that is not happening. This is one addition to the twelve, not a reduction. |
| `under-attack` | B | **Not a state — a confidence penalty.** It means the defender groups disagree; that is `interaction_confidence`, not `interaction_type`. |
| `building` / `holding` | B | **Not interaction — health.** Who is defending the level. Stays in Zone Intel, feeds `interaction_strength`. |
| `created` / `untested` / `retired` | B | **Not interaction — biography.** Stays in Zone Intel entirely. |
| `PINNED` | E | Belongs to the entry gate's own logic (OI magnet), not to level behaviour. Out of scope. |
| `NO_ROOM` / `CHOP_WAIT` | E | Regime/target checks wearing a level-state costume. Out of scope. |

---

## 3 · The 25-point rule — every instance, and what replaces it

The brief says remove it entirely. Here is what "entirely" means.

### 3.1 `simple_entry.NEAR_POINTS` — replace with a state test

Rule 1 becomes: **the level's `interaction_state` is one of the AT-LEVEL states**
(`TOUCHING`, `ABSORBING`, `REJECTING`, `RECLAIMING`, `RETESTING`). `APPROACHING`,
`LEAVING` and `BREAKING` do not qualify.

That is the behavioural test the brief asked for: spot 50 points through support and
*coming back* is `RECLAIMING` and passes; spot 5 points from support and *still falling* is
`APPROACHING` and does not — which is the inversion of today's behaviour, and the correct
one.

### 3.2 `classify_sr_behavior`'s `BUILDING` — **delete the branch** ⭐

This is the most consequential finding in the audit, and it is not an advisory path.

```python
# vob_minimal.py:6683-6688
# ── BUILDING: within 25pt of level (pressure pending — soft tilt)
if abs(dist) <= 25:
    candidates.append((1, 'BUILDING', side, level, 'bull' if support else 'bear'))
```

`BUILDING` means one thing and one thing only: **spot is within 25 points of a level.** No
volume, no wick, no flow, no direction of travel. It then feeds three consumers:

**1 · A directional bias vote** (`vob_minimal.py:9527-9535`):

```python
wt = 2 if state in ('BREAKING', 'REJECTING') else 1
_push("S/R Behavior", direction, detail, weight=wt)
```

Proximity alone casts a weight-1 bullish vote at support and bearish at resistance.

**2 · A live Telegram entry alert** (`vob_minimal.py:12139` → `:12152`):

```python
action_ok = st_state in ('REJECTING', 'BUILDING', 'ACCEPTING') and lvl
...
if opt_dir == 'bull' and action_ok and st_dir == 'bull':
    result['signal'] = 'CALL'
```

`compute_fresh_entry_signal` accepts `BUILDING` as its entire "spot price action" layer,
and `send_fresh_entry_alert` — called unconditionally at `vob_minimal.py:9825` and
documented in its own docstring as *"the ONLY automated alert on the main Telegram bot"* —
fires a **BUY CALL / BUY PUT** message off it.

**3 · The status line and the intelligence panel** (`:11204`, `:12168`) which render it as
`· building`.

So the exact scenario in the request — *"spot enters S/R and goes 50 points more"* — today
produces a **BUY CALL blast on the main bot at the top of the 50-point fall**, because at
5 points, 15 points and 24 points below support the state was `BUILDING` and the direction
was `bull` the whole way down. Nothing in the chain ever asked which way price was moving.

The other four branches (`BREAKING`, `REJECTING`, `ACCEPTING`, `NONE`) are candle geometry
that Stage 42 already covers with strictly better evidence (volume, CVD, money flow, OI,
dealer direction, and a *reference point in time*). Recommendation: after 42.5 ships,
`classify_sr_behavior` stops producing states and becomes an **evidence input** —
"last bar wicked through and closed back" — feeding 42.5's `supporting_evidence`.

**Blast radius of deleting `BUILDING`:** four call sites (`:9527`, `:10817`, `:11204`,
`:12133`). `:10817` only reads `BREAKING` and is unaffected. `:9527` loses a weight-1 vote.
`:11204` and `:12133` need the replacement state test from §3.1. `send_fresh_entry_alert`
becomes strictly quieter — it will no longer fire on proximity, only on a reaction.

### 3.3 The alert senders' `proximity_pts=25` — **record, do not touch yet**

`send_atm_wall_vob_entry_alert` (`:11792`) and `send_spot_sr_legs_confluence_alert`
(`:11950`) both take `proximity_pts=25` as a default and both fire real Telegram entries
off it. `entry_gate._prox` (`:7408`), the reversal watch (`:8377`) and the OI-pin band
(`:10797`) are the same family.

These belong to the legacy alert path. Rewriting them inside this work would make 42.5 the
*next* alert system rather than the shared layer underneath. They stay on the
already-flagged list — and that list is longer than previously reported:

> **The app has at least five parallel entry-alert paths**, not three: legacy `entry_gate`,
> `send_fresh_entry_alert`, `send_atm_wall_vob_entry_alert`,
> `send_spot_sr_legs_confluence_alert`, the MIOS V6 chain (72 → 73 → 72.9), and simple
> entry. Consolidating them is its own piece of work, and it is now the highest-value one
> outstanding.

### 3.4 `_zone_memory`'s 25-point bucket — **keep**

`vob_minimal.py:6187` rounds a level price to 25 points to build a memory key. That is
**identity**, not proximity — it stops a cluster average wobbling by a point from creating
a new level every cycle. Different purpose, same number, coincidentally. Leaving it is
correct; a comment saying so is cheap insurance against a future reader deleting it during
the next sweep for "25".

---

## 4 · The two open questions, answered

### 4.1 "Who wins when Stage 42 and Zone Intel disagree?"

**Neither. The question is malformed, and the code shows why.**

Sort Zone Intel's ten lifecycle states by what they actually describe:

| Zone Intel state | Describes | Belongs to |
|---|---|---|
| `created`, `untested`, `retired` | the level's existence | **biography** |
| `holding`, `building` | who is defending it | **health** |
| `under-attack` | that the defenders disagree | **confidence** |
| `breaking`, `broken` | what price is doing to it | **interaction** |
| `retest`, `recovered` | what price is doing to it | **interaction** |

Only **four** of Zone Intel's ten states are level *interaction*. The other six are the
level's biography and health — facts Stage 42 does not compute and never will, because
Stage 42 deliberately has no opinion about a level it is not currently contesting.

So the overlap is not 10-vs-15. It is **4-vs-15**, and even those four resolve cleanly:

- `breaking` / `broken` → Stage 42 wins. It has the reference point (`ref_metrics`
  captured at the moment of the break) and six follow-through checks. Zone Intel's `broken`
  is a status flag copied off the zone dict.
- `retest` / `recovered` → **Zone Intel wins**, and Stage 42 cannot do this at all.
  `zone_intel.advance():140` has a dedicated branch for the post-break arc
  (`broken → retest → recovered`). Stage 42's machine resets to `IDLE` the moment price
  leaves the level's orbit (`acceptance.py:187`), so a level broken at 10:15 and regained
  at 13:40 is, to Stage 42, a fresh `TOUCH` with no history.

**Rule for 42.5:** Stage 42 owns the *within-reaction* states; Zone Intel owns the
*across-reaction* states. Where they genuinely conflict on the same fact, publish both and
lower `interaction_confidence` — the same rule already applied to V5-vs-V6 bias, where a
disagreement is information rather than an error to arbitrate away.

### 4.2 "Is `RECLAIMING` really one state?"

**Yes — but it is not the state I assumed, and it does not collapse the traps.**

The distinction that makes them separate is *which arc price is on*:

| State | Meaning | Evidence today |
|---|---|---|
| `FAILED_BREAKOUT` | A break **attempt** that never established. Price went through, came back, flow has **not** reversed. | Stage 42 `FAILED_BREAKOUT` / `FAILED_BREAKDOWN` |
| `BULL_TRAP` / `BEAR_TRAP` | The same failed break, **plus** the flow that drove it has demonstrably reversed (`_reversal_evidence ≥ 60`). | Stage 42 `_STICKY` |
| `RECLAIMING` | A level **already marked broken** — possibly hours ago — that price has regained and is holding on the original side. | Zone Intel `broken → retest → recovered` |

`FAILED_BREAKOUT` is about a break that never took. `RECLAIMING` is about a level that
*was* lost and has been taken back. They are different events on different clocks, and the
code already separates them into different branches of different modules. Keeping all four
names is correct.

**One simplification the standardisation does buy:** the direction-split pairs collapse,
because `side` (SUPPORT/RESISTANCE) already carries the direction.

- `FAILED_BREAKOUT` + `FAILED_BREAKDOWN` → `FAILED_BREAKOUT` (a failed break of a *support*
  **is** a failed breakdown)
- `CONFIRMED_BREAKOUT` + `CONFIRMED_BREAKDOWN` + `ACCEPTANCE` → `ACCEPTING`, with
  `interaction_confidence` carrying the difference between "accepted" and "confirmed"
- `SWEEP_BUY` + `SWEEP_SELL` → `FAILED_BREAKOUT` with `interaction_type = "sweep"`

Stage 42's fifteen states become twelve **without losing a single distinction** — three
pairs were encoding direction in the state name, and one pair was encoding speed. Both now
have proper fields.

---

## 5 · The four exposed fields — what each can actually be built from

| Field | Buildable today? | Source |
|---|---|---|
| `interaction_distance` | ✅ | `spot − price`, in **points, %, and multiples of the level's own observed reaction width**. The third unit is the point: `acceptance.py` already tracks `max_beyond` (the deepest excursion during this interaction), so distance can be normalised by *how far this level has actually been pushed*, not by a constant. A 25-pt band is wrong on a 90-pt range day and wrong again on a 400-pt day; `max_beyond` is measured. |
| `interaction_strength` | ✅ | `acceptance._score(checks)["pct"]` — six weighted follow-through checks with unknowns excluded from the denominator. Already unknown-safe. |
| `interaction_type` | ⚠️ partial | `sweep` is derivable today (`cycles_beyond ≤ 1 and max_beyond < 0.25`). `probe` / `test` / `drive` / `grind` need a vocabulary defined before they mean anything; do **not** ship placeholder values. |
| `interaction_confidence` | ✅ | `acceptance._confidence()` — already state-aware, 0–97 — penalised when Zone Intel reports `under-attack` or `health.conflicted`. |

### The six published fields from the brief

| Field | Status |
|---|---|
| Current State | ✅ Stage 42 + Zone Intel, per §4.1 |
| Previous State | ❌ **one-field gap.** `acceptance.py`'s memory dict stores `state` but never the prior one. Adding `prev_state` to the returned memory is the whole fix. |
| State Confidence | ✅ `_confidence()` |
| State Duration | ⚠️ in **cycles** today (`cycles_beyond`); duration in *seconds* needs a per-state entry timestamp — the memory dict is the place, `mios_v5/clock.py` is the clock. Publish both; cycle length varies with the refresh interval and a cycle count alone is not comparable across sessions. |
| Transition | ❌ falls out of Previous → Current once `prev_state` exists |
| Supporting Evidence | ✅ `checks` + `reasons` already assembled and already carried into `EngineResult.evidence` |

---

## 6 · Hazards found while reading — fix these regardless

### 6.1 Three writers to one `lifecycle` key, last one wins

`vob_minimal.py:14430` runs the pipeline in this order:

```
build_reaction_sr()  →  annotate_sr_trend()  →  enrich_zone_intel()
```

- `annotate_sr_trend` (`:6097`) writes `z['lifecycle']` from **its own five-state
  vocabulary**: `broken · under-attack · building · fading · stable`.
- `enrich_zone_intel` (`:6355`) then **overwrites** `z['lifecycle']` with Zone Intel's
  ten-state vocabulary.

Consequence: **`fading` and `stable` are written every cycle and never read** — they are
not in `zone_intel._LIFECYCLE_ORDER`, so nothing downstream can consume them. They survive
only when the `from mios_v5.zone_intel import build_zone_card` at `:6367` throws, which
means a stale-import failure silently swaps the *vocabulary* of a field the Decision Engine
gate and the Telegram message both read. `z['trend']` (`:6176`) is still derived from the
overwritten value, so the two fields can disagree by construction.

This is the same **writer-without-a-reader** class as `_atm_leg_ltf_delta` and the three
uncalled frozen stages. It should be fixed whether or not 42.5 is built.

### 6.2 Stage 42 only ever sees two levels

`engines/stage42_acceptance.py:85` loops over exactly `("support", "resistance")` from
`_reaction_sr` — the single best level per side. The ranked `_sr_levels` list that the S/R
panel draws (and that `_mios_market_read()` reads) can hold several per side, and **none of
them past the first has a Stage 42 verdict.**

So 42.5 launches covering **two levels**, not the level list. That is a real scope limit,
not a defect, but it must be stated in the frozen contract — otherwise the first consumer
that asks "what is the interaction state of the #2 resistance?" gets `UNKNOWN` and assumes
a bug.

### 6.3 Two memories, keyed differently

- Stage 42's memory is keyed `"support"` / `"resistance"` (`runner.py:274` →
  `_acceptance_memory`). When the canonical support *changes price*, the memory carries
  over to a different level with the same key.
- `_zone_memory` (`vob_minimal.py:6183`) is keyed by 25-point price bucket, so it follows
  the level.

These disagree the moment the canonical S/R re-ranks. 42.5 needs **one** key, and the
bucketed one is correct — a level's identity is its price, not its rank.

---

## 7 · What this justifies building

**Justified:**
1. `mios_v5/level_interaction.py` — a pure module: the twelve states + `IDLE`, the
   mapping tables from Stage 42's fifteen and Zone Intel's four interaction states, and the
   four `interaction_*` fields. Computes nothing; consumes finished output. Frozen output
   object, deep-immutable, with `id`/`version`/`created_at`/`hash`/`verify()` like every
   other frozen stage.
2. `prev_state` + a state-entry timestamp added to Stage 42's memory dict — the single
   field that unlocks Previous State, Transition and State Duration.
3. `simple_entry` rule 1 rewritten from `NEAR_POINTS` to the AT-LEVEL state test; the
   constant deleted.
4. `classify_sr_behavior`'s `BUILDING` branch deleted, and its four consumers moved to the
   state test — a directional bias vote **and a live main-bot Telegram entry** cast on
   distance alone (§3.2). This is the highest-value item on the list and the only one that
   changes what the app sends today.
5. A `TradingContext` root (`level.*`) so every downstream engine reads one object, and
   a UI surface for it — **Principle 12**: nothing may influence a trading decision unless
   the trader can inspect that exact value somewhere in the UI.

**Not justified — do not build:**
- Any new *measurement*. 42.5 computes nothing. Every input already has an owner.
- `interaction_type` values beyond `sweep` until the vocabulary is defined. A placeholder
  string is worse than `UNKNOWN`, because it reads as a measurement.
- Rewriting `entry_gate`, `send_atm_wall_vob_entry_alert` or
  `send_spot_sr_legs_confluence_alert`. That is the five-alert-paths consolidation (§3.3),
  and doing it here would make 42.5 the next one rather than the layer underneath.
- Extending Stage 42 to the full ranked level list. Real work, separate change, and the
  frozen contract should say so rather than pretend otherwise.

**Assumptions made in this audit, stated because they change the shape of the build:**
- `IDLE` is retained as a thirteenth null sentinel. Twelve states with no way to say
  "nothing is happening" would force a false claim every cycle.
- `SWEEP_BUY`/`SWEEP_SELL` become `interaction_type`, not states. If sweeps should stay
  first-class states, that is a fourteen-state contract and the mapping table changes.
- `RECLAIMING` and `FAILED_BREAKOUT` stay separate per §4.2.

---

## 8 · Freeze conditions

The brief says freeze it afterwards. It should not be frozen until:

1. All six published fields are real — which means `prev_state` exists, so Transition and
   Duration are measured rather than `UNKNOWN`.
2. The two-level scope limit (§6.2) is written into the contract, not discovered by a
   consumer.
3. The three `lifecycle` writers (§6.1) are down to one, so "current state" has exactly
   one producer at the moment it is frozen.
4. Every `interaction_*` field is visible in the UI. Freezing a contract nobody can inspect
   freezes the guesses along with it.
