#!/usr/bin/env python
"""Manage the baseline -> calibration -> baseline workflow for a chosen run config.

Typical usage:
  1) Run calibration and produce a patch file:
     python scripts/calibration/calibrate_model.py --config <config.yml> --calibration-spec configs/calibration.yml

  2) Promote the best patch to baseline:
     python scripts/calibration/calibration_cycle.py promote \
       --config <config.yml> \
       --patch outputs/runs/calibration/<config_stem>/baseline/<timestamp>/best_config_patch.yml

  3) Optionally restore the previous baseline snapshot:
     python scripts/calibration/calibration_cycle.py restore \
       --config <config.yml> \
       --snapshot outputs/runs/calibration/cycle/<config_stem>/<timestamp>/baseline_before.yml
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import yaml
from crm_model.common.run_layout import archive_old_timestamped_runs


def _read_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a top-level mapping: {path}")
    return data


def _write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _deep_update(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_update(out[k], v)
        else:
            out[k] = v
    return out


def _promote_patch(config_path: Path, patch_path: Path, out_root: Path) -> int:
    cfg = _read_yaml(config_path)
    patch = _read_yaml(patch_path)

    if not patch:
        raise ValueError(f"Patch is empty: {patch_path}")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = out_root / config_path.stem / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = run_dir / "baseline_before.yml"
    _write_yaml(snapshot_path, cfg)

    updated = _deep_update(cfg, patch)
    _write_yaml(config_path, updated)

    _write_yaml(
        run_dir / "promotion_metadata.yml",
        {
            "timestamp": ts,
            "config": str(config_path),
            "patch": str(patch_path),
            "snapshot": str(snapshot_path),
        },
    )

    moved = archive_old_timestamped_runs(run_dir.parent, keep_last=3)
    if moved:
        print(f"Archived {len(moved)} older run(s) to: {run_dir.parent / '_archive'}")

    print(f"Promoted patch to baseline config: {config_path}")
    print(f"Saved previous baseline snapshot: {snapshot_path}")
    return 0


def _restore_snapshot(config_path: Path, snapshot_path: Path) -> int:
    snap = _read_yaml(snapshot_path)
    if not snap:
        raise ValueError(f"Snapshot is empty: {snapshot_path}")

    _write_yaml(config_path, snap)
    print(f"Restored baseline config from snapshot: {snapshot_path}")
    print(f"Updated config: {config_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Baseline calibration-cycle utilities.")
    sub = ap.add_subparsers(dest="command", required=True)

    promote = sub.add_parser("promote", help="Apply a calibration patch to baseline config.")
    promote.add_argument("--config", default="configs/runs/mvp.yml")
    promote.add_argument("--patch", required=True, help="Path to best_config_patch.yml")
    promote.add_argument("--outdir", default="outputs/runs/calibration/cycle")

    restore = sub.add_parser("restore", help="Restore baseline config from a saved snapshot.")
    restore.add_argument("--config", default="configs/runs/mvp.yml")
    restore.add_argument("--snapshot", required=True, help="Path to baseline_before.yml")

    args = ap.parse_args()

    cwd = Path.cwd().resolve()
    config_path = (cwd / args.config).resolve()

    if args.command == "promote":
        patch_path = (cwd / args.patch).resolve()
        out_root = (cwd / args.outdir).resolve()
        return _promote_patch(config_path=config_path, patch_path=patch_path, out_root=out_root)

    snapshot_path = (cwd / args.snapshot).resolve()
    return _restore_snapshot(config_path=config_path, snapshot_path=snapshot_path)


if __name__ == "__main__":
    raise SystemExit(main())
