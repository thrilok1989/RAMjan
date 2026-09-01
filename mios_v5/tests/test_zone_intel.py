"""Zone Intelligence — origin / strength / lifecycle / health / battle /
acceptance / probability / HTF / explanation / card."""

from mios_v5.zone_intel import (acceptance, advance, battle, build_zone_card,
                                explain, health, htf_alignment, origin,
                                probabilities, stars, strength, is_dangerous)


def test_stars_scale():
    assert stars(100) == "★★★★★"
    assert stars(0) == "★☆☆☆☆"        # a real level always earns one star
    assert stars(None) == "☆☆☆☆☆"     # unknown is not the same as weak
    assert len(stars(55)) == 5


def test_origin_counts_families_not_tags():
    many_same = origin(["MF-POC", "W-POC", "D-POC"])          # 1 family
    diverse = origin(["MF-POC", "OI-CE", "Round", "PDH"])     # 4 families
    assert many_same["family_count"] == 1
    assert diverse["family_count"] == 4
    assert diverse["score"] > many_same["score"]


def test_strength_touch_curve():
    base = origin(["MF-POC", "OI-CE"])["score"]
    unproven = strength(base, touches=0)["score"]
    proven = strength(base, touches=2)["score"]
    worn = strength(base, touches=7)["score"]
    assert proven > unproven > worn
    assert strength(base, touches=2)["touch_note"] == "proven"


def test_lifecycle_machine():
    # fresh level away from price, never tested
    assert advance("created", at_zone=False, broken=False, touches=0) == "untested"
    # at the zone with defenders piling in
    assert advance("untested", at_zone=True, broken=False, building=3, fading=0) == "building"
    # groups fighting each other
    assert advance("building", at_zone=True, broken=False, building=2, fading=2) == "under-attack"
    # everyone leaving while price sits on it
    assert advance("under-attack", at_zone=True, broken=False, building=0, fading=3) == "breaking"
    # closed through
    assert advance("breaking", at_zone=True, broken=True) == "broken"
    # the post-break arc
    assert advance("broken", at_zone=True, broken=True) == "retest"
    assert advance("retest", at_zone=True, broken=True, reclaimed=True) == "recovered"
    assert advance("broken", at_zone=False, broken=True, far_away=True, age_cycles=99) == "retired"


def test_dangerous_states():
    assert is_dangerous("breaking") and is_dangerous("broken")
    assert is_dangerous("under-attack") and not is_dangerous("building")


def test_health_five_groups_and_conflict():
    all_build = health({"spot": "building", "options": "building", "dealers": "building",
                        "institutions": "building", "liquidity": "building"})
    assert all_build["pct"] == 100 and all_build["aligned"] and not all_build["conflicted"]
    split = health({"spot": "building", "options": "fading"})
    assert split["conflicted"] and not split["aligned"]
    assert health(None)["pct"] == 50          # all neutral = no information


def test_battle_flips_by_side():
    # same strong level: at support the defenders are BUYERS, at resistance SELLERS
    sup = battle("SUPPORT", 85, dir_score=0.0, health_pct=80)
    res = battle("RESISTANCE", 85, dir_score=0.0, health_pct=80)
    assert sup["winner"] == "Buyers" and res["winner"] == "Sellers"
    assert sup["buyer"] + sup["seller"] == 100


def test_battle_war_zone_when_close():
    b = battle("SUPPORT", 50, dir_score=0.0, health_pct=50)
    assert b["war"] and b["winner"] == "Contested"


def test_acceptance_states():
    # price beyond support while defenders still strong → trap
    assert acceptance("SUPPORT", 23800, 23900, health_pct=80)["state"] == "trap"
    # closed beyond with weak defenders → accepted
    assert acceptance("SUPPORT", 23800, 23900, closed_beyond=True,
                      health_pct=20)["state"] == "accepted"
    # probed but back above → rejected
    assert acceptance("SUPPORT", 23905, 23900, pierced=True, health_pct=60)["state"] == "rejected"
    # sitting on it, nothing happened → defended
    assert acceptance("SUPPORT", 23902, 23900, health_pct=50)["state"] == "defended"


def test_probabilities_complement_and_trap():
    p = probabilities("SUPPORT", 80, 80, dir_score=0.0, lifecycle="building")
    assert p["break"] + p["rejection"] == 100
    strong = probabilities("SUPPORT", 85, 85, lifecycle="building")
    weak = probabilities("SUPPORT", 20, 20, lifecycle="breaking")
    assert weak["break"] > strong["break"]
    # an active trap read lifts trap probability
    t_yes = probabilities("SUPPORT", 70, 70, acceptance_state="trap")
    t_no = probabilities("SUPPORT", 70, 70, acceptance_state="accepted")
    assert t_yes["trap"] > t_no["trap"]


def test_htf_alignment_matches_within_tolerance():
    h = htf_alignment(23700, {"1H POC": 23705, "4H VAH": 23698,
                              "Daily HVN": 23702, "Weekly OB": 24100})
    assert h["count"] == 3 and "Weekly OB" not in h["matches"]
    assert htf_alignment(None, {"1H POC": 1})["count"] == 0


def test_explain_is_short_and_names_sources():
    org = origin(["MF-POC", "OI-CE", "Gamma", "Round"])
    hl = health({"dealers": "building", "institutions": "building"})
    btl = battle("RESISTANCE", 80, health_pct=hl["pct"])
    acc = acceptance("RESISTANCE", 23690, 23700, health_pct=hl["pct"])
    probs = probabilities("RESISTANCE", 80, hl["pct"])
    e = explain("RESISTANCE", org, hl, btl, acc, probs, invalidation=23715)
    assert 0 < len(e["why"]) <= 6 and e["expect"]
    assert "Dealer Gamma Wall" in e["why"] or "Heavy Call OI" in e["why"]


def test_build_zone_card_end_to_end():
    zone = {"price": 23700, "strength": 82, "status": "holding",
            "sources": ["MF-POC", "OI-CE", "Round", "PDH"],
            "zone_health": {"spot": "building", "options": "fading",
                            "dealers": "building", "institutions": "building"}}
    card = build_zone_card("RESISTANCE", zone, 23695, dir_score=-0.2,
                           htf_levels={"1H POC": 23702, "4H VAH": 23698,
                                       "Daily HVN": 23705},
                           touches=2)
    for k in ("origin", "strength", "lifecycle", "health", "battle",
              "acceptance", "probabilities", "htf", "explain", "invalidation"):
        assert k in card
    assert card["price"] == 23700 and card["side"] == "RESISTANCE"
    assert card["probabilities"]["break"] + card["probabilities"]["rejection"] == 100
    assert card["health"]["conflicted"]          # options fading vs the rest
    assert card["htf"]["count"] == 3
    assert card["at_zone"] is True
    assert build_zone_card("SUPPORT", None, 23695) is None


if __name__ == "__main__":
    for fn in [test_stars_scale, test_origin_counts_families_not_tags,
               test_strength_touch_curve, test_lifecycle_machine,
               test_dangerous_states, test_health_five_groups_and_conflict,
               test_battle_flips_by_side, test_battle_war_zone_when_close,
               test_acceptance_states, test_probabilities_complement_and_trap,
               test_htf_alignment_matches_within_tolerance,
               test_explain_is_short_and_names_sources,
               test_build_zone_card_end_to_end]:
        fn()
    print("zone intelligence tests passed")
