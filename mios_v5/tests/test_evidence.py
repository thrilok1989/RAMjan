"""Stage 53 — Evidence Correlation (families, not 34 votes)."""

from mios_v5.evidence import (EXCLUDED, FAMILIES, FAMILY_PRIORITY, bias_sign,
                              collapse_family, correlate, family_lines)


def _r(bias, conf=80, ok=True, tier=1):
    return {"bias": bias, "confidence": conf, "ok": ok, "tier": tier}


def test_family_priority_independent_of_member_count():
    # the bug this engine exists to fix: Institutions had MORE engines than
    # Dealer and so silently out-ranked it, inverting the spec ladder.
    assert FAMILY_PRIORITY["dealer"] > FAMILY_PRIORITY["institutions"]
    assert len(FAMILIES["institutions"]) > len(FAMILIES["dealer"])


def test_previously_unvoted_engines_are_now_mapped():
    mapped = {e for m in FAMILIES.values() for e in m}
    for eng in ("stage13_institutional", "stage02_structure",
                "stage20_macro", "stage35_reaction_zone"):
        assert eng in mapped


def test_meta_engine_is_excluded_not_counted_twice():
    assert "stage31_probability" in EXCLUDED
    mapped = {e for m in FAMILIES.values() for e in m}
    assert "stage31_probability" not in mapped


def test_collapse_agreeing_family_is_high_reliability():
    f = collapse_family("institutions", {
        "stage13_institutional": _r("BULL"), "stage25_intent": _r("STRONG_BULL"),
        "stage23_flows": _r("BULL"), "stage18_sector": _r("BULL")})
    assert f["direction"] == "BULL" and f["agreement"] == 100
    assert f["strength"] > 0 and f["n"] == 4 and f["coverage"] == 100
    # flows is EOD data → family is only as fresh as its laggard
    assert f["freshness"] == "OLD"


def test_internal_conflict_is_preserved_not_averaged_away():
    # OI bullish, IV bearish — the split IS the signal and must survive the
    # collapse. It shows up in BOTH strength (the lean nearly cancels) and
    # agreement/reliability — never as a confident single voice.
    united = collapse_family("options", {
        "stage12_options": _r("BULL", 80), "stage22_vix": _r("BULL", 80)})
    split = collapse_family("options", {
        "stage12_options": _r("BULL", 80), "stage22_vix": _r("BEAR", 80)})
    assert split["agreement"] < united["agreement"]
    # the dissenter SUBTRACTS instead of adding: (a+b) → (a−b), so a 2-member
    # family's lean drops to at most half when its minority flips
    assert split["strength"] <= united["strength"] / 2
    assert split["reliability"] != "HIGH"                  # trust is degraded
    assert united["reliability"] == "HIGH"


def test_majority_dissent_drops_reliability_to_low():
    # when the WEIGHT of dissent is real (not a minority voice), trust collapses
    f = collapse_family("institutions", {
        "stage13_institutional": _r("BULL", 80), "stage25_intent": _r("BEAR", 80),
        "stage23_flows": _r("BEAR", 80), "stage18_sector": _r("BULL", 80)})
    assert f["agreement"] <= 60 and f["reliability"] == "LOW"


def test_missing_family_reports_missing_not_neutral():
    f = collapse_family("dealer", {})
    assert f["status"] == "MISSING" and f["n"] == 0
    assert f["reliability"] == "LOW" and f["coverage"] == 0


def test_failed_engine_is_skipped():
    f = collapse_family("macro", {
        "stage19_global": _r("BULL", ok=False), "stage20_macro": _r("BULL"),
        "stage21_news": _r("BULL")})
    assert "stage19_global" not in f["members"] and f["n"] == 2


def test_correlate_collapses_orderflow_to_one_vote():
    # five ways of seeing selling must not become five bear votes
    corr = correlate({"stage14_orderflow": _r("STRONG_BEAR", 90)})
    of = corr["families"]["orderflow"]
    assert of["direction"] == "BEAR" and of["n"] == 1
    assert corr["dominant"] in ("BEAR", "STRONG_BEAR")


def test_correlate_dominant_and_conflict():
    allbull = {e: _r("BULL") for m in FAMILIES.values() for e in m}
    c = correlate(allbull)
    assert c["dominant"] in ("BULL", "STRONG_BULL")
    assert c["agreement_pct"] >= 90 and c["severity"] == "LOW"

    split = dict(allbull)
    for e in FAMILIES["dealer"]:
        split[e] = _r("STRONG_BEAR", 95)
    for e in FAMILIES["orderflow"]:
        split[e] = _r("STRONG_BEAR", 95)
    c2 = correlate(split)
    assert c2["severity"] in ("MEDIUM", "HIGH")
    assert c2["agreement_pct"] < c["agreement_pct"]


def test_low_reliability_family_speaks_more_quietly():
    # same direction+confidence, but one family internally split → less sway
    clean = correlate({"stage12_options": _r("BULL", 90),
                       "stage22_vix": _r("BULL", 90)})
    split = correlate({"stage12_options": _r("BULL", 90),
                       "stage22_vix": _r("BEAR", 90)})
    assert clean["bull_weight"] > split["bull_weight"]


def test_unmapped_engines_are_reported():
    c = correlate({"stage99_new_thing": _r("BULL"), "stage11_dealer": _r("BULL")})
    assert "stage99_new_thing" in c["unmapped"]
    assert "stage11_dealer" not in c["unmapped"]


def test_excluded_engines_are_not_flagged_unmapped():
    c = correlate({"stage31_probability": _r("BULL")})
    assert c["unmapped"] == []


def test_bias_sign_scale():
    assert bias_sign("STRONG_BULL") == 2 and bias_sign("BEAR") == -1
    assert bias_sign("NONE") == 0 and bias_sign(None) == 0


def test_family_lines_are_scannable():
    lines = family_lines(correlate({e: _r("BEAR") for m in FAMILIES.values()
                                    for e in m}))
    assert len(lines) == 7 and all("🔴" in ln for ln in lines)


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"evidence correlation tests passed ({len(fns)})")
