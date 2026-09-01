# MIOS V5 Migration Audit — were the original indicators changed?

**Question:** did MIOS V5 replace, rewrite, simplify or modify the original
app's indicators, or is it using the exact same ones?

**Method:** not name-matching. The V5 boundary commit is `468f152`
(*"MIOS V5 Phase A: engine contract, orchestrator, Stage 0 health engine,
spec"*, 2026-07-21). Every indicator was diffed **across that boundary** —
pre-V5 source versus current source — at file and function level.

---

## Answer

> **✅ Every original indicator is byte-identical to its pre-V5 version.**
> V5 changed no formula, no preprocessing, no threshold, and no cache.
> It reads the original caches directly and computes nothing itself.

The strongest single piece of evidence:

```
$ grep -rn "cumsum|.sum()|clip(0|rolling(|ewm(|np.sign" mios_v5/ --include=*.py
  (excluding tests)
→ no matches
```

**There is no indicator arithmetic anywhere in `mios_v5`.** Not modified —
*absent*. V5 cannot have changed a formula it does not contain.

`mios_v5/engines/_adapters.py:1-9` states the design intent, and the code
matches it:

> *"Phase-B engines are thin adapters: the host app already computes the heavy
> analytics each cycle and stashes them in session_state … so no analytic is
> recomputed and there is zero import coupling to vob_minimal."*

---

## File-level proof

```
$ git diff --stat 468f152 HEAD -- indicators/
 indicators/order_flow.py | 254 +++++++++++++++++++++++++++++++++++++++
```

Only one file in `indicators/` differs from pre-V5, and it is **new, added in
this session** — see the caveat at the end. The two original indicator modules:

```
$ git diff --quiet 468f152 HEAD -- indicators/money_flow_profile.py  → IDENTICAL
$ git diff --quiet 468f152 HEAD -- indicators/volume_delta.py        → IDENTICAL
```

Their last real edits predate V5 by weeks:

| File | Last changed | V5 began |
|---|---|---|
| `indicators/money_flow_profile.py` | 2026-07-15 (`bb10a80`) | 2026-07-21 |
| `indicators/volume_delta.py` | 2026-06-23 (`d6d159f`) | 2026-07-21 |

## Function-level proof

Each function body hashed pre-V5 and now:

| Function | Pre-V5 hash | Now | Verdict |
|---|---|---|---|
| `analyze_vob_volume` | `2e2b7d310c6a` | same | ✅ identical |
| `compute_vpfr` | `0716d28f6656` | same | ✅ identical |
| `_ltf_delta_volume` | `a326e884c74a` | same | ✅ identical |
| `_compute_leg_delta_volume` | `7ffb0197587d` | same | ✅ identical |
| `_mfp_poc_bias` | `25ffc7afa047` | same | ✅ identical |

---

## Per-indicator findings

### Money Flow Profile — ✅ Original code reused

- **Original:** `indicators/money_flow_profile.py::calculate_money_flow_profile()` L10
- **V5 location:** *still using the original function.* V5 reads the result via
  `mios_v5/runner.py:86` → `raw["money_flow"] = session_state.get("_money_flow_data")`
- **Formula changed:** No — file byte-identical across the V5 boundary
- **Preprocessing changed:** No. `num_rows`, `source='Money Flow'` and
  `sentiment_method` defaults untouched
- **Output changed:** No — same function, same inputs, same output by construction
- **Reads the original cache:** **YES**, `_money_flow_data` directly

### Candle Delta Volume — ✅ Original code reused

- **Original:** `indicators/volume_delta.py::calculate_volume_delta()`; per-leg
  variants `_ltf_delta_volume()` (`vob_minimal.py:5811`) and
  `_compute_leg_delta_volume()` (`vob_minimal.py:5870`)
- **V5 location:** still original. Read via `raw["volume_delta"]`
- **Formula / preprocessing / output changed:** No, all three
- **Reads the original cache:** **YES**, `_volume_delta_data`

### CVD — 🟡 Original code wrapped *(changed this session, not by V5)*

- **Original:** six inline copies in `vob_minimal.py` (L19999, L20561, L20852,
  L21066, L22956, L30307)
- **V5 location:** V5 never had its own CVD. It saw CVD only folded inside
  `volume_delta` or via the leg-bias `CVD` column
- **Formula changed by V5:** **No.** V5 never touched it
- **Formula changed by this session's refactor (#269):** the arithmetic is
  **identical** — extracted, not rewritten — and
  `test_the_primitive_reproduces_every_original_site` transcribes all six
  originals verbatim and asserts bit-exact equality against the same frame
- **Reads the original cache:** N/A — CVD was never cached

### CSV / CBV — ✅ Unchanged (and still display-only)

- **Original:** `vob_minimal.py:30306-30307`, locals in the chart block
- **V5 location:** none. V5 has no CSV/CBV reading
- **Changed:** No. Still computed inline, still stored nowhere
- **Reads the original cache:** N/A — there is no cache

### VOB — ✅ Original code reused

- **Original:** `vob_minimal.py::analyze_vob_volume()` L12934
- **V5 location:** still original. Read from `_atm_leg_vob_volume`
- **Formula changed:** No — function body hash identical
- **Reads the original cache:** **YES**, and the reference count is unchanged
  at 14 pre-V5 and 14 now

### VPFR / Volume Profile — ✅ Original code reused

- **Original:** `vob_minimal.py::compute_vpfr()` L1525
- **V5 location:** still original; `_atm_pm1_vpfr` unchanged (8 refs pre-V5,
  8 now)
- **Formula changed:** No — hash identical
- **Note:** `mios_v5` reads `_atm_pm1_vpfr` **zero** times. VPFR reaches V5 only
  indirectly, through the leg-bias table's `MFP` columns

### Buy Volume / Sell Volume / Delta Volume — ✅ Original code reused

- **Original:** `_ltf_delta_volume()` L5811 → `buy_total`, `sell_total`,
  `neutral_total`, `delta`, `delta_pct`
- **Formula changed:** No — hash identical
- **Reads the original cache:** **YES**, `_atm_leg_ltf_delta`

### OI / ΔOI — ✅ Original code reused

- **Original:** `analyze_option_chain()` → `total_ce_change` / `total_pe_change`
- **V5 location:** read via `raw["option_data"]` (the whole chain object)
- **Formula changed:** No. V5 consumes the assembled chain dict; it does not
  recompute OI or its delta

---

## Final table

| Indicator | Original reused | Formula identical | Cache reused | Output identical | Status |
|---|---|---|---|---|---|
| Money Flow | ✅ | ✅ | ✅ `_money_flow_data` | ✅ | ✅ Original code reused |
| Candle Delta | ✅ | ✅ | ✅ `_volume_delta_data` | ✅ | ✅ Original code reused |
| CVD | ✅ | ✅ | n/a — never cached | ✅ proven bit-exact | 🟡 Original code wrapped *(this session)* |
| CSV | ✅ | ✅ | n/a — never stored | ✅ | ✅ Unchanged (display only) |
| CBV | ✅ | ✅ | n/a — never stored | ✅ | ✅ Unchanged (display only) |
| VOB | ✅ | ✅ | ✅ `_atm_leg_vob_volume` | ✅ | ✅ Original code reused |
| VPFR | ✅ | ✅ | ✅ `_atm_pm1_vpfr` | ✅ | ✅ Original code reused |
| Volume Profile | ✅ | ✅ | ✅ | ✅ | ✅ Original code reused |
| Buy / Sell / Delta Volume | ✅ | ✅ | ✅ `_atm_leg_ltf_delta` | ✅ | ✅ Original code reused |
| OI / ΔOI | ✅ | ✅ | ✅ `_cached_option_data` | ✅ | ✅ Original code reused |

**Nothing is 🟠 Modified. Nothing is 🔴 Completely rewritten.**

---

## Did V5 replace any indicator?

**No.** Not one. V5 added an *interpretation* layer on top:

```
Original indicator  →  session_state cache  →  runner.raw  →  V5 engine  →  bias/confidence
      (unchanged)         (unchanged)          (new)         (new)            (new)
```

Everything left of `runner.raw` is the original app, untouched.

---

## The one caveat, stated plainly

**`indicators/order_flow.py` is new, and I wrote it in this session** — it is
not part of the original app and not part of V5's original migration. It
extracts the CVD formula that was inlined six times in `vob_minimal.py`.

Two things make it a **🟡 wrap** rather than a 🟠 modification:

1. The arithmetic is a verbatim transcription, and
   `mios_v5/tests/test_order_flow_source.py::test_the_primitive_reproduces_every_original_site`
   runs the six originals against the new implementation on the same frame and
   asserts bit-exact equality — including the datetime-indexed cumulative
   series.
2. It lives in `indicators/`, the computation layer, not in `mios_v5`. The V5/V6
   boundary is intact.

If you want zero tolerance for *any* post-migration change to indicator code,
this is the one item to review — PR #269. It is the only edit to indicator
arithmetic since the original app, and it was made to remove five duplicate
copies, not to change a number.

## Reproduce this audit

```bash
V5=468f152
git diff --stat $V5 HEAD -- indicators/
git diff --quiet $V5 HEAD -- indicators/money_flow_profile.py && echo IDENTICAL
grep -rn "cumsum\|\.sum()\|clip(0\|rolling(\|ewm(" mios_v5/ --include=*.py | grep -v tests
PYTHONPATH=. python mios_v5/tests/test_order_flow_source.py
```
