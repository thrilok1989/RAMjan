# Stage 71.85 — Premium LTP Behaviour: audit before build

*Taken at `d830865`, before any behaviour code was written. One question per
required input: **who owns it, and is it reachable without recomputing it?***

---

## Verdict

**Every input exists. Nothing needs computing that 71.7 or 71.8 already owns.**

Three corrections to the specification's ownership table, all recorded below,
and one architectural consequence: **Stage 72 is frozen and this stage adds a
component to it.** That requires a version bump, not a quiet edit (§4).

---

## 1 · The requirement table

Status: **EXISTS** = published and reachable · **WIRING** = published, needs a
path · **COMPUTED** = this stage's own · **MISSING** = no producer.

### Consumed from Stage 71.8 — Premium Structure

| Input | Status | Owner | Path |
|---|---|---|---|
| Premium Structure | **EXISTS** | Premium Structure | `structure` |
| Premium Structure Score | **EXISTS** | Premium Structure | `structure.structure_score` |
| Premium S/R | **EXISTS** | Premium Structure | `structure.support` · `.resistance` |
| Premium S/R Strength | **EXISTS** | Stage 71.8 | `validation.sides[side].checks.premium_sr_strength` |
| Break Probability | **EXISTS** | Premium Structure | `structure.break_probability` |
| Fakeout Probability | **EXISTS** | Premium Structure | `structure.fakeout_probability` |
| HVN · LVN | **EXISTS** | Premium Structure | `structure.hvn` · `.lvn` |
| Premium LTP | **EXISTS** | Premium Structure | `structure.ltp` |

### Consumed from Stage 71.7 — Premium Energy

| Input | Status | Owner | Path |
|---|---|---|---|
| Premium Energy | **EXISTS** | Stage 71.7 | `energy.sides[side].energy` |
| Energy Shift | **EXISTS** | Stage 71.7 | `energy.shift[side].state` |
| Acceleration | **EXISTS** | Stage 71.7 | `energy.shift[side].acceleration` |
| Rotation | **EXISTS** | Stage 71.7 | `energy.rotation.label` |
| Dominance | **EXISTS** | Stage 71.7 | `energy.dominance` |
| Spike Probability | **EXISTS** | Stage 71.7 | `energy.sides[side].spike` |

### ⚠️ Three ownership corrections

The specification lists these under Stage 71.7. They are **Stage 71.8's**:

| Input | Spec says | Actually owned by | Path |
|---|---|---|---|
| **Premium CBV · CSV · CVD** | 71.7 | *both* — 71.7 has the per-side glyph read, **71.8 has the numeric totals** | `structure.cbv` · `.csv` · `.cvd` |
| **Premium RVOL** | 71.7 | **71.8** — `premium_structure` computes it; 71.7 has no RVOL at all | `structure.rvol` |
| **Premium Volume** | 71.7 | **71.8** | `structure.volume` |

This stage reads all three from **Stage 71.8**, the single owner. Reading CBV
from 71.7 *and* RVOL from 71.8 would mean two sources for one leg's flow, which
is the failure the whole stack is built to avoid.

### Consumed from the market stages

| Input | Status | Owner | Path |
|---|---|---|---|
| Building · Distribution · Squeeze · Unwinding | **EXISTS** | **Stage 50** | `energy.sides[side].behaviour.state` |
| Buyer / Seller Exhaustion | **EXISTS** | **Stage 50** | `energy.sides[side].behaviour.pressure` |
| Acceptance · Rejection · Reaction | **EXISTS** | **Stage 42** | `fr.reaction.state` |
| Premium's own acceptance | **EXISTS** | native leg S/R via 71.8 | `structure.acceptance_read.state` |
| Value Area | **EXISTS** | **Stage 45** *(index)* · **71.8** *(premium)* | `fr.htf` · `structure.profile.vah/val` |
| Dealer Wall · Gamma Flip · Charm Pin | **EXISTS** | **Stage 11** | `fr.dealer_levels` · `fr.charm_pin` |
| Stability | **EXISTS** | **Stage 44** | `fr.stability` |
| Absorption | **EXISTS** | native leg block / **Stage 43** via 71.8 | `structure.absorption` |

**Nothing is MISSING.**

---

