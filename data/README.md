# Data

This repository treats key drivers as **exogenous inputs**.

Rule: **one file per variable** in `data/exogenous/`, typically long format with a `value` column.
Exception: `collection_routing_rates.csv` is a wide table with three explicit rate columns.
The canonical schema (required columns) is defined in `registry/variable_registry.yml`.

The loaders apply light normalization for robustness:

- `material` is lower-cased (`Tin` -> `tin`).
- `region` supports aliases (e.g., `EU-27` -> `EU27`, `Rest of the World` / `ROW` -> `RoW`).


## `data/exogenous/end_use_shares.csv`
Columns:
- `year` (int)
- `material` (str)
- `region` (str)
- `end_use` (str)
- `value` (float): share

One row per `(year, material, region, end_use)`.
The loader normalizes shares within each `(year, material, region)`.

## `data/exogenous/final_demand.csv`
Columns:
- `year` (int)
- `material` (str)
- `region` (str)
- `value` (float): desired demand [t/year]

Interpretation:
- This is **desired** final demand.
- During calibration (years < `report_start_year`) SD demand response is OFF, so realized demand follows this series.
- During reporting, SD may reduce realized demand through price elasticity.

## `data/exogenous/service_activity.csv` (optional)
Columns:
- `year` (int)
- `material` (str)
- `region` (str)
- `value` (float): service-activity index

Interpretation:
- Optional driver for demand-transformation decomposition.
- Recommended normalization convention is first modeled year = `1.0`.

## `data/exogenous/material_intensity.csv` (optional)
Columns:
- `year` (int)
- `material` (str)
- `region` (str)
- `value` (float): material-intensity index per unit service

Interpretation:
- Optional driver for demand-transformation decomposition.
- Values below `1` represent dematerialization efficiency trends.
- Recommended normalization convention is first modeled year = `1.0`.

## `data/exogenous/primary_refined_output.csv`
Columns:
- `year` (int)
- `material` (str)
- `region` (str)
- `value` (float): domestic primary refined output [t/year]

Interpretation (CONFIRMED):
- This represents **domestic primary refined metal output** (metal content) within the region.
- It is combined with primary refined net imports to estimate primary metal availability to refining.

## `data/exogenous/primary_refined_net_imports.csv`
Columns:
- `year` (int)
- `material` (str)
- `region` (str)
- `value` (float): net imports of primary refined metal [t/year]

Interpretation:
- Positive values increase primary metal available to refining.
- Negative values are allowed (net exporter).
- The model uses:
  `primary_available_to_refining(t, region) = max(0, primary_refined_output(t, region) + primary_refined_net_imports(t, region))`.

## `data/exogenous/stage_yields_losses.csv`
Columns:
- `year` (int)
- `material` (str)
- `region` (str)
- `extraction_yield` (float, [0,1])
- `beneficiation_yield` (float, [0,1])
- `refining_yield` (float, [0,1])
- `sorting_yield` (float, [0,1])
- `extraction_loss_to_sysenv_share` (float, [0,1])
- `beneficiation_loss_to_sysenv_share` (float, [0,1])
- `refining_loss_to_sysenv_share` (float, [0,1])
- `sorting_reject_to_disposal_share` (float, [0,1])
- `sorting_reject_to_sysenv_share` (float, [0,1])

Constraints:
- `sorting_reject_to_disposal_share + sorting_reject_to_sysenv_share = 1` per `(year, material, region)`.

Interpretation:
- Explicit stage-conversion and loss-routing assumptions for primary extraction, beneficiation, refining, and sorting.
- Stage-throughput reconstruction is refining-anchored and uses these yields directly.

## `data/exogenous/stage_yields_losses_v2.csv` (optional, opt-in)
Columns: identical to `stage_yields_losses.csv`.

Interpretation:
- Candidate fitted stage-yield dataset produced by `scripts/calibration/fit_stage_yields_losses.py`.
- Intended for controlled A/B comparison through `configs/runs/mvp-stagefit-v2.yml`.
- Does not replace canonical defaults unless explicitly promoted.

## Upstream observed diagnostics inputs

### `data/exogenous/primary_refined_observed.csv`
Columns:
- `year`, `material`, `region`, `value`

Used for diagnostics fit against modeled `Primary_supply`.

### `data/exogenous/beneficiation_output_observed.csv`
Columns:
- `year`, `material`, `region`, `value`

Used for diagnostics fit against modeled beneficiation-output proxy:
- `Primary_supply / refining_yield`.

### `data/exogenous/primary_extraction_observed.csv`
Columns:
- `year`, `material`, `region`, `value`

Used for diagnostics fit against modeled extraction-output proxy:
- `Primary_supply / (refining_yield * beneficiation_yield)`.

## `data/exogenous/collection_routing_rates.csv`
Columns:
- `year` (int)
- `material` (str)
- `region` (str)
- `recycling_rate` (float): share in [0,1]
- `remanufacturing_rate` (float): share in [0,1]
- `disposal_rate` (float): share in [0,1]

Routing constraint:
- For every `(year, material, region)`:
  `recycling_rate + remanufacturing_rate + disposal_rate = 1`.

## `data/exogenous/remanufacturing_end_use_eligibility.csv`
Columns:
- `year` (int)
- `region` (str)
- `end_use` (str)
- `value` (float): eligibility factor in [0,1]

Interpretation:
- This is a high-level end-use gate for remanufacturing.
- Effective reman routing is scaled by this factor at `(t, region, end_use)`.
- The non-eligible share is rerouted to recycling/disposal while preserving their relative split.

## `data/exogenous/lifetime_distributions.csv`
Long format with one row per parameter.

Columns:
- `cohort_year` (int)
- `material` (str)
- `region` (str)
- `end_use` (str)
- `dist` (str): `weibull`, `lognormal`, or `fixed`
- `param` (str): e.g. `mean_years`, `shape`, `scale`, `mu`, `sigma`
- `value` (float)

Interpretation:
- Lifetimes are specified **per cohort year** and converted to an annual retirement PDF by age.
- The circularity strategy *lifetime extension* scales the lifetime distribution:
  - `fixed`: scales `mean_years`
  - `weibull`: scales `scale` (or inferred `scale` from `mean_years` + `shape`)
  - `lognormal`: scales implied mean and standard deviation
- Validation is strict: duplicate rows for the same `(cohort_year, material, region, end_use, dist, param)` fail fast.

How to switch families safely (for example, Weibull -> Lognormal):
- For each `(cohort_year, material, region, end_use)`, keep exactly one `dist` family across all rows.
- If using `lognormal`, use:
  - required: `sigma`
  - plus one of: `mean_years` or `mu`
- Remove Weibull-only parameters (`shape`, `scale`) when `dist=lognormal`.
- A common standardized setup is `dist=lognormal` with `param in {mean_years, sigma}` and a uniform `sigma` value.
- Revalidate after edits:
  - `python scripts/validate_exogenous_inputs.py --config configs/mvp.yml`

## `data/exogenous/stock_in_use.csv` (optional; calibration only)
Columns:
- `year` (int)
- `material` (str)
- `region` (str)
- `end_use` (str)
- `value` (float): observed stock [t]

Used only to compute calibration/validation metrics (e.g., RMSE) in the calibration window.

## Templates

Starter templates for optional demand-transformation inputs are available in:
- `data/exogenous/templates/service_activity_template.csv`
- `data/exogenous/templates/material_intensity_template.csv`

Copy and adapt them to `data/exogenous/service_activity.csv` and
`data/exogenous/material_intensity.csv` when enabling demand transformation.
