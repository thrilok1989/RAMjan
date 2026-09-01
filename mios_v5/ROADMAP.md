# MIOS V5 — Complete Engine Roadmap

A professional-institutional target architecture (~150–200 features across 17
stages) and an honest map of what is **built**, **partial**, or **not yet**.

> **Guiding principle:** not every stage has equal priority. The focus is
> making the existing **core** stages *reliable and validated* before expanding
> into the advanced / research-oriented modules. More engines ≠ more edge —
> edge is proven from logged outcomes, not added features.

Legend: ✅ built · 🔶 partial · ❌ not yet

---

## 🌍 Stage 1 — Macro Environment
*Does the outside world support or oppose NIFTY?*
- ✅ Global markets, US futures, Asian/European (Stage 19 global)
- ✅ VIX (Stage 22) · Commodities (commodity-risk) · FII flow / DII flow (Stage 23)
- ✅ Sector rotation · News sentiment (Stage 21)
- 🔶 GIFT Nifty (via global) · 🔶 Dollar Index (DXY) · 🔶 Bond yields
- ❌ Economic Calendar · ❌ RBI / Fed event days

## 🕒 Stage 2 — Market Context
*What type of day is today?*
- ✅ Gap Up/Down, Expiry (weekly), Pre-Expiry, Trend, Range, Pin, Gamma
  Unwind, Volatile, Coiled Spring (Stage 4)
- ✅ Time Cycle: Opening / Lunch / Closing (Stage 6)
- ❌ Monthly-vs-weekly expiry distinction · ❌ Post-Expiry · ❌ Reversal Day
  · ❌ Choppy Day · ❌ Holiday effect

## 🏗 Stage 3 — Market Structure
*Where is price located?*
- ✅ Swing High/Low, Support/Resistance, Demand/Supply, Order Blocks,
  Prev/Weekly/Monthly High-Low (Stage 2 structure + memory)
- 🔶 HH/HL/LH/LL market-structure labels
- ❌ Breaker Blocks · ❌ Fair Value Gap · ❌ Volume Imbalance · ❌ Trendlines
  · ❌ Channels · ❌ Fibonacci

## 📊 Stage 4 — Volume & Auction
*How is the auction behaving?*
- ✅ VWAP, Volume Profile, POC, VAH, VAL (Stage 2 structure)
- ❌ Anchored VWAP · ❌ HVN/LVN as signals · ❌ Market Profile · ❌ Opening
  Range · ❌ Initial Balance

## 📈 Stage 5 — Option Positioning  → ✅ **built (Stage 12 options)**
OI, ΔOI, Long/Short Build-up, Long Unwinding, Short Covering, PCR, Max Pain,
CE/PE walls, ATM±2 dashboard, Strong Support/Resistance dashboards.

## ⚡ Stage 6 — Dealer Positioning  → ✅ **built (Stage 11 dealer)**
GEX, DEX, Gamma Flip, Dealer Gamma/Delta, Gamma Wall, Vanna, Charm, hedge
pressure.

## 🌊 Stage 7 — Order Flow  → ✅ **built (Stage 14 order flow)**
CVD, Money Flow, CBV/CSV, Bid/Ask ratio, aggressive buyers/sellers, delta
flow. · ❌ Footprint chart · 🔶 Absorption/Exhaustion (partial via CVD).

## 💧 Stage 8 — Liquidity  → ✅ **built (Stage 17 liquidity)**
Liquidity pools, equal highs/lows, round numbers, magnet levels, walls.
· 🔶 Stop-cluster heatmap · 🔶 Sweep detection · ❌ true L2 depth / resting
orders (retail-data limit).

## 📉 Stage 9 — Volatility  → 🔶 **partial**
- ✅ VIX (Stage 22)
- 🔶 IV, IV Rank, IV Percentile — computed in the app, not yet a MIOS engine
- ❌ IV Skew engine · ❌ Realized/Historical Vol · ❌ ATR · ❌ Vol
  expansion/compression as signals
