# Config Interfaces

This file is the canonical source of truth for config interface contracts in this repository.

Use this file to understand:
- what each config type must contain,
- how configs are merged,
- how temporal values are interpreted,
- how to add new scenarios and exogenous variables safely.

YAML comments inside `configs/**/*.yml` and `registry/variable_registry.yml` are editing aids only.
They are intentionally short and local.

## Document position

- You are here: Tier 2 canonical workflow contract reference.
- Canonical scope: config interfaces, merge/precedence semantics, and temporal value contract rules.
- Out of scope: model equation derivations and scenario rationale narratives.
- Related docs: [SCENARIOS.md](./SCENARIOS.md), [ARCHITECTURE.md](../model/ARCHITECTURE.md), [VARIABLES_AND_PARAMETERS.md](../model/VARIABLES_AND_PARAMETERS.md), [MODEL_GOVERNANCE.md](../governance/MODEL_GOVERNANCE.md)

## 1) Scope

### What this file covers
- run core and run overlays,
- scenarios and variants,
- temporal value forms,
- merge and precedence rules,
- variable registry interface,
- authoring workflow and validation.

### What this file does not cover
- model equations in detail,
- indicator interpretation details,
- scenario narrative design.

For those, use:
- `docs/model/ARCHITECTURE.md`
- `docs/model/INDICATORS.md`
- `docs/workflows/SCENARIOS.md`

## 2) Config architecture

### Main config families

1. Run profiles
- `configs/runs/_core.yml`: shared canonical baseline.
- `configs/runs/*.yml`: thin overlays using `extends`.

2. Scenario files
- `configs/scenarios/**/*.yml`: variants loaded via `includes.scenarios`.

3. Split config blocks
- `configs/time.yml`
- `configs/regions.yml`
- `configs/materials.yml`
- `configs/end_use.yml`
- `configs/end_use_detail.yml`
- `configs/stages.yml`
- `configs/qualities.yml`
- `configs/trade.yml`
- `configs/coupling.yml`
- `configs/indicators.yml`
- `configs/calibration_stock.yml`
- `configs/calibration_trade.yml`

4. Exogenous variable registry
- `registry/variable_registry.yml`

### Runtime loading pattern

1. Loader reads a selected run profile.
2. If `extends` exists, parent is loaded first.
3. `includes.*` files are loaded.
4. Scenario files from `includes.scenarios` are loaded.
5. Inline `variants:` in run config are merged on top of same-name file variants.

## 3) Core run interface contract (`configs/runs/_core.yml`)

### Required top-level keys

- `name`
- `includes`
- `sd_parameters`
- `mfa_parameters`
- `strategy`
- `transition_policy`
- `demand_transformation`
- `shocks`
- `variants`

### Optional top-level keys

- `sd_heterogeneity`
- `scenario_profiles`

### Includes contract

Expected keys in `includes`:
- required in practice: `time`, `regions`, `materials`, `end_uses`, `stages`, `qualities`, `coupling`, `indicators`, `variables`
- optional by run: `trade`, `trade_od`, `scenarios`

### Minimal valid core example

```yaml
name: "Example core"

includes:
  time: ../time.yml
  regions: ../regions.yml
  materials: ../materials.yml
  end_uses: ../end_use.yml
  stages: ../stages.yml
  qualities: ../qualities.yml
  coupling: ../coupling.yml
  indicators: ../indicators.yml
  variables: ../../registry/variable_registry.yml

sd_parameters:
  price_base: 1.0

mfa_parameters:
  collection_rate: 0.6

strategy:
  refinery_stockpile_release_rate: 0.2

transition_policy:
  enabled: false

demand_transformation:
  enabled: false

shocks:
  demand_surge: null

variants:
  baseline:
    description: Baseline reference
    implementation:
      - Uses inherited baseline parameters.
```

### Common mistakes

- Missing `variants.baseline`.
- Using deprecated include aliases (`applications` / `end_use`) instead of `end_uses`.
- Moving scenario-specific behavior into core defaults.
- Overwriting broad blocks in overlays when only one key needs override.

## 4) Overlay interface contract (`configs/runs/*.yml`)

### Purpose
A run overlay should be thin. It should mostly select scenarios and tweak a small set of defaults.

### Required keys

- `name`
- `extends`

### Typical override surfaces

- `includes.scenarios`
- `includes.trade_od`
- `sd_parameters`
- `mfa_parameters`
- `strategy`
- `transition_policy`
- `demand_transformation`
- `shocks`
- `sd_heterogeneity`
- `variants`
- `scenario_profiles`

### Minimal overlay example

