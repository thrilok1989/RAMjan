"""⚔️ Level Confluence — observational, level-specific, never advisory.

The layer answers one question per level: how many independent already-published
engines corroborate the S/R read. These tests pin the three properties that make
that answer trustworthy.

**Level-specific.** "Is delta bullish?" is the wrong question. Falling flow
supports a rejection at resistance and contradicts a break of it — same flow,
opposite meaning — so every case below is stated as an interaction, not a
direction.

**Missing is not disagreement.** Every component reports confirmed /
contradicted / not_reported, and the tally counts only sources that had data.
An absent money-flow profile early in a session must not mark a level down.

**Observational.** It cannot reach a verdict, a gate, or an order.
"""

from __future__ import annotations

import pytest

from mios_v5.level_confluence import (
    CONFIRMED,
    CONTRADICTED,
    DELTA_LABEL,
    HIGH,
    INSUFFICIENT,
    NOT_REPORTED,
    evaluate_leg,
    evaluate_level,
    flow_expectation,
    level_tolerance,
)


def _read(state, side, level):
    return {"state": state, "side": side, "level": level}


BUY_FLOW = {"delta_pct": 12.5}
SELL_FLOW = {"delta_pct": -12.5}


def _verdicts(row):
    return {k: v["verdict"] for k, v in row["components"].items()}


# ── 1-4 · resistance: the interaction decides, not the sign ────────────

def test_resistance_rejection_with_negative_flow_is_confirmed():
    row = evaluate_level(_read("REJECTING", "resistance", 110.0), 110.0,
                         delta=SELL_FLOW)
    assert _verdicts(row)["delta"] == CONFIRMED


def test_resistance_rejection_with_positive_flow_is_contradicted():
    row = evaluate_level(_read("REJECTING", "resistance", 110.0), 110.0,
                         delta=BUY_FLOW)
    assert _verdicts(row)["delta"] == CONTRADICTED


def test_resistance_breakout_with_positive_flow_is_confirmed():
    row = evaluate_level(_read("BREAKING", "resistance", 110.0), 110.0,
                         delta=BUY_FLOW)
    assert _verdicts(row)["delta"] == CONFIRMED


def test_resistance_breakout_with_negative_flow_is_contradicted():
    row = evaluate_level(_read("BREAKING", "resistance", 110.0), 110.0,
                         delta=SELL_FLOW)
    assert _verdicts(row)["delta"] == CONTRADICTED


# ── 5 · support mirrors it exactly ─────────────────────────────────────

@pytest.mark.parametrize("state,flow,want", [
    ("REJECTING", BUY_FLOW, CONFIRMED),      # bounced off support
    ("REJECTING", SELL_FLOW, CONTRADICTED),
    ("BREAKING", SELL_FLOW, CONFIRMED),      # broke down through support
    ("BREAKING", BUY_FLOW, CONTRADICTED),
])
def test_support_is_the_mirror_of_resistance(state, flow, want):
    row = evaluate_level(_read(state, "support", 90.0), 90.0, delta=flow)
    assert _verdicts(row)["delta"] == want


def test_the_same_flow_means_opposite_things_at_the_two_sides():
    """The whole reason this is not a generic direction check."""
    res = evaluate_level(_read("BREAKING", "resistance", 110.0), 110.0,
                         delta=BUY_FLOW)
    sup = evaluate_level(_read("BREAKING", "support", 110.0), 110.0,
                         delta=BUY_FLOW)
    assert _verdicts(res)["delta"] == CONFIRMED
    assert _verdicts(sup)["delta"] == CONTRADICTED


# ── 6 · proximity states make no directional claim ─────────────────────

@pytest.mark.parametrize("state", ["BUILDING", "ACCEPTING"])
@pytest.mark.parametrize("flow", [BUY_FLOW, SELL_FLOW])
@pytest.mark.parametrize("side", ["resistance", "support"])
def test_proximity_states_never_borrow_a_direction(state, flow, side):
    """BUILDING and ACCEPTING say price is AT a level, not that it resolved
    one. Flow direction cannot confirm or contradict that, so it is not
    scored — labelling them bullish because delta happens to be positive is
    exactly the false precision this avoids."""
    row = evaluate_level(_read(state, side, 100.0), 100.0, delta=flow,
                         zones=[{"lower": 99, "upper": 101, "bull_pct": 80.0}])
    v = _verdicts(row)
    assert v["delta"] == NOT_REPORTED
    assert v["cvd"] == NOT_REPORTED
    assert v["vob"] == NOT_REPORTED
    assert flow_expectation(state, side) is None


