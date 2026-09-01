# Stage audit — are all 47 stages working, reporting, and consumed correctly?

Prompted by: *"in many places the app says some stages are not reporting."*

Method: run the **real** orchestrator against a session-state fixture built from
shapes verified against `vob_minimal.py`, then read every engine's status. Then
run the **real** cockpit collectors and see which display blocks stay silent.
Then derive producer/consumer graphs from the AST for both `session_state` and
`raw`.

---

## 1 · The engines themselves are healthy

All 47 engine classes are defined **and** registered — `ALL_ENGINES` matches the
class list exactly, nothing orphaned either way.

With correctly-shaped inputs:

| status | count | stages |
|---|---|---|
| **OK** | 40 | 00 02 04 05 06 11 12 13 14 17 18 19 20 21 22 23 24 25 27 28 29 30 31 33 34 35 36 37 38 39 44 45 47 48 51 52 53 54 68 69 |
| **NEUTRAL** | 6 | 03 memory · 26 patterns · 40 learning · 42 acceptance · 43 absorption · 50 ltp_behaviour |
| **DISABLED** | 1 | 15 microstructure |
| **ERROR** | 0 | — |

The 6 NEUTRALs are honest warm-up states, not faults: `03` needs a previous
session, `50` needs enough LTP history to read intent, `43` depends on `50`,
`40` needs a DB handle, `26` found no pattern, `42` needs canonical S/R. `15` is
DISABLED by design — Level-2 depth does not exist at retail.

### ⚠️ A methodology warning worth recording

My **first** run showed 5 stages in ERROR (`04`, `17`, `35`, `36`, `45`). Four of
those were **my fixture's shapes, not the app's**:

| I assumed | the app really publishes |
|---|---|
| `oi_pin` = `{"strike":…}` | **tuple** `(strike, note)` — `vob_minimal.py:7387` |
| `sup` / `res` = list of zones | **dict** for the single chosen zone — `:7336`, `:7345` |
| `_full_market_read` = `{"bias":…}` | 20+ keys incl. `call_mode`, `breakout` — `:10602` |
| `_leg_bias_cache` = `{}` | **tuple** `(rows, overall)` — `:9088` |

An audit fixture that does not match production shapes manufactures bugs. Every
finding below was re-verified against the real producer before being called a
bug.

---

## 2 · Fixed: the cockpits ran before their producer

**This is the answer to "some stages are not reporting".** The captions say
*stages*, but they list **display blocks that returned empty HTML**.

`st.tabs()` returns containers fillable in any order — the strip's layout comes
from `_TABS` and is unaffected by fill order. But the bodies have a real
dependency:

```
_charts_screen    writes  _leg_profiles
_trading_screen   reads   _leg_profiles
                  writes  _sr_levels · _premium_energy
                          _premium_structures · _entry_decision
_nifty_cockpit    reads   _sr_levels · _entry_decision
_options_cockpit  reads   _premium_energy · _premium_structures
```

The three new cockpits were moved to the **front** of the strip. Their producer
was not. Filled in tab order, four keys were read before they were written:

| key | read by (tab) | written by (tab) |
|---|---|---|
| `_sr_levels` | `_nifty_cockpit` (1) | `_trading_screen` (4) |
| `_entry_decision` | `_nifty_cockpit` (1) | `_trading_screen` (4) |
| `_premium_energy` | `_options_cockpit` (2) | `_trading_screen` (4) |
| `_premium_structures` | `_options_cockpit` (2) | `_trading_screen` (4) |

Consequences:

* **first render of a session** — the keys did not exist, the blocks drew
  nothing, and the tab printed `⚪ Not reporting yet: sr table` /
  `premium energy · premium structure · option flow`;
* **every render after** — they silently showed the **previous cycle's** data,
  one 20-second cycle behind the panels beside them. That is the worse failure,
  because it looks like it is working.

**Fix:** fill order is now `charts → trading → cockpits → …`. Nothing is
recomputed, no engine is touched, and `_TABS` is unchanged, so the strip looks
exactly as before.

### Verified end to end, not just by the graph

Running the real collectors against a fixture built from verified production
shapes:

```
BEFORE (cockpits filled first — the old order)
  NIFTY  : ⚪ Not reporting yet: sr table
  OPTIONS: ⚪ Not reporting yet: premium energy · premium structure · option flow

AFTER (charts → trading → cockpits)
  NIFTY  : ✅ all blocks rendered
  OPTIONS: ✅ all blocks rendered
           _sr_levels · _premium_energy · _premium_structures
           · _entry_decision · _leg_profiles   all published
```