```yaml
name: "Example overlay"
extends: ./_core.yml

includes:
  scenarios: ../scenarios/mvp/*.yml

strategy:
  refinery_stockpile_release_rate: 0.15
```

### `extends` behavior

- Parent is loaded first.
- Child keys merge over parent keys.
- Cycles in `extends` are invalid and fail fast.

## 5) Variant interface contract (`configs/scenarios/**/*.yml`)

### Required fields

- `name`: scenario id used by `--variant`.
- `description`: short scenario intent.
- `implementation`: ordered list that explains mechanism design.

### Optional override blocks

- `sd_parameters`
- `mfa_parameters`
- `strategy`
- `transition_policy`
- `demand_transformation`
- `shocks`
- `dimension_overrides`

### `dimension_overrides` item schema

Each item may contain:
- `name` (recommended)
- `materials` (optional filter list)
- `regions` (optional filter list)
- any override block listed above

If `materials` or `regions` are omitted, that item matches all values in that dimension.

Multiple matching items are applied in file order.

### Global variant example

```yaml
name: demand_surge
description: Global demand pressure scenario.
implementation:
  - Adds a reporting-window demand shock.

shocks:
  demand_surge:
    start_year: 2025
    duration_years: 15
    multiplier: 1.35
```

### Slice-targeted override example

```yaml
name: combined_shocks
description: Global stress plus targeted slice pressure.
implementation:
  - Applies a global demand surge.
  - Adds deeper stress to nickel in EU27.

shocks:
  demand_surge:
    start_year: 2025
    duration_years: 15
    multiplier: 1.45

dimension_overrides:
  - name: nickel_eu27_deeper_stress
    materials: [nickel]
    regions: [EU27]
    shocks:
      recycling_disruption:
        start_year: 2025
        duration_years: 15
        multiplier: 0.30
```

## 6) Temporal interface contract

Temporal-capable keys accept four forms.

### Form A: scalar
Use a constant value for all modeled years.

```yaml
capacity_expansion_gain: 0.26
```

### Form B: year-gated
Use one value before a year and one value from that year onward.

```yaml
capacity_expansion_gain:
  start_year: 2025
  value: 0.34
  before: 0.26
```

`before` is optional in many runtime paths. If omitted, baseline may be injected.

### Form C: full timeseries
Provide one value per modeled year.

```yaml
coupling_signal_smoothing: [0.50, 0.50, 0.52, 0.55]
```

Length must match the modeled year count.

### Form D: exogenous ramp reference
Reference a profile CSV.

```yaml
collection_rate:
  exogenous_ramp: data/ramp_profiles/mvp/circularity_push.csv
```

Optional selectors can be provided when needed (`variant`, `block`, `key`, `material`, `region`).

### Temporal validation rules

- Timeseries length must equal horizon length.
- Pair constraints are validated elementwise after expansion.
- Bounds are validated after expansion.
- Invalid temporal payloads fail config load.

### Reporting-window behavior

Reporting runs enforce reporting-phase activation:
- scenario temporal overrides are clipped/gated to `report_start_year` by runtime policy,
- pre-report years keep baseline behavior unless explicitly supported for reconstruction workflows.

### Practical examples

#### `sd_parameters`

```yaml
sd_parameters:
  # Scalar
  price_scarcity_sensitivity: 0.55

  # Year-gated
  bottleneck_scarcity_gain:
    start_year: 2025
    value: 0.24

  # Full timeseries
  coupling_signal_smoothing: [0.50, 0.50, 0.52, 0.55]
```

#### `strategy`

```yaml
strategy:
  strategic_reserve_enabled:
    start_year: 2025
    value: true
    before: false

  strategic_reserve_target_coverage_years:
    start_year: 2025
    value: 0.8
```

#### `demand_transformation`

```yaml
demand_transformation:
  enabled:
    start_year: 2020
    value: true
    before: false

  material_intensity_multiplier:
    exogenous_ramp: data/ramp_profiles/mvp/import_squeeze_circular_ramp.csv
```

## 7) Precedence and merge semantics

### A) Run inheritance precedence

1. Parent from `extends`
2. Child overlay values

### B) Scenario source precedence

1. Scenario files from `includes.scenarios`
2. Inline run `variants` with same name override file variants

### C) Slice-level precedence (per material x region)

For `sd_parameters`:
1. run `sd_parameters`
2. matching `sd_heterogeneity` rules (in order)
3. variant `sd_parameters`
4. matching `dimension_overrides[*].sd_parameters` (in order)

Equivalent precedence applies to:
- `mfa_parameters`
- `strategy`
- `transition_policy`
- `demand_transformation`
- `shocks`

