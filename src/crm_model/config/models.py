from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


class TimeConfig(BaseModel):
    start_year: int
    calibration_end_year: int
    report_start_year: int
    end_year: int

    @property
    def years(self) -> List[int]:
        return list(range(self.start_year, self.end_year + 1))

    @property
    def calibration_years(self) -> List[int]:
        return list(range(self.start_year, self.calibration_end_year + 1))

    @property
    def report_years(self) -> List[int]:
        return list(range(self.report_start_year, self.end_year + 1))


class MaterialConfig(BaseModel):
    name: str
    unit: str = "t"
    meta: Dict[str, Any] = Field(default_factory=dict)


class DimensionSymbolsConfig(BaseModel):
    time: str = "t"
    region: str = "r"
    material: str = "m"
    end_use: str = "e"
    end_use_detailed: str = "ed"
    stage: str = "p"
    quality: str = "q"
    commodity: str = "c"
    origin_region: str = "o"
    destination_region: str = "d"


class TradeDimensionAliasesConfig(BaseModel):
    origin_region: str = "r"
    destination_region: str = "r"


class DimensionsConfig(BaseModel):
    regions: List[str]
    materials: List[MaterialConfig]
    end_uses: List[str]
    end_use_detailed: List[str] = Field(default_factory=list)
    stages: List[str] = Field(default_factory=list)
    qualities: List[str] = Field(default_factory=list)
    commodities: List[str] = Field(default_factory=list)
    origin_regions: List[str] = Field(default_factory=list)
    destination_regions: List[str] = Field(default_factory=list)
    trade_aliases: TradeDimensionAliasesConfig = Field(default_factory=TradeDimensionAliasesConfig)
    symbols: DimensionSymbolsConfig = Field(default_factory=DimensionSymbolsConfig)

    @model_validator(mode="after")
    def _validate_symbols(self) -> "DimensionsConfig":
        required = {
            "time": "t",
            "region": "r",
            "material": "m",
            "end_use": "e",
            "end_use_detailed": "ed",
            "stage": "p",
            "quality": "q",
            "commodity": "c",
            "origin_region": "o",
            "destination_region": "d",
        }
        for key, expected in required.items():
            got = getattr(self.symbols, key)
            if str(got).strip() != expected:
                raise ValueError(
                    f"dimensions.symbols.{key} must be '{expected}' for canonical dimension handling; got '{got}'."
                )
        for key in ["origin_region", "destination_region"]:
            got_alias = getattr(self.trade_aliases, key)
            if str(got_alias).strip() != "r":
                raise ValueError(
                    f"dimensions.trade_aliases.{key} must be 'r' when provided; got '{got_alias}'."
                )
        return self


class ShockEvent(BaseModel):
    start_year: int
    duration_years: int
    multiplier: float


class ShocksConfig(BaseModel):
    demand_surge: Optional[ShockEvent] = None
    recycling_disruption: Optional[ShockEvent] = None
    primary_refined_output: Optional[ShockEvent] = None
    primary_refined_net_imports: Optional[ShockEvent] = None
    extraction_yield: Optional[ShockEvent] = None
    beneficiation_yield: Optional[ShockEvent] = None
    refining_yield: Optional[ShockEvent] = None
    sorting_yield: Optional[ShockEvent] = None
    collection_rate: Optional[ShockEvent] = None
    recycling_rate: Optional[ShockEvent] = None
    remanufacturing_rate: Optional[ShockEvent] = None
    disposal_rate: Optional[ShockEvent] = None
    strategic_fill_intent: Optional[ShockEvent] = None
    strategic_release_intent: Optional[ShockEvent] = None


