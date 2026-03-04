# Documentation Hub

Use this page as the stable documentation entrypoint.

## Documentation architecture

The documentation system is organized into three tiers:

1. Tier 1 (entry and navigation): this file (`docs/README.md`) and root `README.md`.
2. Tier 2 (canonical topic references): model, workflow, and governance canonical sources.
3. Tier 3 (companions): practical guides and internal playbooks that should not redefine Tier 2 contracts.

## Page index with status flags

| Page | Status | Role |
|---|---|---|
| [ARCHITECTURE.md](./model/ARCHITECTURE.md) | Canonical | System overview and module boundaries |
| [MFA_MODEL.md](./model/MFA_MODEL.md) | Canonical | MFA deep-dive mechanisms and equations |
| [SD_MODEL.md](./model/SD_MODEL.md) | Canonical | SD deep-dive mechanisms and equations |
| [OD_TRADE_MODULE.md](./model/OD_TRADE_MODULE.md) | Canonical | OD module deep-dive |
| [COUPLING_LOGIC.md](./model/COUPLING_LOGIC.md) | Canonical | Coupling deep-dive |
| [INDICATORS.md](./model/INDICATORS.md) | Canonical | Indicator definitions, formulas, interpretation |
| [GLOSSARY.md](./model/GLOSSARY.md) | Canonical | Terminology definitions |
| [VARIABLES_AND_PARAMETERS.md](./model/VARIABLES_AND_PARAMETERS.md) | Canonical | Exogenous/endogenous/parameter taxonomy |
| [CONFIGS.md](./workflows/CONFIGS.md) | Canonical | Config contracts and merge semantics |
| [SCENARIOS.md](./workflows/SCENARIOS.md) | Canonical | Variant definition and execution workflow |
| [CALIBRATION.md](./workflows/CALIBRATION.md) | Canonical | Calibration workflow and policy guidance |
| [MODEL_GOVERNANCE.md](./governance/MODEL_GOVERNANCE.md) | Canonical | Current-valid assumptions and model decisions |
| [RISKS.md](./governance/RISKS.md) | Canonical | Risk register |
| [CHANGELOG.md](./governance/CHANGELOG.md) | Canonical | Historical chronology |
| [QUICKSTART.md](./getting-started/QUICKSTART.md) | Companion | Minimal run path |
| [TROUBLESHOOTING.md](./getting-started/TROUBLESHOOTING.md) | Companion | Runtime and interpretation debugging |
| [COUPLED_MODEL_FLOWCHART.md](./model/COUPLED_MODEL_FLOWCHART.md) | Companion | Visual system map |
| [AGENT_PLAYBOOK.md](./internal/AGENT_PLAYBOOK.md) | Companion (Internal) | Operational agent workflow rules |

## Doc ownership matrix

| Topic | Canonical file | Allowed secondary mentions | Prohibited duplication |
|---|---|---|---|
| Config interfaces, precedence, temporal forms | [CONFIGS.md](./workflows/CONFIGS.md) | `configs/**/*.yml` comments, workflow docs summaries | Repeating full interface contracts in YAML headers or scenario docs |
| Scenario runtime resolution and variant behavior | [SCENARIOS.md](./workflows/SCENARIOS.md) | Architecture section summaries, troubleshooting references | Rewriting variant merge order rules in multiple docs |
| Model architecture and module boundaries | [ARCHITECTURE.md](./model/ARCHITECTURE.md) | Deep-dive introductions | Duplicating full architecture narrative in deep dives |
| Module equations and tuning diagnostics | [MFA_MODEL.md](./model/MFA_MODEL.md), [SD_MODEL.md](./model/SD_MODEL.md), [OD_TRADE_MODULE.md](./model/OD_TRADE_MODULE.md), [COUPLING_LOGIC.md](./model/COUPLING_LOGIC.md) | Architecture summaries, indicator references | Re-copying full mechanism/equation cards into architecture or workflows |
| Indicator definitions and formulas | [INDICATORS.md](./model/INDICATORS.md) | Glossary formula references, troubleshooting checks | Storing formula definitions in glossary or generic docs |
| Terminology definitions | [GLOSSARY.md](./model/GLOSSARY.md) | Parenthetical reminders in technical docs | Competing definitions of the same term across docs |
| Inputs/outputs/control taxonomy | [VARIABLES_AND_PARAMETERS.md](./model/VARIABLES_AND_PARAMETERS.md) | README onboarding pointers | Rebuilding taxonomy lists in unrelated pages |
| Assumptions and persistent decisions | [MODEL_GOVERNANCE.md](./governance/MODEL_GOVERNANCE.md) | Risk references, architecture risk notes | Splitting assumptions/decisions back into separate files |
| Risk statements | [RISKS.md](./governance/RISKS.md) | Governance cross-references | Duplicating risk register text elsewhere |

