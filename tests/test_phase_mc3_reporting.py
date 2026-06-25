"""Phase MC-3 — Monte Carlo reporting tests.

4 acceptance tests:
1. CSV summary output format
2. Parquet paths output format
3. Markdown report generation
4. JSON manifest generation
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from aa_model.monte_carlo import (
    CallTimingScenario,
    MonteCarloConfig,
    ReturnScenario,
    SpendingScenario,
    compute_monte_carlo,
)
from aa_model.monte_carlo.reporting import (
    monte_carlo_paths_dataframe,
    monte_carlo_summary_table,
    write_monte_carlo_artifacts,
)

# ---- fixtures ---------------------------------------------------------------


@pytest.fixture
def synthetic_mc_result() -> object:
    """Generate a small MC result for testing."""
    config = MonteCarloConfig(
        num_paths=20,
        horizon_quarters=8,
        random_seed=44444,
        return_scenarios={
            "eq": ReturnScenario("eq", 0.07, 0.15, 0.05),
        },
        spending_scenarios={
            "base": SpendingScenario("base", 0.03, 0.01, None),
        },
        call_scenarios={
            "pe": CallTimingScenario("pe", [0.25] * 8, 2.5, 0.1),
        },
    )

    return compute_monte_carlo(
        config,
        initial_nav=1_000_000.0,
        initial_liquid_nav=200_000.0,
        annual_spend=50_000.0,
    )


# ---- Test 1: CSV Summary Output -----------------------------------------------


def test_csv_summary_output(synthetic_mc_result: object, tmp_path: Path) -> None:
    """T1: CSV summary contains all metrics with correct headers."""
    written = write_monte_carlo_artifacts(
        synthetic_mc_result,
        tmp_path,
        write_summary=True,
        write_paths=False,
        write_report=False,
        write_manifest=False,
    )

    summary_path = written["summary"]
    assert summary_path.exists()

    df = pd.read_csv(summary_path)
    assert "metric" in df.columns
    assert "value" in df.columns
    assert len(df) > 10  # Multiple metrics

    # Check for key metrics
    metrics = set(df["metric"].tolist())
    assert "probability_of_breach" in metrics
    assert "median_coverage_months" in metrics
    assert "median_final_nav" in metrics


# ---- Test 2: Parquet Paths Output -------------------------------------------


def test_parquet_paths_output(synthetic_mc_result: object, tmp_path: Path) -> None:
    """T2: Parquet paths contains all path/quarter data."""
    written = write_monte_carlo_artifacts(
        synthetic_mc_result,
        tmp_path,
        write_summary=False,
        write_paths=True,
        write_report=False,
        write_manifest=False,
    )

    paths_path = written["paths"]
    assert paths_path.exists()

    df = pd.read_parquet(paths_path)

    # Check schema
    expected_cols = {
        "path_id",
        "seed",
        "quarter",
        "nav_usd",
        "liquid_nav_usd",
        "spending_usd",
        "coverage_months",
        "is_breach",
        "final_nav_usd",
        "cumulative_return_pct",
    }
    assert expected_cols.issubset(set(df.columns))

    # Check data
    assert len(df) == 20 * 8  # 20 paths × 8 quarters
    assert df["path_id"].max() == 19
    assert df["quarter"].max() == 7


# ---- Test 3: Markdown Report Generation -----------------------------------


def test_markdown_report_generation(synthetic_mc_result: object, tmp_path: Path) -> None:
    """T3: Markdown report contains key sections and metrics."""
    written = write_monte_carlo_artifacts(
        synthetic_mc_result,
        tmp_path,
        write_summary=False,
        write_paths=False,
        write_report=True,
        write_manifest=False,
    )

    report_path = written["report"]
    assert report_path.exists()

    content = report_path.read_text()

    # Check for key sections
    assert "Monte Carlo Liquidity Stress Report" in content
    assert "Key Results" in content
    assert "Coverage Percentiles" in content
    assert "Required Liquid NAV" in content
    assert "Interpretation" in content
    assert "Caveats" in content

    # Check for standing advisory
    assert "Standing Advisory" in content
    assert "synthetic" in content.lower() or "not decision-grade" in content.lower()


# ---- Test 4: JSON Manifest Generation --------------------------------------


def test_json_manifest_generation(synthetic_mc_result: object, tmp_path: Path) -> None:
    """T4: JSON manifest contains config hash, fixture hash, and metrics."""
    written = write_monte_carlo_artifacts(
        synthetic_mc_result,
        tmp_path,
        write_summary=False,
        write_paths=False,
        write_report=False,
        write_manifest=True,
    )

    manifest_path = written["manifest"]
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text())

    # Check structure
    assert "timestamp_utc" in manifest
    assert "config_hash" in manifest
    assert "fixture_hash" in manifest
    assert "num_paths" in manifest
    assert "horizon_quarters" in manifest
    assert "metrics" in manifest

    # Check metrics
    metrics = manifest["metrics"]
    assert "probability_of_breach" in metrics
    assert "median_coverage_months" in metrics
    assert "required_liquid_nav_80pct_confidence" in metrics

    # Hashes should be non-empty strings
    assert len(manifest["config_hash"]) == 64  # SHA256
    assert len(manifest["fixture_hash"]) == 64


# ---- Test 5: All Artifacts Written Together ---------------------------------


def test_all_artifacts_written(synthetic_mc_result: object, tmp_path: Path) -> None:
    """Integration: All 4 artifacts written simultaneously."""
    written = write_monte_carlo_artifacts(
        synthetic_mc_result,
        tmp_path,
    )

    assert len(written) == 4
    assert "summary" in written
    assert "paths" in written
    assert "report" in written
    assert "manifest" in written

    for artifact_path in written.values():
        assert artifact_path.exists()
        assert artifact_path.stat().st_size > 0


# ---- Test 6: In-Memory DataFrames (no file I/O) ----------------------------


def test_summary_table_dataframe(synthetic_mc_result: object) -> None:
    """In-memory summary table (no file I/O)."""
    df = monte_carlo_summary_table(synthetic_mc_result)

    assert isinstance(df, pd.DataFrame)
    assert "metric" in df.columns
    assert "value" in df.columns
    assert len(df) > 10


def test_paths_dataframe(synthetic_mc_result: object) -> None:
    """In-memory paths table (no file I/O)."""
    df = monte_carlo_paths_dataframe(synthetic_mc_result)

    assert isinstance(df, pd.DataFrame)
    assert "path_id" in df.columns
    assert "quarter" in df.columns
    assert "coverage_months" in df.columns
    assert len(df) == 20 * 8  # 20 paths × 8 quarters


# ---- Test 7: Advisory Caveat Present ----------------------------------------


def test_advisory_caveat_in_all_outputs(synthetic_mc_result: object, tmp_path: Path) -> None:
    """Advisory caveat should appear in report and manifest."""
    write_monte_carlo_artifacts(
        synthetic_mc_result,
        tmp_path,
    )

    # Check report
    report_content = (tmp_path / "monte_carlo_report.md").read_text()
    assert "Advisory" in report_content or "advisory" in report_content

    # Check manifest
    manifest = json.loads((tmp_path / "monte_carlo_manifest.json").read_text())
    assert "advisory_caveat" in manifest
    assert len(manifest["advisory_caveat"]) > 0
