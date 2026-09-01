# What `vob_minimal.py` Does That MIOS V6 Does Not Need

A line-by-line audit of the app against one question: **if the only thing that
mattered were the MIOS V6 analysis, what could be switched off?**

This is a map, not a deletion plan. Almost everything on the "not needed" list
is needed *by something* — it fires the alerts, draws the charts, or answers a
question the trader asks directly. What the list says is narrower and exact:
**V6 never reads its output.**

---

## 1. How "needed" was decided

MIOS V6 has one entry point and one input surface. It is not a guess.

```
vob_minimal.py : _render_main_analyzer()
    └── _mios_pass()                     line 28165, called at line 31218
          └── mios_v5.runner.run_mios_pass(st.session_state, db)
                └── builds `raw` — a dict read ONLY from st.session_state
                └── orchestrator.run(raw)   → every V6 stage
```

`run_mios_pass` fetches nothing. It reads **session-state keys the app has
already filled**. That dict is the entire contract. Anything whose output never
lands in one of those keys cannot reach a V6 stage — there is no other door.

A second, smaller surface exists for the **V6 dashboard UI**
(`mios_v5/ui/dashboard_v6.py`), which reads a few keys directly for rendering
(ATM leg frames, entry setups). Those are marked separately below, because they
feed the *screen*, not the analysis.

**Method.** Parse the file's 342 top-level defs/classes into a graph, seed it
with every function that writes a V6-consumed key, take the transitive closure.
Everything outside the closure is on this list.

> ### Two corrections, both found by acting on this audit
>
> Executing the reduction proved the first version of this method wrong twice.
> Both corrections are folded into the numbers below.
>
> **1. A call graph is not the whole graph.** App functions also hand data to
> each other through session keys. `compute_market_picture` reads `_gift_mf`
> and `_commodity_risk`; `compute_global_nifty_bias` reads `_global_indices`;
> the bias dashboard reads `_pxoi_cache` and `_greek_absorb_last`. Those keys
> are written by *panels* the first pass called decoration. **11 blocks / 1,677
> lines** moved from "not needed" to "needed" once data edges were followed
> too. Dropping them would not have crashed anything — it would have made those
> Market Picture categories report MISSING, silently degrading V6 rather than
> slimming it.
>
> **2. `ast.Call` misses a reference.** `ReversalDetector` is used only as
> `ReversalDetector.calculate_reversal_score(...)` — an Attribute on the class
> name, never a call *of* it. The eight styling helpers are handed to
> `df.style.applymap(...)` as bare names. All eleven read as uncalled and were
> deleted; pyflakes caught every one. **§A below is corrected accordingly** —
> it listed 21 dead blocks, and 11 of them were alive.

| | blocks | lines |
|---|---|---|
| Total top-level defs/classes | 342 | 35,916 |
| **Inside the V6 closure** (calls + data edges) | 137 | 12,893 |
| **Outside — not needed for V6** | **205** | **~21,900** |

**≈61% of the file is invisible to V6** — and that is what was removed. See §8.

---

## 2. The dependency surface — what V6 actually reads

44 session-state keys. 27 are produced by the app; 17 V6 produces for itself
and rolls forward across cycles.

### App-produced (V6 pipeline inputs)

| Key | Produced by | Line |
|---|---|---|
| `_cached_option_data` | `analyze_option_chain` | 31177 |
| `_market_picture` | `render_market_picture` → `compute_market_picture` | 15204 |
| `_full_market_read` | `compute_full_market_read` | 20345 |
| `_market_structure` | `compute_market_structure` | 20540 |
| `_leg_bias_cache` | `render_all_bias_dashboard` → `build_leg_bias_table` | 18377 |
| `_all_bias_rows` | `render_all_bias_dashboard` | 19017 |
| `_gex_data` | `calculate_dealer_gex` | 32925 |
| `_volume_delta_data` | `calculate_volume_delta` | 28937 |
| `_money_flow_data` | `compute_dual_profile` | 28896 |
| `_composite_profile` | `compute_dual_profile` | 28891 |
| `_value_migration` | `compute_dual_profile` | 28892 |
| `_value_alignment` | `compute_value_alignment` | 12132 |
| `_sector_rotation` | `generate_master_signal` | 9941 |
| `_news_bias` | `compute_news_bias` | 9691 |
| `_fii_dii_cash` / `_fii_deriv_stats` | cached getters | 28743–4 |
| `_nifty_spot_live` | `get_index_spot_ltp` | 28730 |
| `_df_5m` / `_last_df` | `generate_master_signal` | 9869 / 10321 |
| `_day_open_spot` / `_gap_today` | `capture_day_open_and_gap` | 27836 / 27878 |
| `_htf_profiles` | `build_htf_profiles` | 12426 |
| `_reaction_sr` | `build_reaction_sr` + `annotate_sr_trend` + `enrich_zone_intel` | 33466 |
| `_iv_history` | inline, ATM IV append | 32146 |
| `vix_history` | `generate_master_signal` | 9896 |
| `_is_expiry_today` | `_is_expiry_day` | 28180 |
| `_zone_memory` | `_zone_memory` | 12316 |
| `_dhan_token_expired` / `_dhan_429_until` | `_dhan_post` | — |
| `_opt_data_ts` / `_last_cycle_ts` | inline | — |

