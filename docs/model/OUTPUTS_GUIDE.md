# Outputs Guide

This guide explains run output locations and how to interpret key artifacts.

## 1) Run output directory layout

Single run outputs:

`outputs/runs/<config_stem>/<variant>/<timestamp>/`

Core files:

1. `run_metadata.yml`: resolved config and runtime metadata.
2. `assumptions_used.yml`: assumption snapshot for reproducibility.
3. `summary.csv`: per-slice summary diagnostics and final metrics.
4. `indicators/timeseries.csv`: long-form yearly indicators.
5. `indicators/scalar_metrics.csv`: reporting-window scalar resilience metrics.
6. `indicators/coupling_signals_iteration_year.csv`: by-iteration coupling traces.
7. `indicators/coupling_convergence_iteration.csv`: iteration convergence summary.

## 2) First files to inspect after a run

1. `summary.csv` for convergence and headline behavior.
2. `indicators/coupling_convergence_iteration.csv` for numerical stability.
3. `indicators/timeseries.csv` for mechanism-level trajectories.

## 3) Key summary fields for SD capacity/scarcity loop

1. `final_bottleneck_pressure_mean`
2. `final_capacity_envelope_mean`
3. `final_stress_multiplier`
4. `final_collection_rate_mean`
5. `final_service_stress_signal`

## 4) Coupling diagnostics interpretation

`coupling_signals_iteration_year.csv` fields:

1. `*_signal_prev`: signal entering current iteration.
2. `*_signal_target`: value implied by current dMFA outputs.
3. `*_signal_next`: smoothed update used for next iteration.
4. `*_residual_lag`: remaining lag after update.

`coupling_convergence_iteration.csv` field:

1. `max_signal_delta`: stopping norm compared with `convergence_tol`.

## 5) Analysis package outputs

Scenario comparison outputs:

`outputs/analysis/scenario_comparison/<run_config_stem>/latest/`

Typical artifacts:

1. `summary_comparison.csv`
2. `delta_vs_baseline.csv`
3. `scenario_kpis.csv`
4. `plots/subset_panels/*.png`

## 6) Calibration outputs

Calibration runs write under:

- `outputs/runs/calibration/`
- `outputs/runs/calibration/cycle/`

Use these for optimizer traces, patch promotion, and rollback snapshots.

## 7) Archive behavior

Comparison scripts archive pre-existing `latest/` packages by default. Use
`--no-archive-existing` to disable.

## 8) Troubleshooting quick checks

| Symptom | Likely cause | First checks |
|---|---|---|
| `EoL_RR` jump around 2025 | Structural routing/yield control still stepped or mismatched numerator/denominator reroute | Inspect scenario controls for `start_year` steps on structural keys; compare `EoL_generated` vs `EoL_recycled` time series |
| `Collection_rate_effective` saturates near 1.0 too early | Combined pressure from base collection level + SD multiplier cap/lag settings | Check `Coupling_collection_multiplier`, `collection_multiplier_max`, `collection_price_response_gain`, `collection_multiplier_lag_years` |
| `Strategic_release_intent` active but no strategic inventory outflow | Reserve fill gating too strict, so stock never accumulates pre-crisis | Check `Strategic_inventory_stock`, `Strategic_inventory_inflow`, fill thresholds (`strategic_reserve_fill_*`) and pre-crisis fill intent window |
