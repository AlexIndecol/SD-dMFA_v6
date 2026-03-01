# Config Precedence and Temporal Resolution

This document defines how configuration layers are merged and how temporal values are resolved.

## 1) Run inheritance (`extends`)

1. Parent run config is loaded first (for example `configs/runs/_core.yml`).
2. Child overlay applies on top (for example `configs/runs/mvp.yml`).
3. Child keys replace/merge parent keys by path.

## 2) Variant source precedence

For a selected variant name:

1. File-based variants from `includes.scenarios` are loaded.
2. Inline `variants:` entries in run config override same-name file variants.

## 3) Parameter precedence within a selected slice

For each `material x region`:

1. Top-level run `sd_parameters`
2. Matching `sd_heterogeneity` rules (in declared order)
3. Variant `sd_parameters`
4. Matching variant `dimension_overrides[*].sd_parameters` (in declared order)

Equivalent precedence applies for `mfa_parameters`, `strategy`, and `shocks`.

## 4) Temporal value forms for `sd_parameters`

Supported for all temporal-capable SD keys:

1. Scalar
```yaml
capacity_expansion_gain: 0.26
```
2. Year-gated
```yaml
capacity_expansion_gain:
  start_year: 2025
  value: 0.34
  before: 0.26
```
3. Full timeseries
```yaml
capacity_expansion_gain: [0.26, 0.26, 0.27, 0.28]
```

Rules:

1. Full timeseries length must equal modeled year count.
2. Missing year-gate `before` is auto-injected from current baseline when available.
3. Bounds and pair constraints are checked on expanded yearly values.

## 5) Historic-phase policy

Current behavior:

- SD year-gates with `start_year < report_start_year` emit warnings.

Recommended policy:

- keep SD and strategy scenario overrides reporting-phase only;
- avoid historic-phase behavioral overrides unless explicitly intended for reconstruction experiments.

## 6) Deprecated keys (hard fail)

These are no longer accepted:

1. SD aliases: `base_price`, `scarcity_sensitivity`, `price_elasticity`, `service_stress_gain`, `circular_supply_stress_gain`, `scarcity_smooth`.
2. Strategy collection controls: `strategy.collection_multiplier_min`, `strategy.collection_multiplier_max`, `strategy.collection_multiplier_lag_years`.

Use canonical `sd_parameters` keys instead.

## 7) Where to find interface contracts

Authoritative contract comments are embedded in YAML headers:

- `configs/**/*.yml`
- `registry/variable_registry.yml`
