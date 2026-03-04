# Architecture

This document describes the current implemented SD-dMFA model behavior.
It is code-aligned to runtime modules under `src/crm_model/**`.

## Document position

- You are here: Tier 2 canonical model overview.
- Canonical scope: runtime-accurate architecture, module boundaries, and cross-module execution logic.
- Out of scope: full module tuning playbooks and exhaustive indicator card-level semantics.
- Related docs: [MFA_MODEL.md](./MFA_MODEL.md), [SD_MODEL.md](./SD_MODEL.md), [OD_TRADE_MODULE.md](./OD_TRADE_MODULE.md), [COUPLING_LOGIC.md](./COUPLING_LOGIC.md), [INDICATORS.md](./INDICATORS.md), [MODEL_GOVERNANCE.md](../governance/MODEL_GOVERNANCE.md), [RISKS.md](../governance/RISKS.md)

## 1) System scope and execution layers

The model couples:
- a System Dynamics (SD) demand and policy layer (BPTK),
- a dynamic MFA (dMFA) physical flow/stock layer (flodym),
- an optional endogenous OD trade layer that runs across regions.

Core boundaries and dimensions are configured in:
- `configs/time.yml`
- `configs/regions.yml`
- `configs/materials.yml`
- `configs/end_use.yml`
- `configs/stages.yml`

Canonical governance and risk references:
- `docs/governance/MODEL_GOVERNANCE.md`
- `docs/governance/RISKS.md`

Execution modes:
1. Slice-coupled mode (default): inner SD<->dMFA iteration per material-region slice.
2. Endogenous OD mode (optional): adds an outer material-level OD trade loop across all regions.

Notes:
- Coupling is loose-iterative, not year-by-year co-simulation.
- Runtime behavior is defined by `configs/coupling.yml` and runtime code in
  `src/crm_model/coupling/runner.py` and `src/crm_model/cli.py`.

## 2) MFA model: key mechanisms

Operational deep-dive: `docs/model/MFA_MODEL.md`

### 2.1 Demand-to-service flow and stock dynamics

Per year and region/end-use:
1. SD realized demand is split by exogenous end-use shares.
2. Demand enters the use stage through new and remanufactured inflows.
3. Cohort lifetimes drive outflows from use stock.
4. Outflows generate old scrap (EoL), then collection/routing applies.

Collection routing triad is constrained each year:
- `recycling_rate + remanufacturing_rate + disposal_rate = 1`

### 2.2 Circular chain and losses

Mechanisms included explicitly:
- remanufacturing yield,
- sorting yield and reject routing,
- recycling yield,
- collection and process losses,
- uncollected EoL share.

New scrap and old scrap are handled separately:
- new scrap comes from fabrication losses,
- old scrap comes from use-stock outflow.

### 2.3 Secondary and strategic inventories

Two separate stocks exist at refining boundary:
1. `refinery_stockpile_native` (operational secondary buffer).
2. `strategic_inventory_native` (policy reserve controlled by SD intents).

Operational behavior:
- secondary inflows (recycled + routed new scrap + scrap imports) build stockpile,
- stockpile outflow is release-rate limited,
- strategic fill diverts material from near-term use,
- strategic release can reduce shortfall under stress.

### 2.4 Refining-anchor and upstream reconstruction

Primary availability to refining is computed as:

`primary_available_to_refining = max(0, primary_refined_output + trade_refined_net_imports + concentrate_to_refined_coeff * trade_concentrate_net_imports)`

Given required refined input, upstream throughput is reconstructed backward using stage yields:
- `refining_input_primary = primary_total_withdrawn / refining_yield`
- `beneficiation_input_required = refining_input_primary / beneficiation_yield`
- `extraction_input_required = beneficiation_input_required / extraction_yield`

This keeps upstream extraction/beneficiation flows consistent with refined-stage availability and configured losses.

## 3) MFA design decisions and implications

### 3.1 Why the model is anchored at refined stage

