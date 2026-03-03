# Changelog

## 0.10.51
- Promoted calibration patches to active baseline config surfaces:
  - `configs/runs/_core.yml` (shared stock parameters)
  - `configs/trade.yml` (`trade_od` allocator controls)
  - stock patch from `outputs/runs/calibration/mvp/baseline/20260302-152016/search_best_config_patch.yml`,
  - trade patch from `outputs/runs/calibration/trade_od/mvp_stock_calibrated_trial19_tmp/baseline/20260302-163204/best_trade_od_patch.yml`.
- Activated promoted trade controls:
  - `trade_od.coupling_relax_lambda_0_1: 0.5`
  - `trade_od.capacity_cap_sd_multiplier: 1.2`
- Deprecated non-selected patch artifacts for baseline promotion:
  - `outputs/runs/calibration/mvp/baseline/20260302-152016/best_config_patch.yml`
  - `outputs/runs/calibration/trade_od/mvp/baseline/20260302-092503`
  - `outputs/runs/calibration/trade_od/mvp/baseline/20260302-131753`

## 0.10.50
- Fully wired endogenous OD trade into runtime SD-dMFA coupling when `trade_od.enabled=true` and `trade_od.runtime_mode=endogenous`.
- Added material-level outer trade loop controls:
  - `trade_od.outer_trade_max_iter`
  - `trade_od.outer_trade_convergence_tol`
  - runtime diagnostics artifact: `trade_od_outer_loop_convergence.csv`.
- Runtime trade dependency update:
  - `trade_od_weights` is runtime-required in trade mode.
  - `trade_od_observed` and `trade_od_constraints` are calibration/backtesting-only.
- Added runtime weight extrapolation policy:
  - `trade_od.weight_extrapolation_policy=clamp_normalize`.
- Added endogenous commodity trade mapping controls:
  - `trade_od.concentrate_to_refined_coeff`
  - `trade_od.scrap_to_secondary_coeff`.
- Added trade shock channels:
  - `trade_refined_import_need_multiplier`
  - `trade_concentrate_import_need_multiplier`
  - `trade_scrap_import_need_multiplier`
  - `trade_export_capacity_multiplier`.
- Removed legacy compatibility alias for refined-net-import shocks:
  - scenarios must use `trade_refined_import_need_multiplier` directly.
- Removed runtime dependency on exogenous refined-net-import CSV inputs.
- Added MFA runtime diagnostics for endogenous trade constraint construction:
  - refined input required pre-cap,
  - secondary-feed gap/surplus proxies,
  - upstream concentrate-equivalent gap/surplus proxies.
- Added/updated tests for:
  - weight extrapolation clamp+normalize,
  - endogenous constraint builder and direct trade-shock mapping,
  - trade config surface defaults.

## 0.10.49
- Canonicalized active ramp-path usage to `data/ramp_profiles/**` across configs/tests/docs.
- Kept one-cycle runtime backward compatibility for legacy `data/scenario_profiles/**` references in `crm_model.cli`.
- Removed step-style major structural controls in `r36_*` and `r79_*` scenario YAMLs by migrating to per-key `exogenous_ramp` declarations.
- Expanded `data/ramp_profiles/r_strategies/r36_profiles.csv` and `r79_profiles.csv` with multi-anchor ramp trajectories and scoped region rows.
- Tuned `_core` collection dynamics to reduce early saturation pressure:
  - `collection_price_response_gain: 0.22`
  - `collection_multiplier_max: 1.10`
  - `collection_multiplier_lag_years: 4.0`
- Updated `strategic_reserve_build_release` for guaranteed pre-crisis build-up and observable crisis release behavior.
- Added/updated tests for canonical ramp paths and ramp-backed r36/r79 scenario controls:
  - `tests/test_repo_layout_scaffold.py`
  - `tests/test_scenarios.py`
  - `tests/test_scenario_temporal_forms.py`
  - `tests/test_mvp_scenario_consistency_contracts.py`
  - `tests/test_indicator_jump_sanity.py`
- Added scenario/output documentation clarifications:
  - allowed discrete-vs-ramped control policy,
  - ratio-jump interpretation notes,
  - troubleshooting entries for collection saturation and strategic reserve activation gaps.

