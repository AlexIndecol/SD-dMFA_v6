# Decision log

This file captures *project-level* modeling decisions so the repository stays reproducible and a future AI agent has a single source of truth.

## Confirmed decisions (2026-02-17)

1) **Materials**
- tin, zinc, nickel

2) **Regions**
- EU-27 (code label: `EU27`)
- China
- Rest of the World (RoW, code label: `RoW`)

3) **End-uses**
- construction
- computers_and_precision_instruments
- electrical_equipment
- machinery_and_equipment
- motor_vehicles_trailers_and_semi_trailers
- other_transport_equipment
- products_nec

4) **Circularity strategies to represent**
- Recycling yield
- Lifetime extension
- Reuse / remanufacture

5) **Indicators (dynamic over time)**
- Use the indicator categories:
  - *MFA state & flow metrics*
  - *Resilience / service indicators*
- See `docs/model/INDICATORS.md` for definitions and `configs/indicators.yml` for the configured set.

6) **Shocks / stress tests**
- Demand surge
- Recycling disruption **implemented as a multiplier on recycling yield only** (not collection).

7) **Coupling approach**
- Always keep a **loose iterative coupling** between SD and dMFA.

8) **End-use demand shares**
- End-use shares are an **exogenous data input** per **material × region × year**.
- File: `data/exogenous/end_use_shares.csv` (schema in `registry/variable_registry.yml`).

9) **Primary supply exogenous setup (refining anchored)**
- Use **primary refined output by region** plus **primary refined net imports** as the canonical exogenous setup.
- Files: `data/exogenous/primary_refined_output.csv`, `data/exogenous/primary_refined_net_imports.csv`.
- Canonical balance:
  `primary_available_to_refining = max(0, primary_refined_output + primary_refined_net_imports)`.

10) **Final demand (service demand) input**
- Final demand is an **exogenous data input** per **material × region × year**.
- File: `data/exogenous/final_demand.csv`.

In SD, the exogenous demand trajectory is treated as *desired* demand:
- Price-elasticity demand response is forced **OFF during calibration/spin-up** (years < `report_start_year`).
- Demand response can be enabled only during **reporting** (years ≥ `report_start_year`).

11) **Observed stocks (for calibration/validation)**
- Stock-in-use can be provided as an **exogenous input** per **material × region × end-use × year**.
- File: `data/exogenous/stock_in_use.csv`.
- In the template it is used for **fit metrics** during the calibration window (it does not drive the MFA).

12) **Time horizon split**
- Default configuration: **1870–2100** total horizon, with **1870–2019** for spin-up/calibration and **2020–2100** for reporting.

13) **Lifetime modeling**
- Lifetime distributions are an **exogenous data input** per **material × region × end-use × cohort year**.
- File: `data/exogenous/lifetime_distributions.csv`.
- Distributions are converted to a discrete annual retirement PDF and applied via cohort convolution.
- Supported families: `weibull`, `lognormal`, `fixed`.
- Validation is strict: duplicate parameter rows and invalid parameterizations fail fast.

14) **dMFA stages / process naming**
- The dMFA process graph (stages + links) is defined in `configs/stages.yml`.
- Process names may be renamed freely in config.
- Code relies on semantic `role` identifiers (source/fabrication/use_stock/collection/remanufacture/recycling/disposal, with optional refining/upstream/sorting roles) rather than hard-coded names.

15) **Aliases for dimension codes**
- The loaders accept common aliases in exogenous inputs to reduce friction (e.g., `EU-27` → `EU27`, `Rest of the World` / `ROW` → `RoW`).

16) **Explicit upstream stage reconstruction**
- `primary_refined_output` is defined as **domestic primary refined metal production** (metal content).
- Upstream roles (`primary_extraction`, `beneficiation_concentration`, `refining`) are reconstructed from refining-anchored availability using explicit exogenous yields/loss routing from `stage_yields_losses.csv`.
- Identity yields (`1.0`) remain allowed as defaults where measured yield data are not yet available.

17) **Explicit surplus/loss accounting**
- Fabrication losses are explicitly accounted.
- New scrap (pre-use losses) and old scrap (post-use outflow) are explicitly separated.
- Reman/native buffer stocks were removed.
- Secondary inventory is represented as `refinery_stockpile_native` with exogenous release-rate control (`refinery_stockpile_release_rate`) and optional new-scrap routing control (`new_scrap_to_secondary_share`).
- Stockpile is not automatically flushed at horizon end; remaining stock is interpreted as terminal inventory.

