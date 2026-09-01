# Stage 73 — Trade Lifecycle: what the two inputs supply

*Audit taken at `77bf0b4`, before any lifecycle code was written. One question
per phase: **can Stage 73 answer this from `EntryDecision` + `TradingContext`
alone?***

---

## Verdict

**Seven of eight phases are answerable. One is not, and it is Phase 1.**

Stage 73 has **no position input**. `EntryDecision` records what was *decided*,
not what was *filled*, and nothing in `TradingContext` describes an open trade.
So "is there an active trade?" cannot be answered — only *"was an entry
decided, and does the tape still support it?"*

That is not a defect to code around. The spec already anticipates it —
*"UNKNOWN is allowed. Never assume."* — and this audit makes the boundary
explicit so the next stage does not quietly assume a fill happened.

One field is added to `TradingContext` (§3). Everything else is present.

---

## 1. Phase-by-phase

| Phase | Needs | Available? |
|---|---|---|
| **1 · Position awareness** | is a trade open | ⚠️ **NOT ANSWERABLE** — see §2 |
| **2 · Position health** | premium behaviour · energy · structure · liquidity · stability · risk · reward · timing · maturity | ✅ all present |
| **3 · Lifecycle action** | health + stability + energy + structure | ✅ |
| **4 · Trailing** | an existing stop, never invented | ✅ `EntryDecision.stop` |
| **5 · Scale** | energy · structure · stability | ✅ |
| **6 · Exit reasons** | price vs levels · shock · illiquidity · expiry | ⚠️ needs current premium price — **§3** |
| **7 · Summary** | everything above | ✅ |
| **8 · Telegram** | the decision above | ✅ |

### Sources, in full

| Lifecycle input | From | Field |
|---|---|---|
| entry · stop · target1 | **EntryDecision** | `.entry` `.stop` `.targets` |
| the entry verdict and its identity | **EntryDecision** | `.state` `.id` `.side` `.strike` |
| premium energy · shift · acceleration | Context | `energy.energy` `energy.shift` `energy.energy_acceleration` |
| premium structure · score · confidence | Context | `premium.premium_structure` `premium.premium_score` `premium.premium_confidence` |
| liquidity · validation · agreement | Context | `strike.*` |
| stability · shock · freeze | Context | `market.stability` `risk.shock` `risk.freeze` |
| risk · validity · invalidation | Context | `risk.risk` `risk.validity` `risk.invalidation` |
| timing · lifetime · trade risk/quality | Context | `opportunity.*` |
| expiry | Context | `market.day_type` (`EXPIRY_PIN`) |
| acceptance / rejection | Context | `market.acceptance` |

---

## 2. ⛔ Phase 1 is not answerable, and must say so

`EntryDecision.state == "ENTER"` means *this engine concluded an entry was
executable*. It does not mean an order was placed, filled, or partially filled.
Nothing downstream of Stage 72 exists yet to report that.

Treating `ENTER` as "we are in a trade" would be the worst kind of assumption:
every lifecycle decision after it — trail, scale, exit — would be managing a
position that may not exist, and the mistake would be invisible because the
output would look completely normal.

### Decision

`position_known` is **always `UNKNOWN`**, and `PositionAwareness` reports two
separate things:

| Field | Meaning |
|---|---|
| `intent` | what Stage 72 decided — `ENTERED_INTENT` · `NO_ENTRY` · `ABORTED` |
| `position_known` | **`UNKNOWN`, always** — no producer exists |
| `why` | names the missing producer rather than guessing |

`MISSING_PRODUCERS` records `position_state` and `fill_price` by name. When a
broker or position store is added, it becomes a third input to `build()` and
`position_known` starts reporting — **without any other phase changing**,
because every other phase reads the tape, not the fill.

This also settles the state machine's first state: `WAIT_ENTRY` is the honest
reading whenever intent is absent, and `ENTERED` means *intent recorded*, not
*fill confirmed*. The contract says so in as many words.

---

## 3. One field added to TradingContext

Phase 6 must report `Target Hit` and `Stop Hit`, which is a comparison of the
**current premium price** against levels the decision already carries. The
context has that price — inside the `premium.premium_structure` blob as `ltp` —
but not as a field a consumer can read by name.

| Added | Owner | Path |
|---|---|---|
| `premium.premium_ltp` | Premium Structure | `structure.{side}.ltp` |

This follows the precedent `premium.premium_score` already set: the blob is one
field, and a specific fact inside it is another, on a distinct path. The
no-duplicate-path test passes unchanged.

**Nothing else is added.** Stage 73 reads the tape through the context and the
levels through the decision, and needs no other new fact.

---

## 4. What Stage 73 computes

Everything here is a **classification over values the two inputs already
carry**. No price is derived, no market fact measured, no entry re-decided.

| Computed | Why it is not a new market fact |
|---|---|
| **Position health** (6 bands) | a weighted read over eight context verdicts, unknowns excluded |
| **Lifecycle action** (one of six) | a priority ladder over health, stability and exit triggers |
| **Trail band** (4 + UNKNOWN) | a classification of *how* to trail. The stop **level** is consumed from `EntryDecision.stop`, never recomputed |
| **Scale verdict** | a three-way comparison of energy, structure and stability — never an average |
| **Exit reason** | a report of which trigger fired, first match wins. **Never a prediction** |

The trail band deserves the note it gets in the module: Stage 52 owns
`adaptive_trail` and Stage 73 may not import it. What Stage 73 produces is a
*band*, not a level — "trail aggressively" is a lifecycle judgement, "trail to
118.4" is a computation with an owner elsewhere. Where a level is wanted, the
consumer reads `EntryDecision.stop` and applies the band.

---

## 5. ⚠️ Ownership: what Stage 73 must never own

Per the scoping note, and asserted by tests:

| Not owned | Belongs to |
|---|---|
| Position sizing · lot count | a later stage, once capital is an input |
| PnL, realised or unrealised | a later stage |
| Broker integration, order placement | outside MIOS entirely |
| Whether to enter | **Stage 72**, frozen |
| Any analysis fact | **Stages 0–71.8**, through the context |
| Sending a message | downstream, behind a human-flipped switch |

Keeping sizing and PnL out is what makes this stage testable and freezable:
lifecycle decisions are a function of the tape and the levels, and both are
already available. Sizing needs capital, risk-per-trade and fills — three inputs
that do not exist yet, and whose absence would otherwise infect every phase.

---

## 6. Rules this audit forces

1. **`position_known` is always `UNKNOWN`.** Named in `MISSING_PRODUCERS`, never
   inferred from `state == "ENTER"`.
2. **Lifecycle states are Stage 73's own** — `WAIT_ENTRY · ENTERED · HOLD · ADD ·
   SCALE_OUT · TRAIL · EXIT · COMPLETE · ABORT`. Entry states are *not* reused;
   a test asserts the two vocabularies are disjoint except where a word
   genuinely means the same thing in both.
3. **`EntryDecision` is never mutated.** Stage 73 builds a new object that
   *references* `decision.id`.
4. **Two imports only** — `entry_engine` and `trading_context`.
5. **Add `premium.premium_ltp`**, nothing else.
6. **Exit reasons report, never predict.**
