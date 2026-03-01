# Documentation Hub

Use this page as the entry point for model usage, configuration, calibration, and interpretation.

## Start here

1. [QUICKSTART.md](./getting-started/QUICKSTART.md): run baseline, run scenarios, and produce comparison outputs.
2. [ARCHITECTURE.md](./model/ARCHITECTURE.md): SD-dMFA coupling structure and system boundaries.
3. [SCENARIOS.md](./workflows/SCENARIOS.md): scenario schema, precedence, supported shock channels.

## Core technical references

- [CONFIG_PRECEDENCE.md](./workflows/CONFIG_PRECEDENCE.md): authoritative merge order and temporal-parameter behavior.
- [SD_CAPACITY_SCARCITY_PRICE_LOOP.md](./model/SD_CAPACITY_SCARCITY_PRICE_LOOP.md): endogenous capacity/scarcity/price/bottleneck dynamics.
- [INDICATORS.md](./model/INDICATORS.md): indicator formulas, output fields, and interpretation.
- [OUTPUTS_GUIDE.md](./model/OUTPUTS_GUIDE.md): where outputs are written and how to read them.

## Operational guides

- [SCENARIOS.md#scenario-authoring-checklist](./workflows/SCENARIOS.md#scenario-authoring-checklist): safe workflow for adding or editing scenarios.
- [CALIBRATION.md](./workflows/CALIBRATION.md): calibration objective, workflow, and caveats.
- [TROUBLESHOOTING.md](./getting-started/TROUBLESHOOTING.md): common failures, diagnosis, and fixes.

## Model governance

- [ASSUMPTIONS.md](./governance/ASSUMPTIONS.md): confirmed vs temporary assumptions.
- [RISKS.md](./governance/RISKS.md): structural and data risks.
- [DECISION_LOG.md](./governance/DECISION_LOG.md): persistent design decisions.
- [CHANGELOG.md](./governance/CHANGELOG.md): versioned change history.

## Glossary

- [GLOSSARY.md](./model/GLOSSARY.md): canonical terminology and signal definitions.

## Redundancy decisions

- Merged standalone scenario-authoring checklist into `workflows/SCENARIOS.md` to keep one canonical scenario contract + workflow page.
- Kept `model/INDICATORS.md` and `model/OUTPUTS_GUIDE.md` separate:
  indicator semantics and output file navigation serve different use cases and evolve at different pace.

## Interface contracts in config files

Configuration contracts live inline as `#` comments at the top of each YAML file in:

- `configs/**/*.yml`
- `registry/variable_registry.yml`

Read those headers first when editing config interfaces.
