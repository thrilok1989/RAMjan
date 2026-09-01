# MIOS V6 — Stage 72 · Entry Engine — Working Prompt (revision 2)

> **Read this first.** The original version of this prompt was written when
> Stage 72 did not exist and Stage 71.95 was the newest thing in the tree. That
> is no longer the situation. **Stage 72 is built, frozen, amended once, wired
> into the app and covered by tests.** This revision keeps the original intent
> — the ownership rules, the phases, the refusals — and corrects every place
> where the original described a future that has already happened.
>
> Use this as the brief for *changing* Stage 72, not for writing it.

---

## 0. What is actually on disk right now

| Thing | State | Where |
|---|---|---|
| Stage 71.85 — Premium LTP Behaviour | built, `71.85.0` | `mios_v5/premium_behaviour.py` |
| Stage 71.95 — TradingContext | built, `71.95.2`, 6 roots | `mios_v5/trading_context.py` |
| **Stage 72 — Entry Engine** | **built, `72.1`, frozen + Amendment 1** | `mios_v5/entry_engine.py` |
| Stage 72.9 — Dispatcher | built, `72.9`, `VALIDATED_SIMULATED` | `mios_v5/dispatcher.py` |
| Stage 73 — Trade Lifecycle | built, `73.0` | `mios_v5/trade_lifecycle.py` |
| Stage 74 — Liquidity Intelligence | built, `74.1.0`, **calibrating** | `mios_v5/liquidity.py` |
| Execution panel (72 · 73 · 72.9) | built | `mios_v5/ui/execution_panel.py` |
| Chain wiring | built | `dashboard_v6._run_execution_chain` |

Deliverables the original prompt asked for **already exist**:
`mios_v5/entry_engine.py`, `docs/AUDIT_STAGE_72_ENTRY_ENGINE.md`,
`docs/STAGE72_OUTPUT_CONTRACT.md`, plus `docs/STAGE72_FROZEN.md` which the
original did not anticipate.

Do not regenerate any of them. **Audit first; build only what the audit
justifies.**

---

## 1. Purpose (unchanged)

Stage 72 answers one question and stops:

> **Is there an executable trade right now?**

Not *which direction* — Stage 71. Not *which strike* — Stage 71.8. Not *which
premium has energy* — Stage 71.7. Not *what the premium is doing at its level* —
Stage 71.85. Those exist; this stage reads their verdicts.

---

## 2. Input — still exactly one object

```python
from mios_v5.entry_engine import run
decision = run(ctx)          # ctx: TradingContext (71.95)
```

`entry_engine` imports **two** local modules — `trading_context` and
`decision_v2` — and a test asserts that set exactly. No engine import, no
network client, no `session_state`, no database client.

`ADVISORY_ONLY = True`.

---

## 3. The chain is no longer hypothetical

The original prompt drew:

```
Market → TradingContext → Stage 72 → Trade Manager → Telegram
```

The Trade Manager was built as **Stage 73**, and a separate **Stage 72.9**
owns dispatch. The real chain, as wired in `dashboard_v6._run_execution_chain`:

```
TradingContext(71.95) → Stage 72 → Stage 73 → Stage 72.9 → (transport=None)
                                                            ↑ nothing is sent
```

* Stage 73 **references** `decision.id`; it never mints its own decision id.
* Stage 72.9 runs with `transport=None`, reports `telegram_state="NOT_SENT"`,
  and `docs/STAGE72_9_VALIDATION_REPORT.md` records `freeze_ready: False`.
* `SUPPORTED_DECISION_VERSIONS = ("72.0", "72.1")` — the dispatcher accepts
  both shapes, so a stored `72.0` decision still replays.

**Any change to Stage 72's output shape must be checked against all three
consumers**, not just against Stage 72's own tests.

---

## 4. States — the real machine, not the spec's

The original prompt listed ten states:
`WAIT, WATCH, ENTRY_READY, ENTER, SCALE_IN, HOLD, TRAIL, PARTIAL_EXIT,
FULL_EXIT, ABORT`.

Three of those do not exist. `decision_v2.STATES` is imported, never restated:

```
WAIT · ENTRY_READY · FLOOR_CONFIRMED · CEILING_CONFIRMED · ENTER · HOLD
SCALE_IN · SCALE_OUT · TRAIL · EXIT · COMPLETE · ABORT
```

`SPEC_ALIAS` records the mapping so a reader looking for a spec name finds the
real one instead of nothing:

| Spec name | Actual |
|---|---|
| `WATCH` | `WAIT` |
| `PARTIAL_EXIT` | `SCALE_OUT` |
| `FULL_EXIT` | `EXIT` |

**Stage 72 emits only four:** `WAIT · ENTRY_READY · ENTER · ABORT`. The other
eight describe a position already open, and Stage 72 has no position input.
`_checked()` raises if anything outside `STATES` is emitted.

