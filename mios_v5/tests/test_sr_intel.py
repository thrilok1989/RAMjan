"""Dashboard 2 — Support & Resistance Intelligence."""

from mios_v5.sr_intel import (bias_at_level, build_level_intel, defended_by,
                              rank_levels, summarise, trap_risk)
from mios_v5.zone_intel import build_zone_card


def _card(side="SUPPORT", price=23650, health=None, touches=3, at=23652):
    z = {"price": price, "strength": 82, "status": "holding",
         "sources": ["MF-POC", "OI-PE", "Round", "PDL"],
         "zone_health": health or {"spot": "building", "options": "building",
                                   "dealers": "building", "institutions": "neutral"}}
    return build_zone_card(side, z, at, dir_score=0.2,
                           htf_levels={"Daily POC": price - 2,
                                       "Weekly VAH": price + 5},
                           touches=touches)


def test_trap_risk_bands():
    assert trap_risk(90)["label"] == "Extreme"
    assert trap_risk(70)["label"] == "High"
    assert trap_risk(50)["label"] == "Medium"
    assert trap_risk(30)["label"] == "Low"
    assert trap_risk(10)["label"] == "Very Low"
    assert trap_risk(None)["label"] == "Unknown"


def test_defended_by_uses_the_levels_own_groups():
    """A level can be dealer-defended while institutions are elsewhere — that
    distinction is the useful part, so it reads the ZONE's health, not a
    global controller."""
    inst = _card(health={"institutions": "building", "dealers": "neutral",
                         "spot": "neutral", "options": "neutral"})
    assert defended_by(inst)["who"] == "Institutions"
    deal = _card(health={"dealers": "building", "institutions": "neutral",
                         "spot": "neutral", "options": "neutral"})
    assert defended_by(deal)["who"] == "Dealers"


def test_defended_by_reports_nobody_and_mixed_honestly():
    none_ = _card(health={"spot": "neutral", "options": "neutral",
                          "dealers": "neutral", "institutions": "neutral"})
    assert defended_by(none_)["who"] == "Nobody"
    split = _card(health={"spot": "building", "options": "fading",
                          "dealers": "fading", "institutions": "neutral"})
    assert defended_by(split)["who"] in ("Mixed", "Buyers/Sellers")


def test_bias_at_level_is_local_not_global():
    """A support defended by buyers is locally bullish even in a bear market —
    that is the whole reason to trade a level instead of a forecast."""
    b = bias_at_level(_card(), transition={"state": "WEAKENING", "bias": "BEAR"})
    assert b["bias"] in ("Bullish", "Neutral")
    assert b["trend"] in ("Strengthening", "Weakening", "Stable", "Reversing")


def test_lifecycle_drives_the_trend_word():
    c = _card()
    c["lifecycle"] = "building"
    assert bias_at_level(c)["trend"] == "Strengthening"
    c["lifecycle"] = "fading"
    assert bias_at_level(c)["trend"] == "Weakening"


def test_summary_is_at_most_three_plain_lines():
    c = _card()
    s = summarise(c, defended_by(c), bias_at_level(c),
                  trap_risk((c["probabilities"] or {}).get("trap")),
                  {"behaviour": "PASSIVE_BUYING", "label": "🟢 Passive Buying"})
    assert 1 <= len(s) <= 3
    assert all(x.endswith(".") for x in s)
    assert all(len(x) < 90 for x in s)


def test_full_intel_object_has_every_field():
    intel = build_level_intel(
        _card(),
        reaction={"state": "REJECTION", "label": "🛡 Rejection"},
        absorption={"behaviour": "BUYER_RELOADING", "label": "🔁 Buyer Reloading"},
        transition={"state": "STABLE"},
        decision={"side": "CALL", "entry": 23644, "stop": 23632,
                  "trail": {"mode": "normal"}},
        next_target=23780, target_label="Weekly POC", age_min=45)
    for k in ("price", "type", "active", "origin", "confluence_stars",
              "confluence_score", "strength", "lifecycle", "health", "touches",
              "freshness", "acceptance", "absorption", "trap", "htf",
              "defended_by", "bias", "expected", "entry_zone", "stop",
              "trail", "next_target", "confidence", "summary"):
        assert k in intel, f"missing {k}"
    assert intel["next_target"] == 23780 and intel["target_label"] == "Weekly POC"
    assert intel["stop"] == 23632 and intel["stop_is_dynamic"]


