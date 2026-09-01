"""Nothing on the first-paint path may wait on the network.

The instrument context is built while the sidebar is constructed — before any
of the page has been drawn. A slow call there is indistinguishable from a dead
app: the browser sits on the loading screen with nothing to show and no error.

That is exactly what happened. The block called `resolve_index_security_id`,
which reads Dhan's ~26 MB / ~212k-row scrip master. Around 5 seconds on a fast
connection, far worse on a slow one — and `pd.read_csv(url)` accepts no
timeout, so a stalled connection blocked the render thread indefinitely.

These tests are source-level because `vob_minimal` boots Streamlit and reads
secrets on import, so it cannot be imported in a test.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"
_SCRIP_MASTER_URL = "images.dhan.co/api-data/api-scrip-master.csv"


@pytest.fixture(scope="module")
def source() -> str:
    return _SRC.read_text()


@pytest.fixture(scope="module")
def tree(source: str) -> ast.Module:
    return ast.parse(source)


def _function_named(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in vob_minimal.py")


def _calls_within(node: ast.AST) -> set:
    """Names of every function called anywhere inside `node`."""
    out = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        fn = sub.func
        if isinstance(fn, ast.Name):
            out.add(fn.id)
        elif isinstance(fn, ast.Attribute):
            out.add(fn.attr)
    return out


# ── the scrip master is fetched once, with a timeout ───────────────────

def test_scrip_master_is_fetched_in_exactly_one_place(source: str):
    """Three functions each used to `pd.read_csv` the same 26 MB URL, so a
    cold start paid the download once per caller. One fetcher, one download."""
    assert source.count(_SCRIP_MASTER_URL) == 1, (
        "the scrip master URL should appear only inside _scrip_master()")


def test_no_bare_url_read_csv_remains(source: str):
    """`pd.read_csv(<url>)` cannot be given a timeout — it must go through
    requests instead, or a stalled fetch hangs the render thread forever."""
    assert "pd.read_csv(url, low_memory=False)" not in source


def test_the_fetch_carries_a_timeout(tree: ast.Module):
    fn = _function_named(tree, "_scrip_master")
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"):
            assert any(kw.arg == "timeout" for kw in node.keywords), (
                "requests.get on the scrip master must pass timeout=")
            return
    raise AssertionError("_scrip_master() makes no requests.get call")


def test_timeout_is_bounded_and_sane(source: str):
    ns: dict = {}
    for line in source.splitlines():
        if line.startswith("SCRIP_MASTER_TIMEOUT"):
            exec(line, ns)  # noqa: S102 - a literal tuple from our own source
            break
    timeout = ns.get("SCRIP_MASTER_TIMEOUT")
    assert timeout is not None, "SCRIP_MASTER_TIMEOUT is not defined"
    connect, read = timeout
    assert 0 < connect <= 30, connect
    assert 0 < read <= 180, read


# ── the first-paint path stays off the network ─────────────────────────

def test_instrument_context_block_does_not_resolve_ids_over_the_network(source: str):
    """Regression: the sidebar's context block called
    `resolve_index_security_id`, pulling the scrip master before first paint.

    The two index ids are fixed values Dhan does not reissue, and they are
    pinned by `test_instrument_registry`, so the block uses them directly.
    """
    block = source.split("Set instrument context for the render cycle")[-1]
    block = block[:block.index("st.session_state['_current_instrument_context']")]
    # strip comments — the block explains this history in prose
    code = "\n".join(ln for ln in block.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "resolve_index_security_id" not in code, (
        "the first-paint path must not fetch the scrip master")


def test_the_verified_ids_are_used_directly(source: str):
    block = source.split("Set instrument context for the render cycle")[-1]
    block = block[:block.index("st.session_state['_current_instrument_context']")]
    assert "security_id=51" in block, "SENSEX id 51 should be inline"
    assert "security_id=13" in block, "NIFTY id 13 should be inline"


def test_publish_atm_legs_may_still_use_the_scrip_master(tree: ast.Module):
    """The option ids genuinely change every expiry, so that lookup must stay.
    It runs during the data pass, not while the sidebar is being built."""
    fn = _function_named(tree, "_publish_atm_legs")
    assert "get_nifty_option_security_ids" in _calls_within(fn)
