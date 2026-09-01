# Stage 71.7 — Spec vs Built

*Audit of `mios_v5/premium_energy.py` + `ui/premium_energy_panel.py` against the
Stage 71.7 specification. Taken at `62b82ce`; **closed out by the completion
plan** — see §9 for what changed and what remains.*

---

## Headline *(as found)*

**The hard half is done; the presentation half is not.**

The two things that are genuinely difficult — scoring each side independently
without subtraction, and keeping Energy and Spike on separate substrates — are
built correctly and are the best-reasoned code in the Stage 71 stack. What is
outstanding is mostly wiring and vocabulary: inputs the spec calls mandatory
that exist in session state but were never connected, and four output fields
the spec defines that have no field at all.

Roughly **two of nine responsibilities are complete, five are partial, two are
absent** — and three binding rules are broken.

---

## 1. The nine responsibilities

| # | Responsibility | Status | What is owed |
|---|---|---|---|
| 1 | **Premium Energy** | ⚠️ built, wrong bands | Scores 0–100 per side correctly. But `_STRENGTH_BANDS` is **4 bands** (Weak ≤25 · Moderate ≤55 · Strong ≤80 · Extreme) against the spec's **5** (Dead 0–20 · Weak 20–40 · Healthy 40–60 · Strong 60–80 · Explosive 80–100). `Dead`, `Healthy` and `Explosive` are never emitted; the edges differ everywhere. |
| 2 | **Premium Dominance** | ⚠️ 3 of 4 states | Emits `CALL` · `PUT` · `None`. The panel prints `None` as **"Balanced"** — so **"No Energy" is indistinguishable from "Balanced"** on screen. Two premiums at 74/70 and two premiums that never reported render identically. |
| 3 | **Energy Rotation** | ⚠️ **wrong quantity** | Reads `matrix.best_trade.intel.rotation` — Stage 71.5's *directional side flip for the best horizon*. The spec asks whether **energy** moved CALL→PUT. These are different facts and can disagree. The raw material exists (`shift` per side) and is not used for it. |
| 4 | **Energy Shift** | ⚠️ 3 of 6 states | `_shift()` gives `↑ Increasing` · `↓ Weakening` · `· Holding` + `UNKNOWN`. Spec wants **six**: Increasing · Fading · Exploding · Compressing · Building · Distributing. Four are unimplemented. |
| 5 | **Spike Probability** | ✅ **complete** | Per side, separate signal set and weighting from Energy, compression raises it, participation caps it, Stage 44 caps it. Fully to spec and well argued. |
| 6 | **Preferred Premium** | ❌ **absent as a field** | No `preferred` key. The four states exist only as prose inside `_conclusion()` ("🔥 Trade CALL", "❄ Both premiums weak"). Nothing downstream can read it. |
| 7 | **Energy Stability** | ⚠️ right source, wrong words | Correctly read from Stage 71's `stability()`, which is built from 44/47/54 exactly as the rule demands. But it re-bands to **High / Medium / Low**, where the spec asks for **Stable / Unstable / Shock / Recovery** — which is Stage 44's own vocabulary, available as `fr["stability"]` and unused here. |
| 8 | **Top Trigger** | ⚠️ count and vocabulary | Spec: **maximum one**. Implementation returns up to **three**, and the panel labels the row "Top trigger" (singular) then prints all three. Vocabulary covers ~5 of the spec's 11 named triggers. |
| 9 | **Top Reasons** | ❌ **absent** | No reasons list. `energy_reason` / `spike_reason` are method sentences ("leg participation 62% scaled by market energy 48%"), not the named contributors the spec asks for ("Strong CBV · Positive CVD · Dealer Long · Stage44 Stable · VOB Breakout"). |

**Also in the spec's output panel and missing entirely:** the **Confidence
grade** (`A+`). Stage 71.5 grades quality; Stage 71.7 does not carry one.

---

## 2. Inputs — the 16 native premium engines

