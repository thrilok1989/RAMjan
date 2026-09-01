"""Reachability from the entrypoint + fetch/storage/display duplication maps."""
import ast, pathlib, collections, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP = ("__pycache__", "/.git/", "/scratchpad/")
ENTRY = "vob_minimal.py"

allpy = {str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py")
         if not any(s in str(p) for s in SKIP)}


def mod_to_path(m):
    for cand in (m.replace(".", "/") + ".py", m.replace(".", "/") + "/__init__.py"):
        if cand in allpy:
            return cand
    return None


def imports_of(rel):
    try:
        t = ast.parse((ROOT / rel).read_text())
    except Exception:
        return set()
    out = set()
    pkg = rel.rsplit("/", 1)[0] if "/" in rel else ""
    for n in ast.walk(t):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:                      # relative import
                parts = pkg.split("/")
                base = "/".join(parts[:len(parts) - n.level + 1] + ([base.replace(".", "/")] if base else []))
                base = base.replace("/", ".")
            out.add(base)
            for a in n.names:
                out.add(f"{base}.{a.name}" if base else a.name)
    return out


seen, queue = set(), [ENTRY]
while queue:
    cur = queue.pop()
    if cur in seen:
        continue
    seen.add(cur)
    for m in imports_of(cur):
        p = mod_to_path(m)
        if p and p not in seen:
            queue.append(p)

tests = {f for f in allpy if "/tests/" in f or f.startswith("tests/")}
live = seen
orphan = sorted(allpy - live - tests)

print(f"### REACHABLE from {ENTRY}: {len(live)} files")
print(f"### TEST files: {len(tests)}")
print(f"### NOT REACHABLE (excluding tests): {len(orphan)}\n")
loc = {}
for f in orphan:
    try:
        loc[f] = len((ROOT / f).read_text().splitlines())
    except Exception:
        loc[f] = 0
for f in sorted(orphan, key=lambda x: -loc[x])[:30]:
    print(f"  {loc[f]:6d} LOC  {f}")
print(f"\n  orphan LOC total: {sum(loc.values()):,}")

# ── data fetch: which files call which HTTP endpoints
print("\n### DATA FETCH — endpoint literals by file")
ep = collections.defaultdict(set)
for f in sorted(allpy - tests):
    try:
        src = (ROOT / f).read_text()
    except Exception:
        continue
    for m in re.finditer(r"['\"](https?://[^'\"]+|/[a-z][a-z0-9/_-]{2,40})['\"]", src):
        u = m.group(1)
        if any(k in u for k in ("dhan", "nse", "yahoo", "query1", "/charts", "/quotes",
                                "/orders", "/positions", "/optionchain", "/marketfeed",
                                "/holdings", "/v2/")):
            ep[u.split("?")[0]].add(f)
for u, fs in sorted(ep.items(), key=lambda kv: -len(kv[1])):
    if len(fs) > 1:
        print(f"  x{len(fs)}  {u[:72]}")
        for f in sorted(fs):
            print(f"          {f}")

# ── storage: table -> writers/readers
print("\n### STORAGE — supabase table access by file")
tbl = collections.defaultdict(lambda: collections.defaultdict(set))
for f in sorted(allpy - tests):
    try:
        src = (ROOT / f).read_text()
    except Exception:
        continue
    for m in re.finditer(r"\.table\(\s*['\"](\w+)['\"]\s*\)\s*\.\s*(\w+)", src):
        tbl[m.group(1)][m.group(2)].add(f)
multi = {t: ops for t, ops in tbl.items()
         if len({f for s in ops.values() for f in s}) > 1}
for t, ops in sorted(multi.items()):
    files = sorted({f for s in ops.values() for f in s})
    print(f"  {t:26s} {','.join(sorted(ops))[:40]:42s} {', '.join(files)}")
print(f"\n  tables touched: {len(tbl)}; touched by >1 file: {len(multi)}")
