"""The canonical order-flow primitive — ONE owner for the buy/sell split.

## Why this exists

The CLV buy-fraction and the per-bar buy/sell split were written out by hand in
six places in `vob_minimal.py` (L19999, L20561, L20852, L21066, L22956, L30307),
with the line

    bf = ((c - l) / rng).clip(0, 1).fillna(0.5)

repeated identically five times. Nothing shared a result. Two of those six
already fed *different* decisions, so a typo in one would have silently moved
one decision and not the others — the worst kind of bug, because the system
would still look coherent.

This module owns that formula. Everything else derives a *view* of it.

## What was NOT consolidated, and why that matters

The six sites do not compute the same number. They compute six different
aggregations of the same split:

    L19999   normalised score       cvd_normalised()
    L20561   sign of the sum        cvd_sign()
    L20852   sign of the sum        cvd_sign()
    L21066   cumulative series      cumulative()
    L22956   raw sum                cvd_sum()
    L30307   cumulative series      cumulative()

So this is not "six calculations became one". It is **one formula, published
once, with six named views** — which is the honest version of the same win. The
duplication removed is the formula; the views were always legitimately
different.

## Fail fast — never invent market data

Every function returns `MISSING` when the input cannot support it. A frame with
no volume column does not produce zeros; zeros are a market fact ("perfectly
balanced flow") and asserting one that was never observed is worse than
reporting nothing. Callers check `is_missing()` and degrade.

This module is the computation layer. `mios_v5` must never call it directly —
V6 reads the published snapshot. See `docs/ARCHITECTURE_PRINCIPLES.md`.
"""

from __future__ import annotations

from typing import Any, Optional


