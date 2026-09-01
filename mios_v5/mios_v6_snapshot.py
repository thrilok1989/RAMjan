"""MIOS V6 Market Snapshot Reporter — gather existing V6 data, format for Telegram.

Collects ONLY what MIOS V6 already produces. No new calculations, no new engines.
Splits into separate Telegram messages per section (phone-readable, under 4000 chars).

For each missing field: use UNKNOWN or NOT REPORTED, never invent or estimate.
"""

from typing import Any, Dict, List, Optional, Mapping


def _f(v: Any) -> Optional[float]:
    """Safe float conversion."""
    try:
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def _s(v: Any) -> Optional[str]:
    """Safe string conversion."""
    try:
        s = str(v or "").strip()
        return s if s and s.upper() not in ("NONE", "NULL", "UNKNOWN") else None
    except (TypeError, ValueError):
        return None


def gather_mios_v6_data(session_state: Mapping[str, Any]) -> Dict[str, Any]:
    """Collect all MIOS V6 published values from session state.

    Returns a flat dict with every field the snapshot needs.
    Missing values are not included (not set to UNKNOWN here — that's the formatter's job).
    """
    d = {}
    ss = session_state or {}

    # ── Time & Price ──
    d['time'] = (ss.get('_opt_data_ts') or '')[:19].replace('T', ' ') or None
    d['nifty_spot'] = _f(ss.get('_nifty_spot_live'))
    d['nifty_futures'] = _f(ss.get('_nifty_fut_price'))

    basis = _f(ss.get('_nifty_fut_price'))
    spot = _f(ss.get('_nifty_spot_live'))
    if basis is not None and spot is not None:
        d['basis'] = basis - spot

    d['day_pct_change'] = _f(ss.get('_nifty_day_pct'))
    d['day_high'] = _f(ss.get('_nifty_day_high'))
    d['day_low'] = _f(ss.get('_nifty_day_low'))
    d['vwap'] = _f(ss.get('_vwap'))
    d['atr'] = _f(ss.get('_atr'))

    # ── Market Picture ──
    mp = ss.get('_market_picture') or {}
    d['regime'] = mp.get('regime')
    d['regime_emoji'] = mp.get('em')
    d['p_up'] = _f(mp.get('p_up'))
    d['p_down'] = _f(mp.get('p_down'))
    d['p_side'] = _f(mp.get('p_side'))

    # Session/Trend from market picture
    d['session_state'] = mp.get('session_state')
    d['trend_state'] = mp.get('trend_state')
    d['transition_state'] = mp.get('transition_state')
    d['quality'] = mp.get('quality')

    # ── S/R from Final Read ──
    try:
        from mios_v5.final_read import build_final_read
        fr = build_final_read(ss.get('_mios_state')) or {}
        d['support'] = _f(fr.get('strong_support'))
        d['resistance'] = _f(fr.get('strong_resistance'))
        _bz = fr.get('battle_zone') or {}
        d['war_zone'] = _f(_bz.get('price')) if isinstance(_bz, dict) else None
        d['war_zone_type'] = (_bz.get('zone') if isinstance(_bz, dict) else None)
        d['expected_winner'] = fr.get('expected_winner')
    except Exception:
        pass

    # ── Entry Gate (S/R interaction) ──
    _eg = mp.get('entry_gate') or {}
    d['entry_gate_state'] = _eg.get('state')
    d['entry_gate_level'] = _f(_eg.get('level'))
    d['entry_gate_zone'] = _eg.get('zone')
    d['entry_gate_reason'] = _eg.get('reason')

    # ── Premium / Energy ──
    _pe = ss.get('_premium_energy') or {}
    d['total_energy'] = _f(_pe.get('energy_score', {}).get('total'))
    d['call_energy'] = _f(_pe.get('energy_score', {}).get('CALL'))
    d['put_energy'] = _f(_pe.get('energy_score', {}).get('PUT'))
    d['call_spike'] = _pe.get('call_spike_state')
    d['put_spike'] = _pe.get('put_spike_state')
    d['premium_bias'] = _pe.get('premium_bias')

    # ── Options Flow ──
    _fmr = ss.get('_full_market_read') or {}
    d['pcr'] = _f(_fmr.get('pcr'))
    d['oi_pcr'] = _f(_fmr.get('oi_pcr'))
    d['volume_pcr'] = _f(_fmr.get('volume_pcr'))
    d['call_oi'] = _f(_fmr.get('call_oi'))
    d['put_oi'] = _f(_fmr.get('put_oi'))
    d['call_flow'] = _fmr.get('call_mode')
    d['put_flow'] = _fmr.get('put_mode')
    d['oi_change'] = _fmr.get('oi_change_direction')
    d['flow_bias'] = _fmr.get('flow_bias')

    # ── Dealer / OI ──
    d['max_pain'] = _f(mp.get('max_pain'))
    _oc = mp.get('oi_ceiling')
    d['oi_ceiling'] = _f(_oc[0] if _oc else None)
    _of = mp.get('oi_floor')
    d['oi_floor'] = _f(_of[0] if _of else None)
    _op = mp.get('oi_pin')
    d['oi_pin'] = _f(_op[0] if _op else None)

    # ── Greeks ──
    _gx = ss.get('_gex_data') or {}
    d['gamma_regime'] = _gx.get('regime')
    d['gamma_flip'] = _f(_gx.get('gamma_flip_level'))
    d['gex_signal'] = _gx.get('gex_signal')
    d['total_gex'] = _f(_gx.get('total_gex'))

    _vc = mp.get('vc_exp') or {}
    d['net_vanna'] = _f(_vc.get('net_vanna'))
    d['net_charm'] = _f(_vc.get('net_charm'))
    d['net_vega'] = _f(_vc.get('net_vega'))
    d['net_vomma'] = _f(_vc.get('net_vomma'))
    d['net_speed'] = _f(_vc.get('net_speed'))
    d['net_zomma'] = _f(_vc.get('net_zomma'))
    d['net_veta'] = _f(_vc.get('net_veta'))
    d['net_color'] = _f(_vc.get('net_color'))
    d['net_ultima'] = _f(_vc.get('net_ultima'))

    # ── Greek Behaviour ──
    d['greek_behaviour'] = ss.get('_greek_behaviour_synth')

    # ── Liquidity ──
    _liq = ss.get('_liquidity_state') or {}
    d['liquidity_state'] = _liq.get('state')
    d['liquidity_score'] = _f(_liq.get('score'))
    d['call_liquidity'] = _liq.get('call_liquidity')
    d['put_liquidity'] = _liq.get('put_liquidity')

    # ── ATM Verdict ──
    _ab = mp.get('atm_bias') or {}
    d['atm_verdict'] = _ab.get('verdict')
    d['atm_score'] = _f(_ab.get('score'))

    # ── Global / Sector / News ──
    _gb = mp.get('global_bias') or {}
    d['global_bias'] = _gb.get('label') if isinstance(_gb, dict) else _gb
    d['us_futures'] = mp.get('us_futures_sentiment')
    d['asia_sentiment'] = mp.get('asia_sentiment')
    d['europe_sentiment'] = mp.get('europe_sentiment')
    d['usdinr'] = _f(mp.get('usdinr'))
    d['india_vix'] = _f(mp.get('india_vix'))
    d['global_event_risk'] = mp.get('global_event_risk')

    _sb = mp.get('sector_bias') or {}
    d['leaders'] = _sb.get('leaders') if isinstance(_sb, dict) else None
    d['weak'] = _sb.get('weak') if isinstance(_sb, dict) else None
    d['bank_nifty'] = mp.get('bank_nifty_signal')
    d['finnifty'] = mp.get('finnifty_signal')
    d['breadth'] = mp.get('breadth')

    _nb = mp.get('news_bias') or {}
    d['major_news'] = _nb.get('headline') if isinstance(_nb, dict) else _nb
    d['news_bias'] = (_nb.get('label') if isinstance(_nb, dict) else _nb)
    d['event_risk'] = mp.get('event_risk')

    # ── Institutional ──
    d['fii_flow'] = mp.get('fii_flow_direction')
    d['dii_flow'] = mp.get('dii_flow_direction')
    d['options_money_flow'] = mp.get('options_money_flow')

    # ── Money Flow ──
    mf = ss.get('_money_flow_data') or {}
    d['poc'] = _f(mf.get('poc_price'))
    d['vah'] = _f(mf.get('value_area_high'))
    d['val'] = _f(mf.get('value_area_low'))

    # ── V5 ──
    d['v5_verdict'] = _f(ss.get('_v5_verdict'))
    d['v5_confidence'] = _f(ss.get('_v5_confidence'))

    # ── V6 Signal ──
    d['v6_signal'] = ss.get('_v6_signal')
    d['v6_confidence'] = _f(ss.get('_v6_confidence'))
    d['v6_voters'] = ss.get('_v6_voters')
    d['v6_agreement'] = _f(ss.get('_v6_agreement'))

    # ── Guardian ──
    _g = ss.get('_guardian_verdict') or {}
    d['guardian_verdict'] = _g.get('verdict') if isinstance(_g, dict) else _g
    d['guardian_score'] = _f(_g.get('score') if isinstance(_g, dict) else None)
    d['guardian_validity'] = (_g.get('validity') if isinstance(_g, dict) else None)
    d['guardian_hard_gates'] = (_g.get('hard_gates') if isinstance(_g, dict) else None)
    d['guardian_failed_gates'] = (_g.get('failed_gates') if isinstance(_g, dict) else None)
    d['guardian_state_reason'] = (_g.get('state_reason') if isinstance(_g, dict) else None)
    d['guardian_score_reason'] = (_g.get('score_reason') if isinstance(_g, dict) else None)

    # ── Telegram Status ──
    d['telegram_status'] = ss.get('_telegram_sent_status')
    d['telegram_suppression'] = ss.get('_telegram_suppression_reason')

    return d