## 0.10.48
- Added native scenario-level `exogenous_ramp` references for temporal overrides:
  - `key: { exogenous_ramp: <csv_path> }` now resolves from profile CSV rows by `(variant, block, key)` plus material/region scope precedence.
- Updated MVP scenario implementation to use explicit per-key ramp references:
  - `configs/scenarios/mvp/circularity_push.yml`
  - `configs/scenarios/mvp/import_squeeze_circular_ramp.yml`
- Deprecated run-level `scenario_profiles` usage for MVP:
  - removed `scenario_profiles` block from `configs/runs/mvp.yml`.
- Updated scenario interface contracts/docs to present `exogenous_ramp` as the exogenous ramp declaration surface.
- Added regression tests for:
  - runtime exogenous ramp resolution + scope precedence,
  - MVP scenario declarations using `exogenous_ramp`,
  - absence of run-level `scenario_profiles` block in MVP run config.

## 0.10.47
- Refined MVP scenario consistency for `circularity_push`, `demand_surge`, `combined_shocks`, and `recycling_disruption`.
- Harmonized acute-shock timing to `2025-2039` for `demand_surge`, `combined_shocks`, and `recycling_disruption`.
- Updated `demand_surge` to a global baseline shock plus region-specific modulation overlays.
- Updated `recycling_disruption` to keep a global disruption with explicit overrides for all regions (`EU27`, `China`, `RoW`).
- Rebalanced `combined_shocks` severity to stay internally consistent with dedicated disruption scenarios.
- Extended `circularity_push` profile ramps with explicit `2039` anchors for smoother structural transitions.
- Added scenario consistency regression tests:
  - `tests/test_mvp_scenario_consistency_contracts.py`
  - scaffold expectation now includes `data/ramp_profiles/mvp/circularity_push.csv`.

## 0.10.46
- Added explicit `scenario_profiles` run-config interface:
  - `enabled`, `csv_globs`, `interpolation`, `apply_precedence`, `emit_resolved_payload`.
- Added runtime CSV profile auto-activation in `crm_model.cli`:
  - loads all configured profile CSVs,
  - builds full-horizon variant payloads,
  - applies `profile_overrides_variant` precedence during reporting-phase slice resolution,
  - writes `resolved_profile_payload.yml` and profile activation metadata into run artifacts.
- Added loader normalization for `scenario_profiles.csv_globs` relative paths.
- Tightened coupling realism/stability controls:
  - `service_stress_signal_cap`,
  - `coupling_stress_multiplier_cap`,
  - `coupling_signal_smoothing_strategic` (strategic channel smoothing only).
- Updated `_core` SD defaults and heterogeneity to reduce chronic stress amplification and improve stability.
- Updated `strategic_reserve_build_release` scenario controls for improved convergence behavior.
- Converted long structural step-like R-strategies applications toward ramped behavior:
  - removed long-horizon flat `collection_rate`/`sorting_yield` shock usage in `r79_*` and `r_portfolio_combined`,
  - moved to profile-driven temporal `mfa_parameters` pathways.
- Expanded `data/ramp_profiles/r_strategies/*.csv` coverage for demand transformation, capacity/bottleneck progression, and recovery-loop ramps.

## 0.10.45
- Refined scenario internals across `mvp` and `r-strategies` while keeping existing variant IDs stable.
- Added new MVP resilience/circularity scenario:
  - `configs/scenarios/mvp/import_squeeze_circular_ramp.yml`
  - combines primary import squeeze stress with delayed transition-policy and demand-transformation recovery.
- Refined R-strategies mechanism mapping:
  - `r02_*` now uses demand-transformation channels as primary demand-efficiency mechanism.
  - `r36_*` now includes explicit transition-policy adoption/compliance settings.
  - `r79_*` now includes explicit SD collection-response tuning and reporting-phase gating.
- Strengthened scenario heterogeneity contract by ensuring targeted `dimension_overrides` across key stress variants.
- Added reporting-window timeseries profile authoring workflow:
  - profile templates/data under `data/ramp_profiles/**`
  - expansion utility: `scripts/scenarios/build_reporting_timeseries_profiles.py`
  - core expansion helpers: `src/crm_model/scenario_profiles.py`
- Added scenario/profile validation coverage:
  - `tests/test_scenario_dimension_override_contracts.py`
  - `tests/test_reporting_profile_expander.py`
  - `tests/test_scenario_temporal_forms.py`
  - updated scaffold and scenario schema expectations.

