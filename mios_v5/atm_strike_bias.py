"""ATM ±2 strikes — the 14-metric per-strike bias tabulation (seller's view).

Ported from `seller_perspective.py` (`analyze_individual_strike_bias` +
`display_atm_strikes_tabulation`) so the same table can render inside the main
app, unchanged in logic.

**Fetches nothing.** Every input — OI, ΔOI, volume, LTP, IV, and the bid/ask
depth — is read from the option chain the app has ALREADY pulled. The original's
14th-ish "market depth" metric called a 20-level depth API; here it reuses the
bid/ask quantities already carried on `df_summary` (`Depth_CE`/`Depth_PE`), so no
new network call is made. Pure module: numbers in, dicts / HTML out. No `st`, no
I/O, no pandas.

The 14 metrics, in table order:
    OI · ChgOI · Volume · Delta · Gamma · Premium · IV · DeltaExp · GammaExp ·
    IVSkew · OIChgRate · PCR · MktDepth · BA
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

#: metric keys in table order, and their short column headers.
METRIC_KEYS = ["OI", "ChgOI", "Volume", "Delta", "Gamma", "Premium", "IV",
               "DeltaExp", "GammaExp", "IVSkew", "OIChgRate", "PCR",
               "MktDepth", "BA"]
COLUMN_HEADERS = ["Strike", "OI", "ChgOI", "Vol", "Δ", "γ", "Prem", "IV",
                  "ΔExp", "γExp", "IVSkew", "OIRate", "PCR", "MktDepth", "BA",
                  "Verdict"]

_BULL, _BEAR, _NEU = "🐂", "🐻", "⚖️"


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else x


def strike_bias(sd: Mapping[str, Any], strike_price: float,
                atm_strike: float) -> Dict[str, Any]:
    """The 14 seller's-perspective bias metrics for ONE strike.

    `sd` carries the already-fetched per-strike numbers:
    `oi_ce/oi_pe, chg_ce/chg_pe, vol_ce/vol_pe, ltp_ce/ltp_pe, iv_ce/iv_pe,
    bid_ce/bid_pe, ask_ce/ask_pe`. Returns `{strike_price, bias_scores,
    bias_emojis, bias_interpretations, total_bias, verdict, verdict_color}` —
    the same shape the original produced.
    """
    ce_oi, pe_oi = _f(sd.get("oi_ce")), _f(sd.get("oi_pe"))
    ce_chg, pe_chg = _f(sd.get("chg_ce")), _f(sd.get("chg_pe"))
    ce_vol, pe_vol = _f(sd.get("vol_ce")), _f(sd.get("vol_pe"))
    ce_ltp, pe_ltp = _f(sd.get("ltp_ce")), _f(sd.get("ltp_pe"))
    ce_iv, pe_iv = _f(sd.get("iv_ce")), _f(sd.get("iv_pe"))
    ce_bid, pe_bid = _f(sd.get("bid_ce")), _f(sd.get("bid_pe"))
    ce_ask, pe_ask = _f(sd.get("ask_ce")), _f(sd.get("ask_pe"))

    scores: Dict[str, float] = {}
    emojis: Dict[str, str] = {}
    interp: Dict[str, str] = {}

    # 1. OI
    oi_ratio = pe_oi / max(ce_oi, 1)
    scores["OI"], emojis["OI"] = ((1, _BULL) if oi_ratio > 1.3 else
                                  (-1, _BEAR) if oi_ratio < 0.77 else (0, _NEU))
    interp["OI"] = f"PE/CE OI: {oi_ratio:.2f}"

    # 2. Change in OI
    if ce_chg > 0 and pe_chg > 0:
        chg_ratio = pe_chg / max(ce_chg, 1)
        scores["ChgOI"], emojis["ChgOI"] = (
            (1, _BULL) if chg_ratio > 1.2 else
            (-1, _BEAR) if chg_ratio < 0.83 else (0, _NEU))
    elif pe_chg > 0:
        scores["ChgOI"], emojis["ChgOI"] = 1, _BULL
    elif ce_chg > 0:
        scores["ChgOI"], emojis["ChgOI"] = -1, _BEAR
    else:
        scores["ChgOI"], emojis["ChgOI"] = 0, _NEU
    interp["ChgOI"] = f"CE:{ce_chg:,.0f} PE:{pe_chg:,.0f}"

    # 3. Volume
    vol_ratio = pe_vol / max(ce_vol, 1)
    scores["Volume"], emojis["Volume"] = (
        (1, _BULL) if vol_ratio > 1.2 else
        (-1, _BEAR) if vol_ratio < 0.83 else (0, _NEU))
    interp["Volume"] = f"PE/CE Vol: {vol_ratio:.2f}"

    # 4. Delta (position relative to ATM)
    if strike_price < atm_strike:
        delta_bias = 1 if pe_oi > ce_oi else -0.5
    elif strike_price > atm_strike:
        delta_bias = -1 if ce_oi > pe_oi else 0.5
    else:
        delta_bias = 1 if pe_oi > ce_oi * 1.2 else (-1 if ce_oi > pe_oi * 1.2 else 0)
    scores["Delta"] = delta_bias
    emojis["Delta"] = _BULL if delta_bias > 0 else (_BEAR if delta_bias < 0 else _NEU)
    interp["Delta"] = f"Position: {'ITM' if abs(strike_price - atm_strike) < 50 else 'OTM'}"

    # 5. Gamma (highest at ATM)
    dist = abs(strike_price - atm_strike)
    if dist == 0:
        gamma_score = 1 if pe_oi > ce_oi else -1
    else:
        gamma_score = 0.5 if pe_oi > ce_oi else -0.5
    scores["Gamma"] = gamma_score
    emojis["Gamma"] = _BULL if gamma_score > 0 else (_BEAR if gamma_score < 0 else _NEU)
    interp["Gamma"] = f"ATM Distance: {dist:.0f}"

    # 6. Premium
    premium_ratio = pe_ltp / max(ce_ltp, 0.01)
    scores["Premium"], emojis["Premium"] = (
        (1, _BULL) if premium_ratio > 1.5 else
        (-1, _BEAR) if premium_ratio < 0.67 else (0, _NEU))
    interp["Premium"] = f"PE/CE Premium: {premium_ratio:.2f}"

    # 7. IV
    iv_diff = pe_iv - ce_iv
    scores["IV"], emojis["IV"] = ((1, _BULL) if iv_diff > 2 else
                                  (-1, _BEAR) if iv_diff < -2 else (0, _NEU))
    interp["IV"] = f"PE-CE IV: {iv_diff:.2f}%"

    # 8. Delta exposure (OI-weighted, simplified ±0.5)
    net_delta_exp = ce_oi * 0.5 + pe_oi * (-0.5)
    scores["DeltaExp"], emojis["DeltaExp"] = (
        (1, _BULL) if net_delta_exp > 0 else
        (-1, _BEAR) if net_delta_exp < 0 else (0, _NEU))
    interp["DeltaExp"] = f"Net ΔExp: {net_delta_exp:,.0f}"

    # 9. Gamma exposure (OI-weighted, simplified)
    net_gamma_exp = ce_oi * 0.01 - pe_oi * 0.01
    scores["GammaExp"], emojis["GammaExp"] = (
        (-1, _BEAR) if net_gamma_exp > 0 else
        (1, _BULL) if net_gamma_exp < 0 else (0, _NEU))
    interp["GammaExp"] = f"Net γExp: {net_gamma_exp:,.0f}"

    # 10. IV skew (average IV regime)
    avg_iv = (ce_iv + pe_iv) / 2
    scores["IVSkew"], emojis["IVSkew"] = (
        (-0.5, _BEAR) if avg_iv > 18 else
        (0.5, _BULL) if avg_iv < 12 else (0, _NEU))
    interp["IVSkew"] = f"Avg IV: {avg_iv:.2f}%"

    # 11. OI change rate (acceleration)
    total_oi = ce_oi + pe_oi
    chg_rate = (abs(ce_chg) + abs(pe_chg)) / max(total_oi, 1) * 100
    if chg_rate > 5:
        scores["OIChgRate"], emojis["OIChgRate"] = (
            (1, _BULL) if pe_chg > ce_chg else (-1, _BEAR))
    else:
        scores["OIChgRate"], emojis["OIChgRate"] = 0, _NEU
    interp["OIChgRate"] = f"Chg Rate: {chg_rate:.2f}%"

    # 12. PCR at strike
    pcr_strike = pe_oi / max(ce_oi, 1)
    scores["PCR"], emojis["PCR"] = ((1, _BULL) if pcr_strike > 1.5 else
                                    (-1, _BEAR) if pcr_strike < 0.67 else (0, _NEU))
    interp["PCR"] = f"Strike PCR: {pcr_strike:.2f}"

    # 13. Market depth — reuses the ALREADY-FETCHED bid/ask depth (no API call).
    ce_total, pe_total = ce_bid + ce_ask, pe_bid + pe_ask
    if ce_total > 0 or pe_total > 0:
        ce_imb = (ce_bid - ce_ask) / max(ce_total, 1)
        pe_imb = (pe_bid - pe_ask) / max(pe_total, 1)
        depth_score = pe_imb - ce_imb
        if depth_score > 0.3:
            scores["MktDepth"], emojis["MktDepth"] = 1, _BULL
        elif depth_score > 0.1:
            scores["MktDepth"], emojis["MktDepth"] = 0.5, _BULL
        elif depth_score < -0.3:
            scores["MktDepth"], emojis["MktDepth"] = -1, _BEAR
        elif depth_score < -0.1:
            scores["MktDepth"], emojis["MktDepth"] = -0.5, _BEAR
        else:
            scores["MktDepth"], emojis["MktDepth"] = 0, _NEU
        interp["MktDepth"] = f"CE:{ce_total:,.0f} PE:{pe_total:,.0f}"
    else:
        scores["MktDepth"], emojis["MktDepth"] = 0, "⚪"
        interp["MktDepth"] = "N/A"

    # 14. Bid/Ask depth (seller's bid vs ask ratios) — same already-fetched data.
    ba = 0.0
    if pe_bid > 0 or ce_bid > 0:
        bid_ratio = pe_bid / max(ce_bid, 1)
        ba += 0.5 if bid_ratio > 1.3 else (-0.5 if bid_ratio < 0.77 else 0)
    if pe_ask > 0 or ce_ask > 0:
        ask_ratio = ce_ask / max(pe_ask, 1)
        ba += 0.5 if ask_ratio > 1.3 else (-0.5 if ask_ratio < 0.77 else 0)
    if ba > 0.5:
        scores["BA"], emojis["BA"] = 1, _BULL
    elif ba < -0.5:
        scores["BA"], emojis["BA"] = -1, _BEAR
    else:
        scores["BA"], emojis["BA"] = 0, "⚪"
    interp["BA"] = (f"Bid: PE/CE {pe_bid/max(ce_bid,1):.2f} | "
                    f"Ask: CE/PE {ce_ask/max(pe_ask,1):.2f}")

    total_bias = sum(scores.values())
    if total_bias >= 3:
        verdict, verdict_color = "🐂 STRONG BULLISH", "#00FF00"
    elif total_bias >= 1:
        verdict, verdict_color = "🐂 Bullish", "#90EE90"
    elif total_bias <= -3:
        verdict, verdict_color = "🐻 STRONG BEARISH", "#FF0000"
    elif total_bias <= -1:
        verdict, verdict_color = "🐻 Bearish", "#FFA07A"
    else:
        verdict, verdict_color = "⚖️ Neutral", "#FFD700"

    return {"strike_price": strike_price, "bias_scores": scores,
            "bias_emojis": emojis, "bias_interpretations": interp,
            "total_bias": total_bias, "verdict": verdict,
            "verdict_color": verdict_color}


def tabulation(strikes: Sequence[Tuple[float, Mapping[str, Any]]],
               atm_strike: float) -> List[Dict[str, Any]]:
    """Run `strike_bias` for each `(strike_price, sd)` given, in order. The
    caller selects the ATM±2 rows from the chain it already holds."""
    return [strike_bias(sd, sp, atm_strike) for sp, sd in strikes]


def _summary(analyses: Sequence[Mapping[str, Any]],
             atm_strike: float) -> Dict[str, Any]:
    atm = next((a for a in analyses if a["strike_price"] == atm_strike), None)
    if not atm:
        return {"verdict": "N/A", "color": "#FFD700", "bull": 0, "bear": 0,
                "total": 14, "score": 0.0}
    bull = sum(1 for s in atm["bias_scores"].values() if s > 0)
    bear = sum(1 for s in atm["bias_scores"].values() if s < 0)
    color = ("#00FF00" if "BULLISH" in atm["verdict"].upper()
             else "#FF0000" if "BEARISH" in atm["verdict"].upper() else "#FFD700")
    return {"verdict": atm["verdict"], "color": color, "bull": bull,
            "bear": bear, "total": len(atm["bias_scores"]),
            "score": atm["total_bias"]}


def tabulation_html(analyses: Sequence[Mapping[str, Any]],
                    atm_strike: float) -> str:
    """The full HTML block — the ATM verdict summary strip plus the per-strike
    14-metric table, ATM row highlighted. `""` when there is nothing to show.
    Pure string; the app wraps it in one `st.markdown`."""
    if not analyses:
        return ""
    s = _summary(analyses, atm_strike)
    pct_b = (s["bull"] / s["total"] * 100) if s["total"] else 0
    pct_r = (s["bear"] / s["total"] * 100) if s["total"] else 0

    head = (
        "<div style='margin:6px 0 4px;font-weight:800;color:#dbe4ee;font-size:14px;'>"
        "📊 ATM ±2 Strikes — 14 Bias Metrics Tabulation</div>"
        "<div style='display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px;'>"
        f"<div style='flex:1;min-width:160px;background:#12210f;border:2px solid {s['color']};"
        "border-radius:10px;padding:8px 12px;text-align:center;'>"
        "<div style='font-size:10px;letter-spacing:.1em;color:#cfd9e6;'>ATM STRIKE VERDICT</div>"
        f"<div style='font-size:20px;font-weight:900;color:{s['color']};'>{s['verdict']}</div>"
        f"<div style='font-size:11px;color:#fff;'>Strike {atm_strike:.0f} · Score {s['score']:+.2f}</div></div>"
        "<div style='flex:1;min-width:120px;background:#0d131d;border:1px solid #1e2836;"
        "border-radius:10px;padding:8px 12px;text-align:center;'>"
        f"<div style='font-size:11px;color:#cfd9e6;'>🐂 Bullish {s['bull']}/{s['total']}</div>"
        f"<div style='font-size:11px;color:#cfd9e6;margin-top:4px;'>🐻 Bearish {s['bear']}/{s['total']}</div></div>"
        "<div style='flex:1;min-width:120px;background:#0d131d;border:1px solid #1e2836;"
        "border-radius:10px;padding:8px 12px;text-align:center;'>"
        f"<div style='font-size:16px;font-weight:700;color:#00ff88;'>{pct_b:.0f}%</div>"
        f"<div style='font-size:16px;font-weight:700;color:#ff4444;'>{pct_r:.0f}%</div></div></div>")

    rows = ("<tr style='background:#0e1420;color:#fff;'>"
            + "".join(f"<th style='padding:6px;border:1px solid #223;font-size:10px;'>{h}</th>"
                      for h in COLUMN_HEADERS) + "</tr>")
    for a in analyses:
        is_atm = a["strike_price"] == atm_strike
        row_style = ("background:#f5d000;color:#000;font-weight:700;" if is_atm
                     else "background:#141c28;color:#e8eef5;")
        cells = (f"<td style='padding:5px 6px;border:1px solid #223;text-align:center;"
                 f"font-weight:700;'>{a['strike_price']:.0f}</td>")
        for k in METRIC_KEYS:
            emo = a["bias_emojis"].get(k, _NEU)
            sc = a["bias_scores"].get(k, 0)
            cells += (f"<td style='padding:5px 4px;border:1px solid #223;text-align:center;"
                      f"font-size:11px;'>{emo}<br><small>{sc:+.1f}</small></td>")
        cells += (f"<td style='padding:5px 6px;border:1px solid #223;text-align:center;"
                  f"background:{a['verdict_color']};color:#000;font-weight:700;font-size:11px;'>"
                  f"{a['verdict']}</td>")
        rows += f"<tr style='{row_style}'>{cells}</tr>"

    table = ("<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;'>"
             + rows + "</table></div>")
    note = ("<div style='color:#8a95a3;font-size:10px;margin-top:3px;'>"
            "Seller's perspective · 🐂 bullish / 🐻 bearish / ⚖️ neutral · MktDepth & BA "
            "from the already-fetched bid/ask depth. Context only.</div>")
    return head + table + note