class StrategyConfig(BaseModel):
    recycling_yield: Optional[float] = None
    recycling_rate: Optional[float] = None
    remanufacturing_rate: Optional[float] = None
    disposal_rate: Optional[float] = None
    lifetime_multiplier: Optional[float] = None
    reuse_share: Optional[float] = None
    remanufacture_share: Optional[float] = None
    reman_yield: Optional[float] = None
    refinery_stockpile_release_rate: Optional[float] = None
    new_scrap_to_secondary_share: Optional[float] = None
    collection_multiplier_min: Optional[float] = None
    collection_multiplier_max: Optional[float] = None
    collection_multiplier_lag_years: Optional[float] = None
    strategic_reserve_enabled: bool = False
    strategic_reserve_target_coverage_years: float = 0.5
    strategic_reserve_fill_gain: float = 0.5
    strategic_reserve_release_gain: float = 1.0
    strategic_reserve_max_fill_rate: float = 0.15
    strategic_reserve_max_release_rate: float = 0.25
    strategic_reserve_fill_price_threshold: float = 1.0
    strategic_reserve_release_price_threshold: float = 1.1
    strategic_reserve_fill_service_threshold: float = 0.05
    strategic_reserve_release_service_threshold: float = 0.15

    @model_validator(mode="after")
    def _validate_strategic_reserve_params(self) -> "StrategyConfig":
        if self.strategic_reserve_target_coverage_years < 0:
            raise ValueError("strategic_reserve_target_coverage_years must be >= 0.")
        if self.strategic_reserve_fill_gain < 0:
            raise ValueError("strategic_reserve_fill_gain must be >= 0.")
        if self.strategic_reserve_release_gain < 0:
            raise ValueError("strategic_reserve_release_gain must be >= 0.")

        for name, value in {
            "strategic_reserve_max_fill_rate": self.strategic_reserve_max_fill_rate,
            "strategic_reserve_max_release_rate": self.strategic_reserve_max_release_rate,
            "strategic_reserve_fill_service_threshold": self.strategic_reserve_fill_service_threshold,
            "strategic_reserve_release_service_threshold": self.strategic_reserve_release_service_threshold,
        }.items():
            if value < 0 or value > 1:
                raise ValueError(f"{name} must be in [0,1].")

        if self.strategic_reserve_fill_price_threshold <= 0:
            raise ValueError("strategic_reserve_fill_price_threshold must be > 0.")
        if self.strategic_reserve_release_price_threshold <= 0:
            raise ValueError("strategic_reserve_release_price_threshold must be > 0.")

        for key in ["collection_multiplier_min", "collection_multiplier_max", "collection_multiplier_lag_years"]:
            if getattr(self, key) is not None:
                raise ValueError(
                    f"strategy.{key} is no longer supported; use sd_parameters.{key}."
                )

        return self


class TransitionPolicyConfig(BaseModel):
    enabled: bool = False
    start_year: Optional[int] = None
    adoption_target: float = 0.0
    adoption_lag_years: float = 4.0
    compliance_delay_years: float = 0.0
    demand_intensity_reduction_max: float = 0.0
    collection_uplift_max: float = 0.0
    recycling_yield_uplift_max: float = 0.0
    capacity_expansion_gain_uplift: float = 0.0
    bottleneck_relief_max: float = 0.0

    @model_validator(mode="after")
    def _validate_transition_policy(self) -> "TransitionPolicyConfig":
        if self.adoption_target < 0 or self.adoption_target > 1:
            raise ValueError("transition_policy.adoption_target must be in [0,1].")
        if self.adoption_lag_years < 0:
            raise ValueError("transition_policy.adoption_lag_years must be >= 0.")
        if self.compliance_delay_years < 0:
            raise ValueError("transition_policy.compliance_delay_years must be >= 0.")
        if self.demand_intensity_reduction_max < 0 or self.demand_intensity_reduction_max > 1:
            raise ValueError("transition_policy.demand_intensity_reduction_max must be in [0,1].")
        if self.collection_uplift_max < 0:
            raise ValueError("transition_policy.collection_uplift_max must be >= 0.")
        if self.recycling_yield_uplift_max < 0:
            raise ValueError("transition_policy.recycling_yield_uplift_max must be >= 0.")
        if self.capacity_expansion_gain_uplift < 0:
            raise ValueError("transition_policy.capacity_expansion_gain_uplift must be >= 0.")
        if self.bottleneck_relief_max < 0 or self.bottleneck_relief_max > 1:
            raise ValueError("transition_policy.bottleneck_relief_max must be in [0,1].")
        return self


