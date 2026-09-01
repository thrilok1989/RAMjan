"""Clone detection over the repo: same function in two places, under any name."""
import ast, hashlib, pathlib, sys, collections, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP = ("__pycache__", "/.git/", "/tests/", "/scratchpad/")

files = [p for p in ROOT.rglob("*.py") if not any(s in str(p) for s in SKIP)]


class Norm(ast.NodeTransformer):
    """Erase names/constants so two functions differing only in identifiers hash alike."""
    def visit_Name(self, n):  return ast.copy_location(ast.Name(id="_", ctx=n.ctx), n)
    def visit_arg(self, n):   return ast.copy_location(ast.arg(arg="_", annotation=None), n)
    def visit_Attribute(self, n):
        self.generic_visit(n)
        return ast.copy_location(ast.Attribute(value=n.value, attr="_", ctx=n.ctx), n)
    def visit_Constant(self, n):
        return ast.copy_location(ast.Constant(value=type(n.value).__name__), n)


def body_hash(fn):
    try:
        clone = Norm().visit(ast.parse(ast.unparse(fn)))
        return hashlib.sha1(ast.dump(clone).encode()).hexdigest()
    except Exception:
        return None


funcs = []          # (name, file, lineno, nstmt, hash, src)
by_name = collections.defaultdict(list)
for p in files:
    try:
        tree = ast.parse(p.read_text())
    except Exception:
        continue
    rel = str(p.relative_to(ROOT))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            size = sum(1 for _ in ast.walk(n) if isinstance(_, ast.stmt))
            h = body_hash(n)
            funcs.append((n.name, rel, n.lineno, size, h))
            by_name[n.name].append((rel, n.lineno, size))

print(f"### functions scanned: {len(funcs)} across {len(files)} files\n")

# ── 1 · same NAME in >1 file
print("### SAME NAME, DIFFERENT FILES (top 30 by file count)")
multi = {k: v for k, v in by_name.items()
         if len({f for f, _, _ in v}) > 1 and not k.startswith("__")}
for name, locs in sorted(multi.items(), key=lambda kv: -len({f for f, _, _ in kv[1]}))[:30]:
    fl = sorted({f for f, _, _ in locs})
    print(f"  {name:38s} x{len(fl)}  {', '.join(fl[:5])}{' …' if len(fl) > 5 else ''}")

# ── 2 · identical BODY, any name (real clones)
print("\n### IDENTICAL BODIES (structural clones, >=6 stmts)")
by_hash = collections.defaultdict(list)
for name, rel, line, size, h in funcs:
    if h and size >= 6:
        by_hash[h].append((name, rel, line, size))
clones = {h: v for h, v in by_hash.items() if len({r for _, r, _, _ in v}) > 1}
for h, v in sorted(clones.items(), key=lambda kv: -kv[1][0][3])[:35]:
    names = sorted({n for n, _, _, _ in v})
    print(f"  [{v[0][3]:3d} stmts] {' / '.join(names[:3])}")
    for n, r, l, _ in sorted(v)[:5]:
        print(f"        {r}:{l}  ({n})")
print(f"\n  clone groups: {len(clones)}")