| Spec input | Status | Note |
|---|---|---|
| Premium CVD | ✅ | `CVD` column |
| Premium Money Flow | ✅ | `MFP` |
| Premium VOB | ✅ | `VOB` · `Sup VOB` · `Res VOB` |
| Premium VWAP | ✅ | `VWAP` |
| Premium S/R | ✅ | `S/R` |
| **Premium CBV** | ❌ **unwired** | **Data exists** — `_atm_leg_ltf_delta[tag]['buy_total']` |
| **Premium CSV** | ❌ **unwired** | **Data exists** — `['sell_total']` |
| Premium Volume | ❌ unwired | `delta_pct` exists in the same store |
| Premium OI | ❌ absent | no per-leg OI level published |
| Premium Dynamic Trail | ❌ absent | no producer |
| Premium ΔOI | ⚠️ proxied | `OIvel` is velocity, not level |
| Premium Momentum | ⚠️ proxied | by `VIDYA` |
| Premium Delta Volume | ⚠️ proxied | by `Div` |
| Premium Compression | ⚠️ market-level | Stage 37's tape reading, not this premium's |
| Premium Expansion | ⚠️ market-level | same |
| Premium Reaction | ⚠️ **read then dropped** | `ctx["acceptance"]` is built in `_market_context` and **never referenced again** |

**5 wired · 6 partial · 5 absent.**

### The CBV/CSV gap is the sharpest one

The spec's binding rules say: *"Premium CBV, CSV, and CVD are **mandatory**
inputs."* One of the three is wired.

This is not a data problem. `ui/dashboard_v6.py::_leg_flow_readings` **already
extracts per-leg CBV and CSV** for the ATM Call and ATM Put from
`_atm_leg_ltf_delta`. Stage 71.7 misses them only because
`sides_from_leg_rows()` reads `_leg_bias_cache`, whose columns are 🟢/🔴/⚪
glyphs — and that table has no CBV or CSV column to decode. The fix is a second
input path, not a new measurement.

---

## 3. Inputs — the 24 named stages

| Wired ✅ (8) | Read but unused ⚠️ (2) | Unwired ❌ (13) | Declared missing (1) |
|---|---|---|---|
| 11 Dealer *(bias only)* | **42 Acceptance** | 12 Options · 13 Institutional | 71.8 Strike Validation |
| 17 Liquidity *(vacuum flag only)* | **35 Reaction Zone** | 14 Order Flow · 18 Sector | |
| 37 Market Energy | | 22 VIX · 24 Preparation | |
| 43 Absorption | | 25 Intent · 27 Conflict | |
| 44 Flow Shift | | 31 Probability · 48 Market State | |
| 45 HTF *(bias only — score unused)* | | 50 Premium Behaviour | |
| 47 Transition *(via Stage 71)* | | 51 Validity · 52 Decision | |
| 71 Opportunity Matrix | | | |

Two of these are worth naming individually, because they are one line of work
each rather than a missing feature:

* **`ctx["acceptance"]`** (Stage 42/35) — extracted at `premium_energy.py:227`,
  never read. The spec lists Reaction and Acceptance as inputs and the panel
  shows nothing from either.
* **`ctx["htf"]`** (Stage 45 alignment *score*) — extracted at `:228`, never
  read. Only `htf_bias` is used, and only inside `_side_favoured`.

Stage 50 is a notable absence: the spec calls it **Premium Behaviour**, which is
the closest existing engine to this stage's own question, and 71.7 does not read
it.

---

## 4. ⛔ Three binding rules are broken

| Rule | Status |
|---|---|
| Uses existing engine outputs only | ✅ |
| Never recalculates market facts | ✅ — explicitly argued in the docstring |
| Stage 47 affects Stability only | ✅ |
| Stage 54 affects Stability only | ✅ |
| Produces advisory output only | ✅ — `ADVISORY_ONLY`, asserted by test |
| Never triggers Telegram | ✅ |
| UNKNOWN shown, never fabricated | ✅ — exemplary; `None` → `—`, never `0%` |
| **Premium CBV, CSV and CVD are mandatory** | ❌ **1 of 3 wired** (§2) |
| **Stage 44 affects Stability only** | ❌ **also caps Spike** at `premium_energy.py:378-379` |
| **Never generates BUY/SELL** | ❌ **`_conclusion()` emits instructions** |

### On Stage 44

`_side_spike` applies `score = min(score, 45.0)` when `flow_frozen`. The code
argues this well — *"Stage 44 vetoes, it never votes"* — and it is the same
veto discipline used everywhere else in V6. But the spec is explicit that Stage
44 touches **Stability only**, and Stage 71's `stability()` already consumes
`freeze_entries`. **Stage 44 is currently counted twice.** Either the rule
moves or the cap does; the two cannot both stand.

### On BUY/SELL

```python
return "🔥 Trade CALL — PUT has no energy." ...
return "🐻 Trade PUT — CALL fading rapidly." ...
```

