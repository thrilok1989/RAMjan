# Egress round 3 — the 1 GB day

**Reported:** ~1 GB of Supabase egress in one trading day. **Target: 50 MB.**

Rounds 1 and 2 fixed writes echoing their rows and a 15,000-row day scan, and
put a Streamlit cache in front of every read. The bill did not move much. This
round says why, and it is not the thing the earlier rounds were looking at.

---

## 1 · It was not the queries. It was the timer.

`db/read_cache.py` had three lifetimes. Fourteen reads sat in `INTRADAY`, a
**five-minute TTL**, on the reasoning that they were "tables that grow during
the session". A five-minute TTL over a 6.5-hour trading day is **78 refetches
of each, every day, whether or not a single row changed.**

The two worst:

| read | rows | entries | refetches/day |
|---|---|---|---|
| `get_session_log` | 8,000 **and** 4,000 | 2 (different limits) | 156 |
| `get_day_type_log` | 1,000 | 1 | 78 |

`get_session_log` alone is on the order of **187 MB a day**. Across all
fourteen the treadmill accounts for the bulk of the gigabyte.

Streamlit makes this worse than it looks: every `st.tabs()` and
`st.expander()` body runs on **every** rerun, so all fourteen reads were asked
on every cycle regardless of what was open. The cache absorbed 19 of every 20
of those calls — and then let the twentieth through, forever.

### Why the timer was never needed

Every read in this app was matched against every write, by table:

```
57 read methods · 57 of them have a writer in this same file
 0 tables filled by anything outside this process
```

`ws_worker.py` writes `dhan_ticks` and `dhan_sweeps`, and nothing here reads
either. So a timer was being used to discover changes **the app had made
itself and already knew about**.

---

## 2 · The fix: exact invalidation, not periodic refetch

`INTRADAY` is gone. Two lifetimes remain — `STATIC` (until a write or a reset)
and `LIVE` (20s, for the five decision-critical "right now" reads).

Three pieces make that safe:

**`_INVALIDATES` is now complete.** Every writer maps to every read of its
table — 47 writers, up from 32. It is not trusted as written: a test re-derives
it from `db/supabase_client.py` by matching tables, and fails on any pair that
is missing. With the timer gone, a forgotten writer no longer means *refreshed
a bit later*; it means **stale until restart**, so the map has to be provably
complete rather than carefully maintained.

**Invalidation is per entry.** ⚠️ This is the part an earlier attempt got
wrong and had to revert — see `AUDIT_EGRESS_2.md` §7. `invalidate()` used to
call `fetch.clear()`, which drops the *whole bucket*, so moving reads into
`STATIC` would have made every `insert_session_log` dump
`get_engine_attribution`'s 8,000 rows along with it. A module-level record of
live cache keys (`_LIVE_KEYS`) lets a write clear exactly its own entries.

It is module-level, not `session_state`, because `st.cache_data` is global to
the server process: a per-session record would leave another tab's entry
uncleared, which is the stale read this file exists to prevent.

**`REFRESH_FLOOR` bounds the opposite failure.** Three tables are written on
every 20-second cycle — `leg_flow_snapshots`, `nifty_spot_data`,
`candles_data`. Clearing on each write would re-read an all-day, growing table
**1,125 times a day**, which is worse than the timer ever was. The floor caps
that at 300s.

The floor deliberately does **not** bind on the first write after a fetch, so a
rare write — a session log row, a graded trade — is visible on the very next
read. That is a promise the five-minute timer could not make either.

| | before | after |
|---|---|---|
| table nobody wrote | 78 fetches/day | **1 per app lifetime** |
| table written once | 78 fetches/day | **2** (initial + the write) |
| table written every cycle | 78 fetches/day | ≤78, capped by the floor |

---

## 3 · Two full-table scans of the largest table

`candles_data` is the biggest table in the app, and two reads scanned all of
it — both reachable on every fresh session, via `compute_prev_day_value`:

```python
get_available_candle_series()     # select(symbol,exchange,timeframe)
                                  #   no filter, no limit — EVERY candle ever stored
get_candle_trading_days(s, e, tf) # select(trading_day)
                                  #   every row of that series
```

Both existed to derive a handful of distinct values, and the caller then threw
all of them away except **one date** — the previous trading day.

Replaced by `latest_candle_day_before(symbol, exchange, day)`: filtered in the
database, ordered, `.limit(1)`. Two unbounded scans become **one row**. It
returns the timeframe alongside the day, so the caller still does not have to
guess a timeframe the sidebar owns.

The general methods are bounded rather than deleted, and `get_candles` now
orders **newest-first** before its limit — with ascending order a `.limit()`
would drop the newest bars, and a chart missing its live edge is worse than one
missing its history.

---

## 4 · Two panels, one question, two round-trips

The cache keys on arguments, so `get_session_log(4000)` and
`get_session_log(8000)` were two entries and two fetches of overlapping rows —
and both panels ran on every rerun whether or not their tab was open. Same for
`get_trade_signals(300)` and `(100)`.

`SESSION_LOG_LIMIT` and `TRADE_SIGNAL_LIMIT` in `dashboard_v6.py` are now the
single limit per table. A panel wanting fewer rows slices the shared result; it
must not ask a different question.

---

## 5 · What was checked and found innocent

Worth recording, so round 4 does not re-investigate them:

* **`ws_worker.py`** — writes only, already `returning="minimal"`, and neither
  table it writes is read here.
* **Writes echoing rows** — round 2's fix is intact; the test still holds it.
* **Cache key churn** — 1.10 calls per distinct key. The keys were stable; the
  cache was not failing to match.
* **`db/retention.py`** — its full-table preview is behind a button.
* **33 read methods that nothing calls**, including every `*_history` table
  (`pcr_history`, `gex_history`, `bid_ask_history`, `max_pain_history`,
  `volume_delta_history`). Dead, so not the bill. Candidates for deletion in a
  separate pass — deleting them is not an egress fix and should not be sold as
  one.

---

## 6 · What this does not prove

The same caveat `AUDIT_EGRESS_2.md` carried, and it still applies:

**These are counted round-trips, not measured bytes.** The mechanism is
certain — 78 refetches a day became 1 — but converting that to a number on the
invoice needs `MIOS_EGRESS=1` running against the real database. The reduction
is large and structural; the exact figure is a measurement, not an estimate.

Two things this cannot reach at all, both needing Supabase's own breakdown:

* egress that is not Database — Storage, Realtime, Auth, Edge Functions
* traffic from any process that is not this one

**If the bill is still high after this, that breakdown is the next place to
look, not another query.** A round 4 that starts by narrowing more SELECTs
would be guessing again.

---

## 7 · Held by tests

| test | holds |
|---|---|
| `test_nothing_is_re_read_on_a_timer_any_more` | only LIVE may carry a TTL |
| `test_every_writer_marks_every_read_of_its_table` | `_INVALIDATES` re-derived from the client |
| `test_invalidating_one_read_leaves_its_neighbours_alone` | the §2 regression that was reverted |
| `test_one_limit_of_a_read_does_not_evict_another` | per-entry, not per-method |
| `test_a_per_cycle_writer_does_not_refetch_on_every_cycle` | the floor |
| `test_the_floor_lets_go_once_the_window_passes` | it is a floor, not a freeze |
| `test_a_write_is_visible_on_the_very_next_read` | correctness of the whole scheme |
| `test_an_unwritten_table_is_fetched_once_for_the_whole_day` | the headline |
| `test_no_read_of_the_candle_table_is_unbounded` | §3 |
| `test_every_read_is_bounded_by_a_limit_or_a_named_filter` | new unbounded reads |
