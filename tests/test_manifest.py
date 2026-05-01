"""Reproducibility test (SPEC §7): two consecutive runs on the same config
produce byte-identical ledger.parquet.
"""

from __future__ import annotations

import hashlib
import json

from aa_model.integration.manifest import make_run_id
from aa_model.integration.orchestrator import run_orchestrator


def test_two_runs_produce_byte_identical_ledger_parquet(base_config_path):
    r1 = run_orchestrator(base_config_path, dry_run=False)
    parquet1 = (r1.output_dir / "ledger.parquet").read_bytes()
    sha1 = hashlib.sha256(parquet1).hexdigest()

    r2 = run_orchestrator(base_config_path, dry_run=False)
    parquet2 = (r2.output_dir / "ledger.parquet").read_bytes()
    sha2 = hashlib.sha256(parquet2).hexdigest()

    assert r1.output_dir == r2.output_dir, "deterministic run_id should produce same output_dir"
    assert r1.manifest.config_hash == r2.manifest.config_hash
    assert r1.manifest.fixtures_hash == r2.manifest.fixtures_hash
    assert sha1 == sha2, "ledger.parquet bytes diverged across two consecutive runs"


def test_manifest_json_is_valid_and_pinned_keys(base_config_path):
    result = run_orchestrator(base_config_path, dry_run=False)
    text = (result.output_dir / "manifest.json").read_text(encoding="utf-8")
    data = json.loads(text)
    expected_keys = {
        "run_id",
        "config_hash",
        "fixtures_hash",
        "library_versions",
        "seed",
        "started_at",
        "finished_at",
        "outputs",
    }
    assert expected_keys <= set(data.keys())
    assert data["seed"] == 42
    assert data["config_hash"].startswith("sha256:")
    assert data["fixtures_hash"].startswith("sha256:")


def test_run_id_derives_from_input_hashes():
    rid = make_run_id("sha256:abcdef0123456789aabb", "sha256:zzzzyyyy00112233xxxx")
    assert rid == "aa-abcdef012345-zzzzyyyy0011"
