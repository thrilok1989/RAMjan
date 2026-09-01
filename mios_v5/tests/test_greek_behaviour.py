"""🧲 The Greek Behaviour Interpretation Layer.

It must read as an *interpretation* of Greek data the app already computes — not
another engine. So the tests are mostly about what it must NOT do: compute a
Greek, invent a level, emit a trade, or touch the Guardian verdict. The rest pin
the behavioural mapping (positive gamma → CHOP, negative → EXPANSION, charm →
time pressure, vanna → IV/direction only) and the safety rules (missing →
"Not reported", stale flagged).
"""

from __future__ import annotations

import ast
import pathlib

from mios_v5 import greek_behaviour as GB
from mios_v5.ui import greek_behaviour_panel as GP

_ROOT = pathlib.Path(__file__).resolve().parents[2]
NR = GB.NOT_REPORTED


# ── it is an interpreter, not an engine ────────────────────────────────

def test_it_computes_no_greek_and_owns_no_market_fact():
    """No pricing/Greek math, no producer calls, no data libraries — every number
    arrives as a parameter (rules 1-5)."""
    tree = ast.parse((_ROOT / "mios_v5" / "greek_behaviour.py").read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imported.add((n.module or "").split(".")[0])
    assert not (imported & {"pandas", "numpy", "scipy", "math", "requests",
                            "streamlit", "vob_minimal"})
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(tree) if isinstance(c, ast.Call)}
    # it must not re-run any existing Greek/dealer producer
    for producer in ("calculate_dealer_gex", "calculate_dealer_dex",
                     "calculate_vanna_charm_exposure", "calculate_greeks",
                     "calculate_vanna_charm", "norm"):
        assert producer not in called, f"{producer} — this must not compute Greeks"
    # nor define its own calculator
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)}
    assert not any(d.startswith("calculate_") or d.endswith("_greeks")
                   for d in defined)


def test_it_never_emits_a_trade_or_touches_the_verdict():
    """No BUY/SELL anywhere, and context_only is always True (rules 6-8)."""
    read = GB.interpret(spot=24460, pull_level=24400, pull_source="max pain",
                        net_charm=-36.2, net_vanna=-120.0, total_gex=180.0,
                        is_expiry=False)
    assert read["context_only"] is True
    blob = repr(read).lower()
    for banned in ("buy", "sell", "verdict", "entry", "exit"):
        assert banned not in blob, f"'{banned}' must not appear in a context read"


# ── gamma: chop vs expansion ───────────────────────────────────────────

def test_positive_gamma_is_chop_pin():
    r = GB.gamma_regime(180.0)
    assert r["regime"] == "CHOP / PIN"
    assert "mean reversion" in r["text"]
    assert GB.gamma_regime(250.0)["strength"] == "strong"


def test_negative_gamma_is_expansion():
    r = GB.gamma_regime(-180.0)
    assert r["regime"] == "EXPANSION"
    assert "reinforce" in r["text"]
    assert GB.gamma_regime(-250.0)["strength"] == "strong"


def test_near_flat_gamma_is_balanced_not_a_forced_call():
    assert GB.gamma_regime(3.0)["regime"] == "BALANCED"


def test_missing_gamma_is_not_reported_never_zero():
    r = GB.gamma_regime(None)
    assert r["regime"] == NR and r["text"] == NR


# ── charm drives time pressure ─────────────────────────────────────────

def test_charm_drives_time_pressure_direction_and_elevation():
    down = GB.time_pressure(-36.2)
    assert down["direction"] == "downward"
    up = GB.time_pressure(40.0)
    assert up["direction"] == "upward"
    # near expiry + large charm → ELEVATED
    hot = GB.time_pressure(-390.9, is_expiry=True)
    assert hot["strength"] == "ELEVATED"
    assert "expiry" in hot["text"]
    # tiny charm is not a material drift
    assert GB.time_pressure(2.0)["strength"] == "low"


def test_missing_charm_time_pressure_is_not_reported():
    assert GB.time_pressure(None)["strength"] == NR


# ── vanna is IV/direction only, never a trade ──────────────────────────

