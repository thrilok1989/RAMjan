# MIOS V6 — Where It Actually Stands

*Audit taken at `25dbbfc` (2026-07-30), verified against the running code in
`vob_minimal.py` and the `mios_v5/` package — not against the roadmap.*

---

## The one-line answer

**V6 is code-complete through Stage 71.7 and cannot be promoted, because the
commit that slimmed the app to "what V6 reads" also removed the writers that
produce the evidence promotion requires.**

Every analytical engine on the locked roadmap exists, is tested and renders.
Two engines are unbuilt (46, 71.8) and both are declared rather than faked.
Wave 7 has not started. But the binding rule — *"nothing influences a decision
until it has proven itself; promotion requires 2–4 weeks of live data"* — now
has no path to being satisfied, and that is the finding this audit exists for.

---

## 1. Build status by wave

Verified by file existence + registry membership + green tests, not by the
roadmap's own checkmarks.

| Wave | Scope | Status |
|---|---|---|
| **1** Signal Protection | 44, 53 | ✅ built · registered |
| **2** Entry Intelligence | 42, 45 | ✅ built · registered |
| **3** Market State | 37, 43, 47, 48, 50, 51, 54 | ✅ built · registered · **frozen** |
| **4** Decision | 52 built · **46 never built** | ⚠️ incomplete |
| **5** Dashboards | `ui/dashboard_v6.py`, six tabs | ✅ built |
| **6** Validation | 55–60 + Stage 70 | ✅ **code** built · ⛔ **no data** (§4) |
| **6.5** Explainability | 61–67 | ✅ built |
| — | 68 Day Type · 69 Session | ✅ built |
| — | 71 · 71.5 · 71.7 Opportunity Matrix | ✅ built · **71.8 not built** |
| **7** Performance | VPFR/news caching, write batching, latency | ❌ **not started** — zero code |

**`ALL_ENGINES` holds 47 engines.** The Learning layer (55–60), the
Explainability layer (61–67), Stage 70 and the entire Stage 71 stack are
correctly *absent* from that registry — they observe, they do not vote. Tests
assert the absence rather than documenting it.

### The two named absences

Both are handled the way principle 9 demands — reported by name, never
defaulted to a number:

* **Stage 46 — Market Control.** The last unbuilt item in Wave 4. It has no
  module, no engine file and no consumer. Nothing reads a hole where it should
  be, so its absence degrades nothing; it simply means "who controls this
  market" is a question V6 still cannot answer.
* **Stage 71.8 — Strike Validation.** Named in `premium_energy.MISSING_INPUTS`
  and surfaced as MISSING in the panel. Stage 71.7 scores without it rather
  than scoring it as zero.

---

## 2. What changed most recently

The last two working days did more to V6's *shape* than to its engine count.

| Commit | Effect |
|---|---|
| `cfb6c93` | **`vob_minimal.py` 35,916 → 13,996 lines** — 61% removed as invisible to V6 |
| `ecd9e43` | Fixed the V6 Trading-tab crash the reduction caused; restored the Trade Card |
| `5e98608` | Dhan 502 survived instead of blanking for five minutes |
| `7e73db4`, `9fb157b` | Trade Card explains its own absence; chart shows one session |
| `e99fe49` | **Stage 71.7 — Premium Energy & Spike**, folded into the Stage 71 stack |
| `e1f9ad7` | Dropped a horizon parameter that was reporting a precision it did not have |

**Test suite: 1,240 passing, 0 failing** (`pytest mios_v5/tests`, 6.2s).

---

## 3. The architecture is no longer four generations

`MIOS_BIBLE.md` Part 0 opens on the idea that four generations run
simultaneously and that **"only Generation 1 can fire an alert or arm a
trade."** After `cfb6c93` that is no longer true of the running code.

`_render_main_analyzer()` now says so in its own docstring:

> *"This is the whole app now. Everything the native layer used to draw between
> these steps — its own Trade Card, ~40 expanders, 39 charts, every Telegram and
> Discord alert, the AI advisors, the auto-trade panel and the v0/v2 decision
> engines — is gone, because no V6 stage read any of it."*

