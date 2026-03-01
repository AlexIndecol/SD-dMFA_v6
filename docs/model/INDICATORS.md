# Indicators

This file documents indicator meanings, formulas, and grouping conventions.
The canonical indicator configuration is `configs/indicators.yml`.

## Output files

- `outputs/.../indicators/timeseries.csv`
- `outputs/.../indicators/scalar_metrics.csv`
- `outputs/.../indicators/coupling_signals_iteration_year.csv`
- `outputs/.../indicators/coupling_convergence_iteration.csv`

`timeseries.csv` is recorded per `phase, variant, material, region, year, indicator, value`.
Within each material-region slice, values are aggregated over end uses unless indicator names explicitly refer to routing/flows already defined that way.

## Logical subsets

The following subsets are configured under:

- `configs/indicators.yml > mfa_state_and_flow_metrics > logical_subsets`
- `configs/indicators.yml > resilience_service_indicators > logical_subsets`

They are provided to ease plotting and dashboard grouping:

- `stocks_and_use_phase`: `Stock_in_use`, `Inflow_to_use_*`, `Outflow_from_use`
- `primary_secondary_supply`: primary/secondary availability plus refinery and strategic inventory stock-flow channels and upstream stage losses (`Extraction_losses`, `Beneficiation_losses`, `Refining_losses`)
- `eol_and_routing`: EoL generation/collection/routing plus old-scrap routing and sorting rejects
- `losses_surplus_and_stockpile`: fabrication/new-scrap losses, recycling/reman process losses/surplus, and strategic intent controls
- `circularity_ratios`: `EoL_RR`, `RIR`
- `service_outcomes`: `Service_demand`, `Delivered_service`, `Unmet_service`, `Service_level`, `Service_deficit`
- `coupling_signals`: `Coupling_service_stress`, `Coupling_circular_supply_stress`, `Coupling_strategic_stock_coverage_signal`, `Coupling_stress_multiplier`, `Coupling_collection_multiplier`, `SD_scarcity_multiplier_effective`, `SD_capacity_envelope`, `SD_flow_utilization`, `SD_bottleneck_pressure`, `SD_collection_bottleneck_throttle`
- `resilience_scalars`: `Resilience_triangle_area`, `Years_below_service_threshold`, `Max_consecutive_years_below_threshold`
- `diagnostics`: `Mass_balance_residual_max_abs`

Validation policy:

- Subset names must be unique across indicator groups.
- Within each group, `logical_subsets` is a strict partition: every declared indicator appears in exactly one subset.


## Definitions: `resilience_service_indicators`

Time-series indicators:

- `Service_demand`
  - Definition: desired service demand aggregated across end uses for the slice `(material, region, year)`.
  - Formula: exogenous/SD-driven demand input to dMFA for each year.
- `Delivered_service`
  - Definition: service actually delivered by the coupled SD-dMFA system.
  - Formula: modeled fulfilled service flow from dMFA use inflows.
- `Unmet_service`
  - Definition: non-negative service shortfall.
  - Formula: `max(Service_demand - Delivered_service, 0)`.
- `Service_level`
  - Definition: fraction of demand that is delivered.
  - Formula: `clip(Delivered_service / Service_demand, 0, 1)`, with zero-demand years treated as `1.0`.
- `Service_deficit`
  - Definition: shortfall from baseline service level.
  - Formula: `max(1 - Service_level, 0)` (baseline `= 1.0`).
- `Coupling_service_stress`
  - Definition: coupling feedback signal for service pressure.
  - Formula: `Unmet_service / Service_demand` (with denominator protection).
- `Coupling_circular_supply_stress`
  - Definition: coupling feedback signal for circular-supply weakness.
  - Formula: `1 - Secondary_supply / (Primary_supply + Secondary_supply)` (with denominator protection).
- `Coupling_stress_multiplier`
  - Definition: effective SD multiplier after combining both coupling signals.
  - Formula: `1 + coupling_service_stress_gain * service_stress_signal + coupling_circular_supply_stress_gain * circular_supply_stress_signal`.
  - Note: this series is reported as the converged (final-iteration) value across years.
- `Coupling_strategic_stock_coverage_signal`
  - Definition: converged strategic reserve coverage signal used by SD reserve policy equations.
  - Formula: smoothed `strategic_inventory_stock / service_demand`.
- `Coupling_collection_multiplier`
  - Definition: converged collection multiplier applied to base collection rate.
  - Formula:
    `clip_lag((1 + collection_price_response_gain * max(price_ratio - 1, 0)) * collection_bottleneck_throttle)`.
- `SD_capacity_envelope`
  - Definition: SD capacity envelope index used to represent delayed expansion/retirement.
- `SD_flow_utilization`
  - Definition: desired-demand pressure against available capacity envelope.
- `SD_bottleneck_pressure`
  - Definition: non-negative bottleneck pressure `max(flow_utilization - 1, 0)`.
- `SD_collection_bottleneck_throttle`
  - Definition: bottleneck throttle applied to collection multiplier target.
- `SD_scarcity_multiplier_effective`
  - Definition: scarcity multiplier after bottleneck amplification.

Additional MFA routing metric:

- `Collection_rate_effective`
  - Definition: realized collection fraction of generated end-of-life flow.
  - Formula: `EoL_collected / EoL_generated` (zero-denominator protected).

Scalar resilience indicators (computed over reporting window):

- `Resilience_triangle_area`
  - Definition: cumulative service-level shortfall over time.
  - Formula: `sum(max(1 - Service_level, 0))`.
  - Interpretation: larger values mean deeper/longer performance loss.
- `Years_below_service_threshold`
  - Definition: number of reporting years with insufficient service level.
  - Formula: `count(Service_level < threshold_service_level)`.
- `Max_consecutive_years_below_threshold`
  - Definition: longest uninterrupted run of years below threshold.
  - Formula: `max_run_length(Service_level < threshold_service_level)`.

Threshold parameter:

- `threshold_service_level` is configured in `configs/indicators.yml > service_risk`.

Implementation notes:

- Ratios are protected against zero denominators in runtime code (`fillna(0)` behavior where relevant).
- `Coupling_stress_multiplier` in `timeseries.csv` is the final effective multiplier from the converged coupling iteration.
- Detailed by-iteration/by-year signal diagnostics are in `coupling_signals_iteration_year.csv`.
- Iteration-level convergence diagnostics are in `coupling_convergence_iteration.csv`.

Coupling diagnostics interpretation:

- `*_signal_prev` is the signal state used at the start of an iteration.
- `*_signal_target` is the current-iteration evaluated value from dMFA outputs.
- `*_signal_next` is the lagged/smoothed updated signal state after applying coupling smoothing.
- `*_residual_lag = *_signal_target - *_signal_next` quantifies remaining lag after update.
- `max_signal_delta` is the convergence norm used for stopping (`< coupling_tolerance`).
- `collection_multiplier_*` fields show endogenous collection control dynamics:
  - `prev/target/next` are pre-update, desired, and lagged-applied multipliers.
  - `collection_rate_effective` is the applied collection rate for that iteration/year.

## Interpretation notes

- Positive final-year `Refinery_stockpile_stock` is terminal inventory (not losses).
- Positive final-year `Strategic_inventory_stock` is terminal strategic reserve inventory (not losses).
- `Mass_balance_residual_max_abs` should remain close to zero and within configured tolerance.
- Resilience scalar metrics are computed over the reporting window using `service_risk.threshold_service_level` from `configs/indicators.yml`.