Two blocks needed fixture corrections before this was trustworthy, and both are
worth recording because they are the same class of mismatch as the bug itself:

* `_reaction_sr` zones carry **`price`**, not `level` — `card_from_zone` returns
  `None` without it (`sr_intel.py:328`), so `sr_table` stayed empty;
* the strike picker reads `_cockpit_ctx` (`{sids, seg, api, atm, gap}`,
  `vob_minimal.py:13960`), without which `_strike_validation` never publishes
  `_premium_structures`.

### ⚠️ The bug was documented as expected behaviour

Three comments described this lag as normal, and one was also factually wrong:

| where | said | actually |
|---|---|---|
| `_nifty_cockpit` docstring | `_sr_levels` is published by `_sr_intelligence`, "which runs on the **Intelligence** tab" | `_sr_intelligence` is called by **`_trading_screen`** |
| same | "Reordering the tabs to fix that would move a CRITICAL producer" | no tab has to move — only the **fill** sequence |
| `_options_cockpit` docstring | "on the first rerun of a session the structure and flow blocks are empty and **fill on the next**" | that is the bug, recorded as accepted |
| `_TABS` comment | "Streamlit executes tab bodies **in order**" | it executes them when their container is **filled** |

All four corrected. A note that says "this is expected" beside code where it is
not is how the same bug comes back.

### One cycle remains, and it is genuine

There is a **cycle**: `_charts_screen` writes `_leg_profiles` (trading needs it
first) but also reads `_premium_structures` (trading writes it). Both cannot be
first. `_leg_profiles` wins because `_trading_screen`'s whole execution chain is
built on the leg reads, whereas `_premium_structures` reaches `_charts_screen`
only via `_leg_levels`, where it adds **optional** overlay lines (S/R, VWAP,
entry, stop) that are already `or {}`-guarded — one cycle of lag moves a marker
rather than blanking a panel.

Recorded as `KNOWN_CYCLE` in `mios_v5/tests/test_screen_order.py`, with a test
asserting the list neither grows silently nor goes stale.

---

## 3 · Fixed: one `None` took all of Stage 45 down

`htf_vpfr.migration_summary` (line 299):

```python
((reads or {}).get(t) or {}).get("migration", {}).get("direction")
```

`tf_read` stores `"migration": migration` verbatim and its parameter **defaults
to `None`** — so a timeframe whose migration was never computed holds the key
with a `None` value. `.get(k, default)` returns that `None`, never the default,
and the chained `.get("direction")` raised `AttributeError`, taking **the whole
of Stage 45 to ERROR** — which degrades Stage 51 (validity) and Stage 68 (day
type), both of which depend on it.

The same module gets it right 57 lines earlier: `mg = (migration or {}).get(…)`.

**Fix:** `(… .get("migration") or {})`.

I scanned the rest of `mios_v5` for the same pattern and found 5 more
(`sr_intel:134`, `checklist:132`, `stage40_learning:167-169`). All five are
**safe** — `_as_scored` and `_section` always return a dict, never `None` — so
they were left alone rather than patched for symmetry.

---

## 4 · Fixed: Stage 33's gap signal had never once fired

`stage33_event_impact` tests:

```python
(raw.get("gap_today") or {}).get("type") in ("GAP-UP", "GAP-DOWN")
```

Nothing ever put `gap_today` into `raw`. The data was there the whole time —
`capture_day_open_and_gap` publishes `_gap_today` as
`{'type', 'pct', 'open', 'prev_close'}`, the exact `type` key the engine checks,
and the app header already reads it for the previous close.

**Fix:** forwarded in the runner's `raw` literal. Also forwarded
`cached_raw_chain_latest`, Stage 4's expiry fallback.

This is the same failure as the `fii_net` bug: a key read by one layer, published
under a different name (or not at all) by another, with nothing erroring.

---

## 5 · Reported, NOT fixed

### `open_position` and `zone_extremes` — Stage 52 always decides as if flat

`stage52_decision` reads both; **no key anywhere in the app holds either value**.
So `decide(position={}, …)` runs every cycle as though there is no open trade.

Not patched deliberately. `_entry_signal_open` exists but is a per-leg dict, not
the `position` shape `decide()` expects, and guessing at that contract would
change a **trading decision** to satisfy an audit. This needs a decision about
what `position` should contain.

