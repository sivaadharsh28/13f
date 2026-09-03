from __future__ import annotations

import re

import pandas as pd


def build_dashboard_data(snapshot: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Prepare a simple dashboard payload from the latest snapshot."""
    empty = pd.DataFrame(columns=["ticker_clean", "fund", "portfolio_weight", "quarter"])
    if snapshot.empty:
        return {"quarterly_holdings": empty, "consensus": empty}

    df = snapshot.copy()

    if "ticker_clean" not in df.columns and "ticker" in df.columns:
        df["ticker_clean"] = df["ticker"]
    if "fund" not in df.columns and "manager" in df.columns:
        df["fund"] = df["manager"]

    if "portfolio_weight" not in df.columns:
        for candidate in ("pct_portfolio", "weight_pct", "weight", "position_weight"):
            if candidate in df.columns:
                df["portfolio_weight"] = df[candidate]
                break
        else:
            df["portfolio_weight"] = 0.0

    if "quarter" not in df.columns:
        for candidate in ("reporting_period", "as_of_date", "period", "quarter_end"):
            if candidate in df.columns:
                df["quarter"] = df[candidate]
                break
        else:
            df["quarter"] = "unknown"

    if "ticker_clean" in df.columns:
        df["ticker_clean"] = df["ticker_clean"].map(lambda value: value if isinstance(value, str) and re.fullmatch(r"[A-Z0-9\-]+", value.upper()) else None)
    elif "ticker" in df.columns:
        df["ticker_clean"] = df["ticker"].map(lambda value: str(value).split(".", 1)[0].upper() if isinstance(value, str) and re.fullmatch(r"[A-Z0-9\-]+", str(value).split(".", 1)[0].upper()) else None)

    quarterly_holdings = df[["ticker_clean", "fund", "portfolio_weight", "quarter"]].copy()
    quarterly_holdings = quarterly_holdings.dropna(subset=["ticker_clean", "fund"]).copy()
    quarterly_holdings["portfolio_weight"] = pd.to_numeric(quarterly_holdings["portfolio_weight"], errors="coerce").fillna(0.0)

    consensus = (
        quarterly_holdings.groupby("ticker_clean", as_index=False)
        .agg(
            fund_count=("fund", "nunique"),
            avg_weight=("portfolio_weight", "mean"),
        )
        .sort_values("avg_weight", ascending=False)
        .reset_index(drop=True)
    )
    return {"quarterly_holdings": quarterly_holdings, "consensus": consensus}