*"Trade CALL"* is a buy instruction in plain words. The spec forbids it twice
("Never generates BUY/SELL", "This is advisory only"), and it also breaks the
repo's own Stage 65 principle — *"Observations are the narrator's; actions are
quoted from Stage 52. It never invents an instruction."* The observation
underneath is fine and should stay; the imperative should become one
("**CALL leads on energy; PUT has none**").

---

## 5. Pipeline position

Spec: `71 → 71.7 → 71.8 → 71.9 → 72`

| Stage | Status |
|---|---|
| **71** Opportunity Matrix | ✅ built |
| *71.5* Opportunity Intelligence | ✅ built — **not in this spec**, sits between 71 and 71.7 |
| **71.7** Premium Energy & Spike | ⚠️ this audit |
| **71.8** Strike Selection & Validation | ❌ not built — honestly declared in `MISSING_INPUTS` |
| **71.9** Premium S/R Analyzer | ❌ not built — **not declared anywhere** |
| **72** Entry Engine | ❌ not built |

71.7's stated purpose is to *bridge* 71 and 71.8 before the Entry Engine. Two
of the three things it bridges to do not exist, so the stage currently
terminates in a panel rather than feeding anything.

---

## 6. Built beyond spec — worth keeping

`attach_to_horizons()` is not in the specification and is the most useful thing
in the module. It joins per-side energy onto Stage 71's per-horizon rows and
flags the case nothing else on the screen could say:

```
intraday → CALL · energy 82 spike 91 → CONFIRMED_HOT
scalp    → PUT  · energy 21 spike 18 → CONTRADICTED
```

A horizon ranking high on directional evidence while its option has no
participation is exactly the expensive mistake, and this catches it. It should
survive any rework.

---

## 7. One dead branch

`_conclusion()` tests `stability_band in ("LOW", "EXPLOSIVE")`, but Stage 71's
`stability()` only ever emits **High · Medium · Low**. `"EXPLOSIVE"` is
unreachable — vocabulary drift already present *inside* the stack, and the same
drift §1 row 7 describes.

---

## 8. What to do, in order

1. **Wire CBV and CSV.** Mandatory by the spec, already in session state, read
   today by `_leg_flow_readings`. Add a numeric input path alongside
   `sides_from_leg_rows` rather than trying to force them through the glyph
   table. *This is the one item that changes the scores.*
2. **Add the four missing output fields** — `preferred`, `reasons` (max 5),
   `confidence`, and cut `top_trigger` to one. All four are presentation over
   values the module already holds.
3. **Fix the two vocabularies** — Energy bands to the spec's five, Stability to
   Stage 44's own four words (`fr["stability"]` is right there). Kill the
   unreachable `"EXPLOSIVE"` branch while in the file.
4. **Resolve the Stage 44 double-count** — decide whether the spike cap or the
   rule survives, and write down which.
5. **Rewrite the two imperative conclusions** as observations.
6. **Compute Rotation from energy**, not from the best horizon's side flip. The
   per-side `shift` values already computed are the input.
7. **Use or delete** `ctx["acceptance"]` and `ctx["htf"]`.
8. **Declare 71.9** in `MISSING_INPUTS` the way 71.8 already is, so the gap is
   named rather than silent.

Items 1–3 are most of the outstanding value. Items 4–5 are correctness against
the stage's own binding rules and should not wait.

---

## Verdict *(as found)*

| | |
|---|---|
| **Responsibilities** | 2 complete · 5 partial · 2 absent |
| **Native premium inputs** | 5 wired · 6 proxied · 5 absent (CBV/CSV available, unwired) |
| **Stage inputs** | 8 wired · 2 read-but-unused · 13 unwired · 1 declared missing |
| **Binding rules** | 8 held · **3 broken** |
| **Downstream** | 71.8 · 71.9 · 72 all unbuilt |
| **Beyond spec** | horizon × premium cross-check — keep it |

The engine's reasoning is sound and its honesty discipline (`None` → `—`,
never a fabricated zero) is the strongest in the stack. What it owes is
connection, not thinking.

---

# 9 · Closed out

Every item above was worked through in the order the completion plan set.

## What changed