### Test-injection keys — not bugs

`calendar_today`, `now_ist_time`, `now_ist_dt` are read but never published **by
design**: each engine computes a real default from the IST clock and the raw key
exists so a test can move it. `stage30_calendar` says so in a comment.

### Published but never read — one input, not three

⚠️ **Corrected.** An earlier revision of this document claimed `composite_profile`,
`value_alignment` and `value_migration` were all dead. Two of the three are read:

| key | read by |
|---|---|
| `value_alignment` | `narrative.py:175` |
| `value_migration` | `final_read.py:227`, `narrative.py:157` |
| `composite_profile` | **nothing** — genuinely unread as an engine input |

The false positives came from scanning only `mios_v5/engines/` for `raw` reads.
`narrative.py`, `final_read.py` and `trading_context.py` take `state` and read
`state.raw` too. Re-scanned across the whole package, exactly one input is dead.

Two other apparent gaps were also name collisions, not bugs:

* `close` / `high` / `low` / `open` / `timestamp` / `volume` — `runner.coerce_frame`
  takes a Dhan payload parameter that is *also* called `raw`;
* `_run_report` — written by `orchestrator.py` into `raw`, not by `runner.py`, so a
  runner-only publish scan cannot see it;
* `_err_log_seen` — read by `stage00_health` via `raw.setdefault(...)`, a mutation
  rather than a `.get`.

`fii_deriv` is read only by the new UI panel, not by Stage 23 — which is why that
panel labels its verdict **"STAGE 23 FLOWS (cash)"**.

---

## 6 · Guards added

`mios_v5/tests/test_screen_order.py` — derives the graphs from the AST rather
than hardcoding an order, so moving a tab, adding a block, or moving a
`session_state` write is checked on its own terms:

| test | catches |
|---|---|
| `test_no_screen_reads_a_key_a_later_screen_writes` | a consumer filled before its producer |
| `test_the_known_cycle_is_still_the_only_one_and_is_still_real` | the allowlist growing **or** going stale |
| `test_the_tab_strip_order_is_unchanged_by_the_fill_order` | the layout drifting; a tab filled twice or not at all |
| `test_every_raw_key_an_engine_reads_is_published_or_listed` | an engine reading a raw key nothing publishes |
| `test_a_timeframe_with_no_migration_does_not_take_stage_45_down` | the `None`-vs-default crash |

Reverting the fill order reproduces all four faults by name. Suite: **3066
passed, 3 skipped.**

---

## 7 · Stages 50 – 74 specifically

The range splits across **two mechanisms**, which is why "is stage N reporting?"
has two different answers depending on N:

| stages | mechanism | registry |
|---|---|---|
| 50 51 52 53 54 68 69 | engine classes | `ALL_ENGINES` |
| 55 – 67, 70 – 74 (incl. 71.5 / 71.7 / 71.8 / 71.85 / 71.86 / 71.95 / 72.9) | plain modules called by the UI or runner | **none** |

An engine class at least appears in a registry. A stage implemented as a module
has nothing structurally guaranteeing it is called — so it can go dead in silence.

### Engine classes in range — all reporting

Verified by running the real orchestrator: 50 51 52 53 54 68 69 all return
`OK` with correctly-shaped inputs. (Stage 50 `ltp_behaviour` reports NEUTRAL until
it has enough LTP history, and Stage 43 depends on it — both honest warm-ups.)

### Module stages — 18 of 20 reachable from production

| module | stages | verdict |
|---|---|---|
| `entry_engine` `dispatcher` `profile_shape` `liquidity_context` `futures_oi_store` `checklist` `narrator` `daily_summary` `contribution` `calibration` `false_signal` `learning_report` `explain_decision` `risk_explain` `opportunity` `premium_energy` `strike_validation` `engine_accuracy` | 51–74 | ✅ reached from production |
| `mios_v5/dispatch_validation.py` | 72.9 | **test-only, correctly** — a fault-injection harness that must not run in production; `test_dispatcher.py` exercises it |
| `db/dispatch_registry.py` | 72.9 | ⚠️ **dead** — `SupabaseDispatchRegistry` is never constructed. Already recorded in `AUDIT_EGRESS_4.md` §5: it was the prime suspect for the 1 GB egress day and was **disproved** precisely because nothing builds it |

### Every V6 screen renders clean

All nine screens, run in dependency order against a complete fixture:

