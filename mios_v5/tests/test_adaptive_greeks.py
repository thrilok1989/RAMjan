"""MIOS V6 — the Adaptive Greeks layer. Context and confirmation, never a call.

The specification's fifteen rules are the test plan. The ones that would do real
damage if broken, and are therefore asserted directly:

    rule 1   greeks are confirmation, not standalone predictors
    rule 2   price and order flow remain primary
    rule 3-5 never predict direction from Charm / GEX / IV alone
    rule 6   a strong trend must not be faded because a magnet exists
    rule 7   conflicts between flow and dealer positioning are detected
    rule 8   weighting is regime-dependent
    rule 9   expiry raises gamma, charm and vanna
    rule 10  normal days stay driven by price + OI/ΔOI + CVD
    rule 12  MIOS remains deterministic
    rule 14  the layer never creates a trade recommendation
    rule 15  every conclusion carries its evidence
"""

import ast
import pathlib
from typing import Mapping

import pytest

from mios_v5 import adaptive_greeks as AG

ROOT = pathlib.Path(__file__).resolve().parents[2]

_FLOW_BULL = {"regime": "UP", "order_flow": "Bull", "cvd": 1.0}
_FLOW_BEAR = {"regime": "DOWN", "order_flow": "Bear", "cvd": -1.0}
_DOI_BULL = {"label": "Bullish (PE writers building support)"}
_GEX_POS = {"total": 153.0, "signal": "Pin", "flip": 24573.0, "magnet": 24650.0}
_GEX_NEG = {"total": -120.0, "signal": "Breakout", "flip": 24573.0}
_DEX_BULL = {"net_dex": 90.0, "bias": "BULL", "label": "Call-delta heavy"}
_VC = {"net_vanna": 12.0, "net_charm": -8.0}
_SKEW = {"ratio": 1.18, "put_iv": 13.2, "call_iv": 11.2, "bias": "BEAR",
         "label": "Put fear"}
_IV_UP = [11.8, 12.0, 12.6]
_IV_DOWN = [12.6, 12.1, 11.7]


# ══════════════════════════════════════════════════════════════════════
#  rule 14 · it never makes the call
# ══════════════════════════════════════════════════════════════════════

def test_the_output_carries_no_side_and_no_action():
    """⚠️ THE rule. The Guardian decides; this layer modifies confidence.

    Checked on the dict rather than promised in a docstring, because a docstring
    is worth nothing the first time somebody adds a convenient `side` field.
    """
    out = AG.read(flow=_FLOW_BULL, doi=_DOI_BULL, gex=_GEX_POS, dex=_DEX_BULL,
                  vc=_VC, skew=_SKEW, iv_series=_IV_UP, spot=24583.8,
                  magnet=24650.0)
    for key in AG.FORBIDDEN_KEYS:
        assert key not in out, key
    AG.assert_no_recommendation(out)


@pytest.mark.parametrize("reg", AG.REGIMES)
def test_no_regime_produces_a_recommendation(reg):
    """Every regime, because a rule that holds in the common case and not on
    expiry day is not a rule."""
    out = AG.read(flow=_FLOW_BULL, doi=_DOI_BULL, gex=_GEX_POS,
                  is_expiry=(reg == "EXPIRY"), spot=24583.8,
                  market_picture={"regime": "UP"})
    AG.assert_no_recommendation(out)


def test_the_guard_actually_rejects_a_recommendation():
    """A guard nobody can trip is not a guard."""
    with pytest.raises(ValueError):
        AG.assert_no_recommendation({"side": "CALL"})
    with pytest.raises(ValueError):
        AG.assert_no_recommendation({"action": "BUY"})


def test_no_buy_or_sell_ever_reaches_the_OUTPUT():
    """Belt and braces — on the output, not the source.

    ⚠️ The first version banned the literal "BUY" anywhere in the module and
    failed on `_sign_of`, whose whole job is to RECOGNISE bias words handed to it.
    Matching a word is not emitting one, and a test that cannot tell the
    difference would have forced the matcher to get worse. The real property is
    that no directional word appears in anything this layer returns.
    """
    def walk(v):
        if isinstance(v, str):
            yield v
        elif isinstance(v, Mapping):
            for x in v.values():
                yield from walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                yield from walk(x)

    for gex in (_GEX_POS, _GEX_NEG):
        out = AG.read(flow=_FLOW_BULL, doi=_DOI_BULL, gex=gex, dex=_DEX_BULL,
                      vc=_VC, skew=_SKEW, iv_series=_IV_UP, spot=24583.8,
                      magnet=24650.0, market_picture={"regime": "UP"})
        for text in walk(out):
            up = text.upper()
            for banned in ("BUY ", "SELL ", "GO LONG", "GO SHORT"):
                assert banned not in up, (banned, text)