### V6 dashboard-only (screen, not analysis)

`_atm_leg_dfs` (29959) · `_atm_leg_sids` (29966) · `_entry_armed_setups` ·
`_entry_signal_open` (21970–1) · `_day_break_tally`

### V6 self-produced (written back by the runner)

`_absorption_trace` · `_acceptance_memory` · `_bias_trace` · `_day_type_memory` ·
`_energy_memory` · `_flow_trace` · `_flow_stability` · `_flow_calm_cycles` ·
`_ltp_trace` · `_state_memory` · `_mios_market_memory` · `_mios_orchestrator` ·
`_mios_prev_report` · `_mios_prev_snapshot` · `_mios_state` · `_opportunity_prev`

**If a function's result does not end up in one of the 27 app-produced keys,
V6 never sees it.** That is the whole test.

---

## 3. Lines 1–232 — module level

| Lines | What | V6 needs it? |
|---|---|---|
| 1–23 | imports | partial — `mios_v5.*`, `indicators.*`, `db.supabase_client` yes |
| 37–41 | optional `yfinance` | no — side-market panels only |
| 42–46 | optional `google.genai` | no — AI advisor only |
| 52–58 | `st.set_page_config` | no |
| 60–66 | market-hours gate + `st_autorefresh(20000)` | **yes** — it drives the whole cycle |
| 68–127 | global CSS (incl. the ≤640px mobile block) | no |
| 130–131 | Dhan client id / access token | **yes** — the only market-data source |
| 132–133 | Supabase url / anon key | **yes** — Stage 33/40 persistence |
| 134–155 | Gemini / Anthropic / Groq API keys | no |
| 156–174 | Telegram bot + dedicated alert-bot tokens | no |
| 175–200 | Discord webhook + bot token | no |
| 201–208 | `LEG_FETCH_PER_RENDER = 5` | **yes** — bounds the fetch that fills the caches |
| 210–211 | `NIFTY_UNDERLYING_SCRIP` / `_SEG` | **yes** |
| 213–220 | `INSTRUMENT_CONFIGS` (SENSEX, BANKNIFTY, RELIANCE, ICICIBANK, INFOSYS) | no — V6 is NIFTY-only |
| 223–232 | `cached_pivot_calculation`, `cached_iv_average` | no — both unused |

Three things in this range are worth acting on independently of V6:

* **Lines 181 / 184 / 198** — the same live Discord webhook URL is hardcoded
  three times as the no-secrets fallback. Anyone with repo access can post to
  that channel.
* **Line 172** — bare `except:` on the Telegram-secrets block swallows
  `KeyboardInterrupt` and `SystemExit`.
* **Lines 201–207** — the comment says *"The 14 ATM±3 legs… 14 × the 0.3s
  throttle"*. The hot path is **6** legs (`_strikes_to_analyze` = ATM−1/ATM/ATM+1,
  both sides); the 14 figure describes VOB aggregation, a different path. The
  constant is right; the comment overstates the problem by 2.3×.

---

## 4. Not needed for V6 — the full list

### A. Dead code — never referenced anywhere · 10 blocks · 712 lines

Not "unused by V6" — unused by *anything*.

| Line | Lines | Name |
|---|---|---|
| 27386 | 329 | `show_auto_trade_section` |
| 12560 | 95 | `send_major_sr_alert` |
| 1213 | 90 | `PivotIndicator` (class) |
| 20670 | 81 | `run_stage2_backfill` |
| 4331 | 69 | `_cmce_detect_continuation` |
| 11543 | 54 | `send_candle_pattern_alert` |
| 11777 | 37 | `compute_depth_sr` |
| 11678 | 27 | `send_chart_pattern_alert` |
| 5247 | 14 | `_short_trend` |
| 228 | 5 | `cached_iv_average` |

