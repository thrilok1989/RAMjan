"""MIOS V5 — Event Calendar (manually maintained + computed expiries).

The Calendar Engine (Stage 30) reads *known, scheduled* events so MIOS knows when
the market is positioning ahead of a planned catalyst (RBI, Fed, CPI, Budget,
expiry, big earnings). This is the V5.0 source: a small list you maintain by hand
here, plus auto-computed weekly/monthly NIFTY expiries. No external feed, no
dependency — you control it. (V5.5+: swap in an economic-calendar API.)

To add an event: append a dict to CALENDAR with an ISO date, a name, and an
importance 1–5. Past dates are ignored automatically.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

#: NIFTY weekly-expiry weekday (Mon=0 … Sun=6). NSE has moved this before —
#: change this one constant if the exchange shifts the expiry day again.
WEEKLY_EXPIRY_WEEKDAY = 3        # Thursday

#: Manually maintained macro / event calendar. Keep it current.
#: importance: 5 = market-moving (RBI/Fed/Budget/Election), 4 = major (CPI/GDP/
#: monthly expiry), 3 = notable (big earnings), 2 = minor.
#:
#: CATEGORIES scale the calendar: tag each event with a category and adding a
#: future one is just "insert it in the right bucket". Each category has a
#: default importance used when an entry omits one.
CATEGORIES: Dict[str, int] = {
    "Monetary Policy": 5,   # RBI · FOMC · ECB · BOJ
    "Government": 5,        # Budget · Elections · MSCI rebalance
    "Inflation": 4,        # India CPI · US CPI · PPI
    "Growth": 4,           # GDP · PMI · IIP
    "Employment": 4,       # US NFP · Jobless Claims
    "Global Risk": 4,      # G20 · OPEC · geopolitics
    "Options": 3,          # Weekly / Monthly expiry (expiry is auto-computed)
    "Corporate": 3,        # Major earnings
}

#: Manually maintained events, tagged by category. To add one, drop a dict in
#: the right bucket with an ISO date + name (+ optional importance override).
CALENDAR: List[Dict[str, Any]] = [
    # ── Monetary Policy ──
    # {"date": "2026-08-06", "name": "RBI Policy",   "category": "Monetary Policy"},
    # {"date": "2026-09-17", "name": "US FOMC",      "category": "Monetary Policy"},
    # ── Inflation ──
    # {"date": "2026-08-12", "name": "US CPI",       "category": "Inflation"},
    # {"date": "2026-08-13", "name": "India CPI",    "category": "Inflation"},
    # ── Growth / Employment ──
    # {"date": "2026-08-29", "name": "India GDP",    "category": "Growth"},
    # {"date": "2026-09-05", "name": "US NFP",       "category": "Employment"},
    # ── Government / Global Risk / Corporate ──
    # {"date": "2027-02-01", "name": "Union Budget", "category": "Government"},
    # ↑ examples — replace with the real upcoming dates you track.
]


def _importance_for(e: Dict[str, Any]) -> int:
    """Explicit importance if given, else the category default, else 3."""
    if e.get("importance") is not None:
        try:
            return int(e["importance"])
        except Exception:
            pass
    return int(CATEGORIES.get(str(e.get("category", "")), 3))


def _next_weekday(d: date, weekday: int) -> date:
    """The next date on/after `d` that falls on `weekday`."""
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def _last_weekday_of_month(d: date, weekday: int) -> date:
    """The last `weekday` of d's month (monthly expiry)."""
    if d.month == 12:
        first_next = date(d.year + 1, 1, 1)
    else:
        first_next = date(d.year, d.month + 1, 1)
    last = first_next - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _computed_expiries(today: date, horizon_days: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    wk = _next_weekday(today, WEEKLY_EXPIRY_WEEKDAY)
    monthly = _last_weekday_of_month(today, WEEKLY_EXPIRY_WEEKDAY)
    if 0 <= (wk - today).days <= horizon_days:
        is_monthly = (wk == monthly)
        out.append({"date": wk.isoformat(),
                    "name": "Monthly expiry" if is_monthly else "Weekly expiry",
                    "category": "Options",
                    "importance": 4 if is_monthly else 3})
    return out


def upcoming_events(today: date, horizon_days: int = 3) -> List[Dict[str, Any]]:
    """Events within [today, today+horizon_days], soonest first, each annotated
    with days_away / is_today / is_tomorrow. Merges the manual list with the
    computed weekly/monthly expiry; de-dupes same-day events keeping the most
    important."""
    cands: List[Dict[str, Any]] = []
    for e in CALENDAR + _computed_expiries(today, horizon_days):
        try:
            d = date.fromisoformat(str(e["date"]))
        except Exception:
            continue
        days = (d - today).days
        if 0 <= days <= horizon_days:
            cands.append({"date": d.isoformat(), "name": e.get("name", "Event"),
                          "category": e.get("category", "—"),
                          "importance": _importance_for(e),
                          "days_away": days, "is_today": days == 0,
                          "is_tomorrow": days == 1})
    # de-dupe by date, keep highest importance
    by_date: Dict[str, Dict[str, Any]] = {}
    for e in cands:
        cur = by_date.get(e["date"])
        if cur is None or e["importance"] > cur["importance"]:
            by_date[e["date"]] = e
    return sorted(by_date.values(), key=lambda e: (e["days_away"], -e["importance"]))