# ══════════════════════════════════════════════════════════════════════
#  rules 3-5 · no single greek carries a direction
# ══════════════════════════════════════════════════════════════════════

def test_dealer_posture_is_relative_to_flow_and_carries_no_bias():
    """⚠️ Rule 4 as an API that structurally cannot break it: the return value
    has no direction in it — only SUPPORTIVE / OPPOSING / NEUTRAL.

    The same positive gamma OPPOSES a bullish flow and a bearish one, because
    positive gamma dampens movement whichever way it is going.
    """
    up = AG.dealer_posture(_GEX_POS, {}, 24583.8, flow_sign=1)
    down = AG.dealer_posture(_GEX_POS, {}, 24583.8, flow_sign=-1)
    assert up["posture"] == down["posture"] == "OPPOSING"
    for node in (up, down):
        for banned in ("bias", "side", "direction_bias"):
            assert banned not in node


def test_negative_gamma_supports_a_move_in_either_direction():
    for sign in (1, -1):
        got = AG.dealer_posture(_GEX_NEG, {}, 24583.8, flow_sign=sign)
        assert got["posture"] == "SUPPORTIVE"
        assert got["amplification"] == "AMPLIFYING"


def test_charm_produces_pressure_and_a_magnet_never_a_forecast():
    """⚠️ Rule 3, and the wording the spec is explicit about. The sentence must
    say price *may be pulled toward* the magnet, never that it *will reach* it."""
    got = AG.hedging_pressure(_VC, magnet=24650.0, spot=24583.8)
    assert got["direction"] == "UPWARD"
    assert "may be pulled toward" in got["sentence"]
    for banned in ("will reach", "will go", "target", "predict"):
        assert banned not in got["sentence"].lower()


def test_no_charm_magnet_is_invented_when_the_strike_is_unpublished():
    """The per-strike charm frame is not published. Deriving a magnet level from
    a net figure would be exactly the fabricated precision this layer avoids — the
    sign still gives a direction, and the absence is stated."""
    got = AG.hedging_pressure({"net_charm": 9.0}, magnet=None, spot=24583.8)
    assert got["magnet"] is None
    assert got["direction"] == "UPWARD"
    assert any("not published" in e for e in got["evidence"])


def test_volatility_returns_confirmation_never_a_direction():
    """Rule 5. The only directional word in the output is the caller's own."""
    got = AG.volatility_state(_IV_UP, _SKEW, price_sign=1)
    assert got["confirmation"] == "CONFIRMING"
    for banned in ("bias", "side"):
        assert banned not in got


def test_price_up_with_iv_down_is_a_divergence():
    got = AG.volatility_state(_IV_DOWN, {}, price_sign=1)
    assert got["confirmation"] == "DIVERGING"
    assert got["state"] == "CONTRACTING"


def test_price_down_with_put_fear_confirms():
    got = AG.volatility_state(_IV_DOWN, _SKEW, price_sign=-1)
    assert got["confirmation"] == "CONFIRMING"
    assert any("put skew" in e for e in got["evidence"])


def test_a_move_with_no_iv_history_is_silent_not_confirming():
    got = AG.volatility_state(None, {}, price_sign=1)
    assert got["confirmation"] == "SILENT"
    assert got["state"] is None


# ══════════════════════════════════════════════════════════════════════
#  rules 2, 8, 9, 10 · regime-dependent weights, price always primary
# ══════════════════════════════════════════════════════════════════════

def test_price_flow_outweighs_every_greek_in_every_regime():
    """⚠️ Rule 2, checked as data rather than trusted as intent. `price_flow` must
    never sit below any greek layer — that inversion is how a greek quietly
    becomes the primary predictor."""
    for reg, w in AG.WEIGHTS.items():
        for greek in ("dealer", "vanna", "charm", "volatility"):
            assert w["price_flow"] >= w[greek], (reg, greek)


