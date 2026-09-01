# Phase 1 — Zone Intelligence (perfect the S/R first)

Entries, traps and targets are only as reliable as the level they stand on. So
before touching any of those, a support/resistance stops being *a number* and
becomes an object that knows its own story.

Look at one level and you immediately know: **how strong**, **why strong**,
**building or weakening**, **who is defending it**, **whether it is likely to
break**, and **whether to wait or prepare**.

## The ten reads

| # | Read | What it answers |
|---|------|-----------------|
| 1 | **Origin** | Which source *families* formed it (POC · HVN · Order Block · Round · PDH · OI · Gamma). Distinct families count — six tags from one family is one piece of evidence wearing six hats. → ★ score |
| 2 | **Strength** | Origin pedigree + options defence + OI/gamma concentration + freshness, adjusted by a **touch curve** (0 = unproven, 2-3 = proven, >4 = worn out). → % and ★ |
| 3 | **Lifecycle** | `Created → Untested → Holding → Building → Under Attack → Breaking → Broken → Retest → Recovered → Retired` — a real state machine with a post-break arc, not a static label |
| 4 | **Health** | Five defender groups — **Spot · Options · Dealers · Institutions · Liquidity** — each building/fading/neutral → one %. Flags `conflicted` when groups fight |
| 5 | **Battle** | Buyer % vs Seller % at the level, the winner and confidence. Defenders flip by side: buyers defend a support, sellers a resistance. `⚔️ WAR ZONE` when it's close |
| 6 | **Acceptance** | What price is *doing*: `Defended` · `Rejected` · `Accepted` · `🪤 Trap Active` (beyond the level while defenders are still strong = liquidity grab) |
| 7 | **Probability** | `Break %` · `Rejection %` (complements) and an independent `Trap %` |
| 8 | **HTF** | Which higher timeframes confirm the same price (1H/4H/Daily POC·VAH·VAL, PDH/PDL) → ★ |
| 9 | **Explanation** | The short "why is this strong" bullets + what to expect + invalidation |
| 10 | **Card** | All of it assembled into one display object |

## Where it shows

- **MIOS V5 Dashboard** — the full card per side (`mios_v5/ui/zone_card.py::render_zone_card`), replacing the old one-line "strength %" reads.
- **Trade Card** — the same intelligence distilled to a phone-width line per level (`zone_card_line`): level · ★ · lifecycle · health % · winner · break/reject, with a trap flag when it matters. The active zone additionally shows acceptance + the AI "why".
- **Telegram signal** — the `📤 Send Signal` message carries the full per-level breakdown.

## Design

`mios_v5/zone_intel.py` is **pure** — no session, no I/O, no pandas — so every
read is unit-tested (`mios_v5/tests/test_zone_intel.py`, 13 cases). The app layer
(`enrich_zone_intel` in `vob_minimal.py`) supplies the cross-cycle memory a level
needs: touches, age, pierced/reclaimed and the previous lifecycle state, bucketed
to 25 pts so a level keeps its identity when the cluster average wobbles.

The enrichment attaches `intel` to the **existing canonical `_reaction_sr`
object** and keeps `lifecycle` / `zone_health` in sync, so every existing
consumer (Trade Card badge, Decision Engine zone gate, Telegram) gets the richer
read without changing. `_major_sr_zones` — what the Entry Gate actually arms off
— is untouched: **no trade-path change**.

## Next (only after this is solid)

The Liquidity Trap & Entry Engine — entries are only as good as the S/R they're
based on, which is exactly why this came first.
