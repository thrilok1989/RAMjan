"""ATM ±2 — the full per-strike bias grid.

A faithful port of the owner's option-chain bias script: 11 per-strike biases
(LTP · OI · ΔOI · Volume · Delta · Gamma · Bid/Ask · IV · ΔExp · ΓExp · DVP) →
a Score, a Verdict, and the Operator-Entry / Scalp-Moment / Fake-Real reads,
plus the ChgOI and OI "C vs P" comparison strings and a top trade suggestion.

Fetches NOTHING and computes no Greek. Every input — including the real Delta /
Gamma — is read from the option chain the app has ALREADY fetched (`df_summary`
already carries `Delta_CE/PE` and `Gamma_CE/PE` from the chain build). Pure
module: dicts in, dicts / HTML out. No `st`, no I/O, no network.

The bias definitions and the score/verdict banding are kept EXACTLY as the
original (including its quirks: OI/ΔOI read CE-heavy as bearish, and the score
counts a non-bullish metric — Bearish or Neutral — as −1).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

BULLISH, BEARISH, NEUTRAL = "Bullish", "Bearish", "Neutral"

#: the metrics that feed the score, in display order.
BIAS_KEYS = ["LTP", "OI", "ChgOI", "Volume", "Delta", "Gamma", "AskBid", "IV",
             "DeltaExp", "GammaExp", "DVP"]


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else x


def delta_volume_bias(price_diff: float, volume_diff: float,
                      chg_oi_diff: float) -> str:
    """Price / volume / ΔOI confluence — the original's DVP read."""
    if price_diff > 0 and volume_diff > 0 and chg_oi_diff > 0:
        return BULLISH
    if price_diff < 0 and volume_diff > 0 and chg_oi_diff > 0:
        return BEARISH
    if price_diff > 0 and volume_diff > 0 and chg_oi_diff < 0:
        return BULLISH
    if price_diff < 0 and volume_diff > 0 and chg_oi_diff < 0:
        return BEARISH
    return NEUTRAL


def final_verdict(score: int) -> str:
    if score >= 4:
        return "Strong Bull"
    if score >= 2:
        return "Bullish"
    if score <= -4:
        return "Strong Bear"
    if score <= -2:
        return "Bearish"
    return "Neutral"


def _cmp(a: float, b: float) -> str:
    return ">" if a > b else "<" if a < b else "≈"


def strike_row(sd: Mapping[str, Any], strike: float, atm: float,
               underlying: float) -> Dict[str, Any]:
    """All biases + verdict for one strike, from the already-fetched chain row.

    `sd` keys: `ltp_ce/ltp_pe, oi_ce/oi_pe, chg_ce/chg_pe, vol_ce/vol_pe,
    delta_ce/delta_pe, gamma_ce/gamma_pe, bid_ce, ask_ce, iv_ce/iv_pe`.
    """
    ltp_ce, ltp_pe = _f(sd.get("ltp_ce")), _f(sd.get("ltp_pe"))
    oi_ce, oi_pe = _f(sd.get("oi_ce")), _f(sd.get("oi_pe"))
    chg_ce, chg_pe = _f(sd.get("chg_ce")), _f(sd.get("chg_pe"))
    vol_ce, vol_pe = _f(sd.get("vol_ce")), _f(sd.get("vol_pe"))
    d_ce, d_pe = _f(sd.get("delta_ce")), _f(sd.get("delta_pe"))
    g_ce, g_pe = _f(sd.get("gamma_ce")), _f(sd.get("gamma_pe"))
    bid_ce, ask_ce = _f(sd.get("bid_ce")), _f(sd.get("ask_ce"))
    iv_ce, iv_pe = _f(sd.get("iv_ce")), _f(sd.get("iv_pe"))

    b: Dict[str, str] = {}
    b["LTP"] = BULLISH if ltp_ce > ltp_pe else BEARISH
    b["OI"] = BEARISH if oi_ce > oi_pe else BULLISH          # CE-heavy = bearish
    b["ChgOI"] = BEARISH if chg_ce > chg_pe else BULLISH
    b["Volume"] = BULLISH if vol_ce > vol_pe else BEARISH
    b["Delta"] = BULLISH if d_ce > abs(d_pe) else BEARISH
    b["Gamma"] = BULLISH if g_ce > g_pe else BEARISH
    b["AskBid"] = BULLISH if bid_ce > ask_ce else BEARISH
    b["IV"] = BULLISH if iv_ce > iv_pe else BEARISH
    b["DeltaExp"] = BULLISH if (d_ce * oi_ce) > abs(d_pe * oi_pe) else BEARISH
    b["GammaExp"] = BULLISH if (g_ce * oi_ce) > (g_pe * oi_pe) else BEARISH
    b["DVP"] = delta_volume_bias(ltp_ce - ltp_pe, vol_ce - vol_pe, chg_ce - chg_pe)

    # score: +1 for Bullish, −1 for anything else (faithful to the original)
    score = sum(1 if b[k] == BULLISH else -1 for k in BIAS_KEYS)

    zone = ("ATM" if strike == atm else
            "ITM" if strike < underlying else "OTM")
    operator = ("Entry Bull" if b["OI"] == BULLISH and b["ChgOI"] == BULLISH else
                "Entry Bear" if b["OI"] == BEARISH and b["ChgOI"] == BEARISH else
                "No Entry")
    scalp = ("Scalp Bull" if score >= 4 else "Moment Bull" if score >= 2 else
             "Scalp Bear" if score <= -4 else "Moment Bear" if score <= -2 else
             "No Signal")
    fake_real = ("Real Up" if score >= 4 else "Fake Up" if 1 <= score < 4 else
                 "Real Down" if score <= -4 else
                 "Fake Down" if -4 < score <= -1 else "No Move")

    return {
        "strike": strike, "zone": zone, "biases": b, "score": score,
        "verdict": final_verdict(score), "operator": operator,
        "scalp": scalp, "fake_real": fake_real,
        "chgoi_cmp": f"{chg_ce/1000:.0f}K {_cmp(chg_ce, chg_pe)} {chg_pe/1000:.0f}K",
        "oi_cmp": f"{oi_ce/1e6:.2f}M {_cmp(oi_ce, oi_pe)} {oi_pe/1e6:.2f}M",
    }


