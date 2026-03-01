from __future__ import annotations

from glob import glob
import warnings
from pathlib import Path
from typing import Any, Dict

import yaml

from .models import RunConfig


def _read_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a mapping at top level: {path}")
    return data


def _deep_merge_dicts(parent: Dict[str, Any], child: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(parent)
    for key, value in child.items():
        if isinstance(out.get(key), dict) and isinstance(value, dict):
            out[key] = _deep_merge_dicts(out[key], value)
        else:
            out[key] = value
    return out


def _normalize_includes_paths(payload: Dict[str, Any], *, base_dir: Path) -> Dict[str, Any]:
    out = dict(payload)
    includes = out.get("includes")
    if not isinstance(includes, dict):
        return out

    normalized: Dict[str, Any] = {}
    for key, rel in includes.items():
        if rel is None:
            normalized[key] = None
            continue
        if not isinstance(rel, str):
            normalized[key] = rel
            continue
        spec = rel.strip()
        if not spec:
            normalized[key] = rel
            continue
        p = Path(spec)
        normalized[key] = spec if p.is_absolute() else str((base_dir / spec).absolute())

    out["includes"] = normalized
    return out


def _normalize_scenario_profiles_paths(payload: Dict[str, Any], *, base_dir: Path) -> Dict[str, Any]:
    out = dict(payload)
    node = out.get("scenario_profiles")
    if not isinstance(node, dict):
        return out

    csv_globs = node.get("csv_globs")
    if not isinstance(csv_globs, list):
        return out

    normalized_globs: list[Any] = []
    for item in csv_globs:
        if not isinstance(item, str):
            normalized_globs.append(item)
            continue
        spec = item.strip()
        if not spec:
            normalized_globs.append(item)
            continue
        p = Path(spec)
        normalized_globs.append(spec if p.is_absolute() else str((base_dir / spec).absolute()))

    scenario_profiles = dict(node)
    scenario_profiles["csv_globs"] = normalized_globs
    out["scenario_profiles"] = scenario_profiles
    return out


def _load_run_payload_with_extends(path: Path, *, stack: tuple[Path, ...] = ()) -> Dict[str, Any]:
    cfg_path = path.resolve()
    if cfg_path in stack:
        chain = " -> ".join(str(p) for p in (*stack, cfg_path))
        raise ValueError(f"Cyclic run-config extends chain detected: {chain}")

    payload = _normalize_includes_paths(_read_yaml(cfg_path), base_dir=cfg_path.parent)
    payload = _normalize_scenario_profiles_paths(payload, base_dir=cfg_path.parent)

    parent_spec = payload.get("extends")
    if parent_spec is None:
        return payload
    if not isinstance(parent_spec, str) or not parent_spec.strip():
        raise ValueError(f"Run config field 'extends' must be a non-empty string path: {cfg_path}")

    parent_path = Path(parent_spec)
    if not parent_path.is_absolute():
        parent_path = (cfg_path.parent / parent_spec).resolve()

    parent_payload = _load_run_payload_with_extends(parent_path, stack=(*stack, cfg_path))
    child_payload = dict(payload)
    child_payload.pop("extends", None)
    return _deep_merge_dicts(parent_payload, child_payload)


def resolve_repo_root_from_config(config_path: str | Path) -> Path:
    """Infer repository root from a config path.

    Supports configs located at `configs/*.yml` and deeper paths like
    `configs/runs/*.yml`.
    """
    p = Path(config_path).resolve()
    for candidate in [p.parent, *p.parents]:
        if (candidate / "registry" / "variable_registry.yml").exists() and (candidate / "configs").exists():
            return candidate
    # Backward-compatible fallback for legacy layout assumptions.
    return p.parent.parent


def _resolve_scenario_files(base_dir: Path, spec: str) -> list[Path]:
    """Resolve scenario include spec into concrete files.

    Supported forms:
      - directory path (loads `*.yml` and `*.yaml` in that directory)
      - single file path
      - glob pattern (e.g. `scenarios/mvp/*.yml`)
    """
    spec_str = str(spec).strip()
    if not spec_str:
        raise ValueError("Scenario include spec cannot be empty.")

    has_glob = any(ch in spec_str for ch in "*?[]")
    if has_glob:
        if Path(spec_str).is_absolute():
            matches = [Path(p) for p in glob(spec_str)]
        else:
            matches = list(base_dir.glob(spec_str))
        files = sorted(p.resolve() for p in matches if p.is_file())
        if not files:
            raise FileNotFoundError(f"Scenario include glob matched no files: {spec_str}")
        return files

    path = Path(spec_str)
    if not path.is_absolute():
        path = (base_dir / path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Scenario include path does not exist: {path}")

    if path.is_dir():
        return sorted(path.glob("*.yml")) + sorted(path.glob("*.yaml"))

    if path.is_file():
        return [path]

    raise ValueError(f"Scenario include spec must resolve to file(s): {spec_str}")


def _load_scenario_variants(base_dir: Path, spec: str) -> Dict[str, Dict[str, Any]]:
    """Load scenario variants from include spec.

    Each resolved file supports:
      - Optional `name` key (defaults to filename stem)
      - Remaining keys are validated against VariantConfig via RunConfig model validation.
    """
    files = _resolve_scenario_files(base_dir=base_dir, spec=spec)
    out: Dict[str, Dict[str, Any]] = {}
    for f in files:
        payload = _read_yaml(f)
        name_raw = payload.pop("name", f.stem)
        name = str(name_raw).strip()
        if not name:
            raise ValueError(f"Scenario file has empty name: {f}")
        if name in out:
            raise ValueError(
                f"Duplicate scenario name '{name}' across scenario include files (spec: {spec})"
            )
        out[name] = payload
    return out


def _read_dimension_symbol(payload: Dict[str, Any], *, key: str, default: str) -> str:
    node = payload.get(key)
    if node is None:
        return default
    if not isinstance(node, dict):
        raise ValueError(f"Split dimension metadata '{key}' must be a mapping when provided.")
    symbol = node.get("symbol", default)
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError(f"Split dimension metadata '{key}.symbol' must be a non-empty string.")
    return symbol.strip()


def _read_dimension_alias(payload: Dict[str, Any], *, key: str, default: str) -> str:
    node = payload.get(key)
    if node is None:
        return default
    if not isinstance(node, dict):
        raise ValueError(f"Split dimension metadata '{key}' must be a mapping when provided.")
    alias = node.get("alias_of", default)
    if not isinstance(alias, str) or not alias.strip():
        raise ValueError(f"Split dimension metadata '{key}.alias_of' must be a non-empty string.")
    return alias.strip()


def _compose_dimensions_from_split(
    *,
    time_payload: Dict[str, Any],
    regions_payload: Dict[str, Any],
    materials_payload: Dict[str, Any],
    end_use_payload: Dict[str, Any],
    stages_payload: Dict[str, Any] | None = None,
    qualities_payload: Dict[str, Any] | None = None,
    trade_payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    regions = regions_payload.get("regions")
    materials = materials_payload.get("materials")
    end_uses = end_use_payload.get("end_uses")
    end_use_detailed = end_use_payload.get("end_use_detailed", [])
    if not isinstance(regions, list):
        raise ValueError("Split dimensions include 'regions' must define a list field 'regions'.")
    if not isinstance(materials, list):
        raise ValueError("Split dimensions include 'materials' must define a list field 'materials'.")
    if not isinstance(end_uses, list):
        raise ValueError("Split dimensions include end-use file must define a list field 'end_uses'.")
    if not isinstance(end_use_detailed, list):
        raise ValueError("Split dimensions include end-use file field 'end_use_detailed' must be a list when present.")

    stages: list[Any] = []
    if stages_payload is not None:
        stages_raw = stages_payload.get("stages")
        if stages_raw is None:
            processes = stages_payload.get("processes", [])
            if not isinstance(processes, list):
                raise ValueError("Split stages include field 'processes' must be a list when present.")
            stages = [p.get("name") for p in processes if isinstance(p, dict) and "name" in p]
        else:
            if not isinstance(stages_raw, list):
                raise ValueError("Split stages include field 'stages' must be a list when present.")
            stages = stages_raw

    qualities: list[Any] = []
    if qualities_payload is not None:
        qualities_raw = qualities_payload.get("qualities", [])
        if not isinstance(qualities_raw, list):
            raise ValueError("Split qualities include field 'qualities' must be a list when present.")
        qualities = qualities_raw

    commodities: list[Any] = []
    origin_regions: list[Any] = []
    destination_regions: list[Any] = []
    trade_aliases = {
        "origin_region": _read_dimension_alias(trade_payload or {}, key="origin_region_dimension", default="r"),
        "destination_region": _read_dimension_alias(trade_payload or {}, key="destination_region_dimension", default="r"),
    }
    if trade_payload is not None:
        commodities_raw = trade_payload.get("commodities", [])
        origin_regions_raw = trade_payload.get("origin_regions", [])
        destination_regions_raw = trade_payload.get("destination_regions", [])
        if not isinstance(commodities_raw, list):
            raise ValueError("Split trade include field 'commodities' must be a list when present.")
        if not isinstance(origin_regions_raw, list):
            raise ValueError("Split trade include field 'origin_regions' must be a list when present.")
        if not isinstance(destination_regions_raw, list):
            raise ValueError("Split trade include field 'destination_regions' must be a list when present.")
        commodities = commodities_raw
        origin_regions = origin_regions_raw
        destination_regions = destination_regions_raw

        aliases_raw = trade_payload.get("trade_aliases")
        if aliases_raw is not None:
            if not isinstance(aliases_raw, dict):
                raise ValueError("Split trade include field 'trade_aliases' must be a mapping when present.")
            for k in ["origin_region", "destination_region"]:
                if k in aliases_raw:
                    v = aliases_raw[k]
                    if not isinstance(v, str) or not v.strip():
                        raise ValueError(f"Split trade include field 'trade_aliases.{k}' must be a non-empty string.")
                    trade_aliases[k] = v.strip()

    symbols = {
        "time": _read_dimension_symbol(time_payload, key="dimension", default="t"),
        "region": _read_dimension_symbol(regions_payload, key="dimension", default="r"),
        "material": _read_dimension_symbol(materials_payload, key="dimension", default="m"),
        "end_use": _read_dimension_symbol(end_use_payload, key="dimension", default="e"),
        "end_use_detailed": _read_dimension_symbol(
            end_use_payload,
            key="end_use_detailed_dimension",
            default="ed",
        ),
        "stage": _read_dimension_symbol(stages_payload or {}, key="dimension", default="p"),
        "quality": _read_dimension_symbol(qualities_payload or {}, key="dimension", default="q"),
        "commodity": _read_dimension_symbol(trade_payload or {}, key="commodity_dimension", default="c"),
        "origin_region": _read_dimension_symbol(trade_payload or {}, key="origin_region_dimension", default="o"),
        "destination_region": _read_dimension_symbol(
            trade_payload or {},
            key="destination_region_dimension",
            default="d",
        ),
    }

    return {
        "regions": regions,
        "materials": materials,
        "end_uses": end_uses,
        "end_use_detailed": end_use_detailed,
        "stages": stages,
        "qualities": qualities,
        "commodities": commodities,
        "origin_regions": origin_regions,
        "destination_regions": destination_regions,
        "trade_aliases": trade_aliases,
        "symbols": symbols,
    }


def _compose_mfa_graph_from_stages(*, stages_payload: Dict[str, Any]) -> Dict[str, Any]:
    processes = stages_payload.get("processes")
    flows = stages_payload.get("flows")
    stocks = stages_payload.get("stocks", [])
    constraints = stages_payload.get("constraints", [])
    if not isinstance(processes, list):
        raise ValueError("Split mfa_graph include 'stages' must define list field 'processes'.")
    if not isinstance(flows, list):
        raise ValueError("Split mfa_graph include 'stages' must define list field 'flows'.")
    if not isinstance(stocks, list):
        raise ValueError("Split mfa_graph include 'stages' field 'stocks' must be a list when present.")
    if not isinstance(constraints, list):
        raise ValueError("Split mfa_graph include 'stages' field 'constraints' must be a list when present.")
    return {
        "processes": processes,
        "flows": flows,
        "stocks": stocks,
        "constraints": constraints,
    }


def load_run_config(path: str | Path) -> RunConfig:
    """Load a run config with explicit includes.

    Supports optional `extends` inheritance. Parent and child mappings are deep-merged
    (child values override parent values), then includes are resolved.

    The top-level run config defines an `includes` mapping. Each included YAML file is loaded
    and inserted under its corresponding key (time/dimensions/coupling/indicators/variables).

    To keep single sources of truth, overriding an included block in the top-level file is not allowed.
    """

    p = Path(path).resolve()
    top = _load_run_payload_with_extends(p)

    includes = top.get("includes")
    if not isinstance(includes, dict):
        raise ValueError("Run config must include an 'includes' mapping.")
    end_use_keys = [k for k in ["applications", "end_use", "end_uses"] if includes.get(k) is not None]
    if len(end_use_keys) > 1:
        raise ValueError(
            "Run config includes must define only one end-use key among "
            f"'applications', 'end_use', 'end_uses'; found {end_use_keys}."
        )
    if "applications" in end_use_keys:
        warnings.warn(
            "Run config includes.applications is deprecated. Use includes.end_uses instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    if "end_use" in end_use_keys:
        warnings.warn(
            "Run config includes.end_use is deprecated. Use includes.end_uses instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    base_dir = p.parent
    out = dict(top)

    split_time: Dict[str, Any] | None = None
    split_regions: Dict[str, Any] | None = None
    split_materials: Dict[str, Any] | None = None
    split_end_use: Dict[str, Any] | None = None
    split_stages: Dict[str, Any] | None = None
    split_qualities: Dict[str, Any] | None = None
    split_trade: Dict[str, Any] | None = None

    for key, rel in includes.items():
        if key == "scenarios":
            if rel is None:
                continue
            if not isinstance(rel, str):
                raise ValueError("Run config includes.scenarios must be a string path/glob when provided.")
            scenario_variants = _load_scenario_variants(base_dir=base_dir, spec=rel)
            existing = out.get("variants", {})
            if not isinstance(existing, dict):
                raise ValueError("Run config field 'variants' must be a mapping when scenarios include is used.")
            # Scenario-directory variants are loaded first; inline `variants` in the top-level
            # config override file-based definitions for backward-compatible transitions.
            out["variants"] = {**scenario_variants, **existing}
            continue
        if rel is None:
            continue
        if not isinstance(rel, str):
            raise ValueError(f"Run config include '{key}' must be a string path.")
        if key in out and key != "includes":
            raise ValueError(
                f"Do not override included block '{key}' in the run config. "
                f"Edit the included file instead: {rel}"
            )
        rel_path = Path(str(rel))
        inc_path = rel_path if rel_path.is_absolute() else (base_dir / rel_path).resolve()
        payload = _read_yaml(inc_path)
        if key == "regions":
            split_regions = payload
            continue
        if key == "materials":
            split_materials = payload
            continue
        if key == "time":
            split_time = payload
            out[key] = payload
            continue
        if key in {"applications", "end_use", "end_uses"}:
            split_end_use = payload
            continue
        if key == "stages":
            split_stages = payload
            continue
        if key == "qualities":
            split_qualities = payload
            continue
        if key == "trade":
            split_trade = payload
            continue
        out[key] = payload

    if "dimensions" not in out:
        if split_time is None or split_regions is None or split_materials is None or split_end_use is None:
            raise ValueError(
                "Missing split dimension includes. Provide 'time', 'regions', 'materials', and "
                "one of 'applications', 'end_use', or 'end_uses', or provide 'dimensions'."
            )
        out["dimensions"] = _compose_dimensions_from_split(
            time_payload=split_time,
            regions_payload=split_regions,
            materials_payload=split_materials,
            end_use_payload=split_end_use,
            stages_payload=split_stages,
            qualities_payload=split_qualities,
            trade_payload=split_trade,
        )

    if "mfa_graph" not in out:
        if split_stages is None:
            raise ValueError("Missing 'stages' include required to compose mfa_graph when mfa_graph is omitted.")
        out["mfa_graph"] = _compose_mfa_graph_from_stages(stages_payload=split_stages)

    return RunConfig.model_validate(out)
