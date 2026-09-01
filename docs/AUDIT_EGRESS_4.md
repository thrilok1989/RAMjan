# Egress round 4 — the width, and the number nobody could see

**Reported:** still ~1 GB of Supabase egress in one trading day, after round 3.
**Target: 100 MB/day.**

Round 3 removed a five-minute refetch treadmill: 78 fetches of each read per
day became one per app lifetime. The mechanism was certain and the round-trip
counts were proven. **The bill did not visibly move.** Round 3 said, in its own
§6, what to do if that happened:

> These are counted round-trips, not measured bytes. … If the bill is still high
> after this, that breakdown is the next place to look, **not another query**.

This round takes that instruction literally. It does two things: it closes the
one lever caching structurally cannot pull, and it makes the day's bytes
visible so round 5 starts from a measurement instead of a hypothesis.

---

## 1 · Caching fixed *how often*. It cannot fix *how wide*.

`db/read_cache.py` is a good layer and it is working. But two kinds of fetch
survive any cache, and they pay full row width every single time:

* **the cold-start pass** — every app restart re-reads everything, and
  `st.cache_data` lives in the server process
* **the invalidation refetch** — three tables are written every 20-second cycle,
  so `REFRESH_FLOOR` still permits 78 refetches a day

52 of 61 reads were `select('*')`. `tools/egress_meter.py` named this as the
largest remaining item and deliberately deferred it, with a reason worth
repeating because it is the failure this round had to design around:

> narrowing a column list is a per-call-site decision: each one needs its
> consumers checked, and **getting it wrong renders a blank field rather than a
> slow one**.

### What was narrowed, and why only two reads

A JSONB blob dwarfs every scalar column beside it, so dropping one blob from an
8,000-row read is worth more than narrowing thirty small ones. Two reads have
both the most rows **and** a blob column that no reader touches:

| read | rows | declared | projection | dropped |
|---|---|---|---|---|
| `get_engine_attribution` | 8,000 | 17 cols | 16 | `data` (JSONB) |
| `get_trade_signals` | 300 | 24 cols | 23 | `engine_snapshot` (JSONB) |

Both drops were verified, not assumed:

* **`engine_attribution.data`** — written by Stage 55 and never read back. The
  only two hits on the name are producers: `attribution.py::engine_rows` builds
  it from a live `MarketState` in order to *write* it, and `stage29_evolution`
  reads `state.raw["prev_snapshot"][…]["data"]`, which is the runner's own
  in-session snapshot and a different dict that happens to share a key name.
  Every actual reader of these rows — `contribution`, `engine_accuracy`,
  `calibration`, `attribution` — uses only the scalar columns.
* **`trade_signals.engine_snapshot`** — no reference anywhere in the repo
  outside one docstring explaining why per-engine rows replaced it. Its two
  callers are `dashboard_v6::_history` (an explicit column list) and `replay`
  (ten scalar keys).

Every other table keeps `select('*')`. Narrowing is opt-in per table, which is
the safe direction for a read whose consumers have not been checked.

### The failure mode an inclusion list introduces, and how it is closed

A column added to the schema later would be **silently omitted** — and a
silently missing column is exactly the blank field the meter warned about. So
the projection is not trusted as written. `test_read_projections.py` re-derives
every list from `sql/*.sql` and asserts

```
projection == declared columns − dropped blobs
```

Add a column to a migration without adding it to `_PROJECTIONS` and **the suite
fails instead of the panel.** A second test re-derives the read's callers and
fails if a new module starts consuming these rows without being declared, so
the safety argument cannot rot into a comment.

---

## 2 · One limit per read — the rule round 3 wrote and applied to two of six

Round 3 §4 established it: *"A panel wanting fewer rows slices the shared
result; it must not ask a different question."* It fixed `get_session_log` and
`get_trade_signals` and left the four learning reads asking at **three limits
each**, from three panels, all of which run on every rerun because Streamlit
executes every tab body whether or not it is open.

