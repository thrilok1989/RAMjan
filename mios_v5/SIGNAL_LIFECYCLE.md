# MIOS Signal Lifecycle

The Decision Engine says *act or wait*. The **Signal Lifecycle** takes an
`act` decision and turns it into a full, auditable trade life — born, waited on,
entered, and followed to a terminal fate — so nothing is a fire-and-forget alert.

```
WAIT_ENTRY ──confirmed──▶ ENTERED ──target──▶ TARGET_HIT   (win)
    │  │                    │      ──stop────▶ STOP_HIT     (loss)
    │  │                    └──eod while open▶ EXPIRED      (open)
    │  └──flip / zone lost──────────────────▶ CANCELLED    (cancelled)
    └──45m timeout / eod────────────────────▶ EXPIRED      (never_entered)
```

## The 7 steps

1. **Signal Generated** — a qualifying Decision (side CALL/PUT, quality **A/A+**,
   state ARMED/CONFIRMED, not rejected, with a real target **and** stop) is born
   as `SIG-YYYYMMDD-NNN`, status `WAIT_ENTRY`.
2. **Telegram alert** — 🚨 *MIOS SIGNAL* on birth. **A/A+ only** — B/C never alert.
3. **Store in Supabase** — one row in `trade_signals` (setup + `reason` JSON +
   `engine_snapshot` JSON), updated in place as it advances.
4. **Wait patiently** — `WAIT_ENTRY` shows *WAITING FOR ENTRY / do not chase*.
   **Only one signal is alive at a time** — no new signal until this one resolves.
5. **Entry trigger** — the live Entry Gate CONFIRMED for the same side → `ENTERED`;
   a second Telegram ✅ *ENTRY EXECUTED*. (The Entry Gate is the single source of
   truth for "did price confirm", so the lifecycle can't drift from it.)
6. **Trade management** — objective price checks: target → `TARGET_HIT`, stop →
   `STOP_HIT`, session close while open → `EXPIRED (open)`. Every transition is
   stored; a terminal note is pushed to Telegram.
7. **Excel history & analytics** — `📒 Signal Lifecycle — history & analytics`:
   win-rate, avg R:R, avg hold, win-rate **by quality** (is A+ really better than
   A?), full table + CSV download. Misses are kept too (`never_entered`).

## Why never-entered signals are stored

A signal that flashed but never triggered is data: it tells us whether the
WAIT-patiently discipline is skipping losers (good) or missing winners (a
too-tight entry). That's why `CANCELLED` and `EXPIRED/never_entered` are first
-class rows, not silent drops.

## Observational, like everything before it

The lifecycle **mirrors** the live Entry Gate — it uses the gate's CONFIRMED
state as the entry trigger and never places an order. It exists to produce a
clean, gated, fully-logged record so the eventual promotion to a live path is
evidence-based. Design → observe → measure → promote.

## Pieces

- `mios_v5/lifecycle.py` — `advance_lifecycle()` (pure state machine) + `signal_pnl()`.
- `sql/026_trade_signals.sql` — the store (run it in Supabase).
- `db/supabase_client.py` — `insert_trade_signal` / `update_trade_signal` /
  `get_active_trade_signal` / `get_trade_signals` / `count_trade_signals_today`.
- `vob_minimal.py` — `manage_signal_lifecycle()` (birth/advance + Telegram),
  `render_signal_lifecycle()` (live panel), `render_signal_history()` (Excel).
- `mios_v5/tests/test_lifecycle.py` — the state-machine tests.
