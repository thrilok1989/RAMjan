"""⚙️ The Adaptive Greeks display — eight lines, four surfaces, one wording.

Two properties matter here beyond "does it draw":

1. **The Guardian line is READ, never produced.** The engine emits no side, so a
   panel that minted its own BUY would undo the whole layer.
2. **All four surfaces say the same thing about one cycle.** The card, the header
   chip, the Market Picture line and the Trade Card line all read one published
   object, so they cannot describe a cycle differently.
"""

import ast
import pathlib

from mios_v5 import adaptive_greeks as AG
from mios_v5.ui import greeks_panel as GP

ROOT = pathlib.Path(__file__).resolve().parents[2]

_OUT = AG.read(
    flow={"regime": "UP", "order_flow": "Bull", "cvd": 1.0},
    doi={"label": "Bullish (PE writers building support)"},
    gex={"total": 153.0, "signal": "Pin", "flip": 24573.0, "magnet": 24650.0},
    dex={"bias": "BULL", "label": "Call-delta heavy"},
    vc={"net_vanna": 12.0, "net_charm": -8.0},
    skew={"ratio": 1.18, "bias": "BEAR", "label": "Put fear"},
    iv_series=[11.8, 12.0, 12.6], spot=24583.8, magnet=24650.0,
    market_picture={"regime": "UP"})


# ── the eight lines ───────────────────────────────────────────────────

def test_the_card_shows_the_eight_readings_the_spec_asks_for():
    """⚠️ "Hedging pressure" and "Pin / magnet" are ONE row now, not two. They
    were the same subtraction printed twice — once as a bare arrow with no stated
    basis, once as the level that arrow pointed at. Merged so the two cannot be
    read apart, and the row is named for what produced it."""
    html = GP.greeks_card_html(_OUT, "BUY", 72)
    for label in ("Dealer position", "Gamma", "Magnet pull", "Volatility",
                  "Breakout risk", "Fade risk", GP.VERDICT_LABEL):
        assert label in html, label
    assert "Hedging pressure" not in html, (
        "the unbased arrow is back — it reads as a dealer-flow measurement")


def test_it_shows_no_raw_greek_numbers():
    """The point of the layer: eight readings, not twenty greeks."""
    html = GP.greeks_card_html(_OUT, "BUY", 72)
    for word in ("Delta", "Vega", "Theta", "net_vanna", "net_charm"):
        assert word not in html, word


def test_risk_words_come_from_two_stated_thresholds():
    assert GP._band(75) == "HIGH"
    assert GP._band(50) == "MEDIUM"
    assert GP._band(20) == "LOW"
    assert GP._band(None) == "—"


def test_nothing_reported_draws_nothing():
    assert GP.greeks_card_html(None) == ""
    assert GP.greeks_card_html({}) == ""
    assert GP.micro(None) == "" and GP.micro({}) == ""
    assert GP.one_line(None) == "" and GP.one_line({}) == ""


def test_nothing_here_raises_on_junk():
    for junk in (None, {}, [], "x", 7, {"dealer": "no", "modifiers": []}):
        GP.greeks_card_html(junk, "BUY", 70)
        GP.micro(junk)
        GP.one_line(junk)


# ── the Guardian line is read, not produced ───────────────────────────

def test_the_guardian_verdict_is_whatever_it_was_handed():
    """⚠️ The engine emits no side. A panel that produced one would undo the
    layer, so the verdict is echoed verbatim — including a HOLD."""
    for word in ("BUY", "SELL", "HOLD", "BLOCKED", "WAIT", "PINNED"):
        assert word in GP.greeks_card_html(_OUT, word, 60)


def test_no_guardian_verdict_means_no_guardian_row():
    """The greeks context is useful on its own. Inventing a verdict to fill the
    row is the one thing this module must not do."""
    html = GP.greeks_card_html(_OUT, None, None)
    assert GP.VERDICT_LABEL not in html
    assert "GUARDIAN" not in html.upper()
    assert "Dealer position" in html


