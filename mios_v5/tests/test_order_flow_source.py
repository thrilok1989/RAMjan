"""The canonical order-flow primitive, and the snapshot it feeds.

The important test here is the equivalence proof: principle 6 says behaviour
must stay identical, so the original formulas are transcribed verbatim and both
implementations are run against the same frame.
"""

import os
import re

import numpy as np
import pandas as pd

from indicators import order_flow as of
from mios_v5 import order_flow_snapshot as snap


def _frame(n=120, seed=7):
    rng = np.random.default_rng(seed)
    low = 100 + np.cumsum(rng.normal(0, .5, n))
    high = low + rng.uniform(.2, 2.0, n)
    close = low + rng.uniform(0, 1, n) * (high - low)
    return pd.DataFrame({
        "high": high, "low": low, "close": close,
        "volume": rng.uniform(1000, 9000, n),
        "datetime": pd.date_range("2026-07-29 09:15", periods=n, freq="1min")})


# ── principle 6: behaviour must be identical ────────────────────────────
def test_the_primitive_reproduces_every_original_site():
    """Six inline copies of one formula, transcribed verbatim from the
    pre-refactor `vob_minimal.py`, run against the same frame.

    Asserting "I didn't change the numbers" is worth nothing. Proving it is
    the only thing that makes a refactor of live trading logic safe.
    """
    df = _frame()
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    v = df["volume"].astype(float)
    rng = (h - l).replace(0, np.nan)
    bf = ((c - l) / rng).clip(0, 1).fillna(0.5)

    def _clipn(x, lo=-1.0, hi=1.0):
        return lo if x < lo else (hi if x > hi else x)

    tot = float(v.sum()) or 1.0

    # L19999 — the normalised score carrying weight 0.28 in _FACTOR_W
    assert np.isclose(_clipn(float((v * bf - v * (1 - bf)).sum()) / (tot * 0.3)),
                      of.cvd_normalised(df))
    # L20561 and L20852 — sign of the sum
    assert int(np.sign((v * bf - v * (1 - bf)).sum())) == of.cvd_sign(df)
    # L22956 — raw sum, the CVD veto in compute_fresh_entry_signal
    assert np.isclose(float((v * bf - v * (1 - bf)).sum()), of.cvd_sum(df))
    # L21066 — datetime-indexed cumulative series
    for kind, series in (("buy", v * bf), ("sell", v * (1 - bf)),
                         ("delta", v * bf - v * (1 - bf))):
        expected = pd.Series(series.values,
                             index=pd.to_datetime(df["datetime"])).cumsum()
        assert expected.equals(of.cumulative(df, kind, index=df["datetime"]))
    # L30306/30307 — plain cumsum, the chart's Cum Buy / Cum Sell
    assert (v * bf).cumsum().equals(of.cumulative(df, "buy"))
    assert (v * (1 - bf)).cumsum().equals(of.cumulative(df, "sell"))


def test_all_views_come_from_one_split_and_match_exactly():
    """Deduplicating the SOURCE without this would have been cosmetic: each
    view called `split()` itself, so six views still meant six buy-fraction
    computations. The first benchmark measured 6.29 ms before and 6.56 ms
    after — a wash, and slightly worse.

    `all_views` computes the split once. It must still agree to the bit with
    the individual views, or the saving came from changing the answer.
    """
    df = _frame()
    v = of.all_views(df)
    assert np.isclose(v["cvd_sum"], of.cvd_sum(df))
    assert v["cvd_sign"] == of.cvd_sign(df)
    assert np.isclose(v["cvd_normalised"], of.cvd_normalised(df))
    assert v["cum_buy"].equals(of.cumulative(df, "buy"))
    assert v["cum_sell"].equals(of.cumulative(df, "sell"))
    t = of.totals(df)
    assert np.isclose(v["buy_total"], t["buy_total"])
    assert np.isclose(v["delta_pct"], t["delta_pct"])
    assert of.is_missing(of.all_views(None))


def test_one_split_is_measurably_cheaper_than_six():
    """Principle 10: a refactor must REDUCE calculations. Measured, not
    assumed — the first attempt at this refactor didn't."""
    import time

    df = _frame(n=400)

    def six_splits():
        return [of.cvd_sum(df), of.cvd_sign(df), of.cvd_normalised(df),
                of.cvd_sum(df), of.cumulative(df, "buy"),
                of.cumulative(df, "sell")]

    def one_split():
        v = of.all_views(df)
        return [v["cvd_sum"], v["cvd_sign"], v["cvd_normalised"],
                v["cvd_sum"], v["cum_buy"], v["cum_sell"]]

    for fn in (six_splits, one_split):
        fn()
    timings = {}
    for name, fn in (("six", six_splits), ("one", one_split)):
        t = time.perf_counter()
        for _ in range(60):
            fn()
        timings[name] = time.perf_counter() - t
    # generous margin — this is a CI-safe assertion, not a benchmark
    assert timings["one"] < timings["six"] * 0.6, timings


