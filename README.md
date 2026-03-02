# SD–dMFA Coupled Modeling Template (flodym + BPTK-Py)

Starter repository for building a **coupled dynamic Material Flow Analysis (dMFA)** and **System Dynamics (SD)** model to assess how **circularity strategies** affect **criticality** and **resilience/service** indicators.

## What’s implemented

- **dMFA (flodym)**: cohort-based lifetimes (`weibull`/`lognormal`/`fixed`), collection routing (recycling/remanufacturing/disposal), explicit new-scrap vs old-scrap accounting, refinery stockpile dynamics, and refining-anchored primary availability with explicit upstream yields/losses.
- **SD (BPTK-Py)**: demand is driven by an **exogenous desired-demand** series; **demand response is OFF** before the reporting window and can be **ON** during reporting via price elasticity.
- **Coupling**: **loose iterative coupling** with two feedback signals (`service_stress`, `circular_supply_stress`) combined into an effective stress multiplier (SD demand response receives the multiplier; dMFA provides both stress signals).

## Locked project choices

- Materials: **tin, zinc, nickel**
- Regions: **EU27, China, RoW**
- End-uses: 7 sectors (see `configs/end_use.yml`)
- Canonical dimension symbols: `t` (time), `r` (region), `m` (material), `e` (end_use), `ed` (end_use_detailed), `p` (stage), `q` (quality); optional OD-trade placeholders: `c` (commodity), `o` (origin region), `d` (destination region)
- Exogenous inputs (one file per variable): `data/exogenous/*.csv` with schema defined in `registry/variable_registry.yml`
- Optional OD trade inputs: `data/exogenous/trade_od/*.csv` (BACI-derived observed/weights/constraints)
- Time horizon: **1870–2100**, with **calibration 1870–2019** and **reporting 2020–2100** (see `configs/time.yml`)
- Always **loose iterative coupling** (see `configs/coupling.yml`)
- dMFA stages/links/stocks are defined in `configs/stages.yml` (process names can be renamed via roles)

Documentation entrypoint: `docs/README.md`.
See `docs/governance/DECISION_LOG.md` for decisions, `docs/workflows/SCENARIOS.md` for scenario implementation rules, `docs/workflows/CALIBRATION.md` for calibration clarifications, and `docs/governance/ASSUMPTIONS.md` for open assumptions.

## Requirements

- Python **>= 3.11**

## Quickstart

```bash
# For interactive zsh terminals (including VS Code), avoid `-u` to prevent
# `__vsc_preexec: RPROMPT: parameter not set`.
set -eo pipefail

# 1) Environment
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2) Choose run config (examples: mvp.yml, r-strategies.yml)
CONFIG=configs/runs/mvp.yml

# 3) Validate configuration/input surface
python scripts/validation/lint_run_configs.py
python scripts/validation/validate_exogenous_inputs.py --config "$CONFIG"

# 4) Inspect available variants in selected config
python - "$CONFIG" <<'PY'
import sys
from crm_model.common.io import load_run_config
cfg = load_run_config(sys.argv[1])
for name in cfg.variants:
    print(name)
PY

# 5) One scenario run (reporting phase)
python scripts/run_one.py --config "$CONFIG" --variant baseline --phase reporting --save-csv

# 6) One scenario run (calibration phase)
python scripts/run_one.py --config "$CONFIG" --variant baseline --phase calibration --save-csv
```

### Command Cookbook

```bash
# Run all variants in config for reporting, save outputs, and build comparison CSV package
python scripts/run_batch.py --config "$CONFIG" --phase reporting --save-csv --compare

# Run selected variants only
python scripts/run_batch.py \
  --config "$CONFIG" \
  --phase reporting \
  --variants baseline,demand_surge,circularity_push \
  --save-csv \
  --compare

# Run both phases for one variant
python scripts/run_one.py --config "$CONFIG" --variant baseline --phase both --save-csv
```

```bash
# Manual variant loop (explicit and shell-friendly)
for VARIANT in $(python - "$CONFIG" <<'PY'
import sys
from crm_model.common.io import load_run_config
print(" ".join(load_run_config(sys.argv[1]).variants.keys()))
PY
); do
  python scripts/run_one.py --config "$CONFIG" --variant "$VARIANT" --phase reporting --save-csv
done
```

```bash
# Build/refresh scenario comparison package from latest run per variant
python scripts/analysis/compare_scenarios.py --config "$CONFIG"

# Build visual subset and indicator panels from latest precomputed scenario runs
python scripts/analysis/plots/plot_scenario_subset_panels.py --config "$CONFIG"

# Optional: generate end-use stock source, then include end-use detail panels
python scripts/analysis/plots/plot_stock_in_use_by_end_use_region_scenarios.py --config "$CONFIG"
END_USE_SOURCE=$(find outputs/analysis/stock_in_use_by_end_use_region_scenarios -name stock_in_use_by_end_use_region_scenario.csv | sort | tail -n 1)
python scripts/analysis/plots/plot_scenario_subset_panels.py \
  --config "$CONFIG" \
  --end-use-source "$END_USE_SOURCE"
```

