# Architecture

This repository couples a **System Dynamics (SD)** demand module (BPTK-Py) with a **dynamic MFA (dMFA)** module (flodym) using a **loose iterative coupling**.

## Related docs

- Entry point: `docs/README.md`
- Quick execution path: `docs/getting-started/QUICKSTART.md`
- Config merge and temporal precedence: `docs/workflows/CONFIG_PRECEDENCE.md`
- Scenario design process: `docs/workflows/SCENARIOS.md#scenario-authoring-checklist`
- Output interpretation: `docs/model/OUTPUTS_GUIDE.md`
- Failure diagnosis: `docs/getting-started/TROUBLESHOOTING.md`
- Canonical terminology: `docs/model/GLOSSARY.md`

## Data and configuration

Single sources of truth:

- Dimensions: `configs/regions.yml`, `configs/materials.yml`, `configs/end_use.yml`
- Time windows: `configs/time.yml`
- Coupling wiring: `configs/coupling.yml`
- Indicator set + parameters: `configs/indicators.yml`
- Assumptions (CONFIRMED vs TEMP): `configs/assumptions.yml`
- Exogenous variable registry (paths + schemas): `registry/variable_registry.yml`
- Coupling variable registry: `src/crm_model/coupling/interface.py`
- Full config contracts: inline `#` interface-contract comments at the top of each YAML file in `configs/` and `registry/variable_registry.yml`

Run-config architecture uses a shared core with thin overlays:

- `configs/runs/_core.yml`: canonical shared includes and default parameter blocks
- `configs/runs/mvp.yml`: overlay for MVP scenario pack

Overlay configs use `extends` plus minimal overrides (typically `includes.scenarios` and profile-specific levers).

No migration feature flags remain in active runtime config.
Lifetime, buffer, and collection dynamics use native framework implementations by design.

Exogenous inputs (one variable per file):

- End-use shares: `data/exogenous/end_use_shares.csv`
- Desired demand: `data/exogenous/final_demand.csv`
- Primary refined output: `data/exogenous/primary_refined_output.csv`
- Primary refined net imports: `data/exogenous/primary_refined_net_imports.csv`
- Stage yields/loss routing: `data/exogenous/stage_yields_losses.csv`
- Collection routing rates:
  - `data/exogenous/collection_routing_rates.csv` (`recycling_rate`, `remanufacturing_rate`, `disposal_rate`)
- Remanufacturing end-use eligibility:
  - `data/exogenous/remanufacturing_end_use_eligibility.csv` (`value` in [0,1] by `year,region,end_use`)
- Lifetime distributions: `data/exogenous/lifetime_distributions.csv`
- Observed stock-in-use (optional; calibration only): `data/exogenous/stock_in_use.csv`

## Coupling logic

Per **material × region**:

1. SD consumes **desired demand** (exogenous) and an effective stress multiplier.
   SD behavioral parameters can vary by material-region via top-level `sd_heterogeneity`
   rules in the run config.
2. SD outputs realized total demand.
3. Demand is split into end-uses using exogenous shares.
4. dMFA consumes end-use demand, lifetimes, and circularity strategy parameters.
   Primary available to refining is computed exogenously as
   `max(0, primary_refined_output + primary_refined_net_imports)`.
   Upstream throughput is reconstructed with explicit yields at extraction/beneficiation/refining,
   and sorting rejects are routed by configured shares to disposal/sysenv.
   Secondary material (recovered old scrap plus routed new scrap) accumulates in a refinery stockpile
   (`refinery_stockpile_native`) and is released with `refinery_stockpile_release_rate`.
   A separate strategic reserve stock (`strategic_inventory_native`) is held at refining and controlled
   by SD fill/release intents; strategic fill competes with current-year supply and strategic release
   supports demand fulfillment under stress.
   New scrap routing is explicitly controlled by `new_scrap_to_secondary_share`.
   Collection-rate control is BPTK-native and price-linked with bounded lag
   (`sd_parameters.collection_price_response_gain`, `sd_parameters.collection_multiplier_min/max/lag_years`).
   SD also models a lagged capacity envelope and bottleneck pressure loop
   (`capacity_envelope -> bottleneck_pressure -> scarcity/price -> capacity_target`).
   Remaining stockpile in the final simulated year is terminal inventory.
5. dMFA outputs delivered vs unmet service.
6. Coupling computes two feedback signals from dMFA:
   - `service_stress_t = unmet_service / service_demand`
   - `circular_supply_stress_t = 1 - secondary_supply / (primary_supply + secondary_supply)`
   - `strategic_stock_coverage_years_t = strategic_inventory_stock / service_demand`
   In `feedback_signal_mode: time_series`, yearly signals are smoothed iteratively and fed back
   as a time-varying SD scarcity multiplier (service/circular channels) and strategic stock
   coverage signal (strategic reserve channel), optionally only on reporting years.
   In `feedback_signal_mode: scalar_mean`, reporting-window means are used as a scalar fallback.
   Steps 1–6 repeat until convergence or `max_iter`.

The coupling is **iterative within a run**, not a fully co-simulated year-by-year integration.

## Operational run order

1. Validate config and exogenous inputs.
2. Run baseline reporting phase.
3. Run target scenarios.
4. Check convergence and mechanism diagnostics.
5. Build scenario comparison package.

Commands are documented in `docs/getting-started/QUICKSTART.md`.

Canonical flowchart:

- `docs/model/COUPLED_MODEL_FLOWCHART.md` (Mermaid, with exogenous vs endogenous boundaries)
- `docs/model/SD_CAPACITY_SCARCITY_PRICE_LOOP.md` (interpretation + modeling guide for the endogenous capacity/scarcity/price/bottleneck dynamic)

## Outputs

With `--save-csv`, each run writes artifacts to:

`outputs/runs/<config_stem>/<variant>/<timestamp>/`

including:
- `run_metadata.yml`
- `assumptions_used.yml`
- `indicators/timeseries.csv` (time series)
- `indicators/scalar_metrics.csv` (scalar resilience metrics)
- `indicators/coupling_signals_iteration_year.csv` (per-iteration, per-year coupling trace)
- `indicators/coupling_convergence_iteration.csv` (per-iteration convergence diagnostics)
- `summary.csv`

Supporting output folders:
- `outputs/runs/calibration/` (calibration optimization artifacts)
- `outputs/runs/calibration/cycle/` (baseline promotion/restore snapshots)
- `outputs/analysis/` (derived comparisons and figures)
- `outputs/archives/` (archived older artifacts)