def test_no_hand_written_buy_fraction_survives():
    """The line `bf = ((c - l) / rng).clip(0, 1).fillna(0.5)` was typed out
    five times. One typo in one copy would have moved one decision and not the
    others — a system still coherent from outside, and wrong."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    src = open(os.path.join(root, "vob_minimal.py"), encoding="utf-8").read()
    assert "clip(0, 1).fillna(0.5)" not in src
    assert "(1 - bf)" not in src
    assert "(1 - _bf" not in src


# ── principle 9: MISSING is never zero ──────────────────────────────────
def test_missing_is_not_zero():
    """Zero is a market fact — perfectly balanced flow. Asserting one that was
    never observed is fabricating data."""
    assert of.MISSING != 0
    assert of.MISSING != 0.0
    assert not of.MISSING                      # falsy, so `if not x` guards
    assert of.is_missing(of.MISSING)
    assert not of.is_missing(0)
    assert of.MISSING is of._Missing()         # one sentinel, not many


def test_an_unusable_frame_reports_missing_not_zero():
    for bad in (None, pd.DataFrame(),
                pd.DataFrame({"close": [1.0, 2.0]}),      # no high/low/volume
                pd.DataFrame({"high": [1.0], "low": [1.0]})):
        for fn in (of.cvd_sum, of.cvd_sign, of.cvd_normalised, of.totals,
                   of.buy_fraction, of.split, of.delta):
            assert of.is_missing(fn(bad)), (fn.__name__, bad)


def test_balanced_flow_is_zero_and_that_is_a_real_reading():
    """A doji session genuinely is balanced. That must be distinguishable from
    "nothing was measured"."""
    flat = pd.DataFrame({"high": [10.0, 10.0], "low": [10.0, 10.0],
                         "close": [10.0, 10.0], "volume": [500.0, 500.0]})
    assert of.cvd_sign(flat) == 0
    assert not of.is_missing(of.cvd_sign(flat))


# ── principle 8: publish everything once ────────────────────────────────
def test_every_fact_has_exactly_one_owner():
    assert set(snap.FIELDS) == set(snap.OWNERS)
    for field in snap.FIELDS:
        assert snap.owner_of(field)
    # one owner string per fact — not a list, not "or"
    for field, owner in snap.OWNERS.items():
        assert " or " not in owner, field


def test_a_snapshot_defaults_every_unmeasured_fact_to_missing():
    e = snap.empty("NIFTY")
    assert snap.present(e) == 0
    assert e["complete"] is False
    for f in snap.FIELDS:
        assert of.is_missing(e[f]), f


def test_build_records_what_is_missing():
    s = snap.build("ATM Call", cvd=-20477.3, buy_volume=62397010)
    assert s["cvd"] == -20477.3
    assert snap.present(s) == 2
    assert s["complete"] is False
    assert "money_flow" in s["missing"]
    assert of.is_missing(snap.get(s, "money_flow"))
    # None means unmeasured, not a value
    assert of.is_missing(snap.build("x", vob=None)["vob"])


def test_a_typoed_field_is_rejected_not_silently_ignored():
    """A typo'd field would read as MISSING forever, and the engine consuming
    it would degrade quietly and permanently — the exact failure this module
    exists to prevent."""
    try:
        snap.build("NIFTY", cvd_typo=1.0)
    except KeyError as e:
        assert "cvd_typo" in str(e)
    else:
        raise AssertionError("unknown field was accepted")

    for bad in ("nope", "CVD", ""):
        try:
            snap.get({}, bad)
        except KeyError:
            pass
        else:
            raise AssertionError(f"unknown field accepted: {bad!r}")


def test_describe_says_what_is_known():
    assert "no order-flow fact measured" in snap.describe(snap.empty())
    d = snap.describe(snap.build("NIFTY", cvd=1.0))
    assert "1/" in d and "missing" in d
    assert "complete" in snap.describe(
        snap.build("NIFTY", **{f: 1.0 for f in snap.FIELDS}))


# ── principle 12: V6 does not compute ───────────────────────────────────
def test_the_snapshot_module_calculates_nothing():
    import inspect
    src = inspect.getsource(snap)
    for banned in ("cumsum", "rolling(", ".sum()", "clip(0, 1)"):
        assert banned not in src, banned


def test_the_principles_are_written_down():
    """A principle that lives only in a chat message is a principle that will
    be broken by the next person who touches this."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    doc = os.path.join(root, "docs", "ARCHITECTURE_PRINCIPLES.md")
    assert os.path.exists(doc)
    text = open(doc, encoding="utf-8").read()
    for key in ("Single source of truth", "Never recalculate",
                "No hidden logic", "Fail fast", "Non-negotiable"):
        assert key in text, key


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"order flow source tests passed ({len(fns)})")