class _Missing:
    """A market fact that was not observed. Never equal to zero."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "MISSING"

    def __eq__(self, other) -> bool:
        return other is self

    def __hash__(self) -> int:
        return hash("MISSING")


#: the sentinel. `MISSING is not 0` — that distinction is the point.
MISSING = _Missing()


def is_missing(v: Any) -> bool:
    return v is MISSING


def _usable(df) -> bool:
    if df is None or getattr(df, "empty", True):
        return False
    cols = {str(c).lower() for c in getattr(df, "columns", [])}
    return {"high", "low", "close", "volume"} <= cols


def buy_fraction(df):
    """CLV buy fraction ∈ [0, 1] per bar, or `MISSING`.

    `(close − low) / (high − low)`, clipped, with a doji (`high == low`)
    falling back to 0.5 — an even split, because a bar with no range genuinely
    tells you nothing about who was in control.

    This is the single definition. It was five identical lines.
    """
    if not _usable(df):
        return MISSING
    try:
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        c = df["close"].astype(float)
        rng = (h - l).replace(0, float("nan"))
        return ((c - l) / rng).clip(0, 1).fillna(0.5)
    except Exception:
        return MISSING


def split(df):
    """`(buy, sell)` volume per bar, or `MISSING`.

    `buy = volume × bf`, `sell = volume × (1 − bf)` — exactly what the six
    inline copies computed, so every caller's numbers are unchanged.
    """
    bf = buy_fraction(df)
    if is_missing(bf):
        return MISSING
    try:
        v = df["volume"].astype(float)
        return v * bf, v * (1.0 - bf)
    except Exception:
        return MISSING


def delta(df):
    """Per-bar delta series (`buy − sell`), or `MISSING`."""
    got = split(df)
    if is_missing(got):
        return MISSING
    buy, sell = got
    return buy - sell


# ── the six views ───────────────────────────────────────────────────────
def cvd_sum(df):
    """Session delta as one number. Was `float((v*bf - v*(1-bf)).sum())`."""
    d = delta(df)
    if is_missing(d):
        return MISSING
    return float(d.sum())


def cvd_sign(df):
    """`-1 / 0 / +1`. Was `int(np.sign((v*bf - v*(1-bf)).sum()))`.

    Note this returns `0` for genuinely balanced flow — that is a real reading,
    distinct from `MISSING`, which means nothing was measured.
    """
    s = cvd_sum(df)
    if is_missing(s):
        return MISSING
    return 1 if s > 0 else (-1 if s < 0 else 0)


def cvd_normalised(df, scale: float = 0.3, lo: float = -1.0, hi: float = 1.0):
    """Delta as a share of total volume, clipped. Was the `_clipn(... / (tot*0.3))`
    line at L19999 that carries weight 0.28 in the scoring model."""
    got = split(df)
    if is_missing(got):
        return MISSING
    buy, sell = got
    try:
        total = float(df["volume"].astype(float).sum()) or 1.0
        x = float((buy - sell).sum()) / (total * scale)
        return lo if x < lo else (hi if x > hi else x)
    except Exception:
        return MISSING


def cumulative(df, kind: str = "delta", index=None):
    """Running total: `kind` ∈ `{"buy", "sell", "delta"}`, or `MISSING`.

    This is CBV (`buy`), CSV (`sell`) and the CVD line (`delta`) — the three
    series that were being computed inline in the chart block and stored
    nowhere, which is why nothing else could ever use them.
    """
    got = split(df)
    if is_missing(got):
        return MISSING
    buy, sell = got
    series = (buy if kind == "buy" else
              sell if kind == "sell" else buy - sell)
    if index is None:
        return series.cumsum()
    # re-index BEFORE accumulating, matching the original at L21066 which built
    # the datetime-indexed series and then called `.cumsum()` on it
    try:
        import pandas as pd
        return pd.Series(series.values,
                         index=pd.to_datetime(index)).cumsum()
    except Exception:
        return series.cumsum()


def all_views(df, index=None):
    """Every view, from **one** split. Or `MISSING`.

    Deduplicating the source without this would have been cosmetic: each view
    called `split()` itself, so six views still meant six buy-fraction
    computations. The first benchmark measured 6.58 ms before and 6.65 ms
    after — a wash, and slightly worse. Principle 10 says a refactor must
    reduce calculations, so the split is computed once here and every view
    derives from it.

    Use this wherever more than one view of the same frame is wanted.
    """
    got = split(df)
    if is_missing(got):
        return MISSING
    buy, sell = got
    d = buy - sell
    total_v = float(buy.sum() + sell.sum())
    s = float(d.sum())

    cum_buy, cum_sell = buy.cumsum(), sell.cumsum()
    if index is not None:
        try:
            import pandas as pd
            idx = pd.to_datetime(index)
            cum_buy = pd.Series(buy.values, index=idx).cumsum()
            cum_sell = pd.Series(sell.values, index=idx).cumsum()
        except Exception:
            pass

    x = s / (total_v * 0.3) if total_v else 0.0
    return {
        "buy": buy, "sell": sell, "delta": d,
        "cvd_sum": s,
        "cvd_sign": 1 if s > 0 else (-1 if s < 0 else 0),
        "cvd_normalised": -1.0 if x < -1.0 else (1.0 if x > 1.0 else x),
        "cum_buy": cum_buy, "cum_sell": cum_sell,
        "cum_delta": cum_buy - cum_sell,
        "buy_total": float(buy.sum()), "sell_total": float(sell.sum()),
        "delta_pct": (round(s / total_v * 100.0, 2) if total_v else 0.0),
    }


def totals(df):
    """`{buy_total, sell_total, delta, delta_pct}`, or `MISSING`.

    The scalar summary every panel wants, derived from the one split rather
    than from a seventh copy of the formula.
    """
    got = split(df)
    if is_missing(got):
        return MISSING
    buy, sell = got
    b, s = float(buy.sum()), float(sell.sum())
    total = b + s
    return {
        "buy_total": b, "sell_total": s, "delta": b - s,
        "delta_pct": (round((b - s) / total * 100.0, 2) if total else 0.0),
    }
