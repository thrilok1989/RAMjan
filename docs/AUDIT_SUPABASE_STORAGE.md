# Storage audit — and the background cleanup job

*Roadmap items 6 and 8. Taken at `b84f9ec`.*

---

## The headline, first

**Supabase Storage is not used by this application. At all.**

No bucket, no upload, no `.storage` call anywhere in the codebase. The only CSV
it produces goes to an in-memory buffer for `st.download_button` and never
leaves the browser; `generate_analysis_pdf.py` writes to local disk. A test
asserts this against the source, so the claim cannot quietly go stale the day
somebody adds an upload.

Supabase "Storage" (buckets and files) and Supabase database storage are two
different products sharing one word. **If the dashboard figure keeps climbing,
it is the database** — and every finding below is about that.

Anything in a bucket right now was uploaded by a human through the dashboard.
The query to check is at the bottom of `sql/035_storage_audit.sql`.

---

## Item 8 · The storage audit

Delivered as **Postgres functions**, not a script, because PostgREST cannot run
arbitrary SQL — a function is the only way the app can ask a question the schema
does not answer as a table. `docs/AUDIT_QUERY_INDEXES.md` §9 recorded the
absence of RPCs as a gap; this is the first thing to close it.

| Function | Answers |
|---|---|
| `storage_report()` | every table's size, index size, row estimate, vacuum state — biggest first |
| `unused_indexes()` | non-constraint indexes with zero scans |
| `retention_pressure()` | size **joined to** its retention policy |

`retention_pressure()` is the one to read first. Size alone does not tell you
what to do; it sorts every table into three verdicts:

* **`no policy — grows forever`** — needs a decision
* **`policy exists, NOT enabled`** — needs one line of SQL
* **`policed`** — handled

`db/storage_audit.py` reads all three and the sidebar's **🧮 Storage** panel
renders them. A missing migration reads as empty, never as a crash.

### Two things that mislead people

**`live_rows` is an estimate**, from `pg_stat_user_tables`, not a `count(*)`.
Free and approximate, and on a table nobody has `ANALYZE`d it can be badly
wrong — which is why `dead_rows` sits next to it in the same row.

**A `DELETE` does not shrink the file.** It marks rows dead; autovacuum makes
the space reusable, but the file stays as large as it ever was. So the first
purge of a two-year-old table can remove millions of rows and move the
dashboard number by nothing. That is not the purge failing. `VACUUM` reclaims
for reuse; `VACUUM FULL` gives space back to the operating system and takes an
`ACCESS EXCLUSIVE` lock, so it is an out-of-hours job.

### Unused indexes

`unused_indexes()` excludes primary keys and unique constraints — they enforce
correctness whether or not a query reads them, and **every upsert in this
client depends on one**. Dropping a unique index because "nothing scans it"
turns every `upsert` into an `insert`, silently.

Read it only after a full trading day: `idx_scan` counts since the last stats
reset.

---

## Item 6 · Background cleanup

`db/retention.py` runs in-process, on a Streamlit rerun. Two problems with that
as the permanent answer:

1. **It only runs while somebody has the dashboard open.** A maintenance job
   that depends on a human having a browser tab open is not scheduled, it is
   coincidental.
2. **It deletes over HTTP.** Every window is a PostgREST round-trip, which is
   the wrong shape of work for a job whose entire purpose is to make the
   database smaller.

`sql/034_retention_cron.sql` moves it into the database. A purge becomes a
`DELETE` next to the rows, and `pg_cron` runs it whether or not anyone is
watching.

### One owner for the policy numbers ⚠️ BINDING

The windows now exist in two places — `db/retention.py`'s `POLICIES` and the
`retention_policy` table. Two representations of one fact drift within a month
unless something checks.

So the SQL seed is **generated** from the Python policies, and a test parses the
migration's `VALUES` list and asserts it matches `POLICIES` exactly — table for
table, window for window, source for source. Change a window in
`db/retention.py` and regenerate; hand-editing the seed fails the build.

### Installing it deletes nothing

Same two gates as the Python side, restated in SQL:

* `retention_policy.enabled` is **`FALSE` for every row on install**, and
  `retention_purge()` skips every disabled row.
* **The cron job is not scheduled by the migration.** Every `cron.schedule` and
  `CREATE EXTENSION` line is commented out. A test walks the file and asserts no
  uncommented line contains either.

`ON CONFLICT` updates the window but never the `enabled` flag, so re-running the
migration cannot switch a purge on — or off — behind you.

### The purge is safe to interrupt

Chunked by `ctid`, not one statement per table. A single `DELETE` across two
years of `option_chain_data` holds one long transaction and bloats WAL; chunked,
each statement is short and an interrupted run has still committed everything it
removed. There is a per-run row cap, and the next run resumes.

A policy naming a table that does not exist is **reported, not raised** — one
missing table must not abort the other forty-two. Same for a missing column.
Identifiers go through `format(%I)` and `quote_ident`, never string
concatenation.

### Exactly one purger

If you schedule cron, leave `ENABLED = False` in `db/retention.py`. The app-side
preview keeps working and only cron deletes. **Two schedulers purging the same
tables is not twice as safe** — it is two processes racing on the same rows,
and the audit log will show it as one run doing nothing.

The runbook is in the migration: preview → enable a few policies → dry run →
one manual purge you watch → schedule → turn the in-process pass off.

---

## What this did not do

* **Nothing was measured.** These are structural findings; no row counts, no
  table sizes, no `EXPLAIN`. `retention_pressure()` exists precisely because
  those numbers need to come from your database, not from me.
* **Nothing was deleted or scheduled.** Both migrations install inert.
* **`pg_cron` was not enabled.** It is a dashboard toggle
  (Database → Extensions) and enabling an extension on someone's production
  database is not a thing to do on their behalf.
* **No `VACUUM` was run**, and after the first real purge one will be needed
  before the dashboard figure moves.
