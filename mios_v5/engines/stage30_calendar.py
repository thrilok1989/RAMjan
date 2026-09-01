"""Stage 30 — Event Calendar Engine (known scheduled events).

Known events (RBI, Fed, CPI, Budget, expiry, big earnings) are on the calendar
days before they happen, and the market positions ahead of them. This engine
reads the maintained calendar (mios_v5/event_calendar.py) and tells MIOS when a
scheduled catalyst is imminent — and, when Stage 24 also sees the market coiling,
connects the two: "positioning ahead of a KNOWN event."

Non-directional (Bias.NONE) — a calendar date has no direction. It is pure
context. It never predicts the outcome, only flags the schedule. The market
decides; the calendar just says a catalyst is near.
"""

from __future__ import annotations

from datetime import date, datetime

import pytz

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from .. import event_calendar as CAL
from . import _adapters as A

_IST = pytz.timezone("Asia/Kolkata")
_STARS = {5: "⭐⭐⭐⭐⭐", 4: "⭐⭐⭐⭐☆", 3: "⭐⭐⭐☆☆", 2: "⭐⭐☆☆☆", 1: "⭐☆☆☆☆"}


class CalendarEngine(Engine):
    name = "stage30_calendar"
    stage = 30
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        # today (IST); tests may inject raw["calendar_today"] = "YYYY-MM-DD"
        today = None
        inj = state.raw.get("calendar_today")
        if inj:
            try:
                today = date.fromisoformat(str(inj))
            except Exception:
                today = None
        if today is None:
            today = datetime.now(_IST).date()

        try:
            events = CAL.upcoming_events(today, horizon_days=3)
        except Exception:
            events = []

        if not events:
            return EngineResult(
                engine=self.name, status=Status.OK, bias=Bias.NONE, confidence=0.0,
                evidence=["No scheduled event in the next 3 sessions"],
                data={"has_event": False, "next_event": None, "upcoming": []},
                provenance=A.prov("mios:calendar(manual)", Tier.DERIVED))

        nxt = events[0]
        when = ("today" if nxt["is_today"] else "tomorrow" if nxt["is_tomorrow"]
                else f"in {nxt['days_away']} sessions")
        stars = _STARS.get(nxt["importance"], "")
        salience = float(min(100, nxt["importance"] * 18 + (20 if nxt["days_away"] <= 1 else 0)))

        evidence = [f"📅 {nxt['name']} {when} ({stars})"]
        for e in events[1:3]:
            _w = "today" if e["is_today"] else "tomorrow" if e["is_tomorrow"] else f"+{e['days_away']}d"
            evidence.append(f"then {e['name']} {_w} ({_STARS.get(e['importance'], '')})")

        risks, opps = [], []
        # connect to Stage 24: coiling + a known event nearby = positioning ahead
        prep = state.get("stage24_preparation")
        prep_high = prep is not None and prep.ok and (prep.data or {}).get("level") == "HIGH"
        if nxt["importance"] >= 4 and nxt["days_away"] <= 1:
            if prep_high:
                opps.append(f"Market is coiling AND {nxt['name']} is {when} — the positioning "
                            "looks like preparation for this known event; expect a large move "
                            "on/after the announcement")
            else:
                risks.append(f"{nxt['name']} {when} ({stars}) — a scheduled catalyst is near; "
                             "size down into it and expect an event-driven move after")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE, confidence=salience,
            evidence=evidence, risks=risks, opportunities=opps,
            data={"has_event": True, "next_event": nxt, "upcoming": events[:4],
                  "importance": nxt["importance"], "days_away": nxt["days_away"],
                  "when": when, "stars": stars,
                  "coiling_ahead_of_event": bool(prep_high and nxt["importance"] >= 4
                                                 and nxt["days_away"] <= 1)},
            provenance=A.prov("mios:calendar(manual)", Tier.DERIVED),
        )
