"""Phase 24 — entity study CLI. Synthetic fixtures only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aa_model.entity.cli import main

_FIXTURE = "data/fixtures/entities/entity_synth_a.yaml"
_POLICY = "data/fixtures/entities/entity_synth_a_policy.yaml"


def _args(repo_root: Path, out: Path, *extra: str) -> list[str]:
    return [
        "--fixture",
        str(repo_root / _FIXTURE),
        "--policy",
        str(repo_root / _POLICY),
        "--out",
        str(out),
        *extra,
    ]


def test_cli_writes_study(repo_root: Path, tmp_path: Path) -> None:
    rc = main(_args(repo_root, tmp_path))
    assert rc == 0
    assert (tmp_path / "study.md").exists()
    assert (tmp_path / "study.xlsx").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["entity_id"] == "entity_synth_a"
    assert manifest["policy_version"] == "synth_a_policy_v1"
    assert manifest["formats"] == ["md", "xlsx"]
    assert manifest["files"] == ["study.md", "study.xlsx"]
    assert len(manifest["content_hash"]) == 64  # sha256 hex


def test_cli_dry_run_writes_nothing(repo_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "dry"
    rc = main(_args(repo_root, out, "--dry-run"))
    assert rc == 0
    assert not out.exists()  # nothing written


def test_cli_md_only(repo_root: Path, tmp_path: Path) -> None:
    rc = main(_args(repo_root, tmp_path, "--formats", "md"))
    assert rc == 0
    assert (tmp_path / "study.md").exists()
    assert not (tmp_path / "study.xlsx").exists()


def test_cli_without_policy_runs(repo_root: Path, tmp_path: Path) -> None:
    rc = main(["--fixture", str(repo_root / _FIXTURE), "--out", str(tmp_path)])
    assert rc == 0
    assert json.loads((tmp_path / "manifest.json").read_text())["policy_version"] is None
    assert "## Allocation vs. strategic target" not in (tmp_path / "study.md").read_text()


def test_cli_manifest_deterministic(repo_root: Path, tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    main(_args(repo_root, a))
    main(_args(repo_root, b))
    assert (a / "manifest.json").read_bytes() == (b / "manifest.json").read_bytes()
    assert (a / "study.md").read_bytes() == (b / "study.md").read_bytes()


def test_cli_unknown_format_errors(repo_root: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(_args(repo_root, tmp_path, "--formats", "pdf"))


def test_cli_policy_entity_mismatch_errors(repo_root: Path, tmp_path: Path) -> None:
    # synthetic policy is for entity_synth_a; point at a different fixture id
    other = tmp_path / "other.yaml"
    other.write_text(
        "fixture_version: t\nentity_id: other_entity\nas_of_date: 2026-04-30\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="does not match"):
        main(
            [
                "--fixture",
                str(other),
                "--policy",
                str(repo_root / _POLICY),
                "--out",
                str(tmp_path / "x"),
            ]
        )
