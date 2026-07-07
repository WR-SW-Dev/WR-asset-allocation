"""Tests for Morningstar Direct index-return ingestion.

All fixtures are TINY SYNTHETIC data built in-test (CSV text + openpyxl XLSX in
tmp_path). No real Morningstar export is read, imported, or committed. The tests
that assert "all 36 names / preserves display names" load the COMMITTED universe
config and synthesize a workbook from its display names — so they verify the
config <-> parser contract without any licensed data.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pandas as pd
import pytest
from aa_model.ingestion.morningstar_returns import (
    MorningstarIngestError,
    index_keys_for_asset_class,
    load_asset_class_map,
    load_index_universe,
    monthly_return_series,
    run_ingestion,
    trailing_return,
    validate_asset_class_map,
)
from aa_model.ingestion.morningstar_schemas import NORMALIZED_COLUMNS

_REPO_ROOT = Path(__file__).resolve().parents[1]
_UNIVERSE = _REPO_ROOT / "configs" / "morningstar_index_universe.yaml"
_MAP = _REPO_ROOT / "configs" / "asset_class_index_map.yaml"

_MS_HEADER = [
    "Name",
    "Return Date (Mo-End)",
    "Base Currency",
    "Total Ret 1 Mo (Mo-End) Base Currency",
    "Total Ret 3 Mo (Mo-End) Base Currency",
    "Total Ret 6 Mo (Mo-End) Base Currency",
    "Total Ret 1 Yr (Mo-End) Base Currency",
    "Total Ret Annlzd 3 Yr (Mo-End) Base Currency",
    "Total Ret Annlzd 5 Yr (Mo-End) Base Currency",
    "Total Ret Annlzd 10 Yr (Mo-End) Base Currency",
    "Total Ret % Rank Cat 10 Yr (Mo-End)",
    "Total Ret Annlzd 15 Yr (Mo-End) Base Currency",
    "Inception Date",
    "Total Ret Inception (Mo-End) Base Currency",
]

# column indices in _MS_HEADER for the horizons we assemble in fixtures
_H = {
    "1M": 3,
    "3M": 4,
    "6M": 5,
    "1Y": 6,
    "3Y_ann": 7,
    "5Y_ann": 8,
    "10Y_ann": 9,
    "15Y_ann": 11,
    "inception_ann": 13,
}

_SUMMARY_ROWS = [
    ["Summary Statistics"] + [None] * 13,
    ["Eightieth Percentile", None, None, -5.86] + [None] * 10,
    ["Sum", None, None, -122.4] + [None] * 10,
    ["Count", 36, None, 34] + [None] * 10,
    ["Standard Deviation", None, None, 4.30] + [None] * 10,
]


def _ms_row(name, return_date, currency="US Dollar", **horizons):
    row = [name, return_date, currency] + [None] * 11
    for h, v in horizons.items():
        row[_H[h]] = v
    return row


def _write_ms_xlsx(
    path: Path, data_rows, *, n_title_rows=0, with_summary=True, sheet="Common Indices"
):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for _ in range(n_title_rows):
        ws.append(["Index Returns (synthetic)"] + [None] * 13)
    ws.append(_MS_HEADER)
    for r in data_rows:
        ws.append(r)
    if with_summary:
        ws.append([None] * 14)
        for s in _SUMMARY_ROWS:
            ws.append(s)
    wb.save(path)


def _write_csv(path: Path, rows):
    lines = [",".join("" if c is None else str(c) for c in row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- schema / basic parse --------------------------------------------------


def test_output_schema_matches_expected_columns(tmp_path):
    p = tmp_path / "ms.xlsx"
    _write_ms_xlsx(p, [_ms_row("S&P 500 TR USD", "2026-03-31", **{"1M": -4.98, "10Y_ann": 13.0})])
    res = run_ingestion(
        p, universe_path=_UNIVERSE, asset_class_map_path=_MAP, allow_missing_configured=True
    )
    assert list(res.normalized.columns) == list(NORMALIZED_COLUMNS)


def test_percentage_converts_to_decimal(tmp_path):
    p = tmp_path / "ms.xlsx"
    _write_ms_xlsx(p, [_ms_row("S&P 500 TR USD", "2026-03-31", **{"1M": 1.25, "10Y_ann": 13.0})])
    res = run_ingestion(p, universe_path=_UNIVERSE, allow_missing_configured=True)
    v = trailing_return(res.normalized, "sp_500_tr_usd", "1M")
    assert v == pytest.approx(0.0125)


def test_decimal_scale_not_double_divided(tmp_path):
    p = tmp_path / "ms.xlsx"
    _write_ms_xlsx(p, [_ms_row("S&P 500 TR USD", "2026-03-31", **{"1M": 0.0125, "10Y_ann": 0.13})])
    res = run_ingestion(
        p, universe_path=_UNIVERSE, value_scale="decimal", allow_missing_configured=True
    )
    v = trailing_return(res.normalized, "sp_500_tr_usd", "1M")
    assert v == pytest.approx(0.0125)  # unchanged, NOT 0.000125


# ---- wide / long CSV -------------------------------------------------------


def test_wide_csv_parses(tmp_path):
    p = tmp_path / "wide.csv"
    _write_csv(
        p,
        [
            ["Date", "S&P 500 TR USD", "Russell 1000 TR USD"],
            ["2026-01-31", 1.0, 1.5],
            ["2026-02-28", -0.5, -0.75],
        ],
    )
    res = run_ingestion(p, universe_path=_UNIVERSE, allow_missing_configured=True)
    s = monthly_return_series(res.normalized, "sp_500_tr_usd")
    assert len(s) == 2
    assert s.loc["2026-01-31"] == pytest.approx(0.01)
    assert res.meta["layout"] == "wide"


def test_long_csv_parses(tmp_path):
    p = tmp_path / "long.csv"
    _write_csv(
        p,
        [
            ["Date", "Name", "Return"],
            ["2026-01-31", "S&P 500 TR USD", 1.0],
            ["2026-02-28", "S&P 500 TR USD", -0.5],
        ],
    )
    res = run_ingestion(p, universe_path=_UNIVERSE, allow_missing_configured=True)
    s = monthly_return_series(res.normalized, "sp_500_tr_usd")
    assert len(s) == 2
    assert res.meta["layout"] == "long"


def test_xlsx_with_extra_header_rows(tmp_path):
    p = tmp_path / "ms_titles.xlsx"
    _write_ms_xlsx(
        p,
        [_ms_row("S&P 500 TR USD", "2026-03-31", **{"1M": -4.98, "10Y_ann": 13.0})],
        n_title_rows=3,
    )
    res = run_ingestion(p, universe_path=_UNIVERSE, allow_missing_configured=True)
    assert res.meta["layout"] == "morningstar_common_indices"
    assert trailing_return(res.normalized, "sp_500_tr_usd", "1M") == pytest.approx(-0.0498)


# ---- quality flags ---------------------------------------------------------


def test_duplicate_dates_flagged(tmp_path):
    p = tmp_path / "long.csv"
    _write_csv(
        p,
        [
            ["Date", "Name", "Return"],
            ["2026-01-31", "S&P 500 TR USD", 1.0],
            ["2026-01-31", "S&P 500 TR USD", 1.1],
        ],
    )
    res = run_ingestion(p, universe_path=_UNIVERSE, allow_missing_configured=True)
    flags = res.normalized["quality_flag"].tolist()
    assert all("DUPLICATE_DATE" in f for f in flags)


def test_missing_month_flagged(tmp_path):
    # NCREIF-style: blank 1 Mo (quarterly source) -> MISSING_MONTH on the 1M row.
    p = tmp_path / "ms.xlsx"
    _write_ms_xlsx(
        p,
        [_ms_row("NCREIF Property", "2025-12-31", **{"3M": 1.14, "5Y_ann": 3.8, "10Y_ann": 4.85})],
    )
    res = run_ingestion(p, universe_path=_UNIVERSE, allow_missing_configured=True)
    one_m = res.normalized[
        (res.normalized["index_key"] == "ncreif_property") & (res.normalized["horizon"] == "1M")
    ]
    assert len(one_m) == 1
    assert pd.isna(one_m.iloc[0]["return_decimal"])
    assert "MISSING_MONTH" in one_m.iloc[0]["quality_flag"]


def test_non_month_end_date_normalized_and_flagged(tmp_path):
    p = tmp_path / "long.csv"
    _write_csv(p, [["Date", "Name", "Return"], ["2026-03-15", "S&P 500 TR USD", 1.0]])
    res = run_ingestion(p, universe_path=_UNIVERSE, allow_missing_configured=True)
    row = res.normalized.iloc[0]
    assert str(row["date"]) == "2026-03-31"  # snapped to month end
    assert "NON_MONTH_END_DATE" in row["quality_flag"]


def test_stale_series_flagged(tmp_path):
    # modal date is 2026-03-31; the hedge-fund row lags -> STALE_SERIES.
    p = tmp_path / "ms.xlsx"
    _write_ms_xlsx(
        p,
        [
            _ms_row("S&P 500 TR USD", "2026-03-31", **{"1M": -4.98, "10Y_ann": 13.0}),
            _ms_row("Russell 1000 TR USD", "2026-03-31", **{"1M": -4.97, "10Y_ann": 13.0}),
            _ms_row("Credit Suisse Hedge Fund USD", "2025-10-31", **{"1M": -0.3, "10Y_ann": 5.2}),
        ],
    )
    res = run_ingestion(p, universe_path=_UNIVERSE, allow_missing_configured=True)
    cov = res.coverage.set_index("index_key")
    assert cov.loc["credit_suisse_hedge_fund_usd", "stale_series"]
    assert not cov.loc["sp_500_tr_usd", "stale_series"]


def test_short_history_missing_multiyear_not_dropped(tmp_path):
    # ETF with only 1M/3M present; 5Y/10Y blank -> kept, flagged SHORT_HISTORY.
    p = tmp_path / "ms.xlsx"
    _write_ms_xlsx(
        p,
        [_ms_row("Roundhill Magnificent Seven ETF", "2026-03-31", **{"1M": -5.7, "3M": 4.0})],
    )
    res = run_ingestion(p, universe_path=_UNIVERSE, allow_missing_configured=True)
    idx = res.normalized[res.normalized["index_key"] == "roundhill_magnificent_seven_etf"]
    assert not idx.empty  # not dropped
    assert trailing_return(
        res.normalized, "roundhill_magnificent_seven_etf", "1M"
    ) == pytest.approx(-0.057)
    assert idx["quality_flag"].str.contains("SHORT_HISTORY").any()


# ---- mapping contract ------------------------------------------------------


def test_unknown_index_column_fails_unless_allowed(tmp_path):
    p = tmp_path / "wide.csv"
    _write_csv(p, [["Date", "S&P 500 TR USD", "Totally Made Up Index"], ["2026-01-31", 1.0, 2.0]])
    with pytest.raises(MorningstarIngestError):
        run_ingestion(p, universe_path=_UNIVERSE, allow_missing_configured=True)
    # allowed -> succeeds, unmapped name reported and excluded from the store
    res = run_ingestion(
        p, universe_path=_UNIVERSE, allow_unmapped=True, allow_missing_configured=True
    )
    assert "Totally Made Up Index" in res.unmapped_names
    assert "S&P 500 TR USD" not in res.unmapped_names


def test_missing_configured_fails_unless_allowed(tmp_path):
    p = tmp_path / "ms.xlsx"
    _write_ms_xlsx(p, [_ms_row("S&P 500 TR USD", "2026-03-31", **{"1M": -4.98})])
    with pytest.raises(MorningstarIngestError):
        run_ingestion(p, universe_path=_UNIVERSE)  # 35 configured indices missing


# ---- full-basket contract (all 36 names, summary exclusion) ----------------


def test_captures_all_36_and_excludes_summary_rows(tmp_path):
    universe = load_index_universe(_UNIVERSE)
    names = [e.display_name for e in universe.indices]
    assert len(names) == 36
    rows = [
        _ms_row(n, "2026-03-31", **{"1M": 1.0, "3M": 2.0, "5Y_ann": 5.0, "10Y_ann": 8.0})
        for n in names
    ]
    p = tmp_path / "ms_all.xlsx"
    _write_ms_xlsx(p, rows, with_summary=True)
    res = run_ingestion(p, universe_path=_UNIVERSE, asset_class_map_path=_MAP)
    got = set(res.normalized["index_key"].unique())
    assert got == set(e.index_key for e in universe.indices)
    assert not res.unmapped_names
    assert not res.missing_configured
    # summary labels never become index rows
    for bad in ("Summary Statistics", "Sum", "Count", "Standard Deviation"):
        assert bad not in res.normalized["index_key"].tolist()
    # every configured index appears exactly once in coverage
    assert len(res.coverage) == 36
    assert res.coverage["present_in_workbook"].all()


def test_preserves_exact_display_names(tmp_path):
    # A short-form variant ("S&P 500", as used in the copied pivot view) must NOT
    # map — only the exact configured display name does. Stray surrounding
    # whitespace IS tolerated (Excel cells often carry it); substance must match.
    bad = tmp_path / "bad.xlsx"
    _write_ms_xlsx(bad, [_ms_row("S&P 500", "2026-03-31", **{"1M": 1.0})])
    with pytest.raises(MorningstarIngestError):
        run_ingestion(bad, universe_path=_UNIVERSE, allow_missing_configured=True)

    ok = tmp_path / "ok.xlsx"
    _write_ms_xlsx(
        ok, [_ms_row("  S&P 500 TR USD  ", "2026-03-31", **{"1M": 1.0, "10Y_ann": 13.0})]
    )
    res = run_ingestion(ok, universe_path=_UNIVERSE, allow_missing_configured=True)
    row = res.coverage.set_index("index_key").loc["sp_500_tr_usd"]
    assert row["display_name"] == "S&P 500 TR USD"  # exact, from config


# ---- config bridges --------------------------------------------------------


def test_asset_class_map_validates_against_universe():
    universe = load_index_universe(_UNIVERSE)
    map_cfg = load_asset_class_map(_MAP)
    validate_asset_class_map(map_cfg, universe)  # must not raise


def test_index_keys_for_asset_class():
    map_cfg = load_asset_class_map(_MAP)
    r = index_keys_for_asset_class(map_cfg, "US Equity - Total Market", "US Total Market")
    assert r["primary_index_key"] == "russell_3000_tr_usd"
    r2 = index_keys_for_asset_class(
        map_cfg, "Alternatives - Private Credit", "Private Credit Proxy"
    )
    assert r2["requires_approval"] is True
