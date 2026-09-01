"""MIOS V5 — Story Engine Dashboard Panel.

Displays:
- Live market story (event timeline)
- Story recognition (pattern + confidence)
- Probable scenarios
- Story validation statistics
"""

from __future__ import annotations

from typing import Any, Optional

from ._bright import bright_caption as _bc


def render_story_panel(db=None) -> None:
    """Render the Story Engine analysis panel."""
    import streamlit as st

    if not db:
        _bc("📖 Story Engine not available (database unavailable)")
        return

    try:
        # Fetch recent stories
        stories = db.get_market_stories(limit=5)
        if not stories:
            _bc("📖 No stories recorded yet")
            return

        with st.expander("📖 Market Story Timeline", expanded=False):
            for story in stories[:3]:  # Show last 3 stories
                story_type = story.get("story_type", "Unknown").replace("_", " ").title()
                confidence = story.get("confidence", 0)
                summary = story.get("summary", "")
                event_count = story.get("event_count", 0)
                duration = story.get("duration_seconds", 0)

                # Story header
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    st.markdown(
                        f"**{story_type}**" if confidence > 0 else "**Story (unclassified)**"
                    )
                with col2:
                    if confidence > 0:
                        _bc(f"🎯 {confidence:.0f}%")
                with col3:
                    _bc(f"📊 {event_count} events")

                # Story narrative
                if summary:
                    st.markdown(summary, unsafe_allow_html=True)

                # Duration
                if duration > 0:
                    mins = duration // 60
                    _bc(f"⏱️ Duration: {mins}m" if mins > 0 else f"⏱️ Duration: {duration}s")

                st.divider()

        # Story validation stats
        with st.expander("📈 Story Pattern Statistics", expanded=False):
            stats = db.get_story_stats(limit=10)
            if stats:
                st.markdown("**Win-Rate by Pattern**")
                for stat in stats[:5]:
                    story_type = stat.get("story_type", "Unknown").replace("_", " ").title()
                    win_rate = stat.get("win_rate", 0)
                    total = stat.get("total_trades", 0)
                    avg_r = stat.get("avg_r_multiple", 0)
                    pnl = stat.get("total_pnl", 0)

                    # Color code by win rate
                    if win_rate >= 60:
                        wr_color = "#17c98b"
                    elif win_rate >= 50:
                        wr_color = "#f0b429"
                    else:
                        wr_color = "#f0455a"

                    st.markdown(
                        f"<div style='font-size:12px;color:#ffffff'>"
                        f"<b>{story_type}</b> — "
                        f"<span style='color:{wr_color}'>{win_rate:.0f}%</span> "
                        f"({total} trades) "
                        f"avg R: {avg_r:+.2f} "
                        f"PnL: {pnl:+.0f}pts</div>",
                        unsafe_allow_html=True,
                    )
            else:
                _bc("No validation data yet")

    except Exception as e:
        _bc(f"📖 Story panel error: {type(e).__name__}")