## 0.10.44
- Refined `configs/indicators.yml` logical subset memberships for a clearer medium-granularity split while keeping subset IDs stable.
- Tightened indicator subset validation in `IndicatorsConfig`:
  - subset names must be unique across MFA and resilience groups,
  - each group's logical subsets must form a strict partition (no duplicates, no missing assignments).
- Added dedicated subset validation tests:
  - `tests/test_indicators_subsets.py`.

## 0.10.43
- Added explicit transition/demand config interfaces across run+scenario surfaces:
  - `transition_policy` and `demand_transformation` blocks in `RunConfig`, scenario variants, and dimension overrides.
- Wired transition-policy adoption dynamics into runtime preprocessing:
  - adoption/compliance delay stock,
  - collection/recycling/capacity-response uplifts,
  - bottleneck-gain relief channel.
- Wired demand-transformation preprocessing into slice demand setup:
  - optional `service_activity` and `material_intensity` exogenous drivers,
  - scalar/year-gated/timeseries multipliers,
  - efficiency + rebound handling with bounded demand multipliers.
- Added optional exogenous templates:
  - `data/exogenous/templates/service_activity_template.csv`
  - `data/exogenous/templates/material_intensity_template.csv`
- Added new MVP scenarios showcasing the new dynamics:
  - `transition_policy_acceleration`
  - `demand_transformation_shift`
- Extended scaffold/config/scenario tests for the new config surface and scenario pack.

## 0.10.42
- Reorganized documentation into coherent subfolders:
  - `docs/getting-started/`
  - `docs/model/`
  - `docs/workflows/`
  - `docs/governance/`
  - `docs/internal/`
- Merged redundant standalone scenario checklist into:
  - `docs/workflows/SCENARIOS.md` (`#scenario-authoring-checklist`)
  - removed `docs/SCENARIO_AUTHORING_CHECKLIST.md`.
- Updated cross-references in root README and docs pages to the new structure.
- Added explicit redundancy rationale in `docs/README.md`.

## 0.10.41
- Added a central documentation hub page:
  - `docs/README.md` with role-based navigation and source-of-truth pointers.
- Added an end-to-end execution quickstart:
  - `docs/getting-started/QUICKSTART.md` with validation, run, and analysis commands.
- Added explicit config merge and temporal-resolution reference:
  - `docs/workflows/CONFIG_PRECEDENCE.md`.
- Added operational failure diagnosis guide:
  - `docs/getting-started/TROUBLESHOOTING.md` including non-convergence and activation-floor failure interpretation.
- Added scenario implementation runbook:
  - `docs/workflows/SCENARIOS.md#scenario-authoring-checklist`.
- Added output artifact interpretation guide:
  - `docs/model/OUTPUTS_GUIDE.md`.
- Added canonical terminology reference:
  - `docs/model/GLOSSARY.md`.
- Updated `docs/model/ARCHITECTURE.md`:
  - linked to new docs and added explicit operational run order.
- Updated `docs/workflows/SCENARIOS.md`:
  - added authoring workflow and minimum acceptance checks.
- Updated SD-dynamics interpretation docs:
  - `docs/model/SD_CAPACITY_SCARCITY_PRICE_LOOP.md` now documents interactions with stockpile, strategic reserve, coupling signals, and tuning diagnostics.
  - `docs/workflows/CALIBRATION.md` now adds staged guidance on when/how to include SD dynamics in calibration.

## 0.10.40
- Moved config interface contracts into inline YAML comments:
  - each file in `configs/` and `registry/variable_registry.yml` now starts with streamlined `#` interface instructions.
- Updated architecture and scenario docs to reference inline YAML contracts as source of truth.

## 0.10.39
- Enforced hard deprecation for legacy SD aliases in `sd_parameters`:
  - removed runtime alias compatibility; legacy keys now fail fast with explicit canonical replacement guidance.
- Enforced hard deprecation for legacy strategy collection controls:
  - `strategy.collection_multiplier_{min,max,lag_years}` now fail fast; controls must be set in `sd_parameters`.
- Updated tests/config fixtures to canonical SD naming only.
- Added explicit modeling guide for the endogenous capacity-scarcity-price loop with bottleneck delays:
  - `docs/model/SD_CAPACITY_SCARCITY_PRICE_LOOP.md`
  - linked from `docs/model/ARCHITECTURE.md` and scenario documentation.

