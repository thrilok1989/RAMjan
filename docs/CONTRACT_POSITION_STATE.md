# Stage 52's inputs: `open_position` (now wired) and `zone_extremes` (still open)

`mios_v5/engines/stage52_decision.py` consumes two raw inputs that had no
producer. They turned out to be very different problems, so they got different
answers.

| input | status |
|---|---|
| `open_position` | ✅ **wired** — the contract was derivable from evidence and the producer already existed |
| `zone_extremes` | ⛔ **still open** — supplying it would unblock a dead trade-entry path |

---

## 1 · `open_position` — wired, as a one-field rename

### The contract, derived from what `decide()` reads — not from what looks reasonable

Enumerated from the AST of `mios_v5/decision_v2.py`, then verified against the
arithmetic. `decide()` and `_manage()` between them read **exactly three fields**:

| field | type | semantics | evidence |
|---|---|---|---|
| `side` | `"CALL"` \| `"PUT"` | **its presence is the in-a-position flag** — `if pos.get("side"): return _manage(…)` | `decision_v2:143` |
| `entry` | float | a **SPOT / index level**, *not* an option premium | `gain = (spot − entry) if side=="CALL" else (entry − spot)` — `:187` |
| `target` | float | a **SPOT level** — compared directly against spot | `:199` |

**Nothing reads `is_open`, `strike`, `quantity`, `entry_time`, `signal_id` or
`source`.** The earlier speculative field list was mostly wrong, which is exactly
why it should not have been implemented from a guess. `side`'s presence already
*is* `is_open`; adding the flag would do nothing.

### Why `_entry_gate_active`, and why `_entry_signal_open` would have been a bug

`_entry_signal_open` is **per-leg** state — keyed by leg tag — and its `entry` is an
**option premium** — `_leg_levels` draws it as an overlay line on the leg's own price
chart. Feeding that to `decide()` computes `gain = 24,500 − 120` and drives
TRAIL / SCALE_IN off a meaningless number. Concretely wrong, not just
semantically untidy.

`_entry_gate_active` is the app's **position-level** state, and its arithmetic is
already identical to `_manage`'s:

```
vob_minimal.py:8266   (spot_price - _act['entry_spot']) if side == 'CALL'
                      else (_act['entry_spot'] - spot_price)
decision_v2.py:187    (st - entry) if up else (entry - st)
```

So the wiring is a boundary rename of **one** field — `entry_spot` → `entry` —
of the same kind `_mios_market_read` already performs. Not a new interpretation.

### The lifecycle is what makes it safe

A position dict that is never cleared would trap Stage 52 in `_manage` forever —
worse than the flat-forever bug it replaces. `_entry_gate_active`:

* is set only under `if _st_a in ('CALL', 'PUT')` — `vob_minimal.py:8091`;
* is superseded when a new entry arms — `:8155`;
* is **popped on exit** — `:8374` (target/stop) and `:8600` (reverse-exit).

`_open_position()` returns `{}` — never a partial dict — when `side` is absent or
not CALL/PUT, because a dict with `entry` but no `side` puts Stage 52 in a state
it has no branch for.

### Scope: display only

Stage 52's output is read by `terminal.py`, `cockpit_panel.py` and five places in
`dashboard_v6` — all **rendering**. The dispatch path uses `_entry_decision` from
`entry_engine`, a different module, and its transport is `None` unless a human
toggles it on. Wiring this corrects what is *shown* about a live trade; it sends
nothing.

---

## 2 · `zone_extremes` — the finding is worse than "decides as if flat"

### It has a definite meaning, and Stage 52 says so itself

`stage52_decision.py:72` documents it:

> the sequence of lows/highs made while price sat at the zone — the app supplies
> it; **without it the refusal check cannot pass, which is correct**

So of the four candidate meanings, it is unambiguously **the extremes recorded
while price is testing the zone** — lows for a floor, highs for a ceiling.
`floor_ceiling.detect_refusal` needs at least `_MIN_ATTEMPTS` of them and asks
one question: *did the market stop making new extremes?*

### The consequence: Stage 52 can never issue an ENTER

Not "decides as if flat" — **structurally incapable of an entry**, on every cycle
since it was written:

```
detect_refusal([], floor)      → {"proven": False}     (0 < _MIN_ATTEMPTS)
checks["refusal"]              → False
confirmed = all(checks[c] for c in CHECKS)  → False    (CHECKS includes refusal)
decide():  if pf.get("confirmed")           → the ONLY path to ENTER
```

`decision_v2`'s own docstring states the rule this enforces — *"MIOS never enters
on prediction … Permission comes only from `floor_ceiling.prove()` returning
FLOOR/CEILING CONFIRMED"*. With no extremes, permission can never be granted.

The comment calls that "correct", and as fail-safe design it is: the engine
refuses rather than guessing. But it means the entry half of the "final brain"
has never run.

### Why it stays unwired

Producing `zone_extremes` is **not** a rename. It is a new computation — track
the lows/highs made while price sits at the canonical zone, decide what counts as
"at" the zone, how many attempts to retain, and when the sequence resets — and
doing it would take a trade-entry path from *never fires* to *fires*.

That is a strategy change disguised as a wiring fix, and it needs a decision, not
an inference. The questions to settle first:

1. What counts as price being "at" the zone — a tolerance in points, in ATR, or
   the zone's own width?
2. When does the sequence **reset**? On leaving the zone, on a new session, on
   the zone being re-scored?
3. Is one extreme recorded per candle, per touch, or per tick?
4. `_MIN_ATTEMPTS` and `_FLAT_PCT` in `floor_ceiling.py` are calibrated against
   whatever sampling was originally intended — which is it?

Until those are answered, an implementation would produce a plausible-looking
sequence and `prove()` would start confirming entries against it.

---

## Guards

* `test_screen_order.py::test_every_raw_key_an_engine_reads_is_published_or_listed`
  keeps `zone_extremes` on `KNOWN_UNPUBLISHED` with this document as its reason,
  and fails if it becomes published while still listed.
* `test_open_position.py` pins the three-field contract, the `entry_spot` → `entry`
  rename, the CALL/PUT gate, the `{}`-not-partial rule, and asserts the two
  arithmetic sites still agree.