Combined with `RETIRE_ENTRY_ALERTS = True` (which suppresses all ten
entry-tier alert classes at the send layer) and `send_discord_message()`
returning immediately as a no-op, the position today is:

> **Nothing in this application arms a trade or fires a trade-call alert.**
> The system is 100% observational, end to end.

That is a defensible state — it is the conservative direction — but it is a
different system from the one the Bible describes, and the difference is the
root of §4.

---

## 4. ⛔ The blocking finding — the validation pipeline has no writer

Wave 6 is the phase V6 must pass to be promoted. Its storage is five
append-only tables (`sql/027_learning.sql`) plus `signal_outcomes`
(`sql/008`). Stages 55–60, Stage 70 and Stage 40 all read them.

**Nothing writes them any more.**

```
$ grep -rn "insert_signal_outcome|update_signal_outcome|
            insert_trade_attribution|insert_engine_attribution" --include=*.py .
db/supabase_client.py:301:    def insert_trade_attribution(...)
db/supabase_client.py:311:    def insert_engine_attribution(...)
db/supabase_client.py:1229:   def insert_signal_outcome(...)
db/supabase_client.py:1241:   def update_signal_outcome(...)
                              ← four definitions, zero call sites
```

Before the reduction, all four had live callers:

| Call site (at `ad75d28`) | Wrote |
|---|---|
| `vob_minimal.py:17165` `db.insert_trade_attribution(row)` | Stage 55 trade row |
| `vob_minimal.py:17172` `db.insert_engine_attribution(rows)` | Stage 55 per-engine rows |
| `vob_minimal.py:22067` `db.insert_signal_outcome(_row)` | Stage 40 outcome row |

`git log -S insert_signal_outcome` names the commit that removed them:
**`cfb6c93` — "Reduce vob_minimal.py to what MIOS V6 actually reads."**

### Why the reduction missed this

The reduction's method was exact and is documented in `V6_DEPENDENCY_AUDIT.md`:
build the closure of everything V6 **reads**, delete the rest. That method is
correct for its question and structurally blind to this one. The learning
writers are not read by any stage — they are the stages' *output*, landing in
Supabase and returning on a later day. They produce no read edge, so they fell
outside the closure exactly as designed.

The audit's own §1 already recorded two corrections of this shape ("a call
graph is not the whole graph", "`ast.Call` misses a reference"). This is the
third and the most consequential, because it is silent: nothing crashes, no
test fails, and the Learning dashboards render their honest empty-state
message — *"No per-engine attribution rows yet"* — which is
indistinguishable from "we have not traded yet."

### What it costs

| Blocked on missing data | Consequence |
|---|---|
| Stage 52 v2 going live | Gate needs Wave 6 to show v0 beats the Entry Gate — no rows, no comparison |
| Stage 69 `SESSION_AWARE = True` | Counterfactual replay needs a graded history |
| Stages 56–60 (accuracy, calibration, thresholds, Shapley, false signals) | All read attribution rows |
| Stage 40 bias/outcome validation | The comment at `vob_minimal.py:644` still claims *"the LIFECYCLE (arm → track → log to signal_outcomes) still runs"* — **it does not; the caller was removed.** |

**Every promotion gate in V6 is now waiting on evidence that is no longer
being collected.** The clock on "2–4 weeks of live data" is not running.

---

## 5. Promotion switches — all correctly off

| Switch | Value | Correct? |
|---|---|---|
| `session.SESSION_AWARE` | `False` | ✅ — modifiers computed, published, applied by nobody; `modifier_for()` returns `{}` |
| Stage 52 v2 live | No | ✅ — gated on Wave 6 |
| `advisory_only` | Present across 13 V6 modules | ✅ |
| Stage 71 stack in `ALL_ENGINES` | Absent | ✅ — asserted by `test_opportunity.py:74` |
| Learning layer mutators | None | ✅ — asserted by `test_learning_v6.py:435` |

