"""⚙️ The Adaptive Greeks read, in the eight lines the spec asks for.

Not twenty Greek numbers — eight readings a trader acts on:

    DEALER POSITION   🟢 supportive · 🔴 opposing · 🟡 neutral
    GAMMA             positive / negative · flip level
    HEDGING PRESSURE  ↑ upward · ↓ downward · ↔ neutral
    PIN / MAGNET      ₹level · distance
    VOLATILITY        expanding / contracting / neutral
    BREAKOUT RISK     LOW / MEDIUM / HIGH
    FADE RISK         LOW / MEDIUM / HIGH
    ENTRY GATE        the verdict + confidence, READ from the decision

⚠️ That last row is **read, never produced here**. `adaptive_greeks` emits no side
(`assert_no_recommendation` enforces it), so the verdict and its confidence arrive as
parameters from whatever already decided them.

⚠️ It is the ENTRY GATE's verdict, not the Position Guardian — those are two
different things, and calling both "Guardian" put "Position Guardian — idle · no
active trade" and "GUARDIAN ENTER · 100/100" on one screen. This panel shows the
greeks *next to* that verdict — that is the whole point of the layer, and a panel
that minted its own BUY would undo it.

Every conclusion carries its evidence (rule 15): the reason line under the
verdict is assembled from the layer's own `evidence` and `conflicts`, never
re-worded.

Pure module — data in, HTML out.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .nifty_cockpit import _card, _esc, _f, _get, _n, _row
from .theme import (ALERT, BEAR, BULL, CARD_BORDER, INK, MICRO, MUTED, VIOLET,
                    WARN)

#: Posture → (emoji, tone). One map, so the chip and the card agree.
POSTURE = {
    "SUPPORTIVE": ("🟢", BULL),
    "OPPOSING": ("🔴", BEAR),
    "NEUTRAL": ("🟡", WARN),
    "UNKNOWN": ("⚪", MUTED),
}

RISK_TONE = {"LOW": BULL, "MEDIUM": WARN, "HIGH": BEAR}

#: Just the arrow. The words that follow it depend on what was measured — see
#: `_pressure_row`.
PRESSURE_ARROW = {"UPWARD": "↑", "DOWNWARD": "↓", "NEUTRAL": "↔"}

#: What dealers are doing to MOVEMENT, when there is no flow direction for them
#: to be supportive or opposing OF.
#:
#: ⚠️ This row used to print the bare posture word regardless. `SUPPORTIVE` with
#: nothing to support was read in review as "dealers back the UP regime" — a
#: claim `adaptive_greeks` never makes, since the regime is not an input to
#: `dealer_posture` at all. With no flow, the honest statement is what hedging
#: does to movement, which is exactly what gamma's sign already says.
AMPLIFICATION = {"AMPLIFYING": "amplifying moves",
                 "STABILISING": "dampening moves"}

#: Verdict words that mean "act". Everything else — WAIT, HOLD, CHOP_WAIT,
#: AT_ZONE_WAIT, PINNED, BLOCKED, or nothing at all — means "do not act yet".
ACTIONABLE = ("ENTER", "BUY", "SELL", "LONG", "SHORT")

#: How the fade counterweight ends, per verdict. Under a WAIT it explains the wait;
#: under an ENTER it qualifies the entry. Saying "wait for confirmation" under an
#: ENTER told the trader to wait for the entry the card had just issued.
WAIT_CLAUSE = "wait for confirmation"
ACT_CLAUSE = "the greeks do not confirm this entry"

#: What this row is actually showing.
#:
#: ⚠️ It said "GUARDIAN", and the Market Picture has a **Position Guardian** that
#: tracks an OPEN trade and reads "idle · no active trade" when there is none. So one
#: screen carried "Position Guardian — idle · no active trade" and "GUARDIAN ENTER ·
#: 100/100" at the same time, and a reader had no way to know those are two different
#: things. `_guardian_read` supplies this from `_entry_decision` / `entry_gate` — it
#: is the ENTRY GATE's verdict, so that is what it is called. No value changed.
VERDICT_LABEL = "ENTRY GATE"


def _is_actionable(verdict: Any) -> bool:
    w = str(verdict or "").strip().upper()
    return any(a in w for a in ACTIONABLE)


def _risk(word: Any) -> str:
    w = str(word or "").strip().upper()
    return w if w in RISK_TONE else "—"


def _band(pct: Any) -> str:
    """A probability as a risk word. Two thresholds, stated once."""
    v = _f(pct)
    if v is None:
        return "—"
    return "HIGH" if v >= 60 else "MEDIUM" if v >= 40 else "LOW"


def _dealer_row(dealer: Mapping[str, Any]) -> str:
    """The dealer line, saying what the posture is relative TO.

    Three shapes, because there are three situations:

        flow + posture     🟢 SUPPORTIVE of flow · amplifying moves
        no flow            🟡 amplifying moves — no flow direction to back
        nothing published  ⚪ UNKNOWN

    ⚠️ The middle one is the fix. `dealer_posture` scores negative gamma as
    `SUPPORTIVE` whether or not flow has a direction, because negative gamma
    genuinely amplifies movement — but "supportive" with no object invites the
    reader to supply one, and the obvious guess (the regime) is wrong. The score
    is untouched; only the sentence changed.
    """
    posture = str(_get(dealer, "posture") or "UNKNOWN").upper()
    emoji, tone = POSTURE.get(posture, POSTURE["UNKNOWN"])
    amp = AMPLIFICATION.get(str(_get(dealer, "amplification") or "").upper(), "")
    rel = _get(dealer, "relative_to")

    if posture == "UNKNOWN":
        return _row("Dealer position", f"{emoji} UNKNOWN", tone)
    if rel:
        return _row("Dealer position",
                    f"{emoji} {_esc(posture)} of {_esc(str(rel))}", tone, amp)
    # No flow direction. Say what hedging does to movement and say why the
    # posture word is missing, rather than asserting support for nothing.
    return _row("Dealer position",
                f"🟡 {_esc(amp or 'positioned')}", WARN,
                "no flow direction to back")


def _pressure_row(pressure: Mapping[str, Any]) -> str:
    """The hedging line, naming what produced the arrow.

    `direction` is measured two ways and one arrow hid which:

        basis "magnet"     Magnet pull   ↓ toward ₹24,400 · −183 pts
        basis "net_charm"  Charm drag    ↓ (no magnet strike published)
        basis None         Hedging pressure  ↔ neutral

    ⚠️ "Hedging pressure ↓ downward" was read in review as an immediate dealer
    **flow** measurement. In the magnet branch it is one subtraction —
    `magnet − spot` — so the arrow says where the level is, not what dealers are
    doing this minute. Naming the basis is the whole fix.
    """
    word = str(_get(pressure, "direction") or "").upper()
    arrow = PRESSURE_ARROW.get(word, "—")
    basis = str(_get(pressure, "basis") or "")
    mg = _f(_get(pressure, "magnet"))
    dist = _f(_get(pressure, "distance"))

    if basis == "magnet" and mg is not None:
        return _row("Magnet pull", f"{arrow} toward ₹{_n(mg)}", WARN,
                    (f"{dist:+.0f} pts" if dist is not None else ""))
    if basis == "net_charm":
        return _row("Charm drag", f"{arrow} {word.lower()}", MUTED,
                    "no magnet strike published")
    return _row("Hedging pressure",
                f"{arrow} {word.lower() if word else '—'}", MUTED)


def _volatility_row(vol: Mapping[str, Any]) -> str:
    """The volatility line, distinguishing "quiet" from "not measured".

    ⚠️ `confirmation` starts at `SILENT` and only moves off it once there is both
    an IV state and a price sign. Printing that as a reading turned an absence of
    data into a statement about the market — and it was read that way in review.
    """
    if not _get(vol, "reporting"):
        why = str(_get(vol, "why_silent") or "not reporting")
        return _row("Volatility", "⚪ not reporting", MUTED, why)
    return _row("Volatility", _esc(str(_get(vol, "state") or "—").title()),
                VIOLET, str(_get(vol, "confirmation") or "").title())


def greeks_card_html(out: Any = None, guardian: Any = None,
                     confidence: Any = None) -> str:
    """The full eight-line read. `""` when the layer reported nothing.

    `guardian` and `confidence` are the existing verdict, passed in. Absent them
    the card still draws the greeks and simply omits the Guardian line — the
    context is useful on its own, and inventing a verdict to fill the row would
    be the one thing this module must not do.
    """
    o = out if isinstance(out, Mapping) else {}
    if not o:
        return ""
    dealer = _get(o, "dealer") or {}
    pressure = _get(o, "pressure") or {}
    vol = _get(o, "volatility") or {}
    mods = _get(o, "modifiers") or {}

    rows: List[str] = [
        _dealer_row(dealer),
        _row("Gamma",
             _esc(str(_get(dealer, "gamma") or "—").title()), MUTED,
             (f"flip {_n(_get(dealer, 'gamma_flip'))}"
              if _f(_get(dealer, "gamma_flip")) is not None else "")),
        # ⚠️ One row, not two. This used to print "Hedging pressure ↓ downward"
        # AND "Pin / magnet ₹24,400 · −183 pts" — the same subtraction stated
        # twice, once as a direction with no basis and once as a level. Merged so
        # the arrow and the level it points at cannot be read apart.
        _pressure_row(pressure),
        _volatility_row(vol),
    ]

    brk = _band(_get(mods, "breakout_probability"))
    fade = _band(_get(mods, "fade_probability"))
    rows.append(_row("Breakout risk", brk, RISK_TONE.get(brk, MUTED),
                     f"{_n(_get(mods, 'breakout_probability'))}%"))
    rows.append(_row("Fade risk", fade, RISK_TONE.get(fade, MUTED),
                     f"{_n(_get(mods, 'fade_probability'))}%"))

    # ── the Guardian line, read ──────────────────────────────────────
    verdict = ""
    word = str(guardian or "").strip().upper()
    if word:
        conf = _f(confidence)
        # ⚠️ WAIT used to be drawn in MUTED grey — the same tone as a secondary
        # label. WAIT is a DECISION, not an absence of one, and rendering the
        # Guardian's actual call dimmer than the rows above it made the one line
        # that matters the hardest to read. Amber: visible, and still not the green
        # of an entry.
        gt = (BULL if "BUY" in word else BEAR if "SELL" in word
              else WARN if "HOLD" in word or "WAIT" in word else ALERT)
        verdict = (
            f"<div style='margin-top:9px;padding-top:8px;"
            f"border-top:1px solid {CARD_BORDER};display:flex;"
            f"justify-content:space-between;align-items:baseline'>"
            f"<span style='font-size:11px;letter-spacing:.12em;font-weight:700;"
            f"color:{MUTED}'>{VERDICT_LABEL}</span>"
            f"<span style='font-size:26px;font-weight:900;line-height:1.1;"
            f"color:{gt}'>"
            f"{_esc(word)}"
            # ⚠️ A separator, not just a margin — extracted as text the two ran
            # together and read as "WAIT100/100".
            + (f"<span style='font-size:14px;color:{MUTED};font-weight:700;"
               f"margin-left:8px'>· {conf:.0f}/100</span>"
               if conf is not None else "")
            + "</span></div>")

    # ── the reason, from the layer's own words ───────────────────────
    # Brought up from 10.5px/MUTED: this sentence is what explains the verdict
    # above it, and it was set smaller than the rows it was explaining.
    reason = _reason_line(o, word)
    note = (f"<div style='font-size:12.5px;font-weight:600;color:{INK};"
            f"margin-top:6px'>{_esc(reason)}</div>" if reason else "")

    foot = (f"<div style='font-size:10px;color:{MICRO};margin-top:6px'>"
            f"Context and confirmation — greeks modify confidence, they do not "
            f"make the call. Greek weighting: "
            f"{_esc(str(_get(o, 'regime') or '—'))}</div>")

    missing = [str(m).replace("_", " ") for m in (_get(o, "missing") or ())]
    if missing:
        note += (f"<div style='font-size:9.5px;color:{MICRO};margin-top:3px'>"
                 f"⚪ not reporting: {_esc(' · '.join(missing))}</div>")

    return _card("⚙️ Dealer & volatility context",
                 "".join(rows) + verdict + note + foot)


def _reason_line(out: Mapping[str, Any], verdict: Any = None) -> str:
    """One sentence, taken from the layer's own conflict verdicts.

    A conflict is the most actionable thing the layer produces, so it leads. With
    no conflict the confidence reasons stand in. Nothing is re-phrased — the words
    are `adaptive_greeks`'s, so this panel and any other surface say the same
    thing about the same cycle.
    """
    cfl = list(_get(out, "conflicts") or ())
    if cfl:
        first = cfl[0] if isinstance(cfl[0], Mapping) else {}
        verdict = str(_get(first, "verdict") or "").strip()
        why = str(_get(first, "why") or "").strip()
        return f"{verdict} — {why}" if verdict and why else (verdict or why)

    mods = _get(out, "modifiers") or {}
    why = list(_get(mods, "confidence_why") or ())
    line = "; ".join(str(w) for w in why[:2]).capitalize() if why else ""

    # ⚠️ `confidence_why` only records what MOVED the confidence, and a cycle can
    # have one positive entry and nothing else. That produced a reason reading
    # "Dealer hedging supports the move" directly under "Fade risk HIGH 65%" —
    # the one-sidedness a review flagged as the card contradicting itself.
    #
    # `risk_level` is the layer's own conclusion, already computed in
    # `_modifiers` from the same fade figure, and it reached no surface at all
    # (principle 12: a computed decision must be inspectable). Appended, not
    # re-worded — the counterweight is the engine's, not this panel's.
    # ⚠️ MEDIUM as well as HIGH, and it names the number.
    #
    # This fired only on HIGH (fade ≥ 60), so a cycle reading **fade 55%** —
    # MEDIUM — showed the positive half alone: "Dealer hedging supports…" sitting
    # directly under a GUARDIAN WAIT, which was reported as the card contradicting
    # itself. 55% favours a failed move, and that is the reason the Guardian is
    # waiting; it has to appear in the sentence that explains the wait.
    #
    # The percentage is `_modifiers`' own `fade_probability`, quoted not derived,
    # and "wait for confirmation" describes the greeks' limitation — it does not
    # manufacture a side. The Guardian's verdict is untouched either way.
    # ⚠️ The tail depends on WHAT WAS DECIDED. It read "wait for confirmation"
    # whatever the verdict, so a cycle with `ENTER · 100/100` printed
    # "Fade risk 55%; wait for confirmation" directly beneath it — the card telling
    # the trader to wait for the entry it had just issued. Reported, and it is the
    # same contradiction as the WAIT case in mirror image.
    #
    # Under an actionable verdict the greeks' honest role is to flag the risk ON
    # that entry, not to countermand it: they modify confidence, they do not make
    # the call. The fade figure is quoted either way; only the clause changes.
    risk = str(_get(mods, "risk_level") or "").strip().upper()
    fade = _f(_get(mods, "fade_probability"))
    if risk in ("HIGH", "MEDIUM") and "fade" not in line.lower():
        clause = ACT_CLAUSE if _is_actionable(verdict) else WAIT_CLAUSE
        tail = (f"fade risk {fade:.0f}%; {clause}" if fade is not None else
                f"{risk.lower()} fade/pin risk; {clause}")
        line = f"{line} — {tail}" if line else tail.capitalize()
    return line


# ══════════════════════════════════════════════════════════════════════
#  the short forms
# ══════════════════════════════════════════════════════════════════════

def micro(out: Any = None) -> str:
    """The header chip. `""` when there is nothing worth a chip.

    Two facts and a risk, because the strip is frozen on every screen and each
    row it grows costs that space all session: dealer posture, gamma sign, and
    the fade risk that follows from them.
    """
    o = out if isinstance(out, Mapping) else {}
    dealer = _get(o, "dealer") or {}
    mods = _get(o, "modifiers") or {}
    posture = str(_get(dealer, "posture") or "").upper()
    if not posture or posture == "UNKNOWN":
        return ""
    # ⚠️ Same fix as the card, and it matters more here: the chip is frozen on
    # every screen, so "dealer supportive" with no object would be the version a
    # trader reads all session. With no flow direction, say what hedging does to
    # movement instead.
    if _get(dealer, "relative_to"):
        emoji = POSTURE.get(posture, POSTURE["UNKNOWN"])[0]
        bits = [f"{emoji} dealer {posture.lower()} of flow"]
    else:
        amp = AMPLIFICATION.get(str(_get(dealer, "amplification") or "").upper())
        if not amp:
            return ""
        bits = [f"🟡 dealers {amp}"]
    gamma = str(_get(dealer, "gamma") or "").upper()
    if gamma in ("POSITIVE", "NEGATIVE"):
        bits.append(f"{'+' if gamma == 'POSITIVE' else '−'}γ")
    fade = _band(_get(mods, "fade_probability"))
    if fade != "—":
        bits.append(f"fade {fade.lower()}")
    return "⚙️ " + " · ".join(bits)


def one_line(out: Any = None) -> str:
    """The Trade Card / Market Picture line — plain text, one sentence.

    Short on purpose: those two surfaces already carry a verdict, and this adds
    the terrain it has to cross, not a second opinion about it.
    """
    o = out if isinstance(out, Mapping) else {}
    dealer = _get(o, "dealer") or {}
    pressure = _get(o, "pressure") or {}
    mods = _get(o, "modifiers") or {}
    posture = str(_get(dealer, "posture") or "").upper()
    if not posture or posture == "UNKNOWN":
        return ""
    if _get(dealer, "relative_to"):
        parts = [f"Dealers {posture.lower()} of flow"]
    else:
        amp = AMPLIFICATION.get(str(_get(dealer, "amplification") or "").upper())
        if not amp:
            return ""
        parts = [f"Dealers {amp}"]
    gamma = str(_get(dealer, "gamma") or "").title()
    if gamma in ("Positive", "Negative"):
        parts.append(f"{gamma.lower()} gamma")
    mg = _f(_get(pressure, "magnet"))
    if mg is not None and _get(pressure, "near"):
        parts.append(f"magnet ₹{mg:,.0f}")
    fade = _band(_get(mods, "fade_probability"))
    if fade in ("MEDIUM", "HIGH"):
        parts.append(f"{fade.lower()} fade risk")
    return " · ".join(parts) + "."


def verdict_micro(word: Any = None, confidence: Any = None) -> str:
    """`ENTRY GATE · ENTER · 100/100` for the header strip. `""` with no verdict.

    ⚠️ The label is carried, not dropped. On the header this sits a few centimetres
    from the Position Guardian's own line, which is exactly the collision that made
    "GUARDIAN ENTER · 100/100" read as the Position Guardian changing its mind.

    Plain text, no markup: `_chrome_extras` collects strings and the header owns the
    styling. Nothing is decided here — both values arrive already decided.
    """
    w = str(word or "").strip()
    if not w:
        return ""
    conf = _f(confidence)
    tail = f" · {conf:.0f}/100" if conf is not None else ""
    return f"{VERDICT_LABEL} {w.upper()}{tail}"
