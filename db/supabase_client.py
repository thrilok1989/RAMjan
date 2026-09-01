import streamlit as st
import pandas as pd
import numpy as np
import json
import pytz
from datetime import datetime, timedelta
from supabase import create_client, Client
from db.cache_manager import CacheManager

# Every timestamp this client writes is IST. TIMESTAMPTZ stores an absolute
# instant either way, so this does not change WHICH moment is recorded — it
# changes what a human reads in the Supabase table editor, in a CSV export and
# in raw JSON. This desk thinks in IST; the stored rows should too.
IST = pytz.timezone('Asia/Kolkata')

# ══════════════════════════════════════════════════════════════════════════
#  Read projections — the one egress lever caching cannot pull
# ══════════════════════════════════════════════════════════════════════════
#
# `db/read_cache.py` reduced how OFTEN a read reaches Supabase. It cannot
# reduce how BIG the read is, and the fetches it cannot remove are the
# expensive ones: the cold-start pass after every restart, and the refetch
# every invalidation forces. Those pay full row width every time.
#
# 52 of 61 reads were `select('*')`. `tools/egress_meter.py` named this the
# largest remaining item and deferred it for a stated reason:
#
#   > narrowing a column list is a per-call-site decision: each one needs its
#   > consumers checked, and getting it wrong renders a blank field rather
#   > than a slow one.
#
# So this narrows exactly two reads — the two with the most rows AND a JSONB
# blob column that **no read consumer touches**. A JSON snapshot dwarfs every
# numeric column beside it, so dropping one blob from an 8,000-row read is
# worth more than narrowing thirty small ones.
#
# ⚠️ An inclusion list has one dangerous failure mode: a column added to the
# table later is silently omitted, and a silently missing column is precisely
# the blank field the audit warned about. `test_read_projections.py` closes
# that by re-deriving each list from `sql/*.sql` — add a column to the schema
# without adding it here and the suite fails instead of the panel.
#
#: table → the columns a read of it needs, and why the omitted one is safe.
_PROJECTIONS = {
    # `data` is per-engine JSONB, written by Stage 55 and never read back:
    # `attribution.py::engine_rows` builds it from a live MarketState, and
    # `stage29_evolution` reads its own session snapshot, not this table.
    # Every reader of these rows (contribution · engine_accuracy · calibration
    # · attribution) uses only the scalar columns below.
    'engine_attribution': (
        'id', 'signal_id', 'trading_day', 'created_at', 'engine', 'stage',
        'output', 'bias', 'status', 'confidence', 'strength', 'weight',
        'agreement', 'conflict', 'reliability', 'freshness_min'),
    # `engine_snapshot` has no reference anywhere in the repo outside one
    # docstring explaining why per-engine rows replaced it. Its consumers are
    # dashboard_v6's `_history` table and `replay`, and neither asks for it.
    'trade_signals': (
        'id', 'signal_id', 'trading_day', 'created_at', 'updated_at', 'side',
        'quality', 'confidence', 'zone_side', 'entry_price', 'stop', 'target',
        'rr', 'status', 'signal_spot', 'entered_price', 'entered_at',
        'exit_price', 'exit_at', 'outcome', 'pnl_points', 'holding_secs',
        'reason'),
}

#: The blob each projection deliberately drops. Read by the guard test, which
#: asserts `projection == declared columns - dropped` for every entry above,
#: so this file cannot drift from the schema in either direction.
_PROJECTION_DROPS = {
    'engine_attribution': ('data',),
    'trade_signals': ('engine_snapshot',),
}


def projection(table: str) -> str:
    """The column list for a read of `table` — `'*'` when it has no projection.

    Narrowing is opt-in per table. A table absent from `_PROJECTIONS` keeps
    `select('*')`, which is the safe direction for a read whose consumers have
    not been checked.
    """
    cols = _PROJECTIONS.get(table)
    return ','.join(cols) if cols else '*'


