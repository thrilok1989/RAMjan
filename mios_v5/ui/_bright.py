"""MIOS V5 UI — bright_caption().

st.caption() renders in Streamlit's own built-in muted/secondary text
style, which stays dim regardless of the pinned [theme] textColor in
.streamlit/config.toml — every panel that used it kept reading as grey no
matter what custom CSS got fixed elsewhere in the app. This is a drop-in
replacement that renders the same small secondary-info text, but in pure
white via explicit HTML instead of Streamlit's caption styling. (A pale
blue-grey #c9d6e6 was tried first as "the theme's bright text color" —
still read as dull/grey; white removes all ambiguity.)
"""

from __future__ import annotations


def bright_caption(text: str, size: int = 13) -> None:
    """Like st.caption(text), but bright. Markdown syntax (**bold**, etc.)
    still renders — st.markdown processes markdown and embedded HTML
    together even with unsafe_allow_html=True."""
    import streamlit as st
    st.markdown(
        f"<div style='color:#ffffff;font-size:{size}px;line-height:1.5;"
        f"margin:2px 0'>{text}</div>",
        unsafe_allow_html=True,
    )
