from __future__ import annotations

import pandas as pd


def consensus_long_signal(
    df: pd.DataFrame,
    min_funds: int = 3,
    min_weight: float = 2.0,
) -> pd.DataFrame:
    """Calculate point-in-time cross-manager overlap.

    Multiple rows for one manager/security (for example shared discretion) are
    summed before cross-manager averages are calculated.
    """
    security = "security_id" if "security_id" in df else "ticker_clean" if "ticker_clean" in df else "ticker"
    period = "report_period" if "report_period" in df else "quarter" if "quarter" in df else None
    weight = "portfolio_weight" if "portfolio_weight" in df else "pct_portfolio"
    required = {security, "fund", weight}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"DataFrame missing required columns: {sorted(missing)}")
    grouping = ([period] if period else []) + ["fund", security]
    per_fund = df.groupby(grouping, as_index=False, dropna=False)[weight].sum()
    consensus_grouping = ([period] if period else []) + [security]
    result = (
        per_fund.groupby(consensus_grouping, as_index=False, dropna=False)
        .agg(fund_count=("fund", "nunique"), avg_weight=(weight, "mean"), total_weight=(weight, "sum"))
    )
    result = result[(result["fund_count"] >= min_funds) & (result["avg_weight"] >= min_weight)]
    return result.sort_values((([period] if period else []) + ["avg_weight"]), ascending=([True] if period else []) + [False]).reset_index(drop=True)