def test_vanna_reads_iv_direction_interaction_only():
    hi = GB.vol_pressure(250.0)
    assert hi["strength"] == "HIGH" and hi["direction"] == "upside"
    lo = GB.vol_pressure(-250.0)
    assert lo["direction"] == "downside"
    assert "IV" in hi["text"] and "reinforce" in hi["text"]
    # weak vanna → LOW, explicitly "unlikely to materially alter"
    weak = GB.vol_pressure(10.0)
    assert weak["strength"] == "LOW" and "unlikely" in weak["text"]
    # never a trade
    assert "buy" not in hi["text"].lower() and "sell" not in hi["text"].lower()


def test_vanna_does_not_set_the_gamma_regime():
    """Vanna belongs to the volatility read; it must not leak into chop/expansion,
    which is gamma's alone."""
    only_vanna = GB.interpret(net_vanna=300.0)
    assert only_vanna["gamma"]["regime"] == NR
    assert only_vanna["vol"]["strength"] == "HIGH"


# ── expansion risk from gamma; positive gamma absorbs ──────────────────

def test_positive_gamma_makes_expansion_risk_low():
    assert GB.expansion_risk(180.0)["level"] == "LOW"
    assert "absorbing" in GB.expansion_risk(180.0)["text"]


def test_negative_gamma_raises_expansion_risk():
    assert GB.expansion_risk(-250.0)["level"] == "HIGH"


# ── pull is a pull, and never invented ─────────────────────────────────

def test_pull_is_a_pull_not_support_or_resistance():
    p = GB.pull(24460, 24400, "max pain", net_charm=-120.0)
    assert p["direction"] == "downward" and "pull" in p["text"]
    assert "support" not in p["text"] and "resistance" not in p["text"]
    assert p["strength"] == "strong"          # |charm| ≥ 100


def test_pull_never_invents_a_level():
    """No level handed in → Not reported, never a fabricated strike (rule 11)."""
    p = GB.pull(24460, None, "max pain", net_charm=-120.0)
    assert p["level"] == NR and p["text"] == NR


# ── higher-order Greeks stay contextual and honest ─────────────────────

def test_missing_greeks_are_not_reported_never_zero():
    r = GB.interpret(total_gex=100.0)          # no contextual greeks handed in
    for g in GB.CONTEXTUAL_GREEKS:
        assert r["greeks"][g] == NR, g
    assert "vega" not in GB.CONTEXTUAL_GREEKS   # vega is promoted, not contextual
    # zero is a real reading and is kept, not turned into "Not reported"
    assert GB.interpret(vomma=0.0)["greeks"]["vomma"] == 0.0


def test_contextual_greeks_never_create_direction_or_a_regime():
    """Speed/Color/Zomma/Veta/Vomma are context — handing them in must not change
    the gamma regime or invent a direction."""
    base = GB.interpret(total_gex=180.0)
    withx = GB.interpret(total_gex=180.0, vomma=999, zomma=999, veta=999,
                         color=999, speed=999)
    assert base["gamma"] == withx["gamma"]
    assert base["synthesis"] == withx["synthesis"]


# ── vega → vol sensitivity (magnitude, never direction) ────────────────

def test_vega_reports_a_magnitude_not_a_direction():
    lo = GB.vol_sensitivity(1000.0)
    assert lo["strength"] == "LOW"
    mod = GB.vol_sensitivity(GB.VEGA_MODERATE + 1)
    assert mod["strength"] == "MODERATE"
    hi = GB.vol_sensitivity(GB.VEGA_HIGH + 1)
    assert hi["strength"] == "HIGH" and "materially" in hi["text"]
    # magnitude only — sign must not create a bullish/bearish direction
    assert "direction" not in hi
    for banned in ("buy", "sell", "bullish", "bearish", "upside", "downside"):
        assert banned not in hi["text"].lower()
    # absent → Not reported, never a fabricated 0
    assert GB.vol_sensitivity(None)["strength"] == NR


def test_interpret_surfaces_vega_as_vol_sensitivity():
    r = GB.interpret(total_gex=100.0, net_vega=GB.VEGA_HIGH + 5000)
    assert r["vol_sensitivity"]["strength"] == "HIGH"
    # no net_vega → Not reported
    assert GB.interpret(total_gex=100.0)["vol_sensitivity"]["strength"] == NR