`show_auto_trade_section` is the largest single dead block — a full
broker-execution UI, 329 lines, with no caller.

#### Eleven blocks this section listed and got wrong

The first version of §A also claimed `ReversalDetector` (330 lines),
`determine_level`, `_GatePinned` and the eight `color_*` / `highlight_atm_row`
helpers were dead. **They are all live.** The pass that found them followed
`ast.Call`, and none of them is ever called that way:

* `ReversalDetector.calculate_reversal_score(...)` — the Call node's target is
  the *method*; `ReversalDetector` itself is an `ast.Name` load inside an
  `ast.Attribute`. Nine live use sites.
* `df.style.applymap(color_bias)` — the styling helpers are passed as values,
  never invoked at the call site.
* `_GatePinned` — `raise` and `except`, never a call.

Deleting them produced eleven `NameError`s waiting to fire, which pyflakes
caught. The lesson generalises: **any reference-graph analysis of this file must
follow `ast.Name` loads and `ast.Attribute` values, not just `ast.Call`.**
`mios_v5/tests/test_v6_dependency_audit.py` pins the survivors so they cannot
be swept up again.

---

### B. Alerting — Telegram, Discord, audio · 43 blocks · 3,710 lines

Generation 1's output channel. V6 is `advisory_only` and fires nothing.

**The 25 alert senders:** `send_spot_stop_hunt_aligned_alert` (5373) ·
`send_cie_aligned_alert` (5408) · `send_major_sr_touch_aligned_alert` (5440) ·
`send_liquidity_grab_alert` (5479) · `send_grab_confirmation_alert` (5526) ·
`send_ltp_extreme_alert` (5736) · `send_ltp_vob_hvp_alert` (5774) ·
`send_ltp_dpoc_move_alert` (5944) · `send_atm_poc_touch_alert` (6107) ·
`send_atm_leg_stop_hunt_alert` (6151) · `send_vob_retest_alert` (6226) ·
`send_leg_ignition_alert` (6302) · `send_option_chain_signal` (7962) ·
`send_candle_at_sr_alert` (11074) · `send_retest_alert` (11134) ·
`send_capping_at_sr_alert` (11198) · `send_decapping_alert` (11269) ·
`send_ob_zone_alert` (11336) · `send_rejection_alert` (11373) ·
`send_bias_enter_alert` (23452) · `send_premarket_telegram` (23738) ·
`send_ignition_alert` (24120) · `send_spike_alert` (24355) ·
`send_accum_dist_alert` (24801) · `send_leg_entry_alert` (21702)

**Alert triggers:** `check_trading_signals` (2131) · `check_atm_verdict_alert`
(2226) · `check_gex_alert` (2702) · `check_pcr_sr_proximity_alert` (11038)

**Message builders:** `send_master_signal_telegram` (24886) — **1,600 lines,
the single largest non-orchestrator block in the file** ·
`build_mios_v5_telegram_signal` (16781, 213) · `_cmce_build_telegram_message`
(4577) · `_iofce_build_telegram_message` (4878) · `_get_zone_telegram_msg`
(26627) · `_balanced_telegram_chunks` (239)

**Lifecycle alerts:** `_send_signal_birth_telegram` (17233) ·
`_send_signal_entry_telegram` (17256) · `_send_signal_exit_telegram` (17272)

**Other:** `maybe_play_combo_audio` (23836) · `test_telegram_connection` (672) ·
`_mios_stamp` (26) · `ist_iso` (17057) · `_fmt_pts` (17068)

> Note: `send_discord_message`, `send_telegram_message_sync`,
> `_throttled_telegram_send` and `capture_market_event` are *inside* the closure
> only because V6-feeding functions call them on the side. Their own output is
> not read by V6 either.

---

### C. AI / LLM advisors · 15 blocks · 891 lines

Three providers (Gemini, Groq, Anthropic), plus the panel and its diagnostics.
Nothing here writes a V6 key.

`ai_explain_signal` (10568, **409 lines**) · `build_ai_market_snapshot` (19346) ·
`generate_ai_context_message` (11707) · `render_ai_advisor` (19575) ·
`ai_advisor_stream` (19541) · `ai_advisor_diagnostics` (19222) ·
`ai_test_connection` (19252) · `_gemini_stream` (19447) · `_groq_stream` (19484) ·
`_claude_stream` (19527) · `_anthropic_client` (19329) · `_get_gemini_client`
(10558) · `_ai_providers` (19420) · `_ai_user_content` (19434) ·
`ai_analyze_telegram_message` (10508)

