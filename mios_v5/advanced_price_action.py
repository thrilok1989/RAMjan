"""Advanced price-action analysis — BOS, CHOCH, Fibonacci and geometric patterns.

Pure, self-contained analysis over an OHLC frame: swing highs/lows, Break of
Structure (BOS), Change of Character (CHOCH), Fibonacci retracement/extension
levels, and geometric patterns (head & shoulders, triangles, flags/pennants).

No `st`, no I/O, no network — numbers in, dicts out. The chart overlay
(`ui/price_action_overlay.py`) reads `analyze()` and draws it; the whole feature
is opt-in (default OFF), so nothing here runs unless the trader enables it.
"""

import pandas as pd  # noqa: F401  (kept for typing parity with the source module)
import numpy as np  # noqa: F401
from typing import Dict, List, Tuple, Optional


class AdvancedPriceAction:
    """BOS / CHOCH / Fibonacci / geometric-pattern detection over OHLC bars."""

    def __init__(self, swing_length: int = 5):
        self.swing_length = swing_length

    # ── swing high/low detection ────────────────────────────────────────
    def find_swing_highs_lows(self, df: pd.DataFrame) -> Tuple[List[Dict], List[Dict]]:
        high_col = 'High' if 'High' in df.columns else 'high'
        low_col = 'Low' if 'Low' in df.columns else 'low'
        swing_highs: List[Dict] = []
        swing_lows: List[Dict] = []
        length = self.swing_length
        for i in range(length, len(df) - length):
            is_swing_high = True
            for j in range(i - length, i + length + 1):
                if j != i and df[high_col].iloc[j] >= df[high_col].iloc[i]:
                    is_swing_high = False
                    break
            if is_swing_high:
                swing_highs.append({'index': i, 'price': df[high_col].iloc[i],
                                    'time': df.index[i]})
            is_swing_low = True
            for j in range(i - length, i + length + 1):
                if j != i and df[low_col].iloc[j] <= df[low_col].iloc[i]:
                    is_swing_low = False
                    break
            if is_swing_low:
                swing_lows.append({'index': i, 'price': df[low_col].iloc[i],
                                   'time': df.index[i]})
        return swing_highs, swing_lows

    # ── BOS (break of structure) ────────────────────────────────────────
    def detect_bos(self, df, swing_highs=None, swing_lows=None) -> List[Dict]:
        if swing_highs is None or swing_lows is None:
            swing_highs, swing_lows = self.find_swing_highs_lows(df)
        return self._detect_bos_internal(df, swing_highs, swing_lows)

    def _detect_bos_internal(self, df, swing_highs, swing_lows) -> List[Dict]:
        close_col = 'Close' if 'Close' in df.columns else 'close'
        bos_events: List[Dict] = []
        for i in range(len(df)):
            recent_swing_high = None
            for sh in reversed(swing_highs):
                if sh['index'] < i:
                    recent_swing_high = sh
                    break
            recent_swing_low = None
            for sl in reversed(swing_lows):
                if sl['index'] < i:
                    recent_swing_low = sl
                    break
            if recent_swing_high and df[close_col].iloc[i] > recent_swing_high['price']:
                if not any(b['type'] == 'BULLISH' and b['structure_level'] == recent_swing_high['price']
                           for b in bos_events):
                    bos_events.append({
                        'type': 'BULLISH', 'index': i, 'price': df[close_col].iloc[i],
                        'time': df.index[i], 'structure_level': recent_swing_high['price'],
                        'structure_time': recent_swing_high['time']})
            if recent_swing_low and df[close_col].iloc[i] < recent_swing_low['price']:
                if not any(b['type'] == 'BEARISH' and b['structure_level'] == recent_swing_low['price']
                           for b in bos_events):
                    bos_events.append({
                        'type': 'BEARISH', 'index': i, 'price': df[close_col].iloc[i],
                        'time': df.index[i], 'structure_level': recent_swing_low['price'],
                        'structure_time': recent_swing_low['time']})
        return bos_events

    # ── CHOCH (change of character) ─────────────────────────────────────
    def detect_choch(self, df, swing_highs=None, swing_lows=None) -> List[Dict]:
        if swing_highs is None or swing_lows is None:
            swing_highs, swing_lows = self.find_swing_highs_lows(df)
        return self._detect_choch_internal(df, swing_highs, swing_lows)

    def _detect_choch_internal(self, df, swing_highs, swing_lows) -> List[Dict]:
        choch_events: List[Dict] = []
        for i in range(1, len(swing_highs)):
            prev_high, curr_high = swing_highs[i - 1], swing_highs[i]
            if curr_high['price'] < prev_high['price']:
                choch_events.append({
                    'type': 'BEARISH', 'index': curr_high['index'],
                    'price': curr_high['price'], 'time': curr_high['time'],
                    'prev_structure': prev_high['price']})
        for i in range(1, len(swing_lows)):
            prev_low, curr_low = swing_lows[i - 1], swing_lows[i]
            if curr_low['price'] > prev_low['price']:
                choch_events.append({
                    'type': 'BULLISH', 'index': curr_low['index'],
                    'price': curr_low['price'], 'time': curr_low['time'],
                    'prev_structure': prev_low['price']})
        choch_events.sort(key=lambda x: x['index'])
        return choch_events

    # ── Fibonacci retracement / extension ──────────────────────────────
    def calculate_fibonacci_levels(self, df, swing_highs, swing_lows, lookback: int = 3) -> Dict:
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return {'success': False, 'error': 'Insufficient swing points'}
        recent_highs = swing_highs[-lookback:]
        recent_lows = swing_lows[-lookback:]
        highest = max(recent_highs, key=lambda x: x['price'])
        lowest = min(recent_lows, key=lambda x: x['price'])
        trend_up = highest['index'] < lowest['index']
        price_range = highest['price'] - lowest['price']
        fib_ratios = {'0.0': 0.0, '0.236': 0.236, '0.382': 0.382, '0.5': 0.5,
                      '0.618': 0.618, '0.786': 0.786, '1.0': 1.0}
        fib_extensions = {'1.272': 1.272, '1.414': 1.414, '1.618': 1.618,
                          '2.0': 2.0, '2.618': 2.618}
        retracement_levels: Dict[str, float] = {}
        extension_levels: Dict[str, float] = {}
        if trend_up:
            for label, ratio in fib_ratios.items():
                retracement_levels[label] = lowest['price'] + (price_range * ratio)
            for label, ratio in fib_extensions.items():
                extension_levels[label] = lowest['price'] + (price_range * ratio)
        else:
            for label, ratio in fib_ratios.items():
                retracement_levels[label] = highest['price'] - (price_range * ratio)
            for label, ratio in fib_extensions.items():
                extension_levels[label] = highest['price'] - (price_range * ratio)
        return {'success': True, 'trend_up': trend_up, 'swing_high': highest,
                'swing_low': lowest, 'retracement_levels': retracement_levels,
                'extension_levels': extension_levels, 'price_range': price_range}

    # ── geometric patterns ─────────────────────────────────────────────
    def detect_head_and_shoulders(self, swing_highs, swing_lows, tolerance: float = 0.02) -> List[Dict]:
        patterns: List[Dict] = []
        if len(swing_highs) < 3:
            return patterns
        for i in range(len(swing_highs) - 2):
            left_shoulder, head, right_shoulder = swing_highs[i], swing_highs[i + 1], swing_highs[i + 2]
            if head['price'] > left_shoulder['price'] and head['price'] > right_shoulder['price']:
                shoulder_diff = abs(left_shoulder['price'] - right_shoulder['price'])
                avg_shoulder = (left_shoulder['price'] + right_shoulder['price']) / 2
                if avg_shoulder and shoulder_diff / avg_shoulder <= tolerance:
                    neckline_lows = [sl for sl in swing_lows
                                     if left_shoulder['index'] < sl['index'] < right_shoulder['index']]
                    if neckline_lows:
                        neckline_price = sum(sl['price'] for sl in neckline_lows) / len(neckline_lows)
                        patterns.append({
                            'type': 'HEAD_AND_SHOULDERS', 'left_shoulder': left_shoulder,
                            'head': head, 'right_shoulder': right_shoulder,
                            'neckline_price': neckline_price,
                            'target': neckline_price - (head['price'] - neckline_price),
                            'completed': False})
        return patterns

    def detect_inverse_head_and_shoulders(self, swing_highs, swing_lows, tolerance: float = 0.02) -> List[Dict]:
        patterns: List[Dict] = []
        if len(swing_lows) < 3:
            return patterns
        for i in range(len(swing_lows) - 2):
            left_shoulder, head, right_shoulder = swing_lows[i], swing_lows[i + 1], swing_lows[i + 2]
            if head['price'] < left_shoulder['price'] and head['price'] < right_shoulder['price']:
                shoulder_diff = abs(left_shoulder['price'] - right_shoulder['price'])
                avg_shoulder = (left_shoulder['price'] + right_shoulder['price']) / 2
                if avg_shoulder and shoulder_diff / avg_shoulder <= tolerance:
                    neckline_highs = [sh for sh in swing_highs
                                      if left_shoulder['index'] < sh['index'] < right_shoulder['index']]
                    if neckline_highs:
                        neckline_price = sum(sh['price'] for sh in neckline_highs) / len(neckline_highs)
                        patterns.append({
                            'type': 'INVERSE_HEAD_AND_SHOULDERS', 'left_shoulder': left_shoulder,
                            'head': head, 'right_shoulder': right_shoulder,
                            'neckline_price': neckline_price,
                            'target': neckline_price + (neckline_price - head['price']),
                            'completed': False})
        return patterns

    def detect_triangles(self, swing_highs, swing_lows, min_touches: int = 2) -> List[Dict]:
        patterns: List[Dict] = []
        if len(swing_highs) < min_touches or len(swing_lows) < min_touches:
            return patterns
        recent_highs = swing_highs[-6:]
        recent_lows = swing_lows[-6:]
        if len(recent_highs) >= 2 and (recent_highs[-1]['index'] - recent_highs[0]['index']):
            high_slope = (recent_highs[-1]['price'] - recent_highs[0]['price']) / \
                (recent_highs[-1]['index'] - recent_highs[0]['index'])
        else:
            high_slope = 0
        if len(recent_lows) >= 2 and (recent_lows[-1]['index'] - recent_lows[0]['index']):
            low_slope = (recent_lows[-1]['price'] - recent_lows[0]['price']) / \
                (recent_lows[-1]['index'] - recent_lows[0]['index'])
        else:
            low_slope = 0
        if high_slope < 0 and low_slope > 0:
            triangle_type = "SYMMETRICAL_TRIANGLE"
        elif abs(high_slope) < 0.01 and low_slope > 0:
            triangle_type = "ASCENDING_TRIANGLE"
        elif high_slope < 0 and abs(low_slope) < 0.01:
            triangle_type = "DESCENDING_TRIANGLE"
        else:
            return patterns
        patterns.append({'type': triangle_type, 'upper_trendline': recent_highs,
                         'lower_trendline': recent_lows, 'high_slope': high_slope,
                         'low_slope': low_slope, 'apex_estimate': None})
        return patterns

    def detect_flags_and_pennants(self, df, swing_highs, swing_lows, lookback: int = 20) -> List[Dict]:
        close_col = 'Close' if 'Close' in df.columns else 'close'
        patterns: List[Dict] = []
        if len(df) < lookback + 10:
            return patterns
        for i in range(lookback, len(df) - 10):
            flagpole_start, flagpole_end = i - lookback, i
            base = df[close_col].iloc[flagpole_start]
            if not base:
                continue
            price_change = df[close_col].iloc[flagpole_end] - base
            percent_change = (price_change / base) * 100
            if abs(percent_change) > 5:
                consolidation_highs = [sh for sh in swing_highs
                                       if flagpole_end < sh['index'] < flagpole_end + 15]
                consolidation_lows = [sl for sl in swing_lows
                                      if flagpole_end < sl['index'] < flagpole_end + 15]
                if len(consolidation_highs) >= 2 and len(consolidation_lows) >= 2:
                    hi_dx = (consolidation_highs[-1]['index'] - consolidation_highs[0]['index']) or 1
                    lo_dx = (consolidation_lows[-1]['index'] - consolidation_lows[0]['index']) or 1
                    high_slope = (consolidation_highs[-1]['price'] - consolidation_highs[0]['price']) / hi_dx
                    low_slope = (consolidation_lows[-1]['price'] - consolidation_lows[0]['price']) / lo_dx
                    if abs(high_slope - low_slope) < 0.1:
                        pattern_type = "BULL_FLAG" if percent_change > 0 else "BEAR_FLAG"
                    else:
                        pattern_type = "BULL_PENNANT" if percent_change > 0 else "BEAR_PENNANT"
                    patterns.append({
                        'type': pattern_type, 'flagpole_start': flagpole_start,
                        'flagpole_end': flagpole_end, 'percent_change': percent_change,
                        'consolidation_highs': consolidation_highs,
                        'consolidation_lows': consolidation_lows,
                        'breakout_target': df[close_col].iloc[flagpole_end] + price_change})
        return patterns

    # ── convenience wrappers ────────────────────────────────────────────
    def calculate_fibonacci(self, df) -> Dict:
        swing_highs, swing_lows = self.find_swing_highs_lows(df)
        fib_result = self.calculate_fibonacci_levels(df, swing_highs, swing_lows)
        if not fib_result.get('success', False):
            return {}
        return fib_result.get('retracement_levels', {})

    def detect_patterns(self, df) -> List[Dict]:
        swing_highs, swing_lows = self.find_swing_highs_lows(df)
        patterns: List[Dict] = []
        for hs in self.detect_head_and_shoulders(swing_highs, swing_lows):
            patterns.append({'name': 'Head and Shoulders', 'type': 'Bearish Reversal',
                             'start_idx': hs['left_shoulder']['index'],
                             'end_idx': hs['right_shoulder']['index']})
        for ihs in self.detect_inverse_head_and_shoulders(swing_highs, swing_lows):
            patterns.append({'name': 'Inverse Head and Shoulders', 'type': 'Bullish Reversal',
                             'start_idx': ihs['left_shoulder']['index'],
                             'end_idx': ihs['right_shoulder']['index']})
        for tri in self.detect_triangles(swing_highs, swing_lows):
            patterns.append({'name': tri['type'].replace('_', ' ').title(),
                             'type': 'Continuation',
                             'start_idx': tri['lower_trendline'][0]['index'] if tri['lower_trendline'] else 'N/A',
                             'end_idx': tri['lower_trendline'][-1]['index'] if tri['lower_trendline'] else 'N/A'})
        for fp in self.detect_flags_and_pennants(df, swing_highs, swing_lows):
            patterns.append({'name': fp['type'].replace('_', ' ').title(),
                             'type': 'Continuation', 'start_idx': fp['flagpole_start'],
                             'end_idx': fp['flagpole_end']})
        return patterns

    # ── full analysis ───────────────────────────────────────────────────
    def analyze(self, df) -> Dict:
        swing_highs, swing_lows = self.find_swing_highs_lows(df)
        return {
            'success': True,
            'swing_highs': swing_highs, 'swing_lows': swing_lows,
            'bos_events': self._detect_bos_internal(df, swing_highs, swing_lows),
            'choch_events': self._detect_choch_internal(df, swing_highs, swing_lows),
            'fibonacci': self.calculate_fibonacci_levels(df, swing_highs, swing_lows),
            'patterns': {
                'head_and_shoulders': self.detect_head_and_shoulders(swing_highs, swing_lows),
                'inverse_head_and_shoulders': self.detect_inverse_head_and_shoulders(swing_highs, swing_lows),
                'triangles': self.detect_triangles(swing_highs, swing_lows),
                'flags_pennants': self.detect_flags_and_pennants(df, swing_highs, swing_lows)},
        }
