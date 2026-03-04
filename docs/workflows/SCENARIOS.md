# Scenario Variants: Definition and Execution Guide

This document explains how scenario variants are defined and executed in the current model runtime.

Use this file when you need to understand scenario intent, runtime behavior, and operational usage with concrete examples from the live scenario packs.

For full config contracts across all config files, use:
`docs/workflows/CONFIGS.md`.

## Document position

- You are here: Tier 2 canonical workflow reference for scenario variants.
- Canonical scope: variant definition, runtime resolution order, and operational examples from active scenario packs.
- Out of scope: full config contract definitions (kept in `CONFIGS.md`) and low-level module formula derivations.
- Related docs: [CONFIGS.md](./CONFIGS.md), [ARCHITECTURE.md](../model/ARCHITECTURE.md), [COUPLING_LOGIC.md](../model/COUPLING_LOGIC.md), [SD_MODEL.md](../model/SD_MODEL.md), [MFA_MODEL.md](../model/MFA_MODEL.md), [OD_TRADE_MODULE.md](../model/OD_TRADE_MODULE.md), [INDICATORS.md](../model/INDICATORS.md), [TROUBLESHOOTING.md](../getting-started/TROUBLESHOOTING.md)

## 1) Purpose and reader outcomes

After reading this page, you should be able to:

1. Understand how a scenario variant is represented in YAML.
2. Understand how variant values are resolved and applied at runtime.
3. Explain why each current scenario exists and what mechanism it is testing.
4. Run a variant and know what outputs to inspect to verify behavior.

## 2) How scenario variants are defined in config

Variants are defined in two places:

1. Scenario files under `configs/scenarios/**/*.yml`.
2. Inline `variants:` under a run config (`configs/runs/*.yml`).

A scenario file must provide:

- `name`
- `description`
- `implementation`

A scenario file can additionally provide any of these override blocks:

- `sd_parameters`
- `mfa_parameters`
- `strategy`
- `transition_policy`
- `demand_transformation`
- `shocks`
- `dimension_overrides`

`dimension_overrides` is the slice-level mechanism. Each item can target:

- `materials` (optional filter)
- `regions` (optional filter)
- local block overrides (`sd_parameters`, `mfa_parameters`, `strategy`, `transition_policy`, `demand_transformation`, `shocks`)

Practical point: if `materials` or `regions` is omitted in an override item, that item matches all values for the omitted dimension.

## 3) How scenario variants are executed in runtime

This is the actual execution sequence in the current code path.

### 3.1 Variant loading

1. Run config is loaded.
2. If `includes.scenarios` is set, scenario files are loaded first.
3. Inline run-config `variants` are merged on top of file-based variants by name.

Operational implication: inline `variants.<name>` in a run file can override the same-name file variant.

### 3.2 Per-slice variant resolution

For each material-region slice, runtime resolves the active variant in this order:

1. Start from the variant global blocks.
2. Apply matching `dimension_overrides` in file order.
3. Keep block separation (`sd_parameters`, `mfa_parameters`, `strategy`, `transition_policy`, `demand_transformation`, `shocks`).

Operational implication: when multiple `dimension_overrides` match the same slice, later items override earlier ones for overlapping keys.

### 3.3 Scenario profile overlays (when enabled)

If `scenario_profiles.enabled=true`, CSV-based profile payloads are built and merged on top of the resolved variant payload.

Operational implication: profile payloads can overwrite variant values for the same path in reporting runs.

### 3.4 Exogenous ramp resolution

`exogenous_ramp` references are resolved per block and per slice.

Operational implication: the same variant can produce different resolved time series by slice when profile files include material/region-scoped rows.

### 3.5 Reporting-phase enforcement

For reporting runs, runtime enforces reporting-window activation behavior:

1. Shock events are clamped to `report_start_year` if configured earlier.
2. Year-gated values are clamped to start no earlier than `report_start_year`.
3. Certain runtime-impact scalars are converted to reporting-gated form.
4. Missing `before` values are backfilled from baseline where applicable.

Operational implication: a scenario that configures early-year changes can still execute as reporting-phase-only behavior unless intentionally configured otherwise.

### 3.6 Final merge into run bases

Resolved variant blocks are merged into run-level baseline blocks:

- `sd_parameters`
- `mfa_parameters`
- `strategy`
- `transition_policy`
- `demand_transformation`
- `shocks`