# ── staleness ──────────────────────────────────────────────────────────

def test_stale_data_is_flagged():
    fresh = GB.interpret(total_gex=100.0, as_of=1000.0, now=1000.0 + 10)
    stale = GB.interpret(total_gex=100.0, as_of=1000.0,
                         now=1000.0 + GB.STALE_AFTER_S + 1)
    assert fresh["stale"] is False and stale["stale"] is True
    # no timestamps → cannot tell → not falsely marked stale
    assert GB.interpret(total_gex=100.0)["stale"] is False


# ── synthesis ──────────────────────────────────────────────────────────

def test_synthesis_reads_downward_drift_plus_chop():
    r = GB.interpret(spot=24460, pull_level=24400, net_charm=-36.2,
                     total_gex=180.0)
    assert r["synthesis"] == "DOWNWARD DRIFT + CHOP"


# ── the existing Dealer Magnet stays compatible ────────────────────────

def test_the_dealer_magnet_producer_is_untouched():
    """This layer reuses the magnet; it must not have edited the producer. On
    expiry day dealer_magnet still returns charm_pin's read unchanged."""
    from mios_v5 import charm_pin, dealer_magnet
    cp = charm_pin.read(True, 24460, 24400, -36.2, "max pain")
    dm = dealer_magnet.read(True, 24460, 24400, -36.2, "max pain")
    # dealer_magnet adds labels but keeps every charm_pin fact identical
    for k in ("pin", "distance", "drift", "net_charm", "sentence", "active"):
        assert dm[k] == cp[k], k


# ── the panel ──────────────────────────────────────────────────────────

def test_the_panel_renders_context_only_and_missing_greeks():
    read = GB.interpret(spot=24460, pull_level=24400, pull_source="max pain",
                        net_charm=-36.2, net_vanna=-120.0, total_gex=180.0)
    html = GP.behaviour_html(read)
    assert "Greek behaviour" in html
    assert "Context only" in html and "Guardian" in html
    assert "CHOP / PIN" in html and "DOWNWARD DRIFT + CHOP" in html
    # the unavailable higher-order Greeks are named as Not reported
    assert "Not reported" in html and "Vomma" in html
    assert "Vega" not in html          # vega is promoted; not in the missing list
    # never a trade
    assert "buy" not in html.lower() and "sell" not in html.lower()


def test_the_panel_shows_vol_sensitivity_only_when_material():
    material = GB.interpret(spot=24460, pull_level=24400, net_charm=-36.2,
                            total_gex=180.0, net_vega=GB.VEGA_HIGH + 5000)
    assert "Vol sensitivity" in GP.behaviour_html(material)
    # a LOW/absent vega read adds no row on the space-constrained card
    low = GB.interpret(spot=24460, pull_level=24400, net_charm=-36.2,
                       total_gex=180.0, net_vega=10.0)
    assert "Vol sensitivity" not in GP.behaviour_html(low)


def test_the_panel_flags_stale_and_is_empty_when_nothing_to_say():
    stale = GB.interpret(total_gex=100.0, pull_level=24400, spot=24460,
                         net_charm=-30.0, net_vanna=-120.0,
                         as_of=1000.0, now=1000.0 + GB.STALE_AFTER_S + 1)
    assert "STALE" in GP.behaviour_html(stale)
    # an all-absent read draws nothing rather than a permanent empty strip
    assert GP.behaviour_html(GB.interpret()) == ""
    assert GP.behaviour_html(None) == ""


def test_the_panel_adds_no_number_of_its_own():
    """Pure presentation: the panel imports no producer and no data library."""
    tree = ast.parse((_ROOT / "mios_v5" / "ui" / "greek_behaviour_panel.py")
                     .read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[-1])
    assert not ({"pandas", "numpy"} & imported)


# ── the net_vega producer (reuses the existing exposure aggregator) ────

