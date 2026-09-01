"""MIOS V5 — My Analysis notes (Stage 41 §My Analysis).

The trader's own pre-market / live / post-market notes, persisted to Supabase
(`my_analysis`, migration 010). Rendered as three text areas with save
buttons; today's notes load on open. Also shows AI-vs-my-analysis side by side
by pairing the notes with the MIOS final read.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import pytz

from ._bright import bright_caption as _bc

IST = pytz.timezone("Asia/Kolkata")

_SECTIONS = [
    ("premarket", "🌅 Pre-Market"),
    ("live", "📈 Live Market"),
    ("postmarket", "🌆 Post-Market Review"),
]


def render_my_analysis(db=None, final_read: Optional[Dict[str, Any]] = None) -> None:
    import streamlit as st

    st.markdown("#### 📝 My Analysis")
    if db is None:
        _bc("Notes need a database connection.")
        return

    today = datetime.now(IST).date().isoformat()
    # load once per rerun into a cache keyed by day
    cache_key = f"_my_analysis_{today}"
    if cache_key not in st.session_state:
        try:
            st.session_state[cache_key] = db.get_my_analysis(today) or {}
        except Exception:
            st.session_state[cache_key] = {}
    saved: Dict[str, str] = st.session_state[cache_key]

    if final_read:
        _bc(f"🤖 MIOS read: **{final_read.get('preferred_bias')}** @ "
                   f"{final_read.get('confidence_tempered')}% · "
                   f"{final_read.get('session_phase', '')} — compare with your notes below.")

    for key, label in _SECTIONS:
        note = st.text_area(label, value=saved.get(key, ""),
                            key=f"_ma_input_{key}_{today}", height=90)
        if st.button(f"Save {label}", key=f"_ma_save_{key}_{today}"):
            ok = False
            try:
                ok = db.upsert_my_analysis(today, key, note)
            except Exception:
                ok = False
            if ok:
                saved[key] = note
                st.success(f"Saved {label} note.")
            else:
                st.warning("Could not save (check DB / run sql/010_my_analysis.sql).")
