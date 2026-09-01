# Query / index audit

*Taken at `dd4b443`. Method: every query shape extracted from
`db/supabase_client.py`'s **parse tree**, matched against every index declared
across `sql/*.sql` and `db/schema.sql`.*

```
238 indexes   ·   54 tables   ·   110 distinct query shapes
```

---

## Verdict

**No table is unindexed. Twenty-three query shapes filter on an index and then
sort without one** — Postgres finds the rows, then sorts them in a separate
node. And the single heaviest read in the application has no usable index at
all.

`sql/033_query_indexes.sql` adds 24 indexes. Every one exists because a real
query filters or sorts on exactly those columns, in that order. Nothing is
speculative.

---

## 1 · The finding that matters — the learning tables

`_learning_rows` is four lines and it is the most expensive thing in the app:

```python
def _learning_rows(self, table, limit, order='created_at'):
    return (self.client.table(table).select('*')
            .order(order, desc=True).limit(limit).execute())
```

`ORDER BY created_at DESC LIMIT n`, **no filter**. And:

| Table | Read as | Index on `created_at`? |
|---|---|---|
| `engine_attribution` | `get_engine_attribution(8000)` | ❌ **none** |
| `trade_attribution` | `get_trade_attribution(500)` | ❌ **none** |
| `trade_results` | `get_trade_results(500)` | ❌ **none** |
| `learning_snapshots` | `get_learning_snapshots(100)` | ❌ **none** |
| `trade_events` | `get_trade_events(4000)` | ✅ `idx_trade_events_ts` |

Their existing indexes are on `trading_day`, `signal_id` and `engine` — useful
columns, none of which this query touches. So `get_engine_attribution(8000)`,
the largest single read in the codebase, is a **sequential scan plus a sort**,
every time it is not served from cache.

`trade_events` is fine by accident rather than design: it orders by `ts`, and
`idx_trade_events_ts (ts)` serves `ORDER BY ts DESC` because a btree can be
scanned backwards.

> This was nearly missed. The first pass extracted queries by looking for
> `.table('literal')`, and `_learning_rows` takes the table as a **variable** —
> so all five of these were silently absent from the results. A query the
> analysis cannot see reads exactly like a query with no problem.

---

## 2 · Candles — every read misses `exchange`

`idx_candles_symbol_tf` is `(symbol, timeframe, datetime)`. All three candle
reads filter on `(symbol, exchange, timeframe)`. Postgres can still use the
index and then re-check `exchange` on every row it returns.

| Query | Filters | Sorts | Served by |
|---|---|---|---|
| `get_candles` | symbol · exchange · timeframe · `datetime >=` | timestamp | partially |
| `get_candles_for_day` | + trading_day | timestamp | partially |
| `get_candle_trading_days` | symbol · exchange · timeframe | trading_day | ❌ |

`get_candle_trading_days` is the one that matters: it reads `trading_day` for
an **entire series** to compute a DISTINCT, and `compute_prev_day_value` calls
it. `idx_candles_series_day` makes it an index-only scan.

---

## 3 · The live path

The read cache classifies four reads as `LIVE` — they expire every refresh
cycle, so they are the reads that actually reach the database most often. Two
were filter-then-sort:

| Read | Shape | Was |
|---|---|---|
| `get_active_trade_signal` | `status = ? ORDER BY created_at DESC` | two single-column indexes |
| `get_latest_spot` | `security_id = ? ORDER BY timestamp DESC` | index on `timestamp` alone |

---

## 4 · The chain tables

`option_chain_data`, `atm_strike_data` and `orderbook_data` each carry three
single-column indexes — `expiry`, `strike_price`, `timestamp` — and every
query filters on two and sorts on the third.

**Three single-column indexes do not add up to one composite.** Postgres will
pick one, filter with it, and sort the survivors. These are the highest-row-count
tables in the schema, so it is the worst place for that to happen.

---

## 5 · Retention scans