def test_entry_stop_only_come_from_a_matching_side():
    """A PUT decision must not put its entry/stop onto a SUPPORT level."""
    sup = build_level_intel(_card("SUPPORT"),
                            decision={"side": "PUT", "entry": 23706,
                                      "stop": 23718})
    assert sup["entry"] is None
    assert not sup["stop_is_dynamic"]      # falls back to the zone invalidation


def test_stop_is_never_fixed_when_the_engine_supplies_one():
    with_dec = build_level_intel(_card(), decision={"side": "CALL",
                                                    "entry": 23644,
                                                    "stop": 23632})
    assert with_dec["stop_is_dynamic"] and with_dec["stop"] == 23632


def test_entry_zone_spans_level_and_proven_refusal():
    i = build_level_intel(_card(price=23650),
                          decision={"side": "CALL", "entry": 23644})
    lo, hi = i["entry_zone"]
    assert lo == 23644 and hi == 23650


def test_ranking_puts_the_active_level_first():
    a = build_level_intel(_card("SUPPORT", 23650, at=23652))     # price is here
    b = build_level_intel(_card("RESISTANCE", 23820, at=23652))  # far away
    ranked = rank_levels([b, a])
    assert ranked[0]["price"] == 23650 and ranked[0]["medal"] == "🥇"
    assert ranked[1]["medal"] == "🥈"


def test_ranking_is_stable_and_labels_everything():
    lv = [build_level_intel(_card("SUPPORT", 23650 + i * 50, at=99999))
          for i in range(4)]
    ranked = rank_levels(lv)
    assert [r["rank"] for r in ranked] == [1, 2, 3, 4]
    assert ranked[3]["medal"] == "#4"


def test_a_level_below_spot_is_support_whatever_it_was_called():
    """Reported from the live panel: spot 24,229.8, level 24,227 shown as
    "Resistance ... Bounce probability remains high" — about a floor. The
    Reaction-Zone engine names a level when it forms, and the name goes stale
    the moment price crosses it."""
    from mios_v5.sr_intel import resolve_side

    assert resolve_side(24227, 24229.8, "RESISTANCE") == ("SUPPORT", True)
    assert resolve_side(24144, 24229.8, "SUPPORT") == ("SUPPORT", False)
    assert resolve_side(24300, 24229.8, "RESISTANCE") == ("RESISTANCE", False)
    # a support price breaks below flips the other way too
    assert resolve_side(24300, 24100.0, "SUPPORT") == ("RESISTANCE", True)


def test_without_a_spot_the_stored_label_stands():
    """Guessing would be worse than deferring."""
    from mios_v5.sr_intel import resolve_side
    assert resolve_side(24227, None, "RESISTANCE") == ("RESISTANCE", False)
    assert resolve_side(None, 24229.8, "SUPPORT") == ("SUPPORT", False)


def test_a_target_on_the_wrong_side_of_the_trade_is_not_a_target():
    """The same `next_target` was shown on both cards, so the resistance short
    was handed a target ABOVE its own entry — and in the reported case a
    target identical to its stop (both 24,300)."""
    from mios_v5.sr_intel import target_for

    assert target_for("RESISTANCE", 24227, 24300) is None
    assert target_for("RESISTANCE", 24227, 24100) == 24100.0
    assert target_for("SUPPORT", 24144, 24300) == 24300.0
    assert target_for("SUPPORT", 24144, 24000) is None
    assert target_for(None, 24144, 24300) is None
    assert target_for("SUPPORT", None, 24300) is None