class DemandTransformationConfig(BaseModel):
    enabled: bool = False
    service_activity_source: str = "service_activity"
    material_intensity_source: str = "material_intensity"
    service_activity_multiplier: Any = 1.0
    material_intensity_multiplier: Any = 1.0
    efficiency_improvement: Any = 0.0
    rebound_effect: Any = 0.0
    transition_adoption_weight: float = 0.0
    min_demand_multiplier: float = 0.25
    max_demand_multiplier: float = 2.5
    normalize_exogenous: bool = True

    @model_validator(mode="after")
    def _validate_demand_transformation(self) -> "DemandTransformationConfig":
        if self.transition_adoption_weight < 0 or self.transition_adoption_weight > 1:
            raise ValueError("demand_transformation.transition_adoption_weight must be in [0,1].")
        if self.min_demand_multiplier <= 0:
            raise ValueError("demand_transformation.min_demand_multiplier must be > 0.")
        if self.max_demand_multiplier < self.min_demand_multiplier:
            raise ValueError(
                "demand_transformation.max_demand_multiplier must be >= min_demand_multiplier."
            )
        if not str(self.service_activity_source).strip():
            raise ValueError("demand_transformation.service_activity_source must be non-empty.")
        if not str(self.material_intensity_source).strip():
            raise ValueError("demand_transformation.material_intensity_source must be non-empty.")
        return self


class CouplingConfig(BaseModel):
    mode: str = "loose_iterative"
    max_iter: int = 3
    convergence_tol: float = 1e-3
    feedback_signal_mode: Literal["time_series", "scalar_mean"] = "time_series"
    feedback_on_report_years_only: bool = True
    signals: Dict[str, Any] = Field(default_factory=dict)


class ScenarioProfilesConfig(BaseModel):
    enabled: bool = False
    csv_globs: List[str] = Field(default_factory=list)
    interpolation: Literal["linear"] = "linear"
    apply_precedence: Literal["profile_overrides_variant"] = "profile_overrides_variant"
    emit_resolved_payload: bool = True

    @model_validator(mode="after")
    def _validate_csv_globs(self) -> "ScenarioProfilesConfig":
        globs = []
        for raw in self.csv_globs:
            s = str(raw).strip()
            if s:
                globs.append(s)
        self.csv_globs = globs
        if self.enabled and not self.csv_globs:
            raise ValueError("scenario_profiles.enabled=true requires at least one csv_globs entry.")
        return self


class IndicatorGroupConfig(BaseModel):
    indicators: List[str] = Field(default_factory=list)
    logical_subsets: Dict[str, List[str]] = Field(default_factory=dict)


