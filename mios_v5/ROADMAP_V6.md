# MIOS V6 — Locked Roadmap

Build order: **protect signals → improve confirmations → improve context →
improve decisions → validate → optimize.** Nothing is added that isn't on this
list; the architecture is frozen at the end of Wave 4.

## Numbering

The V6 draft reused stage numbers already taken (36 Story, 37 Briefing, 38
Tomorrow, 39 Pre-Market, 40 Learning, 41 Final Read). **New engines start at 42.**

| V6 draft | Locked | Name |
|---|---|---|
| St39 Sudden Flow Shift **+** St49 Market Stability | **Stage 44** | Sudden Flow Shift + Stability |
| St50 Evidence Correlation | **Stage 53** | Evidence Correlation |
| St36 Acceptance/Rejection **+** St47 Trap Intelligence | **Stage 42** | Acceptance / Rejection / Trap |
| St40 HTF VPFR | **Stage 45** | Higher-Timeframe VPFR |
| St44 Market Condition **+** St45 Market Phase | **Stage 48** | Market State |
| St43 Bias Transition | **Stage 47** | Bias Transition |
| St46 LTP Behaviour | **Stage 50** | LTP Behaviour |
| St50A State Persistence | **Stage 54** | State Persistence |
| St47A Signal Validity Filter | **Stage 51** | Signal Validity Filter |
| St42 Market Control | **Stage 46** | Market Control |
| St38 Hidden Liquidity | **Stage 43** | **Absorption Engine** (renamed) |

---

## The admission rule

Before any new engine is accepted into V6:

> **Can this be merged into an existing evidence family?**
> **YES → merge it. NO → only then create an engine.**

And it must do at least one of: **increase accuracy · reduce false entries ·
improve explainability.** If it does none of those, it does not go in. This is
what keeps the engine count from growing without the intelligence growing.

## Wave 1 — Signal Protection

| Stage | Status | Deliverable |
|---|---|---|
| **44 — Sudden Flow Shift + Stability** | ✅ **BUILT** | Reads the *derivative* (CVD swing · OI velocity · gamma repricing · IV jump · volume explosion · price displacement · money-flow swing) → `⚠️ INSTITUTIONAL FLOW SHIFT · freeze entries · recalculate`. Owns `STABLE → UNSTABLE → SHOCK → RECOVERY`. Non-directional (`Bias.NONE`) — it vetoes, never leans. |
| **53 — Evidence Correlation** | ✅ **BUILT** | CVD, Money Flow, Delta and VOB are the same evidence counted 4×. Group into families, collapse each to one weighted vote, feed the Conflict Engine. **This lowers some confidences — that is the point.** |

## Wave 2 — Entry Intelligence

*Acceptance before HTF VPFR: a better entry beats a stronger confidence score.*

| Stage | Deliverable |
|---|---|
| **42 — Acceptance / Rejection / Trap** ✅ **BUILT** | True breakout · true breakdown · **failed** breakout/breakdown · bull trap · bear trap · liquidity sweep (buy/sell-side) · acceptance · rejection. The main confirmation engine. Merged because a "failed breakout" *is* a bull trap — two engines would disagree with each other. |
| **45 — Higher-Timeframe VPFR** ✅ **BUILT** | 1H · 4H · Daily · Weekly · **Monthly · Yearly** VAH/VAL/POC/HVN/LVN + trend + value migration. Monthly/yearly value areas are major institutional magnets. Feasible from daily history via the existing yfinance path, cached once per day. |
| **41 — Institutional Confluence** | Auto-upgrades once 45 lands (already built; currently fed weak HTF input). |

## Wave 3 — Market State

**Stage 37 — Market Energy** ✅ **BUILT** — *promoted*, not rebuilt: the physics
already lived in Stage 4's context blob as three loose numbers. Now a first-class
engine (state · strength · compression · expansion readiness · release
probability · duration), which closes Stage 51's last `None` gate → **9/9 coverage**.