> **Next-priority build** (data mostly exists).

## 🕯 Stage 10 — Pattern Engine  → 🔶 **partial (Stage 26 alignment)**
- ✅ Candle + chart patterns, interpreted **through context** (continuation /
  reversal / trap / forming)
- ❌ Harmonics · ❌ Elliott Wave · ❌ Wyckoff phase (research / V6)

## 🧠 Stage 11 — Psychology  → ❌ **NOT BUILT — the main missing layer**
Accumulation, Distribution, Expansion, Exhaustion, Markup/Markdown, Smart
Money, Retail Trap, Breakout Trap, Liquidity Grab, Stop Hunt.
> **Highest-value genuine gap.** Much of the raw material exists (CVD,
> liquidity sweeps, order blocks) — this would synthesise it into a
> "who's trapping whom" read.

## 🏛 Stage 12 — Institutional  → ✅ **built (Stage 13 + Stage 25 intent)**
Institutional intent/absorption/accumulation/distribution, futures & options
positioning, dealer positioning. · 🔶 Large-block detection.

## 🤖 Stage 13 — Correlation  → 🔶 **partial**
- 🔶 Global + sector leaders (Stage 19)
- ❌ Dedicated engine for Bank Nifty / Sensex / FinNifty / Midcap / USDINR /
  Crude / Gold cross-correlation

## 📈 Stage 14 — Probability  → ✅ **built (Stage 31 + Stage 40 learning)**
Win probability, confidence score, prediction validation, self-grading vs
realised move. · 🔶 "similar historical days" (grows with data) · ❌ per-setup
success-rate table (needs the month of data).

## 🎯 Stage 15 — Entry  → ✅ **built (Entry Gate)**
Zone touch, candle confirmation, entry trigger, invalidation, R:R.
· 🔶 explicit volume/flow/dealer confirmation gates · ❌ position sizing.

## 📡 Stage 16 — Trade Management  → ✅ **built (Position Guardian)**
Exit signal, trade lifecycle, time exit, invalidation, hold-vs-exit.
· ❌ trailing stop / partial exit / break-even shift automation.

## 🧩 Stage 17 — AI Alignment  → ✅ **built (Stage 27 conflict + 41 final read + 36 narrative)**
Aligns every stage into: preferred bias, confidence, conflict %, market story,
risks, opportunities. The Stage 26 pattern engine already follows this
"pattern → context → flow → aligned read" philosophy.

---

## Coverage summary
**~12–13 of 17 stages covered**, with the entire core institutional spine
(Context · Structure · Positioning · Dealer · Order Flow · Liquidity ·
Institutional · Probability · Entry · Management · Alignment) built.

### Genuine gaps, in priority order
1. **Validate first** — run a month, let `alert_log` / `bias_predictions` /
   `entry_gate_signals` fill; find which of the 27 engines actually predict.
2. **Stage 11 Psychology** — the one truly-missing layer; high value, raw
   material already present.
3. **Stage 9 Volatility engine** — IV rank/skew/ATR; data mostly exists.
4. **Stage 13 Correlation engine** — cross-instrument.
5. **Leg Pattern Engine** — see below.
6. **Research / V6** — harmonics, Elliott, Wyckoff, event calendar, footprint.

## Leg Pattern Engine (per-leg CE/PE — planned, build AFTER the data month)
The 6 live legs (ATM, ATM±1 × CE/PE) already carry the primary signals —
**LTP trend · ΔOI · CVD · Money Flow · VWAP · VOB (accum/distrib) · Volume
Profile / Dynamic POC · Greeks · Build-up classification** — all computed
app-side, aggregated into `_full_market_read` + `_leg_bias_cache`, and
consumed by 7 MIOS engines (orderflow, institutional, dealer, intent,
probability, reaction-zone, context). So the per-leg engine is ~80–90%
complete; price + positioning + executed flow are covered.