def format_snapshot(data: Dict[str, Any]) -> List[str]:
    """Format gathered MIOS V6 data into separate Telegram messages.

    Each message is one major section, phone-readable, under 4000 chars.
    Returns list of message strings, one per section.
    """
    msgs = []

    # ── Time & Price ──
    m = "🧬 <b>MIOS V6 SNAPSHOT</b>\n\n⏱ <b>TIME & PRICE</b>"
    if data.get('time'):
        m += f"\n🕐 {data['time']}"
    if data.get('nifty_spot') is not None:
        m += f"\nNIFTY: ₹{data['nifty_spot']:,.1f}"
    if data.get('nifty_futures') is not None:
        m += f"\nFUTURES: ₹{data['nifty_futures']:,.1f}"
    if data.get('basis') is not None:
        m += f"\nBASIS: {data['basis']:+.1f} pts"
    if data.get('day_pct_change') is not None:
        m += f"\nDAY %: {data['day_pct_change']:+.2f}%"
    if data.get('day_high') is not None:
        m += f"\nHIGH: ₹{data['day_high']:,.0f}"
    if data.get('day_low') is not None:
        m += f"\nLOW: ₹{data['day_low']:,.0f}"
    if data.get('vwap') is not None:
        m += f"\nVWAP: ₹{data['vwap']:,.1f}"
    if data.get('atr') is not None:
        m += f"\nATR: {data['atr']:.1f}"
    msgs.append(m)

    # ── Market ──
    m = "📊 <b>MARKET</b>"
    if data.get('regime'):
        emoji = data.get('regime_emoji', '')
        m += f"\nREGIME: {emoji} {data['regime']}".strip()
    if data.get('p_up') is not None or data.get('p_down') is not None or data.get('p_side') is not None:
        m += "\nPARTICIPATION:"
        if data.get('p_up') is not None:
            m += f" ⬆️ {data['p_up']}%"
        if data.get('p_down') is not None:
            m += f" ⬇️ {data['p_down']}%"
        if data.get('p_side') is not None:
            m += f" ↔️ {data['p_side']}%"
    if data.get('session_state'):
        m += f"\nSESSION: {data['session_state']}"
    if data.get('trend_state'):
        m += f"\nTREND: {data['trend_state']}"
    if data.get('transition_state'):
        m += f"\nTRANSITION: {data['transition_state']}"
    if data.get('quality'):
        m += f"\nQUALITY: {data['quality']}"
    if m != "📊 <b>MARKET</b>":
        msgs.append(m)

    # ── S/R ──
    m = "⚔️ <b>S/R & LEVELS</b>"
    if data.get('support') is not None:
        m += f"\nSUPPORT: ₹{data['support']:,.0f}"
    if data.get('resistance') is not None:
        m += f"\nRESISTANCE: ₹{data['resistance']:,.0f}"
    if data.get('war_zone') is not None:
        m += f"\nWAR ZONE: ₹{data['war_zone']:,.0f}"
        if data.get('war_zone_type'):
            m += f" ({data['war_zone_type']})"
    if data.get('entry_gate_state'):
        m += f"\nENTRY GATE: {data['entry_gate_state']}"
        if data.get('entry_gate_level') is not None:
            m += f" @ ₹{data['entry_gate_level']:,.0f}"
        if data.get('entry_gate_reason'):
            m += f" — {data['entry_gate_reason']}"
    if m != "⚔️ <b>S/R & LEVELS</b>":
        msgs.append(m)

    # ── Premium ──
    m = "⚡ <b>PREMIUM</b>"
    if data.get('total_energy') is not None:
        m += f"\nTOTAL: {data['total_energy']:.1f}"
    if data.get('call_energy') is not None or data.get('put_energy') is not None:
        m += "\nENERGY:"
        if data.get('call_energy') is not None:
            m += f" 📞 {data['call_energy']:.1f}"
        if data.get('put_energy') is not None:
            m += f" 📱 {data['put_energy']:.1f}"
    if data.get('call_spike'):
        m += f"\nCALL SPIKE: {data['call_spike']}"
    if data.get('put_spike'):
        m += f"\nPUT SPIKE: {data['put_spike']}"
    if data.get('premium_bias'):
        m += f"\nBIAS: {data['premium_bias']}"
    if m != "⚡ <b>PREMIUM</b>":
        msgs.append(m)

    # ── Options Flow ──
    m = "🌊 <b>OPTIONS FLOW</b>"
    if data.get('pcr') is not None:
        m += f"\nPCR: {data['pcr']:.2f}"
    if data.get('oi_pcr') is not None:
        m += f"\nOI PCR: {data['oi_pcr']:.2f}"
    if data.get('volume_pcr') is not None:
        m += f"\nVOL PCR: {data['volume_pcr']:.2f}"
    if data.get('call_oi') is not None:
        m += f"\nCALL OI: {data['call_oi']:,.0f}L"
    if data.get('put_oi') is not None:
        m += f"\nPUT OI: {data['put_oi']:,.0f}L"
    if data.get('call_flow'):
        m += f"\nCALL MODE: {data['call_flow']}"
    if data.get('put_flow'):
        m += f"\nPUT MODE: {data['put_flow']}"
    if data.get('oi_change'):
        m += f"\nOI CHANGE: {data['oi_change']}"
    if m != "🌊 <b>OPTIONS FLOW</b>":
        msgs.append(m)

    # ── Dealer ──
    m = "🧲 <b>DEALER BEHAVIOUR</b>"
    if data.get('max_pain') is not None:
        m += f"\nMAX PAIN: ₹{data['max_pain']:,.0f}"
    if data.get('oi_ceiling') is not None:
        m += f"\nCE WALL: ₹{data['oi_ceiling']:,.0f}"
    if data.get('oi_floor') is not None:
        m += f"\nPE WALL: ₹{data['oi_floor']:,.0f}"
    if data.get('oi_pin') is not None:
        m += f"\nPINNED AT: ₹{data['oi_pin']:,.0f}"
    if m != "🧲 <b>DEALER BEHAVIOUR</b>":
        msgs.append(m)

    # ── Greeks ──
    m = "🧮 <b>GREEKS</b>"
    if data.get('gamma_regime'):
        m += f"\nGAMMA: {data['gamma_regime']}"
    if data.get('gamma_flip') is not None:
        m += f"\nFLIP: ₹{data['gamma_flip']:,.0f}"
    if data.get('total_gex') is not None:
        m += f"\nTOTAL GEX: {data['total_gex']:+,.0f}"
    if data.get('net_vanna') is not None:
        m += f"\nVANNA: {data['net_vanna']:+,.0f}"
    if data.get('net_charm') is not None:
        m += f"\nCHARM: {data['net_charm']:+,.0f}"
    if data.get('net_vega') is not None:
        m += f"\nVEGA: {data['net_vega']:+,.0f}"
    if data.get('gex_signal'):
        m += f"\nSIGNAL: {data['gex_signal']}"
    if m != "🧮 <b>GREEKS</b>":
        msgs.append(m)

    # ── Greek Behaviour ──
    if data.get('greek_behaviour'):
        m = f"🧠 <b>GREEK BEHAVIOUR</b>\n{data['greek_behaviour']}"
        msgs.append(m)

    # ── Liquidity ──
    m = "💧 <b>LIQUIDITY</b>"
    if data.get('liquidity_state'):
        m += f"\nSTATE: {data['liquidity_state']}"
    if data.get('liquidity_score') is not None:
        m += f"\nSCORE: {data['liquidity_score']:.1f}"
    if data.get('call_liquidity'):
        m += f"\nCALL: {data['call_liquidity']}"
    if data.get('put_liquidity'):
        m += f"\nPUT: {data['put_liquidity']}"
    if m != "💧 <b>LIQUIDITY</b>":
        msgs.append(m)

    # ── Global & Sectors ──
    m = "🌍 <b>GLOBAL & SECTORS</b>"
    if data.get('global_bias'):
        m += f"\nGLOBAL: {data['global_bias']}"
    if data.get('us_futures'):
        m += f"\nUS FUTURES: {data['us_futures']}"
    if data.get('india_vix') is not None:
        m += f"\nINDIA VIX: {data['india_vix']:.1f}"
    if data.get('bank_nifty'):
        m += f"\nBANK NIFTY: {data['bank_nifty']}"
    if data.get('breadth'):
        m += f"\nBREADTH: {data['breadth']}"
    if m != "🌍 <b>GLOBAL & SECTORS</b>":
        msgs.append(m)

    # ── News ──
    m = "📰 <b>NEWS & EVENTS</b>"
    if data.get('major_news'):
        m += f"\n{data['major_news']}"
    if data.get('event_risk'):
        m += f"\nRISK: {data['event_risk']}"
    if m != "📰 <b>NEWS & EVENTS</b>":
        msgs.append(m)

    # ── Verdict ──
    m = "🎯 <b>SIGNAL & VERDICT</b>"
    if data.get('atm_verdict'):
        m += f"\nATM: {data['atm_verdict']}"
    if data.get('v6_signal'):
        m += f"\n<b>SIGNAL: {data['v6_signal']}</b>"
    if data.get('v6_confidence') is not None:
        m += f"\nCONFIDENCE: {data['v6_confidence']:.1f}"
    if data.get('guardian_verdict'):
        m += f"\nGUARDIAN: {data['guardian_verdict']}"
    if m != "🎯 <b>SIGNAL & VERDICT</b>":
        msgs.append(m)

    return msgs
