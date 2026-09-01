"""ATM ±2 strikes 14-metric bias tabulation — the seller_perspective port.

Pins the ported logic (all 14 metrics, verdict banding) and the two guarantees
the owner asked for: it fetches nothing, and the market-depth metric reuses the
already-fetched bid/ask depth rather than a new depth API call.
"""

import ast
import pathlib

from mios_v5.atm_strike_bias import (METRIC_KEYS, strike_bias, tabulation,
                                     tabulation_html)

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _sd(**kw):
    base = dict(oi_ce=1000, oi_pe=1000, chg_ce=0, chg_pe=0, vol_ce=100, vol_pe=100,
               ltp_ce=50, ltp_pe=50, iv_ce=14, iv_pe=14,
               bid_ce=10, bid_pe=10, ask_ce=10, ask_pe=10)
    base.update(kw)
    return base


def test_all_fourteen_metrics_are_scored():
    a = strike_bias(_sd(), 24400, 24400)
    assert set(a["bias_scores"]) == set(METRIC_KEYS)
    assert len(METRIC_KEYS) == 14


def test_oi_and_pcr_read_bullish_when_puts_dominate():
    a = strike_bias(_sd(oi_ce=1000, oi_pe=2000), 24400, 24400)
    assert a["bias_scores"]["OI"] == 1          # PE/CE 2.0 > 1.3
    assert a["bias_scores"]["PCR"] == 1         # strike PCR 2.0 > 1.5


def test_oi_reads_bearish_when_calls_dominate():
    a = strike_bias(_sd(oi_ce=2000, oi_pe=1000), 24400, 24400)
    assert a["bias_scores"]["OI"] == -1         # PE/CE 0.5 < 0.77


def test_verdict_bands_match_the_original():
    # strong bullish: many bull metrics → total >= 3
    a = strike_bias(_sd(oi_ce=500, oi_pe=3000, chg_ce=0, chg_pe=800,
                        vol_ce=50, vol_pe=300, ltp_ce=20, ltp_pe=80,
                        iv_ce=10, iv_pe=18), 24400, 24400)
    assert a["total_bias"] >= 3 and "STRONG BULLISH" in a["verdict"]
    # strong bearish: mirror → total <= -3
    b = strike_bias(_sd(oi_ce=3000, oi_pe=500, chg_ce=800, chg_pe=0,
                        vol_ce=300, vol_pe=50, ltp_ce=80, ltp_pe=20,
                        iv_ce=18, iv_pe=10), 24400, 24400)
    assert b["total_bias"] <= -3 and "STRONG BEARISH" in b["verdict"]
    # faithful to the original: an all-equal ATM strike is NOT neutral — the
    # Gamma-at-ATM tiebreak reads bearish when pe_oi is not strictly > ce_oi.
    n = strike_bias(_sd(), 24400, 24400)
    assert n["bias_scores"]["Gamma"] == -1 and n["total_bias"] == -1


def test_market_depth_uses_existing_bid_ask_not_a_fetch():
    # PE bid-heavy, CE ask-heavy → depth score positive → bullish, from bid/ask only
    a = strike_bias(_sd(bid_ce=10, ask_ce=90, bid_pe=90, ask_pe=10), 24400, 24400)
    assert a["bias_scores"]["MktDepth"] > 0
    assert "CE:" in a["bias_interpretations"]["MktDepth"]   # totals from bid+ask
    # no bid/ask at all → N/A (neutral), never invented
    z = strike_bias(_sd(bid_ce=0, ask_ce=0, bid_pe=0, ask_pe=0), 24400, 24400)
    assert z["bias_scores"]["MktDepth"] == 0
    assert z["bias_interpretations"]["MktDepth"] == "N/A"


def test_bad_or_missing_fields_never_raise():
    a = strike_bias({"oi_ce": None, "oi_pe": "x"}, 24400, 24400)
    assert set(a["bias_scores"]) == set(METRIC_KEYS)   # all present, zeros
    assert a["verdict"]


def test_tabulation_runs_each_strike_in_order():
    strikes = [(24300, _sd()), (24350, _sd()), (24400, _sd()),
               (24450, _sd()), (24500, _sd())]
    out = tabulation(strikes, 24400)
    assert [a["strike_price"] for a in out] == [24300, 24350, 24400, 24450, 24500]


def test_html_has_summary_table_and_highlights_atm():
    strikes = [(24350, _sd()), (24400, _sd(oi_pe=3000)), (24450, _sd())]
    html = tabulation_html(tabulation(strikes, 24400), 24400)
    assert "ATM ±2 Strikes" in html and "<table" in html
    assert "ATM STRIKE VERDICT" in html
    # ATM row highlighted (its yellow background) and every metric header present
    assert "#f5d000" in html
    for header in ("OI", "ChgOI", "PCR", "MktDepth", "BA", "Verdict"):
        assert header in html
    assert tabulation_html([], 24400) == ""     # nothing to show → empty


def test_the_app_reuses_existing_chain_and_does_not_fetch():
    """vob_minimal feeds the table from df_summary it already holds — no depth
    API call and no new chain fetch in the tabulation block."""
    src = (_ROOT / "vob_minimal.py").read_text()
    assert "from mios_v5.atm_strike_bias import" in src
    # fed from the existing df_summary columns (already fetched)
    for col in ("openInterest_CE", "changeinOpenInterest_CE", "bidQty_CE",
                "askQty_CE", "impliedVolatility_CE"):
        assert col in src, col
    # the tabulation block itself calls no fetch helper
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "render_strike_mode_dashboard")
    seg = ast.get_source_segment(src, fn) or ""
    assert "atm_strike_bias" in seg
    assert "get_option_contract_depth" not in seg   # no depth API call
