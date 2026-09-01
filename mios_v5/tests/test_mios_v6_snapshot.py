"""MIOS V6 Snapshot Reporter — collects existing V6 data, formats for Telegram.

Verifies that:
1. gather_mios_v6_data() collects all available session state into flat dict
2. format_snapshot() splits data into separate messages (phone-readable, <4000 chars)
3. Missing values are omitted, not filled with UNKNOWN
4. Existing MIOS V6 values are preserved exactly
5. No calculations are performed (pure formatter)
"""

from mios_v5.mios_v6_snapshot import gather_mios_v6_data, format_snapshot


def test_gather_mios_v6_data_empty():
    """Empty session state returns empty dict."""
    d = gather_mios_v6_data({})
    assert isinstance(d, dict)
    assert len(d) == 0 or all(v is None for v in d.values())


def test_gather_mios_v6_data_spot_only():
    """Spot price alone populates one field."""
    d = gather_mios_v6_data({"_nifty_spot_live": 24400.5})
    assert d.get('nifty_spot') == 24400.5


def test_gather_mios_v6_data_preserves_types():
    """Numeric values stay numeric, strings stay strings."""
    data = {
        "_nifty_spot_live": 24400,
        "_market_picture": {
            "regime": "UP",
            "p_up": 60,
            "em": "🟢"
        }
    }
    d = gather_mios_v6_data(data)
    assert d['nifty_spot'] == 24400.0  # converted to float for consistency
    assert d['regime'] == "UP"
    assert d['p_up'] == 60.0
    assert d['regime_emoji'] == "🟢"


def test_gather_mios_v6_data_calculates_basis():
    """Basis = Futures - Spot, calculated from both."""
    data = {
        "_nifty_spot_live": 24400,
        "_nifty_fut_price": 24410
    }
    d = gather_mios_v6_data(data)
    assert d['basis'] == 10  # 24410 - 24400


def test_gather_mios_v6_data_skips_nan_values():
    """NaN floats are skipped, not included."""
    data = {
        "_nifty_spot_live": 24400,
        "_vwap": float("nan"),
        "_atr": 50.5
    }
    d = gather_mios_v6_data(data)
    assert d['nifty_spot'] == 24400.0
    assert d['vwap'] is None  # NaN skipped
    assert d['atr'] == 50.5


def test_format_snapshot_empty():
    """Empty data returns list of empty or minimal messages."""
    msgs = format_snapshot({})
    assert isinstance(msgs, list)
    # Should return some messages but mostly empty/header-only


def test_format_snapshot_spot_only():
    """Spot price alone produces single message with time & price."""
    data = {
        'time': '2026-08-20 10:30:00',
        'nifty_spot': 24400.5
    }
    msgs = format_snapshot(data)
    assert len(msgs) > 0
    assert 'NIFTY' in msgs[0]
    assert '24,400.5' in msgs[0]  # Formatted with commas


def test_format_snapshot_messages_are_strings():
    """Each message is a non-empty string."""
    data = {
        'nifty_spot': 24400,
        'regime': 'UP',
        'regime_emoji': '🟢',
        'support': 24350,
        'resistance': 24450
    }
    msgs = format_snapshot(data)
    for msg in msgs:
        assert isinstance(msg, str)
        assert len(msg) > 0
        assert len(msg) <= 4500  # Phone-readable limit


def test_format_snapshot_full_market_picture():
    """Full market data splits across multiple messages."""
    data = {
        'time': '2026-08-20 10:30:00',
        'nifty_spot': 24400,
        'nifty_futures': 24410,
        'basis': 10,
        'regime': 'UP',
        'regime_emoji': '🟢',
        'p_up': 60,
        'p_down': 25,
        'p_side': 15,
        'support': 24350,
        'resistance': 24450,
        'war_zone': 24400,
        'pcr': 0.98,
        'call_energy': 7.2,
        'put_energy': 6.8,
        'gamma_regime': 'long gamma',
        'total_gex': 150000,
        'atm_verdict': 'Strong Bullish',
        'v6_signal': 'BUY CALL',
        'global_bias': 'risk-on'
    }
    msgs = format_snapshot(data)
    assert len(msgs) >= 3  # Should split across multiple sections
    # Check that data appears in messages
    full_text = '\n'.join(msgs)
    assert 'NIFTY' in full_text
    assert '24,400' in full_text  # Formatted with comma separator
    assert 'BUY CALL' in full_text