The read cache keys on arguments, so three limits are three cache entries,
three round-trips, and three sets of overlapping rows:

| read | before | after |
|---|---|---|
| `get_engine_attribution` | 2,000 · 8,000 · 3,000 = **13,000** | 8,000 |
| `get_trade_events` | 1,000 · 4,000 · 1,500 = **6,500** | 4,000 |
| `get_trade_results` | 40 · 500 · 60 = **600** | 500 |
| `get_trade_attribution` | 40 · 500 · 60 = **600** | 500 |
| **total per round** | **20,700 rows · 12 cache entries** | **13,000 rows · 4 entries** |

**37% fewer rows, and two thirds of the entries gone** — each of which was an
independent thing to refetch on every invalidation and every cold start.

The reads return newest-first, which is what makes a slice equivalent: `rows[:60]`
is the same sixty rows `limit=60` would have returned.

---

## 3 · Five writes were still echoing, and the test could not see them

Round 2 fixed writes echoing their rows and shipped a test to hold it. The test
only recognised `.insert(` and `.upsert(`.

**PostgREST echoes an UPDATE exactly as it echoes an INSERT.** So five
`update_*` methods went on paying for a copy of every row they wrote, through
two subsequent rounds of egress work, with a green suite the whole time. Four of
them discard the response outright — they `return True`:

| write | table | width |
|---|---|---|
| `update_entry_gate_signal` | `entry_gate_signals` | **37 columns** |
| `update_bias_prediction` | `bias_predictions` | 22 columns |
| `update_trade_signal` | `trade_signals` | 24 columns |
| `update_signal_outcome` | `signal_outcomes` | — |

All four now pass `returning='minimal'`. `upsert_auto_trade` is the one genuine
exception and is untouched: it reads `result.data[0]` for the id Postgres
generates.

`test_egress_writes` now knows all three verbs — 34 write methods detected,
up from 29 — with a lookbehind excluding `self.cache.update(...)`, which is an
in-process dict and would otherwise report the read helper `_safe_query` as an
echoing write.

---

## 4 · The number nobody could see

This is the part that matters more than any of the above, and it is why round 3
could ship a real reduction and not know whether it worked.

`tools/egress_meter.py` measures bytes exactly, but it answers *what did this
one rerun cost*, resets every cycle, and is off unless `MIOS_EGRESS=1`. A 1 GB
day poses a different question: **what did today cost, and which table spent
it.**

`db/egress_budget.py` is that instrument. **On by default**, day-scoped,
per-table, with the 100 MB target rendered beside it and a projection of the
full day at the current rate.

### It is always on because it is sampled, not measured

Measuring exactly means `json.dumps(response.data)` on every response — real
CPU on an 8,000-row read inside a 20-second refresh loop, paid 1,100 times a
day to observe a cost problem. Instead: `len(rows)` is free, and one row's
serialised width is sampled **once per (table, op) per day**. Bytes are
`rows × sampled_width`. A test pins that to one `json.dumps` per table per day,
because the moment it becomes per-call the instrument costs what it measures.

### What the figure is, and is not

A **ranking and a before/after ratio** — not an invoice line. Stated plainly in
the panel and the docstring rather than corrected, because a number presented as
exact would get reconciled against the bill and quietly discredit the ranking,
which is the trustworthy part.

* **gzip** — Supabase compresses responses and repetitive JSON compresses hard,
  so real egress is materially **below** this figure
* **row-shape variance** — a table whose blob varies per row is sampled from
  whichever row arrived first
* **an app restart resets it** — so the panel reports how long it has been
  measuring, and refuses to project from under five minutes. A confident
  fiction with a decimal point is the failure mode here.

`over_budget` is decided on the **projection**, not the running total: the total
only crosses 100 MB near the end of a bad day, which is far too late to be told.

---

## 5 · Two leads this round disproved — do not re-investigate them

Recorded because both looked exactly like the answer, and one of them cost real
time.

### `SupabaseDispatchRegistry` is dead code

