from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Dict, List

import numpy as np
import pandas as pd

from flodym import MFASystem


@dataclass
class MFATimeseries:
    years: List[int]

    service_demand: pd.Series
    delivered_service: pd.Series
    unmet_service: pd.Series
    service_level: pd.Series

    primary_supply: pd.Series
    primary_refined_net_imports: pd.Series
    primary_available_to_refining: pd.Series
    secondary_supply: pd.Series

    inflow_to_use_total: pd.Series
    inflow_to_use_new: pd.Series
    inflow_to_use_reman: pd.Series
    outflow_from_use: pd.Series
    stock_in_use: pd.Series

    eol_generated: pd.Series
    eol_collected: pd.Series
    eol_recycled: pd.Series
    eol_remanufactured: pd.Series
    eol_disposal: pd.Series
    eol_uncollected: pd.Series

    fabrication_losses: pd.Series
    new_scrap_generated: pd.Series
    new_scrap_to_secondary: pd.Series
    new_scrap_to_residue: pd.Series

    old_scrap_generated: pd.Series
    old_scrap_collected: pd.Series
    old_scrap_uncollected: pd.Series

    recycling_process_losses: pd.Series
    recycling_surplus_unused: pd.Series

    refinery_stockpile_inflow: pd.Series
    refinery_stockpile_outflow: pd.Series
    refinery_stockpile_stock: pd.Series

    strategic_inventory_inflow: pd.Series
    strategic_inventory_outflow: pd.Series
    strategic_inventory_stock: pd.Series
    strategic_stock_coverage_years: pd.Series
    strategic_fill_intent: pd.Series
    strategic_release_intent: pd.Series

    remanufacture_process_losses: pd.Series
    remanufacture_surplus_unused: pd.Series

    extraction_losses: pd.Series
    beneficiation_losses: pd.Series
    refining_losses: pd.Series
    sorting_rejects_to_disposal: pd.Series
    sorting_rejects_to_sysenv: pd.Series

    mass_balance_residual_max_abs: pd.Series


