"""Which files COMPUTE each market fact, and which files DISPLAY it."""
import ast, pathlib, collections, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP = ("__pycache__", "/.git/", "/scratchpad/", "/tests/")
allpy = sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py")
               if not any(s in str(p) for s in SKIP))

# a fact → the def-name patterns that mean "this file computes it"
FACTS = {
    "POC / value area": r"(compute_vpfr|calculate_poc|dynamic_poc|value_area|_poc\b)",
    "HVN / LVN": r"(hvn|lvn)",
    "VWAP": r"vwap",
    "ATR": r"\batr\b",
    "RSI": r"\brsi\b",
    "CVD / delta": r"(cvd|volume_delta|calculate_delta)",
    "PCR": r"\bpcr\b",
    "Max pain": r"max_pain",
    "GEX / gamma": r"(gex|gamma)",
    "IV / greeks": r"(implied_vol|get_iv|greeks|_iv\b)",
    "Order blocks": r"(order_block|detect_blocks|\bvob\b)",
    "Support/resistance": r"(support|resistance|\bsr_\b)",
    "Candle patterns": r"(candle_pattern|detect_.*candle|engulf|doji|hammer)",
    "Sector rotation": r"sector_rotation",
    "Market depth": r"(market_depth|orderbook_pressure|depth_based)",
    "Reversal score": r"reversal_score",
    "Swings / pivots": r"(detect_swings|pivot|swing_percent)",
}

print("### WHO COMPUTES WHAT (files defining a function whose NAME matches)")
for fact, pat in FACTS.items():
    rx = re.compile(pat, re.I)
    hits = collections.defaultdict(list)
    for f in allpy:
        try:
            t = ast.parse((ROOT / f).read_text())
        except Exception:
            continue
        for n in ast.walk(t):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and rx.search(n.name):
                hits[f].append(n.name)
    if len(hits) > 1:
        print(f"\n  {fact}  — {len(hits)} files, "
              f"{sum(len(v) for v in hits.values())} functions")
        for f, names in sorted(hits.items(), key=lambda kv: -len(kv[1]))[:8]:
            print(f"      {f:44s} {len(names):2d}  {', '.join(sorted(names)[:4])}")

# ── display duplication: which UI files print the same label
print("\n\n### DISPLAY — the same label rendered by N files")
LABELS = ("POC", "VAH", "VAL", "PCR", "Max Pain", "VWAP", "GEX", "Gamma Flip",
          "Support", "Resistance", "Confidence", "Bias", "Entry", "Stop",
          "Target", "R:R", "Trend", "Regime", "Day Type", "Session")
ui = [f for f in allpy if "/ui/" in f or f.endswith(("vob_minimal.py",
      "seller_perspective.py", "vob_alerts.py", "vob_analysis.py"))]
for lab in LABELS:
    rx = re.compile(r"['\"][^'\"]{0,18}\b" + re.escape(lab) + r"\b[^'\"]{0,18}['\"]")
    fs = [f for f in ui if rx.search((ROOT / f).read_text())]
    if len(fs) > 2:
        print(f"  {lab:12s} x{len(fs):2d}  {', '.join(x.split('/')[-1] for x in fs[:9])}")