## Cross-reference style rules

1. Link canonical page first, then any companion page.
2. Prefer anchor links for formula and section-specific references.
3. Use short local summaries in companion docs and link to canonical sections for full detail.
4. Keep one definition per term in `GLOSSARY.md`; other docs should reference it instead of redefining.
5. Treat YAML comments as editing aids only, not contract documents.

## Cross-reference map

| From doc/section | Canonical target section | Link purpose |
|---|---|---|
| [ARCHITECTURE.md §2](./model/ARCHITECTURE.md#2-mfa-model-key-mechanisms) | [MFA_MODEL.md §2-3](./model/MFA_MODEL.md#2-mechanism-structure-and-equation-map) | Mechanism and formulas |
| [ARCHITECTURE.md §4](./model/ARCHITECTURE.md#4-sd-model-key-mechanisms-and-dynamics) | [SD_MODEL.md §2-3](./model/SD_MODEL.md#2-mechanism-structure-and-equation-map) | Mechanism and formulas |
| [ARCHITECTURE.md §6](./model/ARCHITECTURE.md#6-od-trade-module-across-mfa-and-sd) | [OD_TRADE_MODULE.md §2-3](./model/OD_TRADE_MODULE.md#2-mechanism-structure-and-equation-map) | Runtime OD mechanics |
| [ARCHITECTURE.md §7](./model/ARCHITECTURE.md#7-coupling-logic-inner-outer-loops) | [COUPLING_LOGIC.md §2-3](./model/COUPLING_LOGIC.md#2-mechanism-structure-and-equation-map) | Iteration logic and convergence |
| [GLOSSARY.md](./model/GLOSSARY.md) | [INDICATORS.md §2-6](./model/INDICATORS.md#2-global-conventions-for-formulas-and-guards) | Formula references only |
| [SCENARIOS.md §3](./workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime) | [CONFIGS.md §5-7](./workflows/CONFIGS.md#5-variant-interface-contract-configsscenariosyml) | Merge/precedence alignment |
| [MODEL_GOVERNANCE.md §11](./governance/MODEL_GOVERNANCE.md#11-risk-cross-reference-map) | [RISKS.md](./governance/RISKS.md) | Risk lookup |

## Quality gates and automation

Run these checks when documentation links, structure, or canonical references change:

```bash
python scripts/validation/lint_docs_links.py
python scripts/validation/check_docs_dedup.py --min-length 220 --max-occurrences 1
```

Recommended companion checks:

```bash
rg -n "BACI_OD_ASSUMPTIONS|OUTPUTS_GUIDE|CONFIG_PRECEDENCE\.md|ASSUMPTIONS\.md|DECISION_LOG\.md" README.md docs --glob '!docs/governance/CHANGELOG.md' --glob '!docs/README.md'
rg -n "canonical source|source of truth" docs | sort
```

## Quarterly documentation audit checklist

1. Confirm every canonical topic still has one authoritative file.
2. Run link and dedup checks and fix findings.
3. Verify glossary canonical terms are used in active docs.
4. Confirm removed/legacy files are not referenced by active links.
5. Confirm companion docs point to canonical sources for formulas/contracts/definitions.

## Interface contracts

`docs/workflows/CONFIGS.md` is the canonical contract source for all config interfaces.
YAML comments in config files are editing aids only (examples, definitions, formulas, and local reminders).
