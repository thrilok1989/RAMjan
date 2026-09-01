# Dead File Report — Stage A

*Generated, then manually verified. Nothing has been moved or deleted.*

```bash
python tools/dead_file_report.py              # regenerate this table
python tools/dead_file_report.py --why FILE   # why one file was classified
```

Entry path: **`vob_minimal.py`** · 313 files scanned · **181 reachable**

**29 candidates (8,165 LOC)** · **15 held back**

## Why static reachability alone was not trusted

Static imports miss `importlib`, `__import__`, Streamlit page discovery and
plugin lookup. The generator layers all of these on and **refuses to mark a
file safe if any of them touch it**. That caught a real case immediately:

```python
# mios_v5/ui/dashboard_v6.py:742
quality = _try(lambda: __import__(
    "mios_v5.explain_decision", fromlist=["market_quality"]).market_quality(fr))
risk = _try(lambda: __import__("mios_v5.risk_explain", fromlist=["analyse"]) …)
```

Two modules reached only by string. A pure import-graph scan would have called
`mios_v5/risk_explain.py` dead.

Checked and found absent: no `pages/` directory, no plugin registry, no
`importlib.import_module` on a local module, nothing in `.streamlit/config.toml`
naming a module.

---

## Safe to archive — 29 files, 8,165 LOC

| File | LOC | Import Count | Reason | Safe Delete |
|---|---|---|---|---|
| `vob_analysis.py` | 1,782 | 0 | no importer anywhere | **Yes** |
| `vob_alerts.py` | 1,751 | 0 | no importer anywhere | **Yes** |
| `seller_features.py` | 902 | 0 | no importer anywhere | **Yes** |
| `vob_data.py` | 683 | 0 | no importer anywhere | **Yes** |
| `indicators/reversal_detector.py` | 333 | 0 | no importer anywhere | **Yes** |
| `mios_v5/dispatch_validation.py` | 297 | 1 | only tests import it | **Yes** |
| `discord_bot.py` | 265 | 0 | no importer anywhere — separate process, see note | **Yes** |
| `mios_v5/backfill.py` | 251 | 1 | only tests import it | **Yes** |
| `mios_v5/scenario_engine.py` | 231 | 1 | only tests import it | **Yes** |
| `api/dhan_api.py` | 181 | 0 | no importer anywhere — ⚠️ see note | **Yes** |
| `mios_v5/story_validation.py` | 174 | 1 | only tests import it | **Yes** |
| `db/dispatch_registry.py` | 171 | 0 | no importer anywhere | **Yes** |
| `indicators/future_swing.py` | 147 | 0 | no importer anywhere | **Yes** |
| `mios_v5/order_flow_snapshot.py` | 129 | 1 | only tests import it | **Yes** |
| `analysis/gex_analyzer.py` | 115 | 0 | no importer anywhere | **Yes** |
| `mios_v5/lifecycle.py` | 108 | 1 | only tests import it · ⚠ bare name in 12 files | **Yes** |
| `indicators/pivot_indicator.py` | 99 | 0 | no importer anywhere | **Yes** |
| `mios_v5/ui/order_flow_panel.py` | 98 | 1 | only tests import it | **Yes** |
| `ui/styles.py` | 77 | 0 | no importer anywhere | **Yes** |
| `mios_v5/ui/overlay_panel.py` | 69 | 1 | only tests import it | **Yes** |
| `ui/metrics_display.py` | 57 | 0 | no importer anywhere | **Yes** |
| `analysis/greeks.py` | 51 | 0 | no importer anywhere · ⚠ bare name in 2 files | **Yes** |
| `ui/analytics_dashboard.py` | 51 | 0 | no importer anywhere | **Yes** |
| `analysis/bias_engine.py` | 46 | 0 | no importer anywhere | **Yes** |
| `alerts/telegram.py` | 44 | 0 | no importer anywhere · ⚠ bare name in 4 files | **Yes** |
| `analysis/max_pain.py` | 39 | 0 | no importer anywhere · ⚠ bare name in 4 files | **Yes** |
| `ui/helpers.py` | 14 | 0 | no importer anywhere | **Yes** |
| `alerts/__init__.py` · `analysis/__init__.py` | 0 | 0 | empty package markers | **Yes** |

### Manual verification — three rows the generator got only half right

**1 · `discord_bot.py` is a separate process, not dead code.** It has no
importer because nothing imports a bot; it is run on its own and it reads
`vob_app_state` from Supabase. **Do not delete it** — archive it separately or
leave it in place. The generator cannot know this and marked it `Yes`; a human
must not.