**Missing:** candle/chart-pattern detection on the leg LTP charts, and a
formal consolidated **Leg Score** → CALL Score / PUT Score.

**Design (agreed):** patterns are *confirmation, not primary*. A Hammer alone
is noise; Hammer + Long Build-up + positive CVD + accumulation + at support
is meaningful. So:
- Run `detect_candle_patterns` / `detect_chart_patterns` on each of the 6 legs.
- Show them per leg alongside the existing reads (info only), and **log
  (leg, pattern, context, later outcome) to Supabase** for validation.
- **0% voting weight initially.** After ≥1 month of data, answer "does a
  Hammer on a CE leg actually improve prediction beyond LTP+ΔOI+CVD?" — give
  weight (~5–10%) only to the leg patterns the data shows add value.
- Candidate Leg Score weights to validate: Pattern 20 · Order Flow 25 ·
  Positioning 25 · Accumulation 20 · Location 10.

**Wiring decision (from the architecture review):** build it as a **dedicated
engine reading a new forwarded `raw["leg_patterns"]` object** (runner adds the
per-leg dataset to MarketState.raw), *not* by blending patterns into
`_full_market_read`. This keeps each leg's score independent and lets the
engine be logged at 0% and validated on its own before it earns voting power
— exactly parallel to how VIX / FII-DII / Liquidity were added.

## Opening Auction — Gap Behavior & Quality (observe now, build after the data)
The app now detects the gap from the ~09:06 pre-open spot and classifies it as
**Inside / Outside yesterday's value area** (pure classification, no prediction),
and **logs every gap session to `opening_auction_log`** — opening fields +
value location + how the gap resolved (fill % / acceptance) through the day.

That log is the evidence to build — *only after ≥1 month of real gap sessions
confirms the setup→outcome mapping* — the behaviour layer:
- **Gap Behavior** (outcomes, validated from the log): Gap-and-Go · Gap-Fill ·
  Gap-Reversal · Inside-Value · Outside-Value. Outside-value that holds → accept
  → gap-and-go; outside-value that fills → reject/reversal; inside-value → chop.
- **Opening-Auction-Quality score**: gap size × acceptance strength × value
  migration → an opening-strength read of whether the market *accepts or rejects*
  the gap. Institutional-grade context, but it must earn trust from logged
  outcomes first — do NOT give it voting weight until validated.

## Event Intelligence — built + the next two stages
Philosophy: **the market moves first; events explain later.** None of these vote
in the Conflict Engine — they are context only.

**Built (V5.1):**
- ✅ Stage 24 — Preparation (market coiling: IV/OI/dealer-hedge/compression)
- ✅ Stage 28 — Shock Detection (VIX/volume/gamma/CVD shock → reaction)
- ✅ Stage 30 — Calendar (known scheduled catalysts; categorized, you maintain it)
- ✅ Stage 34 — Explanation (searches calendar + news for a *possible* cause)

**Plan for V5.2 / V6 (need the logged data first — validate before you weight):**
- ❌ **Stage 33 — Event Impact** (note: "36" is taken by the Story engine). Not
  every RBI/Fed/headline matters. This measures the EFFECT, not the cause: did
  the event actually change market structure? (gap · volume · gamma flip · dealer
  hedge · CVD · institution flow) → Impact LOW / MEDIUM / HIGH / VERY HIGH. Turns
  "what happened?" into "how much did it matter?".
- ❌ **Event History Library** — log each event's realised outcome (avg move, IV
  crush, typical direction, duration) to Supabase. After months MIOS can say
  "historically markets moved ~1.4% after this event; today's positioning is
  stronger than usual." Learns from *your own* logged results, not textbook
  assumptions — the same "log now, weight later" pattern as the Leg/Opening logs.

## V6 — self-learning (after ≥1 month of data)
Learn which setups work best · auto-adjust feature weights · detect new
recurring market states · improve probabilities from *your own* results rather
than fixed rules.
