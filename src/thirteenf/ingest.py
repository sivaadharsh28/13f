from __future__ import annotations

import pandas as pd

from thirteenf.normalize import standardize_dataframe_ticker_column


def prepare_holdings_dataframe(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Standardize holdings data for downstream consensus calculations."""
    if raw_df.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "ticker_clean",
                "company",
                "fund",
                "source",
                "pct_portfolio",
                "portfolio_weight",
                "shares",
                "market_value_m",
            ]
        )

    result = raw_df.copy()
    result["source"] = result.get("source", "unknown")
    if "portfolio_weight" not in result.columns:
        result["portfolio_weight"] = result.get("pct_portfolio", 0.0)

    if "ticker" in result.columns:
        result = result[result["ticker"].map(lambda value: str(value).strip() if value is not None else "") != ""]
        result = result[result["ticker"].map(lambda value: value is not None and str(value).strip() not in {"≡", "—", "-"})]

    result = standardize_dataframe_ticker_column(result)
    result["ticker_clean"] = result["ticker_clean"].fillna(result.get("ticker"))
    result = result[result["ticker_clean"].notna()]
    result = result[result["ticker_clean"].map(lambda value: bool(str(value).strip()) and str(value).strip() not in {"≡", "—", "-"})]
    return result
