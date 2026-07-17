"""J.P. Morgan Long-Term Capital Market Assumptions (LTCMA) as a CMA source.

Thin, review-gated adapter that turns a captured JPM LTCMA matrix
(``data/external/jpm_ltcma_<year>.yaml`` — gitignored, since JPM material is
institutional/qualified-investor only) into a
:class:`~aa_model.io.schemas.CMAConfig`-shaped candidate.

It mirrors :mod:`aa_model.assumptions.benchmark_calibration`: nothing here is
imported by the orchestrator or the allocators, so it does **not** change model
behavior. Production CMAs still come from ``configs/cma.yaml``. Use
``scripts/build_cma_from_jpm.py`` to emit ``configs/cma_jpm.yaml`` for review;
promote by hand into ``configs/cma.yaml`` when the allocation bucket taxonomy is
expanded to match — a separate, governed behavior change.

The JPM source stores **both** return bases (arithmetic and compound):
arithmetic is the mathematically correct input to a mean-variance optimizer and
is the active series here; compound is retained as a companion for planning and
is surfaced in the emitted candidate as annotation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

ReturnBasis = Literal["arithmetic", "compound"]
LiquidityTier = Literal["liquid", "semi_liquid", "illiquid", "locked_strategic"]


@dataclass(frozen=True)
class JpmBucket:
    """One allocation bucket's JPM assumptions (fractions, annualized)."""

    jpm_class: str
    expected_return_arithmetic: float
    expected_return_compound: float
    vol_annual: float

    def expected_return(self, basis: ReturnBasis) -> float:
        return (
            self.expected_return_arithmetic
            if basis == "arithmetic"
            else self.expected_return_compound
        )


@dataclass(frozen=True)
class JpmLtcma:
    """A captured JPM LTCMA edition mapped to allocation buckets."""

    provider: str
    edition: str
    as_of: str
    currency: str
    buckets: dict[str, JpmBucket]
    corr_order: list[str]
    corr_matrix: list[list[float]]

    def correlation(self, a: str, b: str) -> float:
        i, j = self.corr_order.index(a), self.corr_order.index(b)
        return self.corr_matrix[i][j]


def load_jpm_source(path: Path | str) -> JpmLtcma:
    """Parse a ``jpm_ltcma_<year>.yaml`` capture into a :class:`JpmLtcma`."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    try:
        buckets = {
            key: JpmBucket(
                jpm_class=str(v["jpm_class"]),
                expected_return_arithmetic=float(v["expected_return_arithmetic"]),
                expected_return_compound=float(v["expected_return_compound"]),
                vol_annual=float(v["vol_annual"]),
            )
            for key, v in raw["buckets"].items()
        }
        corr = raw["correlations"]
        order = [str(x) for x in corr["order"]]
        matrix = [[float(x) for x in row] for row in corr["matrix"]]
    except (KeyError, TypeError) as e:
        raise ValueError(f"malformed JPM LTCMA source at {path}: {e}") from e

    if sorted(order) != sorted(buckets):
        raise ValueError(
            "correlations.order does not match buckets — "
            f"order={sorted(order)}, buckets={sorted(buckets)}"
        )
    n = len(order)
    if len(matrix) != n or any(len(row) != n for row in matrix):
        raise ValueError(f"correlation matrix is not {n}x{n}")

    return JpmLtcma(
        provider=str(raw.get("provider", "")),
        edition=str(raw.get("edition", "")),
        as_of=str(raw.get("as_of", "")),
        currency=str(raw.get("currency", "")),
        buckets=buckets,
        corr_order=order,
        corr_matrix=matrix,
    )


def build_cma_dict(
    source: JpmLtcma,
    *,
    return_basis: ReturnBasis = "arithmetic",
    aliases: dict[str, str] | None = None,
    drop: list[str] | None = None,
    renames: dict[str, str] | None = None,
    liquidity: dict[str, LiquidityTier] | None = None,
) -> dict:
    """Produce a :class:`CMAConfig`-shaped dict from a JPM source.

    ``aliases`` maps a derived bucket to an existing source bucket whose
    return/vol/correlations it borrows (e.g.
    ``{"re_opco_stabilized": "real_estate"}``). A derived bucket is perfectly
    correlated (1.0) with the bucket it proxies.

    ``drop`` removes source buckets from the output (e.g. classes with no role
    in the target profile). ``renames`` maps an internal bucket name to its
    output name (e.g. ``{"cash_and_cash_alts": "cash"}``), applied last — after
    aliasing and dropping. ``liquidity`` (if given) is keyed by **output**
    names and must cover every output bucket.
    """
    aliases = aliases or {}
    drop = drop or []
    renames = renames or {}
    for derived, base in aliases.items():
        if base not in source.buckets:
            raise ValueError(f"alias target {base!r} for {derived!r} is not a source bucket")
        if derived in source.buckets:
            raise ValueError(f"alias {derived!r} collides with an existing source bucket")
    unknown_drop = set(drop) - set(source.buckets)
    if unknown_drop:
        raise ValueError(f"drop names not in source buckets: {sorted(unknown_drop)}")

    # internal bucket universe: source (minus dropped) + derived aliases
    internal = [b for b in source.buckets if b not in drop] + list(aliases)

    def resolve(b: str) -> str:
        return aliases.get(b, b)

    def er(b: str) -> float:
        return source.buckets[resolve(b)].expected_return(return_basis)

    def vol(b: str) -> float:
        return source.buckets[resolve(b)].vol_annual

    def corr(a: str, b: str) -> float:
        if a == b:
            return 1.0
        ra, rb = resolve(a), resolve(b)
        # A derived bucket is a proxy of its base -> identical -> corr 1.0.
        return 1.0 if ra == rb else source.correlation(ra, rb)

    def name(b: str) -> str:  # internal -> output name
        return renames.get(b, b)

    out: dict = {
        "expected_returns_annual": {name(b): round(er(b), 4) for b in internal},
        "vol_annual": {name(b): round(vol(b), 4) for b in internal},
        "correlations": {
            name(a): {name(b): round(corr(a, b), 2) for b in internal} for a in internal
        },
    }
    if liquidity is not None:
        out_buckets = {name(b) for b in internal}
        missing = out_buckets - set(liquidity)
        if missing:
            raise ValueError(f"liquidity map missing buckets: {sorted(missing)}")
        out["liquidity"] = {name(b): liquidity[name(b)] for b in internal}
    return out


def compound_returns(
    source: JpmLtcma,
    *,
    aliases: dict[str, str] | None = None,
    drop: list[str] | None = None,
    renames: dict[str, str] | None = None,
) -> dict[str, float]:
    """Companion series: compound (geometric) return per output bucket.

    Applies the same ``aliases`` / ``drop`` / ``renames`` transform as
    :func:`build_cma_dict` so the companion aligns with the active series.
    """
    aliases = aliases or {}
    drop = drop or []
    renames = renames or {}
    internal = [b for b in source.buckets if b not in drop] + list(aliases)
    return {
        renames.get(b, b): round(source.buckets[aliases.get(b, b)].expected_return_compound, 4)
        for b in internal
    }
