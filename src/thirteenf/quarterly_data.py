from __future__ import annotations

import pandas as pd


ROTATION_COLUMNS = ["quarter", "fund", "sector", "portfolio_weight", "market_value_usd"]


def build_quarterly_sector_rotation_window(
    holdings: pd.DataFrame | None = None,
    start_quarter: str | None = None,
    end_quarter: str | None = None,
) -> pd.DataFrame:
    """Build quarterly sector weights from a point-in-time holdings snapshot."""
    if holdings is None or holdings.empty:
        return pd.DataFrame(columns=ROTATION_COLUMNS)

    required = {"report_period", "sector", "market_value_usd"}
    missing = required - set(holdings.columns)
    if missing:
        raise KeyError(f"Holdings missing columns: {sorted(missing)}")

    data = holdings.copy()
    if "fund" not in data.columns:
        data["fund"] = data.get("manager_code", "Unknown")
    data["report_period"] = pd.to_datetime(data["report_period"], errors="coerce")
    data = data[data["report_period"].notna()].copy()
    if data.empty:
        return pd.DataFrame(columns=ROTATION_COLUMNS)

    data["quarter"] = pd.PeriodIndex(data["report_period"], freq="Q").astype(str)
    if start_quarter is not None:
        data = data[data["quarter"].ge(start_quarter)]
    if end_quarter is not None:
        data = data[data["quarter"].le(end_quarter)]
    if data.empty:
        return pd.DataFrame(columns=ROTATION_COLUMNS)

    data["sector"] = data["sector"].fillna("Unknown")
    data["market_value_usd"] = pd.to_numeric(data["market_value_usd"], errors="coerce").fillna(0.0)
    grouped = (
        data.groupby(["fund", "quarter", "sector"], as_index=False)["market_value_usd"]
        .sum()
    )
    totals = grouped.groupby(["fund", "quarter"])["market_value_usd"].transform("sum")
    grouped = grouped[totals.gt(0)].copy()
    grouped["portfolio_weight"] = grouped["market_value_usd"] / totals[totals.gt(0)].to_numpy() * 100
    return grouped[ROTATION_COLUMNS].sort_values(["fund", "quarter", "sector"]).reset_index(drop=True)