class IndicatorsConfig(BaseModel):
    mfa_state_and_flow_metrics: IndicatorGroupConfig = Field(default_factory=IndicatorGroupConfig)
    resilience_service_indicators: IndicatorGroupConfig = Field(default_factory=IndicatorGroupConfig)
    service_risk: Dict[str, Any] = Field(default_factory=dict)
    formulas: Dict[str, str] = Field(default_factory=dict)

    def mfa_metrics(self) -> List[str]:
        return list(self.mfa_state_and_flow_metrics.indicators)

    def resilience_metrics(self) -> List[str]:
        return list(self.resilience_service_indicators.indicators)

    def all_metrics(self) -> List[str]:
        return self.mfa_metrics() + self.resilience_metrics()

    @model_validator(mode="after")
    def _validate_indicator_subsets(self) -> "IndicatorsConfig":
        mfa_metrics = self.mfa_metrics()
        resilience_metrics = self.resilience_metrics()

        def _dup_items(items: List[str]) -> List[str]:
            seen = set()
            dups = []
            for item in items:
                if item in seen and item not in dups:
                    dups.append(item)
                seen.add(item)
            return dups

        mfa_dups = _dup_items(mfa_metrics)
        if mfa_dups:
            raise ValueError(
                f"indicators.mfa_state_and_flow_metrics.indicators contains duplicates: {sorted(mfa_dups)}"
            )
        res_dups = _dup_items(resilience_metrics)
        if res_dups:
            raise ValueError(
                f"indicators.resilience_service_indicators.indicators contains duplicates: {sorted(res_dups)}"
            )
        overlap = sorted(list(set(mfa_metrics) & set(resilience_metrics)))
        if overlap:
            raise ValueError(
                "Indicators cannot be declared in both mfa_state_and_flow_metrics and "
                f"resilience_service_indicators: {overlap}"
            )

        mfa_subset_names = set(self.mfa_state_and_flow_metrics.logical_subsets.keys())
        res_subset_names = set(self.resilience_service_indicators.logical_subsets.keys())
        subset_name_overlap = sorted(list(mfa_subset_names & res_subset_names))
        if subset_name_overlap:
            raise ValueError(
                "Subset names must be unique across indicator groups; overlapping names: "
                + str(subset_name_overlap)
            )

        def _validate_subset_map(
            subsets: Dict[str, List[str]],
            *,
            declared_metrics: List[str],
            scope: str,
        ) -> None:
            declared_set = set(declared_metrics)
            all_members: List[str] = []
            for subset_name, members in subsets.items():
                dup_members = _dup_items(members)
                if dup_members:
                    raise ValueError(
                        f"{scope}['{subset_name}'] contains duplicate indicators: {sorted(dup_members)}"
                    )
                unknown = sorted(list(set(members) - declared_set))
                if unknown:
                    raise ValueError(
                        f"{scope}['{subset_name}'] contains unknown indicators: {unknown}"
                    )
                all_members.extend(members)

            if not subsets:
                return

            duplicate_assignments = _dup_items(all_members)
            if duplicate_assignments:
                raise ValueError(
                    f"{scope} assigns indicators to multiple subsets: {sorted(duplicate_assignments)}"
                )

            assigned_set = set(all_members)
            missing = sorted(list(declared_set - assigned_set))
            if missing:
                raise ValueError(
                    f"{scope} must define a strict partition; indicators missing from subsets: {missing}"
                )

        _validate_subset_map(
            self.mfa_state_and_flow_metrics.logical_subsets,
            declared_metrics=mfa_metrics,
            scope="indicators.mfa_state_and_flow_metrics.logical_subsets",
        )
        _validate_subset_map(
            self.resilience_service_indicators.logical_subsets,
            declared_metrics=resilience_metrics,
            scope="indicators.resilience_service_indicators.logical_subsets",
        )

        known = set(mfa_metrics + resilience_metrics)
        unknown_formula_keys = sorted(list(set(self.formulas.keys()) - known))
        if unknown_formula_keys:
            raise ValueError(
                "indicators.formulas contains unknown indicators: "
                + str(unknown_formula_keys)
            )

        return self


class VariableMeta(BaseModel):
    path: str
    required: bool = True
    columns: List[str]
    unit: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class MFAProcessConfig(BaseModel):
    id: int
    name: str
    role: str


class MFAFlowConfig(BaseModel):
    from_process: str = Field(alias="from")
    to_process: str = Field(alias="to")
    dim_letters: List[str]


class MFAStockConfig(BaseModel):
    name: str
    process: str
    dim_letters: List[str]
    role: str | None = None


