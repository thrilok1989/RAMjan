"""Market snapshot for AI analysis — one text block of everything that matters.

A button in the app gathers the reads the app ALREADY produced and hands them
here; this formats them into one structured, LLM-friendly message the trader
forwards to an AI to analyse the market. Computes nothing — numbers/strings in,
text out. Pure: no `st`, no I/O.

Every field is optional: a section whose inputs are all absent is skipped, so a
partial cycle still produces a clean snapshot rather than rows of blanks.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence

#: Telegram hard-caps a message at 4096 chars; keep a margin for HTML/edges.
CHUNK_LIMIT = 3800


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _price(v: Any) -> Optional[str]:
    x = _f(v)
    return f"₹{x:,.0f}" if x is not None else None


def _pct(v: Any) -> Optional[str]:
    x = _f(v)
    return f"{x:.0f}%" if x is not None else None


def _s(v: Any) -> Optional[str]:
    v = None if v is None else str(v).strip()
    return v or None


def _line(label: str, *parts: Optional[str]) -> Optional[str]:
    kept = [p for p in parts if p]
    return f"{label}: {' · '.join(kept)}" if kept else None


def _section(title: str, lines: Sequence[Optional[str]]) -> Optional[str]:
    body = [ln for ln in lines if ln]
    return title + "\n" + "\n".join(body) if body else None


def build(d: Optional[Mapping[str, Any]]) -> str:
    """One snapshot string from the gathered reads `d` (all keys optional)."""
    d = d or {}
    g = d.get

    header_bits = ["📊 MARKET SNAPSHOT — NIFTY"]
    if _s(g("time")):
        header_bits.append(str(g("time")))
    header = " · ".join(header_bits)
    spot = _line("Spot", _price(g("spot")))

    regime = _section("🧭 REGIME", [
        _line("Bias", _s(g("regime"))),
        _line("Odds", (f"Up {p}" if (p := _pct(g("p_up"))) else None),
              (f"Down {p}" if (p := _pct(g("p_down"))) else None),
              (f"Side {p}" if (p := _pct(g("p_side"))) else None)),
        _line("Breakout/Rejection",
              (f"Breakout {p}" if (p := _pct(g("breakout"))) else None),
              (f"Rejection {p}" if (p := _pct(g("rejection"))) else None)),
        _line("Day", _s(g("day_type")), _s(g("session"))),
    ])

    levels = _section("📐 LEVELS", [
        _line("Support / Resistance", _price(g("support")), _price(g("resistance"))),
        _line("War zone", _price(g("war_zone"))),
        _line("VWAP", _price(g("vwap"))),
        _line("Value area", (f"POC {p}" if (p := _price(g("poc"))) else None),
              (f"VAH {p}" if (p := _price(g("vah"))) else None),
              (f"VAL {p}" if (p := _price(g("val"))) else None)),
        _line("OI walls", (f"CE {p}" if (p := _price(g("oi_ce_wall"))) else None),
              (f"PE {p}" if (p := _price(g("oi_pe_wall"))) else None)),
        _line("Dealer magnet", _price(g("magnet"))),
        _line("Expected winner", _s(g("expected_winner"))),
    ])

    options = _section("🅾️ OPTIONS (ATM±2)", [
        _line("ATM verdict", _s(g("atm_verdict")),
              (f"score {s}" if (s := _s(g("atm_score"))) else None)),
        _line("PCR", _s(g("pcr"))),
        _line("ΔOI bias", _s(g("doi_bias"))),
        _line("CALL", _s(g("call_mode")),
              (f"str {p}" if (p := _pct(g("call_strength"))) else None)),
        _line("PUT", _s(g("put_mode")),
              (f"str {p}" if (p := _pct(g("put_strength"))) else None)),
        _line("Writing/Capping", _s(g("writing"))),
    ])

    dealer = _section("⚙️ DEALER / GREEKS", [
        _line("GEX", _s(g("total_gex")),
              (f"flip {p}" if (p := _price(g("gamma_flip"))) else None),
              _s(g("gex_signal"))),
        _line("DEX", _s(g("dex"))),
        _line("Net vanna/charm/vega", _s(g("net_vanna")), _s(g("net_charm")),
              _s(g("net_vega"))),
        _line("Greek behaviour", _s(g("greek_behaviour"))),
        _line("Skew", _s(g("skew"))),
    ])

    flow = _section("🌊 FLOW", [
        _line("CVD / order flow", _s(g("cvd"))),
        _line("Money flow", _s(g("money_flow"))),
    ])

    la = g("level_acceptance")
    la_lines = ([_s(x) for x in la] if isinstance(la, (list, tuple))
                else [_s(la)])
    acceptance = _section("⚔️ LEVEL ACCEPTANCE", la_lines)

    context = _section("🌍 CONTEXT", [
        _line("Global", _s(g("global"))),
        _line("News", _s(g("news"))),
        _line("Commodity", _s(g("commodity"))),
        _line("FII/DII", _s(g("fii_dii"))),
    ])

    ask = ("— — —\nPlease analyse this NIFTY options market completely: the most "
           "likely direction, key levels to watch, the highest-probability trade "
           "(CALL/PUT/wait) with entry, stop and target, and the main risks.")

    blocks = [b for b in (header, spot, regime, levels, options, dealer, flow,
                          acceptance, context, ask) if b]
    return "\n\n".join(blocks)


def chunks(text: str, limit: int = CHUNK_LIMIT) -> List[str]:
    """Split into Telegram-sized parts on blank-line boundaries, labelled
    `(1/N)` when more than one is needed."""
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    parts: List[str] = []
    cur = ""
    for block in text.split("\n\n"):
        if cur and len(cur) + len(block) + 2 > limit:
            parts.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        parts.append(cur)
    n = len(parts)
    return [f"({i}/{n})\n{p}" if n > 1 else p for i, p in enumerate(parts, 1)]
