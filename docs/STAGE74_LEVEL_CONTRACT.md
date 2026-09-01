# Stage 74 — the clustered level contract

*`LEVEL_SCHEMA_VERSION = "74.1"` · `mios_v5/liquidity.py` · ⚠️ **FROZEN***

Seven stages are queued to consume clustered levels:

```
S/R Engine → Liquidity → Options Sentiment → Closing Auction
           → LTP Behaviour → Smart Money → Decision Fusion
```

If each reads a bare dict, improving the clustering breaks all seven. If each
reads `Level`, the internals can change freely as long as these fields keep
their meaning. **That is the entire reason this document exists** — it is frozen
*before* injection starts, not after.

---

## The object

```python
from mios_v5.liquidity import Level, LEVEL_SCHEMA_VERSION
```

| Field | Type | Meaning |
|---|---|---|
| `price` | `float` | the clustered level — the mean of its members |
| `side` | `str` | `support` · `resistance` · `at_spot` |
| `rank` | `str` | `Major` · `Minor` · `Dynamic` |
| **`confidence`** | `int \| UNKNOWN` | **0–100 — gate on this** |
| `witness_count` | `int` | how many levels fell in the cluster |
| `engine_sources` | `tuple[str, …]` | the **distinct** owners behind it |
| `kinds` | `tuple[str, …]` | `POC` · `VAH` · `HVN` · `Gamma Flip` · … |
| `dispersion` | `float` | widest minus narrowest, in price |
| `dispersion_pct` | `float` | the same, as a share of the tolerance |
| `freshness` | `UNKNOWN` | no producer timestamps a level yet |
| `low` · `high` | `float` | the cluster's extremes |
| `reporting` · `of` | `int` | confidence components that reported |
| `why` | `str` | how the confidence was reached |
| `schema` | `str` | the version this level was written against |
| `.diversity` | `int` | property — `len(engine_sources)` |

`to_dict()` gives the same shape as JSON, so a stored level replays identically.

### ⚠️ Gate on `confidence`, not `witness_count`

The count is **one input** to the confidence. Using it directly throws away the
dispersion and freshness that qualify it — and `witness_count` counts *levels*,
not opinions. Three HVN bins from one profile is three witnesses and **one**
engine.

---

## Confidence

```
confidence = diversity_ceiling × quality
```

**Diversity is a ceiling, not a term in an average.** Two engines cannot reach
60 however perfectly they agree. Averaging a perfect dispersion score against
them would push it to 62 and lose the point.

### The ceiling, on the supplied calibration

| Distinct engines | Confidence |
|---|---|
| 1 | 20 |
| 2 | **45** |
| 5 | **82** |
| 8 | **97** |
| 12+ | 98 |

Linear between anchors, flat outside. The bold rows are the supplied
calibration and land exactly. `1 → 20` is this module's addition and the
important one: a single source naming a price is a number, not a level.

Saturating on purpose — the jump from two engines to five is worth far more
than five to eight, because the second engine may be correlated with the first
while the eighth is almost certainly measuring something else.

### The quality modifiers

| Component | Weight | Producer |
|---|---|---|
| `dispersion` | 1.5 | ✅ always |
| `engine_confidence` | 1.0 | ❌ **none today** |
| `freshness` | 0.5 | ❌ **none today** |

Unknown components **leave the denominator** — Stage 72's rule. `reporting/of`
travels with the score, so a barely-measured cluster is distinguishable from a
weak one. Today every level reports **2 of 4**.

`dispersion` floors at **0.6**, not 0: engines that agreed loosely still agreed,
and a level losing everything for imprecision would rank below one nobody
corroborated.

**The two absent producers are wired and named.** Pass them and the score moves.
An absent component is visible; a component nobody wrote is invisible.

---

## The tolerance is volatility-adaptive

```
distance = max(floor, ATR(14) × 1.0)          # strike_gap × 2 optional
floor    = max(20 points, 0.05% of spot)
```

A quiet session clusters tightly, expiry clusters wide, and cluster quality
stays comparable across both.

### ⚠️ Why the multiple is 1.0 and not 0.12

`ATR × 0.12` is calibrated for a **daily** ATR — 0.12 × 250 NIFTY points ≈ 30,
the intended band. The ATR this codebase publishes (`runner.py`, from
`today_slice`) is a **per-bar** ATR of roughly 10–45 points, and 0.12 × 25 is
three points: **the floor would win every time and nothing would adapt at all**,
which is the one thing the change was for.

One per-bar true range is the sensible band: two prices closer than a single
bar's travel are not separable by price action.

| ATR | Tolerance | Set by |
|---|---|---|
| — | 20.0 | floor |
| 10 | 20.0 | floor |
| 25 | 25.0 | ATR |
| 45 | 45.0 | ATR |
| 80 | 80.0 | ATR |

`strike_gap × 2` is supported via the `strike_gap` argument but **off unless
passed**: NIFTY strikes are 50 apart, so the term is 100 points — correct for
clustering *chain* levels, which sit on strikes, and wrong for price levels.

**ATR is read, never computed.** `runner.py` owns ATR(14) and now publishes
`session_state["_atr"]`. A second ATR here would be the same mistake as a sixth
POC, and a test asserts no `atr` function is defined in this module.

---

## The POC regime is self-normalising

`poc_migration.trend` and `poc_regime.regime` are **different facts**:

* **trend** — `Rising` · `Falling` · `Stable`: which way
* **regime** — `Stable` · `Normal` · `Rotating`: whether that is a lot **for
  this instrument today**

The regime bands come from the distribution of the instrument's own per-bar POC
movement: bottom quartile `Stable`, middle half `Normal`, top quartile
`Rotating`. A fixed threshold cannot work across regimes — one tuned on a quiet
session calls every expiry day a rotation, and one tuned on expiry calls a quiet
session stable.

Below **20 bars** the quartiles are noise, so the regime is `UNKNOWN` rather
than a number invented from four bars.

---

## Changing this contract

**Add fields; never remove or repurpose one.** Bump `LEVEL_SCHEMA_VERSION` when
the contract changes, so a stored level says which shape it was written against
and a consumer can refuse one it does not understand.

The clustering *internals* — how levels are gathered, how the tolerance is
derived, how confidence is weighted — are free to change without a bump, as long
as every field above still means what this table says.

---

## Consuming it

```python
ctx = st.session_state["_liquidity_context"]

for level in ctx.value("levels.resistance") or ():
    if level.confidence != "UNKNOWN" and level.confidence >= 70:
        ...
```

The context also carries `levels.tolerance_pct` and `levels.schema`. Read the
first when comparing two cycles — the band moves underneath you — and the second
before trusting a stored level.
