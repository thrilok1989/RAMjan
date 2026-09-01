# Audit — Stage 71.90, Closing Auction Behaviour Engine

*The spec's own rule: "Do not duplicate any logic already present in existing
MIOS engines. Consume outputs wherever possible." This applies it to the spec.*

## Verdict

**Build it — but three of the nine behaviours cannot be delivered from the data
this app has, and one input has to exist first.**

This is the first spec in this roadmap where the audit says *yes, mostly*. The
reason is a genuine discovery: **MIOS already fetches NIFTY futures — price,
volume, OI, OI delta, basis and stance — and no engine reads any of it.**

| Spec element | Verdict |
|---|---|
| Consume dealer · institutional · global · news · regime engines | ✅ all exist |
| The 15:15–15:30 window | ✅ already owned by `session.py` |
| Futures trend · basis · volume | ✅ **data exists, unused** |
| Institutional Accumulation / Distribution | ✅ buildable |
| Dealer Hedging | ✅ buildable |
| Short Covering · Long Unwinding | ⚠️ needs a **day-anchored OI baseline** first |
| Window Dressing | ⚠️ partial — breadth is available, sector timing is not |
| **Sector closing participation** | ❌ feed is ~15 min delayed |
| **Auction Manipulation** | ❌ no auction-imbalance feed exists |
| **Gap probability from GIFT/SGX + futures** | ❌ GIFT is a *proxy of the same futures* |

---

## Finding 1 — futures are fetched and nothing in MIOS reads them

`get_nifty_futures_data()` (`vob_minimal.py:1472`) returns, every cycle:

```python
{'symbol', 'expiry', 'price', 'volume', 'oi', 'chg_oi',
 'chg_price', 'basis', 'stance'}   # stance: Premium | Discount | Flat
```

It lands in `st.session_state['_nifty_futures_data']`, and has **exactly one
reader** — a display panel at `vob_minimal.py:9197`. No engine consumes it, and
it reaches no bridge, so no stage can see it.

The spec says *"Weight futures behaviour above spot, and spot above
options-only signals."* MIOS today weights futures at **zero**, because nothing
reads them. That single gap justifies this stage more than any of its nine
behaviours do.

> This is the **third** writer-without-a-reader in this repo, after `cfb6c93`
> and the three frozen stages that sat with no caller. It is the same class of
> defect and it is invisible in exactly the same way: the fetch succeeds, the
> panel renders, and the intelligence goes nowhere.

## Finding 2 — `chg_oi` is not the OI change this engine needs

```python
prev = st.session_state.get('_nifty_fut_prev_oi')
st.session_state['_nifty_fut_prev_oi'] = oi
chg_oi = (oi - prev) if (prev is not None and oi) else 0.0
```

That is the delta **since the previous refresh** — roughly 20 seconds — held in
`session_state`, which resets when the app restarts or the tab reloads.