### Calibration cycle (baseline -> calibration -> baseline)

```bash
# 1) Run calibration
python scripts/calibration/calibrate_model.py --config "$CONFIG" --calibration-spec configs/calibration.yml

# 2) Promote latest generated patch into run config
LATEST_PATCH=$(find outputs/runs/calibration -name best_config_patch.yml | sort | tail -n 1)
python scripts/calibration/calibration_cycle.py promote --config "$CONFIG" --patch "$LATEST_PATCH"

# 3) Optional rollback to latest saved baseline snapshot
# LATEST_SNAPSHOT=$(find outputs/runs/calibration/cycle -name baseline_before.yml | sort | tail -n 1)
# python scripts/calibration/calibration_cycle.py restore --config "$CONFIG" --snapshot "$LATEST_SNAPSHOT"
```

### Diagnostics, Audit, and Plotting

```bash
# Realism audit across one or more run configs
python scripts/analysis/audit_scenario_realism.py \
  --config configs/runs/mvp.yml \
  --config configs/runs/r-strategies.yml

# Compare observed exogenous vs modeled baseline/calibrated outputs
python scripts/analysis/plots/plot_observed_vs_model.py \
  --config "$CONFIG" \
  --phase full \
  --baseline-variant baseline \
  --calibrated-variant calibrated
```

### Profile Expansion Utility (authoring support)

```bash
# Expand reporting-window ramp CSV(s) into full-horizon YAML payload(s)
python scripts/scenarios/build_reporting_timeseries_profiles.py \
  --config "$CONFIG" \
  --profile data/ramp_profiles/r_strategies/r36_profiles.csv \
  --profile data/ramp_profiles/r_strategies/r79_profiles.csv
```

## Inputs you should replace early

The template ships with **synthetic placeholder data** in `data/exogenous/`.
Replace these with real datasets before drawing conclusions:

- `data/exogenous/final_demand.csv`
- `data/exogenous/end_use_shares.csv`
- `data/exogenous/primary_refined_output.csv`
- `data/exogenous/primary_refined_net_imports.csv`
- `data/exogenous/stage_yields_losses.csv`
- `data/exogenous/collection_routing_rates.csv` (`recycling_rate`, `remanufacturing_rate`, `disposal_rate`)
- `data/exogenous/remanufacturing_end_use_eligibility.csv` (`value` in [0,1] by year/region/end_use)
- `data/exogenous/lifetime_distributions.csv`
- `data/exogenous/stock_in_use.csv` (optional; calibration only)

Schemas are documented in `data/README.md` and enforced by `registry/variable_registry.yml`.

## Repo layout

- `configs/` – split config blocks (`time.yml`, `regions.yml`, `materials.yml`, `end_use.yml`, `stages.yml`, …)
- `configs/runs/_core.yml` – shared canonical run core (base parameters/includes)
- `configs/base.yml` – deprecated compatibility shim (temporary)
- `configs/scenarios/mvp/*.yml` – scenario-file sets loaded via `includes.scenarios`
- `configs/runs/mvp.yml` – thin overlay run config (`extends: ./_core.yml`)
- `configs/regions.yml`, `configs/materials.yml`, `configs/end_use.yml`, `configs/stages.yml`, `configs/qualities.yml` – split-layout single sources
- `configs/trade_od.yml` – optional OD-trade allocator controls (default disabled)
- `registry/` – exogenous variable registry (file paths + schema)
- `data/exogenous/` – exogenous inputs (one variable per file)
- `data/raw/`, `data/processed/`, `data/external/` – data-lake scaffold for future ingestion/ETL separation
- `src/crm_model/` – canonical model code
- `scripts/run_one.py` – thin wrapper for one CLI run (`python -m crm_model.cli`)
- `scripts/run_batch.py` – batch wrapper to run all/selected variants and optional compare step
- `scripts/calibration/` – calibration and promotion workflow
- `scripts/validation/` – exogenous input validation
- `scripts/validation/lint_run_configs.py` – run-config structure/canonical-key lint
- `scripts/analysis/` – comparison and plotting utilities
- `scripts/data/` – data processing utilities
- `outputs/runs/<config_stem>/<variant>/` – scenario run artifacts
- `outputs/runs/calibration/` – calibration artifacts
- `outputs/runs/calibration/cycle/` – baseline promotion/restore snapshots
- `outputs/analysis/` – derived comparisons and figures
- `docs/` – documentation hub and structured subfolders:
  - `docs/getting-started/` (quickstart, troubleshooting)
  - `docs/model/` (architecture, SD loop, indicators, outputs, glossary, flowchart)
  - `docs/workflows/` (scenarios, calibration, config precedence)
  - `docs/governance/` (assumptions, risks, decision log, changelog)
  - `docs/internal/` (agent playbook)
- `tests/` – smoke tests
