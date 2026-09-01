"""Stage 30 — Event Calendar engine + event_calendar helpers."""

from datetime import date

from mios_v5.core.contract import Bias, EngineResult, MarketState, Status
from mios_v5 import event_calendar as CAL
from mios_v5.engines.stage30_calendar import CalendarEngine


def _state(today, prep_level=None, calendar=None):
    st = MarketState(raw={"calendar_today": today})
    if prep_level:
        st.results["stage24_preparation"] = EngineResult(
            engine="stage24_preparation", status=Status.OK, bias=Bias.NONE,
            confidence=80.0, data={"level": prep_level}, provenance=None)
    return st


def test_weekly_expiry_is_found(monkeypatch):
    monkeypatch.setattr(CAL, "CALENDAR", [])
    # a Monday → the Thursday weekly expiry is 3 days away (inside horizon)
    r = CalendarEngine().compute(_state("2026-08-03"))
    assert r.data["has_event"] is True
    assert "expiry" in r.data["next_event"]["name"].lower()
    assert r.bias == Bias.NONE                      # calendar has no direction


def test_manual_event_tomorrow(monkeypatch):
    monkeypatch.setattr(CAL, "CALENDAR",
                        [{"date": "2026-08-04", "name": "RBI Policy", "importance": 5}])
    r = CalendarEngine().compute(_state("2026-08-03"))
    ne = r.data["next_event"]
    assert ne["name"] == "RBI Policy" and ne["is_tomorrow"] is True
    assert r.data["when"] == "tomorrow"


def test_coiling_ahead_of_event(monkeypatch):
    monkeypatch.setattr(CAL, "CALENDAR",
                        [{"date": "2026-08-04", "name": "RBI Policy", "importance": 5}])
    r = CalendarEngine().compute(_state("2026-08-03", prep_level="HIGH"))
    assert r.data["coiling_ahead_of_event"] is True
    assert any("preparation" in o.lower() or "ahead of" in o.lower() for o in r.opportunities)


def test_nothing_scheduled(monkeypatch):
    monkeypatch.setattr(CAL, "CALENDAR", [])
    # a Friday → next weekly expiry (Thu) is 6 days out, beyond the 3-day horizon
    r = CalendarEngine().compute(_state("2026-08-07"))
    assert r.data["has_event"] is False and r.bias == Bias.NONE


if __name__ == "__main__":
    class _MP:
        def setattr(self, obj, name, val):
            self._saved = (obj, name, getattr(obj, name))
            setattr(obj, name, val)
    def run(fn):
        mp = _MP()
        try:
            fn(mp)
        finally:
            if hasattr(mp, "_saved"):
                o, n, v = mp._saved
                setattr(o, n, v)
    for fn in [test_weekly_expiry_is_found, test_manual_event_tomorrow,
               test_coiling_ahead_of_event, test_nothing_scheduled]:
        run(fn)
    print("stage30 calendar tests passed")
