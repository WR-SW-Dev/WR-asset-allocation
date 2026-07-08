"""Entity study runner — render a Wake Robin study from an entity fixture.

Usage::

    python scripts/run_entity_study.py --fixture data/external/entity_jd_local.yaml \\
        --policy data/external/entity_jd_policy_local.yaml
    python scripts/run_entity_study.py --fixture <f> --dry-run
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow direct ``python scripts/run_entity_study.py`` from the repo root
# without an editable install.
_REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from aa_model.entity.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
