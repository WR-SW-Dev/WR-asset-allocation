"""Tests for the optional Morningstar benchmark -> CMA calibration adapter.

Hermetic: a synthetic mini-feed (copy of morningstar_feed.py + tiny CSVs) is
built in tmp_path, so no network and no dependency on the real 10yr data. The
whole module is skipped if the feed module cannot be located on this machine.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from aa_model.assumptions import benchmark_calibration as bc


def _find_feed_module() -> Path | None:
    try:
        import morningstar_feed as m  # noqa: F401

        return Path(m.__file__)
    except Exception:
        pass
    candidates = [
        Path(__file__).resolve().parents[2].parent / "morningstar" / "morningstar_feed.py",
        Path("/mnt/c/Projects/morningstar/morningstar_feed.py"),
    ]
    return next((c for c in candidates if c.exists()), None)


_FEED_SRC = _find_feed_module()
pytestmark = pytest.mark.skipif(_FEED_SRC is None, reason="morningstar_feed not available")

_EQ = "S&P 500 TR USD"
_BOND = "Bloomberg US Agg Bond TR USD"


def _build_synthetic_feed(dirpath: Path, seed: int = 7, n: int = 600) -> None:
    """Write a two-benchmark mini-feed with the real column contract."""
    shutil.copy(_FEED_SRC, dirpath / "morningstar_feed.py")
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-01", periods=n)
    specs = {_EQ: ("F00000W7S7", 0.0004, 0.010), _BOND: ("FOUSA05Y32", 0.0001, 0.003)}
    idx_rows, ret_rows = [], []
    for name, (sid, mu, sd) in specs.items():
        r = rng.normal(mu, sd, n)  # daily fractional returns
        level = 10000.0 * np.cumprod(1.0 + r)
        pct = pd.Series(level).pct_change() * 100.0
        for d, lv, p in zip(dates, level, pct, strict=False):
            idx_rows.append((name, sid, d.date(), lv))
            ret_rows.append((name, sid, d.date(), "" if pd.isna(p) else p))
    pd.DataFrame(idx_rows, columns=["Benchmark", "Id", "Date", "Daily Return Index"]).to_csv(
        dirpath / "benchmark_return_index_10yr.csv", index=False
    )
    pd.DataFrame(ret_rows, columns=["Benchmark", "Id", "Date", "daily_ret_pct"]).to_csv(
        dirpath / "benchmark_daily_ret_pct_10yr.csv", index=False
    )


@pytest.fixture()
def synthetic_feed(tmp_path, monkeypatch):
    _build_synthetic_feed(tmp_path)
    monkeypatch.setenv("MORNINGSTAR_FEED_DIR", str(tmp_path))
    sys.modules.pop("morningstar_feed", None)  # force re-import against tmp DATA_DIR
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    sys.modules.pop("morningstar_feed", None)


def test_load_proxy_map_reads_repo_config():
    proxies, params = bc.load_proxy_map()
    assert {"cash", "public_bond", "public_equity"} <= set(proxies)
    assert "pe_buyout" not in proxies  # intentionally no public proxy
    assert params["lookback_years"] >= 1
    assert params["annualization_factor"] == 252


def test_empirical_moments_shapes_and_ordering(synthetic_feed):
    proxies = {"public_equity": _EQ, "public_bond": _BOND}
    m = bc.empirical_moments(proxies, lookback_years=2)

    assert list(m.vol_annual.index) == ["public_equity", "public_bond"]
    assert list(m.corr.index) == ["public_equity", "public_bond"]
    assert m.n_obs > 100
    # equity synthetic sd 1.0%/day -> ~0.159 annualized; bond 0.3%/day -> ~0.048
    assert m.vol_annual["public_equity"] > m.vol_annual["public_bond"] > 0
    assert 0.10 < m.vol_annual["public_equity"] < 0.25
    # correlation matrix: unit diagonal, symmetric, in [-1, 1]
    assert np.allclose(np.diag(m.corr.values), 1.0)
    assert np.allclose(m.corr.values, m.corr.values.T)
    assert (m.corr.abs().values <= 1.0 + 1e-9).all()


def test_to_cma_yaml_overlay_preserves_unmapped_bucket(synthetic_feed, tmp_path):
    base = {
        "expected_returns_annual": {"public_equity": 0.0, "public_bond": 0.0, "pe_buyout": 0.0},
        "vol_annual": {"public_equity": 0.16, "public_bond": 0.04, "pe_buyout": 0.20},
        "correlations": {
            "public_equity": {"public_equity": 1.0, "public_bond": 0.0, "pe_buyout": 0.0},
            "public_bond": {"public_equity": 0.0, "public_bond": 1.0, "pe_buyout": 0.0},
            "pe_buyout": {"public_equity": 0.0, "public_bond": 0.0, "pe_buyout": 1.0},
        },
        "liquidity": {"public_equity": "liquid", "public_bond": "liquid", "pe_buyout": "illiquid"},
    }
    base_path = tmp_path / "cma_base.yaml"
    import yaml

    base_path.write_text(yaml.safe_dump(base), encoding="utf-8")

    m = bc.empirical_moments({"public_equity": _EQ, "public_bond": _BOND}, lookback_years=2)
    doc = bc.to_cma_yaml_dict(m, base_cma_path=base_path)

    # calibrated bucket vol replaced; unmapped bucket preserved
    assert doc["vol_annual"]["public_equity"] != 0.16
    assert doc["vol_annual"]["pe_buyout"] == 0.20
    assert doc["liquidity"]["pe_buyout"] == "illiquid"
    # pe_buyout stays uncorrelated with the calibrated buckets
    assert doc["correlations"]["pe_buyout"]["public_equity"] == 0.0
    assert doc["correlations"]["public_equity"]["public_equity"] == 1.0
    assert "_provenance" in doc