def test_a_trend_deprioritises_charm():
    """Rule 6: a strong trend must not be faded just because a magnet exists."""
    for reg in ("TREND_UP", "TREND_DOWN"):
        assert AG.WEIGHTS[reg]["charm"] < AG.WEIGHTS["RANGE"]["charm"]
        assert AG.WEIGHTS[reg]["charm"] < AG.WEIGHTS[reg]["price_flow"]


def test_expiry_raises_gamma_charm_and_vanna():
    """Rule 9."""
    e, r = AG.WEIGHTS["EXPIRY"], AG.WEIGHTS["RANGE"]
    for layer in ("dealer", "charm", "vanna"):
        assert e[layer] > r[layer], layer


def test_a_normal_day_stays_driven_by_price_oi_and_flow():
    """Rule 10."""
    r = AG.WEIGHTS["RANGE"]
    assert r["price_flow"] >= r["charm"] and r["oi_positioning"] >= r["charm"]


def test_every_regime_has_a_full_weight_row():
    for reg in AG.REGIMES:
        assert reg in AG.WEIGHTS, reg
        assert set(AG.WEIGHTS[reg]) == set(AG.LAYERS), reg


def test_expiry_outranks_every_other_regime():
    """On expiry day the hedging mechanics dominate whatever else is true."""
    reg, ev = AG.regime({"regime": "UP"}, is_expiry=True,
                        pin={"active": True}, iv_state={"state": "EXPANDING"})
    assert reg == "EXPIRY"
    assert ev, "rule 15 — the classification must carry its evidence"


def test_a_live_pin_outranks_a_trend():
    reg, _ = AG.regime({"regime": "UP"}, pin={"active": True, "distance": 16})
    assert reg == "PINNED"


def test_a_trend_is_read_from_the_market_pictures_own_regime():
    """Classification of a published read, not a new measurement."""
    assert AG.regime({"regime": "UP"})[0] == "TREND_UP"
    assert AG.regime({"regime": "DOWN"})[0] == "TREND_DOWN"
    assert AG.regime({"regime": "SIDEWAYS"})[0] == "RANGE"


def test_no_regime_published_falls_back_to_range_and_says_so():
    reg, ev = AG.regime(None)
    assert reg == "RANGE"
    assert any("defaulting" in e for e in ev)


# ══════════════════════════════════════════════════════════════════════
#  rule 7 · conflicts
# ══════════════════════════════════════════════════════════════════════

def test_bullish_flow_into_positive_gamma_with_a_magnet_is_a_fade_risk():
    """The spec's first worked example."""
    out = AG.read(flow=_FLOW_BULL, doi=_DOI_BULL, gex=_GEX_POS, dex=_DEX_BULL,
                  vc=_VC, spot=24583.8, magnet=24650.0,
                  market_picture={"regime": "UP"})
    names = {c["name"] for c in out["conflicts"]}
    assert "FLOW_INTO_PIN" in names
    hit = next(c for c in out["conflicts"] if c["name"] == "FLOW_INTO_PIN")
    assert "FADE" in hit["verdict"] or "PIN" in hit["verdict"]


def test_bullish_flow_with_negative_gamma_and_iv_expansion_is_momentum_risk():
    """The spec's second worked example."""
    out = AG.read(flow=_FLOW_BULL, doi=_DOI_BULL, gex=_GEX_NEG, dex=_DEX_BULL,
                  iv_series=_IV_UP, spot=24583.8,
                  market_picture={"regime": "UP"})
    names = {c["name"] for c in out["conflicts"]}
    assert "FLOW_WITH_NEGATIVE_GAMMA" in names
    hit = next(c for c in out["conflicts"]
               if c["name"] == "FLOW_WITH_NEGATIVE_GAMMA")
    assert "MOMENTUM" in hit["verdict"]


def test_flow_that_nothing_confirms_is_a_fakeout_risk():
    out = AG.read(flow=_FLOW_BULL, gex=_GEX_POS,
                  dex={"bias": "BEAR"}, iv_series=_IV_DOWN, spot=24583.8,
                  market_picture={"regime": "UP"})
    names = {c["name"] for c in out["conflicts"]}
    assert "FLOW_UNCONFIRMED" in names