`db/retention.py` counts and deletes on `day_col`. Where that column is
`trading_day` an index already exists. Where it is a timestamp —
`market_events`, `market_stories`, `story_validations` — there was none, so a
purge would scan the whole table to find the rows to remove. That is the wrong
shape of work for a job whose entire purpose is to make the table smaller.

---

## 6 · What was already correct

Worth recording, because most of the schema is fine:

* every table has a primary key and RLS
* `trading_day` is indexed nearly everywhere it is filtered
* `engine_state`, `session_log` and `day_type_log` already index their sort
  column `DESC` — someone thought about this
* `dispatch_history`'s partial unique index on `decision_hash WHERE status =
  'SENT'` is exactly right for the claim protocol
* the unique constraints backing every `upsert`'s `on_conflict` all exist —
  without them an upsert silently becomes an insert

---

## 7 · Applying it

⚠️ **Outside market hours.** A plain `CREATE INDEX` takes a `SHARE` lock and
blocks writes on that table until it finishes. On `option_chain_data` that can
be minutes, and this app writes every twenty seconds. `CONCURRENTLY` variants
are at the bottom of the migration; they cannot run inside a transaction, so
run them one statement at a time.

Then `ANALYZE` — a stale estimate after a bulk build can make the planner
ignore an index it should use.

Afterwards, the check that matters:

```sql
SELECT relname, indexrelname, idx_scan
  FROM pg_stat_user_indexes
 WHERE idx_scan = 0
 ORDER BY relname;
```

An index with `idx_scan = 0` after a full trading day is dead weight — it costs
write time and storage and serves nothing. That query will also flag some of
the **pre-existing** indexes this audit did not touch; `option_chain_data`'s
three single-column indexes are the ones I would expect to show up once the
composites are in.

---

## 8 · Batch writes

Not an index finding, but it came out of the same read of the client.

`_safe_upsert` has always taken a **list**. The cost was in call sites handing
it one row at a time:

```python
for p in db.get_open_bias_predictions():        # Stage 40, grading
    db.update_bias_prediction(p["id"], {...})   # one round-trip. each.
```

Predictions come due in clumps — every one logged in the same window matures in
the same window — so twenty round-trips to write twenty small rows was the
normal case, not the worst one. `db/write_batch.py` collects them and writes
once.

### Why batching is opt-in

The obvious version intercepts every `insert_*` and defers it. That version
breaks the dispatch claim protocol: `reserve()` writes the `SENT` row **before**
the Telegram message goes out, so a crash between the two leaves a recorded
claim rather than a silent duplicate. A deferred reserve is not a claim, it is
an intention, and the next cycle would send the message again.

So a call site asks for batching where its author has decided a row landing a
few milliseconds later is fine. A test asserts `dispatch_registry.py` does not
import it.

### Two properties over the saving

* **It always flushes**, including out of a raising block. Queued rows dropped
  because something *else* failed is data loss with nothing pointing at it.
* **It refuses a row missing its conflict key.** An upsert whose conflict target
  is absent does not update anything — it inserts a second row. A loud refusal
  beats a silent duplicate.

And the grading loop keeps its per-row path for any shortfall. That is not
padding: a grading pass that writes nothing loses predictions that have already
matured — read as open, graded, dropped, and still open next cycle with a
`due_at` further in the past. Measured, then forgotten, permanently.

---

## 9 · What this audit did not do

Stated so nobody reads more into it than it did:

* **No `EXPLAIN` was run.** These are structural findings from the query shapes
  and the declared schema. Confirming a plan actually improved needs `EXPLAIN
  ANALYZE` against real data volumes.
* **No row counts were measured.** Which of these matters most depends on table
  sizes nobody has looked at. `SELECT count(*)` on `option_chain_data`,
  `candles_data` and `engine_attribution` would rank them.
* **No RPCs were introduced.** `get_available_candle_series` and
  `get_candle_trading_days` both pull a whole column to compute a DISTINCT in
  Python, which is what a `DISTINCT` in a Postgres function is for. The read
  cache made both once-per-session, so it stopped being urgent — but the right
  fix is still an RPC, and it is not in this change.
* **Supabase Storage was not audited.** That is roadmap item 8 and it is a
  different system from the database.
