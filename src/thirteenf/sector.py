from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd


# Bootstrap mappings are transparent and intentionally small. Production runs
# should supply a versioned security master with valid_from/valid_to dates.
SECTOR_MAP = {
    "AAPL": "Information Technology", "MSFT": "Information Technology",
    "AMZN": "Consumer Discretionary", "NVDA": "Information Technology",
    "XOM": "Energy", "CVX": "Energy", "JPM": "Financials",
    "UNH": "Health Care", "PG": "Consumer Staples", "COST": "Consumer Staples",
    "BRK-B": "Financials", "META": "Communication Services",
    "GOOG": "Communication Services", "GOOGL": "Communication Services",
    "INTC": "Information Technology", "AVGO": "Information Technology",
}


def load_security_master(path: str | Path) -> pd.DataFrame:
    master = pd.read_csv(path, dtype={"cusip": str})
    required = {"cusip", "ticker", "sector"}
    missing = required - set(master.columns)
    if missing:
        raise KeyError(f"Security master missing columns: {sorted(missing)}")
    master["cusip"] = master["cusip"].astype(str).str.strip().str.zfill(9)
    return master


def _resolve_master_columns(result: pd.DataFrame, master: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Resolve point-in-time master rows in one vectorized join."""
    lookup = result[["cusip"]].copy().reset_index(drop=True)
    lookup["_row_position"] = range(len(lookup))
    lookup["report_period"] = pd.to_datetime(
        result.get("report_period", pd.Series(pd.NaT, index=result.index)).to_numpy(),
        errors="coerce",
    )
    available_columns = [column for column in ("cusip", "ticker", "sector", "valid_from", "valid_to") if column in master]
    candidates = lookup.merge(master[available_columns], on="cusip", how="left")
    if {"valid_from", "valid_to"}.issubset(candidates.columns):
        candidates["_valid_from"] = pd.to_datetime(candidates["valid_from"], errors="coerce").fillna(pd.Timestamp.min)
        candidates["_valid_to"] = pd.to_datetime(candidates["valid_to"], errors="coerce").fillna(pd.Timestamp.max)
        candidates = candidates[
            candidates["report_period"].notna()
            & candidates["report_period"].ge(candidates["_valid_from"])
            & candidates["report_period"].le(candidates["_valid_to"])
        ]
        candidates = candidates.sort_values(["_row_position", "_valid_from"])
    selected = candidates.drop_duplicates("_row_position", keep="last").set_index("_row_position")
    ticker_values = selected.get("ticker", pd.Series(dtype=object)).reindex(range(len(result)))
    sector_values = selected.get("sector", pd.Series(dtype=object)).reindex(range(len(result)))
    return (
        pd.Series(ticker_values.to_numpy(), index=result.index),
        pd.Series(sector_values.to_numpy(), index=result.index),
    )


def assign_sector(
    df: pd.DataFrame,
    ticker_mapping: Mapping[str, str] | None = None,
    security_master: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Assign sectors while preserving unresolved holdings as ``Unknown``."""
    result = df.copy()
    mapping = dict(ticker_mapping or SECTOR_MAP)
    if security_master is not None:
        master = security_master.copy()
        if "cusip" in result and "cusip" in master:
            master["cusip"] = master["cusip"].astype(str).str.zfill(9)
            result["cusip"] = result["cusip"].astype(str).str.zfill(9)
            master_ticker, master_sector = _resolve_master_columns(result, master)
            existing_ticker = result.get("ticker", pd.Series("", index=result.index))
            result["ticker"] = existing_ticker.replace("", pd.NA).fillna(master_ticker)
            existing_sector = result.get("sector", pd.Series("", index=result.index))
            result["sector"] = existing_sector.replace({"": pd.NA, "Unknown": pd.NA}).fillna(master_sector)
    ticker_column = "ticker_clean" if "ticker_clean" in result else "ticker"
    inferred = result.get(ticker_column, pd.Series("", index=result.index)).map(mapping)
    if "sector" in result:
        result["sector"] = result["sector"].replace("", pd.NA).fillna(inferred).fillna("Unknown")
    else:
        result["sector"] = inferred.fillna("Unknown")
    return result


def build_sector_rotation(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate disclosed-book weights by manager, quarter and sector."""
    if df.empty:
        return pd.DataFrame(columns=["quarter", "fund", "sector", "portfolio_weight"])
    period = "quarter" if "quarter" in df else "report_period"
    required = {period, "fund", "sector", "portfolio_weight"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"DataFrame missing required columns: {sorted(missing)}")
    result = df.copy()
    result["quarter"] = pd.PeriodIndex(pd.to_datetime(result[period]), freq="Q").astype(str) if period == "report_period" else result[period]
    return (
        result.groupby(["quarter", "fund", "sector"], as_index=False)["portfolio_weight"]
        .sum().sort_values(["fund", "quarter", "portfolio_weight"], ascending=[True, True, False])
        .reset_index(drop=True)
    )


def build_overall_sector_rotation(
    df: pd.DataFrame,
    weighting: str = "equal_manager",
) -> pd.DataFrame:
    """Aggregate all reporting managers into quarterly sector allocations.

    ``equal_manager`` averages each manager's within-13F sector weights.
    ``disclosed_value`` pools the reported market values before calculating
    sector weights, so managers with larger disclosed books contribute more.
    """
    columns = ["quarter", "sector", "portfolio_weight", "manager_count"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    if weighting not in {"equal_manager", "disclosed_value"}:
        raise ValueError("weighting must be 'equal_manager' or 'disclosed_value'")

    rotation = build_sector_rotation(df)
    manager_totals = rotation.groupby(["quarter", "fund"])["portfolio_weight"].sum()
    valid_manager_quarters = manager_totals[manager_totals.gt(0)].index.to_frame(index=False)
    rotation = rotation.merge(valid_manager_quarters, on=["quarter", "fund"], how="inner")
    if rotation.empty:
        return pd.DataFrame(columns=columns)
    manager_counts = rotation.groupby("quarter")["fund"].nunique().rename("manager_count")
    if weighting == "equal_manager":
        overall = (
            rotation.groupby(["quarter", "sector"], as_index=False)["portfolio_weight"]
            .sum()
            .merge(manager_counts, on="quarter", how="left")
        )
        overall["portfolio_weight"] = overall["portfolio_weight"] / overall["manager_count"]
    else:
        required = {"market_value_usd", "sector", "fund"}
        missing = required - set(df.columns)
        if missing:
            raise KeyError(f"DataFrame missing required columns: {sorted(missing)}")
        values = df.copy()
        period = "quarter" if "quarter" in values else "report_period"
        if period not in values:
            raise KeyError("DataFrame requires report_period or quarter")
        values["quarter"] = (
            pd.PeriodIndex(pd.to_datetime(values[period]), freq="Q").astype(str)
            if period == "report_period" else values[period]
        )
        values["market_value_usd"] = pd.to_numeric(values["market_value_usd"], errors="coerce").fillna(0.0)
        values = values.merge(valid_manager_quarters, on=["quarter", "fund"], how="inner")
        overall = values.groupby(["quarter", "sector"], as_index=False)["market_value_usd"].sum()
        quarter_totals = overall.groupby("quarter")["market_value_usd"].transform("sum")
        overall["portfolio_weight"] = (
            overall["market_value_usd"].div(quarter_totals.where(quarter_totals.ne(0))).mul(100).fillna(0.0)
        )
        overall = overall.merge(manager_counts, on="quarter", how="left")
        overall = overall.drop(columns="market_value_usd")

    return overall[columns].sort_values(["quarter", "portfolio_weight"], ascending=[True, False]).reset_index(drop=True)