def test_no_conflict_when_everything_agrees():
    out = AG.read(flow=_FLOW_BULL, doi=_DOI_BULL, gex=_GEX_NEG, dex=_DEX_BULL,
                  iv_series=_IV_UP, spot=24583.8,
                  market_picture={"regime": "UP"})
    assert "FLOW_INTO_PIN" not in {c["name"] for c in out["conflicts"]}


# ══════════════════════════════════════════════════════════════════════
#  rule 1 · modifiers lean, they do not swamp
# ══════════════════════════════════════════════════════════════════════

def test_the_confidence_delta_is_bounded():
    """⚠️ Rule 1. The greeks layer may lean on a verdict and may never replace
    it, so ±20 is a hard cap — otherwise a pile of conditions could turn a
    high-confidence read into a low-confidence one on their own."""
    for gex in (_GEX_POS, _GEX_NEG, {}):
        for iv in (_IV_UP, _IV_DOWN, None):
            out = AG.read(flow=_FLOW_BULL, doi=_DOI_BULL, gex=gex,
                          dex={"bias": "BEAR"}, vc=_VC, skew=_SKEW,
                          iv_series=iv, spot=24583.8, magnet=24650.0)
            d = out["modifiers"]["confidence_delta"]
            assert -20.0 <= d <= 20.0, d


def test_every_probability_is_a_percentage():
    out = AG.read(flow=_FLOW_BULL, doi=_DOI_BULL, gex=_GEX_POS, vc=_VC,
                  spot=24583.8, magnet=24650.0)
    m = out["modifiers"]
    for key in ("pin_probability", "fade_probability", "breakout_probability",
                "continuation_probability", "reversal_probability"):
        assert 0 <= m[key] <= 100, (key, m[key])
    assert m["continuation_probability"] + m["reversal_probability"] == 100
    assert m["risk_level"] in ("LOW", "MEDIUM", "HIGH")


def test_apply_to_moves_a_confidence_and_keeps_it_bounded():
    out = AG.read(flow=_FLOW_BULL, gex=_GEX_POS, vc=_VC, spot=24583.8,
                  magnet=24650.0)
    assert 0 <= AG.apply_to(70, out) <= 100
    assert AG.apply_to(0, out) >= 0
    assert AG.apply_to(100, out) <= 100
    assert AG.apply_to(None, out) is None


def test_apply_to_takes_and_returns_a_confidence_never_a_side():
    """The helper exists so the clamp lives in one place. It must not become a
    back door for a direction."""
    import inspect
    sig = inspect.signature(AG.apply_to)
    assert list(sig.parameters) == ["confidence", "out"]


# ══════════════════════════════════════════════════════════════════════
#  rules 12, 15 · deterministic, and evidenced
# ══════════════════════════════════════════════════════════════════════

def test_the_same_inputs_give_the_same_output():
    """Rule 12. No clock, no randomness, no session state."""
    kw = dict(flow=_FLOW_BULL, doi=_DOI_BULL, gex=_GEX_POS, dex=_DEX_BULL,
              vc=_VC, skew=_SKEW, iv_series=_IV_UP, spot=24583.8,
              magnet=24650.0, market_picture={"regime": "UP"})
    assert AG.read(**kw) == AG.read(**kw)


def test_it_reads_no_clock_and_no_session_state():
    src = (ROOT / "mios_v5" / "adaptive_greeks.py").read_text()
    tree = ast.parse(src)
    mods = {a.name.split(".")[0] for n in ast.walk(tree)
            if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.module}
    for banned in ("streamlit", "requests", "pandas", "numpy", "random",
                   "datetime", "time"):
        assert banned not in mods, banned
    # Attribute access, not a text search: the module docstring says it reads no
    # `session_state`, and grepping the source finds that promise.
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "session_state" not in attrs


def test_every_conclusion_carries_evidence():
    """Rule 15."""
    out = AG.read(flow=_FLOW_BULL, doi=_DOI_BULL, gex=_GEX_POS, dex=_DEX_BULL,
                  vc=_VC, skew=_SKEW, iv_series=_IV_UP, spot=24583.8,
                  magnet=24650.0, market_picture={"regime": "UP"})
    assert out["evidence"], "no evidence at all"
    assert out["regime_evidence"]
    assert out["dealer"]["evidence"] and out["pressure"]["evidence"]
    assert out["volatility"]["evidence"]
    assert out["modifiers"]["confidence_why"]
    for c in out["conflicts"]:
        assert c["why"], c


