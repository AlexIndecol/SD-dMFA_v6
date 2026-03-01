"""Run-output layout helpers exposed via crm_model compatibility namespace."""

from crm_model.utils import (
    archive_old_timestamped_runs,
    config_runs_root,
    latest_timestamp_dir,
    latest_timestamp_from_candidate_roots,
    scenario_variant_root,
    scenario_variant_root_candidates,
)

__all__ = [
    "archive_old_timestamped_runs",
    "config_runs_root",
    "latest_timestamp_dir",
    "latest_timestamp_from_candidate_roots",
    "scenario_variant_root",
    "scenario_variant_root_candidates",
]