The discipline here is intact and enforced by tests rather than convention.
This is the healthiest part of the system.

---

## 6. The Stage 71 stack — built past a freeze, legitimately

Wave 3 was declared 🧊 **FROZEN** with the rule "no new analytical engines."
Stages 71, 71.5 and 71.7 were built after it. They do not violate the freeze:
each is an **orchestrator** that computes no market fact, fuses only what
Stages 11–52 already published, is absent from `ALL_ENGINES` and carries
`advisory_only` throughout.

The anti-double-count discipline carried forward correctly.
`horizon_owner.py` holds **93 producers, each in exactly one category**:

| Category | n | Votes |
|---|---|---|
| `OWNED` | 52 | ✅ once |
| `STABILITY` | 3 | ❌ shapes the veto |
| `AGGREGATE` | 15 | ❌ shown |
| `EXCLUDED` | 8 | ❌ shown |
| `NON_DIRECTIONAL` | 15 | ❌ hidden |

This is Stage 53's lesson applied one level up: without it, one CVD read fed
into scalp *and* midday *and* intraday would render as "three horizons agree."

The `positional` horizon is honestly marked `DEGRADED` — *"uses current + next
expiries — reliable to several days, not multi-week positioning."*

---

## 7. Documentation drift

`MIOS_BIBLE.md` is the reference and is now stale in ways that matter, all of
it caused by the same reduction:

| Claim | Reality |
|---|---|
| "1,123 tests, all passing" | **1,240** passing |
| "`vob_minimal.py`, 35,843 lines" | **13,996** |
| Part 15 line refs (`:178`, `:18294`, `:28165`, `:31218`) | All stale — file is 61% shorter |
| §15.2 hardcoded Discord webhook | **Resolved** — removed; `send_discord_message` is a no-op pending `market_events` migration |
| Bare `except:` at `:169` | Now 4 occurrences (`:571`, `:2229`, `:2245`, `:2258`) |
| "Four generations run at once" / "only Gen 1 can arm a trade" | Gen 1's decision surface is gone; **nothing arms a trade** (§3) |
| §7.7 documents 71 and 71.5 | **71.7 is undocumented** in the Bible |
| Part 15 omits it | The severed learning pipeline (§4) is not recorded anywhere |

---

## 8. Recommended order of work

1. **Restore the learning writers.** Re-attach `insert_signal_outcome`,
   `insert_trade_attribution` and `insert_engine_attribution` to the reduced
   render path, taking the call sites from `ad75d28`. Nothing else on this list
   matters until the evidence clock is running again. Add a test that fails
   when a `sql/027` or `sql/008` table has no writer — the class of regression
   that a read-closure audit cannot catch should be caught by an assertion.
2. **Fix the stale comment at `vob_minimal.py:644`**, which asserts a lifecycle
   that no longer runs. A comment that lies about persistence is worse than no
   comment, because it is what someone will check first.
3. **Then wait.** 2–4 weeks of logged live data, per the rule that outranks the
   roadmap. Nothing about V6 improves faster than this.
4. **Wave 7** (caching, batching, latency) is safe to do during the wait — it
   is the only remaining work that adds no logic and needs no evidence.
5. **Stage 46 and Stage 71.8** stay unbuilt until the admission rule is
   answered for each. Neither is blocking; both are honestly declared.

---

## Verdict

| | |
|---|---|
| **Engines** | 47 registered · Waves 1–3 complete and frozen · 46 unbuilt |
| **Decision** | Stage 52 v2 built, correctly not live |
| **Dashboards** | Wave 5 complete; Stage 71 stack on the Trading tab |
| **Explainability** | 61–67 complete |
| **Learning** | Code complete · **data pipeline severed** ⛔ |
| **Performance** | Wave 7 not started |
| **Tests** | 1,240 green |
| **Current stage** | **Stage 71.7 · end of build, start of validation — with validation blocked** |

V6 has finished building and has not started proving. The gap between those two
is the whole remaining project, and right now it is not closing.
