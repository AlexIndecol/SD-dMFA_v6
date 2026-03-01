# Scenario Definitions

This document explains how scenario variants are defined and executed.

For full contracts across all config files (not only scenarios), use the inline `#`
interface-contract comments at the top of each YAML file in `configs/` and
`registry/variable_registry.yml`.

Related references:

- `docs/workflows/CONFIG_PRECEDENCE.md`
- `docs/getting-started/TROUBLESHOOTING.md`
- `docs/model/SD_CAPACITY_SCARCITY_PRICE_LOOP.md`

## Config structure

Scenario variants can be loaded from scenario files via
`includes.scenarios` (directory, single file, or `*.yml` glob), and/or
declared inline in your run config under `variants:`.

When both are present, inline `variants` entries override file-based entries
with the same variant name for backward-compatible transitions.

Cross-cutting SD heterogeneity can be defined at top-level using:

- `sd_heterogeneity`: ordered material/region-scoped rules with `sd_parameters`.
- Rules are applied per material-region slice before variant overrides.
- Variant `sd_parameters` / `dimension_overrides[*].sd_parameters` still take precedence.

Useful SD coupling controls:

- `coupling_service_stress_gain`: weight from service-stress coupling signal to SD stress multiplier.
- `coupling_circular_supply_stress_gain`: weight from circular-supply-stress coupling signal to SD stress multiplier.
- `coupling_signal_smoothing`: iterative smoothing factor applied to both coupling signals.

Each variant should provide:

- `description`: what the scenario represents.
- `implementation`: how the scenario is translated into model behavior.
- optional global overrides:
  - `sd_parameters`
  - `mfa_parameters`
  - `strategy`
  - `transition_policy`
  - `demand_transformation`
  - `shocks`
- optional `dimension_overrides`: material/region-scoped overrides.

For `mfa_parameters` and `strategy`, overrides can be year-gated:

```yaml
strategy:
  recycling_yield:
    start_year: 2020
    value: 0.9
```

Gate behavior: baseline values are used before `start_year`, and `value` is applied from `start_year` onward. This keeps historic years free of scenario overrides.

## Scenario authoring workflow (recommended)

1. Start from one mechanism and one target hypothesis.
2. Use reporting-phase gates by default (`start_year >= report_start_year`).
3. Apply the smallest override set needed to test that mechanism.
4. Run baseline and scenario with identical run config.
5. Validate convergence and mechanism movement before broadening scope.

## Scenario authoring checklist

### 1) Define objective and stress channel

1. State the mechanism to excite (capacity bottlenecks, collection disruptions, reserve policy).
2. Choose the smallest set of shocks/parameters needed to isolate that mechanism.

### 2) Start from canonical schema

Required keys:

- `name`
- `description`
- `implementation` (list)

Optional blocks:

- `sd_parameters`
- `mfa_parameters`
- `strategy`
- `transition_policy`
- `demand_transformation`
- `shocks`
- `dimension_overrides`

Use YAML header contracts in each scenario file as source of truth.

### 3) Respect temporal policy

1. Prefer reporting-phase starts (`start_year >= report_start_year`).
2. Keep historic phase free of scenario behavior unless explicitly intended.
3. For SD keys, use scalar/year-gate/full-timeseries forms consistently.
4. Runtime guardrail: temporal scenario/profile overrides are reporting-phase enforced (pre-report years keep baseline values).
5. Keep acute crisis events as discrete steps (`shocks.*`), but represent structural transitions as ramps.
6. Structural controls that should be ramped in active scenario packs include:
   - `mfa_parameters.collection_rate`, `mfa_parameters.sorting_yield`
   - routing mix (`strategy.recycling_rate`, `strategy.remanufacturing_rate`, `strategy.disposal_rate`)
   - yield/loop closure controls (`strategy.recycling_yield`, `strategy.reman_yield`, `strategy.new_scrap_to_secondary_share`)

### 4) Dimension override discipline