def test_net_vega_is_summed_from_the_chain_and_optional():
    """`vob_minimal` cannot be imported here (heavy Streamlit deps), so the
    net_vega aggregate is pinned on the parse tree of the existing exposure
    producer: it sums the per-strike Vega columns and returns `net_vega`, and it
    is OPTIONAL — `None` when the chain has no Vega columns, never a fabricated 0.
    """
    src = (_ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "calculate_vanna_charm_exposure")
    seg = ast.get_source_segment(src, fn) or ""
    # it reuses the per-strike Vega columns the chain already carries…
    assert "Vega_CE" in seg and "Vega_PE" in seg
    # …aggregated the same OI-weighted / contract_multiplier / 1e5 way…
    assert "contract_multiplier" in seg
    # …returned as net_vega, optional: None when the columns are absent
    assert "'net_vega'" in seg
    assert "if has_vega else None" in seg


# ── the "other 5" third-order reads (vomma/speed/zomma/veta/color) ─────

def test_each_third_order_greek_reads_a_magnitude_never_a_direction():
    for g in GB.CONTEXTUAL_GREEKS:
        mod, high = GB.CONTEXTUAL_BANDS[g]
        lo = GB.contextual_read(g, mod * 0.5)
        assert lo["strength"] == "LOW", g
        md = GB.contextual_read(g, mod + 1)
        assert md["strength"] == "MODERATE", g
        hi = GB.contextual_read(g, high + 1)
        assert hi["strength"] == "HIGH", g
        # sign carries NOTHING — a negative net reads the same magnitude bucket
        assert GB.contextual_read(g, -(high + 1))["strength"] == "HIGH", g
        # never a trade or a direction word
        for banned in ("buy", "sell", "bullish", "bearish", "upside",
                       "downside", "long", "short"):
            assert banned not in hi["text"].lower(), (g, banned)
        # absent → Not reported, never a fabricated 0
        assert GB.contextual_read(g, None)["strength"] == NR, g


def test_interpret_surfaces_the_five_as_contextual_reads():
    r = GB.interpret(total_gex=100.0,
                     vomma=GB.CONTEXTUAL_BANDS["vomma"][1] + 1,
                     speed=GB.CONTEXTUAL_BANDS["speed"][1] + 1)
    assert r["contextual"]["vomma"]["strength"] == "HIGH"
    assert r["contextual"]["speed"]["strength"] == "HIGH"
    # a greek with no producer value handed in → Not reported, never 0
    assert r["contextual"]["zomma"]["strength"] == NR


def test_the_five_do_not_change_the_gamma_regime_or_synthesis():
    base = GB.interpret(spot=24460, pull_level=24400, net_charm=-36.2,
                        total_gex=180.0)
    loud = GB.interpret(spot=24460, pull_level=24400, net_charm=-36.2,
                        total_gex=180.0, vomma=9e9, speed=9e9, zomma=9e9,
                        veta=9e9, color=9e9)
    assert base["gamma"] == loud["gamma"]
    assert base["synthesis"] == loud["synthesis"]
    assert loud["context_only"] is True


def test_the_panel_shows_a_third_order_row_only_when_material():
    material = GB.interpret(spot=24460, pull_level=24400, net_charm=-36.2,
                            total_gex=180.0,
                            speed=GB.CONTEXTUAL_BANDS["speed"][1] + 1)
    html = GP.behaviour_html(material)
    assert "Gamma acceleration" in html
    # a LOW read adds no row, and with a producer present it is NOT "Not reported"
    low = GB.interpret(spot=24460, pull_level=24400, net_charm=-36.2,
                       total_gex=180.0, speed=0.0)
    lhtml = GP.behaviour_html(low)
    assert "Gamma acceleration" not in lhtml
    # speed reported (0.0) → it drops off the "Not reported" list
    assert "Speed" not in lhtml


# ── self-calibrating buckets (rolling history) ─────────────────────────

def test_history_makes_the_bucket_self_calibrating_not_absolute():
    """The SAME value, far below the absolute HIGH band, reads HIGH when it tops
    its own recent range and only MODERATE when its range sits above it — proof
    the bucket calibrates against the Greek's own history, not a fixed constant."""
    g = "speed"
    mod, high = GB.CONTEXTUAL_BANDS[g]
    val = mod * 1.5                       # material, but well under the HIGH band
    assert val < high
    # a window with real spread whose whole range sits BELOW val → val is a standout
    busy = [mod * f for f in (0.5, 0.7, 0.9, 0.6, 0.8, 1.0, 0.7, 0.9, 0.6, 0.8, 1.0, 0.7)]
    quiet = [high * 2] * 12               # its recent range sits ABOVE val
    assert GB.contextual_read(g, val, history=busy)["strength"] == "HIGH"
    assert GB.contextual_read(g, val, history=quiet)["strength"] == "MODERATE"


