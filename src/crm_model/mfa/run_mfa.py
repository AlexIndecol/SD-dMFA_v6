from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from flodym import (
    Dimension,
    DimensionSet,
    FlowDefinition,
    Parameter,
    Process,
    SimpleFlowDrivenStock,
    make_empty_flows,
)

from .dimensions import _subset_dims
from .parameters import _as_timeseries, _resolve_routing_rates
from .system import MFATimeseries, SimpleMetalCycleWithReman


def _strategy_override_with_before(strategy: Dict[str, Any], key: str, baseline: Any) -> Any:
    if key not in strategy:
        return baseline
    value = strategy.get(key)
    if isinstance(value, dict) and "start_year" in value and "value" in value and "before" not in value:
        out = dict(value)
        out["before"] = baseline
        return out
    return value


def _resolve_stockpile_release_rate(
    *,
    years: List[int],
    strategy: Dict[str, Any],
    params: Dict[str, Any],
) -> np.ndarray:
    release_rate = _strategy_override_with_before(
        strategy,
        "refinery_stockpile_release_rate",
        params.get("refinery_stockpile_release_rate"),
    )
    if release_rate is not None:
        return _as_timeseries(
            release_rate,
            years=years,
            name="refinery_stockpile_release_rate",
            default=0.25,
        )

    return _as_timeseries(
        None,
        years=years,
        name="refinery_stockpile_release_rate",
        default=0.25,
    )


def _resolve_primary_available_to_refining(
    *,
    years: List[int],
    regions: List[str],
    params: Dict[str, Any],
) -> np.ndarray:
    primary_available = params.get("primary_available_to_refining")
    if primary_available is None:
        raise ValueError(
            "mfa_params must include primary_available_to_refining with shape (t,r)."
        )

    primary_available_tr = np.array(primary_available, dtype=float)
    if primary_available_tr.ndim != 2 or primary_available_tr.shape != (len(years), len(regions)):
        raise ValueError(
            "primary_available_to_refining must have shape "
            f"(t,r)=({len(years)},{len(regions)}); got {primary_available_tr.shape}"
        )
    if (primary_available_tr < 0).any():
        raise ValueError("primary_available_to_refining must be non-negative.")
    return primary_available_tr


def _resolve_primary_refined_net_imports(
    *,
    years: List[int],
    regions: List[str],
    params: Dict[str, Any],
) -> np.ndarray:
    net = params.get("primary_refined_net_imports")
    if net is None:
        return np.zeros((len(years), len(regions)), dtype=float)

    net_tr = np.array(net, dtype=float)
    if net_tr.ndim != 2 or net_tr.shape != (len(years), len(regions)):
        raise ValueError(
            "primary_refined_net_imports must have shape "
            f"(t,r)=({len(years)},{len(regions)}); got {net_tr.shape}"
        )
    return net_tr