def grid(strikes: Sequence[Tuple[float, Mapping[str, Any]]], atm: float,
         underlying: float) -> List[Dict[str, Any]]:
    """Run `strike_row` for each `(strike, sd)` given, in order."""
    return [strike_row(sd, sp, atm, underlying) for sp, sd in strikes]


def top_suggestion(rows: Sequence[Mapping[str, Any]]) -> str:
    """The original's headline: the strongest-scoring strike's implied trade."""
    if not rows:
        return ""
    best = max(rows, key=lambda r: abs(r.get("score", 0)))
    side = "CALL" if best["score"] > 0 else "PUT"
    momo = "STRONG" if abs(best["score"]) >= 4 else "MODERATE"
    return (f"📢 TRADE {side} · Momentum {momo} · Move {best['fake_real'].upper()}"
            f" · Suggested {best['scalp'].upper()}")


# ── rendering (pure HTML) ───────────────────────────────────────────────

_EMO = {BULLISH: ("🐂", "#00c853"), BEARISH: ("🐻", "#ff3b30"),
        NEUTRAL: ("⚖️", "#c9a227")}
_VERD_COL = {"Strong Bull": "#00e676", "Bullish": "#7bd88f",
             "Strong Bear": "#ff5252", "Bearish": "#ff8a80", "Neutral": "#ffd54f"}
_COLS = ["Strike", "Zone", "LTP", "OI", "ΔOI", "Vol", "Δ", "Γ", "Bid/Ask",
         "IV", "ΔExp", "ΓExp", "DVP", "Score", "Verdict", "Operator",
         "Scalp/Mom", "Fake/Real", "ChgOI C·P", "OI C·P"]


def grid_html(rows: Sequence[Mapping[str, Any]], atm: float) -> str:
    """The full bias grid — the top suggestion, then a per-strike table with
    every bias, the score/verdict and the operator/scalp/fake reads. `""` when
    there is nothing to show."""
    if not rows:
        return ""
    head = (
        "<div style='margin:8px 0 4px;font-weight:800;color:#dbe4ee;font-size:14px;'>"
        "📊 ATM ±2 — Full Bias Grid (11 biases → verdict)</div>"
        f"<div style='margin-bottom:5px;font-weight:700;color:#e6dbff;font-size:12.5px;'>"
        f"{top_suggestion(rows)}</div>")

    header = ("<tr style='background:#0e1420;color:#fff;'>"
              + "".join(f"<th style='padding:5px 6px;border:1px solid #223;font-size:10px;'>{c}</th>"
                        for c in _COLS) + "</tr>")
    body = ""
    for r in rows:
        is_atm = r["strike"] == atm
        rst = ("background:#f5d000;color:#000;font-weight:700;" if is_atm
               else "background:#141c28;color:#e8eef5;")
        b = r["biases"]

        def _cell(bias):
            emo, col = _EMO.get(bias, ("⚖️", "#c9a227"))
            return (f"<td style='padding:4px;border:1px solid #223;text-align:center;'>"
                    f"<span style='color:{col};font-size:12px;'>{emo}</span></td>")

        cells = (f"<td style='padding:4px 6px;border:1px solid #223;text-align:center;font-weight:700;'>{r['strike']:.0f}</td>"
                 f"<td style='padding:4px 6px;border:1px solid #223;text-align:center;font-size:10px;'>{r['zone']}</td>")
        for k in BIAS_KEYS:
            cells += _cell(b[k])
        _scol = "#00e676" if r["score"] > 0 else "#ff5252" if r["score"] < 0 else "#ffd54f"
        cells += (f"<td style='padding:4px 6px;border:1px solid #223;text-align:center;"
                  f"font-weight:800;color:{_scol};'>{r['score']:+d}</td>")
        _vc = _VERD_COL.get(r["verdict"], "#ffd54f")
        cells += (f"<td style='padding:4px 6px;border:1px solid #223;text-align:center;"
                  f"font-weight:700;color:{_vc};font-size:11px;'>{r['verdict']}</td>")
        for key in ("operator", "scalp", "fake_real", "chgoi_cmp", "oi_cmp"):
            cells += (f"<td style='padding:4px 6px;border:1px solid #223;text-align:center;"
                      f"font-size:10px;white-space:nowrap;'>{r[key]}</td>")
        body += f"<tr style='{rst}'>{cells}</tr>"

    table = ("<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;'>"
             + header + body + "</table></div>")
    note = ("<div style='color:#8a95a3;font-size:10px;margin-top:3px;'>"
            "🐂 bullish · 🐻 bearish · ⚖️ neutral. OI/ΔOI read CE-heavy as bearish. "
            "Real Δ/Γ and all inputs from the already-fetched chain. Context only.</div>")
    return head + table + note