If a future revision wants a new state, it goes in `decision_v2` — adding one
locally would be Stage 72 inventing vocabulary.

---

## 5. Phase 2 — the score is **eleven** weights, not ten

```python
WEIGHTS = {
    "strike.validation":            2.5,
    "energy.energy":                2.0,
    "opportunity.opportunity_score":2.0,
    "premium.premium_score":        1.5,
    "premium.behaviour":            1.5,   # ← Stage 71.85, added at 72.1
    "opportunity.confidence":       1.5,
    "strike.liquidity":             1.5,
    "energy.spike_probability":     1.0,
    "risk.validity":                1.0,
    "htf.alignment":                1.0,
    "market.stability":             1.0,
}
```

Every weight reads a **different** context field — a test asserts it.

`_SCALES["premium.behaviour"]`:

| Behaviour | Score |
|---|---|
| Support Building | 100 |
| Resistance Fading | 90 |
| Acceptance | 70 |
| Resistance Building | 30 |
| Support Fading | 10 |
| `Neutral` | **`None`** |
| `UNKNOWN` | **`None`** |

`None` means *leaves the denominator*. Stage 71.85 emits `Neutral` when the
evidence did not agree enough to name a fight — an **absence of a read**, not a
weak read. Scoring it 50 would let "we could not tell" hold the score up.

### The rules that survive any revision

* **Unknown-excluded scoring.** Unknown inputs leave the denominator. `score`
  travels with `reporting` and `of`.
* **Fewer than 4 of 11 reporting → `WAIT`**, with the count in the reason.
* **Gates are checked before the score and cannot be outvoted**: entries frozen,
  tape shocked, strike invalid, strike illiquid, Stage 51 rejection.
* Thresholds: `score ≥ 75` in an Early/Optimal window → `ENTER`;
  `score ≥ 60` → `ENTRY_READY`; otherwise `WAIT`.

---

## 6. Phase 7 — what has no producer, named

```python
MISSING_PRODUCERS = ("target2", "target3")
```

Stage 35 publishes **one** `next_target`. A ladder is new computation and
outside this stage's remit; deriving T2/T3 from R-multiples would be fabricating
levels. They are `UNKNOWN` **by name**, recorded in `metadata["missing_producers"]`
so the gap is visible rather than inferred.

Entry and stop are **premium levels** from Premium Structure — the leg's own
zones. There is no delta-based NIFTY→premium conversion anywhere in MIOS, and
inventing one would be a new market computation.

`risk_reward` is `UNKNOWN` unless entry, stop **and** target1 are all known and
both legs are positive.

---

## 7. Phase 8 — the Telegram payload, now 7 keys longer

Still a **prepared payload**, still `sent: False`, still no network client
importable. Amendment 1 appended, all copied from `decision["behaviour"]`:

```
behaviour · behaviour_strength · momentum · break_probability
fakeout_probability · premium_acceptance · top_behaviour_reason
```

`ready` means *the payload is well formed*, not *this should go out*.
Identity (`id`, `version`, `created_at`, `hash`) comes first so a message can
always be joined back to its decision.

---

## 8. The `behaviour` field — read, never interpreted

`EntryDecision.behaviour` is a mapping of **ten** Stage 71.85 reads plus an
`owner` string. Every entry is a `self._v(...)` context read. Stage 72 does not
re-rank, re-interpret or re-score them — the weighted mean already consumed
`premium.behaviour` like any other component. The block exists so Stage 72.9 can
put the same values in a message without reaching past the bridge.

```python
behaviour: Mapping[str, Any] = _dc_field(
    default_factory=lambda: MappingProxyType({}))
```

`MappingProxyType({})` as a bare dataclass default raises
`ValueError: mutable default`. Use `default_factory`.

---

## 9. Identity and immutability (unchanged, and load-bearing)

```python
HASH_FIELDS = ("id", "version", "state", "confidence", "score", "created_at")
```

Identity plus verdict — deliberately not the whole object, so a reworded reason
does not make `verify()` cry wolf. Values are stringified, so `83` and `"83"`
hash the same.

`decision.verify()` · `decision.identity()`. Stage 73 and 72.9 carry the
identity forward; they never mint their own.

Immutability is **deep**: `@dataclass(frozen=True)`, `MappingProxyType`,
tuples, recursively. `targets`, `telegram`, `metadata` and
`metadata["components"]` all reject writes. A decision represents history; a
consumer that could edit one could rewrite what was decided.

---

## 10. "No UI changes yet" is void

The original prompt said Stage 72 required no UI. **Principle 12 now binds:**

> Nothing may influence a trading decision unless the trader can inspect that
> exact value somewhere in the UI.

