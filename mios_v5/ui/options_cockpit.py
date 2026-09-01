"""📈 Dashboard 2 — option / LTP intelligence, in six blocks.

Answers what the **premiums** are doing, and deliberately answers nothing about
the index. The NIFTY read is Dashboard 1's; repeating it here is the duplication
the two-dashboard split exists to remove.

    1. Which expiry and strike are we on?     `option_header_html`
    2. What is each leg actually doing?       `leg_cards_html`
    3. Where is the premium building?         `premium_ladder_html`
    4. Which side has participation?          `premium_energy_html`
    5. What is each premium's own structure?  `premium_structure_html`
    6. Who is buying?                          `option_flow_html`

The synchronised CE/PE charts are block 7 in the spec and already live on the
`📊 Charts` tab, drawn by `_terminal_chart`. They are not duplicated here.

## Pure, like Dashboard 1

Data in, HTML out. No `streamlit`, no `session_state`, no engine imports — so
every block can be rendered from synthetic data and screenshotted before it
reaches the app. The collector that reads session state lives in
`dashboard_v6.py`.

## It calculates nothing ⚠️

Every field is read from a stage that already published it:

    Stage 71.8  `premium_structure`  ltp · support · resistance · vp_poc ·
                                     acceptance · momentum · rvol · cbv/csv/cvd ·
                                     break_probability · fakeout_probability ·
                                     structure_score · confidence
    Stage 71.7  `premium_energy`     energy · spike · strength · preferred
    the chain   `df_summary`         LTP · OI · ΔOI · volume · bid/ask

`break_probability` and `fakeout_probability` in particular are Stage 71.8's, and
a second estimate of "will this premium hold" computed here would be a competing
engine wearing a display panel's clothes.

## Greeks are behind a toggle, not on the screen

The spec is explicit: no delta, gamma, vega, theta, charm or vanna by default.
`greeks_table_html` exists for the collector to draw inside an expander, so the
data stays one click away rather than deleted.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .nifty_cockpit import _card, _dist, _esc, _f, _get, _n, _pct, _row
from .theme import (BEAR, BULL, CARD_BORDER, FAINT, INK, LABEL, MICRO, MUTED,
                    VIOLET, WARN)

#: The two sides, in the order every option screen in this repo lists them.
SIDES = ("CALL", "PUT")

#: Colour per side. CALL green / PUT red is the convention the leg cards, the
#: terminal chart and the OI walls already use — a third scheme here would make
#: one screen contradict two.
SIDE_TONE = {"CALL": BULL, "PUT": BEAR}


def _side_of(data: Any, side: str) -> Mapping[str, Any]:
    """One side's node, tolerant of the shapes these stages publish.

    ⚠️ `Mapping`, not `dict`: Stage 71.95 freezes per-side values as
    `MappingProxyType`, which is not a dict subclass. Four bugs in this repo have
    been that exact confusion.
    """
    if not isinstance(data, Mapping):
        return {}
    node = data.get(side)
    if node is None:
        node = data.get(side.lower())
    return node if isinstance(node, Mapping) else {}


def _money(v: Any) -> str:
    """Rupees, in the unit a trader reads. Crore above a lakh, else plain."""
    f = _f(v)
    if f is None:
        return "—"
    if abs(f) >= 1e7:
        return f"{f / 1e7:+,.1f}Cr"
    if abs(f) >= 1e5:
        return f"{f / 1e5:+,.1f}L"
    return f"{f:+,.0f}"


def _vol(v: Any) -> str:
    f = _f(v)
    if f is None:
        return "—"
    return f"{f / 1e5:.1f}L" if abs(f) >= 1e5 else f"{f:,.0f}"


# ══════════════════════════════════════════════════════════════════════
#  1 · which expiry, which strike
# ══════════════════════════════════════════════════════════════════════

def option_header_html(expiry: Any = None, atm: Any = None,
                       legs: Any = None, spot: Any = None) -> str:
    """The one line that says what the rest of the dashboard is about.

    `legs` is `{'CALL': {...}, 'PUT': {...}}` carrying `ltp`, `change_pct` and
    `volume`. Absent an expiry AND a strike there is nothing to head, so the
    block stands aside rather than drawing a frame around two dashes.
    """
    call, put = _side_of(legs, "CALL"), _side_of(legs, "PUT")
    if _f(atm) is None and not str(expiry or "").strip():
        return ""

    bits = []
    if str(expiry or "").strip():
        bits.append(f"Expiry <b style='color:{INK}'>{_esc(expiry)}</b>")
    if _f(atm) is not None:
        bits.append(f"ATM <b style='color:{WARN}'>{_n(atm)}</b>")
    if _f(spot) is not None:
        bits.append(f"Spot <b style='color:{INK}'>{_n(spot, 2)}</b>"
                    f"<span style='color:{MICRO}'> · ATM {_dist(atm, spot)} pts"
                    f"</span>" if _f(atm) is not None else
                    f"Spot <b style='color:{INK}'>{_n(spot, 2)}</b>")

    quotes = "".join(
        f"<div style='flex:1 1 0;min-width:118px;padding:4px 8px;"
        f"border-left:3px solid {SIDE_TONE[s]}'>"
        f"<div style='font-size:8.5px;letter-spacing:.11em;color:{MICRO}'>"
        f"{s} PREMIUM</div>"
        f"<div style='font-size:18px;font-weight:800;color:{SIDE_TONE[s]}'>"
        f"₹{_n(_get(_side_of(legs, s), 'ltp'), 2)}"
        + (f"<span style='font-size:10.5px;color:{MICRO};font-weight:600;"
           f"margin-left:5px'>{_pct(_get(_side_of(legs, s), 'change_pct'), 1)}"
           f"</span>"
           if _f(_get(_side_of(legs, s), "change_pct")) is not None else "")
        + "</div>"
        f"<div style='font-size:10px;color:{MUTED}'>vol "
        f"{_vol(_get(_side_of(legs, s), 'volume'))}</div></div>"
        for s in SIDES if _side_of(legs, s))

    inner = (f"<div style='font-size:11.5px;color:{MUTED};margin-bottom:5px'>"
             + " · ".join(bits) + "</div>"
             + (f"<div style='display:flex;gap:8px;flex-wrap:wrap'>{quotes}"
                f"</div>" if quotes else ""))
    return _card("📈 Option header", inner)


# ══════════════════════════════════════════════════════════════════════
#  2 · the two legs, side by side
# ══════════════════════════════════════════════════════════════════════

#: What a leg card shows, in reading order: what it costs, how much is trading,
#: who is trading it, and where it sits. Kept as data so the two cards cannot
#: drift out of alignment and so a test can assert the rows.
LEG_ROWS = (
    ("LTP", "ltp", "money2"),
    ("Change", "change_pct", "pct"),
    ("Volume", "volume", "vol"),
    ("RVOL", "rvol", "x"),
    ("OI", "oi", "vol"),
    ("ΔOI", "doi", "signed"),
    ("CBV", "cbv", "money"),
    ("CSV", "csv", "money"),
    ("CVD", "cvd", "money"),
    ("Money flow", "money_flow", "word"),
    ("Bid / Ask", "bid_ask", "raw"),
)


def _fmt(kind: str, v: Any) -> str:
    if kind == "money2":
        return f"₹{_n(v, 2)}"
    if kind == "pct":
        return _pct(v, 1)
    if kind == "vol":
        return _vol(v)
    if kind == "x":
        f = _f(v)
        return "—" if f is None else f"{f:.1f}×"
    if kind == "signed":
        f = _f(v)
        return "—" if f is None else (f"{f / 1e5:+.1f}L" if abs(f) >= 1e5
                                      else f"{f:+,.0f}")
    if kind == "money":
        return _money(v)
    if kind == "word":
        return _esc(str(v).upper()) if str(v or "").strip() else "—"
    return _esc(v) if str(v or "").strip() else "—"


def leg_cards_html(legs: Any = None) -> str:
    """🟢 CALL ‖ 🔴 PUT — the same rows for both, so they can be compared.

    Identical row order on both sides is the whole point: a trader reads across,
    not down, and two cards with different orders force them to find each field
    twice.
    """
    present = [s for s in SIDES if _side_of(legs, s)]
    if not present:
        return ""
    cards = []
    for s in present:
        node = _side_of(legs, s)
        tone = SIDE_TONE[s]
        rows = "".join(
            _row(label, _fmt(kind, node.get(key)),
                 tone if key in ("ltp",) else
                 (BULL if (_f(node.get(key)) or 0) > 0 else BEAR)
                 if key in ("cvd", "doi") and _f(node.get(key)) is not None
                 else MUTED)
            for label, key, kind in LEG_ROWS
            if node.get(key) is not None or key == "ltp")
        cards.append(
            f"<div style='flex:1 1 46%;min-width:210px;padding:6px 9px;"
            f"border:1px solid {CARD_BORDER};border-left:3px solid {tone};"
            f"border-radius:8px'>"
            f"<div style='font-size:11px;font-weight:800;color:{tone};"
            f"margin-bottom:3px'>{'🟢' if s == 'CALL' else '🔴'} {s}"
            + (f"<span style='color:{MICRO};font-weight:600;margin-left:5px'>"
               f"{_n(_get(node, 'strike'))}</span>"
               if _f(_get(node, "strike")) is not None else "")
            + f"</div>{rows}</div>")
    return _card("🎯 ATM option premiums",
                 f"<div style='display:flex;gap:8px;flex-wrap:wrap'>"
                 f"{''.join(cards)}</div>")


# ══════════════════════════════════════════════════════════════════════
#  3 · the premium ladder
# ══════════════════════════════════════════════════════════════════════

def premium_ladder_html(rows: Optional[Sequence[Mapping[str, Any]]] = None,
                        atm: Any = None) -> str:
    """📊 ATM±2 — premium and flow per strike, CE left, PE right.

    ⚠️ **No Greeks.** The spec removes delta, gamma, vega, theta, charm and vanna
    from the default view, and `greeks_table_html` puts them behind an expander
    instead of deleting them. Nine columns of Greeks across five strikes is the
    single biggest source of the overload this dashboard exists to fix.

    Strike in the middle, for the reason the OI ladder uses: it is the axis both
    sides are measured against.
    """
    live = [r for r in (rows or ()) if isinstance(r, Mapping)
            and _f(_get(r, "strike")) is not None]
    if not live:
        return ""
    live.sort(key=lambda r: -_f(_get(r, "strike")))
    atm_f = _f(atm)

    head = ("<tr>" + "".join(
        f"<th style='text-align:{a};font-size:8.5px;letter-spacing:.08em;"
        f"color:{MICRO};font-weight:600;padding:3px 5px'>{h}</th>"
        for h, a in (("CE FLOW", "left"), ("CE CVD", "right"),
                     ("CE ΔOI", "right"), ("CE LTP", "right"),
                     ("STRIKE", "center"),
                     ("PE LTP", "left"), ("PE ΔOI", "left"),
                     ("PE CVD", "left"), ("PE FLOW", "right"))) + "</tr>")

    body = []
    for r in live:
        k = _f(_get(r, "strike"))
        is_atm = atm_f is not None and abs(k - atm_f) < 0.5
        bg = "background:rgba(255,208,0,.08)" if is_atm else ""
        body.append(
            f"<tr style='{bg}'>"
            + _c(_flow_word(_get(r, "ce_flow")), "left")
            + _c(_money(_get(r, "ce_cvd")), "right", _sgn(_get(r, "ce_cvd")))
            + _c(_lakh_signed(_get(r, "ce_doi")), "right",
                 _sgn(_get(r, "ce_doi")))
            + _c(f"₹{_n(_get(r, 'ce_ltp'), 1)}", "right", BULL)
            + _c(f"<b>{k:,.0f}</b>" + (" ◀" if is_atm else ""), "center",
                 WARN if is_atm else INK)
            + _c(f"₹{_n(_get(r, 'pe_ltp'), 1)}", "left", BEAR)
            + _c(_lakh_signed(_get(r, "pe_doi")), "left",
                 _sgn(_get(r, "pe_doi")))
            + _c(_money(_get(r, "pe_cvd")), "left", _sgn(_get(r, "pe_cvd")))
            + _c(_flow_word(_get(r, "pe_flow")), "right")
            + "</tr>")
    return _card("📊 ATM ±2 premium & flow",
                 f"<table style='width:100%;border-collapse:collapse'>"
                 f"{head}{''.join(body)}</table>")


def _c(inner: str, align: str, tone: str = MUTED) -> str:
    return (f"<td style='text-align:{align};font-size:11.5px;color:{tone};"
            f"padding:2px 5px;white-space:nowrap'>{inner}</td>")


def _lakh_signed(v: Any) -> str:
    """ΔOI in lakhs, ALWAYS — one unit for the whole column.

    ⚠️ Caught by looking at the render. The mixed formatter printed `+80,000`
    directly beneath `+21.8L`, so comparing two rows of the same column meant
    converting units in your head. Lakh is the unit Indian option OI is quoted
    in, so every row uses it even when the value is small.
    """
    f = _f(v)
    return "—" if f is None else f"{f / 1e5:+.1f}L"


def _sgn(v: Any) -> str:
    f = _f(v)
    return MUTED if f is None or f == 0 else BULL if f > 0 else BEAR


def _flow_word(v: Any) -> str:
    t = str(v or "").strip()
    if not t:
        return "—"
    up = t.upper()
    tone = BULL if "BULL" in up or "BUY" in up else BEAR if (
        "BEAR" in up or "SELL" in up) else MUTED
    return f"<span style='color:{tone}'>{_esc(up)}</span>"


def greeks_table_html(rows: Optional[Sequence[Mapping[str, Any]]] = None
                      ) -> str:
    """The Greeks, for the collector to draw inside an expander.

    Kept as a function rather than deleted: the spec says *not by default*, not
    *never*. A trader who wants delta on an expiry day should not have to read
    the option chain in another tab to get it.
    """
    live = [r for r in (rows or ()) if isinstance(r, Mapping)
            and _f(_get(r, "strike")) is not None]
    if not live:
        return ""
    live.sort(key=lambda r: -_f(_get(r, "strike")))
    cols = (("STRIKE", "strike"), ("CE Δ", "ce_delta"), ("CE Γ", "ce_gamma"),
            ("CE ν", "ce_vega"), ("CE θ", "ce_theta"),
            ("PE Δ", "pe_delta"), ("PE Γ", "pe_gamma"), ("PE ν", "pe_vega"),
            ("PE θ", "pe_theta"))
    head = ("<tr>" + "".join(
        f"<th style='text-align:right;font-size:8.5px;color:{MICRO};"
        f"font-weight:600;padding:3px 5px'>{h}</th>" for h, _k in cols)
        + "</tr>")
    body = "".join(
        "<tr>" + "".join(
            _c(_n(_get(r, k), 0 if k == "strike" else 3), "right",
               INK if k == "strike" else MUTED) for _h, k in cols)
        + "</tr>" for r in live)
    return (f"<table style='width:100%;border-collapse:collapse'>"
            f"{head}{body}</table>")


# ══════════════════════════════════════════════════════════════════════
#  4 · premium energy
# ══════════════════════════════════════════════════════════════════════

def premium_energy_html(energy: Any = None) -> str:
    """⚡ Participation and expansion per side, then the preferred side.

    `energy` is Stage 71.7's output. Both numbers are shown for both sides
    because they routinely point opposite ways — participation can be healthy
    while expansion is dead — and the second is not the one to cut for space.

    `preferred` is the stage's own conclusion. NO EDGE is a real answer and is
    rendered as one, not as a blank.
    """
    e = energy if isinstance(energy, Mapping) else {}
    sides = e.get("sides") if isinstance(e.get("sides"), Mapping) else {}
    if not e.get("ready") and not sides:
        return ""

    cells = []
    for s in SIDES:
        node = _side_of(sides, s)
        if not node:
            continue
        tone = SIDE_TONE[s]
        cells.append(
            f"<div style='flex:1 1 46%;min-width:150px;padding:6px 9px;"
            f"border:1px solid {CARD_BORDER};border-left:3px solid {tone};"
            f"border-radius:8px'>"
            f"<div style='font-size:11px;font-weight:800;color:{tone}'>{s}</div>"
            + _row("Energy", _pct(node.get("energy")), MUTED,
                   str(node.get("strength") or ""))
            + _row("Spike", _pct(node.get("spike")), MUTED,
                   str(node.get("spike_band") or ""))
            + _row("CVD", _money(node.get("cvd")), _sgn(node.get("cvd")))
            + "</div>")
    if not cells:
        return ""

    pref = str(e.get("preferred") or "").strip().upper() or "NO EDGE"
    tone = SIDE_TONE.get(pref, MUTED)
    verdict = (
        f"<div style='margin-top:7px;padding-top:6px;"
        f"border-top:1px solid {CARD_BORDER};text-align:center'>"
        f"<span style='font-size:9px;letter-spacing:.12em;color:{MICRO}'>"
        f"PREMIUM EDGE</span> "
        f"<span style='font-size:15px;font-weight:800;color:{tone}'>"
        f"{_esc(pref)}</span>"
        + (f"<span style='font-size:10.5px;color:{MICRO};margin-left:6px'>"
           f"{_pct(e.get('confidence'))}</span>"
           if _f(e.get("confidence")) is not None else "")
        + "</div>")
    return _card("⚡ Premium energy",
                 f"<div style='display:flex;gap:8px;flex-wrap:wrap'>"
                 f"{''.join(cells)}</div>{verdict}")


# ══════════════════════════════════════════════════════════════════════
#  5 · each premium's own structure
# ══════════════════════════════════════════════════════════════════════

#: One card's rows. Every one is Stage 71.8's — including the two
#: probabilities, which is why nothing here estimates them.
STRUCTURE_ROWS = (
    ("LTP", "ltp", "money2"),
    ("Premium POC", "vp_poc", "money2"),
    ("Support", "support", "money2"),
    ("Resistance", "resistance", "money2"),
    ("Structure", "structure_score", "score"),
    ("Momentum", "momentum", "pct"),
    ("Acceptance", "acceptance_word", "word"),
    ("Break", "break_probability", "pct0"),
    ("Fakeout", "fakeout_probability", "pct0"),
)


def premium_structure_html(structures: Any = None) -> str:
    """🏗 Where each premium sits in its own volume profile.

    Its OWN levels, in rupees — not the index's. A premium has support and
    resistance of its own, and that is the pair a leg trade is managed against.

    ⚠️ `break_probability` and `fakeout_probability` are Stage 71.8's numbers.
    A second estimate of "will this premium hold" computed in a display panel
    would be a competing engine wearing a panel's clothes.
    """
    present = [s for s in SIDES if _side_of(structures, s)]
    if not present:
        return ""
    cards = []
    for s in present:
        node = dict(_side_of(structures, s))
        # `acceptance` is a bool from Stage 71.8 and `acceptance_read.state` is
        # the word behind it. The word is what a trader reads, so it is used
        # when present — REJECTING and "False" are the same fact worded very
        # differently, and only one of them is legible.
        read = node.get("acceptance_read")
        node["acceptance_word"] = (
            _get(read, "state") if isinstance(read, Mapping) else None
        ) or ("ACCEPTING" if node.get("acceptance") else
              "REJECTING" if node.get("rejection") else None)
        tone = SIDE_TONE[s]
        rows = "".join(
            _row(label, _sfmt(kind, node.get(key)),
                 _risk_tone(key, node.get(key)))
            for label, key, kind in STRUCTURE_ROWS
            if node.get(key) is not None)
        if not rows:
            continue
        cards.append(
            f"<div style='flex:1 1 46%;min-width:200px;padding:6px 9px;"
            f"border:1px solid {CARD_BORDER};border-left:3px solid {tone};"
            f"border-radius:8px'>"
            f"<div style='font-size:11px;font-weight:800;color:{tone};"
            f"margin-bottom:3px'>{s} STRUCTURE</div>{rows}</div>")
    if not cards:
        return ""
    return _card("🏗 Premium structure",
                 f"<div style='display:flex;gap:8px;flex-wrap:wrap'>"
                 f"{''.join(cards)}</div>")


def _sfmt(kind: str, v: Any) -> str:
    if kind == "score":
        f = _f(v)
        return "—" if f is None else f"{f:.0f}/100"
    if kind == "pct0":
        return _pct(v)
    return _fmt(kind, v)


def _risk_tone(key: str, v: Any) -> str:
    """Amber on the two readings that mean "do not trust this level".

    A 67% fakeout probability printed in the same grey as a support level is a
    warning nobody sees.
    """
    f = _f(v)
    if key == "fakeout_probability" and f is not None and f >= 60:
        return WARN
    if key == "break_probability" and f is not None and f >= 60:
        return WARN
    if key == "acceptance_word":
        up = str(v or "").upper()
        return BULL if "ACCEPT" in up else WARN if "REJECT" in up else MUTED
    return MUTED


# ══════════════════════════════════════════════════════════════════════
#  6 · who is buying
# ══════════════════════════════════════════════════════════════════════

def option_flow_html(flows: Any = None, verdict: Any = None) -> str:
    """💰 CBV · CSV · CVD per side, then which side is actually being bought.

    `verdict` is read, not derived. Comparing the two CVDs here would be a
    second opinion on a question Stage 71.7 already answers with `preferred`,
    and the two would disagree on the days it mattered.
    """
    present = [s for s in SIDES if _side_of(flows, s)]
    if not present:
        return ""
    cells = []
    for s in present:
        node = _side_of(flows, s)
        tone = SIDE_TONE[s]
        cells.append(
            f"<div style='flex:1 1 46%;min-width:150px;padding:6px 9px;"
            f"border:1px solid {CARD_BORDER};border-left:3px solid {tone};"
            f"border-radius:8px'>"
            f"<div style='font-size:11px;font-weight:800;color:{tone}'>{s}</div>"
            + _row("Cum buy", _money(node.get("cbv")), MUTED)
            + _row("Cum sell", _money(node.get("csv")), MUTED)
            + _row("CVD", _money(node.get("cvd")), _sgn(node.get("cvd")))
            # ⚠️ Nested. Stage 71.8 publishes `buy_share` inside `flow`, not at
            # the top level, so the flat read printed — for a value that was
            # right there. Both shapes are accepted.
            + _row("Buy share",
                   _pct(node.get("buy_share")
                        if node.get("buy_share") is not None
                        else _get(node.get("flow"), "buy_share")), MUTED)
            + "</div>")
    tail = ""
    if str(verdict or "").strip():
        v = str(verdict).strip().upper()
        tail = (f"<div style='margin-top:7px;padding-top:6px;"
                f"border-top:1px solid {CARD_BORDER};text-align:center'>"
                f"<span style='font-size:9px;letter-spacing:.12em;"
                f"color:{MICRO}'>OPTION FLOW</span> "
                f"<span style='font-size:14px;font-weight:800;"
                f"color:{SIDE_TONE.get(v, MUTED)}'>{_esc(v)}</span></div>")
    return _card("💰 Option flow",
                 f"<div style='display:flex;gap:8px;flex-wrap:wrap'>"
                 f"{''.join(cells)}</div>{tail}")


# ══════════════════════════════════════════════════════════════════════
#  the block order
# ══════════════════════════════════════════════════════════════════════

#: Reading order: what am I looking at, what is it doing, where is it building,
#: who has the energy, what is its own structure, who is buying. Data rather
#: than a comment so a test can assert it.
BLOCK_ORDER = ("option_header", "leg_cards", "premium_ladder",
               "premium_energy", "premium_structure", "option_flow")


def cockpit_blocks(data: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Every block, keyed by name. Blocks with nothing to say are absent.

    One entry point, so the collector reads session state once and this file
    decides what is renderable — and so a preview harness can build the whole
    dashboard from a single dict.
    """
    d = data if isinstance(data, Mapping) else {}
    out = {
        "option_header": option_header_html(d.get("expiry"), d.get("atm"),
                                            d.get("legs"), d.get("spot")),
        "leg_cards": leg_cards_html(d.get("legs")),
        "premium_ladder": premium_ladder_html(d.get("ladder"), d.get("atm")),
        "premium_energy": premium_energy_html(d.get("energy")),
        "premium_structure": premium_structure_html(d.get("structures")),
        "option_flow": option_flow_html(d.get("flows"), d.get("flow_verdict")),
    }
    return {k: v for k, v in out.items() if v}
