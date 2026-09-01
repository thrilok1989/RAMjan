# Survey — duplication across the whole repository

*Fetch · analysis · storage · display. Measured, not eyeballed.*

Everything below is reproducible:

```bash
python tools/dupscan.py        # structural clones — same function, any name
python tools/reachability.py   # what the app can actually reach; fetch + storage maps
python tools/fact_owners.py    # who computes each fact, who displays it
```

The clone detector normalises identifiers and literals before hashing a
function body, so it finds duplicates that were **renamed**, not just copied.

---

## Headline

| | |
|---|---|
| Python files (excl. tests) | 225 · **104,960 LOC** |
| Functions scanned | 2,122 |
| **Structural clone groups** | **69** |
| **LOC unreachable from `vob_minimal.py`** | **22,795** (44 files, ~22%) |
| Supabase tables | 51 · **only 2 touched by more than one file** |
| `@st.cache_data` in the 14,269-line entrypoint | **6** |

**The storage layer is the one that is already right.** Everything else has
between two and three copies of itself.

---

## 1 · The triplication spine

The dominant pattern in this repo is one calculation existing in **three**
places:

```
indicators/<thing>.py   →   vob_indicators.py   →   inline in vob_minimal.py
   (a module)                (a second copy)          (the copy that RUNS)
```

`vob_minimal.py` imports **only two** modules from `indicators/`:
`money_flow_profile` and `volume_delta`. Every other indicator it uses, it
**defines inline** — beside a module that already defines it identically.

Structural clones, largest first (statement counts from `tools/dupscan.py`):

| Function | Stmts | Copies |
|---|---|---|
| `display_comprehensive_depth_analysis` | 152 | `seller_features.py:575` · `seller_perspective.py:4713` |
| `detect_candle_patterns` | 136 | `vob_indicators.py:1404` · `vob_minimal.py:3796` |
| `display_market_depth_dashboard` | 80 | `seller_features.py:358` · `seller_perspective.py:4496` |
| `calculate_bearish_reversal_score` | 65 | `indicators/reversal_detector.py:265` · `vob_indicators.py:771` · `vob_minimal.py:450` |
| `detect_blocks` | 57 | `indicators/volume_order_blocks.py:26` · `vob_indicators.py:120` · `vob_minimal.py:1545` |
| `calculate_reversal_score` | 55 | `indicators/reversal_detector.py:129` · `vob_indicators.py:635` · `vob_minimal.py:314` |
| `calculate_vidya` | 53 | `vob_indicators.py:1704` · `vob_minimal.py:4070` |
| `compute_sector_rotation` | 50 | `vob_data.py:474` · `vob_minimal.py:4404` |
| `calculate_dealer_gex` | 50 | `analysis/gex_analyzer.py:6` · `vob_indicators.py:1022` · `vob_minimal.py:1800` |
| `detect_order_blocks` | 49 | `vob_indicators.py:1580` · `vob_minimal.py:3972` |
| `calculate_poc` | 28 | `indicators/triple_poc.py:8` · `vob_indicators.py:242` |
| `calculate_max_pain` | 24 | `vob_indicators.py:841` · `vob_minimal.py:1759` |
| `get_iv_fallback` | 13 | `analysis/greeks.py:23` · `vob_indicators.py:1248` · `vob_minimal.py:2233` |

…and 56 more groups.

### Why this is worse than wasted lines

A bug fixed in `indicators/reversal_detector.py` does not reach the running
app, because the running app never imports it. The module is the obvious place
to look and the wrong place to edit. That is a **maintenance trap**, and it is
already load-bearing: this repo has twice shipped a reader without a writer,
and this is the same failure with the arrow reversed.

---

## 2 · `seller_perspective.py` — 9,026 lines, unreachable

The second-largest file in the repo cannot be reached from the entrypoint. It
duplicates six functions from `seller_features.py` (902 LOC, also unreachable),
including the 152-statement and 80-statement display functions above.

