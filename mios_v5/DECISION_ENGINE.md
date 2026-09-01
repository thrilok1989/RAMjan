# MIOS V5 — Decision Engine

The final major architectural piece. Every other engine answers *what is
happening / why / who / where*. The Decision Engine answers the only question
that matters at the moment of action:

> **Do I act now, or do I wait?**

WAIT and STAND ASIDE are **first-class decisions**, not failed signals — which is
exactly why it is a *Decision* Engine, not a "signal generator".

```
33 Engines
     │
     ▼
Conflict Engine   (direction — a weighted vote)
     │
     ▼
Decision Engine   (gates — confluence; act or wait)
     │
     ▼
Trade Card
```

The Decision Engine **never recalculates** anything. It only asks *"are all
required conditions satisfied?"* over the reads the other engines already produced.

## The gate stack (a stack, not a vote)

For an entry you want **confluence** — a single weak read must never fire a trade.
So it is a sequence of gates; the first six decide, the seventh grades:

| # | Gate | Question |
|---|------|----------|
| 1 | **Location** | Is spot *at* a zone? (never mid-range) |
| 2 | **Direction** | Does the MIOS bias agree with the side? |
| 3 | **Zone Health** | Is the level *building*, not *fading*? |
| 4 | **Confirmation** | Candle/flow confirmation (don't chase the first touch) |
| 5 | **Risk** | R:R ≥ 1.2, room to target, invalidation defined |
| 6 | **Event / Veto** | Shock / preparation / hard conflict → stand aside |
| 7 | **Quality** | *How good* is the setup? A+ / A / B / C |

Gates 1–6 → **CALL / PUT / WAIT / STAND ASIDE**. The **Quality** gate scores each
gate ★1–5 and averages them: **A+ ≥ 4.5 · A ≥ 3.8 · B ≥ 3.0 · C < 3.0**. The same
direction can be an A+ or a C — that's how experienced traders actually think.

## Output

```
Decision:     CALL              |   Decision:     WAIT
Quality:      A                 |   Reason:       Zone healthy · Direction mixed ·
Confidence:   89%               |                 Order flow missing · Need confirmation
Reasons:      Support building  |
              Dealer alignment  |
              Positive flow     |
              Event clear       |
Invalidation: 23,970            |
Target:       24,040            |
```

The **"WAIT because…"** explanation is as valuable as a trade signal.

## v0 — observation only (current)

- Produces the decision + quality + reasons, renders it on the Trade Card, and
  **logs every state transition and every REJECTION** to `mios_decisions`.
- **Does NOT drive alerts.** The live Entry Gate keeps firing exactly as today.
- Both run in parallel: `Entry Gate → trade` and `Decision Engine → prediction →
  log`.

## Log every rejection

A **rejection** = spot was *at* a zone (a trade was possible) but a gate blocked
it. Each is logged with the blocking gate, e.g. `PUT rejected — Zone Health` /
`CALL rejected — Event Veto`. Without logging rejected opportunities you can never
learn things like *"the Event Veto prevented 73% of losing trades"* or *"ignoring
Zone Health cut win-rate from 71% to 58%."*

## Promotion path (design → observe → measure → promote)

1. ✅ Merge Event Intelligence (#233).
2. ✅ Lock the architecture in this doc.
3. ✅ Build v0 observation-only (produces + logs decisions; drives nothing).
4. ⏳ Run 2–4 weeks live; compare vs the Entry Gate on logged outcomes:
   Entry-Gate win-rate vs Decision-Engine win-rate · false positives · false
   negatives · which gate most often blocks losing trades.
5. ⏳ **Only if it performs as well or better** does it become the live decision
   path.

For something that ultimately decides whether to trade or wait, that evidence
-first path is the safe one.
