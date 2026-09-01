"""Market snapshot for AI analysis — the one-click Telegram export.

Pins the formatter (sections, skip-when-empty, chunking) and the app wiring (a
button that gathers existing reads and sends, computing nothing new).
"""

import ast
import pathlib

from mios_v5.market_snapshot import CHUNK_LIMIT, build, chunks

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _full():
    return {"time": "07:31 IST", "spot": 24395.8, "regime": "SIDEWAYS",
            "p_up": 40, "p_down": 35, "p_side": 25, "breakout": 49,
            "rejection": 51, "support": 24351, "resistance": 24399,
            "war_zone": 24400, "vwap": 24380, "poc": 24352, "vah": 24398,
            "val": 24321, "oi_ce_wall": 24500, "oi_pe_wall": 24300,
            "magnet": 24400, "atm_verdict": "Strong Bullish", "atm_score": "+5",
            "pcr": "1.12", "doi_bias": "PUT writing", "call_mode": "Long Building",
            "put_mode": "Short Covering", "total_gex": "+137L",
            "gamma_flip": 24420, "gex_signal": "long gamma",
            "greek_behaviour": "UPWARD DRIFT", "cvd": "rising",
            "money_flow": "bullish", "level_acceptance": ["₹24,400 TESTING"],
            "global": "risk-on", "news": "neutral", "expected_winner": "Support holds"}


def test_build_has_all_sections_and_the_ai_ask():
    t = build(_full())
    for header in ("MARKET SNAPSHOT", "REGIME", "LEVELS", "OPTIONS",
                   "DEALER / GREEKS", "FLOW", "LEVEL ACCEPTANCE", "CONTEXT"):
        assert header in t
    assert "₹24,351" in t and "Strong Bullish" in t and "risk-on" in t
    assert "analyse this" in t.lower()          # the instruction for the AI


def test_empty_sections_are_skipped_not_blank():
    t = build({"spot": 24400, "regime": "UP"})
    assert "Spot: ₹24,400" in t and "REGIME" in t
    # nothing about levels/options/greeks when none were provided
    assert "LEVELS" not in t and "DEALER" not in t and "FLOW" not in t
    # still ends with the AI ask
    assert "analyse" in t.lower()


def test_build_is_safe_on_none_and_empty():
    assert "MARKET SNAPSHOT" in build(None)
    assert "MARKET SNAPSHOT" in build({})


def test_bad_numbers_are_dropped_not_rendered_as_junk():
    t = build({"spot": "x", "support": None, "poc": float("nan"), "regime": "UP"})
    assert "Spot:" not in t                      # unparseable spot dropped
    assert "REGIME" in t


def test_chunks_splits_long_text_and_labels_parts():
    small = build(_full())
    assert chunks(small) == [small]              # fits → single part, unlabelled
    big = "block\n\n" * 4000                      # well over the limit
    parts = chunks(big)
    assert len(parts) > 1
    assert all(len(p) <= CHUNK_LIMIT + 20 for p in parts)   # ~within the cap
    assert parts[0].startswith("(1/")            # labelled when split


def test_the_app_wires_a_button_that_reuses_existing_reads():
    src = (_ROOT / "vob_minimal.py").read_text()
    assert "from mios_v5.market_snapshot import" in src
    assert "_gather_market_snapshot" in src and "_send_market_snapshot" in src
    assert "st.sidebar.button" in src            # the button
    # gathers from already-published session objects, not a new fetch
    for key in ("_market_picture", "_gex_data", "_money_flow_data",
                "_full_market_read", "build_final_read"):
        assert key in src, key
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_gather_market_snapshot")
    seg = ast.get_source_segment(src, fn) or ""
    assert "get_intraday_data" not in seg        # no new fetch in the gather
