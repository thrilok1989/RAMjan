"""Stage 45 — Higher-Timeframe VPFR (institutional big picture)."""

from mios_v5.htf_vpfr import (TIMEFRAMES, alignment, build_profile, htf_levels,
                              market_structure, migration_summary,
                              signal_validity, tf_read, value_migration)


def _bars(center=23700.0, n=40, spread=50.0):
    """Bars clustered around `center` so the POC lands there."""
    hs, ls, vs = [], [], []
    for i in range(n):
        off = ((i % 5) - 2) * (spread / 5.0)
        hs.append(center + off + 10)
        ls.append(center + off - 10)
        vs.append(1000.0 if abs(off) < spread / 5.0 else 300.0)
    return hs, ls, vs


def test_profile_has_value_area_and_nodes():
    p = build_profile(*_bars())
    assert p and p["val"] <= p["poc"] <= p["vah"]
    assert p["hvn"] and isinstance(p["lvn"], list)
    assert p["n_bars"] == 40
    # POC should sit near where volume was concentrated
    assert abs(p["poc"] - 23700) < 60


def test_profile_needs_data_and_never_invents():
    assert build_profile([], [], []) is None
    assert build_profile([1, 2], [1, 2], [1, 1]) is None      # < 3 bars
    flat = build_profile([100, 100, 100], [100, 100, 100], [1, 1, 1])
    assert flat["poc"] == flat["vah"] == flat["val"] == 100


def test_profile_spreads_volume_across_spanned_bins():
    # one very wide bar must not dump all volume into a single bin
    p = build_profile([120, 101, 101], [80, 99, 99], [1000, 10, 10])
    assert p and p["vah"] > p["val"]


def test_value_migration_directions():
    assert value_migration(23720, 23650)["direction"] == "up"
    assert value_migration(23650, 24100)["direction"] == "down"
    assert value_migration(23700, 23700)["direction"] == "flat"
    assert value_migration(None, 23700)["direction"] == "unknown"
    assert "strong" in value_migration(23650, 24100)["label"]


def test_market_structure_detects_trend():
    up_h = [100 + i * 2 for i in range(30)]
    up_l = [95 + i * 2 for i in range(30)]
    assert market_structure(up_h, up_l)["trend"] in ("uptrend", "rotation")
    dn_h = [200 - i * 2 for i in range(30)]
    dn_l = [195 - i * 2 for i in range(30)]
    assert market_structure(dn_h, dn_l)["trend"] in ("downtrend", "rotation")
    assert market_structure([1, 2], [1, 2])["trend"] == "unknown"


def test_tf_read_location_drives_bias():
    p = build_profile(*_bars())
    above = tf_read("Daily", p["vah"] + 100, p,
                    {"trend": "uptrend"}, {"direction": "up"})
    below = tf_read("Daily", p["val"] - 100, p,
                    {"trend": "downtrend"}, {"direction": "down"})
    assert above["bias"] == "BULL" and above["location"] == "above VAH"
    assert below["bias"] == "BEAR" and below["location"] == "below VAL"
    assert above["confidence"] > 0


def test_tf_read_missing_profile_is_missing_not_neutral_opinion():
    r = tf_read("Weekly", 23700, None)
    assert r["status"] == "MISSING" and r["confidence"] == 0


def _reads(**biases):
    out = {}
    for tf in TIMEFRAMES:
        b = biases.get(tf)
        if b is None:
            continue
        out[tf] = {"tf": tf, "bias": b, "confidence": 80, "status": "OK"}
    return out


def test_alignment_counts_and_stars():
    r = _reads(**{"1H": "BEAR", "4H": "BEAR", "Daily": "BEAR",
                  "Weekly": "BEAR", "Monthly": "NEUTRAL", "Yearly": "BULL"})
    a = alignment(r)
    assert a["bias"] == "BEAR" and a["n"] == 6
    assert a["n_bear"] == 4 and "Yearly" in a["disagree"]
    assert a["stars"].count("★") >= 3


def test_alignment_weights_slower_timeframes_more():
    # one Yearly bull vs one 1H bear → the Yearly should win
    a = alignment(_reads(**{"1H": "BEAR", "Yearly": "BULL"}))
    assert a["bias"] == "BULL"


def test_alignment_empty_is_safe():
    a = alignment(None)
    assert a["bias"] == "NEUTRAL" and a["n"] == 0


def test_migration_summary_short_medium_long():
    reads = {
        "1H": {"status": "OK", "migration": {"direction": "up"}},
        "4H": {"status": "OK", "migration": {"direction": "up"}},
        "Daily": {"status": "OK", "migration": {"direction": "down"}},
        "Weekly": {"status": "OK", "migration": {"direction": "down"}},
        "Monthly": {"status": "OK", "migration": {"direction": "flat"}},
    }
    m = migration_summary(reads)
    # short-term rally inside a longer bearish market
    assert m["short"] == "↑" and m["medium"] == "↓"


def test_signal_validity_rejects_against_higher_timeframes():
    r = _reads(**{"1H": "BULL", "4H": "BULL", "Daily": "BEAR",
                  "Weekly": "BEAR", "Monthly": "BEAR"})
    v = signal_validity("CALL", r)
    assert v["verdict"] == "REJECT" and not v["approved"]
    assert "Monthly" in v["against"] and v["pct"] < 60


def test_signal_validity_approves_full_agreement():
    r = _reads(**{t: "BULL" for t in TIMEFRAMES})
    v = signal_validity("CALL", r)
    assert v["approved"] and v["pct"] >= 95
    assert signal_validity("PUT", r)["approved"] is False


def test_signal_validity_unknown_side_is_safe():
    assert signal_validity(None, _reads(**{"1H": "BULL"}))["verdict"] == "UNKNOWN"


def test_htf_levels_map_for_confluence():
    p = build_profile(*_bars())
    lv = htf_levels({"Daily": {"status": "OK", "profile": p},
                     "Weekly": {"status": "OK", "profile": p}})
    assert "Daily VAH" in lv and "Weekly POC" in lv
    assert all(isinstance(v, float) for v in lv.values())


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"HTF VPFR tests passed ({len(fns)})")