Rationale:
- exogenous and trade signals are most operationally available near refining/refined product balance,
- coupling to demand fulfillment is direct at the refined/fabrication boundary,
- upstream ore/concentrate needs can be reconstructed deterministically from yields.

Implications:
- high sensitivity to stage-yield quality (`R-YLD-01`),
- aggregate refined-equivalent anchor can under/over constrain physical reality in missing channels (`R-PRI-01`).

### 3.2 Conversion-path clarification (refined-equivalent <-> commodity-space)

Current runtime conversion sequence in endogenous OD mode:
1. Concentrate net imports are converted to refined-equivalent when computing `primary_available_to_refining`.
2. MFA diagnostics produce refined-equivalent upstream gap/surplus proxies.
3. OD constraint builder converts those proxies back to concentrate commodity units (divide by `concentrate_to_refined_coeff`) for allocation.
4. Allocated concentrate net trade is injected next outer iteration and converted again to refined-equivalent in step 1.

This is a unit-mapping loop between commodity-space allocation and refined-equivalent MFA balance, not two independent concentrate supply channels.

Risk framing:
- simplification still inherits `R-PRI-01` because one coefficient bridges heterogeneous conversion realities.

## 4) SD model: key mechanisms and dynamics

Operational deep-dive: `docs/model/SD_MODEL.md`

### 4.1 Scarcity-price-demand channel

Core path:
- coupling stress multiplier -> effective scarcity -> price -> demand response.

Demand response gating:
- before `demand_response_start_year`, effective elasticity is zero,
- from `demand_response_start_year`, price elasticity can reduce realized demand.

### 4.2 Capacity envelope loop (with delays)

Implemented dynamic:
1. `flow_utilization = demand_desired / flow_capacity`
2. `bottleneck_pressure = max(0, flow_utilization - 1)`
3. `scarcity_multiplier_effective = scarcity_multiplier * (1 + bottleneck_scarcity_gain * bottleneck_pressure)`
4. `price` rises with scarcity-effective multiplier.
5. `capacity_pressure` blends shortage and price channels.
6. `capacity_target` is bounded between envelope min/max.
7. `capacity_envelope` smooths toward `capacity_target` with `capacity_adjustment_lag_years`.

### 4.3 Collection response sub-loop

Collection is SD-native and price-linked:
- target multiplier rises with price pressure,
- bottlenecks can throttle collection response,
- target is bounded by min/max,
- realized collection multiplier is lagged.

Effective collection rate sent to dMFA:
- `collection_rate_effective = clip(base_collection_rate * collection_multiplier, 0, 1)`

### 4.4 Strategic reserve intent policy

SD computes policy intents each year:
- fill intent from coverage gap and fill thresholds,
- release intent from stress/emergency pressure and release thresholds,
- both intents bounded by max rates and enable flags.

Intents are passed to dMFA and applied to strategic inventory flow decisions.

## 5) SD design decisions and implications

1. Calendar-gated demand response keeps historical calibration phase stable and avoids retrofitting strong behavioral response where not intended.
2. Capacity is modeled as an envelope index, not explicit stage assets (`R-CAP-01`).
3. Collection control is bounded/lagged and aggregated, not asset-resolved (`R-COL-01`).
4. Strategic reserve control can materially change stress timing (`R-RES-01`, `R-RES-02`).

## 6) OD trade module across MFA and SD

Operational deep-dive: `docs/model/OD_TRADE_MODULE.md`

Endogenous OD mode is active only when all are true:
- `trade_od.enabled = true`
- `trade_od.runtime_mode = endogenous`
- current phase is in `trade_od.activation_phases`

Runtime data dependency:
- required: `trade_od_weights` (prepared with clamp+normalize policy)
- optional calibration/backtesting utilities: `trade_od_observed`, `trade_od_constraints`

Outer-loop structure (per material):
1. Run slice-level SD-dMFA for all regions with current trade state.
2. Build endogenous trade constraints from MFA diagnostics for commodities:
   - `refined_metal`, `concentrates`, `scrap`.
