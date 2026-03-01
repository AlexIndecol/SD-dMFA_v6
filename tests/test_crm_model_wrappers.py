from __future__ import annotations

import re
from pathlib import Path

from crm_model.cli import run_one_variant
from crm_model.common.run_layout import scenario_variant_root_candidates
from crm_model.coupling.runner import run_loose_coupled
from crm_model.data import load_final_demand
from crm_model.mfa.lifetime_adapter import lifetime_pdf_trea_flodym_adapter
from crm_model.scenarios import deep_update


def test_crm_runtime_exports_are_importable():
    assert callable(run_one_variant)
    assert callable(run_loose_coupled)
    assert callable(load_final_demand)
    assert callable(lifetime_pdf_trea_flodym_adapter)
    assert callable(deep_update)
    assert callable(scenario_variant_root_candidates)


def test_scripts_do_not_directly_import_sd_dmfa():
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    pat = re.compile(r"^\s*(from|import)\s+sd_dmfa\b", flags=re.MULTILINE)
    for path in sorted((root / "scripts").rglob("*.py")):
        txt = path.read_text(encoding="utf-8")
        if pat.search(txt):
            offenders.append(str(path.relative_to(root)))
    assert not offenders, f"Found direct sd_dmfa imports in scripts: {offenders}"


def test_sd_dmfa_package_is_retired():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "src" / "sd_dmfa").exists()