**2 · `api/dhan_api.py` is on the delete list *and* nominated as the future
owner of Dhan access.** The duplication survey recommends consolidating five
`_dhan_post()` copies into it. Deleting it now and rebuilding it later is
strictly worse than leaving it. **Hold it back until the Dhan consolidation is
decided.**

**3 · The whole top-level `ui/` package is dead.** `ui/styles.py`,
`helpers.py`, `metrics_display.py`, `analytics_dashboard.py` and
`ui/__init__.py` have zero importers between them — verified by searching for
`from ui.` / `import ui` across the repo. The generator held `ui/__init__.py`
back on a bare `"ui"` string match; it should go with the rest of its package.
(Distinct from `mios_v5/ui/`, which is live.)

### The `⚠ bare name` flags are all false positives

Verified individually: `"max_pain"`, `"lifecycle"`, `"telegram"` and `"greeks"`
appear as **column names, dict keys and table names** — not module paths. They
are kept in the output rather than suppressed because the one time such a
string *is* a dynamic import is the time deleting the file breaks production.
One look each dismisses them.

---

## Held back — 15 files

| File | LOC | Held by |
|---|---|---|
| `seller_perspective.py` | 9,026 | a separate Streamlit entrypoint (`set_page_config`) |
| `vob_indicators.py` | 1,865 | imported by `vob_data.py` — **cascades**, see below |
| `market_depth_advanced.py` | 866 | imported by `seller_features.py`, `seller_perspective.py` |
| `auto_option_trader.py` | 787 | separate entrypoint — **places real Dhan orders** |
| `generate_analysis_pdf.py` | 462 | separate entrypoint |
| `ws_worker.py` | 422 | separate entrypoint |
| `nifty_price_alert.py` | 318 | separate entrypoint |
| `quick_buy_option.py` | 252 | separate entrypoint — places real orders |
| `mios_v5/overlays.py` | 231 | imported by `ui/overlay_panel.py` — **cascades** |
| `mios_v5/market_state.py` | 142 | imported by `scenario_engine.py` — **cascades** |
| `indicators/volume_order_blocks.py` | 139 | named in `test_premium_structure.py` |
| `indicators/triple_poc.py` | 75 | named in `test_premium_structure.py` |
| `config.py` | 45 | imported by `alerts/telegram.py`, `api/dhan_api.py` — **cascades** |
| `api/__init__.py` · `ui/__init__.py` | 0 | bare-name string match |

### ⚠️ A test naming a module can mean the opposite of "uses it"

`indicators/volume_order_blocks.py` and `indicators/triple_poc.py` are held
back because `mios_v5/tests/test_premium_structure.py` names them. It names
them in a **banned-imports set**:

```python
banned = {"indicators", "indicators.volume_order_blocks",
          "indicators.triple_poc", "indicators.volume_delta", …}
```

That is a guard asserting `premium_structure` **must not** import them.
Deleting the modules is safe; the guard simply becomes vacuous. This is exactly
why Stage A is a human step: *named in a test* can mean *forbidden*, not
*used*.

---

## Round 2 — 3 files (418 LOC) that unlock once round 1 is archived

| File | LOC | Held back today by |
|---|---|---|
| `mios_v5/overlays.py` | 231 | `mios_v5/ui/overlay_panel.py` (itself on the list) |
| `mios_v5/market_state.py` | 142 | `mios_v5/scenario_engine.py` (itself on the list) |
| `config.py` | 45 | `alerts/telegram.py`, `api/dhan_api.py` (both on the list) |

**Stage B has to be iterative.** `vob_indicators.py` (1,865 LOC) is held only
by `vob_data.py`, which is itself going — so a second pass reaches it, and a
third may reach `market_depth_advanced.py`. Re-run the report after each
archive round rather than trusting these rows blind.

---

## Recommended Stage B

Archive **26 files** — the 29 `Yes` rows minus `discord_bot.py` and
`api/dhan_api.py`, plus `ui/__init__.py` from the manual verification:

```
archive/
  vob_analysis.py  vob_alerts.py  seller_features.py  vob_data.py
  indicators/…  analysis/…  ui/…  alerts/…  mios_v5/…
```

Then: run the suite, open every dashboard tab, let one full 20-second refresh
cycle complete, and re-run this report for round 2.

**What breaks if this is right:** nothing.
**What breaks if it is wrong:** an `ImportError` at page load, immediately, on
the tab that needed the file — loud and trivially reversible from `archive/`.

The tests that import the archived modules move with them or get deleted in the
same commit; **six of the 29 are covered only by tests**, and a test for an
archived module is the "tested but not running" problem preserved in amber.
