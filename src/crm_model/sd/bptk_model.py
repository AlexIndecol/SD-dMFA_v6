from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pandas as pd

from BPTK_Py import Model
from BPTK_Py import sd_functions as sd


@dataclass
class SDTimeseries:
    years: List[int]
    demand: pd.Series
    price: pd.Series
    scarcity_multiplier: pd.Series
    scarcity_multiplier_effective: pd.Series
    capacity_envelope: pd.Series
    flow_utilization: pd.Series
    bottleneck_pressure: pd.Series
    collection_bottleneck_throttle: pd.Series
    collection_multiplier_target: pd.Series
    collection_multiplier: pd.Series
    strategic_fill_intent: pd.Series
    strategic_release_intent: pd.Series


class DemandModel(Model):
    """Minimal SD model (BPTK-Py) driven by an exogenous desired-demand series.

    Demand response is *calendar-switched*:
    - before `demand_response_start_year`: price elasticity = 0 (demand follows exogenous input)
    - from `demand_response_start_year`: price elasticity can reduce demand as price increases

    This implements the project decision: demand response OFF in calibration, ON in reporting.
    """

    def __init__(self):
        super().__init__(starttime=0.0, stoptime=1.0, dt=1.0, name="DemandModel")

        t = self.converter("t")
        t.equation = sd.time()

        start_year = self.constant("start_year")
        demand_response_start_year = self.constant("demand_response_start_year")

        start_year.equation = 0.0
        demand_response_start_year.equation = 0.0

        current_year = self.converter("current_year")
        current_year.equation = start_year + t

        price_base = self.converter("price_base")
        scarcity_multiplier = self.converter("scarcity_multiplier")
        price_scarcity_sensitivity = self.converter("price_scarcity_sensitivity")
        demand_price_elasticity = self.converter("demand_price_elasticity")
        capacity_envelope_initial = self.constant("capacity_envelope_initial")
        capacity_envelope_min = self.converter("capacity_envelope_min")
        capacity_envelope_max = self.converter("capacity_envelope_max")
        capacity_expansion_gain = self.converter("capacity_expansion_gain")
        capacity_retirement_gain = self.converter("capacity_retirement_gain")
        capacity_adjustment_lag_years = self.converter("capacity_adjustment_lag_years")
        capacity_pressure_shortage_weight = self.converter("capacity_pressure_shortage_weight")
        bottleneck_scarcity_gain = self.converter("bottleneck_scarcity_gain")
        bottleneck_collection_sensitivity = self.converter("bottleneck_collection_sensitivity")

        surge_start = self.constant("demand_surge_start")
        surge_duration = self.constant("demand_surge_duration")
        surge_multiplier = self.constant("demand_surge_multiplier")
        collection_shock_start = self.constant("collection_shock_start")
        collection_shock_duration = self.constant("collection_shock_duration")
        collection_shock_multiplier = self.constant("collection_shock_multiplier")
        collection_price_response_gain = self.converter("collection_price_response_gain")
        collection_multiplier_min = self.converter("collection_multiplier_min")
        collection_multiplier_max = self.converter("collection_multiplier_max")
        collection_multiplier_lag_years = self.converter("collection_multiplier_lag_years")
        strategic_reserve_enabled = self.converter("strategic_reserve_enabled")
        strategic_reserve_target_coverage_years = self.converter("strategic_reserve_target_coverage_years")
        strategic_reserve_fill_gain = self.converter("strategic_reserve_fill_gain")
        strategic_reserve_release_gain = self.converter("strategic_reserve_release_gain")
        strategic_reserve_max_fill_rate = self.converter("strategic_reserve_max_fill_rate")
        strategic_reserve_max_release_rate = self.converter("strategic_reserve_max_release_rate")
        strategic_reserve_fill_price_threshold = self.converter("strategic_reserve_fill_price_threshold")
        strategic_reserve_release_price_threshold = self.converter("strategic_reserve_release_price_threshold")
        strategic_reserve_fill_service_threshold = self.converter("strategic_reserve_fill_service_threshold")
        strategic_reserve_release_service_threshold = self.converter("strategic_reserve_release_service_threshold")

        price_base.equation = sd.lookup(t, "price_base")
        scarcity_multiplier.equation = sd.lookup(t, "scarcity_multiplier")
        price_scarcity_sensitivity.equation = sd.lookup(t, "price_scarcity_sensitivity")
        demand_price_elasticity.equation = sd.lookup(t, "demand_price_elasticity")
        capacity_envelope_initial.equation = 1.0
        capacity_envelope_min.equation = sd.lookup(t, "capacity_envelope_min")
        capacity_envelope_max.equation = sd.lookup(t, "capacity_envelope_max")
        capacity_expansion_gain.equation = sd.lookup(t, "capacity_expansion_gain")
        capacity_retirement_gain.equation = sd.lookup(t, "capacity_retirement_gain")
        capacity_adjustment_lag_years.equation = sd.lookup(t, "capacity_adjustment_lag_years")
        capacity_pressure_shortage_weight.equation = sd.lookup(t, "capacity_pressure_shortage_weight")
        bottleneck_scarcity_gain.equation = sd.lookup(t, "bottleneck_scarcity_gain")
        bottleneck_collection_sensitivity.equation = sd.lookup(t, "bottleneck_collection_sensitivity")

        surge_start.equation = -1.0
        surge_duration.equation = 0.0
        surge_multiplier.equation = 1.0
        collection_shock_start.equation = -1.0
        collection_shock_duration.equation = 0.0
        collection_shock_multiplier.equation = 1.0
        collection_price_response_gain.equation = sd.lookup(t, "collection_price_response_gain")
        collection_multiplier_min.equation = sd.lookup(t, "collection_multiplier_min")
        collection_multiplier_max.equation = sd.lookup(t, "collection_multiplier_max")
        collection_multiplier_lag_years.equation = sd.lookup(t, "collection_multiplier_lag_years")
        strategic_reserve_enabled.equation = sd.lookup(t, "strategic_reserve_enabled")
        strategic_reserve_target_coverage_years.equation = sd.lookup(
            t, "strategic_reserve_target_coverage_years"
        )
        strategic_reserve_fill_gain.equation = sd.lookup(t, "strategic_reserve_fill_gain")
        strategic_reserve_release_gain.equation = sd.lookup(t, "strategic_reserve_release_gain")
        strategic_reserve_max_fill_rate.equation = sd.lookup(t, "strategic_reserve_max_fill_rate")
        strategic_reserve_max_release_rate.equation = sd.lookup(t, "strategic_reserve_max_release_rate")
        strategic_reserve_fill_price_threshold.equation = sd.lookup(
            t, "strategic_reserve_fill_price_threshold"
        )
        strategic_reserve_release_price_threshold.equation = sd.lookup(
            t, "strategic_reserve_release_price_threshold"
        )
        strategic_reserve_fill_service_threshold.equation = sd.lookup(
            t, "strategic_reserve_fill_service_threshold"
        )
        strategic_reserve_release_service_threshold.equation = sd.lookup(
            t, "strategic_reserve_release_service_threshold"
        )

        demand_exogenous = self.converter("demand_exogenous")
        demand_exogenous.equation = sd.lookup(t, "demand_exogenous")
        strategic_stock_coverage_years = self.converter("strategic_stock_coverage_years")
        strategic_stock_coverage_years.equation = sd.lookup(t, "strategic_stock_coverage_years")
        service_stress_signal = self.converter("service_stress_signal")
        service_stress_signal.equation = sd.lookup(t, "service_stress_signal")

        demand_shock_mult = self.converter("demand_shock_mult")
        demand_shock_mult.equation = sd.If(
            sd.And(t >= surge_start, t < (surge_start + surge_duration)),
            surge_multiplier,
            1.0,
        )
        collection_shock_mult = self.converter("collection_shock_mult")
        collection_shock_mult.equation = sd.If(
            sd.And(t >= collection_shock_start, t < (collection_shock_start + collection_shock_duration)),
            collection_shock_multiplier,
            1.0,
        )

        demand_desired = self.converter("demand_desired")
        demand_desired.equation = demand_exogenous * demand_shock_mult

        price_ratio = self.converter("price_ratio")
        price_ratio.equation = 1.0

        capacity_target_raw = self.converter("capacity_target_raw")
        capacity_target = self.converter("capacity_target")
        capacity_envelope = self.converter("capacity_envelope")
        flow_capacity = self.converter("flow_capacity")
        flow_utilization = self.converter("flow_utilization")
        bottleneck_pressure = self.converter("bottleneck_pressure")
        collection_bottleneck_throttle = self.converter("collection_bottleneck_throttle")
        scarcity_multiplier_effective = self.converter("scarcity_multiplier_effective")
        capacity_pressure = self.converter("capacity_pressure")

        capacity_target_raw.equation = (
            1.0
            + capacity_expansion_gain * capacity_pressure
            - capacity_retirement_gain * sd.max(0.0, 1.0 - price_ratio)
        )
        capacity_target.equation = sd.min(
            capacity_envelope_max,
            sd.max(capacity_envelope_min, capacity_target_raw),
        )
        capacity_envelope.equation = sd.smooth(
            self,
            capacity_target,
            sd.max(capacity_adjustment_lag_years, 1.0e-6),
            capacity_envelope_initial,
        )
        flow_capacity.equation = sd.max(1.0e-12, demand_exogenous * sd.max(capacity_envelope, 1.0e-6))
        flow_utilization.equation = demand_desired / flow_capacity
        bottleneck_pressure.equation = sd.max(0.0, flow_utilization - 1.0)
        collection_bottleneck_throttle.equation = 1.0 / (
            1.0 + bottleneck_collection_sensitivity * bottleneck_pressure
        )
        scarcity_multiplier_effective.equation = scarcity_multiplier * (
            1.0 + bottleneck_scarcity_gain * bottleneck_pressure
        )

        price = self.converter("price")
        price.equation = price_base * (
            1.0 + price_scarcity_sensitivity * (scarcity_multiplier_effective - 1.0)
        )
        price_ratio.equation = price / sd.max(price_base, 1.0e-12)
        capacity_pressure.equation = (
            capacity_pressure_shortage_weight * bottleneck_pressure
            + (1.0 - capacity_pressure_shortage_weight) * sd.max(0.0, price_ratio - 1.0)
        )

        demand_price_elasticity_eff = self.converter("demand_price_elasticity_eff")
        demand_price_elasticity_eff.equation = sd.If(
            current_year < demand_response_start_year,
            0.0,
            demand_price_elasticity,
        )

        demand = self.converter("demand")
        demand.equation = demand_desired * sd.max(
            0.0, 1.0 - demand_price_elasticity_eff * (price_ratio - 1.0)
        )

        # SD-native collection-pressure channel.
        collection_multiplier_target_raw = self.converter("collection_multiplier_target_raw")
        collection_multiplier_target_raw.equation = (
            1.0 + collection_price_response_gain * sd.max(0.0, price_ratio - 1.0)
        ) * collection_shock_mult * collection_bottleneck_throttle

        collection_multiplier_target = self.converter("collection_multiplier_target")
        collection_multiplier_target.equation = sd.min(
            collection_multiplier_max,
            sd.max(collection_multiplier_min, collection_multiplier_target_raw),
        )

        collection_multiplier = self.converter("collection_multiplier")
        collection_multiplier.equation = sd.If(
            collection_multiplier_lag_years <= 0.0,
            collection_multiplier_target,
            sd.smooth(
                self,
                collection_multiplier_target,
                sd.max(collection_multiplier_lag_years, 1.0e-6),
                1.0,
            ),
        )

        # Strategic reserve policy intents driven by SD signals.

        strategic_coverage_gap = self.converter("strategic_coverage_gap")
        strategic_coverage_gap.equation = sd.max(
            0.0,
            strategic_reserve_target_coverage_years - strategic_stock_coverage_years,
        )

        strategic_fill_active = self.converter("strategic_fill_active")
        strategic_fill_active.equation = sd.If(
            sd.And(
                price_ratio <= strategic_reserve_fill_price_threshold,
                service_stress_signal <= strategic_reserve_fill_service_threshold,
            ),
            1.0,
            0.0,
        )

        strategic_fill_intent_raw = self.converter("strategic_fill_intent_raw")
        strategic_fill_intent_raw.equation = strategic_reserve_fill_gain * strategic_coverage_gap

        strategic_fill_intent = self.converter("strategic_fill_intent")
        strategic_fill_intent.equation = sd.If(
            strategic_reserve_enabled <= 0.0,
            0.0,
            sd.min(
                1.0,
                sd.max(
                    0.0,
                    sd.If(
                        strategic_fill_active > 0.0,
                        sd.min(strategic_reserve_max_fill_rate, strategic_fill_intent_raw),
                        0.0,
                    ),
                ),
            ),
        )

        strategic_emergency_pressure = self.converter("strategic_emergency_pressure")
        strategic_emergency_pressure.equation = sd.max(
            0.0,
            sd.max(
                service_stress_signal - strategic_reserve_release_service_threshold,
                price_ratio - strategic_reserve_release_price_threshold,
            ),
        )

        strategic_release_intent_raw = self.converter("strategic_release_intent_raw")
        strategic_release_intent_raw.equation = strategic_reserve_release_gain * strategic_emergency_pressure

        strategic_release_intent = self.converter("strategic_release_intent")
        strategic_release_intent.equation = sd.If(
            strategic_reserve_enabled <= 0.0,
            0.0,
            sd.min(
                1.0,
                sd.max(
                    0.0,
                    sd.min(strategic_reserve_max_release_rate, strategic_release_intent_raw),
                ),
            ),
        )



__all__ = ["SDTimeseries", "DemandModel"]