| Stage | Deliverable |
|---|---|
| **48 — Market State** ✅ **BUILT** | One engine, one responsibility: Trend · Pullback · Rotation · Compression · Expansion · Range · Accumulation · Distribution · Mark Up · Mark Down |
| **47 — Bias Transition** ✅ **BUILT** | `Bear ↓ Weakening` / `Bull ↑ Strengthening` — extends Evolution from "it flipped" to "it's decaying" |
| **50 — LTP Behaviour** ✅ **BUILT** | Price + Money Flow + VOB + Delta + CVD → "Call exhaustion", "Put building", "Selling pressure increasing" |
| **54 — Market Memory** (renamed from State Persistence) ✅ **BUILT** | How long Bear / Bull / Compression / Distribution / Conflict has existed. Feeds 47 and 53. |
| **51 — Signal Validity Filter** ✅ **BUILT** | Check 1H/4H/Daily/Weekly agreement before any entry; reject weak signals. *Blocked on 45.* |
| **43 — Institutional Absorption** ✅ **BUILT** | Buyer/seller absorption · exhaustion · aggressive buying/selling. **Renamed from "Hidden Liquidity": iceberg detection needs L2 depth we do not receive** (that's why Stage 15 is DISABLED). Absorption is measurable; icebergs would be fabricated. |

## 🧊 WAVE 3 FROZEN

With Stage 43 complete the intelligence layer is **done — 44 coordinated
engines**. From here:

> ❌ **No new analytical engines.**
> ✅ Finish the Decision Engine (Wave 4) · finish Dashboard V6 (Wave 5) ·
> spend most effort on Validation & Learning (Wave 6).

The biggest remaining improvements will not come from adding intelligence —
they come from **proving the existing intelligence works consistently in live
markets**. Any proposal for a new engine must first answer the admission rule
above, and now also: *why can't this be a field on an existing engine?*

## Wave 4 — Decision

| Stage | Deliverable |
|---|---|
| **46 — Market Control** | Who controls: Institutions · Dealers · Options · Order Flow · Liquidity · Structure |
| **52 — Decision Engine v2** ✅ **BUILT** | Full trade lifecycle: `WAIT · WATCH · ENTRY READY · ENTER · SCALE IN · HOLD · TRAIL · PARTIAL EXIT · FULL EXIT · ABORT` + adaptive trailing stop + scale logic |

⚠️ **Gate:** v2 does not go live until Wave 6 shows the v0 gate stack beats the
Entry Gate. Validate before you weight.

## Wave 5 — Dashboards ✅ **BUILT**

`mios_v5/ui/dashboard_v6.py` — six tabs, each answering one question:
Decision · Trading · Intelligence · History · Learning · Replay.

**Dashboard 2** carries the **Support & Resistance Intelligence** panel below the
chart: every level as an object (origin · confluence ★ · strength · lifecycle ·
health · acceptance · absorption · trap risk · HTF · defender · local bias ·
entry zone · dynamic stop · adaptive trail · target · confidence · 3-line
summary), **ranked** so the most important level is unmistakably first.

Two gaps are **declared in the UI rather than faked**:
per-engine accuracy needs an outcome-attribution job (the `engine_snapshot` JSON
already captures the inputs), and candle-synced replay stepping needs the
`engine_state` rows joined to the candle series on timestamp.

### Original plan

1. **Decision** ✅ · 2. **Charts** — NIFTY ‖ ATM Call ‖ ATM Put on a **shared
timeline** so a NIFTY reversal, Call VOB and Put VOB are seen changing together
· 3. **Intelligence** ✅ · 4. **History** ✅ · 5. **Learning**

## Wave 6 — Validation *(longest phase)* ✅ **BUILT**

Runs **in parallel from Wave 1 onward**, not at the end. Per engine: win rate ·
profit factor · avg MFE/MAE · false-entry rate · confidence-vs-outcome · engine
contribution.

> **Every engine ships observational-only and logged. Nothing influences a
> decision until it has proven itself.** Promotion requires 2–4 weeks of live
> data. This rule outranks every other item on this roadmap.

### Phase 6 — Learning & Validation Engine (Stages 55–60)

| Stage | Module | Deliverable |
|---|---|---|
| **55 — Trade Attribution** | `attribution.py` | Before-entry state of the world + **one row per engine per trade** · append-only during-trade events (MFE/MAE/trail/partial/flow shift) · outcome row at exit. Without the per-engine rows there is only a blended win rate that cannot say *which* engine to fix. |
| **56 — Engine Accuracy** | `engine_accuracy.py` | Confusion matrix in trading terms over last30/100/500/lifetime. **Abstention is not a vote** and **small samples are labelled, not hidden** (Wilson interval). |
| **57 — Confidence Calibration** | `calibration.py` | "Claims 90%, delivers 52%." Brier score + banded claimed-vs-actual. Suggests a **half-step**, only when the interval excludes the claim. |
| **58 — Threshold Optimisation** | `threshold_opt.py` | Sweeps the v0 guesses (`_MIN_EVIDENCE`, `_BEYOND_PCT`, …). Guards: ≥15 trades **each side**, ≥5-point uplift, and the **winners a filter would have cost** reported as prominently as the losers it avoids. |
| **59 — Engine Contribution** | `contribution.py` | **Shapley** values, not correlation — correlation rewards the redundant engine and punishes the pivotal one. Seeded, so a report never changes on refresh. |
| **60 — False Signal Analysis** | `false_signal.py` | Every loss investigated: one named primary cause, plus **the engine that called it right and was outvoted** — a direct pointer at a weight that is too low. Separates a bad signal from a bad exit. |
| **Dashboard 5** | `ui/learning_panel.py` | Rankings · calibration · threshold suggestions · contributions · false signals — every number beside its sample size. |

Storage is `sql/027_learning.sql`: five **append-only** tables. Nothing is ever
updated, so replay and backtesting show what was known *at the time*.

> ⛔ **Binding.** The Learning Engine may only **observe · measure · explain ·
> recommend · validate**. It never influences a live decision, never moves a
> threshold or an engine weight, and never hides a poor result. It is not
> registered in `ALL_ENGINES` and exposes no `apply`/`deploy`/`promote` —
> both facts are asserted by tests, not just documented.

## V6.5 — AI Explainability & Decision Intelligence (Stages 61–67) ✅ **BUILT**

No new trading logic and no new engines. This layer only explains, narrates,
justifies, summarises and reviews what the existing engines already decided.

| Stage | Module | Deliverable |
|---|---|---|
| **61 — Decision Explainability** | `explain_decision.py` | Why BUY · SELL · WAIT · EXIT · TRAIL · ABORT. **No generic explanations** — every ✓/✗ is constructed *from* an engine read and carries that engine's name and actual output. When an engine is silent no line is produced, so thin evidence renders as a short explanation rather than confident filler. |
| **62 — WAIT Analysis** | *(same module)* | What is missing, what you currently have instead, and a weighted **readiness %**. Same module as 61 because "why did you act" and "why didn't you" have the same answer shape; split, they would drift until MIOS could justify an entry with evidence it had just called insufficient. |
| **63 — Entry Checklist** | `checklist.py` | Nine weighted conditions, live. **Three states, not two:** ✅ met · ❌ not met · ⚪ the engine could not report. Unknowns are excluded from readiness rather than guessed — guessing either way is a lie in one direction. Weights mirror `validity.WEIGHTS` so the checklist and the gatekeeper cannot disagree. |
| **64 — Risk Analysis** | `risk_explain.py` | Why this entry · stop · target · trail · R:R, plus what invalidates the trade. Reasoning is labelled **proven vs derived**, and invalidation is never empty while a stop exists. |
| **65 — Trade Narrator** | `narrator.py` | Timestamped commentary, written **on transitions only** — a narrator that prints the current reading every cycle gets ignored within a day. **Observations are the narrator's; actions are quoted from Stage 52.** It never invents an instruction. |
| **66 — Post-Trade Review** | `trade_review.py` | Winners reviewed too: a +50 out of a +55 run and a +50 out of a +200 run are the same P&L row and completely different work. Best/weakest engine come from Stage 59's **Shapley credit**, not from being right — that separates *decisive* from *merely correct*. Losses reuse Stage 60. |
| **67 — Daily Summary** | `daily_summary.py` | End-of-day report. **What MIOS refused is half the report** — the WAIT log makes "the day was spent blocked on Acceptance" recoverable. Personality reads how the day was *spent*, not how it closed. Tomorrow is a **watch-list, never a forecast**. |

Dashboard integration: **D1** explanation + checklist + risk · **D2** live
narrator · **D3** full checklist drill-down · **D4** trade reviews · **D5**
daily summary above the Phase 6 forensics · **D6** condition reference. Trade
Card carries the ✓/✗ strip, the Need list and the readiness %.

> ⛔ **Binding.** The Explainability Layer may only **explain · narrate ·
> summarise · justify · educate · review**. It generates no signal, changes no
> confidence, moves no threshold or engine weight, and never influences the
> Decision Engine. No module is registered in `ALL_ENGINES` and none exposes a
> mutator — asserted by tests, not just documented.

## Stage 68 — Market Day Classification ✅ **BUILT**

> ⚠️ **Numbering.** The spec called this "Stage 61", but 61 is Decision
> Explainability (V6.5). Assigned **68** — the next free number. Same reason
> the numbering table at the top of this file exists.

`day_type.py` · `engines/stage68_day_type.py` · `ui/day_type_panel.py` ·
`sql/028_day_type_log.sql`

Eight evidence groups — price · levels · order flow · dealer · options ·
behaviour engines · institutions · depth — classify the **session**:

📈 Trend · 🔄 Swing · ↔ Range · 🔪 Choppy · ⚡ High Volatility ·
🧲 Expiry Pin · 💥 News Event · 💤 Low Participation

**Confidence is cross-group agreement, not signal count.** Twelve signals from
one group is one opinion repeated twelve times — the correlated-evidence
failure Stage 53 exists to fix. The winner's vote share is scaled by how many
*independent* groups made it their top pick, and by how many could report.

**Two types are facts, not votes.** `NEWS_EVENT` (Stage 28 fired) and
`EXPIRY_PIN` (expiry + a measurable charm pin) take precedence — the tape can
look like a trend all morning and the correct read is still "news day". The
underlying vote is preserved and shown.

**Style is separate from classification.** A trending tape stays a trend day
when flow shocks, but "ride winners on a wide trail" is dangerous advice at
that moment, so `style_caveat` overrides the guidance without touching the type.

**Not Stage 48.** Stage 48 owns "what is price doing right now" (minutes);
this owns "what kind of session is this" (hours) and drives *style*, not
direction. It **reads** Stage 48 rather than re-deriving it, and Stage 67's
own mini-classifier was removed in favour of quoting it.

> ⛔ `Bias.NONE` · listed in `evidence.EXCLUDED` · no mutators · every output
> carries `advisory_only`. It cannot vote, cannot change a confidence, and
> cannot override the Decision Engine — asserted by tests.

## Dashboard 2 — Trading Terminal ✅ **BUILT**

`terminal.py` · `ui/terminal_chart.py` · `ui/terminal_panel.py`

```
┌──────────────────────────┬──────────────────┐
│                          │    ATM CALL      │
│        NIFTY  (60%)      ├─ CALL vs PUT ────┤
│                          │    ATM PUT       │
└──────────────────────────┴──────────────────┘
        Option intelligence · TRADE BANNER
```

**One figure, not three.** Streamlit columns would give three independent
Plotly figures, and Plotly can only synchronise axes *within* a figure — three
figures means three independently-scrolling charts, which is exactly what a
terminal must not be. A single figure with a `rowspan` cell and `matches="x"`
on every axis gives the 60/40 proportions **and** real synchronised zoom, pan
and crosshair.

**The dashboard creates nothing.** Every value traces to an engine that already
computed it: Stage 50 for the LTP × OI badges, the leg-bias tally for strength
(a vote share, the same quantity Stage 53 reports), the VOB store for zones,
Stage 43 for exhaustion, Stage 52 for the trade. Two places say "not available"
rather than inventing:

* **option-premium entry/stop** — the Decision Engine works in NIFTY points and
  the conversion needs delta, which no engine produces. Premium appears only
  when the leg Entry Gate has armed a real setup.
* **per-leg strength without a leg-bias row** — reported as absent, not 50%.

Tint requires a ≥10-point strength gap; tinting on a 51/49 split would read as
a signal where there is none.

## Stage 69 — Market Session Intelligence ✅ **BUILT**

`session.py` · `engines/stage69_session.py` · `ui/session_panel.py` ·
`sql/029_session_log.sql`

A 09:20 breakout is not a 13:00 breakout. Eight windows —
Pre-Open · Opening Auction · Opening Drive · Morning Trend · Midday Balance ·
Afternoon Trend · Closing · Closed — each with nine measured characteristics
(strength · momentum · volatility · liquidity · trend quality · institutional ·
dealer · order flow · options), a session behaviour, and **contextual
modifiers** for Stages 42 · 44 · 48 · 50 · 51 · 52.

**Not Stage 6.** Stage 6 is a pure clock whose conviction weight
`confidence_tempered` has used since V5. Stage 69 measures what the session is
*doing*. Two engines naming the session differently would be a real defect, so
Stage 69 **owns the name** (finer windows) and **carries Stage 6's conviction
through** rather than recomputing it.

> ⛔ **`SESSION_AWARE = False`.** The modifiers are computed, published and
> logged every cycle — and applied by nobody. Changing what Stage 51 demands
> is a real intervention in what MIOS trades, and *"nothing influences a
> decision until it has proven itself"* outranks the feature. `modifier_for()`
> returns `{}` while the switch is off, so the gate cannot be bypassed by
> reading `applies_to`. The panel shows what it *would* have done, which is
> the evidence needed to promote it.

Two modifiers move in **opposite** directions by design: Stage 44's spike
sensitivity is ×0.6 in the Opening Drive (opening spikes are normal) and ×1.4
at Midday (a spike in a quiet tape is meaningful). Where a session and a
behaviour disagree on the decision stance, the **more conservative** one wins.

## Stage 70 — Session Intelligence Validation ✅ **BUILT**

`session_validation.py` · `ui/session_validation_panel.py` ·
`sql/030_session_validation.sql`

**No new engine.** Not registered in `ALL_ENGINES`, no mutators, cannot touch
the Decision Engine, a confidence or a threshold. It logs and validates.

| Part | Deliverable |
|---|---|
| **1 Performance logger** | Per-session signals · valid · win/loss rate · avg R:R · holding · MFE · MAE · confidence · market quality · market state. Bucket = **Stage 69 window × condition** (expiry / event / gap), so no tenth classifier is invented. |
| **2 Behaviour validation** | The **counterfactual** — Stage 69's modifiers have never been live, so every logged row's published stance is replayed against the graded history. |
| **3 Session profiles** | Best strategy · avoid · volatility · dealer · institutions · false-breakout rate, **labelled measured or a-priori**. |
| **4 Adaptive recommendations** | Evidence-driven, each with its sample size and Wilson interval; an explicit *"not enough evidence"* where that is the truth. |
| **5 Dashboard** | Inside D5 Learning. |
| **6 Recommendation scoring** | Every recommendation stored **with the win rate it was made on**, then compared to what the session did afterwards. |

Two limits stated on every result rather than buried:

* **In-sample.** The modifiers were written from reasoning, then evaluated
  against the sessions that followed. Suggestive, not conclusive.
* **Removal-only.** A modifier that would have *permitted* a declined entry
  leaves no outcome, so the measured improvement is a lower bound on harm
  avoided and says nothing about opportunity missed.

> ⛔ Promotion of Stage 69 to live behaviour requires statistically significant
> evidence **and** a human flipping `session.SESSION_AWARE`. An AST test fails
> the build if Stage 70 ever writes that constant.

## Wave 7 — Performance

Optimization only, no new logic: VPFR caching · news/sector caching · Telegram
latency · Supabase write batching · chart rendering · background scheduling.

---

## Completion criteria

Freeze V6 when: every engine validated independently · HTF context fully
integrated · false breakouts and liquidity traps handled · bias transitions
detected early · entries/exits/trailing automated by the Decision Engine ·
dashboard clean and decision-focused · every signal logged to Telegram +
Supabase + Excel · replay and live testing stable over hundreds of trades.

Then spend **at least a month** validating and refining thresholds before
considering V7. That will improve real-world performance more than any new
analytical module.