18) **Scalar resilience metrics computed over reporting window**
- Scalar resilience metrics (triangle area, years below threshold, max consecutive years below threshold) are computed over the reporting window (`time.report_years`) when available.

19) **Collection/disposal routing structure**
- dMFA roles include `collection` and `disposal` in addition to `end_of_life`, `recycling`, and `remanufacture`.
- Collection routing is exogenous via `collection_routing_rates.csv` (`recycling_rate`, `remanufacturing_rate`, `disposal_rate`), with the hard constraint that rates sum to 1.0.
- Collection-rate controls are bounded/lagged (`sd_parameters.collection_multiplier_min/max/lag_years`) with SD price-linked response (`sd_parameters.collection_price_response_gain`).

26) **SD capacity/bottleneck loop (refining-first envelope)**
- SD includes a lagged capacity envelope with bottleneck feedback:
  `capacity_envelope -> flow_utilization -> bottleneck_pressure -> scarcity/price -> capacity_target -> capacity_envelope`.
- Bottleneck pressure can amplify scarcity (`bottleneck_scarcity_gain`) and dampen collection pressure response (`bottleneck_collection_sensitivity`).

20) **Primary availability balance and compatibility window**
- Exogenous `primary_refined_output` and `primary_refined_net_imports` are required canonical runtime inputs.
- Primary availability to refining uses:
  `primary_available_to_refining = max(0, primary_refined_output + primary_refined_net_imports)`.
- Deprecated one-cycle aliases are retained:
  `primary_production -> primary_refined_output`,
  `primary_refined_net_imports -> primary_refined_net_imports`,
  `primary_available_to_refining -> primary_available_to_refining`.

21) **Mass-balance conservation guardrail**
- Beyond flodym checks, the model enforces explicit process-level conservation checks with tolerance control (`mass_balance_tolerance`) across fabrication/use/collection/remanufacture/recycling/stockpile handling (and `end_of_life` where present).

22) **Baseline configuration**
- `configs/runs/mvp.yml` is the baseline run configuration.
- Calibration workflow uses `scripts/calibration/calibrate_model.py` + `scripts/calibration/calibration_cycle.py` for baseline promotion/rollback.

23) **Material-region SD heterogeneity**
- SD behavioral parameters can be configured per material-region slice using ordered top-level `sd_heterogeneity` rules in run config.
- Resolution order: `sd_parameters` base -> matching `sd_heterogeneity` rules (in order) -> variant overrides.

24) **Two-signal coupling feedback**
- Coupling uses two distinct MFA->SD signals:
  `service_stress_t = unmet_service / service_demand` and
  `circular_supply_stress_t = 1 - secondary_supply / (primary_supply + secondary_supply)`.
- Both signals are iteratively smoothed and combined into the effective SD stress multiplier using configurable gains.
- Per-iteration/per-year signal traces are exported for transparency.

25) **Strategic reserve architecture and policy**
- Strategic reserve is modeled as a separate native stock: `strategic_inventory_native` (at refining), distinct from operational `refinery_stockpile_native`.
- SD computes reserve-control intents (`strategic_fill_intent_t`, `strategic_release_intent_t`) using target-coverage and emergency trigger logic.
- MFA enforces physical reserve accounting and mass balance:
  - fill competes with current-year supply,
  - fill source priority is secondary diversion first, then primary diversion,
  - release is bounded by available strategic stock (no negative stock).
- Coupling includes a third MFA->SD feedback signal:
  `strategic_stock_coverage_years_t = strategic_inventory_stock / service_demand`.
- Mechanism is disabled by default via `strategy.strategic_reserve_enabled: false`.

## Open decisions / assumptions (still needed)

- **Lifetime data source** (family support is implemented; data provenance/selection is still a project choice).
- **Criticality framework choice** (EU CRM-style, Graedel/Yale, etc.) and the required time-dynamic inputs.
- **Trade / inter-regional exchange** (MVP treats regions independently).
- **Material- and region-specific process parameters** (yields, collection, reman shares).