class MFAGraphConfig(BaseModel):
    processes: List[MFAProcessConfig]
    flows: List[MFAFlowConfig]
    stocks: List[MFAStockConfig] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> "MFAGraphConfig":
        names = [p.name for p in self.processes]
        if len(set(names)) != len(names):
            raise ValueError("MFAGraphConfig.processes contains duplicate process names")
        ids = [p.id for p in self.processes]
        if len(set(ids)) != len(ids):
            raise ValueError("MFAGraphConfig.processes contains duplicate process ids")

        roles = [p.role for p in self.processes]
        # The compute() implementation currently requires these roles.
        required_roles = {
            "source",
            "fabrication",
            "use_stock",
            "collection",
            "remanufacture",
            "recycling",
            "disposal",
        }
        missing = sorted(list(required_roles - set(roles)))
        if missing:
            raise ValueError(f"MFAGraphConfig missing required roles: {missing}")
        dup_roles = [r for r in set(roles) if roles.count(r) > 1]
        if dup_roles:
            raise ValueError(f"MFAGraphConfig has duplicate role assignments: {sorted(dup_roles)}")

        role_to_name = {p.role: p.name for p in self.processes}
        primary_name = role_to_name.get("primary_extraction")
        beneficiation_name = role_to_name.get("beneficiation_concentration")
        refining_name = role_to_name.get("refining")
        sorting_name = role_to_name.get("sorting_preprocessing")
        collection_name = role_to_name.get("collection")
        recycling_name = role_to_name.get("recycling")

        if (primary_name is None) ^ (beneficiation_name is None):
            raise ValueError(
                "MFAGraphConfig must define both roles 'primary_extraction' and "
                "'beneficiation_concentration' together, or omit both."
            )
        if (primary_name is not None or beneficiation_name is not None) and refining_name is None:
            raise ValueError(
                "MFAGraphConfig with primary extraction/beneficiation chain requires role 'refining'."
            )

        name_set = set(names)
        flow_pairs = set()
        for f in self.flows:
            if f.from_process not in name_set:
                raise ValueError(f"Flow references unknown process in 'from': {f.from_process}")
            if f.to_process not in name_set:
                raise ValueError(f"Flow references unknown process in 'to': {f.to_process}")
            if not f.dim_letters:
                raise ValueError("Flow.dim_letters must be a non-empty list")
            flow_pairs.add((f.from_process, f.to_process))

        if sorting_name is not None:
            if collection_name is None or recycling_name is None:
                raise ValueError(
                    "MFAGraphConfig role 'sorting_preprocessing' requires roles 'collection' and 'recycling'."
                )
            if (collection_name, sorting_name) not in flow_pairs:
                raise ValueError(
                    "MFAGraphConfig with 'sorting_preprocessing' must include flow "
                    f"'{collection_name} -> {sorting_name}'."
                )
            if (sorting_name, recycling_name) not in flow_pairs:
                raise ValueError(
                    "MFAGraphConfig with 'sorting_preprocessing' must include flow "
                    f"'{sorting_name} -> {recycling_name}'."
                )

        stock_names = [s.name for s in self.stocks]
        if len(set(stock_names)) != len(stock_names):
            raise ValueError("MFAGraphConfig.stocks contains duplicate stock names")
        for s in self.stocks:
            if s.process not in name_set:
                raise ValueError(
                    f"Stock references unknown process in 'process': {s.process}"
                )
            if not s.dim_letters:
                raise ValueError("Stock.dim_letters must be a non-empty list")
        if self.stocks:
            required_stock_names = {
                "stock_in_use",
                "refinery_stockpile_native",
                "strategic_inventory_native",
            }
            missing_stock_names = sorted(list(required_stock_names - set(stock_names)))
            if missing_stock_names:
                raise ValueError(
                    "MFAGraphConfig missing required native stocks: "
                    f"{missing_stock_names}"
                )
        return self