Then the selected phase (`calibration`, `reporting`, `both`) executes.

### 3.7 Phase behavior

- Reporting phase receives scenario profile payloads when profiles are enabled.
- Calibration phase does not apply profile payload overlays.

### 3.8 OD trade interaction

When endogenous OD runtime is enabled (`trade_od.runtime_mode=endogenous`), variant resolution happens inside the per-slice inner loop and is re-evaluated across outer OD iterations.

Operational implication: variant shocks and overrides affect both local slice dynamics and the trade-constraint feedback loop.

## 4) Current scenario catalog by variant family

The current repository has 20 scenario-file variants:

- Family A (`mvp`): 10 variants.
- Family B (`r_strategies`): 10 variants.

### 4.1 Family A: `mvp`

#### `capacity_crunch_recovery`

- Variant file: `configs/scenarios/mvp/capacity_crunch_recovery.yml`
- Why it exists: stress-test endogenous scarcity-capacity-bottleneck recovery under prolonged supply pressure.
- What it does: combines demand pressure with tighter primary and trade availability, then lets recovery emerge endogenously.
- Blocks used: `sd_parameters`, `shocks`, `dimension_overrides`.
- Time structure: acute window starts in 2025, duration 18 years.
- Scope structure: global stress plus deeper nickel-EU27 stress.
- Runtime execution notes: SD gains are intensified before SD normalization; shock channels are applied after base series load.
- What to verify in outputs:
  - `SD_bottleneck_pressure` rises in stress window.
  - `Service_level` drops and later recovers.
  - `Coupling_service_stress` and `Coupling_stress_multiplier` peak during stress.

#### `circularity_push`

- Variant file: `configs/scenarios/mvp/circularity_push.yml`
- Why it exists: test an improvement pathway centered on circular loops rather than crisis shocks.
- What it does: raises collection and circular conversion performance through ramps, with targeted nickel-EU27 reinforcement.
- Blocks used: `mfa_parameters`, `strategy`, `dimension_overrides`.
- Time structure: exogenous ramps from `data/ramp_profiles/mvp/circularity_push.csv`.
- Scope structure: global improvements plus targeted EU27 nickel routing/collection reinforcement.
- Runtime execution notes: ramp references are resolved per slice; routing keys are interpreted with routing-triad normalization behavior.
- What to verify in outputs:
  - `Collection_rate_effective`, `EoL_recycled`, `EoL_remanufactured` increase.
  - `Secondary_supply` increases and `Primary_supply` pressure eases.

#### `combined_shocks`

- Variant file: `configs/scenarios/mvp/combined_shocks.yml`
- Why it exists: represent realistic mixed stress where multiple channels hit different slices at once.
- What it does: applies a global demand surge and adds layered regional/material shocks.
- Blocks used: `shocks`, `dimension_overrides`.
- Time structure: global and local shocks start in 2025 for 15 years.
- Scope structure: global demand stress; deeper nickel-EU27 and zinc-China local stress.
- Runtime execution notes: local override order matters where channels overlap.
- What to verify in outputs:
  - Compare `Unmet_service` and `Service_deficit` across affected slices.
  - Confirm local stress slices move more than non-target slices.

#### `demand_surge`

- Variant file: `configs/scenarios/mvp/demand_surge.yml`
- Why it exists: provide a clean demand-only stress baseline for comparison.
- What it does: applies a harmonized demand shock window globally, with region-specific multipliers.
- Blocks used: `shocks`, `dimension_overrides`.
- Time structure: shock starts in 2025, duration 15 years.
- Scope structure: global plus region-specific severity (`China`, `EU27`, `RoW`).
- Runtime execution notes: same shock channel, different regional multipliers via dimension overrides.
- What to verify in outputs:
  - `Service_demand` rises according to configured severity pattern.
  - `Service_level` and bottleneck indicators diverge by region.

#### `demand_transformation_shift`

- Variant file: `configs/scenarios/mvp/demand_transformation_shift.yml`
- Why it exists: isolate demand-structure effects from transition-policy effects.
- What it does: activates demand transformation, increases service activity, reduces intensity, adds bounded rebound.
- Blocks used: `demand_transformation`, `shocks`, `dimension_overrides`.
- Time structure:
  - `enabled` gate from 2020 (`before: false`).
  - demand-transformation parameter gates from 2025.
  - supporting demand shock window from 2025 for 10 years.
