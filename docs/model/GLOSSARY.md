# Glossary

Canonical terminology for SD, dMFA, coupling, OD trade, indicators, and scenario authoring.
This glossary is definition-only: formulas are referenced, not reproduced.

## Document position

- You are here: Tier 2 canonical terminology reference.
- Canonical scope: plain-language definitions for model and workflow terms, with links to formula sources.
- Out of scope: formula derivations and implementation procedures.
- Related docs: [INDICATORS.md](./INDICATORS.md), [SD_MODEL.md](./SD_MODEL.md), [MFA_MODEL.md](./MFA_MODEL.md), [COUPLING_LOGIC.md](./COUPLING_LOGIC.md), [OD_TRADE_MODULE.md](./OD_TRADE_MODULE.md), [SCENARIOS.md](../workflows/SCENARIOS.md)

## Canonical terms

- Term: **Loose iterative coupling**
- Definition: SD and MFA are run back and forth in short rounds until the results stop changing in a meaningful way.
- Formula reference: [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Slice**
- Definition: A single material-region pair. Most runtime calculations and diagnostics are done at this level.
- Formula reference: [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Inner loop**
- Definition: The repeated SD-MFA solve that runs inside one slice.
- Formula reference: [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Outer loop**
- Definition: An optional extra loop that updates OD trade across regions for a material after inner-loop results.
- Formula reference: [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference)

- Term: **Runtime channels**
- Definition: The pathways used during execution to pass values between modules, such as feedback signals and trade channels.
- Formula reference: [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Reporting phase**
- Definition: The model phase used for scenario analysis and reported outputs.
- Formula reference: [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Calibration phase**
- Definition: The model phase used to fit behavior to historical data and check consistency.
- Formula reference: [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers), [Calibration objective](../workflows/CALIBRATION.md#1-what-the-calibration-objective-is-actually-fitting)

- Term: **Reporting window**
- Definition: The years used for reporting-focused interpretation and scalar metrics.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Scenario execution flow](../workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime)

- Term: **Convergence metric**
- Definition: A single value that summarizes how much values changed between iterations.
- Formula reference: [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Convergence tolerance**
- Definition: The cutoff that decides when iteration changes are small enough to stop.
- Formula reference: [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference)

- Term: **Coupling relaxation (lambda)**
- Definition: The damping setting for iterative updates. Lower values change slowly; higher values change faster.
- Formula reference: [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Feedback signal mode**
- Definition: The rule for sending feedback as full year-by-year series or as one summary value.
- Formula reference: [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Time-series feedback mode**
- Definition: Feedback mode that keeps year-by-year variation.
- Formula reference: [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Scalar-mean feedback mode**
- Definition: Feedback mode that replaces the yearly pattern with one average value.
- Formula reference: [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Reporting-year gating**
- Definition: A rule that applies updates only in reporting years.
- Formula reference: [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Desired demand**
- Definition: Demand target before price and other dynamic effects are applied.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Service demand**
- Definition: The amount of service the system needs to deliver.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference)

- Term: **Delivered service**
- Definition: The amount of service the system actually delivers.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference)

- Term: **Unmet service**
- Definition: The part of service demand that is not delivered.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference)

- Term: **Service level**
- Definition: How much demand is met, expressed as a ratio.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Service deficit**
- Definition: How far delivered service falls below full service.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Service stress signal**
- Definition: A coupling signal that rises when service delivery is under pressure.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [SD equations](./SD_MODEL.md#3-consolidated-equation-reference)

- Term: **Circular supply stress signal**
- Definition: A coupling signal that rises when circular supply is weak relative to total supply.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [SD equations](./SD_MODEL.md#3-consolidated-equation-reference)

- Term: **Stress multiplier**
- Definition: The combined stress factor that scales scarcity pressure in SD.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [SD equations](./SD_MODEL.md#3-consolidated-equation-reference)

- Term: **Capacity envelope**
- Definition: An SD index that represents effective throughput room in the system.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Capacity envelope ceilings**
- Definition: Upper limits that stop the capacity envelope from growing unrealistically.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Capacity pressure**
- Definition: The combined pressure value used to move the capacity target.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Capacity target**
- Definition: The level the capacity envelope tries to move toward.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Lagged adjustment**
- Definition: A delayed move from a current value toward a target value.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference)

- Term: **Flow utilization**
- Definition: How hard the system is being used compared with available effective capacity.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Bottleneck pressure**
- Definition: Congestion pressure when utilization pushes beyond feasible capacity.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Bottleneck channel**
- Definition: The path through which congestion affects scarcity and control responses.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Price channel**
- Definition: The path through which scarcity affects price and then other behaviors.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Scarcity multiplier effective**
- Definition: Scarcity after bottleneck amplification has been applied.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Price ratio**
- Definition: Current price relative to the baseline price.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Demand response gate**
- Definition: A start-year switch that turns demand-price response on.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Configurable gains**
- Definition: Tuning parameters that control how strongly channels react.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [Scenario execution flow](../workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime)

- Term: **Throttle**
- Definition: A damping factor that reduces response strength.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Collection bottleneck throttle**
- Definition: The damping factor that limits collection response when bottlenecks are high.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Collection multiplier**
- Definition: The SD scaling factor applied to baseline collection behavior.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Collection multiplier target**
- Definition: The target value for collection response before lag is applied.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Collection rate effective**
- Definition: The final collection rate after multipliers and bounds are applied.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference)

- Term: **Bounded/lagged multipliers**
- Definition: Multipliers that are both limited by min/max bounds and adjusted with lag.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Strategic reserve enabled**
- Definition: Switch that turns strategic reserve behavior on or off.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference)

- Term: **Strategic fill/release intent**
- Definition: Control intents that guide when reserves should build or be released.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Target-coverage logic**
- Definition: Reserve logic that fills stock when coverage is below the target.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Emergency trigger logic**
- Definition: Reserve logic that releases stock when stress triggers are hit.
- Formula reference: [SD equations](./SD_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Strategic inventory**
- Definition: Policy reserve stock held to buffer stress periods.
- Formula reference: [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Strategic stock coverage years**
- Definition: How many years of service demand the strategic stock can cover.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [SD equations](./SD_MODEL.md#3-consolidated-equation-reference)

- Term: **Refinery stockpile**
- Definition: Operational stock used to buffer short-term refinery-side fluctuations.
- Formula reference: [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Terminal inventory**
- Definition: Stock left at the end of the simulation horizon; this is carry-over, not automatically a loss.
- Formula reference: [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Risk register](../governance/RISKS.md#model-structure-risks)

- Term: **EoL routing triad**
- Definition: The split of end-of-life flow among recycling, remanufacturing, and disposal.
- Formula reference: [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **New scrap**
- Definition: Scrap generated during fabrication before products reach use.
- Formula reference: [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Old scrap**
- Definition: Scrap generated when products leave use at end of life.
- Formula reference: [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Sorting rejects**
- Definition: Material that fails sorting and is routed away from circular recovery.
- Formula reference: [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Primary available to refining**
- Definition: Primary material available at refining stage after relevant additions and constraints.
- Formula reference: [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference), [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Refining anchor**
- Definition: Design choice that anchors primary accounting at refined stage.
- Formula reference: [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Upstream reconstruction**
- Definition: Back-calculation of beneficiation and extraction needs from refined-stage requirements.
- Formula reference: [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Refined-equivalent conversion**
- Definition: Conversion of other channels into refined-equivalent units for consistent accounting.
- Formula reference: [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference), [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Mass-balance residual**
- Definition: The leftover accounting gap after stocks, flows, losses, and boundaries are reconciled.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference)

- Term: **Mass-balance tolerance**
- Definition: Allowed size of mass-balance residual before it is treated as a problem.
- Formula reference: [MFA equations](./MFA_MODEL.md#3-consolidated-equation-reference), [Config precedence and temporal rules](../workflows/CONFIGS.md#7-precedence-and-merge-semantics)

- Term: **OD endogenous mode**
- Definition: OD trade mode where trade is solved inside runtime loops and fed back into MFA.
- Formula reference: [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **OD sidecar mode**
- Definition: Removed legacy OD trade mode previously used for non-endogenous compatibility diagnostics.
- Formula reference: [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference)

- Term: **Activation phases**
- Definition: Settings that define in which phase OD runtime behavior is active.
- Formula reference: [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference), [Config precedence and temporal rules](../workflows/CONFIGS.md#7-precedence-and-merge-semantics)

- Term: **Import need**
- Definition: Required imports for a channel after endogenous constraints are applied.
- Formula reference: [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Supply available**
- Definition: Volume available on the export side for a channel after constraints.
- Formula reference: [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference)

- Term: **Export cap**
- Definition: Maximum export volume allowed by the selected cap logic.
- Formula reference: [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Cap smoothing**
- Definition: Iteration-to-iteration damping used when updating cap values.
- Formula reference: [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference), [Coupling equations](./COUPLING_LOGIC.md#3-consolidated-equation-reference)

- Term: **Exportable supply**
- Definition: Supply that is actually available to allocation after caps and guards.
- Formula reference: [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference)

- Term: **Allocation feasibility**
- Definition: Condition that allocations stay within both import needs and export availability.
- Formula reference: [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Supplier concentration (HHI)**
- Definition: A concentration score showing how dependent imports are on a small number of suppliers.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference)

- Term: **Supplier diversification**
- Definition: A breadth score showing how spread imports are across suppliers.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference)

- Term: **Effective suppliers**
- Definition: The equivalent number of balanced suppliers implied by concentration.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference)

- Term: **Governance-risk-weighted supplier exposure**
- Definition: Supplier exposure metric that combines import shares with governance risk.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference)

- Term: **Resilience triangle area**
- Definition: Summary scalar of cumulative service underperformance over the evaluation period.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Years below service threshold**
- Definition: Count of years where service level stays below the threshold.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Maximum consecutive years below threshold**
- Definition: Longest uninterrupted run of years below the service threshold.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards)

- Term: **Threshold service level**
- Definition: The cutoff service level used by threshold-based resilience scalars.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Config precedence and temporal rules](../workflows/CONFIGS.md#7-precedence-and-merge-semantics)

- Term: **Logical subsets**
- Definition: Named groups used to organize indicators for reading and reporting.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Config precedence and temporal rules](../workflows/CONFIGS.md#7-precedence-and-merge-semantics)

- Term: **Strict partition**
- Definition: Rule that each indicator belongs to one and only one subset.
- Formula reference: [Indicator formulas and guards](./INDICATORS.md#2-global-conventions-for-formulas-and-guards), [Config precedence and temporal rules](../workflows/CONFIGS.md#7-precedence-and-merge-semantics)

- Term: **Variant**
- Definition: A scenario package containing coordinated overrides to test a mechanism.
- Formula reference: [Scenario execution flow](../workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime), [Config precedence and temporal rules](../workflows/CONFIGS.md#7-precedence-and-merge-semantics)

- Term: **Baseline variant**
- Definition: The reference scenario used as the comparison point.
- Formula reference: [Scenario execution flow](../workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime), [Architecture mechanism map](./ARCHITECTURE.md#1-system-scope-and-execution-layers)

- Term: **Dimension overrides**
- Definition: Ordered slice-level overrides by material and/or region.
- Formula reference: [Scenario execution flow](../workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime), [Config precedence and temporal rules](../workflows/CONFIGS.md#7-precedence-and-merge-semantics)

- Term: **Precedence order**
- Definition: The fixed merge order that decides which value wins when overrides overlap.
- Formula reference: [Config precedence and temporal rules](../workflows/CONFIGS.md#7-precedence-and-merge-semantics), [Scenario execution flow](../workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime)

- Term: **Scalar temporal form**
- Definition: A single value used across the modeled horizon unless overridden later.
- Formula reference: [Config precedence and temporal rules](../workflows/CONFIGS.md#7-precedence-and-merge-semantics), [Scenario execution flow](../workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime)

- Term: **Year-gated temporal form**
- Definition: A value that becomes active from a start year onward.
- Formula reference: [Config precedence and temporal rules](../workflows/CONFIGS.md#7-precedence-and-merge-semantics), [Scenario execution flow](../workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime)

- Term: **Full timeseries temporal form**
- Definition: A full year-by-year value series provided directly.
- Formula reference: [Config precedence and temporal rules](../workflows/CONFIGS.md#7-precedence-and-merge-semantics), [Scenario execution flow](../workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime)

- Term: **Exogenous ramp reference**
- Definition: A pointer to an external profile that supplies year-by-year values.
- Formula reference: [Config precedence and temporal rules](../workflows/CONFIGS.md#7-precedence-and-merge-semantics), [Scenario execution flow](../workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime)

- Term: **Scenario shock channels**
- Definition: Scenario controls that apply temporary disturbances to selected pathways.
- Formula reference: [Scenario execution flow](../workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime), [OD trade equations](./OD_TRADE_MODULE.md#3-consolidated-equation-reference)

## Deprecated synonyms

| Deprecated term | Canonical term |
|---|---|
| service pressure | service stress signal |
| circular-supply stress | circular supply stress signal |
| bottleneck collection throttle | collection bottleneck throttle |
| relax-update factor | coupling relaxation (lambda) |
| arget-coverage logic | target-coverage logic |

## Related sections

- [INDICATORS.md §2-6](./INDICATORS.md#2-global-conventions-for-formulas-and-guards) for formulas and guard conventions behind glossary terms.
- [ARCHITECTURE.md](./ARCHITECTURE.md) for system-level placement of canonical terms.
- [CONFIGS.md §6-7](../workflows/CONFIGS.md#6-temporal-interface-contract) for temporal and precedence terms used in scenario configuration.