def test_proximity_states_still_report_structure_and_location():
    """They are not scoreless — where the level sits is still evidence."""
    row = evaluate_level(_read("BUILDING", "resistance", 100.0), 100.2,
                         mfp={"poc_price": 100.0})
    v = _verdicts(row)
    assert v["structure"] == CONFIRMED
    assert v["mfp"] == CONFIRMED


# ── 7-9 · missing data is never disagreement ───────────────────────────

def test_missing_mfp_is_not_counted():
    row = evaluate_level(_read("REJECTING", "resistance", 110.0), 110.0,
                         delta=SELL_FLOW)
    assert _verdicts(row)["mfp"] == NOT_REPORTED
    assert row["contradicted"] == 0


def test_missing_delta_is_not_counted():
    row = evaluate_level(_read("REJECTING", "resistance", 110.0), 110.0,
                         mfp={"poc_price": 110.0})
    assert _verdicts(row)["delta"] == NOT_REPORTED
    assert row["contradicted"] == 0


def test_missing_vob_is_not_counted():
    row = evaluate_level(_read("BREAKING", "resistance", 110.0), 110.0,
                         delta=BUY_FLOW)
    assert _verdicts(row)["vob"] == NOT_REPORTED
    assert row["contradicted"] == 0


def test_nothing_reported_at_all_is_insufficient_not_zero():
    row = evaluate_level(_read("BREAKING", "resistance", 110.0), None)
    assert row["quality"] == INSUFFICIENT
    assert row["contradicted"] == 0


def test_checked_counts_only_sources_with_data():
    row = evaluate_level(_read("REJECTING", "resistance", 110.0), 110.0,
                         mfp={"poc_price": 110.0},
                         hvn=[{"price": 110.0}],
                         zones=[{"lower": 109, "upper": 111, "bull_pct": 20.0}],
                         delta=SELL_FLOW)
    # structure, mfp, hvn, vob, delta = 5 reported; CVD is not published
    assert row["checked"] == 5
    assert row["confirmed"] == 5
    assert row["score"] == "5/5"
    assert row["quality"] == HIGH
    assert _verdicts(row)["cvd"] == NOT_REPORTED


# ── 10 · both sides always come back ───────────────────────────────────

def test_both_sides_are_returned_for_a_leg():
    sr = {"state": "BUILDING", "side": "resistance", "level": 109.88,
          "sides": {"resistance": _read("BUILDING", "resistance", 109.88),
                    "support": _read("REJECTING", "support", 104.2)}}
    rows = evaluate_leg(sr, 109.3, label="ATM CE 24250")
    assert [r["side"] for r in rows] == ["resistance", "support"]
    assert all(r["reported"] for r in rows)
    assert all(r["label"] == "ATM CE 24250" for r in rows)


def test_a_missing_side_is_reported_not_failed():
    sr = {"state": "BUILDING", "side": "support", "level": 58.83,
          "sides": {"support": _read("BUILDING", "support", 58.83)}}
    res, sup = evaluate_leg(sr, 58.9)
    assert res["reported"] is False
    assert res["score"] is None
    assert res["contradicted"] == 0
    assert sup["reported"] is True


def test_a_leg_with_no_read_reports_both_sides_unreported():
    for row in evaluate_leg(None, 100.0):
        assert row["reported"] is False
        assert row["confirmed"] == 0 and row["contradicted"] == 0


# ── 14 · the tolerance is the classifier's, unchanged ──────────────────

def test_tolerance_matches_the_classifier_exactly():
    """`max(LTP * 0.005, 0.50)`. If these drifted, a level the classifier
    calls BUILDING could be reported here as far from its own POC."""
    for ltp in (58.9, 109.3, 24400.0, 10.0, 0.0):
        assert level_tolerance(ltp) == max(ltp * 0.005, 0.5)
    assert level_tolerance(None) == 0.5