def test_a_layer_that_said_nothing_is_not_averaged_in_as_zero():
    """⚠️ `MISSING is not 0`, at the scoring layer. Weighting an unreported
    layer as zero would quietly drag every score toward neutral and make a quiet
    chain look balanced."""
    out = AG.read(flow=_FLOW_BULL, spot=24583.8)
    assert "oi_positioning" in out["missing"]
    assert out["scores"]["oi_positioning"] is None
    assert out["adaptive_score"] != 0.0


def test_it_reports_which_layers_are_missing():
    out = AG.read(spot=24583.8)
    assert set(out["missing"]) >= {"price_flow", "oi_positioning"}


def test_nothing_here_raises_on_junk():
    """It is consumed by four display surfaces; it may not take any of them
    down."""
    for junk in (None, {}, [], "x", 7, True, {"regime": object()}):
        AG.read(flow=junk, doi=junk, gex=junk, dex=junk, vc=junk, skew=junk,
                iv_series=junk if isinstance(junk, list) else None,
                spot=junk, magnet=junk, pin=junk, market_picture=junk,
                reaction=junk)


def test_a_frozen_mapping_is_accepted_everywhere():
    """Stage 71.95 freezes payloads as `MappingProxyType`, which is not a dict
    subclass — the confusion this repo has shipped four times."""
    from types import MappingProxyType
    out = AG.read(flow=MappingProxyType(dict(_FLOW_BULL)),
                  gex=MappingProxyType(dict(_GEX_POS)),
                  market_picture=MappingProxyType({"regime": "UP"}),
                  spot=24583.8)
    assert out["regime"] == "TREND_UP"
    assert out["dealer"]["gamma"] == "POSITIVE"


# ══════════════════════════════════════════════════════════════════════
#  it consumes charm_pin rather than re-deriving the pin
# ══════════════════════════════════════════════════════════════════════

def test_the_expiry_pin_is_charm_pins_and_the_module_is_untouched():
    """⚠️ `charm_pin` already owns the pin rule, its wording and its
    `context_only` flag. A second implementation would let the Trade Card and
    this layer disagree about whether the day is pinned."""
    src = (ROOT / "mios_v5" / "adaptive_greeks.py").read_text()
    assert "charm_pin" in src
    assert "NEAR_POINTS" in src, "the 'near' threshold must be shared, not re-chosen"
    from mios_v5.charm_pin import NEAR_POINTS
    assert AG.NEAR_POINTS == NEAR_POINTS


def test_an_active_charm_pin_makes_the_pressure_read_near():
    got = AG.hedging_pressure({}, magnet=None, spot=24583.8,
                              pin={"active": True, "distance": 16})
    assert got["near"] is True
    assert any("charm_pin" in e for e in got["evidence"])


def test_conflicts_are_ordered_worst_first():
    """⚠️ Found by rendering, not by the suite.

    A cycle detected BOTH `FLOW_UNCONFIRMED` and `FLOW_INTO_PIN`, and the panel —
    which leads its reason line with `conflicts[0]` — showed "high fade/pin risk"
    and never mentioned that nothing confirmed the flow at all. That is the more
    serious of the two and the one that decides whether to trade. Code order is
    not severity order.
    """
    out = AG.read(flow=_FLOW_BULL, gex=_GEX_POS, dex={"bias": "BEAR"},
                  vc=_VC, iv_series=_IV_DOWN, spot=24583.8, magnet=24650.0,
                  market_picture={"regime": "UP"})
    names = [c["name"] for c in out["conflicts"]]
    assert "FLOW_UNCONFIRMED" in names and "FLOW_INTO_PIN" in names
    assert names[0] == "FLOW_UNCONFIRMED", names


def test_every_named_conflict_has_a_severity_rank():
    """A conflict missing from the table sorts last silently, which would hide a
    new and possibly serious reading at the bottom of the list."""
    import re
    src = (ROOT / "mios_v5" / "adaptive_greeks.py").read_text()
    body = src[src.index("def conflicts("):src.index("#: Keys that must NEVER")]
    emitted = set(re.findall(r'"name":\s*"([A-Z_]+)"', body))
    assert emitted, "no conflicts found — the parse anchor moved"
    assert emitted <= set(AG.CONFLICT_SEVERITY), (
        f"unranked conflicts: {sorted(emitted - set(AG.CONFLICT_SEVERITY))}")
