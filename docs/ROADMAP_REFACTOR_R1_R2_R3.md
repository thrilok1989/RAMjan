# Roadmap — the three refactors, before any more feature stages

**Decision:** Stage 42.5 is cancelled. It would have been an eighth owner of
level behaviour wearing the word "unified" — the thing the audit was written to
prevent. The work becomes **R1**, a refactor of Stage 42, and it is the first of
three cleanups that run before any new capability.

> No Stage 75. No Stage 76. No Stage 42.5. Nothing is added until one fact has
> one owner again.

Numbering deliberately leaves the stage sequence: `R1`, `R2`, `R3` are not
stages, they remove stages. A refactor with a stage number invites the next
reader to consume it as a producer.

---

## Why not another stage

`docs/AUDIT_STAGE_42_5_LEVEL_INTERACTION.md` found **seven** state machines
answering "what is price doing around this level?", publishing **48 state names**
and reading **fourteen** different "at the level" thresholds. Adding a
canonical eighth without deleting the seven produces eight — the new one is just
the one with the best docstring.

The audit's other finding is what makes a refactor tractable rather than heroic:
**Stage 42 and Zone Intel are not duplicates.** Only four of Zone Intel's ten
states are level *interaction*; the other six are the level's biography and
health, which Stage 42 does not compute and never will. They are one concept
accidentally split, not two competing answers. Separating them correctly is a
smaller job than arbitrating between them.

---

## R1 · Unified Level Behaviour

**Merge into Stage 42:** Zone Intel's four interaction states, the reclaim
helpers, the sweep logic, and every proximity constant.

**Publishes one object:**

| Field | Source today |
|---|---|
| `interaction_state` | Stage 42's fifteen states → twelve (see below) |
| `previous_state` | ❌ one-field gap — Stage 42's memory stores `state`, never the prior one |
| `state_confidence` | `acceptance._confidence()`, already 0–97 |
| `state_duration` | `cycles_beyond` today; needs a state-entry timestamp for seconds |
| `transition` | falls out of previous → current |
| `interaction_side` | already on the zone |
| `interaction_distance` | ⭐ normalised by `max_beyond` — the level's own observed reaction width, which Stage 42 already tracks — **not** a constant |
| `interaction_strength` | `acceptance._score()` pct, unknown-excluded |
| `interaction_type` | `sweep` derivable today; the rest need a vocabulary before they mean anything |
| `reaction_count` | `_zone_memory['touches']` |
| `last_interaction` | `_zone_memory` |

**Twelve states:** `APPROACHING · TOUCHING · ABSORBING · REJECTING · ACCEPTING ·
BREAKING · FAILED_BREAKOUT · BULL_TRAP · BEAR_TRAP · RECLAIMING · RETESTING ·
LEAVING`, plus `IDLE` as a null sentinel — twelve states with no way to say
"nothing is happening" would force a false claim every cycle.

Fifteen map to twelve **without losing a distinction**: three pairs encoded
direction in the state name (`side` already carries it) and one pair encoded
speed (`interaction_type = "sweep"`).

**Every magic constant dies.** Fourteen thresholds today, three of which
disagree by 3×. Replaced by adaptive width — ATR, session range, and the level's
own `max_beyond`. Nobody outside Stage 42 contains `25`, `20` or `15`.

**Delete, do not wrap:**

| Delete | Why |
|---|---|
| `classify_sr_behavior`'s `BUILDING` | ⭐ means only "within 25 points". Casts a directional bias vote **and** feeds `send_fresh_entry_alert` — the main bot's only automated alert. Fires BUY CALL at the top of a 50-point fall. |
| `simple_entry.NEAR_POINTS` | rule 1 becomes a state test, not a distance test |
| Zone Intel's `acceptance()` | Stage 42 answers this with a reference point in time |
| `annotate_sr_trend`'s `lifecycle` | third vocabulary into a key that gets overwritten; `fading` and `stable` are unreadable downstream |

**Keep:** `_zone_memory`'s 25-point bucket. That is level *identity*, not
proximity — same number, unrelated purpose.

**Known scope limit, to be written into the contract:** Stage 42 evaluates
exactly two levels (`("support", "resistance")` from `_reaction_sr`), never the
ranked `_sr_levels` list. R1 ships covering two. Extending it is separate work,
and the contract must say so rather than let the first consumer discover it.

---

## R2 · Unified Alert Pipeline

**At least five parallel entry-alert paths**, not the three previously reported:

1. legacy `entry_gate` (`vob_minimal.py:7404`)
2. `send_fresh_entry_alert` (`:12152`) — *"the ONLY automated alert on the main bot"*
3. `send_atm_wall_vob_entry_alert` (`:11792`, `proximity_pts=25`)
4. `send_spot_sr_legs_confluence_alert` (`:11950`, `proximity_pts=25`)
5. the MIOS V6 chain (72 → 73 → 72.9)
6. simple entry (5 rules)

Six, counting properly. Each has its own cooldown, its own proximity band and
its own idea of what a signal is. **One dispatcher, one claim protocol, one
suppression vocabulary** — and every suppression reason visible in the UI.

**Already done, ahead of R2** (this PR): the execution panel now reports
gate-by-gate status, why there is no signal, and why Telegram was suppressed.
That work is the observability R2 needs to be verifiable — you cannot
consolidate six senders safely without being able to see which one spoke.

---

## R3 · Unified Level Model

One canonical S/R object. Today `_major_sr_zones`, `_reaction_sr`, `_sr_levels`
and the OI walls are four shapes for the same levels, and R1's two-level scope
limit is a direct consequence of that fragmentation. R3 removes the limit R1
documents.

---

## Sequencing

R1 → R2 → R3, in order, and nothing else in between.

R2 depends on R1: consolidating six senders while they each define "at a level"
differently just moves the disagreement inside one function. R3 depends on R1
for the same reason — the canonical level object has to carry a behaviour field
that already means one thing.

**Freeze conditions for R1** (from the audit, unchanged):

1. `previous_state` exists, so `transition` and `duration` are measured rather
   than `UNKNOWN`.
2. The two-level scope limit is in the contract, not discovered.
3. The three `lifecycle` writers are down to one.
4. Every `interaction_*` field is visible in the UI — **Principle 12**. Freezing
   a contract nobody can inspect freezes the guesses with it.

---

## Standing items, unchanged

- Stage 74 calibration week — *"do not touch the calibration until the live week
  completes."*
- Round 2 archiving (9 files held back; 5 need test untangling).
- Delete the archived files, after live verification.
- `MIOS_PROFILE=1` and decide caching from real numbers.
- Position Store — *"auto trade create later."*