```
_charts_screen    0 absence messages
_trading_screen   0
_nifty_cockpit    0
_options_cockpit  0
_decision_center  0
_intelligence     0
_history          0
_learning         1 — "Learning tables not available on this DB client" (db=None)
_replay           0
```

The one message is correct: the learning family (56–60, 67) needs Supabase, and
with no DB handle it says so rather than drawing empty tables.

### ⚠️ Two more false positives I caught in my own scanners

Recorded because both would have produced confident, wrong bug reports:

* **`from . import calibration` has `node.module is None`.** Keying an import
  scan on `node.module` alone misses that form entirely, and it reported
  `calibration` (Stage 57) and `dispatch_validation` as dead. `learning_report.py:66`
  really does call `calibration.by_engine`. `test_stage_reachability.py` now has a
  test guarding *the scanner*, so this cannot silently regress into vacuous passes.
* **`setdefault` both reads and writes.** Counting it as a read alone made 25 live
  session keys look write-only. Adding `st.session_state[var] = …` loop writes
  (dynamic subscripts) cut a 62-key "read but never written" list down to nothing
  provable.

Combined with the four fixture-shape mismatches in §1, that is **six** false
positives this audit generated before verification. Any conclusion here that was
not re-checked against the real producer should be assumed wrong.

---

## 8 · Stage 52's two inputs — one wired, one deliberately not

### `open_position` — ✅ wired, as a one-field rename

The contract turned out to be **derivable**, so it needed no guess. `decide()` and
`_manage()` read exactly three fields — `side`, `entry`, `target` — and nothing
else. `is_open`, `strike`, `quantity`, `entry_time` and `signal_id` are read by
nothing; `side`'s presence already *is* the in-a-position flag.

`_entry_gate_active` was already the authoritative producer, and the arithmetic
proves the mapping rather than assuming it:

```
vob_minimal.py:8266   (spot_price - _act['entry_spot']) if side == 'CALL'
decision_v2.py:187    (st - entry) if up else (entry - st)
```

So `entry_spot` → `entry` is a boundary rename of the same kind
`_mios_market_read` performs. `_entry_signal_open` would have been a genuine bug:
it is per-leg and its `entry` is an option **premium**, so `gain = 24,500 − 120`
would drive TRAIL / SCALE_IN off a meaningless number.

Safe because the lifecycle is real — set only under `if _st_a in ('CALL','PUT')`,
superseded on a new entry, **popped on exit** at two sites — and because Stage 52
is display-only: the dispatch path uses `_entry_decision` from `entry_engine`.

### `zone_extremes` — ⛔ still open, and the finding is worse than reported

Earlier this said "decides as if flat". The truth is stronger: **Stage 52 can
never issue an ENTER at all.**

```
detect_refusal([], floor)                   → {"proven": False}
checks["refusal"]                           → False
confirmed = all(checks[c] for c in CHECKS)  → False   (CHECKS includes refusal)
decide():  if pf.get("confirmed")           → the ONLY path to ENTER
```

`stage52_decision.py:72` defines the input precisely — *"the sequence of lows/highs
made while price sat at the zone"* — and adds *"without it the refusal check cannot
pass, which is correct"*. As fail-safe design that is right; it also means the entry
half of the "final brain" has never run.

Producing it is a new computation, not a rename, and it would take a trade-entry
path from *never fires* to *fires*. Four sampling questions have to be answered
first. Full reasoning: **`docs/CONTRACT_POSITION_STATE.md`**.

---

## 9 · Scanner false positives — the running count

Every one came from an under-scoped scan, and each would have been a confident
wrong bug report:

| # | claim | reality |
|---|---|---|
| 1–4 | 5 stages in ERROR | four were my fixture's shapes (§1) |
| 5 | `calibration` (Stage 57) dead | `from . import X` has `node.module is None` |
| 6 | `dispatch_validation` dead | same cause; it is correctly test-only |
| 7 | `value_alignment` dead | read by `narrative.py:175` |
| 8 | `value_migration` dead | read by `final_read.py:227` |

Plus three name collisions that looked like gaps: `close`/`high`/`low`/`open`/
`timestamp`/`volume` (`coerce_frame` has a payload parameter also called `raw`),
`_run_report` (written by `orchestrator.py`, not `runner.py`), and `_err_log_seen`
(read via `raw.setdefault`, a mutation rather than a `.get`).

**Lesson: scan the whole package, handle every import and access form, and
re-verify against the real producer before calling anything a bug.** Eight of my
own findings did not survive that step.
