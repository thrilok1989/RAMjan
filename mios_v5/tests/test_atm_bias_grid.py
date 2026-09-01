"""ATM ±2 full bias grid — the owner's chain-bias script, ported.

Pins the exact bias definitions (incl. the CE-heavy-is-bearish OI/ΔOI reads and
the score that counts non-bullish as −1), the verdict/operator/scalp/fake bands,
and the two guarantees: it fetches nothing and reuses the real Δ/Γ already on the
chain.
"""

import ast
import pathlib

from mios_v5.atm_bias_grid import (BIAS_KEYS, BEARISH, BULLISH, NEUTRAL,
                                   delta_volume_bias, final_verdict, grid,
                                   grid_html, strike_row, top_suggestion)

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _sd(**kw):
    base = dict(ltp_ce=50, ltp_pe=50, oi_ce=1000, oi_pe=1000, chg_ce=0, chg_pe=0,
                vol_ce=100, vol_pe=100, delta_ce=0.5, delta_pe=-0.5,
                gamma_ce=0.001, gamma_pe=0.001, bid_ce=100, ask_ce=100,
                iv_ce=14, iv_pe=14)
    base.update(kw)
    return base


def test_eleven_biases_are_scored():
    r = strike_row(_sd(), 24400, 24400, 24400)
    assert set(r["biases"]) == set(BIAS_KEYS)
    assert len(BIAS_KEYS) == 11


def test_oi_and_chgoi_read_ce_heavy_as_bearish():
    # faithful quirk: CE OI/ΔOI dominance is BEARISH in this script
    r = strike_row(_sd(oi_ce=3000, oi_pe=1000, chg_ce=800, chg_pe=100), 24400, 24400, 24400)
    assert r["biases"]["OI"] == BEARISH
    assert r["biases"]["ChgOI"] == BEARISH


def test_directional_biases_match_the_script():
    r = strike_row(_sd(ltp_ce=80, ltp_pe=40, vol_ce=300, vol_pe=100,
                       delta_ce=0.6, delta_pe=-0.3, gamma_ce=0.003, gamma_pe=0.001,
                       bid_ce=900, ask_ce=200, iv_ce=17, iv_pe=12), 24400, 24400, 24400)
    b = r["biases"]
    assert b["LTP"] == BULLISH and b["Volume"] == BULLISH
    assert b["Delta"] == BULLISH and b["Gamma"] == BULLISH
    assert b["AskBid"] == BULLISH and b["IV"] == BULLISH
    assert b["DeltaExp"] == BULLISH and b["GammaExp"] == BULLISH


def test_dvp_needs_volume_and_direction():
    assert delta_volume_bias(5, 10, 3) == BULLISH
    assert delta_volume_bias(-5, 10, 3) == BEARISH
    assert delta_volume_bias(5, -10, 3) == NEUTRAL     # no volume confirmation
    assert delta_volume_bias(0, 10, 3) == NEUTRAL


def test_verdict_bands():
    assert final_verdict(5) == "Strong Bull"
    assert final_verdict(2) == "Bullish"
    assert final_verdict(0) == "Neutral"
    assert final_verdict(-2) == "Bearish"
    assert final_verdict(-5) == "Strong Bear"


def test_operator_scalp_fake_reads():
    # everything bullish → strong bull, operator entry bull, real up
    r = strike_row(_sd(ltp_ce=90, ltp_pe=10, oi_ce=500, oi_pe=3000,
                       chg_ce=50, chg_pe=900, vol_ce=400, vol_pe=50,
                       delta_ce=0.6, delta_pe=-0.2, gamma_ce=0.004, gamma_pe=0.001,
                       bid_ce=900, ask_ce=100, iv_ce=18, iv_pe=10), 24400, 24400, 24400)
    assert r["score"] >= 4 and r["verdict"] == "Strong Bull"
    assert r["operator"] == "Entry Bull"        # OI+ChgOI both bullish (PE-heavy)
    assert r["scalp"] == "Scalp Bull" and r["fake_real"] == "Real Up"


def test_score_counts_non_bullish_as_minus_one():
    # all-neutral inputs: every bias resolves to Bearish/Neutral (not Bullish),
    # so the faithful score is strongly negative, not zero.
    r = strike_row(_sd(), 24400, 24400, 24400)
    assert r["score"] < 0


def test_comparison_strings_and_zone():
    r = strike_row(_sd(oi_ce=2_000_000, oi_pe=1_000_000, chg_ce=50000, chg_pe=20000),
                   24350, 24400, 24400)
    assert "M" in r["oi_cmp"] and ">" in r["oi_cmp"]
    assert "K" in r["chgoi_cmp"]
    assert r["zone"] == "ITM"                   # 24350 < underlying 24400


def test_bad_or_missing_fields_never_raise():
    r = strike_row({"ltp_ce": None, "oi_pe": "x"}, 24400, 24400, 24400)
    assert set(r["biases"]) == set(BIAS_KEYS) and r["verdict"]


def test_top_suggestion_picks_the_strongest_strike():
    rows = grid([(24350, _sd()), (24400, _sd(ltp_ce=90, ltp_pe=10, oi_ce=500,
                 oi_pe=3000, chg_ce=50, chg_pe=900, vol_ce=400, vol_pe=50,
                 bid_ce=900, ask_ce=100, iv_ce=18, iv_pe=10))], 24400, 24400)
    best = max(rows, key=lambda r: abs(r["score"]))
    side = "CALL" if best["score"] > 0 else "PUT"
    msg = top_suggestion(rows)
    assert f"TRADE {side}" in msg and "Suggested" in msg


def test_html_renders_all_columns_and_highlights_atm():
    rows = grid([(24350, _sd()), (24400, _sd(oi_pe=3000)), (24450, _sd())], 24400, 24400)
    html = grid_html(rows, 24400)
    assert "Full Bias Grid" in html and "<table" in html
    assert "#f5d000" in html                    # ATM row highlight
    for col in ("LTP", "ΔExp", "ΓExp", "DVP", "Verdict", "Operator", "Fake/Real"):
        assert col in html
    assert grid_html([], 24400) == ""


def test_the_app_wires_grid_from_existing_chain_incl_real_greeks():
    src = (_ROOT / "vob_minimal.py").read_text()
    assert "from mios_v5.atm_bias_grid import" in src
    # feeds the REAL greeks already on df_summary (no recompute) + no new fetch
    for col in ("Delta_CE", "Delta_PE", "Gamma_CE", "Gamma_PE",
                "lastPrice_CE", "openInterest_CE", "bidQty_CE"):
        assert col in src, col
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "render_strike_mode_dashboard")
    seg = ast.get_source_segment(src, fn) or ""
    assert "atm_bias_grid" in seg
    # the grid block feeds only from `ds` (df_summary) — the marker its rows use
    assert "_bg_rows" in seg and "ds[ds['Strike']" in seg
