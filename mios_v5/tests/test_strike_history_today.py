"""Per-strike OI history is ONE session — today only.

The store is process-wide (cache_resource) and bounded by count, so without a
day boundary it drew yesterday's series next to today's on the ATM±2 "Call vs
Put OI" chart. `record` now drops any snapshot from a previous IST trading day.
"""

import pandas as pd

import mios_v5.strike_history as SH

_DAY = 86400
_GAP = SH.MIN_GAP_S + 1     # clear the min-gap so each record actually stores


def _df():
    return pd.DataFrame([{
        "Strike": 24400, "openInterest_CE": 1000, "openInterest_PE": 1200,
        "changeinOpenInterest_CE": 50, "changeinOpenInterest_PE": 60}])


def test_previous_day_snapshots_are_dropped_when_today_records():
    store = {}
    df = pd.DataFrame([
        {"Strike": k, "openInterest_CE": 1000, "openInterest_PE": 1200,
         "changeinOpenInterest_CE": 50, "changeinOpenInterest_PE": 60}
        for k in (24350, 24400, 24450)])
    base = 1_700_000_000
    y = base - _DAY                              # yesterday
    # two yesterday snapshots, spaced past the min-gap
    assert SH.record(store, df, 24400, now=y - _GAP)
    assert SH.record(store, df, 24400, now=y)
    assert len(store["snaps"]) == 2
    # today's first snapshot must prune both of yesterday's
    assert SH.record(store, df, 24400, now=base)
    assert len(store["snaps"]) == 1
    assert SH.series(store, 24400, "ce_oi")["t"] == [base]


def test_same_day_snapshots_are_kept():
    store = {}
    df = _df()
    t0 = 1_700_000_000
    assert SH.record(store, df, 24400, now=t0)
    assert SH.record(store, df, 24400, now=t0 + _GAP)
    assert SH.record(store, df, 24400, now=t0 + 2 * _GAP)
    assert len(store["snaps"]) == 3            # all same IST day → all kept


def test_ist_day_boundary_is_utc_plus_530():
    # a point at 18:30 UTC is 00:00 IST the NEXT day — so a 17:00 UTC point the
    # same UTC day is the PREVIOUS IST day and must be pruned.
    store = {}
    df = _df()
    # 2023-11-14 17:00:00 UTC = 22:30 IST (14th); 2023-11-14 19:00 UTC = 00:30 IST (15th)
    prev_ist = 1_699_981_200      # 2023-11-14 17:00 UTC → IST 14th
    next_ist = prev_ist + 2 * 3600  # +2h → 19:00 UTC → IST 15th 00:30
    assert SH.record(store, df, 24400, now=prev_ist)
    assert SH.record(store, df, 24400, now=next_ist)
    # crossed the IST midnight → the earlier (previous IST day) snapshot dropped
    assert len(store["snaps"]) == 1
    assert store["snaps"][0]["t"] == next_ist
