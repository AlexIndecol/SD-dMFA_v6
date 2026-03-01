from __future__ import annotations

import numpy as np
import pytest

from crm_model.data.io import load_lifetime_distributions
from crm_model.mfa.lifetime_adapter import lifetime_pdf_trea_flodym_adapter


def test_lognormal_lifetimes_supported(tmp_path):
    p = tmp_path / "lifetimes.csv"
    p.write_text(
        "\n".join(
            [
                "cohort_year,material,region,end_use,dist,param,value",
                "2000,tin,EU27,construction,lognormal,mean_years,12",
                "2000,tin,EU27,construction,lognormal,sigma,0.5",
            ]
        ),
        encoding="utf-8",
    )

    lt = load_lifetime_distributions(p)
    pdf = lifetime_pdf_trea_flodym_adapter(
        lt,
        years=[2000, 2001, 2002],
        material="tin",
        regions=["EU27"],
        end_uses=["construction"],
    )

    assert pdf.shape == (3, 1, 1, 3)
    assert (pdf >= 0.0).all()


def test_lifetime_duplicates_fail_fast(tmp_path):
    p = tmp_path / "lifetimes_dup.csv"
    p.write_text(
        "\n".join(
            [
                "cohort_year,material,region,end_use,dist,param,value",
                "2000,tin,EU27,construction,weibull,mean_years,10",
                "2000,tin,EU27,construction,weibull,mean_years,11",
                "2000,tin,EU27,construction,weibull,shape,3",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate"):
        load_lifetime_distributions(p)


def test_lifetime_invalid_parameterization_fail_fast(tmp_path):
    p = tmp_path / "lifetimes_bad.csv"
    p.write_text(
        "\n".join(
            [
                "cohort_year,material,region,end_use,dist,param,value",
                "2000,tin,EU27,construction,lognormal,mean_years,10",
                "2000,tin,EU27,construction,lognormal,sigma,-0.2",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="sigma"):
        load_lifetime_distributions(p)


def test_flodym_lifetime_adapter_weibull_valid_pdf(tmp_path):
    p = tmp_path / "lifetimes_weibull.csv"
    p.write_text(
        "\n".join(
            [
                "cohort_year,material,region,end_use,dist,param,value",
                "2000,tin,EU27,construction,weibull,mean_years,10",
                "2000,tin,EU27,construction,weibull,shape,3",
            ]
        ),
        encoding="utf-8",
    )

    lt = load_lifetime_distributions(p)
    years = list(range(2000, 2008))
    pdf = lifetime_pdf_trea_flodym_adapter(
        lt,
        years=years,
        material="tin",
        regions=["EU27"],
        end_uses=["construction"],
        max_age=20,
    )

    assert pdf.shape == (len(years), 1, 1, 21)
    assert np.all(pdf >= 0.0)
    assert np.all(pdf <= 1.0)
    assert np.allclose(pdf[:, :, :, 0], 0.0, atol=1e-12)
    assert np.all(pdf.sum(axis=3) <= 1.0 + 1e-9)


def test_flodym_lifetime_adapter_lognormal_valid_pdf(tmp_path):
    p = tmp_path / "lifetimes_lognormal.csv"
    p.write_text(
        "\n".join(
            [
                "cohort_year,material,region,end_use,dist,param,value",
                "2000,tin,EU27,construction,lognormal,mean_years,12",
                "2000,tin,EU27,construction,lognormal,sigma,0.5",
            ]
        ),
        encoding="utf-8",
    )

    lt = load_lifetime_distributions(p)
    years = list(range(2000, 2008))
    pdf = lifetime_pdf_trea_flodym_adapter(
        lt,
        years=years,
        material="tin",
        regions=["EU27"],
        end_uses=["construction"],
        max_age=20,
    )

    assert pdf.shape == (len(years), 1, 1, 21)
    assert np.all(pdf >= 0.0)
    assert np.all(pdf <= 1.0)
    assert np.allclose(pdf[:, :, :, 0], 0.0, atol=1e-12)
    assert np.all(pdf.sum(axis=3) <= 1.0 + 1e-9)


def test_flodym_lifetime_adapter_fixed_spike(tmp_path):
    p = tmp_path / "lifetimes_fixed.csv"
    p.write_text(
        "\n".join(
            [
                "cohort_year,material,region,end_use,dist,param,value",
                "2000,tin,EU27,construction,fixed,mean_years,7",
            ]
        ),
        encoding="utf-8",
    )

    lt = load_lifetime_distributions(p)
    years = list(range(2000, 2008))
    pdf = lifetime_pdf_trea_flodym_adapter(
        lt,
        years=years,
        material="tin",
        regions=["EU27"],
        end_uses=["construction"],
        max_age=20,
    )

    assert pdf.shape == (len(years), 1, 1, 21)
    # fixed mean_years=7 -> deterministic retirement at age 7
    assert np.allclose(pdf[:, 0, 0, 7], 1.0, atol=1e-12)
    assert np.allclose(pdf[:, 0, 0, :7], 0.0, atol=1e-12)
    assert np.allclose(pdf[:, 0, 0, 8:], 0.0, atol=1e-12)