---

### D. Auto-trading / broker execution · 4 blocks · 185 lines

`_analyze_zone` (26520) · `_place_trade` (26637) · `_exit_trade` (26672) ·
`_detect_candle_pattern` (26492) — plus dead `show_auto_trade_section` (§A).

V6 never places an order and has no execution path.

---

### E. Native confirmation engines · 18 blocks · 1,018 lines

Four self-contained engines that exist to gate a Telegram alert. Each has its
own detector set and its own message builder; none writes a V6 key.

| Engine | Entry point | Blocks |
|---|---|---|
| **CIE** — Candlestick Intelligence | `run_candlestick_intelligence_engine` (4128) | 6 · 430L |
| **CMCE** — Cross-Market Confirmation | `run_cross_market_confirmation` (4458) | 5 · 276L |
| **IOFCE** — Institutional Order Flow | `run_iofce` (4790) | 7 · 289L |
| **AMIE** — ATM OI/depth reads | `_amie_oi_behavior` (3106), `_amie_depth_signal` (3174) | 2 · 97L |

V6 answers the same questions structurally — Stage 42 acceptance, Stage 43
absorption, Stage 45 HTF alignment — from the canonical caches instead.

---

### F. Native analysis V6 does not read · 36 blocks · 3,480 lines

The biggest and least obvious category. These are real analyses; V6 simply
never reads their result. Several ask a question a V6 stage also asks.

| Line | Lines | Name | V6 asks the same question at |
|---|---|---|---|
| 13220 | **983** | `compute_composite_bias` | `v6_bias` four-voter (Stage 53) |
| 24180 | 173 | `compute_spike_probability` | Stage 37 energy |
| 23956 | 162 | `compute_ignition_score` | Stage 37 energy |
| 12788 | 140 | `compute_bull_bear_meter` | Stage 53 bias compare |
| 7701 | 260 | `analyze_strike_activity` | Stage 41 layer scores |
| 7032 | 201 | `get_instrument_capping_analysis` | — (multi-instrument, NIFTY-only in V6) |
| 24708 | 91 | `compute_accum_dist_score` | Stage 43 absorption |
| 22275 | 97 | `compute_greek_absorption` | Stage 43 absorption |
| 24647 | 32 | `detect_absorption` | Stage 43 absorption |
| 1613 | 147 | `FutureSwing` (class) | Stage 45 HTF |
| 1441 | 75 | `TriplePOC` (class) | `htf_vpfr` profiles |
| 22549 | 76 | `compute_leg_depth_profile` | — |
| 22486 | 61 | `compute_accumulation_flow` | — |
| 10978 | 59 | `compute_unwinding_summary` | — |
| 24501 | 55 | `compute_per_candle_pxoi` | — |
| 6977 | 53 | `calculate_pcr_sr_level` | Stage 42 acceptance levels |
| 24595 | 50 | `compute_vp_shape` | `htf_vpfr` |
| 23691 | 45 | `compute_premarket_analysis` | Stage 68 day type |
| 2452 | 41 | `compute_iv_rank_percentile` | — |
| 2805 | 37 | `calculate_pcr_gex_confluence` | — |
| 24558 | 35 | `detect_cum_delta_divergence` | Stage 44 flow shift |
| 24681 | 25 | `compute_vwap_bands` | — |
| 27959 | 56 | `observe_opening_auction` | Stage 4 gap |
| 4980 | 83 | `_detect_chart_candle_types` | — |
| 5085 | 96 | `_detect_liquidity_candles` | — |
| 5843 | 57 | `_ltf_delta_volume` | — |
| 5902 | 40 | `_compute_leg_delta_volume` | — |
| 23890 | 64 | `_detect_depth_sweep` | — |
| 5325 | 46 | `_alignment_verdict` | Stage 45 HTF alignment |
| 5222 | 23 | `_check_grab_confirmation` | — |
| 5650 | 29 | `_capture_atm_mfp_bins` | — |
| 23861 | 27 | `_get_ws_sweep_in_last` | — |
| 24405 | 23 | `_track_total_oi_timeseries` | — |
| 6070 | 17 | `_vpfr_zone_bias` | — |
| 27234 | 15 | `_oi_flow_mode` | — |
| 24493 | 6 | `_classify_pxoi` | — |