class SimpleMetalCycleWithReman(MFASystem):
    """dMFA skeleton with explicit scrap split, operational stockpile, and strategic reserve."""

    role_map: Dict[str, str] = {}
    end_use_dim_letter: str = "e"
    USE_STOCK_NAME: ClassVar[str] = "stock_in_use"
    REFINERY_STOCKPILE_STOCK_NAME: ClassVar[str] = "refinery_stockpile_native"
    STRATEGIC_INVENTORY_STOCK_NAME: ClassVar[str] = "strategic_inventory_native"

    def _param_t(self, name: str, default: float) -> np.ndarray:
        t_len = len(self.dims["t"].items)
        if name not in self.parameters:
            return np.array([float(default)] * t_len, dtype=float)
        values = self.parameters[name].values.astype(float).reshape(-1)
        if values.size != t_len:
            raise ValueError(f"{name} must have length {t_len}; got {values.size}")
        return values

    def compute(self):
        years = list(self.dims["t"].items)
        t_len = len(years)

        service_demand = self.parameters["service_demand"].values.astype(float)  # (t,r,e)

        fab_yield = self.parameters["fabrication_yield"].values.astype(float)  # (t,)
        collection = self.parameters["collection_rate"].values.astype(float)  # (t,)
        rec_yield = self.parameters["recycling_yield"].values.astype(float)  # (t,)
        recycling_rate = self.parameters["recycling_rate"].values.astype(float)  # (t,)
        remanufacturing_rate = self.parameters["remanufacturing_rate"].values.astype(float)  # (t,)
        disposal_rate = self.parameters["disposal_rate"].values.astype(float)  # (t,)
        reman_eligibility = self.parameters["remanufacturing_end_use_eligibility"].values.astype(float)  # (t,r,e)
        reman_yield = self.parameters["reman_yield"].values.astype(float)  # (t,)
        stockpile_release_rate = self.parameters["refinery_stockpile_release_rate"].values.astype(float)  # (t,)
        new_scrap_to_secondary_share = self.parameters["new_scrap_to_secondary_share"].values.astype(float)  # (t,)
        strategic_reserve_enabled = self._param_t("strategic_reserve_enabled", 0.0)
        strategic_fill_intent = self._param_t("strategic_fill_intent", 0.0)
        strategic_release_intent = self._param_t("strategic_release_intent", 0.0)

        if "primary_available_to_refining" in self.parameters:
            primary_available = self.parameters["primary_available_to_refining"].values.astype(float)  # (t,r)
        else:
            raise ValueError(
                "Missing required primary availability parameter. Expected "
                "'primary_available_to_refining'."
            )

        if "primary_refined_net_imports" in self.parameters:
            primary_refined_net_imports = self.parameters["primary_refined_net_imports"].values.astype(float)
        else:
            primary_refined_net_imports = np.zeros_like(primary_available)

        # Stage yields/loss routing: explicit and exogenous.
        extraction_yield = self._param_t("extraction_yield", 1.0)
        beneficiation_yield = self._param_t("beneficiation_yield", 1.0)
        refining_yield = self._param_t("refining_yield", 1.0)
        sorting_yield = self._param_t("sorting_yield", 1.0)
        extraction_loss_to_sysenv_share = self._param_t("extraction_loss_to_sysenv_share", 1.0)
        beneficiation_loss_to_sysenv_share = self._param_t("beneficiation_loss_to_sysenv_share", 1.0)
        refining_loss_to_sysenv_share = self._param_t("refining_loss_to_sysenv_share", 1.0)
        sorting_reject_to_disposal_share = self._param_t("sorting_reject_to_disposal_share", 1.0)
        sorting_reject_to_sysenv_share = self._param_t("sorting_reject_to_sysenv_share", 0.0)

        mass_balance_tolerance = float(self.parameters["mass_balance_tolerance"].values[0])

        if "lifetime_pdf" not in self.parameters:
            raise ValueError("Missing required parameter 'lifetime_pdf' (t,r,e,a)")
        lifetime_pdf = self.parameters["lifetime_pdf"].values.astype(float)  # (t,r,e,a)

        r_len = len(self.dims["r"].items)
        e_len = len(self.dims[self.end_use_dim_letter].items)
        a_len = lifetime_pdf.shape[3]
        eps = 1.0e-12

        primary_used = np.zeros((t_len, r_len, e_len))
        primary_diverted_to_strategic = np.zeros((t_len, r_len, e_len))
        primary_total_withdrawn = np.zeros((t_len, r_len, e_len))
        secondary_used = np.zeros((t_len, r_len, e_len))
        secondary_diverted_to_strategic = np.zeros((t_len, r_len, e_len))
        strategic_release_to_fabrication = np.zeros((t_len, r_len, e_len))

        inflow_total = np.zeros((t_len, r_len, e_len))
        inflow_new = np.zeros((t_len, r_len, e_len))
        inflow_reman = np.zeros((t_len, r_len, e_len))

        outflow_use = np.zeros((t_len, r_len, e_len))

        old_scrap_generated = np.zeros((t_len, r_len, e_len))
        old_scrap_collected = np.zeros((t_len, r_len, e_len))
        old_scrap_uncollected = np.zeros((t_len, r_len, e_len))

        collection_to_reman = np.zeros((t_len, r_len, e_len))
        collection_to_recycling = np.zeros((t_len, r_len, e_len))
        collection_to_disposal = np.zeros((t_len, r_len, e_len))

        sorting_to_recycling = np.zeros((t_len, r_len, e_len))
        sorting_reject_to_disposal = np.zeros((t_len, r_len, e_len))
        sorting_reject_to_sysenv = np.zeros((t_len, r_len, e_len))

        reman_to_use = np.zeros((t_len, r_len, e_len))
        reman_loss = np.zeros((t_len, r_len, e_len))
        reman_surplus = np.zeros((t_len, r_len, e_len))

        recycled_secondary = np.zeros((t_len, r_len, e_len))
        recycling_loss = np.zeros((t_len, r_len, e_len))
        recycling_surplus = np.zeros((t_len, r_len, e_len))

        fabrication_loss = np.zeros((t_len, r_len, e_len))
        new_scrap_generated = np.zeros((t_len, r_len, e_len))
        new_scrap_to_secondary = np.zeros((t_len, r_len, e_len))
        new_scrap_to_residue = np.zeros((t_len, r_len, e_len))

        # Upstream chain reconstruction from refining anchor.
        refining_input_primary = np.zeros((t_len, r_len, e_len))
        beneficiation_input_required = np.zeros((t_len, r_len, e_len))
        beneficiation_output_required = np.zeros((t_len, r_len, e_len))
        extraction_input_required = np.zeros((t_len, r_len, e_len))
        extraction_output_required = np.zeros((t_len, r_len, e_len))

        extraction_losses = np.zeros((t_len, r_len, e_len))
        beneficiation_losses = np.zeros((t_len, r_len, e_len))
        refining_losses = np.zeros((t_len, r_len, e_len))

        extraction_losses_to_sysenv = np.zeros((t_len, r_len, e_len))
        extraction_losses_to_disposal = np.zeros((t_len, r_len, e_len))
        beneficiation_losses_to_sysenv = np.zeros((t_len, r_len, e_len))
        beneficiation_losses_to_disposal = np.zeros((t_len, r_len, e_len))
        refining_losses_to_sysenv = np.zeros((t_len, r_len, e_len))
        refining_losses_to_disposal = np.zeros((t_len, r_len, e_len))

        stockpile_inflow = np.zeros((t_len, r_len, e_len))
        stockpile_outflow = np.zeros((t_len, r_len, e_len))
        stockpile_stock = np.zeros((t_len, r_len, e_len))
        strategic_inventory_inflow = np.zeros((t_len, r_len, e_len))
        strategic_inventory_outflow = np.zeros((t_len, r_len, e_len))
        strategic_inventory_stock = np.zeros((t_len, r_len, e_len))

        unmet_service = np.zeros((t_len, r_len, e_len))
        stockpile_state = np.zeros((r_len, e_len), dtype=float)
        strategic_inventory_state = np.zeros((r_len, e_len), dtype=float)

        if (fab_yield <= 0).any() or (fab_yield > 1).any():
            raise ValueError("fabrication_yield must be in (0, 1].")
        for name, arr in {
            "collection_rate": collection,
            "recycling_yield": rec_yield,
            "recycling_rate": recycling_rate,
            "remanufacturing_rate": remanufacturing_rate,
            "disposal_rate": disposal_rate,
            "reman_yield": reman_yield,
            "refinery_stockpile_release_rate": stockpile_release_rate,
            "new_scrap_to_secondary_share": new_scrap_to_secondary_share,
            "strategic_reserve_enabled": strategic_reserve_enabled,
            "strategic_fill_intent": strategic_fill_intent,
            "strategic_release_intent": strategic_release_intent,
            "extraction_yield": extraction_yield,
            "beneficiation_yield": beneficiation_yield,
            "refining_yield": refining_yield,
            "sorting_yield": sorting_yield,
            "extraction_loss_to_sysenv_share": extraction_loss_to_sysenv_share,
            "beneficiation_loss_to_sysenv_share": beneficiation_loss_to_sysenv_share,
            "refining_loss_to_sysenv_share": refining_loss_to_sysenv_share,
            "sorting_reject_to_disposal_share": sorting_reject_to_disposal_share,
            "sorting_reject_to_sysenv_share": sorting_reject_to_sysenv_share,
        }.items():
            if (arr < 0).any() or (arr > 1).any():
                raise ValueError(f"{name} must be in [0, 1].")

        if not np.allclose(
            sorting_reject_to_disposal_share + sorting_reject_to_sysenv_share,
            1.0,
            atol=1.0e-9,
        ):
            raise ValueError(
                "sorting_reject_to_disposal_share + sorting_reject_to_sysenv_share must equal 1.0 for every year."
            )

        if reman_eligibility.shape != (t_len, r_len, e_len):
            raise ValueError(
                "remanufacturing_end_use_eligibility must have shape "
                f"(t,r,{self.end_use_dim_letter})=({t_len},{r_len},{e_len}); got {reman_eligibility.shape}"
            )
        if (reman_eligibility < 0).any() or (reman_eligibility > 1).any():
            raise ValueError("remanufacturing_end_use_eligibility must be in [0,1].")
        rate_sum = recycling_rate + remanufacturing_rate + disposal_rate
        if not np.allclose(rate_sum, 1.0, atol=1e-9):
            raise ValueError(
                "recycling_rate + remanufacturing_rate + disposal_rate must equal 1.0 for every year."
            )
        if (primary_available < 0).any():
            raise ValueError("primary_available_to_refining must be >= 0.")

        for i in range(t_len):
            # Cohort convolution (age=0 is skipped).
            for e_idx in range(e_len):
                out = np.zeros(r_len, dtype=float)
                max_age_here = min(i, a_len - 1)
                for age in range(1, max_age_here + 1):
                    c = i - age
                    out += inflow_total[c, :, e_idx] * lifetime_pdf[c, :, e_idx, age]
                outflow_use[i, :, e_idx] = out

            old_scrap_generated[i] = outflow_use[i]
            old_scrap_collected[i] = old_scrap_generated[i] * collection[i]
            old_scrap_uncollected[i] = old_scrap_generated[i] * (1.0 - collection[i])

            eff_reman_rate = remanufacturing_rate[i] * reman_eligibility[i]
            non_reman_base = recycling_rate[i] + disposal_rate[i]
            remaining_share = 1.0 - eff_reman_rate
            rec_split = (recycling_rate[i] / non_reman_base) if non_reman_base > 1.0e-12 else 1.0
            eff_recycling_rate = remaining_share * rec_split
            eff_disposal_rate = remaining_share - eff_recycling_rate

            collection_to_reman[i] = old_scrap_collected[i] * eff_reman_rate
            collection_to_recycling[i] = old_scrap_collected[i] * eff_recycling_rate
            collection_to_disposal[i] = old_scrap_collected[i] * eff_disposal_rate

            reman_to_use[i] = collection_to_reman[i] * reman_yield[i]
            reman_loss[i] = collection_to_reman[i] * (1.0 - reman_yield[i])

            # Sorting stage before recycling.
            sort_input = collection_to_recycling[i]
            sort_pass = sort_input * sorting_yield[i]
            sort_reject = sort_input - sort_pass
            sorting_to_recycling[i] = sort_pass
            sorting_reject_to_disposal[i] = sort_reject * sorting_reject_to_disposal_share[i]
            sorting_reject_to_sysenv[i] = sort_reject * sorting_reject_to_sysenv_share[i]

            recycled_secondary[i] = sorting_to_recycling[i] * rec_yield[i]
            recycling_loss[i] = sorting_to_recycling[i] * (1.0 - rec_yield[i])

            desired_inflow = service_demand[i]

            reman_direct = reman_to_use[i]
            reman_direct_used = np.minimum(reman_direct, desired_inflow)
            inflow_reman[i] = reman_direct_used
            reman_surplus[i] = np.maximum(reman_direct - reman_direct_used, 0.0)

            remaining_for_new = np.maximum(desired_inflow - inflow_reman[i], 0.0)
            required_input = remaining_for_new / np.maximum(fab_yield[i], eps)

            available_for_secondary = stockpile_state + recycled_secondary[i]
            secondary_release_cap = available_for_secondary * stockpile_release_rate[i]

            reserve_on = strategic_reserve_enabled[i] > 0.5
            fill_intent_i = strategic_fill_intent[i] if reserve_on else 0.0
            release_intent_i = strategic_release_intent[i] if reserve_on else 0.0
            strategic_fill_desired = np.maximum(fill_intent_i * required_input, 0.0)

            secondary_diverted_to_strategic[i] = np.minimum(secondary_release_cap, strategic_fill_desired)
            remaining_secondary_cap = np.maximum(secondary_release_cap - secondary_diverted_to_strategic[i], 0.0)
            secondary_used[i] = np.minimum(remaining_secondary_cap, required_input)

            remaining_input = np.maximum(required_input - secondary_used[i], 0.0)
            cap = primary_available[i]

            fill_need_after_secondary = np.maximum(
                strategic_fill_desired - secondary_diverted_to_strategic[i],
                0.0,
            )
            fill_need_total = fill_need_after_secondary.sum(axis=1)
            fill_share = np.zeros_like(fill_need_after_secondary)
            for r_idx in range(r_len):
                if fill_need_total[r_idx] > 0:
                    fill_share[r_idx, :] = fill_need_after_secondary[r_idx, :] / fill_need_total[r_idx]

            primary_diverted_total = np.minimum(cap, fill_need_total)
            primary_diverted_to_strategic[i] = fill_share * primary_diverted_total[:, None]

            remaining_primary_cap = np.maximum(cap - primary_diverted_total, 0.0)
            need_total = remaining_input.sum(axis=1)

            share = np.zeros_like(remaining_input)
            for r_idx in range(r_len):
                if need_total[r_idx] > 0:
                    share[r_idx, :] = remaining_input[r_idx, :] / need_total[r_idx]

            primary_total_used_for_demand = np.minimum(remaining_primary_cap, need_total)
            primary_used[i] = share * primary_total_used_for_demand[:, None]
            primary_total_withdrawn[i] = primary_used[i] + primary_diverted_to_strategic[i]

            input_shortfall = np.maximum(required_input - (secondary_used[i] + primary_used[i]), 0.0)
            strategic_release_cap = np.maximum(release_intent_i * strategic_inventory_state, 0.0)
            strategic_release_to_fabrication[i] = np.minimum(strategic_release_cap, input_shortfall)
            strategic_inventory_inflow[i] = secondary_diverted_to_strategic[i] + primary_diverted_to_strategic[i]
            strategic_inventory_outflow[i] = strategic_release_to_fabrication[i]
            strategic_inventory_state = np.maximum(
                strategic_inventory_state + strategic_inventory_inflow[i] - strategic_inventory_outflow[i],
                0.0,
            )
            strategic_inventory_stock[i] = strategic_inventory_state

            stockpile_outflow[i] = secondary_used[i] + secondary_diverted_to_strategic[i]

            # Upstream chain reconstruction from refining anchor.
            ry = max(refining_yield[i], eps)
            by = max(beneficiation_yield[i], eps)
            ey = max(extraction_yield[i], eps)

            refining_input_primary[i] = primary_total_withdrawn[i] / ry
            refining_losses[i] = refining_input_primary[i] - primary_total_withdrawn[i]

            beneficiation_output_required[i] = refining_input_primary[i]
            beneficiation_input_required[i] = beneficiation_output_required[i] / by
            beneficiation_losses[i] = beneficiation_input_required[i] - beneficiation_output_required[i]

            extraction_output_required[i] = beneficiation_input_required[i]
            extraction_input_required[i] = extraction_output_required[i] / ey
            extraction_losses[i] = extraction_input_required[i] - extraction_output_required[i]

            extraction_losses_to_sysenv[i] = extraction_losses[i] * extraction_loss_to_sysenv_share[i]
            extraction_losses_to_disposal[i] = extraction_losses[i] - extraction_losses_to_sysenv[i]
            beneficiation_losses_to_sysenv[i] = (
                beneficiation_losses[i] * beneficiation_loss_to_sysenv_share[i]
            )
            beneficiation_losses_to_disposal[i] = (
                beneficiation_losses[i] - beneficiation_losses_to_sysenv[i]
            )
            refining_losses_to_sysenv[i] = refining_losses[i] * refining_loss_to_sysenv_share[i]
            refining_losses_to_disposal[i] = refining_losses[i] - refining_losses_to_sysenv[i]

            total_input_used = primary_used[i] + secondary_used[i] + strategic_release_to_fabrication[i]

            # New scrap is the pre-use process loss from fabrication.
            fabrication_loss[i] = total_input_used * (1.0 - fab_yield[i])
            new_scrap_generated[i] = fabrication_loss[i]
            new_scrap_to_secondary[i] = new_scrap_generated[i] * new_scrap_to_secondary_share[i]
            new_scrap_to_residue[i] = new_scrap_generated[i] - new_scrap_to_secondary[i]

            stockpile_inflow[i] = recycled_secondary[i] + new_scrap_to_secondary[i]
            stockpile_state = np.maximum(stockpile_state + stockpile_inflow[i] - stockpile_outflow[i], 0.0)
            stockpile_stock[i] = stockpile_state

            produced_new = total_input_used * fab_yield[i]
            inflow_new[i] = np.minimum(produced_new, remaining_for_new)

            inflow_total[i] = inflow_reman[i] + inflow_new[i]
            unmet_service[i] = np.maximum(desired_inflow - inflow_total[i], 0.0)

            recycling_surplus[i] = 0.0

        if not getattr(self, "role_map", None):
            raise ValueError("SimpleMetalCycleWithReman.role_map not set. This is a configuration/build error.")

        src = self.role_map["source"]
        fab = self.role_map["fabrication"]
        use = self.role_map["use_stock"]
        col = self.role_map["collection"]
        rem = self.role_map["remanufacture"]
        rec = self.role_map["recycling"]
        disp = self.role_map["disposal"]
        eol = self.role_map.get("end_of_life")
        sort = self.role_map.get("sorting_preprocessing")
        refining = self.role_map.get("refining")
        primary_extraction = self.role_map.get("primary_extraction")
        beneficiation = self.role_map.get("beneficiation_concentration")

        if refining is not None:
            if primary_extraction is not None and beneficiation is not None:
                self.flows[f"{src} => {primary_extraction}"].values = extraction_input_required
                self.flows[f"{primary_extraction} => {beneficiation}"].values = extraction_output_required
                self.flows[f"{beneficiation} => {refining}"].values = beneficiation_output_required
            else:
                self.flows[f"{src} => {refining}"].values = refining_input_primary

            self.flows[f"{rec} => {refining}"].values = recycled_secondary
            if f"{fab} => {refining}" in self.flows:
                self.flows[f"{fab} => {refining}"].values = new_scrap_to_secondary
            self.flows[f"{refining} => {fab}"].values = (
                primary_used + secondary_used + strategic_release_to_fabrication
            )
        else:
            self.flows[f"{src} => {fab}"].values = primary_used
            self.flows[f"{rec} => {fab}"].values = secondary_used + strategic_release_to_fabrication

        self.flows[f"{fab} => {use}"].values = inflow_new
        self.flows[f"{fab} => {src}"].values = new_scrap_to_residue

        if eol is not None:
            self.flows[f"{use} => {eol}"].values = outflow_use
            self.flows[f"{eol} => {col}"].values = old_scrap_collected
            self.flows[f"{eol} => {src}"].values = old_scrap_uncollected
        else:
            self.flows[f"{use} => {col}"].values = old_scrap_collected
            self.flows[f"{use} => {src}"].values = old_scrap_uncollected

        self.flows[f"{col} => {rem}"].values = collection_to_reman
        self.flows[f"{col} => {disp}"].values = collection_to_disposal
        if sort is not None:
            self.flows[f"{col} => {sort}"].values = collection_to_recycling
            self.flows[f"{sort} => {rec}"].values = sorting_to_recycling
            if f"{sort} => {disp}" in self.flows:
                self.flows[f"{sort} => {disp}"].values = sorting_reject_to_disposal
            if f"{sort} => {src}" in self.flows:
                self.flows[f"{sort} => {src}"].values = sorting_reject_to_sysenv
            elif f"{sort} => {disp}" not in self.flows:
                # Fallback when neither reject sink flow is defined.
                self.flows[f"{col} => {disp}"].values += sorting_reject_to_disposal
                self.flows[f"{rem} => {src}"].values += sorting_reject_to_sysenv
        else:
            self.flows[f"{col} => {rec}"].values = collection_to_recycling

        self.flows[f"{rem} => {use}"].values = inflow_reman
        self.flows[f"{rem} => {src}"].values = (reman_loss + reman_surplus)
        self.flows[f"{rec} => {src}"].values = (recycling_loss + recycling_surplus)

        disposal_inflow_total = (
            collection_to_disposal
            + sorting_reject_to_disposal
            + extraction_losses_to_disposal
            + beneficiation_losses_to_disposal
            + refining_losses_to_disposal
        )
        self.flows[f"{disp} => {src}"].values = disposal_inflow_total

        # Stage loss sink flows (when available).
        if primary_extraction is not None:
            if f"{primary_extraction} => {src}" in self.flows:
                self.flows[f"{primary_extraction} => {src}"].values = (
                    extraction_losses_to_sysenv
                    + np.where(
                        f"{primary_extraction} => {disp}" in self.flows,
                        0.0,
                        extraction_losses_to_disposal,
                    )
                )
            if f"{primary_extraction} => {disp}" in self.flows:
                self.flows[f"{primary_extraction} => {disp}"].values = extraction_losses_to_disposal

        if beneficiation is not None:
            if f"{beneficiation} => {src}" in self.flows:
                self.flows[f"{beneficiation} => {src}"].values = (
                    beneficiation_losses_to_sysenv
                    + np.where(
                        f"{beneficiation} => {disp}" in self.flows,
                        0.0,
                        beneficiation_losses_to_disposal,
                    )
                )
            if f"{beneficiation} => {disp}" in self.flows:
                self.flows[f"{beneficiation} => {disp}"].values = beneficiation_losses_to_disposal

        if refining is not None:
            if f"{refining} => {src}" in self.flows:
                self.flows[f"{refining} => {src}"].values = (
                    refining_losses_to_sysenv
                    + np.where(
                        f"{refining} => {disp}" in self.flows,
                        0.0,
                        refining_losses_to_disposal,
                    )
                )
            if f"{refining} => {disp}" in self.flows:
                self.flows[f"{refining} => {disp}"].values = refining_losses_to_disposal

        try:
            use_stock = self.stocks[self.USE_STOCK_NAME]
        except KeyError as exc:
            raise ValueError(
                f"Required stock '{self.USE_STOCK_NAME}' missing from MFASystem.stocks."
            ) from exc

        use_stock.inflow.values[...] = inflow_total
        use_stock.outflow.values[...] = outflow_use
        use_stock.compute()
        stock = use_stock.stock.values

        try:
            refinery_stockpile_native = self.stocks[self.REFINERY_STOCKPILE_STOCK_NAME]
        except KeyError as exc:
            raise ValueError(
                f"Required stock '{self.REFINERY_STOCKPILE_STOCK_NAME}' missing from MFASystem.stocks."
            ) from exc

        refinery_stockpile_native.inflow.values[...] = stockpile_inflow
        refinery_stockpile_native.outflow.values[...] = stockpile_outflow
        if np.any(stockpile_inflow) or np.any(stockpile_outflow):
            refinery_stockpile_native.compute()
        else:
            refinery_stockpile_native.stock.values[...] = 0.0
        stockpile_stock = refinery_stockpile_native.stock.values.copy()

        try:
            strategic_inventory_native = self.stocks[self.STRATEGIC_INVENTORY_STOCK_NAME]
        except KeyError as exc:
            raise ValueError(
                f"Required stock '{self.STRATEGIC_INVENTORY_STOCK_NAME}' missing from MFASystem.stocks."
            ) from exc

        strategic_inventory_native.inflow.values[...] = strategic_inventory_inflow
        strategic_inventory_native.outflow.values[...] = strategic_inventory_outflow
        if np.any(strategic_inventory_inflow) or np.any(strategic_inventory_outflow):
            strategic_inventory_native.compute()
        else:
            strategic_inventory_native.stock.values[...] = 0.0
        strategic_inventory_stock = strategic_inventory_native.stock.values.copy()

        delta_stock = np.zeros_like(stock)
        delta_stock[0] = stock[0]
        if t_len > 1:
            delta_stock[1:] = stock[1:] - stock[:-1]

        fabrication_residual = (
            primary_used + secondary_used + strategic_release_to_fabrication
        ) - (inflow_new + new_scrap_generated)
        use_residual = (inflow_new + inflow_reman) - (outflow_use + delta_stock)

        if eol is not None:
            eol_residual = outflow_use - (old_scrap_collected + old_scrap_uncollected)
            collection_input = old_scrap_collected
        else:
            eol_residual = np.zeros_like(outflow_use)
            collection_input = old_scrap_collected

        collection_residual = collection_input - (
            collection_to_reman + collection_to_recycling + collection_to_disposal
        )
        if sort is not None:
            sorting_residual = collection_to_recycling - (
                sorting_to_recycling + sorting_reject_to_disposal + sorting_reject_to_sysenv
            )
            recycling_input = sorting_to_recycling
        else:
            sorting_residual = np.zeros_like(collection_to_recycling)
            recycling_input = collection_to_recycling

        reman_residual = collection_to_reman - (inflow_reman + reman_loss + reman_surplus)
        recycling_residual = recycling_input - (recycled_secondary + recycling_loss)

        stockpile_prev = np.zeros_like(stockpile_stock)
        if t_len > 1:
            stockpile_prev[1:] = stockpile_stock[:-1]
        stockpile_delta = stockpile_stock - stockpile_prev
        stockpile_residual = stockpile_inflow - (stockpile_outflow + stockpile_delta)

        strategic_prev = np.zeros_like(strategic_inventory_stock)
        if t_len > 1:
            strategic_prev[1:] = strategic_inventory_stock[:-1]
        strategic_delta = strategic_inventory_stock - strategic_prev
        strategic_residual = strategic_inventory_inflow - (
            strategic_inventory_outflow + strategic_delta
        )

        if primary_extraction is not None and beneficiation is not None:
            extraction_residual = extraction_input_required - (
                extraction_output_required + extraction_losses_to_sysenv + extraction_losses_to_disposal
            )
            beneficiation_residual = beneficiation_input_required - (
                beneficiation_output_required + beneficiation_losses_to_sysenv + beneficiation_losses_to_disposal
            )
        else:
            extraction_residual = np.zeros_like(primary_used)
            beneficiation_residual = np.zeros_like(primary_used)

        primary_refining_residual = refining_input_primary - (
            primary_total_withdrawn + refining_losses_to_sysenv + refining_losses_to_disposal
        )

        disposal_residual = disposal_inflow_total - disposal_inflow_total

        residuals = [
            fabrication_residual,
            use_residual,
            eol_residual,
            collection_residual,
            sorting_residual,
            reman_residual,
            recycling_residual,
            stockpile_residual,
            strategic_residual,
            extraction_residual,
            beneficiation_residual,
            primary_refining_residual,
            disposal_residual,
        ]
        annual_residual_max = np.max(
            np.stack([np.max(np.abs(r), axis=(1, 2)) for r in residuals], axis=1),
            axis=1,
        )
        residual_abs_max = float(np.max(annual_residual_max))
        flow_scale = max(
            1.0,
            float(np.max(np.abs(primary_used + secondary_used + strategic_release_to_fabrication))),
            float(np.max(np.abs(primary_total_withdrawn))),
            float(np.max(np.abs(inflow_new + inflow_reman))),
            float(np.max(np.abs(outflow_use))),
            float(np.max(np.abs(disposal_inflow_total + old_scrap_uncollected + new_scrap_to_residue))),
        )
        if residual_abs_max > (mass_balance_tolerance * flow_scale):
            raise ValueError(
                "Mass balance conservation check failed: "
                f"max absolute residual={residual_abs_max:.6g} exceeds tolerance="
                f"{mass_balance_tolerance:.6g} * scale={flow_scale:.6g}."
            )

        self.parameters["__stock_in_use"].values = stock
        self.parameters["__service_demand"].values = service_demand
        self.parameters["__delivered_service"].values = inflow_total
        self.parameters["__unmet_service"].values = unmet_service
        self.parameters["__primary_refined_net_imports"].values = np.repeat(
            primary_refined_net_imports[:, :, None],
            e_len,
            axis=2,
        )
        self.parameters["__primary_available_to_refining"].values = np.repeat(
            primary_available[:, :, None],
            e_len,
            axis=2,
        )
        self.parameters["__primary_supply_used"].values = primary_used
        self.parameters["__secondary_supply_used"].values = secondary_used
        self.parameters["__eol_disposal"].values = disposal_inflow_total

        self.parameters["__fabrication_losses"].values = new_scrap_generated
        self.parameters["__new_scrap_generated"].values = new_scrap_generated
        self.parameters["__new_scrap_to_secondary"].values = new_scrap_to_secondary
        self.parameters["__new_scrap_to_residue"].values = new_scrap_to_residue

        self.parameters["__old_scrap_generated"].values = old_scrap_generated
        self.parameters["__old_scrap_collected"].values = old_scrap_collected
        self.parameters["__old_scrap_uncollected"].values = old_scrap_uncollected
        self.parameters["__eol_uncollected"].values = old_scrap_uncollected

        self.parameters["__recycling_process_losses"].values = recycling_loss
        self.parameters["__recycling_surplus_unused"].values = recycling_surplus

        self.parameters["__refinery_stockpile_inflow"].values = stockpile_inflow
        self.parameters["__refinery_stockpile_outflow"].values = stockpile_outflow
        self.parameters["__refinery_stockpile_stock"].values = stockpile_stock

        strategic_coverage = np.divide(
            strategic_inventory_stock,
            np.maximum(service_demand, eps),
        )
        self.parameters["__strategic_inventory_inflow"].values = strategic_inventory_inflow
        self.parameters["__strategic_inventory_outflow"].values = strategic_inventory_outflow
        self.parameters["__strategic_inventory_stock"].values = strategic_inventory_stock
        self.parameters["__strategic_stock_coverage_years"].values = strategic_coverage
        self.parameters["__strategic_fill_intent"].values = np.repeat(
            strategic_fill_intent[:, None, None],
            r_len,
            axis=1,
        ).repeat(e_len, axis=2)
        self.parameters["__strategic_release_intent"].values = np.repeat(
            strategic_release_intent[:, None, None],
            r_len,
            axis=1,
        ).repeat(e_len, axis=2)

        self.parameters["__remanufacture_process_losses"].values = reman_loss
        self.parameters["__remanufacture_surplus_unused"].values = reman_surplus

        self.parameters["__extraction_losses"].values = extraction_losses
        self.parameters["__beneficiation_losses"].values = beneficiation_losses
        self.parameters["__refining_losses"].values = refining_losses
        self.parameters["__sorting_rejects_to_disposal"].values = sorting_reject_to_disposal
        self.parameters["__sorting_rejects_to_sysenv"].values = sorting_reject_to_sysenv

        self.parameters["__mass_balance_residual_abs_max"].values = annual_residual_max


__all__ = ["MFATimeseries", "SimpleMetalCycleWithReman"]