3. Apply SD capacity-envelope-informed export caps.
4. Allocate OD flows using weights + constraints.
5. Compute net imports/exports and apply coupling relaxation (lambda) to trade state.
6. Stop when outer trade delta <= `outer_trade_convergence_tol` or max iterations reached.

Important accuracy note:
- `historical_window_start_year`, `historical_window_end_year`, and
  `fallback_mode_outside_window` were removed from active config/runtime interfaces.
- runtime allocation is endogenous-only and does not support legacy fallback branching.

## 7) Coupling logic (inner + outer loops)

Operational deep-dive: `docs/model/COUPLING_LOGIC.md`

### 7.1 Inner loop: SD<->dMFA per slice

Feedback signals from dMFA:
- `service_stress_t = unmet_service / service_demand`
- `circular_supply_stress_t = 1 - secondary_supply / (primary_supply + secondary_supply)`
- `strategic_stock_coverage_years_t = strategic_inventory_stock / service_demand`

Stress multiplier used by SD:
- `1 + coupling_service_stress_gain * service_stress + coupling_circular_supply_stress_gain * circular_supply_stress`
- capped by `coupling_stress_multiplier_cap`

Modes:
- `time_series`: year-by-year targets.
- `scalar_mean`: reporting-window mean signals applied as scalars.

Optional gating:
- if `feedback_on_report_years_only=true`, feedback updates apply only on reporting years.

Convergence metric (implemented):
- `max(max_signal_delta, collection_multiplier_delta, strategic_intent_delta)`
- converged when metric `< coupling.convergence_tol`.

### 7.2 Outer loop: OD trade (optional)

When endogenous OD is active, the above inner loop runs inside a material-level outer trade iteration across regions. Net trade results are re-injected and the process repeats until outer-loop convergence.

## 8) Diagnostics and verification

Use these outputs to verify mechanism activation and stability:
- `indicators/coupling_signals_iteration_year.csv`
- `indicators/coupling_convergence_iteration.csv`
- `summary.csv` (`coupling_converged`, convergence metric, SD loop means)
- OD mode outputs:
  - `indicators/trade_od_flows.csv`
  - `indicators/trade_od_imports_exports.csv`
  - `indicators/trade_od_outer_loop_convergence.csv`

Mechanism checks:
1. Stress window: utilization, bottleneck pressure, and price should rise.
2. Recovery window: capacity envelope should adjust with lag; bottleneck should relax.
3. OD mode: outer trade delta should contract toward tolerance.

## 9) Known simplifications and risk cross-reference

Key risks for interpreting results:
- refining-anchor simplification: `R-PRI-01`
- stage-yield quality sensitivity: `R-YLD-01`
- capacity-envelope abstraction: `R-CAP-01`
- collection-response abstraction: `R-COL-01`
- OD scope limits and commodity mapping constraints: `R-OD-01`
- strategic reserve sensitivity/composition simplification: `R-RES-01`, `R-RES-02`

See:
- `docs/governance/RISKS.md`
- `docs/governance/MODEL_GOVERNANCE.md`

## Related docs

- [COUPLED_MODEL_FLOWCHART.md](./COUPLED_MODEL_FLOWCHART.md) for visual system map.
- [MFA_MODEL.md](./MFA_MODEL.md) for MFA mechanism equations, controls, and diagnostics.
- [SD_MODEL.md](./SD_MODEL.md) for SD mechanism equations, controls, and diagnostics.
- [OD_TRADE_MODULE.md](./OD_TRADE_MODULE.md) for OD trade runtime behavior and diagnostics.
- [COUPLING_LOGIC.md](./COUPLING_LOGIC.md) for SD<->MFA coupling update rules and convergence.
- [INDICATORS.md](./INDICATORS.md) for output semantics and formula-level interpretation.
- [SCENARIOS.md](../workflows/SCENARIOS.md) for scenario execution behavior.
- [CONFIGS.md](../workflows/CONFIGS.md) for config contracts and precedence.