Short Covering (*"futures up, OI falling"*) and Long Unwinding (*"price down,
OI down"*) are claims about **the day's** OI, not the last twenty seconds. A
20-second delta is noise at closing-auction volumes, and a `session_state`
counter that resets mid-session would silently report `0.0` as though OI had
been flat.

> **A day-anchored OI baseline is a producer, not an engine** — the day's first
> observed futures OI, stored, so `oi - day_open_oi` is available. Small, and
> exactly the shape of the Position Store conclusion: the consumer is easy, the
> missing thing is a fact with no writer.

Until it exists, those two behaviours report `UNKNOWN` by name.

## Finding 3 — the sector feed cannot see the closing window

Stage 18's own docstring:

> *"It is SELF-AWARE about its own (Yahoo-sourced, **~15-min-delayed**) data. It
> votes only when the data is trustworthy and otherwise stands aside as
> NEUTRAL: coverage < `_MIN_SECTORS` → NEUTRAL; snapshot older than
> `_MAX_STALE_MIN` → NEUTRAL."*

The engine window is 15:15–15:30. A feed delayed ~15 minutes describes, at
best, **15:00–15:15** — the period *before* the window. "Closing participation"
and "institutional rotation into the close" are not measurable from it.

Stage 18 already set the precedent by refusing to vote rather than voting on
stale data. Stage 71.90 must inherit that: sector contribution is consumable as
*context for the session*, and must not be labelled a *closing* read.

## Finding 4 — "Auction Manipulation" has no feed behind it

The spec detects *"large imbalance, one-sided auction move, no confirmation
from futures."*

NSE's closing-auction imbalance is a distinct data product. Nothing in this app
subscribes to it — the Dhan quote gives last price, volume and OI, and there is
no order-imbalance field anywhere in the tree. Three of the four listed
conditions have no measurement.

The fourth — *"sudden spike with no confirmation from futures"* — **is**
measurable, because spot and futures are both available. That is a real and
useful read, and it is a different claim:

> **`Unconfirmed Spot Spike`**, not `Auction Manipulation`.

Naming it manipulation asserts intent from a divergence. It belongs with
institutional-vs-retail liquidity from the Stage 71.86 audit: a label with no
measurement behind it, rendered beside labels that have one.

## Finding 5 — GIFT Nifty is the same series as the futures

`compute_gift_nifty_moneyflow()` says so plainly:

> *"True GIFT NIFTY (NSE IX) OHLCV is not publicly accessible… proxied via
> NIFTY near-month futures."*

So a gap-probability model that weighs *"Futures"* and *"SGX/GIFT"* as two
inputs would count **one series twice** and read the agreement as
confirmation. Gap probability may use futures **or** GIFT, never both, and the
double-count must be named in the code so nobody re-adds it.

## Finding 6 — the window and the engines already exist

| Fact | Owner |
|---|---|
| 15:00–15:30 is `CLOSING` | `mios_v5/session.py` (Stage 69) — purpose already lists *Position squaring · Expiry effects · Dealer hedging* |
| Dealer gamma · delta · walls · net position | Stage 11 — Dealer Positioning |
| Institutional positioning modes + score | Stage 13 — Institutional Position |
| Global context | Stage 19 · Stage 20 |
| News | Stage 21 · VIX Stage 22 |
| Regime | Stage 05 |
| Premium LTP behaviour | Stage 71.85 |
| Time-of-day cycles | Stage 06 |

The engine consumes all of these. It must not restate the window boundaries —
`session.py` owns them, and a second definition of "closing" is how 15:15 comes
to mean two different times one stage apart.

There is a `sql/023_opening_auction_log.sql` and **no closing equivalent**, so
persistence is genuinely new.

---

## What the audit justifies

**A behaviour-interpretation engine over existing outputs, plus one producer.**

| Build | Size | Notes |
|---|---|---|
| **Day-anchored futures OI baseline** | producer, tiny | unblocks Short Covering + Long Unwinding |
| `mios_v5/closing_auction.py` | the engine | consumes only published facts |
| A futures bridge | small | so the fetched data reaches a stage at all |
| `ui/closing_panel.py` | the panel | Principle 12 |
| `sql/0xx_closing_auction_log.sql` | schema | opening has one; closing does not |

**Six behaviours are deliverable now:** Institutional Accumulation,
Institutional Distribution, Dealer Hedging, Window Dressing (breadth-only),
Unconfirmed Spot Spike, Neutral. **Two more** once the OI baseline exists:
Short Covering, Long Unwinding. **Gap preparation** is deliverable from futures
+ global, with GIFT excluded as a duplicate.

**Not deliverable, and to be recorded in `MISSING_PRODUCERS` rather than
approximated:** sector closing participation (feed too slow), auction imbalance
(no feed), `Auction Manipulation` as a named verdict (no measurement of
intent).

## The scoring rule this engine needs

The spec asks for nine independent 0–100 scores and one dominant verdict. With
three inputs unavailable, the unknown-excluded rule from Stage 72 applies
directly and is not optional here:

> Unknown inputs leave the denominator. A behaviour scored from three of eight
> conditions is not a weak read, it is a barely-informed one, and the two must
> not render as the same number.

Every score therefore travels with `reporting` and `of`, and the dominant
verdict is `UNKNOWN` — not `Neutral` — when too few conditions reported.
`Neutral` means *the evidence agreed that nothing is happening*; that is a
different fact from *we could not see*.