- Scope structure: global transformation + region-specific adjustments (China and EU27).
- Runtime execution notes: demand transformation is applied before MFA flow execution for each slice.
- What to verify in outputs:
  - `Service_demand` and delivered-service metrics separate from baseline pattern.
  - intensity-driven changes reduce pressure relative to equal-service baseline.

#### `import_squeeze_circular_ramp`

- Variant file: `configs/scenarios/mvp/import_squeeze_circular_ramp.yml`
- Why it exists: test staged crisis-to-recovery logic with combined SD, policy, and demand-transformation levers.
- What it does: starts with import/supply squeeze, then activates policy and efficiency response from 2028 onward.
- Blocks used: `sd_parameters`, `transition_policy`, `demand_transformation`, `shocks`, `dimension_overrides`.
- Time structure:
  - stress shocks start in 2025 for 11 years.
  - response controls ramp from 2028.
  - mixed temporal forms (year-gated + exogenous ramp).
- Scope structure: global stress/recovery with deeper nickel-EU27 squeeze and slower RoW policy response.
- Runtime execution notes: this variant exercises most resolution layers (global blocks, dimension overrides, ramps, reporting clamp).
- What to verify in outputs:
  - early stress: higher `Coupling_service_stress`, lower `Service_level`.
  - recovery period: improving `Coupling_circular_supply_stress` and lower bottleneck pressure.

#### `recycling_disruption`

- Variant file: `configs/scenarios/mvp/recycling_disruption.yml`
- Why it exists: isolate circular-loop disruption effects and regional resilience differences.
- What it does: applies global recycling disruption with regional severity differences and routing/trade stress.
- Blocks used: `shocks`, `dimension_overrides`.
- Time structure: start 2025, duration 15 years.
- Scope structure: global disruption plus explicit EU27/China/RoW severity overrides.
- Runtime execution notes: local shock sets include collection and routing channels to shape secondary-flow stress.
- What to verify in outputs:
  - declines in `EoL_recycled` and `Secondary_supply`.
  - rising service stress in more severe regions.

#### `strategic_reserve_build_release`

- Variant file: `configs/scenarios/mvp/strategic_reserve_build_release.yml`
- Why it exists: test strategic reserve policy behavior across build and release phases.
- What it does: enables reserve controls, applies fill intent before crisis and release intent during demand/import stress.
- Blocks used: `sd_parameters`, `strategy`, `shocks`, `dimension_overrides`.
- Time structure: reserve controls and strategic smoothing gated from 2025; stress/release channels are staged.
- Scope structure: global reserve behavior plus region/material-specific damping and priority buffering.
- Runtime execution notes: strategic channels influence coupling through strategic coverage signals.
- What to verify in outputs:
  - `Strategic_inventory_stock` builds before crisis and declines during release.
  - `Strategic_stock_coverage_years` and strategic intent indicators follow configured pattern.

#### `surplus_build_drawdown`

- Variant file: `configs/scenarios/mvp/surplus_build_drawdown.yml`
- Why it exists: test buffer accumulation then natural drawdown behavior without introducing new structural modules.
- What it does: combines lower demand pressure with stronger collection/routing in build phase, then allows drawdown after shocks end.
- Blocks used: `sd_parameters`, `strategy`, `shocks`, `dimension_overrides`.
- Time structure:
  - build-oriented shock window from 2025 with long horizon.
  - drawdown behavior after shock expiry.
- Scope structure: global buffer pattern with nickel-EU27 priority intensification.
- Runtime execution notes: collection multiplier bounds/lag tuning supports smoother build dynamics.
- What to verify in outputs:
  - stockpile and circular surplus diagnostics show build then drawdown pattern.
  - service metrics stabilize when buffer is available.

#### `transition_policy_acceleration`

- Variant file: `configs/scenarios/mvp/transition_policy_acceleration.yml`
- Why it exists: isolate transition-policy and adoption/compliance lag effects.
- What it does: activates transition-policy and linked demand-transformation settings without explicit shock channels.
- Blocks used: `transition_policy`, `demand_transformation`, `dimension_overrides`.
- Time structure: policy enable gate at 2020; active intervention starts in 2026.
- Scope structure: global policy acceleration plus nickel-EU27 front-runner override.
- Runtime execution notes: this variant is useful for policy-loop testing under low shock noise.
- What to verify in outputs:
  - gradual service and bottleneck improvements aligned with adoption lag.
  - sensitivity of recovery speed to regional front-runner settings.

