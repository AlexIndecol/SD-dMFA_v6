#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from crm_model.config.io import load_run_config
from crm_model.scenario_profiles import (
    build_variant_payload_from_profiles,
    load_reporting_profile_csv,
)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Expand reporting-window scenario profile CSVs into full-horizon timeseries payloads "
            "for scenario authoring."
        )
    )
    ap.add_argument("--config", required=True, help="Run config path (e.g., configs/runs/mvp.yml)")
    ap.add_argument(
        "--profile",
        action="append",
        required=True,
        help="Profile CSV path. Can be provided multiple times.",
    )
    ap.add_argument(
        "--outdir",
        default="outputs/analysis/scenario_profile_expansions/latest",
        help="Directory for generated YAML payload files.",
    )
    args = ap.parse_args()

    cfg = load_run_config(Path(args.config))
    if cfg.time is None:
        raise SystemExit("Run config did not load time horizon.")

    years = cfg.time.years
    report_start_year = int(cfg.time.report_start_year)
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    for profile_path in args.profile:
        profile = load_reporting_profile_csv(profile_path)
        payload = build_variant_payload_from_profiles(
            profiles=profile,
            years=years,
            report_start_year=report_start_year,
        )
        out_path = outdir / f"{Path(profile_path).stem}.generated.yml"
        out_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

