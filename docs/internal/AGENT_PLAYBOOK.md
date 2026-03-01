# Agent Playbook

Operational contract for this repo. Priorities: runnable, explicit, reproducible.

## 1) Hard Rules

### 1.1 High-impact assumptions: ask first
Ask before deciding anything that can materially affect results (units, boundaries, mappings, lifetimes, calibration targets, scenario semantics, trade interpretation).

If a placeholder is required to keep execution alive, it must be:
- declared under `TEMP` in `configs/assumptions.yml`
- documented in `docs/governance/ASSUMPTIONS.md` (impact + removal path)
- exported in run artifacts (`assumptions_used.yml`)

### 1.2 Stop-the-run validation
Before any run:
- run `python scripts/validation/validate_exogenous_inputs.py --config <config.yml>`
- run `python scripts/validation/lint_run_configs.py` when run-config structure changes
- treat these as schema authorities:
  - `registry/variable_registry.yml`
  - `configs/regions.yml`
  - `configs/materials.yml`
  - `configs/end_use.yml`
  - `configs/time.yml`

Alias normalization is allowed (`EU-27` -> `EU27`, `ROW` -> `RoW`), but unknown codes must still warn/fail.

### 1.3 Config over code
Change behavior in:
- `configs/*.yml`
- `registry/variable_registry.yml`
- `data/exogenous/*.csv`
- docs

Do not hardcode dimensions, horizon, coupling behavior, or indicator names.

### 1.4 Native-framework-first (prominent rule)
Prefer framework-native implementations first:
- `flodym`: stocks/flows/lifetimes/mass balance
- `BPTK-Py`: SD stocks/equations/delays/smoothing/scenarios

Custom code is acceptable only if native options are insufficient or clearly reduce clarity.

If custom code is used, record rationale in:
- `docs/governance/DECISION_LOG.md`
- `docs/governance/RISKS.md`
- `docs/governance/CHANGELOG.md`

### 1.5 Periodic native-framework sweep
Run at least:
- once per sprint/milestone
- before structural rewrites

Each sweep must list:
- custom candidates
- native alternatives
- priority (`quick win` / `safe structural` / `behavior-changing`)
- decision (`migrate now` / `defer` + reason)

## 2) Sources Of Truth

- exogenous inputs: `data/exogenous/<variable>.csv`
- variable schema: `registry/variable_registry.yml`
- dimensions: `configs/regions.yml`, `configs/materials.yml`, `configs/end_use.yml`
- time: `configs/time.yml`
- dMFA graph: `configs/stages.yml`
- coupling wiring: `configs/coupling.yml`
- indicators: `configs/indicators.yml`
- assumptions: `configs/assumptions.yml`
- reserved mapping: `configs/end_use_detail_mapping.yml`

Run configs should follow core+overlay structure:
- shared core in `configs/runs/_core.yml`
- overlays in `configs/runs/*.yml` using `extends`

Canonical include key is `includes.end_uses`.
`includes.applications` and `includes.end_use` are compatibility aliases only and should not be used in newly edited configs.

## 3) Run Completion Contract

A run is complete only if validation passed, assumptions were exported, and standard outputs exist.

`--save-csv` target:
- `outputs/runs/<config_stem>/<variant>/<timestamp>/`

Required artifacts:
- `run_metadata.yml`
- `assumptions_used.yml`
- `summary.csv`
- `indicators/timeseries.csv`
- `indicators/scalar_metrics.csv`
- `indicators/coupling_signals_iteration_year.csv`
- `indicators/coupling_convergence_iteration.csv`

## 4) Model Invariants

- calibration years (`< report_start_year`): SD demand response OFF
- reporting years (`>= report_start_year`): SD demand response may be ON
- coupling remains loose iterative (no year-step co-simulation unless explicitly redesigned and logged)

## 5) Standard Workflows