### 4.2 Family B: `r_strategies`

The `r_strategies` family is organized as mechanism-specific intensity ladders.

- R02 demand efficiency
- R36 lifetime and remanufacturing
- R79 recovery loops

#### `r02_demand_efficiency` intensity ladder (`low`, `medium`, `high`)

- Variant IDs:
  - `r02_demand_efficiency_low`
  - `r02_demand_efficiency_medium`
  - `r02_demand_efficiency_high`
- Variant files:
  - `configs/scenarios/r_strategies/r02_demand_efficiency_low.yml`
  - `configs/scenarios/r_strategies/r02_demand_efficiency_medium.yml`
  - `configs/scenarios/r_strategies/r02_demand_efficiency_high.yml`
- Why this grouped block exists: provide one comparable demand-efficiency ladder where only ambition level changes.
- What this grouped block does: applies the same demand-efficiency mechanism (demand transformation + fabrication-yield improvements) at three intensity levels.
- Blocks used across all three variants: `mfa_parameters`, `demand_transformation`, `dimension_overrides`.
- Time structure across all three variants: year-gated activation from 2025 with demand-transformation `enabled` gate from 2020.
- Scope structure across all three variants: regional differentiation across `EU27`, `China`, and `RoW`.
- Runtime execution notes:
  - Resolution path is identical across low/medium/high; only parameter intensity differs.
  - This makes the three variants suitable for direct sensitivity comparison.
- Intensity interpretation:
  - `low`: modest demand moderation and efficiency gains.
  - `medium`: stronger moderation than low with same mechanism structure.
  - `high`: strongest demand and efficiency shift in the R02 track.
- What to verify in outputs:
  - monotonic movement in `Service_deficit` and stress indicators from low to high.
  - same qualitative pattern by region, with stronger magnitude at higher intensity.

#### `r36_lifetime_reman` intensity ladder (`low`, `medium`, `high`)

- Variant IDs:
  - `r36_lifetime_reman_low`
  - `r36_lifetime_reman_medium`
  - `r36_lifetime_reman_high`
- Variant files:
  - `configs/scenarios/r_strategies/r36_lifetime_reman_low.yml`
  - `configs/scenarios/r_strategies/r36_lifetime_reman_medium.yml`
  - `configs/scenarios/r_strategies/r36_lifetime_reman_high.yml`
- Why this grouped block exists: provide one comparable lifetime/reman ladder where ambition increases without changing the mechanism family.
- What this grouped block does: increases lifetime extension, reman routing, reman yield, and related policy support at three intensity levels.
- Blocks used across all three variants: `sd_parameters`, `strategy`, `transition_policy`, `dimension_overrides`.
- Time structure across all three variants: exogenous ramps from `r36_profiles.csv` plus transition-policy gating.
- Scope structure across all three variants: region-specific adoption targets and policy tuning.
- Runtime execution notes:
  - Resolution structure is identical across low/medium/high; intensity values differ.
  - This ladder is suitable for direct ambition-sensitivity comparison on reman/lifetime mechanisms.
- Intensity interpretation:
  - `low`: moderate lifetime and reman improvements with conservative policy support.
  - `medium`: stronger lifetime/reman shift with higher policy ambition.
  - `high`: strongest lifetime/reman and policy support settings in the R36 track.
- What to verify in outputs:
  - monotonic increase in reman-related outputs from low to high.
  - progressively lower primary-pressure dependence as intensity increases.

#### `r79_recovery_loops` intensity ladder (`low`, `medium`, `high`)

- Variant IDs:
  - `r79_recovery_loops_low`
  - `r79_recovery_loops_medium`
  - `r79_recovery_loops_high`
- Variant files:
  - `configs/scenarios/r_strategies/r79_recovery_loops_low.yml`
  - `configs/scenarios/r_strategies/r79_recovery_loops_medium.yml`
  - `configs/scenarios/r_strategies/r79_recovery_loops_high.yml`
- Why this grouped block exists: provide one comparable recovery-loop ladder from incremental to ambitious circular recovery performance.
- What this grouped block does: strengthens collection, sorting, recycling, routing, and manufacturing scrap-loop closure at three intensity levels.
- Blocks used across all three variants: `sd_parameters`, `mfa_parameters`, `strategy`.
- Time structure across all three variants: exogenous ramps from `r79_profiles.csv`.
- Scope structure across all three variants: global pathway (no `dimension_overrides`).
- Runtime execution notes:
  - Execution path is the same across low/medium/high; only ramp amplitudes differ.
  - This ladder is suitable for clean low-noise global pathway comparisons.
