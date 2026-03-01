# Coupled SD-dMFA Flowchart

This is the canonical system flowchart for the current model implementation.

- Data input files are shown in amber.
- Scenario files are shown in rose.
- Model processes are shown in blue.
- Model stocks are shown in green.
- Coupling/control nodes are shown in violet.

```mermaid
flowchart LR
    %% ========= Exogenous Inputs =========
    subgraph EXO
        FD[final_demand.csv]
        EUS[end_use_shares.csv]
        PRO[primary_refined_output.csv]
        PNI[primary_refined_net_imports.csv]
        SYL[stage_yields_losses.csv]
        RE["remanufacturing_end_use_eligibility.csv"]
        LT[lifetime_distributions.csv]
        SIO["stock_in_use.csv - calibration observation"]
        SHK["Scenario files (*.yml): demand, routing/yield, import/output, disruption, strategic-intent shocks"]
    end

    %% ========= SD Module =========
    subgraph SD
        SCAR[stress_multiplier]
        SCAR_EFF[scarcity_multiplier_effective]
        PRICE[price]
        DMD[demand_realized_t]
        CAPENV[capacity_envelope]
        UTIL[flow_utilization]
        BOT[bottleneck_pressure]
        SFILL[strategic_fill_intent_t]
        SREL[strategic_release_intent_t]
    end

    %% ========= Coupling =========
    subgraph CPL
        ITER["Loose iterative coupling: max_iter, convergence_tol"]
        SS["service_stress_t = unmet_service / service_demand"]
        CS["circular_supply_stress_t = 1 - secondary/(primary+secondary)"]
        STRCOV["strategic_stock_coverage_years_t = strategic_inventory_stock / service_demand"]
    end

    %% ========= Environment =========
    subgraph ENVG["Environment Boundary"]
        direction TB
        ENV[sysenv]
    end

    %% ========= dMFA Module =========
    subgraph MFA
        direction TB
        subgraph CHAIN["Linear primary-to-use chain"]
            direction LR
            PEX[primary_extraction]
            BEN[beneficiation_concentration]
            REF[refining]
            FAB[fabrication_and_manufacturing]
            USEP[use]
        end

        subgraph REV["Reverse/circular chain"]
            direction LR
            COL[collection]
            SORT[sorting_preprocessing]
            REC[recycling_refining_secondary]
            REM[remanufacturing]
            RTD[residue_treatment_disposal]
        end

        subgraph DYN["Demand, availability, and stocks"]
            direction TB
            SPLIT[Demand split by end-use]
            SDTRE[service_demand_tre]
            PRI["Primary availability (refined output + net imports)"]
            STOCK[Use-stock cohorts]
            OUT[Outflow from use]
            EOL[Old-scrap generation]
            NSCRAP[New-scrap generation]
            SEC[Secondary refined supply]
            RSTOCK[Refinery stockpile/inventory]
            STRAT[Strategic reserve inventory]
            DEL[Delivered service]
            UNM[Unmet service]
            STKINUSE[Stock_in_use]
        end
    end

    %% ========= Indicators =========
    subgraph IND
        TS[timeseries indicators]
        SCAL[scalar resilience metrics]
    end

    %% Exogenous -> SD/MFA
    FD --> DMD
    SHK --> DMD
    SHK --> EOL
    SHK --> PRI
    EUS --> SPLIT
    PRO --> PRI
    PNI --> PRI
    SYL --> PEX
    SYL --> BEN
    SYL --> REF
    SYL --> FAB
    SYL --> REM
    SYL --> SORT
    SYL --> REC
    LT --> STOCK
    RE --> REM
    SIO -->|calibration fit only| SCAL

    %% SD internal
    SCAR --> SCAR_EFF
    BOT --> SCAR_EFF
    SCAR_EFF --> PRICE
    PRICE --> DMD
    DMD --> UTIL
    CAPENV --> UTIL
    UTIL --> BOT
    BOT --> CAPENV
    PRICE --> SFILL
    PRICE --> SREL

    %% SD -> dMFA
    DMD --> SPLIT
    SFILL --> STRAT
    SREL --> STRAT
    SPLIT --> SDTRE
    SDTRE --> USEP

    %% dMFA internal (full-chain stages from configs/stages.yml)
    ENV --> PEX
    PEX --> BEN
    PEX --> ENV
    PEX --> RTD
    BEN --> REF
    BEN --> ENV
    BEN --> RTD
    PRI --> REF
    REF --> FAB
    REF --> ENV
    REF --> RTD
    FAB --> USEP
    FAB --> ENV
    FAB --> REF
    USEP --> COL
    USEP --> ENV
    COL --> RTD
    SORT --> RTD
    SORT --> ENV
    REC --> REF
    REC --> ENV
    REM --> USEP
    REM --> ENV
    RTD --> ENV

    %% dMFA stock/loop dynamics
    USEP --> STOCK
    STOCK --> OUT
    OUT --> EOL
    EOL --> COL
    COL -->|Remanufacturing loop| REM
    COL -->|Recycling loop| SORT
    SORT --> REC
    REC --> SEC
    SEC --> RSTOCK
    SEC --> REF
    NSCRAP --> RSTOCK
    RSTOCK --> REF
    STRAT --> REF
    USEP --> DEL
    FAB --> NSCRAP
    STOCK --> STKINUSE
    SDTRE --> UNM
    DEL --> UNM

    %% Coupling loop
    UNM --> SS
    SDTRE --> SS
    SEC --> CS
    PRI --> CS
    SS --> ITER
    CS --> ITER
    STRAT --> STRCOV
    SDTRE --> STRCOV
    STRCOV --> ITER
    SS --> SFILL
    SS --> SREL
    ITER --> SCAR

    %% Indicators
    DEL --> TS
    UNM --> TS
    PRI --> TS
    SEC --> TS
    STKINUSE --> TS
    EOL --> TS
    COL --> TS
    RTD --> TS
    SS --> SCAL
    CS --> SCAL
    DEL --> SCAL
    UNM --> SCAL

    classDef dataInput fill:#fef3c7,stroke:#d97706,stroke-width:1.4px,color:#111827;
    classDef scenario fill:#ffe4e6,stroke:#e11d48,stroke-width:1.4px,color:#111827;
    classDef process fill:#dbeafe,stroke:#2563eb,stroke-width:1.2px,color:#111827;
    classDef stock fill:#dcfce7,stroke:#16a34a,stroke-width:1.3px,color:#111827;
    classDef coupling fill:#ede9fe,stroke:#7c3aed,stroke-width:1.2px,color:#111827;
    classDef outputs fill:#e0f2fe,stroke:#0284c7,stroke-width:1.2px,color:#111827;

    class FD,EUS,PRO,PNI,SYL,RE,LT,SIO dataInput;
    class SHK scenario;
    class SCAR,SCAR_EFF,PRICE,DMD,UTIL,BOT,SFILL,SREL,ENV,PEX,BEN,REF,FAB,USEP,COL,SORT,REM,REC,RTD,SPLIT,SDTRE,PRI,OUT,EOL,NSCRAP,SEC,DEL,UNM process;
    class CAPENV,STOCK,RSTOCK,STRAT,STKINUSE stock;
    class ITER,SS,CS,STRCOV coupling;
    class TS,SCAL outputs;
```

## Update rule

Update this diagram whenever any of the following changes:

- `configs/coupling.yml`
- `src/crm_model/coupling/runner.py`
- `src/crm_model/sd/builder.py`
- `src/crm_model/mfa/builder.py`
- `registry/variable_registry.yml`
- `configs/stages.yml`

Minimum update checklist:

1. Exogenous node list still matches configured inputs/boundary.
2. SD->dMFA and dMFA->SD coupling arrows still match code.
3. Indicator/output nodes still match `configs/indicators.yml`.