### 5.1 Dimensions/time change
1. Update `configs/regions.yml`, `configs/materials.yml`, `configs/end_use.yml` and/or `configs/time.yml`.
2. Keep canonical symbols consistent: `t` (time), `r` (region), `m` (material), `e` (end_use), `ed` (end_use_detailed), `p` (stage), `q` (quality); optional OD-trade placeholders: `c` (commodity), `o` (origin region), `d` (destination region).
3. Update affected exogenous CSVs + registry entries.
4. Run validator.
5. Update `DECISION_LOG`, `ASSUMPTIONS`, `RISKS`, `CHANGELOG`.

### 5.2 dMFA graph change
1. Edit `configs/stages.yml`.
2. Keep required process roles unique/present.
3. Preserve flow dimensionality expected by `compute()`:
   - `environment -> primary_extraction -> beneficiation_concentration -> refining -> fabrication_and_manufacturing -> use`: `[t, r, e]`
   - `use -> collection -> sorting_preprocessing -> recycling_refining_secondary -> refining`: `[t, r, e]`
   - `collection -> remanufacturing` and `remanufacturing -> use`: `[t, r, e]`
   - `collection -> residue_treatment_disposal -> environment`: `[t, r, e]`
4. Keep native stock declarations explicit and present in `configs/stages.yml`:
   - `stock_in_use`
   - `refinery_stockpile_native`
5. Run validator + smoke run.
6. Update `DECISION_LOG`, `RISKS`, `COUPLED_MODEL_FLOWCHART`, `CHANGELOG`.

### 5.3 Coupling boundary change (SD <-> dMFA)
1. Update relevant files:
   - `configs/coupling.yml`
   - `src/crm_model/coupling/runner.py`
   - `src/crm_model/sd/builder.py`
   - `src/crm_model/mfa/builder.py`
   - `registry/variable_registry.yml`
2. Update `docs/model/COUPLED_MODEL_FLOWCHART.md`.
3. Run:
   - `python scripts/validation/validate_exogenous_inputs.py --config <config.yml>`
   - `python -m crm_model.cli --config <config.yml> --variant baseline --phase reporting`
4. Update `DECISION_LOG` and `CHANGELOG`.

### 5.4 New exogenous variable
1. Add registry entry (`path`, `required`, `columns`, `unit`, constraints).
2. Add `data/exogenous/<variable>.csv` (long format).
3. Update loader (`src/crm_model/data/io.py`) if needed.
4. Update validator (`src/crm_model/data/validate.py`) if needed.

### 5.5 New indicator
1. Implement in `src/crm_model/indicators/`.
2. Register in `configs/indicators.yml`.
3. Ensure export in standard artifacts.

### 5.6 Calibration cycle
1. `python scripts/calibration/calibrate_model.py --config <config.yml> --calibration-spec configs/calibration.yml`
2. `python scripts/calibration/calibration_cycle.py promote --config <config.yml> --patch <best_config_patch.yml>`
3. Re-run baseline reporting.
4. Optional rollback: `python scripts/calibration/calibration_cycle.py restore --config <config.yml> --snapshot <baseline_before.yml>`

### 5.7 Scenario implementation
Each variant in `<config.yml>` should include:
- `description`
- `implementation`
- optional global overrides (`strategy`, `shocks`, `mfa_parameters`, `sd_parameters`)
- optional `dimension_overrides` (`materials`, `regions`)

Supported shock channels:
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

Routing invariant:
- `recycling_rate + remanufacturing_rate + disposal_rate = 1`

Strategy controls:
- `refinery_stockpile_release_rate`
- `new_scrap_to_secondary_share`

SD controls (in `sd_parameters`):
- `collection_multiplier_min`
- `collection_multiplier_max`
- `collection_multiplier_lag_years`

## 6) Hygiene

- never rely silently on `TEMP` defaults
- if dimensions/variables/schema/units/indicators change: update validators, docs/templates, and `CHANGELOG`
- never commit caches/build artifacts (`__pycache__`, `*.pyc`, `dist/`, `build/`, `.venv/`)
- prefer explicit failures over silent fallbacks
- keep tests runnable (`pytest`)