`compute_composite_bias` alone is 983 lines — the third-largest block in the
file — and its only outputs are `_composite_bias` (→ a native panel) and
`_sr_behavior_state` (which no `mios_v5` module reads).

---

### G. Charts and graphs · 9 blocks · 1,447 lines

Every chart in the app is a *drawing*. V6 reads none of them; Dashboard 2 draws
its own from `mios_v5/ui/terminal_chart.py`.

| Line | Lines | Name | What it draws |
|---|---|---|---|
| 6342 | **561** | `create_candlestick_chart` | main NIFTY candles + every overlay |
| 27014 | 218 | `_render_cvd_suite` | NIFTY · LTP net · order-book · ATM±2 OI CVD |
| 21133 | 182 | `render_atm_cvd_graphs` | ATM±1 CALL vs PUT CVD / cum buy / cum sell |
| 27251 | 133 | `_render_per_strike_oi_top` | per-strike CE vs PE OI |
| 26904 | 108 | `_render_vol_delta_chart` | buy vs sell volume delta |
| 12695 | 91 | `render_oi_charts` | CE/PE OI and ΔOI |
| 23771 | 60 | `render_sector_heatmap` | sector rotation strength |
| 5681 | 53 | `render_atm_mfp_bin_charts` | ATM money-flow-profile bins |
| 24430 | 41 | `render_total_oi_timeseries` | total OI over time |

**39 `st.plotly_chart` calls · 37 figure builds · 71 tables · 39 metrics — none
read by V6.**

---

### H. Native UI panels · 25 blocks · 1,935 lines

| Line | Lines | Name |
|---|---|---|
| 17671 | **663** | `render_clean_card` — the full Trade Card |
| 26750 | 152 | `_render_alignment_capping_top` |
| 16395 | 123 | `_render_mobile_view` |
| 21317 | 105 | `render_leg_bias_table` |
| 21786 | 86 | `render_leg_entry_decisions` |
| 19943 | 79 | `render_leg_volume_table` |
| 17596 | 73 | `render_signal_history` |
| 22155 | 61 | `render_confirmed_entry_signals` |
| 22218 | 55 | `render_factor_performance` |
| 17541 | 53 | `render_signal_lifecycle` |
| 26695 | 53 | `_render_fii_dii_futures_section` |
| 24835 | 49 | `render_smart_money_panel` |
| 16658 | 48 | `render_data_cleanup` |
| 7653 | 47 | `display_analytics_dashboard` |
| 19164 | 40 | `render_composite_bias_panel` |
| 12657 | 36 | `render_major_sr_table` |
| 6904 | 34 | `display_metrics` |
| 23534 | 31 | `render_ws_health_badge` |
| 16625 | 31 | `render_decision_performance` |
| 12930 | 30 | `render_bull_bear_meter` |
| 21762 | 22 | `_render_leg_signal_history` |
| 24385 | 18 | `render_spike_meter` |
| 24161 | 17 | `render_ignition_meter` |
| 22374 | 17 | `render_greek_absorption` |
| 22627 | 12 | `render_leg_depth_profile` |

`render_clean_card` is the app's own Trade Card. It *consumes* V6 (it calls
`build_final_read`) — the dependency runs the other way. Removing it would not
change a single V6 number.

---

### I. Side markets and other instruments · 2 blocks · 55 lines

**Corrected.** This section originally listed all seven side-market blocks,
including the four panels. Four of them are **needed** — they are the
fetch-and-publish path for data the Market Picture reads, not decoration:

| Panel | publishes | read by |
|---|---|---|
| `render_global_indices_panel` | `_global_indices` | `compute_global_nifty_bias` |
| `render_gift_nifty_moneyflow_panel` | `_gift_mf` | `compute_market_picture` |
| `render_commodity_risk_panel` | `_commodity_risk` | `compute_market_picture`, bias dashboard |
| `_panel_self_fetch` | `_panel_fetch_errors` | all three panels |

Each of those reads is `… or {}`, so deleting the panel would not crash — it
would make the category report MISSING. That is the failure mode this audit
exists to prevent, so they stay.

Genuinely not needed: `get_sensex_option_security_ids` (1105, 52) — SENSEX, and
V6 is NIFTY-only end to end — and `get_market_breadth_cached` (1209, 3).

---

### J. Decision engines v0 / v2 and signal lifecycle · 26 blocks · 1,132 lines