class IncludesConfig(BaseModel):
    time: str
    dimensions: str | None = None
    mfa_graph: str | None = None
    regions: str | None = None
    materials: str | None = None
    applications: str | None = None
    end_use: str | None = None
    end_uses: str | None = None
    stages: str | None = None
    qualities: str | None = None
    trade: str | None = None
    coupling: str
    indicators: str
    variables: str
    scenarios: str | None = None

    @model_validator(mode="after")
    def _validate_split_include_options(self) -> "IncludesConfig":
        has_dims = self.dimensions is not None
        has_dims_split = self.regions is not None and self.materials is not None and (
            self.applications is not None or self.end_use is not None or self.end_uses is not None
        )
        if not has_dims and not has_dims_split:
            raise ValueError(
                "IncludesConfig requires either 'dimensions' or split "
                "'regions'+'materials'+('applications' or 'end_use' or 'end_uses') includes."
            )

        has_graph = self.mfa_graph is not None
        has_graph_split = self.stages is not None
        if not has_graph and not has_graph_split:
            raise ValueError("IncludesConfig requires either 'mfa_graph' or 'stages' include.")

        return self


class ScenarioDimensionOverride(BaseModel):
    name: Optional[str] = None
    materials: Optional[List[str]] = None
    regions: Optional[List[str]] = None
    strategy: Optional[StrategyConfig | Dict[str, Any]] = None
    transition_policy: Optional[TransitionPolicyConfig | Dict[str, Any]] = None
    demand_transformation: Optional[DemandTransformationConfig | Dict[str, Any]] = None
    shocks: Optional[ShocksConfig] = None
    sd_parameters: Optional[Dict[str, Any]] = None
    mfa_parameters: Optional[Dict[str, Any]] = None


class SDHeterogeneityRule(BaseModel):
    name: Optional[str] = None
    materials: Optional[List[str]] = None
    regions: Optional[List[str]] = None
    sd_parameters: Dict[str, Any] = Field(default_factory=dict)


class VariantConfig(BaseModel):
    description: Optional[str] = None
    implementation: List[str] = Field(default_factory=list)
    strategy: Optional[StrategyConfig | Dict[str, Any]] = None
    transition_policy: Optional[TransitionPolicyConfig | Dict[str, Any]] = None
    demand_transformation: Optional[DemandTransformationConfig | Dict[str, Any]] = None
    shocks: Optional[ShocksConfig] = None
    sd_parameters: Optional[Dict[str, Any]] = None
    mfa_parameters: Optional[Dict[str, Any]] = None
    dimension_overrides: List[ScenarioDimensionOverride] = Field(default_factory=list)


class RunConfig(BaseModel):
    name: str
    includes: IncludesConfig

    # Included blocks (populated by the loader)
    time: TimeConfig | None = None
    dimensions: DimensionsConfig | None = None
    mfa_graph: MFAGraphConfig | None = None
    coupling: CouplingConfig | None = None
    indicators: IndicatorsConfig | None = None
    variables: Dict[str, VariableMeta] | None = None

    # Model parameters
    sd_parameters: Dict[str, Any] = Field(default_factory=dict)
    sd_heterogeneity: List[SDHeterogeneityRule] = Field(default_factory=list)
    mfa_parameters: Dict[str, Any] = Field(default_factory=dict)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    transition_policy: TransitionPolicyConfig = Field(default_factory=TransitionPolicyConfig)
    demand_transformation: DemandTransformationConfig = Field(default_factory=DemandTransformationConfig)
    scenario_profiles: ScenarioProfilesConfig = Field(default_factory=ScenarioProfilesConfig)
    shocks: ShocksConfig = Field(default_factory=ShocksConfig)

    variants: Dict[str, VariantConfig] = Field(default_factory=lambda: {"baseline": VariantConfig()})

    @model_validator(mode="after")
    def _validate_loaded_includes(self) -> "RunConfig":
        missing = [
            k
            for k in ["time", "dimensions", "mfa_graph", "coupling", "indicators", "variables"]
            if getattr(self, k) is None
        ]
        if missing:
            raise ValueError(
                "Included configs were not loaded into RunConfig. Missing: " + ", ".join(missing)
            )
        if "baseline" not in self.variants:
            self.variants["baseline"] = VariantConfig()
        return self
