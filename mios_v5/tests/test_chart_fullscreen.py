"""⛶ Every chart on the Charts tab carries the one Fullscreen button.

The button is Streamlit's, injected into the Plotly modebar. `displayModeBar: False`
removed the whole modebar and the button with it — which is why the terminal chart,
the one a trader most wants to enlarge, was the only chart that could not be. These
tests pin the shared config on all three chart calls and the CSS that makes the
button visible rather than hover-only.
"""

from __future__ import annotations

import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
_TREE = ast.parse(_SRC)


def _const(name):
    for node in ast.walk(_TREE):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not defined")


# ── the shared config ─────────────────────────────────────────────────

def test_the_config_shows_the_modebar_but_not_scroll_zoom():
    cfg = _const("FS_CHART_CONFIG")
    assert cfg["displayModeBar"] is True, "no modebar means no Fullscreen button"
    assert cfg["scrollZoom"] is False, "the wheel must not zoom the chart"


def test_every_plotly_button_but_fullscreen_is_stripped():
    """⚠️ The Fullscreen button is Streamlit's, so `modeBarButtonsToRemove` — which
    names only Plotly's own buttons — cannot touch it. Removing all of Plotly's
    leaves exactly the one control. Verified on screen; asserted here so the list
    cannot quietly shrink and let the pan/zoom clutter back in."""
    removed = set(_const("FS_CHART_CONFIG")["modeBarButtonsToRemove"])
    assert {"zoom2d", "pan2d", "select2d", "lasso2d", "zoomIn2d", "zoomOut2d",
            "autoScale2d", "resetScale2d"} <= removed


def test_the_css_forces_the_modebar_visible_not_hover_only():
    """⚠️ The default modebar is hover-only and top-right — discoverable enough to be
    reported missing. Opacity 1 makes it an actual button."""
    css = _const("FS_CHART_CSS")
    assert "stFullScreenFrame" in css and ".modebar" in css
    assert "opacity:1" in css.replace(" ", "")


# ── the wiring: all three charts, and the CSS once ─────────────────────

def _charts_screen_src():
    fn = next(n for n in ast.walk(_TREE)
              if isinstance(n, ast.FunctionDef) and n.name == "_charts_screen")
    return ast.get_source_segment(_SRC, fn) or ""


def test_the_css_is_injected_on_the_charts_tab():
    body = _charts_screen_src()
    assert "FS_CHART_CSS" in body


def test_every_chart_call_uses_the_shared_config():
    """The three split terminal panels (NIFTY / Call / Put), the per-strike OI
    charts and the POC chart — one config, so a chart added later without it is
    the odd one out, not the norm.

    ⚠️ The terminal used to be ONE `plotly_chart` call; it is now three, one per
    panel, because each needs its own Streamlit Fullscreen button. The invariant
    that matters is not the count but that EVERY call carries the shared config —
    the count is pinned alongside it only so a chart cannot quietly vanish."""
    calls = [c for c in ast.walk(_TREE)
             if isinstance(c, ast.Call)
             and getattr(c.func, "attr", "") == "plotly_chart"]
    assert len(calls) == 5, f"expected 5 plotly_chart calls, found {len(calls)}"
    for c in calls:
        cfg = next((kw.value for kw in c.keywords if kw.arg == "config"), None)
        assert isinstance(cfg, ast.Name) and cfg.id == "FS_CHART_CONFIG", \
            "a chart is not using the shared fullscreen config"


def test_no_chart_still_disables_the_modebar():
    """⚠️ `displayModeBar: False` anywhere is a chart with no Fullscreen button —
    the exact regression this fixes. It must not reappear."""
    assert "displayModeBar\": False" not in _SRC
    assert "'displayModeBar': False" not in _SRC