1. Use explicit `materials` and `regions` filters when behavior is slice-specific.
2. Keep override count minimal and ordered intentionally.
3. Avoid overlapping overrides unless precedence is deliberate and documented.

### 5) Shock design checklist

1. Duration and multiplier should be plausible for the tested mechanism.
2. Routing-rate shocks must preserve normalized triad semantics.
3. Demand and supply shocks should not accidentally cancel each other.

### 6) SD parameter design checklist

1. Change only parameters required for the hypothesis.
2. Keep the first pass conservative; escalate stress before gain inflation.
3. Record intended sign and expected direction in `implementation` bullets.

### 7) Validation run

```bash
PYTHONPATH=src python scripts/run_one.py \
  --config configs/runs/mvp.yml \
  --variant <your_variant> \
  --phase reporting \
  --save-csv
```

Minimum checks:

1. `coupling_converged == True` by slice.
2. Key mechanism indicators move in expected direction.
3. No obvious mass-balance or routing anomalies.

### 8) Baseline comparison

1. Compare against `baseline` for changed indicators only.
2. Confirm effect is concentrated in intended slices.
3. Document any spillovers explicitly.

### 9) Regression and catalog updates

1. Update scaffold tests if a new scenario file is added.
2. Update scenario docs for intent and channels.
3. Add changelog entry when scenario meaning or defaults change.

## `sd_parameters` temporal formats

`sd_parameters` and `sd_heterogeneity[*].sd_parameters` support three value forms:

| Form | Example | Behavior |
|---|---|---|
| Scalar | `capacity_expansion_gain: 0.26` | Constant over all modeled years. |
| Year-gated | `capacity_expansion_gain: {start_year: 2025, value: 0.34}` | Uses baseline before `start_year`, then `value` from `start_year` onward. Optional `before` can be provided explicitly. |
| Full timeseries | `coupling_signal_smoothing: [0.50, 0.52, 0.55, ...]` | Applied year-by-year; length must equal modeled year count. |

Rules and precedence:

- Resolution order is `run sd_parameters` -> matching `sd_heterogeneity` rules (in order) -> variant `sd_parameters` -> matching `dimension_overrides[*].sd_parameters` (in order).
- Missing `before` in year-gated values is auto-injected from the active baseline where available.
- Numeric bounds are validated for scalar, year-gated, and full-timeseries values.
- Pair constraints are validated elementwise (`collection_multiplier_min <= collection_multiplier_max`, `capacity_envelope_min <= capacity_envelope_max`).
- Historic-phase SD gates (`start_year < report_start_year`) emit warnings in the current release; enforcement is planned for a later release.
- Legacy SD aliases are no longer accepted (`base_price`, `scarcity_sensitivity`, `price_elasticity`, `service_stress_gain`, `circular_supply_stress_gain`, `scarcity_smooth`).
- Legacy strategy collection controls are no longer accepted; use `sd_parameters.collection_multiplier_{min,max,lag_years}` only.

For interpretation and modeling of the endogenous loop:

- See `docs/model/SD_CAPACITY_SCARCITY_PRICE_LOOP.md`.

`dimension_overrides` entries support:

- `materials`: list filter (optional, defaults to all materials)
- `regions`: list filter (optional, defaults to all regions)
- override blocks (`sd_parameters`, `mfa_parameters`, `strategy`, `shocks`)

Multiple matching `dimension_overrides` are applied in order.

## Useful strategy controls

- `refinery_stockpile_release_rate` (0..1): yearly share of refinery stockpile inventory allowed to re-enter demand fulfillment.
- `new_scrap_to_secondary_share` (0..1): share of fabrication losses routed to the secondary loop (remainder goes to residue/environment boundary).
- SD collection controls (set in `sd_parameters`):
  - `collection_multiplier_min` / `collection_multiplier_max`: lower/upper bounds for collection-rate shock multiplier.
  - `collection_multiplier_lag_years` (>=0): first-order lag (in years) applied to collection-rate shock multiplier.
  - `collection_price_response_gain` (>=0): SD price-response gain for collection multiplier.
