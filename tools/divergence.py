"""Have the duplicate copies actually DRIFTED?

`tools/dupscan.py` normalises identifiers and literals before hashing, so it
answers "did these start as the same function". It cannot answer "are they
still the same", and that is the question that decides which copy is canonical.

This does the second half: for every clone group it compares the real bodies —
exact text, then AST shape, then **the constants**. A pair that differs only in
a threshold is the dangerous case, because it looks identical in review and
behaves differently in production.

    python tools/divergence.py            # summary
    python tools/divergence.py --full     # + unified diffs
"""
import ast
import collections
import difflib
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP = ("__pycache__", "/.git/", "/tests/", "/scratchpad/")
FULL = "--full" in sys.argv

files = [p for p in ROOT.rglob("*.py") if not any(s in str(p) for s in SKIP)]


class Norm(ast.NodeTransformer):
    def visit_Name(self, n):  return ast.copy_location(ast.Name(id="_", ctx=n.ctx), n)
    def visit_arg(self, n):   return ast.copy_location(ast.arg(arg="_", annotation=None), n)
    def visit_Attribute(self, n):
        self.generic_visit(n)
        return ast.copy_location(ast.Attribute(value=n.value, attr="_", ctx=n.ctx), n)
    def visit_Constant(self, n):
        return ast.copy_location(ast.Constant(value=type(n.value).__name__), n)


def consts(fn):
    """Every literal in the function, in order — the thing normalisation hides.

    Read off the docstring-stripped body: prose is not a threshold, and a
    reworded docstring reporting as "different numbers" is the same cry-wolf
    problem in the category that most needs to be trusted.
    """
    return [n.value for n in ast.walk(ast.parse(docstrip(fn)))
            if isinstance(n, ast.Constant)
            and not isinstance(n.value, bool)
            and isinstance(n.value, (int, float, str))]


class _Annos(ast.NodeTransformer):
    """Drop type annotations.

    `List[float]` vs `Sequence[float]` is not a behavioural difference, and
    leaving annotations in reported the only two identical `_slope`
    implementations in this repo as "different logic" — a false alarm in the
    one category that must not cry wolf.
    """
    def visit_arg(self, n):
        return ast.copy_location(ast.arg(arg=n.arg, annotation=None), n)

    def visit_FunctionDef(self, n):
        self.generic_visit(n)
        n.returns = None
        return n


def docstrip(fn):
    """The function with docstring and annotations removed, unparsed — comments
    are already gone at AST level, so this compares CODE, not prose."""
    f = _Annos().visit(ast.parse(ast.unparse(fn))).body[0]
    if (f.body and isinstance(f.body[0], ast.Expr)
            and isinstance(f.body[0].value, ast.Constant)
            and isinstance(f.body[0].value.value, str)):
        f.body = f.body[1:] or [ast.Pass()]
    return ast.unparse(f)


groups = collections.defaultdict(list)
for p in files:
    try:
        tree = ast.parse(p.read_text())
    except Exception:
        continue
    rel = str(p.relative_to(ROOT))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            size = sum(1 for _ in ast.walk(n) if isinstance(_, ast.stmt))
            if size < 6:
                continue
            try:
                h = hashlib.sha1(ast.dump(Norm().visit(
                    ast.parse(ast.unparse(n)))).encode()).hexdigest()
            except Exception:
                continue
            groups[h].append((rel, n.name, n.lineno, size, n))

pairs = {h: v for h, v in groups.items() if len({f for f, *_ in v}) > 1}

IDENTICAL, CONSTS, LOGIC = [], [], []
for h, members in pairs.items():
    base = members[0]
    base_code, base_consts = docstrip(base[4]), consts(base[4])
    for other in members[1:]:
        if other[0] == base[0]:
            continue
        code, cs = docstrip(other[4]), consts(other[4])
        rec = (base, other)
        if code == base_code:
            IDENTICAL.append(rec)
        elif cs != base_consts:
            diff = [(a, b) for a, b in zip(base_consts, cs) if a != b]
            CONSTS.append((base, other, diff, base_code, code))
        else:
            LOGIC.append((base, other, base_code, code))


def loc(m):
    return f"{m[0]}:{m[2]} {m[1]}()"


print("### DIVERGENCE between duplicate copies\n")
print(f"  identical code (docstrings aside) : {len(IDENTICAL)}")
print(f"  ⚠️  DIFFERENT CONSTANTS            : {len(CONSTS)}")
print(f"  ⚠️  DIFFERENT LOGIC                : {len(LOGIC)}\n")

if CONSTS:
    print("### ⚠️ SAME SHAPE, DIFFERENT NUMBERS — behaves differently in production")
    for base, other, diff, a, b in sorted(CONSTS, key=lambda r: -r[0][3]):
        print(f"\n  {loc(base)}\n  {loc(other)}")
        for was, now in diff[:8]:
            print(f"      {was!r:28} → {now!r}")
        if FULL:
            for line in list(difflib.unified_diff(
                    a.splitlines(), b.splitlines(),
                    base[0], other[0], lineterm="", n=1))[:40]:
                print("      " + line)

if LOGIC:
    print("\n### ⚠️ SAME NUMBERS, DIFFERENT CODE")
    for base, other, a, b in sorted(LOGIC, key=lambda r: -r[0][3]):
        print(f"\n  {loc(base)}\n  {loc(other)}")
        if FULL:
            for line in list(difflib.unified_diff(
                    a.splitlines(), b.splitlines(),
                    base[0], other[0], lineterm="", n=1))[:40]:
                print("      " + line)

print("\n### IDENTICAL — safe to treat as one implementation")
for base, other in sorted(IDENTICAL, key=lambda r: -r[0][3])[:40]:
    print(f"  [{base[3]:3d}] {loc(base):58s} == {loc(other)}")