def test_no_history_keeps_the_absolute_band_behaviour():
    """Backward compatible: with no window the #92 absolute bands still apply."""
    g = "veta"
    mod, high = GB.CONTEXTUAL_BANDS[g]
    assert GB.contextual_read(g, high + 1)["strength"] == "HIGH"
    assert GB.contextual_read(g, mod + 1)["strength"] == "MODERATE"
    assert GB.contextual_read(g, mod * 0.5)["strength"] == "LOW"


def test_interpret_threads_history_into_each_contextual_read():
    g = "zomma"
    mod, high = GB.CONTEXTUAL_BANDS[g]
    val = mod * 1.5
    busy = [mod * f for f in (0.5, 0.7, 0.9, 0.6, 0.8, 1.0, 0.7, 0.9, 0.6, 0.8, 1.0, 0.7)]
    r = GB.interpret(total_gex=100.0, **{g: val}, contextual_history={g: busy})
    assert r["contextual"][g]["strength"] == "HIGH"      # self-calibrated
    # without the history the same value would only be MODERATE
    r2 = GB.interpret(total_gex=100.0, **{g: val})
    assert r2["contextual"][g]["strength"] == "MODERATE"


# ── the app wiring ─────────────────────────────────────────────────────

def test_the_app_feeds_the_layer_existing_producers_only():
    """vob_minimal builds the strip from `_gex_data`, the market picture's
    `vc_exp` and the ranked magnet — it does not recompute a Greek for it."""
    src = (_ROOT / "vob_minimal.py").read_text()
    assert "greek_behaviour import interpret" in src
    assert "behaviour_html" in src
    # the inputs come from already-published data, now including net_vega
    assert "_gex_data" in src and "vc_exp" in src
    assert "net_vega" in src
    # …and the five third-order nets are passed through by name
    for g in ("vomma", "speed", "zomma", "veta", "color"):
        assert f"net_{g}" in src, g


def test_the_app_maintains_a_rolling_window_and_passes_it_through():
    """The app keeps a bounded per-greek history in session state and hands it to
    the layer so each read self-calibrates — it does not hand-set a threshold."""
    src = (_ROOT / "vob_minimal.py").read_text()
    assert "_greek_ctx_hist" in src            # the session-state window store
    assert "contextual_history=" in src        # threaded into interpret
    assert "_CTX_HIST_WINDOW" in src           # the window is bounded


def test_the_producer_sums_the_five_third_order_columns_optionally():
    """Pinned on the parse tree (vob_minimal can't be imported): the exposure
    producer sums the per-strike third-order columns the chain now carries, and
    each net is OPTIONAL — None when its columns are absent, never a fabricated 0.
    """
    src = (_ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "calculate_vanna_charm_exposure")
    seg = ast.get_source_segment(src, fn) or ""
    # column names are built in a loop over the capitalised greek tuple, so the
    # producer references the five names and constructs `_CE`/`_PE` + `net_`
    for g in ("Vomma", "Speed", "Zomma", "Veta", "Color"):
        assert g in seg, g
    assert "f'{g}_CE'" in seg and "f'{g}_PE'" in seg
    assert "net_{g.lower()}" in seg
    # the same OI-weighted / contract_multiplier / 1e5 basis, and optional
    assert "contract_multiplier" in seg
    assert "has_higher" in seg


def test_the_chain_build_produces_the_five_columns():
    """The chain build must call the higher_greeks producer and assign the five
    per-strike columns for both legs — otherwise the aggregate has nothing to sum.
    """
    src = (_ROOT / "vob_minimal.py").read_text()
    assert "from mios_v5.higher_greeks import higher_greeks" in src
    for g in ("Vomma", "Speed", "Zomma", "Veta", "Color"):
        assert f"'{g}_CE'" in src and f"'{g}_PE'" in src, g