- Strategic reserve controls:
  - `strategic_reserve_enabled` (bool, default `false`)
  - `strategic_reserve_target_coverage_years`
  - `strategic_reserve_fill_gain`, `strategic_reserve_release_gain`
  - `strategic_reserve_max_fill_rate`, `strategic_reserve_max_release_rate`
  - `strategic_reserve_fill_price_threshold`, `strategic_reserve_release_price_threshold`
  - `strategic_reserve_fill_service_threshold`, `strategic_reserve_release_service_threshold`

Collection-rate shock implementation is SD-native:
- coupling maps `shocks.collection_rate` into SD shock constants (`collection_shock_start`, `collection_shock_duration`, `collection_shock_multiplier`)
- SD computes the multiplier target as price-pressure response times the shock multiplier
- SD applies bounds and first-order lag (`collection_multiplier_min/max/lag_years`) from `sd_parameters`
- effective dMFA collection rate is `clip(base_collection_rate * SD_collection_multiplier, 0, 1)`

## Supported scenario shock channels

- `demand_surge`
- `recycling_disruption`
- `primary_refined_output`
- `primary_refined_net_imports`
- `extraction_yield`
- `beneficiation_yield`
- `refining_yield`
- `sorting_yield`
- `collection_rate`
- `recycling_rate`
- `remanufacturing_rate`
- `disposal_rate`
- `strategic_fill_intent`
- `strategic_release_intent`

For routing-rate shocks (`recycling_rate`, `remanufacturing_rate`, `disposal_rate`), runtime renormalizes each year so:

`recycling_rate + remanufacturing_rate + disposal_rate = 1`

Remanufacturing routing is additionally constrained by end-use eligibility from
`data/exogenous/remanufacturing_end_use_eligibility.csv` at high-level end-use resolution.

## Current baseline scenario set (`configs/runs/mvp.yml`)

- `baseline`
  - No scenario-specific overrides.
- `demand_surge`
  - Global demand shock with regional severity modulation.
  - Harmonized acute window: 2025-2039.
- `recycling_disruption`
  - Global recycling disruption with explicit regional overrides for `EU27`, `China`, and `RoW`.
  - Harmonized acute window: 2025-2039.
- `combined_shocks`
  - Global demand surge plus targeted material-region supply/circularity stresses.
  - Harmonized acute window: 2025-2039.
- `circularity_push`
  - Profile-driven circularity ramps with global uplift and additional `nickel`/`EU27` targeted routing reinforcement.
- `capacity_crunch_recovery`
  - Explicit crunch-recovery stress test targeting the endogenous capacity-envelope, bottleneck-pressure, and scarcity/price response loop.
- `transition_policy_acceleration`
  - Activates policy-adoption/compliance delay dynamics to strengthen collection/recycling/capacity response while reducing bottleneck amplification.
- `demand_transformation_shift`
  - Activates demand transformation via optional service-activity and material-intensity drivers plus efficiency/rebound controls.
- `import_squeeze_circular_ramp`
  - External primary availability squeeze followed by delayed transition-policy and demand-transformation ramp to test resilience recovery.

## Additional stress scenarios (in `configs/scenarios/mvp/*.yml`)

- `strategic_reserve_build_release`
  - Enables strategic reserve policy.
  - Uses a pre-crisis accumulation window and later crisis drawdown via demand and strategic-intent shocks.

## R-strategies pack (`configs/runs/r-strategies.yml`)

This pack is dMFA-first and maps scenarios to grouped R-strategies levers.
It uses a 3-level ladder per group plus one cross-group portfolio scenario.
Runtime CSV profile overlay is enabled in `configs/runs/r-strategies.yml`.

- Pack-level baseline adjustment:
  - `strategy.new_scrap_to_secondary_share: 0.85`
  - Rationale: creates explicit headroom for R7-R9 manufacturing-scrap loop closure scenarios.