Generation 4. It sits **downstream** of V6 — it reads `build_final_read` and
turns it into a gated decision, a logged signal, and a trade life. V6 does not
read any of it back.

`compute_leg_entry_decisions` (21424, 276) · `process_confirmed_entry_signals`
(21954, 199) · `_advance_signal` (17474, 65) · `compute_decision_performance`
(16566, 57) · `advance_explainability` (17369, 52) ·
`build_mios_decision_and_log` (16737, 42) · `_record_signal_attribution` (17140) ·
`log_event_impact` (27921) · `_store_leg_entry_signals` (21730) · `_birth_signal`
(17326) · `manage_signal_lifecycle` (17296) · `_attribution_reliability` (17110) ·
`_mios_decision_gate` (16708) · `_record_trade_excursion` (17179) ·
`_record_trade_result` (17206) · `_attribution_reads` (17086) ·
`_log_day_type_change` (17440) · `_fresh_oi_wall_against` (21874) ·
`_log_session` (17423) · `_signal_engine_snapshot` (17041) ·
`_candles_after` (16550) · `_new_signal_id` (17026) · `_grade_trade` (16536) ·
`_signal_qualifies` (17013) · `_mios_final_read` (17461) · `_closed_bar_delta` (21911)

**One exception.** `process_confirmed_entry_signals` writes
`_entry_armed_setups` and `_entry_signal_open`, which **Dashboard 2 reads**
(`dashboard_v6.py:307–8, 507–8`) to show armed setups. That is a *screen*
dependency, not an analysis one — no V6 stage reads them.

---

### K. Infrastructure and ops · 11 blocks · 194 lines

`get_ws_health` (23483, 49) · `save_app_state` (23638) · `restore_app_state`
(23663) · `main` (35891, 22) · `validate_credentials` (6939, 27) ·
`_serialize_value` (23602) · `_deserialize_value` (23622) · `_supabase_client`
(23593) · `create_csv_download` (6972) · `get_user_id` (6967) ·
`cached_pivot_calculation` (223)

---

### L. `_render_main_analyzer` — lines 28017–35888 · 7,872 lines · **partial**

The one block that cannot be classified whole. It is the page, and it is where
V6's inputs are published. Roughly **11 of its 7,872 lines** matter to V6:

| Line | Writes | For |
|---|---|---|
| 28169 | `build_htf_profiles(...)` | Stage 45 |
| 28178 | `_is_expiry_today` | Stage 68 |
| **31218** | **`_mios_pass()`** | **the V6 run itself** |
| 28707 | `capture_day_open_and_gap` | Stage 4 |
| 28730 | `_nifty_spot_live` | spot, every stage |
| 28743–4 | `_fii_dii_cash`, `_fii_deriv_stats` | Stage 23 |
| 28891–6 | `_composite_profile`, `_value_migration`, `_money_flow_data` | Stages 42/45 |
| 28937 | `_volume_delta_data` | Stage 44 |
| 29959–66 | `_atm_leg_dfs`, `_atm_leg_sids` | Dashboard 2 charts |
| 30001 | `render_all_bias_dashboard` | `_all_bias_rows`, `_leg_bias_cache` |
| 31175–7 | `analyze_option_chain` → `_cached_option_data` | every chain stage |
| 32146 | `_iv_history` | IV stages |
| 32925 | `_gex_data` | GEX stages |
| 33466 | `_reaction_sr` | Stage 42 |

Everything else in those 7,872 lines is the ~40 expanders enumerated below.

---

## 5. The UI surface — 40+ expanders, and who needs them

Not needed for V6 (the entire native page, in render order):

⚡ Buy vs Sell Volume Delta · 📈 CVD Suite · 📊 Per-Strike CE/PE OI ·
🌡️ Sector Heatmap · 📊 Bull/Bear Meter · 🎯 Spike Probability ·
💰 Smart Money Footprint · 🚀 Movement Ignition · 📊 OI CE vs PE & ΔOI ·
🎯 Major S/R Zones · 📊 NIFTY VPFR + Money Flow · 🧠 CIE Signals ·
📐 Geometric & Reversal Patterns · 🔗 CMCE · 🏦 IOFCE · 💧 Liquidity Grab ·
💧 Stop Hunt + VPFR on ATM±1 · 🕯️ Candle Patterns · 💰 Money Flow ATM±4 ·
🔄 OI Unwinding ATM±5 · 📈 HTF S/R · 🔍 Option Chain Deep ATM±5 ·
🗂️ OC Signal History · 📊 PCR / OI / ΔOI / Volume / Bid Qty / Ask Qty
time series (6 expanders) · 📊 GEX Analysis · 📊 Detailed Greeks ·
🎯 Master Trading Signal · 📊 Multi-Instrument Capping Monitor ·
🕯 Candle Pattern Timeline · 📋 Signal History · 📊 Market Depth Analyzer ·
📅 Expiry Day Spike Detector · 🎯 All-Day Spike Detector ·
🏦 NIFTY Futures/FII-DII/Breadth · 🌍 Alignment · 📡 Index/Stock Capping ·
🔄 Sector Rotation · 📋 Today's Trade History · 🔧 AI status ·
📸 AI Snapshot · 📒 Signal Lifecycle history · 🗄️ Supabase Cleanup ·
🎯 Decision Engine Performance · 📊 Entry Gate History