- Intensity interpretation:
  - `low`: incremental loop strengthening.
  - `medium`: stronger circular-loop uplift than low.
  - `high`: strongest collection/sorting/recycling and near-closed new-scrap loop settings in the R79 track.
- What to verify in outputs:
  - monotonic improvements in circular-flow metrics from low to high.
  - stronger circular supply contribution and lower stress pressure at higher intensity.

#### `r_portfolio_combined`

- Variant file: `configs/scenarios/r_strategies/r_portfolio_combined.yml`
- Why it exists: combine R02 + R36 + R79 logic into one integrated pathway.
- What it does: blends demand efficiency, lifetime/reman, and recovery-loop controls with transition policy and SD tuning.
- Blocks used: `sd_parameters`, `mfa_parameters`, `strategy`, `transition_policy`, `demand_transformation`.
- Time structure: profile-driven ramps (`r_portfolio_profiles.csv`) with transition-policy gating and mid-horizon pressure features.
- Scope structure: global integrated pathway (no explicit local overrides).
- Runtime execution notes: this is the most comprehensive non-shock pathway variant in the repository.
- What to verify in outputs:
  - joint movement across service, circular supply, and bottleneck indicators.
  - balanced improvement pattern rather than single-channel improvement.

## 5) Practical execution examples

The examples below use current run overlays and current variant IDs.

### 5.1 Acute demand shock (`demand_surge`)

```bash
PYTHONPATH=src python scripts/run_one.py \
  --config configs/runs/mvp.yml \
  --variant demand_surge \
  --phase reporting \
  --save-csv
```

What is active:

- Block focus: `shocks` + region `dimension_overrides`.
- No policy or demand-transformation block changes.

How overrides resolve:

1. Global `demand_surge` shock is set.
2. Region-specific overrides replace multiplier by region.
3. Reporting clamp ensures reporting-phase activation behavior.

What to check:

- `indicators/timeseries.csv`: `Service_demand`, `Service_level`, `SD_bottleneck_pressure` by region.
- `summary.csv`: convergence flags and final stress metrics.

### 5.2 Layered multi-channel stress (`combined_shocks`)

```bash
PYTHONPATH=src python scripts/run_one.py \
  --config configs/runs/mvp.yml \
  --variant combined_shocks \
  --phase reporting \
  --save-csv
```

What is active:

- Global demand shock.
- Local nickel-EU27 and zinc-China shock bundles.

How overrides resolve:

1. Global shock applies everywhere.
2. Local override bundles apply only to matching slices.
3. Overlap is resolved by listed order.

What to check:

- targeted slices should show stronger `Unmet_service` and circular-stress effects than untargeted slices.

### 5.3 Crisis-to-recovery (`import_squeeze_circular_ramp`)

```bash
PYTHONPATH=src python scripts/run_one.py \
  --config configs/runs/mvp.yml \
  --variant import_squeeze_circular_ramp \
  --phase reporting \
  --save-csv
```

What is active:

- `sd_parameters`, `transition_policy`, `demand_transformation`, `shocks`, and local overrides.

How overrides resolve:

1. Global stress + policy/efficiency response blocks are resolved.
2. Local EU27 nickel and RoW overrides are applied.
3. Ramps are expanded from CSV and then reporting-gated as needed.

What to check:

- early-window stress increase then late-window recovery in service and bottleneck indicators.

### 5.4 Strategic reserve dynamics (`strategic_reserve_build_release`)

```bash
PYTHONPATH=src python scripts/run_one.py \
  --config configs/runs/mvp.yml \
  --variant strategic_reserve_build_release \
  --phase reporting \
  --save-csv
```

What is active:

- reserve controls in `strategy`, strategic smoothing in `sd_parameters`, crisis and intent shocks.

How overrides resolve:

1. Reserve policy parameters activate via gated strategy values.
2. Strategic intent shocks shape fill/release behavior.
3. Local damping/priority overrides modify region/material behavior.

What to check:

- reserve stock and coverage indicators show build then release pattern.

### 5.5 Demand-structure transformation (`demand_transformation_shift`)