`db/dispatch_registry.py::rows()` is a `select("*") limit 500` on
`dispatch_history` that **bypasses `CachedDB` entirely** — it goes through
`self.db.client.table(...)`. Worse, `last_dispatched_hash`, `last_dispatched_id`
and `last_dispatch_time` are *properties*, each calling `rows()` afresh, and
`Dispatcher.run()` touches them plus `sent_hashes`, `superseded`, `duplicate`
and `live_message` — around **13 full 500-row fetches per cycle**, which at
1,170 cycles a day models out to almost exactly the missing gigabyte.

**It never runs.** `dashboard_v6` constructs `MemoryRegistry()`, and
`SupabaseDispatchRegistry` is not instantiated anywhere in the app —
the only non-test reference is a docstring in `db/write_batch.py`. The path
costs nothing because nothing walks it.

It is worth fixing before anything ever does construct one (the per-property
refetch is a bug waiting for a caller), but **it is not the bill**, and it
should not be sold as an egress win.

### Round 3's timer removal is intact

Verified, not assumed: `INTRADAY` is gone, only `LIVE` carries a TTL, and every
one of the 61 read methods on `SupabaseDB` is accounted for in `read_cache`'s
`_READS` except `count_rows_older_than` and `oldest_day` — both reachable only
from `retention.preview()`, which sits behind a button.

---

## 6 · What this does and does not claim

**Claimed, and mechanical:** 37% fewer rows on the four heaviest reads, two
thirds fewer cache entries, the widest read in the app no longer carries its
unread JSONB blob, and four writes no longer pay for a copy of themselves.

**Not claimed:** that this reaches 100 MB. Round 3's mistake was converting a
proven round-trip reduction into an assumed byte reduction, and repeating it
would be worse the second time. The reductions here are real and they are
bounded — none of them can explain a full gigabyte on its own.

**What to do next, in order:**

1. Run a full trading day with the new panel open and read the top line. It
   ranks the tables on real data, which no amount of static analysis can.
2. If the top entry is a **write** (`option_chain_data.upsert` is the
   candidate — per-strike, per-cycle, the biggest table in the app), the fix is
   write cadence, not another read.
3. If the projection is still far above 100 MB and no single table explains it,
   the remaining suspects are the ones no in-process instrument can see:
   Supabase's own Database-vs-Storage-vs-Realtime breakdown, and the other
   processes (`ws_worker.py`, `discord_bot.py` at a 15-second poll).
4. **Focus Mode** is the largest reduction still on the table and it is already
   designed: `docs/AUDIT_FOCUS_MODE.md` found 127 of 153 render functions write
   nothing anyone reads, with **19 read methods reachable only from skippable
   panels** — including every heavy analytics read narrowed above. The best
   query is the one that never executes, and that is a bigger win than any
   projection.

---

## 7 · Held by tests

| test | holds |
|---|---|
| `test_a_projection_is_exactly_the_schema_minus_its_dropped_blobs` | a new column cannot become a blank field |
| `test_a_dropped_column_is_one_the_table_really_has` | the drop list cannot go stale |
| `test_every_dropped_column_has_no_reader_among_its_consumers` | the safety argument, checked |
| `test_the_consumer_surface_is_complete` | a new caller must be declared |
| `test_the_two_narrowed_reads_go_through_projection` | a projection map no read consults saves nothing |
| `test_a_read_is_asked_at_exactly_one_limit` | §2, for all six reads |
| `test_every_write_that_discards_its_response_asks_for_minimal` | now across all three verbs |
| `test_the_row_width_is_serialised_once_per_table_per_day` | the ledger stays cheap enough to leave on |
| `test_no_projection_from_too_short_a_window` | it refuses to guess |
| `test_over_budget_is_decided_on_the_projection_not_the_total` | told at 10am, not at 15:30 |
| `test_the_panel_reports_that_it_is_not_measuring_rather_than_zero` | ⚪ could not measure is a report |
| `test_the_app_installs_the_ledger_on_the_raw_client` | before the cache wrapper, or it counts hits as egress |