def test_the_tolerance_is_what_decides_nearness():
    tol = level_tolerance(109.3)          # 0.5465
    near = evaluate_level(_read("BUILDING", "resistance", 109.88), 109.4)
    far = evaluate_level(_read("BUILDING", "resistance", 109.88), 105.0)
    assert abs(109.4 - 109.88) <= tol
    assert _verdicts(near)["structure"] == CONFIRMED
    assert _verdicts(far)["structure"] == CONTRADICTED


# ── 15 · deterministic ─────────────────────────────────────────────────

def test_identical_inputs_give_identical_output():
    kw = dict(ltp=110.0, mfp={"poc_price": 110.0}, hvn=[{"price": 110.0}],
              zones=[{"lower": 109, "upper": 111, "bull_pct": 20.0}],
              delta=SELL_FLOW)
    a = evaluate_level(_read("REJECTING", "resistance", 110.0), **kw)
    b = evaluate_level(_read("REJECTING", "resistance", 110.0), **kw)
    assert a == b


# ── the delta is labelled as the estimate it is ────────────────────────

def test_delta_is_labelled_a_proxy_not_measured():
    """The split is inferred from 1-minute OHLC via CLV, not from tick or
    lower-timeframe data. Calling it measured delta would overstate it."""
    assert "proxy" in DELTA_LABEL.lower()
    row = evaluate_level(_read("BREAKING", "resistance", 110.0), 110.0,
                         delta=BUY_FLOW)
    assert DELTA_LABEL in row["components"]["delta"]["note"]


def test_cvd_is_not_faked_from_delta():
    """`order_flow.totals` publishes no CVD. Deriving one from delta would
    double-count the same evidence under two names."""
    row = evaluate_level(_read("BREAKING", "resistance", 110.0), 110.0,
                         delta={"delta_pct": 40.0, "delta": 900.0})
    assert _verdicts(row)["cvd"] == NOT_REPORTED


def test_a_published_cvd_would_be_used():
    row = evaluate_level(_read("BREAKING", "resistance", 110.0), 110.0,
                         delta={"delta_pct": 5.0, "cvd": 120.0})
    assert _verdicts(row)["cvd"] == CONFIRMED


# ── labels are explanatory, never advisory ─────────────────────────────

def test_quality_labels_never_advise():
    from mios_v5 import level_confluence as lc
    banned = ("BUY", "SELL", "ENTRY", "TRADE", "PROFIT", "TARGET")
    for label in (lc.HIGH, lc.MODERATE, lc.LOW, lc.MIXED, lc.INSUFFICIENT):
        for word in banned:
            assert word not in label.upper(), label


def test_the_score_is_a_tally_not_a_probability():
    row = evaluate_level(_read("REJECTING", "resistance", 110.0), 110.0,
                         mfp={"poc_price": 110.0}, delta=SELL_FLOW)
    assert isinstance(row["score"], str) and "/" in row["score"]
    assert not isinstance(row["score"], float)


# ── 13 · it cannot reach a decision path ───────────────────────────────

def test_the_module_imports_nothing_impure():
    """No Streamlit, no network, no I/O — checked on the parsed imports rather
    than on substrings, because prose like "exist." matches a naive "st." scan
    and a test that fails on its own docstring teaches nobody anything."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "level_confluence.py").read_text()
    banned = {"streamlit", "requests", "urllib", "httpx", "socket",
              "sqlite3", "os", "subprocess"}
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & banned), imported & banned


def test_the_module_touches_no_shared_state():
    """Reads its inputs, returns its output. No session, no globals mutated."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "level_confluence.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            owner = node.value
            if isinstance(owner, ast.Name) and owner.id in ("st", "session_state"):
                raise AssertionError(f"touches {owner.id}.{node.attr}")
        if isinstance(node, ast.Global):
            raise AssertionError("declares a global")


