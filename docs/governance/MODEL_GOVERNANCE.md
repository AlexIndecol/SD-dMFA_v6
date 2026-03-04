# Model Governance

This file is the canonical governance source for assumptions and persistent model decisions.
It is organized by model logic, not chronology.

Use this file to understand what is currently valid in the model.
Use `docs/governance/CHANGELOG.md` for historical chronology.

## Document position

- You are here: Tier 2 canonical governance reference.
- Canonical scope: current-valid assumptions, persistent design decisions, and risk cross-links.
- Out of scope: chronological change history and module-level implementation formulas.
- Related docs: [RISKS.md](./RISKS.md), [CHANGELOG.md](./CHANGELOG.md), [ARCHITECTURE.md](../model/ARCHITECTURE.md), [CONFIGS.md](../workflows/CONFIGS.md)

## 1) Purpose and usage rules

- Keep only current-valid statements here.
- Move superseded decisions to changelog entries, not this file.
- Keep assumptions/decisions explicit enough for reproducibility and review.
- Each run should export `assumptions_used.yml` in run artifacts for traceability.

## 2) Status taxonomy

- `CONFIRMED`: agreed and active modeling choices.
- `TEMP`: temporary placeholders to keep the pipeline runnable; replace before interpretation.
- `OPEN`: unresolved decisions requiring a project choice and supporting evidence.

## 3) Model scope and boundaries (`CONFIRMED`)

- Materials: `tin`, `zinc`, `nickel`.
- Regions: `EU27`, `China`, `RoW`.
- End uses: 7 canonical sectors from `configs/end_use.yml`.
- Time split: 1870–2019 calibration/spin-up, 2020–2100 reporting.
- Coupling: loose iterative SD-dMFA coupling.
- dMFA graph: defined in `configs/stages.yml` with role-driven process semantics.
- Terminal stocks are kept as in-boundary inventory (not auto-flushed losses):
  - `Refinery_stockpile_stock`
  - `Strategic_inventory_stock`

Related risks: `R-CAP-01`, `R-INV-01`, `R-INV-02`.

## 4) Data and dimensional conventions (`CONFIRMED`)

- Region aliases are accepted in loaders (for example `EU-27 -> EU27`, `ROW -> RoW`).
- Exogenous demand and shares are mandatory and schema-validated:
  - `data/exogenous/final_demand.csv`
  - `data/exogenous/end_use_shares.csv`
- Observed stock (`stock_in_use.csv`) is calibration/validation input only, not a direct state driver.
- Lifetimes are exogenous by cohort (`weibull`, `lognormal`, `fixed`) and fail fast on invalid parameterization.

Related risks: `R-YLD-01`, `R-DMD-01`.

## 5) Physical stocks and flow assumptions (`CONFIRMED`)

- Primary availability to refining in endogenous-trade runtime:
  `primary_available_to_refining = max(0, primary_refined_output + trade_refined_net_imports + concentrate_to_refined_coeff * trade_concentrate_net_imports)`
- Upstream extraction/beneficiation/refining and sorting losses are explicit via `stage_yields_losses.csv`.
- New scrap and old scrap are explicitly separated.
- Secondary inventory is buffered at refining (`refinery_stockpile_native`) with release-rate control.
- Strategic reserve inventory is separate (`strategic_inventory_native`) and optional.
- Collection routing triad is constrained each year:
  `recycling_rate + remanufacturing_rate + disposal_rate = 1`.

Related risks: `R-PRI-01`, `R-YLD-01`, `R-SEC-01`, `R-RES-02`, `R-COL-01`.

## 6) SD and coupling assumptions (`CONFIRMED`)

- SD consumes exogenous desired demand and can apply price-elasticity demand response during reporting years.
- Collection dynamics are SD-native with bounded/lagged multiplier controls.
- Capacity/scarcity/price dynamic uses refining-first envelope and bottleneck pressure feedback.
- SD heterogeneity can be set by material-region rules (`sd_heterogeneity`).
- Coupling feedback uses two explicit MFA->SD signals:
  - `service_stress_t = unmet_service / service_demand`
  - `circular_supply_stress_t = 1 - secondary_supply / (primary_supply + secondary_supply)`