### R0/R2: Demand + material efficiency
- `r02_demand_efficiency_low`
- `r02_demand_efficiency_medium`
- `r02_demand_efficiency_high`
- Main channels:
  - `demand_transformation` (`service_activity_multiplier`, `material_intensity_multiplier`, `efficiency_improvement`, `rebound_effect`)
  - higher `mfa_parameters.fabrication_yield`

### R3/R6: Lifetime extension + remanufacturing loops
- `r36_lifetime_reman_low`
- `r36_lifetime_reman_medium`
- `r36_lifetime_reman_high`
- Main channels:
  - `strategy.lifetime_multiplier`
  - routing mix (`recycling_rate`, `remanufacturing_rate`, `disposal_rate`) with normalized sums
  - `strategy.reman_yield`

### R7-R9: Collection/sorting/recycling + new scrap loop closure
- `r79_recovery_loops_low`
- `r79_recovery_loops_medium`
- `r79_recovery_loops_high`
- Main channels:
  - `mfa_parameters.collection_rate`
  - `mfa_parameters.sorting_yield`
  - `strategy.recycling_yield`
  - routing mix (`recycling_rate`, `remanufacturing_rate`, `disposal_rate`)
  - `strategy.new_scrap_to_secondary_share`

### Cross-group portfolio
- `r_portfolio_combined`
  - blends medium-to-high ambition settings across R0/R2, R3/R6, and R7-R9.

All R-strategies scenarios use a hybrid regional template with explicit `dimension_overrides` for:
- `EU27` (ambition-up),
- `China` (reference/moderate),
- `RoW` (more conservative transition).

## Reporting profile workflow

CSV profiles are used as exogenous ramp sources and can be consumed in two ways:

1. Key-level `exogenous_ramp` references in scenario YAML (preferred for MVP).
2. Run-level runtime auto-activation via `scenario_profiles` (used in `r-strategies`).

Authoring inputs:

- `data/ramp_profiles/mvp/`
- `data/ramp_profiles/r_strategies/`
- template: `data/ramp_profiles/templates/reporting_timeseries_profile_template.csv`

Manual expansion utility (for review/debug):

```bash
PYTHONPATH=src python scripts/scenarios/build_reporting_timeseries_profiles.py \
  --config configs/runs/mvp.yml \
  --profile data/ramp_profiles/mvp/import_squeeze_circular_ramp.csv
```

Generated payloads are written under:
- `outputs/analysis/scenario_profile_expansions/latest/`

Current usage policy:

- `configs/runs/mvp.yml`: run-level `scenario_profiles` overlay is deprecated/not used; MVP ramps should be declared per key using `exogenous_ramp`.
- `configs/runs/r-strategies.yml`: runtime `scenario_profiles` auto-activation remains enabled for `data/ramp_profiles/r_strategies/*.csv`.

Canonical path policy:

- Active scenario authoring should use `data/ramp_profiles/**`.
- `data/scenario_profiles/**` references are backward-compatible only for one release cycle via runtime path fallback.

## Ramp mechanisms and activation

There are two distinct ways ramps can appear in scenarios.

### Why both exist

Both are intentionally kept because they serve different purposes:

1. Endogenous ramps are mechanism-first:
   - used when timing should emerge from model feedbacks, delays, and saturation behavior.
   - best for policy/adoption interpretation and interaction realism.
2. Exogenous ramps are assumption-first:
   - used when a scenario requires an explicit prescribed trajectory from outside the model.
   - best for reproducibility, transparent scenario governance, and deterministic comparisons.
3. Practical workflow split in this repo:
   - use endogenous ramps for transition/policy behavior channels.
   - use exogenous profile ramps for scenario-scripted temporal paths (especially in `r-strategies`).
   - keep acute disruption pulses as exogenous shocks when abrupt events are the intended narrative.

Allowed discrete steps vs must-ramp controls:

- Keep discrete: acute crisis pulses in `shocks` (for example embargo/disruption windows).
- Ramp instead of step: long-duration structural changes in collection, routing, yields, and loop-closure controls.

### Interpreting ratio jumps (`EoL_RR`, `RIR`)