Needed: **🖥 MIOS V6** (31225) and **🧭 MIOS V5** (31234) — and those two
render V6/V5's own UI, not the app's.

---

## 6. Findings this audit turned up

### 6.1 Four V6 inputs were one full cycle stale — now fixed

> **Fixed by the reduction (§8).** Every producer now runs above the pass, and
> `test_every_producer_now_runs_before_the_pass` fails if one moves back below
> it. What follows is what the full app did.

`_mios_pass()` ran at **line 31218**. Four producers ran *after* it:

| Key | Written at | V6 stage affected |
|---|---|---|
| `_iv_history` | 32146 | IV reads |
| `_gex_data` | 32925 | GEX reads |
| `_reaction_sr` | **33466** | **Stage 42 acceptance** |
| `_df_5m` · `vix_history` · `_sector_rotation` · `_last_df` | 33414/33429 via `generate_master_signal` | Stages 22, 45, sector |

At a 20s refresh, Stage 42 is judging acceptance against S/R levels built 20s
ago, and `build_htf_profiles` (line 28169, inside `_mios_pass`) builds Stage 45's
profiles from the **previous** cycle's `_last_df`.

At a 20s refresh, Stage 42 was judging acceptance against S/R levels built 20s
earlier, and `build_htf_profiles` built Stage 45's profiles from the previous
cycle's `_last_df`. The runner's docstring tolerates this — Phase-B engines "may
be one cycle old" — but tolerating is not the same as being correct.

### 6.2 The same question is answered up to four times

Absorption is computed by `compute_greek_absorption` (22275), `detect_absorption`
(24647), `compute_accum_dist_score` (24708) — and by `mios_v5/absorption.py`
(Stage 43). Bias is computed by `compute_composite_bias` (983 lines),
`compute_bull_bear_meter` (140), the native master signal, and V6's four-voter.
Only the V6 versions reach the Opportunity Matrix.

### 6.3 712 lines are unreachable

10 blocks with no reference anywhere, including a 329-line broker-execution UI
(`show_auto_trade_section`) and a 90-line indicator class. The first count was
1,178 across 21 blocks; eleven of those were live and are documented in §A.

---

## 7. Summary

Corrected totals. §A lost 11 blocks that were live; §I lost 4 that feed the
Market Picture; §F lost `compute_per_candle_pxoi`, `_classify_pxoi`,
`compute_greek_absorption`, `render_greek_absorption` and `render_atm_cvd_graphs`
for the same reason.

| Category | Blocks | Lines | % of file |
|---|---|---|---|
| A · Dead code | 10 | 712 | 2.0% |
| B · Alerting | 43 | 3,710 | 10.3% |
| C · AI advisors | 15 | 891 | 2.5% |
| D · Auto-trading | 4 | 185 | 0.5% |
| E · Native confirmation engines | 18 | 1,018 | 2.8% |
| F · Native analysis V6 ignores | 31 | 2,977 | 8.3% |
| G · Charts & graphs | 8 | 1,265 | 3.5% |
| H · Native UI panels | 24 | 1,918 | 5.3% |
| I · Side markets | 2 | 55 | 0.2% |
| J · Decision v0/v2 + lifecycle | 26 | 1,132 | 3.2% |
| K · Infrastructure | 11 | 194 | 0.5% |
| L · `_render_main_analyzer` | 1 | 7,872 | 21.9% (partial) |
| **Not needed for V6** | **205** | **~21,900** | **61%** |
| **Inside the V6 closure** | **137** | **12,893** | **36%** |

---

## 8. The reduction — what was actually removed

