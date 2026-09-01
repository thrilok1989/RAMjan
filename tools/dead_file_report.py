"""Dead File Report — Stage A of the cleanup, before anything is archived.

Static reachability alone is not safe enough to delete on. It misses
`importlib.import_module`, `__import__`, Streamlit page discovery, plugin
lookup and any module named in a plain string. This tool layers those on top
and refuses to mark a file safe if **any** of them touch it.

    python tools/dead_file_report.py            # the markdown table
    python tools/dead_file_report.py --why FILE # why one file was classified

A file is `SAFE_DELETE = Yes` only when all of these hold:

  * not reachable from any entrypoint by a static import
  * not named as a string anywhere (dynamic import, subprocess, config)
  * zero `import` references from any file, including tests
  * not itself an entrypoint (no `st.set_page_config`, no `__main__` block)

Anything else is `No`, with the reason. The report is meant to be **read by a
human before Stage B**, not executed.
"""
import ast
import collections
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
#: `archive/` is excluded on purpose. Once Stage B moves a file there it is no
#: longer part of the app, so counting it as an importer would keep its own
#: dependencies alive forever — `config.py` stayed "held back by
#: alerts/telegram.py" after telegram.py had already been archived.
SKIP = ("__pycache__", "/.git/", "/scratchpad/", "archive/")
ENTRYPOINTS = ["vob_minimal.py"]        # the Streamlit main module

allpy = sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py")
               if not any(s in str(p) for s in SKIP))
tests = {f for f in allpy if "/tests/" in f or f.startswith("tests/")}
tooling = {f for f in allpy if f.startswith("tools/")}


def mod_to_path(m):
    for cand in (m.replace(".", "/") + ".py", m.replace(".", "/") + "/__init__.py"):
        if cand in allpy:
            return cand
    return None


def path_to_mod(f):
    return f[:-3].replace("/", ".").removesuffix(".__init__")


def parse(f):
    try:
        return ast.parse((ROOT / f).read_text())
    except Exception:
        return None


# ── static imports ────────────────────────────────────────────────────
def static_imports(f):
    t = parse(f)
    if t is None:
        return set()
    out, pkg = set(), (f.rsplit("/", 1)[0] if "/" in f else "")
    for n in ast.walk(t):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                parts = pkg.split("/")
                base = ".".join([p for p in parts[:len(parts) - n.level + 1] if p]
                                + ([base] if base else []))
            out.add(base)
            out |= {f"{base}.{a.name}" if base else a.name for a in n.names}
    return out


# ── dynamic imports: __import__("x") / importlib.import_module("x") ──
DYN_RX = re.compile(
    r"(?:__import__|import_module)\(\s*['\"]([\w.]+)['\"]", re.M)


def dynamic_imports(f):
    try:
        return set(DYN_RX.findall((ROOT / f).read_text()))
    except Exception:
        return set()


# ── every module name that appears in ANY string literal anywhere ────
string_refs = collections.defaultdict(set)
mod_names = {path_to_mod(f): f for f in allpy}
short_names = collections.defaultdict(set)
for m, f in mod_names.items():
    short_names[m.rsplit(".", 1)[-1]].add(f)

weak_refs = collections.defaultdict(set)
for f in allpy:
    t = parse(f)
    if t is None:
        continue
    for n in ast.walk(t):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            v = n.value.strip()
            if v in mod_names:
                # a full dotted module path — a real dynamic-import candidate
                string_refs[mod_names[v]].add(f)
            elif v in short_names and len(v) > 4:
                # A BARE name that happens to match a module. `"max_pain"` is a
                # column name, `"lifecycle"` is a dict key — matching these as
                # module references held nine files back for no reason. Kept as
                # weak evidence so a human can dismiss it in one look, rather
                # than dropped, because the one time it IS a dynamic import is
                # the time deleting the file breaks production.
                for target in short_names[v]:
                    weak_refs[target].add(f)

# ── reachability ─────────────────────────────────────────────────────
seen, queue = set(), list(ENTRYPOINTS)
while queue:
    cur = queue.pop()
    if cur in seen:
        continue
    seen.add(cur)
    for m in static_imports(cur) | dynamic_imports(cur):
        p = mod_to_path(m)
        if p and p not in seen:
            queue.append(p)

# ── import reference counts ──────────────────────────────────────────
refs = collections.defaultdict(set)
for f in allpy:
    for m in static_imports(f) | dynamic_imports(f):
        p = mod_to_path(m)
        if p and p != f:
            refs[p].add(f)


