"""Stage 18 — Sector Rotation engine: voting + self-gating safeguards."""

from datetime import datetime, timedelta
import pytz

from mios_v5.core.contract import MarketState, Bias, Status
from mios_v5.engines.stage18_sector import SectorRotationEngine

_IST = pytz.timezone("Asia/Kolkata")
_CYC = ["BANK", "AUTO", "REALTY", "METAL", "ENERGY", "INFRA", "PSU BANK"]
_DEF = ["IT", "FMCG", "PHARMA", "MEDIA"]
_ALL = _CYC + _DEF


def _snap(up_names, fetched=None, coverage=11):
    rows = [{"name": n, "day_chg_pct": (1.0 if n in up_names else -0.5)}
            for n in _ALL[:coverage]]
    lead = sorted(rows, key=lambda r: -r["day_chg_pct"])[:3]
    top = {r["name"] for r in lead}
    rb = ("RISK-ON 🟢" if len(top & set(_CYC)) >= 2 else
          "RISK-OFF 🔴" if len(top & set(_DEF)) >= 2 else "MIXED ⚪")
    return {"all": rows, "leading": lead, "rotation_bias": rb,
            "fetched_at": (fetched or datetime.now(_IST)).isoformat()}


def _run(sr):
    return SectorRotationEngine().compute(MarketState(raw={"sector_rotation": sr}))


def test_risk_on_votes_bull():
    r = _run(_snap(_CYC))
    assert r.bias == Bias.BULL and r.data["voting"] is True
    assert r.data["risk_mode"] == "Risk-On"
    assert 0 < r.confidence <= 50            # low-weight context, never high


def test_risk_off_votes_bear():
    r = _run(_snap(_DEF))
    assert r.bias == Bias.BEAR and r.data["voting"] is True


def test_thin_coverage_stands_aside():
    r = _run(_snap(["BANK", "AUTO"], coverage=5))
    assert r.bias == Bias.NONE and r.data["voting"] is False and r.confidence == 0.0


def test_stale_stands_aside():
    r = _run(_snap(_CYC, fetched=datetime.now(_IST) - timedelta(minutes=30)))
    assert r.bias == Bias.NONE and r.data["voting"] is False


def test_missing_snapshot_stands_aside():
    r = SectorRotationEngine().compute(MarketState(raw={}))
    assert r.status == Status.OK and r.bias == Bias.NONE and r.data["voting"] is False


if __name__ == "__main__":
    for fn in [test_risk_on_votes_bull, test_risk_off_votes_bear,
               test_thin_coverage_stands_aside, test_stale_stands_aside,
               test_missing_snapshot_stands_aside]:
        fn()
    print("stage18 sector tests passed")