The audit was executed. `vob_minimal.py` went from **35,916 lines to 13,175** —
**22,741 lines removed, 63%** — and from 342 top-level blocks to 145.

### What the app is now

```
_render_main_analyzer()                          ~300 lines, twelve steps
  1  Supabase handle + story task            8  canonical S/R  → _reaction_sr
  2  sidebar: interval / days / expiry       9  price-vs-OI, greek absorption, CVD
  3  NIFTY candles, spot, 5m frame          10  render_all_bias_dashboard
  4  futures · FII/DII · VIX · sector       11  build_htf_profiles → THE MIOS PASS
  5  dual profile · volume delta            12  render V6, then V5
  6  side-market panels (Market Picture inputs)
  7  option chain → _cached_option_data
```

Two new helpers carry the leg fetch that used to live 1,300 lines deep inside a
Stop-Hunt expander: `_leg_intraday` (the cache / budget / 429 discipline,
verbatim) and `_publish_atm_legs` (six legs, the four per-leg stores, the
cockpit wing ids).

### What went

Every category in §4 except the corrected entries: all 43 alerting blocks that
had no kept caller, all 15 AI-advisor blocks, the auto-trade path, CIE, CMCE,
IOFCE, AMIE, the ~40 native expanders, all 39 charts, the v0/v2 decision engines
and signal lifecycle, the multi-instrument monitor, the mobile view, and
`compute_composite_bias` (983 lines — its only reader recomputes via
`classify_sr_behavior`, so the dependency was soft).

**The native Trade Card came back.** `render_clean_card` (663 lines) was removed
on the same correct reasoning as everything else — it *consumes* V6 (it calls
`build_final_read`), so no V6 stage reads it — and restored on request,
verbatim. It turned out to reference nothing else that had been removed. It is
rendered into a container claimed at the top of the page and filled at step 10,
because it reads what `render_all_bias_dashboard` stashes
(`_market_picture`, `_entry_gate_active`, `_guard_state`) yet has to appear
above it.

`generate_master_signal` (652 lines) went too. It was in the closure *only*
because it published `_df_5m`, `_last_df`, `vix_history` and `_sector_rotation`
as side effects. The rewrite publishes those four directly, which orphaned it —
and orphaned five more blocks on the next pass.

### What survived that the audit called "not needed"

Alerting is **not** fully gone, and the audit's §B overstated this. Five alert
functions and `_throttled_telegram_send` are still live because
`render_all_bias_dashboard` and `render_market_picture` call them internally, and
those two are V6 producers — `_all_bias_rows`, `_leg_bias_cache`,
`_market_picture`, `_full_market_read` and `_market_structure` all come from
them. Removing the alerts means editing inside two functions V6 depends on, so
they stayed. **The Entry Gate alerts still fire.**

### Also fixed while in there

* **§6.1 is closed.** All twelve producers now run above the pass. Stage 42 reads
  S/R built this cycle; Stage 45 profiles the current frame.
* **The hardcoded Discord webhook is gone** from all three sites (181/184/198),
  replaced with `""`. Rotating the leaked URL is still worth doing — it was in
  git history for the life of the repo.
* **The bare `except:`** at line 172 is now `except Exception:`.
* Three unused LLM key blocks, the `google.genai` import and
  `INSTRUMENT_CONFIGS` removed.

### How it was verified

| | |
|---|---|
| `ast.parse` | clean |
| pyflakes undefined names | **1 name** (`Vv`, twice on one line) — pre-existing, original line 20112 |
| V6 input keys still published | 31 / 31 |
| Test suite | **1,145 passing** |
| `AppTest` headless run, network stubbed | **0 exceptions** |

The AppTest run earned its place: it caught
`render_dashboard_v6() got multiple values for argument 'db'` — both dashboards
take `(state=, db=)` and never `st`. Static analysis cannot see a wrong call
signature through a keyword collision, and every test in the suite passed while
the app rendered neither dashboard.

Five tests were updated because their anchors moved, not their guarantees:
`test_clock` (the signal lifecycle it checked is gone; the IST rule it enforced
is asserted directly), `test_workstation` and `test_fetch_budget` (the fetch
discipline moved into `_leg_intraday`), and two of the audit's own guards.

### What this costs

Everything the trader used to look at on the native page. No charts, no native
Trade Card, no AI advisor, no OI/PCR/volume time series, no multi-instrument
monitor, no signal history. The V6 workstation and the V5 audit layer are the
whole UI now. That was the ask; it is worth being explicit that it is what
happened.