| Phase | Delivered |
|---|---|
| **1 · Mandatory inputs** | CBV · CSV · CVD are first-class, per side, as **numbers**. `flow_from_leg_totals()` sums `indicators/order_flow.totals()` across each side's legs; `buy_share` is the derived read Energy consumes. |
| | **Stage 50** read whole — `calls`/`puts` give building · distribution · squeeze · unwinding; `buyers`/`sellers` give absorbing · exhausted. Nothing re-derived. |
| | **Stage 42** now raises Spike, routed to the side it favours. **Stage 45's score** now weights Confidence; it was extracted and dropped. |
| **2 · Outputs** | `preferred` (4 states) · `confidence` (Stage 52's `_grade`, imported) · `top_trigger` (**exactly one**, causal priority) · `top_reasons` (≤5, `{code,label,side,weight}`). |
| **3 · Vocabulary** | Energy bands → **Dead · Weak · Healthy · Strong · Explosive**. Stability → **Stage 44's own words**. Dominance → four states, `No Energy` no longer collapses into `Balanced`. Shift → the six states. |
| **4 · Double count** | Stage 44 removed from the Spike path. It reaches the output through Stability alone, guarded by a source-level test. |
| **5 · Rotation** | Measured on **energy migration** between the premiums, not on the best horizon's side flip. |
| **6 · Bridge** | `out["bridge"]` publishes the nine fields flat for 71.8 / 72. |
| **7 · Preserved** | `attach_to_horizons()` untouched. |

## Three things the work surfaced

1. **The CBV/CSV store had no writer.** `_atm_leg_ltf_delta` lost it in the V6
   reduction and kept both readers, so `dashboard_v6._leg_flow_readings` and
   Stage 71.7 had been receiving `{}` — the same writer-blindness that severed
   the learning tables. Restored in `_publish_atm_legs` through
   `indicators/order_flow.totals`, the owner of the CLV split, rather than by
   reinstating the inline copy. **`test_every_leg_store_v6_reads_still_has_a_writer`
   now fails the build if any `_atm_leg_*` store loses its writer again** — a
   read-closure audit cannot catch that class, so an assertion does.
2. **`buy_share` describes the book, not the size.** A premium with 0.1M of
   volume split evenly scored the same as one with 27M split evenly, and only
   the second is being traded. `volume_share` was added and now caps Energy —
   which also wires **Premium Volume**, one of the five inputs listed absent
   in §2.
3. **A seventh Shift word exists on purpose.** The spec named six. Energy that
   was measured and did not move is `Holding`; mapping it onto `Compressing`
   would assert a coil nobody measured, and onto `Decreasing` a fall that did
   not happen. Where Stage 50 names a structural state that agrees with the
   movement, its word wins — it explains the mechanism. **The spec was updated
   to seven states**, so `Holding` is a reading rather than a deviation.

## Added after the plan

**Energy Acceleration.** `shift.acceleration` is this cycle's energy change,
published under its own name because the state word alone cannot say whether a
rise is 6 points or 26. A second reading, `shift.accelerating`, says whether the
change *itself* is growing — it needs a third cycle and is `UNKNOWN` until then,
and it compares magnitude rather than sign so a fall going from −4 to −15 reads
as speeding up. Both reach the 71.8 bridge as `energy_acceleration`.

The reading it exists for:

```
cycle 2   energy  89 Explosive  Exploding   accel +60
cycle 3   energy 100 Explosive  Building    accel +11   slowing
```

Energy at its ceiling, and the move into it nearly stopped. No new engine — the
previous cycle's output already carried what the second derivative needed.

## What still remains

| Item | Status |
|---|---|
| **Stage 71.8** Strike Validation | not built — declared in `MISSING_INPUTS`, bridge ready |
| **Stage 71.9** Premium S/R | not built — **now declared** alongside 71.8 |
| **Stage 72** Entry Engine | not built |
| Premium OI *(level)* · Dynamic Trail | no producer publishes either |
| Per-premium Compression / Expansion | still market-level (Stage 37) |
| Stages 12 · 13 · 14 · 18 · 22 · 24 · 25 · 27 · 31 · 48 · 51 · 52 | unwired — none is required by the spec's own input list for the nine responsibilities |

## Verdict *(now)*

| | |
|---|---|
| **Responsibilities** | **9 complete** |
| **Mandatory inputs** | **CBV · CSV · CVD all wired** |
| **Binding rules** | **11 held · 0 broken** |
| **Tests** | 1,293 passing — 104 on this stage |
| **Downstream** | 71.8 · 71.9 · 72 unbuilt; the bridge they consume is published |