def test_the_intel_object_carries_the_corrected_side_and_the_flip():
    from mios_v5.sr_intel import build_level_intel

    lv = build_level_intel(
        {"price": 24227.0, "side": "RESISTANCE",
         "strength": {"score": 98}, "health": {"pct": 70}, "origin": {}},
        next_target=24300.0, target_label="Daily LVN2", spot=24229.8)
    assert lv["side"] == "SUPPORT"
    assert lv["flipped"] is True and lv["labelled_side"] == "RESISTANCE"
    # 24,300 was NONSENSE above a resistance short's entry; above a support
    # it is exactly where the trade runs to. Correcting the side is what makes
    # the target legitimate, so it survives.
    assert lv["next_target"] == 24300.0 and lv["target_label"] == "Daily LVN2"


def test_a_genuine_resistance_drops_a_target_above_itself():
    from mios_v5.sr_intel import build_level_intel

    lv = build_level_intel(
        {"price": 24227.0, "side": "RESISTANCE", "origin": {}},
        next_target=24300.0, target_label="Daily LVN2", spot=24100.0)
    assert lv["side"] == "RESISTANCE" and lv["flipped"] is False
    assert lv["next_target"] is None and lv["target_label"] is None


def test_the_panel_shows_the_flip_rather_than_quietly_correcting_it():
    """A flipped level is a level that has just been broken — that is
    information, and it explains why the card now says the opposite of what it
    said an hour ago."""
    from mios_v5.ui.sr_panel import level_html

    html = level_html({"price": 24227.0, "side": "SUPPORT", "type": "Support",
                       "flipped": True, "labelled_side": "RESISTANCE"})
    assert "FLIPPED" in html and "was Resistance" in html
    assert "FLIPPED" not in level_html({"price": 1.0, "side": "SUPPORT",
                                        "type": "Support"})


def test_empty_is_safe():
    assert build_level_intel(None) is None
    assert rank_levels(None) == []


# ── the unenriched fallback ─────────────────────────────────────────────
def test_a_raw_zone_still_produces_a_usable_card():
    """`enrich_zone_intel` can fail or partially fail. When it does, the panel
    used to render NOTHING and say "still warming up" — indistinguishable from
    a cold start, and it stayed on screen indefinitely."""
    from mios_v5.sr_intel import build_level_intel, card_from_zone
    card = card_from_zone({"price": 23880.0, "strength": 72,
                           "lifecycle": "stable"}, "SUPPORT")
    assert card and card["price"] == 23880.0 and card["side"] == "SUPPORT"
    assert card["enriched"] is False
    lv = build_level_intel(card)
    assert lv and lv["price"] == 23880.0


def test_a_zone_with_no_price_produces_nothing():
    from mios_v5.sr_intel import card_from_zone
    assert card_from_zone({}, "SUPPORT") is None
    assert card_from_zone(None, "SUPPORT") is None
    assert card_from_zone({"price": "n/a"}, "SUPPORT") is None


def test_the_fallback_reads_health_from_either_shape():
    from mios_v5.sr_intel import card_from_zone
    a = card_from_zone({"price": 1.0, "health_pct": 61}, "SUPPORT")
    b = card_from_zone({"price": 1.0, "zone_health": {"pct": 61}}, "SUPPORT")
    assert a["health"]["pct"] == 61.0 and b["health"]["pct"] == 61.0


def test_the_panel_distinguishes_failure_from_warming_up():
    """A real error and a cold start rendered the same sentence, so a 15-minute
    failure looked like patience."""
    import inspect

    from mios_v5.ui import dashboard_v6
    src = inspect.getsource(dashboard_v6._sr_status)
    assert "_reaction_sr_error" in src
    assert "not a warm-up" in src
    assert "will not clear on its own" in src


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"S/R intelligence tests passed ({len(fns)})")