def run_flodym_mfa(
    years: List[int],
    regions: List[str],
    end_uses: List[str],
    service_demand_tre: np.ndarray,
    params: Dict[str, Any],
    mfa_graph: Optional[Dict[str, Any]] = None,
    *,
    strategy: Optional[Dict[str, Any]] = None,
    shocks: Optional[Dict[str, Any]] = None,
) -> Tuple[SimpleMetalCycleWithReman, MFATimeseries]:
    """Run flodym MFA for multiple regions + end-uses."""

    strategy = strategy or {}
    shocks = shocks or {}

    lifetime_pdf_trea = params.get("lifetime_pdf_trea")
    if lifetime_pdf_trea is None:
        raise ValueError("mfa_params must include lifetime_pdf_trea (t,r,e,a)")
    lifetime_pdf_trea = np.array(lifetime_pdf_trea, dtype=float)
    if lifetime_pdf_trea.ndim != 4:
        raise ValueError("lifetime_pdf_trea must have shape (t,r,e,a)")

    recycling_yield_base = _as_timeseries(
        _strategy_override_with_before(
            strategy,
            "recycling_yield",
            params.get("recycling_yield", 0.8),
        ),
        years=years,
        name="recycling_yield",
        default=0.8,
    )
    reman_yield_ts = _as_timeseries(
        _strategy_override_with_before(
            strategy,
            "reman_yield",
            params.get("reman_yield", 0.9),
        ),
        years=years,
        name="reman_yield",
        default=0.9,
    )

    collection_rate_ts = _as_timeseries(
        params.get("collection_rate", 0.4),
        years=years,
        name="collection_rate",
        default=0.4,
    )
    fabrication_yield_ts = _as_timeseries(
        params.get("fabrication_yield", 0.95),
        years=years,
        name="fabrication_yield",
        default=0.95,
    )

    recycling_rate_ts, remanufacturing_rate_ts, disposal_rate_ts = _resolve_routing_rates(
        years=years,
        strategy=strategy,
        params=params,
    )

    reman_eligibility_tre = params.get("remanufacturing_end_use_eligibility_tre")
    if reman_eligibility_tre is None:
        reman_eligibility_tre = np.ones_like(service_demand_tre, dtype=float)
    else:
        reman_eligibility_tre = np.array(reman_eligibility_tre, dtype=float)
        if reman_eligibility_tre.shape != service_demand_tre.shape:
            raise ValueError(
                "remanufacturing_end_use_eligibility_tre must have shape "
                f"{service_demand_tre.shape}; got {reman_eligibility_tre.shape}"
            )
    if (reman_eligibility_tre < 0).any() or (reman_eligibility_tre > 1).any():
        raise ValueError("remanufacturing_end_use_eligibility_tre must be in [0,1].")

    refinery_stockpile_release_rate_ts = _resolve_stockpile_release_rate(
        years=years,
        strategy=strategy,
        params=params,
    )
    new_scrap_to_secondary_share_ts = _as_timeseries(
        _strategy_override_with_before(
            strategy,
            "new_scrap_to_secondary_share",
            params.get("new_scrap_to_secondary_share", 1.0),
        ),
        years=years,
        name="new_scrap_to_secondary_share",
        default=1.0,
    )
    strategic_reserve_enabled_ts = _as_timeseries(
        _strategy_override_with_before(
            strategy,
            "strategic_reserve_enabled",
            params.get("strategic_reserve_enabled", False),
        ),
        years=years,
        name="strategic_reserve_enabled",
        default=0.0,
    )
    strategic_fill_intent_ts = _as_timeseries(
        params.get("strategic_fill_intent", 0.0),
        years=years,
        name="strategic_fill_intent",
        default=0.0,
    )
    strategic_release_intent_ts = _as_timeseries(
        params.get("strategic_release_intent", 0.0),
        years=years,
        name="strategic_release_intent",
        default=0.0,
    )
    strategic_reserve_enabled_ts = np.clip(strategic_reserve_enabled_ts, 0.0, 1.0)
    strategic_fill_intent_ts = np.clip(strategic_fill_intent_ts, 0.0, 1.0)
    strategic_release_intent_ts = np.clip(strategic_release_intent_ts, 0.0, 1.0)

    rec_disrupt = shocks.get("recycling_disruption_multiplier", 1.0)
    rec_disrupt_ts = _as_timeseries(
        rec_disrupt,
        years=years,
        name="recycling_disruption_multiplier",
        default=1.0,
    )
    rec_yield_ts = rec_disrupt_ts * recycling_yield_base

    primary_available_tr = _resolve_primary_available_to_refining(
        years=years,
        regions=regions,
        params=params,
    )
    primary_refined_net_imports_tr = _resolve_primary_refined_net_imports(
        years=years,
        regions=regions,
        params=params,
    )

    extraction_yield_ts = _as_timeseries(
        params.get("extraction_yield", 1.0),
        years=years,
        name="extraction_yield",
        default=1.0,
    )
    beneficiation_yield_ts = _as_timeseries(
        params.get("beneficiation_yield", 1.0),
        years=years,
        name="beneficiation_yield",
        default=1.0,
    )
    refining_yield_ts = _as_timeseries(
        params.get("refining_yield", 1.0),
        years=years,
        name="refining_yield",
        default=1.0,
    )
    sorting_yield_ts = _as_timeseries(
        params.get("sorting_yield", 1.0),
        years=years,
        name="sorting_yield",
        default=1.0,
    )

    extraction_loss_to_sysenv_share_ts = _as_timeseries(
        params.get("extraction_loss_to_sysenv_share", 1.0),
        years=years,
        name="extraction_loss_to_sysenv_share",
        default=1.0,
    )
    beneficiation_loss_to_sysenv_share_ts = _as_timeseries(
        params.get("beneficiation_loss_to_sysenv_share", 1.0),
        years=years,
        name="beneficiation_loss_to_sysenv_share",
        default=1.0,
    )
    refining_loss_to_sysenv_share_ts = _as_timeseries(
        params.get("refining_loss_to_sysenv_share", 1.0),
        years=years,
        name="refining_loss_to_sysenv_share",
        default=1.0,
    )
    sorting_reject_to_disposal_share_ts = _as_timeseries(
        params.get("sorting_reject_to_disposal_share", 1.0),
        years=years,
        name="sorting_reject_to_disposal_share",
        default=1.0,
    )
    sorting_reject_to_sysenv_share_ts = _as_timeseries(
        params.get("sorting_reject_to_sysenv_share", 0.0),
        years=years,
        name="sorting_reject_to_sysenv_share",
        default=0.0,
    )

    ages = list(range(lifetime_pdf_trea.shape[3]))

    def _default_graph() -> Dict[str, Any]:
        return {
            "processes": [
                {"id": 0, "name": "sysenv", "role": "source"},
                {"id": 1, "name": "fabrication", "role": "fabrication"},
                {"id": 2, "name": "use", "role": "use_stock"},
                {"id": 3, "name": "end_of_life", "role": "end_of_life"},
                {"id": 4, "name": "collection", "role": "collection"},
                {"id": 5, "name": "remanufacture", "role": "remanufacture"},
                {"id": 6, "name": "recycling", "role": "recycling"},
                {"id": 7, "name": "disposal", "role": "disposal"},
            ],
            "stocks": [
                {
                    "name": SimpleMetalCycleWithReman.USE_STOCK_NAME,
                    "process": "use",
                    "dim_letters": ["t", "r", "e"],
                    "role": "use_stock_native",
                },
                {
                    "name": SimpleMetalCycleWithReman.REFINERY_STOCKPILE_STOCK_NAME,
                    "process": "recycling",
                    "dim_letters": ["t", "r", "e"],
                    "role": "refinery_stockpile_native",
                },
                {
                    "name": SimpleMetalCycleWithReman.STRATEGIC_INVENTORY_STOCK_NAME,
                    "process": "recycling",
                    "dim_letters": ["t", "r", "e"],
                    "role": "strategic_inventory_native",
                },
            ],
            "flows": [
                {"from": "sysenv", "to": "fabrication", "dim_letters": ["t", "r", "e"]},
                {"from": "fabrication", "to": "use", "dim_letters": ["t", "r", "e"]},
                {"from": "fabrication", "to": "sysenv", "dim_letters": ["t", "r", "e"]},
                {"from": "use", "to": "end_of_life", "dim_letters": ["t", "r", "e"]},
                {"from": "end_of_life", "to": "collection", "dim_letters": ["t", "r", "e"]},
                {"from": "end_of_life", "to": "sysenv", "dim_letters": ["t", "r", "e"]},
                {"from": "collection", "to": "remanufacture", "dim_letters": ["t", "r", "e"]},
                {"from": "collection", "to": "recycling", "dim_letters": ["t", "r", "e"]},
                {"from": "collection", "to": "disposal", "dim_letters": ["t", "r", "e"]},
                {"from": "remanufacture", "to": "use", "dim_letters": ["t", "r", "e"]},
                {"from": "remanufacture", "to": "sysenv", "dim_letters": ["t", "r", "e"]},
                {"from": "recycling", "to": "fabrication", "dim_letters": ["t", "r", "e"]},
                {"from": "recycling", "to": "sysenv", "dim_letters": ["t", "r", "e"]},
                {"from": "disposal", "to": "sysenv", "dim_letters": ["t", "r", "e"]},
            ],
        }

    graph = mfa_graph or _default_graph()

    role_map: Dict[str, str] = {}
    proc_items = graph.get("processes", [])
    if not isinstance(proc_items, list):
        raise ValueError("mfa_graph.processes must be a list")
    for p in proc_items:
        if not isinstance(p, dict):
            raise ValueError("mfa_graph.processes entries must be mappings")
        role = str(p.get("role"))
        name = str(p.get("name"))
        if role in role_map:
            raise ValueError(f"Duplicate role assignment in mfa_graph: {role}")
        role_map[role] = name

    required_roles = {
        "source",
        "fabrication",
        "use_stock",
        "collection",
        "remanufacture",
        "recycling",
        "disposal",
    }
    missing_roles = sorted(list(required_roles - set(role_map.keys())))
    if missing_roles:
        raise ValueError(f"mfa_graph is missing required roles: {missing_roles}")

    processes: Dict[str, Process] = {}
    for p in proc_items:
        name = str(p.get("name"))
        pid = int(p.get("id"))
        processes[name] = Process(name=name, id=pid)

    flow_items = graph.get("flows", [])
    if not isinstance(flow_items, list):
        raise ValueError("mfa_graph.flows must be a list")

    flow_dims: Dict[Tuple[str, str], Tuple[str, ...]] = {}
    flow_defs: List[FlowDefinition] = []
    for f in flow_items:
        if not isinstance(f, dict):
            raise ValueError("mfa_graph.flows entries must be mappings")
        frm = str(f.get("from"))
        to = str(f.get("to"))
        dim_letters = f.get("dim_letters")
        if not isinstance(dim_letters, (list, tuple)) or not dim_letters:
            raise ValueError(f"Flow dim_letters must be a non-empty list for {frm} -> {to}")
        if frm not in processes:
            raise ValueError(f"Flow references unknown process in 'from': {frm}")
        if to not in processes:
            raise ValueError(f"Flow references unknown process in 'to': {to}")

        dl = tuple(str(x) for x in dim_letters)
        flow_dims[(frm, to)] = dl
        flow_defs.append(FlowDefinition(from_process_name=frm, to_process_name=to, dim_letters=dl))

    src = role_map["source"]
    fab = role_map["fabrication"]
    use = role_map["use_stock"]
    col = role_map["collection"]
    rem = role_map["remanufacture"]
    rec = role_map["recycling"]
    disp = role_map["disposal"]
    eol = role_map.get("end_of_life")
    sort = role_map.get("sorting_preprocessing")
    refining = role_map.get("refining")
    primary_extraction = role_map.get("primary_extraction")
    beneficiation = role_map.get("beneficiation_concentration")

    if (primary_extraction is None) ^ (beneficiation is None):
        raise ValueError(
            "mfa_graph must define both roles 'primary_extraction' and "
            "'beneficiation_concentration' together, or omit both."
        )
    if (primary_extraction is not None or beneficiation is not None) and refining is None:
        raise ValueError(
            "mfa_graph with primary extraction/beneficiation chain also requires role 'refining'."
        )

    end_use_letters: set[str] = set()
    for frm, to in flow_dims.keys():
        dims_here = flow_dims[(frm, to)]
        if len(dims_here) != 3 or dims_here[0] != "t" or dims_here[1] != "r":
            raise ValueError(
                "mfa_graph flows must use dim_letters format ('t','r','<end_use_dim>'). "
                f"Invalid dim_letters for {frm} -> {to}: {dims_here}"
            )
        end_use_letters.add(dims_here[2])
    if not end_use_letters:
        raise ValueError("Unable to infer end-use dimension letter from mfa_graph flow declarations.")
    if len(end_use_letters) != 1:
        raise ValueError(
            "All mfa_graph flows must use the same end-use dimension letter; "
            f"got {sorted(list(end_use_letters))}."
        )
    end_use_dim_letter = next(iter(end_use_letters))

    required_flows: List[Tuple[str, str, Tuple[str, ...]]] = [
        (fab, use, ("t", "r", end_use_dim_letter)),
        (fab, src, ("t", "r", end_use_dim_letter)),
        (col, rem, ("t", "r", end_use_dim_letter)),
        (col, disp, ("t", "r", end_use_dim_letter)),
        (rem, use, ("t", "r", end_use_dim_letter)),
        (rem, src, ("t", "r", end_use_dim_letter)),
        (rec, src, ("t", "r", end_use_dim_letter)),
        (disp, src, ("t", "r", end_use_dim_letter)),
    ]
    if eol is not None:
        required_flows.extend(
            [
                (use, eol, ("t", "r", end_use_dim_letter)),
                (eol, col, ("t", "r", end_use_dim_letter)),
                (eol, src, ("t", "r", end_use_dim_letter)),
            ]
        )
    else:
        required_flows.extend(
            [
                (use, col, ("t", "r", end_use_dim_letter)),
                (use, src, ("t", "r", end_use_dim_letter)),
            ]
        )

    if sort is not None:
        required_flows.extend(
            [
                (col, sort, ("t", "r", end_use_dim_letter)),
                (sort, rec, ("t", "r", end_use_dim_letter)),
                (sort, disp, ("t", "r", end_use_dim_letter)),
                (sort, src, ("t", "r", end_use_dim_letter)),
            ]
        )
    else:
        required_flows.append((col, rec, ("t", "r", end_use_dim_letter)))

    if refining is not None:
        required_flows.extend(
            [
                (rec, refining, ("t", "r", end_use_dim_letter)),
                (refining, fab, ("t", "r", end_use_dim_letter)),
                (refining, src, ("t", "r", end_use_dim_letter)),
            ]
        )
        if primary_extraction is not None and beneficiation is not None:
            required_flows.extend(
                [
                    (src, primary_extraction, ("t", "r", end_use_dim_letter)),
                    (primary_extraction, beneficiation, ("t", "r", end_use_dim_letter)),
                    (beneficiation, refining, ("t", "r", end_use_dim_letter)),
                    (primary_extraction, src, ("t", "r", end_use_dim_letter)),
                    (beneficiation, src, ("t", "r", end_use_dim_letter)),
                ]
            )
        else:
            required_flows.append((src, refining, ("t", "r", end_use_dim_letter)))
    else:
        required_flows.extend(
            [
                (src, fab, ("t", "r", end_use_dim_letter)),
                (rec, fab, ("t", "r", end_use_dim_letter)),
            ]
        )

    for frm, to, dl_req in required_flows:
        if (frm, to) not in flow_dims:
            raise ValueError(f"mfa_graph missing required flow: {frm} -> {to}")
        if tuple(flow_dims[(frm, to)]) != tuple(dl_req):
            raise ValueError(
                f"mfa_graph flow {frm} -> {to} must have dim_letters={dl_req}; got {flow_dims[(frm, to)]}"
            )

    dims = DimensionSet(
        dim_list=[
            Dimension(name="Time", letter="t", items=years),
            Dimension(name="Region", letter="r", items=list(regions)),
            Dimension(name="EndUse", letter=end_use_dim_letter, items=end_uses or ["total"]),
            Dimension(name="Age", letter="a", items=ages),
        ]
    )

    flows = make_empty_flows(processes=processes, flow_definitions=flow_defs, dims=dims)

    mass_balance_tolerance = float(params.get("mass_balance_tolerance", 1.0e-8))
    if mass_balance_tolerance <= 0:
        raise ValueError("mass_balance_tolerance must be > 0.")

    dims_t = _subset_dims(dims, ("t",))
    dims_tr = _subset_dims(dims, ("t", "r"))
    dims_tre = _subset_dims(dims, ("t", "r", end_use_dim_letter))
    dims_trea = _subset_dims(dims, ("t", "r", end_use_dim_letter, "a"))

    stock_items = graph.get("stocks")
    if stock_items is None:
        stock_items = []
    if not isinstance(stock_items, list):
        raise ValueError("mfa_graph.stocks must be a list when provided.")
    if not stock_items:
        stock_items = [
            {
                "name": SimpleMetalCycleWithReman.USE_STOCK_NAME,
                "process": use,
                "dim_letters": ["t", "r", end_use_dim_letter],
                "role": "use_stock_native",
            },
            {
                "name": SimpleMetalCycleWithReman.REFINERY_STOCKPILE_STOCK_NAME,
                "process": refining if refining is not None else rec,
                "dim_letters": ["t", "r", end_use_dim_letter],
                "role": "refinery_stockpile_native",
            },
            {
                "name": SimpleMetalCycleWithReman.STRATEGIC_INVENTORY_STOCK_NAME,
                "process": refining if refining is not None else rec,
                "dim_letters": ["t", "r", end_use_dim_letter],
                "role": "strategic_inventory_native",
            },
        ]

    stocks: Dict[str, SimpleFlowDrivenStock] = {}
    for s in stock_items:
        if not isinstance(s, dict):
            raise ValueError("mfa_graph.stocks entries must be mappings.")
        name = str(s.get("name", "")).strip()
        proc_name = str(s.get("process", "")).strip()
        dim_letters_raw = s.get("dim_letters")
        if not name:
            raise ValueError("mfa_graph.stocks entries must define a non-empty 'name'.")
        if name in stocks:
            raise ValueError(f"Duplicate stock definition in mfa_graph.stocks: {name}")
        if proc_name not in processes:
            raise ValueError(f"Stock references unknown process in 'process': {proc_name}")
        if not isinstance(dim_letters_raw, (list, tuple)) or not dim_letters_raw:
            raise ValueError(f"Stock dim_letters must be a non-empty list for stock '{name}'.")
        dim_letters = tuple(str(x) for x in dim_letters_raw)
        try:
            stock_dims = _subset_dims(dims, dim_letters)
        except Exception as exc:  # pragma: no cover
            raise ValueError(f"Invalid stock dim_letters for stock '{name}': {dim_letters}") from exc

        stocks[name] = SimpleFlowDrivenStock(
            dims=stock_dims,
            name=name,
            process=processes[proc_name],
        )

    required_stocks = {
        SimpleMetalCycleWithReman.USE_STOCK_NAME: use,
        SimpleMetalCycleWithReman.REFINERY_STOCKPILE_STOCK_NAME: refining if refining is not None else rec,
        SimpleMetalCycleWithReman.STRATEGIC_INVENTORY_STOCK_NAME: refining if refining is not None else rec,
    }
    for stock_name, expected_process in required_stocks.items():
        if stock_name not in stocks:
            raise ValueError(f"mfa_graph is missing required stock definition: {stock_name}")
        if stocks[stock_name].process.name != expected_process:
            raise ValueError(
                f"Stock '{stock_name}' must be attached to process '{expected_process}'; "
                f"got '{stocks[stock_name].process.name}'."
            )

    parameters = {
        "service_demand": Parameter(name="service_demand", dims=dims_tre, values=service_demand_tre),
        "fabrication_yield": Parameter(name="fabrication_yield", dims=dims_t, values=fabrication_yield_ts),
        "collection_rate": Parameter(name="collection_rate", dims=dims_t, values=collection_rate_ts),
        "recycling_yield": Parameter(name="recycling_yield", dims=dims_t, values=rec_yield_ts),
        "recycling_rate": Parameter(name="recycling_rate", dims=dims_t, values=recycling_rate_ts),
        "remanufacturing_rate": Parameter(name="remanufacturing_rate", dims=dims_t, values=remanufacturing_rate_ts),
        "disposal_rate": Parameter(name="disposal_rate", dims=dims_t, values=disposal_rate_ts),
        "remanufacturing_end_use_eligibility": Parameter(
            name="remanufacturing_end_use_eligibility",
            dims=dims_tre,
            values=reman_eligibility_tre,
        ),
        "reman_yield": Parameter(name="reman_yield", dims=dims_t, values=reman_yield_ts),
        "lifetime_pdf": Parameter(name="lifetime_pdf", dims=dims_trea, values=lifetime_pdf_trea),
        "primary_available_to_refining": Parameter(
            name="primary_available_to_refining",
            dims=dims_tr,
            values=primary_available_tr,
        ),
        "primary_refined_net_imports": Parameter(
            name="primary_refined_net_imports",
            dims=dims_tr,
            values=primary_refined_net_imports_tr,
        ),
        "extraction_yield": Parameter(name="extraction_yield", dims=dims_t, values=extraction_yield_ts),
        "beneficiation_yield": Parameter(name="beneficiation_yield", dims=dims_t, values=beneficiation_yield_ts),
        "refining_yield": Parameter(name="refining_yield", dims=dims_t, values=refining_yield_ts),
        "sorting_yield": Parameter(name="sorting_yield", dims=dims_t, values=sorting_yield_ts),
        "extraction_loss_to_sysenv_share": Parameter(
            name="extraction_loss_to_sysenv_share",
            dims=dims_t,
            values=extraction_loss_to_sysenv_share_ts,
        ),
        "beneficiation_loss_to_sysenv_share": Parameter(
            name="beneficiation_loss_to_sysenv_share",
            dims=dims_t,
            values=beneficiation_loss_to_sysenv_share_ts,
        ),
        "refining_loss_to_sysenv_share": Parameter(
            name="refining_loss_to_sysenv_share",
            dims=dims_t,
            values=refining_loss_to_sysenv_share_ts,
        ),
        "sorting_reject_to_disposal_share": Parameter(
            name="sorting_reject_to_disposal_share",
            dims=dims_t,
            values=sorting_reject_to_disposal_share_ts,
        ),
        "sorting_reject_to_sysenv_share": Parameter(
            name="sorting_reject_to_sysenv_share",
            dims=dims_t,
            values=sorting_reject_to_sysenv_share_ts,
        ),
        "mass_balance_tolerance": Parameter(
            name="mass_balance_tolerance",
            dims=dims_t,
            values=np.array([mass_balance_tolerance] * len(years), dtype=float),
        ),
        "refinery_stockpile_release_rate": Parameter(
            name="refinery_stockpile_release_rate",
            dims=dims_t,
            values=refinery_stockpile_release_rate_ts,
        ),
        "new_scrap_to_secondary_share": Parameter(
            name="new_scrap_to_secondary_share",
            dims=dims_t,
            values=new_scrap_to_secondary_share_ts,
        ),
        "strategic_reserve_enabled": Parameter(
            name="strategic_reserve_enabled",
            dims=dims_t,
            values=strategic_reserve_enabled_ts,
        ),
        "strategic_fill_intent": Parameter(
            name="strategic_fill_intent",
            dims=dims_t,
            values=strategic_fill_intent_ts,
        ),
        "strategic_release_intent": Parameter(
            name="strategic_release_intent",
            dims=dims_t,
            values=strategic_release_intent_ts,
        ),
        "__stock_in_use": Parameter(name="__stock_in_use", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__service_demand": Parameter(name="__service_demand", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__delivered_service": Parameter(name="__delivered_service", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__unmet_service": Parameter(name="__unmet_service", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__primary_refined_net_imports": Parameter(name="__primary_refined_net_imports", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__primary_available_to_refining": Parameter(name="__primary_available_to_refining", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__primary_supply_used": Parameter(name="__primary_supply_used", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__secondary_supply_used": Parameter(name="__secondary_supply_used", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__eol_disposal": Parameter(name="__eol_disposal", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__mass_balance_residual_abs_max": Parameter(name="__mass_balance_residual_abs_max", dims=dims_t, values=np.zeros(len(years), dtype=float)),
        "__eol_uncollected": Parameter(name="__eol_uncollected", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__fabrication_losses": Parameter(name="__fabrication_losses", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__new_scrap_generated": Parameter(name="__new_scrap_generated", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__new_scrap_to_secondary": Parameter(name="__new_scrap_to_secondary", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__new_scrap_to_residue": Parameter(name="__new_scrap_to_residue", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__old_scrap_generated": Parameter(name="__old_scrap_generated", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__old_scrap_collected": Parameter(name="__old_scrap_collected", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__old_scrap_uncollected": Parameter(name="__old_scrap_uncollected", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__recycling_process_losses": Parameter(name="__recycling_process_losses", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__recycling_surplus_unused": Parameter(name="__recycling_surplus_unused", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__refinery_stockpile_inflow": Parameter(name="__refinery_stockpile_inflow", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__refinery_stockpile_outflow": Parameter(name="__refinery_stockpile_outflow", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__refinery_stockpile_stock": Parameter(name="__refinery_stockpile_stock", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__strategic_inventory_inflow": Parameter(name="__strategic_inventory_inflow", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__strategic_inventory_outflow": Parameter(name="__strategic_inventory_outflow", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__strategic_inventory_stock": Parameter(name="__strategic_inventory_stock", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__strategic_stock_coverage_years": Parameter(name="__strategic_stock_coverage_years", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__strategic_fill_intent": Parameter(name="__strategic_fill_intent", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__strategic_release_intent": Parameter(name="__strategic_release_intent", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__remanufacture_process_losses": Parameter(name="__remanufacture_process_losses", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__remanufacture_surplus_unused": Parameter(name="__remanufacture_surplus_unused", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__extraction_losses": Parameter(name="__extraction_losses", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__beneficiation_losses": Parameter(name="__beneficiation_losses", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__refining_losses": Parameter(name="__refining_losses", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__sorting_rejects_to_disposal": Parameter(name="__sorting_rejects_to_disposal", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
        "__sorting_rejects_to_sysenv": Parameter(name="__sorting_rejects_to_sysenv", dims=dims_tre, values=np.zeros_like(service_demand_tre)),
    }

    mfa = SimpleMetalCycleWithReman(
        dims=dims,
        processes=processes,
        flows=flows,
        stocks=stocks,
        parameters=parameters,
    )
    mfa.role_map = role_map
    mfa.end_use_dim_letter = end_use_dim_letter
    mfa.compute()

    idx = years
    sd_ag = service_demand_tre.sum(axis=(1, 2))
    delivered = mfa.parameters["__delivered_service"].values.sum(axis=(1, 2))
    unmet = mfa.parameters["__unmet_service"].values.sum(axis=(1, 2))
    service_level = np.where(sd_ag > 0, delivered / sd_ag, 1.0)

    primary = mfa.parameters["__primary_supply_used"].values.sum(axis=(1, 2))
    secondary = mfa.parameters["__secondary_supply_used"].values.sum(axis=(1, 2))

    primary_refined_net_imports_ag = mfa.parameters["primary_refined_net_imports"].values.sum(axis=1)
    primary_available_ag = mfa.parameters["primary_available_to_refining"].values.sum(axis=1)

    inflow_new_ag = mfa.flows[f"{fab} => {use}"].values.sum(axis=(1, 2))
    inflow_reman_ag = mfa.flows[f"{rem} => {use}"].values.sum(axis=(1, 2))
    inflow_total_ag = inflow_new_ag + inflow_reman_ag

    outflow_ag = mfa.parameters["__old_scrap_generated"].values.sum(axis=(1, 2))
    stock_ag = mfa.parameters["__stock_in_use"].values.sum(axis=(1, 2))

    eol_gen = mfa.parameters["__old_scrap_generated"].values.sum(axis=(1, 2))
    eol_coll = mfa.parameters["__old_scrap_collected"].values.sum(axis=(1, 2))

    if sort is not None:
        eol_recycled = (
            mfa.flows[f"{sort} => {rec}"].values
            * mfa.parameters["recycling_yield"].values[:, None, None]
        ).sum(axis=(1, 2))
    else:
        eol_recycled = (
            mfa.flows[f"{col} => {rec}"].values
            * mfa.parameters["recycling_yield"].values[:, None, None]
        ).sum(axis=(1, 2))

    eol_reman = (
        mfa.flows[f"{col} => {rem}"].values.sum(axis=(1, 2))
        * mfa.parameters["reman_yield"].values
    )
    eol_disposal = mfa.parameters["__eol_disposal"].values.sum(axis=(1, 2))

    eol_uncollected_ag = mfa.parameters["__eol_uncollected"].values.sum(axis=(1, 2))
    fab_losses_ag = mfa.parameters["__fabrication_losses"].values.sum(axis=(1, 2))

    new_scrap_generated_ag = mfa.parameters["__new_scrap_generated"].values.sum(axis=(1, 2))
    new_scrap_to_secondary_ag = mfa.parameters["__new_scrap_to_secondary"].values.sum(axis=(1, 2))
    new_scrap_to_residue_ag = mfa.parameters["__new_scrap_to_residue"].values.sum(axis=(1, 2))

    old_scrap_generated_ag = mfa.parameters["__old_scrap_generated"].values.sum(axis=(1, 2))
    old_scrap_collected_ag = mfa.parameters["__old_scrap_collected"].values.sum(axis=(1, 2))
    old_scrap_uncollected_ag = mfa.parameters["__old_scrap_uncollected"].values.sum(axis=(1, 2))

    rec_proc_losses_ag = mfa.parameters["__recycling_process_losses"].values.sum(axis=(1, 2))
    rec_surplus_ag = mfa.parameters["__recycling_surplus_unused"].values.sum(axis=(1, 2))

    stockpile_in_ag = mfa.parameters["__refinery_stockpile_inflow"].values.sum(axis=(1, 2))
    stockpile_out_ag = mfa.parameters["__refinery_stockpile_outflow"].values.sum(axis=(1, 2))
    stockpile_stock_ag = mfa.parameters["__refinery_stockpile_stock"].values.sum(axis=(1, 2))
    strategic_inventory_in_ag = mfa.parameters["__strategic_inventory_inflow"].values.sum(axis=(1, 2))
    strategic_inventory_out_ag = mfa.parameters["__strategic_inventory_outflow"].values.sum(axis=(1, 2))
    strategic_inventory_stock_ag = mfa.parameters["__strategic_inventory_stock"].values.sum(axis=(1, 2))
    strategic_coverage_ag = np.where(
        sd_ag > 0.0,
        strategic_inventory_stock_ag / np.maximum(sd_ag, 1.0e-12),
        0.0,
    )
    strategic_fill_intent_ag = mfa.parameters["__strategic_fill_intent"].values.mean(axis=(1, 2))
    strategic_release_intent_ag = mfa.parameters["__strategic_release_intent"].values.mean(axis=(1, 2))

    rem_proc_losses_ag = mfa.parameters["__remanufacture_process_losses"].values.sum(axis=(1, 2))
    rem_surplus_ag = mfa.parameters["__remanufacture_surplus_unused"].values.sum(axis=(1, 2))

    extraction_losses_ag = mfa.parameters["__extraction_losses"].values.sum(axis=(1, 2))
    beneficiation_losses_ag = mfa.parameters["__beneficiation_losses"].values.sum(axis=(1, 2))
    refining_losses_ag = mfa.parameters["__refining_losses"].values.sum(axis=(1, 2))
    sorting_rejects_to_disposal_ag = mfa.parameters["__sorting_rejects_to_disposal"].values.sum(axis=(1, 2))
    sorting_rejects_to_sysenv_ag = mfa.parameters["__sorting_rejects_to_sysenv"].values.sum(axis=(1, 2))

    mb_residual_abs_max = mfa.parameters["__mass_balance_residual_abs_max"].values

    ts = MFATimeseries(
        years=years,
        service_demand=pd.Series(sd_ag, index=idx),
        delivered_service=pd.Series(delivered, index=idx),
        unmet_service=pd.Series(unmet, index=idx),
        service_level=pd.Series(service_level, index=idx),
        primary_supply=pd.Series(primary, index=idx),
        primary_refined_net_imports=pd.Series(primary_refined_net_imports_ag, index=idx),
        primary_available_to_refining=pd.Series(primary_available_ag, index=idx),
        secondary_supply=pd.Series(secondary, index=idx),
        inflow_to_use_total=pd.Series(inflow_total_ag, index=idx),
        inflow_to_use_new=pd.Series(inflow_new_ag, index=idx),
        inflow_to_use_reman=pd.Series(inflow_reman_ag, index=idx),
        outflow_from_use=pd.Series(outflow_ag, index=idx),
        stock_in_use=pd.Series(stock_ag, index=idx),
        eol_generated=pd.Series(eol_gen, index=idx),
        eol_collected=pd.Series(eol_coll, index=idx),
        eol_recycled=pd.Series(eol_recycled, index=idx),
        eol_remanufactured=pd.Series(eol_reman, index=idx),
        eol_disposal=pd.Series(eol_disposal, index=idx),
        eol_uncollected=pd.Series(eol_uncollected_ag, index=idx),
        fabrication_losses=pd.Series(fab_losses_ag, index=idx),
        new_scrap_generated=pd.Series(new_scrap_generated_ag, index=idx),
        new_scrap_to_secondary=pd.Series(new_scrap_to_secondary_ag, index=idx),
        new_scrap_to_residue=pd.Series(new_scrap_to_residue_ag, index=idx),
        old_scrap_generated=pd.Series(old_scrap_generated_ag, index=idx),
        old_scrap_collected=pd.Series(old_scrap_collected_ag, index=idx),
        old_scrap_uncollected=pd.Series(old_scrap_uncollected_ag, index=idx),
        recycling_process_losses=pd.Series(rec_proc_losses_ag, index=idx),
        recycling_surplus_unused=pd.Series(rec_surplus_ag, index=idx),
        refinery_stockpile_inflow=pd.Series(stockpile_in_ag, index=idx),
        refinery_stockpile_outflow=pd.Series(stockpile_out_ag, index=idx),
        refinery_stockpile_stock=pd.Series(stockpile_stock_ag, index=idx),
        strategic_inventory_inflow=pd.Series(strategic_inventory_in_ag, index=idx),
        strategic_inventory_outflow=pd.Series(strategic_inventory_out_ag, index=idx),
        strategic_inventory_stock=pd.Series(strategic_inventory_stock_ag, index=idx),
        strategic_stock_coverage_years=pd.Series(strategic_coverage_ag, index=idx),
        strategic_fill_intent=pd.Series(strategic_fill_intent_ag, index=idx),
        strategic_release_intent=pd.Series(strategic_release_intent_ag, index=idx),
        remanufacture_process_losses=pd.Series(rem_proc_losses_ag, index=idx),
        remanufacture_surplus_unused=pd.Series(rem_surplus_ag, index=idx),
        extraction_losses=pd.Series(extraction_losses_ag, index=idx),
        beneficiation_losses=pd.Series(beneficiation_losses_ag, index=idx),
        refining_losses=pd.Series(refining_losses_ag, index=idx),
        sorting_rejects_to_disposal=pd.Series(sorting_rejects_to_disposal_ag, index=idx),
        sorting_rejects_to_sysenv=pd.Series(sorting_rejects_to_sysenv_ag, index=idx),
        mass_balance_residual_max_abs=pd.Series(mb_residual_abs_max, index=idx),
    )

    return mfa, ts


__all__ = ["run_flodym_mfa"]