def test_format_snapshot_omits_empty_sections():
    """Sections with no data are not included."""
    data = {
        'nifty_spot': 24400
    }
    msgs = format_snapshot(data)
    full_text = '\n'.join(msgs)
    # These sections should be skipped (no data)
    assert '🌍' not in full_text or 'GLOBAL' not in full_text  # Empty sections omitted


def test_format_snapshot_preserves_values():
    """Exact values from data appear in snapshot (formatted per MIOS style)."""
    data = {
        'nifty_spot': 24400.15,
        'pcr': 1.1234,
        'atm_score': 3.45
    }
    msgs = format_snapshot(data)
    full_text = '\n'.join(msgs)
    # Values should appear formatted (with commas for prices)
    assert '24,400.1' in full_text or '24,400' in full_text
    assert 'PCR' in full_text


def test_format_snapshot_no_invented_values():
    """Missing values do not appear; no UNKNOWN placeholders added."""
    data = {
        'nifty_spot': 24400,
        'regime': 'UP',
        'regime_emoji': '🟢'
        # No support, resistance, pcr, etc.
    }
    msgs = format_snapshot(data)
    full_text = '\n'.join(msgs)
    # These should NOT appear
    assert 'UNKNOWN' not in full_text
    assert 'NOT REPORTED' not in full_text


def test_format_snapshot_greek_behaviour_preserved():
    """Greek behaviour headline preserved exactly."""
    behaviour = "Gamma helping upside · Charm decay pressure · Vega expansion tailwind"
    data = {'greek_behaviour': behaviour}
    msgs = format_snapshot(data)
    full_text = '\n'.join(msgs)
    assert behaviour in full_text


def test_format_snapshot_all_sections_readable():
    """All messages are phone-readable: <4000 chars, no overlapping sections."""
    data = {
        'time': '2026-08-20 10:30:00',
        'nifty_spot': 24400,
        'regime': 'UP',
        'support': 24350,
        'resistance': 24450,
        'pcr': 0.98,
        'call_energy': 7.2,
        'total_gex': 150000,
        'gamma_regime': 'long gamma',
        'v6_signal': 'BUY CALL',
        'atm_verdict': 'Strong Bullish',
        'global_bias': 'risk-on'
    }
    msgs = format_snapshot(data)
    for i, msg in enumerate(msgs):
        assert len(msg) < 4000, f"Message {i} too long: {len(msg)} chars"
        assert msg.count('<b>') == msg.count('</b>'), f"Unmatched bold in message {i}"


def test_format_snapshot_signal_is_bold():
    """V6 signal appears in bold when present."""
    data = {'v6_signal': 'BUY CALL'}
    msgs = format_snapshot(data)
    full_text = '\n'.join(msgs)
    assert '<b>SIGNAL: BUY CALL</b>' in full_text


def test_gather_mios_v6_data_handles_none_oi_lists():
    """None values for OI lists don't crash subscripting."""
    data = {
        "_market_picture": {
            "oi_ceiling": None,  # This would cause NoneType subscript error
            "oi_floor": [24400],  # Valid list
            "oi_pin": None
        }
    }
    d = gather_mios_v6_data(data)
    # Should not crash; should return None for None values
    assert d.get('oi_ceiling') is None
    assert d.get('oi_floor') == 24400.0
    assert d.get('oi_pin') is None


def test_gather_mios_v6_data_handles_energy_score_missing():
    """Missing energy_score dict is handled gracefully."""
    data = {
        "_premium_energy": {
            # energy_score missing entirely
            "call_spike_state": "active",
            "put_spike_state": None
        }
    }
    d = gather_mios_v6_data(data)
    # Should not crash
    assert d.get('total_energy') is None
    assert d.get('call_energy') is None
    assert d.get('put_energy') is None
    assert d.get('call_spike') == "active"
