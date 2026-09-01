# Have the duplicate copies drifted? — the canonical-copy decision

*Step 1 of the agreed cleanup sequence. Analysis only; no code moved.*

```bash
python tools/divergence.py           # summary
python tools/divergence.py --full    # + unified diffs
```

## The question this answers

`tools/dupscan.py` normalises identifiers **and literals** before hashing, so
it answers *"did these start as the same function"*. The duplication survey was
explicit that this is not enough:

> A hash match only says the two *started* identical. If a module copy is ever
> promoted to the owner, it needs a diff of the two bodies read line by line
> first.

This is that diff, done mechanically over every clone pair. It compares the
real bodies — docstrings and type annotations removed, then exact code, then
**every literal in order**, because a copy that differs only in a threshold
looks identical in review and behaves differently in production.

## Result

| | |
|---|---|
| **Identical code** | **98 pairs** |
| Different constants | **1** — an error-message string (see below) |
| **Different logic** | **0** |

**No indicator has drifted.** Not one threshold, not one comparison, not one
branch. The maintenance trap the survey identified is real — the wrong copy is
the obvious one to edit — but **nobody has fallen into it yet**.

That makes step 1 far cheaper than it looked: for all 98 pairs there is no
behavioural question to settle. Keep the copy that runs, remove the others.

### The one flagged pair is not a duplicate

```
mios_v5/trading_context.py:344   get()
mios_v5/liquidity_context.py:185 get()
    'no such field in this context' → 'no such field in this liquidity context'
```

Two deliberately separate bridges sharing an accessor idiom, differing only in
the message they print when a field is missing. **Leave both.** Merging them
would give one behaviour two owners, which is the opposite of the goal.

### Two false alarms the tool had to be taught

Both were in the category that must never cry wolf, so they are recorded:

1. **Type annotations.** `_slope(s: List[float])` in `memory.py` vs
   `_slope(s: Sequence[float])` in `ltp_behaviour.py` reported as *different
   logic*. The bodies are identical. The tool now strips annotations.
2. **Docstrings counted as literals.** A reworded docstring reported as
   *different numbers*. Constants are now read off the docstring-stripped body.

An alarm that fires on prose gets ignored, and this is the alarm that would
have caught a drifted threshold.

---

## The canonical copy, per family

| Family | Copies | Canonical | Why |
|---|---|---|---|
| Reversal scoring · order blocks · candle patterns · VIDYA · dealer GEX · max pain · HVP · support-respect · entry rules | `vob_minimal.py` (**runs**) · `vob_indicators.py` · `indicators/*` · `analysis/gex_analyzer.py` | **the inline copy in `vob_minimal.py`** | it is the one the app executes and the one debugged in production |
| Sector rotation · option LTP · Yahoo intraday | `vob_minimal.py` (**runs**) · `vob_data.py` | **the inline copy** | same |
| Market depth — 6 functions incl. the 152- and 80-statement display pair | `seller_features.py` · `seller_perspective.py` | **neither** | both files are unreachable; this is archive material, not a merge |
| `calculate_poc` · swings · pivots · `calculate_pcr_gex_confluence` · `validate_credentials` | `vob_indicators.py` · `indicators/*` · `analysis/*` · `api/dhan_api.py` | **none today** | no reachable copy exists — see the caveat below |
| `get()` accessor | `trading_context.py` · `liquidity_context.py` | **both** | separate bridges, not duplicates |

### Split by reachability

Of 40 identical pairs in the report:

* **13 pairs (506 statements) have *both* copies in unreachable files.** Nothing
  to decide — they disappear when the dead files are archived.
* **27 pairs involve at least one live copy.** For every one of these the live
  copy is `vob_minimal.py`'s inline version, and the duplicate is dead.

So **archiving the unreachable files resolves the entire duplication problem**
without editing a single line the app runs. Step 1 and step 4 of the agreed
sequence turn out to be the same action.

---

## ⚠️ One thing this does not license

`api/dhan_api.py` is in the "no reachable copy" row, and the survey separately
recommends making it the **owner** of Dhan access. Those two facts together are
a trap:

> `validate_credentials()` being identical in `api/dhan_api.py` and
> `vob_data.py` says nothing about whether `api/dhan_api.py`'s **other**
> functions match what `vob_minimal.py` does inline.

The Dhan-client consolidation is still a **behaviour change**, still medium
risk, and still needs the function-by-function comparison this report only did
for the pairs the clone detector found. Identical duplicates are evidence about
those functions and nothing else.

---

## What this changes about the plan

The agreed sequence stands. One item gets cheaper and one gets a firmer basis:

| Step | Status after this report |
|---|---|
| 1 · Fix `vob_minimal` duplication | **no code change needed** — the divergence is zero, so this is resolved by archiving, not by editing |
| 2 · Centralise theme/colours | unchanged — still a real code change |
| 3 · Dead-file report + manual verification | unchanged, and now the *only* thing gating step 1 |
| 4 · Archive | unchanged |
| 5 · Test | unchanged |
| 6 · Delete | unchanged |
| 7 · Caching | unchanged — still measure first |

The one substantive update: **step 1 no longer needs to precede step 3.** There
is nothing to fix in `vob_minimal.py` before archiving, because the copy it
runs is already the correct one. The safest order is now 3 → 4 → 5 → 6, with
step 2 in parallel because it touches nothing the archive touches.
