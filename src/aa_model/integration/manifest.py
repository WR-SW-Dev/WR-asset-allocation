"""Reproducibility manifest. SPEC §5.3 + §8.

Each orchestrator run writes ``manifest.json`` next to the ledger. The
``run_id`` is deterministic in the configs + fixture inputs (truncated
hashes), so reruns of the same config write into the same run dir with
identical content. Per-invocation timestamps are present for audit but do
not influence reproducibility.
"""

from __future__ import annotations

import importlib.metadata as md
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_TRACKED_LIBS = ("aa_model", "numpy", "pandas", "pydantic", "pyyaml", "pyarrow", "jinja2")


def _library_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for lib in _TRACKED_LIBS:
        try:
            versions[lib] = md.version(lib)
        except md.PackageNotFoundError:
            versions[lib] = "unknown"
    return versions


def make_run_id(config_hash: str, fixtures_hash: str) -> str:
    """Deterministic run id from input hashes.

    Two invocations with identical configs + fixtures produce the same
    ``run_id`` and write into the same run dir; the parquet content is
    byte-identical on rerun.
    """
    cfg = config_hash.split(":", 1)[-1][:12]
    fix = fixtures_hash.split(":", 1)[-1][:12]
    return f"aa-{cfg}-{fix}"


def utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Manifest:
    run_id: str
    config_hash: str
    fixtures_hash: str
    library_versions: dict[str, str]
    seed: int
    started_at: str
    finished_at: str
    outputs: list[str] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        *,
        run_id: str,
        config_hash: str,
        fixtures_hash: str,
        seed: int,
        started_at: str,
        finished_at: str,
        outputs: list[str],
    ) -> Manifest:
        return cls(
            run_id=run_id,
            config_hash=config_hash,
            fixtures_hash=fixtures_hash,
            library_versions=_library_versions(),
            seed=seed,
            started_at=started_at,
            finished_at=finished_at,
            outputs=outputs,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def write(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, sort_keys=True, indent=2)
            f.write("\n")