`mios_v5/ui/execution_panel.py` renders Stages 72 · 73 · 72.9 on one card —
score, quality, side, strike, zone, entry, stop, R:R, readiness, plus `id ·
version · hash-prefix` on each row so a reader can confirm the three rows
describe **one** decision. It computes nothing (a test asserts it imports no
`numpy`/`pandas`/`streamlit`/engine module) and it states *"Nothing is sent"*
on **every** render, in the card rather than a footnote.

**A new scored field is not finished until the panel shows it.**

---

## 11. Amending a frozen stage — the procedure

`docs/STAGE72_FROZEN.md` says: *do not change entry scoring, weights, gates or
recommendation logic — bug fixes only.* Stage 71.85 needed an eleventh weight.
Both cannot be true, so the version moved:

1. `VERSION` bumps (`72.0` → `72.1`).
2. The previous version **stays supported** downstream
   (`SUPPORTED_DECISION_VERSIONS`).
3. `STAGE72_FROZEN.md` gains an **Amendment** section recording what changed and
   what did not.
4. New payload keys are **additive**, so an old payload lacks them rather than
   carrying them wrong.

> A freeze that can be edited without a version bump is not a freeze; a freeze
> that can never change is a museum. The bump is the difference.

**An un-versioned edit to Stage 72 is still forbidden.** The next amendment
follows exactly this procedure and becomes *Amendment 2*.

⚠️ **Known doc drift to fix in the next amendment:** the *Scoring*, *Decision
Contract* and *Versioning* sections of `STAGE72_FROZEN.md` still read "Ten
weights" and `VERSION = "72.0"` in their bodies; only Amendment 1 records the
change. The body should be reconciled with the amendment.

---

## 12. Stage 74 — a candidate input, **not** an input

Stage 74 (Liquidity Intelligence, `74.1.0`) publishes clustered S/R levels with
confidence, POC migration, money-flow divergence and net sentiment. It is an
obvious twelfth weight. It is **not wired into Stage 72, and must not be.**

* Stage 74 is **not in `TradingContext.ROOTS`** (`fr · matrix · premium ·
  validation · structure · behaviour`). It has its own bridge,
  `liquidity_context.py` (`74.0.0`), feeding its own panel only.
* Its confidence curve, cluster tolerance and POC regime bands were set from
  *reasoning*, because there was nothing to measure.
* `sql/036_liquidity_telemetry.sql` + `mios_v5/liquidity_telemetry.py` collect
  the evidence: one sample per minute, ~375 rows/day, `MIN_CLUSTERS = 200`
  before any verdict.
* Injection order, when it happens, is **S/R Engine (Stage 42) first** — not
  Stage 72.

> **Standing instruction from the owner, still in force:**
> *"I would not touch the calibration anymore until the live week completes."*

So: **do not add a `liquidity.*` weight, do not add a `liq` root to
TradingContext, do not tune a Stage 74 constant.** A drift report was asked for
*"later (not now)"* — later still means later.

---

## 13. Non-negotiables (verbatim from the original brief)

* Consume `TradingContext` only. No direct stage imports.
* No duplicated calculations. No duplicated ownership.
* **UNKNOWN never becomes zero.**
* Advisory only. No Telegram **sending**. No BUY/SELL alerts.
* Immutable outputs.
* This stage **does not send Telegram** — it only prepares the payload.
  No side effects.
* Prefer `UNKNOWN` over an assumption.

---

## 14. If you are asked to change Stage 72, do this

1. **Audit first.** Search for an existing owner of the fact before writing one.
   Five POC implementations already existed when Stage 74 was specified; the
   correct build count was zero.
2. **Check for a reader without a writer**, and for a writer without a reader.
   This repo has been bitten by both (`cfb6c93`, `_atm_leg_ltf_delta`, and three
   frozen stages that sat with **no caller at all** until `5a73d71`). A test that
   a stage *works* says nothing about whether it *runs*.
3. **Write guard tests against the AST, not the source text.** Greps trip on the
   prose explaining the rule. This has cost time five separate times, in Python
   and again in SQL (`_code()` strips comments before matching).
4. **Bump the version and amend the freeze doc** (§11) — never edit silently.
5. **Show it in the UI** (§10) before calling it done.
6. Update `docs/STAGE72_OUTPUT_CONTRACT.md` and
   `docs/AUDIT_STAGE_72_ENTRY_ENGINE.md` in the same change.
7. Run the full suite. It is currently **green at 2,097 tests**; a change that
   reduces that number needs an explanation, not a skip.

---

## 15. Open gates — both need a human, not code

1. **Apply `sql/036_liquidity_telemetry.sql`** to start Stage 74's calibration
   week. Nothing in this environment has Supabase credentials; the collector
   reports its status loudly rather than failing silently.
2. **Stage 72.9 stays unwired** (`transport=None`) until its live validation
   moves `freeze_ready` to `True`.

Neither is a Stage 72 change. Both bound what Stage 72 may become next.
