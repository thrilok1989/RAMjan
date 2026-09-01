# Stage 1 — Focus Mode dependency audit

**No behaviour change.** This decides what Stages 2–4 are allowed to skip.

> ## The rule
>
> **Focus Mode may suppress presentation. It may not suppress computation
> required by MIOS state, the decision stages, or Telegram alerts.**

Everything below exists to make that rule checkable rather than remembered.

---

## The result

`tools/focus_audit.py`, run against `main`:

```
CRITICAL 7  ·  PRODUCER 19  ·  DRAW-ONLY 127
```

**127 of 153 rendering functions write nothing anyone else reads.** They can be
skipped outright. Only **four real panels** need Stage 4's compute/draw split —
the other three CRITICALs are the render entry points themselves.

---

## 1 · CRITICAL — must keep running

| Panel | Writes | Who breaks without it |
|---|---|---|
| `_strike_validation` | `_trading_context`, `_premium_structures` | ⚠️ **Stage 72 → 73 → 72.9 → Telegram.** The entire alert chain. |
| `_opportunity` | `_premium_energy` | the header's ⚡ chip |
| `_sr_intelligence` | `_sr_levels` | the header's 🛡/🧱 chips **and** the simple entry system |
| `_terminal_chart` | `_leg_profiles` | the charts themselves |
| `_render_main_analyzer` · `_trading_screen` · `render_dashboard_v6` | (entry points) | everything |

This is the finding that shapes the whole feature. Three of the header's own
inputs are produced *inside* `dashboard_v6`'s render path, and one of them is
what the alert chain reads. A Focus Mode implemented as "don't call the V6
dashboard" would take Telegram down with nothing on screen to say so — the same
failure this repo has already had three times.

**Stage 4 is therefore mandatory, and starts with `_strike_validation`.**

---

## 2 · DRAW-ONLY — safe to skip, and where the egress is

127 functions. Fifteen of them issue Supabase reads, and **19 distinct read
methods are reachable *only* from skippable panels**:

| Panel | reads |
|---|---|
| `render_dashboard` | 7 |
| `_learning` | 7 |
| `_daily_summary` | 4 |
| `render_story_panel` · `render_slim_trade_card` · `_session_validation` · `_replay` | 2 each |
| six more | 1 each |

Including the heaviest queries in the app:

```
get_engine_attribution        8,000 rows
get_session_log               2,000
get_resolved_entry_gate_signals 1,000
get_bias_predictions          1,000
get_layer_outcomes              500
```

**The best query is the one that never executes.** This is a larger egress
reduction than any cache tuning, and it also answers the 1.10-calls-per-key
finding from PR #42 by removing the calls rather than trying to cache them.

---

## 3 · PRODUCER — keep running, no header dependency

19 functions write keys other code reads, but nothing in the protected set.
They must keep running for correctness, though none is on the alert path:
`render_market_picture`, `render_full_market_read`, `analyze_option_chain`,
`compute_per_candle_pxoi`, `render_greek_absorption`, and others.

They are Stage 4 candidates only if Stage 5 shows they cost meaningful time.

---

## 4 · The protected set

The audit's `PROTECTED` list is the machine-readable form of the rule. Anything
writing one of these is CRITICAL whatever else it does:

```
header    _cached_option_data · _mios_state · _gap_today · _reaction_sr
          _premium_energy · _chrome_last
chart     _last_df · _atm_leg_dfs · _money_flow_data · _leg_profiles
alerts    _trading_context · _entry_decision · _lifecycle_decision
          _dispatch_decision · _mios_transport
simple    _sr_levels · _premium_structures · _simple_entry_on
```

Adding a key here is how a future reading gets protected without anyone having
to remember this document.

---

## 5 · How the call graph is built, and its bias

Functions are matched **by name**, because this repo calls across modules by
bare name after a local import (`from .foo import bar`, then `bar(...)`). Two
functions sharing a name are merged, which can only make a panel look like it
writes *more* than it does.

That bias is deliberate. A false PRODUCER costs a panel that keeps running; a
false DRAW-ONLY costs the Telegram chain. The audit errs toward keeping things
alive.

**What it cannot see:** a write performed through `globals()`, `setattr`, or a
name built at runtime. None appear on the render path today, but a Stage 3b PR
should still confirm the header and the alert chain still work *in the running
app*, not only in the audit.

---

## 6 · What Stages 2–4 may now do

| Stage | Allowed to skip | Must keep |
|---|---|---|
| **2** CSS hide | nothing — presentation only | everything |
| **3a** minimal chart | profile bands, VOB/leg zones, annotations | candles, CVD, S/R lines, **and `_panel_profile` until proven draw-only** |
| **3b** skip panels | the 127 DRAW-ONLY | the 7 CRITICAL, the 19 PRODUCER |
| **4** untangle | `_strike_validation`'s draw half | its compute half |

### Stage 3a's open question

`_panel_profile` is built inside `_terminal_chart`, which is CRITICAL because it
writes `_leg_profiles`. Dropping the *bands* from the chart does **not** by
itself prove the *profile* can stop being built — Stage 71.86's shape and the
liquidity bars consume the same object. Stage 3a keeps building it and skips
only the drawing, until a follow-up proves otherwise.

---

## 7 · Acceptance test for Stage 4

Not a smoke test. The chain, explicitly, with Focus Mode ON:

```
Focus ON → _trading_context exists
         → Stage 72 produced an EntryDecision
         → Stage 73 produced a lifecycle decision
         → Stage 72.9 produced a dispatch decision
         → the transport is still reachable
```

Plus: every key in §4's protected set is present after a Focus-ON render. That
assertion is what makes the rule at the top of this document enforceable rather
than aspirational.