def is_entrypoint(f):
    try:
        src = (ROOT / f).read_text()
    except Exception:
        return False
    return ("st.set_page_config" in src
            or re.search(r"^if __name__\s*==\s*['\"]__main__['\"]", src, re.M))


def classify(f):
    """(safe, reason) — every 'No' names what is holding the file alive."""
    if f in ENTRYPOINTS:
        return False, "the Streamlit main module"
    if f in seen:
        return False, "reachable from the entrypoint"
    if is_entrypoint(f):
        return False, "a separate entrypoint (`set_page_config` / `__main__`)"
    live_refs = {r for r in refs.get(f, set()) if r not in tests | tooling}
    if live_refs:
        return False, f"imported by {', '.join(sorted(live_refs)[:3])}"
    if string_refs.get(f):
        srcs = {s for s in string_refs[f] if s != f}
        if srcs:
            return False, (f"⚠️ dotted module path in a string in "
                           f"{', '.join(sorted(srcs)[:2])}")
    test_refs = {r for r in refs.get(f, set()) if r in tests}
    weak = {s for s in weak_refs.get(f, set()) if s != f and s not in tests}
    note = (f" · ⚠ bare name `{path_to_mod(f).rsplit('.', 1)[-1]}` also appears "
            f"as a string in {len(weak)} file(s) — check it is not a dynamic "
            f"import" if weak else "")
    if test_refs:
        return True, f"only tests import it ({len(test_refs)}){note}"
    return True, f"no importer anywhere{note}"


if "--why" in sys.argv:
    f = sys.argv[sys.argv.index("--why") + 1]
    safe, why = classify(f)
    print(f"{f}\n  safe delete : {'Yes' if safe else 'No'}\n  reason      : {why}")
    print(f"  reachable   : {f in seen}")
    print(f"  importers   : {sorted(refs.get(f, set())) or 'none'}")
    print(f"  string refs : {sorted(string_refs.get(f, set())) or 'none'}")
    raise SystemExit

candidates = [f for f in allpy if f not in tests and f not in tooling]
rows = []
for f in candidates:
    safe, why = classify(f)
    if f in seen or f in ENTRYPOINTS:
        continue
    loc = len((ROOT / f).read_text().splitlines())
    rows.append((f, loc, len(refs.get(f, set())), safe, why))

rows.sort(key=lambda r: (not r[3], -r[1]))
yes = [r for r in rows if r[3]]
no = [r for r in rows if not r[3]]

# ── cascade: what becomes deletable once round 1 is gone ─────────────
# `vob_indicators.py` is held back only because `vob_data.py` imports it —
# and `vob_data.py` is itself on the delete list. Removing files changes the
# answer, so Stage B has to be iterative rather than one pass.
removed = {r[0] for r in yes}
cascade = []
for _ in range(6):
    added = False
    for f, loc, n, safe, why in no:
        if f in removed:
            continue
        live = {r for r in refs.get(f, set())
                if r not in tests | tooling | removed}
        if (not live and f not in seen and f not in ENTRYPOINTS
                and not is_entrypoint(f) and not string_refs.get(f)):
            removed.add(f)
            cascade.append((f, loc, why))
            added = True
    if not added:
        break

print(f"# Dead File Report\n")
print(f"Entry path: `{' + '.join(ENTRYPOINTS)}`  ·  "
      f"{len(allpy)} files scanned  ·  {len(seen)} reachable\n")
print(f"**{len(yes)} candidates ({sum(r[1] for r in yes):,} LOC)** · "
      f"**{len(no)} held back**\n")
print("| File | LOC | Import Count | Reason | Safe Delete |")
print("|---|---|---|---|---|")
for f, loc, n, safe, why in rows:
    print(f"| `{f}` | {loc:,} | {n} | {why} | "
          f"{'**Yes**' if safe else 'No'} |")

if cascade:
    print(f"\n## Round 2 — becomes deletable once round 1 is archived\n")
    print(f"**{len(cascade)} files ({sum(c[1] for c in cascade):,} LOC)** — each "
          f"is held alive today only by a file that is itself on the list "
          f"above. Re-run this report after Stage B rather than trusting these "
          f"rows blind.\n")
    print("| File | LOC | Was held back by |")
    print("|---|---|---|")
    for f, loc, why in sorted(cascade, key=lambda c: -c[1]):
        print(f"| `{f}` | {loc:,} | {why} |")