Between them: **9,928 LOC of market-depth analysis that the app never runs**,
duplicated within itself.

---

## 3 · 22,795 LOC the app cannot reach

44 non-test files, ~22% of the repo's Python:

| LOC | File | What it is |
|---|---|---|
| 9,026 | `seller_perspective.py` | a whole second analysis app |
| 1,865 | `vob_indicators.py` | the middle copy of the triplication spine |
| 1,782 | `vob_analysis.py` | |
| 1,751 | `vob_alerts.py` | a second alerting path |
| 902 | `seller_features.py` | |
| 866 | `market_depth_advanced.py` | |
| 787 | `auto_option_trader.py` | **places real Dhan orders** (separate app, by design) |
| 683 | `vob_data.py` | a second data-fetch layer |
| 462 | `generate_analysis_pdf.py` | |
| 422 | `ws_worker.py` | |
| 333 | `indicators/reversal_detector.py` | the module copy nothing imports |
| 318 | `nifty_price_alert.py` | |
| 265 | `discord_bot.py` | separate process, by design |
| 252 | `quick_buy_option.py` | separate app, by design |

Three of these are **deliberately separate processes** (`auto_option_trader`,
`quick_buy_option`, `discord_bot`) and should not be deleted — the Position
Store audit already covers `auto_option_trader`. The rest are not deliberate.

### 3a · Tested, but not running

A subset is worse than dead code — it is dead code **with a passing test
suite**:

| Module | Reachable from the app? | Has tests? |
|---|---|---|
| `mios_v5/order_flow_snapshot.py` | ✗ | ✓ |
| `mios_v5/backfill.py` | ✗ | ✓ |
| `mios_v5/dispatch_validation.py` | ✗ | ✓ |
| `mios_v5/scenario_engine.py` | ✗ | ✓ |
| `mios_v5/story_validation.py` | ✗ | ✓ |
| `mios_v5/lifecycle.py` | ✗ | ✓ |
| `mios_v5/market_state.py` | only from `scenario_engine` (itself unreachable) | ✓ |
| `mios_v5/overlays.py` | only from `ui/overlay_panel.py` (unreachable) | ✓ |

Green tests on all of them. **A test that a module works says nothing about
whether it runs** — the exact lesson `test_execution_chain.py` was written for
after three frozen stages sat uncalled for a day.

---

## 4 · Data fetch — five front doors to one API

| Duplicated thing | Copies |
|---|---|
| `https://api.dhan.co/v2` base URL | `auto_option_trader.py` · `config.py` · `quick_buy_option.py` · `vob_data.py` · `vob_minimal.py` |
| `_dhan_post()` | `api/dhan_api.py` · `auto_option_trader.py` · `quick_buy_option.py` · `vob_data.py` · `vob_minimal.py` |
| scrip-master CSV download | `auto_option_trader.py` · `quick_buy_option.py` · `vob_minimal.py` |
| `validate_credentials()` | `api/dhan_api.py:155` · `vob_data.py:210` |
| `get_option_ltp()` | `vob_data.py:117` · `vob_minimal.py:1108` |
| `_fetch_yf_intraday()` | `vob_data.py:449` · `vob_minimal.py:4380` |

`api/dhan_api.py` exists and is the obvious owner — and the entrypoint does not
import it. Retry policy, rate-limit handling and error shape are therefore
defined five times, and a fix to one is a fix to one.

---

## 5 · Storage — the layer that is already correct ✅

51 tables. **Only two are touched by more than one file:**

| Table | Files |
|---|---|
| `market_events` | `db/supabase_client.py` · `discord_bot.py` |
| `market_stories` | `db/supabase_client.py` · `mios_v5/story_integration.py` |

`db/supabase_client.py` is a real gateway, and `db/read_cache.py`,
`db/write_batch.py` and `db/retention.py` sit behind it. This is what the rest
of the repo should look like, and it is worth saying plainly: **no storage
consolidation work is needed.**