## 0.10.38
- Added new MVP scenario `capacity_crunch_recovery` in `configs/scenarios/mvp/` to explicitly exercise endogenous capacity/scarcity/price bottleneck dynamics.
- Tuned `_core` SD defaults in `configs/runs/_core.yml` for balanced-realism activation of:
  - capacity-envelope response,
  - bottleneck scarcity amplification,
  - bottleneck collection throttle,
  while preserving stable loose-iterative convergence.
- Extended test coverage:
  - scaffold and MVP variant set expectations include `capacity_crunch_recovery`,
  - scenario schema test for `capacity_crunch_recovery`,
  - SD unit test for crunch-recovery pressure peak then relaxation,
  - smoke assertions ensure Phase-5 SD diagnostics remain exported.

## 0.10.37
- Added SD canonical parameter normalization and legacy alias compatibility in `src/crm_model/sd/params.py`:
  - `base_price -> price_base`
  - `scarcity_sensitivity -> price_scarcity_sensitivity`
  - `price_elasticity -> demand_price_elasticity`
  - `service_stress_gain -> coupling_service_stress_gain`
  - `circular_supply_stress_gain -> coupling_circular_supply_stress_gain`
  - `scarcity_smooth -> coupling_signal_smoothing`
- Added compatibility migration for deprecated strategy collection controls:
  - `strategy.collection_multiplier_{min,max,lag_years}` are migrated to `sd_parameters`.
- Refactored SD/BPTK loop to include a capacity-envelope and bottleneck pathway:
  - `capacity_envelope`, `flow_utilization`, `bottleneck_pressure`,
  - scarcity amplification and collection bottleneck throttle,
  - lagged capacity adjustment using BPTK-native `smooth`.
- Updated coupling runtime and indicators to export SD diagnostics:
  - `SD_scarcity_multiplier_effective`
  - `SD_capacity_envelope`
  - `SD_flow_utilization`
  - `SD_bottleneck_pressure`
  - `SD_collection_bottleneck_throttle`
- Migrated core config/scenario ownership:
  - moved collection multiplier controls from `strategy` to `sd_parameters` in `configs/runs/_core.yml`,
  - migrated `configs/scenarios/mvp/surplus_build_drawdown.yml` accordingly,
  - updated SD baseline/heterogeneity keys to canonical names.

## 0.10.36
- Promoted latest completed `mvp.yml` calibration patch to baseline defaults in `configs/runs/_core.yml`:
  - `mfa_parameters.fabrication_yield`
  - `mfa_parameters.reman_yield`
  - `strategy.reman_yield`
- Archived deprecated artifacts:
  - `data/exogenous/stage_yields_losses_fit.csv` -> `data/exogenous/_archive/20260223/`
  - incomplete calibration run `outputs/runs/calibration/mvp/baseline/20260223-104445` ->
    `outputs/runs/calibration/mvp/baseline/_archive/20260223/`
- Updated scaffold tests to remove deprecated stagefit overlay file expectations.

## 0.10.35
- Extended upstream stage-yield fitter (`scripts/calibration/fit_stage_yields_losses.py`) with:
  - variable-weighted upstream objective,
  - optional pair-specific smoothing,
  - pairwise degradation penalty diagnostics,
  - region-targeted lambda search mode with region-level degradation constraints.
- Added v3 opt-in stagefit wiring:
  - `registry/variable_registry_stagefit_v3.yml`
  - `configs/runs/mvp-stagefit-v3.yml`
- Added region-targeted v3 opt-in wiring:
  - `registry/variable_registry_stagefit_v3_region.yml`
  - `configs/runs/mvp-stagefit-v3-region.yml`
- Added stagefit-v3 scaffold/config tests in `tests/test_repo_layout_scaffold.py`.

## 0.10.34
- Added upstream stage-yield fitter script: `scripts/calibration/fit_stage_yields_losses.py`.
- Added opt-in stagefit registry/run wiring:
  - `registry/variable_registry_stagefit_v2.yml`
  - `configs/runs/mvp-stagefit-v2.yml`
- Added stage-yield v2/observed-upstream data docs in `data/README.md`.
- Documented upstream fitting workflow and plot-scope deprecation of `primary_production.csv` comparisons in `docs/workflows/CALIBRATION.md`.
- Extended scaffold/config tests for the new run overlay and stagefit registry.