## 2 · What this stage computes

Five things, and only five. Everything else is transport.

| Computed | Why it has no other owner |
|---|---|
| **Premium Behaviour** — one of six | Nothing else asks *what the LTP is doing at its own level*. 71.8 says where the levels are and how strong; 71.7 says whether the premium is being traded. Neither says which one price is fighting over right now |
| **Behaviour Strength** — five stars | the winning behaviour's share of the evidence that reported |
| **Behaviour Confidence** — `decision._grade` | **imported, not a second grading system** |
| **Behaviour Momentum** — one of five | the *rate* read, distinct from the behaviour itself |
| **Reason ranking** | ordering evidence this stage already gathered |

Break and fakeout probability are **read**, never recomputed — a test asserts
the module contains no `_break_` or `_fakeout_` producer.

---

## 3 · Why the value-area read is the premium's, not the index's

The specification lists Stage 45 Value Area. Stage 45's VAH/VAL are **NIFTY**
levels. A premium accepted above its own VAH is a different fact from NIFTY
accepted above its VAH, and only the first one describes the option a trader
holds.

So the **premium** value area (`structure.profile`) drives the `Acceptance`
behaviour, and Stage 45's index alignment is carried as *context* on the
reason, never as the trigger. Both are named in `CONSUMED`.

---

## 4 · ⚠️ Stage 72 is frozen, and this changes it

`STAGE72_FROZEN.md` says, in as many words:

> ⛔ Do not change entry scoring, weights, gates, recommendation logic … Bug
> fixes only.

Adding a Premium Behaviour component to Stage 72's `WEIGHTS` is a scoring
change. It is the correct change and it is what this specification asks for —
but it cannot be a quiet edit inside a frozen stage.

### Decision

* Stage 72's `VERSION` moves **`72.0` → `72.1`**.
* The dispatcher's `SUPPORTED_DECISION_VERSIONS` accepts **both**, so a stored
  `72.0` decision still replays and still dispatches.
* `STAGE72_FROZEN.md` records the amendment with its reason, rather than being
  silently contradicted.

A freeze that can be edited without a version bump is not a freeze; a freeze
that can never change is a museum. The bump is the difference.

---

## 5 · Position in the pipeline

```
71.7 Premium Energy  →  71.8 Premium Structure  →  71.85 Premium Behaviour
                                                          ↓
                            72 Entry  ←  71.95 TradingContext
```

71.85 runs **before** the context, and its output is transported *through* it —
so Stage 72 still reads one object, and the rule that it never reaches past the
bridge holds unchanged.

---

## 6 · Rules this audit forces

1. **CBV · CSV · CVD · RVOL · Volume come from Stage 71.8**, not 71.7 (§1).
2. **Break and fakeout probability are read**, never recomputed.
3. **The premium's own value area** drives Acceptance; Stage 45's is context.
4. **Stage 72 bumps to `72.1`** and the dispatcher accepts both (§4).
5. **Exactly one behaviour**, chosen by a single evidence ledger — never a
   blend, never a subtraction of one side from the other.
6. **This stage analyses ONE premium.** It receives a side and never compares.

---

## 7 · Built — what the audit produced

| Deliverable | Where |
|---|---|
| The stage | `mios_v5/premium_behaviour.py` |
| Output contract | `docs/STAGE71_85_OUTPUT_CONTRACT.md` |
| Context transport | `trading_context.py` — 10 fields, new `behaviour` root, `71.95.2` |
| Stage 72 component | `entry_engine.py` — `premium.behaviour` weight `1.5`, `VERSION` `72.1` |
| Frozen-stage amendment | `docs/STAGE72_FROZEN.md` § Amendment 1 |
| Dispatch | `dispatcher.py` — `SUPPORTED_DECISION_VERSIONS = ("72.0", "72.1")`, payload carried |
| Panel (Principle 12) | `mios_v5/ui/premium_behaviour_panel.py` |
| App wiring | `mios_v5/ui/dashboard_v6.py` — runs between 71.8 and the context |
| Tests | `mios_v5/tests/test_premium_behaviour.py` — 118 tests, the 10 required properties |

Everything §1 marked **EXISTS** was read rather than recomputed, and every
correction in §1 and §3 is enforced by a test rather than by this document.