(`discord_bot.py` is a separate process with its own client — expected. Only
`market_stories` is a genuine second writer inside the app.)

---

## 6 · Display — the same fact on many panels

| Fact | Files rendering it |
|---|---|
| Entry | 12 |
| Confidence | 11 |
| Resistance | 10 |
| Bias · Support | 10 · 9 |
| POC | 8 (`dashboard_v6` · `htf_panel` · `liquidity_panel` · `profile_overlay` · `strike_validation_panel` · `terminal_chart` · `vob_alerts` · `vob_minimal`) |
| VAH / VAL | 7 each |

**This is not automatically a defect.** Principle 12 *requires* a value to be
inspectable, and the same level legitimately appears on a chart, in a level
table and in a decision card. The question for each is whether the panels read
**one owner** or recompute.

What *is* a defect is the constant tables. Despite `ui/theme.py` existing:

- **5** separate `BULL/BEAR/NEUTRAL` colour maps (`family_panel` ×2,
  `htf_panel` ×2, `transition_panel`)
- **4** separate lowercase `_TONE` maps (`absorption_panel`, `ltp_panel`,
  `state_panel`, `terminal_panel`)
- **3** separate grade maps for `A+ / A / B / C` (`dashboard`,
  `execution_panel`, `premium_behaviour_panel`)

Bull green means three different hexes depending on which panel you are looking
at. That is a *readability* bug, not just duplication.

---

## 7 · Recomputation inside one cycle

Call sites in `vob_minimal.py`, all in a path that reruns every ~20 seconds:

| Function | Call sites |
|---|---|
| `calculate_money_flow_profile()` | **11** |
| `compute_vpfr()` | **8** |
| `detect_blocks()` | 5 |
| `compute_dynamic_poc()` · `calculate_dealer_gex()` · `calculate_vidya()` | 4 each |
| `calculate_greeks()` | 3 |

Against **6** `@st.cache_data` decorators in 14,269 lines.

This is the same shape as the Supabase egress problem — which was fixed by
caching reads (96.8%) and batching writes (99.5%) — but on CPU rather than
network. Nobody has measured it, and this survey does not either: **the number
of call sites is not the number of executions**, and some are on branches that
rarely run. It is a place to measure, not a proven cost.

---

## What to fix, in order

| # | Action | Risk | Why first |
|---|---|---|---|
| 1 | **Delete or archive the unreachable analysis files** — `seller_perspective`, `seller_features`, `vob_indicators`, `vob_analysis`, `vob_alerts`, `market_depth_advanced`, `vob_data`, `generate_analysis_pdf`, `nifty_price_alert` | low — nothing imports them | removes ~17,000 LOC and **two thirds of every clone group**, without touching a line the app runs |
| 2 | **Decide the fate of the tested-but-unreachable `mios_v5` modules** (§3a) — wire or retire | low | each is either a missing caller or dead weight, and today they are neither |
| 3 | **One Dhan client.** Make `api/dhan_api.py` the owner; the entrypoint imports it | medium — touches the live fetch path | retry and rate-limit policy stop being defined five times |
| 4 | **Collapse the UI constant tables into `ui/theme.py`** | low | bull green stops meaning three hexes |
| 5 | **Measure the per-cycle recompute** before optimising | — | §7 is a hypothesis; a profile turns it into a fact |
| 6 | Storage | **none** | already correct |

### The one thing not to do

**Do not "deduplicate" by pointing `vob_minimal.py` at the module copies.**
The inline copies are what runs and what has been debugged in production; the
module copies are what has drifted unobserved. Deleting the unused copy is
safe. Switching the running app onto it is a behaviour change disguised as a
cleanup, and the clone detector cannot tell you whether the two have diverged
in a way that matters — only that they started the same.

If a module copy is ever promoted to the owner, it needs a diff of the two
bodies read line by line first, not a hash match.