## 0.10.33
- Simplified default calibration cycle in `configs/calibration.yml` for faster iteration:
  - reduced DE budget (`max_evaluations: 120`, `popsize: 8`),
  - disabled local refinement by default,
  - tightened stopping patience for earlier termination.
- Preserved previous high-budget calibration setup in `configs/calibration_full.yml`.
- Improved calibration runtime behavior in `scripts/calibration/calibrate_model.py`:
  - creates output run directory at start,
  - writes live checkpoint artifacts during search (`checkpoint.yml`, `trial_history.partial.csv`, `search_best_config_patch.partial.yml`),
  - supports wall-clock stop budget via `--max-runtime-minutes`,
  - enforces `optimization.stopping` patience/min-improvement during DE search,
  - preserves best-so-far outputs/metadata on interruption.
- Updated `docs/workflows/CALIBRATION.md` with the new fast-vs-full workflow and recommended commands.

## 0.10.32
- Added dedicated R-strategies run pack: `configs/runs/r-strategies.yml`.
- Added dMFA-first R-strategies scenario catalog under `configs/scenarios/r_strategies/`:
  - R0/R2 ladder: `r02_demand_efficiency_{low,medium,high}`
  - R3/R6 ladder: `r36_lifetime_reman_{low,medium,high}`
  - R7-R9 ladder: `r79_recovery_loops_{low,medium,high}`
  - Cross-group portfolio: `r_portfolio_combined`
- Applied pack-level baseline headroom for manufacturing scrap loop closure:
  - `strategy.new_scrap_to_secondary_share: 0.85` in `r-strategies.yml`.
- Extended scaffold/config tests to include the new run file and scenario set.
- Added a scenario-level smoke test for `r_portfolio_combined` execution path.

## 0.10.31
- Added SD-controlled strategic reserve mechanism with split inventory stocks:
  - retained operational `refinery_stockpile_native`,
  - added separate `strategic_inventory_native` stock at refining.
- Extended SD model outputs with reserve policy intents:
  - `strategic_fill_intent`
  - `strategic_release_intent`
  and wired strategy parameters for target coverage, trigger thresholds, gains, and max rates.
- Extended coupling interface and iteration loop with strategic channel:
  - MFA->SD: `strategic_stock_coverage_years_t`
  - SD->MFA: `strategic_fill_intent_t`, `strategic_release_intent_t`
  - added convergence diagnostics for strategic signal and intent deltas.
- Extended MFA runtime accounting:
  - strategic fill/release flows with non-negative stock enforcement,
  - fill competes with current-year supply (secondary-first, then primary),
  - strategic mass-balance checks and new exported timeseries.
- Added new shock channels:
  - `strategic_fill_intent`
  - `strategic_release_intent`
- Added stress scenario:
  - `configs/scenarios/mvp/strategic_reserve_build_release.yml`.
- Expanded indicator exports/config with strategic reserve metrics and coupling signal.
- Added calibration preflight warning when strategic reserve is enabled during baseline calibration.

## 0.10.30
- Added run-config inheritance (`extends`) with recursive merge and cycle detection in `src/crm_model/config/io.py`.
- Introduced canonical core+overlay run layout:
  - `configs/runs/_core.yml` (shared includes/defaults)
  - `configs/runs/mvp.yml` (thin overlay)
- Canonicalized include usage to `includes.end_uses`; legacy aliases (`includes.applications`, `includes.end_use`) remain supported for one cycle with deprecation warnings.
- Added strict guardrail rejecting simultaneous end-use include aliases in one run config.
- Added run-config lint utility: `scripts/validation/lint_run_configs.py`.
- Converted `configs/base.yml` to a deprecated compatibility shim via `extends: runs/mvp.yml` (planned removal target: 2026-04-30).
- Added/updated config-loader regression tests for extends merge behavior, cycle detection, alias conflict validation, and alias deprecation warnings.

## 0.10.29
- Migrated canonical primary-supply runtime inputs to refining-anchored variables:
  - `primary_refined_output`
  - legacy exogenous refined-net-import input
  - `stage_yields_losses`
