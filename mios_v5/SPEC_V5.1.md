# MIOS V5.1 — Amendments & Backlog

> Amends the version-locked `SPEC_V5.0.md` baseline. V5.0 remains unchanged;
> everything new or changed since the V5.0 lock is recorded here.

Status: ACTIVE · Opened: 2026-07-21 · Baseline: SPEC_V5.0.md

---

## A. Amendments to V5.0 (user-approved changes)

### A1. ENTRY GATE — deliberate exception to the "no BUY/SELL wording" rule
V5.0 Rule 5 says MIOS never generates BUY/SELL. The user explicitly requested
and approved a **zone-gated entry verdict** in the legacy Market Picture:

- A **"BUY CALL/PUT ZONE ACTIVE"** banner (big/bold) renders ONLY when all
  three gates hold: spot AT the S/R zone (±25 pts) · zone strong (≥55%) or
  writers building (ΔOI) · engine votes aligned (net ≥ +2 / ≤ −2).
- On activation it sends **one Telegram message** (`entry_gate` class — the
  single deliberate exception to `_RETIRED_ALERT_CLASSES`) and stores one row
  in Supabase `entry_gate_signals` (migration 012) with the full factor
  snapshot.
- All other states (REVERSED / AT_ZONE_WAIT / WAIT) are small, screen-only.
- The banner and message state "your decision, no auto-entry" — the trader
  still decides. This is gated decision-support, not an auto-trader.

### A2. Post-audit defect fixes (this release)
1. **Stage 3 Memory wired.** The runner now derives previous-session
   PDH/PDL/prev-close from the `_df_5m` intraday cache (cached per trading
   day) and feeds `raw['market_memory']` — the engine previously had no input
   and was permanently NEUTRAL.
2. **Stage 37 Briefing rendered.** The one-page institutional briefing
   (already computed by the Story engine) now renders in the Decision
   Dashboard under "📋 One-Page Institutional Briefing".
3. **Health tempers confidence.** `final_read` multiplies headline confidence
   by a health factor (health 100 → ×1.0, 50 → ×0.8, 0 → ×0.6), fulfilling
   the Stage-0 rule "reduce engine confidence if errors exist".

## B. Backlog — stages not yet built (V5.1+ scope)

Priority order reflects the project's own rule: validate first (the learning
loop must grade real reads before more engines earn their place).

| Priority | Stage | Item | Notes |
|---|---|---|---|
| P1 | 4 | Market Context (gap type, expiry/RBI day, day classification) | inputs mostly present in legacy |
| P1 | 18 | Sector Rotation adapter engine | legacy sector data exists; just needs an adapter that votes |
| P2 | 32–34 | Scenario paths / Risk map + score / dedicated Invalidation | reaction zone covers the active scenario only |
| P2 | 24 | Market Energy | volume expansion / exhaustion proxies exist |
| P2 | 29+ | Evolution: also watch VIX, sector-rotation and sweep shifts | |
| P3 | 7 | Market Structure (BOS/CHOCH, ICT blocks/FVG) | genuinely new build |
| P3 | 16 | Chart patterns (triangle/flag/wedge) | candlesticks exist in legacy |
| P3 | 22/23 | Dependency + Leader/Follower | needs correlation window store |
| P3 | 30 | Historical Pattern (analogue days) | needs a daily-summary store to accumulate first |
| P4 | 17 | Breadth | constituent feed unavailable; heavyweight proxy only |
| P4 | 11+ | Speed/Color/Veta/Zomma greeks; Max Pain surfaced in engine | marginal value |
| — | 1/10/15 | DOM, tick tape, resting stops, iceberg/spoofing | **permanently DISABLED** — retail Dhan data limit |

## C. Known accepted limitations
- V5 adapters read the previous cycle's caches (~20 s lag) — immaterial for a
  monitoring layer; documented in the runner.
- Stage 40 accuracy and IV percentile are meaningful only after data accrues
  (~20–50 graded reads / ~20+ trading days of IV history).
- Legacy dashboard and V5 run side-by-side; V5 reads legacy caches one-way.