def test_the_panel_never_writes_a_verdict_of_its_own():
    """⚠️ Behaviour, not a source grep — the third time this session I confused
    MATCHING a word with EMITTING one.

    `greeks_card_html` tests `if "BUY" in word` to pick a colour for the verdict
    it was HANDED. Banning the literal would have forced the colour logic to get
    worse. The property that actually matters: hand it nothing, and no verdict
    word reaches the page.
    """
    for handed in (None, "", "   "):
        html = GP.greeks_card_html(_OUT, handed, 70)
        up = html.upper()
        for banned in ("BUY", "SELL", "HOLD", "BLOCKED", "GUARDIAN"):
            assert banned not in up, (banned, handed)
    # and the chip and one-line forms never carry a verdict at all
    for text in (GP.micro(_OUT), GP.one_line(_OUT)):
        up = text.upper()
        for banned in ("BUY", "SELL", "HOLD", "BLOCKED"):
            assert banned not in up, banned


def test_the_card_says_it_is_context_not_a_call():
    html = GP.greeks_card_html(_OUT, "BUY", 72)
    assert "do not make the call" in html


# ── the reason carries the layer's own words ───────────────────────────

def test_the_reason_is_the_conflict_verdict_when_there_is_one():
    """A conflict is the most actionable thing the layer produces, so it leads —
    and it is quoted, never re-worded."""
    html = GP.greeks_card_html(_OUT, "BUY", 72)
    assert _OUT["conflicts"], "fixture stopped producing a conflict"
    assert _OUT["conflicts"][0]["verdict"] in html


def test_missing_layers_are_named():
    thin = AG.read(flow={"regime": "UP"}, spot=24583.8)
    html = GP.greeks_card_html(thin, None, None)
    assert "not reporting" in html


# ── one wording across four surfaces ──────────────────────────────────

def test_the_chip_is_short_and_carries_posture_gamma_and_fade():
    chip = GP.micro(_OUT)
    assert chip.startswith("⚙️")
    assert "dealer" in chip and "γ" in chip and "fade" in chip
    assert len(chip) < 60, "the strip is frozen on every screen"


def test_the_one_line_form_is_plain_text():
    line = GP.one_line(_OUT)
    assert line and "<" not in line and line.endswith(".")


def test_the_one_line_form_names_the_magnet_only_when_it_is_near():
    near = GP.one_line(_OUT)
    assert "magnet" in near
    far = AG.read(flow={"regime": "UP"}, gex={"total": 153.0},
                  spot=24583.8, magnet=30000.0)
    assert "magnet" not in GP.one_line(far)