def test_no_decision_path_imports_the_confluence_module():
    """Observational means unreachable from anything that decides. If a gate
    or a verdict ever imports this, that is the change to catch."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    decision_files = [
        root / "mios_v5" / "final_read.py",
        root / "mios_v5" / "entry_alignment.py",
        root / "mios_v5" / "runner.py",
    ]
    for path in decision_files:
        if path.exists():
            assert "level_confluence" not in path.read_text(), path.name


# ── a blank row has to say WHICH kind of blank ─────────────────────────

def test_the_reason_is_carried_onto_unreported_rows():
    """Four rows of "no valid level" that cannot explain themselves are
    indistinguishable from a broken table — the same defect this app has now
    hit twice. The reason comes from the owner that already computes it."""
    rows = evaluate_leg(None, 109.3, label="CE", reason="no_blocks")
    assert all(not r["reported"] for r in rows)
    assert all(r["reason"] == "no_blocks" for r in rows)


def test_a_reported_row_keeps_its_own_reason():
    """The passthrough must not stamp over a level that WAS evaluated."""
    sr = {"sides": {"resistance": _read("BUILDING", "resistance", 109.88)}}
    res, sup = evaluate_leg(sr, 109.3, reason="no_blocks")
    assert res["reported"] and res.get("reason") != "no_blocks"
    assert not sup["reported"] and sup["reason"] == "no_blocks"


def test_no_reason_supplied_still_renders():
    for row in evaluate_leg(None, 109.3):
        assert not row["reported"]


def test_the_renderer_explains_each_kind_of_blank():
    import re
    from mios_v5.ui.level_confluence_table import build_table

    def text(sr, zones):
        html = build_table([{"label": "CE", "ltp": 109.3, "sr": sr,
                             "zones": zones}], theme="dark")
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))

    assert "no read published" in text(None, None)
    assert "28+" in text({"state": "NONE", "sides": {}}, None)
    assert "tested side" in text({"state": "NONE", "sides": {}},
                                 [{"mid": 130.0}])


def test_both_tables_word_a_blank_the_same_way():
    """One set of wordings, one owner — or the two tables start describing
    the same state differently."""
    from mios_v5.ui.leg_sr_table import _NO_LEVEL_REASONS
    from mios_v5.ui.level_confluence_table import _reason_text
    for key, wording in _NO_LEVEL_REASONS.items():
        rendered = _reason_text(key)
        core = wording.split("—")[-1].strip().lower()
        assert core[:12] in rendered.lower(), (key, rendered)


# ── OI: fresh positioning vs unwinding, never a direction ──────────────

OI_UP = {"oi": 4.2e6, "chg_oi": 320000}
OI_DOWN = {"oi": 4.2e6, "chg_oi": -180000}


def test_rising_oi_confirms_and_falling_oi_contradicts():
    """Not "is OI bullish" — that has no answer without knowing who wrote
    what. Fresh positioning corroborates an interaction; unwinding is the
    same price doing less work."""
    up = evaluate_level(_read("REJECTING", "resistance", 110.0), 110.0, oi=OI_UP)
    down = evaluate_level(_read("REJECTING", "resistance", 110.0), 110.0,
                          oi=OI_DOWN)
    assert _verdicts(up)["oi"] == CONFIRMED
    assert _verdicts(down)["oi"] == CONTRADICTED


def test_oi_reads_the_same_whichever_way_the_level_points():
    """Direction-neutral by design: the same ΔOI must not flip meaning
    between a break and a rejection."""
    for state in ("REJECTING", "BREAKING"):
        for side in ("resistance", "support"):
            row = evaluate_level(_read(state, side, 110.0), 110.0, oi=OI_UP)
            assert _verdicts(row)["oi"] == CONFIRMED, (state, side)


@pytest.mark.parametrize("state", ["BUILDING", "ACCEPTING"])
def test_oi_is_scored_for_proximity_states_too(state):
    """The one flow-family column that means something for BUILDING:
    "positions building here" is exactly what the state describes, and it
    needs no direction to say so."""
    row = evaluate_level(_read(state, "resistance", 110.0), 110.0, oi=OI_UP)
    assert _verdicts(row)["oi"] == CONFIRMED
    assert _verdicts(row)["depth"] == NOT_REPORTED   # depth still abstains


def test_missing_or_flat_oi_is_not_counted():
    for oi in (None, {}, {"oi": 4.2e6}, {"chg_oi": 0}):
        row = evaluate_level(_read("REJECTING", "resistance", 110.0), 110.0,
                             oi=oi)
        assert _verdicts(row)["oi"] == NOT_REPORTED, oi
        assert row["contradicted"] == 0


def test_oi_note_names_what_it_saw():
    row = evaluate_level(_read("REJECTING", "resistance", 110.0), 110.0,
                         oi=OI_UP)
    assert "fresh" in row["components"]["oi"]["note"]


# ── Depth: resting size, directional like delta ────────────────────────

ASK_HEAVY = {"bid_qty": 900, "ask_qty": 2400}
BID_HEAVY = {"bid_qty": 2400, "ask_qty": 900}


def test_depth_confirms_the_interaction_not_a_direction():
    """Ask-heavy is sellers waiting: it supports a rejection at resistance
    and contradicts a break of it — the same rule delta follows."""
    rej = evaluate_level(_read("REJECTING", "resistance", 110.0), 110.0,
                         depth=ASK_HEAVY)
    brk = evaluate_level(_read("BREAKING", "resistance", 110.0), 110.0,
                         depth=ASK_HEAVY)
    assert _verdicts(rej)["depth"] == CONFIRMED
    assert _verdicts(brk)["depth"] == CONTRADICTED


def test_depth_mirrors_at_support():
    row = evaluate_level(_read("REJECTING", "support", 90.0), 90.0,
                         depth=BID_HEAVY)
    assert _verdicts(row)["depth"] == CONFIRMED


@pytest.mark.parametrize("state", ["BUILDING", "ACCEPTING"])
def test_depth_abstains_on_proximity_states(state):
    row = evaluate_level(_read(state, "resistance", 110.0), 110.0,
                         depth=ASK_HEAVY)
    assert _verdicts(row)["depth"] == NOT_REPORTED


def test_missing_or_balanced_depth_is_not_counted():
    for depth in (None, {}, {"bid_qty": 0, "ask_qty": 0},
                  {"bid_qty": 500, "ask_qty": 500}, {"bid_qty": 500}):
        row = evaluate_level(_read("REJECTING", "resistance", 110.0), 110.0,
                             depth=depth)
        assert _verdicts(row)["depth"] == NOT_REPORTED, depth
        assert row["contradicted"] == 0


def test_depth_note_quantifies_the_imbalance():
    row = evaluate_level(_read("REJECTING", "resistance", 110.0), 110.0,
                         depth=ASK_HEAVY)
    assert "x" in row["components"]["depth"]["note"]


# ── they are contract-level, and the module says so ────────────────────

def test_oi_and_depth_are_marked_contract_level():
    """Neither can say whether ₹109.88 is a real resistance for that call —
    they describe the contract. Flagging that in the module is what stops
    them being read as structural evidence about the level."""
    from mios_v5.level_confluence import CONTRACT_LEVEL, COMPONENTS
    assert set(CONTRACT_LEVEL) == {"oi", "depth"}
    assert set(CONTRACT_LEVEL) <= set(COMPONENTS)


def test_both_new_columns_have_headings():
    from mios_v5.ui.level_confluence_table import HEADINGS
    from mios_v5.level_confluence import COMPONENTS
    assert set(HEADINGS) == set(COMPONENTS)


# ── the table must read its producer's CURRENT cycle ───────────────────

def test_confluence_is_filled_after_its_producer():
    """`_premium_structures` — the HVN/LVN input — is published by
    `_trading_screen`, which runs AFTER `_charts_screen`. Rendering the table
    inline on the charts screen read nothing on the first render and the
    PREVIOUS cycle's copy on every render after: the exact fault the
    dependency ordering was introduced to fix for the cockpits.

    So the charts screen claims a container and the fill happens later. This
    pins that order, because inlining it again would look harmless.
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "ui" / "dashboard_v6.py").read_text()

    trading = src.index("_trading_screen(st, fr, state)")
    fill = src.index("render_level_confluence(st)", trading)
    assert fill > trading, "confluence is filled before its producer runs"

    # and the charts screen only CLAIMS the slot, never renders into it
    charts = src.index("def _terminal_chart(")
    charts_end = src.index("\ndef ", charts + 10)
    body = src[charts:charts_end]
    assert '_lc_slot' in body, "the charts screen no longer claims the slot"
    assert "level_confluence_table" not in body, (
        "the charts screen renders the table inline again — it would read "
        "`_premium_structures` a cycle late")
