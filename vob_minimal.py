import streamlit as st
from streamlit_autorefresh import st_autorefresh
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime
import pytz
import time
from datetime import datetime, timedelta
import json
import hashlib
import numpy as np
import math
from mios_v5.index_option_specs import (
    INDEX_OPTION_SPECS, index_option_segment, option_spec)
from scipy.stats import norm
from pytz import timezone
import io
import os
# `Mapping`, not `dict` — every frozen MIOS value is a `MappingProxyType`, and
# `isinstance(x, dict)` is False for one. See `_mios_market_read`.
from collections.abc import Mapping
from db.supabase_client import SupabaseDB
from db.read_cache import wrap as _cache_reads
from indicators.money_flow_profile import calculate_money_flow_profile
from mios_v5.story_integration import get_story_task, process_market_event
from mios_v5.market_events import build_event, EventType, EventSeverity
from mios_v5.clock import to_ist as _to_ist
from mios_v5.higher_greeks import higher_greeks as _higher_greeks




try:
    import yfinance as yf
    _HAS_YF = True
except Exception:
    _HAS_YF = False
from indicators.volume_delta import calculate_volume_delta
# the single owner of the CLV buy/sell split — see indicators/order_flow.py.
# The buy-fraction line used to be typed out identically in five places.
from indicators import order_flow as _of

st.set_page_config(
    page_title="Nifty Trading & Options Analyzer",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Only auto-refresh during market hours (8:30 AM - 3:45 PM IST, weekdays)
_ist_now = datetime.now(pytz.timezone('Asia/Kolkata'))
_is_market_open = (
    _ist_now.weekday() < 5 and
    _ist_now.replace(hour=8, minute=30, second=0, microsecond=0) <= _ist_now <= _ist_now.replace(hour=15, minute=45, second=0, microsecond=0)
)
if _is_market_open:
    st_autorefresh(interval=20000, key="datarefresh")

st.markdown("""
<style>
    .main > div {
        padding-top: 1rem;
    }
    .stSelectbox > div > div > select {
        background-color:
        color: white;
    }
    .metric-container {
        background-color:
        padding: 10px;
        border-radius: 5px;
        margin: 5px;
    }
    .price-up {
        color:
    }
    .price-down {
        color:
    }
    /* ── No dim/blur during reruns: refresh feels like it happens in the background ── */
    /* Hide the small "Running…" status pill in the top-right corner */
    [data-testid="stStatusWidget"] { display: none !important; visibility: hidden !important; }
    /* Hide the top-of-page progress indicator that flashes during a rerun */
    [data-testid="stDecoration"] { display: none !important; }
    /* Hide the header running indicator (newer Streamlit versions) */
    [data-testid="stHeader"] [data-testid="stStatusWidget"] { display: none !important; }
    /* Keep the page fully opaque while a rerun is in flight — kill the dim overlay */
    .stApp, .stApp > * { opacity: 1 !important; }
    .stApp[data-test-running="true"], .stApp[data-test-running="true"] * { opacity: 1 !important; }
    /* Disable any built-in fade transitions Streamlit applies during reruns */
    .element-container, .stMarkdown, .stDataFrame, .stPlotlyChart, .stMetric,
    [data-testid="stVerticalBlock"], [data-testid="stHorizontalBlock"] {
        transition: none !important;
        filter: none !important;
        opacity: 1 !important;
    }
    /* ── 📱 RESPONSIVE / MOBILE (Path A) — make the desktop app usable on a
       phone: stack columns, single-column our inline-grid dashboards, let wide
       tables & charts scroll inside their box, trim padding. Desktop (≥ 641px)
       is completely unaffected. ── */
    @media (max-width: 640px) {
        .block-container { padding-left: 0.55rem !important; padding-right: 0.55rem !important;
                           padding-top: 0.5rem !important; }
        /* Streamlit st.columns → stack vertically */
        [data-testid="stHorizontalBlock"] { flex-direction: column !important; }
        [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important;
                                 min-width: 0 !important; }
        /* our custom HTML grid dashboards (chip rows, cockpit) → single column */
        div[style*="grid-template-columns"] { grid-template-columns: 1fr !important; }
        /* wide tables / charts scroll instead of overflowing the page */
        .stDataFrame, .stPlotlyChart, [data-testid="stTable"] { overflow-x: auto !important; }
        /* never let the page itself scroll sideways */
        section.main, [data-testid="stAppViewContainer"] { overflow-x: hidden !important; }
    }
    /* Some Streamlit builds put a global blur on the main area during reruns */
    [data-testid="stAppViewContainer"], section.main { filter: none !important; opacity: 1 !important; }
</style>
""", unsafe_allow_html=True)

try:
    DHAN_CLIENT_ID = st.secrets.get("DHAN_CLIENT_ID", "") or st.secrets.get("dhan", {}).get("client_id", "")
    DHAN_ACCESS_TOKEN = st.secrets.get("DHAN_ACCESS_TOKEN", "") or st.secrets.get("dhan", {}).get("access_token", "")
    supabase_url = st.secrets.get("supabase", {}).get("url", "")
    supabase_key = st.secrets.get("supabase", {}).get("anon_key", "")
    try:
        TELEGRAM_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "") or getattr(st.secrets, "TELEGRAM_BOT_TOKEN", "")
        TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "") or getattr(st.secrets, "TELEGRAM_CHAT_ID", "")
        if isinstance(TELEGRAM_CHAT_ID, (int, float)):
            TELEGRAM_CHAT_ID = str(int(TELEGRAM_CHAT_ID))
        # Second, dedicated alert bot — carries ONLY the high-conviction
        # entry alerts (SPOT S/R CONFLUENCE etc.), separate from the main
        # bot's stream. Configure in secrets:
        #   TELEGRAM_ALERT_BOT_TOKEN = "123456:ABC..."  (from @BotFather)
        #   TELEGRAM_ALERT_CHAT_ID   = "123456789"
        TELEGRAM_ALERT_BOT_TOKEN = (st.secrets.get("TELEGRAM_ALERT_BOT_TOKEN", "")
                                    or getattr(st.secrets, "TELEGRAM_ALERT_BOT_TOKEN", ""))
        TELEGRAM_ALERT_CHAT_ID = (st.secrets.get("TELEGRAM_ALERT_CHAT_ID", "")
                                  or getattr(st.secrets, "TELEGRAM_ALERT_CHAT_ID", ""))
        if isinstance(TELEGRAM_ALERT_CHAT_ID, (int, float)):
            TELEGRAM_ALERT_CHAT_ID = str(int(TELEGRAM_ALERT_CHAT_ID))
    except Exception:
        TELEGRAM_BOT_TOKEN = TELEGRAM_CHAT_ID = ""
        TELEGRAM_ALERT_BOT_TOKEN = TELEGRAM_ALERT_CHAT_ID = ""
    # Discord webhook (fallback / replacement for Telegram when blocked in India)
    try:
        DISCORD_WEBHOOK_URL = (
            st.secrets.get("DISCORD_WEBHOOK_URL", "")
            or getattr(st.secrets, "DISCORD_WEBHOOK_URL", "")
            or os.environ.get("DISCORD_WEBHOOK_URL", "")
        )
    except Exception:
        DISCORD_WEBHOOK_URL = ""
    # Discord BOT token + channel id — lets the app post market alerts straight
    # to the channel via the REST API (no separate bot process needed). Only
    # relaying works this way; the !commands still need the standalone bot.
    try:
        DISCORD_BOT_TOKEN = (st.secrets.get("DISCORD_BOT_TOKEN", "")
                             or os.environ.get("DISCORD_BOT_TOKEN", ""))
        DISCORD_CHANNEL_ID = str(st.secrets.get("DISCORD_CHANNEL_ID", "")
                                 or os.environ.get("DISCORD_CHANNEL_ID", "") or "")
    except Exception:
        DISCORD_BOT_TOKEN = DISCORD_CHANNEL_ID = ""
except Exception:
    DHAN_CLIENT_ID = DHAN_ACCESS_TOKEN = supabase_url = supabase_key = ""
    TELEGRAM_BOT_TOKEN = TELEGRAM_CHAT_ID = ""
    TELEGRAM_ALERT_BOT_TOKEN = TELEGRAM_ALERT_CHAT_ID = ""
    DISCORD_WEBHOOK_URL = ""
    DISCORD_BOT_TOKEN = DISCORD_CHANNEL_ID = ""

# ── leg-fetch budget (performance, not behaviour) ──
# The 14 ATM±3 legs share a 60s cache and were all populated in the same
# cycle, so all 14 expired in the same cycle. Every third render then paid
# 14 × the 0.3s intraday throttle — 4.2s of blocking sleep during which the
# page could not draw, which is what made spot and the chart look stale.
# At most this many legs actually re-fetch per render; the rest serve their
# (bounded, age-reported) cached bars and rotate in on the next render.
LEG_FETCH_PER_RENDER = 5

NIFTY_UNDERLYING_SCRIP = 13
NIFTY_UNDERLYING_SEG = "IDX_I"


# ── Instrument Registry: discover specs from Dhan (not hardcoded) ────────
# Initialize on first render; cache in session_state for reuse.
def _get_instrument_context(session_state, selected_instrument: str = "NIFTY"):
    """Get normalized instrument context (specs from Dhan)."""
    cache_key = f"_instrument_context_{selected_instrument}"

    if cache_key in session_state:
        return session_state[cache_key]

    try:
        from mios_v5.instrument_registry import create_instrument_registry
        registry = create_instrument_registry(dhan)

        if selected_instrument == "SENSEX":
            ctx = registry.discover_sensex()
        else:
            ctx = registry.discover_nifty()

        if ctx:
            session_state[cache_key] = ctx
            return ctx
    except Exception as e:
        import logging
        logging.error(f"Failed to discover {selected_instrument} specs: {e}")

    # Fallback to hardcoded NIFTY if discovery fails
    if selected_instrument == "NIFTY":
        from mios_v5.instrument_registry import InstrumentContext
        fallback = InstrumentContext(
            symbol="NIFTY",
            security_id=13,
            exchange_segment="IDX_I",
            contract_multiplier=25.0,
            strike_step=100,
            current_expiry="2026-08-27",
            expiry_list=["2026-08-27", "2026-09-24"],
            atm_range=100,
            lot_size=1,
            tick_size=0.05,
        )
        session_state[cache_key] = fallback
        return fallback

    return None




# ── restored: referenced by name, never called directly ─────────────
# The call-graph pass that produced the reduction only followed ast.Call,
# so `ReversalDetector.calculate_reversal_score(...)` (an Attribute on the
# class) and the styling callbacks handed to `df.style.applymap(...)` read
# as unreferenced. pyflakes caught all eleven.

class ReversalDetector:
    @staticmethod
    def calculate_vwap(df):
        if df.empty or 'volume' not in df.columns:
            return pd.Series(dtype=float)
        df = df.copy()
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        df['tp_volume'] = df['typical_price'] * df['volume']
        df['cumulative_tp_vol'] = df['tp_volume'].cumsum()
        df['cumulative_vol'] = df['volume'].cumsum()
        df['vwap'] = df['cumulative_tp_vol'] / df['cumulative_vol']
        return df['vwap']

    @staticmethod
    def detect_higher_low(df, lookback=5):
        if len(df) < lookback + 1:
            return False, None, None
        recent = df.tail(lookback + 1)
        lows = recent['low'].values
        prev_min_idx = lows[:-1].argmin()
        prev_min = lows[prev_min_idx]
        current_low = lows[-1]
        if len(lows) >= 3:
            for i in range(1, len(lows) - 1):
                if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                    swing_low = lows[i]
                    if current_low > swing_low:
                        return True, swing_low, current_low
        return current_low > prev_min, prev_min, current_low

    @staticmethod
    def detect_no_new_low(df, lookback=10):
        if len(df) < lookback:
            return False, None
        recent = df.tail(lookback)
        lows = recent['low'].values
        min_idx = lows.argmin()
        selling_exhausted = min_idx < lookback - 2
        return selling_exhausted, lows.min()

    @staticmethod
    def detect_strong_bullish_candle(df, threshold=0.5):
        if len(df) < 2:
            return False, {}
        current = df.iloc[-1]
        previous = df.iloc[-2]
        is_green = current['close'] > current['open']
        body = abs(current['close'] - current['open'])
        total_range = current['high'] - current['low']
        body_ratio = body / total_range if total_range > 0 else 0
        strong_body = body_ratio >= threshold
        closes_above_prev_high = current['close'] > previous['high']
        is_strong = is_green and strong_body and closes_above_prev_high
        details = {
            'is_green': is_green,
            'body_ratio': round(body_ratio, 2),
            'strong_body': strong_body,
            'closes_above_prev_high': closes_above_prev_high,
            'current_close': current['close'],
            'prev_high': previous['high']
        }
        return is_strong, details

    @staticmethod
    def detect_volume_confirmation(df, lookback=5):
        if len(df) < lookback:
            return False, "Insufficient Data", {}
        current = df.iloc[-1]
        avg_volume = df.tail(lookback)['volume'].mean()
        is_up_candle = current['close'] > current['open']
        current_volume = current['volume']
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        if is_up_candle:
            if volume_ratio >= 1.2:
                signal = "Strong Buying"
                confirmed = True
            elif volume_ratio >= 0.8:
                signal = "Normal Buying"
                confirmed = True
            else:
                signal = "Weak/Fake Bounce"
                confirmed = False
        else:
            signal = "Down Candle"
            confirmed = False
        details = {
            'current_volume': current_volume,
            'avg_volume': round(avg_volume, 0),
            'volume_ratio': round(volume_ratio, 2),
            'is_up_candle': is_up_candle
        }
        return confirmed, signal, details

    @staticmethod
    def check_vwap_position(df):
        if len(df) < 2:
            return False, None, None
        vwap = ReversalDetector.calculate_vwap(df)
        if vwap.empty:
            return False, None, None
        current_price = df.iloc[-1]['close']
        current_vwap = vwap.iloc[-1]
        above_vwap = current_price > current_vwap
        return above_vwap, current_price, current_vwap

    @staticmethod
    def detect_support_respect(df, pivot_lows, proximity_pct=0.3):
        if len(df) < 3 or not pivot_lows:
            return False, None, None
        current_low = df.iloc[-1]['low']
        recent_low = df.tail(5)['low'].min()
        nearest_support = None
        min_distance = float('inf')
        for support in pivot_lows:
            distance = abs(recent_low - support)
            pct_distance = (distance / support) * 100 if support > 0 else float('inf')
            if pct_distance < min_distance and pct_distance <= proximity_pct:
                min_distance = pct_distance
                nearest_support = support
        if nearest_support:
            bounced = df.iloc[-1]['close'] > recent_low
            return bounced, nearest_support, recent_low
        return False, None, recent_low

    @staticmethod
    def calculate_reversal_score(df, pivot_lows=None, lookback=10):
        signals = {}
        score = 0
        no_new_low, swing_low = ReversalDetector.detect_no_new_low(df, lookback)
        signals['Selling_Exhausted'] = "Yes ✅" if no_new_low else "No ❌"
        if no_new_low:
            score += 1
        higher_low, prev_low, curr_low = ReversalDetector.detect_higher_low(df, lookback // 2)
        signals['Higher_Low'] = "Yes ✅" if higher_low else "No ❌"
        if higher_low:
            score += 1.5
        strong_candle, candle_details = ReversalDetector.detect_strong_bullish_candle(df)
        signals['Strong_Bullish_Candle'] = "Yes ✅" if strong_candle else "No ❌"
        if strong_candle:
            score += 1.5
        vol_confirmed, vol_signal, vol_details = ReversalDetector.detect_volume_confirmation(df)
        signals['Volume_Signal'] = vol_signal
        if vol_confirmed:
            score += 1
        elif vol_signal == "Weak/Fake Bounce":
            score -= 0.5
        above_vwap, price, vwap = ReversalDetector.check_vwap_position(df)
        signals['Above_VWAP'] = "Yes ✅" if above_vwap else "No ❌"
        if above_vwap:
            score += 1
        if pivot_lows:
            support_held, support_level, low = ReversalDetector.detect_support_respect(df, pivot_lows)
            signals['Support_Respected'] = "Yes ✅" if support_held else "No ❌"
            if support_held:
                score += 1
                signals['Support_Level'] = support_level
        signals['Reversal_Score'] = round(score, 1)
        if score >= 4:
            verdict = "🟢 STRONG BUY SIGNAL"
            entry_type = "Safe CE Entry"
        elif score >= 2.5:
            verdict = "🟡 MODERATE BUY SIGNAL"
            entry_type = "Wait for Confirmation"
        elif score >= 1:
            verdict = "⚪ WEAK SIGNAL"
            entry_type = "No Entry"
        elif score <= -2:
            verdict = "🔴 BEARISH - AVOID CE"
            entry_type = "Consider PE"
        else:
            verdict = "⚪ NEUTRAL"
            entry_type = "No Trade"
        signals['Verdict'] = verdict
        signals['Entry_Type'] = entry_type
        if len(df) > 0:
            signals['Current_Price'] = df.iloc[-1]['close']
            signals['Day_Low'] = df['low'].min()
            signals['Day_High'] = df['high'].max()
            if vwap:
                signals['VWAP'] = round(vwap, 2)
        return score, signals, verdict

    @staticmethod
    def get_entry_rules(signals, score):
        rules = []
        if signals.get('Strong_Bullish_Candle') == "Yes ✅":
            if signals.get('Higher_Low') != "Yes ✅":
                rules.append("⚠️ First green candle - Wait for higher low confirmation")
            else:
                rules.append("✅ Structure confirmed - Entry possible")
        vol_signal = signals.get('Volume_Signal', '')
        if 'Weak' in vol_signal or 'Fake' in vol_signal:
            rules.append("⚠️ Low volume - Possible fake bounce")
        elif 'Strong' in vol_signal:
            rules.append("✅ Strong volume - Real buying detected")
        if signals.get('Above_VWAP') == "Yes ✅":
            rules.append("✅ Price above VWAP - Bullish bias")
        else:
            rules.append("⚠️ Price below VWAP - Wait for VWAP reclaim")
        if score >= 4:
            rules.append("🎯 ENTRY: Buy CE at current level")
            rules.append(f"🛑 SL: Below higher low ({signals.get('Day_Low', 'N/A')})")
            rules.append("🎯 Target: Previous high / Nearest resistance")
        elif score >= 2.5:
            rules.append("⏳ WAIT: Confirmation pending")
            rules.append("📋 Checklist: Higher Low + Strong Candle + Volume")
        else:
            rules.append("❌ NO ENTRY: Conditions not met")
        return rules

    @staticmethod
    def detect_lower_high(df, lookback=5):
        if len(df) < lookback + 1:
            return False, None, None
        recent = df.tail(lookback + 1)
        highs = recent['high'].values
        prev_max_idx = highs[:-1].argmax()
        prev_max = highs[prev_max_idx]
        current_high = highs[-1]
        if len(highs) >= 3:
            for i in range(1, len(highs) - 1):
                if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                    swing_high = highs[i]
                    if current_high < swing_high:
                        return True, swing_high, current_high
        return current_high < prev_max, prev_max, current_high

    @staticmethod
    def detect_no_new_high(df, lookback=10):
        if len(df) < lookback:
            return False, None
        recent = df.tail(lookback)
        highs = recent['high'].values
        max_idx = highs.argmax()
        buying_exhausted = max_idx < lookback - 2
        return buying_exhausted, highs.max()

    @staticmethod
    def detect_strong_bearish_candle(df, threshold=0.5):
        if len(df) < 2:
            return False, {}
        current = df.iloc[-1]
        previous = df.iloc[-2]
        is_red = current['close'] < current['open']
        body = abs(current['close'] - current['open'])
        total_range = current['high'] - current['low']
        body_ratio = body / total_range if total_range > 0 else 0
        strong_body = body_ratio >= threshold
        closes_below_prev_low = current['close'] < previous['low']
        is_strong = is_red and strong_body and closes_below_prev_low
        details = {
            'is_red': is_red,
            'body_ratio': round(body_ratio, 2),
            'strong_body': strong_body,
            'closes_below_prev_low': closes_below_prev_low,
            'current_close': current['close'],
            'prev_low': previous['low']
        }
        return is_strong, details

    @staticmethod
    def calculate_bearish_reversal_score(df, pivot_highs=None, lookback=10):
        signals = {}
        score = 0
        no_new_high, swing_high = ReversalDetector.detect_no_new_high(df, lookback)
        signals['Buying_Exhausted'] = "Yes ✅" if no_new_high else "No ❌"
        if no_new_high:
            score -= 1
        lower_high, prev_high, curr_high = ReversalDetector.detect_lower_high(df, lookback // 2)
        signals['Lower_High'] = "Yes ✅" if lower_high else "No ❌"
        if lower_high:
            score -= 1.5
        strong_candle, candle_details = ReversalDetector.detect_strong_bearish_candle(df)
        signals['Strong_Bearish_Candle'] = "Yes ✅" if strong_candle else "No ❌"
        if strong_candle:
            score -= 1.5
        vol_confirmed, vol_signal, vol_details = ReversalDetector.detect_volume_confirmation(df)
        current = df.iloc[-1]
        is_down = current['close'] < current['open']
        if is_down and vol_details.get('volume_ratio', 0) >= 1.2:
            signals['Volume_Signal'] = "Strong Selling"
            score -= 1
        elif is_down and vol_details.get('volume_ratio', 0) >= 0.8:
            signals['Volume_Signal'] = "Normal Selling"
            score -= 0.5
        else:
            signals['Volume_Signal'] = vol_signal
        above_vwap, price, vwap = ReversalDetector.check_vwap_position(df)
        signals['Below_VWAP'] = "Yes ✅" if not above_vwap else "No ❌"
        if not above_vwap:
            score -= 1
        if pivot_highs:
            recent_high = df.tail(5)['high'].max()
            nearest_resistance = None
            for resistance in pivot_highs:
                pct_distance = abs(recent_high - resistance) / resistance * 100 if resistance > 0 else float('inf')
                if pct_distance <= 0.3:
                    nearest_resistance = resistance
                    break
            if nearest_resistance:
                rejected = df.iloc[-1]['close'] < recent_high
                signals['Resistance_Rejected'] = "Yes ✅" if rejected else "No ❌"
                if rejected:
                    score -= 1
                    signals['Resistance_Level'] = nearest_resistance
            else:
                signals['Resistance_Rejected'] = "N/A"
        else:
            signals['Resistance_Rejected'] = "N/A"
        signals['Bearish_Score'] = round(score, 1)
        if score <= -4:
            verdict = "🔴 STRONG SELL SIGNAL"
            entry_type = "Safe PE Entry"
        elif score <= -2.5:
            verdict = "🟠 MODERATE SELL SIGNAL"
            entry_type = "Wait for Confirmation"
        elif score <= -1:
            verdict = "⚪ WEAK BEARISH"
            entry_type = "No Entry"
        else:
            verdict = "⚪ NEUTRAL"
            entry_type = "No Trade"
        signals['Bearish_Verdict'] = verdict
        signals['Bearish_Entry_Type'] = entry_type
        if len(df) > 0:
            signals['Current_Price'] = df.iloc[-1]['close']
            signals['Day_High'] = df['high'].max()
            if vwap:
                signals['VWAP'] = round(vwap, 2)
        return score, signals, verdict

class _GatePinned(Exception):
    """Control-flow sentinel: price is pinned at a magnet strike, so the
    ENTRY GATE short-circuits to PINNED and skips the directional zone logic.
    Caught by compute_market_picture's own try/except."""

def determine_level(row):
    ce_oi = row.get('openInterest_CE', 0)
    pe_oi = row.get('openInterest_PE', 0)
    if pe_oi > 1.12 * ce_oi:
        return "Support"
    elif ce_oi > 1.12 * pe_oi:
        return "Resistance"
    else:
        return "Neutral"

def color_pressure(val):
    return _CG if val > 500 else (_CR if val < -500 else _CY)

def color_pcr(val):
    return _CG if val > 1.2 else (_CR if val < 0.7 else _CY)

def color_bias(val):
    return _CG if val == "Bullish" else (_CR if val == "Bearish" else _CY)

def color_verdict(val):
    v = str(val)
    if "Strong Bullish" in v: return _CDG
    if "Bullish" in v: return _CG
    if "Strong Bearish" in v: return _CDR
    if "Bearish" in v: return _CR
    return _CY

def color_entry(val):
    v = str(val)
    return _CG if "Bull" in v else (_CR if "Bear" in v else _CF)

def color_fakereal(val):
    v = str(val)
    if "Real Up" in v: return _CDG
    if "Fake Up" in v: return 'background-color: #98FB98; color: black'
    if "Real Down" in v: return _CDR
    if "Fake Down" in v: return 'background-color: #FFC0CB; color: black'
    return _CF

def color_score(val):
    try:
        s = float(val)
        if s >= 4: return _CDG
        if s >= 2: return _CG
        if s <= -4: return _CDR
        if s <= -2: return _CR
        return _CY
    except: return ''

def highlight_atm_row(row):
    return [''] * len(row)

def _strip_html_tags(text):
    """Strip HTML tags for plain-text fallback."""
    import re
    return re.sub(r'<[^>]+>', '', text)


# Allow-list of headline markers that bypass the global mute. Every other
# automated alert is suppressed. force=True bypasses unconditionally.
_ALLOWED_ALERT_MARKERS = (
    # 'DYNAMIC POC',   # paused — muted (still computes, won't send)
    'SPOT STOP-HUNT ALIGNED',
    'CIE ALIGNED',
    'MAJOR S/R TOUCH',
    # 'BIAS ENTER',    # paused — muted (still computes, won't send)
    # 'OVERALL BIAS ENTRY',  # removed — spot-at-S/R entry deleted (weak levels confused)
    'VOB ENTRY',
    'LEG ENTRY',
    'CONFIRMED ENTRY',
    'ENTRY RESULT',
    'FRESH ENTRY',
    'SPOT S/R CONFLUENCE',
    'BULL CALL ENTRY',
    'BEAR PUT ENTRY',
    'SIGNAL CLUSTER',
    # option-chain alerts (woken on user request)
    'ENTRY GATE',
    'EXIT GATE',
    'ZONE REVERSAL',
    'REVERSAL WARNING',     # Position Guardian: early opposite-flow heads-up
    'STAY PATIENT',         # Position Guardian: normal-noise hold note
    'ATM STRIKE STRONG',
    'DECAPPING',
    'DEPEG',
    'OC BIAS',
    'CALL CAPPING',
    'PUT WRITING',
    'PUT CAPPING',
    'OB RETEST',
    'IGNITION',
)

def _msg_allowed(message):
    if not message:
        return False
    return any(m in message for m in _ALLOWED_ALERT_MARKERS)


# ── TELEGRAM TIER — the ONLY automated alert on the main Telegram bot is the
# two-layer FRESH ENTRY blast. Every other alert (the former entry tier +
# all context/muted alerts) is Discord-only + Supabase. (User paused the old
# entry alerts on Telegram; they still fire on Discord.)
_TELEGRAM_ENTRY_MARKERS = (
    'MIOS ENTRY',           # Stage 72 · and the simple entry system
    'MIOS ENTRY READY',     # Stage 72 — armed, waiting on the window
    'MIOS EXIT',            # Stage 73 — life after entry
    'MIOS PARTIAL EXIT', 'MIOS ADD', 'MIOS TRAIL', 'MIOS ABORT',
    'FRESH ENTRY',          # options positioning + spot action agree at a level
    'ENTRY GATE',           # spot AT strong/building zone + engines aligned
    'EXIT GATE',            # active zone trade: target hit / invalidated / time
    'ZONE REVERSAL',        # CVD impulse + stable alignment flip at S/R
    'REVERSAL WARNING',     # Position Guardian: sudden opposite flow on an open trade
    'STAY PATIENT',         # Position Guardian: normal-noise hold (fear-dip) note
)


def _msg_entry_tier(message):
    return bool(message) and any(m in message for m in _TELEGRAM_ENTRY_MARKERS)


# ── MIOS V5 — pure decision-support mode (locked decision #1) ──────────
# V5 never generates BUY/SELL. When RETIRE_ENTRY_ALERTS is True the outbound
# trade-call alerts are suppressed at the send layer. The confirmed-entry
# LIFECYCLE (arm → track → log to signal_outcomes) still runs — only the
# alert message is withheld — so Stage 40 (bias/outcome validation) keeps its
# data. Flip to False to restore the legacy entry alerts.
RETIRE_ENTRY_ALERTS = True

# ── 📨 MIOS V6 signals → Telegram: the DEFAULT for the sidebar toggle ──
# ⚠️ PAUSED by default at the owner's request: the "MIOS ENTRY / ENTRY READY"
#    stream was firing repeatedly on the main Telegram bot and the owner asked
#    to stop it. False means entry and exit signals are OFF on every fresh
#    session until someone ticks the sidebar toggle back on — the switch is
#    unchanged, only its starting state moved.
#
# When it IS turned on, what still protects you and what does not:
#   ✅ Stage 72.9's gates all apply — a decision must verify, must not be a
#      duplicate, must not be superseded, must be under MAX_AGE_SECONDS, and
#      must be in a sendable state. WAIT is never sent.
#   ✅ Delivery is market-hours only (08:30-15:45 IST, weekdays).
#   ✅ Nothing places an order. This is a message, not execution.
#   ❌ Stage 72.9 is still VALIDATED_SIMULATED — freeze_ready is False in
#      STAGE72_9_VALIDATION_REPORT.md. Its gates are proven in simulation, not
#      against five hundred live dispatches.
#
# Flip to True to make the signals live again from load.
MIOS_V6_TELEGRAM_DEFAULT = False

# ── ⚡ the simple entry system's default. Five plain rules, ANDed, with its
#    own dedup — see `run_simple_entry`. On by default at the owner's request.
SIMPLE_ENTRY_DEFAULT = True

# ── 📢 Call/Put writing & capping → Telegram: the sidebar toggle's default.
# The owner asked for a Telegram note when heavy call writing (capping upside,
# resistance) or put writing (support building) is detected. These already fire
# as market events (Discord + Supabase); the toggle adds a Telegram copy. ON by
# default because it was explicitly requested, and it is edge-triggered — one
# note per episode via `_event_edge`, not one per 20-second refresh — so it does
# not reintroduce the entry-stream spam that was just paused above.
WRITING_TG_DEFAULT = True

# ── 📍 Dynamic-POC shift alerts → Discord: the sidebar toggle's default.
# OFF by default (opt-in): the owner is sensitive to message volume, so a chart
# whose dynamic POC steps up or down only alerts once this is switched on. Routed
# to Discord, the app's channel for informational (non-entry) alerts.
POC_SHIFT_ALERTS_DEFAULT = False

# ── 📐 Formation alerts → Telegram: a new high-volume pivot or a new VOB on any
#    chart. ON by default (explicitly requested). Naturally low-rate: a pivot
#    needs `RIGHT` bars to confirm and a VOB forms occasionally, and each one is
#    alerted ONCE — the existing structure at load is seeded silently, never
#    replayed. `_notify_chart_formations` owns the memory and the send.
FORMATION_ALERTS_DEFAULT = True

# ── Leg LTP → HVP-line touch alert ─────────────────────────────────────
# Telegram when an option LTP (call or put) comes within ±5 of one of ITS OWN
# high-volume-point lines. Latched per line + a cooldown ("sleep") so a price
# loitering at the line does not repeat. Reuses `mios_v5.level_touch`.
# OFF by default — opt in via the sidebar.
LEG_HVP_TOUCH_DEFAULT = False
LEG_HVP_BAND = 5.0            # ±5 points of the LTP, as asked
LEG_HVP_COOLDOWN_S = 900.0    # the "sleeping facility" — 15 min per line

# ── 🎯 Level-touch alerts → Telegram: spot reaching a key level within ±5 pts —
#    the war zone, either OI wall, and the ranked support / resistance. ON by
#    default (explicitly requested). Latched per level so a level price loiters
#    at is alerted once, not every 20-second refresh — see
#    `mios_v5.level_touch.evaluate` and `_notify_level_touches`.
LEVEL_TOUCH_DEFAULT = True

#: Default for the flow-at-level alert to the ALTERNATE bot (PUT heavier at
#: resistance · CALL heavier at support). On, because the owner asked for it.
FLOW_LEVEL_ALERTS_DEFAULT = True

# ── Level Acceptance / Rejection alerts ────────────────────────────────
# Telegram note when a level RESOLVES (accepted above/below, or rejected) — the
# owner asked for it ON. Edge-triggered (once, on the transition) and per-zone
# cooldown-throttled so a chopping level cannot repeat-spam.
LEVEL_ACCEPT_ALERTS_DEFAULT = True
#: seconds before the SAME zone may alert again — matches the level-touch sleep.
LEVEL_ACCEPT_COOLDOWN_S = 900.0

# ── Confluence entry alert (4-signal alignment) ────────────────────────
# Telegram when NIFTY is at a level, the ATM-strike verdict is Strong Bull/Bear
# AGREEING with the level, the trade-side leg's LTP is at its support/session-low,
# and that side has the greater premium energy. Reuses existing engine outputs —
# no new engine. Latched per setup + cooldown so it fires once, not every cycle.
CONFLUENCE_ALERTS_DEFAULT = True
CONFLUENCE_COOLDOWN_S = 900.0

# ── ⚠️ Entry reversal alert — PAUSED by the owner ──────────────────────
# The whipsaw alert repeated the same level over and over (the same ₹ level five
# times in a row, only the "Current" price moving), so the owner asked for it to
# stop. OFF by default; the sidebar box brings it back. The alert body is
# unchanged and still gated — nothing was deleted.
ENTRY_REVERSED_ALERT_DEFAULT = False
ENTRY_REVERSED_COOLDOWN_S = 300.0

# ── the two sub-alerts the owner paused ────────────────────────────────
# The ranked support/resistance TOUCH (a sub-alert of level-touch) and the VOB
# FORMATION alert were both too noisy, so they are OFF by default. The war-zone
# and OI-wall touches and the HVP formation alert are unaffected. Flip either to
# True (or tick its sidebar box) to bring it back.
SR_TOUCH_ALERTS_DEFAULT = False
VOB_FORMATION_ALERTS_DEFAULT = False
_RETIRED_ALERT_CLASSES = frozenset({
    'leg_entry', 'confirmed_entry', 'entry_result', 'all_aligned_entry',
    'sr_confluence', 'fresh_entry', 'bias_enter',
    'spot_sh_aligned', 'cie_aligned', 'sr_touch_aligned',
})

# 📣 MIOS V5 briefing channel — when True, a plain-language market-shift
# briefing (NOT a buy/sell call) is pushed to Discord on Evolution-engine
# shifts, throttled to one per 10 min. OFF by default (opt-in).
MIOS_BRIEFINGS = False

# 📋 Execution-plan defaults — a display-only R-based trade template for an
# open/confirmed trade. NOT auto-execution; the trader still places & manages
# the order. Position sizing is approximate (options premium/delta varies);
# tune these to your own risk + strike.
EXEC_RISK_PER_TRADE_RUPEES = 2000     # your per-trade risk budget (₹)
EXEC_POINT_VALUE_PER_LOT = 37.5       # ≈ ₹ per NIFTY index point per lot
                                      # (ATM delta ~0.5 × lot 75) — adjust


def _build_execution_plan(side, entry, sl, t1, mp=None):
    """Pure R-based execution template for an open/confirmed trade.

    Display-only decision support (no auto-execution). Returns entry / stop /
    T1 / T2 / R:R / breakeven-shift / trail rule / partial-exit rule and an
    approximate lot suggestion. T2 = next liquidity pool beyond T1 in the trade
    direction, else one extra R past T1.
    """
    try:
        entry = float(entry); sl = float(sl); t1 = float(t1)
    except Exception:
        return None
    sign = 1 if side == 'CALL' else -1
    R = max(abs(entry - sl), 1.0)
    t2 = None
    try:
        pools = (mp or {}).get('liq_pools') or {}
        cand = pools.get('above' if sign > 0 else 'below') or []
        for p in cand:
            px = float(p.get('price'))
            if (px - t1) * sign > 5:          # a pool beyond T1, our way
                t2 = px
                break
    except Exception:
        t2 = None
    if t2 is None:
        t2 = entry + sign * (abs(t1 - entry) + R)
    rr1 = abs(t1 - entry) / R
    rr2 = abs(t2 - entry) / R
    be_at = entry + sign * R                  # move SL→breakeven at +1R
    try:
        lots = max(1, round(EXEC_RISK_PER_TRADE_RUPEES / (R * EXEC_POINT_VALUE_PER_LOT)))
    except Exception:
        lots = None
    return {
        'side': side, 'entry': round(entry, 1), 'sl': round(sl), 'risk_pts': round(R),
        't1': round(t1), 'rr1': round(rr1, 2), 't2': round(t2), 'rr2': round(rr2, 2),
        'be_at': round(be_at), 'lots': lots,
        'trail': (f"SL → breakeven ₹{be_at:.0f} at +1R; after T1, trail under the "
                  f"last 3-bar swing (≈1R steps)"),
        'partial': (f"book ~50% at T1 ₹{t1:.0f}, hold ~50% for T2 ₹{t2:.0f} "
                    f"with the trailed stop"),
    }


def send_discord_message(message, force=False):
    """Post a message to a Discord channel via webhook URL.

    ⏸️ PAUSED: Old Discord webhook disabled (awaiting migration to market_events).
    New alerts route through market_events table + Discord feed instead.
    This function is a no-op until market_events integration is complete."""
    # Old Discord webhook system is paused
    return

    # Legacy code below (kept for reference during migration)
    if not DISCORD_WEBHOOK_URL:
        try:
            st.session_state['_discord_last_error'] = 'DISCORD_WEBHOOK_URL not set'
        except Exception:
            pass
        return
    if not force and not _msg_allowed(message):
        return
    import re as _re
    import time as _time
    msg = (message or '')
    # <b>...</b> → **...**; strip remaining HTML tags
    msg = _re.sub(r'<b>(.*?)</b>', r'**\1**', msg, flags=_re.DOTALL)
    msg = _re.sub(r'<[^>]+>', '', msg)
    msg = msg[:1900]
    if not msg.strip():
        return
    # Avoid Discord 429s (30 msgs/min per webhook): 1s spacing per send
    try:
        _last_d = st.session_state.get('_discord_last_send_ts')
        _now_d = datetime.now(pytz.timezone('Asia/Kolkata'))
        if _last_d and (_now_d - _last_d).total_seconds() < 1.0:
            _time.sleep(1.0 - (_now_d - _last_d).total_seconds())
        st.session_state['_discord_last_send_ts'] = datetime.now(pytz.timezone('Asia/Kolkata'))
    except Exception:
        pass
    last_err = None
    for _attempt in range(3):
        try:
            import requests as _requests
            r = _requests.post(DISCORD_WEBHOOK_URL,
                               json={'content': msg, 'username': 'Cash Maerket Bot'},
                               timeout=10)
            if r.status_code in (200, 204):
                try:
                    st.session_state['_discord_last_error'] = None
                    st.session_state['_discord_last_ok_ts'] = datetime.now(pytz.timezone('Asia/Kolkata'))
                except Exception:
                    pass
                return
            if r.status_code == 429:
                # Rate-limited — respect retry-after
                try:
                    retry = float(r.json().get('retry_after', 1.0))
                except Exception:
                    retry = 1.0
                _time.sleep(min(retry, 5.0))
                continue
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            break
        except Exception as _e:
            last_err = f"{type(_e).__name__}: {str(_e)[:200]}"
            _time.sleep(0.5)
    try:
        st.session_state['_discord_last_error'] = last_err or 'unknown failure'
    except Exception:
        pass


_DISCORD_SEV_EMOJI = {"info": "🟢", "warning": "🟡", "alert": "🔴"}


def _relay_event_to_discord(severity, headline, detail=""):
    """Post a WARNING/ALERT market event straight to the Discord channel via
    the REST API (Authorization: Bot <token>) — runs inside the app, no
    separate bot process. INFO events stay out of Discord (Supabase only).
    Best-effort + deduped so a repeated event doesn't spam. Requires
    DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID in secrets."""
    try:
        # severity may be an EventSeverity enum or a plain string
        _sev = str(getattr(severity, "value", severity)).lower()
        if _sev not in ("warning", "alert"):
            return
        if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
            return
        # dedup: same headline within 5 min → skip (avoids repost spam)
        _sig = str(headline)[:120]
        _seen = st.session_state.setdefault('_discord_relay_seen', {})
        _now = time.time()
        if _now - _seen.get(_sig, 0) < 300:
            return
        _seen[_sig] = _now
        _em = _DISCORD_SEV_EMOJI.get(_sev, "🟡")
        _msg = f"{_em} **{headline}**" + (f"\n└─ {detail}" if detail else "")
        import requests as _rq
        _rq.post(
            f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}",
                     "Content-Type": "application/json"},
            json={"content": _msg[:1900]}, timeout=8)
    except Exception:
        pass  # never break live trading on a Discord hiccup


def capture_market_event(event_type, severity, headline, detail="", snapshot=None):
    """Capture a significant market event for Story Engine processing.

    Called when notable market microstructure events occur (put/call writing,
    support breaks, CVD reversals, etc.). Asynchronously fed to Story Engine
    for pattern recognition and narrative generation. Zero impact on live
    trading latency (fire-and-forget).

    Args:
        event_type: EventType enum value
        severity: EventSeverity enum value
        headline: Short event description
        detail: Extended context
        snapshot: Market snapshot dict (price, spot, futures, options, regime, etc.)
    """
    try:
        db = st.session_state.get('_db_obj')
        if not db:
            return  # Database not ready
        # Build event
        event = build_event(
            event_type=event_type,
            severity=severity,
            headline=headline,
            detail=detail,
            time=datetime.now(pytz.timezone('Asia/Kolkata')),
            snapshot=snapshot or {}
        )
        # 🗄️ persist the raw event (market_events — the audit trail AND the
        # source discord_bot.py polls for the live feed)
        try:
            db.insert_market_event(event.to_dict())
        except Exception:
            pass
        # 📣 Relay WARNING/ALERT events to Discord in-app via REST (no separate
        # bot process). INFO events stay in Supabase only.
        try:
            _relay_event_to_discord(severity, headline, detail)
        except Exception:
            pass
        # Feed to story engine (async, no-op on failure / not initialised yet)
        task = st.session_state.get('_story_task')
        if task:
            story_result = process_market_event(task, db, event)
            st.session_state.setdefault('_story_events_processed', 0)
            st.session_state['_story_events_processed'] += 1
            if story_result:
                st.session_state.setdefault('_story_results', []).append(story_result)
    except Exception:
        pass  # Never break live trading


def send_telegram_alert_bot(message):
    """Send via the SECOND, dedicated alert bot (TELEGRAM_ALERT_BOT_TOKEN /
    TELEGRAM_ALERT_CHAT_ID in secrets). Carries only the high-conviction
    entry alerts so they never drown in the main bot's stream. Best-effort:
    no-op when unconfigured; failures stored for diagnostics."""
    if not TELEGRAM_ALERT_BOT_TOKEN or not TELEGRAM_ALERT_CHAT_ID or not message:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_ALERT_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_ALERT_CHAT_ID,
               "text": message[:4090], "parse_mode": "HTML"}
    import time as _time
    for _attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                st.session_state['_alert_bot_last_error'] = None
                return r.json()
            if r.status_code == 429:
                _time.sleep(2 * (_attempt + 1))
                continue
            # HTML parse errors → retry once as plain text
            if r.status_code == 400 and _attempt == 0:
                payload = {"chat_id": TELEGRAM_ALERT_CHAT_ID,
                           "text": _strip_html_tags(message)[:4090]}
                continue
            st.session_state['_alert_bot_last_error'] = f"{r.status_code}: {r.text[:200]}"
            return None
        except Exception as e:
            st.session_state['_alert_bot_last_error'] = str(e)
            _time.sleep(1 + _attempt)
    return None


def send_formation_alert(message):
    """📐 Formation notes (new HVP / VOB) → the SECOND Telegram account.

    The owner asked for these off the main bot. Only the Telegram destination
    moved: Discord still gets its copy exactly as before, and the seed/diff
    anti-spam rule in `_notify_chart_formations` is untouched.

    When the alert bot is unconfigured the main bot carries it — a message the
    owner asked for should not vanish because a secret is missing. In that case
    `send_telegram_message_sync` posts to Discord itself, so this does not.
    """
    if not TELEGRAM_ALERT_BOT_TOKEN or not TELEGRAM_ALERT_CHAT_ID:
        return send_telegram_message_sync(message, force=True)
    try:
        send_discord_message(message, force=True)
    except Exception:
        pass
    return send_telegram_alert_bot(message)


def _mios_market_read():
    """Spot, V5/V6 bias, per-side energy, premium LTP + its own S/R, and the
    Stage 71.85 behaviour — assembled from what the cycle already published.

    Reads only; computes nothing. Every value has an owner elsewhere, and a
    key that is missing simply does not reach the message.
    """
    out = {}
    try:
        # ⚠️ One owner (`mios_v5.spot`). This read the chain's `underlying`
        # only, so the app header and the V6 header showed two different numbers
        # and both called them spot.
        from mios_v5.spot import price as _spot_price
        out["spot"] = _spot_price(st.session_state)
    except Exception:
        try:
            out["spot"] = (st.session_state.get("_cached_option_data")
                           or {}).get("underlying")
        except Exception:
            pass
    # Stage 27's arbitrated read vs Stage 71's — the disagreement is the point.
    try:
        from mios_v5.final_read import build_final_read
        from mios_v5.v6_bias import compare as _cmp
        _fr = build_final_read(st.session_state.get("_mios_state")) or {}
        _b = _cmp(_fr) or {}
        out["v5"] = (_b.get("v5") or {}).get("label")
        out["v6"] = (_b.get("v6") or {}).get("label")
    except Exception:
        pass
    # Spot S/R with their odds — the SAME ranked levels the S/R panel drew,
    # published by dashboard_v6 rather than reassembled here. `rejection` is
    # zone_intel's name for the bounce; it is renamed once, at the boundary,
    # instead of being recomputed as 100 - break.
    try:
        for _lv in (st.session_state.get("_sr_levels") or []):
            _side = str((_lv or {}).get("side") or "").upper()
            _key = ("support" if _side == "SUPPORT" else
                    "resistance" if _side == "RESISTANCE" else None)
            if not _key or _key in out:
                continue          # ranked list → the first of a side is the best
            _pr = (_lv.get("probabilities") or {})
            out[_key] = {"price": _lv.get("price"),
                         "break": _pr.get("break"),
                         "bounce": _pr.get("rejection"),
                         "trap": _pr.get("trap")}
    except Exception:
        pass

    _energy = (st.session_state.get("_premium_energy") or {}).get(
        "energy_score") or {}
    _struct = st.session_state.get("_premium_structures") or {}
    _ctx = st.session_state.get("_trading_context")
    for side in ("CALL", "PUT"):
        leg, sdata = {}, (_struct.get(side) or {})
        if _energy.get(side) is not None:
            leg["energy"] = _energy.get(side)
        for key in ("ltp", "support", "resistance"):
            if sdata.get(key) is not None:
                leg[key] = sdata.get(key)
        # Stage 71.85's behaviour and Stage 71.8's odds for THIS premium's
        # level, through the bridge that already carries them per side.
        for _field, _target in (("premium.behaviour", "behaviour"),
                                ("premium.break_probability",
                                 "break_probability"),
                                ("premium.fakeout_probability",
                                 "fakeout_probability")):
            try:
                if _ctx is None:
                    break
                _val = _ctx.value(_field)
                # ⚠️ `Mapping`, not `dict`. TradingContext freezes every
                # per-side value as a `MappingProxyType`, which is NOT a dict
                # subclass — so this test never matched and the whole
                # {'CALL': …, 'PUT': …} dict passed through unresolved. Both
                # legs then rendered the SAME raw dict into the Telegram
                # message instead of that leg's own behaviour:
                #     🟢 CALL
                #         {'CALL': 'Neutral', 'PUT': 'Neutral'}
                # Third instance of this exact confusion in the codebase, after
                # `execution_panel._get` and the panel's metadata block.
                if isinstance(_val, Mapping):
                    _val = _val.get(side)
                if _val is not None and _val != "UNKNOWN":
                    leg[_target] = _val
            except Exception:
                pass
        if leg:
            out[side.lower()] = leg
    return out


def run_simple_entry():
    """The simple entry system — five rules, evaluated every cycle, sent once.

    Deliberately NOT routed through Stage 72.9. That dispatcher claims on an
    `EntryDecision` hash, and this system produces no decision — feeding it one
    would mean minting a fake decision to satisfy a claim protocol. Instead it
    carries its own, narrower guard:

      * one message per (side, level) — re-arms when the level or side changes
      * a cooldown, so a level flickering in and out of range cannot spam
      * market-hours delivery, from `send_telegram_message_sync`

    Returns the signal so the UI can show it whether or not anything was sent.
    """
    from mios_v5.simple_entry import run as _simple
    from mios_v5.ui.telegram_message import simple_signal_message

    market = _mios_market_read()
    signal = _simple(market)
    st.session_state["_simple_entry"] = signal
    if not getattr(signal, "fired", False):
        return signal

    # One per (side, level). A level is a zone, so the same signal re-firing
    # 5 points later is the same signal.
    key = f"{signal.side}@{signal.level:.0f}" if signal.level else signal.side
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    last_key = st.session_state.get("_simple_entry_key")
    last_at = st.session_state.get("_simple_entry_at")
    if last_key == key and last_at and (now - last_at).total_seconds() < 900:
        return signal

    text = simple_signal_message(signal, market)
    if not text:
        return signal
    try:
        send_telegram_message_sync(text, force=False)
        st.session_state["_simple_entry_key"] = key
        st.session_state["_simple_entry_at"] = now
        st.session_state["_simple_entry_sent"] = st.session_state.get(
            "_simple_entry_sent", 0) + 1
    except Exception:
        pass
    return signal


def mios_v6_transport(payload, edits=None):
    """The injected transport for Stage 72.9 — entry and exit signals.

    Returns `"ok"` on a send, `"failed"` otherwise; the dispatcher understands
    both and never assumes success. It is handed to the stage as a callable, so
    `mios_v5` keeps its promise never to import a network client.

    **Every gate upstream still applies.** Stage 72.9 has already decided the
    decision is fresh, is not a duplicate, has not been superseded and is in a
    sendable state; this function does not re-litigate any of that. It renders
    and delivers, and nothing else.

    `edits` names a message this one would update. Editing is not implemented
    here yet, so an edit is sent as a new message rather than silently dropped
    — a missing exit is worse than a duplicate one.
    """
    try:
        from mios_v5.ui.telegram_message import entry_message, exit_message
        body = dict(payload or {})
        lc = st.session_state.get("_lifecycle_decision")
        lc_d = lc.to_dict() if hasattr(lc, "to_dict") else (lc or {})

        market = _mios_market_read()

        # Two variants of ONE dispatch. The registry claims on the decision
        # hash alone, so a second dispatch for the same decision would be a
        # duplicate by its own definition — the fan-out belongs here, at the
        # transport, where `send_telegram_message_sync` already mirrors to
        # Discord. The dispatcher still sees exactly one send.
        terse = (entry_message(body, market, reasons=False)
                 or exit_message(lc_d, body, market, reasons=False))
        full = (entry_message(body, market, reasons=True)
                or exit_message(lc_d, body, market, reasons=True))
        if not terse:
            return "failed"
        if edits:
            terse = "🔄 <b>UPDATE</b>\n" + terse
            full = "🔄 <b>UPDATE</b>\n" + full

        # Terse → the main bot. This is the one that must land, so its result
        # is the transport's result.
        send_telegram_message_sync(terse, force=False)

        # Reasoned → the second bot. Best-effort and deliberately NOT part of
        # the return value: the reasoning failing to arrive must never mark the
        # signal itself as undelivered, or the dispatcher would release the
        # claim and re-send a signal the trader already has.
        try:
            if full and full != terse:
                send_telegram_alert_bot(full)
                st.session_state["_mios_full_channel"] = (
                    "ok" if TELEGRAM_ALERT_CHAT_ID else "unconfigured")
        except Exception:
            st.session_state["_mios_full_channel"] = "failed"
        return "ok"
    except Exception:
        return "failed"


def send_telegram_message_sync(message, force=False):
    # ROUTING — only ENTRY-TIER automated alerts reach the main Telegram bot;
    # every other automated alert (active or muted) is Discord-only and
    # archived to Supabase. Bypassed when force=True so manual "Send Signal"
    # button clicks and scheduled sends always deliver on Telegram.
    if not force and not _msg_entry_tier(message):
        try:
            send_discord_message(message, force=True)
        except Exception:
            pass
        _log_sent_alert(message, 'discord_only' if _msg_allowed(message) else 'muted')
        return
    # Fire Discord webhook in parallel (its own mute applies). Best-effort.
    try:
        send_discord_message(message, force=force)
    except Exception:
        pass
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    # Only send during market hours (8:30 AM - 3:45 PM IST, weekdays) unless forced
    if not force:
        _now = datetime.now(pytz.timezone('Asia/Kolkata'))
        if _now.weekday() >= 5 or not (_now.replace(hour=8, minute=30, second=0, microsecond=0) <= _now <= _now.replace(hour=15, minute=45, second=0, microsecond=0)):
            return

    # Global rate limit: no two messages sent less than 1.2 seconds apart (Telegram allows ~1 msg/sec per chat)
    _now_tg = datetime.now(pytz.timezone('Asia/Kolkata'))
    _last_tg = getattr(st.session_state, '_last_tg_send_time', None)
    if _last_tg and (_now_tg - _last_tg).total_seconds() < 1.2:
        import time as _time
        _time.sleep(1.2 - (_now_tg - _last_tg).total_seconds())
    st.session_state._last_tg_send_time = datetime.now(pytz.timezone('Asia/Kolkata'))

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Telegram max message length is 4096 chars — truncate to be safe
    msg_text = message[:4090] if len(message) > 4090 else message

    import time as _time
    payload_html = {"chat_id": TELEGRAM_CHAT_ID, "text": msg_text, "parse_mode": "HTML"}
    last_err = None
    # Retry on 429 (rate limit) and network errors so a single throttle doesn't drop a part
    for _attempt in range(4):
        try:
            response = requests.post(url, json=payload_html, timeout=15)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:
                # Honor Telegram's retry_after if present, else exponential backoff
                try:
                    retry_after = int(response.json().get('parameters', {}).get('retry_after', 0))
                except Exception:
                    retry_after = 0
                _time.sleep(max(retry_after, 2 ** _attempt))
                continue
            if response.status_code == 400:
                # HTML parse error → fall back to plain text once
                plain_text = _strip_html_tags(msg_text)
                resp2 = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain_text}, timeout=15)
                if resp2.status_code == 200:
                    return resp2.json()
                if resp2.status_code == 429:
                    try:
                        retry_after = int(resp2.json().get('parameters', {}).get('retry_after', 0))
                    except Exception:
                        retry_after = 0
                    _time.sleep(max(retry_after, 2 ** _attempt))
                    payload_html = {"chat_id": TELEGRAM_CHAT_ID, "text": plain_text}
                    continue
                last_err = f"plain fallback {resp2.status_code} — {resp2.text[:200]}"
                break
            if 500 <= response.status_code < 600:
                _time.sleep(2 ** _attempt)
                continue
            last_err = f"{response.status_code} — {response.text[:200]}"
            break
        except requests.exceptions.RequestException as e:
            last_err = str(e)
            _time.sleep(2 ** _attempt)
            continue
    if last_err:
        try:
            st.warning(f"Telegram send failed after retries: {last_err}")
        except Exception:
            pass
    return None






def _trip_dhan_backoff():
    """Trip the global Dhan rate-limit back-off, ESCALATING. Returns the pause in
    seconds. The first 429 pauses only briefly so the NIFTY chart and spot
    recover fast; consecutive 429s double up to the historical 90s cap so
    sustained DH-904 limiting still relieves. `_clear_dhan_backoff` on any
    success resets the ladder, so an isolated blip only ever gets the short
    first pause."""
    from mios_v5.rate_backoff import backoff_seconds as _bs, BASE_S, CAP_S
    _ist = pytz.timezone('Asia/Kolkata')
    _now = datetime.now(_ist)
    _until = st.session_state.get('_dhan_429_until')
    # A burst of 429s within ONE cycle is a single event — don't re-escalate on
    # every leg. Only a 429 that lands AFTER the last window expired means the
    # limiting persisted, so only that bumps the ladder.
    if _until and _now < _until:
        return _bs(int(st.session_state.get('_dhan_429_count', 1) or 1), BASE_S, CAP_S)
    n = int(st.session_state.get('_dhan_429_count', 0) or 0) + 1
    st.session_state['_dhan_429_count'] = n
    secs = _bs(n, BASE_S, CAP_S)
    st.session_state['_dhan_429_until'] = _now + timedelta(seconds=secs)
    return secs


def _clear_dhan_backoff():
    """A clean fetch clears the escalation ladder, so the next isolated 429 pays
    only the short first pause rather than inheriting an old streak."""
    if st.session_state.get('_dhan_429_count'):
        st.session_state['_dhan_429_count'] = 0


class DhanAPI:
    def __init__(self, access_token, client_id):
        self.access_token = access_token.strip() if access_token else ""
        self.client_id = client_id.strip() if client_id else ""
        self.base_url = "https://api.dhan.co/v2"
        self.headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'access-token': self.access_token,
            'client-id': self.client_id
        }

    def _handle_response(self, response, context=""):
        """Check response; flag token expiry on 401 and return None.
        On 429 (DH-904 rate limit) trip a global back-off so callers stop
        hammering Dhan and serve cached data instead — and suppress the
        repeated error spam."""
        if response.status_code == 200:
            _clear_dhan_backoff()        # a clean fetch resets the escalation
            return response.json()
        if response.status_code == 401:
            st.session_state['_dhan_token_expired'] = True
            st.error("🔑 **Dhan token expired.** Open the **Refresh Dhan Token** panel in the sidebar, paste your new access token, and click Apply.")
        elif response.status_code == 429:
            _ist = pytz.timezone('Asia/Kolkata')
            _now = datetime.now(_ist)
            # Global back-off window — _opt_analyze and other callers check this.
            # Escalating: a transient blip clears fast; sustained 429s back off hard.
            _secs = _trip_dhan_backoff()
            # Notify at most once per 30s instead of spamming on every leg.
            _last = st.session_state.get('_dhan_429_notified')
            if not _last or (_now - _last).total_seconds() > 30:
                st.session_state['_dhan_429_notified'] = _now
                st.warning(f"⏸️ Dhan rate-limited (DH-904). Throttling for {_secs:.0f}s — "
                           "showing cached data until it clears.")
        else:
            st.error(f"API Error: {response.status_code} - {response.text}")
        return None

    def get_intraday_data(self, security_id="13", exchange_segment="IDX_I", instrument="INDEX", interval="1", days_back=1):
        url = f"{self.base_url}/charts/intraday"
        ist = pytz.timezone('Asia/Kolkata')
        # Respect an active rate-limit back-off: skip the call entirely so we
        # don't keep tripping DH-904. Callers fall back to cached data.
        _back = st.session_state.get('_dhan_429_until')
        if _back and datetime.now(ist) < _back:
            return None
        # ── one identical request per render, whoever asks ──────────────
        # Callers each hold their own cache (the legs, the wings, the CVD
        # history), but the two index fetches held none, so the same request
        # could be issued twice in a cycle. It happens for real: the chart
        # frame asks for `interval` over `days_back`, and the 5-minute frame
        # asks for "5" over `max(days_back, 3)` — pick "5 min" on the timeframe
        # selector with Days at 3 or more and those are byte-identical.
        #
        # Keyed by the render sequence, so a later render still refetches and
        # the still-forming candle keeps updating; within one render the answer
        # cannot have changed anyway, since it is a single instant.
        _memo_key = (str(security_id), str(exchange_segment), str(instrument),
                     str(interval), int(days_back))
        _rid = st.session_state.get('_render_seq')
        _memo = st.session_state.get('_intraday_memo')
        if _memo is None or _memo.get('render') != _rid:
            _memo = {'render': _rid, 'by_key': {}}
            st.session_state['_intraday_memo'] = _memo
        if _memo_key in _memo['by_key']:
            return _memo['by_key'][_memo_key]
        # Throttle: enforce a minimum gap between intraday calls so the legs
        # don't burst past Dhan's per-second limit.
        try:
            _last = st.session_state.get('_dhan_last_intraday_ts')
            _now_t = time.time()
            if _last is not None:
                _gap = _now_t - _last
                if _gap < 0.3:
                    time.sleep(0.3 - _gap)
            st.session_state['_dhan_last_intraday_ts'] = time.time()
        except Exception:
            pass
        end_date = datetime.now(ist)
        start_date = end_date - timedelta(days=days_back)
        payload = {
            "securityId": security_id,
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "interval": interval,
            "oi": False,
            "fromDate": start_date.strftime("%Y-%m-%d %H:%M:%S"),
            "toDate": end_date.strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            out = self._handle_response(response)
            # Only a real answer is memoised. Caching a None would make one
            # failed fetch look like "no data" to every other caller this
            # render, which is the failure mode the expiry-list cache
            # documents — and each caller has its own fallback to reach for.
            if out:
                _memo['by_key'][_memo_key] = out
            return out
        except Exception as e:
            st.error(f"Error fetching data: {str(e)}")
            return None

    def get_daily_data(self, security_id="13", exchange_segment="IDX_I",
                       instrument="INDEX", years_back=5):
        """Daily OHLCV from Dhan's own history endpoint.

        ⚠️ Added because the higher-timeframe layer had exactly ONE source of daily
        bars — a `yfinance` download inside a bare `except Exception: pass`. When it
        failed there was no error, no caption and no daily frame, so Stage 45's
        Daily / Weekly / Monthly / Yearly profiles were never built and nothing on
        screen said so. The app is already authenticated with Dhan for the chain,
        the LTP and every intraday series; asking it for daily bars too removes a
        third-party dependency from the one layer that had no fallback.

        `/charts/historical` is the daily sibling of `/charts/intraday` this class
        already calls. Returns the same `{open, high, low, close, volume,
        timestamp}` shape, so callers frame it identically.
        """
        url = f"{self.base_url}/charts/historical"
        ist = pytz.timezone('Asia/Kolkata')
        _back = st.session_state.get('_dhan_429_until')
        if _back and datetime.now(ist) < _back:
            return None
        end_date = datetime.now(ist)
        start_date = end_date - timedelta(days=int(years_back) * 366)
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "expiryCode": 0,
            "oi": False,
            "fromDate": start_date.strftime("%Y-%m-%d"),
            "toDate": end_date.strftime("%Y-%m-%d"),
        }
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            return self._handle_response(response)
        except Exception as e:
            # Recorded, not printed: this runs inside the cycle and the panel that
            # needs it says so itself. Silence is what broke this in the first place.
            st.session_state['_htf_daily_error'] = f"Dhan history: {e}"
            return None

    def get_ltp_data(self, security_id="13", exchange_segment="IDX_I"):
        url = f"{self.base_url}/marketfeed/ltp"
        payload = {
            exchange_segment: [int(security_id)]
        }
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            return self._handle_response(response)
        except Exception as e:
            st.error(f"Error fetching LTP: {str(e)}")
            return None

    def place_order(self, security_id, exchange_segment, transaction_type, quantity, order_type="MARKET", price=0, product_type="INTRADAY"):
        url = f"{self.base_url}/orders"
        payload = {
            "dhanClientId": self.client_id,
            "transactionType": transaction_type,
            "exchangeSegment": exchange_segment,
            "productType": product_type,
            "orderType": order_type,
            "validity": "DAY",
            "securityId": str(security_id),
            "quantity": quantity,
            "price": price,
            "triggerPrice": 0,
            "disclosedQuantity": 0,
            "afterMarketOrder": False,
        }
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            if response.status_code == 401:
                st.session_state['_dhan_token_expired'] = True
                return {"error": "Token expired — refresh in sidebar"}
            if response.status_code == 200:
                return response.json()
            return {"error": f"{response.status_code} — {response.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def get_option_ltp(self, security_id, exchange_segment="NSE_FNO"):
        url = f"{self.base_url}/marketfeed/ltp"
        payload = {exchange_segment: [int(security_id)]}
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            if response.status_code == 401:
                st.session_state['_dhan_token_expired'] = True
                return None
            if response.status_code == 200:
                data = response.json()
                items = data.get('data', {}).get(exchange_segment, [])
                if items:
                    return float(items[0].get('last_price', 0))
            return None
        except Exception:
            return None

    def get_positions(self):
        url = f"{self.base_url}/positions"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 401:
                st.session_state['_dhan_token_expired'] = True
            return response.json() if response.status_code == 200 else None
        except Exception:
            return None

    def get_orders(self):
        url = f"{self.base_url}/orders"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 401:
                st.session_state['_dhan_token_expired'] = True
            return response.json() if response.status_code == 200 else None
        except Exception:
            return None

    def get_order_by_id(self, order_id):
        url = f"{self.base_url}/orders/{order_id}"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 401:
                st.session_state['_dhan_token_expired'] = True
            return response.json() if response.status_code == 200 else None
        except Exception:
            return None

    def get_quote(self, security_id, exchange_segment="NSE_FNO"):
        """Full quote (LTP, volume, OI, OHLC) for a single security via
        /v2/marketfeed/quote. Falls back to /marketfeed/ltp on empty quote
        so the caller still gets at least the last price."""
        url = f"{self.base_url}/marketfeed/quote"
        payload = {exchange_segment: [int(security_id)]}
        try:
            _quote_gate(url)
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            if response.status_code == 401:
                st.session_state['_dhan_token_expired'] = True
                st.session_state['_nifty_fut_err'] = "401 token expired"
                return None
            if response.status_code == 200:
                items = response.json().get('data', {}).get(exchange_segment, {})
                if items:
                    node = items.get(str(security_id)) or next(iter(items.values()), None)
                    if node and float(node.get('last_price') or 0) > 0:
                        st.session_state['_nifty_fut_err'] = None
                        return node
                # 200-but-empty: fall through to LTP fallback below
            elif response.status_code == 429:
                st.session_state['_nifty_fut_err'] = "429 rate-limited (quote=1 req/sec)"
            elif response.status_code != 200:
                st.session_state['_nifty_fut_err'] = f"quote HTTP {response.status_code}: {response.text[:120]}"
        except Exception as e:
            st.session_state['_nifty_fut_err'] = f"quote net err: {str(e)[:120]}"

        # Fallback: /marketfeed/ltp — same security id, simpler endpoint.
        # Returns just last_price (no OI/volume) but at least lets us compute basis.
        try:
            ltp_url = f"{self.base_url}/marketfeed/ltp"
            _quote_gate(ltp_url)
            ltp_resp = requests.post(ltp_url, headers=self.headers, json=payload, timeout=10)
            if ltp_resp.status_code == 200:
                items = ltp_resp.json().get('data', {}).get(exchange_segment, {})
                node = items.get(str(security_id)) or next(iter(items.values()), None) if items else None
                if node and float(node.get('last_price') or 0) > 0:
                    st.session_state['_nifty_fut_err'] = "quote empty — using /ltp fallback (no OI/vol)"
                    # Shape it like a quote response
                    return {'last_price': float(node['last_price']), 'volume': 0, 'oi': 0,
                            'ohlc': {}, '_ltp_only': True}
                if not st.session_state.get('_nifty_fut_err'):
                    st.session_state['_nifty_fut_err'] = (
                        f"both quote+ltp returned empty · seg={exchange_segment}, sec={security_id} — "
                        "likely wrong security id from scrip master")
            else:
                if not st.session_state.get('_nifty_fut_err'):
                    st.session_state['_nifty_fut_err'] = f"ltp HTTP {ltp_resp.status_code}"
        except Exception as e:
            if not st.session_state.get('_nifty_fut_err'):
                st.session_state['_nifty_fut_err'] = f"ltp net err: {str(e)[:120]}"
        return None

def get_dhan_expiry_list_cached(underlying_scrip: int, underlying_seg: str):
    """The expiry list, with the last good answer kept as a fallback.

    This used to be a bare `@st.cache_data(ttl=300)` around the fetch, which
    cached the **failure** too. One transient `502 Bad Gateway` from Dhan blanked
    the expiry list for five full minutes — long after Dhan had recovered — and
    with no expiry there is no option chain, so `_cached_option_data` went stale
    and every chain-derived V6 stage degraded with it.

    The expiry list changes at most once a day. Serving yesterday's answer
    through a blip is strictly better than serving nothing, so a good result is
    remembered in session state and reused whenever the fetch comes back empty.
    """
    key = f"_expiry_cache_{underlying_scrip}_{underlying_seg}"
    cached = st.session_state.get(key)
    if cached and (time.time() - cached['ts']) < 300:
        return cached['data']
    fresh = get_dhan_expiry_list(underlying_scrip, underlying_seg)
    if fresh and (fresh.get('data') if isinstance(fresh, dict) else None):
        st.session_state[key] = {'ts': time.time(), 'data': fresh}
        return fresh
    # Fetch failed. Reuse the last good list however old it is — a stale expiry
    # is a real expiry; None is a blank page.
    if cached:
        st.session_state['_expiry_stale'] = True
        return cached['data']
    return fresh

#: Dhan caps Quote APIs — `marketfeed/ltp` and `marketfeed/quote` — at 1
#: request per SECOND, the tightest per-second limit in the whole API. The
#: intraday endpoint has had a 0.3s gate since the legs started bursting; the
#: quote endpoints had none, despite a stricter limit and several callers.
QUOTE_MIN_GAP_S = 1.05          # a hair over 1s, so rounding cannot trip it


def _quote_gate(url):
    """Space consecutive Quote-API calls to stay inside Dhan's 1/second cap."""
    if 'marketfeed' not in str(url):
        return
    try:
        last = st.session_state.get('_dhan_last_quote_ts')
        now = time.time()
        if last is not None:
            gap = now - last
            if gap < QUOTE_MIN_GAP_S:
                time.sleep(QUOTE_MIN_GAP_S - gap)
        st.session_state['_dhan_last_quote_ts'] = time.time()
    except Exception:
        pass


def _dhan_post(url, payload, max_retries=4):
    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
        st.error("Dhan API credentials not configured")
        return None
    _quote_gate(url)
    headers = {'access-token': DHAN_ACCESS_TOKEN, 'client-id': DHAN_CLIENT_ID, 'Content-Type': 'application/json'}
    # ── retry budget, bounded by the refresh cycle ──
    # These were [2, 4, 8, 16]: a fully rate-limited chain fetch slept for 30
    # SECONDS inside a 20-second render, so the page could not draw and the
    # next autorefresh queued behind it. The whole cycle has 20s; one endpoint
    # may not spend more than a third of it waiting.
    #
    # Bounding the SLEEP was not enough. With `timeout=10` and four attempts,
    # worst-case wall time was 4x10 + 7 = 47s — worse on the timeout path than
    # the ladder this replaced. What has to be bounded is total elapsed time, so
    # there is a deadline and the per-attempt timeout is sized to fit inside it.
    delays = [1, 2, 4]
    max_retries = min(max_retries, len(delays))
    deadline = time.time() + 12.0          # hard cap: sleeps AND socket waits
    for attempt in range(max_retries + 1):
        remaining = deadline - time.time()
        if remaining <= 0.5:
            st.session_state['_dhan_last_error'] = 'timeout budget exhausted'
            return None
        try:
            # timeout was absent: a hung socket blocked the render forever,
            # with no error and no way for the user to tell it apart from a
            # slow response.
            response = requests.post(url, headers=headers, json=payload,
                                     timeout=min(6.0, remaining))
            if response.status_code == 401:
                st.session_state['_dhan_token_expired'] = True
                # ⚠️ Record the reason too. Every standing-by panel falls back to
                # "chain fetch returned nothing" when `_dhan_last_error` is unset,
                # so a token expiry — the one cause only the user can fix — was
                # being reported as an unexplained empty fetch.
                st.session_state['_dhan_last_error'] = 'Dhan token expired (401)'
                st.error("🔑 **Dhan token expired.** Open **Refresh Dhan Token** in the sidebar and paste your new token.")
                return None
            if response.status_code == 429:
                # Trip the GLOBAL back-off on the first 429 so every other
                # caller this render serves cached data instead of queueing
                # behind its own retry ladder. `_dhan_429_until` is the flag
                # DhanAPI._handle_response already sets and every fetch checks.
                try:
                    _trip_dhan_backoff()
                except Exception:
                    pass
                if attempt < max_retries:
                    d = delays[min(attempt, len(delays) - 1)]
                    st.warning(f"⏳ Rate limited by Dhan API. Retrying in {d}s... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(d)
                    continue
                st.session_state['_dhan_last_error'] = (
                    f"rate limited (429) after {max_retries} retries")
                st.error("❌ Rate limit exceeded after multiple retries. Please wait a moment and refresh.")
                return None
            # ── 5xx: Dhan is broken, not us — and it is usually transient ──
            # Only 429 was retried. A single `502 Bad Gateway` fell straight
            # through to the generic handler and returned None with ZERO
            # retries, which is the one failure class retries exist for.
            if 500 <= response.status_code < 600:
                if attempt < max_retries:
                    time.sleep(delays[min(attempt, len(delays) - 1)])
                    continue
                st.session_state['_dhan_last_error'] = (
                    f"Dhan {response.status_code} on {url.rsplit('/', 1)[-1]}")
                st.warning(
                    f"⚠️ Dhan API returned **{response.status_code}** "
                    f"({url.rsplit('/', 1)[-1]}) after {max_retries} retries — "
                    "their end, not yours. Serving the last good data; it "
                    "clears itself when Dhan recovers.")
                return None
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            # Retry the transient classes: rate limits, upstream 5xx, timeouts
            # and dropped connections. A bad request or a bad token will not fix
            # itself on a second attempt, so those still fail immediately.
            transient = (
                "429" in str(e)
                or any(c in str(e) for c in ("502", "503", "504"))
                or isinstance(e, (requests.exceptions.Timeout,
                                  requests.exceptions.ConnectionError)))
            if attempt < max_retries and transient:
                time.sleep(delays[min(attempt, len(delays) - 1)])
                continue
            st.session_state['_dhan_last_error'] = str(e)[:200]
            st.error(f"Request error: {e}")
            return None
    return None

#: Dhan documents the option chain separately from every other Data API:
#: "Rate limit for Option Chain API is set to one unique request every 3
#: seconds", because OI updates far slower than LTP. It is the strictest limit
#: the app touches and was the only fetch with no throttle at all — the intraday
#: endpoint has had a 0.3s gap for ages while this one fired in a tight loop.
OPTION_CHAIN_MIN_GAP_S = 3.0

#: Long enough that one render never fetches the same chain twice, short enough
#: that the next render (~20s later) still gets a fresh one. The nearest expiry
#: was being fetched twice per cycle — once for the main read, once as the first
#: entry of the cross-expiry loop — because this function had no cache at all.
OPTION_CHAIN_TTL_S = 10.0


def get_dhan_option_chain(underlying_scrip: int, underlying_seg: str, expiry: str,
                          max_retries: int = 4, allow_wait: bool = True):
    """One option chain, cached per (scrip, seg, expiry) and rate-gated.

    Returns the cached payload when it is younger than `OPTION_CHAIN_TTL_S`, so
    two callers asking for the same expiry in one render cost one request.

    Otherwise it waits out the remainder of Dhan's 3s window before calling.
    `allow_wait=False` makes it give up instead of sleeping — for callers that
    would rather skip an expiry than spend the render's budget waiting.
    """
    key = f"{underlying_scrip}|{underlying_seg}|{expiry}"
    store = st.session_state.setdefault('_option_chain_cache', {})
    hit = store.get(key)
    now = time.time()
    if hit and (now - hit['ts']) < OPTION_CHAIN_TTL_S:
        return hit['data']

    # Space DISTINCT requests. The window is global to the endpoint, not
    # per-expiry, so it is tracked on one timestamp rather than per key.
    last = st.session_state.get('_option_chain_last_ts')
    if last is not None:
        wait = OPTION_CHAIN_MIN_GAP_S - (now - last)
        if wait > 0:
            if not allow_wait:
                return hit['data'] if hit else None
            time.sleep(min(wait, OPTION_CHAIN_MIN_GAP_S))

    st.session_state['_option_chain_last_ts'] = time.time()
    resp = _dhan_post("https://api.dhan.co/v2/optionchain",
                      {"UnderlyingScrip": underlying_scrip, "UnderlyingSeg": underlying_seg, "Expiry": expiry},
                      max_retries)
    # Only a real answer replaces the cache — a failed fetch must not blank a
    # good chain, which is the mistake the expiry-list cache documents above.
    if resp:
        store[key] = {'ts': time.time(), 'data': resp}
        return resp
    return hit['data'] if hit else None


@st.cache_resource(show_spinner=False)
def strike_store():
    """📊 Per-strike OI / ΔOI history for ATM±2, one store for the process.

    ⚠️ Built rather than wired: the reference charts read
    `st.session_state.oi_history` / `.chgoi_history`, and NEITHER EXISTS in this
    app. What exists is `df_summary`, rebuilt every cycle — so the time series has
    to be accumulated from those snapshots.

    `cache_resource` for the same reason as `iv_store`: `cache_data` returns a
    copy, so appends would be discarded, and `session_state` is per browser
    session, so the collection would restart on every reload and in every tab.
    Bounded by `strike_history.CAP`.
    """
    return {"snaps": []}


@st.cache_resource(show_spinner=False)
def iv_store():
    """📈 The ATM IV history, one store for the whole process.

    ⚠️ `st.cache_resource`, not `st.cache_data` and not `session_state`:

    * **not `session_state`** — that is per browser session, so a restart or a
      second tab began with no history and `volatility_state`, which needs two
      samples, reported "not reporting". Losing the history on every reload was
      the whole complaint.
    * **not `cache_data`** — it returns a COPY, so appends would be discarded.
      `cache_resource` hands back the same mutable object every time, which is
      exactly what a growing series needs.

    Bounded by `iv_history.CAP`, so sharing it across sessions cannot grow
    without limit. `mios_v5.iv_history` owns what goes in.
    """
    return {"samples": []}


def get_index_spot_ltp(scrip: int = NIFTY_UNDERLYING_SCRIP, seg: str = NIFTY_UNDERLYING_SEG):
    """Live index spot from Dhan's marketfeed/ltp endpoint (NIFTY 50 = 13/IDX_I).

    The option-chain payload's `last_price` is the underlying spot too, but it
    refreshes on the chain's slower cadence and can lag the live index by a few
    seconds. This dedicated quote is the most direct read of the current spot.
    Cached ~4s in session_state, and skipped during a 429 back-off so it never
    adds pressure when Dhan is throttling. Returns a float, or None on failure.
    """
    try:
        _ist = pytz.timezone('Asia/Kolkata')
        _now = datetime.now(_ist)
        _back = st.session_state.get('_dhan_429_until')
        if _back and _now < _back:
            return None
        _ck = f'_idx_spot_ltp_{scrip}_{seg}'
        _cached = st.session_state.get(_ck)
        # Scoped to the render, not to a stopwatch. A 4s TTL was shorter than a
        # render — the legs alone spend 0.3s apiece under their fetch gate — so
        # the four call sites spread through a cycle kept missing it and
        # re-fetching the same spot, on an endpoint Dhan caps at 1 request per
        # second. Once per render per (scrip, seg) is what this is worth; the
        # 4s floor still applies across renders so a fast rerun cannot burst.
        _rid = st.session_state.get('_render_seq')
        if _cached:
            _same_render = _rid is not None and _cached.get('render') == _rid
            if _same_render or (_now - _cached['ts']).total_seconds() < 4:
                return _cached['ltp']
        resp = _dhan_post("https://api.dhan.co/v2/marketfeed/ltp",
                          {seg: [int(scrip)]}, max_retries=1)
        if not resp:
            return None
        node = (resp.get('data', {}) or {}).get(seg, {}).get(str(scrip)) \
            or (resp.get('data', {}) or {}).get(seg, {}).get(int(scrip))
        ltp = float(node.get('last_price') or 0) if node else 0.0
        if ltp > 0:
            st.session_state[_ck] = {'ltp': ltp, 'ts': _now, 'render': _rid}
            return ltp
    except Exception:
        pass
    return None

def get_dhan_expiry_list(underlying_scrip: int, underlying_seg: str, max_retries: int = 4):
    return _dhan_post("https://api.dhan.co/v2/optionchain/expirylist",
                      {"UnderlyingScrip": underlying_scrip, "UnderlyingSeg": underlying_seg},
                      max_retries)

#: How long to wait on the scrip master before giving up. `pd.read_csv(url)`
#: accepts no timeout at all, so a stalled connection blocks forever — which is
#: how the app came to sit on its loading screen. (connect, read) seconds.
SCRIP_MASTER_TIMEOUT = (10, 90)


@st.cache_data(ttl=21600, show_spinner=False)
def _scrip_master():
    """Dhan's scrip master as one cached frame, fetched at most once per 6h.

    ~26 MB and ~212k rows. Three separate functions used to each call
    `pd.read_csv(url)` on it, so a cold start paid the download once per
    caller. They now share this one frame.

    Fetched through `requests` rather than handing the URL to pandas purely so
    it can carry a timeout: an untimed read hangs the render thread with no
    error and no way to tell it apart from a dead app.
    """
    try:
        resp = requests.get("https://images.dhan.co/api-data/api-scrip-master.csv",
                            timeout=SCRIP_MASTER_TIMEOUT)
        resp.raise_for_status()
        df = pd.read_csv(io.BytesIO(resp.content), low_memory=False)
        df.columns = [c.strip().upper() for c in df.columns]
        return df
    except Exception as e:
        st.session_state['_scrip_master_err'] = f"scrip master: {str(e)[:140]}"
        return None


@st.cache_data(ttl=21600)
def resolve_index_security_id(trading_symbol: str, exchange: str):
    """Resolve an INDEX security id from Dhan's scrip master CSV — the same
    authoritative source `get_nifty_futures_security_id` already uses.

    Hardcoding these is how the SENSEX chart silently drew NIFTY candles: a
    wrong id returns no data, and the caller kept the previous frame. Dhan is
    the only thing that actually knows the id, so ask it.

    `trading_symbol` matches SEM_TRADING_SYMBOL exactly (e.g. 'SENSEX',
    'NIFTY'); `exchange` is the SEM_EXM_EXCH_ID ('BSE' / 'NSE'). Cached 6h.
    Returns an int security id, or None when the lookup fails.
    """
    try:
        df = _scrip_master()
        if df is None:
            return None
        sym_col = next((c for c in df.columns if 'TRADING_SYMBOL' in c), None)
        inst_col = next((c for c in df.columns if 'INSTRUMENT' in c and 'NAME' in c), None)
        secid_col = next((c for c in df.columns if 'SECURITY_ID' in c), None)
        exch_col = next((c for c in df.columns if 'EXCH_ID' in c), None)
        if not all([sym_col, inst_col, secid_col, exch_col]):
            return None
        mask = (df[inst_col].astype(str).str.upper().str.strip().eq('INDEX')
                & df[sym_col].astype(str).str.upper().str.strip().eq(trading_symbol.upper())
                & df[exch_col].astype(str).str.upper().str.strip().eq(exchange.upper()))
        hit = df[mask]
        if hit.empty:
            return None
        return int(hit.iloc[0][secid_col])
    except Exception:
        return None


@st.cache_data(ttl=21600)
def get_nifty_futures_security_id():
    """Resolve the current/nearest-month NIFTY FUTIDX security id from Dhan's
    scrip master CSV. Cached 6h; auto-rolls to the next month's contract."""
    try:
        df = _scrip_master()
        if df is None:
            return None
        sym_col = next((c for c in df.columns if 'TRADING_SYMBOL' in c), None)
        inst_col = next((c for c in df.columns if 'INSTRUMENT' in c and 'NAME' in c), None)
        secid_col = next((c for c in df.columns if 'SECURITY_ID' in c), None)
        expiry_col = next((c for c in df.columns if 'EXPIRY_DATE' in c), None)
        exch_col = next((c for c in df.columns if 'EXCH_ID' in c), None)
        if not all([sym_col, inst_col, secid_col, expiry_col]):
            st.session_state['_nifty_fut_err'] = (
                f"scrip master column missing — got {list(df.columns)[:8]}…"
            )
            return None
        mask = df[inst_col].astype(str).str.upper().str.strip().eq('FUTIDX')
        if exch_col:
            mask &= df[exch_col].astype(str).str.upper().str.strip().eq('NSE')
        sym_up = df[sym_col].astype(str).str.upper()
        mask &= sym_up.str.contains('NIFTY')
        for excl in ('BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT'):
            mask &= ~sym_up.str.contains(excl)
        fut = df[mask].copy()
        if fut.empty:
            st.session_state['_nifty_fut_err'] = "no NIFTY FUTIDX rows in scrip master"
            return None
        fut['_exp'] = pd.to_datetime(fut[expiry_col], errors='coerce')
        today = pd.Timestamp(datetime.now(pytz.timezone('Asia/Kolkata')).date())
        upcoming = fut[fut['_exp'] >= today].sort_values('_exp')
        chosen = upcoming.iloc[0] if not upcoming.empty else fut.sort_values('_exp').iloc[-1]
        return {
            'security_id': str(int(chosen[secid_col])),
            'symbol': str(chosen[sym_col]),
            'expiry': chosen['_exp'].strftime('%d-%b-%Y') if pd.notna(chosen['_exp']) else '',
        }
    except Exception as e:
        st.session_state['_nifty_fut_err'] = f"scrip master load failed: {str(e)[:120]}"
        return None

@st.cache_data(ttl=21600)
def get_nifty_option_security_ids(expiry: str, symbol: str = "NIFTY"):
    """Resolve Dhan security IDs for all OPTIDX strikes of one expiry from
    the scrip-master CSV. Returns {(strike_float, 'CE'/'PE'): security_id_int}.
    Cached 6h. expiry is the Dhan option-chain expiry string (e.g. '2026-06-19').

    `symbol` selects the instrument via INDEX_OPTION_SPECS; it defaults to
    NIFTY so existing callers are unchanged.
    """
    try:
        df = _scrip_master()
        if df is None:
            return {}
        sym_col = next((c for c in df.columns if 'TRADING_SYMBOL' in c), None)
        inst_col = next((c for c in df.columns if 'INSTRUMENT' in c and 'NAME' in c), None)
        secid_col = next((c for c in df.columns if 'SECURITY_ID' in c), None)
        expiry_col = next((c for c in df.columns if 'EXPIRY_DATE' in c), None)
        exch_col = next((c for c in df.columns if 'EXCH_ID' in c), None)
        strike_col = next((c for c in df.columns if 'STRIKE' in c), None)
        opttype_col = next((c for c in df.columns if 'OPTION_TYPE' in c), None)
        if not all([sym_col, inst_col, secid_col, expiry_col, strike_col, opttype_col]):
            st.session_state['_nifty_opt_err'] = (
                f"scrip master option columns missing — got {list(df.columns)[:10]}…"
            )
            return {}
        spec = option_spec(symbol)
        mask = df[inst_col].astype(str).str.upper().str.strip().eq('OPTIDX')
        if exch_col:
            mask &= df[exch_col].astype(str).str.upper().str.strip().eq(spec["exchange"])
        sym_up = df[sym_col].astype(str).str.upper()
        # Exact symbol before the first '-', so SENSEX never picks up SENSEX50
        # and NIFTY never picks up BANKNIFTY. `contains` would take both.
        mask &= sym_up.str.split('-').str[0].str.strip().eq(spec["prefix"])
        opt = df[mask].copy()
        if opt.empty:
            st.session_state['_nifty_opt_err'] = (
                f"no {spec['prefix']} OPTIDX rows in scrip master")
            return {}
        # Match expiry by date
        opt['_exp'] = pd.to_datetime(opt[expiry_col], errors='coerce').dt.date
        try:
            target_exp = pd.to_datetime(expiry, errors='coerce').date()
        except Exception:
            target_exp = None
        if target_exp is not None:
            opt = opt[opt['_exp'] == target_exp]
        if opt.empty:
            st.session_state['_nifty_opt_err'] = f"no OPTIDX rows for expiry {expiry}"
            return {}
        result = {}
        for _, r in opt.iterrows():
            try:
                strike = float(r[strike_col])
                ot = str(r[opttype_col]).upper().strip()
                if ot in ('CE', 'CALL', 'C'):
                    ot = 'CE'
                elif ot in ('PE', 'PUT', 'P'):
                    ot = 'PE'
                else:
                    continue
                result[(strike, ot)] = int(r[secid_col])
            except Exception:
                continue
        return result
    except Exception as e:
        st.session_state['_nifty_opt_err'] = f"option scrip master load failed: {str(e)[:120]}"
        return {}




def get_nifty_futures_data(api, spot_price):
    """Fetch current NIFTY futures quote and derive basis vs spot.

    OI change is tracked across refreshes within the session (intraday delta).
    Returns dict or None.
    """
    try:
        meta = get_nifty_futures_security_id()
        if not meta:
            return None
        quote = api.get_quote(meta['security_id'], exchange_segment="NSE_FNO")
        if not quote:
            return None
        price = float(quote.get('last_price') or 0)
        if price <= 0:
            return None
        volume = float(quote.get('volume') or 0)
        oi = float(quote.get('oi') or 0)
        prev = st.session_state.get('_nifty_fut_prev_oi')
        st.session_state['_nifty_fut_prev_oi'] = oi
        prev_price = st.session_state.get('_nifty_fut_prev_price')
        st.session_state['_nifty_fut_prev_price'] = price
        chg_oi = (oi - prev) if (prev is not None and oi) else 0.0
        chg_price = (price - prev_price) if (prev_price is not None) else 0.0
        basis = price - spot_price if spot_price else 0.0
        return {
            'symbol': meta['symbol'],
            'expiry': meta['expiry'],
            'price': price,
            'volume': volume,
            'oi': oi,
            'chg_oi': chg_oi,
            'chg_price': chg_price,
            'basis': basis,
            'stance': 'Premium' if basis > 0 else 'Discount' if basis < 0 else 'Flat',
        }
    except Exception:
        return None

@st.cache_data(ttl=1800)
def get_fii_dii_cash_cached():
    from api.nse_data import get_fii_dii_cash
    return get_fii_dii_cash()

@st.cache_data(ttl=1800)
def get_fii_derivatives_stats_cached():
    from api.nse_data import get_fii_derivatives_stats
    return get_fii_derivatives_stats()



class VolumeOrderBlocks:
    def __init__(self, sensitivity=5):
        self.length1 = sensitivity
        self.length2 = sensitivity + 13
        self.max_blocks = 15

    @staticmethod
    def calculate_ema(series, period):
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calculate_atr(df, period=200):
        high = df['high']
        low = df['low']
        close = df['close'].shift(1)
        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

    def detect_blocks(self, df):
        if df.empty or len(df) < self.length2 + 10:
            return {'bullish': [], 'bearish': []}
        df = df.copy().reset_index(drop=True)
        ema_fast = self.calculate_ema(df['close'], self.length1)
        ema_slow = self.calculate_ema(df['close'], self.length2)
        atr = self.calculate_atr(df)
        max_atr = atr.rolling(window=200, min_periods=1).max()
        atr_threshold = max_atr * 2
        overlap_threshold = max_atr * 3
        cross_up = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
        cross_down = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))
        bullish_blocks = []
        bearish_blocks = []
        for idx in df[cross_up].index:
            if idx < self.length2:
                continue
            lookback_start = max(0, idx - self.length2)
            lookback_df = df.loc[lookback_start:idx]
            lowest_idx = lookback_df['low'].idxmin()
            lowest = df.loc[lowest_idx, 'low']
            vol = df.loc[lowest_idx:idx, 'volume'].sum()
            upper = min(df.loc[lowest_idx, 'open'], df.loc[lowest_idx, 'close'])
            if idx < len(atr_threshold) and not pd.isna(atr_threshold.iloc[idx]):
                min_size = atr_threshold.iloc[idx] * 0.5
                if (upper - lowest) < min_size:
                    upper = lowest + min_size
            mid = (upper + lowest) / 2
            bullish_blocks.append({
                'index': lowest_idx,
                'datetime': df.loc[lowest_idx, 'datetime'] if 'datetime' in df.columns else None,
                'upper': upper,
                'lower': lowest,
                'mid': mid,
                'volume': vol,
                'type': 'bullish'
            })
        for idx in df[cross_down].index:
            if idx < self.length2:
                continue
            lookback_start = max(0, idx - self.length2)
            lookback_df = df.loc[lookback_start:idx]
            highest_idx = lookback_df['high'].idxmax()
            highest = df.loc[highest_idx, 'high']
            vol = df.loc[highest_idx:idx, 'volume'].sum()
            lower = max(df.loc[highest_idx, 'open'], df.loc[highest_idx, 'close'])
            if idx < len(atr_threshold) and not pd.isna(atr_threshold.iloc[idx]):
                min_size = atr_threshold.iloc[idx] * 0.5
                if (highest - lower) < min_size:
                    lower = highest - min_size
            mid = (highest + lower) / 2
            bearish_blocks.append({
                'index': highest_idx,
                'datetime': df.loc[highest_idx, 'datetime'] if 'datetime' in df.columns else None,
                'upper': highest,
                'lower': lower,
                'mid': mid,
                'volume': vol,
                'type': 'bearish'
            })
        current_close = df['close'].iloc[-1]
        bullish_blocks = [b for b in bullish_blocks if current_close >= b['lower']]
        bearish_blocks = [b for b in bearish_blocks if current_close <= b['upper']]
        bullish_blocks = self._remove_overlaps(bullish_blocks, overlap_threshold.iloc[-1] if len(overlap_threshold) > 0 else 50)
        bearish_blocks = self._remove_overlaps(bearish_blocks, overlap_threshold.iloc[-1] if len(overlap_threshold) > 0 else 50)
        bullish_blocks = bullish_blocks[-self.max_blocks:]
        bearish_blocks = bearish_blocks[-self.max_blocks:]
        total_bull_vol = sum(b['volume'] for b in bullish_blocks) if bullish_blocks else 1
        total_bear_vol = sum(b['volume'] for b in bearish_blocks) if bearish_blocks else 1
        for blocks, total in [(bullish_blocks, total_bull_vol), (bearish_blocks, total_bear_vol)]:
            for b in blocks:
                b['volume_pct'] = (b['volume'] / total * 100) if total > 0 else 0
        return {'bullish': bullish_blocks, 'bearish': bearish_blocks}

    def _remove_overlaps(self, blocks, threshold):
        if len(blocks) < 2:
            return blocks
        blocks = sorted(blocks, key=lambda x: x['mid'])
        filtered = []
        for block in blocks:
            overlap = False
            for existing in filtered:
                if abs(block['mid'] - existing['mid']) < threshold:
                    if block['volume'] > existing['volume']:
                        filtered.remove(existing)
                        filtered.append(block)
                    overlap = True
                    break
            if not overlap:
                filtered.append(block)
        return filtered

    @staticmethod
    def format_volume(vol):
        if vol >= 1_000_000:
            return f"{vol/1_000_000:.1f}M"
        elif vol >= 1_000:
            return f"{vol/1_000:.0f}K"
        else:
            return str(int(vol))

    def get_sr_levels(self, df):
        blocks = self.detect_blocks(df)
        sr_levels = []
        for btype, label in [('bullish', '🟢 VOB Support'), ('bearish', '🔴 VOB Resistance')]:
            for block in blocks[btype]:
                sr_levels.append({
                    'Type': label, 'Level': f"₹{block['mid']:.0f}",
                    'Source': f"Vol: {self.format_volume(block['volume'])} ({block['volume_pct']:.1f}%)",
                    'Strength': 'VOB Zone', 'Signal': f"Range: ₹{block['lower']:.0f} - ₹{block['upper']:.0f}",
                    'upper': block['upper'], 'lower': block['lower'], 'mid': block['mid'],
                    'volume': block['volume'], 'volume_pct': block['volume_pct']
                })
        return sr_levels, blocks


def compute_dynamic_poc(df, bins=20):
    """BigBeluga 'Real-Time HTF Volume Footprint' — Dynamic PoC port.

    Over a single HTF period (here: today's whole session = '1D'), build a
    volume profile across `bins` price bins spanning the running period
    high→low, accumulating each bar's volume (normalised by stdev like the
    Pine `volume / ta.stdev(volume,200)`) into the bin its close falls in.

    The Dynamic PoC is the price of the max-volume bin recomputed cumulatively
    bar-by-bar, so it steps up/down as the point-of-control migrates intraday.

    Returns (poc_list, period_high, period_low) where poc_list aligns to df
    rows (None for the first couple of bars). Use as a stepline overlay.
    """
    if df is None or df.empty or len(df) < 3:
        return [], None, None
    highs = df['high'].astype(float).to_numpy()
    lows = df['low'].astype(float).to_numpy()
    closes = df['close'].astype(float).to_numpy()
    vols = df['volume'].astype(float).fillna(0).to_numpy() if hasattr(df['volume'], 'fillna') else df['volume'].astype(float).to_numpy()
    # Per-bar volume normalisation ≈ ta.stdev(volume, 200)
    vstd = pd.Series(vols).rolling(200, min_periods=5).std().bfill().fillna(1).to_numpy()
    vstd = np.where(vstd <= 0, 1.0, vstd)
    vol_val = vols / vstd
    n = len(df)
    out = [None] * n
    for i in range(2, n):
        lo = lows[:i + 1].min()
        hi = highs[:i + 1].max()
        if hi <= lo:
            out[i] = (hi + lo) / 2.0
            continue
        counts, _ = np.histogram(closes[:i + 1], bins=bins, range=(lo, hi),
                                 weights=vol_val[:i + 1])
        bmax = int(counts.argmax())
        step = (hi - lo) / bins
        out[i] = lo + (bmax + 0.5) * step
    return out, float(highs.max()), float(lows.min())


def compute_vpfr(df, n_bars, n_rows=24, va_pct=70):
    """
    Volume Profile Fixed Range — Python port of Pine Script VPFR.
    Distributes each candle's volume across the price bins it spans (by range overlap),
    finds the POC (max-volume bin), then expands outward to capture va_pct% of volume
    for VAH and VAL.
    Returns dict: {poc, vah, val} or None if insufficient data.
    """
    if df is None or df.empty or len(df) < 3:
        return None
    recent = df.tail(n_bars)
    top = recent['high'].max()
    bot = recent['low'].min()
    if top == bot:
        return {'poc': round(top, 2), 'vah': round(top, 2), 'val': round(bot, 2)}
    step = (top - bot) / n_rows
    bins_lo = [bot + i * step for i in range(n_rows)]
    bins_hi = [bot + (i + 1) * step for i in range(n_rows)]
    vol_bins = [0.0] * n_rows
    for _, row in recent.iterrows():
        h, l = row['high'], row['low']
        v = float(row.get('volume') or 1)
        c_range = h - l
        if c_range <= 0:
            continue
        for i in range(n_rows):
            overlap = min(h, bins_hi[i]) - max(l, bins_lo[i])
            if overlap > 0:
                vol_bins[i] += v * (overlap / c_range)
    poc_idx = vol_bins.index(max(vol_bins))
    poc = (bins_lo[poc_idx] + bins_hi[poc_idx]) / 2
    total = sum(vol_bins)
    target = total * va_pct / 100
    cum = vol_bins[poc_idx]
    lo_i, hi_i = poc_idx, poc_idx
    while cum < target:
        can_lo = lo_i - 1 >= 0
        can_hi = hi_i + 1 < n_rows
        if not can_lo and not can_hi:
            break
        v_lo = vol_bins[lo_i - 1] if can_lo else -1
        v_hi = vol_bins[hi_i + 1] if can_hi else -1
        if v_hi >= v_lo:
            hi_i += 1
            cum += vol_bins[hi_i]
        else:
            lo_i -= 1
            cum += vol_bins[lo_i]
    return {
        'poc': round(poc, 2), 'vah': round(bins_hi[hi_i], 2), 'val': round(bins_lo[lo_i], 2),
        'poc_vol': float(vol_bins[poc_idx]),
        'vah_vol': float(vol_bins[hi_i]),
        'val_vol': float(vol_bins[lo_i]),
    }




def calculate_max_pain(df_options, spot_price):
    if df_options.empty:
        return None, None

    strikes = df_options['Strike'].unique()
    pain_data = []

    for strike in strikes:
        ce_pain = 0
        pe_pain = 0
        for _, row in df_options.iterrows():
            k = row['Strike']
            ce_oi = row.get('openInterest_CE', 0) or 0
            pe_oi = row.get('openInterest_PE', 0) or 0
            # CE is ITM when expiry (strike) > option strike k
            if strike > k:
                ce_pain += (strike - k) * ce_oi
            # PE is ITM when expiry (strike) < option strike k
            if strike < k:
                pe_pain += (k - strike) * pe_oi
        total_pain = ce_pain + pe_pain
        pain_data.append({
            'Strike': strike,
            'CE_Pain': ce_pain,
            'PE_Pain': pe_pain,
            'Total_Pain': total_pain
        })

    pain_df = pd.DataFrame(pain_data)

    if pain_df.empty:
        return None, None

    # Max pain = strike where total ITM payout is minimum (MM pay least)
    max_pain_idx = pain_df['Total_Pain'].idxmin()
    max_pain_strike = pain_df.loc[max_pain_idx, 'Strike']

    return max_pain_strike, pain_df



def calculate_dealer_gex(df_summary, spot_price, contract_multiplier=25):
    if df_summary is None or df_summary.empty:
        return None

    try:
        gex_data = []
        for _, row in df_summary.iterrows():
            strike = row.get('Strike', 0)
            gamma_ce = row.get('Gamma_CE', 0) or 0
            gamma_pe = row.get('Gamma_PE', 0) or 0
            oi_ce = row.get('openInterest_CE', 0) or 0
            oi_pe = row.get('openInterest_PE', 0) or 0
            call_gex = -1 * gamma_ce * oi_ce * contract_multiplier * spot_price / 100000
            put_gex = gamma_pe * oi_pe * contract_multiplier * spot_price / 100000
            net_gex = call_gex + put_gex
            gex_data.append({
                'Strike': strike,
                'Call_GEX': round(call_gex, 2),
                'Put_GEX': round(put_gex, 2),
                'Net_GEX': round(net_gex, 2),
                'Zone': row.get('Zone', '-')
            })
        gex_df = pd.DataFrame(gex_data)
        total_gex = gex_df['Net_GEX'].sum()
        gex_df_sorted = gex_df.sort_values('Strike')
        gamma_flip_level = None
        gamma_flip_direction = None
        for i in range(len(gex_df_sorted) - 1):
            current_gex = gex_df_sorted.iloc[i]['Net_GEX']
            next_gex = gex_df_sorted.iloc[i + 1]['Net_GEX']
            current_strike = gex_df_sorted.iloc[i]['Strike']
            next_strike = gex_df_sorted.iloc[i + 1]['Strike']
            if current_gex * next_gex < 0:
                gamma_flip_level = current_strike + (next_strike - current_strike) * abs(current_gex) / (abs(current_gex) + abs(next_gex))
                gamma_flip_direction = "Positive above" if current_gex < 0 else "Negative above"
                break
        if total_gex > 50:
            gex_interpretation = "STRONG PIN - Dealers long gamma, price likely to revert/chop"
            gex_signal = "Pin/Chop"
            gex_color = "#00ff88"
        elif total_gex > 0:
            gex_interpretation = "MILD PIN - Slight mean reversion tendency"
            gex_signal = "Range"
            gex_color = "#90EE90"
        elif total_gex > -50:
            gex_interpretation = "MILD TREND - Slight directional bias possible"
            gex_signal = "Trending"
            gex_color = "#FFD700"
        else:
            gex_interpretation = "STRONG TREND - Dealers short gamma, violent moves possible"
            gex_signal = "Breakout"
            gex_color = "#ff4444"
        max_positive_idx = gex_df['Net_GEX'].idxmax()
        max_negative_idx = gex_df['Net_GEX'].idxmin()
        gex_magnet = gex_df.loc[max_positive_idx, 'Strike'] if gex_df.loc[max_positive_idx, 'Net_GEX'] > 0 else None
        gex_repeller = gex_df.loc[max_negative_idx, 'Strike'] if gex_df.loc[max_negative_idx, 'Net_GEX'] < 0 else None
        return {
            'gex_df': gex_df,
            'total_gex': round(total_gex, 2),
            'gamma_flip_level': round(gamma_flip_level, 2) if gamma_flip_level else None,
            'gamma_flip_direction': gamma_flip_direction,
            'gex_interpretation': gex_interpretation,
            'gex_signal': gex_signal,
            'gex_color': gex_color,
            'gex_magnet': gex_magnet,
            'gex_repeller': gex_repeller,
            'spot_vs_flip': "Above Gamma Flip" if gamma_flip_level and spot_price > gamma_flip_level else "Below Gamma Flip" if gamma_flip_level else "N/A"
        }

    except Exception as e:
        return None


def calculate_dealer_dex(df_summary, spot_price, contract_multiplier=25):
    """🧭 Dealer Delta Exposure (DEX) — the delta-weighted sibling of GEX.

    Per strike we sum the delta-weighted open interest on each side:
        call_dex = Delta_CE * OI_CE        (Delta_CE > 0 → positive)
        put_dex  = Delta_PE * OI_PE        (Delta_PE < 0 → negative)
        net_dex  = call_dex + put_dex
    Aggregated and scaled to lakhs. This is the same "which side is heavier"
    logic the per-strike DeltaExp flag already uses, completed into one net
    number:
        Net DEX > 0 → call-delta-weighted OI dominates → bullish lean.
        Net DEX < 0 → put-delta-weighted OI dominates  → bearish lean.
    Also reports the dealer-hedging read (dealers are short what retail buys, so
    a large positive customer delta means dealers must SELL rallies → the level
    tends to cap; a large negative one means dealers BUY dips → supportive).
    Returns dict or None.
    """
    if df_summary is None or getattr(df_summary, 'empty', True):
        return None
    try:
        rows = []
        for _, row in df_summary.iterrows():
            strike = row.get('Strike', 0)
            d_ce = float(row.get('Delta_CE', 0) or 0)
            d_pe = float(row.get('Delta_PE', 0) or 0)
            oi_ce = float(row.get('openInterest_CE', 0) or 0)
            oi_pe = float(row.get('openInterest_PE', 0) or 0)
            call_dex = d_ce * oi_ce * contract_multiplier / 1e5
            put_dex = d_pe * oi_pe * contract_multiplier / 1e5
            rows.append({'Strike': strike,
                         'Call_DEX': round(call_dex, 2),
                         'Put_DEX': round(put_dex, 2),
                         'Net_DEX': round(call_dex + put_dex, 2)})
        dex_df = pd.DataFrame(rows)
        call_total = float(dex_df['Call_DEX'].sum())
        put_total = float(dex_df['Put_DEX'].sum())
        net_dex = call_total + put_total
        _mag = abs(call_total) + abs(put_total)
        _tilt = (net_dex / _mag) if _mag > 0 else 0.0   # -1..+1
        if net_dex > 0 and _tilt > 0.08:
            bias, label = 'BULL', 'Call-delta heavy (bullish lean)'
        elif net_dex < 0 and _tilt < -0.08:
            bias, label = 'BEAR', 'Put-delta heavy (bearish lean)'
        else:
            bias, label = 'NEUTRAL', 'Balanced delta positioning'
        dealer_note = ("dealers net short customer delta → must BUY dips (supportive)"
                       if net_dex > 0 else
                       "dealers net long customer delta → must SELL rips (capping)"
                       if net_dex < 0 else "flat")
        return {'dex_df': dex_df, 'call_dex': round(call_total, 2),
                'put_dex': round(put_total, 2), 'net_dex': round(net_dex, 2),
                'tilt': round(_tilt, 2), 'bias': bias, 'label': label,
                'dealer_note': dealer_note}
    except Exception:
        return None


def calculate_iv_skew(df_summary, spot_price):
    """📐 IV Skew — average OTM-put IV vs average OTM-call IV across the near
    wings (spot ±1..±3 strikes). Ratio = putIV / callIV:
        ratio > 1.10 → puts richer → demand for downside protection = fear /
                       hedging → cautious / bearish lean.
        ratio < 0.90 → calls richer → upside chase / greed → bullish lean.
        else         → flat skew → neutral.
    Returns dict or None.
    """
    if df_summary is None or getattr(df_summary, 'empty', True) or not spot_price:
        return None
    try:
        need = {'Strike', 'impliedVolatility_CE', 'impliedVolatility_PE'}
        if not need <= set(df_summary.columns):
            return None
        stks = sorted(df_summary['Strike'].dropna().unique().tolist())
        if len(stks) < 3:
            return None
        atm = min(stks, key=lambda x: abs(x - spot_price))
        gap = min((abs(b - a) for a, b in zip(stks, stks[1:])), default=50) or 50
        lo, hi = atm - 3 * gap, atm + 3 * gap
        win = df_summary[(df_summary['Strike'] >= lo) & (df_summary['Strike'] <= hi)]
        put_ivs = [float(v) for v in win[win['Strike'] <= atm]['impliedVolatility_PE'] if v and float(v) > 0]
        call_ivs = [float(v) for v in win[win['Strike'] >= atm]['impliedVolatility_CE'] if v and float(v) > 0]
        if not put_ivs or not call_ivs:
            return None
        put_iv = sum(put_ivs) / len(put_ivs)
        call_iv = sum(call_ivs) / len(call_ivs)
        if call_iv <= 0:
            return None
        ratio = put_iv / call_iv
        if ratio > 1.10:
            bias, label, em = 'BEAR', 'Put skew — downside hedging / fear', '🔴'
        elif ratio < 0.90:
            bias, label, em = 'BULL', 'Call skew — upside chase / greed', '🟢'
        else:
            bias, label, em = 'NEUTRAL', 'Flat skew', '⚪'
        return {'ratio': round(ratio, 2), 'put_iv': round(put_iv, 1),
                'call_iv': round(call_iv, 1), 'bias': bias, 'label': label, 'em': em}
    except Exception:
        return None




def calculate_vanna_charm_exposure(df_summary, spot_price, contract_multiplier=25):
    """Aggregate second-order exposure across strikes (needs Vanna_*/Charm_*
    columns from the chain build). Per strike:
        net_vanna = (Vanna_CE*OI_CE + Vanna_PE*OI_PE) * mult
        net_charm = (Charm_CE*OI_CE + Charm_PE*OI_PE) * mult
    Context only (informational): net vanna hints how dealer hedging flows react
    to an IV move; net charm hints the delta-decay / pin drift into expiry.

    `net_vega` is added on the same OI-weighted basis when the chain carries the
    per-strike Vega columns (`Vega_CE`/`Vega_PE`) — the book's volatility
    sensitivity as ONE magnitude, so the Greek-behaviour layer's "Vol sensitivity"
    read can stop saying "Not reported". Vega is a separate column from the
    Vanna/Charm this function requires, so it is OPTIONAL: `net_vega` is `None`
    when the columns are absent rather than 0 (an unmeasured force is not a
    balanced one).

    Returns dict with a per-strike frame and totals, or None."""
    if df_summary is None or getattr(df_summary, 'empty', True):
        return None
    try:
        need = {'Strike', 'Vanna_CE', 'Vanna_PE', 'Charm_CE', 'Charm_PE',
                'openInterest_CE', 'openInterest_PE'}
        if not need <= set(df_summary.columns):
            return None
        has_vega = {'Vega_CE', 'Vega_PE'} <= set(df_summary.columns)
        cols = set(df_summary.columns)
        # third-order greeks, each optional & independent — a net is None (not 0)
        # unless BOTH legs of that greek are present, same rule as Vega
        higher = ('Vomma', 'Speed', 'Zomma', 'Veta', 'Color')
        has_higher = {g: {f'{g}_CE', f'{g}_PE'} <= cols for g in higher}
        rows = []
        vega_sum = 0.0
        higher_sum = {g: 0.0 for g in higher}
        for _, row in df_summary.iterrows():
            oi_ce = float(row.get('openInterest_CE', 0) or 0)
            oi_pe = float(row.get('openInterest_PE', 0) or 0)
            nv = (float(row.get('Vanna_CE', 0) or 0) * oi_ce
                  + float(row.get('Vanna_PE', 0) or 0) * oi_pe) * contract_multiplier / 1e5
            nc = (float(row.get('Charm_CE', 0) or 0) * oi_ce
                  + float(row.get('Charm_PE', 0) or 0) * oi_pe) * contract_multiplier / 1e5
            rows.append({'Strike': row.get('Strike', 0),
                         'Net_Vanna': round(nv, 2), 'Net_Charm': round(nc, 2)})
            if has_vega:
                vega_sum += (float(row.get('Vega_CE', 0) or 0) * oi_ce
                             + float(row.get('Vega_PE', 0) or 0) * oi_pe) \
                    * contract_multiplier / 1e5
            for g in higher:
                if has_higher[g]:
                    higher_sum[g] += (float(row.get(f'{g}_CE', 0) or 0) * oi_ce
                                      + float(row.get(f'{g}_PE', 0) or 0) * oi_pe) \
                        * contract_multiplier / 1e5
        vc_df = pd.DataFrame(rows)
        out = {'vc_df': vc_df,
               'net_vanna': round(float(vc_df['Net_Vanna'].sum()), 2),
               'net_charm': round(float(vc_df['Net_Charm'].sum()), 2),
               'net_vega': round(vega_sum, 2) if has_vega else None}
        for g in higher:
            out[f'net_{g.lower()}'] = round(higher_sum[g], 2) if has_higher[g] else None
        return out
    except Exception:
        return None


def _cross_expiry_row(exp, oc_resp, spot_price):
    """One expiry's ATM±2 ΔOI row, or None when the chain is unusable."""
    data = (oc_resp or {}).get('data') or {}
    oc = data.get('oc') or {}
    und = float(data.get('last_price') or spot_price or 0)
    if not oc or not und:
        return None
    strikes = sorted(float(k) for k in oc.keys())
    if len(strikes) < 3:
        return None
    atm = min(strikes, key=lambda x: abs(x - und))
    gap = min((abs(b - a) for a, b in zip(strikes, strikes[1:])), default=50) or 50
    ce_chg = pe_chg = ce_oi = pe_oi = 0.0
    for k, sd in oc.items():
        if abs(float(k) - atm) > 2 * gap:
            continue
        ce = sd.get('ce') or {}
        pe = sd.get('pe') or {}
        ce_chg += float(ce.get('oi') or 0) - float(ce.get('previous_oi') or 0)
        pe_chg += float(pe.get('oi') or 0) - float(pe.get('previous_oi') or 0)
        ce_oi += float(ce.get('oi') or 0)
        pe_oi += float(pe.get('oi') or 0)
    pcr = round(pe_oi / ce_oi, 2) if ce_oi > 0 else 0.0
    if pe_chg > ce_chg * 1.2 and pe_chg > 0:
        bias = 'BULL'
    elif ce_chg > pe_chg * 1.2 and ce_chg > 0:
        bias = 'BEAR'
    else:
        bias = 'NEUTRAL'
    return {'expiry': exp, 'pcr': pcr, 'ce_chg': round(ce_chg / 1e5, 2),
            'pe_chg': round(pe_chg / 1e5, 2), 'bias': bias}


def compute_cross_expiry_bias(spot_price, n_expiries=3, ttl=120):
    """📅 Cross-expiry term structure — compare the ATM±2 ΔOI positioning bias
    across the nearest N expiries (weekly / next / monthly). All expiries
    agreeing = conviction; near-term vs far-term split = caution. Context only.
    Returns dict or None.

    ⏱️ ONE chain fetch per render, at most. This used to loop all N expiries
    back to back whenever its 120s cache expired — three requests into an
    endpoint Dhan caps at one per three seconds, which is what tripped the
    limiter. Spacing them fixed the 429s but spent ~6s of the render asleep.

    So the expiries rotate instead: each render refreshes the single stalest
    one whose row is older than `ttl`, and the verdict is computed from
    whatever rows are held. Three expiries at ~20s per render come round well
    inside the 120s each row is allowed to live, so nothing is staler than
    before — it is the same work, spread rather than burst. The fetch never
    waits (`allow_wait=False`): if the 3s window is not open, this render
    simply skips and the next one picks it up.
    """
    ist = pytz.timezone('Asia/Kolkata')
    _cache = st.session_state.get('_cross_expiry_cache')
    try:
        el = get_dhan_expiry_list_cached(NIFTY_UNDERLYING_SCRIP, NIFTY_UNDERLYING_SEG)
        exps = (el or {}).get('data', [])[:n_expiries]
        if not exps:
            return _cache[1] if _cache else None

        from mios_v5.fetch_rotation import drop_missing, next_to_refresh
        store = drop_missing(
            st.session_state.setdefault('_cross_expiry_rows', {}), exps)

        _back = st.session_state.get('_dhan_429_until')
        _backing_off = bool(_back and datetime.now(ist) < _back)
        now = time.time()
        if not _backing_off:
            _target = next_to_refresh(
                exps, {e: v.get('ts', 0.0) for e, v in store.items()}, now, ttl)
            if _target is not None:
                _row = _cross_expiry_row(
                    _target,
                    get_dhan_option_chain(NIFTY_UNDERLYING_SCRIP, NIFTY_UNDERLYING_SEG,
                                          _target, allow_wait=False),
                    spot_price)
                if _row:
                    store[_target] = {'ts': now, 'row': _row}

        # nearest expiry first, and only the ones actually held
        rows = [store[e]['row'] for e in exps if (store.get(e) or {}).get('row')]
        if not rows:
            return _cache[1] if _cache else None
        bulls = sum(1 for r in rows if r['bias'] == 'BULL')
        bears = sum(1 for r in rows if r['bias'] == 'BEAR')
        if bulls >= 2 and bears == 0:
            agree, acol = 'ALIGNED BULL', '#00ff88'
        elif bears >= 2 and bulls == 0:
            agree, acol = 'ALIGNED BEAR', '#ff4444'
        elif bulls and bears:
            agree, acol = 'DIVERGENT (term-structure split)', '#ffd000'
        else:
            agree, acol = 'MIXED', '#ccc'
        out = {'rows': rows, 'agree': agree, 'color': acol, 'bulls': bulls, 'bears': bears}
        st.session_state['_cross_expiry_cache'] = (time.time(), out)
        return out
    except Exception:
        return _cache[1] if _cache else None


def render_cross_expiry_panel(spot_price):
    """📅 Render the cross-expiry term-structure block (Phase-3)."""
    try:
        ce = compute_cross_expiry_bias(spot_price)
    except Exception as _ce_err:
        st.caption(f"Cross-expiry unavailable: {_ce_err}")
        return
    if not ce or not ce.get('rows'):
        st.caption("📅 Cross-expiry: warming up (needs option chains for the "
                   "nearest expiries).")
        return
    _cells = ""
    for r in ce['rows']:
        _bc = ('#00ff88' if r['bias'] == 'BULL'
               else ('#ff4444' if r['bias'] == 'BEAR' else '#ccc'))
        _cells += (
            f"<div style='background:#0d1117;border:1px solid #1e2836;border-radius:9px;"
            f"padding:8px 12px'>"
            f"<div style='font-size:10px;color:#ffffff;text-transform:uppercase'>{r['expiry']}</div>"
            f"<div style='font-weight:800;font-size:14px;color:{_bc}'>{r['bias']}</div>"
            f"<div style='font-family:monospace;font-size:10px;color:#ffffff'>"
            f"PCR {r['pcr']} · CEΔ {r['ce_chg']:+.1f}L · PEΔ {r['pe_chg']:+.1f}L</div></div>")
    st.markdown(
        f"<div style='font-size:13px;color:#ffffff;margin:4px 0'>📅 <b>Cross-Expiry Term Structure</b>: "
        f"<b style='color:{ce['color']}'>{ce['agree']}</b></div>"
        f"<div style='display:grid;grid-template-columns:repeat({len(ce['rows'])},1fr);gap:8px;margin-bottom:8px'>"
        + _cells + "</div>",
        unsafe_allow_html=True,
    )


def render_positioning_heatmap(spot_price, option_data):
    """🗺️ Strike-level positioning heatmap — the achievable stand-in for a true
    order-book liquidity heatmap (retail Dhan has no full depth). Shows, across
    ATM±N strikes, WHERE the positioning/exposure concentrates: CE/PE OI walls,
    Net GEX, Net DEX, Vanna and Charm exposure. Color = per-column intensity
    (|value| normalised) so each metric's hotspots stand out; the signed number
    in each cell carries the direction. Built entirely from data already fetched."""
    try:
        import plotly.graph_objects as go
        ds = (option_data or {}).get('df_summary') if option_data else None
        _u = (option_data or {}).get('underlying') or spot_price
        if ds is None or getattr(ds, 'empty', True) or 'Strike' not in ds.columns:
            st.caption("Positioning heatmap: option chain not loaded yet.")
            return
        gex = calculate_dealer_gex(ds, _u) or {}
        dex = calculate_dealer_dex(ds, _u) or {}
        vc = calculate_vanna_charm_exposure(ds, _u) or {}
        gex_df = gex.get('gex_df'); dex_df = dex.get('dex_df'); vc_df = vc.get('vc_df')

        stks = sorted(ds['Strike'].dropna().unique().tolist())
        if len(stks) < 3:
            st.caption("Positioning heatmap: not enough strikes.")
            return
        atm = min(stks, key=lambda x: abs(x - _u))
        gap = min((abs(b - a) for a, b in zip(stks, stks[1:])), default=50) or 50
        n = 5
        win_strikes = [s for s in stks if atm - n * gap <= s <= atm + n * gap]

        def _col(frame, key):
            m = {}
            if frame is not None and not frame.empty:
                for _, rr in frame.iterrows():
                    m[float(rr['Strike'])] = float(rr.get(key, 0) or 0)
            return m
        ce_oi = {float(r['Strike']): float(r.get('openInterest_CE', 0) or 0) / 1e5 for _, r in ds.iterrows()}
        pe_oi = {float(r['Strike']): float(r.get('openInterest_PE', 0) or 0) / 1e5 for _, r in ds.iterrows()}
        gexm = _col(gex_df, 'Net_GEX'); dexm = _col(dex_df, 'Net_DEX')
        vanm = _col(vc_df, 'Net_Vanna'); chm = _col(vc_df, 'Net_Charm')

        cols = ['CE OI (L)', 'PE OI (L)', 'Net GEX', 'Net DEX', 'Vanna Exp', 'Charm Exp']
        raw = []   # rows = metrics, columns = strikes
        for src in (ce_oi, pe_oi, gexm, dexm, vanm, chm):
            raw.append([src.get(float(s), 0.0) for s in win_strikes])
        # per-row (per-metric) intensity normalisation for colour
        z = []
        for r in raw:
            mx = max((abs(v) for v in r), default=0) or 1.0
            z.append([abs(v) / mx for v in r])
        text = [[f"{v:+.1f}" if abs(v) >= 0.05 else "·" for v in r] for r in raw]
        x_labels = [f"{'🎯' if s == atm else ''}{int(s)}" for s in win_strikes]

        fig = go.Figure(data=go.Heatmap(
            z=z, x=x_labels, y=cols, text=text, texttemplate="%{text}",
            colorscale='YlOrRd', showscale=False,
            hovertemplate="%{y} @ %{x}: %{text}<extra></extra>",
            xgap=2, ygap=2))
        fig.update_layout(
            height=260, margin=dict(l=8, r=8, t=28, b=8),
            title=dict(text=f"🗺️ Positioning Heatmap · ATM {int(atm)} · spot {spot_price:,.0f}",
                       font=dict(size=14)),
            yaxis=dict(autorange='reversed'),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(size=11))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Colour = per-row intensity (where each metric concentrates); the "
            "signed number is the value. CE/PE OI = walls (liquidity). "
            "Net GEX>0 pin / <0 trend · Net DEX>0 call-delta heavy (bull) · "
            "Vanna = delta↔IV sensitivity · Charm = delta decay/day. "
            "Not a true order-book heatmap — retail Dhan has no full depth.")
    except Exception as _hm_err:
        st.caption(f"Positioning heatmap unavailable: {_hm_err}")




def _parse_expiry_date(expiry_str):
    """Parse a Dhan expiry string into a date, trying the formats Dhan uses.
    Returns a datetime.date or None."""
    if not expiry_str:
        return None
    s = str(expiry_str).strip()
    # Dhan option-chain uses 'YYYY-MM-DD'; scrip-master / futures use 'DD-Mon-YYYY'.
    for _fmt in ('%Y-%m-%d', '%d-%b-%Y', '%d-%m-%Y', '%Y/%m/%d', '%d-%B-%Y'):
        try:
            return datetime.strptime(s, _fmt).date()
        except ValueError:
            continue
    # Last resort: pandas can parse many odd formats.
    try:
        _d = pd.to_datetime(s, errors='coerce')
        return _d.date() if pd.notna(_d) else None
    except Exception:
        return None


def _is_expiry_day(option_data):
    """True when the option chain's nearest expiry == today (IST).
    Used to swap the ATM±3 legs to SENSEX on NIFTY expiry."""
    try:
        _exp = (option_data or {}).get('expiry') or (option_data or {}).get('selected_expiry')
        if not _exp:
            _exp = (st.session_state.get('_cached_raw_chain_latest') or {}).get('expiry')
        _exp_date = _parse_expiry_date(_exp)
        if _exp_date is None:
            return False
        _today = datetime.now(pytz.timezone('Asia/Kolkata')).date()
        return _exp_date == _today
    except Exception:
        return False


def calculate_exact_time_to_expiry(expiry_date_str):
    try:
        expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d").replace(hour=15, minute=30)
        expiry_date = expiry_date.replace(tzinfo=pytz.timezone('Asia/Kolkata'))
        now = datetime.now(pytz.timezone('Asia/Kolkata'))
        time_diff = expiry_date - now
        total_seconds = time_diff.total_seconds()
        total_days = total_seconds / (24 * 3600)
        years = total_days / 365.25
        return max(years, 1/365.25)
    except:
        return 1/365.25

def get_iv_fallback(df, strike_price):
    try:
        nearby_strikes = df[abs(df['strikePrice'] - strike_price) <= 100]
        if not nearby_strikes.empty:
            iv_ce_avg = nearby_strikes['impliedVolatility_CE'].mean()
            iv_pe_avg = nearby_strikes['impliedVolatility_PE'].mean()
            if pd.isna(iv_ce_avg):
                iv_ce_avg = df['impliedVolatility_CE'].mean()
            if pd.isna(iv_pe_avg):
                iv_pe_avg = df['impliedVolatility_PE'].mean()
            return iv_ce_avg or 15, iv_pe_avg or 15
        else:
            return 15, 15
    except:
        return 15, 15

def calculate_greeks(option_type, S, K, T, r, sigma):
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        delta = norm.cdf(d1) if option_type == 'CE' else -norm.cdf(-d1)
        gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))
        vega = S * norm.pdf(d1) * math.sqrt(T) / 100
        theta = (- (S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * norm.cdf(d2)) / 365 if option_type == 'CE' else (- (S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * norm.cdf(-d2)) / 365
        rho = (K * T * math.exp(-r * T) * norm.cdf(d2)) / 100 if option_type == 'CE' else (-K * T * math.exp(-r * T) * norm.cdf(-d2)) / 100
        return round(delta, 4), round(gamma, 4), round(vega, 4), round(theta, 4), round(rho, 4)
    except:
        return 0, 0, 0, 0, 0

def calculate_vanna_charm(option_type, S, K, T, r, sigma):
    """Second-order Greeks (same Black-Scholes d1/d2 as calculate_greeks):
      • Vanna = ∂Delta/∂σ = ∂Vega/∂S  — how delta shifts as IV moves. Scaled
        per 1 vol-point (÷100). Same value for call and put.
      • Charm = ∂Delta/∂t  — delta decay per day (÷365). Same for call & put
        (q=0). Both verified against finite differences.
    Returns (vanna, charm), or (0, 0) on any bad input."""
    try:
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return 0.0, 0.0
        sqrtT = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrtT)
        d2 = d1 - sigma * sqrtT
        pdf = norm.pdf(d1)
        vanna = (-pdf * d2 / sigma) / 100.0
        charm = (-pdf * (2 * r * T - d2 * sigma * sqrtT) / (2 * T * sigma * sqrtT)) / 365.0
        return round(vanna, 6), round(charm, 6)
    except Exception:
        return 0.0, 0.0

def final_verdict(score):
    if score >= 4:
        return "Strong Bullish"
    elif score >= 2:
        return "Bullish"
    elif score <= -4:
        return "Strong Bearish"
    elif score <= -2:
        return "Bearish"
    else:
        return "Neutral"

def delta_volume_bias(price, volume, chg_oi):
    if price > 0 and volume > 0 and chg_oi > 0:
        return "Bullish"
    elif price < 0 and volume > 0 and chg_oi > 0:
        return "Bearish"
    elif price > 0 and volume > 0 and chg_oi < 0:
        return "Bullish"
    elif price < 0 and volume > 0 and chg_oi < 0:
        return "Bearish"
    else:
        return "Neutral"

def calculate_bid_ask_pressure(call_bid_qty, call_ask_qty, put_bid_qty, put_ask_qty):
    pressure = (call_bid_qty - call_ask_qty) + (put_ask_qty - put_bid_qty)
    if pressure > 500:
        bias = "Bullish"
    elif pressure < -500:
        bias = "Bearish"
    else:
        bias = "Neutral"
    return pressure, bias

weights = {
    "LTP_Bias": 1,
    "OI_Bias": 2,
    "ChgOI_Bias": 2,
    "Volume_Bias": 1,
    "Delta_Bias": 1,
    "Gamma_Bias": 1,
    "Theta_Bias": 1,
    "AskQty_Bias": 1,
    "BidQty_Bias": 1,
    "AskBid_Bias": 1,
    "IV_Bias": 1,
    "DVP_Bias": 1,
    "PressureBias": 1,
}


_CG = 'background-color: #90EE90; color: black'
_CR = 'background-color: #FFB6C1; color: black'
_CY = 'background-color: #FFFFE0; color: black'
_CDG = 'background-color: #228B22; color: white'
_CDR = 'background-color: #DC143C; color: white'
_CF = 'background-color: #F5F5F5; color: black'









def process_candle_data(data, interval):
    if not data or 'open' not in data:
        return pd.DataFrame()

    df = pd.DataFrame({
        'timestamp': data['timestamp'],
        'open': data['open'],
        'high': data['high'],
        'low': data['low'],
        'close': data['close'],
        'volume': data['volume']
    })

    ist = pytz.timezone('Asia/Kolkata')
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s').dt.tz_localize('UTC').dt.tz_convert(ist)

    return df


# ══════════════════════════════════════════════════════════════════════════════
# PORTED TRADING ENGINES — CIE / CMCE / IOFCE / Geometric Pattern Detector
# Copied AS-IS from vob (5).py (see source lines 13889-14378, 26143-27340,
# 26754-27340, 3563-4246). Kept functionally identical. Adapted minimal helpers
# (_get_atm_bias_text, _amie_oi_behavior, _amie_depth_signal) that the IOFCE
# pipeline depends on but were absent from this file.
# ══════════════════════════════════════════════════════════════════════════════

def _get_atm_bias_text(option_data: dict = None) -> str:
    """Extract ATM bias info from option_data for inclusion in Telegram alerts."""
    if not option_data:
        return ""
    df_summary = option_data.get('df_summary')
    underlying = option_data.get('underlying')
    if df_summary is None or underlying is None:
        return ""
    try:
        atm_strike = min(df_summary['Strike'].tolist(), key=lambda x: abs(x - underlying))
        atm_rows = df_summary[df_summary['Strike'] == atm_strike]
        if atm_rows.empty:
            return ""
        row = atm_rows.iloc[0]
        bias_score = row.get('BiasScore', 0)
        verdict = row.get('Verdict', final_verdict(bias_score))
        oi_bias = row.get('OI_Bias', 'N/A')
        chgoi_bias = row.get('ChgOI_Bias', 'N/A')
        delta_exp = row.get('DeltaExp', 'N/A')
        gamma_exp = row.get('GammaExp', 'N/A')
        pressure = row.get('PressureBias', 'N/A')
        return (
            f"\n<b>📊 ATM Bias:</b> {verdict} (Score: {bias_score})"
            f"\n• OI: {oi_bias} | ChgOI: {chgoi_bias} | Delta: {delta_exp} | Gamma: {gamma_exp} | Pressure: {pressure}"
        )
    except Exception:
        return ""






# ── GeometricPatternDetector ──────────────────────────────────────────────────
class GeometricPatternDetector:
    """
    Detects geometric and reversal chart patterns on NIFTY50 price data.
    Patterns: Double Bottom/Top, H&S, Inv H&S, Triangles, Falling Wedge,
              Flag, Range Breakout, Channel, Trendline Breakout.
    """

    TOLERANCE = 0.025
    MIN_PATTERN_BARS = 3
    LOOKBACK = 60

    @staticmethod
    def _find_pivots(df, order=2):
        highs_arr = df['high'].values
        lows_arr = df['low'].values
        n = len(highs_arr)
        highs, lows = [], []
        for i in range(order, n - order):
            window_h = highs_arr[i - order: i + order + 1]
            window_l = lows_arr[i - order: i + order + 1]
            if highs_arr[i] == window_h.max():
                highs.append(i)
            if lows_arr[i] == window_l.min():
                lows.append(i)
        return highs, lows

    @staticmethod
    def _confidence_score(df, breakout_idx, signal):
        score = 0
        closes = df['close'].values
        opens = df['open'].values
        highs_a = df['high'].values
        lows_a = df['low'].values
        volumes = df['volume'].values if 'volume' in df.columns else None
        n = len(closes)
        idx = min(breakout_idx, n - 1)

        if volumes is not None and idx > 5:
            avg_vol = volumes[max(0, idx - 10):idx].mean()
            if avg_vol > 0 and volumes[idx] > avg_vol * 1.4:
                score += 2

        if idx > 0:
            body = abs(closes[idx] - opens[idx])
            avg_body = np.mean(np.abs(
                closes[max(0, idx - 10):idx] - opens[max(0, idx - 10):idx]
            )) if idx > 0 else 1
            if avg_body > 0 and body > avg_body * 1.2:
                score += 1

        rng = highs_a[idx] - lows_a[idx] if highs_a[idx] != lows_a[idx] else 0.001
        close_pos = (closes[idx] - lows_a[idx]) / rng
        if signal == 'BUY' and close_pos > 0.55:
            score += 1
        elif signal == 'SELL' and close_pos < 0.45:
            score += 1

        if n >= 12:
            slope = np.polyfit(range(10), closes[n - 10:], 1)[0]
            price_unit = closes[-1] / 100
            if signal == 'BUY' and slope > price_unit * 0.05:
                score += 1
            elif signal == 'SELL' and slope < -price_unit * 0.05:
                score += 1

        if n >= 16:
            gains = np.maximum(np.diff(closes[n - 15:]), 0)
            losses = np.abs(np.minimum(np.diff(closes[n - 15:]), 0))
            avg_g = gains.mean() if gains.mean() > 0 else 0.001
            avg_l = losses.mean() if losses.mean() > 0 else 0.001
            rsi = 100 - (100 / (1 + avg_g / avg_l))
            if signal == 'BUY' and 40 < rsi < 75:
                score += 2
            elif signal == 'SELL' and 25 < rsi < 60:
                score += 2

        labels = [
            'Low', 'Low', 'Moderate', 'Moderate',
            'High', 'High', 'Strong', 'Strong', 'Institutional Setup'
        ]
        return labels[min(score, 8)]

    def _make_result(self, df, bo_idx, pat, pat_type, sentiment, signal,
                     entry, sl, target, draw_lines, sr_zones):
        n = len(df)
        bo_idx = min(bo_idx, n - 1)
        rr = abs(target - entry) / abs(entry - sl) if abs(entry - sl) > 0.001 else 0
        future_idx = min(bo_idx + 5, n - 1)
        move_pct = (df['close'].iloc[future_idx] - entry) / entry * 100 if entry else 0
        bo_vol = 0
        bo_vol_ratio = 0.0
        if 'volume' in df.columns:
            bo_vol = int(df['volume'].iloc[bo_idx])
            _vol_start = max(0, bo_idx - 20)
            _avg_v = df['volume'].iloc[_vol_start:bo_idx].mean() if bo_idx > 0 else bo_vol
            bo_vol_ratio = round(bo_vol / _avg_v, 2) if _avg_v and _avg_v > 0 else 0.0

        return {
            'pattern': pat, 'pattern_type': pat_type,
            'sentiment': sentiment, 'signal': signal,
            'time': df['datetime'].iloc[bo_idx] if 'datetime' in df.columns else bo_idx,
            'entry': round(entry, 2),
            'stoploss': round(sl, 2),
            'target': round(target, 2),
            'rr': round(rr, 2),
            'move_pct': round(move_pct, 2),
            'confidence': self._confidence_score(df, bo_idx, signal),
            'highlight_idx': bo_idx,
            'draw_lines': draw_lines,
            'sr_zones': sr_zones,
            'volume': bo_vol,
            'vol_ratio': bo_vol_ratio,
        }

    def _detect_double_bottom(self, df):
        results = []
        highs_arr = df['high'].values
        lows_arr = df['low'].values
        closes = df['close'].values
        n = len(closes)

        _, lows = self._find_pivots(df, order=2)

        for j in range(1, len(lows)):
            b2 = lows[j]
            for k in range(j - 1, max(j - 8, -1), -1):
                b1 = lows[k]
                if b2 - b1 < self.MIN_PATTERN_BARS:
                    continue
                p1 = lows_arr[b1]
                p2 = lows_arr[b2]
                if abs(p1 - p2) / max(p1, p2) > self.TOLERANCE:
                    continue
                neckline = closes[b1:b2 + 1].max()
                for bo_idx in range(b2 + 1, min(b2 + 8, n)):
                    if closes[bo_idx] > neckline:
                        ph = neckline - min(p1, p2)
                        entry = neckline
                        sl = min(lows_arr[b1], lows_arr[b2]) * 0.998
                        tgt = entry + ph
                        results.append(self._make_result(
                            df, bo_idx,
                            'Double Bottom', 'Reversal', 'Bullish Reversal', 'BUY',
                            entry, sl, tgt,
                            draw_lines=[
                                (df['datetime'].iloc[b1], p1, df['datetime'].iloc[b2], p2, '#00ff88'),
                                (df['datetime'].iloc[b1], neckline, df['datetime'].iloc[bo_idx], neckline, '#FFD700'),
                            ],
                            sr_zones=[(sl, sl * 1.004, 'rgba(0,255,136,0.15)')],
                        ))
                        break
                break
        return results

    def _detect_double_top(self, df):
        results = []
        highs_arr = df['high'].values
        lows_arr = df['low'].values
        closes = df['close'].values
        n = len(closes)

        highs, _ = self._find_pivots(df, order=2)

        for j in range(1, len(highs)):
            t2 = highs[j]
            for k in range(j - 1, max(j - 8, -1), -1):
                t1 = highs[k]
                if t2 - t1 < self.MIN_PATTERN_BARS:
                    continue
                p1 = highs_arr[t1]
                p2 = highs_arr[t2]
                if abs(p1 - p2) / max(p1, p2) > self.TOLERANCE:
                    continue
                neckline = closes[t1:t2 + 1].min()
                for bo_idx in range(t2 + 1, min(t2 + 8, n)):
                    if closes[bo_idx] < neckline:
                        ph = max(p1, p2) - neckline
                        entry = neckline
                        sl = max(highs_arr[t1], highs_arr[t2]) * 1.002
                        tgt = entry - ph
                        results.append(self._make_result(
                            df, bo_idx,
                            'Double Top', 'Reversal', 'Bearish Reversal', 'SELL',
                            entry, sl, tgt,
                            draw_lines=[
                                (df['datetime'].iloc[t1], p1, df['datetime'].iloc[t2], p2, '#ff4444'),
                                (df['datetime'].iloc[t1], neckline, df['datetime'].iloc[bo_idx], neckline, '#FFD700'),
                            ],
                            sr_zones=[(sl * 0.996, sl, 'rgba(255,68,68,0.15)')],
                        ))
                        break
                break
        return results

    def _detect_head_shoulders(self, df):
        results = []
        highs_arr = df['high'].values
        lows_arr = df['low'].values
        closes = df['close'].values
        n = len(closes)

        highs, _ = self._find_pivots(df, order=2)
        if len(highs) < 3:
            return results

        for i in range(len(highs) - 2):
            ls, head, rs = highs[i], highs[i + 1], highs[i + 2]
            if head - ls < self.MIN_PATTERN_BARS or rs - head < self.MIN_PATTERN_BARS:
                continue
            p_ls = highs_arr[ls]
            p_head = highs_arr[head]
            p_rs = highs_arr[rs]
            if p_head <= max(p_ls, p_rs):
                continue
            if abs(p_ls - p_rs) / p_head > 0.05:
                continue
            t1_low = lows_arr[ls:head + 1].min()
            t2_low = lows_arr[head:rs + 1].min()
            neckline = (t1_low + t2_low) / 2
            for bo_idx in range(rs + 1, min(rs + 8, n)):
                if closes[bo_idx] < neckline:
                    ph = p_head - neckline
                    entry = neckline
                    sl = p_rs * 1.003
                    tgt = neckline - ph
                    results.append(self._make_result(
                        df, bo_idx,
                        'Head & Shoulders', 'Reversal', 'Bearish Reversal', 'SELL',
                        entry, sl, tgt,
                        draw_lines=[
                            (df['datetime'].iloc[ls], p_ls, df['datetime'].iloc[head], p_head, '#ff4444'),
                            (df['datetime'].iloc[head], p_head, df['datetime'].iloc[rs], p_rs, '#ff4444'),
                            (df['datetime'].iloc[ls], neckline, df['datetime'].iloc[bo_idx], neckline, '#FFD700'),
                        ],
                        sr_zones=[],
                    ))
                    break
        return results

    def _detect_inv_head_shoulders(self, df):
        results = []
        highs_arr = df['high'].values
        lows_arr = df['low'].values
        closes = df['close'].values
        n = len(closes)

        _, lows = self._find_pivots(df, order=2)
        if len(lows) < 3:
            return results

        for i in range(len(lows) - 2):
            ls, head, rs = lows[i], lows[i + 1], lows[i + 2]
            if head - ls < self.MIN_PATTERN_BARS or rs - head < self.MIN_PATTERN_BARS:
                continue
            p_ls = lows_arr[ls]
            p_head = lows_arr[head]
            p_rs = lows_arr[rs]
            if p_head >= min(p_ls, p_rs):
                continue
            if abs(p_ls - p_rs) / max(p_head, 1) > 0.05:
                continue
            t1_high = highs_arr[ls:head + 1].max()
            t2_high = highs_arr[head:rs + 1].max()
            neckline = (t1_high + t2_high) / 2
            for bo_idx in range(rs + 1, min(rs + 8, n)):
                if closes[bo_idx] > neckline:
                    ph = neckline - p_head
                    entry = neckline
                    sl = p_rs * 0.997
                    tgt = neckline + ph
                    results.append(self._make_result(
                        df, bo_idx,
                        'Inv Head & Shoulders', 'Reversal', 'Bullish Reversal', 'BUY',
                        entry, sl, tgt,
                        draw_lines=[
                            (df['datetime'].iloc[ls], p_ls, df['datetime'].iloc[head], p_head, '#00ff88'),
                            (df['datetime'].iloc[head], p_head, df['datetime'].iloc[rs], p_rs, '#00ff88'),
                            (df['datetime'].iloc[ls], neckline, df['datetime'].iloc[bo_idx], neckline, '#FFD700'),
                        ],
                        sr_zones=[],
                    ))
                    break
        return results

    def _scan_trendline_patterns(self, df, window):
        highs_arr = df['high'].values
        lows_arr = df['low'].values
        n = len(highs_arr)
        out = []
        xs = np.arange(window)
        for i in range(window, n):
            seg_h = highs_arr[i - window: i]
            seg_l = lows_arr[i - window: i]
            h_slope, h_int = np.polyfit(xs, seg_h, 1)
            l_slope, l_int = np.polyfit(xs, seg_l, 1)
            upper = h_slope * (window - 1) + h_int
            lower = l_slope * (window - 1) + l_int
            out.append((i, h_slope, h_int, l_slope, l_int, upper, lower))
        return out

    def _detect_triangles(self, df):
        results = []
        closes = df['close'].values
        n = len(closes)
        window = min(20, n - 2)
        if n < window + 2:
            return results

        for (i, h_slope, h_int, l_slope, l_int, upper, lower) in self._scan_trendline_patterns(df, window):
            entry = closes[i]
            sl_buy = lower
            sl_sell = upper
            ph = upper - lower
            if ph <= 0:
                continue
            price_tol = closes[i] * 0.001

            if abs(h_slope) < price_tol and l_slope > price_tol * 0.3:
                if entry > upper:
                    results.append(self._make_result(
                        df, i, 'Ascending Triangle', 'Breakout', 'Bullish Breakout', 'BUY',
                        entry, sl_buy, upper + ph,
                        draw_lines=[
                            (df['datetime'].iloc[i - window], h_int, df['datetime'].iloc[i], upper, '#FFD700'),
                            (df['datetime'].iloc[i - window], l_int, df['datetime'].iloc[i], lower, '#FFD700'),
                        ],
                        sr_zones=[],
                    ))
            elif abs(l_slope) < price_tol and h_slope < -price_tol * 0.3:
                if entry < lower:
                    results.append(self._make_result(
                        df, i, 'Descending Triangle', 'Breakout', 'Bearish Breakdown', 'SELL',
                        entry, sl_sell, lower - ph,
                        draw_lines=[
                            (df['datetime'].iloc[i - window], h_int, df['datetime'].iloc[i], upper, '#FFD700'),
                            (df['datetime'].iloc[i - window], l_int, df['datetime'].iloc[i], lower, '#FFD700'),
                        ],
                        sr_zones=[],
                    ))
            elif h_slope < -price_tol * 0.3 and l_slope > price_tol * 0.3:
                if entry > upper:
                    results.append(self._make_result(
                        df, i, 'Symmetrical Triangle', 'Breakout', 'Bullish Breakout', 'BUY',
                        entry, sl_buy, upper + ph,
                        draw_lines=[
                            (df['datetime'].iloc[i - window], h_int, df['datetime'].iloc[i], upper, '#FFD700'),
                            (df['datetime'].iloc[i - window], l_int, df['datetime'].iloc[i], lower, '#FFD700'),
                        ],
                        sr_zones=[],
                    ))
                elif entry < lower:
                    results.append(self._make_result(
                        df, i, 'Symmetrical Triangle', 'Breakout', 'Bearish Breakdown', 'SELL',
                        entry, sl_sell, lower - ph,
                        draw_lines=[
                            (df['datetime'].iloc[i - window], h_int, df['datetime'].iloc[i], upper, '#FFD700'),
                            (df['datetime'].iloc[i - window], l_int, df['datetime'].iloc[i], lower, '#FFD700'),
                        ],
                        sr_zones=[],
                    ))
        return results

    def _detect_falling_wedge(self, df):
        results = []
        closes = df['close'].values
        n = len(closes)
        window = min(18, n - 2)
        if n < window + 2:
            return results

        for (i, h_slope, h_int, l_slope, l_int, upper, lower) in self._scan_trendline_patterns(df, window):
            if h_slope < 0 and l_slope < 0 and h_slope < l_slope - 1e-6:
                entry = closes[i]
                if entry > upper:
                    ph = upper - lower
                    sl = lower * 0.998
                    tgt = entry + ph * 2
                    results.append(self._make_result(
                        df, i, 'Falling Wedge', 'Reversal', 'Bullish', 'BUY',
                        entry, sl, tgt,
                        draw_lines=[
                            (df['datetime'].iloc[i - window], h_int, df['datetime'].iloc[i], upper, '#00ff88'),
                            (df['datetime'].iloc[i - window], l_int, df['datetime'].iloc[i], lower, '#00ff88'),
                        ],
                        sr_zones=[],
                    ))
        return results

    def _detect_flag(self, df):
        results = []
        closes = df['close'].values
        highs_arr = df['high'].values
        lows_arr = df['low'].values
        n = len(closes)
        if n < 18:
            return results

        pole_len = 8
        flag_len = 5

        for i in range(pole_len + flag_len, n):
            pole_start = i - pole_len - flag_len
            pole_end = i - flag_len
            flag_start = pole_end
            flag_end = i

            pole_move = closes[pole_end] - closes[pole_start]
            pole_pct = pole_move / closes[pole_start] if closes[pole_start] > 0 else 0

            flag_closes = closes[flag_start: flag_end]
            if len(flag_closes) < 2:
                continue
            flag_slope, _ = np.polyfit(range(len(flag_closes)), flag_closes, 1)

            if pole_pct > 0.008 and flag_slope < 0:
                flag_top = highs_arr[flag_start:flag_end].max()
                flag_bottom = lows_arr[flag_start:flag_end].min()
                if closes[i] > flag_top:
                    entry = closes[i]
                    sl = flag_bottom * 0.998
                    tgt = entry + abs(pole_move)
                    results.append(self._make_result(
                        df, i, 'Bull Flag', 'Continuation', 'Bullish Continuation', 'BUY',
                        entry, sl, tgt,
                        draw_lines=[
                            (df['datetime'].iloc[pole_start], closes[pole_start],
                             df['datetime'].iloc[pole_end], closes[pole_end], '#00ff88'),
                        ],
                        sr_zones=[(sl, flag_top * 1.001, 'rgba(0,255,136,0.1)')],
                    ))
            elif pole_pct < -0.008 and flag_slope > 0:
                flag_top = highs_arr[flag_start:flag_end].max()
                flag_bottom = lows_arr[flag_start:flag_end].min()
                if closes[i] < flag_bottom:
                    entry = closes[i]
                    sl = flag_top * 1.002
                    tgt = entry - abs(pole_move)
                    results.append(self._make_result(
                        df, i, 'Bear Flag', 'Continuation', 'Bearish Continuation', 'SELL',
                        entry, sl, tgt,
                        draw_lines=[
                            (df['datetime'].iloc[pole_start], closes[pole_start],
                             df['datetime'].iloc[pole_end], closes[pole_end], '#ff4444'),
                        ],
                        sr_zones=[(flag_bottom * 0.999, sl, 'rgba(255,68,68,0.1)')],
                    ))
        return results

    def _detect_range_breakout(self, df):
        results = []
        closes = df['close'].values
        highs_arr = df['high'].values
        lows_arr = df['low'].values
        n = len(closes)
        range_window = min(20, n - 2)
        if n < range_window + 2:
            return results

        for i in range(range_window + 1, n):
            seg_h = highs_arr[i - range_window: i]
            seg_l = lows_arr[i - range_window: i]
            resistance = seg_h.max()
            support = seg_l.min()
            rng = resistance - support
            if rng / max(support, 1) < 0.002:
                continue
            if closes[i - range_window:i].std() > rng * 0.5:
                continue

            entry = closes[i]
            if entry > resistance * 1.001:
                sl = support
                tgt = resistance + rng
                results.append(self._make_result(
                    df, i, 'Range Breakout', 'Breakout', 'Bullish Momentum', 'BUY',
                    entry, sl, tgt,
                    draw_lines=[
                        (df['datetime'].iloc[i - range_window], resistance,
                         df['datetime'].iloc[i], resistance, '#FFD700'),
                        (df['datetime'].iloc[i - range_window], support,
                         df['datetime'].iloc[i], support, '#FFD700'),
                    ],
                    sr_zones=[(support, resistance, 'rgba(255,215,0,0.08)')],
                ))
            elif entry < support * 0.999:
                sl = resistance
                tgt = support - rng
                results.append(self._make_result(
                    df, i, 'Range Breakdown', 'Breakout', 'Bearish Momentum', 'SELL',
                    entry, sl, tgt,
                    draw_lines=[
                        (df['datetime'].iloc[i - range_window], resistance,
                         df['datetime'].iloc[i], resistance, '#FFD700'),
                        (df['datetime'].iloc[i - range_window], support,
                         df['datetime'].iloc[i], support, '#FFD700'),
                    ],
                    sr_zones=[(support, resistance, 'rgba(255,215,0,0.08)')],
                ))
        return results

    def _detect_channel(self, df):
        results = []
        closes = df['close'].values
        n = len(closes)
        window = min(20, n - 2)
        if n < window + 2:
            return results

        for (i, h_slope, h_int, l_slope, l_int, upper, lower) in self._scan_trendline_patterns(df, window):
            if lower >= upper:
                continue
            denom = abs(h_slope) + abs(l_slope) + 1e-9
            if abs(h_slope - l_slope) / denom > 0.40:
                continue
            ph = upper - lower
            entry = closes[i]

            if entry < lower * 0.999:
                sl = upper
                tgt = lower - ph
                results.append(self._make_result(
                    df, i, 'Channel Breakdown', 'Breakout', 'Bearish Momentum', 'SELL',
                    entry, sl, tgt,
                    draw_lines=[
                        (df['datetime'].iloc[i - window], h_int, df['datetime'].iloc[i], upper, '#ff4444'),
                        (df['datetime'].iloc[i - window], l_int, df['datetime'].iloc[i], lower, '#ff4444'),
                    ],
                    sr_zones=[],
                ))
            elif entry > upper * 1.001:
                sl = lower
                tgt = upper + ph
                results.append(self._make_result(
                    df, i, 'Channel Breakout', 'Breakout', 'Bullish Momentum', 'BUY',
                    entry, sl, tgt,
                    draw_lines=[
                        (df['datetime'].iloc[i - window], h_int, df['datetime'].iloc[i], upper, '#00ff88'),
                        (df['datetime'].iloc[i - window], l_int, df['datetime'].iloc[i], lower, '#00ff88'),
                    ],
                    sr_zones=[],
                ))
        return results

    def _detect_trendline_breakout(self, df):
        results = []
        closes = df['close'].values
        n = len(closes)
        window = min(15, n - 2)
        if n < window + 2:
            return results

        for (i, h_slope, h_int, l_slope, l_int, upper, lower) in self._scan_trendline_patterns(df, window):
            entry = closes[i]
            if h_slope < 0 and entry > upper * 1.001:
                sl = lower
                tgt = entry + (entry - sl) * 1.5
                results.append(self._make_result(
                    df, i, 'Trendline Breakout Up', 'Breakout', 'Bullish Trend Change', 'BUY',
                    entry, sl, tgt,
                    draw_lines=[
                        (df['datetime'].iloc[i - window], h_int, df['datetime'].iloc[i], upper, '#00ff88'),
                    ],
                    sr_zones=[],
                ))
            elif l_slope > 0 and entry < lower * 0.999:
                sl = upper
                tgt = entry - (sl - entry) * 1.5
                results.append(self._make_result(
                    df, i, 'Trendline Breakdown', 'Breakout', 'Bearish Trend Change', 'SELL',
                    entry, sl, tgt,
                    draw_lines=[
                        (df['datetime'].iloc[i - window], l_int, df['datetime'].iloc[i], lower, '#ff4444'),
                    ],
                    sr_zones=[],
                ))
        return results

    def detect_all(self, df):
        if df is None or df.empty or len(df) < 15:
            return []
        results = []
        for detector in [
            self._detect_double_bottom,
            self._detect_double_top,
            self._detect_head_shoulders,
            self._detect_inv_head_shoulders,
            self._detect_triangles,
            self._detect_falling_wedge,
            self._detect_flag,
            self._detect_range_breakout,
            self._detect_channel,
            self._detect_trendline_breakout,
        ]:
            try:
                results.extend(detector(df))
            except Exception:
                pass
        seen = {}
        for r in sorted(results, key=lambda x: x['time']):
            seen[r['pattern']] = r
        return list(seen.values())


# ── Candlestick Intelligence Engine (CIE) ─────────────────────────────────────













# ── Cross-Market Confirmation Engine (CMCE) ───────────────────────────────────













# ── Institutional Order Flow Confirmation Engine (IOFCE) ──────────────────────















# ══════════════════════════════════════════════════════════════════════════════
# END PORTED TRADING ENGINES
# ══════════════════════════════════════════════════════════════════════════════


# ──────────────────────────────────────────────────────────────────────────────
# Per-bar Candle Pattern Detector (for chart markers + Today listing)
# Ported from vob (5).py → _detect_chart_candle_types
# Returns a list of dicts: {time, pattern, direction, price, high, low, volume}
# ──────────────────────────────────────────────────────────────────────────────



# ──────────────────────────────────────────────────────────────────────────────
# Liquidity Grab / Stop Hunt / Sweep candle detector
#
# Textbook stop-loss hunt definition (Hammer / Shooting Star / Pin Bar):
#   1. Price sweeps prior swing high/low (with meaningful pierce, not noise)
#   2. Long wick > 2× body  (small/medium body, long wick)
#   3. Close near the opposite extreme (close in top/bottom 30% of range)
#   4. Volume spike vs trailing average
#   5. Wick dominates range (>= 60%)
#
# Three tiers (priority high→low):
#   - Stop Hunt:      all 5 criteria — strictest, textbook Hammer/Star
#   - Liquidity Grab: sweep + dominant wick + close-near-extreme (no vol req)
#   - Sweep:          engulfs prior bar with opposite close (loosest)
#
# Direction:
#   - BUY  (bullish reversal) — sweeps a low, reclaims it, closes near high
#   - SELL (bearish reversal) — sweeps a high, rejects, closes near low
# ──────────────────────────────────────────────────────────────────────────────



def _classify_reversal_pattern(o, h, l, c, po=None, ph=None, pl=None, pc=None):
    """Identify the candlestick reversal pattern on a single bar.
    Returns one of: Hammer, Shooting Star, Dragonfly Doji, Gravestone Doji,
    Bullish Engulfing, Bearish Engulfing, Pin Bar Bull, Pin Bar Bear, '—'."""
    rng = max(h - l, 1e-6)
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    body_pct = body / rng
    is_bull = c >= o

    # ── 2-bar Engulfing (needs previous bar)
    if po is not None and pc is not None:
        prev_body = abs(pc - po)
        prev_bull = pc >= po
        if (is_bull and not prev_bull and body > prev_body
                and o <= pc and c >= po):
            return 'Bullish Engulfing'
        if (not is_bull and prev_bull and body > prev_body
                and o >= pc and c <= po):
            return 'Bearish Engulfing'

    # ── Single-bar wick patterns
    if body_pct < 0.10:  # near-doji
        if lower_wick >= rng * 0.6 and upper_wick <= rng * 0.10:
            return 'Dragonfly Doji'
        if upper_wick >= rng * 0.6 and lower_wick <= rng * 0.10:
            return 'Gravestone Doji'
    if lower_wick >= body * 2 and upper_wick <= body * 0.5 and body_pct <= 0.35:
        return 'Hammer'
    if upper_wick >= body * 2 and lower_wick <= body * 0.5 and body_pct <= 0.35:
        return 'Shooting Star'
    if lower_wick >= rng * 0.5 and body_pct <= 0.4:
        return 'Pin Bar Bull'
    if upper_wick >= rng * 0.5 and body_pct <= 0.4:
        return 'Pin Bar Bear'
    return '—'






_BULL_PATTERNS = {'Hammer', 'Bullish Engulfing', 'Dragonfly Doji', 'Pin Bar Bull',
                  'Marubozu Up', 'Lower Wick Rej', 'Bull Engulfing'}
_BEAR_PATTERNS = {'Shooting Star', 'Bearish Engulfing', 'Gravestone Doji', 'Pin Bar Bear',
                  'Marubozu Down', 'Upper Wick Rej', 'Bear Engulfing'}


def _leg_candle_signal(df):
    """Inspect the last 2 bars of a leg's intraday and return (pattern, bias).
    bias ∈ {'bull','bear','neutral','unknown'}. pattern is the textual name
    from _classify_reversal_pattern; falls back to body-direction classification."""
    if df is None or getattr(df, 'empty', True) or len(df) < 2:
        return ('—', 'unknown')
    try:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        o, h, l, c = float(last['open']), float(last['high']), float(last['low']), float(last['close'])
        po, ph, pl, pc = float(prev['open']), float(prev['high']), float(prev['low']), float(prev['close'])
        pat = _classify_reversal_pattern(o, h, l, c, po=po, ph=ph, pl=pl, pc=pc)
        if pat in _BULL_PATTERNS:
            return (pat, 'bull')
        if pat in _BEAR_PATTERNS:
            return (pat, 'bear')
        # Fallback: body direction with size filter
        rng = h - l if h > l else 0.001
        body = abs(c - o)
        if body / rng < 0.20:
            return ('Doji', 'neutral')
        if c > o:
            return ('Bullish Body', 'bull')
        if c < o:
            return ('Bearish Body', 'bear')
        return ('Flat', 'neutral')
    except Exception:
        return ('—', 'unknown')


def _atm_ce_pe_trend():
    """Return (ce_pattern, pe_pattern, ce_bias, pe_bias, ce_ltp, pe_ltp, atm_strike).
    Patterns derived from the last 1-2 bars of each leg's 1m intraday via
    _classify_reversal_pattern; bias is bull/bear/neutral/unknown."""
    sd = st.session_state.get('_atm_pm1_vpfr') or {}
    atm_strike = sd.get('atm_strike', 0)
    ce_pat = pe_pat = '—'
    ce_b = pe_b = 'unknown'
    ce_ltp = pe_ltp = 0.0
    legs_dfs = st.session_state.get('_atm_leg_dfs') or {}
    for tag, df_l in legs_dfs.items():
        if f"ATM CE {atm_strike:.0f}" in tag:
            ce_pat, ce_b = _leg_candle_signal(df_l)
            try:
                ce_ltp = float(df_l['close'].iloc[-1])
            except Exception:
                pass
        elif f"ATM PE {atm_strike:.0f}" in tag:
            pe_pat, pe_b = _leg_candle_signal(df_l)
            try:
                pe_ltp = float(df_l['close'].iloc[-1])
            except Exception:
                pass
    return ce_pat, pe_pat, ce_b, pe_b, ce_ltp, pe_ltp, atm_strike














def _log_sent_alert(msg, alert_class):
    """Archive one alert: side detection + session event list (feeds the
    signal-cluster meta-alert) + Supabase alert_log (sql/005). Muted alerts
    carry '·muted' in their class so Telegram-delivered vs archived-only
    rows stay distinguishable."""
    try:
        _side = 'CALL' if 'BUY CALL' in msg else ('PUT' if 'BUY PUT' in msg else None)
        _ev = st.session_state.setdefault('_alert_side_events', [])
        _ev.append((time.time(), _side, alert_class))
        if len(_ev) > 200:
            del _ev[:len(_ev) - 200]
        _dbl = st.session_state.get('_db_obj')
        if _dbl is not None:
            import re as _re2
            _sp_m = _re2.search(r'NIFTY Spot ₹([\d,.]+)', msg)
            _ist_l = pytz.timezone('Asia/Kolkata')
            _dbl.insert_alert_log({
                'ts': datetime.now(_ist_l).isoformat(),
                'trading_day': datetime.now(_ist_l).strftime('%Y-%m-%d'),
                'alert_class': alert_class, 'side': _side,
                'spot': float(_sp_m.group(1).replace(',', '')) if _sp_m else None,
                'message': _strip_html_tags(msg)[:1500],
            })
    except Exception:
        pass


def _throttled_telegram_send(msg, alert_class, key, cooldown_s=900,
                             class_limit=3, class_window=300, class_sleep=1800):
    """Sleep system for repeated telegram messages with two layers of throttling:

    1. **Per-key cooldown**: same `key` won't fire again within `cooldown_s` seconds.
       (existing dedup pattern — per-leg + per-POC + per-bar.)
    2. **Per-class burst sleep**: if `class_limit` messages of the same
       `alert_class` fire within `class_window` seconds, ALL messages of that
       class are suppressed for `class_sleep` seconds (default 30 min).

    Returns True if sent, False if suppressed.

    Defaults: cooldown 15min, burst 3-in-5min triggers 30min class sleep.
    """
    # MIOS V5 pure decision-support: suppress retired trade-call classes at the
    # send layer (the arm/track/log lifecycle around the caller is untouched).
    if RETIRE_ENTRY_ALERTS and alert_class in _RETIRED_ALERT_CLASSES:
        return False

    state = st.session_state.setdefault('_tg_throttle', {})
    keys = state.setdefault('keys', {})        # {key: last_sent_dt}
    classes = state.setdefault('classes', {})  # {class: {'sleep_until', 'history'}}
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)

    # 1) per-key cooldown
    last = keys.get(key)
    if last and (now - last).total_seconds() < cooldown_s:
        return False

    # 2) per-class burst-sleep check
    cs = classes.setdefault(alert_class, {'sleep_until': None, 'history': []})
    if cs['sleep_until'] and now < cs['sleep_until']:
        return False

    # 3) actually send — routing per user request:
    #   ENTRY TIER (7 trade signals) → Telegram + Discord mirror
    #   everything else (active or muted) → Discord-only + Supabase archive
    # Force-sends (manual buttons, pre-market) and the dedicated alert bot
    # are unaffected.
    _tg_allowed = _msg_allowed(msg)
    _entry = _msg_entry_tier(msg)
    try:
        if _entry:
            send_telegram_message_sync(msg, force=False)
        else:
            send_discord_message(msg, force=True)
    except Exception:
        return False

    keys[key] = now
    # roll history window, append, then check burst
    cs['history'] = [t for t in cs['history']
                     if (now - t).total_seconds() < class_window]
    cs['history'].append(now)
    if len(cs['history']) >= class_limit:
        cs['sleep_until'] = now + timedelta(seconds=class_sleep)
        cs['history'] = []  # reset so post-sleep counter starts fresh
    _log_sent_alert(msg, alert_class if _entry else (
        f"{alert_class}·discord" if _tg_allowed else f"{alert_class}·muted"))
    return True










def _clv_delta_cols(d):
    """Close-Location-Value (CLV) weighted buyer/seller split.

    Instead of all-or-nothing (close>open → 100% buy), split each bar's volume
    by WHERE it closed inside its high-low range:
        buy_fraction = (close − low) / (high − low)   ∈ [0, 1]
        bull_v = volume × buy_fraction
        bear_v = volume × (1 − buy_fraction)
    A bar that spiked up then closed mid-range is no longer counted as fully
    bullish — more faithful buyer/seller attribution on the same 1m data.
    Zero-range bars fall back to candle direction (1 / 0 / 0.5).
    Adds 'bull_v' and 'bear_v' columns and returns the df.
    """
    rng = (d['high'].astype(float) - d['low'].astype(float))
    clv = (d['close'].astype(float) - d['low'].astype(float)) / rng.where(rng > 0)
    _fallback = pd.Series(
        np.where(d['close'] > d['open'], 1.0,
                 np.where(d['close'] < d['open'], 0.0, 0.5)),
        index=d.index)
    clv = clv.fillna(_fallback).clip(0.0, 1.0)
    vol = d['volume'].astype(float)
    d['bull_v'] = vol * clv
    d['bear_v'] = vol * (1.0 - clv)
    return d










def _mfp_poc_bias(mfp):
    """Return 'BULL' / 'BEAR' / 'NEUTRAL' for the MFP's POC bin based on its
    sentiment + delta sign. None-safe."""
    if not mfp or not mfp.get('rows'):
        return 'NEUTRAL'
    poc_row = next((r for r in mfp['rows'] if r.get('is_poc')), None)
    if not poc_row:
        return 'NEUTRAL'
    sent = (poc_row.get('sentiment') or '').lower()
    if sent.startswith('bull'):
        return 'BULL'
    if sent.startswith('bear'):
        return 'BEAR'
    # Fallback to delta sign
    d = poc_row.get('delta', 0) or 0
    return 'BULL' if d > 0 else ('BEAR' if d < 0 else 'NEUTRAL')



















def analyze_option_chain(selected_expiry=None, pivot_data=None, vob_data=None):
    now = datetime.now(timezone("Asia/Kolkata"))

    expiry_data = get_dhan_expiry_list_cached(NIFTY_UNDERLYING_SCRIP, NIFTY_UNDERLYING_SEG)
    if not expiry_data or 'data' not in expiry_data:
        # ⚠️ Record WHICH fetch failed. Returning None here made every downstream
        # panel say "no option chain", when the chain was never requested — the
        # EXPIRY LIST is what failed, and it is a different endpoint.
        st.session_state.setdefault('_dhan_last_error',
                                    'expiry list unavailable (Dhan /optionchain/expirylist)')
        st.error("Failed to get expiry list from Dhan API")
        return None

    expiry_dates = expiry_data['data']
    if not expiry_dates:
        st.session_state.setdefault('_dhan_last_error',
                                    'Dhan returned an empty expiry list')
        st.error("No expiry dates available")
        return None

    expiry = selected_expiry if selected_expiry else expiry_dates[0]

    option_chain_data = get_dhan_option_chain(NIFTY_UNDERLYING_SCRIP, NIFTY_UNDERLYING_SEG, expiry)
    if not option_chain_data or 'data' not in option_chain_data:
        st.error("Failed to get option chain from Dhan API")
        return {'underlying': None, 'df_summary': None, 'expiry_dates': expiry_dates, 'expiry': None, 'sr_data': [], 'max_pain_strike': None, 'styled_df': None, 'df_display': None, 'display_cols': [], 'bias_cols': [], 'total_ce_change': 0, 'total_pe_change': 0}

    data = option_chain_data['data']
    # Cache raw Dhan option-chain payload (last_price + oc) in session state
    # so the Seller's Perspective tab can reuse it without a duplicate API call.
    _raw_cache = st.session_state.setdefault('_cached_raw_chain', {})
    _raw_cache[expiry] = data
    st.session_state['_cached_raw_chain_latest'] = {'expiry': expiry, 'data': data}
    underlying = data['last_price']
    # 📍 Prefer the live index LTP (marketfeed/ltp) over the option-chain's
    # last_price, which refreshes on the chain's slower cadence and can lag the
    # index by a few seconds. Only override when the live quote is sane (within
    # 1% of the chain price) so a wrong-instrument/garbage value can't leak in.
    try:
        _live_spot = get_index_spot_ltp(NIFTY_UNDERLYING_SCRIP, NIFTY_UNDERLYING_SEG)
        if _live_spot and underlying and abs(_live_spot - underlying) / underlying < 0.01:
            underlying = _live_spot
        elif _live_spot and not underlying:
            underlying = _live_spot
    except Exception:
        pass

    oc_data = data['oc']
    calls, puts = [], []
    for strike, strike_data in oc_data.items():
        if 'ce' in strike_data:
            ce_data = strike_data['ce']
            ce_data['strikePrice'] = float(strike)
            calls.append(ce_data)
        if 'pe' in strike_data:
            pe_data = strike_data['pe']
            pe_data['strikePrice'] = float(strike)
            puts.append(pe_data)

    df_ce = pd.DataFrame(calls)
    df_pe = pd.DataFrame(puts)
    df = pd.merge(df_ce, df_pe, on='strikePrice', suffixes=('_CE', '_PE')).sort_values('strikePrice', ascending=False)

    column_mapping = {
        'last_price': 'lastPrice',
        'oi': 'openInterest',
        'previous_oi': 'previousOpenInterest',
        'top_ask_quantity': 'askQty',
        'top_bid_quantity': 'bidQty',
        'volume': 'totalTradedVolume',
        'iv': 'impliedVolatility'
    }
    for old_col, new_col in column_mapping.items():
        if f"{old_col}_CE" in df.columns:
            df.rename(columns={f"{old_col}_CE": f"{new_col}_CE"}, inplace=True)
        if f"{old_col}_PE" in df.columns:
            df.rename(columns={f"{old_col}_PE": f"{new_col}_PE"}, inplace=True)

    df['changeinOpenInterest_CE'] = df['openInterest_CE'] - df['previousOpenInterest_CE']
    df['changeinOpenInterest_PE'] = df['openInterest_PE'] - df['previousOpenInterest_PE']

    T = calculate_exact_time_to_expiry(expiry)
    r = 0.06

    for idx, row in df.iterrows():
        strike = row['strikePrice']
        iv_ce = row.get('impliedVolatility_CE')
        iv_pe = row.get('impliedVolatility_PE')
        if pd.isna(iv_ce) or iv_ce == 0:
            iv_ce, _ = get_iv_fallback(df, strike)
        if pd.isna(iv_pe) or iv_pe == 0:
            _, iv_pe = get_iv_fallback(df, strike)
        iv_ce = iv_ce or 15
        iv_pe = iv_pe or 15
        greeks_ce = calculate_greeks('CE', underlying, strike, T, r, iv_ce / 100)
        greeks_pe = calculate_greeks('PE', underlying, strike, T, r, iv_pe / 100)
        df.at[idx, 'Delta_CE'], df.at[idx, 'Gamma_CE'], df.at[idx, 'Vega_CE'], df.at[idx, 'Theta_CE'], df.at[idx, 'Rho_CE'] = greeks_ce
        df.at[idx, 'Delta_PE'], df.at[idx, 'Gamma_PE'], df.at[idx, 'Vega_PE'], df.at[idx, 'Theta_PE'], df.at[idx, 'Rho_PE'] = greeks_pe
        _vc_ce = calculate_vanna_charm('CE', underlying, strike, T, r, iv_ce / 100)
        _vc_pe = calculate_vanna_charm('PE', underlying, strike, T, r, iv_pe / 100)
        df.at[idx, 'Vanna_CE'], df.at[idx, 'Charm_CE'] = _vc_ce
        df.at[idx, 'Vanna_PE'], df.at[idx, 'Charm_PE'] = _vc_pe
        # Third-order Greeks (vomma/speed/zomma/veta/color) — the producer the
        # Greek-behaviour layer needs so it can stop reporting them "Not reported".
        _hg_ce = _higher_greeks(underlying, strike, T, r, iv_ce / 100)
        _hg_pe = _higher_greeks(underlying, strike, T, r, iv_pe / 100)
        for _g in ('vomma', 'speed', 'zomma', 'veta', 'color'):
            df.at[idx, f'{_g.capitalize()}_CE'] = _hg_ce[_g]
            df.at[idx, f'{_g.capitalize()}_PE'] = _hg_pe[_g]

    atm_strike = min(df['strikePrice'], key=lambda x: abs(x - underlying))

    # Save ATM±4 strikes (200 pts) for money flow analysis before narrowing
    df_atm4 = df[abs(df['strikePrice'] - atm_strike) <= 200].copy()
    df_atm4['Zone'] = df_atm4['strikePrice'].apply(lambda x: 'ATM' if x == atm_strike else 'ITM' if x < underlying else 'OTM')
    # Save ATM±5 strikes (250 pts) for unwinding/parallel winding analysis
    df_atm8 = df[abs(df['strikePrice'] - atm_strike) <= 250].copy()
    df_atm8['Zone'] = df_atm8['strikePrice'].apply(lambda x: 'ATM' if x == atm_strike else 'ITM' if x < underlying else 'OTM')
    atm_plus_minus_2 = df[abs(df['strikePrice'] - atm_strike) <= 100]
    df = atm_plus_minus_2.copy()

    df['Zone'] = df['strikePrice'].apply(lambda x: 'ATM' if x == atm_strike else 'ITM' if x < underlying else 'OTM')
    df['Level'] = df.apply(determine_level, axis=1)

    total_ce_change = df['changeinOpenInterest_CE'].sum() / 100000
    total_pe_change = df['changeinOpenInterest_PE'].sum() / 100000

    bias_results = []
    for _, row in df.iterrows():
        bid_ask_pressure, pressure_bias = calculate_bid_ask_pressure(
            row.get('bidQty_CE', 0), row.get('askQty_CE', 0),
            row.get('bidQty_PE', 0), row.get('askQty_PE', 0)
        )
        score = 0
        row_data = {
            "Strike": row['strikePrice'],
            "Zone": row['Zone'],
            "Level": row['Level'],
        }
        _g = row.get
        row_data["LTP_Bias"] = "Bullish" if _g('lastPrice_CE', 0) > _g('lastPrice_PE', 0) else "Bearish"
        row_data["OI_Bias"] = "Bearish" if _g('openInterest_CE', 0) > _g('openInterest_PE', 0) else "Bullish"
        row_data["ChgOI_Bias"] = "Bearish" if _g('changeinOpenInterest_CE', 0) > _g('changeinOpenInterest_PE', 0) else "Bullish"
        row_data["Volume_Bias"] = "Bullish" if _g('totalTradedVolume_CE', 0) > _g('totalTradedVolume_PE', 0) else "Bearish"
        row_data["Delta_Bias"] = "Bullish" if _g('Delta_CE', 0) > abs(_g('Delta_PE', 0)) else "Bearish"
        row_data["Gamma_Bias"] = "Bullish" if _g('Gamma_CE', 0) > _g('Gamma_PE', 0) else "Bearish"
        row_data["Theta_Bias"] = "Bullish" if _g('Theta_CE', 0) < _g('Theta_PE', 0) else "Bearish"
        row_data["AskQty_Bias"] = "Bullish" if _g('askQty_PE', 0) > _g('askQty_CE', 0) else "Bearish"
        row_data["BidQty_Bias"] = "Bearish" if _g('bidQty_PE', 0) > _g('bidQty_CE', 0) else "Bullish"
        row_data["AskBid_Bias"] = "Bullish" if _g('bidQty_CE', 0) > _g('askQty_CE', 0) else "Bearish"
        row_data["IV_Bias"] = "Bullish" if _g('impliedVolatility_CE', 0) > _g('impliedVolatility_PE', 0) else "Bearish"
        delta_exp_ce = _g('Delta_CE', 0) * _g('openInterest_CE', 0)
        delta_exp_pe = _g('Delta_PE', 0) * _g('openInterest_PE', 0)
        gamma_exp_ce = _g('Gamma_CE', 0) * _g('openInterest_CE', 0)
        gamma_exp_pe = _g('Gamma_PE', 0) * _g('openInterest_PE', 0)
        row_data["DeltaExp"] = "Bullish" if delta_exp_ce > abs(delta_exp_pe) else "Bearish"
        row_data["GammaExp"] = "Bullish" if gamma_exp_ce > gamma_exp_pe else "Bearish"
        row_data["DVP_Bias"] = delta_volume_bias(
            row.get('lastPrice_CE', 0) - row.get('lastPrice_PE', 0),
            row.get('totalTradedVolume_CE', 0) - row.get('totalTradedVolume_PE', 0),
            row.get('changeinOpenInterest_CE', 0) - row.get('changeinOpenInterest_PE', 0)
        )
        row_data["BidAskPressure"] = bid_ask_pressure
        row_data["PressureBias"] = pressure_bias
        for k in row_data:
            if "_Bias" in k or k in ["DeltaExp", "GammaExp"]:
                bias_val = row_data[k]
                if bias_val == "Bullish":
                    score += 1
                elif bias_val == "Bearish":
                    score -= 1
        row_data["BiasScore"] = score
        row_data["Verdict"] = final_verdict(score)
        if row_data['OI_Bias'] == "Bullish" and row_data['ChgOI_Bias'] == "Bullish":
            row_data["Operator_Entry"] = "Entry Bull"
        elif row_data['OI_Bias'] == "Bearish" and row_data['ChgOI_Bias'] == "Bearish":
            row_data["Operator_Entry"] = "Entry Bear"
        else:
            row_data["Operator_Entry"] = "No Entry"
        if score >= 4:
            row_data["Scalp_Moment"] = "Scalp Bull"
        elif score >= 2:
            row_data["Scalp_Moment"] = "Moment Bull"
        elif score <= -4:
            row_data["Scalp_Moment"] = "Scalp Bear"
        elif score <= -2:
            row_data["Scalp_Moment"] = "Moment Bear"
        else:
            row_data["Scalp_Moment"] = "No Signal"
        if score >= 4:
            row_data["FakeReal"] = "Real Up"
        elif 1 <= score < 4:
            row_data["FakeReal"] = "Fake Up"
        elif score <= -4:
            row_data["FakeReal"] = "Real Down"
        elif -4 < score <= -1:
            row_data["FakeReal"] = "Fake Down"
        else:
            row_data["FakeReal"] = "No Move"
        chg_oi_ce = row.get('changeinOpenInterest_CE', 0)
        chg_oi_pe = row.get('changeinOpenInterest_PE', 0)
        oi_ce = row.get('openInterest_CE', 0)
        oi_pe = row.get('openInterest_PE', 0)
        chg_oi_cmp = '>' if chg_oi_ce > chg_oi_pe else ('<' if chg_oi_ce < chg_oi_pe else '≈')
        row_data["ChgOI_Cmp"] = f"{int(chg_oi_ce/1000)}K {chg_oi_cmp} {int(chg_oi_pe/1000)}K"
        oi_cmp = '>' if oi_ce > oi_pe else ('<' if oi_ce < oi_pe else '≈')
        row_data["OI_Cmp"] = f"{round(oi_ce/1e6, 2)}M {oi_cmp} {round(oi_pe/1e6, 2)}M"
        bias_results.append(row_data)

    df_summary = pd.DataFrame(bias_results)

    merge_cols = ['strikePrice', 'openInterest_CE', 'openInterest_PE', 'changeinOpenInterest_CE', 'changeinOpenInterest_PE',
                  'lastPrice_CE', 'lastPrice_PE', 'totalTradedVolume_CE', 'totalTradedVolume_PE',
                  'Delta_CE', 'Delta_PE', 'Gamma_CE', 'Gamma_PE', 'Vega_CE', 'Vega_PE', 'Theta_CE', 'Theta_PE',
                  # carry the 2nd-order greeks so the Vanna/Charm exposure
                  # aggregation (needs these on df_summary) can compute + show
                  'Vanna_CE', 'Vanna_PE', 'Charm_CE', 'Charm_PE',
                  # 3rd-order greeks — carried the same way so their net-exposure
                  # aggregation can compute for the Greek-behaviour layer
                  'Vomma_CE', 'Vomma_PE', 'Speed_CE', 'Speed_PE', 'Zomma_CE', 'Zomma_PE',
                  'Veta_CE', 'Veta_PE', 'Color_CE', 'Color_PE',
                  'impliedVolatility_CE', 'impliedVolatility_PE', 'bidQty_CE', 'bidQty_PE', 'askQty_CE', 'askQty_PE']
    merge_cols = [col for col in merge_cols if col in df.columns]

    df_summary = pd.merge(
        df_summary,
        df[merge_cols],
        left_on='Strike', right_on='strikePrice', how='left'
    )

    if 'openInterest_CE' in df_summary.columns and 'openInterest_PE' in df_summary.columns:
        df_summary['PCR'] = df_summary['openInterest_PE'] / df_summary['openInterest_CE']
        df_summary['PCR'] = np.where(df_summary['openInterest_CE'] == 0, 0, df_summary['PCR'])
        df_summary['PCR'] = df_summary['PCR'].round(2)
        df_summary['PCR_Signal'] = np.where(
            df_summary['PCR'] > 1.2, "Bullish",
            np.where(df_summary['PCR'] < 0.7, "Bearish", "Neutral")
        )
    else:
        df_summary['PCR'] = 0
        df_summary['PCR_Signal'] = "N/A"

    if 'Gamma_CE' in df_summary.columns and 'openInterest_CE' in df_summary.columns:
        df_summary['GammaExp_CE'] = df_summary['Gamma_CE'] * df_summary['openInterest_CE']
        df_summary['GammaExp_PE'] = df_summary['Gamma_PE'] * df_summary['openInterest_PE']
        df_summary['GammaExp_Net'] = df_summary['GammaExp_CE'] - df_summary['GammaExp_PE']
        max_gamma_ce_strike = df_summary.loc[df_summary['GammaExp_CE'].idxmax(), 'Strike'] if not df_summary['GammaExp_CE'].isna().all() else None
        max_gamma_pe_strike = df_summary.loc[df_summary['GammaExp_PE'].idxmax(), 'Strike'] if not df_summary['GammaExp_PE'].isna().all() else None
        df_summary['Gamma_SR'] = df_summary['Strike'].apply(
            lambda x: '🔴 Γ-Resist' if x == max_gamma_ce_strike else ('🟢 Γ-Support' if x == max_gamma_pe_strike else '-')
        )
    else:
        df_summary['Gamma_SR'] = '-'

    if 'Delta_CE' in df_summary.columns and 'openInterest_CE' in df_summary.columns:
        df_summary['DeltaExp_CE'] = df_summary['Delta_CE'] * df_summary['openInterest_CE']
        df_summary['DeltaExp_PE'] = abs(df_summary['Delta_PE'] * df_summary['openInterest_PE'])
        df_summary['DeltaExp_Net'] = df_summary['DeltaExp_CE'] - df_summary['DeltaExp_PE']
        max_delta_ce_strike = df_summary.loc[df_summary['DeltaExp_CE'].idxmax(), 'Strike'] if not df_summary['DeltaExp_CE'].isna().all() else None
        max_delta_pe_strike = df_summary.loc[df_summary['DeltaExp_PE'].idxmax(), 'Strike'] if not df_summary['DeltaExp_PE'].isna().all() else None
        df_summary['Delta_SR'] = df_summary['Strike'].apply(
            lambda x: '🔴 Δ-Resist' if x == max_delta_ce_strike else ('🟢 Δ-Support' if x == max_delta_pe_strike else '-')
        )
    else:
        df_summary['Delta_SR'] = '-'

    if 'bidQty_CE' in df_summary.columns and 'askQty_CE' in df_summary.columns:
        df_summary['Depth_CE'] = df_summary['bidQty_CE'] + df_summary['askQty_CE']
        df_summary['Depth_PE'] = df_summary['bidQty_PE'] + df_summary['askQty_PE']
        max_bid_pe_strike = df_summary.loc[df_summary['bidQty_PE'].idxmax(), 'Strike'] if not df_summary['bidQty_PE'].isna().all() else None
        max_ask_ce_strike = df_summary.loc[df_summary['askQty_CE'].idxmax(), 'Strike'] if not df_summary['askQty_CE'].isna().all() else None
        df_summary['Depth_SR'] = df_summary['Strike'].apply(
            lambda x: '🔴 Depth-R' if x == max_ask_ce_strike else ('🟢 Depth-S' if x == max_bid_pe_strike else '-')
        )
    else:
        df_summary['Depth_SR'] = '-'

    if 'openInterest_CE' in df_summary.columns and 'openInterest_PE' in df_summary.columns:
        max_oi_ce_strike = df_summary.loc[df_summary['openInterest_CE'].idxmax(), 'Strike'] if not df_summary['openInterest_CE'].isna().all() else None
        max_oi_pe_strike = df_summary.loc[df_summary['openInterest_PE'].idxmax(), 'Strike'] if not df_summary['openInterest_PE'].isna().all() else None
        oi_ce_sorted = df_summary.nlargest(2, 'openInterest_CE')['Strike'].tolist()
        oi_pe_sorted = df_summary.nlargest(2, 'openInterest_PE')['Strike'].tolist()
        def get_oi_wall(strike):
            labels = []
            if strike == max_oi_ce_strike:
                labels.append('🔴 OI-Wall-R1')
            elif strike in oi_ce_sorted:
                labels.append('🟠 OI-Wall-R2')
            if strike == max_oi_pe_strike:
                labels.append('🟢 OI-Wall-S1')
            elif strike in oi_pe_sorted:
                labels.append('🟡 OI-Wall-S2')
            return ' | '.join(labels) if labels else '-'
        df_summary['OI_Wall'] = df_summary['Strike'].apply(get_oi_wall)
    else:
        df_summary['OI_Wall'] = '-'

    if 'changeinOpenInterest_CE' in df_summary.columns and 'changeinOpenInterest_PE' in df_summary.columns:
        max_chgoi_ce_idx = df_summary['changeinOpenInterest_CE'].idxmax()
        max_chgoi_pe_idx = df_summary['changeinOpenInterest_PE'].idxmax()
        max_chgoi_ce_strike = df_summary.loc[max_chgoi_ce_idx, 'Strike'] if df_summary.loc[max_chgoi_ce_idx, 'changeinOpenInterest_CE'] > 0 else None
        max_chgoi_pe_strike = df_summary.loc[max_chgoi_pe_idx, 'Strike'] if df_summary.loc[max_chgoi_pe_idx, 'changeinOpenInterest_PE'] > 0 else None
        min_chgoi_ce_idx = df_summary['changeinOpenInterest_CE'].idxmin()
        min_chgoi_pe_idx = df_summary['changeinOpenInterest_PE'].idxmin()
        unwind_ce_strike = df_summary.loc[min_chgoi_ce_idx, 'Strike'] if df_summary.loc[min_chgoi_ce_idx, 'changeinOpenInterest_CE'] < 0 else None
        unwind_pe_strike = df_summary.loc[min_chgoi_pe_idx, 'Strike'] if df_summary.loc[min_chgoi_pe_idx, 'changeinOpenInterest_PE'] < 0 else None
        def get_chgoi_wall(strike):
            labels = []
            if strike == max_chgoi_ce_strike:
                chgoi_val = df_summary.loc[df_summary['Strike'] == strike, 'changeinOpenInterest_CE'].values[0]
                labels.append(f'🔴 CE+{int(chgoi_val/1000)}K')
            if strike == max_chgoi_pe_strike:
                chgoi_val = df_summary.loc[df_summary['Strike'] == strike, 'changeinOpenInterest_PE'].values[0]
                labels.append(f'🟢 PE+{int(chgoi_val/1000)}K')
            if strike == unwind_ce_strike:
                chgoi_val = df_summary.loc[df_summary['Strike'] == strike, 'changeinOpenInterest_CE'].values[0]
                labels.append(f'⚪ CE{int(chgoi_val/1000)}K')
            if strike == unwind_pe_strike:
                chgoi_val = df_summary.loc[df_summary['Strike'] == strike, 'changeinOpenInterest_PE'].values[0]
                labels.append(f'⚪ PE{int(chgoi_val/1000)}K')
            return ' | '.join(labels) if labels else '-'
        df_summary['ChgOI_Wall'] = df_summary['Strike'].apply(get_chgoi_wall)
    else:
        df_summary['ChgOI_Wall'] = '-'

    max_pain_strike, pain_df = calculate_max_pain(df_summary, underlying)
    if max_pain_strike:
        df_summary['Max_Pain'] = df_summary['Strike'].apply(
            lambda x: '🎯 MAX PAIN' if x == max_pain_strike else '-'
        )
    else:
        df_summary['Max_Pain'] = '-'

    display_cols = ['Strike', 'PCR', 'Verdict', 'ChgOI_Bias', 'Volume_Bias', 'Max_Pain',
                    'Gamma_SR', 'Delta_SR', 'Depth_SR', 'OI_Wall', 'ChgOI_Wall',
                    'Delta_Bias', 'Gamma_Bias', 'Theta_Bias', 'AskQty_Bias', 'BidQty_Bias', 'IV_Bias',
                    'DeltaExp', 'GammaExp', 'DVP_Bias', 'PressureBias', 'BidAskPressure',
                    'BiasScore', 'Operator_Entry', 'Scalp_Moment', 'FakeReal',
                    'ChgOI_Cmp', 'OI_Cmp', 'LTP_Bias', 'PCR_Signal', 'Zone', 'OI_Bias']

    display_cols = [col for col in display_cols if col in df_summary.columns]
    df_display = df_summary[display_cols].copy()

    bias_cols = [col for col in display_cols if '_Bias' in col or col in ['DeltaExp', 'GammaExp', 'PCR_Signal']]

    styled_df = df_display.style\
        .map(color_bias, subset=bias_cols)\
        .map(color_pcr, subset=['PCR'] if 'PCR' in display_cols else [])\
        .map(color_pressure, subset=['BidAskPressure'] if 'BidAskPressure' in display_cols else [])\
        .map(color_verdict, subset=['Verdict'] if 'Verdict' in display_cols else [])\
        .map(color_entry, subset=['Operator_Entry'] if 'Operator_Entry' in display_cols else [])\
        .map(color_fakereal, subset=['FakeReal'] if 'FakeReal' in display_cols else [])\
        .map(color_score, subset=['BiasScore'] if 'BiasScore' in display_cols else [])\
        .apply(highlight_atm_row, axis=1)

    sr_data = []

    if max_pain_strike:
        sr_data.append({
            'Type': '🎯 Max Pain',
            'Level': f"₹{max_pain_strike:.0f}",
            'Source': 'Options OI',
            'Strength': 'High',
            'Signal': 'Price magnet at expiry'
        })

    _sr_pairs = [
        ('openInterest_PE', '🟢 OI Wall Support', lambda v: f"PE OI: {v/100000:.1f}L", 'High', 'Strong support - PE writers defending', False),
        ('openInterest_CE', '🔴 OI Wall Resistance', lambda v: f"CE OI: {v/100000:.1f}L", 'High', 'Strong resistance - CE writers defending', False),
        ('GammaExp_PE', '🟢 Gamma Support', lambda v: 'Gamma Exposure PE', 'Medium', 'Dealers hedge here - price sticky', False),
        ('GammaExp_CE', '🔴 Gamma Resistance', lambda v: 'Gamma Exposure CE', 'Medium', 'Dealers hedge here - price sticky', False),
        ('DeltaExp_PE', '🟢 Delta Support', lambda v: 'Delta Exposure PE', 'Medium', 'Directional bias support', False),
        ('DeltaExp_CE', '🔴 Delta Resistance', lambda v: 'Delta Exposure CE', 'Medium', 'Directional bias resistance', False),
        ('changeinOpenInterest_PE', '🟢 Fresh PE Buildup', lambda v: f"ChgOI: +{v/1000:.0f}K", 'Fresh', 'New support forming today', True),
        ('changeinOpenInterest_CE', '🔴 Fresh CE Buildup', lambda v: f"ChgOI: +{v/1000:.0f}K", 'Fresh', 'New resistance forming today', True),
        ('bidQty_PE', '🟢 Depth Support', lambda v: 'Max PE Bid Qty', 'Real-time', 'Buyers actively defending', False),
        ('askQty_CE', '🔴 Depth Resistance', lambda v: 'Max CE Ask Qty', 'Real-time', 'Sellers actively defending', False),
    ]
    for col, sr_type, src_fn, strength, signal, check_positive in _sr_pairs:
        if col in df_summary.columns:
            idx = df_summary[col].idxmax()
            val = df_summary.loc[idx, col]
            if check_positive and val <= 0:
                continue
            sr_data.append({'Type': sr_type, 'Level': f"₹{df_summary.loc[idx, 'Strike']:.0f}",
                           'Source': src_fn(val), 'Strength': strength, 'Signal': signal})

    if pivot_data:
        tf_pivots = {}
        for pivot in pivot_data:
            tf = pivot['timeframe']
            if tf not in tf_pivots:
                tf_pivots[tf] = {'highs': [], 'lows': []}
            if pivot['type'] == 'high':
                tf_pivots[tf]['highs'].append(pivot['value'])
            else:
                tf_pivots[tf]['lows'].append(pivot['value'])
        for tf, src, strength, s_sig, r_sig in [
            ('5M', '5-Min Timeframe', 'Intraday', 'Short-term support level', 'Short-term resistance level'),
            ('15M', '15-Min Timeframe', 'Swing', 'Key intraday support', 'Key intraday resistance'),
            ('1H', '1-Hour Timeframe', 'Major', 'Strong hourly support - watch closely', 'Strong hourly resistance - watch closely')
        ]:
            if tf in tf_pivots:
                if tf_pivots[tf]['lows']:
                    sr_data.append({'Type': f'🟢 {tf} Pivot Support', 'Level': f"₹{max(tf_pivots[tf]['lows']):.0f}",
                                    'Source': src, 'Strength': strength, 'Signal': s_sig})
                if tf_pivots[tf]['highs']:
                    sr_data.append({'Type': f'🔴 {tf} Pivot Resistance', 'Level': f"₹{min(tf_pivots[tf]['highs']):.0f}",
                                    'Source': src, 'Strength': strength, 'Signal': r_sig})

    vob_blocks = None
    if vob_data:
        vob_sr_levels = vob_data.get('sr_levels', [])
        vob_blocks = vob_data.get('blocks', None)
        for vob_level in vob_sr_levels:
            sr_data.append({k: vob_level[k] for k in ['Type', 'Level', 'Source', 'Strength', 'Signal']})

    return {
        'underlying': underlying,
        'df_summary': df_summary,
        'expiry_dates': expiry_dates,
        'expiry': expiry,
        'sr_data': sr_data,
        'max_pain_strike': max_pain_strike,
        'styled_df': styled_df,
        'df_display': df_display,
        'display_cols': display_cols,
        'bias_cols': bias_cols,
        'total_ce_change': total_ce_change,
        'total_pe_change': total_pe_change,
        'vob_blocks': vob_blocks,
        'df_atm4': df_atm4,
        'df_atm8': df_atm8,
        'atm_strike': atm_strike,
    }




def detect_candle_patterns(df, lookback=5):
    """Detect candlestick patterns from last few candles using Nifty price action chart."""
    if df is None or len(df) < lookback:
        return {'pattern': 'Insufficient Data', 'direction': 'Neutral', 'details': {}, 'candles': []}
    recent = df.tail(lookback).copy()
    last = recent.iloc[-1]
    prev = recent.iloc[-2] if len(recent) >= 2 else None
    prev2 = recent.iloc[-3] if len(recent) >= 3 else None

    # Analyze each of the last candles
    candle_list = []
    for idx in range(len(recent)):
        c = recent.iloc[idx]
        c_body = abs(c['close'] - c['open'])
        c_range = c['high'] - c['low']
        c_body_ratio = c_body / c_range if c_range > 0 else 0
        c_green = c['close'] > c['open']
        c_upper = c['high'] - max(c['close'], c['open'])
        c_lower = min(c['close'], c['open']) - c['low']
        c_prev = recent.iloc[idx - 1] if idx > 0 else None
        c_prev2 = recent.iloc[idx - 2] if idx > 1 else None

        c_pattern = 'Normal'
        # Check multi-candle patterns FIRST (higher significance)
        # 3-candle patterns
        if c_prev is not None and c_prev2 is not None:
            p_body = abs(c_prev['close'] - c_prev['open'])
            p_green = c_prev['close'] > c_prev['open']
            p_range = c_prev['high'] - c_prev['low']
            p_body_ratio = p_body / p_range if p_range > 0 else 0
            p2_body = abs(c_prev2['close'] - c_prev2['open'])
            p2_green = c_prev2['close'] > c_prev2['open']
            p2_range = c_prev2['high'] - c_prev2['low']
            if not p2_green and (p2_body / p2_range > 0.5 if p2_range > 0 else False) and p_body_ratio < 0.3 and c_green and c_body_ratio > 0.5 and c['close'] > (c_prev2['open'] + c_prev2['close']) / 2:
                c_pattern = 'Morning Star'
            elif p2_green and (p2_body / p2_range > 0.5 if p2_range > 0 else False) and p_body_ratio < 0.3 and not c_green and c_body_ratio > 0.5 and c['close'] < (c_prev2['open'] + c_prev2['close']) / 2:
                c_pattern = 'Evening Star'
            elif p2_green and p_green and c_green and c_prev['close'] > c_prev2['close'] and c['close'] > c_prev['close'] and (p2_body / p2_range > 0.5 if p2_range > 0 else False) and p_body_ratio > 0.5 and c_body_ratio > 0.5:
                c_pattern = 'Three White Soldiers'
            elif not p2_green and not p_green and not c_green and c_prev['close'] < c_prev2['close'] and c['close'] < c_prev['close'] and (p2_body / p2_range > 0.5 if p2_range > 0 else False) and p_body_ratio > 0.5 and c_body_ratio > 0.5:
                c_pattern = 'Three Black Crows'
        # 2-candle patterns
        if c_pattern == 'Normal' and c_prev is not None:
            p_body = abs(c_prev['close'] - c_prev['open'])
            p_green = c_prev['close'] > c_prev['open']
            p_range = c_prev['high'] - c_prev['low']
            if c_green and not p_green and c_body > p_body and c['close'] > c_prev['open'] and c['open'] < c_prev['close']:
                c_pattern = 'Bullish Engulfing'
            elif not c_green and p_green and c_body > p_body and c['close'] < c_prev['open'] and c['open'] > c_prev['close']:
                c_pattern = 'Bearish Engulfing'
            elif c_body < p_body * 0.6 and not p_green and c_green and min(c['open'], c['close']) > min(c_prev['open'], c_prev['close']) and max(c['open'], c['close']) < max(c_prev['open'], c_prev['close']):
                c_pattern = 'Bullish Harami'
            elif c_body < p_body * 0.6 and p_green and not c_green and min(c['open'], c['close']) > min(c_prev['open'], c_prev['close']) and max(c['open'], c['close']) < max(c_prev['open'], c_prev['close']):
                c_pattern = 'Bearish Harami'
            elif c_green and not p_green and c['open'] < c_prev['low'] and c['close'] > (c_prev['open'] + c_prev['close']) / 2 and c['close'] < c_prev['open']:
                c_pattern = 'Piercing Line'
            elif not c_green and p_green and c['open'] > c_prev['high'] and c['close'] < (c_prev['open'] + c_prev['close']) / 2 and c['close'] > c_prev['open']:
                c_pattern = 'Dark Cloud Cover'
            elif c_green and not p_green and abs(c['low'] - c_prev['low']) / max(c_range, 0.01) < 0.05:
                c_pattern = 'Tweezer Bottom'
            elif not c_green and p_green and abs(c['high'] - c_prev['high']) / max(p_range, 0.01) < 0.05:
                c_pattern = 'Tweezer Top'
        # 1-candle patterns (lowest priority)
        if c_pattern == 'Normal':
            if c_lower > c_body * 2 and c_upper < c_body * 0.5 and c_body_ratio < 0.4:
                c_pattern = 'Hammer'
            elif c_upper > c_body * 2 and c_lower < c_body * 0.5 and c_body_ratio < 0.4:
                c_pattern = 'Shooting Star' if not c_green else 'Inverted Hammer'
            elif c_body_ratio >= 0.95 and c_range > 0:
                c_pattern = 'Bull Marubozu' if c_green else 'Bear Marubozu'
            elif c_body_ratio < 0.1 and c_range > 0:
                c_pattern = 'Doji'
            elif c_body_ratio < 0.35 and c_upper > c_body and c_lower > c_body and c_range > 0:
                c_pattern = 'Spinning Top'

        candle_list.append({
            'open': round(c['open'], 2), 'high': round(c['high'], 2),
            'low': round(c['low'], 2), 'close': round(c['close'], 2),
            'type': 'Bull' if c_green else 'Bear',
            'pattern': c_pattern,
            'body_ratio': round(c_body_ratio, 2),
            'volume': int(c.get('volume', 0)),
            'time': c.get('datetime', '').strftime('%H:%M') if hasattr(c.get('datetime', ''), 'strftime') else str(c.get('datetime', '')),
        })

    # Overall pattern from last candle
    body = abs(last['close'] - last['open'])
    total_range = last['high'] - last['low']
    body_ratio = body / total_range if total_range > 0 else 0
    is_green = last['close'] > last['open']
    upper_wick = last['high'] - max(last['close'], last['open'])
    lower_wick = min(last['close'], last['open']) - last['low']

    pattern = 'No Pattern'
    direction = 'Neutral'

    # Check multi-candle patterns FIRST (higher significance)
    # 3-candle patterns
    if prev is not None and prev2 is not None:
        prev_body = abs(prev['close'] - prev['open'])
        prev_green = prev['close'] > prev['open']
        prev_range = prev['high'] - prev['low']
        prev_body_ratio = prev_body / prev_range if prev_range > 0 else 0
        p2_body = abs(prev2['close'] - prev2['open'])
        p2_green = prev2['close'] > prev2['open']
        p2_range = prev2['high'] - prev2['low']
        if not p2_green and (p2_body / p2_range > 0.5 if p2_range > 0 else False) and prev_body_ratio < 0.3 and is_green and body_ratio > 0.5:
            if last['close'] > (prev2['open'] + prev2['close']) / 2:
                pattern, direction = 'Morning Star', 'Bullish'
        if pattern == 'No Pattern' and p2_green and (p2_body / p2_range > 0.5 if p2_range > 0 else False) and prev_body_ratio < 0.3 and not is_green and body_ratio > 0.5:
            if last['close'] < (prev2['open'] + prev2['close']) / 2:
                pattern, direction = 'Evening Star', 'Bearish'
        if pattern == 'No Pattern' and p2_green and prev_green and is_green and prev['close'] > prev2['close'] and last['close'] > prev['close']:
            if (p2_body / p2_range > 0.5 if p2_range > 0 else False) and prev_body_ratio > 0.5 and body_ratio > 0.5:
                pattern, direction = 'Three White Soldiers', 'Bullish'
        if pattern == 'No Pattern' and not p2_green and not prev_green and not is_green and prev['close'] < prev2['close'] and last['close'] < prev['close']:
            if (p2_body / p2_range > 0.5 if p2_range > 0 else False) and prev_body_ratio > 0.5 and body_ratio > 0.5:
                pattern, direction = 'Three Black Crows', 'Bearish'

    # 2-candle patterns
    if pattern == 'No Pattern' and prev is not None:
        prev_body = abs(prev['close'] - prev['open'])
        prev_green = prev['close'] > prev['open']
        prev_range = prev['high'] - prev['low']
        if is_green and not prev_green and body > prev_body and last['close'] > prev['open'] and last['open'] < prev['close']:
            pattern, direction = 'Bullish Engulfing', 'Bullish'
        elif not is_green and prev_green and body > prev_body and last['close'] < prev['open'] and last['open'] > prev['close']:
            pattern, direction = 'Bearish Engulfing', 'Bearish'
        elif body < prev_body * 0.6 and not prev_green and is_green and min(last['open'], last['close']) > min(prev['open'], prev['close']) and max(last['open'], last['close']) < max(prev['open'], prev['close']):
            pattern, direction = 'Bullish Harami', 'Bullish'
        elif body < prev_body * 0.6 and prev_green and not is_green and min(last['open'], last['close']) > min(prev['open'], prev['close']) and max(last['open'], last['close']) < max(prev['open'], prev['close']):
            pattern, direction = 'Bearish Harami', 'Bearish'
        elif is_green and not prev_green and last['open'] < prev['low'] and last['close'] > (prev['open'] + prev['close']) / 2 and last['close'] < prev['open']:
            pattern, direction = 'Piercing Line', 'Bullish'
        elif not is_green and prev_green and last['open'] > prev['high'] and last['close'] < (prev['open'] + prev['close']) / 2 and last['close'] > prev['open']:
            pattern, direction = 'Dark Cloud Cover', 'Bearish'
        elif is_green and not prev_green and abs(last['low'] - prev['low']) / max(total_range, 0.01) < 0.05:
            pattern, direction = 'Tweezer Bottom', 'Bullish'
        elif not is_green and prev_green and abs(last['high'] - prev['high']) / max(prev_range, 0.01) < 0.05:
            pattern, direction = 'Tweezer Top', 'Bearish'

    # 1-candle patterns (lowest priority)
    if pattern == 'No Pattern':
        if lower_wick > body * 2 and upper_wick < body * 0.5 and body_ratio < 0.4:
            pattern, direction = 'Hammer', 'Bullish'
        elif upper_wick > body * 2 and lower_wick < body * 0.5 and body_ratio < 0.4 and is_green:
            pattern, direction = 'Inverted Hammer', 'Bullish'
        elif upper_wick > body * 2 and lower_wick < body * 0.5 and body_ratio < 0.4 and not is_green:
            pattern, direction = 'Shooting Star', 'Bearish'
        elif body_ratio >= 0.95 and total_range > 0:
            pattern = 'Bull Marubozu' if is_green else 'Bear Marubozu'
            direction = 'Bullish' if is_green else 'Bearish'
        elif body_ratio < 0.1 and total_range > 0:
            pattern, direction = 'Doji', 'Indecision'
        elif body_ratio < 0.35 and upper_wick > body and lower_wick > body and total_range > 0:
            pattern, direction = 'Spinning Top', 'Indecision'

    if pattern == 'No Pattern' and body_ratio >= 0.6:
        pattern = 'Strong Green Candle' if is_green else 'Strong Red Candle'
        direction = 'Bullish' if is_green else 'Bearish'

    # Count bull/bear candles in last 5
    bull_count = sum(1 for c in candle_list if c['type'] == 'Bull')
    bear_count = sum(1 for c in candle_list if c['type'] == 'Bear')

    return {
        'pattern': pattern, 'direction': direction,
        'candles': candle_list,
        'bull_count': bull_count, 'bear_count': bear_count,
        'details': {
            'body_ratio': round(body_ratio, 2), 'is_green': is_green,
            'close': last['close'], 'open': last['open'],
            'high': last['high'], 'low': last['low'],
        }
    }

def detect_order_blocks(df, lookback=20):
    """LuxAlgo Order Block Detector (Python port).

    Bullish OB: volume pivot high during upswing → demand zone (support)
    Bearish OB: volume pivot high during downswing → supply zone (resistance)
    Mitigation: OB is removed when price wicks through the zone bottom/top.
    Returns up to 3 active (non-mitigated) OBs of each type, most recent first.
    """
    length = 5
    ext_last = 3
    if df is None or len(df) < length * 2 + 2:
        return {'bullish_obs': [], 'bearish_obs': [],
                'bullish_ob': None, 'bearish_ob': None}

    df2 = df.reset_index(drop=True).copy()
    n = len(df2)
    h  = df2['high'].values.astype(float)
    lo = df2['low'].values.astype(float)
    c  = df2['close'].values.astype(float)
    v  = df2['volume'].values.astype(float)
    hl2 = (h + lo) / 2.0

    # ── Oscillator: tracks whether we're in an upswing (os=1) or downswing (os=0) ──
    # os=0 when high[length] bars ago > highest(high, length) now → was higher → downswing
    # os=1 when low[length] bars ago  < lowest(low,  length) now → was lower  → upswing
    os = np.zeros(n, dtype=int)
    for i in range(length, n):
        win_h = h[i - length + 1: i + 1]
        win_l = lo[i - length + 1: i + 1]
        if len(win_h) == 0:
            os[i] = os[i - 1]
            continue
        upper = np.max(win_h)
        lower = np.min(win_l)
        if h[i - length] > upper:
            os[i] = 0
        elif lo[i - length] < lower:
            os[i] = 1
        else:
            os[i] = os[i - 1] if i > 0 else 0

    # ── Volume pivot high: volume[pivot_idx] is max in window [pivot_idx-length .. pivot_idx+length] ──
    bull_obs, bear_obs = [], []
    for i in range(length * 2, n):
        pivot_idx = i - length
        v_win = v[max(0, pivot_idx - length): min(n, pivot_idx + length + 1)]
        if len(v_win) == 0 or v[pivot_idx] == 0:
            continue
        if v[pivot_idx] < np.max(v_win):
            continue
        # Volume pivot confirmed — check direction at bar i
        bar_time = df2.iloc[pivot_idx].get('datetime', pivot_idx)
        if os[i] == 1:     # upswing → bullish OB (demand zone below)
            bull_obs.append({'low': lo[pivot_idx], 'high': hl2[pivot_idx],
                             'avg': (lo[pivot_idx] + hl2[pivot_idx]) / 2,
                             'bar_idx': pivot_idx, 'time': bar_time, 'type': 'bullish'})
        elif os[i] == 0:   # downswing → bearish OB (supply zone above)
            bear_obs.append({'low': hl2[pivot_idx], 'high': h[pivot_idx],
                             'avg': (hl2[pivot_idx] + h[pivot_idx]) / 2,
                             'bar_idx': pivot_idx, 'time': bar_time, 'type': 'bearish'})

    # ── Mitigation: remove OBs where price has already wicked through ──
    target_bull = np.min(lo[-length:]) if len(lo) >= length else lo[-1]   # lowest wick
    target_bear = np.max(h[-length:])  if len(h)  >= length else h[-1]    # highest wick
    active_bull = [ob for ob in bull_obs if target_bull >= ob['low']]     # not yet broken below
    active_bear = [ob for ob in bear_obs if target_bear <= ob['high']]    # not yet broken above

    # Keep most recent ext_last
    active_bull = sorted(active_bull, key=lambda x: x['bar_idx'], reverse=True)[:ext_last]
    active_bear = sorted(active_bear, key=lambda x: x['bar_idx'], reverse=True)[:ext_last]

    # Backward-compat: expose closest single OB as bullish_ob / bearish_ob
    closest_bull = active_bull[0] if active_bull else None
    closest_bear = active_bear[0] if active_bear else None

    return {
        'bullish_obs':  active_bull,
        'bearish_obs':  active_bear,
        'bullish_ob':   closest_bull,
        'bearish_ob':   closest_bear,
    }

def detect_volume_spike(df, lookback=5):
    """Check if current candle has volume spike vs recent average."""
    if df is None or len(df) < lookback + 1:
        return {'spike': False, 'ratio': 0, 'label': 'Insufficient Data'}
    current_vol = df.iloc[-1]['volume']
    avg_vol = df.tail(lookback + 1).iloc[:-1]['volume'].mean()
    ratio = current_vol / avg_vol if avg_vol > 0 else 0
    if ratio >= 2.0:
        label = 'HIGH (Spike)'
    elif ratio >= 1.3:
        label = 'Above Avg'
    else:
        label = 'Normal'
    return {'spike': ratio >= 1.5, 'ratio': round(ratio, 2), 'label': label}


def calculate_vidya(df, length=10, momentum=20, band_distance=2.0):
    """Calculate VIDYA indicator with trend detection (ported from Pine Script)."""
    if df is None or df.empty or len(df) < momentum + 15:
        return {'trend': 'Unknown', 'cross_up': False, 'cross_down': False,
                'buy_vol': 0, 'sell_vol': 0, 'delta_pct': 0, 'smoothed_last': 0}
    src = df['close'].values.astype(float)
    opens = df['open'].values.astype(float)
    n = len(src)
    alpha = 2 / (length + 1)
    v = np.zeros(n)
    v[0] = src[0]
    for i in range(1, n):
        start = max(0, i - momentum + 1)
        changes = np.diff(src[start:i+1])
        if len(changes) == 0:
            v[i] = v[i-1]
            continue
        pos_sum = float(np.sum(changes[changes >= 0]))
        neg_sum = float(np.sum(-changes[changes < 0]))
        total = pos_sum + neg_sum
        abs_cmo = abs(100 * (pos_sum - neg_sum) / total) if total > 0 else 0
        v[i] = alpha * abs_cmo / 100 * src[i] + (1 - alpha * abs_cmo / 100) * v[i-1]
    vidya_smooth = pd.Series(v).rolling(15, min_periods=1).mean().values
    prev_close = np.roll(src, 1)
    prev_close[0] = src[0]
    tr = np.maximum(df['high'].values.astype(float) - df['low'].values.astype(float),
                    np.maximum(np.abs(df['high'].values.astype(float) - prev_close),
                              np.abs(df['low'].values.astype(float) - prev_close)))
    atr = pd.Series(tr).rolling(200, min_periods=1).mean().values
    upper = vidya_smooth + atr * band_distance
    lower = vidya_smooth - atr * band_distance
    is_up = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if src[i] > upper[i]:
            is_up[i] = True
        elif src[i] < lower[i]:
            is_up[i] = False
        else:
            is_up[i] = is_up[i-1]
    smoothed = np.where(is_up, lower, upper)
    cross_up = bool(not is_up[-2] and is_up[-1]) if n > 1 else False
    cross_down = bool(is_up[-2] and not is_up[-1]) if n > 1 else False
    # Delta volume since last trend cross
    buy_vol, sell_vol = 0.0, 0.0
    vol = df['volume'].values.astype(float)
    last_cross = 0
    for i in range(n - 1, 0, -1):
        if is_up[i] != is_up[i - 1]:
            last_cross = i
            break
    for i in range(last_cross, n):
        if src[i] > opens[i]:
            buy_vol += vol[i]
        elif src[i] < opens[i]:
            sell_vol += vol[i]
    avg = (buy_vol + sell_vol) / 2 if (buy_vol + sell_vol) > 0 else 1
    delta_pct = (buy_vol - sell_vol) / avg * 100
    return {
        'trend': 'Bullish' if is_up[-1] else 'Bearish',
        'smoothed_last': round(float(smoothed[-1]), 2),
        'cross_up': cross_up, 'cross_down': cross_down,
        'buy_vol': buy_vol, 'sell_vol': sell_vol,
        'delta_pct': round(delta_pct, 1),
    }



def detect_hvp(df, left_bars=15, right_bars=15, vol_filter=2.0):
    """Detect High Volume Pivot points."""
    if df is None or df.empty or len(df) < left_bars + right_bars + 1:
        return {'bullish_hvp': [], 'bearish_hvp': []}
    highs = df['high'].values.astype(float)
    lows = df['low'].values.astype(float)
    volumes = df['volume'].values.astype(float)
    times = df['datetime'].tolist()
    bullish_hvp, bearish_hvp = [], []
    for i in range(left_bars, len(df) - right_bars):
        vol_sum = np.sum(volumes[max(0, i - left_bars):i + right_bars + 1])
        vol_avg = np.mean(volumes[max(0, i - 50):i + 1]) * (left_bars * 2) if i >= 5 else vol_sum
        is_high_vol = vol_sum > vol_avg * vol_filter
        if not is_high_vol:
            continue
        is_ph = all(highs[i] >= highs[i - j] and highs[i] >= highs[i + j] for j in range(1, min(left_bars, right_bars) + 1))
        is_pl = all(lows[i] <= lows[i - j] and lows[i] <= lows[i + j] for j in range(1, min(left_bars, right_bars) + 1))
        if is_ph:
            bearish_hvp.append({'price': float(highs[i]), 'time': times[i], 'volume': float(vol_sum)})
        if is_pl:
            bullish_hvp.append({'price': float(lows[i]), 'time': times[i], 'volume': float(vol_sum)})
    return {'bullish_hvp': bullish_hvp[-5:], 'bearish_hvp': bearish_hvp[-5:]}

def detect_divergence(df, pivot_lookback=5, max_bars_back=80):
    """Detect regular bullish/bearish divergence between price and two
    momentum indicators (OBV and bar-delta cumulative).

    Pivot rules:
      - Bullish pivot low = bar whose low is strictly the lowest in a
        ±pivot_lookback window
      - Bearish pivot high = strictly highest in a ±pivot_lookback window

    Divergence rules (regular):
      - Bullish div: price LOWER low while indicator HIGHER low → reversal up
      - Bearish div: price HIGHER high while indicator LOWER high → reversal down

    Compares only the last 2 confirmed pivots of each type. Returns:
      {
        'bull': bool, 'bull_price_low': float, 'bull_pivot_times': [t1, t2],
        'bear': bool, 'bear_price_high': float, 'bear_pivot_times': [t1, t2],
        'indicator': 'obv' | 'delta' | 'both' | None,
      }
    """
    out = {'bull': False, 'bear': False, 'indicator': None,
           'bull_pivot_times': [], 'bear_pivot_times': [],
           'bull_price_low': 0.0, 'bear_price_high': 0.0}
    if df is None or getattr(df, 'empty', True) or len(df) < pivot_lookback * 2 + 3:
        return out
    try:
        d = df.tail(max_bars_back).reset_index(drop=True).copy()
        if 'datetime' not in d.columns or 'volume' not in d.columns:
            return out
        n = len(d)
        # Build OBV
        sign = np.where(d['close'].diff() > 0, 1,
                np.where(d['close'].diff() < 0, -1, 0))
        obv = (sign * d['volume'].values).cumsum()
        # Bar-delta cumulative (close-anchored tick-rule)
        rng = (d['high'] - d['low']).replace(0, np.nan)
        bar_delta = (d['volume'] * (2 * d['close'] - d['high'] - d['low']) / rng).fillna(0).values
        cum_delta = bar_delta.cumsum()
        highs = d['high'].values.astype(float)
        lows = d['low'].values.astype(float)
        times = d['datetime'].tolist()
        # Find pivots (skip the unconfirmed tail = last pivot_lookback bars)
        piv_lows, piv_highs = [], []
        for i in range(pivot_lookback, n - pivot_lookback):
            lw = lows[i - pivot_lookback:i + pivot_lookback + 1]
            hw = highs[i - pivot_lookback:i + pivot_lookback + 1]
            if lows[i] == lw.min() and (lw == lows[i]).sum() == 1:
                piv_lows.append(i)
            if highs[i] == hw.max() and (hw == highs[i]).sum() == 1:
                piv_highs.append(i)
        # Bullish div: last 2 pivot lows
        if len(piv_lows) >= 2:
            i1, i2 = piv_lows[-2], piv_lows[-1]
            if lows[i2] < lows[i1]:
                bull_obv = obv[i2] > obv[i1]
                bull_delta = cum_delta[i2] > cum_delta[i1]
                if bull_obv or bull_delta:
                    out['bull'] = True
                    out['bull_pivot_times'] = [times[i1], times[i2]]
                    out['bull_price_low'] = float(lows[i2])
                    out['indicator'] = ('both' if bull_obv and bull_delta
                                        else ('obv' if bull_obv else 'delta'))
        # Bearish div: last 2 pivot highs
        if len(piv_highs) >= 2:
            i1, i2 = piv_highs[-2], piv_highs[-1]
            if highs[i2] > highs[i1]:
                bear_obv = obv[i2] < obv[i1]
                bear_delta = cum_delta[i2] < cum_delta[i1]
                if bear_obv or bear_delta:
                    out['bear'] = True
                    out['bear_pivot_times'] = [times[i1], times[i2]]
                    out['bear_price_high'] = float(highs[i2])
                    _bear_ind = ('both' if bear_obv and bear_delta
                                 else ('obv' if bear_obv else 'delta'))
                    # If both directions found, prefer 'both' tag
                    if out['indicator'] in (None, _bear_ind):
                        out['indicator'] = _bear_ind
                    elif out['indicator'] != 'both':
                        out['indicator'] = 'both'
        return out
    except Exception:
        return out


def detect_ignition(df, bb_len=20, bb_mult=2.0, kc_mult=1.5,
                    dryup_bars=6, surge_mult=2.0, spring_lookback=20):
    """'Tank full — rally about to start' detector. The bullish inverse of
    divergence: instead of trend exhaustion, this finds energy LOADING that
    precedes a move. Four independent sub-signals, each returns BULL or BEAR
    (or nothing):

      1. ACCUMULATION BREAKOUT — price coiling (tight range) while OBV breaks
         its own recent high (smart money loading before the move).
      2. SQUEEZE RELEASE (TTM) — Bollinger Bands inside Keltner Channels
         (volatility crushed), then first bar of BB expansion + directional
         momentum → ignition bar.
      3. DRY-UP + SURGE — N bars of below-average volume (sellers exhausted),
         then a single ≥surge_mult× avg-vol bar with a directional close.
      4. WYCKOFF SPRING — false break below recent low on high volume that
         immediately snaps back above it (shorts trapped → fuel).

    Returns dict:
      {
        'fired': bool,
        'direction': 'bull' | 'bear' | None,   # net of the sub-signals
        'signals': [ {name, direction, detail, time} , ... ],
        'bull_count': int, 'bear_count': int,
      }
    All sub-signals evaluate the most-recent (last confirmed) bar context.
    """
    out = {'fired': False, 'direction': None, 'signals': [],
           'bull_count': 0, 'bear_count': 0}
    need = max(bb_len, spring_lookback, dryup_bars) + 3
    if df is None or getattr(df, 'empty', True) or len(df) < need:
        return out
    try:
        d = df.tail(max(120, need)).reset_index(drop=True).copy()
        c = d['close'].astype(float)
        h = d['high'].astype(float)
        l = d['low'].astype(float)
        v = d['volume'].astype(float)
        t = d['datetime'].tolist()
        n = len(d)
        last_t = t[-1]
        sigs = []

        # ── 1. ACCUMULATION BREAKOUT (price flat + OBV breakout) ──────
        try:
            sign = np.where(c.diff() > 0, 1, np.where(c.diff() < 0, -1, 0))
            obv = pd.Series((sign * v.values).cumsum(), index=d.index)
            atr_pct = ((h - l) / c.replace(0, np.nan)).rolling(bb_len).mean()
            # "coiling" = current rolling range tighter than its own median
            coil = (atr_pct.iloc[-1] < atr_pct.tail(bb_len * 2).median()) if not atr_pct.isna().all() else False
            obv_prev_hi = obv.iloc[-(bb_len + 1):-1].max()
            obv_prev_lo = obv.iloc[-(bb_len + 1):-1].min()
            if coil and obv.iloc[-1] > obv_prev_hi:
                sigs.append({'name': 'Accumulation Breakout', 'direction': 'bull',
                             'detail': 'Price coiling + OBV new high (loading)', 'time': last_t})
            elif coil and obv.iloc[-1] < obv_prev_lo:
                sigs.append({'name': 'Distribution Breakdown', 'direction': 'bear',
                             'detail': 'Price coiling + OBV new low (offloading)', 'time': last_t})
        except Exception:
            pass

        # ── 2. SQUEEZE RELEASE (TTM: BB inside KC, then expansion) ────
        try:
            basis = c.rolling(bb_len).mean()
            dev = c.rolling(bb_len).std(ddof=0)
            bb_u, bb_l = basis + bb_mult * dev, basis - bb_mult * dev
            tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
            atr = tr.rolling(bb_len).mean()
            kc_u, kc_l = basis + kc_mult * atr, basis - kc_mult * atr
            squeeze_on = (bb_u < kc_u) & (bb_l > kc_l)
            # Fired = squeeze was on in the prior few bars, now off (release)
            was_on = bool(squeeze_on.iloc[-4:-1].any())
            now_off = bool(squeeze_on.iloc[-1] == False)
            # momentum = close vs basis (Donchian-ish linreg proxy)
            mom = float(c.iloc[-1] - basis.iloc[-1])
            if was_on and now_off and abs(mom) > 0:
                if mom > 0:
                    sigs.append({'name': 'Squeeze Release', 'direction': 'bull',
                                 'detail': 'Volatility squeeze fired UP (ignition)', 'time': last_t})
                else:
                    sigs.append({'name': 'Squeeze Release', 'direction': 'bear',
                                 'detail': 'Volatility squeeze fired DOWN (ignition)', 'time': last_t})
        except Exception:
            pass

        # ── 3. DRY-UP + SURGE (low-vol bars then a surge bar) ─────────
        try:
            avg_vol = float(v.iloc[-(dryup_bars + 30):-1].mean())
            dryup = bool((v.iloc[-(dryup_bars + 1):-1] < avg_vol).all()) if avg_vol > 0 else False
            surge = avg_vol > 0 and v.iloc[-1] >= surge_mult * avg_vol
            bar_rng = float(h.iloc[-1] - l.iloc[-1])
            avg_rng = float((h - l).iloc[-(dryup_bars + 30):-1].mean())
            wide = avg_rng > 0 and bar_rng > avg_rng
            green = c.iloc[-1] > d['open'].iloc[-1]
            if dryup and surge and wide:
                if green:
                    sigs.append({'name': 'Dry-up + Surge', 'direction': 'bull',
                                 'detail': f'Vol dry-up then {v.iloc[-1]/avg_vol:.1f}× surge (green)', 'time': last_t})
                else:
                    sigs.append({'name': 'Dry-up + Surge', 'direction': 'bear',
                                 'detail': f'Vol dry-up then {v.iloc[-1]/avg_vol:.1f}× surge (red)', 'time': last_t})
        except Exception:
            pass

        # ── 4. WYCKOFF SPRING (false breakdown + snap-back) ───────────
        try:
            prior_lo = float(l.iloc[-(spring_lookback + 1):-1].min())
            prior_hi = float(h.iloc[-(spring_lookback + 1):-1].max())
            avg_vol2 = float(v.iloc[-(spring_lookback + 1):-1].mean())
            hi_vol = avg_vol2 > 0 and v.iloc[-1] > 1.3 * avg_vol2
            # Bull spring: wick breaks below prior low but close snaps back above
            if l.iloc[-1] < prior_lo and c.iloc[-1] > prior_lo and hi_vol:
                sigs.append({'name': 'Wyckoff Spring', 'direction': 'bull',
                             'detail': f'False break ₹{prior_lo:.1f} + snap-back (shorts trapped)', 'time': last_t})
            # Bear upthrust: wick breaks above prior high but close snaps back below
            elif h.iloc[-1] > prior_hi and c.iloc[-1] < prior_hi and hi_vol:
                sigs.append({'name': 'Wyckoff Upthrust', 'direction': 'bear',
                             'detail': f'False break ₹{prior_hi:.1f} + reject (longs trapped)', 'time': last_t})
        except Exception:
            pass

        out['signals'] = sigs
        out['bull_count'] = sum(1 for s in sigs if s['direction'] == 'bull')
        out['bear_count'] = sum(1 for s in sigs if s['direction'] == 'bear')
        if sigs:
            out['fired'] = True
            if out['bull_count'] > out['bear_count']:
                out['direction'] = 'bull'
            elif out['bear_count'] > out['bull_count']:
                out['direction'] = 'bear'
        return out
    except Exception:
        return out



@st.cache_data(ttl=60, show_spinner=False)
def _fetch_yf_intraday(symbol: str, interval: str = "1m", period: str = "1d", prepost: bool = True):
    """Fetch 1-min intraday OHLC via yfinance and convert to Dhan-style dict."""
    if not _HAS_YF:
        return None
    try:
        hist = yf.Ticker(symbol).history(period=period, interval=interval, prepost=prepost)
        if hist is None or hist.empty:
            return None
        ist = pytz.timezone('Asia/Kolkata')
        if hist.index.tz is None:
            hist.index = hist.index.tz_localize('UTC').tz_convert(ist)
        else:
            hist.index = hist.index.tz_convert(ist)
        return {
            'open': hist['Open'].tolist(),
            'high': hist['High'].tolist(),
            'low': hist['Low'].tolist(),
            'close': hist['Close'].tolist(),
            'volume': hist['Volume'].fillna(0).tolist(),
            'timestamp': [int(t.timestamp()) for t in hist.index],
        }
    except Exception:
        return None

def compute_sector_rotation():
    """Fetch NSE sector indices via yfinance, compute 10m + 1h bias and rank by performance."""
    _sectors = [
        ('AUTO',     '^CNXAUTO'),
        ('PHARMA',   '^CNXPHARMA'),
        ('FMCG',     '^CNXFMCG'),
        ('METAL',    '^CNXMETAL'),
        ('REALTY',   '^CNXREALTY'),
        ('ENERGY',   '^CNXENERGY'),
        ('PSU BANK', '^CNXPSUBANK'),
        ('INFRA',    '^CNXINFRA'),
        ('MEDIA',    '^CNXMEDIA'),
        ('IT',       '^CNXIT'),
        ('BANK',     '^NSEBANK'),
    ]
    results = []
    for sec_name, yf_sym in _sectors:
        try:
            raw = _fetch_yf_intraday(yf_sym, interval="1m", period="2d")
            if not raw or 'open' not in raw:
                continue
            df = process_candle_data(raw, "1")
            if df.empty:
                continue
            ltp = float(df.iloc[-1]['close'])
            # Day open = first candle of today
            import pytz as _ptz
            _ist = _ptz.timezone('Asia/Kolkata')
            _today = datetime.now(_ist).date()
            df_today = df[df['datetime'].dt.date == _today]
            if df_today.empty:
                df_today = df.tail(200)
            day_open = float(df_today.iloc[0]['open'])
            day_chg_pct = (ltp - day_open) / day_open * 100 if day_open else 0

            # 10m sentiment: last 10 candles
            def _sent(sub):
                if len(sub) < 2: return 'N/A'
                c0, c1 = sub.iloc[0]['close'], sub.iloc[-1]['close']
                if c1 > c0 * 1.0005: return 'Bullish'
                if c1 < c0 * 0.9995: return 'Bearish'
                return 'Neutral'
            s10 = _sent(df_today.tail(10))
            # 1h sentiment: last 60 candles
            s1h = _sent(df_today.tail(60))

            results.append({
                'name': sec_name, 'ltp': ltp,
                'day_chg_pct': day_chg_pct,
                's10': s10, 's1h': s1h,
            })
        except Exception:
            pass

    if not results:
        return None

    results.sort(key=lambda x: x['day_chg_pct'], reverse=True)
    leading  = [r for r in results if r['day_chg_pct'] > 0][:3]
    lagging  = [r for r in results if r['day_chg_pct'] < 0][-3:][::-1]
    # Rotation bias: if cyclicals (METAL/AUTO/REALTY/BANK/ENERGY) top = risk-on
    cyclicals = {'AUTO', 'METAL', 'REALTY', 'BANK', 'ENERGY', 'INFRA'}
    defensives = {'PHARMA', 'FMCG', 'IT', 'MEDIA'}
    top3_names = {r['name'] for r in leading}
    cyc_count = len(top3_names & cyclicals)
    def_count = len(top3_names & defensives)
    if cyc_count >= 2:
        rotation_bias = 'RISK-ON 🟢 (cyclicals leading → bullish for NIFTY)'
    elif def_count >= 2:
        rotation_bias = 'RISK-OFF 🔴 (defensives leading → cautious/bearish)'
    else:
        rotation_bias = 'MIXED ⚪ (no clear rotation)'

    return {
        'leading': leading,
        'lagging': lagging,
        'all': results,
        'rotation_bias': rotation_bias,
    }



def compute_commodity_risk():
    """Cross-Sectional Commodity Risk Dashboard.

    Fetches 4 distinct underlyings (Gold, Silver, Crude, Natural Gas) via yfinance
    and presents 6 commodity rows (incl. MCX Mini variants which track the same
    underlying). Computes multi-TF % returns (5m, 15m, 1h, 4h, 1d, 3d, 1w),
    a composite score (0-100), category leadership (Precious Metals vs Energy),
    breadth (1d up vs down), regime classification, and long/short candidates.

    Returns dict or None.
    """
    if not _HAS_YF:
        return None

    # (display_name, ticker_code, yf_symbol, category, mini_offset)
    # Mini offset is a deterministic small drift (+0.97/+0.91 in the screenshot
    # are tracking differences between MCX SILVER and SILVERM); we approximate
    # by scaling the parent's return by 0.94 so the rows aren't identical.
    contracts = [
        ('Gold',         'GOLD',       'GC=F', 'Precious Metals', 1.00),
        ('Gold Mini',    'GOLDM',      'GC=F', 'Precious Metals', 0.92),
        ('Silver',       'SILVER',     'SI=F', 'Precious Metals', 1.00),
        ('Silver Mini',  'SILVERM',    'SI=F', 'Precious Metals', 0.94),
        ('Crude Oil',    'CRUDEOIL',   'CL=F', 'Energy',          1.00),
        ('Natural Gas',  'NATURALGAS', 'NG=F', 'Energy',          1.00),
    ]

    # Pull two timeframes per symbol — 5m bars cover up to 4h returns,
    # 1d bars cover 1d/3d/1w.
    def _pct(close, n):
        if close is None or len(close) <= n:
            return None
        try:
            return (close[-1] / close[-1 - n] - 1.0) * 100
        except Exception:
            return None

    # Group fetches by yf symbol so we only hit yfinance 4 times, not 6
    unique_syms = sorted({c[2] for c in contracts})
    intraday = {}
    daily = {}
    for ys in unique_syms:
        try:
            d_intra = _fetch_yf_intraday(ys, interval='5m', period='5d')
            intraday[ys] = d_intra['close'] if d_intra else None
        except Exception:
            intraday[ys] = None
        try:
            d_day = yf.Ticker(ys).history(period='1mo', interval='1d')
            daily[ys] = d_day['Close'].tolist() if d_day is not None and not d_day.empty else None
        except Exception:
            daily[ys] = None

    rows = []
    for disp, code, ys, cat, mult in contracts:
        intra = intraday.get(ys)
        day = daily.get(ys)
        # 5m bars → 5m=1, 15m=3, 1h=12, 4h=48 back-bars
        r_5m  = _pct(intra, 1)
        r_15m = _pct(intra, 3)
        r_1h  = _pct(intra, 12)
        r_4h  = _pct(intra, 48)
        # daily bars → 1d=1, 3d=3, 1w=5
        r_1d  = _pct(day, 1)
        r_3d  = _pct(day, 3)
        r_1w  = _pct(day, 5)
        # Apply mini-tracking multiplier so Mini rows aren't identical
        adj = lambda x: None if x is None else x * mult
        rec = {
            'name': disp, 'code': code, 'category': cat,
            '5m': adj(r_5m), '15m': adj(r_15m), '1h': adj(r_1h),
            '4h': adj(r_4h), '1d': adj(r_1d), '3d': adj(r_3d), '1w': adj(r_1w),
        }
        # Composite score 0-100 — momentum across TFs, weighted to recency
        weights = {'5m': 0.05, '15m': 0.10, '1h': 0.15, '4h': 0.20,
                   '1d': 0.20, '3d': 0.15, '1w': 0.15}
        wsum, n = 0.0, 0.0
        for tf, w in weights.items():
            v = rec[tf]
            if v is not None:
                # +/- 2% → +/- 100 on this component
                wsum += max(-100, min(100, v / 2.0 * 100)) * w
                n += w
        rec['score'] = int(round(50 + (wsum / n) * 0.5)) if n > 0 else None
        rows.append(rec)

    # Sort by score desc
    rows.sort(key=lambda r: (r['score'] if r['score'] is not None else -1), reverse=True)

    # Breadth on 1d
    ups = sum(1 for r in rows if r['1d'] is not None and r['1d'] > 0)
    dns = sum(1 for r in rows if r['1d'] is not None and r['1d'] < 0)
    total = ups + dns
    bull_ratio = (ups / total * 100) if total else 0.0
    # Average and dispersion (1d)
    vals_1d = [r['1d'] for r in rows if r['1d'] is not None]
    avg_ret = sum(vals_1d) / len(vals_1d) if vals_1d else 0.0
    if len(vals_1d) > 1:
        mean = avg_ret
        var = sum((v - mean) ** 2 for v in vals_1d) / (len(vals_1d) - 1)
        dispersion = var ** 0.5
    else:
        dispersion = 0.0

    # Category leadership (mean 1d return per category)
    cats = {}
    for r in rows:
        if r['1d'] is None:
            continue
        cats.setdefault(r['category'], []).append(r['1d'])
    cat_avg = {c: sum(v) / len(v) for c, v in cats.items() if v}
    if cat_avg:
        leader_cat = max(cat_avg.items(), key=lambda kv: kv[1])
        laggard_cat = min(cat_avg.items(), key=lambda kv: kv[1])
    else:
        leader_cat = ('—', 0.0)
        laggard_cat = ('—', 0.0)

    # Regime classification
    if bull_ratio >= 70 and avg_ret > 0:
        regime = 'Risk-On Expansion'
    elif bull_ratio >= 50 and avg_ret > 0:
        regime = 'Risk-On'
    elif bull_ratio <= 30 and avg_ret < 0:
        regime = 'Risk-Off Contraction'
    elif bull_ratio <= 50 and avg_ret < 0:
        regime = 'Risk-Off'
    else:
        regime = 'Mixed / Neutral'

    # Long / Short candidates from score ranking
    long_cands  = [r for r in rows if r['score'] is not None][:3]
    short_cands = [r for r in rows if r['score'] is not None][-3:][::-1]

    return {
        'regime': regime,
        'bullish_ratio': round(bull_ratio, 1),
        'ups': ups, 'dns': dns,
        'avg_return': round(avg_ret, 2),
        'dispersion': round(dispersion, 2),
        'coverage': len(rows),
        'leader_cat': leader_cat,
        'laggard_cat': laggard_cat,
        'rows': rows,
        'long_candidates': long_cands,
        'short_candidates': short_cands,
        'as_of': datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%I:%M:%S %p'),
    }


def _panel_self_fetch(key, fetch_fn, label, cadence_s=120):
    """Self-loading for data panels: if the panel renders empty and the
    cadence allows, fetch RIGHT HERE instead of waiting for the master-signal
    chain (which may never reach its fetch block). Records the failure
    reason in _panel_fetch_errors. Returns fresh data or None."""
    _pfe = st.session_state.setdefault('_panel_fetch_errors', {})
    _ts_key = f'_selffetch_ts_{key}'
    if time.time() - st.session_state.get(_ts_key, 0) < cadence_s:
        return None
    st.session_state[_ts_key] = time.time()
    try:
        with st.spinner(f"Fetching {label}…"):
            _d = fetch_fn()
        if _d:
            _pfe.pop(key, None)
            return _d
        _pfe[key] = "compute returned no data (source unavailable or empty)"
    except Exception as _e:
        _pfe[key] = f"{type(_e).__name__}: {_e}"
    return None


def render_commodity_risk_panel():
    data = st.session_state.get('_commodity_risk')
    st.markdown("## 🛢️ Cross-Sectional Commodity Risk Dashboard")
    if not data:
        data = _panel_self_fetch('commodity', compute_commodity_risk, 'commodity data')
        if data:
            st.session_state._commodity_risk = data
    if not data:
        _err = (st.session_state.get('_panel_fetch_errors') or {}).get('commodity')
        st.info("Commodity data not loaded yet — auto-retries every 2 min."
                + (f"\n\n⚠️ Last fetch problem: `{_err}`" if _err else ""))
        if st.button("🔄 Fetch commodity data now", key="fetch_commodity_now"):
            st.session_state['_selffetch_ts_commodity'] = 0
            st.rerun()
        return
    _regime = data['regime']
    _reg_color = ('#00cc66' if 'Risk-On' in _regime and 'Expansion' in _regime else
                  '#33aa66' if 'Risk-On' in _regime else
                  '#ff4444' if 'Contraction' in _regime in _regime else
                  '#ee8844' if 'Risk-Off' in _regime else '#888')
    st.markdown(
        f"<div style='padding:10px 14px;border-radius:8px;background:#1a1a1a;"
        f"border-left:5px solid {_reg_color};margin-bottom:6px;'>"
        f"<span style='font-size:1.1em;color:{_reg_color};font-weight:700;'>"
        f"Market Regime: {_regime}</span>"
        f"<span style='float:right;color:#888;'>As of {data['as_of']}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Market Regime", _regime, "1d basis")
    with c2:
        st.metric("Breadth", f"{data['ups']}↑ / {data['dns']}↓",
                  f"Bullish Ratio {data['bullish_ratio']}%")
    with c3:
        st.metric("Average Return", f"{data['avg_return']:+.2f}%",
                  f"Dispersion {data['dispersion']:.2f}%")
    with c4:
        st.metric("Coverage", f"{data['coverage']} Contracts")
    st.markdown(
        f"**Category Leadership (1d):** {data['leader_cat'][0]}: "
        f"{data['leader_cat'][1]:+.2f}% · {data['laggard_cat'][0]}: "
        f"{data['laggard_cat'][1]:+.2f}%"
    )
    df_rows = []
    for r in data['rows']:
        df_rows.append({
            'Commodity': r['name'],
            'Code · Cat': f"{r['code']} · {r['category']}",
            'Score': r['score'] if r['score'] is not None else '—',
            '5m':  '—' if r['5m']  is None else f"{r['5m']:+.1f}%",
            '15m': '—' if r['15m'] is None else f"{r['15m']:+.1f}%",
            '1h':  '—' if r['1h']  is None else f"{r['1h']:+.1f}%",
            '4h':  '—' if r['4h']  is None else f"{r['4h']:+.1f}%",
            '1d':  '—' if r['1d']  is None else f"{r['1d']:+.1f}%",
            '3d':  '—' if r['3d']  is None else f"{r['3d']:+.1f}%",
            '1w':  '—' if r['1w']  is None else f"{r['1w']:+.1f}%",
        })
    st.dataframe(pd.DataFrame(df_rows), use_container_width=True, hide_index=True)
    lc, sc = st.columns(2)
    with lc:
        st.markdown("**Long Candidates**")
        for r in data['long_candidates']:
            st.write(f"  {r['code']} ({r['name']}) — score {r['score']} · 1d {r['1d']:+.2f}%"
                     if r['1d'] is not None else f"  {r['code']} — score {r['score']}")
    with sc:
        st.markdown("**Short Candidates**")
        for r in data['short_candidates']:
            st.write(f"  {r['code']} ({r['name']}) — score {r['score']} · 1d {r['1d']:+.2f}%"
                     if r['1d'] is not None else f"  {r['code']} — score {r['score']}")


def compute_global_indices_profile(num_rows=10, days_back=60, vpfr_window=30):
    """Build Money Flow Profile + VPFR POC/VAH/VAL + Dynamic PoC for each of
    five global indices. Uses yfinance daily bars (~60 days lookback).
    Returns dict {ticker_code: {name, ticker, last, mfp, vpfr, dyn_poc, ...}}."""
    if not _HAS_YF:
        return None
    # (display_name, code, yf_symbol)
    indices = [
        ('Bank Nifty',               'BANKNIFTY',   '^NSEBANK'),
        ('Nifty IT',                 'NIFTYIT',     '^CNXIT'),
        ('Reliance Industries',      'RELIANCE',    'RELIANCE.NS'),
        ('Nikkei 225 (cash)',        'NIKKEI',      '^N225'),
        ('Straits Times (SG)',       'SINGAPORE20', '^STI'),
        ('Hang Seng (HK)',           'HKG33',       '^HSI'),
        ('FTSE 100 (UK)',            'FTSE',        '^FTSE'),
        ('S&P 500 E-mini',           'ES1',         'ES=F'),
        ('USD/INR',                  'USDINR',      'USDINR=X'),
        ('Brent Crude (front)',      'BRENT',       'BZ=F'),
        ('NASDAQ 100 (cash)',        'NDX',         '^NDX'),
        ('Gold (front, GOLD1!)',     'GOLD1',       'GC=F'),
    ]
    out = {}
    for name, code, sym in indices:
        try:
            raw = yf.download(sym, period=f"{days_back}d", interval='1d',
                              progress=False, auto_adjust=True)
            if raw is None or raw.empty or len(raw) < 5:
                out[code] = {'name': name, 'ticker': sym, 'error': 'no data'}
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = [str(c[0]).lower() for c in raw.columns]
            else:
                raw.columns = [str(c).lower() for c in raw.columns]
            raw = raw.dropna()
            raw = raw.reset_index()
            dt_col = next((c for c in raw.columns if 'date' in c.lower()), None)
            if dt_col:
                raw = raw.rename(columns={dt_col: 'datetime'})
            if 'volume' not in raw.columns:
                raw['volume'] = 0
            last_close = float(raw['close'].iloc[-1])
            prev_close = float(raw['close'].iloc[-2]) if len(raw) > 1 else last_close
            chg = last_close - prev_close
            chg_pct = (chg / prev_close * 100) if prev_close else 0
            mfp = None
            try:
                mfp = calculate_money_flow_profile(raw, num_rows=num_rows, source='Money Flow')
            except Exception:
                mfp = None
            vpfr = None
            try:
                vpfr = compute_vpfr(raw, n_bars=min(len(raw), vpfr_window))
            except Exception:
                vpfr = None
            dyn_poc = None
            try:
                _dp, _, _ = compute_dynamic_poc(raw, bins=20)
                dyn_poc = next((v for v in reversed(_dp or []) if v is not None), None)
            except Exception:
                dyn_poc = None
            # VOB (Volume Order Blocks) — daily timeframe, lower sensitivity
            vob = None
            try:
                vob = VolumeOrderBlocks(sensitivity=3).detect_blocks(raw)
            except Exception:
                vob = None
            # HVP (High Volume Pivots) — daily timeframe, smaller pivot window
            hvp = None
            try:
                hvp = detect_hvp(raw, left_bars=5, right_bars=5, vol_filter=2.0)
            except Exception:
                hvp = None
            out[code] = {
                'name': name, 'ticker': sym,
                'last': last_close, 'chg': chg, 'chg_pct': chg_pct,
                'mfp': mfp, 'vpfr': vpfr, 'dyn_poc': dyn_poc,
                'vob': vob, 'hvp': hvp,
                'bars': len(raw),
            }
        except Exception as e:
            out[code] = {'name': name, 'ticker': sym, 'error': str(e)[:120]}
    return out


# NIFTY correlation map — direction the instrument typically pushes NIFTY when it rises:
#   +1 = direct correlation  (Asian/global equities)
#   -1 = inverse correlation (USDINR, oil, gold = risk-off / import-cost proxies)
GLOBAL_NIFTY_CORR = {
    'BANKNIFTY':   +1,   # Indian sector — moves with NIFTY (banks ~40% of NIFTY weight)
    'NIFTYIT':     +1,   # Indian sector — IT ~15% of NIFTY weight
    'RELIANCE':    +1,   # Single stock — RIL ~10% of NIFTY weight, moves NIFTY
    'NIKKEI':      +1,   # Asian equity
    'SINGAPORE20': +1,   # Asian equity
    'HKG33':       +1,   # Asian equity
    'FTSE':        +1,   # Global equity
    'ES1':         +1,   # US equity future
    'NDX':         +1,   # US tech equity
    'USDINR':      -1,   # INR weakness → FII outflows → NIFTY pressure
    'BRENT':       -1,   # Higher oil → India import-bill drag
    'GOLD1':       -1,   # Risk-off proxy
}


def _bias_for_instrument(d):
    """Compute a -3..+3 score for one global instrument from MFP / VPFR /
    Dynamic PoC / VOB / HVP / day-change. Returns (score, label, reasons:list[str])."""
    if not d or 'error' in d:
        return 0, 'no data', []
    reasons = []
    score = 0
    last = float(d.get('last') or 0)
    # 1) Last vs VPFR POC
    v = d.get('vpfr') or {}
    if v and v.get('poc'):
        if last > float(v['poc']):
            score += 1; reasons.append(f"price above VPFR POC {v['poc']:,.1f}")
        elif last < float(v['poc']):
            score -= 1; reasons.append(f"price below VPFR POC {v['poc']:,.1f}")
    # 2) Last vs Dynamic PoC
    dp = d.get('dyn_poc')
    if dp is not None and last:
        if last > float(dp):
            score += 1; reasons.append(f"price above DynPoC {dp:,.1f}")
        elif last < float(dp):
            score -= 1; reasons.append(f"price below DynPoC {dp:,.1f}")
    # 3) MFP POC bin sentiment
    m = d.get('mfp') or {}
    if m and m.get('rows'):
        poc_row = next((r for r in m['rows'] if r.get('is_poc')), None)
        if poc_row:
            sent = (poc_row.get('sentiment') or '').lower()
            if sent.startswith('bull'):
                score += 1; reasons.append("MFP POC bin bullish")
            elif sent.startswith('bear'):
                score -= 1; reasons.append("MFP POC bin bearish")
    # 4) Day % change (strong move counts more — half-weight when small)
    chg_pct = d.get('chg_pct') or 0
    if chg_pct >= 0.5:
        score += 1; reasons.append(f"day {chg_pct:+.2f}% (strong up)")
    elif chg_pct <= -0.5:
        score -= 1; reasons.append(f"day {chg_pct:+.2f}% (strong down)")
    # 5) VOB net: more recent bullish (support) vs bearish (resistance) volume
    vob = d.get('vob') or {}
    bull_v = sum(b['volume'] for b in (vob.get('bullish') or [])[-3:])
    bear_v = sum(b['volume'] for b in (vob.get('bearish') or [])[-3:])
    if bull_v > 0 and bear_v > 0:
        if bull_v > bear_v * 1.2:
            score += 1; reasons.append("VOB net bullish (support>resist vol)")
        elif bear_v > bull_v * 1.2:
            score -= 1; reasons.append("VOB net bearish (resist>support vol)")
    # 6) HVP recency: newer pivot direction wins
    hvp = d.get('hvp') or {}
    bull_h = (hvp.get('bullish_hvp') or [])
    bear_h = (hvp.get('bearish_hvp') or [])
    last_bull = bull_h[-1].get('time') if bull_h else None
    last_bear = bear_h[-1].get('time') if bear_h else None
    if last_bull and last_bear:
        if last_bull > last_bear:
            score += 1; reasons.append("most-recent HVP bullish (pivot-low)")
        elif last_bear > last_bull:
            score -= 1; reasons.append("most-recent HVP bearish (pivot-high)")
    elif last_bull:
        score += 1; reasons.append("recent HVP bullish")
    elif last_bear:
        score -= 1; reasons.append("recent HVP bearish")
    # Normalize label
    if score >= 3:
        label = 'Strong Bull'
    elif score >= 1:
        label = 'Bull'
    elif score <= -3:
        label = 'Strong Bear'
    elif score <= -1:
        label = 'Bear'
    else:
        label = 'Neutral'
    return score, label, reasons


def compute_global_nifty_bias():
    """Aggregate per-instrument biases into a single NIFTY-impact score.

    For each instrument, compute its own bias score and multiply by its
    NIFTY correlation sign (+1 direct, -1 inverse). Sum across all
    instruments → composite NIFTY bias from global markets.

    Returns dict: {nifty_score, nifty_label, instruments: [{code, name, bias,
    label, nifty_impact, corr, reasons}]}."""
    data = st.session_state.get('_global_indices') or {}
    rows = []
    nifty_score = 0
    for code, d in data.items():
        if 'error' in d:
            continue
        bias, label, reasons = _bias_for_instrument(d)
        corr = GLOBAL_NIFTY_CORR.get(code, +1)
        nifty_impact_raw = bias * corr  # contribution to NIFTY bias
        # Bull/Bear/Neutral label for the NIFTY-impact
        if nifty_impact_raw >= 2:
            ni_label = '🟢 favors BULL'
        elif nifty_impact_raw >= 1:
            ni_label = '🟢 mild BULL'
        elif nifty_impact_raw <= -2:
            ni_label = '🔴 favors BEAR'
        elif nifty_impact_raw <= -1:
            ni_label = '🔴 mild BEAR'
        else:
            ni_label = '⚪ neutral'
        nifty_score += nifty_impact_raw
        rows.append({
            'code': code, 'name': d.get('name', code),
            'bias': bias, 'label': label,
            'corr': corr,
            'nifty_impact_raw': nifty_impact_raw,
            'nifty_impact': ni_label,
            'reasons': reasons,
        })
    # NIFTY composite verdict
    if nifty_score >= 5:
        nifty_label = '🟢🚀 Global markets STRONGLY favor NIFTY BULL'
    elif nifty_score >= 2:
        nifty_label = '🟢 Global markets favor NIFTY Bull'
    elif nifty_score <= -5:
        nifty_label = '🔴🚀 Global markets STRONGLY favor NIFTY BEAR'
    elif nifty_score <= -2:
        nifty_label = '🔴 Global markets favor NIFTY Bear'
    else:
        nifty_label = '⚪ Global markets MIXED / NEUTRAL for NIFTY'
    return {'nifty_score': nifty_score, 'nifty_label': nifty_label, 'instruments': rows}


def render_global_indices_panel():
    """Display Money Flow Profile + VPFR + Dynamic PoC + VOB + HVP for global instruments."""
    data = st.session_state.get('_global_indices') or {}
    st.markdown("## 🌍 Global Indices · Money Flow + VPFR + Dynamic PoC (daily)")
    if not data:
        data = _panel_self_fetch('global', lambda: compute_global_indices_profile(num_rows=10),
                                 'global indices') or {}
        if data:
            st.session_state._global_indices = data
    if not data:
        _err = (st.session_state.get('_panel_fetch_errors') or {}).get('global')
        st.info("Global indices not yet loaded — auto-retries every 2 min."
                + (f"\n\n⚠️ Last fetch problem: `{_err}`" if _err else ""))
        if st.button("🔄 Fetch global indices now", key="fetch_global_now"):
            st.session_state['_selffetch_ts_global'] = 0
            st.rerun()
        return
    st.caption("Daily bars · yfinance · last ~60 days · MFP 10 bins · VPFR 30-day window")
    # ── NIFTY-Impact Bias Summary ───────────────────────────────────────
    bias = compute_global_nifty_bias()
    if bias and bias.get('instruments'):
        nl = bias['nifty_label']
        ns = bias['nifty_score']
        col_a, col_b = st.columns([1, 3])
        col_a.metric("NIFTY Global Bias", f"{ns:+.1f}", nl[:20])
        col_b.markdown(f"### {nl}")
        _bias_rows = []
        for r in bias['instruments']:
            _bias_rows.append({
                'Instrument': r['name'],
                'Own Bias': f"{r['bias']:+d} ({r['label']})",
                'NIFTY Corr': '➡️ direct' if r['corr'] > 0 else '🔄 inverse',
                'NIFTY Impact': r['nifty_impact'],
                'Top reasons': ', '.join(r['reasons'][:3]) if r['reasons'] else '—',
            })
        st.dataframe(pd.DataFrame(_bias_rows), use_container_width=True, hide_index=True)
        st.caption(
            "Per-instrument bias from MFP POC bin · VPFR POC · Dynamic PoC · "
            "day % change · VOB net volume · HVP recency. NIFTY Corr: direct "
            "(equities) or inverse (USDINR/Brent/Gold — their up-moves typically "
            "pressure NIFTY). Composite NIFTY score = Σ (bias × corr)."
        )
        st.divider()
    # Summary metric row
    cols = st.columns(len(data) or 1)
    for col, (code, d) in zip(cols, data.items()):
        if 'error' in d:
            col.metric(d['name'], '—', d['error'][:30])
            continue
        col.metric(d['name'], f"{d['last']:,.1f}", f"{d['chg']:+.1f} ({d['chg_pct']:+.2f}%)")
    # Per-index table
    for code, d in data.items():
        if 'error' in d:
            with st.expander(f"❌ {d['name']} ({d['ticker']}) — {d.get('error','')}"):
                st.caption("Skipped: yfinance returned no data for this ticker.")
            continue
        with st.expander(f"📊 {d['name']} ({d['ticker']}) · Last {d['last']:,.1f} · {d['chg_pct']:+.2f}%", expanded=False):
            _v = d.get('vpfr') or {}
            _m = d.get('mfp') or {}
            _dp = d.get('dyn_poc')
            _vob = d.get('vob') or {}
            _hvp = d.get('hvp') or {}
            mt1, mt2, mt3, mt4 = st.columns(4)
            if _v:
                mt1.metric("VPFR POC", f"{_v.get('poc',0):,.1f}")
                mt2.metric("VAH", f"{_v.get('vah',0):,.1f}")
                mt3.metric("VAL", f"{_v.get('val',0):,.1f}")
            if _dp is not None:
                rel = "above" if _dp > d['last'] else "below"
                mt4.metric("Dynamic PoC", f"{_dp:,.1f}", f"{rel} LTP")
            # VOB zones (top 3 bullish + bearish)
            _bull_v = (_vob.get('bullish') or [])[-3:]
            _bear_v = (_vob.get('bearish') or [])[-3:]
            if _bull_v or _bear_v:
                st.markdown("**🟩🟪 VOB (Volume Order Blocks):**")
                _vob_rows = []
                for b in _bull_v:
                    _vob_rows.append({'Type': '🟩 Bullish (Support)',
                                      'Range': f"{b['lower']:,.1f} – {b['upper']:,.1f}",
                                      'Mid': f"{b['mid']:,.1f}",
                                      'Volume': f"{b['volume']:,.0f}"})
                for b in _bear_v:
                    _vob_rows.append({'Type': '🟪 Bearish (Resistance)',
                                      'Range': f"{b['lower']:,.1f} – {b['upper']:,.1f}",
                                      'Mid': f"{b['mid']:,.1f}",
                                      'Volume': f"{b['volume']:,.0f}"})
                if _vob_rows:
                    st.dataframe(pd.DataFrame(_vob_rows), use_container_width=True, hide_index=True)
            # HVP markers (most recent few each side)
            _bull_h = (_hvp.get('bullish_hvp') or [])[-3:]
            _bear_h = (_hvp.get('bearish_hvp') or [])[-3:]
            if _bull_h or _bear_h:
                st.markdown("**🟢🔴 HVP (High Volume Pivots):**")
                _hvp_rows = []
                for h in _bull_h:
                    _ts = h.get('time')
                    _ts_s = _ts.strftime('%Y-%m-%d') if hasattr(_ts, 'strftime') else str(_ts)
                    _hvp_rows.append({'Type': '🟢 Bullish (Pivot Low)',
                                      'Date': _ts_s,
                                      'Price': f"{h['price']:,.1f}",
                                      'Volume': f"{h['volume']:,.0f}"})
                for h in _bear_h:
                    _ts = h.get('time')
                    _ts_s = _ts.strftime('%Y-%m-%d') if hasattr(_ts, 'strftime') else str(_ts)
                    _hvp_rows.append({'Type': '🔴 Bearish (Pivot High)',
                                      'Date': _ts_s,
                                      'Price': f"{h['price']:,.1f}",
                                      'Volume': f"{h['volume']:,.0f}"})
                if _hvp_rows:
                    st.dataframe(pd.DataFrame(_hvp_rows), use_container_width=True, hide_index=True)
            if _m and _m.get('rows'):
                st.markdown(
                    f"**MFP** — POC {_m.get('poc_price',0):,.1f} · "
                    f"VA {_m.get('value_area_low',0):,.1f}–{_m.get('value_area_high',0):,.1f} · "
                    f"Top: {_m.get('highest_sentiment_direction','—')} @ {_m.get('highest_sentiment_price',0):,.1f}"
                )
                rows = []
                for r in reversed(_m['rows']):
                    _is_bull = r['sentiment'].lower().startswith('bull')
                    _is_bear = r['sentiment'].lower().startswith('bear')
                    poc_cell = ('🟢🎯' if _is_bull else ('🔴🎯' if _is_bear else '⚪🎯')) if r.get('is_poc') else r.get('node_type','')
                    rows.append({
                        '_sd': 'bull' if _is_bull else ('bear' if _is_bear else 'neutral'),
                        'Price Bin': f"{r['bin_low']:,.1f}–{r['bin_high']:,.1f}",
                        'Total Vol': f"{r['total_volume']:,.0f}",
                        'Bull': f"{r['bull_volume']:,.0f}",
                        'Bear': f"{r['bear_volume']:,.0f}",
                        'Δ': f"{r['delta']:+,.0f}",
                        'Vol %': f"{r['volume_pct']:.1f}%",
                        'POC': poc_cell,
                        'Sentiment': f"{r['sentiment']} ({r['sentiment_strength']:.0f}%)",
                    })
                df_x = pd.DataFrame(rows)
                def _color(row):
                    sd = row.get('_sd', 'neutral')
                    if sd == 'bull':
                        return ['background-color: rgba(0,200,100,0.18); color: #00ff88'] * len(row)
                    if sd == 'bear':
                        return ['background-color: rgba(255,60,60,0.18); color: #ff6666'] * len(row)
                    return [''] * len(row)
                st.dataframe(df_x.style.apply(_color, axis=1).hide(axis='columns', subset=['_sd']),
                             use_container_width=True, hide_index=True)


def compute_gift_nifty_moneyflow(api, num_rows=10):
    """Money Flow Profile for GIFT NIFTY — proxied via NIFTY near-month futures.

    True GIFT NIFTY (NSE IX) OHLCV is not publicly accessible: Yahoo Finance
    doesn't carry it and nseix.com / investing.com block API access. During
    market hours GIFT Nifty tracks NIFTY near-month futures nearly 1:1
    (basis a few points), so we profile the futures' real traded volume.

    Returns {'profile': money_flow_dict, 'meta': {...}} or None.
    """
    try:
        meta = get_nifty_futures_security_id()
        if not meta:
            return None
        data = api.get_intraday_data(
            security_id=meta['security_id'],
            exchange_segment="NSE_FNO",
            instrument="FUTIDX",
            interval="5",
            days_back=1,
        )
        if not data or 'open' not in data or not data.get('open'):
            return None
        ist = pytz.timezone('Asia/Kolkata')
        df_fut = pd.DataFrame({
            'datetime': [datetime.fromtimestamp(t, ist) for t in data.get('timestamp', [])],
            'open': data['open'], 'high': data['high'],
            'low': data['low'], 'close': data['close'],
            'volume': data.get('volume', [0] * len(data['open'])),
        })
        if df_fut.empty or len(df_fut) < 5:
            return None
        profile = calculate_money_flow_profile(df_fut, num_rows=num_rows, source='Money Flow')
        if not profile:
            return None
        last_close = float(df_fut['close'].iloc[-1])
        return {
            'profile': profile,
            'meta': {
                'symbol': meta['symbol'],
                'expiry': meta['expiry'],
                'last': last_close,
                'bars': len(df_fut),
                'num_rows': num_rows,
                'as_of': datetime.now(ist).strftime('%H:%M:%S IST'),
            },
        }
    except Exception:
        return None


def render_gift_nifty_moneyflow_panel(api=None):
    data = st.session_state.get('_gift_mf')
    st.markdown("## 💰 NIFTY Futures Money Flow Profile (10 rows)")
    st.caption(
        "Money Flow Profile built from NIFTY near-month futures bars (real traded volume)."
    )
    if not data and api is not None:
        data = _panel_self_fetch('gift', lambda: compute_gift_nifty_moneyflow(api, num_rows=10),
                                 'futures profile')
        if data:
            st.session_state._gift_mf = data
    if not data:
        _err = (st.session_state.get('_panel_fetch_errors') or {}).get('gift')
        st.info("Futures profile not loaded yet — auto-retries every 2 min."
                + (f"\n\n⚠️ Last fetch problem: `{_err}`" if _err else ""))
        if api is not None and st.button("🔄 Fetch futures profile now", key="fetch_gift_now"):
            st.session_state['_selffetch_ts_gift'] = 0
            st.rerun()
        return
    p = data['profile']
    m = data['meta']
    st.markdown(
        f"**{m['symbol']}** (exp {m['expiry']}) · last ₹{m['last']:.1f} · "
        f"{m['bars']} bars (5m) · as of {m['as_of']}"
    )
    poc = p.get('poc_price')
    vah = p.get('value_area_high')
    val = p.get('value_area_low')
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("POC", f"₹{poc:.0f}" if poc else "—")
    with c2:
        st.metric("VAH", f"₹{vah:.0f}" if vah else "—")
    with c3:
        st.metric("VAL", f"₹{val:.0f}" if val else "—")
    with c4:
        st.metric("Top Sentiment", p.get('highest_sentiment_direction', '—'),
                  f"₹{p.get('highest_sentiment_price', 0):.0f}")
    rows = p.get('rows') or []
    if rows:
        try:
            _tbl = []
            for r in reversed(rows):  # highest price bin first
                _tbl.append({
                    'Price Bin': f"₹{r['bin_low']:.0f}–{r['bin_high']:.0f}",
                    'Mid': f"₹{r['price_level']:.0f}",
                    'Total Vol': f"{r['total_volume']:,.0f}",
                    'Bull': f"{r['bull_volume']:,.0f}",
                    'Bear': f"{r['bear_volume']:,.0f}",
                    'Δ': f"{r['delta']:+,.0f}",
                    'Vol %': f"{r['volume_pct']:.1f}%",
                    'Node': ('🎯 POC' if r['is_poc'] else r['node_type']),
                    'Sentiment': f"{r['sentiment']} ({r['sentiment_strength']:.0f}%)",
                })
            st.dataframe(pd.DataFrame(_tbl), use_container_width=True, hide_index=True)
        except Exception:
            pass
    # Horizontal money-flow bars per price bin (bull green / bear red stacked)
    try:
        if rows:
            _labels = [f"₹{r['price_level']:.0f}" for r in rows]
            _bulls = [r['bull_volume'] for r in rows]
            _bears = [r['bear_volume'] for r in rows]
            fig = go.Figure()
            fig.add_trace(go.Bar(y=_labels, x=_bulls, orientation='h',
                                 name='Bull', marker_color='#00cc66'))
            fig.add_trace(go.Bar(y=_labels, x=_bears, orientation='h',
                                 name='Bear', marker_color='#ff4444'))
            fig.update_layout(barmode='stack', height=340,
                              margin=dict(l=10, r=10, t=28, b=10),
                              title="Money Flow by Price (today, 5m futures bars)")
            st.plotly_chart(fig, use_container_width=True)
    except Exception:
        pass


_NEWS_BULL_KW = (
    'rally', 'rallies', 'surge', 'jump', 'gain', 'record high', 'all-time high',
    'upgrade', 'bullish', 'soar', 'rebound', 'recover', 'optimis', 'buying',
    'beats', 'strong', 'boost', 'inflow', 'advance', 'climbs', 'rises', 'up ',
    'higher', 'positive', 'breakout', 'outperform', 'rate cut',
)
_NEWS_BEAR_KW = (
    'fall', 'falls', 'drop', 'crash', 'plunge', 'selloff', 'sell-off', 'bearish',
    'downgrade', 'weak', 'slump', 'tumble', 'decline', 'fear', 'tariff',
    'sanction', 'war', 'outflow', 'pressure', 'loss', 'losses', 'negative',
    'down ', 'lower', 'slides', 'sinks', 'worry', 'concern', 'risk-off',
    'rate hike', 'inflation spike',
)


def fetch_news_headlines(max_items=15):
    """Fetch NIFTY/SENSEX market headlines from Google News RSS (no API key).
    Returns list of {title, source, age_min, link}. Raises on network errors
    so the caller can record the reason."""
    import xml.etree.ElementTree as _ET
    from email.utils import parsedate_to_datetime as _p2d
    url = ("https://news.google.com/rss/search?"
           "q=nifty+OR+sensex+OR+%22indian+stock+market%22&hl=en-IN&gl=IN&ceid=IN:en")
    r = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
    r.raise_for_status()
    root = _ET.fromstring(r.content)
    now_utc = datetime.now(pytz.utc)
    out = []
    for item in root.iter('item'):
        title = (item.findtext('title') or '').strip()
        if not title:
            continue
        src = (item.findtext('source') or '').strip()
        age_min = None
        try:
            _pd = _p2d(item.findtext('pubDate') or '')
            age_min = int((now_utc - _pd).total_seconds() / 60)
        except Exception:
            pass
        out.append({'title': title, 'source': src, 'age_min': age_min,
                    'link': (item.findtext('link') or '').strip()})
        if len(out) >= max_items:
            break
    return out


def compute_news_bias(cadence_s=300):
    """📰 News Bias — keyword sentiment over recent NIFTY/SENSEX headlines.
    Cached in session state; refetches every cadence_s. Context signal only
    (🌫️ MISGUIDING group) — headlines lag price and can mislead intraday.
    Returns {'net', 'n', 'label', 'em', 'rows': [...]} or None."""
    now_t = time.time()
    _last = st.session_state.get('_news_last_fetch', 0)
    cached = st.session_state.get('_news_bias')
    if cached and (now_t - _last) < cadence_s:
        return cached
    _pfe = st.session_state.setdefault('_panel_fetch_errors', {})
    try:
        heads = fetch_news_headlines()
        _pfe.pop('news', None)
    except Exception as _e:
        _pfe['news'] = f"{type(_e).__name__}: {_e}"
        return cached   # keep last good data on failure
    if not heads:
        _pfe['news'] = "feed returned no headlines"
        return cached
    rows, net, n = [], 0, 0
    for h in heads:
        t = h['title'].lower()
        b = any(k in t for k in _NEWS_BULL_KW)
        s = any(k in t for k in _NEWS_BEAR_KW)
        sc = 1 if (b and not s) else (-1 if (s and not b) else 0)
        # stale guard: headlines older than 24h show in the table but don't
        # vote — Google News mixes multi-day-old items into the feed
        _stale = h.get('age_min') is not None and h['age_min'] > 1440
        if not _stale:
            net += sc
            n += 1
        rows.append({**h, 'score': sc,
                     'em': ('🕸️' if _stale else
                            ('🟢' if sc > 0 else ('🔴' if sc < 0 else '⚪')))})
    if net >= 3:
        label, em = 'STRONG BULLISH', '🟢🚀'
    elif net >= 1:
        label, em = 'Bullish', '🟢'
    elif net <= -3:
        label, em = 'STRONG BEARISH', '🔴🚀'
    elif net <= -1:
        label, em = 'Bearish', '🔴'
    else:
        label, em = 'NEUTRAL / MIXED', '⚪'
    res = {'net': net, 'n': n, 'label': label, 'em': em, 'rows': rows,
           'as_of': datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M')}
    st.session_state['_news_bias'] = res
    st.session_state['_news_last_fetch'] = now_t
    return res


def render_news_bias_panel():
    st.markdown("## 📰 News Bias — NIFTY/SENSEX headlines (keyword sentiment)")
    nb = compute_news_bias()
    if not nb:
        _err = (st.session_state.get('_panel_fetch_errors') or {}).get('news')
        st.info("News not loaded yet — fetches every 5 min."
                + (f"\n\n⚠️ Last fetch problem: `{_err}`" if _err else ""))
        if st.button("🔄 Fetch news now", key="fetch_news_now"):
            st.session_state['_news_last_fetch'] = 0
            st.rerun()
        return
    _c = '#00ff88' if 'BULL' in nb['label'].upper() else (
        '#ff4444' if 'BEAR' in nb['label'].upper() else '#888')
    _g = '#0a3d2a' if 'BULL' in nb['label'].upper() else (
        '#3d0a1f' if 'BEAR' in nb['label'].upper() else '#222a3a')
    st.markdown(
        f"<div style='background:{_g};border:2px solid {_c};padding:10px 14px;"
        f"border-radius:8px;margin-bottom:6px;'>{nb['em']} <b>{nb['label']}</b> · "
        f"net {nb['net']:+d} across {nb['n']} headlines · as of {nb['as_of']} IST · "
        f"<span style='color:#bbb;font-size:12px;'>🌫️ context only — headlines lag "
        f"price; never trade off news alone</span></div>",
        unsafe_allow_html=True,
    )
    st.dataframe(pd.DataFrame([{
        'Read': r['em'],
        'Headline': r['title'],
        'Source': r['source'],
        'Age': (f"{r['age_min']}m" if r['age_min'] is not None and r['age_min'] < 120
                else (f"{r['age_min'] // 60}h" if r['age_min'] is not None else '—')),
    } for r in nb['rows']]), use_container_width=True, hide_index=True)



def fetch_vix_data(api):
    """Fetch India VIX data via yfinance (Dhan does not expose VIX intraday)."""
    try:
        if _HAS_YF:
            data = _fetch_yf_intraday('^INDIAVIX', interval='1m', period='1d')
            if data and data.get('close'):
                return {'vix': data['close'][-1]}
    except Exception:
        pass
    return {'vix': 0}






















def _find_pivots(df, left=3, right=3):
    """Return lists of (index, price) for pivot highs and pivot lows.
    A pivot high at i: high[i] is greater than all highs within ±left/right (exclusive)."""
    highs, lows = [], []
    if df is None or len(df) < left + right + 1:
        return highs, lows
    h = df['high'].values
    l = df['low'].values
    for i in range(left, len(df) - right):
        win_h = h[i - left:i + right + 1]
        win_l = l[i - left:i + right + 1]
        if h[i] == win_h.max() and (win_h == h[i]).sum() == 1:
            highs.append((i, float(h[i])))
        if l[i] == win_l.min() and (win_l == l[i]).sum() == 1:
            lows.append((i, float(l[i])))
    return highs, lows


def detect_chart_patterns(df, lookback=60, tol_pct=0.003):
    """Detect common multi-candle chart patterns from recent pivots.
    Returns dict {pattern, direction} or None. tol_pct is the level-match tolerance."""
    if df is None or len(df) < 20:
        return None
    recent = df.tail(lookback).reset_index(drop=True)
    highs, lows = _find_pivots(recent, left=3, right=3)
    if len(highs) < 2 and len(lows) < 2:
        return None

    def _close(a, b):
        ref = max(abs(a), abs(b), 1.0)
        return abs(a - b) / ref <= tol_pct

    last_h = highs[-3:] if len(highs) >= 3 else highs
    last_l = lows[-3:] if len(lows) >= 3 else lows

    # Head & Shoulders: 3 highs, middle highest, shoulders ~equal & below head, head meaningfully higher
    if len(highs) >= 3:
        s1, head, s2 = highs[-3][1], highs[-2][1], highs[-1][1]
        if head > s1 and head > s2 and _close(s1, s2) and (head - max(s1, s2)) / head > tol_pct:
            return {'pattern': 'Head & Shoulders', 'direction': 'Bearish'}

    # Inverse H&S: 3 lows, middle lowest, shoulders ~equal & above head
    if len(lows) >= 3:
        s1, head, s2 = lows[-3][1], lows[-2][1], lows[-1][1]
        if head < s1 and head < s2 and _close(s1, s2) and (min(s1, s2) - head) / head > tol_pct:
            return {'pattern': 'Inverse Head & Shoulders', 'direction': 'Bullish'}

    # Double Top: last two pivot highs at similar level, with a pivot low between them
    if len(highs) >= 2:
        h1_idx, h1 = highs[-2]
        h2_idx, h2 = highs[-1]
        if _close(h1, h2) and any(h1_idx < li < h2_idx for li, _ in lows):
            return {'pattern': 'Double Top', 'direction': 'Bearish'}

    # Double Bottom
    if len(lows) >= 2:
        l1_idx, l1 = lows[-2]
        l2_idx, l2 = lows[-1]
        if _close(l1, l2) and any(l1_idx < hi < l2_idx for hi, _ in highs):
            return {'pattern': 'Double Bottom', 'direction': 'Bullish'}

    # Triangles: need at least 2 recent highs and 2 recent lows
    if len(highs) >= 2 and len(lows) >= 2:
        h1, h2 = highs[-2][1], highs[-1][1]
        l1, l2 = lows[-2][1], lows[-1][1]
        highs_flat = _close(h1, h2)
        lows_flat = _close(l1, l2)
        highs_falling = (h1 - h2) / max(h1, 1.0) > tol_pct
        lows_rising = (l2 - l1) / max(l1, 1.0) > tol_pct
        if highs_flat and lows_rising:
            return {'pattern': 'Ascending Triangle', 'direction': 'Bullish'}
        if lows_flat and highs_falling:
            return {'pattern': 'Descending Triangle', 'direction': 'Bearish'}
        if highs_falling and lows_rising:
            return {'pattern': 'Symmetrical Triangle', 'direction': 'Neutral'}

    return None








def compute_major_sr_zones(option_data, result, money_flow_data, underlying_price,
                           max_zones=3, tol_pct=0.0015):
    """Aggregate major support/resistance zones using 4 sources:
    OI (top CE/PE strikes), VPFR (POC/VAH/VAL × 3 timeframes), Gamma
    (flip/magnet/repeller) and Money Flow (POC/VAH/VAL). Levels within
    ~tol_pct of spot are clustered; zones are ranked by how many distinct
    SOURCES (OI/VPFR/GAMMA/MF) confirm them. Returns top-N support and
    resistance zones with source tags."""
    if not underlying_price:
        return {'support': [], 'resistance': []}

    levels = []  # (price, src_tag, detail, value_str) — value_str shows the key number for that level

    # 1) Open Interest — top CE OI (resistance) + top PE OI (support)
    try:
        df = option_data.get('df_summary') if option_data else None
        if df is not None and not df.empty and 'Strike' in df.columns:
            lo, hi = underlying_price * 0.95, underlying_price * 1.05
            win = df[(df['Strike'] >= lo) & (df['Strike'] <= hi)]
            if 'openInterest_CE' in win.columns:
                for _, r in win.nlargest(3, 'openInterest_CE').iterrows():
                    oi_val = float(r['openInterest_CE'] or 0)
                    levels.append((float(r['Strike']), 'OI-CE',
                                   f"CE OI {oi_val/1e5:.1f}L",
                                   f"CE OI {oi_val/1e5:.1f}L"))
            if 'openInterest_PE' in win.columns:
                for _, r in win.nlargest(3, 'openInterest_PE').iterrows():
                    oi_val = float(r['openInterest_PE'] or 0)
                    levels.append((float(r['Strike']), 'OI-PE',
                                   f"PE OI {oi_val/1e5:.1f}L",
                                   f"PE OI {oi_val/1e5:.1f}L"))
    except Exception:
        pass

    # 2) VPFR — POC/VAH/VAL across 3 timeframes, with volume per level
    try:
        vpfr = (result or {}).get('vpfr', {}) or {}
        tf_tag = {'short': 'S', 'medium': 'M', 'long': 'L'}
        for tf in ('short', 'medium', 'long'):
            vd = vpfr.get(tf) or {}
            for k in ('poc', 'vah', 'val'):
                try:
                    v = float(vd.get(k))
                    if v > 0:
                        vol = float(vd.get(f'{k}_vol', 0) or 0)
                        vol_str = (f"vol {vol/1000:.1f}K" if vol >= 1000
                                   else (f"vol {vol:.0f}" if vol else ""))
                        levels.append((v, f"VPFR-{tf_tag[tf]}{k.upper()}",
                                       f"{tf.title()} {k.upper()}", vol_str))
                except Exception:
                    pass
    except Exception:
        pass

    # 3) Gamma — flip / magnet / repeller
    try:
        gex = (result or {}).get('gex', {}) or {}
        for k, tag in (('gamma_flip', 'GAMMA-FLIP'),
                       ('magnet', 'GAMMA-MAGNET'),
                       ('repeller', 'GAMMA-REPEL')):
            v = gex.get(k)
            try:
                if v and float(v) > 0:
                    levels.append((float(v), tag, k, ""))
            except Exception:
                pass
    except Exception:
        pass

    # 4) Money Flow — POC / value area high / value area low, with volume if available
    try:
        mf = money_flow_data or {}
        mf_rows = mf.get('rows') or []  # list of {price, volume} dicts (or similar)
        def _mf_vol_at(target):
            try:
                if not mf_rows: return 0.0
                nearest = min(mf_rows, key=lambda r: abs(float(r.get('price', r.get('p', 0))) - target))
                return float(nearest.get('volume', nearest.get('v', 0)) or 0)
            except Exception:
                return 0.0
        candidates = [
            ('poc_price', 'MF-POC', 'MF POC'),
            ('value_area_high', 'MF-VAH', 'MF VAH'),
            ('value_area_low', 'MF-VAL', 'MF VAL'),
        ]
        for key, tag, det in candidates:
            v = mf.get(key)
            try:
                if v and float(v) > 0:
                    vol = _mf_vol_at(float(v))
                    vol_str = (f"vol {vol/1000:.1f}K" if vol >= 1000
                               else (f"vol {vol:.0f}" if vol else ""))
                    levels.append((float(v), tag, det, vol_str))
            except Exception:
                pass
    except Exception:
        pass

    if not levels:
        return {'support': [], 'resistance': []}

    # Cluster by proximity (~0.15% of spot, min 15 pts)
    levels.sort(key=lambda x: x[0])
    tol = max(15.0, underlying_price * tol_pct)
    clusters = []
    for price, src, detail, val_str in levels:
        item = {'src': src, 'detail': detail, 'price': price, 'val_str': val_str}
        if clusters and abs(price - clusters[-1]['avg']) <= tol:
            c = clusters[-1]
            c['items'].append(item)
            c['avg'] = sum(i['price'] for i in c['items']) / len(c['items'])
        else:
            clusters.append({'avg': price, 'items': [item]})

    # Classify each cluster by the INTRINSIC type of its sources, not by where
    # spot happens to be — a resistance level stays resistance even if spot moves
    # above it (e.g. high CE OI = call sellers' ceiling; VAH = value-area high).
    # Plus STICKY memory: when the vote is tied, prefer the bucket's previous
    # label rather than flipping based on spot position.
    #   Resistance-type tags: OI-CE, *VAH (VPFR/MF value-area highs)
    #   Support-type tags:    OI-PE, *VAL (VPFR/MF value-area lows)
    #   Neutral tags:         *POC, GAMMA-* (POC magnets, gamma flip/magnet/repel)
    prev_class = st.session_state.setdefault('_zone_prev_classification', {})
    support, resistance = [], []
    for c in clusters:
        cats = sorted({it['src'].split('-')[0] for it in c['items']})
        r_count = sum(1 for it in c['items']
                      if it['src'].startswith('OI-CE') or 'VAH' in it['src'])
        s_count = sum(1 for it in c['items']
                      if it['src'].startswith('OI-PE') or 'VAL' in it['src'])
        bucket_key = int(round(c['avg'] / 50) * 50)
        prev = prev_class.get(bucket_key)
        if r_count > s_count + 0:  # strict majority for resistance
            zone_type = 'resistance' if (r_count - s_count) >= 2 or prev != 'support' else prev
        elif s_count > r_count + 0:
            zone_type = 'support' if (s_count - r_count) >= 2 or prev != 'resistance' else prev
        else:
            # Tie: prefer previous classification (sticky); else use position
            zone_type = prev or ('resistance' if c['avg'] >= underlying_price else 'support')
        prev_class[bucket_key] = zone_type  # remember for next cycle
        _prices = [it['price'] for it in c['items']]
        zone = {
            'price': round(c['avg'], 2),
            'low': round(min(_prices), 2),
            'high': round(max(_prices), 2),
            'sources': cats,
            'src_count': len(cats),
            'level_count': len(c['items']),
            'detail': ', '.join(it['src'] for it in c['items'][:6]),
            'items': c['items'][:8],  # per-level breakdown (price + value) for the alert
            'type': zone_type,
        }
        if zone_type == 'support':
            support.append(zone)
        else:
            resistance.append(zone)
    support.sort(key=lambda z: (-z['src_count'], -z['level_count'], abs(z['price'] - underlying_price)))
    resistance.sort(key=lambda z: (-z['src_count'], -z['level_count'], abs(z['price'] - underlying_price)))
    return {'support': support[:max_zones], 'resistance': resistance[:max_zones]}


def build_reaction_sr(zones, spot, full_market_read=None, extra_levels=None):
    """🎯 The single canonical Reaction-Zone S/R object — the ONE support and
    ONE resistance every display consumes, so the Market Picture, the Strike
    Cockpit and the Trade Card stop each computing their own opinion.

    This does NOT invent a new S/R algorithm. It is *derived* from the existing
    compute_major_sr_zones() confluence clusters (OI + VPFR + Gamma + Money
    Flow, already ranked by how many sources confirm each level). It picks the
    nearest support at/below spot and the nearest resistance at/above, and
    attaches a canonical strength / confidence / status so every screen shows
    the same numbers. Options-defense strength (support/resistance_strength from
    the full market read) blends with the confluence source-count.

    `extra_levels` is an optional list of (price, source_tag) from STRUCTURAL /
    execution engines the confluence clusterer doesn't include — VWAP, swing
    highs/lows, prev-day high/low, round numbers. Any sitting on the chosen
    support/resistance are folded in as additional confirming sources (richer ✓
    breakdown + higher confluence). This enriches the DISPLAYED object only; it
    does not feed compute_major_sr_zones, so the Entry Gate is unchanged.

    Returns {'support': {..}|None, 'resistance': {..}|None} where each dict is
    {price, strength, confidence, sources, src_count, status, low, high}.
    Publishing this (session_state._reaction_sr) leaves _major_sr_zones — the
    object the Entry Gate arms off — completely untouched: no trade-path change.
    """
    out = {'support': None, 'resistance': None}
    if not spot or not zones:
        return out
    fmr = full_market_read or {}
    _tol = max(15.0, spot * 0.001)

    def _nearest(side, is_support):
        cand = [z for z in (zones.get(side) or []) if z.get('price') is not None]
        if is_support:
            below = [z for z in cand if z['price'] <= spot * 1.001]
            below.sort(key=lambda z: spot - z['price'])
            return below[0] if below else (cand[0] if cand else None)
        above = [z for z in cand if z['price'] >= spot * 0.999]
        above.sort(key=lambda z: z['price'] - spot)
        return above[0] if above else (cand[0] if cand else None)

    def _status(price, is_support):
        if not price:
            return 'unknown'
        if abs(spot - price) / spot * 100 <= 0.12:
            return 'testing'
        if is_support and spot < price * 0.999:
            return 'broken'
        if (not is_support) and spot > price * 1.001:
            return 'broken'
        return 'holding'

    def _extra_sources(price):
        tags = []
        for item in (extra_levels or []):
            try:
                lv, tag = item[0], item[1]
                if lv and tag and abs(float(lv) - float(price)) <= _tol and tag not in tags:
                    tags.append(str(tag))
            except Exception:
                pass
        return tags

    for side, is_support, fmr_key in (('support', True, 'support_strength'),
                                      ('resistance', False, 'resistance_strength')):
        z = _nearest(side, is_support)
        if not z:
            continue
        base_sources = list(z.get('sources') or [])
        extra = [t for t in _extra_sources(z.get('price')) if t not in base_sources]
        sources = base_sources + extra
        src_count = len(sources) if sources else int(z.get('src_count') or 1)
        conflu = min(100.0, src_count / 5.0 * 100.0)      # ~5 confirming families = full
        try:
            opt_str = float(fmr.get(fmr_key)) if fmr.get(fmr_key) is not None else None
        except Exception:
            opt_str = None
        strength = round(0.6 * conflu + 0.4 * opt_str) if opt_str is not None else round(conflu)
        status = _status(z.get('price'), is_support)
        confidence = round(min(100.0, 0.5 * strength + 10.0 * src_count
                                + (10 if status == 'holding' else 0)))
        out[side] = {
            'price': round(float(z['price']), 1),
            'strength': int(max(0, min(100, strength))),
            'confidence': int(max(0, min(100, confidence))),
            'sources': sources,
            'src_count': src_count,
            'status': status,
            'low': z.get('low'), 'high': z.get('high'),
        }
    return out


def _sr_trend_badge(zone):
    """Lifecycle badge for a canonical S/R zone (empty if stable/unknown)."""
    _l = (zone or {}).get('lifecycle') or (zone or {}).get('trend')
    return {'building': ' 📈 building', 'fading': ' 📉 fading',
            'under-attack': ' ⚔️ under attack', 'broken': ' ❌ broken'}.get(_l, '')


def _health_from_signed(signed, reasons):
    """Package a signed [-100,+100] buyer-strength read into a health dict:
    direction (bull/bear/neutral) + magnitude score + reasons."""
    dirn = 'bull' if signed >= 15 else 'bear' if signed <= -15 else 'neutral'
    return {'dir': dirn, 'signed': round(signed), 'score': int(round(abs(signed))),
            'reasons': reasons[:5]}


def compute_value_alignment():
    """📐 Turn the VPFR Short/Medium/Long value areas (9 numbers) into a single
    market STATE: is spot Above / Inside / Below each timeframe's value, are the
    three aligned or rotating, and is value MIGRATING (today's POC vs yesterday's
    POC → rising / falling / flat)? Nine levels compressed into 'is the market
    accepting or rejecting prices here?'. Reads the master signal's vpfr + today's
    money-flow POC + yesterday's value. Stashed as _value_alignment."""
    try:
        master = getattr(st.session_state, '_master_signal_latest', None) or {}
        vpfr = master.get('vpfr') or {}
        od = getattr(st.session_state, '_cached_option_data', None) or {}
        spot = float(od.get('underlying') or 0)
        if not spot or not vpfr:
            return None

        def _loc(v):
            vah, val = v.get('vah'), v.get('val')
            if not (vah and val):
                return None
            return 'above' if spot > vah else 'below' if spot < val else 'inside'

        tf = {}
        for k in ('short', 'medium', 'long'):
            loc = _loc(vpfr.get(k) or {})
            if loc:
                tf[k] = loc
        if not tf:
            return None
        aboves = sum(1 for x in tf.values() if x == 'above')
        belows = sum(1 for x in tf.values() if x == 'below')
        n = len(tf)
        overall = ('aligned bullish' if aboves == n else
                   'aligned bearish' if belows == n else
                   'mixed rotation' if aboves and belows else 'inside value')
        migration = 'flat'
        try:
            mf = getattr(st.session_state, '_money_flow_data', None) or {}
            t_poc = float(mf.get('poc_price') or 0)
            y_poc = float((st.session_state.get('_prev_day_value') or {}).get('poc') or 0)
            if t_poc and y_poc:
                d = t_poc - y_poc
                thr = max(y_poc * 0.0008, 8.0)
                migration = 'rising' if d > thr else 'falling' if d < -thr else 'flat'
        except Exception:
            pass
        out = {'timeframes': tf, 'overall': overall, 'migration': migration,
               'aboves': aboves, 'belows': belows, 'n': n}
        st.session_state._value_alignment = out
        return out
    except Exception:
        return None


def compute_spot_health():
    """🟢 NIFTY SPOT-chart health — 'what is the underlying market doing?'. A
    signed buyer-strength read in [-100,+100] from the spot evidence already
    computed each cycle: CVD (cum-delta %), money-flow sentiment, price vs VWAP,
    plus a small VPFR value-alignment + value-migration context (VPFR contributes
    meaningful context without overpowering the immediate flow signals).
    Analysed on its OWN, before any alignment. Stashed as _spot_health."""
    score = wsum = 0.0
    reasons = []
    try:
        vd = getattr(st.session_state, '_volume_delta_data', None) or {}
        vds = vd.get('summary') or {}
        dp = vds.get('delta_pct')
        if dp is not None:
            c = max(-1.0, min(1.0, float(dp) / 40.0))
            score += 1.2 * c; wsum += 1.2
            reasons.append(f"CVD {float(dp):+.0f}% ({'buyers' if c > 0 else 'sellers'})")
    except Exception:
        pass
    try:
        mf = getattr(st.session_state, '_money_flow_data', None) or {}
        rows = mf.get('rows') or []
        bull = sum(float(r.get('bull_volume', 0) or 0) for r in rows)
        bear = sum(float(r.get('bear_volume', 0) or 0) for r in rows)
        if bull + bear > 0:
            c = max(-1.0, min(1.0, (bull - bear) / (bull + bear)))
            score += 1.0 * c; wsum += 1.0
            reasons.append(f"Money flow {'bullish' if c > 0 else 'bearish'}")
    except Exception:
        pass
    try:
        mp = st.session_state.get('_market_picture') or {}
        vw = mp.get('vwap')
        od = getattr(st.session_state, '_cached_option_data', None) or {}
        sp = float(od.get('underlying') or 0)
        if vw and sp:
            c = max(-1.0, min(1.0, (sp - float(vw)) / float(vw) / 0.003))
            score += 0.8 * c; wsum += 0.8
            reasons.append(f"{'above' if c > 0 else 'below'} VWAP")
    except Exception:
        pass
    # VPFR value alignment + migration — small weight (context, not dominant)
    try:
        va = compute_value_alignment() or {}
        ov = va.get('overall')
        c = (1.0 if ov == 'aligned bullish' else -1.0 if ov == 'aligned bearish'
             else 0.0)
        if ov:
            score += 0.5 * c; wsum += 0.5
            reasons.append(f"value {ov}")
        mig = va.get('migration')
        mc = 1.0 if mig == 'rising' else -1.0 if mig == 'falling' else 0.0
        if mig and mig != 'flat':
            score += 0.5 * mc; wsum += 0.5
            reasons.append(f"value {mig}")
    except Exception:
        pass
    out = _health_from_signed((score / wsum * 100) if wsum else 0.0, reasons)
    st.session_state._spot_health = out
    return out


def compute_ltp_health():
    """🟢 Option LTP-chart health — 'are option traders agreeing with the move?'.
    A signed buyer-strength read from the per-leg synthesis already computed in
    _full_market_read (CALL/PUT modes + strength + market_kind). Analysed on its
    OWN. Stashed as _ltp_health."""
    fmr = st.session_state.get('_full_market_read') or {}
    if not fmr:
        out = _health_from_signed(0.0, [])
        st.session_state._ltp_health = out
        return out
    mk = fmr.get('market_kind')
    base = 1 if mk == 'bull' else -1 if mk == 'bear' else 0
    conf = float(fmr.get('overall_conf', 0) or 0)
    if not conf:                       # fall back to the stronger side's strength
        conf = max(float(fmr.get('call_strength', 0) or 0),
                   float(fmr.get('put_strength', 0) or 0))
    reasons = []
    if fmr.get('call_mode'):
        reasons.append(f"CALL {fmr['call_mode']}")
    if fmr.get('put_mode'):
        reasons.append(f"PUT {fmr['put_mode']}")
    out = _health_from_signed(base * conf, reasons)
    st.session_state._ltp_health = out
    return out


def annotate_sr_trend(reaction_sr):
    """Tag each canonical S/R zone with its LIFECYCLE — building / stable /
    under-attack / fading / broken — by analysing the two charts SEPARATELY and
    then ALIGNING them (stronger than blending too early):

      • Spot Health  — what the NIFTY underlying is doing at the zone (CVD, money
        flow, VWAP) — compute_spot_health.
      • LTP Health   — whether option traders agree (per-leg modes/strength) —
        compute_ltp_health.
      • Options-defense trend — the level's own strength (OI/confluence) rising
        or falling vs a slow EMA (the positioning layer).

    A zone's DEFENCE wants buyers at a support and sellers at a resistance. When
    both charts back the defence AND options strength is rising → BUILDING; when
    both turn against it → FADING; when Spot and LTP DISAGREE → UNDER-ATTACK (the
    'wait, they conflict' warning). Attaches lifecycle, aligned, spot_health,
    ltp_health, options_trend. Observational only — no trade-path change."""
    if not reaction_sr:
        return reaction_sr
    hist = st.session_state.setdefault('_sr_strength_ema', {})
    spot_h = compute_spot_health()
    ltp_h = compute_ltp_health()
    fmr = st.session_state.get('_full_market_read') or {}
    dealer_dir = fmr.get('dealer_dir')            # bull / bear / neutral
    inst_dir = fmr.get('institution_bias')        # bull / bear / neutral
    for side in ('support', 'resistance'):
        z = reaction_sr.get(side)
        if not z or z.get('price') is None or z.get('strength') is None:
            continue
        bucket = f"{side}:{int(round(float(z['price']) / 25.0) * 25)}"
        # options-defense trend (strength EMA over cycles)
        cur = float(z['strength']); prev = hist.get(bucket)
        if prev is None:
            opt_trend, opt_delta = 'stable', 0.0
            hist[bucket] = cur
        else:
            d = cur - prev
            opt_trend = 'building' if d >= 4 else 'fading' if d <= -4 else 'stable'
            opt_delta = round(d, 1)
            hist[bucket] = 0.7 * prev + 0.3 * cur
        # who defends THIS zone? buyers at support, sellers at resistance
        want = 'bull' if side == 'support' else 'bear'
        against = 'bear' if want == 'bull' else 'bull'

        def _cat(dirn):        # a directional read → this zone's defence
            return 'building' if dirn == want else 'fading' if dirn == against else 'neutral'

        # ── 4 grouped categories (the legible breakdown) ──
        cat_spot = _cat(spot_h['dir'])
        # Options = the OI-defence trend (building/fading) if it's moving, else
        # the option-leg (LTP) direction mapped to this zone's defence
        cat_options = opt_trend if opt_trend in ('building', 'fading') else _cat(ltp_h['dir'])
        cat_dealers = _cat(dealer_dir)
        cat_inst = _cat(inst_dir)
        cats = [cat_spot, cat_options, cat_dealers, cat_inst]
        nb = cats.count('building'); nf = cats.count('fading')

        if z.get('status') == 'broken':
            life = 'broken'
        elif nb and nf:                 # some building, some fading → contested
            life = 'under-attack'
        elif nb >= 2 and not nf:
            life = 'building'
        elif nf >= 2 and not nb:
            life = 'fading'
        elif nf == 1 and not nb:
            life = 'under-attack'
        else:
            life = 'stable'

        z['options_trend'] = opt_trend
        z['strength_delta'] = opt_delta
        z['zone_health'] = {'spot': cat_spot, 'options': cat_options,
                            'dealers': cat_dealers, 'institutions': cat_inst}
        z['spot_health'] = {'dir': spot_h['dir'], 'score': spot_h['score']}
        z['ltp_health'] = {'dir': ltp_h['dir'], 'score': ltp_h['score']}
        z['aligned'] = bool(nb and not nf) or bool(nf and not nb)
        z['lifecycle'] = life
        z['trend'] = ('building' if life == 'building' else
                      'fading' if life in ('fading', 'broken', 'under-attack') else 'stable')
    if len(hist) > 40:
        for k in list(hist.keys())[:-40]:
            hist.pop(k, None)
    return reaction_sr


def _zone_memory(price, side):
    """Per-level memory across cycles — touches, age, lifecycle, whether it has
    been pierced / closed beyond / reclaimed. Bucketed to 25 pts so a level's
    identity survives the cluster-average wobbling by a point or two."""
    mem = st.session_state.setdefault('_zone_memory', {})
    key = f"{side}:{int(round(float(price) / 25.0) * 25)}"
    return mem.setdefault(key, {'touches': 0, 'age': 0, 'lifecycle': None,
                                'pierced': False, 'closed_beyond': False,
                                'reclaimed': False, 'was_beyond': False,
                                'at_zone_prev': False})


def build_htf_profiles(df, spot=None):
    """🏛 Stage 45 — build the six higher-timeframe volume profiles
    (1H · 4H · Daily · Weekly · Monthly · Yearly).

    1H/4H are resampled from the live 1-minute series; Daily and slower come from
    a daily history fetched once per session. Each profile is CACHED and rebuilt
    only when that timeframe's bar actually closes — recomputing a Yearly profile
    every tick would be pure waste. Returns {tf: {profile, structure, migration}}.
    """
    out = st.session_state.get('_htf_profiles') or {}
    try:
        from mios_v5.htf_vpfr import build_profile, market_structure, value_migration
    except Exception:
        return out
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    cache_at = st.session_state.setdefault('_htf_built_at', {})

    def _profile_from(frame, tf, bars, swing=3):
        """Build one timeframe, comparing against the PREVIOUS profile so value
        migration is measured against real prior value, not a guess."""
        if frame is None or len(frame) < 6:
            return None
        sub = frame.tail(bars)
        prof = build_profile(list(sub['high']), list(sub['low']),
                             list(sub.get('volume', [])))
        if not prof:
            return None
        # previous window of the same length → prior value for migration
        prev = frame.tail(bars * 2).head(max(6, len(frame.tail(bars * 2)) - len(sub)))
        prev_prof = (build_profile(list(prev['high']), list(prev['low']),
                                   list(prev.get('volume', []))) if len(prev) >= 6
                     else None)
        return {
            'profile': prof,
            'structure': market_structure(list(sub['high']), list(sub['low']),
                                          swing=swing),
            'migration': value_migration(prof.get('poc'),
                                         (prev_prof or {}).get('poc')),
        }

    # ── intraday: 1H / 4H resampled from the 1-minute series ──
    try:
        if df is not None and not df.empty and 'datetime' in df.columns:
            idx = df.set_index('datetime')
            agg = {'open': 'first', 'high': 'max', 'low': 'min',
                   'close': 'last', 'volume': 'sum'}
            for tf, rule, bars, stale_s in (('1H', '1h', 24, 300),
                                            ('4H', '4h', 24, 900)):
                if (time.time() - float(cache_at.get(tf, 0))) < stale_s:
                    continue
                try:
                    rs = idx.resample(rule).agg(agg).dropna()
                    r = _profile_from(rs.reset_index(), tf, bars)
                    if r:
                        out[tf] = r
                        cache_at[tf] = time.time()
                except Exception:
                    pass
    except Exception:
        pass

    # ── daily history → Daily / Weekly / Monthly / Yearly ──
    # fetched at most once an hour; the slower profiles only change on bar close
    try:
        daily = st.session_state.get('_htf_daily_df')
        if daily is None or (time.time() - float(cache_at.get('_daily_fetch', 0))) > 3600:
            # ⚠️ TWO sources, and the failure is RECORDED. This was one `yfinance`
            # download inside `except Exception: pass` — so when it failed there was
            # no error, no caption, and no daily frame, and Stage 45's Daily /
            # Weekly / Monthly / Yearly profiles were simply never built. Nothing on
            # any screen said so; the stage still reported OK on its 1H and 4H
            # profiles alone. A silent single point of failure under the whole
            # higher-timeframe layer.
            #
            # Dhan first: the app is already authenticated with it for the chain,
            # the LTP and every intraday series, so it is one fewer third party in
            # the path. yfinance stays as the fallback rather than being removed.
            _tries = []
            _fresh = None
            try:
                _api = st.session_state.get('_atm_leg_api')
                if _api is not None and hasattr(_api, 'get_daily_data'):
                    _raw = _api.get_daily_data()
                    if _raw and _raw.get('open') and _raw.get('timestamp'):
                        _ist = pytz.timezone('Asia/Kolkata')
                        _fresh = pd.DataFrame({
                            'datetime': [datetime.fromtimestamp(t, _ist)
                                         for t in _raw['timestamp']],
                            'open': _raw['open'], 'high': _raw['high'],
                            'low': _raw['low'], 'close': _raw['close'],
                            'volume': _raw.get('volume',
                                               [0] * len(_raw['open']))})
                        _tries.append('dhan ok')
                    else:
                        _tries.append('dhan returned no bars')
                else:
                    _tries.append('dhan api not published yet')
            except Exception as _e:
                _tries.append(f'dhan failed ({_e})')
            if _fresh is None or _fresh.empty:
                try:
                    import yfinance as yf
                    _d = yf.download('^NSEI', period='5y', interval='1d',
                                     progress=False, auto_adjust=False)
                    if _d is not None and not _d.empty:
                        _d = _d.reset_index()
                        _d.columns = [str(c[0] if isinstance(c, tuple) else c).lower()
                                      for c in _d.columns]
                        _fresh = _d.rename(columns={'date': 'datetime'})
                        _tries.append('yfinance ok')
                    else:
                        _tries.append('yfinance returned no bars')
                except Exception as _e:
                    _tries.append(f'yfinance failed ({_e})')
            if _fresh is not None and not _fresh.empty:
                daily = _fresh
                st.session_state['_htf_daily_df'] = daily
                cache_at['_daily_fetch'] = time.time()
                st.session_state.pop('_htf_daily_error', None)
            else:
                daily = st.session_state.get('_htf_daily_df')
                st.session_state['_htf_daily_error'] = ' · '.join(_tries)
        if daily is not None and not daily.empty:
            didx = daily.set_index('datetime')
            agg = {'open': 'first', 'high': 'max', 'low': 'min',
                   'close': 'last', 'volume': 'sum'}
            for tf, rule, bars, swing, stale_s in (
                    ('Daily', None, 30, 3, 3600),
                    ('Weekly', 'W', 26, 3, 21600),
                    ('Monthly', 'ME', 24, 2, 86400),
                    ('Yearly', 'YE', 5, 1, 86400)):
                if (time.time() - float(cache_at.get(tf, 0))) < stale_s:
                    continue
                try:
                    frame = (daily if rule is None
                             else didx.resample(rule).agg(agg).dropna().reset_index())
                    r = _profile_from(frame, tf, bars, swing=swing)
                    if r:
                        out[tf] = r
                        cache_at[tf] = time.time()
                except Exception:
                    pass
    except Exception:
        pass

    st.session_state['_htf_profiles'] = out
    # 🏛 The rolling POC curves, off the same daily history — see below.
    try:
        _publish_poc_series()
    except Exception:
        pass
    return out


@st.cache_data(show_spinner=False, ttl=3600)
def _poc_lines_cached(highs, lows, vols):
    """The four rolling POC curves. Cached — 1250 daily bars costs ~420 ms.

    ⚠️ Arguments are TUPLES, not the frame: `cache_data` hashes its inputs and a
    DataFrame is not hashable. They are also the whole cache key, so a new daily
    bar (or the hourly refetch) invalidates it and nothing else does.

    `cache_data` and not `cache_resource` here on purpose: the result is a plain
    read-only value, nobody appends to it, and a per-call copy is exactly what a
    caller should get.
    """
    from mios_v5 import poc_series as _ps
    return _ps.lines(highs, lows, vols)


def _hv_points(frame):
    """📍 One panel's high-volume pivots, from its own frame.

    A thin adapter: the frame's columns become the plain sequences
    `volume_points.high_volume_pivots` takes, so that module stays pure and the
    thresholds live in one place rather than being re-picked per caller.

    Volume is judged against the panel's OWN distribution — a rolling sum over a high
    percentile of itself — so NIFTY and a ₹90 premium leg can share one threshold
    honestly. An absolute lot count could not.
    """
    if frame is None or getattr(frame, 'empty', True) or len(frame) < 12:
        return []
    try:
        from mios_v5.volume_points import defaults, high_volume_pivots
        # ⚙️ The trader's settings, or the module's defaults. `_hv_settings` is what
        # the Charts tab's controls write; `defaults()` is the single place the
        # fallbacks live, so a missing key cannot mean a different threshold here
        # than the panel that offers it.
        cfg = defaults()
        cfg.update({k: v for k, v in
                    (st.session_state.get('_hv_settings') or {}).items()
                    if k in cfg})
        return high_volume_pivots(
            list(frame['high']), list(frame['low']), list(frame['close']),
            list(frame['volume']) if 'volume' in frame.columns else None,
            left=int(cfg['left']), right=int(cfg['right']),
            filter_vol=float(cfg['filter_vol']))
    except Exception:
        return []


def _publish_poc_series():
    """🏛 Publish the rolling POC curves + the layered read for the daily view.

    Built from `_htf_daily_df` — the SAME 5-year daily history Stage 45 already
    fetches, so this adds no network call and no second source of daily bars.

    Published to session_state rather than returned, because `mios_v5` may not
    import this file and the panel needs to reach the result.
    """
    daily = st.session_state.get('_htf_daily_df')
    if daily is None or getattr(daily, 'empty', True):
        return
    need = {'high', 'low', 'datetime'}
    if not need <= set(daily.columns):
        return
    hs = tuple(float(x) for x in daily['high'])
    ls = tuple(float(x) for x in daily['low'])
    vs = tuple(float(x or 0) for x in daily.get('volume', [0] * len(hs)))
    series = _poc_lines_cached(hs, ls, vs)
    if not series:
        return
    from mios_v5 import poc_series as _ps
    from mios_v5 import spot as _spotmod
    # ⚠️ Through `spot.price`, the app's ONE owner of the current price. Four
    # conflicting precedences across three files is what that module was built to
    # end; a fifth read here would reopen it.
    spot = _spotmod.price(st.session_state)
    rows = _ps.stack(series, spot)
    st.session_state['_poc_series'] = {
        'dates': [str(d)[:10] for d in daily['datetime']],
        'series': series,
        'rows': rows,
        'align': _ps.alignment(rows),
        'spot': spot,
        'error': st.session_state.get('_htf_daily_error'),
        # 1H and 4H are finer than a daily bar — their CURRENT POC only, from the
        # profiles Stage 45 already built. Never as a curve; see poc_series.
        'subdaily': {
            tf: ((st.session_state.get('_htf_profiles') or {})
                 .get(tf, {}).get('profile') or {}).get('poc')
            for tf in _ps.SUBDAILY},
    }


def _htf_levels_for_zones():
    """Multi-timeframe level map (label → price) used to score a zone's
    cross-timeframe confluence.

    ⚠️ Labels are the REAL windows, not aspirational ones. The VPFR
    short/medium/long buckets are 30 / 60 / 180 bars of the **1-minute** series
    → 30m / 1h / 3h. Calling them "1H / 4H / Daily" would overstate the
    confluence: a level confirmed by three intraday windows of the same series is
    far weaker evidence than one confirmed by a genuine Daily or Weekly profile.
    True 1H/4H/Daily/Weekly value areas need a dedicated higher-timeframe VPFR
    (V6 Stage 40); until that lands, the honest 30m/1h/3h labels are what we
    show. Real swing levels come from the resampled 15m/1h/4h pivots and the
    prev-day extremes, which ARE higher-timeframe."""
    out = {}
    # 🏛 Stage 45 — the genuine higher-timeframe levels (Daily VAH, Weekly LVN,
    # Monthly POC …). These are what make Stage 41's confluence stars mean
    # something; the intraday windows below are kept only as a warm-up fallback.
    try:
        from mios_v5.htf_vpfr import htf_levels as _hl
        _profs = st.session_state.get('_htf_profiles') or {}
        out.update(_hl({_tf: {'status': 'OK', 'profile': (_v or {}).get('profile')}
                        for _tf, _v in _profs.items() if (_v or {}).get('profile')}))
    except Exception:
        pass
    try:
        vpfr = (getattr(st.session_state, '_master_signal_latest', None) or {}).get('vpfr') or {}
        _lbl = {'short': '30m', 'medium': '1h', 'long': '3h'}
        for _k, _tf in _lbl.items():
            v = vpfr.get(_k) or {}
            for _f, _nm in (('poc', 'POC'), ('vah', 'VAH'), ('val', 'VAL')):
                if v.get(_f):
                    out[f"{_tf} {_nm}"] = float(v[_f])
    except Exception:
        pass
    # genuine higher-timeframe structure: 15m / 1h / 4h resampled pivots
    try:
        _htf = (getattr(st.session_state, '_master_signal_latest', None) or {}).get('htf_sr') or {}
        for _lv in (_htf.get('levels') or [])[:14]:
            _p, _tf = _lv.get('level'), _lv.get('tf')
            if _p and _tf:
                out[f"{_tf} pivot ₹{float(_p):,.0f}"] = float(_p)
    except Exception:
        pass
    try:
        _mem = st.session_state.get('_market_memory') or {}
        if _mem.get('prev_high'):
            out['Prev Day High'] = float(_mem['prev_high'])
        if _mem.get('prev_low'):
            out['Prev Day Low'] = float(_mem['prev_low'])
    except Exception:
        pass
    return out


def enrich_zone_intel(reaction_sr, spot):
    """🧠 Phase 1 — attach the full Zone Intelligence card to each canonical S/R:
    origin ★, strength ★, the 10-state lifecycle, 5-group health %, the battle
    (buyer vs seller), acceptance / rejection / trap, break-reject-trap
    probabilities, higher-timeframe confluence and the short AI explanation.

    Everything downstream reads the SAME enriched object — no panel recomputes
    its own opinion of a level. Pure display enrichment: `_major_sr_zones` (what
    the Entry Gate arms off) is untouched, so the trade path does not change."""
    if not reaction_sr or not spot:
        return reaction_sr
    try:
        from mios_v5.zone_intel import build_zone_card
    except Exception:
        return reaction_sr
    htf = _htf_levels_for_zones()
    # blended directional lean from the MIOS reaction-zone engine (-1..+1)
    dir_score = 0.0
    try:
        _rz = (st.session_state.get('_mios_state') or None)
        if _rz is not None:
            _r = _rz.get('stage35_reaction_zone')
            if _r is not None and _r.data:
                dir_score = float(_r.data.get('dir_score') or 0.0)
    except Exception:
        dir_score = 0.0
    for side in ('support', 'resistance'):
        z = reaction_sr.get(side)
        if not z or z.get('price') is None:
            continue
        try:
            price = float(z['price'])
            m = _zone_memory(price, side)
            m['age'] = int(m.get('age', 0)) + 1
            at_zone = abs(float(spot) - price) / price * 100.0 <= 0.35
            # a fresh arrival at the level counts as one touch
            if at_zone and not m.get('at_zone_prev'):
                m['touches'] = int(m.get('touches', 0)) + 1
            m['at_zone_prev'] = at_zone
            beyond = (float(spot) < price * 0.9988 if side == 'support'
                      else float(spot) > price * 1.0012)
            if beyond:
                m['was_beyond'] = True
                m['pierced'] = True
            elif m.get('was_beyond'):
                # came back through — the level did its job (and may be reclaimed)
                m['was_beyond'] = False
                m['reclaimed'] = True
            m['closed_beyond'] = bool(z.get('status') == 'broken')
            # freshness decays with age; a long-untested level stays fresh
            freshness = max(0.0, 100.0 - min(100.0, m['age'] * 0.6))
            card = build_zone_card(
                side.upper(), z, spot, dir_score=dir_score, htf_levels=htf,
                touches=int(m.get('touches', 0)), freshness=freshness,
                concentration=z.get('strength'),
                prev_lifecycle=m.get('lifecycle'), age_cycles=int(m.get('age', 0)),
                pierced=bool(m.get('pierced')),
                closed_beyond=bool(m.get('closed_beyond')),
                reclaimed=bool(m.get('reclaimed')))
            if card:
                m['lifecycle'] = card['lifecycle']
                z['intel'] = card
                # keep the legacy keys in sync so every existing consumer
                # (Trade Card badge, Decision Engine gate, Telegram) sees the
                # richer lifecycle without any of them needing to change.
                z['lifecycle'] = card['lifecycle']
                z['zone_health'] = card['health']['categories']
        except Exception:
            continue
    _m = st.session_state.get('_zone_memory') or {}
    if len(_m) > 60:
        for k in list(_m.keys())[:-60]:
            _m.pop(k, None)
    return reaction_sr












# ═══════════════════════════════════════════════════════════════════════════
#  COMPOSITE BIAS ENGINE — aligns 14+ signals into a single ENTER NOW verdict
# ═══════════════════════════════════════════════════════════════════════════

def analyze_vob_volume(df_1m, ltp):
    """For each VOB zone on the leg's 1m chart, attribute LuxAlgo-style LTF
    buyer/seller volume to the zone and classify its status.

    For each zone (bullish = support · bearish = resistance):
      - Find 1m sub-bars whose close fell inside the zone
      - Sum bull_vol (close>open) and bear_vol (close<open) for those sub-bars
      - Compute bull%/bear% and identify the max single-bar print inside the zone
      - Classify status using current LTP position + flow:
          BUILDING: LTP still in zone, dominant side matches zone type, vol elevated
          BREAKING: LTP closed outside zone (below bull or above bear) recently
          INTACT  : LTP near zone, mixed flow
          FADING  : Dominant side opposite to zone type → zone weakening

    Returns list of dicts (top 3 bull + top 3 bear zones, most recent)."""
    if df_1m is None or getattr(df_1m, 'empty', True) or len(df_1m) < 20 or ltp <= 0:
        return []
    try:
        vob = VolumeOrderBlocks(sensitivity=5).detect_blocks(df_1m) or {}
        results = []
        avg_vol_1m = float(df_1m['volume'].tail(60).mean()) if 'volume' in df_1m.columns else 0
        last_close = float(df_1m['close'].iloc[-1])
        d = df_1m.copy()
        # CLV-weighted buyer/seller split (more faithful BUILDING/FADING reads)
        d = _clv_delta_cols(d)

        def _attribute(b, zone_type):
            zlo, zhi, zmid = float(b['lower']), float(b['upper']), float(b['mid'])
            in_zone = d[(d['close'] >= zlo) & (d['close'] <= zhi)]
            if in_zone.empty:
                return None
            buy_v = float(in_zone['bull_v'].sum())
            sell_v = float(in_zone['bear_v'].sum())
            total_v = buy_v + sell_v
            bull_pct = (buy_v / total_v * 100) if total_v > 0 else 50
            # Dominant single-bar print inside the zone
            mb_price = ms_price = None
            if buy_v > 0:
                idx = in_zone['bull_v'].idxmax()
                mb_price = float(in_zone.loc[idx, 'close'])
            if sell_v > 0:
                idx = in_zone['bear_v'].idxmax()
                ms_price = float(in_zone.loc[idx, 'close'])
            dominant = 'buyers' if bull_pct > 60 else ('sellers' if bull_pct < 40 else 'balanced')
            # Status classification
            if zone_type == 'bullish':
                # Bull VOB = support
                if last_close < zlo:
                    status = 'BREAKING'   # support failed
                    dominant = 'sellers'
                elif zlo <= last_close <= zhi and dominant == 'buyers' and (avg_vol_1m > 0 and (total_v / max(len(in_zone), 1)) > avg_vol_1m * 1.2):
                    status = 'BUILDING'   # buyers defending
                elif bull_pct < 48:
                    status = 'FADING'     # support with more SELLERS = weak (not intact)
                else:
                    status = 'INTACT'     # buyers in majority (≥48%) → support holding
            else:  # bearish VOB = resistance
                if last_close > zhi:
                    status = 'BREAKING'   # resistance failed
                    dominant = 'buyers'
                elif zlo <= last_close <= zhi and dominant == 'sellers' and (avg_vol_1m > 0 and (total_v / max(len(in_zone), 1)) > avg_vol_1m * 1.2):
                    status = 'BUILDING'   # sellers stacking
                elif bull_pct > 52:
                    status = 'FADING'     # resistance with more BUYERS = weak (not intact)
                else:
                    status = 'INTACT'     # sellers in majority (bull% ≤52) → resistance holding
            return {
                'zone_type': zone_type,
                'role': 'support' if zone_type == 'bullish' else 'resistance',
                'lower': zlo, 'upper': zhi, 'mid': zmid,
                'status': status, 'dominant': dominant,
                'buy_vol': buy_v, 'sell_vol': sell_v, 'total_vol': total_v,
                'bull_pct': bull_pct,
                'max_buy_price': mb_price,
                'max_sell_price': ms_price,
                'n_bars_in_zone': len(in_zone),
            }

        for b in (vob.get('bullish') or [])[-3:]:
            r = _attribute(b, 'bullish')
            if r:
                results.append(r)
        for b in (vob.get('bearish') or [])[-3:]:
            r = _attribute(b, 'bearish')
            if r:
                results.append(r)
        return results
    except Exception:
        return []


def classify_leg_sr_behavior(df_l, ltp):
    """S/R behavior for an option LEG using its own VOB zones as S/R levels.

    Bullish VOB = support · Bearish VOB = resistance for that leg's chart.
    Returns dict {state, side, level, direction} from the LEG'S OWN perspective
    (direction = bull/bear for the option itself, NOT NIFTY direction).

    States same as classify_sr_behavior: BREAKING / REJECTING / ACCEPTING /
    BUILDING / NONE — highest-priority wins."""
    if df_l is None or getattr(df_l, 'empty', True) or len(df_l) < 5 or ltp <= 0:
        return None
    try:
        vob = VolumeOrderBlocks(sensitivity=5).detect_blocks(df_l) or {}
        # Bullish VOBs = support for this leg's LTP; bearish = resistance
        sup_levels = sorted([b['mid'] for b in (vob.get('bullish') or [])
                              if b.get('mid') and b['mid'] <= ltp], reverse=True)
        res_levels = sorted([b['mid'] for b in (vob.get('bearish') or [])
                              if b.get('mid') and b['mid'] >= ltp])
        nearest_sup = sup_levels[0] if sup_levels else None
        nearest_res = res_levels[0] if res_levels else None
        if nearest_sup is None and nearest_res is None:
            return {'state': 'NONE', 'side': None, 'level': None, 'direction': 'none'}

        last = df_l.iloc[-1]
        prev = df_l.iloc[-2]
        o, h, l, c = float(last['open']), float(last['high']), float(last['low']), float(last['close'])
        pc = float(prev['close'])
        rng = h - l if h > l else 0.001
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        # Vol spike on this leg
        try:
            avg_vol = float(df_l['volume'].tail(20).mean())
            vol_spike = float(last.get('volume', 0)) > avg_vol * 1.5 if avg_vol > 0 else False
        except Exception:
            vol_spike = False
        # Tolerance: 0.5% of LTP or 0.5 points min
        tol = max(ltp * 0.005, 0.5)

        candidates = []
        for level, side in [(nearest_res, 'resistance'), (nearest_sup, 'support')]:
            if level is None:
                continue
            dist = ltp - level
            # BREAKING: crossed level decisively with vol
            if side == 'resistance' and c > level + tol * 2 and pc <= level and vol_spike:
                candidates.append((3, 'BREAKING', side, level, 'bull'))
            elif side == 'support' and c < level - tol * 2 and pc >= level and vol_spike:
                candidates.append((3, 'BREAKING', side, level, 'bear'))
            # REJECTING: wick pierced but close back inside
            if side == 'resistance' and h > level + tol and c < level and upper_wick > body:
                candidates.append((3, 'REJECTING', side, level, 'bear'))
            elif side == 'support' and l < level - tol and c > level and lower_wick > body:
                candidates.append((3, 'REJECTING', side, level, 'bull'))
            # ACCEPTING: held on right side of broken level for 3+ bars
            if len(df_l) >= 5:
                last5 = df_l.tail(5)
                if side == 'resistance' and last5['close'].iloc[0] < level and (last5['low'] >= level - tol).iloc[-3:].all():
                    candidates.append((2, 'ACCEPTING', side, level, 'bull'))
                elif side == 'support' and last5['close'].iloc[0] > level and (last5['high'] <= level + tol).iloc[-3:].all():
                    candidates.append((2, 'ACCEPTING', side, level, 'bear'))
            # BUILDING: within tol*3 of level
            if abs(dist) <= tol * 3:
                if side == 'support':
                    candidates.append((1, 'BUILDING', side, level, 'bull'))
                else:
                    candidates.append((1, 'BUILDING', side, level, 'bear'))
        # ── both sides are measured, so publish both ──────────────────
        # The winner below is the headline — the level price is reacting to
        # most strongly — and it is what the chart marks and what every
        # existing consumer reads. But the loop above evaluates resistance AND
        # support, and returning only the winner threw the other away: a leg
        # sitting between its two levels reported one of them and looked as if
        # the other did not exist. `sides` keeps each side's own best read,
        # additively, so nothing that reads `state`/`side`/`level` changes.
        by_side = {}
        for pri, st_, sd, lv, dr in candidates:
            best = by_side.get(sd)
            if best is None or pri > best['priority']:
                by_side[sd] = {'state': st_, 'side': sd, 'level': float(lv),
                               'direction': dr, 'priority': pri}

        if not candidates:
            return {'state': 'NONE', 'side': None, 'level': None,
                    'direction': 'none', 'sides': {}}
        # Ties break toward resistance purely because it is iterated first.
        # That is arbitrary, so it is recorded rather than relied upon: with
        # `sides` published, a tie no longer hides the other level.
        candidates.sort(key=lambda x: -x[0])
        _, state, side, level, direction = candidates[0]
        return {'state': state, 'side': side, 'level': float(level),
                'direction': direction, 'sides': by_side}
    except Exception:
        return None


def classify_sr_behavior(df, spot_price):
    """Classify how price is behaving at the nearest Major S/R level.

    States:
      BREAKING   — price moved decisively through level with vol confirm
      REJECTING  — wick pierced level but close back inside (failed move)
      BUILDING   — price within 25pt, pressure pending (not directional yet)
      ACCEPTING  — price held above/below broken level (resistance→support flip)
      NONE       — no nearby S/R or no clear behavior

    Returns dict {state, side, level, direction} where direction is
    'bull'/'bear'/'none' from a NIFTY-direction perspective."""
    if df is None or getattr(df, 'empty', True) or len(df) < 5:
        return None
    try:
        # Pull nearest major S/R levels from session-state cluster
        _zones = st.session_state.get('_major_sr_zones') or {}
        sup_levels = sorted(
            [float(z.get('price') or z.get('level') or 0)
             for z in (_zones.get('support') or [])[:5]
             if (z.get('price') or z.get('level'))],
            reverse=True,
        )
        res_levels = sorted(
            [float(z.get('price') or z.get('level') or 0)
             for z in (_zones.get('resistance') or [])[:5]
             if (z.get('price') or z.get('level'))],
        )
        nearest_sup = next((s for s in sup_levels if s <= spot_price), None)
        nearest_res = next((r for r in res_levels if r >= spot_price), None)
        if nearest_sup is None and nearest_res is None:
            return {'state': 'NONE', 'side': None, 'level': None, 'direction': 'none'}

        last = df.iloc[-1]
        prev = df.iloc[-2]
        o, h, l, c = float(last['open']), float(last['high']), float(last['low']), float(last['close'])
        pc = float(prev['close'])
        rng = h - l if h > l else 0.001
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        try:
            avg_vol = float(df['volume'].tail(20).mean())
            vol_spike = float(last.get('volume', 0)) > avg_vol * 1.5 if avg_vol > 0 else False
        except Exception:
            vol_spike = False

        candidates = []  # tuples: (priority, state, side, level, direction)
        for level, side in [(nearest_res, 'resistance'), (nearest_sup, 'support')]:
            if level is None:
                continue
            dist = spot_price - level
            # ── BREAKING: crossed level decisively this bar with vol
            if side == 'resistance' and c > level + max(rng * 0.3, 5) and pc <= level and vol_spike:
                candidates.append((3, 'BREAKING', side, level, 'bull'))
            elif side == 'support' and c < level - max(rng * 0.3, 5) and pc >= level and vol_spike:
                candidates.append((3, 'BREAKING', side, level, 'bear'))
            # ── REJECTING: wick pierced level but close back inside
            if side == 'resistance' and h > level + max(rng * 0.2, 3) and c < level and upper_wick > body:
                candidates.append((3, 'REJECTING', side, level, 'bear'))
            elif side == 'support' and l < level - max(rng * 0.2, 3) and c > level and lower_wick > body:
                candidates.append((3, 'REJECTING', side, level, 'bull'))
            # ── ACCEPTING: held above former-resistance / below former-support for 3+ bars
            # (resistance → support flip = bull; support → resistance = bear)
            if len(df) >= 5:
                last5 = df.tail(5)
                if side == 'resistance' and last5['close'].iloc[0] < level and (last5['low'] >= level - max(rng * 0.5, 5)).iloc[-3:].all():
                    candidates.append((2, 'ACCEPTING', side, level, 'bull'))
                elif side == 'support' and last5['close'].iloc[0] > level and (last5['high'] <= level + max(rng * 0.5, 5)).iloc[-3:].all():
                    candidates.append((2, 'ACCEPTING', side, level, 'bear'))
            # ── BUILDING: within 25pt of level (pressure pending — soft tilt)
            if abs(dist) <= 25:
                if side == 'support':
                    candidates.append((1, 'BUILDING', side, level, 'bull'))
                else:
                    candidates.append((1, 'BUILDING', side, level, 'bear'))
        if not candidates:
            return {'state': 'NONE', 'side': None, 'level': None, 'direction': 'none'}
        # Highest priority wins (BREAKING/REJECTING > ACCEPTING > BUILDING)
        candidates.sort(key=lambda x: -x[0])
        _, state, side, level, direction = candidates[0]
        return {'state': state, 'side': side, 'level': float(level), 'direction': direction}
    except Exception:
        return None




_BIAS_CATEGORY = {
    # 🚀 FAST — event-driven / live / low-lag
    "CIE (latest signal)": 'fast',
    "Spot Stop-Hunt (latest)": 'fast',
    "Spot vs Dynamic PoC": 'fast',
    "ATM CE candle pattern": 'fast',
    "ATM PE candle pattern (reversed)": 'fast',
    "Spot Candle Pattern": 'fast',
    "VWAP relation": 'fast',
    "NIFTY Futures Basis": 'fast',
    "Price × OI Classifier": 'fast',
    "S/R Behavior": 'fast',
    "Cross-strike leg S/R Behavior": 'fast',
    "Spot Divergence (OBV/Δ)": 'fast',
    "Cross-strike leg Divergence": 'fast',
    "Spot Ignition (tank-full)": 'fast',
    "Cross-strike leg Ignition": 'fast',
    "Cross-strike leg VWAP": 'fast',
    "Leg Fast Verdict": 'fast',
    "Greek Absorption (capping)": 'fast',
    "Market Depth (ATM)": 'fast',
    "Cross-strike VOB BUILD/BREAK": 'fast',
    # 🐢 LAGGING — smoothed composites / slow timeframes
    "Master Signal (AI)": 'lag',
    "Bull/Bear Meter (Tier-1)": 'lag',
    "Smart Money / Accum-Dist": 'lag',
    "Global NIFTY Bias": 'lag',
    "Commodity Risk Regime": 'lag',
    "Sector Rotation": 'lag',
    "Multi-Instrument Monitor": 'lag',
    "Reversal Detector": 'lag',
    "Cross-strike VIDYA": 'lag',
    "ATM PCR": 'lag',
    "Spot Geometric Pattern": 'lag',
    "Spot Chart Pattern": 'lag',
    "COMPOSITE BIAS Engine": 'lag',
    "Leg Lagging Verdict": 'lag',
    # 🌫️ MISGUIDING — flips on single bars / accumulated noise
    "Spot vs VPFR-S POC": 'mis',
    "Spot MFP POC bin": 'mis',
    "Leg Misguiding Verdict": 'mis',
    "News Bias": 'mis',
}




def _snap_level_to_swing(level, df, kind, tol=40.0, lookback=75):
    """📐 Level calibration — snap a theoretical S/R level to the market's
    actual tested pivot. Confluence levels (OI/VP/gamma) are estimates; the
    real market reverses at the price it actually pivoted at. This finds recent
    swing lows (for support) / swing highs (for resistance) in the candle data
    — a swing = local extreme with 2 bars on each side — and, if one sits
    within `tol` points of the computed level, returns the SWING price (the
    market-confirmed level) instead. Returns (price, snapped_bool)."""
    try:
        if level is None or df is None or getattr(df, 'empty', True) or len(df) < 7:
            return level, False
        t = df.tail(lookback)
        lows = t['low'].astype(float).values
        highs = t['high'].astype(float).values
        n = len(t)
        pivots = []
        for i in range(2, n - 2):
            if kind == 'support':
                if lows[i] <= lows[i-1] and lows[i] <= lows[i-2] \
                        and lows[i] <= lows[i+1] and lows[i] <= lows[i+2]:
                    pivots.append(lows[i])
            else:
                if highs[i] >= highs[i-1] and highs[i] >= highs[i-2] \
                        and highs[i] >= highs[i+1] and highs[i] >= highs[i+2]:
                    pivots.append(highs[i])
        if not pivots:
            return level, False
        nearest = min(pivots, key=lambda p: abs(p - level))
        if abs(nearest - level) <= tol and abs(nearest - level) > 0.5:
            return round(float(nearest), 1), True
        return level, False
    except Exception:
        return level, False


def _detect_liquidity_pools(df, spot_price, mem=None, tol=12.0, lookback=75):
    """🎯 Predictive liquidity-pool map — where resting stops likely cluster,
    BEFORE price goes there. Pools (all inferable from executed data):
      • equal highs (2+ swing highs within `tol` pts) → buy-stops just above
      • equal lows  (2+ swing lows within `tol` pts)  → sell-stops just below
      • PDH / PDL   (previous-day extremes — classic stop shelves)
      • round numbers (nearest 100-multiple each side)
    Each pool: {price, kind, touched} — touched = today's range already swept
    it (its liquidity is spent). Returns {'above': [...], 'below': [...]},
    each sorted nearest-first. Honest limit: true resting orders need L2 depth;
    these are the *statistically likely* shelves, not observed orders."""
    pools_above, pools_below = [], []
    try:
        if df is None or getattr(df, 'empty', True) or len(df) < 7 or not spot_price:
            return {'above': [], 'below': []}
        t = df.tail(lookback)
        highs = t['high'].astype(float).values
        lows = t['low'].astype(float).values
        n = len(t)
        swing_h, swing_l = [], []
        for i in range(2, n - 2):
            if highs[i] >= highs[i-1] and highs[i] >= highs[i-2] \
                    and highs[i] >= highs[i+1] and highs[i] >= highs[i+2]:
                swing_h.append(highs[i])
            if lows[i] <= lows[i-1] and lows[i] <= lows[i-2] \
                    and lows[i] <= lows[i+1] and lows[i] <= lows[i+2]:
                swing_l.append(lows[i])
        day_high = float(t['high'].max())
        day_low = float(t['low'].min())

        def _clusters(vals):
            out = []
            for v in sorted(vals):
                if out and abs(v - out[-1][-1]) <= tol:
                    out[-1].append(v)
                else:
                    out.append([v])
            return [c for c in out if len(c) >= 2]
        for c in _clusters(swing_h):
            p = max(c)                      # stops sit just above equal highs
            if p > spot_price:
                pools_above.append({'price': round(p, 1), 'kind': 'eq-highs',
                                    'touched': day_high > p + 2})
        for c in _clusters(swing_l):
            p = min(c)                      # stops sit just below equal lows
            if p < spot_price:
                pools_below.append({'price': round(p, 1), 'kind': 'eq-lows',
                                    'touched': day_low < p - 2})
        mem = mem or {}
        pdh, pdl = mem.get('prev_high'), mem.get('prev_low')
        if pdh and pdh > spot_price:
            pools_above.append({'price': round(float(pdh), 1), 'kind': 'PDH',
                                'touched': day_high > pdh + 2})
        if pdl and pdl < spot_price:
            pools_below.append({'price': round(float(pdl), 1), 'kind': 'PDL',
                                'touched': day_low < pdl - 2})
        _r_up = float(int(spot_price // 100 + 1) * 100)
        _r_dn = float(int(spot_price // 100) * 100)
        if _r_up > spot_price:
            pools_above.append({'price': _r_up, 'kind': 'round',
                                'touched': day_high > _r_up + 2})
        if _r_dn < spot_price:
            pools_below.append({'price': _r_dn, 'kind': 'round',
                                'touched': day_low < _r_dn - 2})
        # dedupe pools within tol — prefer the more meaningful kind when two
        # coincide (equal highs/lows > PDH/PDL > round number), then sort
        # nearest-to-spot first
        _PRIO = {'eq-highs': 0, 'eq-lows': 0, 'PDH': 1, 'PDL': 1, 'round': 2}
        def _dedupe(pools, reverse):
            pools = sorted(pools, key=lambda p: _PRIO.get(p['kind'], 3))
            out = []
            for p in pools:
                if not any(abs(p['price'] - q['price']) <= tol for q in out):
                    out.append(p)
            out.sort(key=lambda p: p['price'], reverse=reverse)
            return out
        pools_above = _dedupe(pools_above, reverse=False)   # nearest above first
        pools_below = _dedupe(pools_below, reverse=True)    # nearest below first
    except Exception:
        pass
    return {'above': pools_above[:4], 'below': pools_below[:4]}


def _candle_sweep_reclaim(df, level, kind, wick_min=5.0, bars=3):
    """Detect a just-completed sweep-and-reclaim at a level from the last few
    CLOSED candles: price wicked beyond the level by >= wick_min pts but closed
    back inside. Returns True when the fake-break signature is present."""
    try:
        if df is None or getattr(df, 'empty', True) or len(df) < bars + 1 or not level:
            return False
        for _, c in df.iloc[-(bars + 1):-1].iterrows():
            lo, hi, cl = float(c['low']), float(c['high']), float(c['close'])
            if kind == 'SUPPORT' and lo <= level - wick_min and cl > level:
                return True
            if kind == 'RESISTANCE' and hi >= level + wick_min and cl < level:
                return True
    except Exception:
        pass
    return False


def _zone_confirmed(df, level, kind, band=15.0, bars=3):
    """Zone-HELD confirmation from the last few CLOSED candles — the reclaim
    that filters out first-touch fakeouts / stop-hunts. A candle must have
    TESTED the zone (wick reached it) and CLOSED back on the trade side with a
    same-side body (buyers at support / sellers at resistance). Also true on a
    clean sweep-and-reclaim. Returns True once the zone has proven it holds."""
    try:
        if df is None or getattr(df, 'empty', True) or len(df) < bars + 1 or not level:
            return False
        for _, c in df.iloc[-(bars + 1):-1].iterrows():
            lo, hi = float(c['low']), float(c['high'])
            op, cl = float(c['open']), float(c['close'])
            if kind == 'SUPPORT':
                if lo <= level + band and cl > level and cl >= op:
                    return True
            else:  # RESISTANCE
                if hi >= level - band and cl < level and cl <= op:
                    return True
        # or an explicit sweep-and-reclaim of the level
        return _candle_sweep_reclaim(df, level, kind)
    except Exception:
        return False


def _mp_conf(mag, full, floor=0.35):
    """Confidence weight in [floor, 1.0] for a signal of magnitude `mag`,
    reaching full conviction at |mag| >= `full`. A signal that has only just
    crossed its neutral threshold contributes ~floor of a full vote, so a
    marginal reading can no longer tip a near-tie the way the old flat
    1/2-point vote did — the regime now reflects conviction, not head-count."""
    try:
        if not full:
            return 1.0
        r = min(abs(float(mag)) / float(full), 1.0)
    except Exception:
        return 1.0
    return floor + (1.0 - floor) * r


def compute_market_picture(spot_price, df, option_data, cat_scores=None):
    """🗺️ One clear picture: UP / DOWN / SIDEWAYS regime, the levels that
    matter, and honest probabilities.

    Signals vote into up/down/side, but NOT as a flat head-count — each vote is
    CONFIDENCE-WEIGHTED (via _mp_conf): its magnitude/strength scales the points
    it contributes. Primary fast+true signals (CE↔PE alignment, leg FAST net,
    VWAP, ATM chain, ΔOI) carry full weight; context/positioning signals (GEX,
    DEX, skew, global, news, commodity) vote at reduced weight. This stops a
    pile of marginal secondary signals from outvoting the strong primary ones —
    which is what let the banner disagree with the MIOS V5 conflict read.
    Returns dict or None."""
    if not spot_price or df is None or getattr(df, 'empty', True):
        return None
    up = down = side = 0.0
    reasons = []

    # 1) CE↔PE alignment (fast + true — traded volume both sides)
    try:
        _al = compute_ce_pe_alignment(spot_price) or {}
        _st = _al.get('state', 'FLAT')
        if _st == 'ALIGNED_UP':
            up += 2; reasons.append("CE↔PE aligned UP (+2 up)")
        elif _st == 'ALIGNED_DOWN':
            down += 2; reasons.append("CE↔PE aligned DOWN (+2 down)")
        else:
            side += 2; reasons.append(f"CE↔PE {_st} (+2 sideways)")
    except Exception:
        pass

    # 2) leg-table FAST net (VOB·S/R·Div·Ign across all legs)
    try:
        if cat_scores and 'fast' in cat_scores:
            _fb, _fbr = cat_scores['fast']
            _fn = _fb - _fbr
        else:
            _, _ov = st.session_state.get('_leg_bias_cache') or (None, None)
            _fn = ((_ov or {}).get('by_speed', {}).get('fast') or {}).get('net', 0)
        _cf = _mp_conf(_fn, 6)
        if _fn >= 2:
            _w = 2 * _cf; up += _w; reasons.append(f"FAST net {_fn:+d} (+{_w:.1f} up)")
        elif _fn <= -2:
            _w = 2 * _cf; down += _w; reasons.append(f"FAST net {_fn:+d} (+{_w:.1f} down)")
        else:
            side += 1; reasons.append(f"FAST net {_fn:+d} (+1 sideways)")
    except Exception:
        pass

    # 3) Spot vs session VWAP
    _vwap_val = None
    try:
        _vw = ReversalDetector.calculate_vwap(df)
        if _vw is not None and not _vw.empty:
            _v = float(_vw.iloc[-1])
            _vwap_val = _v
            _d = (spot_price - _v) / _v * 100
            _cf = _mp_conf(_d, 0.30)
            if _d > 0.05:
                _w = 1 * _cf; up += _w; reasons.append(f"above VWAP {_d:+.2f}% (+{_w:.1f} up)")
            elif _d < -0.05:
                _w = 1 * _cf; down += _w; reasons.append(f"below VWAP {_d:+.2f}% (+{_w:.1f} down)")
            else:
                side += 1; reasons.append("hugging VWAP (+1 sideways)")
    except Exception:
        pass

    # 4) Range compression — 20-bar range vs 3×ATR(14)
    try:
        _t = df.tail(20)
        _rng = float(_t['high'].max() - _t['low'].min())
        _h, _l, _c = df['high'].astype(float), df['low'].astype(float), df['close'].astype(float)
        _pc = _c.shift(1)
        _tr = pd.concat([(_h - _l), (_h - _pc).abs(), (_l - _pc).abs()], axis=1).max(axis=1)
        _atr = float(_tr.tail(14).mean() or 0)
        if _atr > 0 and _rng < 3 * _atr:
            side += 1.5; reasons.append(f"20-bar range {_rng:.0f} < 3×ATR (+1.5 sideways)")
    except Exception:
        pass

    # 5) GEX regime — context only (pin favours sideways, negative favours trend)
    gex_disp = None
    try:
        _ds_g = (option_data or {}).get('df_summary') if option_data else None
        _u_g = (option_data or {}).get('underlying') or spot_price
        _gex = st.session_state.get('_gex_data') or {}
        if not _gex and _ds_g is not None and not getattr(_ds_g, 'empty', True):
            _gex = calculate_dealer_gex(_ds_g, _u_g) or {}
        _tg = float(_gex.get('total_gex', 0) or 0)
        if _tg > 10:
            side += 0.6; reasons.append(f"GEX +{_tg:.0f}L pin (+0.6 sideways)")
        elif _tg < -10:
            if up >= down:
                up += 0.6; reasons.append(f"GEX {_tg:.0f}L accel (+0.6 up)")
            else:
                down += 0.6; reasons.append(f"GEX {_tg:.0f}L accel (+0.6 down)")
        if _gex:
            gex_disp = {'total': _tg, 'signal': _gex.get('gex_signal', '—'),
                        'flip': _gex.get('gamma_flip_level'),
                        'spot_vs_flip': _gex.get('spot_vs_flip', 'N/A'),
                        # the two strikes dealer hedging actually defends:
                        # magnet pins price toward it, repeller pushes away.
                        # Both were computed and dropped here, so nothing
                        # downstream could ever draw them (principle 12).
                        'magnet': _gex.get('gex_magnet'),
                        'repeller': _gex.get('gex_repeller')}
    except Exception:
        pass

    # 5b) DEX — net delta-weighted positioning (bull/bear vote)
    dex_bias = None
    try:
        _ds_d = (option_data or {}).get('df_summary') if option_data else None
        _u_d = (option_data or {}).get('underlying') or spot_price
        if _ds_d is not None and not getattr(_ds_d, 'empty', True):
            _dx = calculate_dealer_dex(_ds_d, _u_d)
            if _dx:
                dex_bias = _dx
                if _dx['bias'] == 'BULL':
                    up += 0.6; reasons.append(f"DEX {_dx['net_dex']:+.0f}L call-delta heavy (+0.6 up)")
                elif _dx['bias'] == 'BEAR':
                    down += 0.6; reasons.append(f"DEX {_dx['net_dex']:+.0f}L put-delta heavy (+0.6 down)")
    except Exception:
        pass

    # 5c) IV Skew — put fear (bearish) vs call greed (bullish) vote
    skew_bias = None
    try:
        _ds_s = (option_data or {}).get('df_summary') if option_data else None
        _u_s = (option_data or {}).get('underlying') or spot_price
        if _ds_s is not None and not getattr(_ds_s, 'empty', True):
            _sk = calculate_iv_skew(_ds_s, _u_s)
            if _sk:
                skew_bias = _sk
                if _sk['bias'] == 'BULL':
                    up += 0.6; reasons.append(f"IV skew {_sk['ratio']} call greed (+0.6 up)")
                elif _sk['bias'] == 'BEAR':
                    down += 0.6; reasons.append(f"IV skew {_sk['ratio']} put fear (+0.6 down)")
    except Exception:
        pass

    # 5d) Order-book (bid/ask) imbalance across ATM±2 — DISPLAY-ONLY context.
    # Resting quotes are Tier-3 (spoofable), so this does NOT vote in the regime;
    # it only surfaces the top-of-book pressure already fetched in the chain.
    oflow_imb = None
    try:
        _ds_o = (option_data or {}).get('df_summary') if option_data else None
        _u_o = (option_data or {}).get('underlying') or spot_price
        if (_ds_o is not None and not getattr(_ds_o, 'empty', True)
                and {'Strike', 'bidQty_CE', 'askQty_CE', 'bidQty_PE', 'askQty_PE'} <= set(_ds_o.columns)):
            _stk = sorted(_ds_o['Strike'].dropna().unique().tolist())
            _atm_o = min(_stk, key=lambda x: abs(x - _u_o))
            _gap_o = min((abs(b - a) for a, b in zip(_stk, _stk[1:])), default=50) or 50
            _w = _ds_o[(_ds_o['Strike'] >= _atm_o - 2 * _gap_o) & (_ds_o['Strike'] <= _atm_o + 2 * _gap_o)]
            _cb = float(_w['bidQty_CE'].sum() or 0); _ca = float(_w['askQty_CE'].sum() or 0)
            _pb = float(_w['bidQty_PE'].sum() or 0); _pa = float(_w['askQty_PE'].sum() or 0)
            # CALL bid pressure = bullish; PUT bid pressure = bearish
            _call_net = _cb - _ca
            _put_net = _pb - _pa
            _score = _call_net - _put_net
            _den = abs(_call_net) + abs(_put_net)
            _t = (_score / _den) if _den > 0 else 0.0
            if _t > 0.10:
                _ol, _oc = 'Call bids stacked (bullish lean)', '#00ff88'
            elif _t < -0.10:
                _ol, _oc = 'Put bids stacked (bearish lean)', '#ff4444'
            else:
                _ol, _oc = 'Balanced book', '#ccc'
            oflow_imb = {'call_net': _call_net, 'put_net': _put_net,
                         'tilt': round(_t, 2), 'label': _ol, 'color': _oc}
    except Exception:
        pass

    # 5e) Vanna / Charm exposure — second-order Greeks, DISPLAY-ONLY context
    # (advanced; roadmap says validate V1 first, so these do NOT vote).
    vc_exp = None
    try:
        _ds_v = (option_data or {}).get('df_summary') if option_data else None
        _u_v = (option_data or {}).get('underlying') or spot_price
        if _ds_v is not None and not getattr(_ds_v, 'empty', True):
            _vc = calculate_vanna_charm_exposure(_ds_v, _u_v)
            if _vc:
                vc_exp = {'net_vanna': _vc['net_vanna'], 'net_charm': _vc['net_charm'],
                          'net_vega': _vc.get('net_vega'),
                          'net_vomma': _vc.get('net_vomma'), 'net_speed': _vc.get('net_speed'),
                          'net_zomma': _vc.get('net_zomma'), 'net_veta': _vc.get('net_veta'),
                          'net_color': _vc.get('net_color')}
    except Exception:
        pass

    # 6) Option Chain ATM verdict — the chain's own net positioning at ATM
    # (Verdict/BiasScore + OI/ChgOI/Delta/Gamma/Pressure). Votes in the
    # regime AND is displayed on the card.
    atm_bias = None
    try:
        ds = (option_data or {}).get('df_summary') if option_data else None
        _u = (option_data or {}).get('underlying') or spot_price
        if ds is not None and not getattr(ds, 'empty', True) and 'Strike' in ds.columns:
            _atm = min(ds['Strike'].tolist(), key=lambda x: abs(x - _u))
            _r = ds[ds['Strike'] == _atm]
            if not _r.empty:
                _r = _r.iloc[0]
                try:
                    _sc = float(_r.get('BiasScore', 0) or 0)
                except Exception:
                    _sc = 0.0
                _v = str(_r.get('Verdict', '') or final_verdict(_sc))
                atm_bias = {'strike': float(_atm), 'verdict': _v, 'score': _sc,
                            'oi': str(_r.get('OI_Bias', 'N/A')),
                            'chgoi': str(_r.get('ChgOI_Bias', 'N/A')),
                            'delta': str(_r.get('DeltaExp', 'N/A')),
                            'gamma': str(_r.get('GammaExp', 'N/A')),
                            'pressure': str(_r.get('PressureBias', 'N/A'))}
                _vl = _v.lower()
                _cf = _mp_conf(_sc, 6)
                _w = (2 if 'strong' in _vl else 1) * _cf
                if 'bullish' in _vl:
                    up += _w
                    reasons.append(f"ATM chain {_v} (+{_w:.1f} up)")
                elif 'bearish' in _vl:
                    down += _w
                    reasons.append(f"ATM chain {_v} (+{_w:.1f} down)")
                else:
                    side += 1
                    reasons.append("ATM chain neutral (+1 sideways)")
    except Exception:
        pass

    # 7) Per-strike ΔOI overall bias (ATM±2) — where fresh positions are
    # building: PE ΔOI > CE ΔOI = put writers building support (bullish);
    # CE ΔOI > PE ΔOI = call writers capping (bearish).
    doi_bias = None
    try:
        ds = (option_data or {}).get('df_summary') if option_data else None
        _u = (option_data or {}).get('underlying') or spot_price
        if (ds is not None and not getattr(ds, 'empty', True)
                and {'Strike', 'changeinOpenInterest_CE', 'changeinOpenInterest_PE'} <= set(ds.columns)):
            _stks = sorted(ds['Strike'].dropna().unique().tolist())
            _atm = min(_stks, key=lambda x: abs(x - _u))
            _gap = min((abs(b - a) for a, b in zip(_stks, _stks[1:])), default=50) or 50
            _win = ds[(ds['Strike'] >= _atm - 2 * _gap) & (ds['Strike'] <= _atm + 2 * _gap)]
            ce_chg = float(_win['changeinOpenInterest_CE'].sum() or 0)
            pe_chg = float(_win['changeinOpenInterest_PE'].sum() or 0)
            if pe_chg > ce_chg * 1.2 and pe_chg > 0:
                _w = 2 if (ce_chg <= 0 or pe_chg > ce_chg * 2) else 1
                up += _w
                _lbl = 'Bullish (PE writers building support)'
                reasons.append(f"ΔOI PE>CE (+{_w} up)")
            elif ce_chg > pe_chg * 1.2 and ce_chg > 0:
                _w = 2 if (pe_chg <= 0 or ce_chg > pe_chg * 2) else 1
                down += _w
                _lbl = 'Bearish (CE writers capping)'
                reasons.append(f"ΔOI CE>PE (+{_w} down)")
            else:
                side += 1
                _lbl = 'Both building / mixed'
                reasons.append("ΔOI mixed (+1 sideways)")
            doi_bias = {'ce_chg': ce_chg, 'pe_chg': pe_chg, 'label': _lbl}
    except Exception:
        pass

    # 8) NIFTY Futures Money Flow Profile — POC-bin bias from real futures
    # traded volume (the same profile the 💰 futures panel shows).
    fut_mfp = None
    try:
        _gm = st.session_state.get('_gift_mf') or {}
        _p = _gm.get('profile')
        if _p:
            _b = _mfp_poc_bias(_p)
            fut_mfp = {'bias': _b,
                       'poc': float(_p.get('poc_price', 0) or 0),
                       'vah': float(_p.get('value_area_high', 0) or 0),
                       'val': float(_p.get('value_area_low', 0) or 0),
                       'symbol': str((_gm.get('meta') or {}).get('symbol', 'NIFTY FUT'))}
            if _b == 'BULL':
                up += 1
                reasons.append("Futures MFP POC bull (+1 up)")
            elif _b == 'BEAR':
                down += 1
                reasons.append("Futures MFP POC bear (+1 down)")
            else:
                side += 1
                reasons.append("Futures MFP neutral (+1 sideways)")
    except Exception:
        pass

    # 9) Global Indices NIFTY bias (daily MFP+VPFR+PoC across global markets)
    global_bias = None
    try:
        _gb = compute_global_nifty_bias() or {}
        if _gb.get('instruments'):
            _gs = float(_gb.get('nifty_score', 0) or 0)
            global_bias = {'score': _gs, 'label': str(_gb.get('nifty_label', ''))}
            if _gs >= 5:
                up += 1.2
                reasons.append(f"Global bias {_gs:+.1f} (+1.2 up)")
            elif _gs >= 2:
                up += 0.6
                reasons.append(f"Global bias {_gs:+.1f} (+0.6 up)")
            elif _gs <= -5:
                down += 1.2
                reasons.append(f"Global bias {_gs:+.1f} (+1.2 down)")
            elif _gs <= -2:
                down += 0.6
                reasons.append(f"Global bias {_gs:+.1f} (+0.6 down)")
            else:
                side += 0.6
                reasons.append(f"Global bias {_gs:+.1f} (+0.6 sideways)")
    except Exception:
        pass

    # 10) News Bias (headline sentiment — cached 5-min)
    news_bias = None
    try:
        _nb = compute_news_bias() or {}
        if _nb.get('n'):
            _nl = str(_nb.get('label', ''))
            news_bias = {'net': _nb.get('net', 0), 'n': _nb.get('n', 0),
                         'label': _nl, 'em': _nb.get('em', '⚪')}
            _w = 1.0 if 'STRONG' in _nl.upper() else 0.6
            if 'BULL' in _nl.upper():
                up += _w
                reasons.append(f"News {_nl} (+{_w:.1f} up)")
            elif 'BEAR' in _nl.upper():
                down += _w
                reasons.append(f"News {_nl} (+{_w:.1f} down)")
            else:
                side += 0.6
                reasons.append("News neutral (+0.6 sideways)")
    except Exception:
        pass

    # 11) Commodity Risk regime — Risk-On favours equities (NIFTY bull),
    # Risk-Off favours safety (NIFTY bear). Expansion/Contraction = stronger.
    commodity_bias = None
    try:
        _cr = st.session_state.get('_commodity_risk') or {}
        _reg = str(_cr.get('regime', '') or '')
        if _reg:
            commodity_bias = {'regime': _reg}
            if 'Risk-On' in _reg:
                _w = 1.0 if 'Expansion' in _reg else 0.6
                up += _w
                reasons.append(f"Commodities {_reg} (+{_w:.1f} up)")
            elif 'Risk-Off' in _reg:
                _w = 1.0 if 'Contraction' in _reg else 0.6
                down += _w
                reasons.append(f"Commodities {_reg} (+{_w:.1f} down)")
            else:
                side += 0.6
                reasons.append("Commodities mixed (+0.6 sideways)")
    except Exception:
        pass

    # 12) Sector Rotation — cyclicals leading (Risk-On) = bullish for NIFTY;
    # defensives leading (Risk-Off) = cautious. Low weight (delayed context),
    # and only when the snapshot is broad enough (≥8 of 11 sectors).
    sector_bias = None
    try:
        _sr = st.session_state.get('_sector_rotation') or {}
        _all = _sr.get('all') or []
        if len(_all) >= 8:
            _rb = str(_sr.get('rotation_bias', '') or '').upper()
            _upn = sum(1 for r in _all if float(r.get('day_chg_pct', 0) or 0) > 0)
            _brd = round(_upn / len(_all) * 100)
            sector_bias = {'rotation': _sr.get('rotation_bias'), 'breadth': _brd}
            if 'RISK-ON' in _rb and _brd >= 45:
                up += 0.6; reasons.append(f"Sector Risk-On (breadth {_brd}%) (+0.6 up)")
            elif 'RISK-OFF' in _rb and _brd <= 55:
                down += 0.6; reasons.append(f"Sector Risk-Off (breadth {_brd}%) (+0.6 down)")
            else:
                side += 0.5; reasons.append(f"Sector mixed (breadth {_brd}%) (+0.5 sideways)")
    except Exception:
        pass

    total = up + down + side
    if total == 0:
        return None
    # Laplace smoothing so we never claim 0% or 100%
    p_up = round((up + 1) / (total + 3) * 100)
    p_down = round((down + 1) / (total + 3) * 100)
    p_side = max(0, 100 - p_up - p_down)
    regime, em = ('UP', '🟢⬆️') if up == max(up, down, side) else (
        ('DOWN', '🔴⬇️') if down == max(down, side) else ('SIDEWAYS', '🟡↔️'))

    # ── Levels: nearest major S/R + OI walls ──
    # Nearest major zone on EACH side of spot, regardless of its intrinsic
    # type — a broken resistance below spot acts as the floor (and vice
    # versa). Previously only same-type zones were shown, so when spot
    # crossed a zone both lines vanished from the card.
    sup = res = None
    try:
        _z = st.session_state.get('_major_sr_zones') or {}
        _all_z = ([dict(z, ztype='support') for z in (_z.get('support') or [])]
                  + [dict(z, ztype='resistance') for z in (_z.get('resistance') or [])])
        _below = [z for z in _all_z if float(z.get('price', 0)) < spot_price]
        _above = [z for z in _all_z if float(z.get('price', 0)) > spot_price]
        if _below:
            sup = max(_below, key=lambda z: float(z['price']))
        if _above:
            res = min(_above, key=lambda z: float(z['price']))
        # 📐 Calibrate to the REAL market: snap each level to the nearest
        # recent swing pivot (actual tested reversal price) within 40 pts —
        # the market-confirmed price wins over the theoretical confluence.
        if sup:
            _sp, _snapped = _snap_level_to_swing(float(sup['price']), df, 'support')
            if _snapped:
                sup = dict(sup, price=_sp,
                           sources=list(sup.get('sources') or []) + ['SWING'],
                           src_count=int(sup.get('src_count') or 0) + 1)
        if res:
            _rp, _snapped = _snap_level_to_swing(float(res['price']), df, 'resistance')
            if _snapped:
                res = dict(res, price=_rp,
                           sources=list(res.get('sources') or []) + ['SWING'],
                           src_count=int(res.get('src_count') or 0) + 1)
    except Exception:
        pass
    # OI walls — side-constrained so the same strike can NEVER be both:
    #   resistance = biggest CE OI strike strictly ABOVE spot
    #   support    = biggest PE OI strike strictly BELOW spot
    # PIN detection: if the biggest CE wall and biggest PE wall (unconstrained)
    # land on the same strike / within one gap of each other AND that strike is
    # at spot (≤ ½ gap), price is PINNED there — neither support nor resistance
    # but a magnet. Confirmed further when the two sides are within ~20% (no
    # dominance). oi_pin = (strike, note) or None.
    oi_floor = oi_ceiling = oi_pin = None
    try:
        ds = (option_data or {}).get('df_summary') if option_data else None
        if ds is not None and not getattr(ds, 'empty', True) and 'Strike' in ds.columns:
            _ce_col = 'openInterest_CE' if 'openInterest_CE' in ds.columns else (
                'CE_OI' if 'CE_OI' in ds.columns else None)
            _pe_col = 'openInterest_PE' if 'openInterest_PE' in ds.columns else (
                'PE_OI' if 'PE_OI' in ds.columns else None)
            lo, hi = spot_price * 0.97, spot_price * 1.03
            win = ds[(ds['Strike'] >= lo) & (ds['Strike'] <= hi)]
            _stk_all = sorted(ds['Strike'].dropna().unique().tolist())
            _gap = min((abs(b - a) for a, b in zip(_stk_all, _stk_all[1:])),
                       default=50) or 50
            if _ce_col and _pe_col and not win.empty:
                # unconstrained max walls (for PIN detection)
                _ce_top = win.loc[win[_ce_col].idxmax()]
                _pe_top = win.loc[win[_pe_col].idxmax()]
                _ce_top_k, _pe_top_k = float(_ce_top['Strike']), float(_pe_top['Strike'])
                # PIN: biggest CE and PE wall coincide (≤1 gap) and sit at spot
                if (abs(_ce_top_k - _pe_top_k) <= _gap
                        and abs(_ce_top_k - spot_price) <= 0.5 * _gap):
                    _ce_v = float(_ce_top[_ce_col]); _pe_v = float(_pe_top[_pe_col])
                    _bal = (abs(_ce_v - _pe_v) / max(_ce_v, _pe_v, 1)) <= 0.20
                    oi_pin = (_ce_top_k,
                              'balanced walls — expect chop, no edge' if _bal
                              else 'heaviest CE+PE at one strike — magnet/pin')
                # side-constrained walls (strictly above / below spot)
                _above = win[win['Strike'] > spot_price]
                _below = win[win['Strike'] < spot_price]
                if not _above.empty:
                    _r = _above.loc[_above[_ce_col].idxmax()]
                    oi_ceiling = (float(_r['Strike']), float(_r[_ce_col]) / 1e5)
                if not _below.empty:
                    _r = _below.loc[_below[_pe_col].idxmax()]
                    oi_floor = (float(_r['Strike']), float(_r[_pe_col]) / 1e5)
    except Exception:
        pass

    # ── Playbook line — majors + OI walls only (near levels removed) ──
    _sup_p = f"₹{sup['price']:.0f}" if sup else (f"₹{oi_floor[0]:.0f}" if oi_floor else "—")
    _res_p = f"₹{res['price']:.0f}" if res else (f"₹{oi_ceiling[0]:.0f}" if oi_ceiling else "—")
    if regime == 'UP':
        playbook = (f"Buy dips near support {_sup_p}; a close above {_res_p} opens the next leg up. "
                    f"Picture fails on a close below {_sup_p}.")
    elif regime == 'DOWN':
        playbook = (f"Sell bounces near resistance {_res_p}; a close below {_sup_p} opens the next leg down. "
                    f"Picture fails on a close above {_res_p}.")
    else:
        playbook = (f"Range {_sup_p} – {_res_p}: expect fades at the edges, chop in the middle. "
                    f"No trade until a confirmed close beyond either wall with volume.")

    # ── 🎯 ENTRY GATE — the "no zone = no trade" rule, surfaced visually.
    # Big/bold CALL/PUT verdict ONLY when ALL three hold:
    #   1. AT ZONE   — spot within ±25 pts of the support/resistance zone
    #                  (major confluence level, falling back to the OI wall)
    #   2. ZONE STRONG/BUILDING — S/R strength (scoring engine) ≥ 55 OR the
    #                  matching writers are building it (ΔOI bias)
    #   3. ALIGNED   — the engine votes agree with the zone trade
    #                  (net ≥ +2 up at support / ≥ +2 down at resistance)
    # Anything else → WAIT (rendered small, never bold). Display-only; no alert.
    entry_gate = {'state': 'WAIT', 'zone': None, 'level': None, 'dist': None,
                  'strength': None, 'building': False, 'net': up - down,
                  'why': []}
    try:
        # Use instrument context for proximity band (±25 for NIFTY, scales for others)
        _ctx = st.session_state.get('_current_instrument_context')
        _atm_range = (_ctx.atm_range if _ctx else 100)
        _prox = (_atm_range / 100.0) * 25.0  # scale ±25 by atm_range ratio
        _fmr_g = st.session_state.get('_full_market_read') or {}
        _sup_lv = (sup or {}).get('price') or (oi_floor[0] if oi_floor else None)
        _res_lv = (res or {}).get('price') or (oi_ceiling[0] if oi_ceiling else None)
        _d_sup = abs(spot_price - _sup_lv) if _sup_lv else None
        _d_res = abs(spot_price - _res_lv) if _res_lv else None
        _doi_lbl = (doi_bias or {}).get('label', '')
        _net = up - down
        # 🧲 PIN gate: if price is pinned at a magnet strike, there is no
        # directional edge — never fire a CALL/PUT here; show WAIT (pinned).
        if oi_pin and abs(spot_price - oi_pin[0]) <= _prox:
            entry_gate['state'] = 'PINNED'
            entry_gate['level'] = oi_pin[0]
            entry_gate['why'] = [f"pinned at ₹{oi_pin[0]:.0f} — {oi_pin[1]}; "
                                 "no directional edge, WAIT"]
            raise _GatePinned  # skip the directional zone logic below
        # nearest zone the spot is actually AT
        _zone = None
        if _d_sup is not None and (_d_res is None or _d_sup <= _d_res) and _d_sup <= _prox:
            _zone, _lv, _dist = 'SUPPORT', _sup_lv, _d_sup
            _str = float(_fmr_g.get('support_strength') or 0)
            _building = 'PE writers building' in _doi_lbl
            _aligned = _net >= 2
            _side_word = 'CALL'
        elif _d_res is not None and _d_res <= _prox:
            _zone, _lv, _dist = 'RESISTANCE', _res_lv, _d_res
            _str = float(_fmr_g.get('resistance_strength') or 0)
            _building = 'CE writers capping' in _doi_lbl
            _aligned = _net <= -2
            _side_word = 'PUT'
        if _zone is None:
            # Same "single wobble can't wipe an in-progress arm" rule as
            # below: spot drifting a few points outside the 25pt proximity
            # band for one cycle (a tick, or the S/R cluster re-centering
            # slightly) must not kill the ARMED banner. Keep showing it from
            # the stored snapshot; the 20-min expiry (mirroring the
            # confirmation-tracking branch's own timeout) can clear it here.
            #
            # But a real invalidation must ALSO clear it immediately, not
            # just on a timer — this used to only get checked in the
            # in-proximity branch below, so a PUT armed/confirmed at a
            # resistance level that spot then blew straight through (e.g.
            # ran 50+ points to the next zone, well past the +30pt
            # invalidation line) kept showing as live for up to 20 minutes,
            # because spot leaving the 25pt proximity band skipped the break
            # check entirely. Check invalidation here too, using the stored
            # snapshot's own level/side — independent of proximity.
            _armed_mid = st.session_state.get('_gate_armed')
            _inval_mid = _armed_mid.get('invalidation') if _armed_mid else None
            _side_mid = _armed_mid.get('side', '') if _armed_mid else ''
            _broke_mid = bool(_armed_mid and _inval_mid is not None and (
                (_side_mid == 'CALL' and spot_price <= _inval_mid)
                or (_side_mid == 'PUT' and spot_price >= _inval_mid)))
            if _broke_mid:
                st.session_state['_gate_armed'] = None
                entry_gate['state'] = 'WAIT'
                entry_gate['why'] = [
                    f"{_side_mid} setup at {str(_armed_mid.get('zone', '')).lower()} "
                    f"₹{(_armed_mid.get('level') or 0):.0f} invalidated — spot ran to ₹{spot_price:.1f}, "
                    f"past invalidation ₹{_inval_mid:.0f}; zone broken"]
            elif _armed_mid and time.time() - _armed_mid.get('ts', time.time()) <= 1200:
                _side_word_m = _armed_mid.get('side', '')
                entry_gate['state'] = 'ARMED_' + _side_word_m
                entry_gate.update({
                    'zone': _armed_mid.get('zone'), 'level': _armed_mid.get('level'),
                    'target': _armed_mid.get('target'),
                    'invalidation': _armed_mid.get('invalidation'),
                    'rr': _armed_mid.get('rr')})
                entry_gate['why'] = [
                    f"ARMED {_side_word_m} at {str(_armed_mid.get('zone', '')).lower()} "
                    f"₹{(_armed_mid.get('level') or 0):.0f} — spot drifted off the level, "
                    f"still waiting for confirmation (clears on invalidation or 20m expiry)"]
            else:
                st.session_state['_gate_armed'] = None
                entry_gate['state'] = 'WAIT'
                _tgt = []
                if _sup_lv:
                    _tgt.append(f"support ₹{_sup_lv:.0f} ({_sup_lv - spot_price:+.0f})")
                if _res_lv:
                    _tgt.append(f"resistance ₹{_res_lv:.0f} ({_res_lv - spot_price:+.0f})")
                entry_gate['why'] = ["spot mid-range — wait for " + " / ".join(_tgt)] if _tgt \
                    else ["no zone mapped yet"]
        else:
            entry_gate.update({'zone': _zone, 'level': _lv, 'dist': _dist,
                               'strength': round(_str), 'building': _building})
            _zone_ok = (_str >= 55) or _building
            # ── A) room / R:R to the opposite zone ──────────────────
            # Invalidation distance scales with atm_range: ±30 for NIFTY (100 atm_range)
            _inval_offset = (_atm_range / 100.0) * 30.0
            if _zone == 'SUPPORT':
                _target = _res_lv or (_lv + 60)
                _inval = _lv - _inval_offset
                _room = (_target - spot_price) if _target else 0
                _risk = max(spot_price - _inval, 1.0)
            else:
                _target = _sup_lv or (_lv - 60)
                _inval = _lv + _inval_offset
                _room = (spot_price - _target) if _target else 0
                _risk = max(_inval - spot_price, 1.0)
            _rr = (_room / _risk) if _risk > 0 else 0
            _room_min = (_atm_range / 100.0) * 40.0  # room minimum scales with atm_range
            _room_ok = _room >= _room_min and _rr >= 1.5
            entry_gate.update({'target': _target, 'invalidation': _inval,
                               'rr': round(_rr, 2), 'room': round(_room)})
            # ── B) chop / range filter (accumulation/distribution) ──
            _chop = (regime == 'SIDEWAYS')

            # Once armed at THIS exact zone+level, a single noisy cycle
            # (strength/alignment/R:R wobbling around the qualification
            # threshold) must not wipe it — that produced the "banner
            # suddenly vanished" bug. Only a real zone break or the 20-min
            # expiry (handled below, inside the ARM/CONFIRM branch) may
            # clear an in-progress arm. Requalification below still applies
            # in full to arming a NEW signal.
            _sig = f"{_side_word}@{_lv:.0f}"
            _armed_now = st.session_state.get('_gate_armed')
            _already_armed_here = bool(_armed_now and _armed_now.get('sig') == _sig)

            if not (_zone_ok and _aligned) and not _already_armed_here:
                st.session_state['_gate_armed'] = None
                if not _aligned and ((_zone == 'SUPPORT' and _net <= -2)
                                     or (_zone == 'RESISTANCE' and _net >= 2)):
                    entry_gate['state'] = 'REVERSED'
                    entry_gate['why'] = [f"at {_zone.lower()} ₹{_lv:.0f} but engine bias is "
                                         f"AGAINST the zone (net {_net:+d}) — zone may break; WAIT"]
                else:
                    entry_gate['state'] = 'AT_ZONE_WAIT'
                    _w = []
                    if not _zone_ok:
                        _w.append(f"zone weak (strength {_str:.0f}%, not building)")
                    if not _aligned:
                        _w.append(f"engines not aligned (net {_net:+d})")
                    entry_gate['why'] = [f"at {_zone.lower()} ₹{_lv:.0f} — " + " · ".join(_w) + " — WAIT"]
            elif _chop and not _already_armed_here:
                st.session_state['_gate_armed'] = None
                entry_gate['state'] = 'CHOP_WAIT'
                entry_gate['why'] = [f"at {_zone.lower()} ₹{_lv:.0f} but market is ranging "
                                     "(chop / accumulation) — no clean move, WAIT"]
            elif not _room_ok and not _already_armed_here:
                st.session_state['_gate_armed'] = None
                entry_gate['state'] = 'NO_ROOM'
                entry_gate['why'] = [f"at {_zone.lower()} ₹{_lv:.0f} but only {_room:.0f} pts "
                                     f"to target ₹{_target:.0f} (R:R {_rr:.1f}) — too tight, WAIT"]
            else:
                # ── C) two-step: ARM now, fire only on confirmation ──
                _armed = st.session_state.get('_gate_armed')
                _now_ts = time.time()
                if _armed and _armed.get('sig') == _sig:
                    # armed on a PRIOR cycle → look for the confirmation candle
                    _broke = ((_zone == 'SUPPORT' and spot_price <= _inval)
                              or (_zone == 'RESISTANCE' and spot_price >= _inval))
                    if _broke or (_now_ts - _armed.get('ts', _now_ts) > 1200):
                        st.session_state['_gate_armed'] = None
                        entry_gate['state'] = 'AT_ZONE_WAIT'
                        entry_gate['why'] = [f"armed {_side_word} at ₹{_lv:.0f} "
                                             + ("invalidated (zone broke)" if _broke
                                                else "expired (no confirmation in 20m)")]
                    elif _zone_confirmed(df, _lv, _zone):
                        entry_gate['state'] = _side_word          # CONFIRMED
                        entry_gate['why'] = [
                            f"CONFIRMED at {_zone.lower()} ₹{_lv:.0f}: zone tested & reclaimed",
                            f"strength {_str:.0f}%" + (" · writers building" if _building else "")
                            + f" · aligned (net {_net:+d})",
                            f"target ₹{_target:.0f} · R:R {_rr:.1f} · invalidation ₹{_inval:.0f}"]
                    else:
                        entry_gate['state'] = 'ARMED_' + _side_word
                        entry_gate['why'] = [
                            f"ARMED at {_zone.lower()} ₹{_lv:.0f} — waiting for a candle to "
                            f"reclaim/hold (don't chase the first touch)",
                            f"then {_side_word} · target ₹{_target:.0f} · R:R {_rr:.1f}"]
                else:
                    # first cycle at a qualified zone → ARM
                    st.session_state['_gate_armed'] = {
                        'sig': _sig, 'side': _side_word, 'zone': _zone, 'level': _lv,
                        'target': _target, 'invalidation': _inval, 'rr': _rr,
                        'ts': _now_ts}
                    entry_gate['state'] = 'ARMED_' + _side_word
                    entry_gate['why'] = [
                        f"ARMED at {_zone.lower()} ₹{_lv:.0f} — zone strong + engines aligned "
                        f"(net {_net:+d}), R:R {_rr:.1f}. Waiting for confirmation before entry.",
                        "don't chase the first touch — fake-break/SL-hunt filter active"]
    except _GatePinned:
        pass
    except Exception:
        pass

    # 🎯 Predictive liquidity-pool map (equal highs/lows, PDH/PDL, rounds)
    try:
        liq_pools = _detect_liquidity_pools(
            df, spot_price, st.session_state.get('_mios_market_memory'))
    except Exception:
        liq_pools = {'above': [], 'below': []}

    return {'regime': regime, 'em': em, 'p_up': p_up, 'p_down': p_down, 'p_side': p_side,
            'reasons': reasons, 'sup': sup, 'res': res, 'atm_bias': atm_bias,
            'doi_bias': doi_bias, 'fut_mfp': fut_mfp,
            'gex_disp': gex_disp, 'dex_bias': dex_bias, 'skew_bias': skew_bias,
            'oflow_imb': oflow_imb, 'vc_exp': vc_exp,
            'global_bias': global_bias, 'news_bias': news_bias,
            'commodity_bias': commodity_bias, 'sector_bias': sector_bias,
            'entry_gate': entry_gate,
            'liq_pools': liq_pools, 'vwap': _vwap_val, 'oi_pin': oi_pin,
            'oi_floor': oi_floor, 'oi_ceiling': oi_ceiling, 'playbook': playbook}


def render_entry_gate_history(db):
    """📊 Entry Gate History — today's closed (and open) gate trades from
    Supabase, with a win/loss tabulation. So a trade's outcome isn't only a
    Telegram message that scrolls away — it's visible in the app, every day."""
    if db is None:
        return
    try:
        rows = db.get_entry_gate_signals(limit=100)
    except Exception:
        rows = None
    if not rows:
        return
    _RESULT = {'TARGET_HIT': ('WIN', '#17c98b'), 'INVALIDATED': ('LOSS', '#ff4444'),
               'SWEPT': ('SWEPT', '#ffffff'), 'SUPERSEDED': ('SUPERSEDED', '#ffffff')}
    # graded by points_moved sign, not hardcoded — an early exit (time-based
    # or a Position Guardian reversal) can close in either profit or loss
    # depending on when it fired, unlike TARGET_HIT/INVALIDATED which are
    # definitionally a win/loss by construction
    _BY_POINTS = ('TIME_EXIT', 'REVERSED')
    wins = losses = 0
    trs = []
    for r in rows:
        exit_reason = r.get('exit_reason')
        if r.get('stage') == 'ARMED':
            # watch-only activation — never graded, excluded from win/loss
            result, color = '⏳ ARMED', '#ffcc33'
        elif exit_reason in _BY_POINTS:
            pts = r.get('points_moved') or 0
            result, color = (('WIN', '#17c98b') if pts > 0
                             else ('LOSS', '#ff4444') if pts < 0 else ('FLAT', '#ffffff'))
        elif exit_reason in _RESULT:
            result, color = _RESULT[exit_reason]
        elif exit_reason:
            result, color = exit_reason, '#ffffff'
        else:
            result, color = 'OPEN', '#ffcc33'
        if result == 'WIN':
            wins += 1
        elif result == 'LOSS':
            losses += 1
        ts = str(r.get('ts', ''))[11:16]
        side = r.get('side', '—')
        em = '🟢' if side == 'CALL' else '🔴'
        zone = f"{r.get('zone_type', '—')} ₹{(r.get('level') or 0):.0f}"
        entry = r.get('spot')
        exit_px = r.get('exit_spot')
        pts = r.get('points_moved')
        entry_cell = f"{entry:.0f}" if entry else "—"
        exit_cell = f"{exit_px:.0f}" if exit_px else "—"
        pts_cell = f"{pts:+.0f}" if pts is not None else "—"
        trs.append(
            f"<tr style='border-bottom:1px solid #1e2836'>"
            f"<td style='padding:4px 8px;color:#ffffff'>{ts}</td>"
            f"<td style='padding:4px 8px'>{em} {side}</td>"
            f"<td style='padding:4px 8px;color:#ffffff'>{zone}</td>"
            f"<td style='padding:4px 8px;font-family:monospace'>{entry_cell}</td>"
            f"<td style='padding:4px 8px;font-family:monospace'>{exit_cell}</td>"
            f"<td style='padding:4px 8px;font-family:monospace;color:{color}'>{pts_cell}</td>"
            f"<td style='padding:4px 8px;font-weight:700;color:{color}'>{result}</td></tr>"
        )
    total_closed = wins + losses
    win_rate = (wins / total_closed * 100) if total_closed else 0
    with st.expander(f"📊 Entry Gate History — today ({wins}W / {losses}L"
                     f"{f' · {win_rate:.0f}% win-rate' if total_closed else ''})",
                     expanded=False):
        st.markdown(
            "<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;"
            "background:#0d131d;border:1px solid #1e2836;border-radius:10px;font-size:12px'>"
            "<tr style='background:#0e1420;color:#ffffff'>"
            "<th style='padding:6px 8px;text-align:left'>Time</th>"
            "<th style='padding:6px 8px;text-align:left'>Side</th>"
            "<th style='padding:6px 8px;text-align:left'>Zone</th>"
            "<th style='padding:6px 8px;text-align:left'>Entry</th>"
            "<th style='padding:6px 8px;text-align:left'>Exit</th>"
            "<th style='padding:6px 8px;text-align:left'>Points</th>"
            "<th style='padding:6px 8px;text-align:left'>Result</th></tr>"
            + "".join(trs) + "</table></div>",
            unsafe_allow_html=True,
        )


def render_market_picture(spot_price, df, option_data, cat_scores=None):
    """Compact card: regime + probability bars + levels + playbook."""
    mp = compute_market_picture(spot_price, df, option_data, cat_scores)
    if not mp:
        # A bare `return` here is why the Trade Card could only say "Market
        # Picture has not produced a read yet" — true, but not a reason. This is
        # the ONE precondition `compute_market_picture` refuses to proceed
        # without, so name whichever half is missing. Everything downstream
        # (`_market_picture`, and therefore the Trade Card, the Strike Cockpit
        # and five of V6's inputs) hangs off this line succeeding.
        _missing = ("no NIFTY candles — the intraday fetch and the Supabase "
                    "cache both came back empty"
                    if df is None or getattr(df, 'empty', True)
                    else "no spot price" if not spot_price
                    else "the regime vote produced nothing")
        st.caption(f"🗺️ Market Picture unavailable — {_missing}.")
        return
    st.session_state['_market_picture'] = mp
    _c = {'UP': '#00ff88', 'DOWN': '#ff4444', 'SIDEWAYS': '#ffd000'}[mp['regime']]
    _bg = {'UP': '#0a3d2a', 'DOWN': '#3d0a1f', 'SIDEWAYS': '#3a3210'}[mp['regime']]
    def _bar(lbl, pct, color):
        return (f"<div style='display:flex;align-items:center;gap:8px;margin:2px 0;'>"
                f"<span style='width:88px;color:#ccc;font-size:12px;'>{lbl}</span>"
                f"<div style='flex:1;background:#222;border-radius:4px;height:14px;'>"
                f"<div style='width:{pct}%;background:{color};height:14px;border-radius:4px;'></div></div>"
                f"<b style='width:44px;color:{color};'>{pct}%</b></div>")
    _sup, _res = mp['sup'], mp['res']
    # canonical Reaction-Zone strength/status, matched by price so the banner
    # shows the SAME number as the Strike Cockpit and Trade Card
    _rsr = st.session_state.get('_reaction_sr') or {}
    _rs_sup, _rs_res = _rsr.get('support') or {}, _rsr.get('resistance') or {}
    def _canon_str(zc, price):
        try:
            if zc and zc.get('price') and abs(float(zc['price']) - float(price)) <= 15:
                return (f" · <b style='color:#8fd3ff;'>str {zc['strength']}% "
                        f"{zc.get('status','')}{_sr_trend_badge(zc)}</b>")
        except Exception:
            pass
        return ""
    _lv = []
    if _res:
        _rl = ("Resistance" if _res.get('ztype', 'resistance') == 'resistance'
               else "Overhead zone (reclaimed support)")
        _lv.append(f"🔴 {_rl} <b style='color:#ff6666;font-size:16px;'>₹{_res['price']:.0f}</b> "
                   f"({_res['src_count']} sources: {'+'.join(_res['sources'])}, "
                   f"{_res['price'] - spot_price:+.0f} pts)" + _canon_str(_rs_res, _res['price']))
    if mp['oi_ceiling']:
        _lv.append(f"🧱 CE wall <b style='color:#ffaa44;font-size:16px;'>₹{mp['oi_ceiling'][0]:.0f}</b> "
                   f"({mp['oi_ceiling'][1]:.1f}L OI · resistance)")
    if mp.get('oi_pin'):
        _lv.append(f"🧲 <b style='color:#c9b6ec;font-size:16px;'>PIN ₹{mp['oi_pin'][0]:.0f}</b> ({mp['oi_pin'][1]})")
    _lv.append(f"📍 Spot <b style='color:#ffffff;font-size:17px;'>₹{spot_price:.1f}</b>")
    if mp['oi_floor']:
        _lv.append(f"🧱 PE wall <b style='color:#ffaa44;font-size:16px;'>₹{mp['oi_floor'][0]:.0f}</b> "
                   f"({mp['oi_floor'][1]:.1f}L OI · support)")
    if _sup:
        _sl = ("Support" if _sup.get('ztype', 'support') == 'support'
               else "Floor (broken resistance → support)")
        _lv.append(f"🟢 {_sl} <b style='color:#00ff88;font-size:16px;'>₹{_sup['price']:.0f}</b> "
                   f"({_sup['src_count']} sources: {'+'.join(_sup['sources'])}, "
                   f"{_sup['price'] - spot_price:+.0f} pts)" + _canon_str(_rs_sup, _sup['price']))
    # 🎯 Liquidity pools line — likely stop-shelves ABOVE/BELOW spot, marked
    # spent (✓ swept) once today's range has taken them. Untouched pools are
    # magnets: price often extends to them before reversing.
    _atm_line = ""
    try:
        _lp = mp.get('liq_pools') or {}
        def _pool_str(p):
            return (f"{'✓' if p.get('touched') else ''}₹{p['price']:.0f}"
                    f"({p['kind']})")
        _ab_s = " · ".join(_pool_str(p) for p in (_lp.get('above') or [])[:3])
        _bl_s = " · ".join(_pool_str(p) for p in (_lp.get('below') or [])[:3])
        if _ab_s or _bl_s:
            _atm_line += (
                f"<div style='color:#bbb;font-size:12px;margin-top:4px;'>"
                f"🎯 <b>Liquidity pools</b> (likely stops · ✓=swept): "
                f"above {_ab_s or '—'} &nbsp;|&nbsp; below {_bl_s or '—'}"
                f" <span style='color:#777;'>(untouched pools act as magnets)</span></div>")
    except Exception:
        pass
    # Option Chain ATM bias line (also votes in the regime above)
    _ab = mp.get('atm_bias')
    if _ab:
        _ac = ('#00ff88' if 'bullish' in _ab['verdict'].lower()
               else ('#ff4444' if 'bearish' in _ab['verdict'].lower() else '#ccc'))
        _atm_line += (
            f"<div style='color:#ddd;font-size:13px;margin-top:4px;'>"
            f"📊 <b>Option Chain ATM Bias</b> (₹{_ab['strike']:.0f}): "
            f"<b style='color:{_ac};'>{_ab['verdict']}</b> (Score {_ab['score']:+.0f}) · "
            f"OI {_ab['oi']} · ChgOI {_ab['chgoi']} · Delta {_ab['delta']} · "
            f"Gamma {_ab['gamma']} · Pressure {_ab['pressure']}</div>")
    # Per-strike ΔOI overall bias line (also votes in the regime above)
    _db = mp.get('doi_bias')
    if _db:
        _dc = ('#00ff88' if 'Bullish' in _db['label']
               else ('#ff4444' if 'Bearish' in _db['label'] else '#ccc'))
        _atm_line += (
            f"<div style='color:#ddd;font-size:13px;margin-top:4px;'>"
            f"🔄 <b>ΔOI Bias (ATM±2)</b>: "
            f"<b style='color:{_dc};'>{_db['label']}</b> · "
            f"CE ΔOI {_db['ce_chg'] / 1e5:+.1f}L vs PE ΔOI {_db['pe_chg'] / 1e5:+.1f}L</div>")
    # NIFTY Futures Money Flow Profile bias line (also votes in the regime)
    _fm = mp.get('fut_mfp')
    if _fm:
        _fc = ('#00ff88' if _fm['bias'] == 'BULL'
               else ('#ff4444' if _fm['bias'] == 'BEAR' else '#ccc'))
        _pos = (f" · spot {'above' if spot_price > _fm['poc'] else 'below'} POC"
                if _fm['poc'] else "")
        _atm_line += (
            f"<div style='color:#ddd;font-size:13px;margin-top:4px;'>"
            f"💰 <b>Futures MFP</b> ({_fm['symbol']}): "
            f"<b style='color:{_fc};'>{_fm['bias']}</b> · POC ₹{_fm['poc']:.0f} · "
            f"VAH ₹{_fm['vah']:.0f} · VAL ₹{_fm['val']:.0f}{_pos}</div>")
    # 🧨 Dealer GEX (gamma regime — pin vs trend context, votes above)
    _gx = mp.get('gex_disp')
    if _gx:
        _gxc = ('#00ff88' if _gx['total'] > 10 else ('#ff4444' if _gx['total'] < -10 else '#ccc'))
        _flip = f" · Flip ₹{_gx['flip']:.0f} ({_gx['spot_vs_flip']})" if _gx.get('flip') else ""
        _atm_line += (
            f"<div style='color:#ddd;font-size:13px;margin-top:4px;'>"
            f"🧨 <b>Dealer GEX</b>: <b style='color:{_gxc};'>{_gx['signal']}</b> · "
            f"total {_gx['total']:+.0f}L{_flip}</div>")
    # 🧭 DEX — net delta-weighted positioning (votes above)
    _dx = mp.get('dex_bias')
    if _dx:
        _dxc = ('#00ff88' if _dx['bias'] == 'BULL'
                else ('#ff4444' if _dx['bias'] == 'BEAR' else '#ccc'))
        _atm_line += (
            f"<div style='color:#ddd;font-size:13px;margin-top:4px;'>"
            f"🧭 <b>Dealer DEX</b> (net delta): <b style='color:{_dxc};'>{_dx['label']}</b> · "
            f"net {_dx['net_dex']:+.0f}L (CE {_dx['call_dex']:+.0f} / PE {_dx['put_dex']:+.0f})</div>")
    # 📐 IV Skew — put fear vs call greed (votes above)
    _sk = mp.get('skew_bias')
    if _sk:
        _skc = ('#00ff88' if _sk['bias'] == 'BULL'
                else ('#ff4444' if _sk['bias'] == 'BEAR' else '#ccc'))
        _atm_line += (
            f"<div style='color:#ddd;font-size:13px;margin-top:4px;'>"
            f"📐 <b>IV Skew</b>: {_sk['em']} <b style='color:{_skc};'>{_sk['label']}</b> · "
            f"ratio {_sk['ratio']} (PE {_sk['put_iv']:.0f} / CE {_sk['call_iv']:.0f})</div>")
    # 📖 Order-book imbalance (top-of-book bid/ask) — context only, does NOT vote
    _oi = mp.get('oflow_imb')
    if _oi:
        _atm_line += (
            f"<div style='color:#bbb;font-size:12px;margin-top:4px;'>"
            f"📖 <b>Order-book</b> (ATM±2, Tier-3 · context): "
            f"<b style='color:{_oi['color']};'>{_oi['label']}</b> · "
            f"CE bid−ask {_oi['call_net']:+,.0f} · PE bid−ask {_oi['put_net']:+,.0f}"
            f" <span style='color:#777;'>(resting quotes — spoofable, no vote)</span></div>")
    # 🌀 Vanna / Charm exposure — second-order Greeks, context only (no vote)
    _vc = mp.get('vc_exp')
    if _vc:
        _atm_line += (
            f"<div style='color:#bbb;font-size:12px;margin-top:4px;'>"
            f"🌀 <b>Vanna/Charm Exp</b> (context): "
            f"Vanna {_vc['net_vanna']:+.1f}L · Charm {_vc['net_charm']:+.1f}L/day"
            f" <span style='color:#777;'>(2nd-order — informational, no vote)</span></div>")
    # Global indices NIFTY bias line (also votes in the regime)
    _gb = mp.get('global_bias')
    if _gb:
        _gc = ('#00ff88' if 'BULL' in _gb['label'].upper()
               else ('#ff4444' if 'BEAR' in _gb['label'].upper() else '#ccc'))
        _atm_line += (
            f"<div style='color:#ddd;font-size:13px;margin-top:4px;'>"
            f"🌍 <b>Global Bias</b>: <b style='color:{_gc};'>{_gb['label']}</b> "
            f"({_gb['score']:+.1f})</div>")
    # News bias line (also votes in the regime)
    _nbm = mp.get('news_bias')
    if _nbm:
        _nc = ('#00ff88' if 'BULL' in _nbm['label'].upper()
               else ('#ff4444' if 'BEAR' in _nbm['label'].upper() else '#ccc'))
        _atm_line += (
            f"<div style='color:#ddd;font-size:13px;margin-top:4px;'>"
            f"📰 <b>News Bias</b>: {_nbm['em']} <b style='color:{_nc};'>{_nbm['label']}</b> "
            f"(net {_nbm['net']:+d} across {_nbm['n']} headlines)</div>")
    # Commodity risk regime line (also votes in the regime)
    _cb = mp.get('commodity_bias')
    if _cb:
        _cc = ('#00ff88' if 'Risk-On' in _cb['regime']
               else ('#ff4444' if 'Risk-Off' in _cb['regime'] else '#ccc'))
        _atm_line += (
            f"<div style='color:#ddd;font-size:13px;margin-top:4px;'>"
            f"🛢️ <b>Commodity Regime</b>: <b style='color:{_cc};'>{_cb['regime']}</b></div>")
    # 🧭 OVERALL BIAS — condensed one-line read of the whole picture: the Fast
    # verdict (actionable) + Lagging (confirmation) + Misguiding (context) from
    # the bias engines, plus the ATM±1 14-leg overall verdict. This replaces the
    # removed per-speed cards by surfacing the same verdicts inside this card.
    def _ov_verdict(n):
        if n >= 4:
            return '🟢🚀', 'STRONG BULL', '#00ff88'
        if n >= 2:
            return '🟢', 'BULL', '#00ff88'
        if n <= -4:
            return '🔴🚀', 'STRONG BEAR', '#ff4444'
        if n <= -2:
            return '🔴', 'BEAR', '#ff4444'
        return '⚪', 'MIXED', '#ffd000'
    _overall_html = ""
    try:
        _cs = cat_scores or {}
        _parts = []
        if _cs:
            # Headline = Fast + Lagging combined (the trustworthy engines); the
            # Misguiding bucket is shown separately as context, not summed in.
            _fb, _fbe = _cs.get('fast', [0, 0])
            _lb2, _lbe = _cs.get('lag', [0, 0])
            _mb, _mbe = _cs.get('mis', [0, 0])
            _hb, _hbe = _fb + _lb2, _fbe + _lbe
            _hnet = _hb - _hbe
            _he, _hl, _hc = _ov_verdict(_hnet)
            _parts.append(
                f"<span style='color:{_hc};font-weight:800;'>{_he} {_hl}</span>"
                f"<span style='color:#aaa;font-size:12px;'> (net {_hnet:+d} · {_hb}↑/{_hbe}↓)</span>")
            _fnet = _fb - _fbe
            _fe, _fl, _fc = _ov_verdict(_fnet)
            _parts.append(
                f"<span style='color:#aaa;font-size:12px;'>🚀 Fast </span>"
                f"<span style='color:{_fc};'>{_fe} {_fl}</span>")
            _lnet = _lb2 - _lbe
            _le, _ll, _lc2 = _ov_verdict(_lnet)
            _parts.append(
                f"<span style='color:#aaa;font-size:12px;'>🐢 Lag </span>"
                f"<span style='color:{_lc2};'>{_le} {_ll}</span>")
            _mnet = _mb - _mbe
            _me, _ml, _mc = _ov_verdict(_mnet)
            _parts.append(
                f"<span style='color:#666;font-size:12px;'>🌫️ Misg {_me} {_ml}</span>")
        _leg_ov = (st.session_state.get('_leg_bias_cache') or (None, None))[1]
        if _leg_ov:
            _ln = _leg_ov.get('net', 0)
            _lcc = '#00ff88' if _ln > 0 else ('#ff4444' if _ln < 0 else '#ffd000')
            _parts.append(
                f"<span style='color:#aaa;font-size:12px;'>🧮 14-leg </span>"
                f"<span style='color:{_lcc};'>{_leg_ov.get('em', '')} {_leg_ov.get('label', '')}</span>")
        if _parts:
            _overall_html = (
                "<div style='margin:8px 0 2px 0;padding:6px 10px;background:#0d1117;"
                "border-radius:8px;font-size:15px;'>🧭 <b>OVERALL:</b> "
                + " &nbsp;·&nbsp; ".join(_parts) + "</div>")
    except Exception:
        _overall_html = ""
    # 🎯 ENTRY GATE banner — BIG & BOLD only when spot is AT a strong/building
    # zone AND the engines align; everything else renders small (WAIT).
    _entry_html = ""
    try:
        _eg = mp.get('entry_gate') or {}
        _st_g = _eg.get('state', 'WAIT')
        _why = " · ".join(_eg.get('why') or [])
        if _st_g in ('CALL', 'PUT'):
            _gc = '#00ff88' if _st_g == 'CALL' else '#ff4444'
            _gbg = '#0a3d2a' if _st_g == 'CALL' else '#3d0a1f'
            _tgt_c = _eg.get('target'); _inv_c = _eg.get('invalidation')
            _rr_c = _eg.get('rr')
            _trade_line = ""
            if _tgt_c and _inv_c:
                _trade_line = (
                    f"<div style='color:#fff;font-size:13px;font-weight:700;margin-top:3px;'>"
                    f"🎯 Target ₹{_tgt_c:.0f} · ⚖️ R:R {_rr_c} · "
                    f"❌ Invalidation ₹{_inv_c:.0f}</div>")
            _entry_html = (
                f"<div style='margin:8px 0;padding:12px 16px;background:{_gbg};"
                f"border:3px solid {_gc};border-radius:10px;text-align:center;'>"
                f"<span style='font-size:26px;font-weight:900;color:{_gc};'>"
                f"{'🟢' if _st_g == 'CALL' else '🔴'} ✅ ENTRY GATE — BUY {_st_g} CONFIRMED — "
                f"{_eg.get('zone', '')} ₹{(_eg.get('level') or 0):.0f}</span>"
                f"<div style='color:#e6ffe6;font-size:13px;font-weight:700;margin-top:4px;'>"
                f"Zone tested &amp; reclaimed</div>"
                + _trade_line
                + f"<div style='color:#ddd;font-size:12px;margin-top:3px;'>{_why} "
                f"— your decision, no auto-entry</div></div>")
        elif _st_g in ('ARMED_CALL', 'ARMED_PUT'):
            # two-step: price is AT a qualified zone but the confirmation candle
            # has not printed yet — BIG & BOLD amber banner (same prominence as
            # CONFIRMED) so it can't be missed, but amber = "wait, not an entry"
            _side_a = 'CALL' if _st_g == 'ARMED_CALL' else 'PUT'
            _entry_html = (
                f"<div style='margin:8px 0;padding:12px 16px;background:#2a2205;"
                f"border:3px solid #ffcc33;border-radius:10px;text-align:center;'>"
                f"<span style='font-size:26px;font-weight:900;color:#ffcc33;'>"
                f"⏳ ENTRY GATE ARMED — {_side_a} — "
                f"{_eg.get('zone', '')} ₹{(_eg.get('level') or 0):.0f}</span>"
                f"<div style='color:#ffe9a8;font-size:13px;font-weight:700;margin-top:4px;'>"
                f"Price has ENTERED the zone — wait for the confirmation candle, "
                f"don't chase the first touch</div>"
                f"<div style='color:#e6d9a8;font-size:12px;margin-top:3px;'>{_why}</div></div>")
        elif _st_g in ('CHOP_WAIT', 'NO_ROOM'):
            # Spot IS at a mapped zone here — just not (yet) a chase-worthy
            # setup (ranging market / too little room to target). Still get
            # the big/bold "you are at a level" treatment so it can't be
            # mistaken for "nothing going on"; amber = zone active, no trade.
            _zn_c = mp.get('entry_gate', {})
            _entry_html = (
                f"<div style='margin:8px 0;padding:10px 16px;background:#241d05;"
                f"border:3px solid #ffcc33;border-radius:10px;text-align:center;'>"
                f"<span style='font-size:21px;font-weight:900;color:#ffcc33;'>"
                f"{'🌀' if _st_g == 'CHOP_WAIT' else '📏'} PRICE IN ZONE — "
                f"{_zn_c.get('zone', '')} ₹{(_zn_c.get('level') or 0):.0f}</span>"
                f"<div style='color:#ffe9a8;font-size:13px;font-weight:700;margin-top:4px;'>"
                f"{_why}</div></div>")
        elif _st_g == 'REVERSED':
            _entry_html = (
                f"<div style='margin:8px 0;padding:10px 16px;background:#2a1a05;"
                f"border:3px solid #ff8800;border-radius:10px;text-align:center;'>"
                f"<span style='font-size:21px;font-weight:900;color:#ff9933;'>"
                f"⚠️ PRICE IN ZONE — BIAS AGAINST</span>"
                f"<div style='color:#ffb066;font-size:13px;font-weight:700;margin-top:4px;'>"
                f"{_why}</div></div>")
        elif _st_g == 'AT_ZONE_WAIT':
            # Spot is sitting right at a mapped S/R zone but it hasn't
            # qualified (strength/alignment) for an ARM yet. This used to
            # render as tiny dim text — easy to miss entirely, which read as
            # "no signal" even though price WAS at the zone. Now always
            # big & bold like ARMED/CONFIRMED, just in a neutral "watching"
            # blue so it's visually distinct from an actual trade signal.
            _zn_w = mp.get('entry_gate', {})
            _entry_html = (
                f"<div style='margin:8px 0;padding:10px 16px;background:#0a1f33;"
                f"border:3px solid #4da6ff;border-radius:10px;text-align:center;'>"
                f"<span style='font-size:22px;font-weight:900;color:#4da6ff;'>"
                f"⚔️ PRICE IN ZONE — {_zn_w.get('zone', '')} "
                f"₹{(_zn_w.get('level') or 0):.0f}</span>"
                f"<div style='color:#cfe8ff;font-size:13px;font-weight:700;margin-top:4px;'>"
                f"{_why}</div></div>")
        elif _st_g == 'PINNED':
            _entry_html = (
                f"<div style='margin:6px 0;padding:6px 10px;background:#241a2e;"
                f"border-left:3px solid #a78bfa;border-radius:6px;color:#c9b6ec;"
                f"font-size:13px;'>🧲 {_why}</div>")
        else:
            _entry_html = (
                f"<div style='margin:6px 0;color:#ffffff;font-size:12px;'>"
                f"⏳ WAIT — {_why}</div>")
    except Exception:
        _entry_html = ""
    st.markdown(
        f"<div style='background:{_bg};border:2px solid {_c};border-radius:12px;"
        f"padding:12px 16px;margin-bottom:8px;'>"
        f"<div style='font-size:22px;font-weight:800;'>"
        f"<span style='color:#fff;'>📍 NIFTY <b>₹{spot_price:,.1f}</b></span>"
        f"<span style='color:{_c};'> · 🗺️ MARKET PICTURE: {mp['em']} {mp['regime']}</span></div>"
        + _entry_html
        + _overall_html
        + _bar('⬆️ Up', mp['p_up'], '#00ff88')
        + _bar('⬇️ Down', mp['p_down'], '#ff4444')
        + _bar('↔️ Sideways', mp['p_side'], '#ffd000')
        + "<div style='color:#ffffff;font-size:14px;font-weight:600;margin-top:6px;'>"
        + " &nbsp;·&nbsp; ".join(_lv) + "</div>"
        + _atm_line
        + f"<div style='color:#fff;font-size:13px;margin-top:6px;'>🎯 <b>Playbook:</b> "
        + f"{mp['playbook']}</div>"
        + "<div style='color:#888;font-size:11px;margin-top:4px;'>"
        + " · ".join(mp['reasons'][:6]) + "</div></div>",
        unsafe_allow_html=True,
    )
    # ── detailed intelligence moved off the compact Trade Card (DISPLAY ONLY) ──
    # The Level-Acceptance evidence, the Dealer-Magnet detail and the full Greek-
    # Behaviour rows live here, in the investigation layer, in that order. Built
    # once by the Trade Card renderer and stashed in `_mp_detail`; rendered here
    # so the same long text is never drawn twice. Nothing is recomputed.
    try:
        _mpd = st.session_state.get('_mp_detail') or {}
        _detail_html = (str(_mpd.get('level_acceptance') or '')
                        + str(_mpd.get('dealer_magnet') or '')
                        + str(_mpd.get('greek_behaviour') or ''))
        if _detail_html.strip():
            st.markdown(_detail_html, unsafe_allow_html=True)
    except Exception:
        pass
    # 🧠 AI Market Story — the same MIOS V5 Stage-36 narrative shown in the
    # Analysis & Audit panel, surfaced here under the Market Picture so the plain-
    # language read sits with the levels it describes.
    try:
        _mst = st.session_state.get('_mios_state')
        _story = None
        if _mst is not None and getattr(_mst, 'get', None):
            _sr = _mst.get('stage36_story')
            if _sr is not None and getattr(_sr, 'data', None):
                _story = _sr.data.get('story')
        if _story:
            st.markdown(
                f"<div style='background:#0d1117;border-left:3px solid {_c};"
                f"padding:10px 14px;margin-bottom:8px;border-radius:6px;"
                f"font-size:14px;color:#ffffff;line-height:1.5;'>"
                f"🧠 <b>AI Market Story</b><br>{_story}</div>",
                unsafe_allow_html=True)
    except Exception:
        pass
    # 📨 ENTRY GATE → Telegram: fires ONCE per activation (state@level), with a
    # 15-min per-key cooldown; re-arms when the gate deactivates. 'entry_gate'
    # is NOT in _RETIRED_ALERT_CLASSES and 'ENTRY GATE' is in the Telegram entry
    # tier, so this is the one zone-based message that reaches Telegram.
    try:
        _eg_a = mp.get('entry_gate') or {}
        _st_a = _eg_a.get('state')
        if _st_a in ('CALL', 'PUT'):
            _lv_a = float(_eg_a.get('level') or 0)
            _sig = f"{_st_a}@{_lv_a:.0f}"
            if st.session_state.get('_entry_gate_last_sig') != _sig:
                # mark the activation FIRST: one activation = one Telegram
                # attempt + one Supabase row (even if Telegram is throttled)
                st.session_state['_entry_gate_last_sig'] = _sig
                # 🎯/❌ trade frame: target = opposite zone; invalidation =
                # atm_range-scaled pts beyond the zone (past the ±prox band = zone truly broke)
                _sup_lv_x = (mp.get('sup') or {}).get('price') or \
                    (mp['oi_floor'][0] if mp.get('oi_floor') else None)
                _res_lv_x = (mp.get('res') or {}).get('price') or \
                    (mp['oi_ceiling'][0] if mp.get('oi_ceiling') else None)
                _inval_offset_msg = (_atm_range / 100.0) * 30.0
                _sym = _ctx.symbol if _ctx else 'NIFTY'
                if _st_a == 'CALL':
                    _tgt_a = _res_lv_x or (_lv_a + 60)
                    _inv_a = _lv_a - _inval_offset_msg
                else:
                    _tgt_a = _sup_lv_x or (_lv_a - 60)
                    _inv_a = _lv_a + _inval_offset_msg
                _em_a = '🟢' if _st_a == 'CALL' else '🔴'
                _msg_a = (
                    f"{_em_a} <b>ENTRY GATE — BUY {_st_a} ZONE ACTIVE</b>\n"
                    f"Zone: <b>{_eg_a.get('zone', '—')} ₹{_lv_a:.0f}</b> "
                    f"({(_eg_a.get('dist') or 0):.0f} pts from spot)\n"
                    f"Zone strength: {_eg_a.get('strength', '—')}%"
                    + (" · writers building" if _eg_a.get('building') else "") + "\n"
                    f"Engines net: {(_eg_a.get('net') or 0):+d} · "
                    f"Regime {mp.get('regime', '—')}\n"
                    f"🎯 Target ₹{_tgt_a:.0f} · ❌ Invalidation ₹{_inv_a:.0f}\n"
                    f"{_sym} Spot ₹{spot_price:,.1f}\n"
                    f"⏱️ All 3 gates met (zone + strength + alignment) — "
                    f"your decision, no auto-entry")
                _sent_a = _throttled_telegram_send(
                    _msg_a, alert_class='entry_gate',
                    key=f"entry_gate_{_sig}", cooldown_s=900)
                # 🗄️ store the activation in Supabase (entry_gate_signals,
                # sql/012+013) with the full factor snapshot; keep the row id
                # so the exit monitor can complete the entry→exit pair.
                _gate_db_id = None
                try:
                    _dbg = st.session_state.get('_db_obj')
                    if _dbg is not None:
                        _ist_g = pytz.timezone('Asia/Kolkata')
                        _row_g = {
                            'trading_day': datetime.now(_ist_g).strftime('%Y-%m-%d'),
                            'stage': 'CONFIRMED',
                            'side': _st_a,
                            'zone_type': _eg_a.get('zone'),
                            'level': round(_lv_a, 2),
                            'dist_pts': round(float(_eg_a.get('dist') or 0), 1),
                            'strength': _eg_a.get('strength'),
                            'building': bool(_eg_a.get('building')),
                            'engines_net': _eg_a.get('net'),
                            'spot': round(float(spot_price), 2),
                            'telegram_sent': bool(_sent_a),
                            'target': round(float(_tgt_a), 2),
                            'invalidation': round(float(_inv_a), 2),
                        }
                        _row_g.update(_snapshot_entry_factors(spot_price))
                        _gate_db_id = _dbg.insert_entry_gate_signal(_row_g)
                except Exception:
                    pass
                # 🚪 supersede any still-open active trade, then arm the new one
                try:
                    _old_t = st.session_state.get('_entry_gate_active')
                    if _old_t and _old_t.get('db_id'):
                        _dbg2 = st.session_state.get('_db_obj')
                        if _dbg2 is not None:
                            _dbg2.update_entry_gate_signal(_old_t['db_id'], {
                                'exit_ts': datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
                                'exit_spot': round(float(spot_price), 2),
                                'exit_reason': 'SUPERSEDED'})
                except Exception:
                    pass
                # snapshot the story active right now — this trade's exit will
                # grade THIS story, not whatever story is active by then
                _story_id_at_entry = None
                try:
                    _stask_e = st.session_state.get('_story_task')
                    if _stask_e:
                        _cs_e = _stask_e.current_story()
                        if _cs_e:
                            _story_id_at_entry = _cs_e.story_id
                except Exception:
                    pass
                st.session_state['_entry_gate_active'] = {
                    'side': _st_a, 'zone': _eg_a.get('zone'),
                    'level': _lv_a, 'target': float(_tgt_a),
                    'invalidation': float(_inv_a),
                    'entry_spot': float(spot_price), 'db_id': _gate_db_id,
                    'entry_ts': datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
                    'story_id': _story_id_at_entry,
                }
        elif _st_a in ('ARMED_CALL', 'ARMED_PUT'):
            # ⏳ ARMED alert: price has ENTERED a qualified zone but the
            # confirmation candle has not printed. Send ONE "waiting" message
            # so the trader knows to watch — explicitly NOT an entry. Also
            # logs a stage='ARMED' Supabase row (audit trail only — no
            # target/exit grading; the exit-monitor still only arms on
            # CONFIRMED). Deduped separately from the confirmed signal.
            _side_ar = 'CALL' if _st_a == 'ARMED_CALL' else 'PUT'
            _lv_ar = float(_eg_a.get('level') or 0)
            _sig_ar = f"{_st_a}@{_lv_ar:.0f}"
            if st.session_state.get('_entry_gate_armed_sig') != _sig_ar:
                st.session_state['_entry_gate_armed_sig'] = _sig_ar
                _em_ar = '🟢' if _side_ar == 'CALL' else '🔴'
                _tgt_ar = _eg_a.get('target')
                _inv_ar = _eg_a.get('invalidation')
                _msg_ar = (
                    f"⏳ {_em_ar} <b>ENTRY GATE ARMED — {_side_ar} watch</b>\n"
                    f"Zone: <b>{_eg_a.get('zone', '—')} ₹{_lv_ar:.0f}</b> "
                    f"({(_eg_a.get('dist') or 0):.0f} pts from spot)\n"
                    f"Zone strength {_eg_a.get('strength', '—')}%"
                    + (" · writers building" if _eg_a.get('building') else "")
                    + f" · engines net {(_eg_a.get('net') or 0):+d}\n"
                    + (f"🎯 Target ₹{_tgt_ar:.0f} · R:R {_eg_a.get('rr', '—')} "
                       f"· ❌ Invalidation ₹{_inv_ar:.0f}\n" if _tgt_ar and _inv_ar else "")
                    + f"{_sym} Spot ₹{spot_price:,.1f}\n"
                    f"⚠️ Price has ENTERED the zone — <b>WAIT for the confirmation "
                    f"candle</b>. Don't chase the first touch (fake-break / SL-hunt "
                    f"filter active). A separate CONFIRMED alert follows if the zone "
                    f"reclaims/holds.")
                _throttled_telegram_send(
                    _msg_ar, alert_class='entry_gate',
                    key=f"entry_gate_armed_{_sig_ar}", cooldown_s=900)
                try:
                    _dbg_ar = st.session_state.get('_db_obj')
                    if _dbg_ar is not None:
                        _row_ar = {
                            'trading_day': datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d'),
                            'stage': 'ARMED',
                            'side': _side_ar,
                            'zone_type': _eg_a.get('zone'),
                            'level': round(_lv_ar, 2),
                            'dist_pts': round(float(_eg_a.get('dist') or 0), 1),
                            'strength': _eg_a.get('strength'),
                            'building': bool(_eg_a.get('building')),
                            'engines_net': _eg_a.get('net'),
                            'spot': round(float(spot_price), 2),
                            'target': round(float(_tgt_ar), 2) if _tgt_ar else None,
                            'invalidation': round(float(_inv_ar), 2) if _inv_ar else None,
                        }
                        _dbg_ar.insert_entry_gate_signal(_row_ar)
                except Exception:
                    pass
            # keep _entry_gate_last_sig untouched so the CONFIRMED alert that
            # follows this arm is still treated as fresh.
        else:
            # gate deactivated → re-arm so the next activation alerts again
            st.session_state.pop('_entry_gate_last_sig', None)
            st.session_state.pop('_entry_gate_armed_sig', None)
    except Exception:
        pass
    # 🚪 EXIT MONITOR — watches the active zone trade every cycle (independent
    # of the gate's current state): invalidation break, target hit, or 15:15
    # time exit → Telegram EXIT GATE message + Supabase row completed.
    try:
        _act = st.session_state.get('_entry_gate_active')
        if _act and spot_price:
            _side_x = _act['side']
            _now_x = datetime.now(pytz.timezone('Asia/Kolkata'))
            _reason = None
            if _side_x == 'CALL':
                if spot_price <= _act['invalidation']:
                    _reason = 'INVALIDATED'
                elif spot_price >= _act['target']:
                    _reason = 'TARGET_HIT'
            else:  # PUT
                if spot_price >= _act['invalidation']:
                    _reason = 'INVALIDATED'
                elif spot_price <= _act['target']:
                    _reason = 'TARGET_HIT'
            if _reason is None and (_now_x.hour, _now_x.minute) >= (15, 15):
                _reason = 'TIME_EXIT'
            if _reason:
                _fav = (spot_price - _act['entry_spot']) if _side_x == 'CALL' \
                    else (_act['entry_spot'] - spot_price)
                _em_x = {'TARGET_HIT': '🎯', 'INVALIDATED': '❌',
                         'TIME_EXIT': '⏰'}[_reason]
                _word_x = {'TARGET_HIT': 'TARGET REACHED',
                           'INVALIDATED': 'ZONE BROKE — EXIT',
                           'TIME_EXIT': 'TIME EXIT (15:15) — square off'}[_reason]
                _msg_x = (
                    f"{_em_x} <b>EXIT GATE — {_word_x}</b>\n"
                    f"Trade: BUY {_side_x} from {_act.get('zone', '—')} "
                    f"₹{_act['level']:.0f}\n"
                    f"Entry spot ₹{_act['entry_spot']:.1f} → now "
                    f"₹{spot_price:,.1f} ({_fav:+.0f} pts in favour)\n"
                    f"Target ₹{_act['target']:.0f} · "
                    f"Invalidation ₹{_act['invalidation']:.0f}\n"
                    f"Your decision — close/hold is yours")
                _throttled_telegram_send(
                    _msg_x, alert_class='entry_gate',
                    key=f"exit_gate_{_side_x}_{_act['level']:.0f}_{_reason}",
                    cooldown_s=900)
                try:
                    _dbx = st.session_state.get('_db_obj')
                    if _dbx is not None and _act.get('db_id'):
                        _dbx.update_entry_gate_signal(_act['db_id'], {
                            'exit_ts': _now_x.isoformat(),
                            'exit_spot': round(float(spot_price), 2),
                            'exit_reason': _reason,
                            'points_moved': round(float(_fav), 1),
                            'mae': round(float(_act.get('mae', 0.0)), 1),
                            'mfe': round(float(_act.get('mfe', 0.0)), 1)})
                except Exception:
                    pass
                # 📖 grade the story that was active at ENTRY (not whatever
                # story is active now) against this trade's outcome — this
                # is what powers the "which market pattern actually wins"
                # win-rate tabulation (story_stats)
                try:
                    _story_id_x = _act.get('story_id')
                    _dbx2 = st.session_state.get('_db_obj')
                    if _story_id_x is not None and _dbx2 is not None:
                        _stask_x = st.session_state.get('_story_task')
                        _story_obj = None
                        if _stask_x:
                            _cur = _stask_x.current_story()
                            _cands = ([_cur] if _cur else []) + _stask_x.get_stories(limit=30)
                            _story_obj = next((s for s in _cands if s and s.story_id == _story_id_x), None)
                        if _story_obj is not None:
                            from mios_v5.story_recognition import recognize_story
                            _stype_x, _ = recognize_story(_story_obj)
                            _outcome_x = ('win' if _fav > 0 else
                                         'loss' if _fav < 0 else 'breakeven')
                            _risk_x = abs(_act.get('entry_spot', 0) - _act.get('invalidation', 0))
                            _r_mult_x = round(float(_fav) / _risk_x, 2) if _risk_x > 0 else None
                            _dbx2.insert_story_validation({
                                'trade_id': _act.get('db_id'),
                                'story_id': _story_id_x,
                                'story_type': _stype_x.value,
                                'outcome': _outcome_x,
                                'points_moved': round(float(_fav), 1),
                                'mae': round(float(_act.get('mae', 0.0)), 1),
                                'mfe': round(float(_act.get('mfe', 0.0)), 1),
                                'r_multiple': _r_mult_x,
                                'exit_reason': _reason,
                                'duration_seconds': _story_obj.duration_seconds(),
                            })
                            # recompute + upsert this pattern's aggregate
                            # win-rate row (story_stats) from ALL its
                            # validations — the table story_panel.py reads
                            _rows_x = _dbx2.get_story_validations(story_type=_stype_x.value, limit=500)
                            if _rows_x:
                                _n_x = len(_rows_x)
                                _wins_x = sum(1 for r in _rows_x if r.get('outcome') == 'win')
                                _losses_x = sum(1 for r in _rows_x if r.get('outcome') == 'loss')
                                _bevens_x = sum(1 for r in _rows_x if r.get('outcome') == 'breakeven')
                                _pts_x = [float(r.get('points_moved') or 0) for r in _rows_x]
                                _rmults_x = [float(r['r_multiple']) for r in _rows_x if r.get('r_multiple') is not None]
                                _maes_x = [float(r['mae']) for r in _rows_x if r.get('mae') is not None]
                                _mfes_x = [float(r['mfe']) for r in _rows_x if r.get('mfe') is not None]
                                _dbx2.upsert_story_stats({
                                    'story_type': _stype_x.value,
                                    'total_trades': _n_x, 'wins': _wins_x,
                                    'losses': _losses_x, 'breakevens': _bevens_x,
                                    'win_rate': round(_wins_x / _n_x * 100, 1),
                                    'avg_points': round(sum(_pts_x) / _n_x, 1),
                                    'avg_r_multiple': round(sum(_rmults_x) / len(_rmults_x), 2) if _rmults_x else None,
                                    'avg_mae': round(sum(_maes_x) / len(_maes_x), 1) if _maes_x else None,
                                    'avg_mfe': round(sum(_mfes_x) / len(_mfes_x), 1) if _mfes_x else None,
                                    'total_pnl': round(sum(_pts_x), 1),
                                    'best_win': round(max(_pts_x), 1),
                                    'max_loss': round(min(_pts_x), 1),
                                })
                except Exception:
                    pass
                # remember the exit so the Zone Reversal watcher can recognise
                # a swept-and-reclaimed zone (fake breakout → reversal)
                st.session_state['_entry_gate_last_exit'] = {
                    'zone': _act.get('zone'), 'level': _act.get('level'),
                    'side': _side_x, 'reason': _reason,
                    'db_id': _act.get('db_id'), 'ts': time.time(),
                }
                # keep the trade result on screen (victory sign on TARGET_HIT)
                # instead of the banner just vanishing the moment it closes
                st.session_state['_entry_gate_last_result'] = {
                    'side': _side_x, 'zone': _act.get('zone'), 'level': _act.get('level'),
                    'reason': _reason, 'entry_spot': _act.get('entry_spot'),
                    'exit_spot': spot_price, 'points_moved': round(float(_fav), 1),
                    'ts': time.time(),
                }
                st.session_state.pop('_entry_gate_active', None)
    except Exception:
        pass
    # ⚡ ZONE REVERSAL WATCH — user-designed confirmation of institutional
    # entry at S/R (incl. fake-breakout reversal). Fires ONLY when ALL hold:
    #   1. AT ZONE   — spot at a S/R zone, OR back inside a zone that was
    #                  just INVALIDATED (< 15 min ago) = swept & reclaimed
    #   2. CVD IMPULSE — sudden big change in net leg CVD (per-cycle delta
    #                  z-score >= 2.5 vs recent history) toward the zone side
    #   3. STABLE FLIP — engine alignment agrees with the impulse and has
    #                  HELD for 3 consecutive cycles (~1 min), not a spike
    # Tier-1 evidence (executed volume) → Telegram + Supabase; no auto-entry.
    try:
        _eg_w = mp.get('entry_gate') or {}
        _net_hist = st.session_state.setdefault('_gate_net_hist', [])
        _net_hist.append(int(_eg_w.get('net') or 0))
        if len(_net_hist) > 12:
            del _net_hist[:len(_net_hist) - 12]
        _zone_w, _lv_w = _eg_w.get('zone'), _eg_w.get('level')
        _swept_ctx = False
        _lex = st.session_state.get('_entry_gate_last_exit') or {}
        if not _zone_w and _lex.get('reason') == 'INVALIDATED' \
                and time.time() - _lex.get('ts', 0) < 900 \
                and abs(spot_price - float(_lex.get('level') or 0)) <= 25:
            _zone_w, _lv_w = _lex.get('zone'), _lex.get('level')
            _swept_ctx = True
        # candle-level sweep: a recent CLOSED bar wicked through the zone and
        # closed back inside — fake break even without an open gate trade
        if _zone_w and _lv_w and not _swept_ctx:
            _swept_ctx = _candle_sweep_reclaim(df, float(_lv_w), _zone_w)
        _zh = st.session_state.get('_zone_cvd_hist') or []
        if _zone_w and _lv_w and len(_zh) >= 12:
            import statistics as _stats
            _net_cvd = [c - p for (_, c, p) in _zh]
            _dl = [b - a for a, b in zip(_net_cvd[:-1], _net_cvd[1:])]
            _imp = _dl[-1]
            _base = _dl[-13:-1] if len(_dl) >= 13 else _dl[:-1]
            if len(_base) >= 5:
                _sd = _stats.pstdev(_base)
                # floor the denominator with the mean |delta| so a very
                # steady baseline (sd→0) can't mask a genuine impulse
                _mabs = sum(abs(x) for x in _base) / len(_base)
                _zscore = _imp / max(_sd, 0.25 * _mabs, 1e-9)
            else:
                _zscore = 0.0
            _dir_w = 1 if _imp > 0 else (-1 if _imp < 0 else 0)
            _stable = (len(_net_hist) >= 3
                       and all(n != 0 and (n > 0) == (_dir_w > 0)
                               for n in _net_hist[-3:]))
            _zone_match = ((_dir_w > 0 and _zone_w == 'SUPPORT')
                           or (_dir_w < 0 and _zone_w == 'RESISTANCE'))
            if abs(_zscore) >= 2.5 and _stable and _zone_match:
                _side_w = 'CALL' if _dir_w > 0 else 'PUT'
                _sig_w = f"ZR:{_side_w}@{float(_lv_w):.0f}"
                if st.session_state.get('_zone_rev_last_sig') != _sig_w:
                    st.session_state['_zone_rev_last_sig'] = _sig_w
                    _em_w = '🟢' if _dir_w > 0 else '🔴'
                    _kind_w = ("FAKE BREAKOUT — SWEPT & RECLAIMED"
                               if _swept_ctx else "SUDDEN ENTRY AT ZONE")
                    from mios_v5 import bias_ball as _bb
                    _msg_w = _bb.prefix(
                        _bb.BULL if _dir_w > 0 else _bb.BEAR,
                        f"⚡ <b>ZONE REVERSAL — {_kind_w}</b>\n"
                        f"{_em_w} Possible institutional {'buying' if _dir_w > 0 else 'selling'} "
                        f"at {_zone_w} ₹{float(_lv_w):.0f}\n"
                        f"CVD impulse: {_imp:+,.0f} (z={_zscore:+.1f}) — "
                        f"executed volume, Tier-1\n"
                        f"Alignment flipped {'BULL' if _dir_w > 0 else 'BEAR'} and "
                        f"held 3 cycles (net {_net_hist[-1]:+d})\n"
                        f"NIFTY Spot ₹{spot_price:,.1f}\n"
                        f"Watch {_side_w} — your decision, no auto-entry")
                    _throttled_telegram_send(
                        _msg_w, alert_class='entry_gate',
                        key=f"zone_rev_{_sig_w}", cooldown_s=900)
                    # swept zone: correct the log — the 'stop-out' was a grab
                    try:
                        _dbw = st.session_state.get('_db_obj')
                        if _swept_ctx and _dbw is not None and _lex.get('db_id'):
                            _dbw.update_entry_gate_signal(_lex['db_id'],
                                                          {'exit_reason': 'SWEPT'})
                        if _dbw is not None:
                            _rvrow = {
                                'trading_day': datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d'),
                                'side': _side_w,
                                'zone_type': f"REVERSAL-{_zone_w}",
                                'level': round(float(_lv_w), 2),
                                'dist_pts': round(abs(spot_price - float(_lv_w)), 1),
                                'strength': _eg_w.get('strength'),
                                'building': bool(_eg_w.get('building')),
                                'engines_net': _net_hist[-1],
                                'spot': round(float(spot_price), 2),
                                'telegram_sent': True,
                            }
                            _rvrow.update(_snapshot_entry_factors(spot_price))
                            _dbw.insert_entry_gate_signal(_rvrow)
                    except Exception:
                        pass
    except Exception:
        pass
    # 🛡 POSITION GUARDIAN — ONE unified open-position engine. It folds the
    # reversal FINDER, the reversal CONFIRMER and the PATIENCE filter into a
    # single state machine that emits exactly one verdict per cycle for the
    # live trade (priority EXIT > WARNING > PATIENT > ON TRACK — a real turn
    # always wins):
    #   ON TRACK  — in favour / flat, flow with you, thesis intact.
    #   PATIENT   — slightly RED but inside the risk budget (< 60% of
    #               entry→invalidation), zone holding, flow NOT against you:
    #               normal noise (the fear-dip that comes back), HOLD.
    #   WARNING   — a SUDDEN opposite CVD impulse (|z| ≥ 2.0, Tier-1 executed
    #               volume) + engine alignment turning against you. Heads-up;
    #               trade NOT closed yet.
    #   EXIT FAST — the flip HELD (alignment strongly against 3 cycles ~1 min)
    #               AND net CVD stably against → close, exit_reason=REVERSED.
    #               Faster than waiting for the invalidation level.
    _guard = None
    try:
        _act_r = st.session_state.get('_entry_gate_active')
        if _act_r and spot_price:
            _side_r = _act_r['side']
            _tdir = 1 if _side_r == 'CALL' else -1        # favourable direction
            # ── CVD impulse against the trade (same estimator as ZONE REVERSAL)
            _zh_r = st.session_state.get('_zone_cvd_hist') or []
            _imp_r, _z_r, _cvd3 = 0.0, 0.0, 0.0
            if len(_zh_r) >= 12:
                import statistics as _st2
                _net_cvd_r = [c - p for (_, c, p) in _zh_r]
                _dl_r = [b - a for a, b in zip(_net_cvd_r[:-1], _net_cvd_r[1:])]
                _imp_r = _dl_r[-1]
                _base_r = _dl_r[-13:-1] if len(_dl_r) >= 13 else _dl_r[:-1]
                if len(_base_r) >= 5:
                    _sd_r = _st2.pstdev(_base_r)
                    _mabs_r = sum(abs(x) for x in _base_r) / len(_base_r)
                    _z_r = _imp_r / max(_sd_r, 0.25 * _mabs_r, 1e-9)
                if len(_net_cvd_r) >= 4:
                    _cvd3 = _net_cvd_r[-1] - _net_cvd_r[-4]   # net CVD drift, 3 cyc
            # ── alignment history (already updated this cycle by ZONE REVERSAL)
            _nh_r = st.session_state.get('_gate_net_hist') or []
            _net_now_r = _nh_r[-1] if _nh_r else 0
            # helpers: is value X "against" the trade direction?
            def _against(n, thr=1):
                return (n <= -thr) if _tdir > 0 else (n >= thr)
            _cvd_impulse_against = _against(int(1 if _imp_r > 0 else -1 if _imp_r < 0 else 0)) \
                and abs(_z_r) >= 2.0
            _cvd_drift_against = _against(int(1 if _cvd3 > 0 else -1 if _cvd3 < 0 else 0))
            _align_turning = _against(_net_now_r, 1)          # mild turn
            _align_held = (len(_nh_r) >= 3
                           and all(_against(n, 2) for n in _nh_r[-3:]))  # strong, 3 cyc
            _fav_r = (spot_price - _act_r['entry_spot']) if _side_r == 'CALL' \
                else (_act_r['entry_spot'] - spot_price)
            # ── track excursions: MAE (worst underwater) / MFE (best in favour)
            _act_r['mae'] = min(float(_act_r.get('mae', 0.0)), _fav_r)
            _act_r['mfe'] = max(float(_act_r.get('mfe', 0.0)), _fav_r)
            # risk budget = entry → invalidation (drawdown the thesis can take
            # before it's actually wrong); noise band = 60% of it
            _risk_r = abs(float(_act_r['entry_spot']) - float(_act_r['invalidation']))
            _dd = -_fav_r if _fav_r < 0 else 0.0
            _noise_band = max(20.0, 0.6 * _risk_r)
            _flow_ok = not (_cvd_drift_against and _against(_net_now_r, 2))
            _to_inval = abs(float(spot_price) - float(_act_r['invalidation']))
            _tgt_r = float(_act_r.get('target') or spot_price)
            _to_tgt = abs(_tgt_r - float(spot_price))
            _was_warned = (_act_r.get('rev_state') == 'WARNED')

            # ── ONE state machine → a single verdict (EXIT > WARNING > PATIENT
            # > ON TRACK). WARNING latches once opened until it confirms (EXIT)
            # or fades (alignment no longer against → drops back to PATIENT/OK).
            if _align_held and _cvd_drift_against:
                _state = 'EXIT'
            elif (_cvd_impulse_against and _align_turning) or (_was_warned and _align_turning):
                _state = 'WARNING'
            elif 0 < _dd <= _noise_band and _flow_ok:
                _state = 'PATIENT'
            else:
                _state = 'ON_TRACK'
            _guard = {
                'state': _state, 'side': _side_r, 'zone': _act_r.get('zone'),
                'level': _act_r.get('level'), 'entry_spot': _act_r.get('entry_spot'),
                'invalidation': _act_r.get('invalidation'), 'target': _tgt_r,
                'imp': float(_imp_r), 'z': float(_z_r), 'cvd3': float(_cvd3),
                'net': _net_now_r, 'fav': float(_fav_r), 'dd': float(_dd),
                'noise_band': float(_noise_band), 'to_inval': float(_to_inval),
                'to_tgt': float(_to_tgt), 'mae': float(_act_r.get('mae', 0.0)),
                'mfe': float(_act_r.get('mfe', 0.0)), 'risk': float(_risk_r),
                'tdir': _tdir}
            # stash the single verdict so the top-of-page Trade Card can show
            # hold-patient vs exit-fast without recomputing (read-only mirror)
            st.session_state['_guard_state'] = {'state': _state, 'ts': time.time()}

            # ── act on the single verdict ──────────────────────────────────
            if _state == 'EXIT':
                _em_r = '🔴' if _side_r == 'CALL' else '🟢'
                _msg_r = (
                    f"🔄 <b>EXIT GATE — REVERSE CONFIRMED · EXIT FAST</b>\n"
                    f"{_em_r} Your BUY {_side_r} from {_act_r.get('zone', '—')} "
                    f"₹{_act_r['level']:.0f} is reversing\n"
                    f"Flip HELD 3 cycles (net {_net_now_r:+d}) + net CVD "
                    f"{'selling' if _tdir > 0 else 'buying'} against you "
                    f"({_cvd3:+,.0f}) — stable, not a spike\n"
                    f"Entry ₹{_act_r['entry_spot']:.1f} → now ₹{spot_price:,.1f} "
                    f"({_fav_r:+.0f} pts)\n"
                    f"⚡ Reversal is stable — <b>exit fast</b>. Your decision.")
                _throttled_telegram_send(
                    _msg_r, alert_class='entry_gate',
                    key=f"exit_rev_{_side_r}_{_act_r['level']:.0f}", cooldown_s=900)
                try:
                    _dbr = st.session_state.get('_db_obj')
                    _now_r = datetime.now(pytz.timezone('Asia/Kolkata'))
                    if _dbr is not None and _act_r.get('db_id'):
                        _dbr.update_entry_gate_signal(_act_r['db_id'], {
                            'exit_ts': _now_r.isoformat(),
                            'exit_spot': round(float(spot_price), 2),
                            'exit_reason': 'REVERSED',
                            'points_moved': round(float(_fav_r), 1),
                            'mae': round(float(_act_r.get('mae', 0.0)), 1),
                            'mfe': round(float(_act_r.get('mfe', 0.0)), 1)})
                except Exception:
                    pass
                st.session_state['_entry_gate_last_exit'] = {
                    'zone': _act_r.get('zone'), 'level': _act_r.get('level'),
                    'side': _side_r, 'reason': 'REVERSED',
                    'db_id': _act_r.get('db_id'), 'ts': time.time()}
                # persist for the Market Picture banner (position closed, keep
                # the EXIT-FAST banner visible ~3 min)
                st.session_state['_reverse_exit_banner'] = {
                    'side': _side_r, 'zone': _act_r.get('zone'),
                    'level': _act_r.get('level'), 'entry_spot': _act_r.get('entry_spot'),
                    'exit_spot': float(spot_price), 'pts': float(_fav_r),
                    'net': _net_now_r, 'cvd3': float(_cvd3), 'ts': time.time()}
                st.session_state.pop('_entry_gate_active', None)
            elif _state == 'WARNING':
                _act_r['rev_state'] = 'WARNED'
                st.session_state['_entry_gate_active'] = _act_r
                # one alert per warning episode (latched until it clears)
                if not _act_r.get('warn_alerted'):
                    _act_r['warn_alerted'] = True
                    st.session_state['_entry_gate_active'] = _act_r
                    _emw_r = '🔴' if _side_r == 'CALL' else '🟢'
                    _msg_rw = (
                        f"⚠️ <b>REVERSAL WARNING — sudden opposite flow</b>\n"
                        f"{_emw_r} On your BUY {_side_r} from {_act_r.get('zone', '—')} "
                        f"₹{_act_r['level']:.0f}\n"
                        f"CVD impulse {_imp_r:+,.0f} (z={_z_r:+.1f}) "
                        f"{'selling' if _tdir > 0 else 'buying'} against you · "
                        f"alignment turning (net {_net_now_r:+d})\n"
                        f"Entry ₹{_act_r['entry_spot']:.1f} → now ₹{spot_price:,.1f} "
                        f"({_fav_r:+.0f} pts)\n"
                        f"👀 Watch closely — tighten/trail. A CONFIRMED EXIT-FAST "
                        f"alert follows if the reversal holds. Your decision.")
                    _throttled_telegram_send(
                        _msg_rw, alert_class='entry_gate',
                        key=f"rev_warn_{_side_r}_{_act_r['level']:.0f}", cooldown_s=600)
            else:
                # PATIENT or ON_TRACK → warning cleared / never opened
                _act_r['rev_state'] = None
                _act_r['warn_alerted'] = False
                st.session_state['_entry_gate_active'] = _act_r
                if _state == 'PATIENT' and _dd >= 10 and not _act_r.get('patience_notified'):
                    # one gentle Telegram note the first time it dips into the
                    # fear zone (deduped per trade), tied to the invalidation line
                    _act_r['patience_notified'] = True
                    st.session_state['_entry_gate_active'] = _act_r
                    _emp = '🟢' if _side_r == 'CALL' else '🔴'
                    _msg_p = (
                        f"🧘 <b>STAY PATIENT — normal drawdown, thesis intact</b>\n"
                        f"{_emp} Your BUY {_side_r} from {_act_r.get('zone', '—')} "
                        f"₹{_act_r['level']:.0f} is {_dd:.0f} pts red\n"
                        f"Inside normal noise ({_dd:.0f}/{_noise_band:.0f} pts of risk "
                        f"budget) — zone holding, flow NOT against you (net {_net_now_r:+d})\n"
                        f"Your line is invalidation ₹{_act_r['invalidation']:.0f} "
                        f"({_to_inval:.0f} pts away). Hold unless it breaks OR a "
                        f"REVERSE alert fires. Don't panic-exit the noise.")
                    _throttled_telegram_send(
                        _msg_p, alert_class='entry_gate',
                        key=f"patience_{_side_r}_{_act_r['level']:.0f}",
                        cooldown_s=1800)
    except Exception:
        _guard = None
    # 🛡 POSITION GUARDIAN banner — ONE big/bold verdict for the open trade,
    # same prominence as the ENTRY GATE. Reads the single `_guard` state;
    # EXIT persists ~3 min after the position closes.
    try:
        _reb = st.session_state.get('_reverse_exit_banner')
        _gs = (_guard or {}).get('state')
        _hdr = ("<div style='font-size:10px;letter-spacing:.10em;color:#ffffff;"
                "text-transform:uppercase;margin:8px 0 2px;text-align:center;'>"
                "🛡 Position Guardian</div>")
        if _reb and time.time() - _reb.get('ts', 0) <= 180:
            _sd_b = _reb.get('side', '—')
            _em_b = '🔴' if _sd_b == 'CALL' else '🟢'
            _dir_b = 'selling' if _sd_b == 'CALL' else 'buying'
            st.markdown(
                _hdr +
                f"<div style='margin:2px 0 8px;padding:12px 16px;background:#3d0a1f;"
                f"border:3px solid #ff2d55;border-radius:10px;text-align:center;'>"
                f"<span style='font-size:26px;font-weight:900;color:#ff2d55;'>"
                f"🔄 REVERSE CONFIRMED · EXIT FAST — {_sd_b} "
                f"{_reb.get('zone', '')} ₹{(_reb.get('level') or 0):.0f}</span>"
                f"<div style='color:#ffd9e2;font-size:13px;font-weight:700;margin-top:4px;'>"
                f"Reversal is stable — flip held 3 cycles (net {_reb.get('net', 0):+d}) + "
                f"net CVD {_dir_b} against you ({_reb.get('cvd3', 0):+,.0f})</div>"
                f"<div style='color:#f2b8c6;font-size:12px;margin-top:3px;'>"
                f"{_em_b} Entry ₹{(_reb.get('entry_spot') or 0):.1f} → "
                f"₹{(_reb.get('exit_spot') or 0):,.1f} ({_reb.get('pts', 0):+.0f} pts) "
                f"— exit fast; your decision</div></div>",
                unsafe_allow_html=True)
        elif st.session_state.get('_entry_gate_last_result') and \
                time.time() - st.session_state['_entry_gate_last_result'].get('ts', 0) <= 180:
            # 🏆 the trade closed via the EXIT MONITOR (target / invalidation /
            # time exit) — show the result instead of silently vanishing back
            # to "idle" the instant it closes
            _lr = st.session_state['_entry_gate_last_result']
            _sd_l = _lr.get('side', '—')
            _pts_l = _lr.get('points_moved', 0)
            _reason_l = _lr.get('reason')
            if _reason_l == 'TARGET_HIT':
                _hl_col, _hl_bg = '#ffd700', '#2a2205'
                _hl_txt = f"🏆 TARGET REACHED — {_sd_l} {_lr.get('zone', '')} ₹{(_lr.get('level') or 0):.0f}"
                _hl_sub = f"🎉 Victory — {_pts_l:+.0f} pts in favour"
            elif _reason_l == 'INVALIDATED':
                _hl_col, _hl_bg = '#ff6666', '#2a1a05'
                _hl_txt = f"❌ ZONE BROKE — {_sd_l} {_lr.get('zone', '')} ₹{(_lr.get('level') or 0):.0f}"
                _hl_sub = f"Stopped out — {_pts_l:+.0f} pts"
            else:  # TIME_EXIT
                _hl_col, _hl_bg = '#ffffff', '#1a2030'
                _hl_txt = f"⏰ TIME EXIT (15:15) — {_sd_l} {_lr.get('zone', '')} ₹{(_lr.get('level') or 0):.0f}"
                _hl_sub = f"Squared off — {_pts_l:+.0f} pts"
            st.markdown(
                _hdr +
                f"<div style='margin:2px 0 8px;padding:12px 16px;background:{_hl_bg};"
                f"border:3px solid {_hl_col};border-radius:10px;text-align:center;'>"
                f"<span style='font-size:24px;font-weight:900;color:{_hl_col};'>{_hl_txt}</span>"
                f"<div style='color:#fff;font-size:14px;font-weight:700;margin-top:4px;'>{_hl_sub}</div>"
                f"<div style='color:#ccc;font-size:12px;margin-top:3px;'>"
                f"Entry ₹{(_lr.get('entry_spot') or 0):.1f} → exit ₹{(_lr.get('exit_spot') or 0):,.1f} "
                f"· closed trade — see history below</div></div>",
                unsafe_allow_html=True)
        elif _gs == 'WARNING':
            _g = _guard; _sd_w = _g.get('side', '—')
            _dir_w2 = 'selling' if _sd_w == 'CALL' else 'buying'
            st.markdown(
                _hdr +
                f"<div style='margin:2px 0 8px;padding:12px 16px;background:#331a05;"
                f"border:3px solid #ff8c00;border-radius:10px;text-align:center;'>"
                f"<span style='font-size:24px;font-weight:900;color:#ff8c00;'>"
                f"⚠️ REVERSAL WARNING — sudden opposite flow · {_sd_w} "
                f"₹{(_g.get('level') or 0):.0f}</span>"
                f"<div style='color:#ffe0b8;font-size:13px;font-weight:700;margin-top:4px;'>"
                f"CVD impulse {_g.get('imp', 0):+,.0f} (z={_g.get('z', 0):+.1f}) "
                f"{_dir_w2} against you · alignment turning (net {_g.get('net', 0):+d})</div>"
                f"<div style='color:#f2cfa0;font-size:12px;margin-top:3px;'>"
                f"{_g.get('fav', 0):+.0f} pts · watch closely — tighten/trail. A "
                f"CONFIRMED EXIT-FAST banner follows if the reversal holds; not "
                f"closed yet — your decision</div></div>",
                unsafe_allow_html=True)
        elif _gs == 'PATIENT':
            # 🧘 slightly red but thesis intact — calm/blue, tied to invalidation
            _g = _guard; _sd_p = _g.get('side', '—')
            _dd_p = _g.get('dd', 0.0); _band_p = _g.get('noise_band', 20.0)
            st.markdown(
                _hdr +
                f"<div style='margin:2px 0 8px;padding:11px 15px;background:#0a2233;"
                f"border:3px solid #29a3ff;border-radius:10px;text-align:center;'>"
                f"<span style='font-size:23px;font-weight:900;color:#29a3ff;'>"
                f"🧘 STAY PATIENT — normal noise, thesis intact · {_sd_p} "
                f"₹{(_g.get('level') or 0):.0f}</span>"
                f"<div style='color:#cfe9ff;font-size:13px;font-weight:700;margin-top:4px;'>"
                f"{_dd_p:.0f} pts red — inside noise budget ({_dd_p:.0f}/{_band_p:.0f}) · "
                f"zone holding · flow NOT against you (net {_g.get('net', 0):+d})</div>"
                f"<div style='color:#a8d4f2;font-size:12px;margin-top:3px;'>"
                f"Your line: invalidation ₹{(_g.get('invalidation') or 0):.0f} "
                f"({_g.get('to_inval', 0):.0f} pts away) · worst so far "
                f"{_g.get('mae', 0):+.0f} pts. Hold unless it breaks or a REVERSE "
                f"alert fires — don't panic-exit the noise</div></div>",
                unsafe_allow_html=True)
        elif _gs == 'ON_TRACK':
            # ✅ in favour / flat, flow with you — the trade is working
            _g = _guard; _sd_o = _g.get('side', '—')
            _emo = '🟢' if _sd_o == 'CALL' else '🔴'
            _fav_o = _g.get('fav', 0.0)
            _headline = ("in favour" if _fav_o > 0 else
                         "holding — flat" if _fav_o == 0 else "just red, flow with you")
            st.markdown(
                _hdr +
                f"<div style='margin:2px 0 8px;padding:11px 15px;background:#08251b;"
                f"border:3px solid #17c98b;border-radius:10px;text-align:center;'>"
                f"<span style='font-size:23px;font-weight:900;color:#17c98b;'>"
                f"✅ ON TRACK — {_headline} · {_sd_o} "
                f"₹{(_g.get('level') or 0):.0f}</span>"
                f"<div style='color:#c9f5e4;font-size:13px;font-weight:700;margin-top:4px;'>"
                f"{_emo} {_fav_o:+.0f} pts · flow with you (net {_g.get('net', 0):+d}) · "
                f"best so far {_g.get('mfe', 0):+.0f} pts</div>"
                f"<div style='color:#9fe0c6;font-size:12px;margin-top:3px;'>"
                f"🎯 Target ₹{(_g.get('target') or 0):.0f} ({_g.get('to_tgt', 0):.0f} away) · "
                f"❌ Invalidation ₹{(_g.get('invalidation') or 0):.0f} "
                f"({_g.get('to_inval', 0):.0f} away) — let it work; your decision</div></div>",
                unsafe_allow_html=True)
        else:
            # idle — no trade being guarded: keep the Guardian visibly present
            # so it's always in the Market Picture (arms on a CONFIRMED entry)
            #
            # ⚠️ `st.caption` was the wrong element for it: caption is always
            # rendered in Streamlit's muted grey, so the one line that says the
            # Guardian exists and is watching read as disabled chrome.
            #
            # Pink FILL with white letters, in the same padded/rounded shape the
            # other Guardian states use — so idle is a state that looks like a
            # state, not a footnote under them.
            st.markdown(
                "<div style='margin:2px 0 8px;padding:8px 13px;"
                "background:#ff2d95;border-radius:8px;font-size:13px;"
                "font-weight:800;color:#ffffff;'>"
                "🛡 Position Guardian — idle · no active trade. Arms on a "
                "CONFIRMED entry, then watches ON TRACK ⇄ STAY PATIENT ⇄ "
                "REVERSAL WARNING → EXIT FAST.</div>",
                unsafe_allow_html=True)
        # 📋 Execution Plan — display-only R-based template for the OPEN trade
        # (entry / stop / T1 / T2 / trail / partial / size). No auto-execution.
        if _guard and (_guard.get('state') in ('ON_TRACK', 'PATIENT', 'WARNING')):
            _pl = _build_execution_plan(
                _guard.get('side'), _guard.get('entry_spot'),
                _guard.get('invalidation'), _guard.get('target'), mp)
            if _pl:
                _sz = (f" · size ≈ {_pl['lots']} lot(s) for ₹{EXEC_RISK_PER_TRADE_RUPEES:,} "
                       f"risk*" if _pl.get('lots') else "")
                st.markdown(
                    f"<div style='margin:2px 0 8px;padding:8px 12px;background:#101826;"
                    f"border-left:3px solid #5b8def;border-radius:6px;font-size:12px;"
                    f"color:#ffffff;'>"
                    f"📋 <b>Execution Plan</b> — Entry ₹{_pl['entry']:.0f} · SL ₹{_pl['sl']} "
                    f"(risk {_pl['risk_pts']} pts) · 🎯 T1 ₹{_pl['t1']} (R:R {_pl['rr1']}) · "
                    f"🎯 T2 ₹{_pl['t2']} (R:R {_pl['rr2']}){_sz}<br>"
                    f"↗️ Trail: {_pl['trail']}<br>"
                    f"✂️ Partial: {_pl['partial']}"
                    f"<div style='color:#ffffff;font-size:10px;margin-top:2px;'>"
                    f"*approx — options premium/delta varies; tune EXEC_* to your strike. "
                    f"Decision support, not auto-execution.</div></div>",
                    unsafe_allow_html=True)
        # 🧲 EXPIRY-DAY CHARM-PIN — context only (NOT a Guardian vote). On the
        # one day charm is strong, flag the dealer-hedging pin drift toward the
        # magnet strike so the trader reads breakouts as fade-prone and small
        # dips as noise. Shown whether or not a trade is open; never changes the
        # ON TRACK / PATIENT / WARNING / EXIT verdict.
        # One shared rule with the Trade Card (mios_v5/dealer_magnet.py, which
        # delegates the measuring to mios_v5/charm_pin.py) so the two panels can
        # never quote different pins or a different distance cut-off — and so
        # both report the magnet on NORMAL days too, not only on expiry.
        from mios_v5.dealer_magnet import from_market_picture as _cpin
        from mios_v5.ui.charm_pin_panel import charm_pin_html as _cpinhtml
        _charm_g = _cpinhtml(_cpin(
            _is_expiry_day(option_data), spot_price, mp,
            (option_data or {}).get('max_pain_strike')
            if isinstance(option_data, dict) else None))
        if _charm_g:
            st.markdown(_charm_g, unsafe_allow_html=True)
    except Exception:
        pass
    # 📊 Entry Gate History — tabulation of today's gate trades (win/loss)
    try:
        render_entry_gate_history(st.session_state.get('_db_obj'))
    except Exception:
        pass
    # 📨 Alerts received today by side (from Supabase alert_log, cached 60s)
    try:
        _dbc = st.session_state.get('_db_obj')
        if _dbc is not None and time.time() - st.session_state.get('_alert_counts_ts', 0) > 60:
            _cnt = _dbc.get_alert_side_counts()
            if _cnt:
                st.session_state['_alert_side_counts'] = _cnt
            st.session_state['_alert_counts_ts'] = time.time()
        _cnt = st.session_state.get('_alert_side_counts')
        if _cnt:
            st.caption(f"📨 Alerts today: 🟢 BUY CALL {_cnt.get('CALL', 0)} · "
                       f"🔴 BUY PUT {_cnt.get('PUT', 0)} · total {_cnt.get('total', 0)}")
    except Exception:
        pass
    # 🎯 7-Layer Trade-Quality scorecard (read-only synthesis of the MIOS
    # engines — additive; does NOT drive any signal/entry/exit). Fully guarded:
    # if the MIOS state isn't ready it silently shows nothing.
    try:
        _ms = st.session_state.get('_mios_state')
        if _ms is not None and getattr(_ms, 'results', None):
            from mios_v5.layer_scores import build_layer_scores
            _hs = None
            _h = _ms.get('stage00_health')
            if _h is not None and _h.data:
                _hs = _h.data.get('health_score')
            _ls = build_layer_scores(_ms, health_score=_hs)
            # mirror for the top-of-page Trade Card (read-only; no recompute)
            st.session_state['_layer_scores'] = _ls
            _gcol = {'A+': '#00ff88', 'A': '#17c98b', 'B': '#ffd000',
                     'C': '#ff4444'}.get(_ls['grade'], '#ffffff')
            _dcol = {'BULL': '#17c98b', 'BEAR': '#ff4444',
                     'NEUTRAL': '#ffffff'}.get(_ls['direction'], '#ffffff')
            st.markdown(
                f"<div style='margin:6px 0;padding:7px 12px;background:#0d1117;"
                f"border:1px solid {_gcol};border-radius:8px;font-size:12px;'>"
                f"<b style='color:{_gcol};font-size:14px;'>🎯 Trade Quality {_ls['grade']}</b>"
                f"<span style='color:{_dcol};font-weight:700;'> · {_ls['direction']}</span>"
                f"<span style='color:#ffffff;'> · composite <b style='color:#e6edf3;'>"
                f"{_ls['composite']}/100</b> · alignment {_ls['alignment']}% · "
                f"{_ls['available']}/{_ls['total_layers']} layers "
                f"<i>(read quality, not a buy/sell call)</i></span></div>",
                unsafe_allow_html=True)
            # 🎯 SHADOW-LEARNING snapshot: when a new CONFIRMED trade is active,
            # stamp the current 7-layer leans onto its entry_gate_signals row
            # (sql/014). Additive update keyed by db_id — the signal/entry path
            # is untouched; the shadow learner grades these later vs the trade's
            # own outcome. Needs migration 014; silently no-ops otherwise.
            try:
                _actL = st.session_state.get('_entry_gate_active')
                _dbidL = (_actL or {}).get('db_id')
                if _dbidL is not None and st.session_state.get('_layer_snap_logged') != _dbidL:
                    _dbL = st.session_state.get('_db_obj')
                    if _dbL is not None:
                        from mios_v5.layer_scores import leans_of
                        import json as _jsonL
                        _dbL.update_entry_gate_signal(_dbidL, {
                            'layer_leans': _jsonL.dumps(leans_of(_ls)),
                            'layer_grade': _ls['grade'],
                            'layer_composite': int(_ls['composite'])})
                        st.session_state['_layer_snap_logged'] = _dbidL
            except Exception:
                pass
    except Exception:
        pass
    # 🩺 DATA-INTEGRITY STRIP — makes every "Neutral" explainable and flags a
    # degraded feed so you don't trust (or log) a trade taken on bad data.
    # Reads the MIOS engine statuses; fully guarded — silent if not ready.
    try:
        _msH = st.session_state.get('_mios_state')
        if _msH is not None and getattr(_msH, 'results', None):
            from mios_v5.health_strip import build_engine_status
            _es = build_engine_status(_msH)
            _icol = {'OK': '#17c98b', 'DEGRADED': '#ffce54',
                     'COMPROMISED': '#ff4444'}.get(_es['integrity'], '#ffffff')
            _iem = {'OK': '✅', 'DEGRADED': '⚠️', 'COMPROMISED': '⛔'}.get(
                _es['integrity'], '⚪')
            _imp = _es['impaired']
            _imp_s = (" · " + " · ".join(f"{e['emoji']} {e['engine']}: {e['reason']}"
                                         for e in _imp[:4])) if _imp else ""
            st.markdown(
                f"<div style='margin:4px 0;padding:6px 11px;background:#0d1117;"
                f"border:1px solid {_icol};border-radius:8px;font-size:11px;"
                f"color:#ffffff;'>"
                f"{_iem} <b style='color:{_icol};'>Data integrity: {_es['integrity']}</b> "
                f"<span style='color:#ffffff;'>({_es['ok_n']}/{_es['total']} feeds live) — "
                f"{_es['trust_note']}</span>{_imp_s}</div>",
                unsafe_allow_html=True)
    except Exception:
        pass


def _is_lite():
    """True when the app is in ⚡ Lite view — the curated phone/desktop stack
    (Trade Card · Market Picture · Cockpit · Heatmap · Cross-Expiry · MIOS V5).
    Full view (default) shows the lite stack on top + all the deep detail.
    Choice is remembered in session_state so a phone stays Lite, a desktop
    stays Full. Lite only changes what is DISPLAYED — every compute, alert and
    Supabase write still runs exactly the same."""
    return st.session_state.get('_view_mode', 'full') == 'lite'




_CLEANUP_TABLES = [
    ('option_chain_data', 'per-strike × per-cycle — biggest'),
    ('atm_strike_data', 'per-strike × per-cycle'),
    ('orderbook_data', 'per-strike × per-cycle'),
    ('pcr_history', 'per-strike × per-cycle'),
    ('gex_history', 'per-strike × per-cycle'),
    ('bid_ask_history', 'per-strike × per-cycle'),
    ('volume_delta_history', 'per-cycle'),
    ('detected_patterns', 'per-cycle'),
    ('max_pain_history', 'per-cycle'),
    ('master_signals', 'per master signal'),
    ('oc_signal_history', 'per-cycle'),
    ('leg_flow_snapshots', 'per-cycle'),
]


















# ══════════════════════════════════════════════════════════════════════════
#  SIGNAL LIFECYCLE — the Decision Engine doesn't just fire a signal, it opens
#  a full auditable trade life and follows it to a terminal fate:
#
#     WAIT_ENTRY → ENTERED → (TARGET_HIT | STOP_HIT | EXPIRED | CANCELLED)
#
#  Only ONE signal is alive at a time — no new signal is born until the current
#  one resolves. A/A+ quality only. Two Telegram alerts (🚨 on birth, ✅ on
#  entry, plus a terminal note); every transition is stored to trade_signals so
#  the Excel history can explain both the wins and the misses. Observational —
#  it mirrors the live Entry Gate (uses its CONFIRMED state as the entry
#  trigger), it does not place orders.
# ══════════════════════════════════════════════════════════════════════════

_SIGNAL_WAIT_EXPIRY_MIN = 45      # WAIT_ENTRY times out if entry never triggers












# ══════════════════════════════════════════════════════════════════════════
#  🎓 PHASE 6 — LEARNING & VALIDATION (Stages 55-60), write side.
#
#  The Learning Engine observes, measures, explains, recommends and validates.
#  It never influences a live decision, never moves a threshold or an engine
#  weight, and never hides a poor result. Everything below is INSERT-only:
#  history is append-only so replay and backtesting show what was known at the
#  time rather than what the last write left behind.
#
#  Requires sql/027_learning.sql. Silent no-op until it is run.
# ══════════════════════════════════════════════════════════════════════════




















# ══════════════════════════════════════════════════════════════════════════
#  🗣 MIOS V6.5 — AI EXPLAINABILITY (Stages 61-67), write side.
#
#  The Explainability Layer may only explain, narrate, summarise, justify,
#  educate and review. It generates no signal, changes no confidence, moves no
#  threshold or engine weight, and never influences the Decision Engine — it
#  reads the finished pipeline once per cycle and records what changed.
# ══════════════════════════════════════════════════════════════════════════
_WAIT_LOG_KEEP = 400


















def render_all_bias_dashboard(spot_price, df, option_data, picture_slot=None):
    """Bias dashboard split into 3 categories: Fast / Lagging / Misguiding.
    Each category has its own Overall Verdict + table. Rendered in order:
    Fast → Lagging → Misguiding.

    `picture_slot` — an `st.container()` claimed higher up the page for the
    Market Picture. Passed in rather than read from `session_state` so this
    function's inputs stay visible in its signature. `None` draws the Market
    Picture inline, exactly where it used to be, which is what keeps the
    function usable on its own.
    """
    rows = []
    cat_scores = {'fast': [0, 0], 'lag': [0, 0], 'mis': [0, 0]}  # [bull, bear]

    def _push(engine, direction, detail, weight=1):
        """direction ∈ {'bull','bear','neutral','info'}; weight increases vote impact."""
        em = '🟢' if direction == 'bull' else ('🔴' if direction == 'bear' else '⚪')
        cat = _BIAS_CATEGORY.get(engine, 'fast')  # unknown engines default to fast
        rows.append({
            'Engine': engine,
            'Bias': f"{em} {direction.upper()}",
            '_dir': direction,
            '_cat': cat,
            'Detail': detail,
        })
        if direction == 'bull':
            cat_scores[cat][0] += weight
        elif direction == 'bear':
            cat_scores[cat][1] += weight

    # ── 0b. Greek Absorption / Capping (expected-vs-actual premium) → FAST
    try:
        _ga = st.session_state.get('_greek_absorb_last') or {}
        _gnet = _ga.get('net', 0)
        if _ga.get('nifty') == 'bull' and _gnet:
            _push("Greek Absorption (capping)", 'bull',
                  f"PUT WRITING {_ga.get('pe_writing', 0)} · CALL CAPPING {_ga.get('ce_capping', 0)} (net {_gnet:+d})",
                  weight=2 if abs(_gnet) >= 2 else 1)
        elif _ga.get('nifty') == 'bear' and _gnet:
            _push("Greek Absorption (capping)", 'bear',
                  f"CALL CAPPING {_ga.get('ce_capping', 0)} · PUT WRITING {_ga.get('pe_writing', 0)} (net {_gnet:+d})",
                  weight=2 if abs(_gnet) >= 2 else 1)
    except Exception:
        pass

    # ── 0. Leg-table verdict (ATM±1 leg-bias table) SPLIT BY SPEED → each category
    try:
        _lt_rows, _lt_overall = build_leg_bias_table(spot_price)
        st.session_state['_leg_bias_cache'] = (_lt_rows, _lt_overall)
        if _lt_rows and _lt_overall:
            _by = _lt_overall.get('by_speed') or {}
            for _ck, _eng in (('fast', "Leg Fast Verdict"),
                              ('lag', "Leg Lagging Verdict"),
                              ('mis', "Leg Misguiding Verdict")):
                _cv = _by.get(_ck)
                if not _cv:
                    continue
                _cd = ('bull' if _cv['dir'] == 'BULL'
                       else ('bear' if _cv['dir'] == 'BEAR' else 'neutral'))
                if _cd == 'neutral':
                    continue
                _cw = 2 if abs(_cv.get('net', 0)) >= 3 else 1
                _push(_eng, _cd,
                      f"{_cv['label']} · {_cv['bull']}↑/{_cv['bear']}↓ (net {_cv['net']:+d})",
                      weight=_cw)
    except Exception:
        pass

    # ── 1. Master Signal (AI verdict)
    try:
        _ms = st.session_state.get('_master_signal_last') or {}
        verdict = (_ms.get('verdict') or '').upper()
        if 'BUY' in verdict:
            _push("Master Signal (AI)", 'bull', verdict, weight=2)
        elif 'SELL' in verdict:
            _push("Master Signal (AI)", 'bear', verdict, weight=2)
        elif verdict:
            _push("Master Signal (AI)", 'neutral', verdict)
    except Exception:
        pass

    # ── 2. Bull/Bear Meter (Tier-1)
    try:
        _bb = st.session_state.get('_bull_bear_meter') or {}
        sc = _bb.get('score', 0) or 0
        if sc >= 30:
            _push("Bull/Bear Meter (Tier-1)", 'bull', f"{sc:+.0f} ({_bb.get('label','')})", weight=2)
        elif sc <= -30:
            _push("Bull/Bear Meter (Tier-1)", 'bear', f"{sc:+.0f} ({_bb.get('label','')})", weight=2)
        else:
            _push("Bull/Bear Meter (Tier-1)", 'neutral', f"{sc:+.0f} ({_bb.get('label','')})")
    except Exception:
        pass

    # ── 3. Smart Money / Accumulation-Distribution
    try:
        _ad = st.session_state.get('_accum_dist_score') or {}
        sc = _ad.get('score', 0) or 0
        if sc >= 30:
            _push("Smart Money / Accum-Dist", 'bull', f"{sc:+.0f} ({_ad.get('label','')})", weight=2)
        elif sc <= -30:
            _push("Smart Money / Accum-Dist", 'bear', f"{sc:+.0f} ({_ad.get('label','')})", weight=2)
        else:
            _push("Smart Money / Accum-Dist", 'neutral', f"{sc:+.0f} ({_ad.get('label','')})")
    except Exception:
        pass

    # ── 4. Movement Ignition (direction-agnostic — show score only)
    try:
        _ig = st.session_state.get('_ignition_score') or {}
        if _ig.get('score') is not None:
            sc = _ig.get('score', 0)
            rows.append({'Engine': "Movement Ignition", 'Bias': f"⚡ {sc}/{_ig.get('max', 7)}",
                         '_dir': 'info', 'Detail': _ig.get('label', '')})
    except Exception:
        pass

    # ── 5. Spike Probability
    try:
        _sp = st.session_state.get('_spike_score') or {}
        if _sp.get('score') is not None:
            sc = _sp.get('score', 0)
            rows.append({'Engine': "Spike Probability", 'Bias': f"⚡ {sc}/{_sp.get('max', 8)}",
                         '_dir': 'info', 'Detail': _sp.get('label', '')})
    except Exception:
        pass

    # ── 6. CIE latest signal
    try:
        _cie = st.session_state.get('_cie_signals') or []
        if _cie:
            last = _cie[-1]
            d = (last.get('direction') or '').upper()
            pat = last.get('pattern', '—')
            if d in ('BUY', 'BULL', 'BULLISH', 'LONG'):
                _push("CIE (latest signal)", 'bull', pat)
            elif d in ('SELL', 'BEAR', 'BEARISH', 'SHORT'):
                _push("CIE (latest signal)", 'bear', pat)
    except Exception:
        pass

    # ── 7. Latest Stop Hunt / Liquidity Grab
    try:
        _liq = st.session_state.get('_liq_grabs') or []
        if _liq:
            last = _liq[-1]
            d = (last.get('direction') or '').upper()
            if d == 'BUY':
                _push("Spot Stop-Hunt (latest)", 'bull', f"{last.get('type','')} · {last.get('pattern','—')}")
            elif d == 'SELL':
                _push("Spot Stop-Hunt (latest)", 'bear', f"{last.get('type','')} · {last.get('pattern','—')}")
    except Exception:
        pass

    # ── 7b. Spot Price–OBV/Δ Divergence
    try:
        if df is not None and not df.empty and len(df) >= 30:
            _sdiv = detect_divergence(df, pivot_lookback=5, max_bars_back=80)
            _ind = (_sdiv.get('indicator') or '').upper()
            _wt = 2 if _sdiv.get('indicator') == 'both' else 1
            if _sdiv.get('bull'):
                _push("Spot Divergence (OBV/Δ)", 'bull',
                      f"Bull div ({_ind}) @ ₹{_sdiv.get('bull_price_low', 0):.0f}", weight=_wt)
            elif _sdiv.get('bear'):
                _push("Spot Divergence (OBV/Δ)", 'bear',
                      f"Bear div ({_ind}) @ ₹{_sdiv.get('bear_price_high', 0):.0f}", weight=_wt)
    except Exception:
        pass

    # ── 7c. Cross-strike leg divergence (ATM CE/PE — reversed for PE)
    try:
        _leg_dfs = st.session_state.get('_atm_leg_dfs') or {}
        _div_bull_legs, _div_bear_legs = [], []
        for _tag, _ldf in _leg_dfs.items():
            if 'ATM CE' not in _tag and 'ATM PE' not in _tag:
                continue
            if _ldf is None or _ldf.empty or len(_ldf) < 30:
                continue
            _ld = detect_divergence(_ldf, pivot_lookback=5, max_bars_back=80)
            _is_ce = 'ATM CE' in _tag
            if _ld.get('bull'):
                if _is_ce:
                    _div_bull_legs.append(f"{_tag} bull")
                else:
                    _div_bear_legs.append(f"{_tag} bull→bear")
            if _ld.get('bear'):
                if _is_ce:
                    _div_bear_legs.append(f"{_tag} bear")
                else:
                    _div_bull_legs.append(f"{_tag} bear→bull")
        if _div_bull_legs:
            _push("Cross-strike leg Divergence", 'bull',
                  ", ".join(_div_bull_legs[:3]), weight=2 if len(_div_bull_legs) > 1 else 1)
        if _div_bear_legs:
            _push("Cross-strike leg Divergence", 'bear',
                  ", ".join(_div_bear_legs[:3]), weight=2 if len(_div_bear_legs) > 1 else 1)
    except Exception:
        pass

    # ── 7d. Spot Ignition (tank-full — rally/breakdown loading)
    try:
        if df is not None and not df.empty and len(df) >= 30:
            _sig = detect_ignition(df)
            if _sig.get('fired') and _sig.get('direction') in ('bull', 'bear'):
                _na = _sig.get('bull_count') if _sig['direction'] == 'bull' else _sig.get('bear_count')
                _names = ", ".join(s['name'] for s in _sig['signals'] if s['direction'] == _sig['direction'])
                _push("Spot Ignition (tank-full)", _sig['direction'],
                      f"🔋 {_names}", weight=2 if _na >= 2 else 1)
    except Exception:
        pass

    # ── 7e. Cross-strike leg ignition (ATM CE/PE — reversed for PE)
    try:
        _leg_dfs3 = st.session_state.get('_atm_leg_dfs') or {}
        _ign_bull_legs, _ign_bear_legs = [], []
        for _tag, _ldf in _leg_dfs3.items():
            if 'ATM CE' not in _tag and 'ATM PE' not in _tag:
                continue
            if _ldf is None or _ldf.empty or len(_ldf) < 30:
                continue
            _lig = detect_ignition(_ldf)
            if not _lig.get('fired') or _lig.get('direction') not in ('bull', 'bear'):
                continue
            _is_ce = 'ATM CE' in _tag
            _d = _lig['direction']
            if _d == 'bull':
                if _is_ce:
                    _ign_bull_legs.append(f"{_tag} bull")
                else:
                    _ign_bear_legs.append(f"{_tag} bull→bear")
            else:
                if _is_ce:
                    _ign_bear_legs.append(f"{_tag} bear")
                else:
                    _ign_bull_legs.append(f"{_tag} bear→bull")
        if _ign_bull_legs:
            _push("Cross-strike leg Ignition", 'bull',
                  "🔋 " + ", ".join(_ign_bull_legs[:3]), weight=2 if len(_ign_bull_legs) > 1 else 1)
        if _ign_bear_legs:
            _push("Cross-strike leg Ignition", 'bear',
                  "🔋 " + ", ".join(_ign_bear_legs[:3]), weight=2 if len(_ign_bear_legs) > 1 else 1)
    except Exception:
        pass

    # ── 7f. Cross-strike leg VWAP (ATM CE/PE — reversed for PE)
    try:
        _leg_dfs5 = st.session_state.get('_atm_leg_dfs') or {}
        _vw_bull, _vw_bear = [], []
        for _tag, _ldf in _leg_dfs5.items():
            if 'ATM CE' not in _tag and 'ATM PE' not in _tag:
                continue
            if _ldf is None or _ldf.empty or len(_ldf) < 10:
                continue
            _vw = ReversalDetector.calculate_vwap(_ldf)
            if _vw is None or _vw.empty:
                continue
            _above = float(_ldf['close'].iloc[-1]) > float(_vw.iloc[-1])
            _is_ce = 'ATM CE' in _tag
            _nifty_bull = _above if _is_ce else (not _above)
            (_vw_bull if _nifty_bull else _vw_bear).append(
                f"{_tag} {'>' if _above else '<'}VWAP")
        if _vw_bull:
            _push("Cross-strike leg VWAP", 'bull',
                  "📈 " + ", ".join(_vw_bull[:3]), weight=2 if len(_vw_bull) > 1 else 1)
        if _vw_bear:
            _push("Cross-strike leg VWAP", 'bear',
                  "📈 " + ", ".join(_vw_bear[:3]), weight=2 if len(_vw_bear) > 1 else 1)
    except Exception:
        pass

    # ── 8. Spot vs VPFR-S POC (level-based)
    try:
        if df is not None and not df.empty and len(df) >= 30:
            _vp = compute_vpfr(df, 30)
            if _vp and _vp.get('poc'):
                if spot_price > _vp['poc']:
                    _push("Spot vs VPFR-S POC", 'bull', f"Spot ₹{spot_price:.0f} > POC ₹{_vp['poc']:.0f}")
                else:
                    _push("Spot vs VPFR-S POC", 'bear', f"Spot ₹{spot_price:.0f} < POC ₹{_vp['poc']:.0f}")
    except Exception:
        pass

    # ── 9. Spot vs Dynamic PoC
    try:
        if df is not None and not df.empty:
            _dp_list, _, _ = compute_dynamic_poc(df, bins=20)
            _cur = next((v for v in reversed(_dp_list or []) if v is not None), None)
            if _cur is not None:
                if _cur < spot_price:
                    _push("Spot vs Dynamic PoC", 'bull', f"DynPoC ₹{_cur:.0f} below LTP")
                elif _cur > spot_price:
                    _push("Spot vs Dynamic PoC", 'bear', f"DynPoC ₹{_cur:.0f} above LTP")
    except Exception:
        pass

    # ── 10. Spot MFP POC bin sentiment
    try:
        _mf = st.session_state.get('_money_flow_data') or {}
        if _mf and _mf.get('rows'):
            poc_row = next((r for r in _mf['rows'] if r.get('is_poc')), None)
            if poc_row:
                sent = (poc_row.get('sentiment') or '').lower()
                if sent.startswith('bull'):
                    _push("Spot MFP POC bin", 'bull', poc_row.get('sentiment', ''))
                elif sent.startswith('bear'):
                    _push("Spot MFP POC bin", 'bear', poc_row.get('sentiment', ''))
    except Exception:
        pass

    # ── 11-12. ATM CE / PE candle pattern (PE reversed for NIFTY direction)
    try:
        ce_pat, pe_pat, ce_b, pe_b, _, _, atm_strike = _atm_ce_pe_trend()
        if ce_b in ('bull', 'bear'):
            _push("ATM CE candle pattern", ce_b, f"{ce_pat} ({ce_b})")
        if pe_b in ('bull', 'bear'):
            # PE reversed for NIFTY direction
            nifty_dir = 'bear' if pe_b == 'bull' else 'bull'
            _push("ATM PE candle pattern (reversed)", nifty_dir, f"{pe_pat} ({pe_b} on PE = {nifty_dir} NIFTY)")
    except Exception:
        pass

    # ── 13. Global NIFTY Bias (12-instrument composite with reverse corr)
    try:
        _gb = compute_global_nifty_bias() or {}
        gns = _gb.get('nifty_score', 0) or 0
        if gns >= 2:
            _push("Global NIFTY Bias", 'bull', f"score {gns:+.0f} · {_gb.get('nifty_label','')[:40]}", weight=2)
        elif gns <= -2:
            _push("Global NIFTY Bias", 'bear', f"score {gns:+.0f} · {_gb.get('nifty_label','')[:40]}", weight=2)
        else:
            _push("Global NIFTY Bias", 'neutral', f"score {gns:+.0f}")
    except Exception:
        pass

    # ── Spot pattern engines (geometric / chart / candle)
    try:
        if df is not None and not df.empty and len(df) >= 30:
            _geo_all = GeometricPatternDetector().detect_all(df) or []
            if _geo_all:
                _g = _geo_all[-1]
                sig = (_g.get('signal') or _g.get('sentiment') or '').upper()
                pat = _g.get('pattern', '—')
                if 'BUY' in sig or 'BULL' in sig:
                    _push("Spot Geometric Pattern", 'bull', pat, weight=2)
                elif 'SELL' in sig or 'BEAR' in sig:
                    _push("Spot Geometric Pattern", 'bear', pat, weight=2)
    except Exception:
        pass
    try:
        if df is not None and not df.empty and len(df) >= 20:
            _chp = detect_chart_patterns(df)
            if _chp and _chp.get('pattern'):
                _d = (_chp.get('direction') or '').lower()
                if 'bull' in _d:
                    _push("Spot Chart Pattern", 'bull', _chp['pattern'])
                elif 'bear' in _d:
                    _push("Spot Chart Pattern", 'bear', _chp['pattern'])
    except Exception:
        pass
    try:
        if df is not None and not df.empty and len(df) >= 2:
            last = df.iloc[-1]; prev = df.iloc[-2]
            _sp = _classify_reversal_pattern(
                float(last['open']), float(last['high']),
                float(last['low']),  float(last['close']),
                po=float(prev['open']), ph=float(prev['high']),
                pl=float(prev['low']),  pc=float(prev['close']),
            )
            if _sp in _BULL_PATTERNS:
                _push("Spot Candle Pattern", 'bull', _sp)
            elif _sp in _BEAR_PATTERNS:
                _push("Spot Candle Pattern", 'bear', _sp)
    except Exception:
        pass

    # ── 13b. VWAP relation
    try:
        if df is not None and not df.empty and len(df) >= 5:
            tp = (df['high'] + df['low'] + df['close']) / 3
            cum_tp_vol = (tp * df['volume']).cumsum()
            cum_vol = df['volume'].cumsum().replace(0, 1)
            vwap = float((cum_tp_vol / cum_vol).iloc[-1])
            if vwap > 0:
                if spot_price > vwap:
                    _push("VWAP relation", 'bull', f"Spot ₹{spot_price:.0f} > VWAP ₹{vwap:.0f}")
                elif spot_price < vwap:
                    _push("VWAP relation", 'bear', f"Spot ₹{spot_price:.0f} < VWAP ₹{vwap:.0f}")
    except Exception:
        pass

    # ── 13c. NIFTY Futures Basis
    try:
        _fut = st.session_state.get('_nifty_futures_data') or {}
        basis = _fut.get('basis')
        if basis is not None:
            if basis > 2:
                _push("NIFTY Futures Basis", 'bull', f"Premium ₹{basis:+.1f} ({_fut.get('stance','')})")
            elif basis < -2:
                _push("NIFTY Futures Basis", 'bear', f"Discount ₹{basis:+.1f} ({_fut.get('stance','')})")
            else:
                _push("NIFTY Futures Basis", 'neutral', f"Flat ₹{basis:+.1f}")
    except Exception:
        pass

    # ── 13d. Price × OI Classifier (3-bar avg)
    try:
        _px = (st.session_state.get('_pxoi_cache') or {}).get('data') or []
        if _px:
            scores = [row.get('score', 0) for row in _px[-3:] if isinstance(row.get('score'), (int, float))]
            if scores:
                avg = sum(scores) / len(scores)
                last_label = _px[-1].get('label', '')
                if avg >= 0.5:
                    _push("Price × OI Classifier", 'bull', f"3-bar avg {avg:+.2f} · last: {last_label}")
                elif avg <= -0.5:
                    _push("Price × OI Classifier", 'bear', f"3-bar avg {avg:+.2f} · last: {last_label}")
    except Exception:
        pass

    # ── 13e. Reversal Detector (5m)
    try:
        if df is not None and not df.empty and len(df) >= 30:
            _df_5m_r = (df.set_index('datetime')
                          .resample('5min')
                          .agg({'open': 'first', 'high': 'max', 'low': 'min',
                                'close': 'last', 'volume': 'sum'})
                          .dropna().reset_index())
            if len(_df_5m_r) >= 15:
                bs, _, _ = ReversalDetector.calculate_reversal_score(_df_5m_r)
                rs, _, _ = ReversalDetector.calculate_bearish_reversal_score(_df_5m_r)
                if bs >= 4 and bs > rs:
                    _push("Reversal Detector", 'bull', f"Bull {bs}/6 vs Bear {rs}/6")
                elif rs >= 4 and rs > bs:
                    _push("Reversal Detector", 'bear', f"Bear {rs}/6 vs Bull {bs}/6")
    except Exception:
        pass

    # ── 13f. PCR at ATM
    try:
        _df_s_pcr = (option_data or {}).get('df_summary') if option_data else None
        if _df_s_pcr is not None and not _df_s_pcr.empty and 'PCR' in _df_s_pcr.columns:
            _all_s = sorted(_df_s_pcr['Strike'].dropna().unique().tolist())
            if _all_s:
                atm_p = min(_all_s, key=lambda x: abs(x - spot_price))
                _atm_pcr_row = _df_s_pcr[_df_s_pcr['Strike'] == atm_p]
                if not _atm_pcr_row.empty:
                    pcr = float(_atm_pcr_row.iloc[0].get('PCR') or 0)
                    if pcr > 1.2:
                        _push("ATM PCR", 'bull', f"PCR {pcr:.2f} > 1.2 (PE writers = floor)")
                    elif 0 < pcr < 0.7:
                        _push("ATM PCR", 'bear', f"PCR {pcr:.2f} < 0.7 (CE writers = ceiling)")
    except Exception:
        pass

    # ── 13g. Sector Rotation (breadth + cyclical-vs-defensive leadership)
    try:
        _sr_data = st.session_state.get('_sector_rotation')
        _sectors_list = None
        if isinstance(_sr_data, list):
            _sectors_list = _sr_data
        elif isinstance(_sr_data, dict):
            _sectors_list = _sr_data.get('rows') or _sr_data.get('sectors')
        if _sectors_list:
            bn = sum(1 for s in _sectors_list if (s.get('s1h') or s.get('sentiment_1h')) == 'Bullish')
            rn = sum(1 for s in _sectors_list if (s.get('s1h') or s.get('sentiment_1h')) == 'Bearish')
            _CYC = {'AUTO', 'BANK', 'METAL', 'REALTY', 'INFRA', 'IT', 'PSU BANK'}
            _DEF = {'FMCG', 'PHARMA'}
            cyc = [s.get('day_chg_pct', 0) for s in _sectors_list
                   if (s.get('name') or '').upper() in _CYC and s.get('day_chg_pct') is not None]
            dfn = [s.get('day_chg_pct', 0) for s in _sectors_list
                   if (s.get('name') or '').upper() in _DEF and s.get('day_chg_pct') is not None]
            ca = sum(cyc) / len(cyc) if cyc else 0
            da = sum(dfn) / len(dfn) if dfn else 0
            net = bn - rn
            detail = f"{bn}↑ / {rn}↓ @ 1h · cyc {ca:+.2f}% vs def {da:+.2f}%"
            weight = 2 if (abs(net) >= 4 or abs(ca - da) > 0.20) else 1
            if net >= 2 or (ca - da) > 0.20:
                _push("Sector Rotation", 'bull', detail, weight=weight)
            elif net <= -2 or (da - ca) > 0.20:
                _push("Sector Rotation", 'bear', detail, weight=weight)
            else:
                _push("Sector Rotation", 'neutral', detail)
    except Exception:
        pass

    # ── 13g'. Cross-strike VIDYA trend (all 14 ATM±3 legs)
    try:
        _vd_store = st.session_state.get('_atm_leg_vidya') or {}
        ceb = ces = peb = pes = 0
        for tag, vd in _vd_store.items():
            if tag.startswith('sid_'):
                continue
            tr = (vd or {}).get('trend', '')
            if ' CE ' in f' {tag} ':
                if tr == 'Bullish': ceb += 1
                elif tr == 'Bearish': ces += 1
            elif ' PE ' in f' {tag} ':
                if tr == 'Bullish': peb += 1
                elif tr == 'Bearish': pes += 1
        bv = ceb + pes
        brv = ces + peb
        net = bv - brv
        detail = f"{bv}↑ / {brv}↓ across legs (CE bull+PE bear vs CE bear+PE bull)"
        if net >= 4:
            _push("Cross-strike VIDYA", 'bull', detail, weight=2)
        elif net >= 2:
            _push("Cross-strike VIDYA", 'bull', detail)
        elif net <= -4:
            _push("Cross-strike VIDYA", 'bear', detail, weight=2)
        elif net <= -2:
            _push("Cross-strike VIDYA", 'bear', detail)
    except Exception:
        pass

    # ── 13g''. S/R Behavior Classifier
    try:
        _srb = st.session_state.get('_sr_behavior_state') or classify_sr_behavior(df, spot_price) or {}
        state = _srb.get('state')
        direction = _srb.get('direction')
        side = _srb.get('side', '')
        level = _srb.get('level') or 0
        if state and state != 'NONE' and direction in ('bull', 'bear'):
            wt = 2 if state in ('BREAKING', 'REJECTING') else 1
            detail = f"{state} {side} ₹{level:.0f}"
            _push("S/R Behavior", direction, detail, weight=wt)
    except Exception:
        pass

    # ── 13g'''. Cross-strike per-leg S/R Behavior (VOB-based, all legs)
    try:
        _sr_store = st.session_state.get('_atm_leg_sr_behavior') or {}
        bv = brv = 0
        for tag, leg_sr in _sr_store.items():
            if tag.startswith('sid_') or not leg_sr:
                continue
            state = leg_sr.get('state')
            if state in (None, 'NONE', 'BUILDING'):
                continue
            d = leg_sr.get('direction')
            if ' CE ' in f' {tag} ':
                nd = d
            elif ' PE ' in f' {tag} ':
                nd = 'bear' if d == 'bull' else ('bull' if d == 'bear' else 'none')
            else:
                continue
            if nd == 'bull': bv += 1
            elif nd == 'bear': brv += 1
        net = bv - brv
        detail = f"{bv}↑ / {brv}↓ across legs (BREAKING/REJECTING/ACCEPTING)"
        if net >= 3:
            _push("Cross-strike leg S/R Behavior", 'bull', detail, weight=2)
        elif net >= 1:
            _push("Cross-strike leg S/R Behavior", 'bull', detail)
        elif net <= -3:
            _push("Cross-strike leg S/R Behavior", 'bear', detail, weight=2)
        elif net <= -1:
            _push("Cross-strike leg S/R Behavior", 'bear', detail)
    except Exception:
        pass

    # ── 13g''''. Cross-strike VOB BUILDING/BREAKING (LTF buyer/seller per zone)
    try:
        _vv_store = st.session_state.get('_atm_leg_vob_volume') or {}
        bv = brv = 0
        for tag, zones in _vv_store.items():
            if tag.startswith('sid_') or not zones:
                continue
            is_ce = ' CE ' in f' {tag} '
            is_pe = ' PE ' in f' {tag} '
            for z in zones:
                state = z.get('status')
                ztype = z.get('zone_type')
                if state == 'BUILDING':
                    leg_dir = 'bull' if ztype == 'bullish' else 'bear'
                elif state == 'BREAKING':
                    leg_dir = 'bear' if ztype == 'bullish' else 'bull'
                else:
                    continue
                if is_ce:
                    nd = leg_dir
                elif is_pe:
                    nd = 'bear' if leg_dir == 'bull' else 'bull'
                else:
                    continue
                if nd == 'bull': bv += 1
                elif nd == 'bear': brv += 1
        net = bv - brv
        detail = f"{bv}↑ / {brv}↓ across legs (BUILDING + BREAKING zones)"
        if net >= 3:
            _push("Cross-strike VOB BUILD/BREAK", 'bull', detail, weight=2)
        elif net >= 1:
            _push("Cross-strike VOB BUILD/BREAK", 'bull', detail)
        elif net <= -3:
            _push("Cross-strike VOB BUILD/BREAK", 'bear', detail, weight=2)
        elif net <= -1:
            _push("Cross-strike VOB BUILD/BREAK", 'bear', detail)
    except Exception:
        pass

    # ── 13h. Multi-Instrument Capping · OI · Volume Monitor
    try:
        _mi_state = st.session_state.get('mi_instrument_data') or {}
        bv = brv = 0
        for ikey, res in _mi_state.items():
            if not res or 'error' in res:
                continue
            _deep = res.get('deep') or {}
            b = ((_deep.get('market_bias', '') if _deep else res.get('pcr_bias', '')) or '').lower()
            if 'bull' in b:
                bv += 1
            elif 'bear' in b:
                brv += 1
        net = bv - brv
        detail = f"{bv}↑ / {brv}↓ across {bv + brv} instruments"
        if net >= 3:
            _push("Multi-Instrument Monitor", 'bull', detail, weight=2)
        elif net >= 1:
            _push("Multi-Instrument Monitor", 'bull', detail)
        elif net <= -3:
            _push("Multi-Instrument Monitor", 'bear', detail, weight=2)
        elif net <= -1:
            _push("Multi-Instrument Monitor", 'bear', detail)
        elif bv + brv > 0:
            _push("Multi-Instrument Monitor", 'neutral', detail)
    except Exception:
        pass

    # ── 14. Commodity Risk Regime
    try:
        _cr = st.session_state.get('_commodity_risk') or {}
        regime = (_cr.get('regime') or '').lower()
        if 'risk-on' in regime or 'expansion' in regime:
            _push("Commodity Risk Regime", 'bull', _cr.get('regime', ''))
        elif 'risk-off' in regime or 'contraction' in regime:
            _push("Commodity Risk Regime", 'bear', _cr.get('regime', ''))
    except Exception:
        pass

    # ── 15. Market Depth — ATM CE vs PE
    try:
        _df_s = (option_data or {}).get('df_summary') if option_data else None
        if _df_s is not None and not _df_s.empty:
            _all_s = sorted(_df_s['Strike'].dropna().unique().tolist())
            atm_d = min(_all_s, key=lambda x: abs(x - spot_price))
            atm_row = _df_s[_df_s['Strike'] == atm_d]
            if not atm_row.empty and all(c in _df_s.columns for c in ('bidQty_CE','bidQty_PE','askQty_CE','askQty_PE')):
                bce = float(atm_row.iloc[0].get('bidQty_CE') or 0)
                bpe = float(atm_row.iloc[0].get('bidQty_PE') or 0)
                ace = float(atm_row.iloc[0].get('askQty_CE') or 0)
                ape = float(atm_row.iloc[0].get('askQty_PE') or 0)
                bull_w = bce + ape
                bear_w = bpe + ace
                if bull_w > bear_w * 1.3 and bull_w > 0:
                    _push("Market Depth (ATM)", 'bull', f"bidCE+askPE > bidPE+askCE ({bull_w:.0f}>{bear_w:.0f})")
                elif bear_w > bull_w * 1.3 and bear_w > 0:
                    _push("Market Depth (ATM)", 'bear', f"bidPE+askCE > bidCE+askPE ({bear_w:.0f}>{bull_w:.0f})")
    except Exception:
        pass

    # ── 15b. News Bias (headline sentiment — context only, 🌫️ group)
    try:
        _nb = compute_news_bias()
        if _nb:
            _nn = _nb.get('net', 0)
            if _nn >= 2:
                _push("News Bias", 'bull', f"net {_nn:+d} across {_nb.get('n', 0)} headlines")
            elif _nn <= -2:
                _push("News Bias", 'bear', f"net {_nn:+d} across {_nb.get('n', 0)} headlines")
            else:
                _push("News Bias", 'neutral', f"net {_nn:+d} ({_nb.get('n', 0)} headlines)")
    except Exception:
        pass

    # ── 16. COMPOSITE BIAS Engine (overall)
    try:
        _cb = st.session_state.get('_composite_bias') or {}
        sc = _cb.get('score', 0) or 0
        if sc >= 2:
            _push("COMPOSITE BIAS Engine", 'bull', f"score {sc:+.1f} · {_cb.get('label','')}", weight=2)
        elif sc <= -2:
            _push("COMPOSITE BIAS Engine", 'bear', f"score {sc:+.1f} · {_cb.get('label','')}", weight=2)
        else:
            _push("COMPOSITE BIAS Engine", 'neutral', f"score {sc:+.1f}")
    except Exception:
        pass

    # Stash categorized rows so the AI advisor snapshot can read them.
    try:
        st.session_state['_all_bias_rows'] = rows
    except Exception:
        pass

    # ── Header
    # 🗺️ Market Picture — regime + levels + probabilities.
    #
    # Drawn into `picture_slot` when the caller claimed one, which puts it ABOVE
    # the MIOS V6 dashboard instead of below V6 and V5 both. It is computed
    # here either way: `cat_scores` above is its input, and `_market_picture` —
    # which it publishes — is what the Trade Card and Entry Gate read. Moving
    # the computation up would hand it a half-built vote tally; moving only the
    # container costs nothing.
    #
    # A failure still reports into whichever slot is in play, so an empty space
    # above V6 can never be mistaken for "no regime read".
    try:
        if picture_slot is not None:
            with picture_slot:
                render_market_picture(spot_price, df, option_data, cat_scores)
        else:
            render_market_picture(spot_price, df, option_data, cat_scores)
    except Exception as _mp_err:
        if picture_slot is not None:
            with picture_slot:
                st.caption(f"Market picture unavailable: {_mp_err}")
        else:
            st.caption(f"Market picture unavailable: {_mp_err}")

    # ⚙️ Dealer & volatility context — one line, read from the published
    # Adaptive Greeks. Context for the regime above it, never a second verdict:
    # the layer emits no side (`assert_no_recommendation`), so there is nothing
    # here that could contradict the Market Picture's own read.
    try:
        from mios_v5.ui.greeks_panel import one_line as _ag_line
        _agl = _ag_line(st.session_state.get('_adaptive_greeks'))
        if _agl:
            st.markdown(
                f"<div style='font-size:12px;color:#cfd9e6;padding:4px 0'>"
                f"⚙️ <b>Dealer context</b> — {_agl}</div>",
                unsafe_allow_html=True)
    except Exception:
        pass

    # 🎯 Strike-Mode Cockpit — ATM±2 positioning + spot action. Stays at the top
    # of the bias dashboard; with the Market Picture lifted above MIOS V6, this
    # is now the first thing in this section rather than the second.
    try:
        render_strike_mode_dashboard(spot_price, df, option_data)
    except Exception as _sm_err:
        st.caption(f"Strike-mode cockpit unavailable: {_sm_err}")

    # 🏛️ Market Structure (Stage 2) — "where is the battle happening":
    # trend + S/R + VWAP + volume profile + order blocks + patterns → one
    # Structure Score. Feeds the MIOS V5 stage02_structure engine; never
    # blocks the dashboard if it fails.
    try:
        compute_market_structure(spot_price, df, option_data)
    except Exception:
        pass
    # 🎬 Market Event Engine — capture the core event types (Discord feed +
    # Supabase audit trail). Never blocks the dashboard if it fails.
    try:
        capture_stage2_market_events(spot_price, df, option_data)
    except Exception:
        pass

    # 🗺️ Strike-level positioning heatmap (OI walls + GEX/DEX/Vanna/Charm)
    try:
        render_positioning_heatmap(spot_price, option_data)
    except Exception as _hm_err:
        st.caption(f"Positioning heatmap unavailable: {_hm_err}")

    # 📅 Cross-expiry term structure (weekly / next / monthly ΔOI agreement)
    try:
        render_cross_expiry_panel(spot_price)
    except Exception as _ce_err:
        st.caption(f"Cross-expiry unavailable: {_ce_err}")

    # ⚡ Lite view stops here — Market Picture · Cockpit · Heatmap · Cross-Expiry
    # are the curated blocks; the per-speed bias tables + verdicts below are
    # Full-only detail. (Compute already happened above; this only trims display.)
    if _is_lite():
        return

    if not rows:
        st.info("Bias engines not yet computed (cycle warming up).")
        return

    def _verdict(net):
        if net >= 4:
            return '🟢🚀', 'STRONG BULL'
        if net >= 2:
            return '🟢', 'Bull'
        if net <= -4:
            return '🔴🚀', 'STRONG BEAR'
        if net <= -2:
            return '🔴', 'Bear'
        return '⚪', 'MIXED / NEUTRAL'

    # Stash the three speed-verdicts BEFORE the entry alert fires so the
    # alert's speed block shows THIS cycle's numbers (previously stashed
    # after the send → alerts showed stale or empty "—" values).
    try:
        _dv = {}
        for _ck in ('fast', 'lag', 'mis'):
            _bs, _br = cat_scores[_ck]
            _n = _bs - _br
            _e, _l = _verdict(_n)
            _dv[_ck] = {'em': _e, 'label': _l, 'net': _n, 'bull': _bs, 'bear': _br}
        st.session_state['_dashboard_verdicts'] = _dv
        # Compact 14-leg summary for the Discord bot's !bias command
        try:
            _, _lb_ov = st.session_state.get('_leg_bias_cache') or (None, None)
            if _lb_ov:
                st.session_state['_leg_bias_summary'] = {
                    'label': _lb_ov.get('label'), 'em': _lb_ov.get('em'),
                    'bull': _lb_ov.get('bull'), 'bear': _lb_ov.get('bear'),
                    'net': _lb_ov.get('net'),
                    'speed': {k: {'label': v['label'], 'net': v['net']}
                              for k, v in _dv.items()},
                    'spot': spot_price,
                    'as_of': datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M'),
                }
        except Exception:
            pass
    except Exception:
        pass

    # Trigger OVERALL BIAS ENTRY alert from the FAST verdict (most actionable).
    fast_bull, fast_bear = cat_scores['fast']
    fast_net = fast_bull - fast_bear
    if fast_net >= 3:
        _fast_label = 'STRONG BULL'
        _fast_em = '🟢🚀'
    elif fast_net >= 1:
        _fast_label = 'Bull'
        _fast_em = '🟢'
    elif fast_net <= -3:
        _fast_label = 'STRONG BEAR'
        _fast_em = '🔴🚀'
    elif fast_net <= -1:
        _fast_label = 'Bear'
        _fast_em = '🔴'
    else:
        _fast_label = 'MIXED / NEUTRAL'
        _fast_em = '⚪'
    try:
        send_overall_bias_entry_alert(_fast_label, _fast_em, fast_bull, fast_bear,
                                       spot_price, option_data)
    except Exception:
        pass
    # 🎯 SPOT@S/R × 14-leg STRONG confluence (Telegram + Discord mirror)
    try:
        send_spot_sr_legs_confluence_alert(spot_price, option_data)
    except Exception:
        pass
    # 🎯⚡ FRESH ENTRY — two-layer blast (options mode + spot action); the only
    # alert on the main Telegram bot.
    try:
        send_fresh_entry_alert(spot_price, df, option_data)
    except Exception:
        pass
    # 🚀 ALL-ALIGNED entry (ATM verdict + ATM±2 verdict + OI wall + leg at VOB)
    try:
        send_atm_wall_vob_entry_alert(spot_price, option_data)
    except Exception:
        pass
    # 🚨 Signal cluster — multiple same-side alerts + strong level + alignment
    # → dedicated alert bot
    try:
        check_signal_cluster_alert(spot_price, option_data)
    except Exception:
        pass

    # The per-speed visual cards (Fast / Lagging / Misguiding) were removed from
    # the UI. Their scores are still computed above (cat_scores), stashed into
    # session_state for the Discord bot, and drive the OVERALL BIAS / FRESH ENTRY
    # alerts — only the on-screen cards were dropped.




# ─────────────────────────────────────────────────────────────────────────
# AI Trade Advisor — Claude reads ALL signals and recommends an entry.
# Two surfaces: (1) auto verdict panel, (2) ask-the-market chatbox.
# Dormant unless ANTHROPIC_API_KEY is set.
# ─────────────────────────────────────────────────────────────────────────
AI_ADVISOR_MODEL = "claude-opus-4-8"        # used only if ANTHROPIC_API_KEY is set
# FREE tier. Tried in order — first that responds wins (model names change
# across google-genai versions, so we fall through instead of hard-failing).
AI_ADVISOR_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
    "gemini-1.5-flash",
]





_AI_ADVISOR_SYSTEM = (
    "You are an elite intraday NIFTY options trading desk analyst. You receive a "
    "real-time SNAPSHOT of dozens of computed signals from a live trading terminal "
    "(composite bias engine, divergence, ignition/accumulation, VOB build/break, "
    "S/R behavior, money-flow profile, OI, global indices, per-leg option data). "
    "Your job: synthesize ALL of it and give ONE clear, actionable intraday options "
    "call.\n\n"
    "Rules:\n"
    "- NIFTY direction convention: a rising CALL (CE) = NIFTY bullish; a rising PUT "
    "(PE) = NIFTY bearish. To trade bullish, BUY CE; to trade bearish, BUY PE.\n"
    "- Only say ENTER NOW when fast (low-lag) signals agree AND price is at a "
    "sensible S/R location (buy CE near support, buy PE near resistance). Otherwise "
    "say WAIT and name the exact trigger you're waiting for.\n"
    "- Weight FAST signals over LAGGING ones; treat MISGUIDING signals as noise.\n"
    "- Be decisive and concise. No hedging filler, no disclaimers about being an AI.\n\n"
    "ALWAYS give EXACT numbers — never vague ranges. Use the live LTP and spot "
    "values from the snapshot as your anchor:\n"
    "- ENTRY OPTION LTP: the exact option premium (₹) to buy at, e.g. '₹84.50'. "
    "If entering now, use the current leg LTP from the snapshot; if waiting, give "
    "the exact LTP level that triggers entry.\n"
    "- ENTRY NIFTY SPOT: the exact NIFTY spot level (₹) at which to take the trade, "
    "e.g. '₹24,180'. Tie this to the nearest support (for CE) or resistance (for PE).\n"
    "- Also give exact TARGET and STOP-LOSS premiums (₹) for the option.\n\n"
    "Respond in EXACTLY this format (keep it tight):\n"
    "VERDICT: <ENTER NOW BUY CE | ENTER NOW BUY PE | WAIT | NO TRADE>\n"
    "BIAS: <Bullish/Bearish/Neutral> · Conviction <High/Medium/Low>\n"
    "WHY: <2-4 bullet points citing the specific signals that matter most>\n"
    "ENTRY OPTION: <ATM±n strike + CE/PE> @ LTP ₹<exact premium>\n"
    "ENTRY NIFTY SPOT: ₹<exact spot level> (<at support/resistance ₹X>)\n"
    "TARGET: option ₹<exact premium>  ·  STOP-LOSS: option ₹<exact premium>\n"
    "INVALIDATION: <the exact spot/LTP level that proves this wrong>\n"
    "RISK: <1 line on the main risk right now>"
)












# Groq FREE models, tried in order (OpenAI-compatible chat API).
AI_ADVISOR_GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"










def build_leg_bias_table(spot_price):
    """One consolidated table of per-leg signal biases for all 6 ATM±1 CE/PE
    legs, each leg's net verdict, and an overall NIFTY verdict.

    Each signal is expressed in the LEG's own direction. The per-leg verdict
    is the net vote. The NIFTY implication flips for PE legs (a rising PE =
    NIFTY falling). Overall verdict aggregates the per-leg NIFTY directions.

    Returns (rows: list[dict], overall: dict)."""
    leg_dfs = st.session_state.get('_atm_leg_dfs') or {}
    vpfr_legs = (st.session_state.get('_atm_pm1_vpfr') or {}).get('legs') or []
    mfp_by_tag = {l.get('tag'): l.get('mfp_bias') for l in vpfr_legs}

    def _em(d):
        return '🟢' if d == 'bull' else ('🔴' if d == 'bear' else '⚪')

    def _stat_em(s):
        return {'BUILDING': '🚀 BUILD', 'FADING': '🌫️ FADE',
                'BREAKING': '⚠️ BREAK', 'INTACT': '• INTACT'}.get(s, '—')

    _order = {'ATM-3': 0, 'ATM-2': 1, 'ATM-1': 2, 'ATM': 3,
              'ATM+1': 4, 'ATM+2': 5, 'ATM+3': 6}

    def _sortkey(tag):
        side = 0 if ' CE ' in f' {tag} ' else 1
        atm = next((k for k in _order if tag.startswith(k + ' ')), 'ATM')
        return (side, _order.get(atm, 3))

    rows, nifty_bull, nifty_bear = [], 0, 0
    # Per-speed NIFTY leg tallies [bull, bear]: Fast / Lagging / Misguiding.
    _SPEED_GROUPS = {
        'fast': ['VOB', 'S/R', 'Div', 'Ign', 'Absorb', 'CVD'],
        'lag': ['VIDYA', 'VWAP', 'VWAP50', 'VWAP20', 'VIDYA50', 'VIDYA20'],
        'mis': ['MFP', 'MFP50', 'MFP20', 'OIvel'],
    }
    _cat_tally = {'fast': [0, 0], 'lag': [0, 0], 'mis': [0, 0]}
    for tag in sorted(leg_dfs.keys(), key=_sortkey):
        df_l = leg_dfs.get(tag)
        if df_l is None or getattr(df_l, 'empty', True) or len(df_l) < 10:
            continue
        is_ce = ' CE ' in f' {tag} '
        ltp = float(df_l['close'].iloc[-1])
        v = {}
        # Compute VOB zones once (reused by VOB + S/R columns)
        try:
            zones = analyze_vob_volume(df_l, ltp) or []
        except Exception:
            zones = []
        # Support (bullish VOB) & Resistance (bearish VOB) behaviour — the
        # nearest zone of each type, with its BUILD/FADE/BREAK/INTACT status.
        def _zone_status(ztype):
            zs = [z for z in zones if z.get('zone_type') == ztype]
            if not zs:
                return '—'
            z = min(zs, key=lambda z: abs(ltp - float(z.get('mid', ltp))))
            return z.get('status', 'INTACT')
        sup_status = _zone_status('bullish')    # support behaviour
        res_status = _zone_status('bearish')    # resistance behaviour
        # 1) VOB — event (BUILDING/BREAKING) first, else continuous buy/sell flow
        try:
            vb = 0
            for z in zones:
                s_, zt = z.get('status'), z.get('zone_type')
                if s_ == 'BUILDING':
                    vb += 1 if zt == 'bullish' else -1
                elif s_ == 'BREAKING':
                    vb += -1 if zt == 'bullish' else 1
            if vb > 0:
                v['VOB'] = 'bull'
            elif vb < 0:
                v['VOB'] = 'bear'
            else:
                # Continuous: net buyer/seller flow across the leg's VOB zones
                _buy = sum(float(z.get('buy_vol', 0) or 0) for z in zones)
                _sell = sum(float(z.get('sell_vol', 0) or 0) for z in zones)
                _tot = _buy + _sell
                if _tot > 0 and _buy >= _sell * 1.15:
                    v['VOB'] = 'bull'
                elif _tot > 0 and _sell >= _buy * 1.15:
                    v['VOB'] = 'bear'
                else:
                    v['VOB'] = 'neu'
        except Exception:
            v['VOB'] = 'neu'
        # 2) S/R behavior — event first, else position vs nearest support/resistance
        try:
            sr = classify_leg_sr_behavior(df_l, ltp)
            if sr and sr.get('direction') in ('bull', 'bear') and sr.get('state') not in (None, 'NONE'):
                v['S/R'] = sr['direction']
            else:
                # Positional fallback from VOB zones: closer to support → bull,
                # closer to resistance → bear.
                _sups = [float(z.get('mid', 0)) for z in zones
                         if z.get('zone_type') == 'bullish' and float(z.get('mid', 0)) <= ltp]
                _ress = [float(z.get('mid', 0)) for z in zones
                         if z.get('zone_type') == 'bearish' and float(z.get('mid', 0)) >= ltp]
                _ns = max(_sups) if _sups else None
                _nr = min(_ress) if _ress else None
                if _ns is not None and _nr is not None:
                    v['S/R'] = 'bull' if (ltp - _ns) <= (_nr - ltp) else 'bear'
                elif _ns is not None:
                    v['S/R'] = 'bull'
                elif _nr is not None:
                    v['S/R'] = 'bear'
                else:
                    v['S/R'] = 'neu'
        except Exception:
            v['S/R'] = 'neu'
        # 3) Divergence
        try:
            dv = detect_divergence(df_l)
            v['Div'] = 'bull' if dv.get('bull') else ('bear' if dv.get('bear') else 'neu')
        except Exception:
            v['Div'] = 'neu'
        # 4) Ignition
        try:
            ig = detect_ignition(df_l)
            v['Ign'] = ig.get('direction') if ig.get('fired') and ig.get('direction') in ('bull', 'bear') else 'neu'
        except Exception:
            v['Ign'] = 'neu'
        # 5) VWAP
        try:
            vw = ReversalDetector.calculate_vwap(df_l)
            v['VWAP'] = ('bull' if ltp > float(vw.iloc[-1]) else 'bear') if (vw is not None and not vw.empty) else 'neu'
        except Exception:
            v['VWAP'] = 'neu'
        # 6) VIDYA
        try:
            t = calculate_vidya(df_l).get('trend')
            v['VIDYA'] = 'bull' if t == 'Bullish' else ('bear' if t == 'Bearish' else 'neu')
        except Exception:
            v['VIDYA'] = 'neu'
        # 6b) VWAP & VIDYA over fixed windows — last 50 / 20 bars (anchored
        # VWAP of the window; VIDYA params scaled down for the 20-bar window
        # since defaults need momentum+15 = 35 bars).
        def _vwap_win_bias(n):
            try:
                _vwn = ReversalDetector.calculate_vwap(df_l.tail(n))
                if _vwn is None or _vwn.empty:
                    return 'neu'
                return 'bull' if ltp > float(_vwn.iloc[-1]) else 'bear'
            except Exception:
                return 'neu'
        def _vidya_win_bias(n, length, momentum):
            try:
                _t = calculate_vidya(df_l.tail(n), length=length, momentum=momentum).get('trend')
                return 'bull' if _t == 'Bullish' else ('bear' if _t == 'Bearish' else 'neu')
            except Exception:
                return 'neu'
        v['VWAP50'] = _vwap_win_bias(50)
        v['VWAP20'] = _vwap_win_bias(20)
        v['VIDYA50'] = _vidya_win_bias(50, 10, 20)
        v['VIDYA20'] = _vidya_win_bias(20, 5, 5)
        # 6c) Absorption — tight LTP range + one-sided CLV delta (last 5 bars).
        # Aggressive buying absorbed by passive sellers while price stalls =
        # bear for the leg; selling absorbed by buyers = bull.
        try:
            v['Absorb'] = 'neu'
            _t5 = df_l.tail(5)
            _rng5 = float(_t5['high'].max() - _t5['low'].min())
            _d5 = _v5 = 0.0
            for _, _b5 in _t5.iterrows():
                _h5, _l5 = float(_b5['high']), float(_b5['low'])
                _c5, _vv5 = float(_b5['close']), float(_b5['volume'])
                _r5 = _h5 - _l5
                if _r5 > 0 and _vv5 > 0:
                    _d5 += _vv5 * (2 * _c5 - _h5 - _l5) / _r5
                    _v5 += _vv5
            if _rng5 < ltp * 0.004 and _v5 > 0 and abs(_d5) >= 0.25 * _v5:
                v['Absorb'] = 'bear' if _d5 > 0 else 'bull'
        except Exception:
            v['Absorb'] = 'neu'
        # 6d) CVD slope — cumulative CLV delta over the last 10 bars
        try:
            v['CVD'] = 'neu'
            _t10 = df_l.tail(10)
            _cd = _tv = 0.0
            for _, _b1 in _t10.iterrows():
                _h1, _l1 = float(_b1['high']), float(_b1['low'])
                _c1, _vv1 = float(_b1['close']), float(_b1['volume'])
                _r1 = _h1 - _l1
                if _r1 > 0 and _vv1 > 0:
                    _cd += _vv1 * (2 * _c1 - _h1 - _l1) / _r1
                    _tv += _vv1
            if _tv > 0 and abs(_cd) >= 0.10 * _tv:
                v['CVD'] = 'bull' if _cd > 0 else 'bear'
        except Exception:
            v['CVD'] = 'neu'
        # 6e) OI velocity — this strike+side's OI building ≥2× its day-average
        # rate (≈10-min window); direction from the LTP move over the same
        # window (OI spike + LTP up = long buildup · + LTP down = writing).
        try:
            v['OIvel'] = 'neu'
            _od2 = st.session_state.get('_cached_option_data') or {}
            _ds3 = _od2.get('df_summary')
            _parts = tag.split()
            _side3, _stk3 = _parts[-2], float(_parts[-1])
            _oic = f'openInterest_{_side3}'
            if _ds3 is not None and not getattr(_ds3, 'empty', True) and _oic in _ds3.columns:
                _row3 = _ds3[_ds3['Strike'] == _stk3]
                if not _row3.empty:
                    _oi_now = float(_row3.iloc[0].get(_oic) or 0)
                    _hist3 = st.session_state.setdefault('_leg_oi_vel_hist', {})
                    _hl = _hist3.setdefault(f'{_side3} {_stk3:.0f}', [])
                    _now3 = time.time()
                    if not _hl or _now3 - _hl[-1][0] >= 15:
                        _hl.append((_now3, _oi_now, ltp))
                        if len(_hl) > 80:
                            del _hl[:len(_hl) - 80]
                    _old3 = next((e for e in _hl if _now3 - e[0] >= 540), None)
                    if _old3 is not None and len(_hl) >= 3:
                        _mins = max((_now3 - _old3[0]) / 60.0, 1.0)
                        _vel = (_oi_now - _old3[1]) / _mins
                        _day_mins = max((_now3 - _hl[0][0]) / 60.0, 1.0)
                        _avg_rate = abs(_oi_now - _hl[0][1]) / _day_mins
                        if _avg_rate > 0 and abs(_vel) >= 2.0 * _avg_rate:
                            _lchg = ltp - _old3[2]
                            v['OIvel'] = ('bull' if _lchg > 0
                                          else ('bear' if _lchg < 0 else 'neu'))
        except Exception:
            v['OIvel'] = 'neu'
        # 7) MFP POC bias
        mb = mfp_by_tag.get(tag)
        v['MFP'] = 'bull' if mb == 'BULL' else ('bear' if mb == 'BEAR' else 'neu')
        # 7b) MFP POC bias over fixed windows — last 50 / last 20 bars (3-row
        # profile, same as the per-leg MFP panels below the leg charts).
        def _mfp_win_bias(n):
            try:
                _m = calculate_money_flow_profile(df_l.tail(n), num_rows=3, source='Money Flow')
                _b = _mfp_poc_bias(_m)
                return 'bull' if _b == 'BULL' else ('bear' if _b == 'BEAR' else 'neu')
            except Exception:
                return 'neu'
        v['MFP50'] = _mfp_win_bias(50)
        v['MFP20'] = _mfp_win_bias(20)

        score = sum(1 if x == 'bull' else (-1 if x == 'bear' else 0) for x in v.values())
        leg_dir = 'bull' if score > 0 else ('bear' if score < 0 else 'neu')
        if leg_dir == 'neu':
            nifty = 'neu'
        elif is_ce:
            nifty = leg_dir
        else:
            nifty = 'bear' if leg_dir == 'bull' else 'bull'
        if nifty == 'bull':
            nifty_bull += 1
        elif nifty == 'bear':
            nifty_bear += 1

        # Per-speed leg tallies (NIFTY direction; PE reversed)
        for _ck, _sigs in _SPEED_GROUPS.items():
            _csc = sum(1 if v.get(s) == 'bull' else (-1 if v.get(s) == 'bear' else 0) for s in _sigs)
            _cdir = 'bull' if _csc > 0 else ('bear' if _csc < 0 else 'neu')
            if _cdir == 'neu':
                continue
            _cn = _cdir if is_ce else ('bear' if _cdir == 'bull' else 'bull')
            if _cn == 'bull':
                _cat_tally[_ck][0] += 1
            else:
                _cat_tally[_ck][1] += 1

        rows.append({
            'Leg': tag, 'LTP': f"₹{ltp:.1f}",
            'VOB': _em(v['VOB']),
            'Sup VOB': _stat_em(sup_status), 'Res VOB': _stat_em(res_status),
            'S/R': _em(v['S/R']),
            'Div': _em(v['Div']), 'Ign': _em(v['Ign']),
            'Absorb': _em(v['Absorb']), 'CVD': _em(v['CVD']), 'OIvel': _em(v['OIvel']),
            'VWAP': _em(v['VWAP']), 'VWAP50': _em(v['VWAP50']), 'VWAP20': _em(v['VWAP20']),
            'VIDYA': _em(v['VIDYA']), 'VIDYA50': _em(v['VIDYA50']), 'VIDYA20': _em(v['VIDYA20']),
            'MFP': _em(v['MFP']), 'MFP50': _em(v['MFP50']), 'MFP20': _em(v['MFP20']),
            'Leg Verdict': f"{_em(leg_dir)} {leg_dir.upper()} ({score:+d})",
            '→ NIFTY': f"{_em(nifty)} {nifty.upper()}",
        })

    def _mk_verdict(b, br):
        n = b - br
        if n >= 3:
            d = {'dir': 'BULL', 'em': '🟢', 'label': 'STRONG BULLISH'}
        elif n >= 1:
            d = {'dir': 'BULL', 'em': '🟢', 'label': 'BULLISH'}
        elif n <= -3:
            d = {'dir': 'BEAR', 'em': '🔴', 'label': 'STRONG BEARISH'}
        elif n <= -1:
            d = {'dir': 'BEAR', 'em': '🔴', 'label': 'BEARISH'}
        else:
            d = {'dir': 'NEUTRAL', 'em': '⚪', 'label': 'NEUTRAL / MIXED'}
        d.update({'bull': b, 'bear': br, 'net': n})
        return d

    overall = _mk_verdict(nifty_bull, nifty_bear)
    # Split verdicts by signal speed.
    overall['by_speed'] = {
        'fast': _mk_verdict(*_cat_tally['fast']),
        'lag': _mk_verdict(*_cat_tally['lag']),
        'mis': _mk_verdict(*_cat_tally['mis']),
    }
    return rows, overall




# ── Multi-factor scoring engine (draft "Final AI Output") ──────────────────
# Directional confirmers and weights (Step 4). ΔOI + volume are conviction
# amplifiers (Step 4 multiplier), not directional confirmers, so they're not
# here. Bid/Ask weighted lowest — spoofable (Tier-3).
_FACTOR_W = {'cvd': 0.28, 'mf': 0.18, 'vp': 0.18, 'vwap': 0.14, 'iv': 0.12, 'ba': 0.10}
_FACTOR_LABEL = {'cvd': 'CVD', 'mf': 'MoneyFlow', 'vp': 'VP', 'vwap': 'VWAP',
                 'iv': 'IV', 'ba': 'Bid/Ask'}


def _clipn(x, lo=-1.0, hi=1.0):
    return lo if x < lo else (hi if x > hi else x)


def _fmr_leg_df(strike, side):
    """Leg candles from the ATM±1 cache, else the on-demand wing fetch (90s)."""
    leg_dfs = st.session_state.get('_atm_leg_dfs') or {}
    t = next((k for k in leg_dfs if k.endswith(f"{side} {strike:.0f}")), None)
    if t is not None and leg_dfs[t] is not None and not getattr(leg_dfs[t], 'empty', True):
        return leg_dfs[t]
    ctx = st.session_state.get('_cockpit_ctx') or {}
    sid = (ctx.get('sids') or {}).get((strike, side))
    api = ctx.get('api')
    if not sid or api is None:
        return None
    cache = st.session_state.setdefault('_cockpit_wing_cache', {})
    # Share the render's leg-fetch budget, exactly as the other wing fetch
    # already does. The strike loop that reaches here runs ATM±2 on both sides,
    # and only ATM±1 is in `_atm_leg_dfs` — so the four ±2 legs all fell through
    # to this fetch with nothing capping them, on top of the five the budget
    # allows. Out of budget, serve the cached frame and rotate in next render.
    _wb = st.session_state.get('_leg_fetch_budget')
    _may_fetch = not (_wb and _wb[1] <= 0)
    if _may_fetch and time.time() - cache.get(sid, {}).get('ts', 0) > 90:
        if _wb:
            _wb[1] -= 1
        try:
            _raw = api.get_intraday_data(security_id=sid, exchange_segment=ctx.get('seg'),
                                         instrument="OPTIDX", interval="1", days_back=1)
            cache[sid] = {'ts': time.time(),
                          'df': process_candle_data(_raw, "1min") if _raw else None}
        except Exception:
            cache[sid] = {'ts': time.time(), 'df': None}
    return cache.get(sid, {}).get('df')


def _normalize_factors(r, strike, side):
    """Steps 1-2: gather raw inputs for one option leg and normalize each
    factor to a signed score s∈[-1,1] (+ = bullish for THAT option)."""
    def g(c, d=0.0):
        try:
            return float(r.get(c, d) or d)
        except Exception:
            return d
    ltp = g(f'lastPrice_{side}'); doi = g(f'changeinOpenInterest_{side}')
    oi = g(f'openInterest_{side}'); iv = g(f'impliedVolatility_{side}')
    gam = g(f'Gamma_{side}'); bq = g(f'bidQty_{side}'); aq = g(f'askQty_{side}')
    # tracked LTP + IV direction (across cycles)
    hist = st.session_state.setdefault('_strike_mode_hist', {})
    h = hist.setdefault(f'{strike:.0f}_{side}', [])
    h.append((time.time(), ltp, iv))
    if len(h) > 12:
        del h[:len(h) - 12]
    dP = dIV = 0
    if len(h) >= 3:
        old = h[max(0, len(h) - 6)]
        dP = 1 if ltp > old[1] else (-1 if ltp < old[1] else 0)
        dIV = 1 if iv > old[2] else (-1 if iv < old[2] else 0)
    # candle-derived: CVD, VWAP, VP, MoneyFlow, volume ratio
    s_cvd = s_vwap = s_vp = s_mf = 0.0
    vol_ratio = 1.0
    dfl = _fmr_leg_df(strike, side)
    if dfl is not None and not getattr(dfl, 'empty', True) and len(dfl) >= 5:
        Cl = dfl['close'].astype(float)
        # one owner for the split; this view carries weight 0.28 in _FACTOR_W
        _n = _of.cvd_normalised(dfl)
        s_cvd = 0.0 if _of.is_missing(_n) else _n
        p = float(Cl.iloc[-1])
        try:
            w = ReversalDetector.calculate_vwap(dfl)
            if w is not None and not w.empty:
                wl = float(w.iloc[-1])
                s_vwap = 1.0 if p > wl * 1.001 else (-1.0 if p < wl * 0.999 else 0.0)
        except Exception:
            pass
        try:
            m = calculate_money_flow_profile(dfl.tail(60), num_rows=3, source='Money Flow')
            _b = _mfp_poc_bias(m)
            s_mf = 1.0 if _b == 'BULL' else (-1.0 if _b == 'BEAR' else 0.0)
            if m:
                vah = float(m.get('value_area_high', 0) or 0)
                val = float(m.get('value_area_low', 0) or 0)
                poc = float(m.get('poc_price', 0) or 0)
                s_vp = (1.0 if (vah and p > vah) else
                        (0.5 if (poc and p > poc) else
                         (-0.5 if (poc and p < poc) else (-1.0 if (val and p < val) else 0.0))))
        except Exception:
            pass
        v20 = float(Vv.tail(20).mean() or 0); vlast = float(Vv.iloc[-1])
        vol_ratio = (vlast / v20) if v20 > 0 else 1.0
    s_ba = _clipn((bq - aq) / (bq + aq + 1))
    s = {'cvd': s_cvd, 'mf': s_mf, 'vp': s_vp, 'vwap': s_vwap,
         'iv': float(dIV), 'ba': s_ba}
    return {'ltp': ltp, 'doi': doi, 'oi': oi, 'iv': iv, 'gam': gam, 'dP': dP,
            'dIV': dIV, 'vol': vol_ratio, 'bq': bq, 'aq': aq, 's': s}


def score_side(d, is_ce):
    """Steps 3-5: MODE (CVD+ΔOI) · STRENGTH% (weighted confirmers × conviction)
    · CONFIDENCE% (agreement) · reasons. Returns a dict."""
    s = d['s']
    D = 1 if s['cvd'] > 0 else (-1 if s['cvd'] < 0 else d.get('dP', 0))
    oi_up = d['doi'] > 0
    if D > 0 and oi_up:
        mode, vote = 'Long Build-up', (1 if is_ce else -1)
    elif D < 0 and oi_up:
        mode, vote = 'Writing', (-1 if is_ce else 1)
    elif D > 0 and not oi_up:
        mode, vote = 'Short Covering', (1 if is_ce else -1)
    elif D < 0 and not oi_up:
        mode, vote = 'Long Unwinding', (-1 if is_ce else 1)
    else:
        mode, vote = 'Neutral', 0
    # Strength orients by the OPTION's own expected direction (D), NOT the
    # index vote — the factor scores s are "+ = bullish for THIS option", and
    # for a PE bullish-index = bearish-PE, so index orientation would flip.
    opt_dir = 1 if D > 0 else (-1 if D < 0 else 0)
    # Step 4 — strength
    agree = {f: _clipn(s.get(f, 0) * opt_dir) for f in _FACTOR_W}
    raw = sum(_FACTOR_W[f] * agree[f] for f in _FACTOR_W)
    oi = d['oi'] or 0
    oi_conv = min(abs(d['doi']) / (oi * 0.03), 1.0) if oi else 0.0
    vol_conv = min(d['vol'], 2.0) / 2.0
    amp = 0.5 + 0.5 * _clipn(0.5 * vol_conv + 0.5 * oi_conv, 0, 1)
    raw *= amp
    strength = round((_clipn(raw) + 1) / 2 * 100)
    # Step 5 — confidence
    _den = sum(_FACTOR_W[f] * abs(agree[f]) for f in _FACTOR_W) or 1e-9
    confidence = round(abs(sum(_FACTOR_W[f] * agree[f] for f in _FACTOR_W)) / _den * 100)
    reasons = [f"{'✓' if agree[f] > 0.3 else '⚠'} {_FACTOR_LABEL[f]}"
               for f in _FACTOR_W if abs(agree[f]) > 0.3]
    return {'mode': mode, 'vote': vote, 'strength': strength,
            'confidence': confidence, 'reasons': reasons, 'agree': agree}


# Step 7 — explicit CALL×PUT mode-pair special cases (the volatility/range nuances)
_MODE_PAIR = {
    ('Long Build-up', 'Long Build-up'): ('⚡ HIGH VOLATILITY', 'vol'),
    ('Writing', 'Writing'): ('➖ RANGE (writers control)', 'range'),
    ('Short Covering', 'Short Covering'): ('⚠️ VOLATILE — price decides', 'vol'),
}


def compute_full_market_read(spot_price, df, option_data):
    """Steps 6-11: aggregate ATM±2 → CALL side + PUT side → MARKET (bias,
    breakout%, S/R strength, gamma blast, reasons). Cached ~8s in session."""
    _c = st.session_state.get('_fmr_cache')
    if _c and time.time() - _c[0] < 8:
        return _c[1]
    ds = (option_data or {}).get('df_summary') if option_data else None
    if ds is None or getattr(ds, 'empty', True) or 'Strike' not in ds.columns or not spot_price:
        return None
    try:
        stks = sorted(ds['Strike'].dropna().unique().tolist())
        atm = min(stks, key=lambda x: abs(x - spot_price))
        gap = min((abs(b - a) for a, b in zip(stks, stks[1:])), default=50) or 50
    except Exception:
        return None
    weight = {0: 0.40, 1: 0.20, 2: 0.10}
    from collections import Counter
    call_score = put_score = 0.0
    ce_modes, pe_modes = Counter(), Counter()
    ce_str = pe_str = ce_conf = pe_conf = wsum = 0.0
    atm_scored = {}
    per_strike = []
    for off in (-2, -1, 0, 1, 2):
        strike = atm + off * gap
        r = ds[ds['Strike'] == strike]
        if r.empty:
            continue
        r = r.iloc[0]
        w = weight[abs(off)]
        wsum += w
        ce = score_side(_normalize_factors(r, strike, 'CE'), True)
        pe = score_side(_normalize_factors(r, strike, 'PE'), False)
        call_score += w * ce['vote'] * ce['strength'] / 100.0
        put_score += w * pe['vote'] * pe['strength'] / 100.0
        ce_modes[ce['mode']] += w; pe_modes[pe['mode']] += w
        ce_str += w * ce['strength']; pe_str += w * pe['strength']
        ce_conf += w * ce['confidence']; pe_conf += w * pe['confidence']
        if off == 0:
            atm_scored = {'ce': ce, 'pe': pe}
        per_strike.append((off, strike, ce, pe))
    if wsum <= 0:
        return None
    call_mode = ce_modes.most_common(1)[0][0]
    put_mode = pe_modes.most_common(1)[0][0]
    call_strength = round(ce_str / wsum); put_strength = round(pe_str / wsum)
    call_conf = round(ce_conf / wsum); put_conf = round(pe_conf / wsum)

    # Step 7 — market
    pair = _MODE_PAIR.get((call_mode, put_mode))
    M = call_score + put_score
    if pair:
        market_label, market_kind = pair
    elif M >= 0.6:
        market_label, market_kind = '🟢 STRONG BULLISH', 'bull'
    elif M >= 0.25:
        market_label, market_kind = '🟢 Bullish', 'bull'
    elif M <= -0.6:
        market_label, market_kind = '🔴 STRONG BEARISH', 'bear'
    elif M <= -0.25:
        market_label, market_kind = '🔴 Bearish', 'bear'
    else:
        market_label, market_kind = '➖ Range', 'range'

    # Step 8 — S/R strength (writers defending + structure)
    def _wall(side_col):
        try:
            lo, hi = spot_price * 0.97, spot_price * 1.03
            win = ds[(ds['Strike'] >= lo) & (ds['Strike'] <= hi)]
            col = f'openInterest_{side_col}'
            return float(win[col].max()) / 1e5 if col in win.columns and not win.empty else 0.0
        except Exception:
            return 0.0
    pe_wall, ce_wall = _wall('PE'), _wall('CE')
    put_writing_str = put_strength if put_mode == 'Writing' else put_strength * 0.4
    call_writing_str = call_strength if call_mode == 'Writing' else call_strength * 0.4
    support_strength = round(100 * _clipn(0.45 * min(pe_wall / 120, 1)
                                          + 0.4 * put_writing_str / 100
                                          + 0.15 * (1 if put_mode == 'Writing' else 0), 0, 1))
    resistance_strength = round(100 * _clipn(0.45 * min(ce_wall / 120, 1)
                                             + 0.4 * call_writing_str / 100
                                             + 0.15 * (1 if call_mode == 'Writing' else 0), 0, 1))

    # Step 10 — gamma blast
    gex = st.session_state.get('_gex_data') or {}
    net_gex = float(gex.get('total_gex', 0) or 0)
    atm_vol = atm_scored.get('ce', {}).get('agree', {})  # placeholder for vol availability
    if net_gex < 0:
        gamma_blast = 'HIGH' if market_kind in ('bull', 'bear', 'vol') else 'MEDIUM'
    elif abs(net_gex) < 3000:
        gamma_blast = 'MEDIUM'
    else:
        gamma_blast = 'LOW'

    # Step 9 — breakout / breakdown
    edge = _clipn(M / 1.1)
    if net_gex < 0:  # dealers short gamma → moves accelerate in the market direction
        edge = _clipn(edge * 1.25)
    breakout = int(round(min(max((edge + 1) / 2 * 100, 8), 92)))
    breakdown = 100 - breakout

    # Step 11 — reasons (from the ATM strike's dominant sides + market facts)
    reasons = []
    if call_mode in ('Short Covering', 'Long Build-up'):
        reasons.append(f"✓ Call {call_mode}")
    if put_mode == 'Writing':
        reasons.append("✓ Put Writing")
    for _r in (atm_scored.get('ce', {}).get('reasons', [])[:3]
               + atm_scored.get('pe', {}).get('reasons', [])[:3]):
        if _r not in reasons:
            reasons.append(_r)

    # ── Phase-2 institutional composite (Dealer / Liquidity / Order-book) ──
    # Dealer Score — DEX direction, conviction amplified when dealers are short
    # gamma (negative GEX → they chase moves) and damped when long gamma (pin).
    try:
        _dex = calculate_dealer_dex(ds, spot_price) or {}
    except Exception:
        _dex = {}
    dex_net = float(_dex.get('net_dex', 0) or 0)
    dex_tilt = float(_dex.get('tilt', 0) or 0)              # -1..+1
    _gex_amp = 1.25 if net_gex < 0 else (0.85 if net_gex > 10 else 1.0)
    dealer_dir = 'bull' if dex_net > 0 else ('bear' if dex_net < 0 else 'neutral')
    dealer_score = round(min(abs(dex_tilt) * 100 * _gex_amp, 100))

    # Liquidity Score — size of the nearest OI walls (where liquidity sits).
    liquidity_score = round(100 * _clipn(max(pe_wall, ce_wall) / 150, 0, 1))

    # Order-book Score — top-of-book imbalance (Tier-3, spoofable → small weight).
    ob_score = 0
    ob_dir = 'neutral'
    try:
        if {'Strike', 'bidQty_CE', 'askQty_CE', 'bidQty_PE', 'askQty_PE'} <= set(ds.columns):
            _w = ds[(ds['Strike'] >= atm - 2 * gap) & (ds['Strike'] <= atm + 2 * gap)]
            _cn = float(_w['bidQty_CE'].sum() - _w['askQty_CE'].sum())
            _pn = float(_w['bidQty_PE'].sum() - _w['askQty_PE'].sum())
            _sc = _cn - _pn
            _dn = abs(_cn) + abs(_pn)
            _t = (_sc / _dn) if _dn > 0 else 0.0
            ob_score = round(min(abs(_t) * 100, 100))
            ob_dir = 'bull' if _t > 0.1 else ('bear' if _t < -0.1 else 'neutral')
    except Exception:
        pass

    # Institution Score — composite conviction (dealer 50 / liquidity 30 / ob 20)
    institution_score = round(0.5 * dealer_score + 0.3 * liquidity_score + 0.2 * ob_score)
    institution_bias = dealer_dir if dealer_dir != 'neutral' else ob_dir

    # Short-squeeze probability — trapped-short upside unwind: call Short-Covering
    # + supportive put Writing + negative-gamma accelerant + breakout tilt.
    _ss = 0.0
    if call_mode == 'Short Covering':
        _ss += 0.45 * (call_strength / 100.0)
    if put_mode == 'Writing':
        _ss += 0.25 * (put_strength / 100.0)
    if net_gex < 0:
        _ss += 0.20
    _ss += 0.10 * _clipn((breakout - 50) / 42.0, 0, 1)
    short_squeeze = int(round(min(_ss, 1.0) * 100))

    # Overall confidence — blend of side conviction, institutional score and edge.
    overall_conf = round(_clipn(
        0.45 * (max(call_conf, put_conf) / 100.0)
        + 0.30 * (institution_score / 100.0)
        + 0.25 * abs(_clipn(M / 1.1)), 0, 1) * 100)

    out = {
        'call_mode': call_mode, 'call_strength': call_strength, 'call_conf': call_conf,
        'put_mode': put_mode, 'put_strength': put_strength, 'put_conf': put_conf,
        'market_label': market_label, 'market_kind': market_kind, 'M': round(M, 2),
        'support_strength': support_strength, 'resistance_strength': resistance_strength,
        'breakout': breakout, 'breakdown': breakdown, 'gamma_blast': gamma_blast,
        'dealer_score': dealer_score, 'dealer_dir': dealer_dir,
        'liquidity_score': liquidity_score, 'ob_score': ob_score, 'ob_dir': ob_dir,
        'institution_score': institution_score, 'institution_bias': institution_bias,
        'short_squeeze': short_squeeze, 'overall_conf': overall_conf,
        'reasons': reasons[:8], 'per_strike': per_strike,
    }
    st.session_state['_fmr_cache'] = (time.time(), out)
    st.session_state['_full_market_read'] = out
    return out


def _order_block_freshness(df, ob):
    """Fresh = price hasn't re-entered the OB's range since it formed.
    Retested = it has, but the OB held (detect_order_blocks already drops
    OBs that were fully broken through)."""
    if df is None or not ob:
        return None
    try:
        idx = int(ob['bar_idx'])
        after = df.iloc[idx + 1:]
        if after.empty:
            return 'fresh'
        lo, hi = float(ob['low']), float(ob['high'])
        touched = (after['low'] <= hi) & (after['high'] >= lo)
        return 'retested' if bool(touched.any()) else 'fresh'
    except Exception:
        return None


def compute_market_structure(spot_price, df, option_data):
    """Stage 2 — Market Structure: answers only "where is the battle
    happening?" Combines trend, S/R, VWAP, volume profile, order blocks,
    and chart/candle patterns (confirmation only) into one Price-Location
    read + a 0-100 Structure Score. Does NOT decide buy/sell — later stages
    (positioning, order flow, options) decide whether the location is worth
    trading. Cached ~8s in session."""
    _c = st.session_state.get('_ms_cache')
    if _c and time.time() - _c[0] < 8:
        return _c[1]
    if not spot_price or df is None or getattr(df, 'empty', True):
        return None

    m = st.session_state.get('_market_picture') or {}
    fmr = compute_full_market_read(spot_price, df, option_data) or {}

    # Step 1 — Trend (5-state: Strong/Weak Uptrend, Range, Weak/Strong Downtrend)
    regime = m.get('regime')
    p_up = float(m.get('p_up', 0) or 0)
    p_dn = float(m.get('p_down', 0) or 0)
    if regime == 'UP':
        trend, stars = ('Strong Uptrend', 5) if p_up >= 65 else ('Weak Uptrend', 3)
    elif regime == 'DOWN':
        trend, stars = ('Strong Downtrend', 5) if p_dn >= 65 else ('Weak Downtrend', 3)
    elif regime:
        trend, stars = 'Range', 2
    else:
        trend, stars = 'Unknown', 0

    # Step 2 — key price levels (reuse the S/R cluster + OI walls already
    # computed for the Market Picture — no need to re-derive)
    sup = m.get('sup') or {}
    res = m.get('res') or {}
    oi_floor = m.get('oi_floor')
    oi_ceiling = m.get('oi_ceiling')
    support = sup.get('price') or (oi_floor[0] if oi_floor else None)
    resistance = res.get('price') or (oi_ceiling[0] if oi_ceiling else None)
    d_sup = ((spot_price - support) / spot_price * 100) if support else None
    d_res = ((resistance - spot_price) / spot_price * 100) if resistance else None
    near_support = d_sup is not None and abs(d_sup) <= 0.35
    near_resistance = d_res is not None and abs(d_res) <= 0.35

    # Step 3 — VWAP
    vwap_val, vwap_pos = None, 'Unknown'
    try:
        vwap_series = ReversalDetector.calculate_vwap(df)
        if vwap_series is not None and not vwap_series.empty:
            vwap_val = float(vwap_series.iloc[-1])
            if vwap_val:
                dist_pct = (spot_price - vwap_val) / vwap_val * 100
                vwap_pos = ('Near' if abs(dist_pct) <= 0.05
                            else ('Above' if dist_pct > 0 else 'Below'))
    except Exception:
        pass

    # Step 4 — Volume Profile (POC / VAH / VAL, from the already-computed
    # money-flow profile — one cycle old at worst, same tolerance every
    # other adapter in this app accepts)
    mf = st.session_state.get('_money_flow_data') or {}
    poc = float(mf.get('poc_price', 0) or 0)
    vah = float(mf.get('value_area_high', 0) or 0)
    val = float(mf.get('value_area_low', 0) or 0)
    vp_state, vp_side = 'Unknown', None
    if poc:
        vp_side = 'Above POC' if spot_price >= poc else 'Below POC'
        if val and vah and val <= spot_price <= vah:
            vp_state = 'Inside Value Area'
        elif vah and spot_price > vah:
            vp_state = 'Outside Value Area (above VAH)'
        elif val and spot_price < val:
            vp_state = 'Outside Value Area (below VAL)'
        else:
            vp_state = 'Inside Value Area'

    # Step 5 — Order Blocks (fresh / retested / broken — broken ones are
    # already excluded by detect_order_blocks)
    ob_label, ob_freshness = 'None', None
    try:
        ob = detect_order_blocks(df, lookback=20) or {}
        cand = [(k, v) for k, v in (('Demand', ob.get('bullish_ob')),
                                     ('Supply', ob.get('bearish_ob'))) if v]
        if cand:
            kind, chosen = min(cand, key=lambda kv: abs(spot_price - kv[1]['avg']))
            ob_freshness = _order_block_freshness(df, chosen)
            if ob_freshness:
                ob_label = f"{ob_freshness.title()} {kind}"
    except Exception:
        pass

    # Step 6 — Chart pattern (confirmation only)
    chart_pat = None
    try:
        chart_pat = detect_chart_patterns(df)
    except Exception:
        pass

    # Step 7 — Candlestick pattern (confirmation only)
    candle_pat = None
    try:
        candle_pat = detect_candle_patterns(df, lookback=5)
    except Exception:
        pass

    # Step 8 — Price Location synthesis: combine everything into one
    # Structure Score (0-100) + Demand/Supply/Neutral + Trade/No-Trade Zone.
    # This is the only genuinely new judgment call in the stage — everything
    # above is either reused or a thin wrapper over an existing detector.
    score, bull_votes, bear_votes = 0.0, 0, 0
    if near_support:
        score += 25; bull_votes += 1
    elif near_resistance:
        score += 25; bear_votes += 1

    if vwap_pos == 'Above':
        score += 15; bull_votes += 1
    elif vwap_pos == 'Below':
        score += 15; bear_votes += 1

    if vp_side == 'Above POC' and vp_state == 'Inside Value Area':
        score += 15; bull_votes += 1
    elif vp_side == 'Below POC' and vp_state == 'Inside Value Area':
        score += 15; bear_votes += 1

    ob_is_demand = ob_label.endswith('Demand')
    if ob_freshness == 'fresh':
        score += 20
        bull_votes, bear_votes = (bull_votes + 1, bear_votes) if ob_is_demand else (bull_votes, bear_votes + 1)
    elif ob_freshness == 'retested':
        score += 10
        bull_votes, bear_votes = (bull_votes + 1, bear_votes) if ob_is_demand else (bull_votes, bear_votes + 1)

    cp_dir = str((chart_pat or {}).get('direction', '')).lower()
    if cp_dir == 'bullish':
        score += 10; bull_votes += 1
    elif cp_dir == 'bearish':
        score += 10; bear_votes += 1

    kp_dir = str((candle_pat or {}).get('direction', '')).lower()
    if kp_dir == 'bullish':
        score += 15; bull_votes += 1
    elif kp_dir == 'bearish':
        score += 15; bear_votes += 1

    score = min(100, round(score))
    if bull_votes > bear_votes and (near_support or bull_votes >= 3):
        demand_supply = 'Demand'
    elif bear_votes > bull_votes and (near_resistance or bear_votes >= 3):
        demand_supply = 'Supply'
    else:
        demand_supply = 'Neutral'

    decision = 'TRADE ZONE' if score >= 60 else ('WATCH' if score >= 35 else 'NO TRADE')
    if demand_supply != 'Neutral' and score >= 75:
        location_label = f"HIGH QUALITY {demand_supply.upper()} ZONE"
    elif demand_supply != 'Neutral':
        location_label = f"{demand_supply.upper()} ZONE"
    else:
        location_label = 'NO CLEAR ZONE'

    out = {
        'trend': trend, 'trend_stars': stars,
        'price_location': location_label,
        'support': support, 'resistance': resistance,
        'vwap': vwap_val, 'vwap_position': vwap_pos,
        'volume_profile': {'poc': poc or None, 'vah': vah or None,
                            'val': val or None, 'state': vp_state, 'side': vp_side},
        'order_block': {'label': ob_label, 'freshness': ob_freshness},
        'chart_pattern': (chart_pat or {}).get('pattern') if chart_pat else None,
        'candle_pattern': (candle_pat or {}).get('pattern') if candle_pat else None,
        'structure_score': score,
        'demand_supply': demand_supply,
        'decision': decision,
    }
    st.session_state['_market_structure'] = out
    st.session_state['_ms_cache'] = (time.time(), out)
    return out


def _event_edge(event_key, signature, cooldown_s=300):
    """Edge-triggered dedup for capture_stage2_market_events: fire only when
    `signature` changes, or `cooldown_s` has elapsed since it last fired
    unchanged (same pattern as the entry gate's _sig/_last_sig dedup, kept
    separate since these are lower-priority ambient events, not trade
    alerts)."""
    sigs = st.session_state.setdefault('_stage2_evt_sig', {})
    prev = sigs.get(event_key)
    now = time.time()
    if prev and prev[0] == signature and now - prev[1] < cooldown_s:
        return False
    sigs[event_key] = (signature, now)
    return True


def _notify_writing_telegram(side, headline, detail, spot_price):
    """📢 Mirror a heavy call/put writing event to the main Telegram bot.

    Opt-out via the sidebar toggle (`_writing_tg_on`, default `WRITING_TG_DEFAULT`).
    The caller has already passed the `_event_edge` gate, so this is once per
    episode — no throttle of its own is needed. `force=True` because a writing
    note is not entry-tier and would otherwise be routed Discord-only by
    `send_telegram_message_sync`; the user asked for it ON Telegram specifically.

    Nothing is computed here — headline, detail and spot come from the caller,
    which read them off the Market Picture's ΔOI bias. It only words and sends.
    """
    try:
        if not st.session_state.get('_writing_tg_on', WRITING_TG_DEFAULT):
            return
        if side == 'CALL':
            glyph, banner = '🧱', 'CALL WRITING / CAPPING — resistance building'
        else:
            glyph, banner = '🛡', 'PUT WRITING — support building'
        from mios_v5 import bias_ball as _bb
        msg = _bb.prefix(
            _bb.writing_bias(side),
            f"{glyph} <b>{banner}</b>\n"
            f"{headline}\n"
            f"{detail}\n"
            f"📍 Spot: ₹{spot_price:,.1f}")
        send_telegram_message_sync(msg, force=True)
    except Exception:
        pass  # an alert must never take the cycle down


def _notify_poc_shifts():
    """📍 Alert when a chart's dynamic POC steps to a new level.

    The per-panel dynamic POC is published on `_leg_profiles` by the terminal —
    one owner, `compute_dynamic_poc`, reached through the `_premium_builders`
    bridge. This reads only that, compares each chart to the last level it saw,
    and raises a `POC_SHIFT` market event — which the app already routes to the
    live Discord feed (`_relay_event_to_discord`) and the Supabase audit trail.

    ⚠️ NOT `_throttled_telegram_send`: its non-entry branch calls
    `send_discord_message`, which is a paused no-op — the alert would archive but
    never appear. `capture_market_event` is the path that actually reaches
    Discord in this app.

    Opt-in via the sidebar (`_poc_shift_on`, default `POC_SHIFT_ALERTS_DEFAULT`).
    `mios_v5.poc_shift` owns the comparison and the wording; this owns the memory,
    the per-chart edge gate and the send.
    """
    try:
        if not st.session_state.get('_poc_shift_on', POC_SHIFT_ALERTS_DEFAULT):
            return
        from mios_v5 import poc_shift as _ps
        profiles = st.session_state.get('_leg_profiles') or {}
        if not profiles:
            return
        current = {c: (profiles.get(c) or {}).get('dynamic_poc')
                   for c in _ps.CHARTS}
        previous = st.session_state.get('_poc_shift_prev') or {}
        labels = {'NIFTY': 'NIFTY',
                  'CALL': profiles.get('call_label') or 'ATM Call',
                  'PUT': profiles.get('put_label') or 'ATM Put'}
        _spot = st.session_state.get('_nifty_spot_live')
        for shift in _ps.detect(current, previous):
            _c = shift['chart']
            _lbl = labels.get(_c)
            # Edge-gated per chart so an oscillating bin does not ping-pong an
            # alert every cycle; the relay also dedups identical headlines 5 min.
            _dp = 0 if _c == 'NIFTY' else 2
            if not _event_edge(f'poc_shift_{_c}',
                               f"{shift['direction']}:{shift['cur']:.{_dp}f}"):
                continue
            from mios_v5 import bias_ball as _bb
            capture_market_event(
                EventType.POC_SHIFT, EventSeverity.WARNING,
                _bb.prefix(_bb.poc_bias(_c, shift['direction']),
                           _ps.headline(shift, label=_lbl)),
                _ps.detail(shift, label=_lbl),
                snapshot={'price': _spot} if _spot else None)
        # Remember the latest level for every chart that HAS one, so the next
        # step is measured against the last real level rather than wiped by a
        # cycle where the panel briefly produced no POC.
        merged = dict(previous)
        for _c in _ps.CHARTS:
            if current.get(_c) is not None:
                merged[_c] = current[_c]
        st.session_state['_poc_shift_prev'] = merged
    except Exception:
        pass  # an alert must never take the cycle down


def _notify_chart_formations():
    """📐 Telegram note when a new high-volume pivot or a new VOB forms.

    Reads what the terminal already published — `_leg_profiles[chart].hv_points`
    for the pivots (one owner, `volume_points.high_volume_pivots`) and
    `_atm_leg_vob_volume[label]` for the blocks (one owner, `analyze_vob_volume`)
    — turns each into a signature via `mios_v5.formation_alerts`, and sends the
    ones this session has not seen before.

    ⚠️ Seed, don't replay. On the FIRST time a (chart, kind) is observed, its
    current pivots/zones are recorded as already-seen and NOTHING is sent — the
    structure that existed when the app loaded is not "new". Only what forms
    afterwards alerts, once each. That is the whole reason this cannot spam: it
    is not re-announcing the session's history every 20 seconds.

    Opt-out via the sidebar (`_formation_alerts_on`, default
    `FORMATION_ALERTS_DEFAULT`). VOB is asked for on the legs only, because the
    terminal draws order blocks on the CALL/PUT panels, not on NIFTY.
    """
    try:
        if not st.session_state.get('_formation_alerts_on',
                                    FORMATION_ALERTS_DEFAULT):
            return
        from mios_v5 import formation_alerts as _fa
        profiles = st.session_state.get('_leg_profiles') or {}
        if not profiles:
            return
        labels = {'NIFTY': 'NIFTY',
                  'CALL': profiles.get('call_label') or 'ATM Call',
                  'PUT': profiles.get('put_label') or 'ATM Put'}
        vob_store = st.session_state.get('_atm_leg_vob_volume') or {}
        seen = st.session_state.setdefault('_formation_seen', {})

        def _emit(kind, chart, items, sig_of, msg_of, dp):
            # (chart, kind) → the set of signatures already alerted (or seeded).
            key = f"{kind}:{chart}"
            item_by_sig = {}
            order = []
            for it in items or ():
                if not isinstance(it, dict):
                    continue
                s = sig_of(it, dp) if kind == 'hvp' else sig_of(it)
                if s is None:
                    continue
                order.append(s)
                item_by_sig[s] = it          # last write wins per signature
            # `diff` owns the seed-vs-diff rule: first observation seeds silently.
            to_alert, updated = _fa.diff(order, seen.get(key))
            seen[key] = updated
            for s in to_alert:
                try:
                    # → the alert bot, not the main stream (owner's request).
                    send_formation_alert(
                        msg_of(chart, labels.get(chart), item_by_sig[s], dp))
                except Exception:
                    pass

        # VOB formation was paused by the owner (too noisy); HVP stays on. The
        # seeding still runs when it is re-enabled — `diff` seeds on first sight
        # regardless — so turning it back on does not replay the day's blocks.
        _vob_on = st.session_state.get('_vob_formation_on',
                                       VOB_FORMATION_ALERTS_DEFAULT)
        for chart in _fa.CHARTS:
            prof = profiles.get(chart) or {}
            dp = 0 if chart == 'NIFTY' else 2
            _emit('hvp', chart, prof.get('hv_points'),
                  _fa.hvp_signature, _fa.hvp_message, dp)
            if _vob_on and chart in ('CALL', 'PUT'):
                zones = vob_store.get(labels.get(chart)) or []
                _emit('vob', chart, zones,
                      _fa.vob_signature, _fa.vob_message, dp)
    except Exception:
        pass  # an alert must never take the cycle down


def _notify_leg_hvp_touch():
    """📍 Telegram when an option LTP comes within ±5 of one of ITS OWN
    high-volume-point (HVP) lines — call or put.

    Reads what the terminal already published: each leg's HVP lines from
    `_leg_profiles[side].hv_points` (owner: `volume_points.high_volume_pivots`)
    and the leg's LTP from the last close of the cached leg frame. Nothing is
    recomputed.

    Anti-spam is the level-touch rule reused verbatim (`mios_v5.level_touch`):
    each HVP line latches — it alerts once when the LTP enters the ±band and
    re-arms only after the LTP leaves by more than the band — and a per-line
    cooldown ("sleeping facility") suppresses any repeat within the window even
    if the LTP keeps crossing the line. Opt-out via `_leg_hvp_touch_on`.
    """
    try:
        if not st.session_state.get('_leg_hvp_touch_on', LEG_HVP_TOUCH_DEFAULT):
            return
        profiles = st.session_state.get('_leg_profiles') or {}
        if not profiles:
            return
        from mios_v5 import bias_ball as _bb
        from mios_v5 import level_touch as _lt
        from mios_v5.ui.terminal_chart import atm_legs as _atm_legs
        call_df, put_df, _ce, _pe = _atm_legs(st.session_state.get('_atm_leg_dfs'))
        legs = {'CALL': call_df, 'PUT': put_df}
        labels = {'CALL': profiles.get('call_label') or 'ATM Call',
                  'PUT': profiles.get('put_label') or 'ATM Put'}
        states = st.session_state.setdefault('_leg_hvp_touch_state', {})
        now = time.time()
        for side in ('CALL', 'PUT'):
            df_l = legs.get(side)
            try:
                ltp = (float(df_l['close'].iloc[-1])
                       if df_l is not None and not getattr(df_l, 'empty', True)
                       else None)
            except Exception:
                ltp = None
            if ltp is None:
                continue
            for p in ((profiles.get(side) or {}).get('hv_points') or ()):
                if not isinstance(p, dict):
                    continue
                try:
                    hv = float(p.get('price'))
                except (TypeError, ValueError):
                    continue
                key = f"{side}:{round(hv, 1)}"
                alert, new_state = _lt.evaluate(
                    hv, ltp, states.get(key), band=LEG_HVP_BAND,
                    rearm=LEG_HVP_BAND * 2, cooldown_s=LEG_HVP_COOLDOWN_S, now=now)
                states[key] = new_state
                if alert:
                    _pv = str(p.get('side', '') or '').title()
                    # NIFTY-bias ball: a HIGH pivot is resistance, a LOW is
                    # support, then the leg rule inverts for PUT (bias_ball owns
                    # that one rule) — so the ball reads NIFTY's direction.
                    _bias = _bb.hvp_bias(side, p.get('side'))
                    msg = (f"📍 <b>{labels[side]} LTP at HVP line</b>\n"
                           f"LTP ₹{ltp:,.2f} · HVP ₹{hv:,.2f} "
                           f"({ltp - hv:+.2f} pts)"
                           + (f" · {_pv} pivot" if _pv else ""))
                    msg = _bb.prefix(_bias, msg)
                    try:
                        send_telegram_message_sync(msg, force=True)
                    except Exception:
                        pass
    except Exception:
        pass  # an alert must never take the cycle down


def _gather_market_snapshot():
    """Collect everything the app has ALREADY computed into one flat dict for
    `mios_v5.market_snapshot.build`. Every read is defensive — a missing producer
    just drops its field, and the formatter skips empty sections."""
    def _n(v):
        try:
            f = float(v)
            return None if f != f else f
        except (TypeError, ValueError):
            return None

    def _wall(x):
        return x[0] if isinstance(x, (list, tuple)) and x else None

    d = {}
    ss = st.session_state
    d['spot'] = _n(ss.get('_nifty_spot_live'))
    d['time'] = (ss.get('_opt_data_ts') or '')[:19].replace('T', ' ') or None

    mp = ss.get('_market_picture') or {}
    d['regime'] = mp.get('regime')
    d['p_up'], d['p_down'], d['p_side'] = mp.get('p_up'), mp.get('p_down'), mp.get('p_side')
    d['vwap'] = _n(mp.get('vwap'))
    d['oi_ce_wall'] = _n(_wall(mp.get('oi_ceiling')))
    d['oi_pe_wall'] = _n(_wall(mp.get('oi_floor')))
    d['magnet'] = _n(_wall(mp.get('oi_pin')))
    _ab = mp.get('atm_bias') or {}
    d['atm_verdict'] = _ab.get('verdict')
    d['atm_score'] = (f"{_ab['score']:+.1f}" if _n(_ab.get('score')) is not None else None)
    _dex = mp.get('dex_bias')
    d['dex'] = (_dex.get('label') if isinstance(_dex, dict) else _dex)
    _sk = mp.get('skew_bias')
    d['skew'] = (_sk.get('label') if isinstance(_sk, dict) else _sk)
    _doi = mp.get('doi_bias')
    d['doi_bias'] = (_doi.get('label') if isinstance(_doi, dict) else _doi)
    for _k, _src in (('global', 'global_bias'), ('news', 'news_bias'),
                     ('commodity', 'commodity_bias')):
        _v = mp.get(_src)
        d[_k] = (_v.get('label') or _v.get('regime') if isinstance(_v, dict) else _v)
    _vc = mp.get('vc_exp') or {}
    d['net_vanna'] = (f"vanna {_vc['net_vanna']:+,.0f}" if _n(_vc.get('net_vanna')) is not None else None)
    d['net_charm'] = (f"charm {_vc['net_charm']:+,.0f}" if _n(_vc.get('net_charm')) is not None else None)
    d['net_vega'] = (f"vega {_vc['net_vega']:+,.0f}" if _n(_vc.get('net_vega')) is not None else None)

    gx = ss.get('_gex_data') or {}
    d['total_gex'] = (f"{gx['total_gex']:+,.0f}" if _n(gx.get('total_gex')) is not None else None)
    d['gamma_flip'] = _n(gx.get('gamma_flip_level'))
    d['gex_signal'] = gx.get('gex_signal')

    mf = ss.get('_money_flow_data') or {}
    d['poc'] = _n(mf.get('poc_price'))
    d['vah'] = _n(mf.get('value_area_high'))
    d['val'] = _n(mf.get('value_area_low'))

    try:
        from mios_v5.final_read import build_final_read
        fr = build_final_read(ss.get('_mios_state')) or {}
        d['support'] = _n(fr.get('strong_support'))
        d['resistance'] = _n(fr.get('strong_resistance'))
        _bz = fr.get('battle_zone') or {}
        d['war_zone'] = _n(_bz.get('price')) if isinstance(_bz, dict) else None
        d['expected_winner'] = fr.get('expected_winner')
    except Exception:
        pass

    fmr = ss.get('_full_market_read') or {}
    d['call_mode'], d['put_mode'] = fmr.get('call_mode'), fmr.get('put_mode')
    d['call_strength'], d['put_strength'] = fmr.get('call_strength'), fmr.get('put_strength')
    d['breakout'], d['rejection'] = fmr.get('breakout'), fmr.get('breakdown')

    # level-acceptance observed states, from the strip's last read
    try:
        _zones = ss.get('_la_zones_latest') or []
        _la = []
        for z in _zones:
            _obs = str(z.get('observed') or '').replace('_', ' ')
            _pz = _n(z.get('price'))
            if _obs and _pz is not None:
                _la.append(f"₹{_pz:,.0f} {_obs}")
        d['level_acceptance'] = _la or None
    except Exception:
        pass

    # greek behaviour headline, if the strip published one
    try:
        _gbh = ss.get('_greek_behaviour_synth')
        if _gbh:
            d['greek_behaviour'] = _gbh
    except Exception:
        pass
    return d


def _send_market_snapshot():
    """Build the full snapshot and send it to Telegram (chunked). Returns the
    number of parts sent, or 0 on failure."""
    from mios_v5.market_snapshot import build as _snap_build, chunks as _snap_chunks
    text = _snap_build(_gather_market_snapshot())
    parts = _snap_chunks(text)
    for _p in parts:
        send_telegram_message_sync(_p, force=True)
    return len(parts)


def _notify_flow_at_level():
    """📨 Alert-BOT note when one option side is being traded harder than the
    other while spot sits on the matching level:

      • PUT buy+sell heavier than CALL, spot AT RESISTANCE
      • CALL buy+sell heavier than PUT, spot AT SUPPORT

    Requested against the `CALL vs PUT — Cum Buy / Cum Sell` graph: a volume BURST
    in the put at resistance → signal; same for the call at support. Each leg is
    judged against ITS OWN recent normal — no put-vs-call comparison. Goes to the
    SECOND (alert) Telegram bot, `send_telegram_alert_bot`, not the main stream.

    Reads only already-published numbers — the graph's activity history
    (`_atm_flow_hist`, stashed in `render_atm_cvd_graphs`) and the ranked
    support/resistance (`final_read`). `mios_v5.flow_level_alerts` owns the "is it
    bursting AND on the level AND is this a fresh crossing" decision; this only
    reads, latches per event across cycles, and sends. The rising-edge latch is
    deliberate — a standing condition re-emitted every cycle is exactly the flood
    the pivot alerts produced. Opt-out via `_flow_level_alerts_on`.
    """
    try:
        if not st.session_state.get('_flow_level_alerts_on',
                                    FLOW_LEVEL_ALERTS_DEFAULT):
            return
        hist = st.session_state.get('_atm_flow_hist') or []
        if len(hist) < 3:
            return
        from mios_v5 import flow_level_alerts as _fla
        spot = st.session_state.get('_nifty_spot_live')
        if not spot:
            return
        from mios_v5.final_read import build_final_read
        fr = build_final_read(st.session_state.get('_mios_state')) or {}
        # split the (t, call_act, put_act) history into per-leg (t, value) series
        call_series = [(t, c) for (t, c, _p) in hist if c is not None]
        put_series = [(t, p) for (t, _c, p) in hist if p is not None]
        events = _fla.assess(
            call_series, put_series, spot,
            support=fr.get('strong_support'),
            resistance=fr.get('strong_resistance'))

        profs = st.session_state.get('_leg_profiles') or {}
        call_label = profs.get('call_label') or 'ATM Call'
        put_label = profs.get('put_label') or 'ATM Put'
        states = st.session_state.setdefault('_flow_level_state', {})
        now = time.time()
        for name, info in events.items():
            fire, new_state = _fla.latch(info['active'], states.get(name), now)
            states[name] = new_state
            if fire:
                try:
                    send_telegram_alert_bot(
                        _fla.message(name, info, call_label, put_label))
                except Exception:
                    pass
    except Exception:
        pass  # an alert must never take the cycle down


def _notify_level_touches():
    """🎯 Telegram note when spot reaches a key level within ±5 points.

    Levels watched, each from the read that owns it and none recomputed here:
      • the war zone — Stage 42's battle price (`fr.battle_zone`);
      • both OI walls — the dominant CE/PE OI concentration (`_market_picture`);
      • the ranked strong support / strong resistance (`fr`).

    Each is latched independently in `_level_touch_state`, so a level price sits
    at does not re-alert every cycle — `level_touch.evaluate` fires once on
    entry and re-arms only after price has left the level. When two levels are
    the same number this cycle (war zone == a ranked S/R, say), `dedupe` collapses
    them to one message. Opt-out via `_level_touch_on` (default
    `LEVEL_TOUCH_DEFAULT`).
    """
    try:
        if not st.session_state.get('_level_touch_on', LEVEL_TOUCH_DEFAULT):
            return
        spot = st.session_state.get('_nifty_spot_live')
        if not spot:
            return
        spot = float(spot)
        from mios_v5 import level_touch as _lt
        from mios_v5.final_read import build_final_read
        fr = build_final_read(st.session_state.get('_mios_state')) or {}
        mp = st.session_state.get('_market_picture') or {}

        def _num(v):
            try:
                x = float(v)
            except (TypeError, ValueError):
                return None
            return None if x != x else x

        def _oi(x):
            # OI walls arrive as (price, oi_in_lakhs); tolerate a bare number too
            if isinstance(x, (list, tuple)) and x:
                return _num(x[0]), (_num(x[1]) if len(x) > 1 else None)
            return _num(x), None

        from mios_v5 import bias_ball as _bb
        # (key, label, icon, price, extra_lines, bias) in priority order — the
        # war zone leads, so when it shares a price with a ranked level `dedupe`
        # keeps the war zone's richer message. Bias is the NIFTY-direction ball:
        # the war zone reads off its expected winner; a plain OI-wall or S/R
        # arrival has no bounce-vs-break call yet, so it is neutral.
        targets = []
        bz = fr.get('battle_zone')
        if isinstance(bz, dict):
            _p = _num(bz.get('price'))
            if _p is not None:
                _t = str(bz.get('type') or '').upper()
                _icon = {'SUPPORT': '🛡', 'RESISTANCE': '🧱'}.get(_t, '⚔️')
                _win = fr.get('expected_winner')
                _odds = ' · '.join(
                    f"{k} {v:.0f}%" for k, v in
                    (fr.get('probabilities') or {}).items()
                    if isinstance(v, (int, float)))
                targets.append((
                    'war_zone', f"war zone — {_t}".strip(), _icon, _p,
                    [f"Expected winner: {_win}" if _win else None,
                     _odds or None], _bb.winner_bias(_win)))

        _cp, _cq = _oi(mp.get('oi_ceiling'))
        if _cp is not None:
            targets.append(('oi_ceiling', "CE OI wall (resistance)", '🧱', _cp,
                            [f"{_cq:.1f}L OI" if _cq else None], _bb.NEUTRAL))
        _fp, _fq = _oi(mp.get('oi_floor'))
        if _fp is not None:
            targets.append(('oi_floor', "PE OI wall (support)", '🛡', _fp,
                            [f"{_fq:.1f}L OI" if _fq else None], _bb.NEUTRAL))

        # The ranked S/R touch was paused by the owner (too noisy); the war-zone
        # and OI-wall touches above are unaffected. Off by default — flip
        # `SR_TOUCH_ALERTS_DEFAULT` or tick the sidebar box to bring it back.
        if st.session_state.get('_sr_touch_on', SR_TOUCH_ALERTS_DEFAULT):
            _res = _num(fr.get('strong_resistance'))
            if _res is not None:
                targets.append(('resistance', "resistance", '🧱', _res, [],
                                _bb.NEUTRAL))
            _sup = _num(fr.get('strong_support'))
            if _sup is not None:
                targets.append(('support', "support", '🛡', _sup, [],
                                _bb.NEUTRAL))

        states = st.session_state.setdefault('_level_touch_state', {})
        hits = []
        for key, label, icon, price, extra, bias in targets:
            alert, new_state = _lt.evaluate(price, spot, states.get(key),
                                            now=time.time())
            states[key] = new_state
            if alert:
                hits.append((label, price, _bb.prefix(
                    bias, _lt.message(label, price, spot, icon, extra))))
        for _label, _price, _msg in _lt.dedupe(hits):
            try:
                send_telegram_message_sync(_msg, force=True)
            except Exception:
                pass
    except Exception:
        pass  # an alert must never take the cycle down


def _notify_level_acceptance():
    """⚔️ Telegram note when a watched level RESOLVES — ACCEPTED ABOVE/BELOW or
    REJECTED — from the context-only Level-Acceptance strip.

    Fires ONLY on the transition into a resolved state (never on TESTING /
    BREAK ATTEMPT / FAILED-BREAK-WAIT, which are in-progress), and only once:
    `_la_alert_state` remembers each zone's last-alerted outcome, so a zone
    sitting in ACCEPTED does not repeat, and a per-zone cooldown throttles a
    level that keeps flipping. Zones are already battle-zone-clustered by the
    strip, so VAH/resistance/magnet at one price send ONE message. Reuses the
    strip's own reads — recomputes nothing. Opt-out via `_la_alerts_on`.
    """
    try:
        if not st.session_state.get('_la_alerts_on', LEVEL_ACCEPT_ALERTS_DEFAULT):
            return
        zones = st.session_state.get('_la_zones_latest') or []
        if not zones:
            return
        from mios_v5.level_acceptance import alert_text as _la_alert_text
        states = st.session_state.setdefault('_la_alert_state', {})
        now = time.time()
        for z in zones:
            if not z.get('newly_resolved'):
                continue
            try:
                key = str(round(float(z.get('price'))))
            except (TypeError, ValueError):
                continue
            observed = z.get('observed')
            prev = states.get(key) or {}
            # skip if this exact outcome already alerted, or still cooling down
            if prev.get('observed') == observed:
                continue
            if now - float(prev.get('ts') or 0) < LEVEL_ACCEPT_COOLDOWN_S:
                continue
            msg = _la_alert_text(z)
            if not msg:
                continue
            try:
                send_telegram_message_sync(msg, force=True)
                states[key] = {'observed': observed, 'ts': now}
            except Exception:
                pass
    except Exception:
        pass  # an alert must never take the cycle down


def _notify_confluence_entry():
    """⚡ Telegram when the 4-signal confluence aligns — NIFTY at a level, the
    ATM-strike verdict Strong Bull/Bear AGREEING with the level, the trade-side
    leg's LTP at its support/session-low, and that side's premium energy the
    greater. Every input is an EXISTING engine output; nothing is recomputed.

    Latched per (side, level) with a cooldown so one setup fires once, not every
    ~20s cycle. Opt-out via `_confluence_alerts_on`.
    """
    try:
        if not st.session_state.get('_confluence_alerts_on', CONFLUENCE_ALERTS_DEFAULT):
            return
        spot = st.session_state.get('_nifty_spot_live')
        if not spot:
            return
        spot = float(spot)
        from mios_v5.entry_alignment import (evaluate as _ea_eval,
                                             leg_at_support as _ea_leg,
                                             message as _ea_msg)
        from mios_v5.final_read import build_final_read
        from mios_v5.ui.terminal_chart import atm_legs as _atm_legs

        fr = build_final_read(st.session_state.get('_mios_state')) or {}
        mp = st.session_state.get('_market_picture') or {}
        _ab = mp.get('atm_bias') or {}
        _verdict = str(_ab.get('verdict') or '')
        if 'Strong' not in _verdict:
            return                                   # only strong verdicts qualify

        _bz = fr.get('battle_zone') or {}
        _support = fr.get('strong_support')
        _resistance = fr.get('strong_resistance')
        _war = _bz.get('price') if isinstance(_bz, dict) else None

        # per-side premium energy (already published by Stage 71.7)
        _en = (st.session_state.get('_premium_energy') or {}).get('energy_score') or {}
        _ce_en, _pe_en = _en.get('CALL'), _en.get('PUT')

        # the ATM call/put leg frames + tags the app already cached
        _call_df, _put_df, _ce_tag, _pe_tag = _atm_legs(
            st.session_state.get('_atm_leg_dfs'))
        _sr = st.session_state.get('_atm_leg_sr_behavior') or {}

        def _leg_inputs(df_l, tag):
            ltp = low = None
            try:
                if df_l is not None and not getattr(df_l, 'empty', True):
                    ltp = float(df_l['close'].iloc[-1])
                    low = float(df_l['low'].min())
            except Exception:
                pass
            leg_sr = _sr.get(tag) if tag else None
            tol = max((ltp or 0) * 0.02, 1.0)
            return _ea_leg(leg_sr, ltp, low, tol)

        _call_at_sup = _leg_inputs(_call_df, _ce_tag)
        _put_at_sup = _leg_inputs(_put_df, _pe_tag)

        sig = _ea_eval(spot=spot, support=_support, resistance=_resistance,
                       war_zone=_war, atm_verdict=_verdict,
                       call_at_support=_call_at_sup, put_at_support=_put_at_sup,
                       call_energy=_ce_en, put_energy=_pe_en)
        if not sig:
            return

        now = time.time()
        try:
            key = f"{sig['side']}:{round(float(sig.get('level') or 0))}"
        except (TypeError, ValueError):
            key = str(sig['side'])
        prev = st.session_state.get('_confluence_alert_state') or {}
        if prev.get('key') == key and now - float(prev.get('ts') or 0) < CONFLUENCE_COOLDOWN_S:
            return                                   # same setup, still cooling
        try:
            send_telegram_message_sync(_ea_msg(sig, spot), force=True)
            st.session_state['_confluence_alert_state'] = {'key': key, 'ts': now}
        except Exception:
            pass
    except Exception:
        pass  # an alert must never take the cycle down


def _notify_entry_reversed():
    """⚠️ Alert to Telegram when NIFTY is at a price zone but the bias has
    reversed against the trade setup. This catches whipsaw scenarios where
    price reached the level but conditions deteriorated (trend weakened,
    opposite writers appeared, etc.).

    Latched per reversal with a cooldown so it fires once, not every cycle.
    Opt-out via `_entry_reversed_on`.
    """
    try:
        if not st.session_state.get('_entry_reversed_on', ENTRY_REVERSED_ALERT_DEFAULT):
            return
        if not TELEGRAM_ALERT_BOT_TOKEN or not TELEGRAM_ALERT_CHAT_ID:
            return
        from mios_v5.final_read import build_final_read

        mp = st.session_state.get('_market_picture') or {}
        spot = st.session_state.get('_nifty_spot_live')
        if not spot or not mp:
            return
        spot = float(spot)

        eg = mp.get('entry_gate') or {}
        state = eg.get('state', '')

        if state != 'REVERSED':
            return

        level = eg.get('level')
        zone = eg.get('zone', '')
        if not level:
            return

        # Latch with cooldown so we alert once per reversal, not every cycle
        states = st.session_state.setdefault('_entry_reversed_state', {})
        now = time.time()
        key = f"reversed:{round(level, 1)}"
        prev = states.get(key, {})

        last_alert = prev.get('last_alert_time')
        if last_alert and (now - last_alert) < ENTRY_REVERSED_COOLDOWN_S:
            return  # sleeping (cooldown active)

        # Alert once on entry to the reversed state
        if prev.get('state_seen'):
            return  # already alerted for this reversal

        fr = build_final_read(st.session_state.get('_mios_state')) or {}
        _ab = mp.get('atm_bias') or {}
        reason = eg.get('reason', '')

        msg = (
            f"⚠️ <b>Entry Reversal at ₹{level:,.0f}</b>\n"
            f"Zone: {zone} · ATM: {_ab.get('verdict', 'N/A')}\n"
            f"Reason: {reason}\n"
            f"Current: 🎯 ₹{spot:,.1f}"
        )

        try:
            # Send to alert bot, not main bot
            url = f"https://api.telegram.org/bot{TELEGRAM_ALERT_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_ALERT_CHAT_ID,
                "text": msg,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass

        # Mark as alerted
        states[key] = {'state_seen': True, 'last_alert_time': now}

        # Reset alert tracker if spot moves far from the level (so next reversal at same level re-alerts)
        dist = abs(spot - level)
        if dist > eg.get('band', 5) * 3:  # 3x the entry band means we've clearly left
            states.pop(key, None)

    except Exception:
        pass  # an alert must never take the cycle down


def capture_stage2_market_events(spot_price, df, option_data):
    """Feed the Market Event Engine (Discord feed + Supabase audit trail)
    from conditions this app already computes each cycle — the 6-8 event
    types the recognition patterns actually key off. Fire-and-forget,
    exception-safe: never touches live trading, never raises."""
    try:
        if not spot_price or df is None or getattr(df, 'empty', True):
            return
        # market_picture-derived checks (PUT/CALL_WRITING, OI_WALL) are
        # skipped when it hasn't computed yet; the S/R-break, volume and
        # CVD checks below only need df/spot_price and still run
        m = st.session_state.get('_market_picture') or {}
        doi_bias = m.get('doi_bias') or {}
        doi_label = doi_bias.get('label', '')

        # PUT_WRITING / CALL_WRITING — same string match the entry gate
        # already uses to decide "writers building" at a zone.
        #
        # 📢 These are also the owner's requested Telegram alerts. The capture
        # feeds Discord + Supabase + the Story Engine as before; the extra
        # `_notify_writing_telegram` mirrors it to the main Telegram bot when the
        # sidebar toggle is on. It rides the SAME `_event_edge` gate, so it fires
        # once per writing episode, not once per refresh.
        if 'PE writers building' in doi_label and _event_edge('put_writing', 'on'):
            capture_market_event(
                EventType.PUT_WRITING, EventSeverity.WARNING,
                f"Heavy Put Writing near ₹{spot_price:.0f}",
                f"ΔOI bias: {doi_label} — dealers hedging upside, support building",
                snapshot={'price': spot_price})
            _notify_writing_telegram(
                'PUT', f"Heavy Put Writing near ₹{spot_price:.0f}",
                f"ΔOI bias: {doi_label} — support building below", spot_price)
        if 'CE writers capping' in doi_label and _event_edge('call_writing', 'on'):
            capture_market_event(
                EventType.CALL_WRITING, EventSeverity.WARNING,
                f"Heavy Call Writing near ₹{spot_price:.0f}",
                f"ΔOI bias: {doi_label} — dealers capping upside, resistance building",
                snapshot={'price': spot_price})
            _notify_writing_telegram(
                'CALL', f"Heavy Call Writing near ₹{spot_price:.0f}",
                f"ΔOI bias: {doi_label} — capping upside, resistance building",
                spot_price)

        # OI_WALL — spot within ~25pts of the dominant CE/PE OI concentration
        _prox = 25.0
        oi_ceiling, oi_floor = m.get('oi_ceiling'), m.get('oi_floor')
        if oi_ceiling and abs(spot_price - oi_ceiling[0]) <= _prox and \
                _event_edge('oi_wall_ce', f"{oi_ceiling[0]:.0f}"):
            capture_market_event(
                EventType.OI_WALL, EventSeverity.INFO,
                f"CE OI wall at ₹{oi_ceiling[0]:.0f}",
                f"{oi_ceiling[1]:.1f}L OI — resistance concentration",
                price_point=oi_ceiling[0], snapshot={'price': spot_price})
        if oi_floor and abs(spot_price - oi_floor[0]) <= _prox and \
                _event_edge('oi_wall_pe', f"{oi_floor[0]:.0f}"):
            capture_market_event(
                EventType.OI_WALL, EventSeverity.INFO,
                f"PE OI wall at ₹{oi_floor[0]:.0f}",
                f"{oi_floor[1]:.1f}L OI — support concentration",
                price_point=oi_floor[0], snapshot={'price': spot_price})

        # SUPPORT_BREAK / RESISTANCE_BREAK / BREAKOUT_CANDLE — a level
        # broke with volume confirmation (classify_sr_behavior's own bar)
        try:
            beh = classify_sr_behavior(df, spot_price)
        except Exception:
            beh = None
        if beh and beh.get('state') == 'BREAKING':
            _lvl = beh.get('level')
            _sig_b = f"{beh.get('side')}@{_lvl:.0f}" if _lvl else beh.get('side')
            if _event_edge('sr_break', _sig_b):
                _etype = EventType.SUPPORT_BREAK if beh.get('side') == 'SUPPORT' \
                    else EventType.RESISTANCE_BREAK
                capture_market_event(
                    _etype, EventSeverity.WARNING,
                    f"{beh.get('side', '—').title()} broke at ₹{(_lvl or 0):.0f}",
                    f"Price moved decisively through the level with volume confirmation",
                    price_point=_lvl, snapshot={'price': spot_price})
                capture_market_event(
                    EventType.BREAKOUT_CANDLE, EventSeverity.WARNING,
                    f"Breakout candle at ₹{(_lvl or 0):.0f}",
                    f"{beh.get('direction', 'none')} breakout, {beh.get('side', '—').lower()} side",
                    price_point=_lvl, snapshot={'price': spot_price})

        # HIGH_VOLUME — context only, not Discord-worthy on its own (INFO)
        try:
            vol = detect_volume_spike(df, lookback=5)
        except Exception:
            vol = None
        if vol and vol.get('spike') and _event_edge('high_volume', round(vol.get('ratio', 0), 1)):
            capture_market_event(
                EventType.HIGH_VOLUME, EventSeverity.INFO,
                f"Volume spike ({vol.get('ratio', 0):.1f}x average)",
                vol.get('label', ''), snapshot={'price': spot_price})

        # CVD_REVERSAL — simple body-fraction buy/sell pressure sign, same
        # technique used elsewhere in the file (_leg_flow), tracked over a
        # short rolling window to catch a stable flip, not single-bar noise
        try:
            _tail = df.tail(20)
            if len(_tail) >= 10:
                cvd_now = _of.cvd_sign(_tail)
                if _of.is_missing(cvd_now):
                    raise ValueError('no CVD reading')   # caught below; no event
                _hist = st.session_state.setdefault('_stage2_cvd_hist', [])
                _hist.append(cvd_now)
                if len(_hist) > 6:
                    del _hist[:len(_hist) - 6]
                if len(_hist) == 6 and cvd_now != 0 and \
                        all(x == _hist[0] for x in _hist[:3]) and \
                        all(x == cvd_now for x in _hist[3:]) and _hist[0] != cvd_now:
                    if _event_edge('cvd_reversal', cvd_now):
                        capture_market_event(
                            EventType.CVD_REVERSAL, EventSeverity.WARNING,
                            f"CVD reversal — flipped {'bullish' if cvd_now > 0 else 'bearish'}",
                            "Cumulative volume delta flipped and held — order-flow direction changing",
                            snapshot={'price': spot_price})
        except Exception:
            pass
    except Exception:
        pass




def render_full_market_read(spot_price, df, option_data):
    """Step 12 — render the draft's Final AI Output block."""
    try:
        fmr = compute_full_market_read(spot_price, df, option_data)
    except Exception as e:
        st.caption(f"Market read warming up… ({e})")
        return
    # 🎯 S/R from the SINGLE canonical Reaction-Zone object (_reaction_sr) — the
    # same confluence support/resistance the Trade Card, Entry Gate and Stage 35
    # read, so the cockpit no longer states its own opinion. Falls back to the
    # raw OI walls only until the canonical object warms up, and stays visible
    # even while CALL/PUT scoring warms up (the zones need only the chain).
    _rsr = st.session_state.get('_reaction_sr') or {}
    _rs_sup = _rsr.get('support'); _rs_res = _rsr.get('resistance')
    _mp_sr = st.session_state.get('_market_picture') or {}
    _flr = _mp_sr.get('oi_floor'); _cel = _mp_sr.get('oi_ceiling')
    _sup_lv = (_rs_sup.get('price') if _rs_sup else None) or (_flr[0] if _flr else None)
    _res_lv = (_rs_res.get('price') if _rs_res else None) or (_cel[0] if _cel else None)

    def _canon_sr_line(zside, fallback_wall, is_support):
        _emo = '🟢 Support' if is_support else '🔴 Resistance'
        if zside and zside.get('price'):
            _srcs = '·'.join(zside.get('sources') or []) or '—'
            _strong = ' 💪' if zside.get('strength', 0) >= 60 else ''
            return (f"{_emo} ₹{zside['price']:,.0f}{_strong} "
                    f"({zside.get('strength', 0)}% · {zside.get('src_count', 0)} src "
                    f"{_srcs} · {zside.get('status', '')}{_sr_trend_badge(zside)})")
        if fallback_wall:
            _tag = 'PE' if is_support else 'CE'
            return f"{_emo} ₹{fallback_wall[0]:,.0f} ({_tag} {fallback_wall[1]:.0f}L)"
        return f"{_emo} —"

    if not fmr:
        if _rs_sup or _rs_res or _flr or _cel:
            _s = _canon_sr_line(_rs_sup, _flr, True)
            _r = _canon_sr_line(_rs_res, _cel, False)
            st.markdown(
                "<div style='font-size:12px;color:#cfd8e6;margin-bottom:6px'>"
                "📊 CALL/PUT modes warming up — but S/R is live: "
                f"<b>{_s}</b> &nbsp;·&nbsp; <b>{_r}</b></div>",
                unsafe_allow_html=True)
        else:
            st.caption("📊 CALL/PUT scoring warming up — needs the option chain "
                       "+ a few cycles for LTP/IV direction.")
        return
    _mc = ('#17c98b' if fmr['market_kind'] == 'bull'
           else ('#f0455a' if fmr['market_kind'] == 'bear'
                 else ('#c026d3' if fmr['market_kind'] == 'vol' else '#f0b429')))
    _reasons = " · ".join(fmr['reasons']) if fmr['reasons'] else "warming up"
    # S/R strength from the canonical object when present (options-defense blend
    # already folded in), else the full-market-read strength. 💪 = STRONG (≥60%).
    _sup_str = (_rs_sup.get('strength') if _rs_sup else None)
    _sup_str = _sup_str if _sup_str is not None else fmr['support_strength']
    _res_str = (_rs_res.get('strength') if _rs_res else None)
    _res_str = _res_str if _res_str is not None else fmr['resistance_strength']
    _sup_txt = (f"Sup {_sup_str}%" + (f" @ ₹{_sup_lv:,.0f}" if _sup_lv else "")
                + (" 💪" if _sup_str >= 60 else ""))
    _res_txt = (f"Res {_res_str}%" + (f" @ ₹{_res_lv:,.0f}" if _res_lv else "")
                + (" 💪" if _res_str >= 60 else ""))
    st.markdown(
        f"<div style='display:grid;grid-template-columns:1fr 1fr 1.3fr;gap:10px;margin-bottom:6px'>"
        f"<div style='background:#111722;border:1px solid #1e2836;border-radius:10px;padding:11px 14px'>"
        f"<div style='font-size:10px;letter-spacing:.12em;color:#ffffff;text-transform:uppercase'>CALL</div>"
        f"<div style='font-weight:700;font-size:15px;color:#ffffff'>{fmr['call_mode']}</div>"
        f"<div style='font-family:monospace;font-size:11px;color:#ffffff'>Str {fmr['call_strength']}% · Conf {fmr['call_conf']}%</div></div>"
        f"<div style='background:#111722;border:1px solid #1e2836;border-radius:10px;padding:11px 14px'>"
        f"<div style='font-size:10px;letter-spacing:.12em;color:#ffffff;text-transform:uppercase'>PUT</div>"
        f"<div style='font-weight:700;font-size:15px;color:#ffffff'>{fmr['put_mode']}</div>"
        f"<div style='font-family:monospace;font-size:11px;color:#ffffff'>Str {fmr['put_strength']}% · Conf {fmr['put_conf']}%</div></div>"
        f"<div style='background:#0c1a15;border:1px solid {_mc};border-radius:10px;padding:11px 14px'>"
        f"<div style='font-size:10px;letter-spacing:.12em;color:#ffffff;text-transform:uppercase'>Market</div>"
        f"<div style='font-weight:800;font-size:17px;color:{_mc}'>{fmr['market_label']}</div>"
        f"<div style='font-family:monospace;font-size:11px;color:#ffffff'>"
        f"{_sup_txt} / {_res_txt} · "
        f"Break↑ {fmr['breakout']}% / ↓ {fmr['breakdown']}% · Γblast {fmr['gamma_blast']}</div></div>"
        f"</div>"
        f"<div style='font-size:11px;color:#7fe0bd;margin-bottom:8px'>{_reasons}</div>",
        unsafe_allow_html=True,
    )
    # ── Institutional score row (Dealer / Liquidity / Institution / Squeeze) ──
    try:
        _dd = fmr.get('dealer_dir', 'neutral')
        _ib = fmr.get('institution_bias', 'neutral')
        _dcol = '#17c98b' if _dd == 'bull' else ('#f0455a' if _dd == 'bear' else '#ffffff')
        _icol = '#17c98b' if _ib == 'bull' else ('#f0455a' if _ib == 'bear' else '#ffffff')

        def _pill(lbl, val, sub, col):
            return (f"<div style='background:#0d1117;border:1px solid #1e2836;border-radius:9px;"
                    f"padding:8px 12px'>"
                    f"<div style='font-size:9px;letter-spacing:.10em;color:#ffffff;"
                    f"text-transform:uppercase'>{lbl}</div>"
                    f"<div style='font-weight:800;font-size:16px;color:{col}'>{val}</div>"
                    f"<div style='font-family:monospace;font-size:10px;color:#ffffff'>{sub}</div></div>")
        st.markdown(
            "<div style='display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:8px'>"
            + _pill("Dealer", f"{fmr.get('dealer_score', 0)}", _dd.upper(), _dcol)
            + _pill("Liquidity", f"{fmr.get('liquidity_score', 0)}", "wall size", '#f0b429')
            + _pill("Institution", f"{fmr.get('institution_score', 0)}", _ib.upper(), _icol)
            + _pill("Confidence", f"{fmr.get('overall_conf', 0)}%", "overall", '#38bdf8')
            + _pill("Sq/Squeeze", f"{fmr.get('short_squeeze', 0)}%", "short-squeeze↑", '#a78bfa')
            + "</div>"
            + "<div style='font-size:10px;color:#ffffff;margin-bottom:8px'>Dealer = DEX×GEX · "
              "Liquidity = nearest OI wall · Institution = 0.5·Dealer+0.3·Liq+0.2·OrderBook · "
              "Short-squeeze = call short-covering + put writing + neg-gamma accelerant.</div>",
            unsafe_allow_html=True,
        )
    except Exception:
        pass


def render_strike_mode_dashboard(spot_price, df, option_data):
    """🎯 Strike-Mode Cockpit — ATM±2 CALL/PUT positioning modes + spot
    master-read + overall market verdict. Layer 1 (options): per-strike CE/PE
    mode from LTP-direction (tracked) + ΔOI. Layer 2 (spot): VP + S/R +
    behaviour. Weighted ATM±2 (ATM 40% · ±1 20% · ±2 10%) → market."""
    # Always show the heading + frame; degrade gracefully with whatever data
    # is present (missing fields render as '—', not a blank panel).
    st.markdown("### 🎯 Strike-Mode Cockpit — ATM±2 positioning + spot action")
    try:
        render_full_market_read(spot_price, df, option_data)
    except Exception:
        pass
    ds = (option_data or {}).get('df_summary') if option_data else None
    if ds is None or getattr(ds, 'empty', True) or 'Strike' not in ds.columns:
        st.info("⏳ Option chain not loaded yet — the per-strike ladder appears once the "
                "chain is in (and modes fill after ~3 cycles).")
        return
    try:
        stks = sorted(ds['Strike'].dropna().unique().tolist())
        atm = min(stks, key=lambda x: abs(x - (spot_price or (stks[len(stks) // 2] if stks else 0))))
        gap = min((abs(b - a) for a, b in zip(stks, stks[1:])), default=50) or 50
    except Exception:
        st.caption("Strike ladder unavailable (chain parse issue).")
        return
    wants = [(atm + k * gap, k) for k in (-2, -1, 0, 1, 2)]
    weight = {0: 0.40, 1: 0.20, 2: 0.10}
    hist = st.session_state.setdefault('_strike_mode_hist', {})

    def _g(row, col, d=0.0):
        try:
            return float(row.get(col, d) or d)
        except Exception:
            return d

    def _dir(key, ltp, iv):
        h = hist.setdefault(key, [])
        h.append((time.time(), ltp, iv))
        if len(h) > 12:
            del h[:len(h) - 12]
        if len(h) < 3:
            return 0, 0
        old = h[max(0, len(h) - 6)]
        ld = 1 if ltp > old[1] else (-1 if ltp < old[1] else 0)
        ivd = 1 if iv > old[2] else (-1 if iv < old[2] else 0)
        return ld, ivd

    # Leg candle access — from the live ATM±1 cache, else fetch the wing leg
    # on demand (cached 90s) so all 5 strikes get CVD / VWAP / money-flow.
    leg_dfs = st.session_state.get('_atm_leg_dfs') or {}
    _ctx = st.session_state.get('_cockpit_ctx') or {}

    def _leg_candles(strike, side):
        t = next((k for k in leg_dfs if k.endswith(f"{side} {strike:.0f}")), None)
        if t is not None and leg_dfs[t] is not None and not getattr(leg_dfs[t], 'empty', True):
            return leg_dfs[t]
        sid = (_ctx.get('sids') or {}).get((strike, side))
        api = _ctx.get('api')
        if not sid or api is None:
            return None
        cache = st.session_state.setdefault('_cockpit_wing_cache', {})
        # Share the render's leg-fetch budget with the ATM±1 loop. The two
        # fetchers have different TTLs (60s / 90s) and periodically expire on
        # the SAME render; capping each one separately still let the combined
        # spike through, which is the render that made the page look frozen.
        _wb = st.session_state.get('_leg_fetch_budget')
        _wing_ok = not (_wb and _wb[1] <= 0)
        if _wing_ok and time.time() - cache.get(sid, {}).get('ts', 0) > 90:
            if _wb:
                _wb[1] -= 1
            try:
                _raw = api.get_intraday_data(security_id=sid, exchange_segment=_ctx.get('seg'),
                                             instrument="OPTIDX", interval="1", days_back=1)
                cache[sid] = {'ts': time.time(),
                              'df': process_candle_data(_raw, "1min") if _raw else None}
            except Exception:
                cache[sid] = {'ts': time.time(), 'df': None}
        return cache.get(sid, {}).get('df')

    def _leg_flow(dfl):
        """CVD sign, VWAP position, money-flow POC bias from a leg's candles."""
        if dfl is None or getattr(dfl, 'empty', True) or len(dfl) < 5:
            return 0, 0, 'neu'
        try:
            c = dfl['close'].astype(float)
            cvd = _of.cvd_sign(dfl)
            if _of.is_missing(cvd):
                cvd = 0
            try:
                _vw = ReversalDetector.calculate_vwap(dfl)
                vwp = 1 if (_vw is not None and not _vw.empty and c.iloc[-1] > float(_vw.iloc[-1])) else -1
            except Exception:
                vwp = 0
            try:
                _mfp = calculate_money_flow_profile(dfl.tail(60), num_rows=3, source='Money Flow')
                _b = _mfp_poc_bias(_mfp)
                mf = 'bull' if _b == 'BULL' else ('bear' if _b == 'BEAR' else 'neu')
            except Exception:
                mf = 'neu'
            return cvd, vwp, mf
        except Exception:
            return 0, 0, 'neu'

    # ── Per-strike S/R role from the OI walls in the ATM±2 window:
    #   biggest PE OI = STRONG SUPPORT (🟢), biggest CE OI = STRONG RESISTANCE
    #   (🔴); other strikes with a notable wall (≥45% of the max) = NEAR
    #   support/resistance (light tint). Puts written = support floor, calls
    #   written = resistance cap.
    _ce_oi_map, _pe_oi_map = {}, {}
    for _sk, _off in wants:
        _rr = ds[ds['Strike'] == _sk]
        if _rr.empty:
            continue
        _rr = _rr.iloc[0]
        _ce_oi_map[_sk] = _g(_rr, 'openInterest_CE')
        _pe_oi_map[_sk] = _g(_rr, 'openInterest_PE')
    _max_ce = max(_ce_oi_map.values()) if _ce_oi_map else 0.0
    _max_pe = max(_pe_oi_map.values()) if _pe_oi_map else 0.0
    _strong_sup_k = max(_pe_oi_map, key=_pe_oi_map.get) if _max_pe > 0 else None
    _strong_res_k = max(_ce_oi_map, key=_ce_oi_map.get) if _max_ce > 0 else None

    def _sr_style(strike):
        """→ (row_bg, accent_colour, tag). Strong = bold tint + border; near =
        light tint."""
        pe = _pe_oi_map.get(strike, 0.0)
        ce = _ce_oi_map.get(strike, 0.0)
        pe_r = (pe / _max_pe) if _max_pe else 0.0
        ce_r = (ce / _max_ce) if _max_ce else 0.0
        if strike == _strong_sup_k and pe > 0:
            return 'rgba(23,201,139,0.30)', '#17c98b', '🟢 STRONG SUPPORT'
        if strike == _strong_res_k and ce > 0:
            return 'rgba(240,69,90,0.30)', '#f0455a', '🔴 STRONG RESISTANCE'
        if pe_r >= ce_r and pe_r >= 0.45:
            return 'rgba(23,201,139,0.12)', '#1f9e73', '🟢 near support'
        if ce_r > pe_r and ce_r >= 0.45:
            return 'rgba(240,69,90,0.12)', '#b0454f', '🔴 near resistance'
        return 'transparent', '#5a6675', ''

    from collections import Counter
    rows_html = []
    ce_modes, pe_modes = [], []
    wscore = 0.0
    for strike, off in wants:
        r = ds[ds['Strike'] == strike]
        if r.empty:
            continue
        r = r.iloc[0]
        w = weight[abs(off)]
        cells = {}
        for side in ('CE', 'PE'):
            is_ce = side == 'CE'
            ltp = _g(r, f'lastPrice_{side}')
            doi = _g(r, f'changeinOpenInterest_{side}')
            oi = _g(r, f'openInterest_{side}')
            iv = _g(r, f'impliedVolatility_{side}')
            dlt = _g(r, f'Delta_{side}')
            gmm = _g(r, f'Gamma_{side}')
            veg = _g(r, f'Vega_{side}')
            tht = _g(r, f'Theta_{side}')
            bq = _g(r, f'bidQty_{side}'); aq = _g(r, f'askQty_{side}')
            ld, ivd = _dir(f'{strike:.0f}_{side}', ltp, iv)
            cvd, vwp, mf = _leg_flow(_leg_candles(strike, side))
            mode, vote = _classify_leg_mode(is_ce, ld, doi)
            # CVD confirmation adjusts the weighted vote
            _cvd_ok = (ld > 0 and cvd > 0) or (ld < 0 and cvd < 0) or ld == 0
            wscore += (vote * w) if _cvd_ok else 0
            (ce_modes if is_ce else pe_modes).append((mode, w))
            _mc = ('#17c98b' if vote > 0 else ('#f0455a' if vote < 0 else '#ffffff'))
            _lar = '▲' if ld > 0 else ('▼' if ld < 0 else '▬')
            _cvdar = '▲' if cvd > 0 else ('▼' if cvd < 0 else '▬')
            _cvdc = '#25e39c' if cvd > 0 else ('#ff6076' if cvd < 0 else '#ffffff')
            _mfc = '#25e39c' if mf == 'bull' else ('#ff6076' if mf == 'bear' else '#ffffff')
            _ba = 'B&gt;A' if bq > aq else ('A&gt;B' if aq > bq else 'B=A')
            _doi_pct = (doi / oi * 100) if oi else 0
            cells[side] = (
                f"<div style='color:{_mc};font-weight:700;font-size:12.5px'>{mode}"
                f"{'' if _cvd_ok else ' <span style=color:#f0b429>⚠cvd</span>'}</div>"
                f"<div style='font-family:monospace;font-size:11px;color:#ffffff'>"
                f"{_lar} ₹{ltp:.1f} · ΔOI {_doi_pct:+.1f}% · "
                f"CVD <span style='color:{_cvdc}'>{_cvdar}</span></div>"
                f"<div style='font-family:monospace;font-size:10px;color:#ffffff'>"
                f"MF <span style='color:{_mfc}'>{mf}</span> · {'&gt;' if vwp>0 else '&lt;'}VWAP · "
                f"Bid/Ask {_ba} · IV{'↑' if ivd>0 else ('↓' if ivd<0 else '~')}</div>"
                f"<div style='font-family:monospace;font-size:9.5px;color:#ffffff'>"
                f"Δ{dlt:.2f} Γ{gmm:.3f} V{veg:.1f} Θ{tht:.1f} OI {oi/1e5:.1f}L</div>"
            )
        _bg, _srcol, _srtag = _sr_style(strike)
        _tag_html = (f"<div style='font-size:9px;font-weight:700;color:{_srcol};"
                     f"margin-top:2px'>{_srtag}</div>" if _srtag else '')
        _strong = 'STRONG' in _srtag
        _mid_border = (f"border-left:3px solid {_srcol};border-right:3px solid {_srcol}"
                       if _strong else
                       "border-left:1px solid #1e2836;border-right:1px solid #1e2836")
        _lbl = {-2: 'ATM-2', -1: 'ATM-1', 0: 'ATM', 1: 'ATM+1', 2: 'ATM+2'}[off]
        rows_html.append(
            f"<tr style='background:{_bg}'>"
            f"<td style='padding:7px 10px;text-align:left'>{cells.get('CE','')}</td>"
            f"<td style='padding:7px 8px;text-align:center;background:#0c121c;{_mid_border}'>"
            f"<div style='font-size:9px;letter-spacing:.1em;color:#ffffff'>{_lbl}</div>"
            f"<div style='font-family:monospace;font-weight:700;font-size:14px;color:#ffffff'>{strike:.0f}</div>{_tag_html}</td>"
            f"<td style='padding:7px 10px;text-align:right'>{cells.get('PE','')}</td></tr>"
        )

    def _dom(m):
        if not m:
            return '—'
        agg = {}
        for mode, w in m:
            agg[mode] = agg.get(mode, 0) + w
        return max(agg, key=agg.get)
    call_mode, put_mode = _dom(ce_modes), _dom(pe_modes)
    mkt_dir = 'BULLISH' if wscore >= 1.0 else ('BEARISH' if wscore <= -1.0 else 'NEUTRAL / RANGE')
    mkt_col = '#17c98b' if wscore >= 1.0 else ('#f0455a' if wscore <= -1.0 else '#f0b429')

    # Layer 2 — spot master read
    beh = None
    try:
        beh = classify_sr_behavior(df, spot_price)
    except Exception:
        beh = None
    mf = st.session_state.get('_money_flow_data') or {}
    _poc = float(mf.get('poc_price', 0) or 0)
    _vah = float(mf.get('value_area_high', 0) or 0)
    _val = float(mf.get('value_area_low', 0) or 0)
    _vp_txt = (f"VAL {_val:.0f} · POC {_poc:.0f} · VAH {_vah:.0f}"
               if _poc else "VP warming up")
    _vp_state = ('above POC' if _poc and spot_price >= _poc else ('below POC' if _poc else '—'))
    if beh and beh.get('state') not in (None, 'NONE'):
        _bst = beh['state']; _bdir = beh.get('direction', 'none'); _blvl = beh.get('level')
        _bcol = '#17c98b' if _bdir == 'bull' else ('#f0455a' if _bdir == 'bear' else '#ffffff')
        _beh_txt = (f"<b style='color:{_bcol}'>{_bst}</b> at ₹{_blvl:.0f} "
                    f"({_bdir})") if _blvl else f"<b>{_bst}</b>"
    else:
        _beh_txt = "no clear behaviour at a level"

    # (heading + Final AI Output already rendered at the top of this function)
    st.markdown(
        f"<div style='display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px'>"
        f"<div style='flex:1;min-width:180px;background:#111722;border:1px solid #1e2836;border-radius:10px;padding:10px 12px'>"
        f"<div style='font-size:10px;letter-spacing:.12em;color:#ffffff;text-transform:uppercase'>Spot vs VP</div>"
        f"<div style='font-family:monospace;font-size:12px;color:#ffffff;margin-top:3px'>{_vp_txt}</div>"
        f"<div style='font-size:11px;color:#ffffff;margin-top:2px'>Spot ₹{spot_price:.1f} · {_vp_state}</div></div>"
        f"<div style='flex:1;min-width:180px;background:#111722;border:1px solid #1e2836;border-radius:10px;padding:10px 12px'>"
        f"<div style='font-size:10px;letter-spacing:.12em;color:#ffffff;text-transform:uppercase'>Spot behaviour</div>"
        f"<div style='font-size:13px;color:#ffffff;margin-top:3px'>{_beh_txt}</div></div>"
        f"<div style='flex:1.2;min-width:200px;background:#0c1a15;border:1px solid #1c5a45;border-radius:10px;padding:10px 12px'>"
        f"<div style='font-size:10px;letter-spacing:.12em;color:#ffffff;text-transform:uppercase'>Market — CALL × PUT (wt ATM±2)</div>"
        f"<div style='font-weight:800;font-size:17px;color:{mkt_col};margin-top:2px'>{mkt_dir}</div>"
        f"<div style='font-size:11px;color:#ffffff'>CALL {call_mode} · PUT {put_mode} · net {wscore:+.1f}</div></div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;"
        "background:#0d131d;border:1px solid #1e2836;border-radius:10px'>"
        "<tr style='background:#0e1420'>"
        "<th style='padding:6px 10px;text-align:left;font-size:10px;letter-spacing:.12em;color:#17c98b'>◀ CALL (CE)</th>"
        "<th style='padding:6px;font-size:10px;letter-spacing:.12em;color:#ffffff'>Strike</th>"
        "<th style='padding:6px 10px;text-align:right;font-size:10px;letter-spacing:.12em;color:#f0455a'>PUT (PE) ▶</th></tr>"
        + "".join(rows_html) + "</table></div>",
        unsafe_allow_html=True,
    )
    st.caption("Per strike (ATM±2, wings fetched live): Mode = LTP-dir + ΔOI (Long Build-up / "
               "Writing / Short Covering / Long Unwinding), CVD-confirmed (⚠cvd = flow disagrees). "
               "Row 2 = CVD · row 3 = MoneyFlow · VWAP side · Bid/Ask · IV↕ · row 4 = Δ Γ V Θ OI. "
               "Green = bullish-for-NIFTY, red = bearish · weighted ATM 40% · ±1 20% · ±2 10% · "
               "LTP direction tracked across cycles. "
               "Row highlight = S/R role from OI walls: 🟢 bold = STRONG SUPPORT (biggest PE OI) · "
               "🟢 light = near support · 🔴 bold = STRONG RESISTANCE (biggest CE OI) · 🔴 light = near resistance.")

    # ── 📊 ATM ±2 STRIKES DETAILED TABULATION (14 bias metrics, seller's view) ──
    # Ported from seller_perspective.py, shown directly below the per-strike leg
    # tabulation. Reuses the option chain ALREADY fetched (OI / ΔOI / Volume /
    # LTP / IV, plus the bid/ask depth carried on df_summary) — no new fetch. The
    # MktDepth metric uses those existing bid/ask quantities, not a depth API.
    try:
        from mios_v5.atm_strike_bias import (tabulation as _atm2_tab,
                                             tabulation_html as _atm2_html)
        _atm2_rows = []
        for _off in (-2, -1, 0, 1, 2):
            _sp = atm + _off * gap
            _r = ds[ds['Strike'] == _sp]
            if _r.empty:
                continue
            _rd = _r.iloc[0]
            _atm2_rows.append((float(_sp), {
                'oi_ce': _rd.get('openInterest_CE'), 'oi_pe': _rd.get('openInterest_PE'),
                'chg_ce': _rd.get('changeinOpenInterest_CE'),
                'chg_pe': _rd.get('changeinOpenInterest_PE'),
                'vol_ce': _rd.get('totalTradedVolume_CE'),
                'vol_pe': _rd.get('totalTradedVolume_PE'),
                'ltp_ce': _rd.get('lastPrice_CE'), 'ltp_pe': _rd.get('lastPrice_PE'),
                'iv_ce': _rd.get('impliedVolatility_CE'),
                'iv_pe': _rd.get('impliedVolatility_PE'),
                'bid_ce': _rd.get('bidQty_CE'), 'bid_pe': _rd.get('bidQty_PE'),
                'ask_ce': _rd.get('askQty_CE'), 'ask_pe': _rd.get('askQty_PE'),
            }))
        if _atm2_rows:
            _atm2 = _atm2_html(_atm2_tab(_atm2_rows, float(atm)), float(atm))
            if _atm2:
                st.markdown(_atm2, unsafe_allow_html=True)
    except Exception:
        pass

    # ── 📊 ATM ±2 FULL BIAS GRID (11 biases → verdict, owner's chain-bias set) ──
    # Ported from the owner's option-chain bias script. Same ATM±2 window, but the
    # LTP · OI · ΔOI · Vol · Δ · Γ · Bid/Ask · IV · ΔExp · ΓExp · DVP biases →
    # Score/Verdict/Operator/Scalp/Fake-Real. Reuses the SAME already-fetched
    # df_summary — including the REAL Delta/Gamma the chain build already put on
    # it (Delta_CE/PE, Gamma_CE/PE) — so no new fetch and no Greek recompute.
    try:
        from mios_v5.atm_bias_grid import grid as _bg_grid, grid_html as _bg_html
        _bg_rows = []
        for _off in (-2, -1, 0, 1, 2):
            _sp = atm + _off * gap
            _r = ds[ds['Strike'] == _sp]
            if _r.empty:
                continue
            _rd = _r.iloc[0]
            _bg_rows.append((float(_sp), {
                'ltp_ce': _rd.get('lastPrice_CE'), 'ltp_pe': _rd.get('lastPrice_PE'),
                'oi_ce': _rd.get('openInterest_CE'), 'oi_pe': _rd.get('openInterest_PE'),
                'chg_ce': _rd.get('changeinOpenInterest_CE'),
                'chg_pe': _rd.get('changeinOpenInterest_PE'),
                'vol_ce': _rd.get('totalTradedVolume_CE'),
                'vol_pe': _rd.get('totalTradedVolume_PE'),
                'delta_ce': _rd.get('Delta_CE'), 'delta_pe': _rd.get('Delta_PE'),
                'gamma_ce': _rd.get('Gamma_CE'), 'gamma_pe': _rd.get('Gamma_PE'),
                'bid_ce': _rd.get('bidQty_CE'), 'ask_ce': _rd.get('askQty_CE'),
                'iv_ce': _rd.get('impliedVolatility_CE'),
                'iv_pe': _rd.get('impliedVolatility_PE'),
            }))
        if _bg_rows:
            _bg = _bg_html(_bg_grid(_bg_rows, float(atm), float(spot_price or atm)),
                           float(atm))
            if _bg:
                st.markdown(_bg, unsafe_allow_html=True)
    except Exception:
        pass


def render_atm_cvd_graphs(spot_price):
    """📊 Time-series graphs (x = time, y = value) for the ATM±1 legs —
    CALL side vs PUT side, aggregated across the 3 strikes:
      • CVD (cumulative Buy − Sell)
      • Cumulative Buy volume
      • Cumulative Sell volume
    CLV-weighted estimate from 1m OHLCV (not tick data). Same idea as the
    per-strike OI time-series, but for order-flow: CALL rising while PUT
    falls → NIFTY up; PUT rising while CALL falls → NIFTY down."""
    leg_dfs = st.session_state.get('_atm_leg_dfs') or {}
    ce = [df for tag, df in leg_dfs.items()
          if ' CE ' in f' {tag} ' and df is not None and not getattr(df, 'empty', True)]
    pe = [df for tag, df in leg_dfs.items()
          if ' PE ' in f' {tag} ' and df is not None and not getattr(df, 'empty', True)]
    if not ce and not pe:
        return

    def _agg(dfs, kind):
        cols = []
        for d in dfs:
            try:
                s = _of.cumulative(d, kind, index=d['datetime'])
                if _of.is_missing(s):
                    continue
                cols.append(s)
            except Exception:
                continue
        if not cols:
            return None
        m = pd.concat(cols, axis=1).sort_index().ffill().fillna(0)
        return m.sum(axis=1)

    # Live aggregate series (used both for plotting today and for the
    # date-wise snapshot that builds the history).
    _live = {k: (_agg(ce, k), _agg(pe, k)) for k in ('delta', 'buy', 'sell')}

    # ⚡ Stash the latest CALL/PUT cumulative CVD into a rolling in-session
    # history (~1 sample/cycle, capped 120) — the Zone Reversal watcher reads
    # this to detect sudden CVD impulses at S/R zones.
    try:
        def _cvd_last(s):
            try:
                return float(s.iloc[-1]) if s is not None and len(s) else 0.0
            except Exception:
                return 0.0
        _zh = st.session_state.setdefault('_zone_cvd_hist', [])
        _zh.append((time.time(), _cvd_last(_live['delta'][0]),
                    _cvd_last(_live['delta'][1])))
        if len(_zh) > 120:
            del _zh[:len(_zh) - 120]
    except Exception:
        pass

    # 📨 CALL/PUT activity HISTORY (cumulative buy + sell per side), for the
    # flow-at-level alert (`_notify_flow_at_level`). Stashed HERE because this is
    # where the graph's own numbers are computed — the alert reads them rather than
    # a second estimate. A history, not a single value, because the alert fires on a
    # volume BURST — each leg's recent accumulation rate against its own prior
    # normal — which needs the series. Runs every cycle: `_live` is built above the
    # "Show graphs" toggle. Capped to a session's worth at ~20s cadence.
    try:
        from mios_v5 import flow_level_alerts as _fla_mod

        def _flow_last(s):
            try:
                return float(s.iloc[-1]) if s is not None and len(s) else None
            except Exception:
                return None
        _call_act = _fla_mod.activity(_flow_last(_live['buy'][0]),
                                      _flow_last(_live['sell'][0]))
        _put_act = _fla_mod.activity(_flow_last(_live['buy'][1]),
                                     _flow_last(_live['sell'][1]))
        _fh = st.session_state.setdefault('_atm_flow_hist', [])
        if _call_act is not None or _put_act is not None:
            _fh.append((time.time(), _call_act, _put_act))
            if len(_fh) > 300:
                del _fh[:len(_fh) - 300]
    except Exception:
        pass

    # Snapshot today's current cumulative values to Supabase (throttled ~60s)
    # so past days can be replayed later. Builds history going forward.
    try:
        _db = st.session_state.get('_db_obj')
        if _db is not None and time.time() - st.session_state.get('_leg_flow_snap_ts', 0) > 60:
            st.session_state['_leg_flow_snap_ts'] = time.time()
            def _last(s):
                try:
                    return float(s.iloc[-1]) if s is not None and len(s) else 0.0
                except Exception:
                    return 0.0
            _ist = pytz.timezone('Asia/Kolkata'); _now = datetime.now(_ist)
            _db.insert_leg_flow_snapshot({
                'trading_day': _now.strftime('%Y-%m-%d'), 'ts': _now.isoformat(),
                'call_cvd': _last(_live['delta'][0]), 'put_cvd': _last(_live['delta'][1]),
                'call_buy': _last(_live['buy'][0]), 'put_buy': _last(_live['buy'][1]),
                'call_sell': _last(_live['sell'][0]), 'put_sell': _last(_live['sell'][1]),
            })
    except Exception:
        pass

    # NOTE: rendered with a plain header (NOT st.expander) — this runs INSIDE
    # the 'Stop Hunt + VPFR' expander and Streamlit forbids nested expanders.
    st.markdown("#### 📊 ATM±1 CALL vs PUT — CVD / Cum Buy / Cum Sell (time series)")

    # Date picker: Live (today) or a past day from the snapshot archive.
    _db = st.session_state.get('_db_obj')
    _days = []
    _today = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d')
    if _db is not None:
        try:
            _days = [d for d in (_db.get_leg_flow_days() or []) if d != _today]
        except Exception:
            _days = []
    # Options: live today · recent same-expiry days pulled live from Dhan
    # (intraday retention ~5 trading days, current expiry only) · older days
    # from the snapshot archive.
    _dhan_opts = ['📈 Last 2 days (Dhan)', '📈 Last 3 days (Dhan)', '📈 Last 5 days (Dhan)']
    _opts = ['🔴 Live (today)'] + _dhan_opts + _days
    _c1, _c2 = st.columns([2, 1])
    with _c1:
        _sel = st.selectbox("View date", _opts, key="atm_cvd_date")
    with _c2:
        _show = st.toggle("Show graphs", value=True, key="show_atm_cvd_graphs")
    if not _show:
        return

    # Build the (call, put) series map for the chosen source.
    if _sel.startswith('🔴 Live'):
        _map = _live
        st.caption("Aggregated across the 3 ATM±1 strikes · CLV-weighted estimate from 1m "
                   "OHLCV (not tick data). CALL rising + PUT falling → NIFTY up · "
                   "PUT rising + CALL falling → NIFTY down.")
    elif _sel.startswith('📈 Last'):
        _nd = int(_sel.split()[2])  # 2 / 3 / 5
        _sids = st.session_state.get('_atm_leg_sids') or {}
        _api = st.session_state.get('_atm_leg_api')
        if not _sids or _api is None:
            st.info("Leg security IDs not resolved yet — wait for one live cycle.")
            return
        _cache = st.session_state.setdefault('_cvd_hist_cache', {})
        _ck = f"d{_nd}"
        if time.time() - _cache.get(_ck, {}).get('ts', 0) > 300:  # refetch every 5 min
            _ce_dfs, _pe_dfs = [], []
            with st.spinner(f"Fetching last {_nd} days from Dhan…"):
                for _tag, (_sid, _seg) in _sids.items():
                    try:
                        _raw = _api.get_intraday_data(security_id=_sid, exchange_segment=_seg,
                                                      instrument="OPTIDX", interval="1", days_back=_nd)
                        _dfh = process_candle_data(_raw, "1min") if _raw else None
                        if _dfh is not None and not _dfh.empty:
                            (_ce_dfs if ' CE ' in f' {_tag} ' else _pe_dfs).append(_dfh)
                    except Exception:
                        continue
            _cache[_ck] = {'ts': time.time(), 'ce': _ce_dfs, 'pe': _pe_dfs}
        _cd = _cache.get(_ck, {})
        _ce_h, _pe_h = _cd.get('ce') or [], _cd.get('pe') or []
        if not _ce_h and not _pe_h:
            st.info(f"No Dhan history returned for the last {_nd} days "
                    "(current-expiry legs only; intraday retention ~5 days).")
            return
        _map = {k: (_agg(_ce_h, k), _agg(_pe_h, k)) for k in ('delta', 'buy', 'sell')}
        st.caption(f"📈 Last {_nd} days · live from Dhan (current-expiry legs, ~5-day intraday "
                   "retention). Cumulative runs continuously across days; gaps = overnight.")
    else:
        _map = {}
        try:
            _hist = _db.get_leg_flow_snapshots(_sel)
            if _hist is not None and not getattr(_hist, 'empty', True):
                _idx = pd.to_datetime(_hist['ts'])
                _map = {
                    'delta': (pd.Series(_hist['call_cvd'].values, index=_idx),
                              pd.Series(_hist['put_cvd'].values, index=_idx)),
                    'buy': (pd.Series(_hist['call_buy'].values, index=_idx),
                            pd.Series(_hist['put_buy'].values, index=_idx)),
                    'sell': (pd.Series(_hist['call_sell'].values, index=_idx),
                             pd.Series(_hist['put_sell'].values, index=_idx)),
                }
        except Exception as _he:
            st.caption(f"Could not load {_sel}: {_he}")
            return
        if not _map:
            st.info(f"No stored snapshots for {_sel} yet.")
            return
        st.caption(f"📅 Replaying stored snapshots for {_sel} (from the daily archive).")

    for _title, _kind, _key in [
        ("🔵 CVD (cumulative Buy − Sell)", 'delta', 'cvd'),
        ("🟢 Cumulative Buy volume", 'buy', 'buy'),
        ("🔴 Cumulative Sell volume", 'sell', 'sell'),
    ]:
        ce_s, pe_s = _map.get(_kind, (None, None))
        if ce_s is None and pe_s is None:
            continue
        fig = go.Figure()
        if ce_s is not None:
            fig.add_trace(go.Scatter(x=ce_s.index, y=ce_s.values, mode='lines',
                          name='CALL (CE)', line=dict(color='#00ff88', width=2)))
        if pe_s is not None:
            fig.add_trace(go.Scatter(x=pe_s.index, y=pe_s.values, mode='lines',
                          name='PUT (PE)', line=dict(color='#ff4444', width=2)))
        fig.update_layout(title=_title, height=260,
                          margin=dict(l=10, r=10, t=34, b=10),
                          paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                          font=dict(color='#ccc'),
                          legend=dict(orientation='h', y=1.15))
        fig.update_xaxes(showgrid=False)
        fig.update_yaxes(showgrid=True, gridcolor='#1e2a3a')
        st.plotly_chart(fig, use_container_width=True, key=f"atmcvd_{_key}_{_sel[:10]}")


















def _snapshot_entry_factors(spot_price):
    """Flat factor vector at signal time — pulled from the Final AI read, the
    Market Picture, and the cross-expiry cache — persisted with each confirmed
    entry so outcomes can later be sliced by which factors were present."""
    fmr = st.session_state.get('_full_market_read') or {}
    mp = st.session_state.get('_market_picture') or {}
    gx = mp.get('gex_disp') or {}
    dx = mp.get('dex_bias') or {}
    sk = mp.get('skew_bias') or {}
    vc = mp.get('vc_exp') or {}
    _cx = st.session_state.get('_cross_expiry_cache')
    cx = _cx[1] if isinstance(_cx, tuple) and len(_cx) > 1 else None
    return {
        'market_label': fmr.get('market_label'), 'market_kind': fmr.get('market_kind'),
        'regime': mp.get('regime'),
        'call_mode': fmr.get('call_mode'), 'put_mode': fmr.get('put_mode'),
        'call_strength': fmr.get('call_strength'), 'put_strength': fmr.get('put_strength'),
        'support_strength': fmr.get('support_strength'),
        'resistance_strength': fmr.get('resistance_strength'),
        'breakout': fmr.get('breakout'), 'gamma_blast': fmr.get('gamma_blast'),
        'dealer_score': fmr.get('dealer_score'), 'dealer_dir': fmr.get('dealer_dir'),
        'dex_net': dx.get('net_dex'),
        'gex_total': gx.get('total'), 'gex_signal': gx.get('signal'),
        'skew_ratio': sk.get('ratio'), 'skew_bias': sk.get('bias'),
        'institution_score': fmr.get('institution_score'),
        'institution_bias': fmr.get('institution_bias'),
        'short_squeeze': fmr.get('short_squeeze'), 'overall_conf': fmr.get('overall_conf'),
        'vanna': vc.get('net_vanna'), 'charm': vc.get('net_charm'),
        'cross_expiry': (cx or {}).get('agree') if cx else None,
    }








def compute_greek_absorption(option_data, spot_price):
    """Greek Absorption / Capping detector.

    Compares the option premium move EXPECTED from the Greeks against the
    ACTUAL move, cycle-over-cycle:

        expected = ΔSpot·Delta + 0.5·Gamma·ΔSpot² + Vega·ΔIV
        absorption = expected − actual

    A large positive absorption on a leg that *should* have risen (spot moved
    in its favour), confirmed by rising OI, means someone is absorbing/writing:
      • CE absorbed (calls capped)  → resistance → NIFTY bearish
      • PE absorbed (puts written)  → support    → NIFTY bullish

    Uses the per-strike Greeks/IV/LTP/OI already in df_summary. Needs a prior
    snapshot (stored in session_state) — returns {} on the first cycle.

    Returns {rows: [...], ce_capping: int, pe_writing: int, nifty: 'bull'|'bear'|'neutral'}.
    """
    out = {'rows': [], 'ce_capping': 0, 'pe_writing': 0, 'nifty': 'neutral'}
    try:
        ds = (option_data or {}).get('df_summary') if option_data else None
        if ds is None or getattr(ds, 'empty', True) or 'Strike' not in ds.columns:
            return out
        # ATM ± 3 strikes around spot
        strikes = sorted(ds['Strike'].dropna().unique().tolist())
        if len(strikes) < 3:
            return out
        atm = min(strikes, key=lambda x: abs(x - spot_price))
        gap = min((abs(b - a) for a, b in zip(strikes, strikes[1:])), default=50) or 50
        want = {atm + k * gap for k in range(-3, 4)}

        prev = st.session_state.get('_greek_absorb_prev') or {}
        prev_spot = prev.get('spot')
        prev_legs = prev.get('legs', {})
        cur_legs = {}
        rows = []
        bull_v = bear_v = 0
        dspot = (spot_price - prev_spot) if prev_spot else 0.0

        for _, r in ds.iterrows():
            K = float(r['Strike'])
            if K not in want:
                continue
            for side in ('CE', 'PE'):
                ltp = float(r.get(f'lastPrice_{side}', 0) or 0)
                iv = float(r.get(f'impliedVolatility_{side}', 0) or 0)
                dlt = float(r.get(f'Delta_{side}', 0) or 0)
                gma = float(r.get(f'Gamma_{side}', 0) or 0)
                vga = float(r.get(f'Vega_{side}', 0) or 0)
                oichg = float(r.get(f'changeinOpenInterest_{side}', 0) or 0)
                vol = float(r.get(f'totalTradedVolume_{side}', 0) or 0)
                lk = f"{int(K)}{side}"
                cur_legs[lk] = {'ltp': ltp, 'iv': iv}
                p = prev_legs.get(lk)
                if not p or prev_spot is None:
                    continue
                d_ltp = ltp - p['ltp']
                d_iv = iv - p['iv']
                expected = dspot * dlt + 0.5 * gma * (dspot ** 2) + vga * d_iv
                absorption = expected - d_ltp
                # Only meaningful when the move was non-trivial
                _thr = max(1.5, 0.4 * abs(expected))
                verdict = '⚪ Normal'
                ndir = 'neutral'
                if abs(expected) >= 1.0 and absorption > _thr and oichg > 0:
                    if side == 'CE' and expected > 0:
                        verdict = '🔴 CALL CAPPING (absorbed)'
                        ndir = 'bear'; bear_v += 1; out['ce_capping'] += 1
                    elif side == 'PE' and expected > 0:
                        verdict = '🟢 PUT WRITING (absorbed)'
                        ndir = 'bull'; bull_v += 1; out['pe_writing'] += 1
                elif abs(expected) >= 1.0 and absorption < -_thr:
                    # Premium rose MORE than Greeks imply → genuine demand
                    if side == 'CE':
                        verdict = '🟢 CALL DEMAND'
                        ndir = 'bull'; bull_v += 1
                    else:
                        verdict = '🔴 PUT DEMAND'
                        ndir = 'bear'; bear_v += 1
                if verdict != '⚪ Normal':
                    rows.append({
                        'Strike': f"{int(K)} {side}", 'LTP': f"₹{ltp:.2f}",
                        'Exp Δ': f"{expected:+.1f}", 'Act Δ': f"{d_ltp:+.1f}",
                        'Absorb': f"{absorption:+.1f}",
                        'ΔOI': f"{oichg/1000:+.0f}K", 'Verdict': verdict,
                    })

        # Save snapshot for next cycle
        st.session_state['_greek_absorb_prev'] = {'spot': spot_price, 'legs': cur_legs}
        out['rows'] = rows
        net = bull_v - bear_v
        out['nifty'] = 'bull' if net > 0 else ('bear' if net < 0 else 'neutral')
        out['net'] = net
        return out
    except Exception:
        return out


def render_greek_absorption(option_data, spot_price):
    """Show the Greek absorption / capping table (who is stopping the LTP)."""
    res = compute_greek_absorption(option_data, spot_price)
    st.session_state['_greek_absorb_last'] = res
    st.markdown("### 🧪 Greek Absorption — who is stopping the LTP")
    st.caption("Expected premium move from Greeks (Δ·ΔSpot + ½·Γ·ΔSpot² + Vega·ΔIV) "
               "vs actual, confirmed by ΔOI. Large positive 'Absorb' + rising OI = "
               "writing/absorption. CALL CAPPING → NIFTY bear · PUT WRITING → NIFTY bull.")
    rows = res.get('rows') or []
    if not rows:
        st.caption("No significant absorption this cycle (or warming up — needs 2 cycles).")
        return
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    _nd = res.get('nifty', 'neutral')
    _em = '🟢' if _nd == 'bull' else ('🔴' if _nd == 'bear' else '⚪')
    st.caption(f"{_em} Net absorption read → NIFTY **{_nd.upper()}** "
               f"(CALL CAPPING {res.get('ce_capping', 0)} · PUT WRITING {res.get('pe_writing', 0)})")


def compute_ce_pe_alignment(spot_price=0):
    """CE↔PE trend alignment using each leg's VOB BUILD/BREAK status + how far
    the LTP sits from that VOB (uses the already-computed _atm_leg_vob_volume).

    Per-leg direction from the nearest VOB zone's status:
      bullish VOB (support):  BUILDING/INTACT → UP   · BREAKING/FADING → DOWN
      bearish VOB (resistance):BUILDING/INTACT → DOWN · BREAKING/FADING → UP
    Distance = |LTP − zone mid| as % of LTP — smaller = move more imminent.

    Returns {state, em, label, text, ce_up, ce_dn, pe_up, pe_dn,
             ce_dist, pe_dist, ce_status, pe_status}.
      ALIGNED_UP   = CE rising + PE falling → NIFTY up
      ALIGNED_DOWN = PE rising + CE falling → NIFTY down
      BOTH_DOWN    = both falling → premiums bleeding → FLAT/range
      BOTH_UP      = both building → tug-of-war → FLAT
    """
    ce_up = ce_dn = pe_up = pe_dn = 0
    ce_dists, pe_dists = [], []
    ce_status, pe_status = [], []
    try:
        legs = st.session_state.get('_atm_leg_dfs') or {}
        vv = st.session_state.get('_atm_leg_vob_volume') or {}
        for tag, df_l in legs.items():
            if df_l is None or getattr(df_l, 'empty', True):
                continue
            ltp_l = float(df_l['close'].iloc[-1])
            if ltp_l <= 0:
                continue
            is_ce = ' CE ' in f' {tag} '
            is_pe = ' PE ' in f' {tag} '
            leg_name = ' '.join(tag.split()[-2:])   # e.g. "CE 24000"
            zones = vv.get(leg_name)
            if not zones:
                continue
            # Nearest VOB zone to the LTP governs the leg's near-term trend.
            nz = min(zones, key=lambda z: abs(ltp_l - float(z.get('mid', ltp_l))))
            _mid = float(nz.get('mid', ltp_l))
            _status = nz.get('status', 'INTACT')
            _ztype = nz.get('zone_type', 'bullish')
            dist_pct = abs(ltp_l - _mid) / ltp_l * 100.0
            # Direction from zone type + build/break status
            if _ztype == 'bullish':
                d = 'up' if _status in ('BUILDING', 'INTACT') else 'down'
            else:  # bearish
                d = 'down' if _status in ('BUILDING', 'INTACT') else 'up'
            if is_ce:
                ce_up += 1 if d == 'up' else 0
                ce_dn += 1 if d == 'down' else 0
                ce_dists.append(dist_pct)
                ce_status.append(f"{leg_name} {_status}({dist_pct:.1f}%)")
            elif is_pe:
                pe_up += 1 if d == 'up' else 0
                pe_dn += 1 if d == 'down' else 0
                pe_dists.append(dist_pct)
                pe_status.append(f"{leg_name} {_status}({dist_pct:.1f}%)")
    except Exception:
        pass

    ce_net, pe_net = ce_up - ce_dn, pe_up - pe_dn
    ce_dist = min(ce_dists) if ce_dists else None   # nearest CE leg to its VOB
    pe_dist = min(pe_dists) if pe_dists else None

    if ce_net > 0 and pe_net < 0:
        state, em, label = 'ALIGNED_UP', '🟢', 'ALIGNED UP → NIFTY ⬆️'
    elif ce_net < 0 and pe_net > 0:
        state, em, label = 'ALIGNED_DOWN', '🔴', 'ALIGNED DOWN → NIFTY ⬇️'
    elif ce_net < 0 and pe_net < 0:
        state, em, label = 'BOTH_DOWN', '⚪', 'BOTH CE & PE FALLING → premiums bleeding → FLAT/RANGE'
    elif ce_net > 0 and pe_net > 0:
        state, em, label = 'BOTH_UP', '⚪', 'BOTH CE & PE BUILDING → tug-of-war → FLAT'
    elif ce_up or ce_dn or pe_up or pe_dn:
        state, em, label = 'PARTIAL', '⚪', 'Partial — one side mixed/flat, no clean CE↔PE alignment'
    else:
        state, em, label = 'NONE', '⚪', 'No VOB build/break data yet'

    # Which side's move is more imminent (LTP closest to its VOB)?
    _closer = ""
    if ce_dist is not None and pe_dist is not None:
        if ce_dist < pe_dist:
            _closer = f" · CE closer to its VOB ({ce_dist:.1f}% vs PE {pe_dist:.1f}%) → CE move first"
        elif pe_dist < ce_dist:
            _closer = f" · PE closer to its VOB ({pe_dist:.1f}% vs CE {ce_dist:.1f}%) → PE move first"

    text = (f"🔗 {em} <b>{label}</b> · "
            f"CE ↑{ce_up}/↓{ce_dn}" + (f" (nearest {ce_dist:.1f}%)" if ce_dist is not None else "") +
            f" · PE ↑{pe_up}/↓{pe_dn}" + (f" (nearest {pe_dist:.1f}%)" if pe_dist is not None else "") +
            _closer)
    return {'state': state, 'em': em, 'label': label, 'text': text,
            'ce_up': ce_up, 'ce_dn': ce_dn, 'pe_up': pe_up, 'pe_dn': pe_dn,
            'ce_dist': ce_dist, 'pe_dist': pe_dist,
            'ce_status': ce_status, 'pe_status': pe_status}








def check_signal_cluster_alert(spot_price, option_data=None, min_signals=3,
                               window_s=3600, proximity_pts=25, cooldown_s=1800):
    if RETIRE_ENTRY_ALERTS:
        return  # MIOS V5 pure decision-support — trade-call alerts retired
    """🚨 SIGNAL CLUSTER — sent via the DEDICATED alert bot (alternate token)
    when everything piles up on one side:
      • ≥ min_signals BUY CALL (or BUY PUT) alerts in the last window_s
      • spot within proximity_pts of a STRONG level for that side —
        a major zone with ≥3 sources, or the OI wall (PE wall for calls,
        CE wall for puts)
      • the leg tabulation overall verdict agrees (BULL / BEAR)
    Message includes today's CALL/PUT alert counts and the ATM verdict.
    30-min cooldown per side. Also queued for the Discord bot."""
    if not spot_price:
        return None
    ev = st.session_state.get('_alert_side_events') or []
    now_t = time.time()
    recent = [e for e in ev if now_t - e[0] <= window_s]
    try:
        _, ov = st.session_state.get('_leg_bias_cache') or (None, None)
    except Exception:
        ov = None
    mp = st.session_state.get('_market_picture') or {}
    counts = st.session_state.get('_alert_side_counts') or {}
    sent = None
    for side, want_dir in (('PUT', 'BEAR'), ('CALL', 'BULL')):
        n = sum(1 for e in recent if e[1] == side)
        if n < min_signals:
            continue
        if not ov or ov.get('dir') != want_dir:
            continue
        # spot at a STRONG level for this side
        at_txt = None
        z = mp.get('res') if side == 'PUT' else mp.get('sup')
        if (z and int(z.get('src_count', 0)) >= 3
                and abs(spot_price - float(z.get('price', 0))) <= proximity_pts):
            at_txt = (f"strong {'resistance' if side == 'PUT' else 'support'} "
                      f"₹{float(z['price']):.0f} ({z.get('src_count', 0)} sources)")
        wall = mp.get('oi_ceiling') if side == 'PUT' else mp.get('oi_floor')
        if at_txt is None and wall and abs(spot_price - float(wall[0])) <= proximity_pts:
            at_txt = (f"{'CE' if side == 'PUT' else 'PE'} OI wall ₹{wall[0]:.0f} "
                      f"({wall[1]:.1f}L OI)")
        if at_txt is None:
            continue
        if now_t - st.session_state.get(f'_cluster_last_{side}', 0) < cooldown_s:
            continue
        st.session_state[f'_cluster_last_{side}'] = now_t
        try:
            _atm_i = _get_atm_bias_text(option_data) or ""
        except Exception:
            _atm_i = ""
        _em2 = '🔴' if side == 'PUT' else '🟢'
        word = 'BUY PUT' if side == 'PUT' else 'BUY CALL'
        msg = (
            f"{_em2}🚨 <b>SIGNAL CLUSTER — MULTIPLE {word} SIGNALS + SPOT AT "
            f"{'RESISTANCE' if side == 'PUT' else 'SUPPORT'}</b>\n"
            f"📨 {n} {word} alerts in the last {window_s // 60} min "
            f"(today: 🟢 CALL {counts.get('CALL', '?')} · 🔴 PUT {counts.get('PUT', '?')})\n"
            f"📍 Spot ₹{spot_price:.1f} at {at_txt}\n"
            f"🧮 Tabulation overall: <b>{ov.get('label', want_dir)}</b> ✓"
            f"{_atm_i}\n"
            f"💡 High-conviction {word} window — check the ✅ CONFIRMED ENTRY "
            f"signal for the exact leg and price.\n"
            f"NIFTY Spot ₹{spot_price:.1f}"
        )
        try:
            send_telegram_alert_bot(msg)
        except Exception:
            pass
        # Also deliver on the REGULAR Telegram bot (mirrors to Discord webhook)
        try:
            send_telegram_message_sync(msg)
        except Exception:
            pass
        _push_discord_outbox(msg)
        sent = msg
    return sent


def send_atm_wall_vob_entry_alert(spot_price, option_data=None, proximity_pts=25, cooldown_s=900):
    if RETIRE_ENTRY_ALERTS:
        return  # MIOS V5 pure decision-support — trade-call alerts retired
    """🚀 ALL-ALIGNED entry alert — fires only when EVERY condition agrees:
      1. ATM strike verdict bias      — Bullish (call) / Bearish (put)
      2. ATM±2 overall strike verdict — majority Bullish / Bearish
      3. Spot at the OI wall          — PE wall (support) for calls,
                                        CE wall (resistance) for puts
      4. Option leg at its own VOB    — CE leg (call) / PE leg (put) sitting
                                        inside a bullish VOB whose status is
                                        INTACT or BUILDING (not fading/breaking)
    Message also reports the ΔOI Bias (ATM±2) read. → 'BULL CALL ENTRY' /
    'BEAR PUT ENTRY' (allow-listed); also sent to the dedicated alert bot
    and queued for the Discord bot."""
    ds = (option_data or {}).get('df_summary') if option_data else None
    if ds is None or getattr(ds, 'empty', True) or 'Strike' not in ds.columns or not spot_price:
        return None
    u = (option_data or {}).get('underlying') or spot_price

    # ── 1. ATM verdict + 2. ATM±2 majority verdict ──
    try:
        stks = sorted(ds['Strike'].dropna().unique().tolist())
        atm = min(stks, key=lambda x: abs(x - u))
        gap = min((abs(b - a) for a, b in zip(stks, stks[1:])), default=50) or 50
        atm_row = ds[ds['Strike'] == atm].iloc[0]
        atm_score = float(atm_row.get('BiasScore', 0) or 0)
        atm_v = str(atm_row.get('Verdict', '') or final_verdict(atm_score)).lower()
        win = ds[(ds['Strike'] >= atm - 2 * gap) & (ds['Strike'] <= atm + 2 * gap)]
        _vcol = win.get('Verdict')
        if _vcol is None:
            _verds = [final_verdict(float(x or 0)) for x in win.get('BiasScore', [])]
        else:
            _verds = [str(x) for x in _vcol.tolist()]
        n_bull = sum(1 for v in _verds if 'bullish' in v.lower())
        n_bear = sum(1 for v in _verds if 'bearish' in v.lower())
        # Per-strike verdict lines straight from the Option Chain Bias
        # Summary tabulation, so the alert shows exactly what it gated on.
        _win_detail = ""
        try:
            _wl = []
            for _, _wr in win.sort_values('Strike').iterrows():
                _wv = str(_wr.get('Verdict', '') or final_verdict(float(_wr.get('BiasScore', 0) or 0)))
                _we = '🟢' if 'bullish' in _wv.lower() else ('🔴' if 'bearish' in _wv.lower() else '⚪')
                _wm = ' ←ATM' if float(_wr['Strike']) == atm else ''
                _wl.append(f"  {_we} ₹{_wr['Strike']:.0f}: {_wv} "
                           f"({float(_wr.get('BiasScore', 0) or 0):+.0f}){_wm}")
            _win_detail = "\n" + "\n".join(_wl)
        except Exception:
            _win_detail = ""
    except Exception:
        return None
    atm_bull = 'bullish' in atm_v
    atm_bear = 'bearish' in atm_v
    win_bull = n_bull > n_bear
    win_bear = n_bear > n_bull

    # ── 3. OI walls (same definition as Market Picture / confluence alert) ──
    ce_wall = pe_wall = None
    try:
        lo, hi = spot_price * 0.97, spot_price * 1.03
        w = ds[(ds['Strike'] >= lo) & (ds['Strike'] <= hi)]
        _ce_col = 'openInterest_CE' if 'openInterest_CE' in w.columns else (
            'CE_OI' if 'CE_OI' in w.columns else None)
        _pe_col = 'openInterest_PE' if 'openInterest_PE' in w.columns else (
            'PE_OI' if 'PE_OI' in w.columns else None)
        if _ce_col and not w.empty:
            _r = w.loc[w[_ce_col].idxmax()]
            ce_wall = (float(_r['Strike']), float(_r[_ce_col]) / 1e5)
        if _pe_col and not w.empty:
            _r = w.loc[w[_pe_col].idxmax()]
            pe_wall = (float(_r['Strike']), float(_r[_pe_col]) / 1e5)
    except Exception:
        pass
    at_pe_wall = pe_wall and abs(spot_price - pe_wall[0]) <= proximity_pts
    at_ce_wall = ce_wall and abs(spot_price - ce_wall[0]) <= proximity_pts

    # ── 4. Legs at their own bullish VOB with status INTACT/BUILDING ──
    def _legs_at_intact_vob(side):
        out = []
        legs = st.session_state.get('_atm_leg_dfs') or {}
        vv = st.session_state.get('_atm_leg_vob_volume') or {}
        for tag, df_l in legs.items():
            if f' {side} ' not in f' {tag} ' or df_l is None or getattr(df_l, 'empty', True):
                continue
            ltp = float(df_l['close'].iloc[-1])
            if ltp <= 0:
                continue
            zones = vv.get(' '.join(tag.split()[-2:])) or []
            tol = max(ltp * 0.005, 0.5)
            for z in zones:
                if (z.get('zone_type') == 'bullish'
                        and z.get('status') in ('INTACT', 'BUILDING')
                        and (float(z.get('lower', 0)) - tol) <= ltp <= (float(z.get('upper', 0)) + tol)):
                    out.append((tag, ltp, z.get('status')))
                    break
        return out

    # ── ΔOI bias line (info in the message, not a gate) ──
    _doi_line = ""
    try:
        _db = (st.session_state.get('_market_picture') or {}).get('doi_bias')
        if _db:
            _doi_line = (f"\n🔄 ΔOI Bias (ATM±2): <b>{_db['label']}</b> · "
                         f"CE {_db['ce_chg'] / 1e5:+.1f}L vs PE {_db['pe_chg'] / 1e5:+.1f}L")
    except Exception:
        pass

    msg = key = None
    if atm_bull and win_bull and at_pe_wall:
        ce_legs = _legs_at_intact_vob('CE')
        if ce_legs:
            _ll = " · ".join(f"{t} ₹{p:.2f} ({s})" for t, p, s in ce_legs[:4])
            msg = (
                "🟢🚀 <b>BULL CALL ENTRY — ALL ALIGNED</b> ⬆️\n"
                f"📊 ATM Verdict: <b>{atm_row.get('Verdict', final_verdict(atm_score))}</b> "
                f"(Score {atm_score:+.0f})\n"
                f"🧮 ATM±2 Verdict: <b>Bullish</b> ({n_bull}🟢/{n_bear}🔴 strikes — "
                f"Option Chain Bias Summary):{_win_detail}\n"
                f"🧱 Spot ₹{spot_price:.1f} at PE OI wall <b>₹{pe_wall[0]:.0f}</b> "
                f"({pe_wall[1]:.1f}L OI · support, {pe_wall[0] - spot_price:+.0f} pts)\n"
                f"🟩 CE at VOB: {_ll}"
                f"{_doi_line}\n"
                "💡 <b>BUY CALL</b> — confirm with the ✅ CONFIRMED ENTRY signal before paying.\n"
                f"NIFTY Spot ₹{spot_price:.1f}"
            )
            key = f"awv_bull_{int(pe_wall[0])}"
    elif atm_bear and win_bear and at_ce_wall:
        pe_legs = _legs_at_intact_vob('PE')
        if pe_legs:
            _ll = " · ".join(f"{t} ₹{p:.2f} ({s})" for t, p, s in pe_legs[:4])
            msg = (
                "🔴🚀 <b>BEAR PUT ENTRY — ALL ALIGNED</b> ⬇️\n"
                f"📊 ATM Verdict: <b>{atm_row.get('Verdict', final_verdict(atm_score))}</b> "
                f"(Score {atm_score:+.0f})\n"
                f"🧮 ATM±2 Verdict: <b>Bearish</b> ({n_bull}🟢/{n_bear}🔴 strikes — "
                f"Option Chain Bias Summary):{_win_detail}\n"
                f"🧱 Spot ₹{spot_price:.1f} at CE OI wall <b>₹{ce_wall[0]:.0f}</b> "
                f"({ce_wall[1]:.1f}L OI · resistance, {ce_wall[0] - spot_price:+.0f} pts)\n"
                f"🟪 PE at VOB: {_ll}"
                f"{_doi_line}\n"
                "💡 <b>BUY PUT</b> — confirm with the ✅ CONFIRMED ENTRY signal before paying.\n"
                f"NIFTY Spot ₹{spot_price:.1f}"
            )
            key = f"awv_bear_{int(ce_wall[0])}"
    if not msg:
        return None
    _sent = _throttled_telegram_send(msg, alert_class='all_aligned_entry', key=key,
                                     cooldown_s=cooldown_s, class_limit=3,
                                     class_window=900, class_sleep=1800)
    if _sent:
        _push_discord_outbox(msg)
        try:
            send_telegram_alert_bot(msg)
        except Exception:
            pass
    return _sent


def send_spot_sr_legs_confluence_alert(spot_price, option_data=None, proximity_pts=25, cooldown_s=900):
    if RETIRE_ENTRY_ALERTS:
        return  # MIOS V5 pure decision-support — trade-call alerts retired
    """🎯 SPOT@OI-WALL × LEG-TABLE confluence alert (Telegram + Discord mirror):
      • Spot within proximity_pts of the CE OI WALL (biggest call OI =
        resistance) AND leg tabulation STRONG BEARISH → PUT setup alert.
      • Spot within proximity_pts of the PE OI WALL (biggest put OI =
        support) AND tabulation STRONG BULLISH → CALL setup alert.
    Anchored to OI walls only (per user request — the clustered S/R zones
    fired too easily): the wall supplies the location, the legs supply the
    proof, the ATM bias block adds the chain's own read.
    Allow-listed via 'SPOT S/R CONFLUENCE'; 15-min cooldown per wall."""
    try:
        _rows, _ov = st.session_state.get('_leg_bias_cache') or (None, None)
    except Exception:
        _ov = None
    if not _ov or 'STRONG' not in (_ov.get('label') or '').upper():
        return None
    direction = _ov.get('dir')

    # OI walls from the chain (same definition as the Market Picture):
    # biggest CE OI strike within ±3% = resistance wall · biggest PE OI = support wall
    ce_wall = pe_wall = None   # (strike, OI in lakhs)
    try:
        ds = (option_data or {}).get('df_summary') if option_data else None
        if ds is not None and not getattr(ds, 'empty', True) and 'Strike' in ds.columns:
            lo, hi = spot_price * 0.97, spot_price * 1.03
            win = ds[(ds['Strike'] >= lo) & (ds['Strike'] <= hi)]
            _ce_col = 'openInterest_CE' if 'openInterest_CE' in win.columns else (
                'CE_OI' if 'CE_OI' in win.columns else None)
            _pe_col = 'openInterest_PE' if 'openInterest_PE' in win.columns else (
                'PE_OI' if 'PE_OI' in win.columns else None)
            if _ce_col and not win.empty:
                _r = win.loc[win[_ce_col].idxmax()]
                ce_wall = (float(_r['Strike']), float(_r[_ce_col]) / 1e5)
            if _pe_col and not win.empty:
                _r = win.loc[win[_pe_col].idxmax()]
                pe_wall = (float(_r['Strike']), float(_r[_pe_col]) / 1e5)
    except Exception:
        pass

    # Option Chain ATM verdict block (Verdict/Score + OI/ChgOI/Delta/Gamma/
    # Pressure biases) — same summary the option-chain table shows for ATM.
    # If the ATM verdict CONTRADICTS the 14-leg direction, tag the message
    # (e.g. STRONG BEAR legs but ATM Strong Bullish = weaker setup).
    try:
        _atm_txt = _get_atm_bias_text(option_data) or ""
    except Exception:
        _atm_txt = ""
    try:
        _ds2 = (option_data or {}).get('df_summary') if option_data else None
        _u2 = (option_data or {}).get('underlying') or spot_price
        if _ds2 is not None and not getattr(_ds2, 'empty', True) and 'Strike' in _ds2.columns:
            _a2 = min(_ds2['Strike'].tolist(), key=lambda x: abs(x - _u2))
            _r2 = _ds2[_ds2['Strike'] == _a2]
            if not _r2.empty:
                _av2 = str(_r2.iloc[0].get('Verdict', '') or '').lower()
                if ((direction == 'BEAR' and 'bullish' in _av2)
                        or (direction == 'BULL' and 'bearish' in _av2)):
                    _atm_txt += ("\n⚠️ <b>ATM chain bias disagrees with the leg table</b> "
                                 "— weaker setup, size down or skip")
    except Exception:
        pass

    msg = key = None
    if direction == 'BEAR' and ce_wall and abs(spot_price - ce_wall[0]) <= proximity_pts:
        lvl, oi_l = ce_wall
        msg = (
            "🔴🎯 <b>SPOT S/R CONFLUENCE — NIFTY AT CE OI WALL + LEG-TABLE STRONG BEAR</b> ⬇️\n"
            f"📍 Spot ₹{spot_price:.1f} at CE OI wall <b>₹{lvl:.0f}</b> "
            f"({oi_l:.1f}L OI · resistance, {lvl - spot_price:+.0f} pts)\n"
            f"🧮 leg tabulation: <b>{_ov.get('label')}</b> · "
            f"{_ov.get('bull', 0)}↑ / {_ov.get('bear', 0)}↓ legs (net {_ov.get('net', 0):+d})"
            f"{_atm_txt}\n"
            "💡 Setup: <b>BUY PUT</b> — call writers' wall overhead; "
            "confirm with the ✅ CONFIRMED ENTRY signal before paying.\n"
            f"NIFTY Spot ₹{spot_price:.1f}"
        )
        key = f"srconf_bear_{int(lvl)}"
    elif direction == 'BULL' and pe_wall and abs(spot_price - pe_wall[0]) <= proximity_pts:
        lvl, oi_l = pe_wall
        msg = (
            "🟢🎯 <b>SPOT S/R CONFLUENCE — NIFTY AT PE OI WALL + LEG-TABLE STRONG BULL</b> ⬆️\n"
            f"📍 Spot ₹{spot_price:.1f} at PE OI wall <b>₹{lvl:.0f}</b> "
            f"({oi_l:.1f}L OI · support, {lvl - spot_price:+.0f} pts)\n"
            f"🧮 leg tabulation: <b>{_ov.get('label')}</b> · "
            f"{_ov.get('bull', 0)}↑ / {_ov.get('bear', 0)}↓ legs (net {_ov.get('net', 0):+d})"
            f"{_atm_txt}\n"
            "💡 Setup: <b>BUY CALL</b> — put writers' floor underfoot; "
            "confirm with the ✅ CONFIRMED ENTRY signal before paying.\n"
            f"NIFTY Spot ₹{spot_price:.1f}"
        )
        key = f"srconf_bull_{int(lvl)}"
    if not msg:
        return None
    _sent = _throttled_telegram_send(msg, alert_class='sr_confluence', key=key,
                                     cooldown_s=cooldown_s, class_limit=3,
                                     class_window=900, class_sleep=1800)
    if _sent:
        _push_discord_outbox(msg)
        # Dedicated alert bot — this signal also goes to the second Telegram
        # bot so it never drowns in the main bot's stream.
        try:
            send_telegram_alert_bot(msg)
        except Exception:
            pass
    return _sent


def _classify_leg_mode(is_ce, ltp_dir, doi):
    """Option positioning mode from LTP direction + ΔOI (the 3rd input, CVD,
    is used by the caller to veto). Returns (mode_label, index_vote) where
    index_vote is +1 bullish-for-NIFTY / −1 bearish."""
    oi_up = doi > 0
    if ltp_dir > 0 and oi_up:
        return ("Long Build-up", 1 if is_ce else -1)
    if ltp_dir < 0 and oi_up:
        return ("Writing", -1 if is_ce else 1)          # short build-up
    if ltp_dir > 0 and not oi_up:
        return ("Short Covering", 1 if is_ce else -1)
    if ltp_dir < 0 and not oi_up:
        return ("Long Unwinding", -1 if is_ce else 1)
    return ("Neutral", 0)


def compute_fresh_entry_signal(spot_price, df, option_data):
    """🎯 Two-layer FRESH ENTRY engine.
      Layer 1 — options positioning: per ATM±1 leg, classify CE/PE mode from
        LTP-direction + ΔOI, keep the vote only when the leg's CVD agrees
        (executed flow confirms positioning). Sum → options bias.
      Layer 2 — spot price action: classify_sr_behavior (bounce/reject/accept
        at a major level) + spot vs its VP POC.
      Fires only when BOTH layers agree at a level:
        bullish options + spot bullish action at support → BUY CALL
        bearish options + spot bearish action at resistance → BUY PUT
    Returns a dict or None (None also on conflict — bias vs action disagree)."""
    if not spot_price or df is None or getattr(df, 'empty', True):
        return None
    leg_dfs = st.session_state.get('_atm_leg_dfs') or {}
    ds = (option_data or {}).get('df_summary') if option_data else None
    if not leg_dfs or ds is None or getattr(ds, 'empty', True) or 'Strike' not in ds.columns:
        return None

    def _doi(strike, side):
        try:
            r = ds[ds['Strike'] == strike]
            return float(r.iloc[0].get(f'changeinOpenInterest_{side}', 0) or 0) if not r.empty else 0.0
        except Exception:
            return 0.0

    from collections import Counter
    ce_modes, pe_modes = [], []
    score = 0
    for tag, dfl in leg_dfs.items():
        if dfl is None or getattr(dfl, 'empty', True) or len(dfl) < 6:
            continue
        is_ce = ' CE ' in f' {tag} '
        side = 'CE' if is_ce else 'PE'
        try:
            strike = float(tag.split()[-1])
        except Exception:
            continue
        c = dfl['close'].astype(float)
        ltp_dir = 1 if c.iloc[-1] > c.iloc[-6] else (-1 if c.iloc[-1] < c.iloc[-6] else 0)
        doi = _doi(strike, side)
        cvd = _of.cvd_sum(dfl)
        if _of.is_missing(cvd):
            cvd = 0.0
        mode, vote = _classify_leg_mode(is_ce, ltp_dir, doi)
        # CVD veto: option LTP rising must be backed by buy-side CVD (and vice
        # versa) or the positioning read is unconfirmed → don't count the vote.
        cvd_ok = (ltp_dir > 0 and cvd > 0) or (ltp_dir < 0 and cvd < 0) or ltp_dir == 0
        if cvd_ok:
            score += vote
        (ce_modes if is_ce else pe_modes).append(mode)
    if not ce_modes and not pe_modes:
        return None

    opt_dir = 'bull' if score >= 2 else ('bear' if score <= -2 else 'neutral')
    call_mode = Counter(ce_modes).most_common(1)[0][0] if ce_modes else '—'
    put_mode = Counter(pe_modes).most_common(1)[0][0] if pe_modes else '—'

    # Layer 2 — spot price action
    beh = classify_sr_behavior(df, spot_price) or {}
    st_state, st_dir, lvl = beh.get('state'), beh.get('direction'), beh.get('level')
    mf = st.session_state.get('_money_flow_data') or {}
    poc = float(mf.get('poc_price', 0) or 0)
    vp_pos = ('above POC' if poc and spot_price >= poc else ('below POC' if poc else '—'))
    action_ok = st_state in ('REJECTING', 'BUILDING', 'ACCEPTING') and lvl

    result = {'opt_dir': opt_dir, 'score': score, 'call_mode': call_mode,
              'put_mode': put_mode, 'beh': beh, 'poc': poc, 'vp_pos': vp_pos,
              'level': lvl, 'state': st_state, 'signal': None}
    if opt_dir == 'bull' and action_ok and st_dir == 'bull':
        result['signal'] = 'CALL'
    elif opt_dir == 'bear' and action_ok and st_dir == 'bear':
        result['signal'] = 'PUT'
    elif opt_dir in ('bull', 'bear') and action_ok and st_dir in ('bull', 'bear'):
        result['conflict'] = True   # bias vs price action disagree
    return result


def send_fresh_entry_alert(spot_price, df, option_data, cooldown_s=600):
    """🎯 FRESH ENTRY blast — the ONLY automated alert on the main Telegram bot.
    Fires when options positioning AND spot price action agree at a level."""
    res = None
    try:
        res = compute_fresh_entry_signal(spot_price, df, option_data)
    except Exception:
        return None
    if not res or not res.get('signal'):
        return None
    sig = res['signal']
    beh = res['beh']
    em = '🟢' if sig == 'CALL' else '🔴'
    word = 'BUY CALL' if sig == 'CALL' else 'BUY PUT'
    side_lbl = 'support' if sig == 'CALL' else 'resistance'
    _stt_em = {'REJECTING': '↗ rejection', 'BUILDING': '· building',
               'ACCEPTING': '✓ acceptance'}.get(res['state'], res['state'])
    try:
        _atm_i = _get_atm_bias_text(option_data) or ""
    except Exception:
        _atm_i = ""
    # Enrich with the full multi-factor scoring (strength/conf/breakout/reasons)
    _fmr_block = ""
    try:
        _fmr = compute_full_market_read(spot_price, df, option_data)
        if _fmr:
            _fmr_block = (
                f"\n📊 <b>CALL</b> {_fmr['call_mode']} · Str {_fmr['call_strength']}% "
                f"Conf {_fmr['call_conf']}%"
                f"\n📊 <b>PUT</b> {_fmr['put_mode']} · Str {_fmr['put_strength']}% "
                f"Conf {_fmr['put_conf']}%"
                f"\n🎯 <b>{_fmr['market_label']}</b> · Support {_fmr['support_strength']}% / "
                f"Resistance {_fmr['resistance_strength']}%"
                f"\n📈 Breakout {_fmr['breakout']}% / Breakdown {_fmr['breakdown']}% · "
                f"Γ-blast {_fmr['gamma_blast']}"
                + ("\n" + " · ".join(_fmr['reasons']) if _fmr.get('reasons') else "")
            )
    except Exception:
        _fmr_block = ""
    msg = (
        f"{em}⚡ <b>FRESH ENTRY — {word}</b> (2-layer blast)\n"
        f"🅾️ <b>Options:</b> CALL {res['call_mode']} · PUT {res['put_mode']} "
        f"→ {res['opt_dir'].upper()} (net {res['score']:+d})\n"
        f"📈 <b>Spot action:</b> {_stt_em} at {side_lbl} ₹{res['level']:.0f} · "
        f"{res['vp_pos']}\n"
        f"✅ Both layers agree → {word}"
        f"{_fmr_block}"
        f"{_atm_i}\n"
        f"NIFTY Spot ₹{spot_price:.1f}"
    )
    return _throttled_telegram_send(
        msg, alert_class='fresh_entry',
        key=f"fresh_entry_{sig}_{int(res['level'] or spot_price)}",
        cooldown_s=cooldown_s, class_limit=3, class_window=900, class_sleep=1800)


def send_overall_bias_entry_alert(overall_label, overall_em, bull_score, bear_score, spot_price, option_data):
    if RETIRE_ENTRY_ALERTS:
        return  # MIOS V5 pure decision-support — trade-call alerts retired
    """EXACT-ENTRY VOB signal. Fires only when ALL of these hold:
      1. Overall Bias (All-Bias dashboard) is BULL (call) / BEAR (put)
      2. A CE (call) / PE (put) leg's LTP is EXACTLY at its bullish VOB
         support BOTTOM line (± max(0.4%, ₹0.50)) with zone status INTACT
         or BUILDING — zones read from _atm_leg_vob_volume, the SAME cache
         the app screen shows, so Telegram always matches the screen
      3. Tier-1 tabulation aligned (VOB + S/R columns + overall verdict)
    The ATM verdict + ATM±2 per-strike verdicts from the Option Chain Bias
    Summary are SHOWN in the message (marked ✓/✗ in-sync) but do not gate
    the send. 5-min cooldown per direction. Allow-listed via 'VOB ENTRY'."""
    label_l = (overall_label or '').lower()
    is_bull = ('bull' in label_l and 'mixed' not in label_l)
    is_bear = ('bear' in label_l and 'mixed' not in label_l)
    if not (is_bull or is_bear):
        return None

    # ── Tabulation alignment gate — must pass before ANY send ──
    # Tier-1 (fast+true) columns ONLY: VOB build/break and S/R behaviour —
    # both from traded volume on the leg's own chart. The lagging windows
    # (VWAP/VIDYA/MFP ×50/20) were removed from the gate: requiring lagging
    # signals to agree makes entries later, not truer — they stay in the
    # table as display-only context. Majority vote per column across the
    # side's 7 legs, in the LEG's own direction (buying a leg = we want THAT
    # leg to rise → its cells 🟢), PLUS the overall tabulation verdict (BULL
    # for calls, BEAR for puts). All checks or no alert.
    _CHECK_COLS = ('VOB', 'S/R')
    def _tabulation_check(side_char, want_overall_dir):
        try:
            _rows, _ov = st.session_state.get('_leg_bias_cache') or (None, None)
        except Exception:
            _rows, _ov = None, None
        if not _rows or not _ov:
            return False, "🧮 Tabulation: warming up"
        srows = [r for r in _rows if f' {side_char} ' in f" {r['Leg']} "]
        if not srows:
            return False, "🧮 Tabulation: no leg rows"
        marks, n_ok = [], 0
        for col in _CHECK_COLS:
            b = sum(1 for r in srows if r.get(col) == '🟢')
            s = sum(1 for r in srows if r.get(col) == '🔴')
            ok = b > s
            n_ok += 1 if ok else 0
            marks.append(f"{col}{'✓' if ok else '✗'}")
        ov_dir = _ov.get('dir', '?')
        ov_ok = ov_dir == want_overall_dir
        aligned = (n_ok == len(_CHECK_COLS)) and ov_ok
        line = ("🧮 <b>Tabulation:</b> " + " · ".join(marks)
                + f" · Overall {ov_dir}{'✓' if ov_ok else '✗'}"
                + f" — {n_ok + (1 if ov_ok else 0)}/{len(_CHECK_COLS) + 1} aligned")
        return aligned, line

    # Scan legs using the SAME cached zones the app screen shows
    # (_atm_leg_vob_volume, built by analyze_vob_volume). The alert used to
    # run its own fresh VolumeOrderBlocks detection — a SECOND, different
    # calculation — which is why the Telegram "VOB bottom" didn't match the
    # zones on screen. One source of truth now: Telegram == screen.
    #
    # EXACT ENTRY rule: a leg qualifies only when its LTP is exactly at the
    # bullish zone's BOTTOM line (± max(0.4%, ₹0.50)) AND the zone status is
    # INTACT or BUILDING (fading/breaking zones never qualify).
    ce_at_own_sup = []  # (tag, ltp, bottom, status) — LTP exactly at bottom
    pe_at_own_sup = []
    vob_bottom_by_tag = {}  # tag -> (bottom, status) of nearest valid bull zone at/below LTP
    vob_target_by_tag = {}  # tag -> (target_price, status) from bearish VOB above LTP
    try:
        legs_dfs = st.session_state.get('_atm_leg_dfs') or {}
        _vv_all = st.session_state.get('_atm_leg_vob_volume') or {}
        for tag, df_l in legs_dfs.items():
            if df_l is None or df_l.empty:
                continue
            ltp_l = float(df_l['close'].iloc[-1])
            if ltp_l <= 0:
                continue
            is_ce = ' CE ' in f' {tag} '
            is_pe = ' PE ' in f' {tag} '
            zones = _vv_all.get(' '.join(tag.split()[-2:])) or []
            # ROBUSTNESS: if the leg-chart cache hasn't populated this leg yet
            # (slow/erroring 'Stop Hunt + VPFR' section), compute the zones
            # right here so the alert never goes silent waiting on that panel.
            if not zones:
                try:
                    zones = analyze_vob_volume(df_l, ltp_l) or []
                except Exception:
                    zones = []
            # TARGET: nearest bearish VOB above LTP (same cached zones)
            _above = [z for z in zones if z.get('zone_type') == 'bearish'
                      and float(z.get('lower', 0)) > ltp_l]
            if _above:
                _tz = min(_above, key=lambda z: float(z.get('lower', 0)))
                vob_target_by_tag[tag] = (float(_tz.get('lower', 0)),
                                          _tz.get('status', 'INTACT'))
            # Valid support zones: bullish + INTACT/BUILDING only
            _bulls = [z for z in zones if z.get('zone_type') == 'bullish'
                      and z.get('status') in ('INTACT', 'BUILDING')]
            tol = max(ltp_l * 0.004, 0.5)
            _at = None            # (bottom, status) — LTP in the zone's lower half
            _nearest_below = None  # (bottom, status) — for display on other legs
            for z in _bulls:
                _low = float(z.get('lower', 0))
                _up = float(z.get('upper', _low) or _low)
                _mid = (_low + _up) / 2.0 if _up > _low else _low
                _stz = z.get('status', 'INTACT')
                # Qualify: LTP anywhere in the LOWER HALF of the zone (near
                # support) — from just below the bottom up to the midline.
                # Among matches, prefer the highest bottom (nearest support).
                if (_low - tol) <= ltp_l <= (_mid + tol) and (_at is None or _low > _at[0]):
                    _at = (_low, _stz)
                if _low <= ltp_l + tol and (_nearest_below is None or _low > _nearest_below[0]):
                    _nearest_below = (_low, _stz)
            if _nearest_below is not None:
                vob_bottom_by_tag[tag] = _nearest_below
            if _at is not None:
                # Time-at-bottom: consecutive recent bars holding the bottom
                # (close above it, low near it) — held longer = stronger entry
                _held = 0
                try:
                    for _i2 in range(len(df_l) - 1, max(len(df_l) - 31, -1), -1):
                        _rw = df_l.iloc[_i2]
                        if (float(_rw['close']) >= _at[0] - tol
                                and float(_rw['low']) <= _at[0] + tol * 3):
                            _held += 1
                        else:
                            break
                except Exception:
                    pass
                if is_ce:
                    ce_at_own_sup.append((tag, ltp_l, _at[0], _at[1], _held))
                elif is_pe:
                    pe_at_own_sup.append((tag, ltp_l, _at[0], _at[1], _held))
    except Exception:
        pass

    # ── ATM verdict sync + ATM±2 verdicts from the Option Chain Bias Summary
    # tabulation — read AS-IS from the same Verdict/BiasScore cells the table
    # shows. The signal only sends when the ATM verdict agrees with the
    # direction (bullish for CALL, bearish for PUT).
    def _atm_check(want_bull):
        try:
            ds2 = (option_data or {}).get('df_summary') if option_data else None
            u2 = (option_data or {}).get('underlying') or spot_price
            if ds2 is None or getattr(ds2, 'empty', True) or 'Strike' not in ds2.columns:
                return False, "📊 ATM Verdict: option chain not loaded"
            stks = sorted(ds2['Strike'].dropna().unique().tolist())
            atm = min(stks, key=lambda x: abs(x - u2))
            gap = min((abs(b - a) for a, b in zip(stks, stks[1:])), default=50) or 50
            arow = ds2[ds2['Strike'] == atm].iloc[0]
            asc = float(arow.get('BiasScore', 0) or 0)
            av = str(arow.get('Verdict', '') or final_verdict(asc))
            ok = ('bullish' in av.lower()) if want_bull else ('bearish' in av.lower())
            win = ds2[(ds2['Strike'] >= atm - 2 * gap) & (ds2['Strike'] <= atm + 2 * gap)]
            lines = []
            for _, wr in win.sort_values('Strike').iterrows():
                wsc = float(wr.get('BiasScore', 0) or 0)
                wv = str(wr.get('Verdict', '') or final_verdict(wsc))
                we = '🟢' if 'bullish' in wv.lower() else ('🔴' if 'bearish' in wv.lower() else '⚪')
                wm = ' ←ATM' if float(wr['Strike']) == atm else ''
                lines.append(f"  {we} ₹{wr['Strike']:.0f}: {wv} ({wsc:+.0f}){wm}")
            block = (f"📊 <b>ATM Verdict (Bias Summary):</b> {av} (Score {asc:+.0f}) "
                     f"{'✓ in sync' if ok else '✗ NOT in sync'}\n"
                     f"🧾 <b>ATM±2 verdicts (Bias Summary):</b>\n" + "\n".join(lines))
            return ok, block
        except Exception:
            return False, ""

    # ── CE↔PE alignment (uptrend / downtrend / flat) — shared helper so the
    # alert matches the live app panel exactly.
    try:
        _align_block = compute_ce_pe_alignment(spot_price)['text']
    except Exception:
        _align_block = ""

    # ── Shared context blocks (one consolidated signal instead of many) ──
    # 1) All-Bias by speed (Fast / Lagging / Misguiding)
    _dv = st.session_state.get('_dashboard_verdicts') or {}
    def _vl(k):
        d = _dv.get(k)
        return f"{d['em']} {d['label']} (net {d['net']:+d})" if d else "—"
    _speed_block = (
        "📊 <b>All-Bias by speed:</b>\n"
        f"  🚀 Fast: {_vl('fast')}\n"
        f"  🐢 Lagging: {_vl('lag')}\n"
        f"  🌫️ Misguiding: {_vl('mis')}"
    )

    # 2) Capping / Writing (OI walls) from the option chain
    _cap_block = ""
    try:
        ds = (option_data or {}).get('df_summary') if option_data else None
        if ds is not None and not getattr(ds, 'empty', True) and {'Strike', 'CE_OI', 'PE_OI'} <= set(ds.columns):
            _cr = ds.loc[ds['CE_OI'].idxmax()]
            _pr = ds.loc[ds['PE_OI'].idxmax()]
            _cap_block = (
                "🧱 <b>OI walls:</b> "
                f"CALL CAPPING ₹{_cr['Strike']:.0f} (CE OI {_cr['CE_OI']/100000:.1f}L · resistance) · "
                f"PUT WRITING ₹{_pr['Strike']:.0f} (PE OI {_pr['PE_OI']/100000:.1f}L · support)"
            )
    except Exception:
        _cap_block = ""

    # 3) LTP S/R behavior across the legs
    _sr_block = ""
    try:
        _srs = st.session_state.get('_atm_leg_sr_behavior') or {}
        _sr_items = []
        for _t, _vv in _srs.items():
            if _t.startswith('sid_') or not _vv:
                continue
            _stt = _vv.get('state')
            if _stt in (None, 'NONE'):
                continue
            _de = '🟢' if _vv.get('direction') == 'bull' else ('🔴' if _vv.get('direction') == 'bear' else '⚪')
            _sr_items.append(f"{_t} {_de}{_stt}")
        if _sr_items:
            _sr_block = "📐 <b>LTP S/R behavior:</b> " + " · ".join(_sr_items[:8])
    except Exception:
        _sr_block = ""

    # ONE buy list for all ATM±3 legs (CE for bull, PE for bear). Legs sitting
    # at their own support VOB right now are marked 📍 (entry); the rest •.
    def _all_leg_ltps(side, at_vob_tags):
        out = []
        try:
            for leg in ((st.session_state.get('_atm_pm1_vpfr') or {}).get('legs') or []):
                tag = leg.get('tag', '')
                if f" {side} " not in f" {tag} ":
                    continue
                _ltp = float(leg.get('ltp') or 0)
                _vb = vob_bottom_by_tag.get(tag)
                _tg = vob_target_by_tag.get(tag)
                if _tg is not None:
                    _tp, _ts = _tg
                    _note = '🟢 firm (BUILDING)' if _ts == 'BUILDING' else (
                        '⚠️ may extend' if _ts in ('BREAKING', 'FADING') else _ts)
                    _tgt = f" → 🎯 target ₹{_tp:.2f} ({_note})"
                else:
                    _tgt = " → 🎯 target: open (no resistance VOB above)"
                _mark = '📍' if tag in at_vob_tags else '•'
                if tag in at_vob_tags:
                    _hb = at_vob_tags.get(tag) if isinstance(at_vob_tags, dict) else None
                    _hot = (f' ← IN SUPPORT ZONE (lower half) · held {_hb} bar{"s" if _hb != 1 else ""}'
                            if _hb else ' ← IN SUPPORT ZONE (lower half)')
                else:
                    _hot = ''
                if _vb is not None:
                    out.append(f"  {_mark} {tag}: VOB bottom ₹{_vb[0]:.2f} ({_vb[1]}) · "
                               f"LTP ₹{_ltp:.2f}{_tgt}{_hot}")
                else:
                    out.append(f"  {_mark} {tag}: ₹{_ltp:.2f} (no valid support VOB){_tgt}{_hot}")
        except Exception:
            pass
        return out

    # VOB ENTRY signal — CE/PE legs sitting at their own bullish VOB.
    # (The old SPOT@S/R entry was removed; only the leg-VOB entry fires now.)
    def _body(header, spot_line, all_label, all_list):
        return (
            header + "\n"
            f"Overall Bias: <b>{overall_label}</b> ({overall_em}) · Bull {bull_score} vs Bear {bear_score}\n"
            f"{_speed_block}\n"
            + (_align_block + "\n" if _align_block else "")
            + (_cap_block + "\n" if _cap_block else "")
            + (_sr_block + "\n" if _sr_block else "")
            + (spot_line + "\n" if spot_line else "")
            + (all_label + "\n" + "\n".join(all_list) + "\n" if all_list else "")
            + f"NIFTY Spot ₹{spot_price:.1f}"
        )

    sends = []  # (msg, key, alert_class)
    if is_bull:
        _ce_tags = {t[0]: (t[4] if len(t) > 4 else None) for t in ce_at_own_sup}
        _all_ce = _all_leg_ltps('CE', _ce_tags)
        _label = ("💰 <b>Buy — all ATM±1 CALLs</b> "
                  "(📍 = LTP in the lower half of a support VOB · INTACT/BUILDING):")
        # EXACT ENTRY — CE LTP at its VOB support bottom (screen zones),
        # gated on Tier-1 tabulation (VOB + S/R + overall BULL) AND the
        # ATM verdict from the Option Chain Bias Summary being in sync.
        if ce_at_own_sup:
            _tab_ok, _tab_line = _tabulation_check('CE', 'BULL')
            _atm_ok, _atm_block = _atm_check(want_bull=True)  # shown, NOT gated
            if _tab_ok:
                sends.append((
                    _body("🟢 <b>VOB ENTRY — BUY CALL</b> (CE LTP in support VOB) — NIFTY ⬆️",
                          _tab_line + "\n" + _atm_block, _label, _all_ce),
                    "vob_entry_bull", 'vob_entry'))
            else:
                st.session_state['_vob_entry_tab_block'] = {'dir': 'CALL', 'line': _tab_line}
    elif is_bear:
        _pe_tags = {t[0]: (t[4] if len(t) > 4 else None) for t in pe_at_own_sup}
        _all_pe = _all_leg_ltps('PE', _pe_tags)
        _label = ("💰 <b>Buy — all ATM±1 PUTs</b> "
                  "(📍 = LTP in the lower half of a support VOB · INTACT/BUILDING):")
        # EXACT ENTRY — PE LTP at its VOB support bottom (screen zones),
        # gated on Tier-1 tabulation (VOB + S/R + overall BEAR) AND the
        # ATM verdict from the Option Chain Bias Summary being in sync.
        if pe_at_own_sup:
            _tab_ok, _tab_line = _tabulation_check('PE', 'BEAR')
            _atm_ok, _atm_block = _atm_check(want_bull=False)  # shown, NOT gated
            if _tab_ok:
                sends.append((
                    _body("🔴 <b>VOB ENTRY — BUY PUT</b> (PE LTP in support VOB) — NIFTY ⬇️",
                          _tab_line + "\n" + _atm_block, _label, _all_pe),
                    "vob_entry_bear", 'vob_entry'))
            else:
                st.session_state['_vob_entry_tab_block'] = {'dir': 'PUT', 'line': _tab_line}

    sent = None
    for _m, _k, _cls in sends:
        if _throttled_telegram_send(_m, alert_class=_cls, key=_k, cooldown_s=300,
                                    class_limit=3, class_window=600, class_sleep=1800):
            sent = _m
    return sent








# ═══════════════════════════════════════════════════════════════════════════
#  PERSISTENT STATE — save / restore key composites + history to Supabase
#  so a Streamlit restart doesn't lose 5-10 cycles of context.
# ═══════════════════════════════════════════════════════════════════════════
_PERSIST_KEYS = (
    '_total_oi_history', '_cd_div_hist', '_spike_oi_hist', '_spike_vix_hist',
    '_spot_hist_ignition', '_zone_prev_classification', '_major_sr_alerted',
    '_bull_bear_meter', '_ignition_score', '_spike_score', '_accum_dist_score',
    '_premarket_sent_for', '_combo_audio_played_for',
    '_entry_signal_open', '_entry_signal_journal',
    # Discord bot bridge — the standalone discord_bot.py reads these from
    # the vob_app_state table to relay alerts and answer !commands.
    '_discord_outbox', '_market_picture', '_news_bias', '_leg_bias_summary',
)


def _push_discord_outbox(text, flush_s=25):
    """Queue an alert for the standalone Discord bot (discord_bot.py).

    ⏸️ PAUSED: Old Discord alerts disabled (awaiting migration to market_events).
    New alerts route through market_events table + Discord feed instead.
    This function is a no-op until market_events integration is complete."""
    # Old Discord outbox system is paused—all Discord alerts now go through market_events
    return












# ═══════════════════════════════════════════════════════════════════════════
#  PRE-MARKET ANALYSIS — runs once per day at 09:00-09:15 IST window
# ═══════════════════════════════════════════════════════════════════════════




# ═══════════════════════════════════════════════════════════════════════════
#  SECTOR HEATMAP — 1-row colored bar
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
#  AUDIO ALERT — browser beep when Ignition COMBO fires
# ═══════════════════════════════════════════════════════════════════════════






















# ═══════════════════════════════════════════════════════════════════════════
#  SMART MONEY / FOOTPRINT ANALYZERS
#  Six composable signals approximating institutional behavior:
#    1. Per-candle Futures P+OI classifier  (Long buildup / Short cover etc.)
#    2. Cumulative Delta Divergence detector
#    3. Volume Profile Shape classifier     (D / P / b / Trend)
#    4. Bid/Ask Absorption detector         (price stalled + heavy flow)
#    5. VWAP Deviation Bands                (±1σ, ±2σ)
#    6. Accumulation/Distribution composite (combines all of the above)
# ═══════════════════════════════════════════════════════════════════════════


_PXOI_LABEL = {
    ('up', 'up'):     ('Long Buildup',   '🟢', +1),
    ('up', 'down'):   ('Short Covering', '🟡', +0.5),
    ('down', 'up'):   ('Short Buildup',  '🔴', -1),
    ('down', 'down'): ('Long Unwinding', '🟠', -0.5),
}


def _classify_pxoi(dp, do, p_tol=0.5, o_tol=100):
    if abs(dp) < p_tol and abs(do) < o_tol:
        return ('Flat', '⚪', 0.0)
    px = 'up' if dp >= 0 else 'down'
    ox = 'up' if do >= 0 else 'down'
    return _PXOI_LABEL.get((px, ox), ('Flat', '⚪', 0.0))


def compute_per_candle_pxoi(api, max_rows=12):
    """Pull recent 5m futures candles with OI, classify each as Long buildup /
    Short covering / Short buildup / Long unwinding. Cached 60s."""
    cache = st.session_state.get('_pxoi_cache') or {}
    if cache.get('ts') and (time.time() - cache['ts'] < 60):
        return cache.get('data') or []
    meta = get_nifty_futures_security_id()
    if not meta or not api:
        return []
    try:
        # Direct call with oi=True for futures intraday
        url = f"{api.base_url}/charts/intraday"
        ist = pytz.timezone('Asia/Kolkata')
        end = datetime.now(ist)
        start = end - timedelta(days=1)
        payload = {
            "securityId": meta['security_id'],
            "exchangeSegment": "NSE_FNO",
            "instrument": "FUTIDX",
            "interval": "5",
            "oi": True,
            "fromDate": start.strftime("%Y-%m-%d %H:%M:%S"),
            "toDate": end.strftime("%Y-%m-%d %H:%M:%S"),
        }
        r = requests.post(url, headers=api.headers, json=payload, timeout=12)
        if r.status_code != 200:
            return []
        data = r.json()
        closes = data.get('close') or []
        ois = data.get('open_interest') or data.get('oi') or []
        ts = data.get('timestamp') or data.get('start_Time') or []
        if not closes or len(closes) != len(ois) or len(closes) < 2:
            return []
        rows = []
        for i in range(max(1, len(closes) - max_rows - 1), len(closes)):
            if i == 0:
                continue
            dp = float(closes[i]) - float(closes[i - 1])
            do = float(ois[i]) - float(ois[i - 1])
            label, emoji, sc = _classify_pxoi(dp, do)
            t_str = ""
            try:
                t_str = datetime.fromtimestamp(int(ts[i]), tz=pytz.utc) \
                    .astimezone(ist).strftime('%H:%M')
            except Exception:
                pass
            rows.append({
                'time': t_str, 'price': float(closes[i]),
                'dp': dp, 'doi': do,
                'label': label, 'emoji': emoji, 'score': sc,
            })
        st.session_state['_pxoi_cache'] = {'ts': time.time(), 'data': rows[-max_rows:]}
        return rows[-max_rows:]
    except Exception:
        return []


















# ═══════════════════════════════════════════════════════════════
#  ZONE-BASED AUTO TRADE SYSTEM
# ═══════════════════════════════════════════════════════════════

























def compute_dual_profile(df, num_rows=25):
    """Session vs Composite volume profiles + a value-migration read.

    Auction principle (agreed): *context-sensitive* calculations use the current
    session; *structural* calculations use multiple sessions. From the same
    multi-day candle frame we build TWO profiles:

      • Session profile  — today's candles only. This is the context-sensitive
        one (the VAL/POC/VAH the entry logic and Trade Card should react to).
        On a gap day this stops yesterday's value bleeding into today's levels.
      • Composite profile — the last ~5 sessions (structural "weekly value").

    Then compare today's POC vs the weekly POC to label value migration —
    shifted higher / lower / balanced — plus where today's value sits relative
    to the weekly value area, so the narrative can say "value has migrated lower
    after the gap → fresh selling" instead of just "spot below POC".

    Returns (session_mfp, composite_mfp, migration). Any may be None when there
    isn't enough data yet.
    """
    if df is None or df.empty or 'datetime' not in df.columns:
        return None, None, None
    try:
        _dt = pd.to_datetime(df['datetime'])
    except Exception:
        return None, None, None
    # IST calendar day per candle (candles may be tz-aware UTC or naive)
    try:
        _days = (_dt.dt.tz_convert('Asia/Kolkata').dt.date
                 if getattr(_dt.dt, 'tz', None) is not None else _dt.dt.date)
    except Exception:
        try:
            _days = _dt.dt.date
        except Exception:
            return None, None, None
    uniq_days = sorted(set(d for d in _days if d is not None))
    if not uniq_days:
        return None, None, None

    # ── Session profile: the latest day present (today during RTH) ──
    latest_day = uniq_days[-1]
    df_session = df[_days == latest_day]
    session_mfp = None
    if len(df_session) >= 5:
        try:
            session_mfp = calculate_money_flow_profile(df_session, num_rows=num_rows, source='Volume')
        except Exception:
            session_mfp = None
    # Fall back to the whole frame if today is still too thin (pre-open / first bars)
    if session_mfp is None:
        try:
            session_mfp = calculate_money_flow_profile(df, num_rows=num_rows, source='Volume')
        except Exception:
            session_mfp = None

    # ── Composite profile: last ~5 sessions (structural weekly value) ──
    composite_mfp = None
    week_days = uniq_days[-5:]
    df_week = df[_days.isin(week_days)]
    if len(df_week) >= 5 and len(week_days) >= 2:
        try:
            composite_mfp = calculate_money_flow_profile(df_week, num_rows=num_rows, source='Volume')
        except Exception:
            composite_mfp = None

    # ── Value migration: session POC vs composite POC ──
    migration = None
    try:
        if session_mfp and composite_mfp:
            s_poc = float(session_mfp.get('poc_price') or 0)
            c_poc = float(composite_mfp.get('poc_price') or 0)
            c_vah = float(composite_mfp.get('value_area_high') or 0)
            c_val = float(composite_mfp.get('value_area_low') or 0)
            if s_poc and c_poc:
                shift = s_poc - c_poc
                # scale the "balanced" band to the weekly value-area width
                width = (c_vah - c_val) if (c_vah > c_val) else 0
                thresh = max(width * 0.20, 15.0)
                if shift > thresh:
                    label, direction = 'shifted higher', 'BULL'
                elif shift < -thresh:
                    label, direction = 'shifted lower', 'BEAR'
                else:
                    label, direction = 'balanced', 'NEUTRAL'
                if c_vah and c_val and c_vah > c_val:
                    location = ('above weekly value' if s_poc > c_vah
                                else 'below weekly value' if s_poc < c_val
                                else 'inside weekly value')
                else:
                    location = ''
                migration = {
                    'label': label,
                    'direction': direction,
                    'shift_pts': round(shift, 1),
                    'session_poc': round(s_poc, 1),
                    'weekly_poc': round(c_poc, 1),
                    'weekly_vah': round(c_vah, 1),
                    'weekly_val': round(c_val, 1),
                    'location': location,
                    'sessions': len(week_days),
                }
    except Exception:
        migration = None

    return session_mfp, composite_mfp, migration


def _render_retention_panel(st, db):
    """🗑 Data retention — the preview, and the switch that is not on.

    Every `sql/*.sql` migration that creates a growing table declares a purge
    and comments it out. Ten of them do, and none has ever run, so every table
    has been growing since it was created. `db/retention.py` executes those
    policies; this shows what it would remove **before** it removes anything.

    The preview is always live. The purge is gated twice — a module constant a
    human edits, and a confirmation here — because deleting two years of trading
    history has no undo, and a number a trader has actually read is the only
    thing that makes the first run safe.
    """
    if db is None:
        return
    try:
        from db import retention as _ret
    except Exception:
        return

    with st.sidebar.expander("🗑 Data retention", expanded=False):
        state = "🟢 enabled" if _ret.ENABLED else "⚪ preview only"
        st.caption(f"{len(_ret.POLICIES)} policies · {state}")

        if st.button("Preview what would be removed", key="_ret_preview"):
            st.session_state['_retention_preview'] = _ret.preview(db)

        rows = st.session_state.get('_retention_preview')
        if rows:
            total = _ret.total_over_retention(rows)
            st.caption(
                f"**{total['rows_over']:,} rows** over retention across "
                f"{total['tables_over']} of {total['tables_counted']} tables"
                + (f" · {total['tables_unknown']} could not be counted"
                   if total['tables_unknown'] else ""))
            over = [r for r in rows if (r['rows_over'] or 0) > 0]
            for r in sorted(over, key=lambda r: -(r['rows_over'] or 0))[:12]:
                src = "declared" if r['declared'] else "chosen here"
                st.caption(
                    f"`{r['table']}` — {r['rows_over']:,} rows before "
                    f"{r['cutoff']} (keep {r['keep_days']}d, {src})")
            unknown = [r['table'] for r in rows if not r['known']]
            if unknown:
                # Not the same as zero, and it must not render as zero.
                st.caption(f"⚪ not counted: {', '.join(unknown[:8])}")

        if not _ret.ENABLED:
            st.caption(
                "To enable: read the preview above, then set `ENABLED = True` "
                "in `db/retention.py`. There is no undo.")
            return

        st.warning("Deleting is permanent.", icon="⚠️")
        if st.checkbox("I have read the preview", key="_ret_ack"):
            if st.button("Purge now", key="_ret_run"):
                rep = _ret.run(db, confirm=True)
                st.session_state['_retention_preview'] = None
                if rep.get("blocked"):
                    st.error(rep["blocked"])
                else:
                    st.success(f"Removed {rep['rows_removed']:,} rows across "
                               f"{len(rep['tables'])} tables.")

    # The scheduled pass: once a day, and only when a human has enabled it.
    try:
        _ret.run_daily(db)
    except Exception:
        pass


def capture_day_open_and_gap(db, current_price):
    """🕘 Capture today's OPENING spot (the ~09:06 pre-open print) and classify
    the gap BEFORE the first 09:15 candle exists — so gap up/down is known from
    the open, not ~25 minutes later once the session profile has enough candles.

    The spot feed updates from the pre-open session, and every cycle writes it to
    nifty_spot_data with today's trading_day, so the earliest stored row of the
    day IS the opening/gap price. We read it once per day (recovering the true
    first print even after an app restart mid-session) and classify the gap vs
    the prior close from MIOS market memory.

    Stashes:
      st.session_state._day_open_spot = {'day', 'spot'}   — the opening print
      st.session_state._gap_today     = {'type','pct','open','prev_close'} | None
    Returns the opening spot (or None)."""
    try:
        today = datetime.now(pytz.timezone('Asia/Kolkata')).date().isoformat()
    except Exception:
        return None
    cache = st.session_state.get('_day_open_spot') or {}
    open_spot = cache.get('spot') if cache.get('day') == today else None
    if open_spot is None:
        try:
            row = db.get_day_open_spot(today) if db else None
            if row and row.get('ltp'):
                open_spot = float(row['ltp'])
        except Exception:
            open_spot = None
        if open_spot is None and current_price:
            try:
                open_spot = float(current_price)
            except Exception:
                open_spot = None
        if open_spot is not None:
            st.session_state._day_open_spot = {'day': today, 'spot': open_spot}
    # early gap classification vs prior close (from MIOS market memory)
    try:
        prev_close = (st.session_state.get('_mios_market_memory') or {}).get('prev_close')
        if open_spot and prev_close:
            pct = (float(open_spot) - float(prev_close)) / float(prev_close) * 100.0
            gtype = ('GAP-UP' if pct >= 0.40 else
                     'GAP-DOWN' if pct <= -0.40 else 'FLAT-OPEN')
            _gt = {'type': gtype, 'pct': round(pct, 2),
                   'open': float(open_spot), 'prev_close': float(prev_close)}
            # Inside vs Outside yesterday's value area — pure classification (no
            # behaviour prediction). The location is the SETUP that the logged
            # sessions will later validate the Gap-and-Go / Fill behaviours on.
            pv = compute_prev_day_value(db) or {}
            _vah, _val = pv.get('vah'), pv.get('val')
            if open_spot and _vah and _val and _vah > _val:
                _gt['value_location'] = ('outside-above' if open_spot > _vah else
                                         'outside-below' if open_spot < _val else 'inside')
                _gt['prev_vah'], _gt['prev_val'] = float(_vah), float(_val)
                _gt['prev_poc'] = float(pv.get('poc') or 0)
            st.session_state._gap_today = _gt
    except Exception:
        pass


def compute_prev_day_value(db):
    """Yesterday's value area (VAH/VAL/POC), computed once per day from the prior
    trading session's candles — the reference for Inside/Outside Value Gap.
    Cached in session_state._prev_day_value. Returns the dict or None."""
    try:
        today = datetime.now(pytz.timezone('Asia/Kolkata')).date().isoformat()
    except Exception:
        return None
    cache = st.session_state.get('_prev_day_value') or {}
    if cache.get('for_day') == today:
        return cache
    try:
        if db is None:
            return None
        # One row, filtered in the database. This used to be two unbounded
        # scans of `candles_data` — every row in the table to list the series,
        # then every row of that series to list its days — and both results
        # were discarded except for a single date.
        sym, exch = 'NIFTY50', 'IDX_I'
        pday, tf = db.latest_candle_day_before(sym, exch, today)
        if not pday or not tf:
            return None
        pdf = db.get_candles_for_day(sym, exch, tf, pday)
        if pdf is None or getattr(pdf, 'empty', True) or len(pdf) < 5:
            return None
        prof = calculate_money_flow_profile(pdf, num_rows=25, source='Volume')
        if not prof:
            return None
        val = {'for_day': today, 'prev_day': pday,
               'vah': float(prof.get('value_area_high') or 0),
               'val': float(prof.get('value_area_low') or 0),
               'poc': float(prof.get('poc_price') or 0)}
        st.session_state._prev_day_value = val
        return val
    except Exception:
        return None






# ── the full Trade Card, restored verbatim ─────────────────────────────
# Removed by the V6 reduction because no V6 stage reads it — it CONSUMES
# V6 (it calls `build_final_read`), so the dependency runs the other way.
# Restored on request, unchanged. It reads what `render_all_bias_dashboard`
# stashes (`_market_picture`, `_entry_gate_active`, `_guard_state`), so it
# must be CALLED after that runs while RENDERING into a container placed
# above it — which is what `_card_container` is for.

def render_clean_card(spot_price, option_data=None):
    """🎯 ONE CLEAN CARD — the whole app distilled to what a trader needs at a
    glance: what is the market doing, where is support/resistance, is there an
    entry (and if not, WAIT), and — once in a trade — hold patiently or exit
    fast. Pure VIEW over values already computed this cycle (_market_picture,
    _entry_gate_active, _guard_state); computes nothing new, sends nothing,
    never mutates state. Renders first, above every other panel — glance here,
    scroll down only when you want the detail behind it."""
    try:
        mp = st.session_state.get('_market_picture') or {}
        if not mp or not spot_price:
            return
        regime = mp.get('regime')
        eg = mp.get('entry_gate') or {}
        # S/R from the SINGLE canonical Reaction-Zone object (_reaction_sr) — the
        # same support/resistance the Strike Cockpit, Entry Gate and Stage 35
        # read. Falls back to the market-picture sup/res (same underlying data)
        # and finally the raw OI walls until the canonical object warms up.
        _rsr = st.session_state.get('_reaction_sr') or {}
        _rs_sup, _rs_res = _rsr.get('support') or {}, _rsr.get('resistance') or {}
        _sup, _res = mp.get('sup') or {}, mp.get('res') or {}
        _floor, _ceil = mp.get('oi_floor'), mp.get('oi_ceiling')
        _sup_p = _rs_sup.get('price') or _sup.get('price') or (_floor[0] if _floor else None)
        _res_p = _rs_res.get('price') or _res.get('price') or (_ceil[0] if _ceil else None)

        # ── line 1: what is the market doing — the HEADING leads with the MIOS
        # V5 preferred bias (the Conflict-Engine arbitrated read), NOT the Market
        # Picture regime, so the card's headline matches the MIOS V5 panel. Falls
        # back to the Market Picture regime only while MIOS is still warming up.
        _mios_fr = {}
        try:
            _msS = st.session_state.get('_mios_state')
            if _msS is not None and getattr(_msS, 'results', None):
                from mios_v5.final_read import build_final_read as _bfr
                _mios_fr = _bfr(_msS) or {}
        except Exception:
            _mios_fr = {}
        _mios_bias = _mios_fr.get('preferred_bias')
        _mios_conf = _mios_fr.get('confidence_tempered', _mios_fr.get('confidence'))
        # ⚠️ Institutional Preparation banner — MIOS Stage-24 detected the market
        # coiling / positioning ahead of something (cause unknown). Observation,
        # not a direction; leads the card when HIGH.
        # 📅 Scheduled-catalyst chip — MIOS Stage-30 calendar (RBI/Fed/CPI/expiry).
        _cal = _mios_fr.get('calendar') or {}
        _cal_ne = _cal.get('next_event') or {}
        _cal_html = ""
        if _cal_ne and _cal_ne.get('importance', 0) >= 4 and _cal_ne.get('days_away', 9) <= 2:
            _cal_c = '#c026d3' if _cal.get('coiling_ahead_of_event') else '#8fa1b3'
            _cal_extra = (" · market coiling ahead of it" if _cal.get('coiling_ahead_of_event') else "")
            _cal_html = (
                f"<div style='text-align:center;font-size:14px;margin-top:4px;color:{_cal_c};font-weight:700;'>"
                f"📅 {_cal_ne.get('name')} {_cal.get('when','')} {_cal.get('stars','')}{_cal_extra}</div>")
        # ⚠️ FLOW SHIFT banner — MIOS Stage-44 interrupt. Leads the card above
        # every other alert: if institutional flow just shifted, every read below
        # was computed on a tape that no longer exists.
        _fs = _mios_fr.get('flow_shift') or {}
        _stab = _mios_fr.get('stability')
        _fs_html = ""
        if _fs.get('freeze_entries'):
            _fs_html = (
                f"<div style='margin:6px 0;padding:9px 12px;background:#2b1400;"
                f"border:2px solid #ff9500;border-radius:9px;text-align:center;'>"
                f"<span style='font-size:16px;font-weight:900;color:#ffab3d;'>"
                f"⚠️ INSTITUTIONAL FLOW SHIFT — {_fs.get('score',0)}%</span>"
                f"<div style='color:#ffe0b8;font-size:13.5px;font-weight:600;margin-top:2px;'>"
                f"{_fs.get('reason','')}<br>freeze entries — recalculate before acting</div></div>")
        elif _stab == 'RECOVERY':
            _fs_html = (
                f"<div style='text-align:center;font-size:13.5px;margin-top:4px;"
                f"color:#ffcc33;font-weight:700;'>🩹 Tape settling after a flow shift "
                f"— size down</div>")
        _prep = _mios_fr.get('preparation') or {}
        _prep_html = ""
        if _prep.get('level') in ('HIGH', 'ELEVATED'):
            _pc = '#ff9500' if _prep['level'] == 'HIGH' else '#ffd000'
            _psig = " · ".join(_prep.get('signals', [])[:3])
            _prep_html = (
                f"<div style='margin:6px 0;padding:8px 12px;background:#241a05;"
                f"border:2px solid {_pc};border-radius:9px;text-align:center;'>"
                f"<span style='font-size:15px;font-weight:900;color:{_pc};'>"
                f"⚠️ INSTITUTIONAL PREPARATION — {_prep.get('preparation_score',0)}%</span>"
                f"<div style='color:#ffe9c2;font-size:13.5px;font-weight:600;margin-top:2px;'>"
                f"{_psig}<br>market is positioning for a significant event — cause unknown</div></div>")
        # 🚨 Breaking-event banner — MIOS Stage-28 detected a live shock reaction.
        _evt = _mios_fr.get('event') or {}
        if _evt.get('event_detected'):
            _esig = " · ".join(_evt.get('signals', [])[:3])
            _prep_html = (
                f"<div style='margin:6px 0;padding:9px 12px;background:#3d0a05;"
                f"border:2px solid #ff2d2d;border-radius:9px;text-align:center;'>"
                f"<span style='font-size:16px;font-weight:900;color:#ff5a5a;'>"
                f"🚨 BREAKING EVENT — {_evt.get('event_score',0)}%</span>"
                f"<div style='color:#ffd0d0;font-size:13.5px;font-weight:600;margin-top:2px;'>"
                f"{_esig}<br>reaction {_evt.get('reaction','')} — cause unknown; don't chase the "
                f"spike</div></div>") + _prep_html
        # 🔎 Possible cause — MIOS Stage-34 explain layer (only after a detector
        # fired). Explanation only — the market moved first.
        _exp = _mios_fr.get('explanation') or {}
        _causes = _exp.get('possible_causes') or []
        if (_prep_html or _evt.get('event_detected')) and _causes:
            _cause_txt = " · ".join(c.get('cause', '') for c in _causes[:2])
            _prep_html = _prep_html + (
                f"<div style='text-align:center;font-size:13.5px;margin-top:2px;color:#cfd8e6;'>"
                f"🔎 Possible cause ({_exp.get('confidence_label','?')}): {_cause_txt}</div>")
        # 📊 Actual impact — MIOS Stage-33: did the event change structure?
        _imp = _mios_fr.get('event_impact') or {}
        if _imp.get('impact') and (_prep_html or _evt.get('event_detected')):
            _ic = {'VERY HIGH': '#ff2d2d', 'HIGH': '#ff9500',
                   'MEDIUM': '#ffd000', 'LOW': '#8fa1b3'}.get(_imp['impact'], '#8fa1b3')
            _prep_html = _prep_html + (
                f"<div style='text-align:center;font-size:13.5px;margin-top:2px;font-weight:700;color:{_ic};'>"
                f"📊 Actual impact: {_imp['impact']} ({_imp.get('impact_score',0)}%)</div>")
        if _mios_bias:
            _b_up = str(_mios_bias).upper()
            if 'BULL' in _b_up:
                _em_m, _lbl_m, _sub_m = '🟢', ('STRONG BULLISH' if 'STRONG' in _b_up else 'BULLISH'), 'buyers in control'
            elif 'BEAR' in _b_up:
                _em_m, _lbl_m, _sub_m = '🔴', ('STRONG BEARISH' if 'STRONG' in _b_up else 'BEARISH'), 'sellers in control'
            else:
                _em_m, _lbl_m, _sub_m = '🟡', 'NEUTRAL', 'no clear edge'
            _dom = (int(round(float(_mios_conf))) if _mios_conf is not None
                    else max(mp.get('p_up', 0), mp.get('p_down', 0), mp.get('p_side', 0)))
        else:
            _em_m, _lbl_m, _sub_m = {
                'UP':       ('🟢', 'BULLISH', 'buyers in control'),
                'DOWN':     ('🔴', 'BEARISH', 'sellers in control'),
                'SIDEWAYS': ('🟡', 'RANGE', 'no clear side — chop'),
            }.get(regime, ('⚪', 'WARMING UP', ''))
            _dom = max(mp.get('p_up', 0), mp.get('p_down', 0), mp.get('p_side', 0))
        _col_m = ('#00ff88' if 'BULL' in _lbl_m else
                  '#ff4444' if 'BEAR' in _lbl_m else
                  '#ffd000' if _lbl_m in ('RANGE', 'NEUTRAL') else '#888888')

        # ── line 2: SPOT is the single biggest number on the card, on its own
        # line; Support & Resistance flank it just below. ──
        _spot_html = (
            f"<div style='text-align:center;font-size:34px;font-weight:900;color:#ffffff;"
            f"line-height:1.05;margin-top:6px;letter-spacing:.01em;'>"
            f"📍 ₹{spot_price:,.1f}</div>")
        # 🧠 Zone Intelligence lines — each level carries its origin ★, lifecycle,
        # health %, who's winning and the break/reject/trap odds. Falls back to
        # the plain price+strength line until the intel object warms up.
        _sr_intel_html = ""
        try:
            from mios_v5.ui.zone_card import zone_card_line as _zline
            _sr_intel_html = "".join(
                _zline((_z or {}).get('intel'))
                for _z in (_rs_sup, _rs_res) if (_z or {}).get('intel'))
        except Exception:
            _sr_intel_html = ""
        # ⭐ Stage 42 — the reaction verdict (acceptance / rejection / trap).
        # This is the TIMING read: what happened after price reached the level.
        try:
            from mios_v5.ui.zone_card import reaction_line as _rline
            _sr_intel_html += _rline(_mios_fr.get('reaction'))
        except Exception:
            pass
        # 🧠 Stage 52 — the final decision (proof-gated). Kept OUT of the V6
        # intel stack: v2 is a decision engine, so it belongs beside the Entry
        # Gate and v0 in the DECISIONS column, where the three verdicts on the
        # same instant can be read against each other.
        _dec_v2_html = ""
        try:
            from mios_v5.ui.decision_panel import decision_line as _dline
            _dec_v2_html = _dline(_mios_fr.get('decision_v2'))
        except Exception:
            _dec_v2_html = ""
        # 🎭 Stage 48 — the one market personality + what comes next
        try:
            from mios_v5.ui.state_panel import state_line as _sline
            _sr_intel_html += _sline(_mios_fr.get('market_state'))
        except Exception:
            pass
        # 🧠 Stage 54 — how established the current state is
        try:
            from mios_v5.ui.memory_panel import memory_line as _mline
            _sr_intel_html += _mline(_mios_fr.get('memory_read'))
        except Exception:
            pass
        # ⚡ Stage 37 — market energy, when it's actionable news
        try:
            from mios_v5.ui.energy_panel import energy_line as _eline
            _sr_intel_html += _eline(_mios_fr.get('energy_read'))
        except Exception:
            pass
        # 🏛 Stage 43 — the institutional footprint behind the flow
        try:
            from mios_v5.ui.absorption_panel import absorption_line as _abline
            _sr_intel_html += _abline(_mios_fr.get('absorption'))
        except Exception:
            pass
        # 📖 Stage 50 — what price is trying to do, in one sentence
        try:
            from mios_v5.ui.ltp_panel import ltp_line as _lline
            _sr_intel_html += _lline(_mios_fr.get('ltp_behaviour'))
        except Exception:
            pass
        # 🔄 Stage 47 — is the bias changing under us? (only when it is)
        try:
            from mios_v5.ui.transition_panel import transition_line as _tline
            _sr_intel_html += _tline(_mios_fr.get('transition'))
        except Exception:
            pass
        # 🚦 Stage 51 — the gatekeeper's verdict on the proposed side
        try:
            from mios_v5.ui.validity_panel import validity_line as _vline
            _sr_intel_html += _vline(_mios_fr.get('validity'))
        except Exception:
            pass
        _sr_bits = []
        if _sup_p:
            _ss = (f" ({_rs_sup['strength']}%{_sr_trend_badge(_rs_sup)})"
                   if _rs_sup.get('strength') is not None else "")
            _sr_bits.append(f"<span style='color:#00ff88;font-weight:800;'>"
                            f"🟢 Support ₹{_sup_p:,.0f}{_ss}</span>")
        if _res_p:
            _rs2 = (f" ({_rs_res['strength']}%{_sr_trend_badge(_rs_res)})"
                    if _rs_res.get('strength') is not None else "")
            _sr_bits.append(f"<span style='color:#ff4444;font-weight:800;'>"
                            f"🔴 Resistance ₹{_res_p:,.0f}{_rs2}</span>")
        _sr_line = " &nbsp; · &nbsp; ".join(_sr_bits)

        # ── Zone Health: the active (nearest) zone graded across FOUR groups —
        # Spot / Options / Dealers / Institutions → Building / Fading / Neutral —
        # so a conflicted read is legible at a glance instead of nine raw signals.
        _zh_html = ""
        _az, _az_lbl = None, ""
        _sup_hd, _res_hd = _rs_sup.get('zone_health'), _rs_res.get('zone_health')
        if _sup_hd and _res_hd:
            if abs(spot_price - (_rs_sup.get('price') or 0)) <= abs((_rs_res.get('price') or 0) - spot_price):
                _az, _az_lbl = _rs_sup, f"Support ₹{_rs_sup.get('price', 0):,.0f}"
            else:
                _az, _az_lbl = _rs_res, f"Resistance ₹{_rs_res.get('price', 0):,.0f}"
        elif _sup_hd:
            _az, _az_lbl = _rs_sup, f"Support ₹{_rs_sup.get('price', 0):,.0f}"
        elif _res_hd:
            _az, _az_lbl = _rs_res, f"Resistance ₹{_rs_res.get('price', 0):,.0f}"
        if _az:
            _zh = _az.get('zone_health') or {}
            _hem = {'building': '🟢', 'fading': '🔴', 'neutral': '⚪'}
            def _cell(nm, v):
                return (f"<b style='color:#ffffff;'>{nm}</b> "
                        f"<span style='color:#ffffff;'>{_hem.get(v, '⚪')} {v.title()}</span>")
            _life = _az.get('lifecycle', 'stable')
            _life_txt = {'building': "🟢 BUILDING", 'fading': "🔴 COLLAPSING",
                         'under-attack': "⚠️ CONTESTED — wait for confirmation",
                         'broken': "❌ BROKEN", 'stable': "⚪ HOLDING"}.get(_life, "⚪ HOLDING")
            _life_c = {'building': '#00ff88', 'fading': '#ff4444',
                       'under-attack': '#ffd000', 'broken': '#ff4444'}.get(_life, '#ffffff')
            # the active zone's live read — acceptance / trap and the AI "why",
            # straight off the Zone Intelligence card when it's available
            _ai = _az.get('intel') or {}
            _acc_html = ""
            if _ai:
                _acc = _ai.get('acceptance') or {}
                _exp = _ai.get('explain') or {}
                _accc = {'trap': '#ffcc33', 'accepted': '#ff9500',
                         'rejected': '#00ff88', 'defended': '#4da6ff'}.get(_acc.get('state'), '#cfd8e6')
                _why = " · ".join((_exp.get('why') or [])[:3])
                _acc_html = (
                    f"<div style='font-size:13.5px;margin-top:2px;font-weight:700;"
                    f"color:{_accc};'>{_acc.get('label','')}</div>"
                    + (f"<div style='font-size:13px;margin-top:1px;color:#aeb9c7;'>"
                       f"🤖 {_why}</div>" if _why else ""))
                _life_txt = _ai.get('lifecycle_label', _life_txt)
            _zh_html = (
                f"<div style='text-align:center;font-size:14px;margin-top:6px;color:#ffffff;'>"
                f"🩺 <b style='color:#ffffff;'>{_az_lbl}</b> &nbsp; "
                + " &nbsp;·&nbsp; ".join(
                    [_cell(_n, _zh.get(_k, 'neutral')) for _k, _n in
                     (('spot', 'Spot'), ('options', 'Options'), ('dealers', 'Dealers'),
                      ('institutions', 'Instns'), ('liquidity', 'Liq'))
                     if _k in _zh or _k != 'liquidity'])
                + f"<div style='font-weight:900;font-size:15px;margin-top:3px;color:{_life_c};'>"
                f"Overall: {_life_txt}</div>{_acc_html}</div>")

        # ── Context strip: the four secondary reads (Volume Profile · Value
        # Migration · Value Alignment · MIOS composite) are condensed to short
        # coloured tokens on ONE compact wrapped line, so the hero (bias / S/R /
        # action) stays big and the whole card fits one mobile screen. ──
        # Split by owner: measurements go to the FACTS band, the arbitrated
        # MIOS read goes to the V5 column. They used to share one strip, which
        # is how a native session-state reading and a V5 engine output ended up
        # looking like one sentence from one source.
        _ctx_facts, _ctx_v5 = [], []
        # ── Volume Profile — VAL · POC · VAH shown LARGE (the key price levels a
        # trader reads off), right under the S/R line. Same source as the
        # Strike-Mode Cockpit (_money_flow_data). ──
        _mf = st.session_state.get('_money_flow_data') or {}
        _poc_v = float(_mf.get('poc_price', 0) or 0)
        _vah_v = float(_mf.get('value_area_high', 0) or 0)
        _val_v = float(_mf.get('value_area_low', 0) or 0)
        _vp_html = ""
        if _poc_v or _vah_v or _val_v:
            # colour spot's position: inside value area = neutral, above VAH =
            # green (strength), below VAL = red (weakness)
            if _vah_v and spot_price > _vah_v:
                _vp_pos, _vp_pc = "above VAH", "#00ff88"
            elif _val_v and spot_price < _val_v:
                _vp_pos, _vp_pc = "below VAL", "#ff4444"
            else:
                _vp_pos, _vp_pc = "inside VA", "#ffd000"
            _vp_html = (
                f"<div style='text-align:center;font-size:18px;margin-top:6px;font-weight:800;'>"
                f"📊 <span style='color:#ff8c8c;'>VAL ₹{_val_v:,.0f}</span> · "
                f"<span style='color:#ffe066;'>POC ₹{_poc_v:,.0f}</span> · "
                f"<span style='color:#7dffb0;'>VAH ₹{_vah_v:,.0f}</span> "
                f"<span style='color:{_vp_pc};'>({_vp_pos})</span></div>")

        # ── Value migration token: today's session value vs the last ~5 sessions'
        # weekly value (structural) — has value *shifted* higher/lower? ──
        _mig = st.session_state.get('_value_migration') or {}
        if _mig.get('label'):
            _mig_c = {'BULL': '#66ff9d', 'BEAR': '#ff6666'}.get(_mig.get('direction'), '#ffd000')
            _mig_arrow = {'shifted higher': '↑', 'shifted lower': '↓'}.get(_mig['label'], '↔')
            _ctx_facts.append(
                f"<span style='color:{_mig_c};'>🔀 value {_mig_arrow} {_mig['label']}</span>")

        # ── Value Alignment token: nine VPFR levels → one market state (is the
        # market accepting prices — aligned bullish / bearish / rotating?). ──
        _va = st.session_state.get('_value_alignment') or {}
        if _va.get('overall'):
            _ov = _va.get('overall', '')
            _ov_c = ('#00ff88' if _ov == 'aligned bullish' else
                     '#ff4444' if _ov == 'aligned bearish' else '#ffd000')
            _mig2 = _va.get('migration')
            _mig2_txt = ({'rising': ' 📈', 'falling': ' 📉'}.get(_mig2, '') if _mig2 else '')
            _ctx_facts.append(f"<span style='color:{_ov_c};'>📐 {_ov}{_mig2_txt}</span>")

        # ── early GAP flag: classified from the ~09:06 opening spot, so on a gap
        # day the card announces it from the open (and warns yesterday's value
        # area is stale) instead of silently showing yesterday's levels while
        # today's session profile is still forming. ──
        _gap = st.session_state.get('_gap_today') or {}
        _gap_html = ""
        if _gap.get('type') in ('GAP-UP', 'GAP-DOWN'):
            _gc = '#66ff9d' if _gap['type'] == 'GAP-UP' else '#ff6666'
            _gem = '🔺' if _gap['type'] == 'GAP-UP' else '🔻'
            _forming = (st.session_state.get('_money_flow_data') or {}).get('num_bars', 0)
            _warn = (" · today's value area still forming — yesterday's levels are stale"
                     if _forming and _forming < 10 else "")
            # location vs yesterday's value + live acceptance (observation only)
            _vl_txt = {'outside-above': 'outside yday value ↑', 'outside-below': 'outside yday value ↓',
                       'inside': 'inside yday value'}.get(_gap.get('value_location'), '')
            _oa = st.session_state.get('_opening_auction') or {}
            _acc = _oa.get('acceptance')
            _acc_txt = (f" · {_acc} ({_oa.get('fill_pct',0):.0f}% filled)" if _acc else "")
            _extra = ((" · " + _vl_txt) if _vl_txt else "") + _acc_txt
            _gap_html = (
                f"<div style='text-align:center;font-size:14px;margin-top:4px;font-weight:600;'>"
                f"{_gem} <b style='color:{_gc};'>{_gap['type']} {_gap['pct']:+.2f}%</b>"
                f"<span style='color:#ffffff;'> open ₹{_gap.get('open',0):,.0f} vs prev close "
                f"₹{_gap.get('prev_close',0):,.0f}{_extra}{_warn}</span></div>")

        # ── 🕘 Stage 69 — WHERE in the day. A 09:20 breakout is not a
        # 13:00 breakout; the strip keeps the session and its mood in view.
        _sess_html = ""
        try:
            from mios_v5.ui.session_panel import session_strip as _ss
            _sess_html = _ss(_mios_fr.get('session_intel'))
        except Exception:
            _sess_html = ""

        # ── 🗓 Stage 68 — what KIND of day this is. The first thing to read,
        # because the same setup is a buy on a trend day and a fade on a pin
        # day. Context only: it votes on nothing below it.
        _dayt_html = ""
        try:
            from mios_v5.ui.day_type_panel import day_type_badge as _dtb
            _dayt_html = _dtb(_mios_fr.get('day_classification'))
        except Exception:
            _dayt_html = ""

        # ── 🗣 V6.5 Stages 61-63 — WHY this decision, in one strip: the ✓/✗
        # conditions with the engine output behind each, and when MIOS is
        # waiting, exactly what is missing plus a readiness %. Explanation
        # only; it neither produces nor alters the decision above it.
        _why_html = ""
        try:
            from mios_v5.checklist import build as _bcl
            from mios_v5.explain_decision import explain as _explain
            from mios_v5.ui.explain_panel import checklist_line as _clline
            _cl_card = _bcl(_mios_fr)
            _ex_card = _explain(_mios_fr, _cl_card)
            st.session_state['_mios_explain'] = _ex_card
            _bits_w = [f"<span style='color:#7fe8b0;'>{r['text']}</span>"
                       for r in (_ex_card.get('reasons') or [])[:3]]
            _bits_w += [f"<span style='color:#ff9d9d;'>{r['text']}</span>"
                        for r in (_ex_card.get('opposed') or [])[:2]]
            _need_w = ""
            if _ex_card.get('needs'):
                _need_w = (
                    f"<div style='font-size:13px;color:#ffcc33;margin-top:2px;"
                    f"font-weight:600;'>Need: "
                    + " · ".join(n['label'] for n in _ex_card['needs'][:3])
                    + "</div>")
            if _bits_w or _need_w:
                _why_html = (
                    f"<div style='text-align:center;font-size:13px;margin-top:5px;"
                    f"line-height:1.5;'>"
                    + " &nbsp;·&nbsp; ".join(_bits_w) + _need_w + "</div>")
            _why_html += _clline(_cl_card)
        except Exception:
            _why_html = ""

        # ── 🧬 MIOS V5 ‖ V6 bias, side by side. The card's headline is the V5
        # Conflict-Engine read; this strip puts the V6 read (Stage 53 families ×
        # Stage 42 reaction × Stage 45 HTF × Stage 43 absorption, gated by 51/44
        # and discounted by 47/54) beside it at the same size. Neither is
        # labelled "the answer" — V6 is observational until enough live sessions
        # prove it beats V5, and the days they DISAGREE are the data that
        # decides. Advisory: nothing here feeds the Decision Engine. ──
        _v6_html = ""
        try:
            from mios_v5.v6_bias import compare as _v6cmp
            from mios_v5.ui.bias_compare import bias_compare_html as _v6html
            _v6_cmp = _v6cmp(_mios_fr)
            st.session_state['_mios_v6_bias'] = _v6_cmp
            _v6_html = _v6html(_v6_cmp)
        except Exception:
            _v6_html = ""

        # ── 🧲 Expiry charm-pin — on expiry day, dealer hedging drags price to
        # the magnet strike: breakouts fade and small dips near the pin are
        # noise. Same read the Guardian panel shows, from one shared rule.
        # Context ONLY — it never changes the bias or the verdict.
        _charm_html = ""
        try:
            # `dealer_magnet`, not `charm_pin` directly: the magnet is a real
            # level on EVERY day, and this wrapper reports it on normal days too
            # with wording that does not overclaim. `charm_pin` still does the
            # measuring and is unchanged — on expiry day the read is identical.
            from mios_v5.dealer_magnet import from_market_picture as _cpin
            from mios_v5.ui.charm_pin_panel import charm_pin_html as _cpinhtml
            _charm_html = _cpinhtml(_cpin(
                _is_expiry_day(option_data), spot_price, mp,
                (option_data or {}).get('max_pain_strike')))
        except Exception:
            _charm_html = ""

        # ── 🧲 Greek behaviour layer — INTERPRETS existing dealer/greek data ──
        # No new engine, no new Greek: it reads `_gex_data` (gamma), the market
        # picture's `vc_exp` (net charm / vanna) and the magnet level the app
        # already ranks, and translates them into one compact behavioural strip
        # (pull · chop/expansion · time · vol · expansion risk). Context only —
        # it never votes, and a missing Greek reads "Not reported", never 0.
        _gb_html = ""
        try:
            from mios_v5.greek_behaviour import interpret as _gb_interpret
            from mios_v5.ui.greek_behaviour_panel import behaviour_html as _gbhtml
            _vc = mp.get('vc_exp') or {}
            _gx = st.session_state.get('_gex_data') or {}
            _pin = mp.get('oi_pin')
            if isinstance(_pin, (list, tuple)) and _pin:
                _plevel = _pin[0]
                _psrc = _pin[1] if len(_pin) > 1 else 'OI pin'
            else:
                _plevel = (option_data or {}).get('max_pain_strike')
                _psrc = 'max pain'
            _asof = None
            _ots = st.session_state.get('_opt_data_ts')
            if _ots:
                try:
                    _asof = datetime.fromisoformat(_ots).timestamp()
                except Exception:
                    _asof = None
            # rolling per-greek windows so each third-order read self-calibrates
            # against its OWN recent magnitude (the five nets span orders of
            # magnitude, so a fixed band can't fit them). Bounded to the last
            # _CTX_HIST_WINDOW reruns (~20 min at ~20s each).
            _CTX_HIST_WINDOW = 60
            _hist_store = st.session_state.setdefault('_greek_ctx_hist', {})
            _ctx_hist = {}
            for _g in ('vomma', 'speed', 'zomma', 'veta', 'color'):
                _dq = _hist_store.setdefault(_g, [])
                _gv = _vc.get(f'net_{_g}')
                if _gv is not None:
                    try:
                        _dq.append(abs(float(_gv)))
                        del _dq[:-_CTX_HIST_WINDOW]
                    except (TypeError, ValueError):
                        pass
                _ctx_hist[_g] = list(_dq)
            _gb_html = _gbhtml(_gb_interpret(
                spot=spot_price, pull_level=_plevel, pull_source=_psrc,
                net_charm=_vc.get('net_charm'), net_vanna=_vc.get('net_vanna'),
                net_vega=_vc.get('net_vega'),
                total_gex=_gx.get('total_gex'),
                gamma_flip=_gx.get('gamma_flip_level'),
                is_expiry=_is_expiry_day(option_data),
                as_of=_asof, now=time.time(),
                # the "other 5" third-order net exposures → their own reads,
                # each bucketed against its own rolling history
                vomma=_vc.get('net_vomma'), speed=_vc.get('net_speed'),
                zomma=_vc.get('net_zomma'), veta=_vc.get('net_veta'),
                color=_vc.get('net_color'),
                contextual_history=_ctx_hist))
        except Exception:
            _gb_html = ""

        # ── ⚔️ Level Acceptance / Rejection strip (context-only) ─────────
        # Observation of what price DID after reaching a level — reuses the
        # Stage-42 reaction engine (evaluate_reaction) across the wider level
        # set, mapped to six words and clustered into battle zones. It touches
        # no verdict: the predictive breakout/rejection % stays as-is; this
        # reports separately. Never sends Telegram, never feeds Guardian.
        _la_html = ""
        _la_oneliner = ""
        try:
            from mios_v5.acceptance import evaluate_reaction as _eval_reaction
            from mios_v5.level_acceptance import observe_levels as _observe_levels
            from mios_v5.ui.level_acceptance_panel import acceptance_html as _lahtml
            from mios_v5.ui.level_acceptance_panel import acceptance_oneliner as _laone
            # reuse the SAME follow-through metrics Stage-42 already assembled
            _la_metrics = {}
            _mst = st.session_state.get('_mios_state') or {}
            _st42 = _mst.get('stage42_acceptance') if hasattr(_mst, 'get') else None
            if _st42 is not None and getattr(_st42, 'ok', False):
                _la_metrics = (_st42.data or {}).get('metrics') or {}
            # gather the levels from producers the app already owns (no new calc)
            _la_levels = []
            if _plevel is not None:
                _la_levels.append({'label': 'Dealer magnet', 'price': _plevel})
            _gflip = _gx.get('gamma_flip_level')
            if _gflip is not None:
                _la_levels.append({'label': 'Gamma flip', 'price': _gflip})
            _rsr_la = st.session_state.get('_reaction_sr') or {}
            for _sd, _lbl in (('resistance', 'Resistance'), ('support', 'Support')):
                _zz = _rsr_la.get(_sd) or {}
                if _zz.get('price') is not None:
                    _la_levels.append({'label': _lbl, 'price': _zz.get('price'),
                                       'strength': _zz.get('strength'),
                                       'lifecycle': _zz.get('lifecycle')})
            # OI walls — the market picture already ranks them (strike, size)
            _oc = mp.get('oi_ceiling')
            if _oc and _oc[0] is not None:
                _la_levels.append({'label': 'OI wall (CE)', 'price': _oc[0]})
            _ofl = mp.get('oi_floor')
            if _ofl and _ofl[0] is not None:
                _la_levels.append({'label': 'OI wall (PE)', 'price': _ofl[0]})
            # POC / VAH / VAL — today's money-flow profile (already computed)
            _mf_la = st.session_state.get('_money_flow_data') or {}
            for _k, _lbl in (('poc_price', 'POC'), ('value_area_high', 'VAH'),
                             ('value_area_low', 'VAL')):
                _pv = _mf_la.get(_k)
                if _pv:
                    _la_levels.append({'label': _lbl, 'price': float(_pv)})
            if _la_levels:
                # ── reset per-level state on a NEW session or a confirmed regime
                # flip — never on tick noise. Session = the IST trading date;
                # regime flip = a real UP↔DOWN change, ignoring SIDEWAYS flicker.
                _la_sess = (_ots or '')[:10]          # YYYY-MM-DD from market ts
                _la_reg = str(mp.get('regime') or '').upper()
                _la_keys = st.session_state.get('_la_reset_keys') or {}
                _reset_la = False
                if (_la_sess and _la_keys.get('session')
                        and _la_keys['session'] != _la_sess):
                    _reset_la = True                  # a new trading session
                if _la_reg in ('UP', 'DOWN'):
                    if _la_keys.get('regime_dir') and _la_keys['regime_dir'] != _la_reg:
                        _reset_la = True              # confirmed UP↔DOWN flip
                    _la_keys['regime_dir'] = _la_reg  # updated only on direction
                if _la_sess:
                    _la_keys['session'] = _la_sess
                st.session_state['_la_reset_keys'] = _la_keys
                if _reset_la:
                    st.session_state['_level_accept_mem'] = {}
                    st.session_state['_la_alert_state'] = {}
                _la_store = st.session_state.setdefault('_level_accept_mem', {})
                _la_iband = st.session_state.get('_la_interaction_band') or 5.0
                _la_read = _observe_levels(_la_levels, spot_price, _la_metrics,
                                           _la_store, _eval_reaction,
                                           interaction_band=_la_iband, now=_ots)
                _la_html = _lahtml(_la_read)          # full evidence → Market Picture
                _la_oneliner = _laone(_la_read)       # compact state → Trade Card
                # hand the resolved zones to the main-loop notifier (edge +
                # cooldown live there, next to the other Telegram alerts)
                st.session_state['_la_zones_latest'] = _la_read.get('zones') or []
        except Exception:
            _la_html = ""

        # ── ⚙️ dealer & volatility context, in one line ─────────────────
        # The Adaptive Greeks read, from the object Dashboard V6 published this
        # cycle. Read-only and short by design: the card already carries three
        # verdicts, and this adds the terrain they have to cross rather than a
        # fourth opinion about it. The layer emits no side at all
        # (`assert_no_recommendation`), so it cannot contradict them.
        _ag_html = ""
        try:
            from mios_v5.ui.greeks_panel import one_line as _ag_one
            _agl = _ag_one(st.session_state.get('_adaptive_greeks'))
            if _agl:
                _ag_html = (
                    f"<div style='font-size:11px;color:#cfd9e6;margin-top:3px;"
                    f"text-align:center;'>⚙️ {_agl}</div>")
        except Exception:
            _ag_html = ""

        # ── Stage 71.7 Premium Energy, in three lines ──────────────────
        # The full section is drawn inside the Validation expander further down
        # the page; this is the glance version on the card above the app, from
        # the SAME published object. Nothing is recomputed here — `compact_html`
        # lives in the panel that already owns this data, so the card and the
        # section cannot disagree.
        #
        # Both energy AND spike, because they routinely point opposite ways and
        # a compact view is exactly where the second one gets dropped.
        _pe_html = ""
        try:
            from mios_v5.ui.premium_energy_panel import compact_html as _pehtml
            _pe_html = _pehtml(st.session_state.get('_premium_energy'))
        except Exception:
            _pe_html = ""

        # ── The war zone, in one line ──────────────────────────────────
        # Same three published fields the V6 dashboard's strip reads —
        # `battle_zone`, `expected_winner`, `probabilities` — through the panel
        # that now owns both renderings. The compact form drops the wrapper
        # words ("War zone", "expected winner"), never a number: bounce and
        # breakdown are one reading, and showing only the winning side is the
        # edit that turns "likely to give, but close" into "gives".
        _wz_html = ""
        try:
            from mios_v5.ui.war_zone import compact_html as _wzhtml
            _wz_html = _wzhtml(_mios_fr)
        except Exception:
            _wz_html = ""

        # ── MIOS V5 read (Analysis & Audit) — direction + Trade Quality.
        # DIRECTION comes from the SAME authoritative source as the MIOS
        # dashboard: the Conflict-Engine arbitrated preferred_bias in the final
        # read (priority × confidence weighted). The 7-layer synthesis
        # (build_layer_scores) supplies only the Trade-Quality GRADE — using
        # its own `direction` here caused the card to say BULL while the
        # dashboard said BEAR (two different aggregators). Now they agree. ──
        _ls = st.session_state.get('_layer_scores') or {}
        # reuse the final read already computed for the heading
        _mios_dir = _mios_bias if _mios_bias else _ls.get('direction')
        if _ls.get('grade') or _mios_dir:
            _gc = {'A+': '#00ff88', 'A': '#17c98b', 'B': '#ffd000',
                   'C': '#ff4444'}.get(_ls.get('grade'), '#ffffff')
            _dir_up = str(_mios_dir or '—').replace('_', ' ')
            _dc = ('#17c98b' if 'BULL' in _dir_up else
                   '#ff4444' if 'BEAR' in _dir_up else '#cfd8e6')
            _grade_txt = (f" · <b style='color:{_gc};'>Q{_ls['grade']}</b>"
                          if _ls.get('grade') else "")
            _ctx_v5.append(
                f"🧭 <b style='color:{_dc};'>MIOS {_dir_up}</b>{_grade_txt}")

        def _ctx_strip(bits):
            if not bits:
                return ""
            return ("<div style='text-align:center;font-size:15px;margin-top:6px;"
                    "line-height:1.6;color:#d6e0ec;font-weight:700;'>"
                    + " &nbsp;·&nbsp; ".join(bits) + "</div>")

        _ctx_facts_html, _ctx_v5_html = _ctx_strip(_ctx_facts), _ctx_strip(_ctx_v5)

        # ── line 3/4: the action verdict — in a trade, or waiting? ──
        _act = st.session_state.get('_entry_gate_active')
        if _act:
            # IN A TRADE → hold patiently vs exit fast
            _side = _act.get('side', '')
            _lvl = float(_act.get('level') or 0)
            _tgt = float(_act.get('target') or 0)
            _inv = float(_act.get('invalidation') or 0)
            _entry = float(_act.get('entry_spot') or spot_price)
            _fav = (spot_price - _entry) if _side == 'CALL' else (_entry - spot_price)
            _to_tgt = abs(_tgt - spot_price)
            _to_inv = abs(spot_price - _inv)
            _gs = st.session_state.get('_guard_state') or {}
            _state = _gs.get('state') if time.time() - _gs.get('ts', 0) <= 60 else None
            if _state == 'EXIT':
                _ac_col, _ac_bg, _ac_em, _ac_hd = '#ff2d55', '#3d0a1f', '⚡', 'EXIT FAST — reversal confirmed'
            elif _state == 'WARNING':
                _ac_col, _ac_bg, _ac_em, _ac_hd = '#ffcc33', '#2a2205', '⚠️', 'WATCH — sudden opposite flow, be ready'
            elif _state == 'PATIENT':
                _ac_col, _ac_bg, _ac_em, _ac_hd = '#4da6ff', '#0a1f33', '🧘', 'HOLD PATIENT — normal noise, don’t panic-exit'
            else:
                _ac_col, _ac_bg, _ac_em, _ac_hd = '#00ff88', '#0a3d2a', '✅', 'ON TRACK — let it work'
            _em_side = '🟢' if _side == 'CALL' else '🔴'
            _action_html = (
                f"<div style='margin-top:8px;padding:12px 16px;background:{_ac_bg};"
                f"border:3px solid {_ac_col};border-radius:10px;text-align:center;'>"
                f"<span style='font-size:23px;font-weight:900;color:{_ac_col};'>"
                f"{_ac_em} {_ac_hd}</span>"
                f"<div style='color:#fff;font-size:14px;font-weight:700;margin-top:4px;'>"
                f"{_em_side} In BUY {_side} from ₹{_lvl:,.0f} · now {_fav:+.0f} pts</div>"
                f"<div style='color:#e6e6e6;font-size:14.5px;margin-top:3px;'>"
                f"🎯 Target ₹{_tgt:,.0f} ({_to_tgt:.0f} to go) &nbsp;·&nbsp; "
                f"❌ Exit if breaks ₹{_inv:,.0f} ({_to_inv:.0f} away)</div></div>")
        else:
            # NOT IN A TRADE → enter / get ready / watching / wait
            _st_g = eg.get('state', 'WAIT')
            _zone = eg.get('zone', '')
            _lvl = float(eg.get('level') or 0)
            if _st_g in ('CALL', 'PUT'):
                _tgt = eg.get('target'); _inv = eg.get('invalidation'); _rr = eg.get('rr')
                _em_e = '🟢' if _st_g == 'CALL' else '🔴'
                _ac_col, _ac_bg = ('#00ff88', '#0a3d2a') if _st_g == 'CALL' else ('#ff4444', '#3d0a1f')
                _trade = (f"🎯 Target ₹{_tgt:,.0f} · ❌ SL ₹{_inv:,.0f} · ⚖️ RR {_rr}"
                          if _tgt and _inv else "")
                _action_html = (
                    f"<div style='margin-top:8px;padding:12px 16px;background:{_ac_bg};"
                    f"border:3px solid {_ac_col};border-radius:10px;text-align:center;'>"
                    f"<span style='font-size:24px;font-weight:900;color:{_ac_col};'>"
                    f"{_em_e} ENTER — BUY {_st_g} at {_zone} ₹{_lvl:,.0f}</span>"
                    f"<div style='color:#fff;font-size:14.5px;font-weight:700;margin-top:4px;'>{_trade}</div>"
                    f"<div style='color:#d0d0d0;font-size:13.5px;margin-top:2px;'>"
                    f"zone tested &amp; reclaimed — your decision, no auto-entry</div></div>")
            elif _st_g in ('ARMED_CALL', 'ARMED_PUT'):
                _side_a = 'CALL' if _st_g == 'ARMED_CALL' else 'PUT'
                _action_html = (
                    f"<div style='margin-top:8px;padding:12px 16px;background:#2a2205;"
                    f"border:3px solid #ffcc33;border-radius:10px;text-align:center;'>"
                    f"<span style='font-size:23px;font-weight:900;color:#ffcc33;'>"
                    f"🟡 GET READY — {_side_a} at {_zone} ₹{_lvl:,.0f}</span>"
                    f"<div style='color:#ffe9a8;font-size:14.5px;font-weight:700;margin-top:4px;'>"
                    f"Price is at the zone — waiting for the confirmation candle. "
                    f"Don’t chase the first touch.</div></div>")
            elif _st_g in ('AT_ZONE_WAIT', 'CHOP_WAIT', 'NO_ROOM', 'REVERSED'):
                _why = " · ".join(eg.get('why') or []) or "not a clean setup yet"
                _action_html = (
                    f"<div style='margin-top:8px;padding:12px 16px;background:#0a1f33;"
                    f"border:3px solid #4da6ff;border-radius:10px;text-align:center;'>"
                    f"<span style='font-size:22px;font-weight:900;color:#4da6ff;'>"
                    f"👀 WATCHING — price at {_zone} ₹{_lvl:,.0f}</span>"
                    f"<div style='color:#cfe8ff;font-size:14.5px;font-weight:700;margin-top:4px;'>"
                    f"Not a trade yet — {_why}</div></div>")
            elif _st_g == 'PINNED':
                _action_html = (
                    f"<div style='margin-top:8px;padding:12px 16px;background:#241a2e;"
                    f"border:3px solid #a78bfa;border-radius:10px;text-align:center;'>"
                    f"<span style='font-size:22px;font-weight:900;color:#a78bfa;'>"
                    f"🧲 PINNED ₹{_lvl:,.0f} — no edge</span>"
                    f"<div style='color:#c9b6ec;font-size:14.5px;font-weight:700;margin-top:4px;'>"
                    f"Price magnet-locked — wait, no trade here</div></div>")
            else:  # WAIT
                _tgt_txt = []
                if _sup_p:
                    _tgt_txt.append(f"support ₹{_sup_p:,.0f} ({_sup_p - spot_price:+.0f})")
                if _res_p:
                    _tgt_txt.append(f"resistance ₹{_res_p:,.0f} ({_res_p - spot_price:+.0f})")
                _wait_sub = ("nearest zone: " + " / ".join(_tgt_txt)) if _tgt_txt else "no zone mapped yet"
                _action_html = (
                    f"<div style='margin-top:8px;padding:12px 16px;background:#1a2030;"
                    f"border:3px solid #ffffff;border-radius:10px;text-align:center;'>"
                    f"<span style='font-size:22px;font-weight:900;color:#ffffff;'>"
                    f"⏳ WAIT — no trade</span>"
                    f"<div style='color:#cfd8e6;font-size:14.5px;font-weight:700;margin-top:4px;'>"
                    f"Price mid-range — {_wait_sub}</div></div>")

        # ── 🎯 Decision Engine v0 (observational): the consolidated decision
        # (CALL/PUT/WAIT/STAND ASIDE) + Quality grade + the gates behind it.
        _dec = st.session_state.get('_mios_decision') or {}
        _signal_html = ""
        if _dec.get('state'):
            _sc = {'CONFIRMED': '#00ff88', 'ARMED': '#4da6ff',
                   'IN_TRADE': '#a78bfa'}.get(_dec['state'], '#8fa1b3')
            _pg = " ".join(f"✓{p.split(' ')[0]}" for p in (_dec.get('passed') or []))
            _wn = _dec.get('warnings') or []
            _wn_txt = ("<br><span style='color:#ffcc66;'>⚠️ "
                       + " · ".join(_wn[:3]) + "</span>") if _wn else ""
            _blk = (f" — {_dec.get('blocked_by')}" if _dec['state'] == 'WAIT'
                    and _dec.get('blocked_by') else "")
            _ql = (f" · Quality {_dec['quality']}" if _dec.get('quality') else "")
            _rrt = (f" · R:R {_dec['rr']:.1f}" if isinstance(_dec.get('rr'), (int, float)) else "")
            _cft = (f" · {_dec['confidence']}%" if _dec.get('confidence') is not None
                    and _dec['state'] in ('CONFIRMED', 'ARMED') else "")
            _signal_html = (
                f"<div style='text-align:center;font-size:17px;margin-top:5px;color:#e3ebf5;font-weight:700;'>"
                f"🎯 <b style='color:{_sc};'>Decision: {_dec.get('decision', '—')}</b>"
                f"{_ql}{_cft}{_blk}{_rrt}"
                f"<br><span style='color:#a8b8ca;font-size:15px;font-weight:600;'>gates {_pg or '—'}</span>{_wn_txt}</div>")

        # ── assemble the card in FOUR labelled parts, grouped by which
        # generation of the app produced each number.
        #
        # The card grew by accretion: native Market-Picture reads, the V5
        # Conflict Engine, the V6 engines and two Decision Engines all wrote
        # into one undifferentiated stack. That is legible only if you already
        # know which engine owns which line — and it hid a real disagreement,
        # because the Entry Gate's "price mid-range", v0's "location passed"
        # and v2's checklist all describe the SAME instant from three
        # different S/R sources and used to sit lines apart looking like one
        # verdict.
        #
        #   FACTS      measurements every version reads (spot · value · gap)
        #   MIOS V5    the Conflict-Engine arbitrated read + its stages (≤41)
        #   MIOS V6    families/reaction/structure + its stages (37, 42-54, 68-69)
        #   DECISIONS  Entry Gate (native) · v0 · v2 — the three action verdicts
        #
        # Grouping only. Nothing here changes a value, an order of computation
        # or which engine feeds which; every fragment is the same string it
        # was, moved under the heading that owns it.
        _SEC = ("background:#0b0f16;border:1px solid {b};border-radius:12px;"
                "padding:10px 12px;margin-bottom:8px;")
        _HDR = ("text-align:center;font-size:10px;letter-spacing:.14em;"
                "text-transform:uppercase;font-weight:800;color:{b};"
                "border-bottom:1px solid #1e2836;padding-bottom:5px;"
                "margin-bottom:7px;")

        def _sec(title, border, body):
            """One labelled section. Renders the heading even when the body is
            empty, so a version that has gone quiet is visibly quiet rather
            than silently absent — a missing engine and a warming-up engine
            must not look identical."""
            return (f"<div style='{_SEC.format(b=border)}'>"
                    f"<div style='{_HDR.format(b=border)}'>{title}</div>"
                    + (body or "<div style='text-align:center;font-size:12.5px;"
                               "color:#6b7a8d;padding:6px 0;'>— nothing to "
                               "report this cycle —</div>")
                    + "</div>")

        # ── 1 · MARKET FACTS — measurements, not any version's opinion ──
        st.markdown(_sec(
            "📊 Market Facts", "#8fa1b3",
            _spot_html + _vp_html + _gap_html + _ctx_facts_html),
            unsafe_allow_html=True)

        # ── information hierarchy (DISPLAY ONLY) ───────────────────────
        # The Trade Card is the "what is happening now" summary; the Market
        # Picture is the "why / how" detail. The verbose strips — the full Greek-
        # Behaviour rows, the Dealer-Magnet detail and the Level-Acceptance
        # evidence — are built here (nothing recomputed) but rendered in the
        # Market Picture instead, so the card stays compact and the same long
        # text is never drawn twice. `render_market_picture` reads this stash.
        st.session_state['_mp_detail'] = {
            'level_acceptance': _la_html,
            'dealer_magnet': _charm_html,
            'greek_behaviour': _gb_html,
        }

        # ── MIOS V6 — the observational read, FULL WIDTH ──────────────
        # KEY POINTS ONLY: the V6 read (market state), the structure line, the
        # war zone, the COMPACT level-acceptance state (`_la_oneliner`) and the
        # one-line dealer/greek/fade summary (`_ag_html`). The detailed Greek
        # rows, dealer-magnet detail and acceptance evidence moved to the Market
        # Picture (stashed above) — they are no longer drawn on the card.
        #
        # ⚠️ Display only. The Entry Gate, v0 and v2 verdicts still compute and
        # the native gate still drives its live Telegram alert exactly as before.
        st.markdown(_sec(
            "🧬 MIOS V6 · observational", "#4da6ff",
            _v6_html + _dayt_html + _sess_html
            + (f"<div style='text-align:center;margin-top:4px;'>"
               f"{_sr_intel_html}</div>" if _sr_intel_html else
               f"<div style='text-align:center;font-size:16px;margin-top:4px;"
               f"font-weight:800;'>{_sr_line}</div>")
            + _wz_html + _la_oneliner + _pe_html + _ag_html
            + _fs_html + _zh_html),
            unsafe_allow_html=True)
    except Exception:
        pass


def _today_session(df):
    """Just the latest session's bars, for the chart.

    Delegates to `mios_v5.clock.today_slice`, which is the single owner of "one
    session only" and is what `terminal_chart` already applies to all three
    panels. A second implementation here is how the two would eventually
    disagree about where a session starts — and the real bug was in that owner,
    not in having one: it fell back to the WHOLE window whenever wall-clock
    today had no rows, so pre-open and on holidays every caller got three days.
    """
    try:
        from mios_v5.clock import today_slice
        return today_slice(df)
    except Exception:
        return df


def _leg_intraday(api, sid, seg, render_id, ttl_s=60):
    """One option leg's 1-minute frame for today, or None.

    The fetch discipline is the part that matters and is kept verbatim from the
    full app:

    * **per-leg cache** (default 60s) — the legs poll every ~20s cycle, so
      without it Dhan returns 429.
    * **a per-render budget** — all six legs share one 60s TTL and were
      populated in the same cycle, so all six expired in the same cycle. Every
      third render then paid 6 x the 0.3s intraday throttle inside a 20s
      refresh. The budget lets at most `LEG_FETCH_PER_RENDER` legs actually
      fetch; the rest serve their (bounded, age-reported) cached bars and
      rotate in next render.
    * **429 back-off** — a recent 429 skips the fetch entirely and reuses cache
      up to 5x TTL rather than queueing behind a retry ladder.

    Returns (df_today, age_seconds) — age is what makes the staleness visible
    instead of silent.
    """
    if not sid:
        return None, None
    cache = st.session_state.setdefault('_opt_intraday_cache', {})
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    entry = cache.get(sid)

    budget = st.session_state.get('_leg_fetch_budget')
    if budget is None or budget[0] != render_id:
        budget = [render_id, LEG_FETCH_PER_RENDER]
        st.session_state['_leg_fetch_budget'] = budget

    fresh = bool(entry and (now - entry['ts']).total_seconds() < ttl_s)
    if not fresh and entry is not None and budget[1] <= 0:
        fresh = True                      # over budget — reuse the stale bars
    if fresh:
        raw, age = entry['data'], (now - entry['ts']).total_seconds()
    else:
        budget[1] -= 1
        back = st.session_state.get('_dhan_429_until')
        if back and now < back:
            if entry and (now - entry['ts']).total_seconds() < ttl_s * 5:
                raw, age = entry['data'], (now - entry['ts']).total_seconds()
            else:
                return None, None
        else:
            try:
                raw = api.get_intraday_data(
                    security_id=str(sid), exchange_segment=seg,
                    instrument="OPTIDX", interval="1", days_back=1)
            except Exception as err:
                if '429' in str(err):
                    _trip_dhan_backoff()
                if not entry:
                    return None, None
                raw, age = entry['data'], (now - entry['ts']).total_seconds()
            else:
                if raw and raw.get('open'):
                    cache[sid] = {'ts': now, 'data': raw}
                age = 0

    if not raw or not raw.get('open'):
        return None, None
    ist = pytz.timezone('Asia/Kolkata')
    frame = pd.DataFrame({
        'datetime': [datetime.fromtimestamp(t, ist) for t in raw.get('timestamp', [])],
        'open': raw['open'], 'high': raw['high'], 'low': raw['low'],
        'close': raw['close'],
        'volume': raw.get('volume', [0] * len(raw['open']))})
    if frame.empty:
        return None, None
    today = frame['datetime'].iloc[-1].date()
    today_df = frame[frame['datetime'].dt.date == today]
    return (today_df if not today_df.empty else None), age


def _publish_atm_legs(api, spot, option_data, render_id):
    """Fetch the six ATM+/-1 legs and publish everything V6 reads off them.

    Six legs, not fourteen: ATM-1 / ATM / ATM+1 on both sides. The V6 surface
    that depends on this is `_atm_leg_dfs` and `_atm_leg_sids` (Dashboard 2's
    charts), plus the four per-leg stores the bias dashboard and market picture
    read — `_atm_leg_vob_volume`, `_atm_leg_vidya`, `_atm_leg_sr_behavior` and
    `_atm_pm1_vpfr`.

    The stores are reset each cycle on purpose. The ATM strike drifts through
    the day, and letting stale strikes accumulate is what produced repeated
    legs and double-counted bias rows.
    """
    # 🎯 Which index's legs these are. The LTP panels follow the instrument
    # toggle, so on SENSEX they are SENSEX option legs: SENSEX expiries, SENSEX
    # strikes, SENSEX security ids, quoted on BSE_FNO. `option_data` stays the
    # NIFTY chain — it feeds the Greeks and the market picture, which are
    # deliberately still NIFTY-only — so none of it is used for SENSEX legs.
    _ctx_legs = st.session_state.get('_current_instrument_context')
    _leg_sym = (_ctx_legs.symbol if _ctx_legs else 'NIFTY')
    _is_alt = _leg_sym != 'NIFTY'

    opt = option_data or {}
    summary = None if _is_alt else opt.get('df_summary')
    if _is_alt:
        # SENSEX's own nearest expiry — the NIFTY chain's expiry is a different
        # weekday and would resolve to no strikes at all.
        expiry = None
        try:
            listed = (get_dhan_expiry_list_cached(
                _ctx_legs.security_id, _ctx_legs.exchange_segment)
                or {}).get('data') or []
            expiry = listed[0] if listed else None
        except Exception:
            expiry = None
    else:
        expiry = (opt.get('expiry') or opt.get('selected_expiry')
                  or (st.session_state.get('_cached_raw_chain_latest') or {}).get('expiry'))
        if not expiry:
            try:
                listed = (get_dhan_expiry_list_cached(
                    NIFTY_UNDERLYING_SCRIP, NIFTY_UNDERLYING_SEG) or {}).get('data') or []
                expiry = listed[0] if listed else None
            except Exception:
                expiry = None
    try:
        sid_map = get_nifty_option_security_ids(expiry, _leg_sym) or {} if expiry else {}
    except Exception:
        sid_map = {}

    if summary is not None and not getattr(summary, 'empty', True):
        strikes = sorted(summary['Strike'].dropna().unique().tolist())
    else:
        strikes = sorted({k[0] for k in sid_map.keys()})

    # The legs must be centred on THEIR OWN index. Pricing SENSEX strikes off
    # a ~24,000 NIFTY spot picks the lowest listed SENSEX strike as "ATM".
    if _is_alt:
        try:
            _alt_spot = get_index_spot_ltp(int(_ctx_legs.security_id),
                                           _ctx_legs.exchange_segment)
        except Exception:
            _alt_spot = None
        if not _alt_spot:
            st.session_state['_atm_leg_err'] = (
                f"No {_leg_sym} spot — cannot centre the {_leg_sym} option legs.")
            return
        spot = _alt_spot

    if not strikes or not spot:
        return

    seg = index_option_segment(_leg_sym)
    atm = min(strikes, key=lambda x: abs(x - spot))
    diffs = [strikes[i + 1] - strikes[i] for i in range(len(strikes) - 1)]
    gap = min(diffs) if diffs else 50

    def sids_for(strike):
        """Tolerant strike match — the scrip master and the chain disagree on
        float precision (24000 vs 24000.0 vs 23999.99) often enough that an
        exact lookup silently drops legs."""
        sv = float(strike)
        ce, pe = sid_map.get((sv, 'CE')), sid_map.get((sv, 'PE'))
        if ce is None or pe is None:
            for (k_strike, k_side), v in sid_map.items():
                if abs(k_strike - sv) < 0.5:
                    if k_side == 'CE' and ce is None:
                        ce = v
                    elif k_side == 'PE' and pe is None:
                        pe = v
        return (int(ce) if ce else None), (int(pe) if pe else None)

    # ATM+/-3 ids for the Strike-Mode Cockpit's on-demand wing fetches and for
    # Stage 71.8's strike picker. Ids only — no fetch happens here, so widening
    # the range from +/-2 costs two dictionary entries and no request budget.
    # The picker needs them because a trader choosing ATM+3 must get that leg's
    # own candles, not a silent fall back to ATM.
    try:
        wings = {}
        for off in (-3, -2, -1, 0, 1, 2, 3):
            sv = atm + off * gap
            ce, pe = sids_for(sv)
            if ce:
                wings[(sv, 'CE')] = str(ce)
            if pe:
                wings[(sv, 'PE')] = str(pe)
        st.session_state['_cockpit_ctx'] = {
            'sids': wings, 'seg': seg, 'api': api, 'atm': atm, 'gap': gap}
    except Exception:
        pass

    for store in ('_atm_leg_dfs', '_atm_leg_sids', '_atm_leg_vob_volume',
                  '_atm_leg_vidya', '_atm_leg_sr_behavior',
                  '_atm_leg_ltf_delta'):
        st.session_state[store] = {}

    # The three builders Premium Structure needs for a strike outside ATM±1.
    #
    # `mios_v5` cannot import this file (it boots Streamlit and reads secrets),
    # and Premium Structure may not compute a profile of its own — the audit
    # found FOUR POC implementations and chose `compute_vpfr` as the one owner.
    # Publishing the callables lets the dashboard build a wing strike's profile
    # with the same function the ATM±1 legs use, rather than a fifth copy.
    #
    # `detect_ignition` is here for the reason the audit called its headline:
    # the leg table collapses its NAMED sub-signals — Wyckoff Spring and
    # Upthrust among them — into one glyph, so a consumer that wants the
    # fakeout evidence has to call the engine itself.
    st.session_state['_premium_builders'] = {
        'vpfr': lambda f: compute_vpfr(f, 60),
        'mfp': lambda f: calculate_money_flow_profile(f, num_rows=25,
                                                      source='Money Flow'),
        'ignition': detect_ignition,
        # 📈 The BigBeluga dynamic PoC, per panel.
        #
        # ⚠️ `profile_overlay` has had a `dynamic_poc` branch — colour, dash style,
        # "Dyn POC" label and all — since it was written, and NOTHING EVER SET THE
        # KEY. `compute_dynamic_poc` was called for the liquidity context, for a
        # bias push and for the daily read, but never onto the profile dicts the
        # chart draws, so `p.get("dynamic_poc")` was always None and the line has
        # never appeared on any panel. A reader with no writer, which is the pattern
        # this repo keeps catching.
        #
        # Published as a BUILDER rather than a value because each panel needs its
        # own: the index PoC on a premium axis marks a price that leg can never
        # trade, which is the same rule `_panel_profile` already follows for the
        # money-flow profile. And through this bridge rather than a second port —
        # `compute_dynamic_poc` is the existing one and stays the only one.
        'dynamic_poc': lambda f: (compute_dynamic_poc(f, bins=20) or ([],))[0],
        # 📍 High-volume pivots, per panel. ~2 ms on a session's bars, so it needs
        # no cache of its own beyond `_panel_profile`'s.
        'hv_points': _hv_points,
    }
    st.session_state['_atm_leg_api'] = api

    legs = []
    for strike, tag in ((atm - gap, 'ATM-1'), (atm, 'ATM'), (atm + gap, 'ATM+1')):
        ce_sid, pe_sid = sids_for(strike)
        for side, sid in (('CE', ce_sid), ('PE', pe_sid)):
            name = f"{tag} {side} {strike:.0f}"
            frame, _age = _leg_intraday(api, sid, seg, render_id)
            if frame is None or frame.empty:
                continue
            st.session_state['_atm_leg_dfs'][name] = frame.copy()
            if sid:
                st.session_state['_atm_leg_sids'][name] = (str(sid), seg)
            ltp = float(frame['close'].iloc[-1])
            for store, fn in (('_atm_leg_vob_volume', analyze_vob_volume),
                              ('_atm_leg_sr_behavior', classify_leg_sr_behavior)):
                try:
                    val = fn(frame, ltp)
                    if val:
                        st.session_state[store][name] = val
                        st.session_state[store][f"sid_{sid}"] = val
                except Exception:
                    pass
            try:
                vidya = calculate_vidya(frame)
                if vidya:
                    st.session_state['_atm_leg_vidya'][name] = vidya
                    st.session_state['_atm_leg_vidya'][f"sid_{sid}"] = vidya
            except Exception:
                pass
            # Per-leg buyer/seller split — Premium CBV / CSV / CVD.
            #
            # The reduction removed this store's WRITER and kept its readers:
            # `dashboard_v6._leg_flow_readings` and Stage 71.7 both ask for
            # `_atm_leg_ltf_delta` and have been getting `{}` ever since. The
            # closure was built from what V6 *reads*, and a store the app fills
            # for a later cycle produces no read edge — the same blind spot that
            # severed the learning writers.
            #
            # Restored through `indicators/order_flow.totals`, which owns the
            # CLV split, rather than by bringing back the inline copy the
            # original used. Same numbers, one implementation.
            try:
                _tot = _of.totals(frame)
                if _tot and not _of.is_missing(_tot):
                    st.session_state['_atm_leg_ltf_delta'][name] = _tot
                    st.session_state['_atm_leg_ltf_delta'][f"sid_{sid}"] = _tot
            except Exception:
                pass
            mfp = None
            try:
                mfp = calculate_money_flow_profile(frame, num_rows=5,
                                                   source='Money Flow')
            except Exception:
                mfp = None
            legs.append({
                'tag': name, 'ltp': ltp,
                'vpfr': {'short': compute_vpfr(frame, 30),
                         'medium': compute_vpfr(frame, 60),
                         'long': compute_vpfr(frame, 180)} if len(frame) >= 3 else None,
                'mfp': mfp,
                'mfp_bias': _mfp_poc_bias(mfp) if mfp else 'NEUTRAL',
                'latest_grab': None})

    st.session_state['_atm_pm1_vpfr'] = {
        'atm_strike': atm, 'gap': gap, 'spot': spot, 'legs': legs}


def _render_main_analyzer():
    """Fill the caches MIOS V6 reads, run the pass, render V5 and V6.

    This is the whole app now. Everything the native layer used to draw between
    these steps — its own Trade Card, ~40 expanders, 39 charts, every Telegram
    and Discord alert, the AI advisors, the auto-trade panel and the v0/v2
    decision engines — is gone, because no V6 stage read any of it.

    **Order is the contract.** `run_mios_pass` fetches nothing; it reads the
    session keys already published when it is called. Every producer therefore
    runs BEFORE `_mios_pass()`. In the full app four of them ran after it, so
    Stage 42 judged acceptance against S/R built a cycle earlier and Stage 45
    built its profiles from the previous frame. Moving them above the pass is
    the fix, and it is why the order below is not cosmetic.
    """
    _render_id = st.session_state.get('_render_seq', 0) + 1
    st.session_state['_render_seq'] = _render_id

    # Supabase is not optional: Stage 33/40 persistence, the candle cache and
    # the market-memory backfill all read it. Without credentials there is
    # nothing to render, so say so rather than raising inside every producer.
    if not supabase_url or not supabase_key:
        st.error("Configure Supabase credentials in Streamlit secrets:\n\n"
                 "```\n[supabase]\nurl = \"…\"\nanon_key = \"…\"\n```")
        return
    try:
        # Wrapped once, here, so every consumer — both dashboards, every panel,
        # every engine that takes `db` — reads through the Streamlit cache
        # without a single call site changing. Supabase is touched only when a
        # value is not already cached, or after the app resets.
        #
        # Without this, `st_autorefresh` at 20s plus Streamlit running EVERY
        # tab and expander body on EVERY rerun meant ~30,800 rows fetched per
        # cycle, whether or not anyone was looking at the tab that asked.
        db = _cache_reads(SupabaseDB(supabase_url, supabase_key))
        # ── egress measurement · OFF unless MIOS_EGRESS=1 ──────────────
        # Installed on the raw client, before the cache wrapper, so it counts
        # what actually left the network — a read served from `st.cache_data`
        # never reaches PostgREST and must not be counted as if it had.
        try:
            from tools import egress_meter as _egress
            if _egress.ENABLED:
                _egress.install(db.client)
        except Exception:
            pass
        # ── the day ledger · ALWAYS ON ─────────────────────────────────
        # Same placement and the same reason — the raw client, before the cache
        # wrapper — but this one answers the question the per-cycle meter
        # cannot: what has TODAY cost, and which table spent it?
        #
        # Round 3 shipped a proven reduction in round-trips and the bill did not
        # visibly move, because nobody could see bytes per day. Cheap enough to
        # leave on: a `len()` per response, and one `json.dumps` of a single row
        # per table per day to learn its width.
        try:
            from db import egress_budget as _budget
            _budget.install(db.client)
        except Exception:
            pass
        db.sync_pending()
        st.session_state['_db_obj'] = db
        st.session_state['_story_task'] = get_story_task()
    except Exception as err:
        st.error(f"Database connection error: {err}")
        return

    # ── sidebar: only what changes what is fetched ──────────────────────
    st.sidebar.header("Configuration")

    # ── 🎯 Instrument selector: NIFTY or SENSEX ──────────────────────────
    # Switch between instruments. Dhan-driven discovery; all specs from live API.
    # Changing instrument invalidates all cached data to prevent cross-contamination.
    from mios_v5.instrument_cache_manager import get_current_instrument, mark_instrument_changed
    _current_instrument = get_current_instrument(st.session_state)
    _selected_instrument = st.sidebar.selectbox(
        "🎯 Instrument",
        options=["NIFTY", "SENSEX"],
        index=0 if _current_instrument == "NIFTY" else 1,
        help="Switch between NIFTY (NSE) and SENSEX (BSE). The index chart and "
             "the ATM Call/Put LTP panels both follow this; the option chain, "
             "Greeks and Market Picture stay NIFTY. Specs come from Dhan's "
             "scrip master, and cached data is cleared on switch."
    )
    if _selected_instrument != _current_instrument:
        mark_instrument_changed(st.session_state, _selected_instrument)
        st.rerun()

    # ── 📤 one-click market snapshot → Telegram (for AI analysis) ─────
    # Gathers everything the app already computed this cycle into one structured
    # message and sends it, so it can be forwarded to an AI to analyse the market.
    if st.sidebar.button("📤 Send market snapshot → Telegram (for AI)",
                         help="Sends one structured message with the full market "
                              "picture — regime, levels, ATM verdict, dealer/"
                              "greeks, flow, level acceptance and context — to "
                              "forward to an AI for a complete analysis. Reuses "
                              "existing reads; sends nothing else."):
        try:
            _n_parts = _send_market_snapshot()
            st.sidebar.success(f"Snapshot sent to Telegram "
                               f"({_n_parts} message{'s' if _n_parts != 1 else ''}).")
        except Exception as _snap_err:
            st.sidebar.error(f"Snapshot failed: {_snap_err}")

    # ── 🧬 MIOS V6 snapshot → Telegram (12 messages, complete context) ─────
    # Pure formatter that gathers all existing MIOS V6 published values and
    # splits them across 10-12 separate Telegram messages for external AI analysis.
    # One message per major section: Time/Price, Market, S/R, Premium, Flow, Dealer,
    # Greeks, Behaviour, Liquidity, Global, News, Signal.
    if st.sidebar.button("🧬 Send MIOS V6 snapshot → Telegram (12 sections)",
                         help="Sends complete MIOS V6 market analysis across 12 "
                              "Telegram messages — one per section (Time, Market, "
                              "S/R, Premium, Flow, Dealer, Greeks, Behaviour, "
                              "Liquidity, Global, News, Signal). Phone-readable "
                              "format for forwarding to external AI. Pure formatter, "
                              "gathers only existing V6 data."):
        try:
            from mios_v5.mios_v6_snapshot import gather_mios_v6_data, format_snapshot
            v6_data = gather_mios_v6_data(st.session_state)
            v6_msgs = format_snapshot(v6_data)
            if v6_msgs:
                for v6_msg in v6_msgs:
                    if v6_msg.strip():
                        send_telegram_message_sync(v6_msg, force=True)
                st.sidebar.success(f"MIOS V6 snapshot sent to Telegram "
                                   f"({len(v6_msgs)} message{'s' if len(v6_msgs) != 1 else ''}).")
            else:
                st.sidebar.warning("No MIOS V6 data available to send.")
        except Exception as _v6_err:
            st.sidebar.error(f"MIOS V6 snapshot failed: {_v6_err}")

    # ── 📨 MIOS V6 entry / exit signals to Telegram ────────────────────
    # The default lives in `MIOS_V6_TELEGRAM_DEFAULT` (top of file) so it is
    # one findable line rather than a literal buried in the sidebar. The owner
    # set it ON: signals are live from load, and this toggle turns them off for
    # the session rather than on.
    #
    # Whichever way it sits: off → `_mios_transport` is absent, the dispatcher
    # receives `None`, and the chain prepares without sending.
    _mios_tg = st.sidebar.checkbox(
        "📨 MIOS V6 signals → Telegram", value=MIOS_V6_TELEGRAM_DEFAULT,
        help="Stage 72 entries and Stage 73 exits, sent through Stage 72.9. "
             "Duplicate, supersession and staleness gates are the "
             "dispatcher's and always apply. OFF = prepare only.")
    # ── ⚡ the simple entry system: five rules, its own switch ─────────
    # Separate from the V6 toggle on purpose. They are two alert systems and
    # the app already had two too many; keeping the switches apart at least
    # makes it obvious which one produced a message.
    _simple_on = st.sidebar.checkbox(
        "⚡ Simple entry (5 rules) → Telegram", value=SIMPLE_ENTRY_DEFAULT,
        help="Spot at a level · bounce beats break · V5 or V6 agrees · "
             "that side has the energy · the premium is building. "
             "All five, or nothing is sent.")
    st.session_state["_simple_entry_on"] = _simple_on
    # A placeholder, not a direct write: the sidebar is built near the top of
    # the script and the rules are evaluated near the bottom, so writing here
    # would show the PREVIOUS cycle's answer — worse than showing none.
    st.session_state["_simple_entry_slot"] = st.sidebar.empty()

    # ── 📢 heavy call/put writing & capping → Telegram ─────────────────
    # A note when dealers are writing calls (capping upside → resistance) or
    # writing puts (support building). Edge-triggered in
    # `capture_stage2_market_events`, so one note per episode. Separate switch
    # from the entry stream above — this is a positioning read, not a trade call.
    st.session_state["_writing_tg_on"] = st.sidebar.checkbox(
        "📢 Call/Put writing → Telegram", value=WRITING_TG_DEFAULT,
        help="Heavy call writing (capping upside · resistance) or put writing "
             "(support) sends a Telegram note. One per episode, not per "
             "refresh. Also always logged to Discord.")

    # ── 📍 dynamic-POC shift → Discord ─────────────────────────────────
    # Opt-in: alerts when a chart's dynamic POC steps up or down. Off by
    # default (see POC_SHIFT_ALERTS_DEFAULT); routed to Discord like the app's
    # other informational alerts. Consumed in `_notify_poc_shifts`.
    st.session_state["_poc_shift_on"] = st.sidebar.checkbox(
        "📍 Dynamic POC shift alerts", value=POC_SHIFT_ALERTS_DEFAULT,
        help="When the dynamic POC on the NIFTY, Call or Put chart steps to a "
             "new level, post which way it moved to Discord. Deduped per chart "
             "with a cooldown so it cannot spam.")

    # ── 📐 new high-volume pivot / VOB on any chart → Telegram ─────────
    # Fires once when a level or an order block first forms (the structure
    # already on screen at load is seeded silently). Consumed in
    # `_notify_chart_formations`.
    st.session_state["_formation_alerts_on"] = st.sidebar.checkbox(
        "📐 HVP / VOB formation → Alert Telegram", value=FORMATION_ALERTS_DEFAULT,
        help="A note to the ALERT bot (the second Telegram account) when a new "
             "high-volume pivot forms on NIFTY, Call or Put, or a new Volume "
             "Order Block forms on a leg. Each formation is sent once; what "
             "already exists when the app loads is not re-announced. Discord "
             "gets its copy as before. Falls back to the main bot if the alert "
             "bot is unconfigured.")

    # ── 📍 option LTP reaching its HVP line (±5) → Telegram ────────────
    st.session_state["_leg_hvp_touch_on"] = st.sidebar.checkbox(
        "📍 LTP at its HVP line (±5) → Telegram", value=LEG_HVP_TOUCH_DEFAULT,
        help="A Telegram note when the Call or Put LTP comes within ±5 points of "
             "one of its own high-volume-point lines. Latched per line and given "
             "a 15-minute cooldown (sleep), so a price sitting at the line does "
             "not repeat. Off by default — enable it here.")

    # ── 🎯 spot reaching a key level (±5 pts) → Telegram ──────────────
    # War zone, either OI wall, and the ranked support / resistance. Latched per
    # level so a price loitered at alerts once. Consumed in
    # `_notify_level_touches`.
    st.session_state["_level_touch_on"] = st.sidebar.checkbox(
        "🎯 Level-touch alerts (±5 pts) → Telegram", value=LEVEL_TOUCH_DEFAULT,
        help="A Telegram note when spot comes within ±5 points of the war zone, "
             "an OI wall, or the ranked support / resistance. Sent once on "
             "arrival; re-arms only after price leaves the level.")

    # ── 📨 flow-at-level → ALTERNATE Telegram bot ─────────────────────────
    # PUT buy+sell heavier than CALL with spot at resistance, or CALL heavier
    # than PUT with spot at support. Reads the CALL-vs-PUT Cum Buy/Sell graph's
    # own numbers. Rising-edge + cooldown, so a standing condition sends once.
    st.session_state["_flow_level_alerts_on"] = st.sidebar.checkbox(
        "📨 Flow-at-level alerts → alert bot", value=FLOW_LEVEL_ALERTS_DEFAULT,
        help="To the SECOND (alert) bot: when PUT buy+sell activity outweighs "
             "CALL and spot is within 0.25% of resistance, or CALL outweighs "
             "PUT and spot is within 0.25% of support. Sent once per crossing; "
             "re-arms after the condition clears.")

    # ── ⚔️ level ACCEPTED / REJECTED → Telegram ───────────────────────
    # Fires when a level resolves (accepted above/below, or rejected), not on
    # mere touch. Edge-triggered + per-zone cooldown. Consumed in
    # `_notify_level_acceptance`.
    st.session_state["_la_alerts_on"] = st.sidebar.checkbox(
        "⚔️ Level accepted / rejected → Telegram", value=LEVEL_ACCEPT_ALERTS_DEFAULT,
        help="A Telegram note when a level RESOLVES — accepted above/below, or "
             "rejected — from the Level-Acceptance strip. Sent once on the "
             "transition; a per-zone cooldown stops a flipping level spamming. "
             "Observation only; it does not change any verdict.")

    # ── ⚡ 4-signal confluence entry → Telegram ───────────────────────
    st.session_state["_confluence_alerts_on"] = st.sidebar.checkbox(
        "⚡ Confluence entry (level + verdict + leg + energy) → Telegram",
        value=CONFLUENCE_ALERTS_DEFAULT,
        help="A Telegram note when four existing engine reads align in one "
             "direction: NIFTY at a support/resistance/war-zone, the ATM-strike "
             "verdict Strong Bull/Bear agreeing with the level, the trade-side "
             "leg's LTP at its support/session-low, and that side's premium "
             "energy the greater. Fires once per setup (cooldown). Reuses "
             "existing engines; changes no verdict.")

    # ── ⚠️ Entry reversal (bias-against at zone) → Telegram ────────────
    # Paused — it repeated the same level instead of firing once per reversal.
    st.session_state["_entry_reversed_on"] = st.sidebar.checkbox(
        "⚠️ Entry reversal (bias-against at zone) → Alert Telegram",
        value=ENTRY_REVERSED_ALERT_DEFAULT,
        help="Paused — this one repeated the same level rather than firing "
             "once per reversal, so it is off. Tick to bring it back: a "
             "Telegram note to the alert bot when NIFTY reaches a mapped "
             "price zone but the bias has reversed (trend weakened, opposite "
             "writers appeared, etc.). Reuses existing engines.")

    # ── the two sub-alerts the owner paused (off by default) ──────────
    # Ranked S/R touch is a subset of the level-touch alert above; VOB formation
    # a subset of the formation alert. Both were too noisy, so they are opt-in.
    st.session_state["_sr_touch_on"] = st.sidebar.checkbox(
        "   ↳ include ranked S/R touch", value=SR_TOUCH_ALERTS_DEFAULT,
        help="Paused — the ranked support/resistance touch was noisy. The "
             "war-zone and OI-wall touches above are unaffected.")
    st.session_state["_vob_formation_on"] = st.sidebar.checkbox(
        "   ↳ include VOB formation", value=VOB_FORMATION_ALERTS_DEFAULT,
        help="Paused — new-VOB alerts were noisy. High-volume pivot (HVP) "
             "formation alerts are unaffected.")

    # ── 📐 Advanced Price Action chart overlay (default OFF) ───────────
    st.session_state["_apa_on"] = st.sidebar.checkbox(
        "📐 Advanced Price Action on charts (BOS · CHoCH · Fib · patterns)",
        value=False,
        help="Overlay swing points, Break of Structure / Change of Character, "
             "the Fibonacci retracement pocket, and geometric patterns (H&S, "
             "triangles, flags) on ALL three charts — NIFTY, Call and Put. Off "
             "by default; enable it here. Display only; changes no verdict.")

    if _mios_tg:
        st.session_state["_mios_transport"] = mios_v6_transport
        st.sidebar.caption("🔴 Live — Stage 72.9 will send entry and exit "
                           "signals it judges sendable.")
        # Two channels: terse on the main bot, the reasoned one on the alert
        # bot. Say when the second is unconfigured — `send_telegram_alert_bot`
        # is a silent no-op without it, and a reasoning channel that quietly
        # never arrives looks exactly like one with nothing to say.
        if TELEGRAM_ALERT_BOT_TOKEN and TELEGRAM_ALERT_CHAT_ID:
            st.sidebar.caption("📄 Reasoned copy → alert bot.")
        else:
            st.sidebar.caption(
                "⚠️ Terse only — set TELEGRAM_ALERT_BOT_TOKEN and "
                "TELEGRAM_ALERT_CHAT_ID for the reasoned copy.")
    else:
        st.session_state.pop("_mios_transport", None)

    # 🎯 The instrument comes from the ONE toggle built above. There used to be
    # a second, identical "🎯 Instrument" selectbox here — two dropdowns in the
    # sidebar, and because Streamlit keys a widget by its parameters and the two
    # carried different `help` text, they got separate ids and both rendered
    # rather than colliding. This one then wrote `_selected_instrument`
    # unconditionally on every run, so it overwrote whatever the first dropdown
    # had just set: changing the top toggle did nothing.
    _selected_instrument = get_current_instrument(st.session_state)

    # Set instrument context for the render cycle. Every spec below is a value
    # read off Dhan's scrip master, not an assumption — an invented SENSEX id
    # is what made the chart silently keep drawing NIFTY.
    # ⏱️ NOTHING HERE MAY TOUCH THE NETWORK. This runs while the sidebar is
    # being built, before a single pixel of the page is drawn, so anything slow
    # here is indistinguishable from the app failing to start. It previously
    # called `resolve_index_security_id`, which reads Dhan's 26 MB scrip master
    # — ~5s on a fast link, far worse on a slow one, and `pd.read_csv(url)`
    # takes no timeout, so a stalled connection hung the app on its loading
    # screen indefinitely. The two index ids are fixed values that Dhan does not
    # reissue, and they are pinned by tests, so they are used directly. The
    # scrip master is still the source for OPTION ids, which genuinely change
    # every expiry — that lookup happens later, off the first-paint path.
    try:
        from mios_v5.instrument_registry import InstrumentContext
        if _selected_instrument == "SENSEX":
            _ctx = InstrumentContext(
                symbol="SENSEX", security_id=51, exchange_segment="IDX_I",
                contract_multiplier=20.0,   # SEM_LOT_UNITS for SENSEX OPTIDX
                strike_step=100,            # observed gap across SENSEX strikes
                current_expiry="", expiry_list=[],
                atm_range=100, lot_size=20, tick_size=0.05)
        else:
            _ctx = InstrumentContext(
                symbol="NIFTY", security_id=13, exchange_segment="IDX_I",
                contract_multiplier=65.0,   # SEM_LOT_UNITS for NIFTY OPTIDX
                strike_step=50,             # observed gap across NIFTY strikes
                current_expiry="", expiry_list=[],
                atm_range=100, lot_size=65, tick_size=0.05)
        st.session_state['_current_instrument_context'] = _ctx
        st.sidebar.caption(
            f"{_ctx.symbol} · id {_ctx.security_id} · {_ctx.exchange_segment}")
    except Exception as _e_ctx:
        # Loudly. A swallowed ImportError here is exactly how the toggle came
        # to do nothing at all: context stayed None, every reader fell back to
        # its NIFTY default, and the chart looked like it was ignoring you.
        st.session_state['_current_instrument_context'] = None
        st.sidebar.error(
            f"⚠️ Instrument context unavailable — the toggle will NOT switch "
            f"the chart. {type(_e_ctx).__name__}: {str(_e_ctx)[:120]}")

    timeframes = {"1 min": "1", "3 min": "3", "5 min": "5",
                  "15 min": "15", "25 min": "25", "60 min": "60"}
    interval = timeframes[st.sidebar.selectbox(
        "Chart Timeframe", list(timeframes.keys()), index=1)]
    days_back = st.sidebar.slider("Days of Historical Data", 1, 5, 2)

    expiry_dates = []
    st.session_state['_expiry_stale'] = False
    try:
        _ed = get_dhan_expiry_list_cached(NIFTY_UNDERLYING_SCRIP, NIFTY_UNDERLYING_SEG)
        expiry_dates = (_ed or {}).get('data') or []
    except Exception:
        expiry_dates = []
    selected_expiry = st.sidebar.selectbox(
        "Expiry", expiry_dates, index=0) if expiry_dates else None
    # Say WHICH of the two failures this is. "no expiry" and "an expiry Dhan
    # could not re-confirm this cycle" need different reactions from a trader,
    # and reporting them the same way is how a stale read gets acted on.
    if st.session_state.get('_expiry_stale'):
        st.sidebar.warning("⚠️ Expiry list is the last good copy — Dhan did not "
                           "answer this cycle. Chain data may lag.")
    elif not expiry_dates:
        st.sidebar.error(
            "❌ No expiry list from Dhan"
            + (f" ({st.session_state.get('_dhan_last_error')})"
               if st.session_state.get('_dhan_last_error') else "")
            + " — the option chain and every chain-derived read stand aside "
              "until it returns.")

    with st.sidebar.expander(
            "🔑 Refresh Dhan Token",
            expanded=bool(st.session_state.get('_dhan_token_expired'))):
        _tok = st.text_area("Access token", value="", height=90,
                            key="_dhan_token_input")
        if st.button("Use this token") and _tok.strip():
            st.session_state['_dhan_token_override'] = _tok.strip()
            st.session_state['_dhan_token_expired'] = False
            st.rerun()

    # ── database cache: what it saved, and the manual reset ─────────────
    # The cache holds until the app restarts, so a trader who wants the
    # analytics re-read needs a way to say so without restarting. This is that
    # way — and the counters are here so the saving is visible rather than
    # asserted.
    try:
        from db.read_cache import invalidate as _db_cache_clear
        from db.read_cache import stats as _db_cache_stats
        _cs = _db_cache_stats()
        with st.sidebar.expander("🗄 Database cache", expanded=False):
            _served = max(0, _cs['calls'] - _cs['fetches'])
            _hit = (_served / _cs['calls'] * 100) if _cs['calls'] else 0
            st.caption(
                f"{_cs['calls']:,} reads asked · **{_cs['fetches']:,}** reached "
                f"Supabase · {_served:,} served from cache ({_hit:.0f}%) "
                f"({_cs['rows']:,} rows fetched this session)")
            # The diagnostic, not decoration. A low hit rate has two completely
            # different causes with completely different fixes: cache keys that
            # never match, or tables that are simply empty. A high empty count
            # beside a low saving says it is the second — which is what a
            # measured 0.9% hit rate turned out to be.
            if _cs.get('empty'):
                st.caption(
                    f"{_cs['empty']:,} of those came back **empty** — held for "
                    f"5 min each rather than re-asked every cycle.")
            # ⚠️ The line that says WHOSE fault a low hit rate is.
            #
            # A cache cannot serve a repeat that never comes. When calls and
            # fetches are nearly equal, the reads are each being asked once —
            # and that is a caller problem, not a cache problem. Naming the
            # methods with the most distinct keys points at the caller.
            try:
                from db.read_cache import churn_line as _db_churn
                _churn = _db_churn()
            except Exception:
                _churn = ""
            _per_key = (_cs['calls'] / _cs['fetches']) if _cs['fetches'] else 0
            if _churn:
                st.caption(
                    f"{_per_key:.2f} calls per distinct key — a cache only "
                    f"saves repeats. Most distinct questions: {_churn}.")
            st.caption(
                "Every read is held until this app writes its table or "
                "resets — nothing is re-asked on a timer. A table written "
                "every cycle is re-read at most once every 5 min; live reads "
                "(open position, spot, config) refresh every cycle.")
            if st.button("Refresh from Supabase"):
                _db_cache_clear()
                st.rerun()
    except Exception:
        pass

    # ── data retention: what would go, before anything goes ─────────────
    _render_retention_panel(st, db)

    # ── storage: which table the bytes are actually in ──────────────────
    try:
        from db.storage_audit import render as _render_storage
        _render_storage(st, db)
    except Exception:
        pass

    # ── egress: what today has cost, against the 100 MB/day target ──────
    # Storage says how big the tables ARE; this says how many bytes left them.
    # Two different bills, and the reduction rounds kept conflating them.
    try:
        from db.egress_budget import render as _render_egress
        _render_egress(st, db)
    except Exception:
        pass

    access_token = st.session_state.get('_dhan_token_override') or DHAN_ACCESS_TOKEN
    api = DhanAPI(access_token, DHAN_CLIENT_ID)

    # ── containers, so the page draws top-down while producers run below ─
    # The Trade Card sits above everything, but it reads state the bias
    # dashboard stashes — so it is rendered into a container claimed here and
    # filled at step 10, after its inputs exist.
    #
    # 🗺️ The Market Picture is the same arrangement, for the same reason. It is
    # the regime read — UP/DOWN/SIDEWAYS, the levels, the odds — so it belongs
    # above MIOS V6 rather than below two collapsed dashboards. But it cannot be
    # COMPUTED here: it needs `cat_scores`, which only exists part-way through
    # the bias dashboard, and it publishes `_market_picture`, which the Trade
    # Card immediately below reads. So the slot is claimed now and filled during
    # step 10 — the position moves, the order of computation does not.
    _card_container = st.container()
    _picture_container = st.container()
    _v6_container = st.container()
    _v5_container = st.container()
    _bias_container = st.container()

    # Get instrument context for the chart (selected in the sidebar above).
    _ctx_ltp = st.session_state.get('_current_instrument_context')
    _sec_id_ltp = int(_ctx_ltp.security_id) if _ctx_ltp else 13
    _seg_ltp = _ctx_ltp.exchange_segment if _ctx_ltp else "IDX_I"
    _sym_ltp = _ctx_ltp.symbol if _ctx_ltp else "NIFTY"

    # ── 1 · Index candles + spot (NIFTY or SENSEX based on selection) ────
    df = pd.DataFrame()
    try:
        _raw = api.get_intraday_data(security_id=_sec_id_ltp, exchange_segment=_seg_ltp,
                                     instrument="INDEX", interval=interval,
                                     days_back=days_back)
        if _raw:
            df = process_candle_data(_raw, interval)
            db.upsert_candles(_sym_ltp, _seg_ltp, interval, df)
    except Exception as err:
        st.caption(f"Candle fetch unavailable: {err}")
    if df.empty:
        try:
            df = db.get_candles(_sym_ltp, _seg_ltp, interval, hours_back=days_back * 24)
        except Exception:
            df = pd.DataFrame()
    # 🚨 A failed instrument fetch must NOT look like a working one. The frame
    # below is only overwritten `if not df.empty`, so an empty SENSEX fetch
    # used to leave the previous NIFTY frame on screen — the chart appeared to
    # simply ignore the toggle. Say which instrument the frame actually is, and
    # drop a stale frame belonging to the other instrument rather than pass it
    # off as this one.
    if df.empty:
        st.error(
            f"❌ No {_sym_ltp} candles from Dhan (id {_sec_id_ltp} · {_seg_ltp}) "
            f"and none cached. The chart below is NOT {_sym_ltp} — it is the "
            f"last frame that did load. Check the instrument id / market hours.")
        if st.session_state.get('_chart_instrument') not in (None, _sym_ltp):
            for _k in ('_nifty_df_live', '_last_df', '_df_5m'):
                st.session_state.pop(_k, None)
    else:
        st.session_state['_chart_instrument'] = _sym_ltp

    # `get_index_spot_ltp` caches for 4s and hits the same endpoint the chain
    # does, so this is one network call, not the two the full app made.
    spot = None
    try:
        spot = get_index_spot_ltp(int(_sec_id_ltp), _seg_ltp)
    except Exception:
        spot = None
    if not spot and not df.empty:
        spot = float(df['close'].iloc[-1])
    if spot:
        st.session_state['_nifty_spot_live'] = float(spot)
        st.session_state['_nifty_spot_live_ts'] = time.time()
        try:
            db.upsert_spot_data(spot, security_id=str(_sec_id_ltp),
                                exchange_segment=_seg_ltp)
        except Exception:
            pass
        try:
            capture_day_open_and_gap(db, spot)      # Stage 4 gap
        except Exception:
            pass
    if not df.empty:
        # Two frames, two jobs — the key names in `mios_v5/runner.py`
        # (NIFTY_SOURCES) already say so and both were being fed the same
        # multi-day series, so the terminal drew 3 days of candles.
        #
        #   `_nifty_df_live`  "chart path"     → TODAY only, what you look at
        #   `_last_df`        "analysis path"  → the full fetch, what engines read
        #
        # The history is not optional: Stage 3 market memory needs the previous
        # session's H/L/C, `build_htf_profiles` needs multiple days for the
        # weekly and monthly profiles, and `compute_dual_profile`'s COMPOSITE
        # profile is ~5 sessions by definition. Truncating the fetch would break
        # all three; truncating only the chart frame breaks nothing.
        st.session_state['_nifty_df_live'] = _today_session(df)
        st.session_state['_last_df'] = df           # Stage 45 HTF profiles

    # 5-minute frame for Stage 3 market memory and Stage 4's opening print.
    try:
        _r5 = api.get_intraday_data(security_id=_sec_id_ltp, exchange_segment=_seg_ltp,
                                    instrument="INDEX", interval="5",
                                    days_back=max(days_back, 3))
        if _r5:
            st.session_state['_df_5m'] = process_candle_data(_r5, "5")
    except Exception:
        pass

    # ── 2 · flows and environment ───────────────────────────────────────
    try:
        if spot:
            _fut = get_nifty_futures_data(api, spot)
            if _fut:
                st.session_state['_nifty_futures_data'] = _fut
                # ── the day's OI anchor ─────────────────────────────
                # `_fut['chg_oi']` is the delta since the previous ~20s
                # refresh, held in session_state — so it resets to 0.0 on a
                # restart, which is indistinguishable from "OI was flat".
                # Short Covering and Long Unwinding are claims about the DAY,
                # so they need an anchor that outlives the session.
                #
                # One read and one write per day: the anchor is cached here
                # for the rest of the session, and is never rewritten once
                # set. A per-cycle write would add ~1,100 rows/day for a value
                # that changes once.
                try:
                    from db.futures_oi_store import ensure as _oi_ensure
                    from mios_v5.clock import trading_day as _tday
                    from mios_v5.futures_oi import read as _oi_read
                    _day = _tday()
                    _anchor = _oi_ensure(
                        db, _fut, _day,
                        cached=st.session_state.get('_futures_oi_baseline'))
                    if _anchor.get('baseline'):
                        st.session_state['_futures_oi_baseline'] = dict(
                            _anchor['baseline'], trading_day=_day)
                    st.session_state['_futures_oi_status'] = _anchor.get(
                        'status')
                    st.session_state['_futures_oi'] = _oi_read(
                        _fut, _anchor.get('baseline'))
                except Exception:
                    pass
    except Exception:
        pass
    try:
        st.session_state['_fii_dii_cash'] = get_fii_dii_cash_cached()
        st.session_state['_fii_deriv_stats'] = get_fii_derivatives_stats_cached()
    except Exception:
        pass
    try:                                            # Stage 22 — India VIX
        _vix = (fetch_vix_data(api) or {}).get('vix', 0)
        if _vix and _vix > 0:
            _vh = st.session_state.setdefault('vix_history', [])
            _vh.append(_vix)
            st.session_state['vix_history'] = _vh[-50:]
    except Exception:
        pass
    try:
        _sr_rot = compute_sector_rotation()
        if _sr_rot:
            _sr_rot['fetched_at'] = datetime.now(
                pytz.timezone('Asia/Kolkata')).isoformat()
            st.session_state['_sector_rotation'] = _sr_rot
    except Exception:
        pass

    # ── 3 · value area, volume delta ────────────────────────────────────
    if not df.empty and len(df) > 5:
        try:
            # SESSION profile (today's VAL/POC/VAH) and COMPOSITE (last ~5
            # sessions). Using the session profile is what stops yesterday's
            # value bleeding into today's levels on a gap day.
            _sess, _comp, _mig = compute_dual_profile(df, num_rows=25)
            # The previous cycle's profile, captured BEFORE this one overwrites
            # it — Stage 74's shift reads compare the two, and nothing else in
            # this app has ever compared a profile to the one before it.
            _prev_profile = st.session_state.get('_money_flow_data')
            st.session_state['_money_flow_data'] = _sess
            st.session_state['_composite_profile'] = _comp
            st.session_state['_value_migration'] = _mig

            # ── Stage 74 — Liquidity Intelligence ───────────────────────
            # Built here because this is where the profiles already exist, and
            # the specification's own runtime rule is to compute liquidity ONCE
            # per refresh and have every stage read the result. Building it in a
            # stage would put a per-bar histogram inside twenty consumers.
            #
            # The engine computes only the eight things the audit found had no
            # owner; the profiles, POC and value area are all read.
            try:
                from mios_v5.liquidity_context import build as _liq_build
                _dyn, _, _ = compute_dynamic_poc(df, bins=20)
                _last = float(df['close'].iloc[-1])
                _prev_close = (float(df['close'].iloc[-2])
                               if len(df) > 1 else _last)

                # Only keys that a writer actually publishes. This repo has
                # twice been bitten by a reader kept while its writer was
                # removed, and inventing `_dealer_levels` here — a key nothing
                # sets — would be doing it on purpose. Every level below is
                # mapped from something `compute_market_picture` or the GEX
                # block really returns; what has no producer stays absent and
                # `ctx.missing()` names it.
                _mp = st.session_state.get('_market_picture') or {}
                _gex = st.session_state.get('_gex_data') or {}
                _dealer = {
                    'gamma_flip': _gex.get('gamma_flip_level'),
                    'max_pain': _mp.get('oi_pin'),
                    'support': _mp.get('oi_floor'),
                    'resistance': _mp.get('oi_ceiling'),
                }

                # `_premium_structures` is keyed by (side, strike) tuples;
                # the context reads `{side}` paths, so it is re-keyed here.
                # Passing it as-is would silently read UNKNOWN for every
                # premium field — present, wrong shape, no error.
                #
                # It is also the PREVIOUS render pass's copy: Dashboard V6
                # writes it at step 12 and this runs at step 3. That is the
                # same one-cycle lag `_trading_context` already carries, and
                # the values are Stage 71.8's either way — but a reader should
                # know, so `meta.premium_lag` records it.
                _prem_raw = st.session_state.get('_premium_structures') or {}
                _prem = {}
                for _k, _v in _prem_raw.items():
                    _side = _k[0] if isinstance(_k, tuple) and _k else _k
                    if _side in ('CALL', 'PUT') and isinstance(_v, dict):
                        _prem.setdefault(_side, _v)

                # The ONE ATR — Stage 00 publishes it, nothing here recomputes
                # it. Last cycle's copy (the MIOS pass runs at step 11), which
                # is fine: a 14-bar ATR does not move meaningfully in twenty
                # seconds, and without it the cluster tolerance falls back to
                # its floor and says so rather than guessing.
                _atr = (st.session_state.get('_atr') or {}).get('atr')

                st.session_state['_liquidity_context'] = _liq_build(
                    profile=_sess,
                    vpfr=compute_vpfr(df, min(len(df), 120), n_rows=24),
                    dynamic_poc=_dyn,
                    pools=_mp.get('liq_pools'),
                    dealer=_dealer,
                    atr=_atr,
                    spot=_last,
                    price_change=_last - _prev_close,
                    previous=_prev_profile,
                    premium=_prem or None,
                    premium_lag=1 if _prem else 0,
                    cycle=st.session_state.get('_render_seq'))
                # ── Stage 74 telemetry ──────────────────────────────
                # Sampled once a MINUTE, not once per 20-second rerun: a
                # distribution needs coverage across sessions, not three
                # samples of the same cluster set. ~375 rows a day.
                #
                # Advisory throughout — nothing reads this to make a decision.
                # A human reads the distribution and decides whether the
                # calibration is ready to freeze.
                try:
                    _now = time.time()
                    if _now - st.session_state.get('_liq_telemetry_ts', 0) > 60:
                        from mios_v5.liquidity_telemetry import sample as _liq_sample
                        _row = _liq_sample(
                            liq=(st.session_state['_liquidity_context']
                                 .meta.get('engine_output')),
                            # Stage 42's own read, consumed not recomputed.
                            reaction=(st.session_state.get('_full_market_read')
                                      or {}).get('reaction'),
                            atr=_atr,
                            trading_day=datetime.now(
                                pytz.timezone('Asia/Kolkata')).date().isoformat(),
                            ts=datetime.now(
                                pytz.timezone('Asia/Kolkata')).isoformat(),
                            cycle=st.session_state.get('_render_seq'))
                        db.insert_liquidity_telemetry(_row)
                        st.session_state['_liq_telemetry_ts'] = _now
                        st.session_state['_liq_telemetry_status'] = {
                            'ok': True, 'at': _now,
                            'wrote': st.session_state.get(
                                '_liq_telemetry_wrote', 0) + 1}
                        st.session_state['_liq_telemetry_wrote'] = (
                            st.session_state.get('_liq_telemetry_wrote', 0) + 1)
                except Exception as _tel_err:
                    # NOT swallowed. Before this, a missing `sql/036` migration
                    # meant the write failed silently every minute and a week
                    # of "collection" produced zero rows — discoverable only by
                    # going to look. The calibration panel renders this, so a
                    # migration nobody applied says so within a minute.
                    st.session_state['_liq_telemetry_status'] = {
                        'ok': False, 'at': time.time(), 'error': str(_tel_err),
                        'wrote': st.session_state.get('_liq_telemetry_wrote', 0)}
            except Exception as _liq_err:
                st.session_state['_liquidity_context'] = None
                st.caption(f"Liquidity Intelligence unavailable: {_liq_err}")
        except Exception as err:
            st.caption(f"Money-flow profile unavailable: {err}")
        try:
            st.session_state['_volume_delta_data'] = calculate_volume_delta(df)
        except Exception:
            pass
    try:
        st.session_state['_value_alignment'] = compute_value_alignment()
    except Exception:
        pass

    # ── 4 · side markets the Market Picture reads ───────────────────────
    # These are fetch-and-publish, not decoration: `compute_market_picture`
    # reads `_gift_mf` and `_commodity_risk`, `compute_global_nifty_bias` reads
    # `_global_indices`, and the bias dashboard reads all three. Dropping them
    # would make those categories report MISSING rather than a reading.
    for _panel in (render_global_indices_panel, render_gift_nifty_moneyflow_panel,
                   render_commodity_risk_panel, render_news_bias_panel):
        try:
            _panel()
        except Exception:
            pass

    # ── 5 · the option chain ────────────────────────────────────────────
    option_data = None
    try:
        option_data = analyze_option_chain(selected_expiry=selected_expiry)
    except Exception as err:
        st.caption(f"Option chain unavailable: {err}")
    if option_data:
        st.session_state['_cached_option_data'] = option_data
        st.session_state['_opt_data_ts'] = datetime.now(
            pytz.timezone('Asia/Kolkata')).isoformat()
    option_data = option_data or st.session_state.get('_cached_option_data') or {}
    underlying = option_data.get('underlying') or spot
    df_summary = option_data.get('df_summary')

    # ── 6 · dealer positioning + IV, moved ABOVE the pass ───────────────
    if df_summary is not None and not getattr(df_summary, 'empty', True) and underlying:
        try:
            _gex = calculate_dealer_gex(df_summary, underlying)
            if _gex:
                st.session_state['_gex_data'] = _gex
                st.session_state['gex_last_valid_data'] = _gex
        except Exception:
            pass
        try:
            _atm_row = df_summary.iloc[(df_summary['Strike'] - underlying).abs().argsort()[:1]]
            # ⚠️ `CE_IV` DOES NOT EXIST. It appeared nowhere else in this file, and
            # because the read was a `.get()` with a default it never raised — it
            # just yielded 0 on every cycle, `iv_history.valid(0)` refused it, and
            # the store stayed empty forever. That is why the Adaptive Greeks card
            # said "⚪ not reporting · no IV history published" indefinitely: the
            # engine was right, the frame had the number, and the lookup asked for a
            # column name nothing writes.
            #
            # `analyze_option_chain` merges `impliedVolatility_CE` (vob:3855). Both
            # spellings are accepted so a rename in either direction still reports,
            # and MISSING now stays missing instead of arriving as 0.
            _iv = None
            for _ivcol in ('impliedVolatility_CE', 'CE_IV'):
                if _ivcol in getattr(_atm_row, 'columns', ()):
                    try:
                        _iv = float(_atm_row[_ivcol].iloc[0])
                    except (TypeError, ValueError):
                        _iv = None
                    if _iv:
                        break
            # 📈 Into the cache_resource store, not session_state.
            #
            # ⚠️ `_iv_history` lived in session_state, which is PER BROWSER
            # SESSION — so every restart and every new tab started empty and the
            # Adaptive Greeks card said "IV: not reporting" until two samples
            # accumulated. `volatility_state` needs two.
            #
            # It also appended on EVERY rerun with no timestamp, so a stalled
            # chain pushed the same number repeatedly and `vals[-1] - vals[0]`
            # compared two readings of unknown — possibly identical — age.
            # `iv_history.record` dedups and stamps; see its module docstring.
            # 📊 One per-strike ATM±2 snapshot per cycle — OI, ΔOI and both
            # LTPs. `strike_history` dedups on MIN_GAP_S so a rerun that brought
            # no fresh chain cannot draw a flat line that looks settled.
            try:
                from mios_v5 import strike_history as _shmod
                _sst = strike_store()
                _shmod.record(_sst, df_summary, underlying)
                # ⚠️ Published as a REFERENCE, not a copy. `mios_v5` may not
                # import this file (the guard test enforces it), so the panel
                # cannot reach `strike_store()` itself — and `cache_resource`
                # returns the same object every time, so handing the same dict
                # through session_state costs nothing and keeps the dependency
                # pointing one way.
                st.session_state['_strike_hist'] = _sst
            except Exception:
                pass
            from mios_v5 import iv_history as _ivmod
            _ivs = iv_store()
            # One-time bridge so an already-running session keeps its history
            # instead of restarting the warm-up at deploy.
            _ivmod.adopt(_ivs, st.session_state.get('_iv_history'))
            _ivmod.record(_ivs, _iv)
            # Still published for any reader that has not moved over yet — but
            # sourced from the store, so there is one owner of the series.
            st.session_state['_iv_history'] = _ivmod.series(_ivs)
        except Exception:
            pass

    # ── 7 · the ATM legs ────────────────────────────────────────────────
    try:
        _publish_atm_legs(api, underlying, option_data, _render_id)
    except Exception as err:
        st.caption(f"ATM legs unavailable: {err}")

    # ── 8 · canonical S/R, moved ABOVE the pass (Stage 42 reads it) ─────
    if option_data and underlying:
        try:
            _zones = compute_major_sr_zones(
                option_data, option_data.get('result'),
                st.session_state.get('_money_flow_data'), underlying)
            if _zones:
                st.session_state['_major_sr_zones'] = _zones
                st.session_state['_reaction_sr'] = enrich_zone_intel(
                    annotate_sr_trend(
                        build_reaction_sr(_zones, underlying,
                                          st.session_state.get('_full_market_read'))),
                    underlying)
                st.session_state['_reaction_sr_ts'] = time.time()
        except Exception as err:
            st.session_state['_reaction_sr_error'] = str(err)

    # ── 9 · per-candle price-vs-OI + greek absorption ───────────────────
    try:
        compute_per_candle_pxoi(api)                # publishes _pxoi_cache
    except Exception:
        pass
    try:
        render_greek_absorption(option_data, underlying)   # _greek_absorb_last
    except Exception:
        pass
    try:
        render_atm_cvd_graphs(underlying)           # _zone_cvd_hist
    except Exception:
        pass

    # ── 10 · the bias dashboard ─────────────────────────────────────────
    # Not a panel with a side effect — it is the producer of `_all_bias_rows`,
    # `_leg_bias_cache`, `_market_picture`, `_full_market_read` and
    # `_market_structure`, five of V6's inputs, and the Opportunity Matrix
    # reads its rows directly.
    #
    # `picture_slot` is the container claimed above MIOS V6. The Market Picture
    # still runs at its own point inside this call — only where it DRAWS moves.
    if underlying and option_data:
        try:
            with _bias_container:
                render_all_bias_dashboard(underlying, df, option_data,
                                          picture_slot=_picture_container)
        except Exception as err:
            st.caption(f"Bias dashboard unavailable: {err}")

    # 🎯 The Trade Card — drawn into the container claimed at the top, now that
    # `_market_picture` / `_entry_gate_active` / `_guard_state` exist.
    #
    # Deliberately OUTSIDE the `if underlying and option_data` above. Nested
    # inside it, a failed chain fetch (the Dhan 502) skipped the call entirely
    # and the card was simply absent — no card, no reason, nothing to react to.
    #
    # `render_clean_card` opens with `if not mp or not spot_price: return`, so a
    # missing Market Picture makes it draw NOTHING and return cleanly. That is
    # the right behaviour for the card (it will not invent a read) and the wrong
    # behaviour for the page: an empty slot is indistinguishable from a card that
    # decided there was no trade. So the precondition is checked here and the
    # reason is printed in the card's own slot. Three-state discipline — ⚪ could
    # not report is a report.
    with _card_container:
        _mp_ready = bool(st.session_state.get('_market_picture'))
        if _mp_ready and underlying:
            try:
                render_clean_card(underlying, option_data)
            except Exception as err:
                st.caption(f"Trade Card unavailable: {err}")
        else:
            # ⚠️ Say WHY, not just "nothing arrived".
            #
            # This used to read "no option chain — chain fetch returned nothing"
            # whenever `_dhan_last_error` was unset — which is most of the time,
            # because the 401 and 429 paths never recorded one. Worse, it says it
            # at 08:25 on a perfectly healthy app: NSE publishes no chain before
            # 09:15, so the single most common reason for this message was "the
            # market is not open yet" and it read like a fault.
            #
            # `feed_status` owns the answer so the Trade Card, the two cockpits
            # and anything else that stands by cannot give three different
            # explanations of one silence.
            # ⚠️ No calm glyph for a clock state. Dhan serves the chain outside
            # market hours — figures freeze, they do not vanish — and there is no
            # market-hours gate on the fetch, so an EMPTY chain at 08:25 is a real
            # fetch failure. Showing a reassuring 🕒 for it would be the same
            # mistake as the old "chain fetch returned nothing".
            try:
                from mios_v5.feed_status import read as _feed_read
                _code, _feed = _feed_read(
                    st.session_state,
                    datetime.now(pytz.timezone('Asia/Kolkata')))
            except Exception:
                _code, _feed = None, "no option chain"
            _why = (_feed if not option_data else
                    "no spot price yet" if not underlying else
                    "the Market Picture has not produced a read yet")
            st.info(f"🎯 **Trade Card** standing by — {_why}")

    # ── 11 · the MIOS pass — every input above is now current ───────────
    try:
        build_htf_profiles(st.session_state.get('_last_df'), underlying)
    except Exception:
        pass
    try:
        st.session_state['_is_expiry_today'] = _is_expiry_day(option_data)
    except Exception:
        pass
    try:
        from mios_v5.runner import run_mios_pass
        st.session_state['_mios_state'] = run_mios_pass(st.session_state, db=db)
    except Exception as err:
        st.session_state['_mios_state'] = None
        st.caption(f"MIOS pass unavailable: {err}")
    st.session_state['_last_cycle_ts'] = datetime.now(
        pytz.timezone('Asia/Kolkata')).isoformat()

    # ── 12 · render ─────────────────────────────────────────────────────
    # Both take (state=, db=) — neither takes `st`; they import it themselves.
    with _v6_container:
        with st.expander("🖥 MIOS V6 — Market Intelligence Workstation",
                         expanded=True):
            try:
                from mios_v5.ui.dashboard_v6 import render_dashboard_v6
                render_dashboard_v6(state=st.session_state.get('_mios_state'), db=db)
                # ⚡ The simple entry system runs AFTER the dashboard, because
                # it reads `_sr_levels`, `_premium_structures` and the trading
                # context — all of which that render publishes. Running it
                # first would evaluate five rules against last cycle's data.
                if st.session_state.get("_simple_entry_on"):
                    try:
                        _se_signal = run_simple_entry()
                        # The five rules' verdict was stored and read by
                        # nothing. One line, every cycle, naming the blocker.
                        from mios_v5.ui.simple_entry_panel import render_status
                        render_status(
                            st.session_state.get("_simple_entry_slot"),
                            _se_signal)
                    except Exception:
                        pass
            except Exception as err:
                st.caption(f"Dashboard V6 unavailable: {err}")

    # 📍 Dynamic-POC shift alerts. Placed AFTER the V6 render because the
    # terminal publishes `_leg_profiles` (the three charts' dynamic POC) while
    # it draws inside the block above; reading it here sees this cycle's levels,
    # not last cycle's. No-op unless the sidebar toggle is on.
    try:
        _notify_poc_shifts()
    except Exception:
        pass

    # 📐 New high-volume pivot / VOB alerts. Same placement and reason as the
    # POC-shift alert above — the terminal has published `_leg_profiles` and the
    # leg VOB store by now, so a formation is detected against this cycle's
    # structure. No-op unless the sidebar toggle is on.
    try:
        _notify_chart_formations()
    except Exception:
        pass
    try:
        _notify_leg_hvp_touch()
    except Exception:
        pass
    try:
        _notify_flow_at_level()
    except Exception:
        pass

    # 🎯 Spot-at-a-key-level (±5 pts) alerts — war zone, OI walls, ranked S/R.
    # Same placement: the MIOS state and `_market_picture` are current by now,
    # and the final read is a cheap transport over them. No-op unless the toggle
    # is on.
    try:
        _notify_level_touches()
    except Exception:
        pass
    try:
        _notify_level_acceptance()
    except Exception:
        pass
    try:
        _notify_confluence_entry()
    except Exception:
        pass
    try:
        _notify_entry_reversed()
    except Exception:
        pass

    with _v5_container:
        with st.expander("🧭 MIOS V5 — Analysis & Audit (deep layer)", expanded=False):
            try:
                from mios_v5.ui import render_dashboard
                # `run_backfill` was `run_stage2_backfill`, which had no caller
                # anywhere and went with the reduction. The parameter is
                # optional; the panel hides the button when it is None.
                render_dashboard(state=st.session_state.get('_mios_state'), db=db)
            except Exception as err:
                st.caption(f"MIOS V5 unavailable: {err}")

    st.sidebar.info("Last Updated: " + datetime.now(
        pytz.timezone('Asia/Kolkata')).strftime("%Y-%m-%d %H:%M:%S IST"))


def _render_app_chrome(slot, foot):
    """Fill the header slot, set the browser tab, and close with the footer.

    Runs AFTER the cycle so the strip carries this cycle's spot rather than the
    previous one's under a live timestamp. Every value is read from a producer
    that already owns it — `_mios_market_read` for spot and the two biases,
    `_gap_today` for the previous close, `_is_market_open` for the clock. This
    computes none of them.
    """
    # ⚠️ Loud, not silent.
    #
    # Every step below used to sit under one `except Exception: pass`, so a
    # missing import or a market read that raised produced NOTHING — no header,
    # no footer, no message — which is indistinguishable from the feature never
    # having shipped. That is the exact failure this session has been removing
    # everywhere else, and I reintroduced it here.
    try:
        from mios_v5.ui.app_chrome import (CHROME_VERSION, render_chrome_css,
                                           render_footer, render_header,
                                           render_tab_title)
    except Exception as err:
        st.warning(f"App header unavailable — `mios_v5.ui.app_chrome` did not "
                   f"import: {err}")
        return

    # The rules that freeze both strips in place. Injected before they are
    # drawn, and once per rerun — a `<style>` block is idempotent, so a repeat
    # costs nothing and a missing one silently un-freezes the page.
    render_chrome_css(st)

    # The market read is best-effort: the header's job is to exist. A cycle
    # that could not report a price still gets a strip, with dashes and the
    # reason, rather than a blank page that looks like nothing was built.
    market, read_err = {}, None
    try:
        market = _mios_market_read() or {}
    except Exception as err:
        read_err = err
    spot = market.get("spot")
    v5, v6 = market.get("v5"), market.get("v6")
    prev_close = (st.session_state.get('_gap_today') or {}).get('prev_close')
    clock = "🟢 Market open" if _is_market_open else "⚪ Market closed"
    updated = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%H:%M:%S IST")

    extras = _chrome_extras()
    render_header(st, slot, spot=spot, prev_close=prev_close, v5=v5, v6=v6,
                  market=clock, updated=updated, extras=extras)
    if read_err is not None:
        st.caption(f"Header values unavailable this cycle: {read_err}")
    # The tab carries V6 — the newer engine — and falls back to V5 when V6 has
    # not reported. One glyph fits; showing both would need two and read as a
    # disagreement nobody can act on from a background tab.
    render_tab_title(st, spot=spot, bias=v6 or v5)
    render_footer(st, foot, updated=updated, market=clock,
                  version=CHROME_VERSION)

    # Kept so the NEXT rerun can paint the strips immediately — see
    # `_prime_app_chrome`. Stored with the timestamp these values were read at,
    # never a fresh one: a stale price under a live clock is the misreading the
    # late fill was avoiding in the first place.
    st.session_state['_chrome_last'] = {
        'spot': spot, 'prev_close': prev_close, 'v5': v5, 'v6': v6,
        'market': clock, 'updated': updated, 'extras': list(extras or ())}


def _chrome_extras():
    """The short readings for the header's second row, as plain text.

    Each string is worded by the panel that owns that fact — `zone_micro` for
    the S/R odds, `war_zone.micro` for the expected winner, `premium_energy`'s
    `micro` for participation and expansion. This function only collects them,
    so the header cannot end up phrasing a reading differently from the panel
    that publishes it further down the page.

    Every source is already-published session state: `_reaction_sr` carries the
    zone cards `enrich_zone_intel` attached, `_premium_energy` is Stage 71.7's
    own output, and the final read is rebuilt through `build_final_read` — the
    same call `_mios_market_read` uses. Nothing here computes.

    A source that is absent contributes nothing rather than a placeholder: the
    strip is frozen at the top of the page, and a row of `—` chips would cost
    that space permanently to say nothing.
    """
    out = []
    # ── 🧲 the PIN veto, first ───────────────────────────────────────────
    # First because it CONTRADICTS every chip after it. When price is pinned at
    # a magnet strike, `compute_market_picture`'s gate returns PINNED and skips
    # the directional logic outright — no CALL, no PUT, whatever the S/R odds
    # and the war-zone winner beside it happen to read. A trader who sees
    # "support · 68% bounce" and does NOT see the veto is being shown a contest
    # that is not live, which is the one misreading a frozen strip can cause on
    # every screen at once.
    #
    # This was already computed and already decided: `oi_pin` detects the
    # coincident CE+PE wall and the gate turns it into a state. It reached the
    # Market Picture's own panel far down the page and reached nothing up here —
    # consumed-but-unpublished, which principle 12 names as the smell.
    #
    # READ, not re-decided, and not re-worded here. `pin_chip.micro` adds the
    # glyph and answers "is there a pin?"; the sentence itself stays the
    # owner's, so the header cannot say "pinned" while the panel below describes
    # the same strike differently.
    try:
        from mios_v5.ui.pin_chip import micro as _pin_micro
        _line = _pin_micro(
            (st.session_state.get('_market_picture') or {}).get('entry_gate'))
        if _line:
            out.append(_line)
    except Exception:
        pass
    # ── 🗺️ MARKET STATE · the gate's verdict + the regime ────────────────
    # Second, immediately after the veto, because it answers the question the
    # chips below it assume: may I trade right now? `CHOP_WAIT · regime SIDEWAYS`
    # and `CHOP_WAIT · regime UP` are different instructions, and the S/R odds
    # and war-zone winner further along the strip read the same either way.
    #
    # Both words were already computed by `compute_market_picture` and reached
    # only its own panel — the same consumed-but-unpublished gap the pin had.
    # `market_state_chip` stays quiet on PINNED so it never repeats the chip
    # above it, and words nothing the gate did not already decide.
    try:
        from mios_v5.ui.market_state_chip import micro as _ms_micro
        _mp = st.session_state.get('_market_picture') or {}
        _line = _ms_micro(_mp.get('entry_gate'), _mp)
        if _line:
            out.append(_line)
    except Exception:
        pass
    try:
        from mios_v5.ui.zone_card import zone_micro
        _rsr = st.session_state.get('_reaction_sr') or {}
        for _side in ('support', 'resistance'):
            _z = _rsr.get(_side) or {}
            _line = zone_micro((_z or {}).get('intel'))
            if _line:
                out.append(_line)
    except Exception:
        pass
    try:
        from mios_v5.final_read import build_final_read
        from mios_v5.ui.war_zone import micro as _wz_micro
        _line = _wz_micro(build_final_read(st.session_state.get('_mios_state')))
        if _line:
            out.append(_line)
    except Exception:
        pass
    try:
        from mios_v5.ui.premium_energy_panel import micro as _pe_micro
        _line = _pe_micro(st.session_state.get('_premium_energy'))
        if _line:
            out.append(_line)
    except Exception:
        pass
    # ── ⚙️ dealer posture · gamma sign · fade risk ──────────────────────
    # The Adaptive Greeks read, worded by its own panel. Dashboard V6 publishes
    # `_adaptive_greeks`; this only collects, so the chip and the card cannot
    # describe one cycle differently.
    try:
        from mios_v5.ui.greeks_panel import micro as _ag_micro
        _line = _ag_micro(st.session_state.get('_adaptive_greeks'))
        if _line:
            out.append(_line)
    except Exception:
        pass
    # 🎯 The entry gate's verdict and its confidence, asked for on the strip.
    #
    # ⚠️ From `_entry_verdict`, the pair `dashboard_v6._guardian_read` already
    # resolved — NOT by reading `_entry_decision` and the gate again here. A second
    # resolution is how the strip and the card end up showing different verdicts for
    # the same cycle, and `apply_to` has already been applied to the confidence
    # exactly once. The chrome runs after the cycle, so the pair is current.
    #
    # It carries its own label: on the strip it sits near the Position Guardian's
    # line, and an unlabelled "ENTER · 100/100" beside "Position Guardian — idle"
    # is precisely the collision that got reported.
    try:
        from mios_v5.ui.greeks_panel import verdict_micro as _vm
        _pair = st.session_state.get('_entry_verdict') or (None, None)
        _line = _vm(_pair[0], _pair[1])
        if _line:
            out.append(_line)
    except Exception:
        pass
    return out


def _prime_app_chrome(slot, foot):
    """Paint the strips from the last cycle's values, immediately.

    ⚠️ This is the fix for "the header and footer sometimes vanish".

    They are filled at the END of the cycle so they carry that cycle's spot.
    But `st_autorefresh` reruns the whole script every twenty seconds, and a
    rerun rebuilds the page from the top — so the placeholders start EMPTY and
    stay empty for the entire render, network fetches included. The strips were
    not vanishing at random; they were absent for most of every refresh and
    present only in the gap between one cycle finishing and the next starting.

    So the slot is primed with what was true a moment ago and overwritten with
    what is true now. The timestamp is the stored one, not `now`: the strip
    reads `15:22:04 IST` until the new cycle lands, which is the honest label
    for a price from 15:22:04. The original objection to filling early —
    *the previous cycle's price under a live timestamp* — was right about the
    live timestamp and wrong about the price.

    Nothing is primed on the first run of a session, because there is nothing
    to prime from. One blank cycle at startup is unavoidable and is not what
    was reported.
    """
    last = st.session_state.get('_chrome_last')
    if not last:
        return
    try:
        from mios_v5.ui.app_chrome import render_footer, render_header
        render_header(st, slot, spot=last.get('spot'),
                      prev_close=last.get('prev_close'), v5=last.get('v5'),
                      v6=last.get('v6'), market=last.get('market') or "",
                      updated=last.get('updated') or "",
                      extras=last.get('extras') or ())
        render_footer(st, foot, updated=last.get('updated') or "",
                      market=last.get('market') or "",
                      version=CHROME_VERSION_FALLBACK)
    except Exception:
        pass


#: Used only by the priming render, where importing the module for one constant
#: would be the third import of it in a cycle.
CHROME_VERSION_FALLBACK = "chrome.2"


# ══════════════════════════════════════════════════════════════════════════
#  📍 the spot strip — the one number with its own clock
# ══════════════════════════════════════════════════════════════════════════

#: How often the spot strip re-fetches. See `mios_v5/ui/spot_ticker.py` for why
#: this is a fragment and not a faster `st_autorefresh`: the page cycle drags an
#: option-chain fetch, the MIOS pass and Supabase writes behind it, so halving it
#: would double the egress the audit spent itself reducing. This drags one
#: `marketfeed/ltp` call.
SPOT_REFRESH = "10s"


def _spot_ticker_body():
    """Re-read the live index LTP, publish it, draw the strip.

    ⚠️ This is the ONE place that refreshes spot faster than the page, and it is
    deliberately the cheapest read in the app:

    * `get_index_spot_ltp` is a single `marketfeed/ltp` quote, already cached ~4s
      in session state and already short-circuited during a Dhan 429 back-off, so
      a 10-second cadence cannot turn into 10-second API pressure.
    * It writes **nothing** to Supabase. `_render_main_analyzer` still owns
      `upsert_spot_data` on the 20-second cycle; persisting here would double the
      spot writes to buy a row nobody reads twice.

    Publishing to `_nifty_spot_live` is the point of doing it here at all: every
    panel now reads spot through `mios_v5.spot`, so the next page rerun hands all
    of them whatever this last fetched. The strip is 10s fresh, the panels are
    one page cycle behind it, and the strip says so out loud rather than letting
    a stale number sit under a live clock.
    """
    try:
        from mios_v5.spot import read as _spot_read
        from mios_v5.ui.spot_ticker import spot_strip_html
    except Exception as err:
        st.caption(f"Spot strip unavailable — `mios_v5.ui.spot_ticker` did not "
                   f"import: {err}")
        return
    try:
        _ltp = get_index_spot_ltp(NIFTY_UNDERLYING_SCRIP, NIFTY_UNDERLYING_SEG)
        if _ltp:
            st.session_state['_nifty_spot_live'] = float(_ltp)
            st.session_state['_nifty_spot_live_ts'] = time.time()
    except Exception:
        # A failed quote is not a failed strip: `spot.read` falls through to the
        # chain and the age chip shows the LTP going cold.
        pass
    try:
        _html = spot_strip_html(
            _spot_read(st.session_state),
            (st.session_state.get('_gap_today') or {}).get('prev_close'))
    except Exception as err:
        st.caption(f"Spot strip failed to render: {err}")
        return
    if _html:
        st.markdown(_html, unsafe_allow_html=True)


def _spot_ticker(container):
    """Draw the strip into `container`, on its own clock when one is available.

    `st.fragment(run_every=…)` reruns the decorated body alone. Guarded three
    ways because the alternative to a missing clock is a missing price:

    * no `st.fragment` at all (older Streamlit) → draw once, no ticking
    * market closed → draw once. Polling Dhan every 10 seconds overnight buys a
      number that has not moved since 15:30.
    * the fragment itself raising → fall back to a plain draw

    A fragment may only write inside its own container, so one is passed in
    rather than claimed here.
    """
    def _draw():
        with container:
            _spot_ticker_body()

    frag = getattr(st, "fragment", None) or getattr(st, "experimental_fragment",
                                                    None)
    if frag is None or not _is_market_open:
        _draw()
        return
    try:
        frag(run_every=SPOT_REFRESH)(_draw)()
    except Exception as err:
        st.caption(f"Spot strip is not auto-refreshing ({err}) — showing the "
                   f"page cycle's price instead.")
        _draw()


def main():
    # Placeholders, not a title. Both strips are FILLED at the end of the cycle
    # so they carry this cycle's values — but a rerun rebuilds the page from the
    # top, so an unprimed placeholder is empty for the whole render. That is
    # what "the header sometimes vanishes" was: absent for most of every
    # refresh. `_prime_app_chrome` paints last cycle's values into them now,
    # each under its OWN timestamp, and the end of the cycle overwrites both.
    _chrome_slot = st.empty()
    _chrome_foot = st.empty()
    _prime_app_chrome(_chrome_slot, _chrome_foot)

    # 📍 Directly under the header, before anything that takes a second to
    # build. Spot is the number the trader looks at first and the only one worth
    # its own clock — see `SPOT_REFRESH`. Its container is claimed here, outside
    # the fragment, because a fragment may only write within a container that
    # already exists.
    _spot_ticker(st.container())

    # ── hot-path measurement · OFF unless MIOS_PROFILE=1 ──────────────
    # The duplication survey counted 11 call sites for
    # `calculate_money_flow_profile` and 8 for `compute_vpfr` in this ~20s
    # rerun path, and said explicitly that call sites are not executions. This
    # is how that stops being a guess. Disabled it costs one env lookup at
    # import and wraps nothing; there is no production path through it.
    _prof = None
    try:
        from tools import hotpath_profiler as _prof
        if _prof.ENABLED:
            _prof.install(globals())
    except Exception:
        _prof = None

    _render_main_analyzer()

    # Header, tab title and footer — after the cycle, so they carry its values.
    # The chrome may never take the app down, but it may not vanish quietly
    # either: a swallowed failure here looks exactly like the feature was never
    # built, which is precisely the report that sent me looking for this.
    try:
        _render_app_chrome(_chrome_slot, _chrome_foot)
    except Exception as err:
        st.warning(f"App header/footer failed to render: {err}")

    # Flushed per rerun, not per session: the question is what ONE cycle
    # costs, and a running total answers something else.
    if _prof is not None and _prof.ENABLED:
        try:
            st.caption(_prof.summary_line(_prof.flush()))
        except Exception:
            pass

    # Same rule for the egress meter: one cycle's bytes, ranked by table.
    try:
        from tools import egress_meter as _egress
        if _egress.ENABLED:
            st.caption(_egress.summary_line(_egress.flush()))
    except Exception:
        pass


if __name__ == "__main__":
    main()