- Rewired CLI/data validation/MFA runtime to:
  - compute primary availability using refined output plus contemporaneous trade signal (legacy formulation in that release),
  - reconstruct upstream extraction/beneficiation/refining throughput from explicit yields,
  - route stage losses/rejects using configured disposal/sysenv shares.
- Extended scenario shock surface with stage-consistent channels:
  - `primary_refined_output`, legacy exogenous refined-net-import shock,
  - `extraction_yield`, `beneficiation_yield`, `refining_yield`, `sorting_yield`.
- Added migration utilities and diagnostics:
  - `scripts/data/build_primary_chain_model_ready.py`
  - diagnostics outputs under `data/exogenous/diagnostics/primary_chain_model_ready/`.
- Kept one-cycle compatibility aliases with deprecation behavior:
  - `primary_production`, legacy exogenous refined-net-import alias,
  - `primary_available_to_refining`,
  - legacy refined-net-import shock alias.
- Updated architecture/assumptions/scenarios/risk/flowchart documentation to the new canonical setup.

## 0.10.28
- Expanded the canonical dMFA boundary to the forward/reverse-chain stage graph in `configs/stages.yml` and kept `sysenv` as process `id: 0`.
- Removed `secondary_buffer_stock_native` and `reman_buffer_stock_native`; introduced `refinery_stockpile_native`.
- Reworked MFA runtime/accounting to:
  - separate `new_scrap_*` (pre-use losses) from `old_scrap_*` (post-use outflow),
  - route secondary material through refinery stockpile dynamics,
  - retain legacy topology compatibility while supporting expanded graphs without `end_of_life`.
- Added new strategy knobs:
  - `refinery_stockpile_release_rate`
  - `new_scrap_to_secondary_share`
  - with one-cycle deprecated alias support: `secondary_buffer_release_rate`.
- Migrated indicators/config exports from buffer-based metrics to refinery-stockpile and scrap-split metrics.
- Updated tests, docs, and reporting pipeline to the new stockpile/scrap model.

## 0.10.27
- Retired the legacy runtime package entirely by removing its source tree.
- Kept `crm_model` as the only runtime codebase and canonical CLI/module namespace.
- Migrated/cleaned tests and docs to remove active legacy-namespace usage.
- Performed repository hygiene sweep removing stale cache/artifact folders (`__pycache__`, `.DS_Store`, legacy egg-info directory).

## 0.10.26
- Migrated full runtime ownership from the legacy runtime package to `src/crm_model`:
  - copied and activated canonical implementations for config/data/mfa/sd/coupling/indicators/utils/scenarios/cli under `crm_model`.
  - updated internal imports to use `crm_model.*`.
- Converted legacy runtime modules into compatibility shims re-exporting `crm_model` modules (superseded by 0.10.27 retirement).
- Switched operational entry scripts to canonical `crm_model` CLI (`scripts/run_one.py`, `scripts/run_batch.py`).
- Updated migration/architecture docs to reflect completed runtime move and shim compatibility.

## 0.10.25
- Removed legacy top-level config files:
  - `configs/applications.yml`
  - `configs/dimensions.yml`
  - `configs/mfa_graph.yml`
  - `configs/mvp.yml`
- Migrated run configs to `configs/runs/mvp.yml`.
- Migrated dimension/graph includes to split files (`regions.yml`, `materials.yml`, `end_use.yml`, `stages.yml`, `qualities.yml`) via loader-level composition.
- Added robust repo-root resolution from config paths so nested run-config locations remain runtime-safe.

## 0.10.24
- Added missing `crm_model` compatibility wrappers for script-facing surfaces:
  - `crm_model.scenarios`
  - `crm_model.common.run_layout`
  - `crm_model.data`
  - `crm_model.mfa.lifetime_adapter`
  - `crm_model.common.config_models`
  - `crm_model.cli`
- Migrated operational scripts (analysis/calibration/validation/batch) to consume `crm_model` imports instead of legacy runtime imports.
- Updated migration notes to mark direct-import decommission complete for operational scripts while preserving temporary backward compatibility.

## 0.10.23
- Extended `includes.scenarios` loading to accept directory paths, single files, and `*.yml` glob patterns.
- Kept backward compatibility: top-level inline `variants` still override file-based scenario definitions with the same name.
- Updated `configs/base.yml` and `configs/mvp.yml` to explicit scenario glob includes.
- Added scenario-loader regression tests for glob loading, single-file loading, and inline override precedence.