### Deprecated keys and fail-fast behavior

The loader hard-fails deprecated keys such as:
- legacy SD aliases (`base_price`, `scarcity_sensitivity`, `price_elasticity`, etc.)
- legacy strategy collection controls under `strategy.collection_multiplier_*`

Use canonical keys under `sd_parameters`.

## 8) Registry interface contract (`registry/variable_registry.yml`)

Each entry has this shape:

```yaml
<variable_id>:
  path: data/exogenous/<file>.csv
  required: true|false
  columns: [ordered, header, list]
  unit: optional_unit
  constraints:
    - optional rules
  notes:
    - optional notes
```

### Required fields

- `path`
- `required`
- `columns`

### Optional fields

- `unit`
- `constraints`
- `notes`

### Registry validation conventions

- `columns` must match CSV headers exactly and in order.
- Keep units explicit where interpretation depends on units.
- Put normalization/sum-to-one rules in `constraints`.

### Concrete examples

Required variable:

```yaml
final_demand:
  path: data/exogenous/final_demand.csv
  required: true
  columns: [year, material, region, value]
  unit: t_per_year
```

Optional variable:

```yaml
service_activity:
  path: data/exogenous/service_activity.csv
  required: false
  columns: [year, material, region, value]
  unit: index
  notes:
    - "Optional demand-transformation driver."
```

Constraint-rich variable:

```yaml
collection_routing_rates:
  path: data/exogenous/collection_routing_rates.csv
  required: true
  columns: [year, material, region, recycling_rate, remanufacturing_rate, disposal_rate]
  unit: share
  constraints:
    - "0 <= recycling_rate, remanufacturing_rate, disposal_rate <= 1"
    - "recycling_rate + remanufacturing_rate + disposal_rate = 1 per (year, material, region)"
```

## 9) Authoring workflow

### A) Build or edit a core run

1. Start from `configs/runs/_core.yml`.
2. Keep it generic and stable.
3. Put reusable defaults here, not scenario-specific behavior.

### B) Build a run overlay

1. Add `extends: ./_core.yml`.
2. Add `includes.scenarios`.
3. Add only small delta overrides.

### C) Add a scenario

1. Create `configs/scenarios/<pack>/<name>.yml`.
2. Add `name`, `description`, `implementation`.
3. Add minimal override set for the hypothesis.
4. Use `dimension_overrides` only for targeted heterogeneity.

### D) Add a registry variable

1. Add entry in `registry/variable_registry.yml`.
2. Add CSV file at declared `path`.
3. Match `columns` exactly.
4. Update loader/validator only if schema logic truly changes.

### E) Validate before commit

Run:

```bash
python scripts/validation/lint_run_configs.py
python scripts/validation/validate_exogenous_inputs.py --config configs/runs/mvp.yml
```

Recommended targeted tests for config interface work:

```bash
pytest tests/test_repo_layout_scaffold.py \
  tests/test_config_io_scenarios.py \
  tests/test_mvp_scenario_consistency_contracts.py \
  tests/test_scenario_dimension_override_contracts.py
```

## 10) Troubleshooting and acceptance checklist

### Common failures

1. `load_run_config` fails on deprecated keys.
- Fix: migrate to canonical keys.

2. Timeseries length mismatch.
- Fix: align vector length with `time.start_year..time.end_year`.

3. Scenario override not applied.
- Fix: check variant name, include pattern, and precedence order.

4. Slice override not applied.
- Fix: verify `materials` and `regions` names exactly match canonical lists.

5. Registry validation fails on columns.
- Fix: reorder CSV headers to match `columns` contract exactly.

### Acceptance checklist

- `CONFIGS.md` is the only contract source.
- YAML comments are short editing aids.
- No config/template contract files remain.
- No active docs link to removed precedence doc.
- Config lint and targeted interface tests pass.

## Quick reference summary

- Canonical config contract source: `docs/workflows/CONFIGS.md`
- Canonical scenario workflow: `docs/workflows/SCENARIOS.md`
- Canonical architecture: `docs/model/ARCHITECTURE.md`
- Exogenous variable schema: `registry/variable_registry.yml`

## 11) Related sections

- [SCENARIOS.md §3](./SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime) for runtime application of variant overrides defined by this contract.
- [VARIABLES_AND_PARAMETERS.md §6](../model/VARIABLES_AND_PARAMETERS.md#6-parameters-list-canonical-control-surfaces) for control-surface taxonomy across config blocks.
- [INDICATORS.md §6](../model/INDICATORS.md#6-scalar-metric-windowing-and-threshold-semantics) for reporting-window implications tied to temporal contracts.