- Ratio indicators can move sharply even when individual controls are smooth if numerator and denominator channels are both rerouted.
- Diagnose jumps by checking the paired flow components first (`EoL_generated`, `EoL_recycled`, `Secondary_supply`, `Primary_supply`), then control ramps.
- When discontinuities appear around policy start years, inspect whether any structural key still uses a year-gated step instead of a ramp.

### 1) Endogenous transition-policy ramp (runtime, no CSV required)

This ramp is activated when a scenario sets:
- `transition_policy.enabled: true`

Shape controls are:
- `transition_policy.start_year`
- `transition_policy.compliance_delay_years`
- `transition_policy.adoption_lag_years`
- `transition_policy.adoption_target`

At runtime, this creates a smooth adoption trajectory that then modulates selected
MFA/SD/strategy channels (for example collection uplift, recycling-yield uplift,
capacity-expansion gain uplift, and bottleneck relief).

### 2) Exogenous profile ramp (CSV-driven)

Preferred declaration surface (scenario YAML, per-key):

```yaml
mfa_parameters:
  collection_rate:
    exogenous_ramp: data/ramp_profiles/mvp/circularity_push.csv
```

Resolution behavior:

1. Runtime reads the referenced CSV and selects rows by `(variant, block, key)`.
2. Scope precedence is:
   - exact `material+region`
   - `material` only
   - `region` only
   - global (blank material/region)
3. Selected anchors are converted to temporal ramp points and then pass normal reporting-phase clipping/baseline rules.

Run-level auto overlay via `scenario_profiles` is still supported for packs that opt into it (currently `r-strategies`).

### Why some scenarios are defined directly in `.yml`

Scenarios such as `import_squeeze_circular_ramp` are authored directly in scenario
YAML because they combine multiple channels in one variant:
- shocks
- `transition_policy`
- `demand_transformation`
- SD/MFA/strategy overrides
- dimension overrides

The profile CSV for that scenario is optional and mainly used when you want explicit
piecewise time paths for selected parameters beyond simple year-gates.

## Comparison workflow

After running scenario variants, build a standardized comparison package from the latest run of each variant:

```bash
python scripts/analysis/compare_scenarios.py --config <config.yml>
python scripts/analysis/plot_scenario_subset_panels.py --config <config.yml>
```

Outputs are run-scoped (within a single run config) and written by default to
`outputs/analysis/scenario_comparison/<run_config_stem>/latest/`:
- `summary_comparison.csv`
- `delta_vs_baseline.csv`
- `scenario_kpis.csv`
- `plots/subset_panels/*.png` (line-chart grids: rows=indicators, cols=regions, scenario lines)
- `plots/subset_panels/*__matrix_raw.csv` (raw subset matrices by indicator x region-variant)
- `plots/subset_panels/*__matrix_normalized.csv` (row-normalized subset matrices)
- `plots/indicator_panels/<subset>/*.png` (one indicator per panel, material + regional detail)
- `plots/subset_panel_coverage.csv`
- `plots/indicator_panel_coverage.csv`

By default, if a `latest/` package already exists, it is archived before rewriting:
- comparison package archive path: `outputs/analysis/scenario_comparison/<run_config_stem>/archives/<timestamp>/`
- plot package archive path: `outputs/analysis/scenario_comparison/<run_config_stem>/latest/archives/<timestamp>/`

Disable this behavior with `--no-archive-existing` in either script.

Optional end-use detail can be added from a precomputed file (no model run required):

```bash
python scripts/analysis/plot_scenario_subset_panels.py --config <config.yml> \
  --end-use-source outputs/analysis/stock_in_use_by_end_use_region_scenarios/<timestamp>/stock_in_use_by_end_use_region_scenario.csv
```

## Minimum scenario acceptance checks

1. `summary.csv` reports `coupling_converged == True` for all slices.
2. Direction of change matches scenario intent in at least primary target slices.
3. No structural anomalies in diagnostics (`Mass_balance_residual_max_abs`, routing consistency).
