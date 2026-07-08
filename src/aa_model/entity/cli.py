"""Entity study CLI — one command to render a Wake Robin study.

    python scripts/run_entity_study.py \\
        --fixture data/external/entity_jd_local.yaml \\
        --policy  data/external/entity_jd_policy_local.yaml

Registered as ``aa-entity-study`` in pyproject ``[project.scripts]``.

Loads an entity fixture (+ optional strategic policy), renders the study to
markdown and/or xlsx, and writes a deterministic ``manifest.json`` (entity,
versions, content_hash, files). No wall-clock is written, so the manifest is
byte-stable for identical inputs. Real (client) fixtures live in gitignored
paths; the default output dir is under the gitignored ``data/processed/``.
"""

from __future__ import annotations

import argparse
import json
import re as _re
from pathlib import Path

from aa_model.entity import (
    content_hash,
    export_study_xlsx,
    fixture_from_curated_positions,
    load_entity_fixture,
    load_entity_policy,
    read_investment_summary_positions,
    render_study_markdown,
)

_VALID_FORMATS = ("md", "xlsx")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aa-entity-study",
        description="Render a Wake Robin entity asset-allocation study.",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--fixture", type=Path, help="entity fixture YAML/JSON")
    src.add_argument(
        "--from-investment-summary",
        dest="inv_summary",
        type=Path,
        help="build the fixture from the Investment Summary workbook (needs --entity)",
    )
    p.add_argument(
        "--entity",
        default=None,
        help='entity label to filter (with --from-investment-summary), e.g. "Jim\'s Trust / J&D"',
    )
    p.add_argument(
        "--as-of",
        default="2026-03-31",
        help="as-of date YYYY-MM-DD when building from the Investment Summary",
    )
    p.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="optional strategic-policy YAML/JSON (enables the allocation-vs-target section)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output dir (default: data/processed/entity_studies/<entity_id>_<hash8>)",
    )
    p.add_argument(
        "--formats",
        default="md,xlsx",
        help="comma-separated subset of {md,xlsx} (default: md,xlsx)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="load + validate + hash, print summary, write nothing",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    unknown = sorted(set(formats) - set(_VALID_FORMATS))
    if unknown or not formats:
        raise SystemExit(
            f"--formats must be a non-empty subset of {list(_VALID_FORMATS)}; got {args.formats!r}"
        )

    if args.inv_summary is not None:
        if not args.entity:
            raise SystemExit("--from-investment-summary requires --entity")
        positions = read_investment_summary_positions(args.inv_summary, args.entity)
        if not positions:
            raise SystemExit(f"no positions found for entity {args.entity!r}")
        eid = "entity_" + (_re.sub(r"[^a-z0-9]+", "_", args.entity.lower()).strip("_") or "x")
        fixture = fixture_from_curated_positions(
            positions,
            entity_id=eid,
            as_of_date=args.as_of,
            fixture_version=f"{eid}_{args.as_of}",
        )
    else:
        fixture = load_entity_fixture(args.fixture)
    policy = load_entity_policy(args.policy) if args.policy else None
    if policy is not None and policy.entity_id != fixture.entity_id:
        raise SystemExit(
            f"policy.entity_id ({policy.entity_id!r}) does not match "
            f"fixture.entity_id ({fixture.entity_id!r})"
        )
    digest = content_hash(fixture)
    out = args.out or Path("data/processed/entity_studies") / f"{fixture.entity_id}_{digest[:8]}"

    print(f"entity_id:    {fixture.entity_id}")
    print(f"as_of_date:   {fixture.as_of_date.isoformat()}")
    print(f"fixture:      {fixture.fixture_version}")
    print(
        f"policy:       {policy.policy_version if policy else '(none — allocation section omitted)'}"
    )
    print(f"content_hash: {digest}")
    print(f"output_dir:   {out}")
    if args.dry_run:
        print("(dry run — no files written)")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    if "md" in formats:
        (out / "study.md").write_text(
            render_study_markdown(fixture, policy=policy), encoding="utf-8"
        )
        written.append("study.md")
    if "xlsx" in formats:
        export_study_xlsx(fixture, out / "study.xlsx", policy=policy)
        written.append("study.xlsx")

    manifest = {
        "entity_id": fixture.entity_id,
        "as_of_date": fixture.as_of_date.isoformat(),
        "fixture_version": fixture.fixture_version,
        "policy_version": policy.policy_version if policy else None,
        "content_hash": digest,
        "formats": formats,
        "files": written,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote:        {', '.join([*written, 'manifest.json'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
