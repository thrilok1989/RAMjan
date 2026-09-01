"""📊 Per-strike OI / ΔOI history for ATM±2 — accumulated, not fetched.

## Why this had to be built rather than wired

The reference code reads `st.session_state.oi_history` / `.chgoi_history` /
`.oi_current_strikes`. **None of those exist in this repo** — they belong to a
different app. What this repo has is `option_data['df_summary']`, rebuilt every
cycle with `Strike`, the two open-interest columns, the two change-in-OI columns
and the two LTPs — under the names listed in `FIELDS`, which is the only place
those spellings are written down. A time series has to be accumulated from those
snapshots.

Same shape as `mios_v5.iv_history`, and for the same reason: the store lives in a
`st.cache_resource` object rather than `session_state`, so it survives a rerun and
a second browser tab instead of restarting the collection every time.

## The rules

    · one snapshot per cycle, keyed by time — a rerun that brings no new chain
      must not duplicate the last point, or a stalled feed draws a flat line that
      looks like a settled market
    · MIN_GAP_S between kept snapshots, so the series is time-meaningful
    · CAP snapshots, oldest dropped
    · strikes are stored per snapshot, because ATM DRIFTS: the ±2 window at 09:20
      is not the window at 14:50, and a series that silently re-labels a strike
      would draw two different contracts as one line

⚠️ Absolute OI is stored, not lakhs, and ΔOI as the chain reports it. Unit
conversion belongs to the panel — dividing here would bake a display choice into
the data.

Pure module: the store arrives as a parameter.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: Snapshots retained. At ~20s a cycle this is a full session.
CAP = 1200

#: Seconds between kept snapshots.
MIN_GAP_S = 18.0

#: Strikes each side of ATM. The reference charts show ATM±2 → five strikes.
WINGS = 2

#: The fields kept per strike, and the `df_summary` columns each may arrive in.
#:
#: ⚠️ CANDIDATES, not one name. My first version assumed `CE_OI_Change`, which
#: does not exist anywhere in this app — a test asserting the columns against the
#: real source caught it before it shipped. `analyze_option_chain` merges the Dhan
#: names (`openInterest_CE`, `changeinOpenInterest_CE`, `lastPrice_CE`) while
#: other panels read `CE_OI` aliases, so both are accepted and the first one
#: present wins. Guessing a single name is the `fii_net` bug: a lookup that always
#: misses, on a frame that had the data all along.
FIELDS = {
    "ce_oi": ("openInterest_CE", "CE_OI"),
    "pe_oi": ("openInterest_PE", "PE_OI"),
    "ce_chg": ("changeinOpenInterest_CE", "CE_OI_Change", "CE_ChgOI"),
    "pe_chg": ("changeinOpenInterest_PE", "PE_OI_Change", "PE_ChgOI"),
    "ce_ltp": ("lastPrice_CE", "CE_LTP"),
    "pe_ltp": ("lastPrice_PE", "PE_LTP"),
}


def _pick(row: Any, candidates: Sequence[str]) -> Optional[float]:
    """The first candidate column that carries a number."""
    for col in candidates:
        try:
            v = _f(row.get(col))
        except Exception:
            v = None
        if v is not None:
            return v
    return None


def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def atm_window(strikes: Sequence[Any], spot: Any,
               wings: int = WINGS) -> List[float]:
    """The ATM±`wings` strikes actually present in the chain, ascending.

    ⚠️ Picked by distance from spot rather than by index, because the chain does
    not always start on a round strike and an index-based window silently slides.
    """
    vals = sorted({v for v in (_f(s) for s in (strikes or ())) if v is not None})
    sp = _f(spot)
    if not vals or sp is None:
        return []
    nearest = min(vals, key=lambda s: abs(s - sp))
    i = vals.index(nearest)
    return vals[max(0, i - wings): i + wings + 1]


def record(store: Any, df_summary: Any = None, spot: Any = None,
           now: Optional[float] = None, wings: int = WINGS) -> bool:
    """Add one snapshot. `True` when stored.

    `df_summary` is the chain frame; anything with `Strike` and the `FIELDS`
    columns works, so a test needs no pandas fixture beyond a small frame.
    """
    if not isinstance(store, dict):
        return False
    import time
    at = time.time() if now is None else float(now)

    snaps: List[Dict[str, Any]] = store.setdefault("snaps", [])
    # ⚠️ `(at - x or 0)` was `((at - x) or 0)` — the `or` binds looser than the
    # subtraction, so it guarded nothing and would have raised on a None `t`
    # instead of falling back to 0. Checked explicitly.
    if snaps:
        last = _f(snaps[-1].get("t"))
        if last is not None and at - last < MIN_GAP_S:
            return False
    if df_summary is None or getattr(df_summary, "empty", True):
        return False
    try:
        strikes = atm_window(df_summary["Strike"].tolist(), spot, wings)
    except Exception:
        return False
    if not strikes:
        return False

    rows: Dict[str, Dict[str, Optional[float]]] = {}
    for k in strikes:
        try:
            row = df_summary[df_summary["Strike"] == k]
            if row.empty:
                continue
            r = row.iloc[0]
        except Exception:
            continue
        rows[f"{k:.0f}"] = {f: _pick(r, cols) for f, cols in FIELDS.items()}
    if not rows:
        return False

    snaps.append({"t": at, "strikes": [f"{k:.0f}" for k in strikes],
                  "rows": rows})
    # One session only: drop any snapshot from a previous IST trading day, so the
    # per-strike chart never draws yesterday's series alongside today's. The
    # store is process-wide (cache_resource), so without this it accumulates
    # across days until CAP ages the old points out. IST = UTC+5:30 → the day
    # bucket is floor((epoch + 19800) / 86400).
    _ist_day = lambda t: int(((_f(t) or 0) + 19800) // 86400)
    _today = _ist_day(at)
    if snaps and _ist_day(snaps[0].get("t")) != _today:
        snaps[:] = [s for s in snaps if _ist_day(s.get("t")) == _today]
    if len(snaps) > CAP:
        del snaps[:len(snaps) - CAP]
    return True


def strikes(store: Any) -> List[str]:
    """The strike window of the LATEST snapshot, ascending.

    ⚠️ The latest, not the union of all of them. ATM drifts, so the union would
    offer strikes that left the window hours ago and whose lines stop mid-chart.
    """
    if not isinstance(store, dict):
        return []
    snaps = store.get("snaps") or []
    return list(snaps[-1].get("strikes") or ()) if snaps else []


def series(store: Any, strike: Any, field: str) -> Dict[str, List[Any]]:
    """`{"t": [...], "v": [...]}` for one strike and one field, oldest first.

    Snapshots that do not carry the strike are skipped rather than zero-filled —
    a zero is a real OI reading and inventing one would draw a collapse that
    never happened.
    """
    out: Dict[str, List[Any]] = {"t": [], "v": []}
    if not isinstance(store, dict) or field not in FIELDS:
        return out
    key = f"{_f(strike):.0f}" if _f(strike) is not None else str(strike)
    for s in (store.get("snaps") or []):
        v = (s.get("rows") or {}).get(key, {}).get(field)
        if v is None:
            continue
        out["t"].append(s.get("t"))
        out["v"].append(v)
    return out


def read(store: Any) -> Dict[str, Any]:
    """`{n, strikes, span_s, reporting}` — enough for an honest caption."""
    snaps = (store.get("snaps") or []) if isinstance(store, dict) else []
    n = len(snaps)
    span = None
    if n >= 2:
        a, b = _f(snaps[0].get("t")), _f(snaps[-1].get("t"))
        span = round(b - a, 1) if (a is not None and b is not None) else None
    return {"n": n, "strikes": strikes(store), "span_s": span,
            "reporting": n >= 2}


def labels(window: Sequence[Any]) -> Dict[str, str]:
    """`{strike: 'ATM-2' … 'ATM' … 'ATM+2'}` for the given window.

    ⚠️ Distance from ATM, **not** ITM/OTM. Moneyness is side-dependent — ₹24500
    with spot at ₹24600 is ITM for the call and OTM for the put — and these charts
    show BOTH sides on one axis, so an "ITM-2" heading was true of the red line and
    false of the green one on the same picture. It also matches the vocabulary the
    rest of the app already uses ("ATM-1 CE 24550" in the leg table).

    Derived from the window's own length so a truncated window at the edge of the
    chain is labelled from its centre rather than mislabelled from a fixed list.
    """
    ks = [str(k) for k in (window or ())]
    if not ks:
        return {}
    mid = len(ks) // 2
    out = {}
    for i, k in enumerate(ks):
        d = i - mid
        out[k] = "ATM" if d == 0 else f"ATM{d:+d}"
    return out
