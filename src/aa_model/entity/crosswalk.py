"""Phase 24 — deterministic crosswalks from the Phase-15 ingestion taxonomy
to the entity study's Wake Robin vocabulary.

Committed methodology (no client data). Two maps, both fail-loud on anything
without a defined home — never a silent "other" bucket:

1. `asset_class` (+ optional `liquidity_bucket`) -> one of the seven Wake
   Robin policy classes. Real estate is disambiguated by bucket: income-
   producing / operating-company RE (`re_stabilized`, `opco_strategic`) is
   `re_opco_stabilized`; other RE is `real_estate`.
2. `liquidity_bucket` -> the study's redemption tier
   (daily / monthly / quarterly / at_maturity).

Asset classes with no Wake Robin home (infrastructure, commodity,
direct_operating, other) raise — surfacing a real classification decision
rather than mis-bucketing.
"""

from __future__ import annotations

# Unambiguous asset_class -> policy_class.
_ASSET_CLASS_TO_POLICY: dict[str, str] = {
    "public_equity": "equity",
    "private_equity": "private_equity",
    "fixed_income_public": "fixed_income",
    "private_credit": "fixed_income",
    "cash_equivalent": "cash_and_cash_alts",
    "hedge_fund": "absolute_return",
    "real_estate_debt": "real_estate",
    # real_estate_equity is bucket-dependent — handled in policy_class_for.
}

# RE buckets that denote income-producing / operating-company real estate,
# i.e. the "RE OpCo Stabilized" policy class rather than plain "Real Estate".
_RE_OPCO_BUCKETS: frozenset[str] = frozenset({"re_stabilized", "opco_strategic"})

# liquidity_bucket -> study redemption tier.
_BUCKET_TO_TIER: dict[str, str] = {
    "cash_equivalent": "daily",
    "daily_liquid": "daily",
    "semi_liquid": "quarterly",
    "illiquid": "at_maturity",
    "locked_strategic": "at_maturity",
    "re_stabilized": "at_maturity",
    "re_development": "at_maturity",
    "re_land": "at_maturity",
    "opco_strategic": "at_maturity",
}


def policy_class_for(asset_class: str, liquidity_bucket: str | None = None) -> str:
    """Map a Phase-15 `asset_class` to a Wake Robin policy class.

    `real_estate_equity` resolves via `liquidity_bucket`
    (`re_stabilized`/`opco_strategic` -> `re_opco_stabilized`, else
    `real_estate`). Raises `ValueError` for classes with no Wake Robin home.
    """
    if asset_class == "real_estate_equity":
        if liquidity_bucket in _RE_OPCO_BUCKETS:
            return "re_opco_stabilized"
        return "real_estate"
    try:
        return _ASSET_CLASS_TO_POLICY[asset_class]
    except KeyError:
        raise ValueError(
            f"asset_class {asset_class!r} has no Wake Robin policy-class mapping "
            f"(infrastructure / commodity / direct_operating / other require an "
            f"explicit classification decision, not a silent bucket)"
        ) from None


def liquidity_tier_for(liquidity_bucket: str) -> str:
    """Map a Phase-15 `liquidity_bucket` to a study redemption tier.
    Raises `ValueError` for unknown buckets."""
    try:
        return _BUCKET_TO_TIER[liquidity_bucket]
    except KeyError:
        raise ValueError(
            f"unknown liquidity_bucket {liquidity_bucket!r}; valid: " f"{sorted(_BUCKET_TO_TIER)}"
        ) from None


# Firm "Asset Allocation Class" display labels (as authored in the curated
# Investment Summary) -> Wake Robin policy-class literals. Normalization only
# (the family has already classified); matched case-insensitively on a
# collapsed-whitespace, '&'->'and' key. Distinct from policy_class_for, which
# maps the finer Phase-15 asset_class vocabulary.
_POLICY_LABEL_TO_CLASS: dict[str, str] = {
    "re opco stabilized": "re_opco_stabilized",
    "real estate": "real_estate",
    "equity": "equity",
    "private equity": "private_equity",
    "absolute return": "absolute_return",
    "fixed income": "fixed_income",
    "cash and cash alts": "cash_and_cash_alts",
}


def _norm_label(label: str) -> str:
    return " ".join(label.replace("&", " and ").lower().split())


def policy_class_from_label(label: str) -> str:
    """Normalize a firm policy-class display label (e.g. 'Private Equity',
    'Cash & Cash Alts') to its policy-class literal. Case/whitespace/`&`
    insensitive; raises `ValueError` for labels outside the seven classes."""
    key = _norm_label(label)
    try:
        return _POLICY_LABEL_TO_CLASS[key]
    except KeyError:
        raise ValueError(
            f"policy-class label {label!r} is not one of the seven Wake Robin "
            f"classes; valid labels: {sorted(_POLICY_LABEL_TO_CLASS)}"
        ) from None


# Firm liquidity display labels (Investment Summary "Liquidity" column) ->
# study redemption tier. Distinct from liquidity_tier_for (Phase-15 bucket).
_LIQUIDITY_LABEL_TO_TIER: dict[str, str] = {
    "daily": "daily",
    "monthly": "monthly",
    "quarterly": "quarterly",
    "at maturity": "at_maturity",
}


def tier_from_label(label: str | None) -> str | None:
    """Normalize a liquidity display label ('Daily'/'Monthly'/'Quarterly'/
    'At Maturity') to a redemption tier. Blank/None -> None (untiered);
    raises `ValueError` for an unrecognized non-empty label."""
    if label is None or not label.strip():
        return None
    key = " ".join(label.lower().split())
    try:
        return _LIQUIDITY_LABEL_TO_TIER[key]
    except KeyError:
        raise ValueError(
            f"liquidity label {label!r} is not one of " f"{sorted(_LIQUIDITY_LABEL_TO_TIER)}"
        ) from None