```bash
PYTHONPATH=src python scripts/run_one.py \
  --config configs/runs/mvp.yml \
  --variant demand_transformation_shift \
  --phase reporting \
  --save-csv
```

What is active:

- demand transformation gates and regional demand-transformation overrides.

How overrides resolve:

1. Demand transformation is enabled and applied per slice.
2. Regional overrides adjust activity/intensity/efficiency terms.
3. Supporting demand shock runs in the configured window.

What to check:

- compare service indicators and demand-related stress trajectory to baseline.

### 5.6 Integrated pathway (`r_portfolio_combined`)

```bash
PYTHONPATH=src python scripts/run_one.py \
  --config configs/runs/r-strategies.yml \
  --variant r_portfolio_combined \
  --phase reporting \
  --save-csv
```

What is active:

- combined SD + MFA + strategy + transition policy + demand transformation blocks.
- scenario profiles are enabled in this run overlay.

How overrides resolve:

1. Base variant values are loaded.
2. Profile payload overlays variant values for matching keys.
3. Resolved values are merged into run baseline by block.

What to check:

- balanced co-improvement across service, circularity, and bottleneck signals.

## Scenario authoring checklist

This section is intentionally concise and acts as a compatibility anchor and practical quick list.

1. Define one mechanism hypothesis first, then add complexity.
2. Keep `description` and `implementation` explicit and testable.
3. Use global blocks for broad behavior; use `dimension_overrides` only for true slice heterogeneity.
4. Keep override order intentional when multiple items can match the same slice.
5. Prefer reporting-window activation unless historical divergence is explicitly intended.
6. Use `exogenous_ramp` for structural pathways and `shocks` for discrete events.
7. Run baseline and scenario with the same run config before comparing outcomes.
8. Validate convergence and mechanism movement before expanding scope.
9. Keep schema/contract details in `docs/workflows/CONFIGS.md`.

## 7) Troubleshooting and quick validation

### 7.1 Quick checks for scenario catalog and links

```bash
rg -n "^## Scenario authoring checklist" docs/workflows/SCENARIOS.md
rg -n "configs/scenarios/.+\.yml" docs/workflows/SCENARIOS.md
rg -n "SCENARIOS\.md#scenario-authoring-checklist" README.md docs
```

### 7.2 Quick checks for variant coverage

```bash
python - <<'PY'
import glob, yaml
files=sorted(glob.glob('configs/scenarios/**/*.yml', recursive=True))
print('scenario files:', len(files))
print('variant names:')
for f in files:
    d=yaml.safe_load(open(f))
    print('-', d.get('name'))
PY
```

### 7.3 Runtime validation commands

Single variant run:

```bash
PYTHONPATH=src python scripts/run_one.py --config configs/runs/mvp.yml --variant demand_surge --phase reporting --save-csv
```

Pre-report drift warning check:

```bash
PYTHONPATH=src python scripts/validation/check_reporting_preperiod_drift.py --config configs/runs/mvp.yml
```

### 7.4 Typical interpretation issues

1. If a change appears before `report_start_year`, confirm whether explicit `before` values were set in year-gated/ramp forms.
2. If local overrides seem ignored, verify `materials`/`regions` filters match canonical IDs exactly.
3. If profile ramps appear to override YAML values, confirm `scenario_profiles.enabled` and matching profile rows for the active variant.
4. If OD trade effects look inconsistent across iterations, inspect both coupling convergence outputs and OD outer-loop diagnostics.

## 8) Supported scenario shock channels in current packs

Current scenario files actively use the following shock channels:

- `demand_surge`
- `recycling_disruption`
- `primary_refined_output`
- `trade_refined_import_need_multiplier`
- `collection_rate`
- `recycling_rate`
- `remanufacturing_rate`
- `strategic_fill_intent`
- `strategic_release_intent`

Additional channels remain available by contract in run config defaults; see `docs/workflows/CONFIGS.md` for complete interface details.

## 9) Related sections

- [CONFIGS.md §5-7](./CONFIGS.md#5-variant-interface-contract-configsscenariosyml) for schema and precedence details referenced by this execution guide.
- [ARCHITECTURE.md §7](../model/ARCHITECTURE.md#7-coupling-logic-inner-outer-loops) for where scenario overrides act in coupling runtime.
- [INDICATORS.md §5](../model/INDICATORS.md#5-coupling-diagnostics-interpretation-dedicated-section) for post-run iteration diagnostics interpretation.