## 0.10.22
- Split SD builder implementation into staged modules:
  - `sd.bptk_model`
  - `sd.run_sd`
  - `sd.levers`
  - `sd.shocks`
  - `sd.scenario`
- Kept `sd.builder` as a compatibility shim during transition to avoid breaking imports.
- Updated internal SD imports to target the staged modules and added SD module-split compatibility tests.

## 0.10.21
- Split dMFA builder implementation into staged modules:
  - `mfa.dimensions`
  - `mfa.parameters`
  - `mfa.system`
  - `mfa.run_mfa`
- Kept `mfa.builder` as a compatibility shim during transition to avoid breaking imports.
- Updated internal imports to use `run_mfa`/`system` directly and added module-split compatibility tests.

## 0.10.20
- Added authoritative coupling signal registry in the runtime coupling interface and enforced validation of `coupling.signals` names.
- Unified coupling interface exports so both namespaces shared one source of truth during migration.
- Added interface-shape regression tests for core configs and invalid-signal rejection.

## 0.10.19
- Strengthened coupling realism with configurable MFA->SD feedback modes (`time_series` default, `scalar_mean` fallback) and optional reporting-window-only feedback updates.
- Upgraded SD scarcity input from scalar-only to full time-series lookup, enabling year-varying scarcity/price response dynamics.
- Added coupling diagnostics metadata for feedback mode and reporting-window masking.

## 0.10.18
- Removed legacy custom collection-rate pre-shaping; collection shock handling is now fully SD-native (runtime, plotting, tests).

## 0.10.17
- Removed the last migration toggle and made SD-native collection control canonical across runtime/docs.

## 0.10.16
- Cleaned migration config surface (removed retired keys, fail-fast on stale keys with strict schema).

## 0.10.15
- Moved collection multiplier logic into native BPTK equations and consumed SD outputs directly in coupling.

## 0.10.14
- Removed custom lifetime-engine runtime path; flodym-native lifetime handling is now canonical.

## 0.10.13
- Removed custom buffer-engine runtime path; flodym stock-native buffers became canonical; added collection diagnostics/indicators.

## 0.10.12
- Introduced stock-native secondary/reman buffer mode and wired buffer-engine selection through runtime.

## 0.10.11
- Removed deprecated runtime aliases, tightened duplicate validation, and hardened indicator schema consistency checks.

## 0.10.10
- Added first-class coupling diagnostics outputs (iteration-year signals and iteration convergence traces).

## 0.10.9
- Reorganized indicator logical subsets under grouped category blocks in `configs/indicators.yml`.

## 0.10.8
- Added indicator subset/formula metadata and expanded indicator documentation with formulas/interpretation.

## 0.10.7
- Refactored coupling to two explicit stress signals (`service_stress`, `circular_supply_stress`) plus combined multiplier reporting.

## 0.10.6
- Added material-region SD heterogeneity rules with ordered override resolution and regression tests.

## 0.10.5
- Added bounded, lagged dynamic collection behavior and wired controls through strategy/config/runtime.

## 0.10.4
- Extended surplus buffering logic to remanufactured output; added reman buffer indicators and terminal-inventory clarification.

## 0.10.3
- Renamed `disposed` to `disposal` and added secondary buffer stock with release control + indicators.

## 0.10.2
- Added exogenous end-use reman eligibility input and end-use-gated reman routing with strict validation.

## 0.10.1
- Added scenario metadata, material-region overrides, new shock channels, and routing-shock renormalization behavior.

## 0.10.0
- Major model realism update: explicit collection/disposal pathways, unified routing-rate dataset, net-import balance input, strict lifetime validation (`lognormal` support), mass-balance checks, leaner run artifacts, `mvp.yml` baseline + calibration cycle, and repository hygiene cleanup.

## 0.9.0
- Added robust region/material normalization, explicit surplus/loss accounting, improved resilience-window scalar logic, and end-use dimensional consistency in core flows.

## 0.8.1
- Externalized dMFA stage/link definitions to `configs/mfa_graph.yml` with semantic roles and config-driven naming.

## 0.8.0
- Established the coupled SD (BPTK-Py) + dMFA (flodym) template, modular config includes, exogenous schema enforcement, demand-response phase switch, and standardized output artifacts.