def test_the_publisher_is_actually_called():
    """⚠️ The hole that let a broken PR ship claiming four surfaces.

    `_adaptive_greeks` was DEFINED and never CALLED: a patch script printed
    success without verifying its replacement matched, and the anchor had moved.
    Nothing published `_adaptive_greeks`, so the header chip, the Market Picture
    line and the Trade Card line all read an absent key and silently drew
    nothing — three surfaces failing in the one way that looks like "no signal".

    Existence tests are not wiring tests. This asserts the call, inside the
    function that owns it.
    """
    import ast
    src = (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_nifty_cockpit")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "_adaptive_greeks" in called, "the read is never built"
    assert "greeks_card_html" in called, "the card is never drawn"
    assert "_guardian_read" in called, "the Guardian line is never read"


def test_every_surface_reads_the_same_published_object():
    """⚠️ One calculation, published once, four consumers (principle 3). Building
    the read per surface would be four chances to disagree about one cycle."""
    v6 = (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    app = (ROOT / "vob_minimal.py").read_text()
    assert '_adaptive_greeks"] = out' in v6, "V6 must publish the read"
    # header chip + Market Picture + Trade Card all READ it
    assert app.count("_adaptive_greeks") >= 3
    for surface in ("greeks_panel import micro", "greeks_panel import one_line"):
        assert surface in app, surface


def test_the_engine_is_built_once_per_cycle_not_per_surface():
    app = (ROOT / "vob_minimal.py").read_text()
    assert "adaptive_greeks import read" not in app, \
        "vob_minimal must READ the published object, not rebuild it"


def test_the_trade_card_keeps_its_own_guard():
    """The card was restored verbatim; the wiring around it is fair game, the
    card's guard is not."""
    app = (ROOT / "vob_minimal.py").read_text()
    body = app[app.index("def render_clean_card("):]
    body = body[:body.index("\ndef ")]
    assert "if not mp or not spot_price:" in body


def test_charm_pin_is_untouched_and_still_owns_the_pin():
    """The user asked for it to stay exactly as it was, and the layer consumes it
    rather than re-deriving the pin."""
    src = (ROOT / "mios_v5" / "charm_pin.py").read_text()
    assert "context_only" in src and "NEAR_POINTS" in src
    assert "adaptive_greeks" not in src, "charm_pin must not depend on the new layer"


# ══════════════════════════════════════════════════════════════════════
#  the three labels that were read wrong in review
# ══════════════════════════════════════════════════════════════════════
#
# All three came out of one review of a live screen, and all three are the same
# mistake: a word printed without the thing it is measured against. The reviewer
# read `SUPPORTIVE` as "dealers back the UP regime", `↓ downward` as "immediate
# hedging flow", and `Silent` as "IV isn't confirming". None of those are what
# `adaptive_greeks` computes — and every misreading was invited by the label.
#
# ⚠️ Every fix below is display-only. `posture`, `score`, `direction`,
# `confirmation` and `near` are untouched, because they feed `_modifiers` and a
# label defect must not move a decision.


def _out(**kw):
    """A read with the pieces a case cares about overridden."""
    base = dict(flow={"regime": "UP", "order_flow": "Bull", "cvd": 1.0},
                gex={"total": -153.0, "flip": 24459.0},
                dex={"bias": "BULL"}, vc={"net_vanna": 12.0, "net_charm": -8.0},
                iv_series=[11.8, 12.0, 12.6], spot=24583.0, magnet=24400.0,
                market_picture={"regime": "UP"})
    base.update(kw)
    return AG.read(**base)


# ── 1 · SUPPORTIVE of WHAT ────────────────────────────────────────────

def test_the_regime_is_never_an_input_to_the_dealer_posture():
    """The misreading was "supportive of the UP regime". It cannot be: `regime`
    is computed AFTER `dealer_posture` and is not passed to it."""
    import inspect
    sig = inspect.signature(AG.dealer_posture)
    assert "regime" not in sig.parameters
    assert "market_picture" not in sig.parameters
    assert set(sig.parameters) == {"gex", "dex", "spot", "flow_sign"}


def test_the_posture_says_what_it_is_relative_to():
    d = AG.dealer_posture(gex={"total": -153.0}, dex={"bias": "BULL"},
                          spot=24583.0, flow_sign=1)
    assert d["posture"] == "SUPPORTIVE"
    assert d["relative_to"] == "flow"
    assert "of flow" in GP.greeks_card_html(_out())


def test_with_no_flow_the_card_stops_claiming_support():
    """⚠️ The actual fix. `dealer_posture` scores negative gamma as SUPPORTIVE
    whether or not flow has a direction — correctly, since negative gamma really
    does amplify movement. But "supportive" with no object invites the reader to
    supply one, and the obvious guess is wrong."""
    d = AG.dealer_posture(gex={"total": -153.0}, spot=24583.0, flow_sign=0)
    assert d["posture"] == "SUPPORTIVE", "the score must not change"
    assert d["relative_to"] is None

    html = GP.greeks_card_html({"dealer": d, "modifiers": {}})
    assert "SUPPORTIVE" not in html
    assert "amplifying moves" in html
    assert "no flow direction" in html


def test_the_posture_word_and_score_are_untouched_by_the_label_fix():
    """A display defect may not move a decision. `_modifiers` reads `posture`."""
    for flow_sign in (-1, 0, 1):
        d = AG.dealer_posture(gex={"total": -153.0}, dex={"bias": "BULL"},
                              spot=24583.0, flow_sign=flow_sign)
        assert d["posture"] in ("SUPPORTIVE", "OPPOSING", "NEUTRAL")
        assert isinstance(d["score"], float)


def test_the_header_chip_never_says_supportive_without_an_object():
    """It matters most here — the chip is frozen on every screen, so a bare
    "dealer supportive" is the version read all session."""
    with_flow = GP.micro(_out())
    assert "of flow" in with_flow

    d = AG.dealer_posture(gex={"total": -153.0}, spot=24583.0, flow_sign=0)
    bare = GP.micro({"dealer": d, "modifiers": {"fade_probability": 65}})
    assert "supportive" not in bare.lower()
    assert "amplifying moves" in bare


def test_the_trade_card_line_never_says_supportive_without_an_object():
    assert "of flow" in GP.one_line(_out())
    d = AG.dealer_posture(gex={"total": -153.0}, spot=24583.0, flow_sign=0)
    line = GP.one_line({"dealer": d, "pressure": {}, "modifiers": {}})
    assert "supportive" not in line.lower() and "amplifying moves" in line


# ── 2 · which measurement produced the arrow ──────────────────────────

def test_the_magnet_arrow_names_the_level_it_points_at():
    """"Hedging pressure ↓ downward" was read as an immediate dealer-flow
    measurement. In this branch it is one subtraction — `magnet − spot`."""
    p = AG.hedging_pressure(vc={"net_charm": -8.0}, magnet=24400.0, spot=24583.0)
    assert p["direction"] == "DOWNWARD"
    assert p["basis"] == "magnet"

    html = GP.greeks_card_html(_out())
    assert "Magnet pull" in html and "₹24,400" in html and "↓" in html
    assert "-183 pts" in html or "−183 pts" in html


def test_a_charm_only_drag_is_labelled_differently_from_a_magnet():
    """⚠️ Two meanings under one field name, one arrow on screen. With no magnet
    strike published there is no level to name, and the row must not imply one."""
    p = AG.hedging_pressure(vc={"net_charm": -619.5}, magnet=None, spot=24583.0)
    assert p["direction"] == "DOWNWARD" and p["basis"] == "net_charm"

    html = GP.greeks_card_html({"dealer": {}, "pressure": p, "modifiers": {}})
    assert "Charm drag" in html
    assert "no magnet strike published" in html
    assert "Magnet pull" not in html


def test_no_basis_at_all_falls_back_without_inventing_one():
    p = AG.hedging_pressure(vc={}, magnet=None, spot=None)
    assert p["basis"] is None and p["direction"] == "NEUTRAL"
    html = GP.greeks_card_html({"dealer": {}, "pressure": p, "modifiers": {}})
    assert "Magnet pull" not in html and "Charm drag" not in html


def test_the_pressure_direction_and_near_are_untouched():
    """`near` feeds `_modifiers`' pin risk. Only the label moved."""
    p = AG.hedging_pressure(vc={"net_charm": -8.0}, magnet=24400.0, spot=24583.0)
    assert set(("direction", "magnet", "distance", "near", "score")) <= set(p)
    assert p["distance"] == -183.0


# ── 3 · quiet, versus not measured ────────────────────────────────────

def test_silent_with_no_iv_history_reads_as_not_reporting():
    """⚠️ `confirmation` STARTS at SILENT and only moves off it when there is both
    an IV state and a price sign. Printing that as a reading turned an absence of
    data into a statement about the market — which is how it was read."""
    v = AG.volatility_state(iv_series=None, price_sign=1)
    assert v["confirmation"] == "SILENT", "the value must not change"
    assert v["state"] is None
    assert v["reporting"] is False
    assert v["why_silent"] == "no IV history published"

    html = GP.greeks_card_html({"dealer": {}, "volatility": v, "modifiers": {}})
    assert "not reporting" in html and "no IV history published" in html
    assert "Silent" not in html


def test_one_sample_is_also_not_reporting_and_says_why():
    v = AG.volatility_state(iv_series=[12.0], price_sign=1)
    assert v["reporting"] is False
    assert "one IV sample" in v["why_silent"]


def test_a_measured_volatility_still_reads_as_a_measurement():
    v = AG.volatility_state(iv_series=[11.8, 12.0, 12.6], price_sign=1)
    assert v["reporting"] is True and v["state"] == "EXPANDING"
    html = GP.greeks_card_html({"dealer": {}, "volatility": v, "modifiers": {}})
    assert "Expanding" in html and "not reporting" not in html


def test_the_no_volatility_response_conflict_still_does_not_fire_on_missing_data():
    """This guard already existed and is the reason no false conflict was raised
    — `conflicts()` requires `state` truthy. Pinned so the display fix cannot be
    "simplified" into changing `confirmation`."""
    silent_no_data = AG.volatility_state(iv_series=None, price_sign=1)
    names = {c["name"] for c in AG.conflicts(1, {}, {}, silent_no_data)}
    assert "NO_VOLATILITY_RESPONSE" not in names

    measured_flat = AG.volatility_state(iv_series=[12.0, 12.0], price_sign=1)
    assert measured_flat["confirmation"] == "SILENT"
    assert measured_flat["reporting"] is True
    names = {c["name"] for c in AG.conflicts(1, {}, {}, measured_flat)}
    assert "NO_VOLATILITY_RESPONSE" in names


# ── the promise the whole layer rests on ──────────────────────────────

def test_the_relabelled_output_still_emits_no_recommendation():
    AG.assert_no_recommendation(_out())


def test_all_four_surfaces_still_agree_after_the_relabelling():
    out = _out()
    card, chip, line = (GP.greeks_card_html(out, "WAIT", 77), GP.micro(out),
                        GP.one_line(out))
    assert card and chip and line
    for text in (card, chip, line):
        assert "of flow" in text, "one surface dropped the referent"


# ══════════════════════════════════════════════════════════════════════
#  the reason line must not be one-sided
# ══════════════════════════════════════════════════════════════════════

def _his_cycle():
    """The exact cycle from the review: expiry, spot 24,500, magnet 100 pts
    below, negative gamma, no IV history. Reproduces breakout 35% / fade 65%."""
    return AG.read(flow={"regime": "UP", "order_flow": "Bull", "cvd": 1.0},
                   gex={"total": -153.0, "flip": 24459.0, "magnet": 24400.0},
                   dex={"bias": "BULL"},
                   vc={"net_vanna": 12.0, "net_charm": -619.5},
                   iv_series=None, spot=24500.0, magnet=24400.0,
                   is_expiry=True, market_picture={"regime": "UP"})


def test_the_reviewed_cycle_reproduces():
    """Pinned so the case that exposed all of this stays reproducible."""
    out = _his_cycle()
    m = out["modifiers"]
    assert (m["breakout_probability"], m["fade_probability"]) == (35, 65)
    assert m["risk_level"] == "HIGH"
    assert out["regime"] == "EXPIRY"
    assert out["dealer"]["gamma"] == "NEGATIVE"
    assert out["pressure"]["near"] is True


def test_a_high_risk_cycle_never_reads_as_purely_supportive():
    """⚠️ The residual of the review complaint. `confidence_why` records only what
    MOVED the confidence, so this cycle had exactly one entry — the positive one —
    and the reason read "Dealer hedging supports the move" directly under "Fade
    risk HIGH 65%". `risk_level` was already computed and reached no surface."""
    out = _his_cycle()
    assert out["modifiers"]["confidence_why"] == [
        "dealer hedging supports movement, not an entry"], "fixture drifted"
    assert not out["conflicts"], "fixture drifted — a conflict would lead instead"

    reason = GP._reason_line(out)
    assert "supports movement" in reason
    assert "not an entry" in reason, "the scope of 'supports' must be stated"
    assert "risk" in reason.lower(), "the reason is still one-sided"
    assert reason in GP.greeks_card_html(out, "WAIT", 77)


def test_the_counterweight_is_the_engines_own_conclusion():
    """Not this panel's opinion. It fires off `risk_level`, which `_modifiers`
    derives from the same fade figure the card already prints."""
    out = _his_cycle()
    calm = dict(out, modifiers=dict(out["modifiers"], risk_level="LOW"))
    assert "risk" not in GP._reason_line(calm).lower()

    hot = dict(out, modifiers=dict(out["modifiers"], risk_level="HIGH"))
    assert "risk" in GP._reason_line(hot).lower()


def test_a_conflict_still_leads_and_is_not_doubled():
    """A conflict is the more actionable reading, so it keeps the line to itself
    — appending the risk word there would restate what the conflict already says.
    """
    out = AG.read(flow={"regime": "UP", "order_flow": "Bull", "cvd": 1.0},
                  gex={"total": 153.0, "flip": 24459.0, "magnet": 24450.0},
                  dex={"bias": "BULL"}, vc={"net_charm": -619.5},
                  iv_series=None, spot=24500.0, magnet=24450.0, is_expiry=True,
                  market_picture={"regime": "UP"})
    assert out["conflicts"], "fixture stopped producing a conflict"
    reason = GP._reason_line(out)
    assert reason.startswith(out["conflicts"][0]["verdict"])
    assert reason.count("risk") <= 1, "the risk word is stated twice"


def test_the_risk_word_is_not_appended_when_it_is_already_said():
    faked = {"conflicts": [], "modifiers": {
        "confidence_why": ["high fade risk from the magnet overhead"],
        "risk_level": "HIGH"}}
    assert GP._reason_line(faked).lower().count("risk") == 1


def test_no_reason_at_all_still_returns_a_string():
    for out in ({}, {"conflicts": [], "modifiers": {}},
                {"conflicts": [], "modifiers": {"risk_level": "LOW"}}):
        assert GP._reason_line(out) == ""


# ══════════════════════════════════════════════════════════════════════
#  the reported PUT · DOWN cycle — "why WAIT if everything is supportive?"
# ══════════════════════════════════════════════════════════════════════

def _down_cycle():
    """PUT · DOWN · BREAKOUT: negative gamma flip ₹24,315, magnet ₹24,200 eighty
    points below spot, no IV history. Reproduces breakout 45% / fade 55%."""
    return AG.read(flow={"regime": "DOWN", "order_flow": "Bear", "cvd": -1.0},
                   gex={"total": -210.0, "flip": 24315.0, "magnet": 24200.0},
                   dex={"bias": "BEAR"},
                   vc={"net_vanna": -8.0, "net_charm": -120.0},
                   iv_series=None, spot=24280.0, magnet=24200.0,
                   market_picture={"regime": "DOWN"})


def test_the_reported_down_cycle_reproduces():
    m = _down_cycle()["modifiers"]
    assert (m["breakout_probability"], m["fade_probability"]) == (45, 55)
    assert m["risk_level"] == "MEDIUM"


def test_the_reason_no_longer_reads_as_endorsing_a_trade():
    """⚠️ The report: "🟢 SUPPORTIVE of flow" over "GUARDIAN WAIT" over "Dealer
    hedging supports the move" read as *everything is supportive, so why WAIT?*

    Two things were wrong. The engine's sentence did not say what it supported —
    MOVEMENT, not an entry — and the fade counterweight fired only at HIGH
    (≥60), so a 55% cycle showed the positive half alone.
    """
    out = _down_cycle()
    reason = GP._reason_line(out)
    assert "not an entry" in reason, "the scope of 'supports' is unstated"
    assert "55%" in reason, "the fade figure explaining the WAIT is missing"
    assert "wait for confirmation" in reason
    assert reason in GP.greeks_card_html(out, "WAIT", 100)


def test_the_counterweight_fires_at_medium_not_just_high():
    base = _down_cycle()
    for level, fade in (("MEDIUM", 55), ("HIGH", 72)):
        out = dict(base, modifiers=dict(base["modifiers"],
                                        risk_level=level,
                                        fade_probability=fade))
        assert f"{fade}%" in GP._reason_line(out), level
    calm = dict(base, modifiers=dict(base["modifiers"], risk_level="LOW",
                                     fade_probability=22))
    assert "wait for confirmation" not in GP._reason_line(calm)


def test_the_engine_says_movement_not_the_move():
    """Only `greeks_panel` reads `confidence_why`, so the wording is safe to make
    precise — and the imprecision was the whole complaint."""
    why = _down_cycle()["modifiers"]["confidence_why"]
    assert any("movement, not an entry" in w for w in why)
    assert not any(w.endswith("supports the move") for w in why)


def test_the_greeks_still_never_manufacture_a_side():
    """⚠️ The line the user drew: the Greeks explain why confidence is limited;
    they do not turn a DOWN regime into a PUT entry."""
    out = _down_cycle()
    AG.assert_no_recommendation(out)
    assert GP.greeks_card_html(out, "WAIT", 100).count("WAIT") >= 1
    # handed no verdict, no verdict word appears
    up = GP.greeks_card_html(out, None, None).upper()
    for banned in ("BUY", "SELL", "ENTER", "PUT ENTRY"):
        assert banned not in up


# ══════════════════════════════════════════════════════════════════════
#  the verdict row: what it is called, and what the reason says under it
# ══════════════════════════════════════════════════════════════════════

def test_an_actionable_verdict_is_not_told_to_wait_for_itself():
    """⚠️ Reported: `ENTER · 100/100` with "Fade risk 55%; wait for confirmation"
    printed directly beneath it — the card telling the trader to wait for the entry
    it had just issued. Same contradiction as the WAIT case, in mirror image.

    Under an actionable verdict the greeks' role is to flag the risk ON that entry,
    not to countermand it: they modify confidence, they do not make the call. The
    fade figure is quoted either way; only the clause changes.
    """
    out = _down_cycle()
    for word in ("ENTER", "BUY", "SELL", "enter long"):
        line = GP._reason_line(out, word)
        assert "55%" in line, word
        assert "wait for confirmation" not in line, word
        assert GP.ACT_CLAUSE in line, word
    # …and a WAIT still gets the clause that explains the wait
    for word in ("WAIT", "AT_ZONE_WAIT", "CHOP_WAIT", "HOLD", None, ""):
        line = GP._reason_line(out, word)
        assert "wait for confirmation" in line, word
        assert GP.ACT_CLAUSE not in line, word


def test_the_card_carries_the_verdict_aware_reason():
    """The whole card, not just the helper — the contradiction was on screen."""
    out = _down_cycle()
    enter = GP.greeks_card_html(out, "ENTER", 100)
    assert "wait for confirmation" not in enter
    assert GP.ACT_CLAUSE in enter
    assert "wait for confirmation" in GP.greeks_card_html(out, "WAIT", 100)


def test_the_row_is_not_called_guardian():
    """⚠️ The Market Picture has a **Position Guardian** that tracks an OPEN trade
    and reads "idle · no active trade" when there is none. Calling this row GUARDIAN
    too put "Position Guardian — idle · no active trade" and "GUARDIAN ENTER ·
    100/100" on one screen with nothing to say they are different things.

    `_guardian_read` supplies this from `_entry_decision` / `entry_gate`, so it is
    the entry gate's verdict and that is what it is called. No value changed.
    """
    html = GP.greeks_card_html(_OUT, "ENTER", 100)
    assert "GUARDIAN" not in html.upper()
    assert GP.VERDICT_LABEL in html
    assert "ENTER" in html and "100/100" in html


def test_the_footer_does_not_call_the_weighting_regime_the_regime():
    """⚠️ Two different fields were both labelled "regime" on one screen: the chip's
    `market_picture['regime']` (UP · DOWN · SIDEWAYS — what price is doing) and this
    card's weighting regime (TREND_UP · PINNED · EXPIRY · FAKEOUT — which weight set
    `adaptive_greeks` chose). "regime UP" above "Regime: TREND_UP" read as one value
    that kept changing."""
    html = GP.greeks_card_html(_OUT, "WAIT", 60)
    assert "Greek weighting:" in html
    assert "Regime:" not in html


def test_the_verdict_micro_carries_its_label_and_its_confidence():
    assert GP.verdict_micro("ENTER", 100) == "ENTRY GATE ENTER · 100/100"
    assert GP.verdict_micro("wait", 77) == "ENTRY GATE WAIT · 77/100"
    # no confidence is not confidence 0
    assert GP.verdict_micro("ENTER", None) == "ENTRY GATE ENTER"
    assert "0/100" not in GP.verdict_micro("ENTER", None)
    # nothing decided → no chip, rather than a placeholder on a frozen strip
    for junk in (None, "", "   ", 0):
        assert GP.verdict_micro(junk, 90) == ""
    # plain text: the header owns the styling
    assert "<" not in GP.verdict_micro("ENTER", 100)


def test_the_header_reads_the_resolved_pair_not_the_gate_again():
    """⚠️ ONE bridge. Resolving `_entry_decision` and the gate a second time in
    `_chrome_extras` is how the strip and the card end up showing different verdicts
    for the same cycle — and `apply_to` must be applied to the confidence exactly
    once, which `_guardian_read` already did."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    src = (root / "vob_minimal.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_chrome_extras")
    # ⚠️ On the AST, not the text. Comments are not AST nodes, and the note in
    # `_chrome_extras` explaining WHY it must not re-resolve the gate mentions
    # `_entry_decision` and `apply_to` by name — a raw grep matched my own prose, for
    # the tenth time this session.
    keys = {n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    names = {getattr(n, "id", "") or getattr(n, "attr", "") for n in ast.walk(fn)}
    for a in ast.walk(fn):
        if isinstance(a, ast.ImportFrom):
            # both, since it is imported `as _vm`
            names |= {x.name for x in a.names} | {x.asname for x in a.names}
    assert "verdict_micro" in names
    assert "_entry_verdict" in keys
    assert "_entry_decision" not in keys, "the header is resolving the gate itself"
    assert "apply_to" not in names, "the confidence would be adjusted twice"

    # …and the bridge is actually written
    d6 = (root / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    gr = next(n for n in ast.walk(ast.parse(d6))
              if isinstance(n, ast.FunctionDef) and n.name == "_guardian_read")
    gk = {n.value for n in ast.walk(gr)
          if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_entry_verdict" in gk
