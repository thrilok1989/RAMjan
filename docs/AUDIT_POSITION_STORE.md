# Audit — the Position Store

*The missing producer. Audited before building, because the audit found two
partial owners that were not in the roadmap.*

## The question

Stage 73 manages a trade. Six of its fields — `pnl`, `mfe`, `mae`, `drawdown`,
`r_multiple`, `remaining_size` — cannot be computed, because
`MISSING_PRODUCERS = ("position_state", "fill_price")`. Nothing reports a fill.

Who, if anyone, already owns execution facts?

## Finding 1 — real orders are already being placed, outside MIOS

`auto_option_trader.py` (787 lines) is a **standalone Streamlit app**. It:

* places real Dhan orders — `place_order()` → `POST /orders`
* flattens positions — `exit_position()`
* reads **real broker fills** — `get_open_positions()` → `GET /positions`
* persists one trade to Supabase table `auto_option_trades`
* has a `🔴 LIVE TRADING` checkbox, default **off**

`quick_buy_option.py` (252 lines) does the same for a single manual buy.

**Neither is imported anywhere.** `grep` finds no caller. They are separate
apps sharing a database with MIOS and nothing else.

So execution facts exist in this system *today* — they simply never reach
Stage 73. This is the writer-without-a-reader half of the regression class this
repo has already been bitten by twice.

### What `auto_option_trades` actually is

```python
sb.table("auto_option_trades").upsert(
    {"id": TRADE_KEY, "payload": trade, "updated_at": ...})
```

* **No migration.** It is not in `sql/`; it was created ad hoc.
* **One row, one key.** `TRADE_KEY` is a constant — the second trade overwrites
  the first. There is no history.
* **A JSONB blob.** No column is queryable; no index; no retention policy.
* Every write is wrapped in `except Exception: pass`.

It is a session-resume cache for one app, not a store of record. It cannot be
the producer, and it must not be extended into one — a blob keyed by a constant
has no room for a second position.

## Finding 2 — `trade_signals` looks like a position store and is not one

`sql/026_trade_signals.sql` + `sql/027_learning.sql` already carry `entered_price`,
`exit_price`, `pnl_points`, `mfe`, `mae`, `max_drawdown`, `holding_secs`, with a
full writer/reader path in `db/supabase_client.py` and a live caller in
`vob_minimal.py`.

**But every one of those is measured on spot, not on a fill.** The schema says
so itself:

```sql
signal_spot    DOUBLE PRECISION,  -- spot when the signal was generated
entered_price  DOUBLE PRECISION,  -- spot at entry trigger
```

That is a **hypothetical** lifecycle: what the signal would have done. It is the
right input for learning and attribution — which is exactly what reads it — and
the wrong input for managing a real position. A trade that was never placed, or
was placed at a different price, or was placed at half the size, produces
identical rows.

> Two facts wearing one name is the failure this architecture exists to prevent.
> `trade_signals.pnl_points` and a real PnL are different facts. The Position
> Store must not write to these tables, and Stage 73 must not read them.

## What the Position Store owns

Exactly the facts the broker reports, and nothing derived from a model:

| Fact | Source |
|---|---|
| `order_state` — `PLACED · ACCEPTED · REJECTED · PARTIAL · FILLED · EXITING · CLOSED` | broker order response |
| `order_id`, `placed_at`, `reject_reason` | broker |
| `filled_qty`, `remaining_qty` | broker |
| `fill_price` per fill, `avg_fill` | broker |
| exit fills, `exit_avg`, `closed_at` | broker |
| `realized_pnl` | broker fills only — entry avg vs exit avg × qty |
| `mfe`, `mae` — the running water marks **on the premium actually held** | observed per cycle |

### What it does **not** own

* **Unrealized PnL and R-multiple.** Those are arithmetic over `avg_fill`, the
  current premium LTP and `EntryDecision.stop` — two of which live in the
  context and the decision. Stage 73 derives them, exactly as it already derives
  health and trail bands. The store would have to import a market read to do it,
  which is a second owner for a fact the context already has.
* **Any decision.** It records; it never concludes.
* **Order placement.** `auto_option_trader` owns that. The store records what
  happened, which is a different job from making it happen.

### Why MFE/MAE belong here and not in Stage 73

Stage 73 is **stateless per cycle** — it classifies one moment and returns. A
water mark is a memory across cycles. Anything with memory has to be stored, and
the thing that stores position facts is the position store. Stage 73 consumes
`mfe`/`mae` as facts and classifies them, which is what it already does with
every other input.

## Where it lives — the three-piece split

`mios_v5` may not import a database client. This is a named forbidden failure
mode, and it applies here more than anywhere: the store is inherently I/O.

The existing Stage 74 telemetry split is the pattern to copy:

| Piece | File | Rule |
|---|---|---|
| the contract | `mios_v5/position.py` | pure, frozen, no I/O, no `requests`, no `supabase` |
| the persistence | `db/position_store.py` | takes an injected `db`, owns every query |
| the schema | `sql/037_positions.sql` | migration, indexes, RLS, retention note |

Stage 73 receives a `Position` **object**, never a client — the same way it
already receives an `EntryDecision` rather than a way to fetch one.

## Effect on Stage 73

`73.0 → 73.1`, an amendment recorded exactly as Stage 72's was:

* a **third input**, `position`, defaulting to `None`
* `position_known` starts reporting instead of being `UNKNOWN` unconditionally
* six fields become computable **when a position is supplied**, and stay
  `UNKNOWN` when it is not
* `MISSING_PRODUCERS` shrinks to `()` when a position is present, and is
  reported as it stands rather than as a constant

**No other phase changes.** Health, trail, scale and exit reason read the tape
and the levels, which they already had. The docstring anticipated this.

## The gap this does not close

The store records what a broker reports. **Nothing in MIOS places an order**,
and this build does not add that — `auto_option_trader` remains a separate app
with its own switch. So in the normal MIOS run the store will be empty and
Stage 73 will report exactly what it reports today.

That is the correct outcome for a producer built before its writer: the consumer
is ready, the shape is fixed, and the fields say `UNKNOWN` honestly until
something fills them. What it must never do is *look* filled.

## Build list

1. `sql/037_positions.sql` — `positions` (one row per position, updated in
   place) + `position_fills` (append-only, one row per fill)
2. `mios_v5/position.py` — the frozen `Position` contract
3. `db/position_store.py` — reader/writer, injected `db`
4. Stage 73 → `73.1` — third input, six fields, amendment recorded
5. `ui/execution_panel.py` — the facts on the card, because Principle 12 binds
6. Tests — including the guard that `mios_v5/position.py` imports no I/O
