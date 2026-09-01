"""🏛 FII / DII institutional flows — the big-money footprint, on the dashboard.

## What this shows

    FII cash   foreign institutions, cash segment, ₹ crore buy / sell / net
    DII cash   domestic institutions (MFs, insurers, banks), same
    Combined   the cleanest single read, because the two often offset
    FII derivatives  index futures long / short / net, in contracts

## ⚠️ END-OF-DAY. This is not an intraday signal.

NSE publishes FII/DII cash once daily, around 18:00–19:00 IST, for the session
that just closed. The participant-wise OI archive is the same. So during live
trading every number here describes **yesterday**, and the panel says so on its
own face — not in a docstring — because a ₹-crore figure sitting beside live
intraday panels reads as current unless it is labelled otherwise.

`stage23_flows` already states this ("a slow, daily CONTEXT lean — not an
intraday trigger") and weights itself low accordingly.

## The verdict is READ, never re-derived

`stage23_flows` owns the thresholds (`_STRONG = 2500`, `_MILD = 800` ₹cr), the
bias, and the absorption-battle detection — *"if FII and DII disagree strongly,
damp conviction"*. This panel takes that engine's `bias`, `confidence` and its
`conflict` flag as parameters.

⚠️ Re-implementing "is ₹2,500cr a lot?" here would put a second answer to one
question on screen, and the two would drift the first time either moved. The one
thing this file computes is `buy − sell`, and only to check the feed's own `net`
against it.

Pure module — data in, HTML out. No streamlit, no session state.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .nifty_cockpit import _card, _esc, _f, _get, _n, _row
from .theme import (BEAR, BULL, CARD_BORDER, INK, LABEL, MICRO, MUTED, VIOLET,
                    WARN)

#: The two categories, in the order they matter. FII leads because it is the
#: dominant driver of index direction; DII is read as the absorbing side.
SIDES = ("FII", "DII")

#: Longest a published figure may be before the panel calls it out as old.
#:
#: ⚠️ Not a market judgement — a feed-health one. NSE publishes every trading
#: evening, so a figure more than a few days old means the fetch has been
#: failing, and stale institutional flows presented as current are worse than
#: none. Days, because the data itself is daily.
STALE_DAYS = 4

#: What the engine's bias words become on screen.
BIAS_TONE = {"STRONG_BULL": BULL, "BULL": BULL, "NEUTRAL": WARN,
             "BEAR": BEAR, "STRONG_BEAR": BEAR}
BIAS_EMOJI = {"STRONG_BULL": "🟢", "BULL": "🟢", "NEUTRAL": "🟡",
              "BEAR": "🔴", "STRONG_BEAR": "🔴"}


def _cr(v: Any) -> str:
    """₹ crore, signed, with a thousands separator. `—` when absent.

    Signed always: an institutional net of `1,240` and `-1,240` are opposite
    facts and an unsigned number leaves the reader to guess from a colour.
    """
    x = _f(v)
    return "—" if x is None else f"{x:+,.0f}"


def _side_read(entry: Any) -> Dict[str, Any]:
    """One category's buy / sell / net, and whether the three agree.

    ⚠️ `net` is taken from the feed, not computed, so the panel shows what NSE
    published. `buy − sell` is computed only to *check* it: a mismatch means the
    payload changed shape or a field arrived empty, and silently trusting one of
    three inconsistent numbers is how a wrong ₹-crore figure ends up on screen
    looking authoritative.
    """
    e = entry if isinstance(entry, Mapping) else {}
    buy, sell = _f(e.get("buy")), _f(e.get("sell"))
    net = _f(e.get("net"))
    derived = (buy - sell) if (buy is not None and sell is not None) else None
    mismatch = (net is not None and derived is not None
                and abs(net - derived) > 1.0)
    return {"buy": buy, "sell": sell, "net": net, "derived": derived,
            "mismatch": mismatch, "date": str(e.get("date") or "").strip(),
            "reporting": net is not None or derived is not None}


def read(cash: Any = None, deriv: Any = None) -> Dict[str, Any]:
    """`{sides, combined, as_of, deriv, reporting, notes}` — resolved once.

    Separate from the HTML so the cockpit block, a header chip and any test all
    see the same resolution of a payload that arrives in three states: absent,
    partial (FII published, DII not), and complete.
    """
    c = cash if isinstance(cash, Mapping) else {}
    sides = {s: _side_read(c.get(s)) for s in SIDES}

    nets = [sides[s]["net"] for s in SIDES if sides[s]["net"] is not None]
    combined = sum(nets) if nets else None

    as_of = ""
    for s in SIDES:
        if sides[s]["date"]:
            as_of = sides[s]["date"]
            break

    notes: List[str] = []
    for s in SIDES:
        if sides[s]["mismatch"]:
            notes.append(f"{s} buy−sell does not match the published net")
    silent = [s for s in SIDES if not sides[s]["reporting"]]
    if silent and len(silent) < len(SIDES):
        notes.append(f"{' · '.join(silent)} not published yet")

    d = deriv if isinstance(deriv, Mapping) else {}
    return {
        "sides": sides,
        "combined": combined,
        # ⚠️ Only meaningful when BOTH published — a "combined" figure that is
        # really just FII would read as agreement between two parties when one
        # of them has not reported.
        "combined_complete": len(nets) == len(SIDES),
        "as_of": as_of,
        "deriv": {
            "date": str(d.get("date") or "").strip(),
            "fut_long": _f(d.get("fut_index_long")),
            "fut_short": _f(d.get("fut_index_short")),
            "fut_net": _f(d.get("fut_index_net")),
            "call_long": _f(d.get("opt_index_call_long")),
            "put_long": _f(d.get("opt_index_put_long")),
            "call_short": _f(d.get("opt_index_call_short")),
            "put_short": _f(d.get("opt_index_put_short")),
        },
        "reporting": bool(nets),
        "notes": notes,
    }


def fii_dii_html(cash: Any = None, deriv: Any = None, bias: Any = None,
                 confidence: Any = None, conflict: Any = None,
                 evidence: Any = None) -> str:
    """The block. `""` when nothing published — never a row of zeroes.

    `bias`, `confidence`, `conflict` and `evidence` come from `stage23_flows`.
    Absent them the block still shows the numbers and simply omits the verdict
    line: the flows are a fact worth seeing on their own, and inventing a lean
    to fill the row is the one thing this file must not do.
    """
    r = read(cash, deriv)
    if not r["reporting"]:
        return ""

    rows: List[str] = []
    for s in SIDES:
        sd = r["sides"][s]
        if not sd["reporting"]:
            rows.append(_row(f"{s} cash", "⚪ not published", MUTED))
            continue
        net = sd["net"] if sd["net"] is not None else sd["derived"]
        tone = BULL if (net or 0) > 0 else BEAR if (net or 0) < 0 else MUTED
        extra = ""
        if sd["buy"] is not None and sd["sell"] is not None:
            extra = f"buy {_n(sd['buy'])} · sell {_n(sd['sell'])}"
        rows.append(_row(f"{s} cash", f"₹{_cr(net)} Cr", tone, extra))

    if r["combined"] is not None and r["combined_complete"]:
        tone = (BULL if r["combined"] > 0 else BEAR if r["combined"] < 0
                else MUTED)
        rows.append(_row("Combined", f"₹{_cr(r['combined'])} Cr", tone,
                         "FII + DII"))

    # ── FII index derivatives, when the archive was reachable ─────────
    dv = r["deriv"]
    if dv["fut_net"] is not None:
        tone = (BULL if dv["fut_net"] > 0 else BEAR if dv["fut_net"] < 0
                else MUTED)
        # ⚠️ "contracts", always. Caught by rendering: a bare `-58,750` sitting
        # directly under `₹-4,222 Cr` rows reads as another crore figure, and the
        # two units are not remotely comparable.
        extra = "contracts"
        if dv["fut_long"] is not None and dv["fut_short"] is not None:
            extra = f"L {_n(dv['fut_long'])} · S {_n(dv['fut_short'])} contracts"
        rows.append(_row("FII index futures", f"{_cr(dv['fut_net'])}", tone,
                         extra))
    opt = _option_row(dv)
    if opt:
        rows.append(opt)

    # ── the engine's verdict, read ────────────────────────────────────
    verdict = ""
    word = str(bias or "").strip().upper()
    if word:
        conf = _f(confidence)
        emoji = BIAS_EMOJI.get(word, "🟡")
        tone = BIAS_TONE.get(word, WARN)
        verdict = (
            f"<div style='margin-top:7px;padding-top:6px;"
            f"border-top:1px solid {CARD_BORDER};display:flex;"
            f"justify-content:space-between;align-items:baseline'>"
            # ⚠️ "(cash)" is not decoration. `stage23_flows` reads `raw["fii_dii"]`
            # — the CASH segment only — so the two derivatives rows above are
            # context the engine never considered. Rendering showed a STRONG BULL
            # verdict directly beneath "FII index futures −58,750 contracts",
            # which is heavily short: real behaviour (hedged cash longs), and an
            # apparent self-contradiction unless the verdict says what it read.
            f"<span style='font-size:9px;letter-spacing:.12em;color:{MICRO}'>"
            f"STAGE 23 FLOWS (cash)</span>"
            f"<span style='font-size:13px;font-weight:800;color:{tone}'>"
            f"{emoji} {_esc(word.replace('_', ' '))}"
            + (f"<span style='font-size:11px;color:{MICRO};font-weight:600;"
               f"margin-left:6px'>{conf:.0f}/100</span>"
               if conf is not None else "")
            + "</span></div>")

    # ⚠️ The absorption battle, in the engine's own terms. When FII and DII pull
    # opposite ways the net is NOT a directional edge, and that is the single
    # most important thing this block can say — a reader who sees "FII −4,200"
    # without "DII +4,000 absorbing it" reads a one-sided rout.
    if conflict:
        rows.append(
            f"<div style='margin-top:5px;font-size:10.5px;color:{WARN}'>"
            f"⚔️ FII and DII pulling opposite ways — absorption battle, not a "
            f"clean directional edge.</div>")

    note = _evidence_line(evidence)
    body = "".join(rows) + verdict + note + _stamp(r)
    return _card("🏛 Institutional flows (FII / DII)", body)


def _option_row(dv: Mapping[str, Any]) -> str:
    """FII index options, as the net call and net put position.

    Four raw contract counts are four numbers nobody reads. Netted per side they
    answer one question: which way are foreign institutions positioned in index
    options? Long calls and short puts both lean up; the reverse leans down.
    """
    cl, cs = _f(dv.get("call_long")), _f(dv.get("call_short"))
    pl, ps = _f(dv.get("put_long")), _f(dv.get("put_short"))
    if None in (cl, cs, pl, ps):
        return ""
    call_net, put_net = cl - cs, pl - ps
    return _row("FII index options",
                f"CE {_cr(call_net)} · PE {_cr(put_net)}", MUTED,
                "net long contracts")


def _evidence_line(evidence: Any) -> str:
    """Stage 23's own sentence, quoted.

    Not re-worded: the engine writes "FII −4,200cr · DII +4,000cr · net −200cr
    (as of 08-Aug-2026, EOD)", and a second phrasing here would let the panel and
    the engine describe one day differently.
    """
    for line in (evidence or ()):
        text = str(line).strip()
        if text:
            return (f"<div style='font-size:10.5px;color:{MUTED};"
                    f"margin-top:5px'>{_esc(text)}</div>")
    return ""


def _stamp(r: Mapping[str, Any]) -> str:
    """The date, and the warning that this is not intraday.

    ⚠️ Always rendered, never conditional. Every other block on this dashboard
    is live, so a ₹-crore figure among them reads as current unless something
    says otherwise on the same card.
    """
    as_of = str(r.get("as_of") or "")
    dv_date = str((r.get("deriv") or {}).get("date") or "")
    bits = []
    if as_of:
        bits.append(f"cash as of {as_of}")
    if dv_date and dv_date != as_of:
        bits.append(f"derivatives {dv_date}")
    when = " · ".join(bits) if bits else "date not published"

    out = (f"<div style='font-size:9px;color:{MICRO};margin-top:5px'>"
           f"⏳ END-OF-DAY — previous session, published ~18:30 IST. A daily "
           f"context lean, not an intraday trigger. {_esc(when)}</div>")
    for n in (r.get("notes") or ()):
        out += (f"<div style='font-size:9.5px;color:{WARN};margin-top:3px'>"
                f"⚠️ {_esc(str(n))}</div>")
    return out


# ══════════════════════════════════════════════════════════════════════
#  the short form
# ══════════════════════════════════════════════════════════════════════

def micro(cash: Any = None, conflict: Any = None) -> str:
    """One line for the external-context row. `""` when nothing published.

    Both sides when both published, because FII alone is the number that gets
    misread — `FII −4,200` is a rout or a non-event depending entirely on what
    DII did against it.
    """
    r = read(cash)
    if not r["reporting"]:
        return ""
    parts = []
    for s in SIDES:
        net = r["sides"][s]["net"]
        if net is not None:
            parts.append(f"{s} {net:+,.0f}")
    if not parts:
        return ""
    line = "🏛 " + " · ".join(parts) + " Cr"
    if conflict:
        line += " · absorption battle"
    return line + " (EOD)"