- Strategic reserve channel adds:
  - `strategic_stock_coverage_years_t = strategic_inventory_stock / service_demand`

Related risks: `R-CAP-01`, `R-HET-01`, `R-CPG-01`, `R-DMD-01`, `R-RES-01`.

## 7) Trade and OD assumptions (`CONFIRMED`)

- OD trade runtime mode is endogenous when enabled.
- Commodity channels are fixed to `concentrates`, `refined_metal`, `scrap`.
- Runtime uses OD weights plus endogenous constraints and SD-capacity-informed caps.
- Runtime activation phases are calibration and reporting in active run overlays.
- `historical_window_*` and `fallback_mode_outside_window` have been removed from active config/runtime interfaces.
- Observed OD matrices and exogenous OD constraints are used for calibration/backtesting workflows.

Related risks: `R-OD-01`, `R-PRI-01`.

## 8) Calibration and baseline-governance policy (`CONFIRMED`)

- Baseline run config is `configs/runs/mvp.yml`.
- Baseline parameter updates are applied through calibration promotion workflow, then persisted in active run config surfaces.
- Active stock-calibration promoted controls are in `configs/runs/_core.yml`.
- Active OD-trade calibration promoted controls are in `configs/trade.yml`.
- Older patch artifacts are retained for reproducibility/backtesting only and are not active baseline targets.

Related risks: `R-YLD-01`, `R-OD-01`.

## 9) TEMP assumptions and removal paths

### TEMP-01 Identity upstream defaults

- In slices with missing measured stage yields/loss splits, identity defaults can keep runs operational.
- Removal path:
  1. Populate measured yields/loss routing by material-region-year.
  2. Re-run calibration and compare baseline drift.
  3. Lock replacements in active exogenous inputs.

Related risks: `R-YLD-01`.

### TEMP-02 Incremental OD scope boundaries

- OD coupling is still constrained by configured historical windows and current commodity mapping design.
- Removal path:
  1. Extend OD calibration targets and validation windows.
  2. Validate outside-window behavior against accepted references.
  3. Promote widened scope only after convergence and realism checks pass.

Related risks: `R-OD-01`, `R-PRI-01`.

## 10) OPEN decisions and closure requirements

### OPEN-01 Lifetime data provenance policy

- Decision needed: canonical sources and hierarchy when multiple lifetime datasets exist.
- Closure requirements:
  - source ranking rule,
  - uncertainty treatment policy,
  - documented update cadence.

### OPEN-02 Criticality framework selection

- Decision needed: which criticality framework is canonical (for example EU CRM-style vs alternatives).
- Closure requirements:
  - selected methodology,
  - required time-dynamic inputs,
  - indicator mapping into existing outputs.

### OPEN-03 Material/region process parameter evidence coverage

- Decision needed: minimum evidence quality for yields, collection, and reman parameters by slice.
- Closure requirements:
  - acceptance thresholds,
  - gap-handling policy,
  - recalibration trigger rules.

## 11) Risk cross-reference map

- Scope and boundary assumptions -> `R-CAP-01`, `R-INV-01`, `R-INV-02`
- Data conventions and validation assumptions -> `R-YLD-01`, `R-DMD-01`
- Physical flow/stock assumptions -> `R-PRI-01`, `R-SEC-01`, `R-COL-01`, `R-RES-02`
- SD/coupling assumptions -> `R-CAP-01`, `R-HET-01`, `R-CPG-01`, `R-RES-01`, `R-DMD-01`
- Trade/OD assumptions -> `R-OD-01`, `R-PRI-01`
- Calibration governance assumptions -> `R-YLD-01`, `R-OD-01`
- TEMP assumptions -> `R-YLD-01`, `R-OD-01`, `R-PRI-01`

## 12) Related sections

- [RISKS.md](./RISKS.md) for risk definitions referenced by ID in this file.
- [ARCHITECTURE.md §9](../model/ARCHITECTURE.md#9-known-simplifications-and-risk-cross-reference) for implementation-level simplification context.
- [CHANGELOG.md](./CHANGELOG.md) for historical superseded governance statements.
