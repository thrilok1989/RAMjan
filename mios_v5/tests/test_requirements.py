"""Every deployed dependency is bounded above, and none is raised past what
the deployment can install.

There are two failure modes here and they pull in opposite directions.

**Unbounded.** Thirteen bare `>=` let Streamlit Cloud re-resolve the tree on
every rebuild and cross a major version with nothing asking. Streamlit serves
hash-named JS chunks, so a rebuild onto a different version renames them and a
browser holding the previous `index.html` requests files that no longer exist:
`Failed to fetch dynamically imported module`.

**Over-pinned.** The first attempt at fixing that pinned the floors to the
versions installed in *this sandbox* — `pandas~=3.0.5`, `numpy~=2.4.6`,
`streamlit==1.60.0`. The deploy then failed outright with "Error installing
requirements", because pandas 3.x needs Python >=3.11 and nothing in this repo
knows which Python Streamlit Cloud runs. A green suite in a sandbox is not
evidence about a deployment target.

So the rule these tests encode is asymmetric, and deliberately so:

* an upper cap is always safe — it only removes future versions
* **a raised floor is not** — it demands a version the target may not have

The sandbox may not dictate the deployment's floors.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
REQ = ROOT / "requirements.txt"

#: The floors as they stood when the app was known to install and run. A test
#: asserts no requirement demands more than these — raising one is a deployment
#: decision that needs the Cloud build log, not a sandbox `pip list`.
#: ⚠️ `streamlit-autorefresh` is 1.0.0, not the 0.1.6 the file used to claim:
#: that version was never released, so `>=0.1.6` had always resolved to 1.0.1.
#: A floor naming a version that does not exist is not a floor.
#: `streamlit` is 1.60.0 rather than the old 1.28.0 floor because it is now an
#: exact pin, confirmed twice: the Cloud build log shows pip fetching it on
#: Python 3.14.6, and it is the version this suite runs against.
KNOWN_GOOD_FLOORS = {
    "streamlit": "1.60.0", "streamlit-autorefresh": "1.0.0",
    "requests": "2.31.0", "pandas": "2.1.0", "numpy": "1.24.0",
    "scipy": "1.11.0", "plotly": "5.17.0", "pytz": "2023.3",
    "supabase": "1.0.3", "yfinance": "0.2.28", "google-genai": "1.0.0",
    "websockets": "12.0", "anthropic": "0.40.0",
}


def _requirements():
    """(name, spec) per real requirement line — comments and blanks dropped."""
    out = []
    for raw in REQ.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(.*)$", line)
        assert m, f"unparsable requirement: {raw!r}"
        out.append((m.group(1).lower(), m.group(2).strip()))
    return out


def _floor(spec: str):
    """The `>=` floor a spec demands, or None."""
    m = re.search(r">=\s*([0-9][0-9A-Za-z.\-]*)", spec)
    return m.group(1) if m else None


def _parts(v: str):
    """Version → comparable tuple. Non-numeric segments sort as -1 so a
    pre-release never reads as newer than the release it precedes."""
    out = []
    for seg in re.split(r"[.\-]", v):
        out.append(int(seg) if seg.isdigit() else -1)
    return tuple(out)


def test_the_file_has_requirements_in_it():
    """A parser that silently matched nothing would make every test below pass
    on an empty file."""
    assert len(_requirements()) >= 10


@pytest.mark.parametrize("name,spec", _requirements())
def test_every_requirement_has_an_upper_bound(name, spec):
    """`<`, `~=` or `==` — never a bare `>=`. A cap only ever removes future
    versions, so it cannot break an install that works today."""
    assert spec, f"{name} has no version specifier at all"
    bounded = "<" in spec or spec.startswith("~=") or spec.startswith("==")
    assert bounded, (f"{name}{spec} is unbounded — a rebuild can cross a major "
                     f"version with nothing asking")


@pytest.mark.parametrize("name,spec", _requirements())
def test_no_floor_is_raised_above_the_known_good_deployment(name, spec):
    """The regression that took the app down.

    Pinning to the sandbox's versions demanded pandas 3.x, which needs Python
    >=3.11 — a requirement the deployment could not satisfy, and which nothing
    in this repo can check. Raising a floor is a deployment decision and needs
    the Streamlit Cloud build log; it is not something a `pip list` in a test
    environment gets to make.
    """
    known = KNOWN_GOOD_FLOORS.get(name)
    assert known is not None, (
        f"{name} is new — add it to KNOWN_GOOD_FLOORS with the floor the "
        f"deployment is known to install")

    if spec.startswith("=="):
        # An exact pin IS a floor, so it must be one the deployment is known to
        # install — confirmed against the Cloud build log, recorded here. This
        # is the deliberate path, not a forbidden one.
        pinned = spec[2:].strip()
        assert pinned == known, (
            f"{name}=={pinned} is pinned to a version KNOWN_GOOD_FLOORS does "
            f"not record ({known}). Confirm it against the Streamlit Cloud "
            f"build log, update the table, and re-run the dry run")
        return

    floor = _floor(spec)
    if spec.startswith("~="):
        floor = spec[2:].strip()
    assert floor is not None, f"{name}{spec} has no floor at all"
    assert _parts(floor) <= _parts(known), (
        f"{name} demands >={floor}, above the known-good {known}. The sandbox "
        f"is not the deployment — this is how 'Error installing requirements' "
        f"happened")


def test_the_sandbox_does_not_dictate_the_floors():
    """The lesson, asserted directly: no floor may have been copied from what
    happens to be installed here."""
    import importlib.metadata as md
    for name, spec in _requirements():
        try:
            local = md.version(name)
        except md.PackageNotFoundError:
            continue
        floor = _floor(spec) or (spec[2:].strip() if spec.startswith("~=")
                                 else None)
        if floor and _parts(floor) >= _parts(local):
            pytest.fail(
                f"{name} floors at {floor}, which is the locally installed "
                f"{local} — that is the sandbox setting the deployment's "
                f"floor, and it broke the deploy once already")