class SupabaseDB:
    def __init__(self, url, key):
        self.client: Client = create_client(url, key)
        self.cache = CacheManager.get_instance()
        self.is_connected = True
        self._health_check()

    def _health_check(self):
        try:
            self.client.table('candles_data').select('id').limit(1).execute()
            self.is_connected = True
        except:
            self.is_connected = False

    def sync_pending(self):
        if not self.cache.has_pending():
            return
        try:
            self._health_check()
            if not self.is_connected:
                return
            for table_name, batches in list(self.cache.get_pending().items()):
                for batch in batches:
                    try:
                        conflict = batch.get('conflict_cols')
                        records = batch['records']
                        if isinstance(records, pd.DataFrame):
                            records = records.replace({np.nan: None}).to_dict('records')
                        if conflict:
                            self.client.table(table_name).upsert(records, on_conflict=conflict, returning='minimal').execute()
                        else:
                            self.client.table(table_name).upsert(records, returning='minimal').execute()
                    except:
                        continue
                self.cache.clear_pending(table_name)
        except:
            pass

    #: ⚠️ `returning='minimal'` is an EGRESS fix, not a tidy-up.
    #:
    #: PostgREST echoes every written row back by default, and Supabase bills
    #: that echo as egress. Nineteen write paths route through here — including
    #: `save_option_chain`, which writes the whole chain every cycle — and not
    #: one of them reads the response. So the app was paying to receive a copy
    #: of ~100 option rows it had just sent, every twenty seconds, all session.
    #:
    #: A write that genuinely needs the row back (`upsert_auto_trade` reads
    #: `.data` for the generated id) does not use this helper and is untouched.
    #:
    #: ⚠️ Round 2 covered the 19 writes routed through `_safe_upsert` and the
    #: `insert_*` paths, and left the five `update_*` methods echoing. Four of
    #: them discard the response outright — they `return True` — so they were
    #: paying for a row nobody looked at, `entry_gate_signals` at 37 columns
    #: among them. Those four now pass this explicitly.
    #:
    #: `upsert_auto_trade` is the one exception and stays as it is: it reads
    #: `result.data[0]` for the id Postgres generates, so `minimal` would break
    #: it. `test_egress_writes` holds that distinction.
    _WRITE_RETURNING = 'minimal'

    def _safe_upsert(self, table_name, records, conflict_cols):
        if isinstance(records, pd.DataFrame):
            records = records.replace({np.nan: None}).to_dict('records')
        if not records:
            return
        try:
            self.client.table(table_name).upsert(
                records, on_conflict=conflict_cols,
                returning=self._WRITE_RETURNING).execute()
            self.cache.update(table_name, records)
            self.is_connected = True
        except Exception:
            self.cache.queue_write(table_name, records, conflict_cols)
            self.is_connected = False

    def _safe_query(self, table_name, query_fn, filters=None):
        try:
            result = query_fn()
            if result.data:
                df = pd.DataFrame(result.data)
                self.cache.update(table_name, result.data)
                self.is_connected = True
                return df
            return pd.DataFrame()
        except Exception:
            self.is_connected = False
            return self.cache.get(table_name, filters)

    # ── Candles ──
    #: Where the per-series write watermark lives. `SupabaseDB` is rebuilt on
    #: every Streamlit rerun, so instance state would be lost each cycle — this
    #: has to outlive the object, and session_state is what does.
    _CANDLE_MARKS = '_candle_write_marks'

    def _candle_mark(self, key):
        try:
            return st.session_state.setdefault(self._CANDLE_MARKS, {}).get(key)
        except Exception:
            return None

    def _set_candle_mark(self, key, value):
        try:
            st.session_state.setdefault(self._CANDLE_MARKS, {})[key] = value
        except Exception:
            pass

    def upsert_candles(self, symbol, exchange, timeframe, df, full=False):
        """Write only the candles that are new or still forming.

        The app calls this every rerun — every 20 seconds — with the whole
        `days_back × 24h` frame. Rewriting all of it meant ~500 rows upserted
        180 times an hour when one or two were ever new: 90,000 row-writes an
        hour to record roughly 180 bars.

        So a **watermark** per `(symbol, exchange, timeframe)` records how far
        the last write got, and only rows at or after it are sent.

        The watermark is the **second-to-last** bar's timestamp, not the last.
        The most recent candle is still forming — its high, low, close and
        volume all change until the bar closes — so it must be rewritten every
        cycle. Watermarking on the last bar would freeze a partial candle in the
        table and never correct it, which is the one error this table cannot
        afford: every profile, VWAP and value area downstream reads it.

        `full=True` forces a complete rewrite. No watermark (a fresh session, or
        an app reset) also writes everything, once — which is what makes this
        safe: the fallback is the old behaviour, not a gap.
        """
        if df is None or getattr(df, 'empty', True):
            return
        key = f"{symbol}|{exchange}|{timeframe}"
        mark = None if full else self._candle_mark(key)

        out = df
        if mark is not None:
            try:
                out = df[df['timestamp'] >= mark]
            except Exception:
                out = df
        if getattr(out, 'empty', True):
            return                      # nothing has moved since the last write

        records = []
        for _, row in out.iterrows():
            dt = row['datetime']
            records.append({
                'symbol': symbol, 'exchange': exchange, 'timeframe': timeframe,
                'timestamp': int(row['timestamp']),
                'datetime': dt.isoformat(),
                'trading_day': dt.date().isoformat() if hasattr(dt, 'date') else str(dt)[:10],
                'open': float(row['open']), 'high': float(row['high']),
                'low': float(row['low']), 'close': float(row['close']),
                'volume': int(row['volume']),
                'data_source': 'dhan_intraday',
                'update_time': datetime.now(IST).isoformat()
            })
        self._safe_upsert('candles_data', records, 'symbol,exchange,timeframe,timestamp')

        try:
            stamps = sorted(int(t) for t in df['timestamp'])
            # second-to-last, so the forming bar is rewritten next cycle
            self._set_candle_mark(key, stamps[-2] if len(stamps) >= 2 else stamps[-1])
            counters = st.session_state.setdefault(
                '_candle_write_stats', {'calls': 0, 'rows': 0, 'full_rows': 0})
            counters['calls'] += 1
            counters['rows'] += len(records)
            counters['full_rows'] += len(df)
        except Exception:
            pass

    #: Most candles any one chart read may return. A 1-minute series is 375
    #: bars a trading day, so this is roughly a month — more than any chart
    #: draws, and a ceiling on a `hours_back` a caller got wrong.
    CANDLE_ROWS_MAX = 12000

    def get_candles(self, symbol, exchange, timeframe, hours_back=24):
        """Recent candles, oldest first — the shape every chart consumes.

        ⚠️ The database is asked **newest first** and the frame is reversed
        here, which is not cosmetic: with a `.limit()` and ascending order the
        rows dropped would be the newest ones, and a chart missing its live
        edge is worse than a chart missing its history.
        """
        cutoff = (datetime.now(IST) - timedelta(hours=hours_back)).isoformat()
        def query():
            return self.client.table('candles_data').select('*') \
                .eq('symbol', symbol).eq('exchange', exchange).eq('timeframe', timeframe) \
                .gte('datetime', cutoff).order('timestamp', desc=True) \
                .limit(self.CANDLE_ROWS_MAX).execute()
        df = self._safe_query('candles_data', query, {'symbol': symbol, 'timeframe': timeframe})
        if not df.empty:
            if 'datetime' in df.columns:
                df['datetime'] = pd.to_datetime(df['datetime'])
            if 'timestamp' in df.columns:
                df = df.sort_values('timestamp').reset_index(drop=True)
            else:
                df = df.iloc[::-1].reset_index(drop=True)
        return df

    # ── Historical backfill (Stage 2) ──
    #: How many recent candle rows are enough to name every series being
    #: collected. At ~375 bars a day per series this covers several days.
    #:
    #: ⚠️ The bound is the point. This query used to have no filter and no
    #: limit — a full scan of `candles_data`, the largest table in the app,
    #: pulled three columns of every candle ever stored just to derive a
    #: handful of distinct tuples. A series that stopped being collected days
    #: ago now drops off the list, which is the correct answer for a "what is
    #: being collected" question anyway.
    CANDLE_SERIES_SCAN = 5000

    def get_available_candle_series(self):
        """Distinct (symbol, exchange, timeframe) combos recently present in
        candles_data. The chart's timeframe is a user-selectable sidebar
        dropdown (default 3-min, not 1-min) — callers must never hardcode a
        timeframe guess; detect what's really been collected instead."""
        def query():
            return (self.client.table('candles_data')
                    .select('symbol,exchange,timeframe')
                    .order('timestamp', desc=True)
                    .limit(self.CANDLE_SERIES_SCAN).execute())
        res = self._safe_query('candles_data', query)
        try:
            rows = res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            rows = []
        return sorted({(r['symbol'], r['exchange'], r['timeframe']) for r in rows
                       if r.get('symbol') and r.get('exchange') and r.get('timeframe')})

    #: Rows scanned to derive the list of collected trading days. Roughly two
    #: months of one-minute candles for a single series.
    CANDLE_DAYS_SCAN = 25000

    def get_candle_trading_days(self, symbol, exchange, timeframe):
        """Distinct trading days already collected, ascending — the backfill
        scope, most recent first and bounded.

        ⚠️ Bounded because this had no limit: reading one column of every
        candle ever collected for a series — tens of thousands of rows — to
        derive a few dozen distinct dates. `latest_candle_day_before` is the
        cheaper answer when only the previous session is wanted, which is what
        every caller on the render path actually asks for.
        """
        def query():
            return (self.client.table('candles_data').select('trading_day')
                    .eq('symbol', symbol).eq('exchange', exchange).eq('timeframe', timeframe)
                    .order('trading_day', desc=True)
                    .limit(self.CANDLE_DAYS_SCAN).execute())
        res = self._safe_query('candles_data', query, {'symbol': symbol, 'timeframe': timeframe})
        try:
            rows = res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            rows = []
        days = sorted({r['trading_day'] for r in rows if r.get('trading_day')})
        return days

    def latest_candle_day_before(self, symbol, exchange, day):
        """The most recent collected trading day before `day`, and the
        timeframe it was collected at — as `(trading_day, timeframe)`.

        One row. The previous session's value area needs exactly this, and used
        to derive it from two unbounded scans of `candles_data`: every row in
        the table to list the series, then every row of that series to list its
        days. Both answers were thrown away except for one date.

        `timeframe` comes back rather than being passed in because the chart's
        timeframe is a sidebar choice and callers must not guess it.
        """
        if not day:
            return None, None
        def query():
            return (self.client.table('candles_data').select('trading_day,timeframe')
                    .eq('symbol', symbol).eq('exchange', exchange)
                    .lt('trading_day', str(day))
                    .order('trading_day', desc=True).limit(1).execute())
        res = self._safe_query('candles_data', query,
                               {'symbol': symbol, 'exchange': exchange, 'day': day})
        try:
            rows = res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            rows = []
        if not rows:
            return None, None
        row = rows[0]
        return row.get('trading_day'), row.get('timeframe')

    def get_candles_for_day(self, symbol, exchange, timeframe, trading_day):
        """One specific day's candles, oldest first — not limited by
        get_candles()'s recency window.

        The `.limit()` never binds: a trading day is 375 one-minute bars. It is
        there so a wrong `trading_day` — an empty string, a value the filter
        does not narrow — cannot turn this into a full-table read.
        """
        def query():
            return (self.client.table('candles_data').select('*')
                    .eq('symbol', symbol).eq('exchange', exchange).eq('timeframe', timeframe)
                    .eq('trading_day', trading_day).order('timestamp', desc=False)
                    .limit(self.CANDLE_ROWS_MAX).execute())
        df = self._safe_query('candles_data', query,
                              {'symbol': symbol, 'timeframe': timeframe, 'trading_day': trading_day})
        if not df.empty and 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
        return df

    def get_backfill_progress(self, job_name):
        def query():
            return (self.client.table('backfill_progress').select('*')
                    .eq('job_name', job_name).limit(1).execute())
        res = self._safe_query('backfill_progress', query, {'job_name': job_name})
        try:
            rows = res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            rows = []
        return rows[0] if rows else None

    def upsert_backfill_progress(self, job_name, fields):
        row = {'job_name': job_name, 'updated_at': datetime.now(IST).isoformat(), **fields}
        self._safe_upsert('backfill_progress', [row], 'job_name')

    def clear_old_candles(self, days_old=7):
        try:
            cutoff = (datetime.now(IST) - timedelta(days=days_old)).isoformat()
            result = self.client.table('candles_data').delete().lt('datetime', cutoff).execute()
            return len(result.data) if result.data else 0
        except:
            return 0

    # ── Spot Data ──
    def upsert_spot_data(self, ltp, security_id='13', exchange_segment='IDX_I'):
        now = datetime.now(IST)
        record = {
            'timestamp': now.isoformat(),
            'trading_day': now.date().isoformat(),
            'ltp': float(ltp),
            'security_id': security_id,
            'exchange_segment': exchange_segment,
            'data_source': 'dhan_ltp',
            'update_time': datetime.now(IST).isoformat()
        }
        self._safe_upsert('nifty_spot_data', [record], 'timestamp,security_id')

    def get_latest_spot(self, security_id='13'):
        def query():
            return self.client.table('nifty_spot_data').select('*') \
                .eq('security_id', security_id).order('timestamp', desc=True).limit(1).execute()
        df = self._safe_query('nifty_spot_data', query, {'security_id': security_id})
        if not df.empty:
            return df.iloc[0].to_dict()
        return None

    def get_day_open_spot(self, trading_day=None, security_id='13'):
        """The day's OPENING spot — the earliest nifty_spot_data row for the
        trading day. Since the spot feed updates from the ~09:06 pre-open print,
        this is the opening/gap price, available before the first 09:15 candle
        exists. Returns the row dict (with 'ltp' + 'timestamp') or None."""
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            return self.client.table('nifty_spot_data').select('*') \
                .eq('security_id', security_id).eq('trading_day', trading_day) \
                .order('timestamp', desc=False).limit(1).execute()
        df = self._safe_query('nifty_spot_data', query,
                              {'security_id': security_id, 'trading_day': trading_day})
        if not df.empty:
            return df.iloc[0].to_dict()
        return None

    def insert_mios_decision(self, row):
        """Append one Decision-Engine state-transition row (validation log)."""
        row = dict(row)
        row.setdefault('ts', datetime.now(IST).isoformat())
        def query():
            return self.client.table('mios_decisions').insert(row, returning='minimal').execute()
        self._safe_query('mios_decisions', query)

    def get_mios_decisions(self, trading_day=None, rejected_only=False, limit=300):
        def query():
            q = self.client.table('mios_decisions').select('*')
            if trading_day:
                q = q.eq('trading_day', trading_day)
            if rejected_only:
                q = q.eq('rejected', True)
            return q.order('ts', desc=True).limit(limit).execute()
        return self._safe_query('mios_decisions', query, {'trading_day': trading_day})

    # ── Signal Lifecycle (trade_signals) ─────────────────────────────────
    # Rows are keyed and updated by the SIG-YYYYMMDD-NNN `signal_id` string the
    # app generates, so we never depend on the DB's numeric id round-trip.
    def insert_trade_signal(self, row):
        """Create one lifecycle row (status WAIT_ENTRY)."""
        row = dict(row)
        row.setdefault('created_at', datetime.now(IST).isoformat())
        row.setdefault('updated_at', row['created_at'])
        try:
            self.client.table('trade_signals').insert(row, returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def update_trade_signal(self, signal_id, fields):
        """Advance a lifecycle row in place (keyed by signal_id)."""
        if not signal_id:
            return False
        fields = dict(fields)
        fields['updated_at'] = datetime.now(IST).isoformat()
        try:
            self.client.table('trade_signals').update(
                fields, returning=self._WRITE_RETURNING).eq(
                'signal_id', signal_id).execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_active_trade_signal(self):
        """The one live (non-terminal) signal as a dict, if any — enforces
        one-signal-at-a-time across restarts."""
        def query():
            return (self.client.table('trade_signals').select('*')
                    .in_('status', ['WAIT_ENTRY', 'ENTERED'])
                    .order('created_at', desc=True).limit(1).execute())
        df = self._safe_query('trade_signals', query)
        if df is None or getattr(df, 'empty', True):
            return None
        return df.iloc[0].to_dict()

    def get_trade_signals(self, trading_day=None, limit=500):
        """Lifecycle history (newest first) as a DataFrame for the history panel.

        Projected: the `engine_snapshot` blob is not read by the history table
        or by replay, which are this method's only two callers.
        """
        def query():
            q = self.client.table('trade_signals').select(
                projection('trade_signals'))
            if trading_day:
                q = q.eq('trading_day', trading_day)
            return q.order('created_at', desc=True).limit(limit).execute()
        return self._safe_query('trade_signals', query, {'trading_day': trading_day})

    def count_trade_signals_today(self, trading_day):
        """How many signals were born today — for the SIG-YYYYMMDD-NNN counter."""
        def query():
            return (self.client.table('trade_signals').select('id')
                    .eq('trading_day', trading_day).execute())
        df = self._safe_query('trade_signals', query, {'trading_day': trading_day})
        return 0 if df is None or getattr(df, 'empty', True) else len(df)

    # ── 🎓 Phase 6 · Learning & Validation (sql/027_learning.sql) ────────
    # Every method here is INSERT or SELECT. There is deliberately no update
    # and no delete: the Learning Engine's record is append-only, because
    # replay and backtesting are only honest if the row shows what was known
    # at the time rather than what the last write happened to leave behind.
    def insert_trade_attribution(self, row):
        """Stage 55 — the state of the world at signal birth. Written once."""
        try:
            self.client.table('trade_attribution').insert(dict(row), returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def insert_engine_attribution(self, rows):
        """Stage 55 — one row per engine per trade. This is what makes
        per-engine accuracy possible; without it there is only a blended win
        rate that cannot tell you which engine to fix."""
        rows = [dict(r) for r in (rows or [])]
        if not rows:
            return False
        try:
            self.client.table('engine_attribution').insert(rows, returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def insert_trade_event(self, row):
        """Stage 55 — one append-only event in the life of a trade."""
        try:
            self.client.table('trade_events').insert(dict(row), returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def insert_trade_result(self, row):
        """Stage 55 — the outcome, written once at exit and never revised."""
        try:
            self.client.table('trade_results').insert(dict(row), returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def insert_learning_snapshot(self, rows):
        """Stages 56-60 — the learning output is itself history."""
        rows = [dict(r) for r in (rows or [])]
        if not rows:
            return False
        try:
            self.client.table('learning_snapshots').insert(rows, returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def _learning_rows(self, table, limit, order='created_at'):
        """Newest-first records as plain dicts — the order every rolling window
        in Stages 56/57 assumes.

        Reads through `projection()`, so `engine_attribution` — the widest read
        in the app at 8,000 rows — arrives without its unread `data` blob.
        `order` is applied by PostgREST and does not require the column to be
        in the projection.
        """
        def query():
            return (self.client.table(table).select(projection(table))
                    .order(order, desc=True).limit(limit).execute())
        res = self._safe_query(table, query)
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    def get_trade_attribution(self, limit=500):
        return self._learning_rows('trade_attribution', limit)

    def get_engine_attribution(self, limit=8000):
        return self._learning_rows('engine_attribution', limit)

    def get_trade_events(self, limit=4000):
        return self._learning_rows('trade_events', limit, order='ts')

    def get_trade_results(self, limit=500):
        return self._learning_rows('trade_results', limit)

    def get_learning_snapshots(self, stage=None, limit=100):
        def query():
            q = self.client.table('learning_snapshots').select('*')
            if stage:
                q = q.eq('stage', stage)
            return q.order('created_at', desc=True).limit(limit).execute()
        res = self._safe_query('learning_snapshots', query, {'stage': stage})
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    # ── 🗓 Stage 68 · Market Day Classification (sql/028_day_type_log.sql) ──
    # One row per CHARACTER CHANGE, not per cycle. Append-only.
    def insert_day_type(self, row):
        try:
            self.client.table('day_type_log').insert(dict(row), returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_day_type_log(self, trading_day=None, limit=500):
        """Classification history as plain dicts, OLDEST FIRST — attributing a
        trade to the type in force when it was taken needs forward order."""
        def query():
            q = self.client.table('day_type_log').select('*')
            if trading_day:
                q = q.eq('trading_day', trading_day)
            return q.order('ts', desc=False).limit(limit).execute()
        res = self._safe_query('day_type_log', query, {'trading_day': trading_day})
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    # ── 🕘 Stage 69 · Session Intelligence (sql/029_session_log.sql) ────
    def insert_session_log(self, row):
        try:
            self.client.table('session_log').insert(dict(row), returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_session_log(self, trading_day=None, limit=2000):
        """Session history, OLDEST FIRST — attributing a trade to the session
        in force when it was taken needs forward order."""
        def query():
            q = self.client.table('session_log').select('*')
            if trading_day:
                q = q.eq('trading_day', trading_day)
            return q.order('ts', desc=False).limit(limit).execute()
        res = self._safe_query('session_log', query, {'trading_day': trading_day})
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    # ── 🔬 Stage 70 · Session Validation (sql/030_session_validation.sql) ──
    def insert_session_recommendations(self, rows):
        rows = [dict(r) for r in (rows or [])]
        if not rows:
            return False
        try:
            self.client.table('session_recommendations').insert(rows, returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_session_recommendations(self, limit=500):
        def query():
            return (self.client.table('session_recommendations').select('*')
                    .order('created_at', desc=False).limit(limit).execute())
        res = self._safe_query('session_recommendations', query)
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    def insert_session_validation(self, row):
        try:
            self.client.table('session_validation_log').insert(dict(row), returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_session_validation(self, limit=200):
        def query():
            return (self.client.table('session_validation_log').select('*')
                    .order('created_at', desc=True).limit(limit).execute())
        res = self._safe_query('session_validation_log', query)
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    def upsert_event_impact(self, row):
        """Upsert one Event History Library row per (trading_day, event), updated
        through the session so it captures the peak impact. Observation logging."""
        row = dict(row)
        row.setdefault('updated_at', datetime.now(IST).isoformat())
        self._safe_upsert('event_impact_log', [row], 'trading_day,event_name')

    def get_event_impact_log(self, event_name=None, limit=200):
        """Past event impacts (optionally filtered to one event) for the Library."""
        def query():
            q = self.client.table('event_impact_log').select('*')
            if event_name:
                q = q.eq('event_name', event_name)
            return q.order('trading_day', desc=True).limit(limit).execute()
        return self._safe_query('event_impact_log', query, {'event_name': event_name})

    def upsert_opening_auction(self, row):
        """Upsert one opening-auction observation row per trading day (keyed by
        trading_day), updated through the session. Pure observation logging."""
        row = dict(row)
        row.setdefault('updated_at', datetime.now(IST).isoformat())
        self._safe_upsert('opening_auction_log', [row], 'trading_day')

    def get_opening_auction_log(self, limit=60):
        """Recent opening-auction observations, newest first (for later review)."""
        def query():
            return (self.client.table('opening_auction_log').select('*')
                    .order('trading_day', desc=True).limit(limit).execute())
        return self._safe_query('opening_auction_log', query)

    def get_spot_history(self, trading_day=None, security_id='13'):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            return self.client.table('nifty_spot_data').select('*') \
                .eq('security_id', security_id).eq('trading_day', trading_day) \
                .order('timestamp', desc=False).execute()
        return self._safe_query('nifty_spot_data', query, {'security_id': security_id, 'trading_day': trading_day})

    # ── Option Chain ──
    # Columns typed BIGINT in option_chain_data — must be sent as int, not
    # float, or PostgREST rejects "1495.0" with 22P02 (invalid input syntax
    # for type bigint).
    _OC_BIGINT_COLS = {
        'open_interest_ce', 'previous_oi_ce', 'change_in_oi_ce', 'volume_ce',
        'bid_qty_ce', 'ask_qty_ce',
        'open_interest_pe', 'previous_oi_pe', 'change_in_oi_pe', 'volume_pe',
        'bid_qty_pe', 'ask_qty_pe',
    }

    def upsert_option_chain(self, df, expiry, underlying_price, atm_strike):
        now = datetime.now(IST)
        records = []
        for _, row in df.iterrows():
            rec = {
                'timestamp': now.isoformat(),
                'trading_day': now.date().isoformat(),
                'expiry': expiry,
                'strike_price': float(row['strikePrice']),
                'atm_strike': float(atm_strike),
                'underlying_price': float(underlying_price),
                'data_source': 'dhan_optionchain',
                'update_time': datetime.now(IST).isoformat()
            }
            for db_col, df_col in [
                ('last_price_ce', 'lastPrice_CE'), ('open_interest_ce', 'openInterest_CE'),
                ('previous_oi_ce', 'previousOpenInterest_CE'), ('change_in_oi_ce', 'changeinOpenInterest_CE'),
                ('volume_ce', 'totalTradedVolume_CE'), ('iv_ce', 'impliedVolatility_CE'),
                ('bid_qty_ce', 'bidQty_CE'), ('ask_qty_ce', 'askQty_CE'),
                ('last_price_pe', 'lastPrice_PE'), ('open_interest_pe', 'openInterest_PE'),
                ('previous_oi_pe', 'previousOpenInterest_PE'), ('change_in_oi_pe', 'changeinOpenInterest_PE'),
                ('volume_pe', 'totalTradedVolume_PE'), ('iv_pe', 'impliedVolatility_PE'),
                ('bid_qty_pe', 'bidQty_PE'), ('ask_qty_pe', 'askQty_PE'),
                ('delta_ce', 'Delta_CE'), ('gamma_ce', 'Gamma_CE'), ('vega_ce', 'Vega_CE'),
                ('theta_ce', 'Theta_CE'), ('rho_ce', 'Rho_CE'),
                ('delta_pe', 'Delta_PE'), ('gamma_pe', 'Gamma_PE'), ('vega_pe', 'Vega_PE'),
                ('theta_pe', 'Theta_PE'), ('rho_pe', 'Rho_PE'),
            ]:
                val = row.get(df_col)
                if not pd.notna(val):
                    rec[db_col] = None
                elif db_col in self._OC_BIGINT_COLS:
                    rec[db_col] = int(val)
                else:
                    rec[db_col] = float(val)
            records.append(rec)
        self._safe_upsert('option_chain_data', records, 'timestamp,expiry,strike_price')

    def get_option_chain(self, expiry, trading_day=None):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            return self.client.table('option_chain_data').select('*') \
                .eq('expiry', expiry).eq('trading_day', trading_day) \
                .order('timestamp', desc=True).limit(20).execute()
        return self._safe_query('option_chain_data', query, {'expiry': expiry, 'trading_day': trading_day})

    def get_option_chain_history(self, expiry, strike_price, trading_day=None):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            return self.client.table('option_chain_data').select('*') \
                .eq('expiry', expiry).eq('strike_price', strike_price) \
                .eq('trading_day', trading_day).order('timestamp', desc=False).execute()
        return self._safe_query('option_chain_data', query)

    # ── ATM Strike Data ──
    def upsert_atm_strike_data(self, df_summary, expiry, underlying_price, atm_strike):
        now = datetime.now(IST)
        records = []
        col_map = {
            'Strike': 'strike_price', 'Zone': 'zone', 'Level': 'level',
            'PCR': 'pcr', 'PCR_Signal': 'pcr_signal',
            'BiasScore': 'bias_score', 'Verdict': 'verdict',
            'LTP_Bias': 'ltp_bias', 'OI_Bias': 'oi_bias', 'ChgOI_Bias': 'chg_oi_bias',
            'Volume_Bias': 'volume_bias', 'Delta_Bias': 'delta_bias', 'Gamma_Bias': 'gamma_bias',
            'Theta_Bias': 'theta_bias', 'AskQty_Bias': 'ask_qty_bias', 'BidQty_Bias': 'bid_qty_bias',
            'AskBid_Bias': 'ask_bid_bias', 'IV_Bias': 'iv_bias', 'DVP_Bias': 'dvp_bias',
            'PressureBias': 'pressure_bias', 'DeltaExp': 'delta_exp', 'GammaExp': 'gamma_exp',
            'Operator_Entry': 'operator_entry', 'Scalp_Moment': 'scalp_moment', 'FakeReal': 'fake_real',
            'BidAskPressure': 'bid_ask_pressure',
            'Gamma_SR': 'gamma_sr', 'Delta_SR': 'delta_sr', 'Depth_SR': 'depth_sr',
            'OI_Wall': 'oi_wall', 'ChgOI_Wall': 'chg_oi_wall', 'Max_Pain': 'max_pain',
        }
        for _, row in df_summary.iterrows():
            rec = {
                'timestamp': now.isoformat(),
                'trading_day': now.date().isoformat(),
                'expiry': expiry,
                'atm_strike': float(atm_strike),
                'underlying_price': float(underlying_price),
                'data_source': 'computed',
                'update_time': datetime.now(IST).isoformat()
            }
            for src, dst in col_map.items():
                val = row.get(src)
                if pd.notna(val) if not isinstance(val, str) else True:
                    if isinstance(val, (int, float, np.integer, np.floating)):
                        # bias_score is INTEGER in the schema — PostgREST
                        # rejects "-4.0" with 22P02 (invalid input syntax
                        # for type integer); every other numeric column here
                        # is NUMERIC and accepts floats fine.
                        rec[dst] = int(val) if dst == 'bias_score' else float(val)
                    else:
                        rec[dst] = str(val)
            records.append(rec)
        self._safe_upsert('atm_strike_data', records, 'timestamp,expiry,strike_price')

    def get_atm_strike_data(self, expiry, trading_day=None):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            return self.client.table('atm_strike_data').select('*') \
                .eq('expiry', expiry).eq('trading_day', trading_day) \
                .order('timestamp', desc=True).limit(20).execute()
        return self._safe_query('atm_strike_data', query, {'expiry': expiry})

    # ── PCR History ──
    def upsert_pcr_history(self, entries):
        now = datetime.now(IST)
        records = []
        for e in entries:
            records.append({
                'timestamp': e.get('timestamp', now).isoformat() if hasattr(e.get('timestamp', now), 'isoformat') else str(e.get('timestamp', now)),
                'trading_day': now.date().isoformat(),
                'expiry': e['expiry'],
                'strike_price': float(e['strike']),
                'atm_strike': float(e.get('atm_strike', 0)),
                'pcr_value': float(e['pcr']),
                'oi_ce': int(e.get('oi_ce', 0)),
                'oi_pe': int(e.get('oi_pe', 0)),
                'data_source': 'computed',
                'update_time': datetime.now(IST).isoformat()
            })
        self._safe_upsert('pcr_history', records, 'timestamp,expiry,strike_price')

    def get_pcr_history(self, trading_day=None, expiry=None, strikes=None):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            q = self.client.table('pcr_history').select('*').eq('trading_day', trading_day)
            if expiry:
                q = q.eq('expiry', expiry)
            return q.order('timestamp', desc=False).execute()
        df = self._safe_query('pcr_history', query, {'trading_day': trading_day})
        if not df.empty and strikes:
            df = df[df['strike_price'].isin([float(s) for s in strikes])]
        return df

    # ── GEX History ──
    def upsert_gex_history(self, entries):
        now = datetime.now(IST)
        records = []
        for e in entries:
            records.append({
                'timestamp': e.get('timestamp', now).isoformat() if hasattr(e.get('timestamp', now), 'isoformat') else str(e.get('timestamp', now)),
                'trading_day': now.date().isoformat(),
                'expiry': e['expiry'],
                'strike_price': float(e.get('strike', 0)),
                'atm_strike': float(e.get('atm_strike', 0)),
                'total_gex': float(e.get('total_gex', 0)),
                'call_gex': float(e.get('call_gex', 0)),
                'put_gex': float(e.get('put_gex', 0)),
                'net_gex': float(e.get('net_gex', 0)),
                'gamma_flip_level': float(e['gamma_flip']) if e.get('gamma_flip') else None,
                'gex_signal': e.get('signal', ''),
                'spot_price': float(e.get('spot', 0)),
                'data_source': 'computed',
                'update_time': datetime.now(IST).isoformat()
            })
        self._safe_upsert('gex_history', records, 'timestamp,expiry,strike_price')

    def get_gex_history(self, trading_day=None, expiry=None, strikes=None):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            q = self.client.table('gex_history').select('*').eq('trading_day', trading_day)
            if expiry:
                q = q.eq('expiry', expiry)
            return q.order('timestamp', desc=False).execute()
        df = self._safe_query('gex_history', query, {'trading_day': trading_day})
        if not df.empty and strikes:
            df = df[df['strike_price'].isin([float(s) for s in strikes])]
        return df

    # ── Bid/Ask Qty History (per-strike option-chain snapshot) ──
    def upsert_bid_ask_history(self, entries):
        if not entries:
            return
        now = datetime.now(IST)
        records = []
        for e in entries:
            ts = e.get('timestamp', now)
            records.append({
                'timestamp': ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
                'trading_day': now.date().isoformat(),
                'expiry': e['expiry'],
                'strike_price': float(e['strike']),
                'atm_strike': float(e.get('atm_strike', 0)),
                'bid_qty_ce': int(e.get('bid_qty_ce', 0)),
                'bid_qty_pe': int(e.get('bid_qty_pe', 0)),
                'ask_qty_ce': int(e.get('ask_qty_ce', 0)),
                'ask_qty_pe': int(e.get('ask_qty_pe', 0)),
                'volume_ce': int(e.get('volume_ce', 0)),
                'volume_pe': int(e.get('volume_pe', 0)),
                'oi_ce': int(e.get('oi_ce', 0)),
                'oi_pe': int(e.get('oi_pe', 0)),
                'chgoi_ce': int(e.get('chgoi_ce', 0)),
                'chgoi_pe': int(e.get('chgoi_pe', 0)),
                'ltp_ce': float(e.get('ltp_ce', 0)),
                'ltp_pe': float(e.get('ltp_pe', 0)),
                'data_source': 'computed',
                'update_time': datetime.now(IST).isoformat()
            })
        self._safe_upsert('bid_ask_history', records, 'timestamp,expiry,strike_price')

    def get_bid_ask_history(self, trading_day=None, expiry=None, strikes=None):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            q = self.client.table('bid_ask_history').select('*').eq('trading_day', trading_day)
            if expiry:
                q = q.eq('expiry', expiry)
            return q.order('timestamp', desc=False).execute()
        df = self._safe_query('bid_ask_history', query, {'trading_day': trading_day})
        if not df.empty and strikes:
            df = df[df['strike_price'].isin([float(s) for s in strikes])]
        return df

    # ── Volume Delta History (index-level Buy/Sell time series) ──
    def upsert_volume_delta_history(self, entries, symbol='NIFTY50'):
        if not entries:
            return
        now = datetime.now(IST)
        records = []
        for e in entries:
            ts = e.get('timestamp', now)
            records.append({
                'timestamp': ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
                'trading_day': now.date().isoformat(),
                'symbol': symbol,
                'buy_volume': int(e.get('buy_volume', 0)),
                'sell_volume': int(e.get('sell_volume', 0)),
                'delta': int(e.get('delta', 0)),
                'cum_delta': int(e.get('cum_delta', 0)),
                'divergence': bool(e.get('divergence', False)),
                'bias': str(e.get('bias', '')),
                'update_time': datetime.now(IST).isoformat()
            })
        self._safe_upsert('volume_delta_history', records, 'timestamp,symbol')

    def get_volume_delta_history(self, trading_day=None, symbol='NIFTY50'):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            return self.client.table('volume_delta_history').select('*') \
                .eq('trading_day', trading_day).eq('symbol', symbol) \
                .order('timestamp', desc=False).execute()
        return self._safe_query('volume_delta_history', query, {'trading_day': trading_day, 'symbol': symbol})

    # ── Detected Patterns ──
    def upsert_detected_patterns(self, patterns):
        if not patterns:
            return
        now = datetime.now(IST)
        records = []
        for p in patterns:
            rec = {
                'timestamp': p.get('timestamp', now).isoformat() if hasattr(p.get('timestamp', now), 'isoformat') else str(p.get('timestamp', now)),
                'trading_day': now.date().isoformat(),
                'pattern_type': p['pattern_type'],
                'timeframe': p.get('timeframe'),
                'direction': p.get('direction'),
                'price_level': float(p['price_level']) if p.get('price_level') else None,
                'upper_bound': float(p['upper_bound']) if p.get('upper_bound') else None,
                'lower_bound': float(p['lower_bound']) if p.get('lower_bound') else None,
                'score': float(p['score']) if p.get('score') else None,
                'metadata': json.dumps(p.get('metadata', {})),
                'data_source': 'computed',
                'update_time': datetime.now(IST).isoformat()
            }
            records.append(rec)
        self._safe_upsert('detected_patterns', records, 'timestamp,pattern_type,price_level,timeframe')

    def get_detected_patterns(self, trading_day=None, pattern_type=None):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            q = self.client.table('detected_patterns').select('*').eq('trading_day', trading_day)
            if pattern_type:
                q = q.eq('pattern_type', pattern_type)
            return q.order('timestamp', desc=False).execute()
        return self._safe_query('detected_patterns', query, {'trading_day': trading_day})

    # ── Orderbook ──
    def upsert_orderbook(self, data, expiry):
        now = datetime.now(IST)
        records = []
        for entry in data:
            records.append({
                'timestamp': now.isoformat(),
                'trading_day': now.date().isoformat(),
                'expiry': expiry,
                'strike_price': float(entry['strike']),
                'bid_qty_ce': int(entry.get('bid_qty_ce', 0)),
                'ask_qty_ce': int(entry.get('ask_qty_ce', 0)),
                'bid_qty_pe': int(entry.get('bid_qty_pe', 0)),
                'ask_qty_pe': int(entry.get('ask_qty_pe', 0)),
                'bid_ask_pressure': float(entry.get('pressure', 0)),
                'pressure_bias': entry.get('bias', ''),
                'data_source': 'dhan_optionchain',
                'update_time': datetime.now(IST).isoformat()
            })
        self._safe_upsert('orderbook_data', records, 'timestamp,expiry,strike_price')

    def get_orderbook(self, expiry, trading_day=None):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            return self.client.table('orderbook_data').select('*') \
                .eq('expiry', expiry).eq('trading_day', trading_day) \
                .order('timestamp', desc=True).limit(20).execute()
        return self._safe_query('orderbook_data', query, {'expiry': expiry})

    # ── Option Chain Signal History ──
    def upsert_oc_signal(self, record):
        now = datetime.now(IST)
        row = {
            'timestamp': record.get('timestamp', now.isoformat()),
            'trading_day': now.date().isoformat(),
            'spot_price': float(record['spot_price']),
            'condition': record['condition'],
            'confidence': int(record['confidence']),
            'resistance_strikes': json.dumps(record.get('resistance_strikes', [])),
            'support_strikes': json.dumps(record.get('support_strikes', [])),
            'active_signals': json.dumps(record.get('active_signals', [])),
            'breakout_level': record.get('breakout_level'),
            'breakdown_level': record.get('breakdown_level'),
            'bias_reasoning': json.dumps(record.get('bias_reasoning', [])),
        }
        self._safe_upsert('oc_signal_history', [row], 'timestamp')

    def get_oc_signals(self, trading_day=None, limit=50):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            return self.client.table('oc_signal_history').select('*') \
                .eq('trading_day', trading_day) \
                .order('timestamp', desc=True).limit(limit).execute()
        return self._safe_query('oc_signal_history', query, {'trading_day': trading_day})

    # ── User Preferences (carried over) ──
    @staticmethod
    def _default_prefs():
        return {'timeframe': '5', 'auto_refresh': True, 'days_back': 1, 'pivot_proximity': 5,
                'pivot_settings': {'show_3m': True, 'show_5m': True, 'show_10m': True, 'show_15m': True}}

    def save_user_preferences(self, user_id, timeframe, auto_refresh, days_back, pivot_settings, pivot_proximity=5):
        try:
            data = {
                'user_id': user_id, 'timeframe': timeframe, 'auto_refresh': auto_refresh,
                'days_back': days_back, 'pivot_settings': json.dumps(pivot_settings),
                'pivot_proximity': pivot_proximity, 'updated_at': datetime.now(IST).isoformat()
            }
            self.client.table('user_preferences').upsert(data, on_conflict="user_id", returning='minimal').execute()
        except Exception as e:
            if "23505" not in str(e) and "duplicate key" not in str(e).lower():
                st.error(f"Error saving preferences: {str(e)}")

    def get_user_preferences(self, user_id):
        try:
            result = self.client.table('user_preferences').select('*').eq('user_id', user_id).execute()
            if result.data:
                prefs = result.data[0]
                if 'pivot_settings' in prefs and prefs['pivot_settings']:
                    prefs['pivot_settings'] = json.loads(prefs['pivot_settings'])
                else:
                    prefs['pivot_settings'] = {'show_3m': True, 'show_5m': True, 'show_10m': True, 'show_15m': True}
                return prefs
            return self._default_prefs()
        except:
            return self._default_prefs()

    # ── Market Analytics (carried over) ──
    def save_market_analytics(self, symbol, analytics_data):
        try:
            data = {'symbol': symbol, 'date': datetime.now(IST).date().isoformat()}
            data.update({k: analytics_data[k] for k in ['day_high', 'day_low', 'day_open', 'day_close', 'total_volume', 'avg_price', 'price_change', 'price_change_pct']})
            self.client.table('market_analytics').upsert(data, on_conflict="symbol,date", returning='minimal').execute()
        except Exception as e:
            if "23505" not in str(e) and "duplicate key" not in str(e).lower():
                st.error(f"Error saving analytics: {str(e)}")

    def get_market_analytics(self, symbol, days_back=30):
        try:
            cutoff = (datetime.now().date() - timedelta(days=days_back)).isoformat()
            result = self.client.table('market_analytics').select('*') \
                .eq('symbol', symbol).gte('date', cutoff).order('date', desc=False).execute()
            return pd.DataFrame(result.data) if result.data else pd.DataFrame()
        except:
            return pd.DataFrame()

    # ── Alerts History ──
    def upsert_alert(self, alert_type, direction=None, strike_price=None, underlying_price=None,
                     signal_details=None, score=None, metadata=None, sent_via='telegram'):
        now = datetime.now(IST)
        record = {
            'timestamp': now.isoformat(),
            'trading_day': now.date().isoformat(),
            'alert_type': alert_type,
            'direction': direction,
            'strike_price': float(strike_price) if strike_price else None,
            'underlying_price': float(underlying_price) if underlying_price else None,
            'signal_details': signal_details,
            'score': float(score) if score else None,
            'metadata': json.dumps(metadata) if metadata else None,
            'sent_via': sent_via,
            'data_source': 'computed',
            'update_time': datetime.now(IST).isoformat()
        }
        self._safe_upsert('alerts_history', [record], 'timestamp,alert_type,strike_price')

    def get_alerts_history(self, trading_day=None, alert_type=None):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            q = self.client.table('alerts_history').select('*').eq('trading_day', trading_day)
            if alert_type:
                q = q.eq('alert_type', alert_type)
            return q.order('timestamp', desc=False).execute()
        return self._safe_query('alerts_history', query, {'trading_day': trading_day})

    # ── Master Signal History ──
    def upsert_master_signal(self, signal_data):
        """Store master trading signal with all details."""
        now = datetime.now(IST)
        record = {
            'timestamp': now.isoformat(),
            'trading_day': now.date().isoformat(),
            'spot_price': float(signal_data.get('spot_price', 0)),
            'signal': signal_data.get('signal', ''),
            'trade_type': signal_data.get('trade_type', ''),
            'score': int(signal_data.get('score', 0)),
            'abs_score': int(signal_data.get('abs_score', 0)),
            'strength': signal_data.get('strength', ''),
            'confidence': int(signal_data.get('confidence', 0)),
            'candle_pattern': signal_data.get('candle_pattern', ''),
            'candle_direction': signal_data.get('candle_direction', ''),
            'volume_label': signal_data.get('volume_label', ''),
            'volume_ratio': float(signal_data.get('volume_ratio', 0)),
            'location': signal_data.get('location', ''),
            'resistance_levels': signal_data.get('resistance_levels', ''),
            'support_levels': signal_data.get('support_levels', ''),
            'net_gex': float(signal_data.get('net_gex', 0)),
            'atm_gex': float(signal_data.get('atm_gex', 0)),
            'gamma_flip': float(signal_data.get('gamma_flip', 0)) if signal_data.get('gamma_flip') else None,
            'gex_mode': signal_data.get('gex_mode', ''),
            'pcr_gex_badge': signal_data.get('pcr_gex_badge', ''),
            'market_bias': signal_data.get('market_bias', ''),
            'vix_value': float(signal_data.get('vix_value', 0)) if signal_data.get('vix_value') else None,
            'vix_direction': signal_data.get('vix_direction', ''),
            'oi_trend_signal': signal_data.get('oi_trend_signal', ''),
            'ce_activity': signal_data.get('ce_activity', ''),
            'pe_activity': signal_data.get('pe_activity', ''),
            'support_status': signal_data.get('support_status', ''),
            'resistance_status': signal_data.get('resistance_status', ''),
            'vidya_trend': signal_data.get('vidya_trend', ''),
            'vidya_delta_pct': float(signal_data.get('vidya_delta_pct', 0)),
            'delta_vol_trend': signal_data.get('delta_vol_trend', ''),
            'vwap': float(signal_data.get('vwap', 0)) if signal_data.get('vwap') else None,
            'price_vs_vwap': signal_data.get('price_vs_vwap', ''),
            'reasons': signal_data.get('reasons', ''),
            'alignment_summary': signal_data.get('alignment_summary', ''),
            'data_source': 'master_signal',
            'update_time': datetime.now(IST).isoformat()
        }
        self._safe_upsert('master_signals', [record], 'timestamp,trading_day')

    def get_master_signals(self, trading_day=None):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            return self.client.table('master_signals').select('*') \
                .eq('trading_day', trading_day) \
                .order('timestamp', desc=True).execute()
        return self._safe_query('master_signals', query, {'trading_day': trading_day})

    # ── Max Pain History ──
    def upsert_max_pain(self, expiry, max_pain_strike, underlying_price=None):
        now = datetime.now(IST)
        distance = abs(underlying_price - max_pain_strike) if underlying_price and max_pain_strike else None
        record = {
            'timestamp': now.isoformat(),
            'trading_day': now.date().isoformat(),
            'expiry': expiry,
            'max_pain_strike': float(max_pain_strike),
            'underlying_price': float(underlying_price) if underlying_price else None,
            'distance_from_spot': float(distance) if distance else None,
            'data_source': 'computed',
            'update_time': datetime.now(IST).isoformat()
        }
        self._safe_upsert('max_pain_history', [record], 'timestamp,expiry')

    def get_max_pain_history(self, expiry=None, trading_day=None):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        def query():
            q = self.client.table('max_pain_history').select('*').eq('trading_day', trading_day)
            if expiry:
                q = q.eq('expiry', expiry)
            return q.order('timestamp', desc=False).execute()
        return self._safe_query('max_pain_history', query, {'trading_day': trading_day})

    # ── Trade Config (manual S&R, entry, target, SL — persists across refresh) ──
    def save_trade_config(self, config: dict):
        now = datetime.now(IST)
        record = {
            'id': 1,  # single-row config
            'support_zone_bottom': config.get('support_zone_bottom'),
            'support_zone_top': config.get('support_zone_top'),
            'resistance_zone_bottom': config.get('resistance_zone_bottom'),
            'resistance_zone_top': config.get('resistance_zone_top'),
            'selected_strike': config.get('selected_strike'),
            'call_entry': config.get('call_entry'),
            'call_target': config.get('call_target'),
            'call_sl': config.get('call_sl'),
            'put_entry': config.get('put_entry'),
            'put_target': config.get('put_target'),
            'put_sl': config.get('put_sl'),
            'auto_trade_enabled': config.get('auto_trade_enabled', False),
            'lot_size': config.get('lot_size', 1),
            'updated_at': now.isoformat(),
        }
        try:
            self.client.table('trade_config').upsert(record, on_conflict='id', returning='minimal').execute()
        except Exception as e:
            st.warning(f"Could not save trade config: {e}")

    def get_trade_config(self):
        try:
            result = self.client.table('trade_config').select('*').eq('id', 1).execute()
            if result.data:
                return result.data[0]
        except Exception:
            pass
        return {}

    # ── Auto Trades ──
    def upsert_auto_trade(self, trade: dict):
        now = datetime.now(IST)
        record = {
            'trading_day': now.date().isoformat(),
            'trade_type': trade.get('trade_type'),        # 'CALL' or 'PUT'
            'strike': trade.get('strike'),
            'security_id': trade.get('security_id'),
            'entry_price': trade.get('entry_price'),
            'target': trade.get('target'),
            'sl': trade.get('sl'),
            'lot_size': trade.get('lot_size', 1),
            'status': trade.get('status', 'OPEN'),        # OPEN / CLOSED
            'exit_price': trade.get('exit_price'),
            'exit_reason': trade.get('exit_reason'),      # TARGET / SL / MANUAL / REVERSE
            'order_id': trade.get('order_id'),
            'entry_time': trade.get('entry_time', now.isoformat()),
            'exit_time': trade.get('exit_time'),
            'zone_confirmations': trade.get('zone_confirmations'),
            'spot_at_entry': trade.get('spot_at_entry'),
            'updated_at': now.isoformat(),
        }
        if trade.get('id'):
            record['id'] = trade['id']
        try:
            result = self.client.table('auto_trades').upsert(record).execute()
            if result.data:
                return result.data[0]
        except Exception as e:
            st.warning(f"Could not save trade: {e}")
        return record

    def get_active_trade(self):
        try:
            result = self.client.table('auto_trades').select('*').eq('status', 'OPEN').order('entry_time', desc=True).limit(1).execute()
            if result.data:
                return result.data[0]
        except Exception:
            pass
        return None

    def get_trade_history(self, trading_day=None, limit=20):
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        try:
            result = self.client.table('auto_trades').select('*').eq('trading_day', trading_day).order('entry_time', desc=True).limit(limit).execute()
            return result.data or []
        except Exception:
            return []

    # ── 📨 Alert log (sql/005_alert_log.sql) ──
    def insert_alert_log(self, row):
        """Store one sent alert (class, side, spot, message)."""
        try:
            self.client.table('alert_log').insert(row, returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_alert_side_counts(self, trading_day=None):
        """{'CALL': n, 'PUT': n, 'total': n} for the day."""
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()
        try:
            res = (self.client.table('alert_log').select('side')
                   .eq('trading_day', trading_day).execute())
            rows = res.data or []
            out = {'CALL': 0, 'PUT': 0, 'total': len(rows)}
            for r in rows:
                s = (r.get('side') or '').upper()
                if s in out:
                    out[s] += 1
            self.is_connected = True
            return out
        except Exception:
            self.is_connected = False
            return None

    # ── 📊 Leg order-flow snapshots (sql/006_leg_flow_snapshots.sql) ──
    def insert_leg_flow_snapshot(self, row):
        try:
            self.client.table('leg_flow_snapshots').insert(row, returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_leg_flow_snapshots(self, trading_day):
        def query():
            return (self.client.table('leg_flow_snapshots').select('*')
                    .eq('trading_day', trading_day).order('ts').execute())
        return self._safe_query('leg_flow_snapshots', query)

    def get_leg_flow_days(self, limit=30):
        """Distinct trading days that have snapshots, newest first.

        ⚠️ This used to pull **15,000 rows** to derive at most thirty values.

        `leg_flow_snapshots` is written many times a minute and kept for sixty
        days, so the day list was being reconstructed by downloading most of the
        table and throwing all but the date column away — then deduplicating in
        Python. The dedupe belongs in the database.

        There is no `DISTINCT` in PostgREST, so the cap is walked down instead:
        thirty distinct days sit inside a few thousand rows in the worst case,
        and the loop stops the moment it has enough. Ordered descending, the
        newest days arrive first, so the common case exits on the first page.
        """
        try:
            days: list = []
            seen: set = set()
            page, size = 0, 1000
            while len(seen) < limit and page < 6:
                res = (self.client.table('leg_flow_snapshots')
                       .select('trading_day')
                       .order('trading_day', desc=True)
                       .range(page * size, page * size + size - 1).execute())
                rows = res.data or []
                for r in rows:
                    d = r.get('trading_day')
                    if d and d not in seen:
                        seen.add(d)
                        days.append(d)
                if len(rows) < size:
                    break            # the table ended
                page += 1
            return sorted(days, reverse=True)[:limit]
        except Exception:
            return []

    # ── 🎯 Leg Entry Decision Engine signals (sql/004_leg_entry_signals.sql) ──
    def insert_leg_entry_signal(self, sig):
        """Store one qualifying Leg Entry Decision Engine signal."""
        try:
            self.client.table('leg_entry_signals').insert(sig, returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_leg_entry_signals(self, trading_day=None, limit=50):
        """Today's (or given day's) stored engine signals, newest first."""
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()

        def query():
            return (self.client.table('leg_entry_signals').select('*')
                    .eq('trading_day', trading_day)
                    .order('ts', desc=True).limit(limit).execute())
        return self._safe_query('leg_entry_signals', query)

    # ── 📈 Daily ATM IV history (sql/007_iv_history.sql) — for IV Rank/Percentile ──
    def upsert_daily_atm_iv(self, trading_day, atm_iv):
        """Store/refresh today's ATM IV (one row per trading day). Idempotent —
        the latest value of the day overwrites via upsert on trading_day."""
        try:
            self.client.table('iv_history').upsert(
                {'trading_day': trading_day, 'atm_iv': atm_iv},
                on_conflict='trading_day',
                returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_atm_iv_history(self, days=252):
        """Return the last N days of {trading_day, atm_iv}, oldest→newest."""
        def query():
            return (self.client.table('iv_history').select('trading_day, atm_iv')
                    .order('trading_day', desc=True).limit(days).execute())
        res = self._safe_query('iv_history', query)
        try:
            rows = res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            rows = []
        rows.reverse()   # desc → oldest-first
        return rows

    # ── 🧪 Signal → Outcome log (sql/008_signal_outcomes.sql) ──
    def insert_signal_outcome(self, row):
        """Insert one confirmed-entry signal with its factor snapshot. Returns
        the new row id (for the later outcome update), or None on failure."""
        try:
            res = self.client.table('signal_outcomes').insert(row, returning='minimal').execute()
            self.is_connected = True
            data = getattr(res, 'data', None) or []
            return data[0]['id'] if data and 'id' in data[0] else None
        except Exception:
            self.is_connected = False
            return None

    def update_signal_outcome(self, row_id, fields):
        """Fill in the outcome (state / exit / mfe / mae / pnl) for a row."""
        if row_id is None:
            return False
        try:
            self.client.table('signal_outcomes').update(
                fields, returning=self._WRITE_RETURNING).eq(
                'id', row_id).execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_signal_outcomes(self, limit=1000, closed_only=True):
        """Return recent signal_outcomes rows (newest first). closed_only keeps
        just the resolved ones (state set) for win-rate analysis — filtered in
        Python to stay independent of PostgREST operator variations."""
        def query():
            return (self.client.table('signal_outcomes').select('*')
                    .order('ts_entry', desc=True).limit(limit).execute())
        res = self._safe_query('signal_outcomes', query)
        try:
            rows = res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            rows = []
        if closed_only:
            rows = [r for r in rows if r.get('state')]
        return rows

    # ── ⚙️ MIOS V5 engine error log (sql/009_engine_errors.sql) ──
    def insert_engine_error(self, row):
        """Store one structured engine-error record (Stage 0 health engine)."""
        try:
            self.client.table('engine_errors').insert(row, returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_engine_errors(self, trading_day=None, limit=200):
        """Recent engine errors (newest first), for the Error Monitor panel."""
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()

        def query():
            return (self.client.table('engine_errors').select('*')
                    .eq('trading_day', trading_day)
                    .order('ts', desc=True).limit(limit).execute())
        res = self._safe_query('engine_errors', query)
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    # ── 📝 MIOS V5 My Analysis notes (sql/010_my_analysis.sql) ──
    def upsert_my_analysis(self, trading_day, section, note):
        """Store/refresh the trader's note for (trading_day, section)."""
        try:
            self.client.table('my_analysis').upsert(
                {'trading_day': trading_day, 'section': section, 'note': note,
                 'updated_at': datetime.now(IST).isoformat()},
                on_conflict='trading_day,section',
                returning='minimal').execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_my_analysis(self, trading_day=None):
        """Return {section: note} for the given day (default today)."""
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()

        def query():
            return (self.client.table('my_analysis').select('section, note')
                    .eq('trading_day', trading_day).execute())
        res = self._safe_query('my_analysis', query)
        try:
            rows = res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            rows = []
        return {r['section']: r.get('note', '') for r in rows if r.get('section')}

    # ── 🎯 ENTRY GATE signal log (sql/012 + 013) ──
    def insert_entry_gate_signal(self, row):
        """Store one ENTRY GATE activation. Returns the row id (for the exit
        monitor's later update), or None on failure."""
        try:
            res = self.client.table('entry_gate_signals').insert(row, returning='minimal').execute()
            self.is_connected = True
            data = getattr(res, 'data', None) or []
            return data[0]['id'] if data and 'id' in data[0] else None
        except Exception:
            self.is_connected = False
            return None

    def update_entry_gate_signal(self, row_id, fields):
        """Fill in the exit half (exit_ts / exit_spot / exit_reason / points)."""
        if row_id is None:
            return False
        try:
            # 37 columns — the widest echo of the four, and nothing reads it.
            self.client.table('entry_gate_signals').update(
                fields, returning=self._WRITE_RETURNING).eq(
                'id', row_id).execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_entry_gate_signals(self, trading_day=None, limit=100):
        """Gate activations for a day (default today), newest first."""
        if trading_day is None:
            trading_day = datetime.now(IST).date().isoformat()

        def query():
            return (self.client.table('entry_gate_signals').select('*')
                    .eq('trading_day', trading_day)
                    .order('ts', desc=True).limit(limit).execute())
        res = self._safe_query('entry_gate_signals', query)
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    def get_resolved_entry_gate_signals(self, limit=1000):
        """All CLOSED gate signals (exit_reason set), newest first — the raw
        dataset for the Validation Dashboard. Empty on any failure."""
        def query():
            return (self.client.table('entry_gate_signals').select('*')
                    .not_.is_('exit_reason', 'null')
                    .order('ts', desc=True).limit(limit).execute())
        res = self._safe_query('entry_gate_signals', query)
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    def get_layer_outcomes(self, limit=500):
        """Graded 7-layer snapshots for SHADOW weight-learning (sql/014).

        Returns entry_gate_signals rows that have BOTH a layer_leans snapshot
        and a resolved outcome (points_moved), shaped for build_shadow_weights:
        {"leans": {...}, "side": CALL/PUT, "win": bool}. Empty until the
        layer_leans column exists and trades have closed.
        """
        def query():
            return (self.client.table('entry_gate_signals')
                    .select('side, points_moved, layer_leans')
                    .not_.is_('layer_leans', 'null')
                    .not_.is_('points_moved', 'null')
                    .order('ts', desc=True).limit(limit).execute())
        res = self._safe_query('entry_gate_signals', query)
        try:
            rows = res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            rows = []
        out = []
        for r in rows:
            leans = r.get('layer_leans')
            if isinstance(leans, str):
                try:
                    import json as _json
                    leans = _json.loads(leans)
                except Exception:
                    leans = None
            if not isinstance(leans, dict):
                continue
            try:
                pts = float(r.get('points_moved'))
            except Exception:
                continue
            out.append({'leans': leans, 'side': r.get('side'), 'win': pts > 0})
        return out

    # ── 🎯 MIOS V5 bias predictions (sql/011_bias_predictions.sql) — Stage 40 ──
    def insert_bias_prediction(self, row):
        """Log one MIOS directional prediction. Returns row id or None."""
        try:
            res = self.client.table('bias_predictions').insert(row, returning='minimal').execute()
            self.is_connected = True
            data = getattr(res, 'data', None) or []
            return data[0]['id'] if data and 'id' in data[0] else None
        except Exception:
            self.is_connected = False
            return None

    def update_bias_prediction(self, row_id, fields):
        """Grade a prediction in place (spot_then / realized_move / correct)."""
        if row_id is None:
            return False
        try:
            self.client.table('bias_predictions').update(
                fields, returning=self._WRITE_RETURNING).eq(
                'id', row_id).execute()
            self.is_connected = True
            return True
        except Exception:
            self.is_connected = False
            return False

    def get_open_bias_predictions(self, limit=100):
        """Predictions not yet graded (resolved_at is null)."""
        def query():
            return (self.client.table('bias_predictions').select('*')
                    .order('ts', desc=True).limit(limit).execute())
        res = self._safe_query('bias_predictions', query)
        try:
            rows = res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            rows = []
        return [r for r in rows if not r.get('resolved_at')]

    def get_bias_predictions(self, limit=1000, resolved_only=True):
        """Graded predictions (newest first) for the accuracy view."""
        def query():
            return (self.client.table('bias_predictions').select('*')
                    .order('ts', desc=True).limit(limit).execute())
        res = self._safe_query('bias_predictions', query)
        try:
            rows = res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            rows = []
        if resolved_only:
            rows = [r for r in rows if r.get('correct') is not None]
        return rows

    # ── 🎬 Market Events (Discord feed + validation dataset) ──
    def insert_market_event(self, event):
        """Store one market intelligence event (event_type, severity, headline, detail, snapshot)."""
        try:
            res = self.client.table('market_events').insert(event, returning='minimal').execute()
            self.is_connected = True
            data = getattr(res, 'data', None) or []
            return data[0]['id'] if data and 'id' in data[0] else None
        except Exception:
            self.is_connected = False
            return None

    def get_market_events(self, limit=100, event_type=None, severity=None):
        """Recent market intelligence events (newest first) for Discord/UI display."""
        def query():
            q = self.client.table('market_events').select('*')
            if event_type:
                q = q.eq('event_type', event_type)
            if severity:
                q = q.eq('severity', severity)
            return q.order('event_time', desc=True).limit(limit).execute()
        res = self._safe_query('market_events', query)
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    # ── 📖 Market Stories (chronological narratives + validation) ──
    def insert_market_story(self, story):
        """Store a market story with classification."""
        try:
            res = self.client.table('market_stories').insert(story, returning='minimal').execute()
            self.is_connected = True
            data = getattr(res, 'data', None) or []
            return data[0]['id'] if data and 'id' in data[0] else None
        except Exception:
            self.is_connected = False
            return None

    def get_market_stories(self, limit=50, story_type=None):
        """Recent market stories (newest first)."""
        def query():
            q = self.client.table('market_stories').select('*')
            if story_type:
                q = q.eq('story_type', story_type)
            return q.order('market_time_start', desc=True).limit(limit).execute()
        res = self._safe_query('market_stories', query)
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    def insert_story_validation(self, validation):
        """Store a closed trade linked to its story."""
        try:
            res = self.client.table('story_validations').insert(validation, returning='minimal').execute()
            self.is_connected = True
            data = getattr(res, 'data', None) or []
            return data[0]['id'] if data and 'id' in data[0] else None
        except Exception:
            self.is_connected = False
            return None

    def get_story_validations(self, story_type=None, limit=500):
        """Closed-trade validations, optionally filtered by story_type — the
        raw dataset story_stats is aggregated from."""
        def query():
            q = self.client.table('story_validations').select('*')
            if story_type:
                q = q.eq('story_type', story_type)
            return q.order('created_at', desc=True).limit(limit).execute()
        res = self._safe_query('story_validations', query)
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    def upsert_story_stats(self, row):
        """Upsert one story_type's aggregate win-rate row (story_type is
        UNIQUE — sql/017)."""
        self._safe_upsert('story_stats', [row], 'story_type')

    def get_story_stats(self, limit=50):
        """Story type win-rate statistics (ranked by win-rate)."""
        def query():
            return self.client.table('story_stats').select('*').order('win_rate', desc=True).limit(limit).execute()
        res = self._safe_query('story_stats', query)
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    # ── 🏛️ Engine State (Stage 1-41 scoring snapshot per pipeline pass) ──
    def insert_engine_state(self, row):
        """Store one pipeline pass's flattened engine scores + full snapshot."""
        try:
            res = self.client.table('engine_state').insert(row, returning='minimal').execute()
            self.is_connected = True
            data = getattr(res, 'data', None) or []
            return data[0]['id'] if data and 'id' in data[0] else None
        except Exception:
            self.is_connected = False
            return None

    def get_engine_state(self, limit=100, trading_day=None):
        """Recent engine_state rows (newest first)."""
        def query():
            q = self.client.table('engine_state').select('*')
            if trading_day:
                q = q.eq('trading_day', trading_day)
            return q.order('ts', desc=True).limit(limit).execute()
        res = self._safe_query('engine_state', query)
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    # ── 🗄️ Storage cleanup helpers (download / delete unused history) ──
    def count_rows(self, table):
        """Approximate/exact row count for a table (None on failure)."""
        try:
            res = (self.client.table(table).select('id', count='exact')
                   .limit(1).execute())
            return res.count
        except Exception:
            return None

    def fetch_all_rows(self, table, chunk=1000, max_rows=200000):
        """Paginated full-table fetch → list of dicts, capped at max_rows so a
        huge table can't blow up memory (export bigger tables from the Supabase
        dashboard instead)."""
        out, start = [], 0
        try:
            while start < max_rows:
                res = (self.client.table(table).select('*')
                       .range(start, start + chunk - 1).execute())
                rows = res.data or []
                out.extend(rows)
                if len(rows) < chunk:
                    break
                start += chunk
        except Exception:
            pass
        return out

    # ── Stage 74 telemetry (sql/036_liquidity_telemetry.sql) ──
    def insert_liquidity_telemetry(self, row):
        """One calibration sample. Upserts on `ts` so a retried write corrects
        its row rather than appending a second and skewing the distribution."""
        if not row:
            return
        self._safe_upsert('liquidity_telemetry', [dict(row)], 'ts')

    def get_liquidity_telemetry(self, days=7, limit=5000):
        """The calibration window, newest first.

        Seven days by default because that is the question — a single volatile
        session says how the curve behaves on a volatile session; a week says
        whether it survives a quiet Tuesday and an expiry Thursday.
        """
        cutoff = (datetime.now(IST).date() - timedelta(days=int(days))).isoformat()
        def query():
            return (self.client.table('liquidity_telemetry').select('*')
                    .gte('trading_day', cutoff)
                    .order('ts', desc=True).limit(limit).execute())
        res = self._safe_query('liquidity_telemetry', query)
        try:
            return res.to_dict('records') if hasattr(res, 'to_dict') else list(res or [])
        except Exception:
            return []

    # ── retention primitives (db/retention.py orchestrates these) ──
    def cutoff_day(self, days):
        """The date `days` ago, ISO. One place computes it so a preview and the
        delete that follows can never disagree about where the line is."""
        return (datetime.now(IST).date() - timedelta(days=int(days))).isoformat()

    def count_rows_older_than(self, table, days, day_col='trading_day'):
        """How many rows a purge would remove. `None` means the question could
        not be answered — which is not the same as zero, and a caller must not
        render it as "nothing to do"."""
        try:
            res = (self.client.table(table).select('*', count='exact')
                   .lt(day_col, self.cutoff_day(days)).limit(1).execute())
            return res.count
        except Exception:
            return None

    def oldest_day(self, table, day_col='trading_day'):
        """The earliest value of `day_col`, or `None`. Purging walks forward
        from here in bounded windows rather than issuing one delete across
        years of rows."""
        try:
            res = (self.client.table(table).select(day_col)
                   .order(day_col, desc=False).limit(1).execute())
            rows = res.data or []
            return rows[0].get(day_col) if rows else None
        except Exception:
            return None

    def purge_window(self, table, day_col, lo, hi):
        """Delete `lo <= day_col < hi`. Returns True on success, False on error.

        `returning='minimal'` matters: a delete that returns the deleted rows
        sends every one of them back over the wire, so purging to *save* on
        storage would spend egress doing it. Older client versions do not
        accept the argument, hence the fallback.
        """
        def run(minimal):
            q = (self.client.table(table).delete(returning='minimal')
                 if minimal else self.client.table(table).delete())
            return q.gte(day_col, lo).lt(day_col, hi).execute()
        try:
            run(True)
            return True
        except TypeError:
            try:
                run(False)
                return True
            except Exception:
                return False
        except Exception:
            return False

    def delete_rows(self, table, older_than_days=None, day_col='trading_day'):
        """Delete rows from `table`. older_than_days=None → ALL rows (uses a
        match-everything filter since PostgREST requires one); otherwise only
        rows whose day_col is strictly older than the cutoff. Returns the count
        deleted, or None on error."""
        try:
            q = self.client.table(table).delete()
            if older_than_days is not None:
                cutoff = (datetime.now(IST).date()
                          - timedelta(days=int(older_than_days))).isoformat()
                q = q.lt(day_col, cutoff)
            else:
                q = q.gte('id', 0)   # matches every row (id is BIGSERIAL ≥ 1)
            res = q.execute()
            return len(res.data) if getattr(res, 'data', None) else 0
        except Exception:
            return None
