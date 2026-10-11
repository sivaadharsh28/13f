from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


SHORT_TERM_MANAGER_CODES = ("DUQ", "AM", "THIEL")



def _prepare(snapshot: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return report metadata and security-level disclosed holdings."""
    required = {
        "manager_code", "fund", "report_period", "portfolio_weight",
        "market_value_usd", "cusip",
    }
    missing = required - set(snapshot.columns)
    if missing:
        raise KeyError(f"Filing monitor missing columns: {sorted(missing)}")

    data = snapshot.copy()
    data["report_period"] = pd.to_datetime(data["report_period"], errors="coerce")
    data = data[data["report_period"].notna()].copy()
    data["quarter"] = pd.PeriodIndex(data["report_period"], freq="Q").astype(str)
    data["portfolio_weight"] = pd.to_numeric(data["portfolio_weight"], errors="coerce").fillna(0.0)
    data["market_value_usd"] = pd.to_numeric(data["market_value_usd"], errors="coerce").fillna(0.0)

    accepted = pd.Series(pd.NaT, index=data.index, dtype="datetime64[ns, UTC]")
    for column in ("acceptance_datetime", "available_at", "filing_date"):
        if column in data:
            parsed = pd.to_datetime(data[column], errors="coerce", utc=True)
            accepted = accepted.fillna(parsed)
    data["accepted_at"] = accepted
    data = data.sort_values(["manager_code", "report_period", "accepted_at"], na_position="first")

    metadata = (
        data.groupby(["manager_code", "quarter"], as_index=False, dropna=False, sort=False)
        .agg(
            fund=("fund", "last"),
            report_period=("report_period", "max"),
            accepted_at=("accepted_at", "max"),
            source_url=("source_url", "last") if "source_url" in data else ("fund", "last"),
        )
        .sort_values(["manager_code", "report_period"])
        .reset_index(drop=True)
    )

    cusip = data["cusip"].fillna("").astype(str).str.strip().str.zfill(9)
    ticker = data.get("ticker_clean", data.get("ticker", pd.Series("", index=data.index)))
    ticker = ticker.fillna("").astype(str).str.strip()
    issuer = data.get("issuer", pd.Series("", index=data.index)).fillna("").astype(str).str.strip()
    instrument = data.get("put_call", pd.Series("", index=data.index)).fillna("").astype(str).str.strip().str.title()
    instrument = instrument.where(instrument.ne(""), "Shares")

    fallback = ticker.where(ticker.ne(""), issuer)
    security_base = cusip.where(cusip.ne("000000000"), fallback)
    data["cusip_clean"] = cusip
    data["ticker_display"] = ticker
    data["issuer_display"] = issuer
    data["instrument"] = instrument
    data["security_id"] = security_base + "|" + instrument.str.upper()
    valid = (
        data["portfolio_weight"].gt(0)
        | data["market_value_usd"].gt(0)
    ) & security_base.ne("") & cusip.ne("000000000")
    data = data[valid].copy()

    holdings = (
        data.groupby(
            ["manager_code", "fund", "quarter", "report_period", "security_id", "instrument"],
            as_index=False,
            dropna=False,
        )
        .agg(
            cusip=("cusip_clean", "last"),
            ticker=("ticker_display", "last"),
            issuer=("issuer_display", "last"),
            sector=("sector", "last") if "sector" in data else ("fund", "last"),
            portfolio_weight=("portfolio_weight", "sum"),
            market_value_usd=("market_value_usd", "sum"),
        )
        .reset_index(drop=True)
    )
    holdings["asset"] = holdings["ticker"].where(holdings["ticker"].ne(""), holdings["issuer"])
    holdings["asset"] = holdings["asset"].where(holdings["asset"].ne(""), holdings["cusip"])
    derivative = holdings["instrument"].ne("Shares")
    holdings.loc[derivative, "asset"] = (
        holdings.loc[derivative, "asset"] + " (" + holdings.loc[derivative, "instrument"] + ")"
    )
    return metadata, holdings


def _recent_quarters(metadata: pd.DataFrame, quarters: int) -> set[str]:
    ordered = sorted(
        metadata["quarter"].dropna().astype(str).unique(),
        key=lambda value: pd.Period(value, freq="Q").ordinal,
    )
    return set(ordered[-max(int(quarters), 1):])


def build_position_change_alerts(
    snapshot: pd.DataFrame,
    threshold_pp: float = 5.0,
    quarters: int = 8,
    manager_codes: Iterable[str] = SHORT_TERM_MANAGER_CODES,
) -> pd.DataFrame:
    """Compare each short-term manager report with its prior accepted report."""
    columns = [
        "accepted_at", "quarter", "prior_quarter", "manager_code", "fund", "change_type",
        "asset", "ticker", "issuer", "cusip", "instrument", "sector", "previous_weight",
        "current_weight", "change_pp", "current_value_usd", "source_url",
    ]
    metadata, holdings = _prepare(snapshot)
    manager_codes = tuple(manager_codes)
    metadata = metadata[metadata["manager_code"].isin(manager_codes)].copy()
    holdings = holdings[holdings["manager_code"].isin(manager_codes)].copy()
    recent = _recent_quarters(metadata, quarters)
    alerts: list[dict[str, object]] = []

    for manager_code, reports in metadata.groupby("manager_code", sort=False):
        reports = reports.sort_values("report_period").reset_index(drop=True)
        for report_index in range(1, len(reports)):
            current_meta = reports.iloc[report_index]
            if current_meta["quarter"] not in recent:
                continue
            previous_meta = reports.iloc[report_index - 1]
            current = holdings[
                holdings["manager_code"].eq(manager_code)
                & holdings["quarter"].eq(current_meta["quarter"])
            ].set_index("security_id")
            previous = holdings[
                holdings["manager_code"].eq(manager_code)
                & holdings["quarter"].eq(previous_meta["quarter"])
            ].set_index("security_id")
            security_ids = current.index.union(previous.index)
            for security_id in security_ids:
                current_weight = float(current.at[security_id, "portfolio_weight"]) if security_id in current.index else 0.0
                previous_weight = float(previous.at[security_id, "portfolio_weight"]) if security_id in previous.index else 0.0
                change_pp = current_weight - previous_weight
                if previous_weight > 0 and current_weight <= 0:
                    change_type = "Full exit"
                elif abs(change_pp) < float(threshold_pp):
                    continue
                elif previous_weight <= 0 and current_weight > 0:
                    change_type = "New position"
                elif change_pp > 0:
                    change_type = "Weight increase"
                else:
                    change_type = "Weight decrease"

                row = current.loc[security_id] if security_id in current.index else previous.loc[security_id]
                alerts.append({
                    "accepted_at": current_meta["accepted_at"],
                    "quarter": current_meta["quarter"],
                    "prior_quarter": previous_meta["quarter"],
                    "manager_code": manager_code,
                    "fund": current_meta["fund"],
                    "change_type": change_type,
                    "asset": row["asset"],
                    "ticker": row["ticker"],
                    "issuer": row["issuer"],
                    "cusip": row["cusip"],
                    "instrument": row["instrument"],
                    "sector": row["sector"],
                    "previous_weight": previous_weight,
                    "current_weight": current_weight,
                    "change_pp": change_pp,
                    "current_value_usd": float(current.at[security_id, "market_value_usd"]) if security_id in current.index else 0.0,
                    "source_url": current_meta["source_url"],
                })

    if not alerts:
        return pd.DataFrame(columns=columns)
    result = pd.DataFrame(alerts)
    result["_magnitude"] = result["change_pp"].abs()
    return (
        result.sort_values(["accepted_at", "_magnitude"], ascending=[False, False], na_position="last")
        .drop(columns="_magnitude")
        .reset_index(drop=True)[columns]
    )


def build_sector_change_alerts(
    snapshot: pd.DataFrame,
    threshold_pp: float = 5.0,
    quarters: int = 8,
    manager_codes: Iterable[str] = SHORT_TERM_MANAGER_CODES,
) -> pd.DataFrame:
    """Return material manager-level disclosed sector allocation changes."""
    columns = [
        "accepted_at", "quarter", "prior_quarter", "manager_code", "fund", "sector",
        "previous_weight", "current_weight", "change_pp", "source_url",
    ]
    metadata, holdings = _prepare(snapshot)
    manager_codes = tuple(manager_codes)
    metadata = metadata[metadata["manager_code"].isin(manager_codes)].copy()
    holdings = holdings[
        holdings["manager_code"].isin(manager_codes) & holdings["sector"].ne("Unknown")
    ].copy()
    sector_weights = holdings.groupby(
        ["manager_code", "quarter", "sector"], as_index=False
    )["portfolio_weight"].sum()
    recent = _recent_quarters(metadata, quarters)
    alerts: list[dict[str, object]] = []

    for manager_code, reports in metadata.groupby("manager_code", sort=False):
        reports = reports.sort_values("report_period").reset_index(drop=True)
        for report_index in range(1, len(reports)):
            current_meta = reports.iloc[report_index]
            if current_meta["quarter"] not in recent:
                continue
            previous_meta = reports.iloc[report_index - 1]
            current = sector_weights[
                sector_weights["manager_code"].eq(manager_code)
                & sector_weights["quarter"].eq(current_meta["quarter"])
            ].set_index("sector")["portfolio_weight"]
            previous = sector_weights[
                sector_weights["manager_code"].eq(manager_code)
                & sector_weights["quarter"].eq(previous_meta["quarter"])
            ].set_index("sector")["portfolio_weight"]
            for sector in current.index.union(previous.index):
                current_weight = float(current.get(sector, 0.0))
                previous_weight = float(previous.get(sector, 0.0))
                change_pp = current_weight - previous_weight
                if abs(change_pp) < float(threshold_pp):
                    continue
                alerts.append({
                    "accepted_at": current_meta["accepted_at"],
                    "quarter": current_meta["quarter"],
                    "prior_quarter": previous_meta["quarter"],
                    "manager_code": manager_code,
                    "fund": current_meta["fund"],
                    "sector": sector,
                    "previous_weight": previous_weight,
                    "current_weight": current_weight,
                    "change_pp": change_pp,
                    "source_url": current_meta["source_url"],
                })

    if not alerts:
        return pd.DataFrame(columns=columns)
    result = pd.DataFrame(alerts)
    result["_magnitude"] = result["change_pp"].abs()
    return (
        result.sort_values(["accepted_at", "_magnitude"], ascending=[False, False], na_position="last")
        .drop(columns="_magnitude")
        .reset_index(drop=True)[columns]
    )


def build_combined_positioning(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Combine security positioning while retaining equal-manager and value weights."""
    columns = [
        "quarter", "security_id", "asset", "ticker", "issuer", "cusip", "instrument", "sector",
        "fund_count", "managers_reporting", "manager_coverage", "holder_average_weight",
        "equal_manager_weight", "combined_disclosed_value", "pooled_value_weight", "held_by",
        "accepted_at",
    ]
    metadata, holdings = _prepare(snapshot)
    if metadata.empty or holdings.empty:
        return pd.DataFrame(columns=columns)

    manager_counts = metadata.groupby("quarter")["manager_code"].nunique().rename("managers_reporting")
    quarter_values = holdings.groupby("quarter")["market_value_usd"].sum().rename("quarter_disclosed_value")
    accepted = metadata.groupby("quarter")["accepted_at"].max().rename("accepted_at")

    per_manager = (
        holdings.groupby(
            ["quarter", "manager_code", "fund", "security_id", "instrument"],
            as_index=False,
            dropna=False,
        )
        .agg(
            asset=("asset", "last"),
            ticker=("ticker", "last"),
            issuer=("issuer", "last"),
            cusip=("cusip", "last"),
            sector=("sector", "last"),
            portfolio_weight=("portfolio_weight", "sum"),
            market_value_usd=("market_value_usd", "sum"),
        )
    )
    combined = (
        per_manager.groupby(["quarter", "security_id"], as_index=False, dropna=False, sort=False)
        .agg(
            asset=("asset", "last"),
            ticker=("ticker", "last"),
            issuer=("issuer", "last"),
            cusip=("cusip", "last"),
            instrument=("instrument", "last"),
            sector=("sector", "last"),
            fund_count=("manager_code", "nunique"),
            total_manager_weight=("portfolio_weight", "sum"),
            combined_disclosed_value=("market_value_usd", "sum"),
            held_by=("fund", lambda values: ", ".join(sorted(set(values)))),
        )
        .merge(manager_counts, on="quarter", how="left")
        .merge(quarter_values, on="quarter", how="left")
        .merge(accepted, on="quarter", how="left")
    )
    combined["manager_coverage"] = combined["fund_count"] / combined["managers_reporting"]
    combined["holder_average_weight"] = combined["total_manager_weight"] / combined["fund_count"]
    combined["equal_manager_weight"] = combined["total_manager_weight"] / combined["managers_reporting"]
    combined["pooled_value_weight"] = (
        combined["combined_disclosed_value"] / combined["quarter_disclosed_value"].where(
            combined["quarter_disclosed_value"].ne(0)
        ) * 100
    ).fillna(0.0)
    return combined[columns].sort_values(
        ["quarter", "equal_manager_weight"], ascending=[True, False]
    ).reset_index(drop=True)


def build_new_consensus_alerts(
    snapshot: pd.DataFrame,
    min_managers: int = 2,
    quarters: int = 8,
) -> pd.DataFrame:
    """Flag securities that newly cross a multi-manager holder threshold."""
    columns = [
        "accepted_at", "quarter", "prior_quarter", "asset", "ticker", "issuer", "instrument",
        "sector", "previous_fund_count", "fund_count", "managers_reporting", "manager_coverage",
        "equal_manager_weight", "pooled_value_weight", "combined_disclosed_value", "held_by",
    ]
    metadata, _ = _prepare(snapshot)
    combined = build_combined_positioning(snapshot)
    if combined.empty:
        return pd.DataFrame(columns=columns)
    ordered = sorted(
        metadata["quarter"].dropna().astype(str).unique(),
        key=lambda value: pd.Period(value, freq="Q").ordinal,
    )
    recent = set(ordered[-max(int(quarters), 1):])
    by_quarter = {quarter: frame.set_index("security_id") for quarter, frame in combined.groupby("quarter")}
    alerts: list[dict[str, object]] = []
    for quarter_index in range(1, len(ordered)):
        quarter = ordered[quarter_index]
        if quarter not in recent:
            continue
        prior_quarter = ordered[quarter_index - 1]
        current = by_quarter.get(quarter, pd.DataFrame())
        previous = by_quarter.get(prior_quarter, pd.DataFrame())
        if current.empty:
            continue
        for security_id, row in current[current["fund_count"].ge(int(min_managers))].iterrows():
            previous_count = int(previous.at[security_id, "fund_count"]) if security_id in previous.index else 0
            if previous_count >= int(min_managers):
                continue
            alerts.append({
                "accepted_at": row["accepted_at"],
                "quarter": quarter,
                "prior_quarter": prior_quarter,
                "asset": row["asset"],
                "ticker": row["ticker"],
                "issuer": row["issuer"],
                "instrument": row["instrument"],
                "sector": row["sector"],
                "previous_fund_count": previous_count,
                "fund_count": int(row["fund_count"]),
                "managers_reporting": int(row["managers_reporting"]),
                "manager_coverage": row["manager_coverage"],
                "equal_manager_weight": row["equal_manager_weight"],
                "pooled_value_weight": row["pooled_value_weight"],
                "combined_disclosed_value": row["combined_disclosed_value"],
                "held_by": row["held_by"],
            })
    if not alerts:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(alerts).sort_values(
        ["accepted_at", "fund_count", "equal_manager_weight"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)[columns]


def build_monitor_payload(
    snapshot: pd.DataFrame,
    position_threshold_pp: float = 5.0,
    sector_threshold_pp: float = 5.0,
    consensus_min_managers: int = 2,
    quarters: int = 8,
) -> dict[str, pd.DataFrame]:
    """Build every table needed by the Streamlit filing-change workspace."""
    return {
        "position_alerts": build_position_change_alerts(
            snapshot, threshold_pp=position_threshold_pp, quarters=quarters
        ),
        "sector_alerts": build_sector_change_alerts(
            snapshot, threshold_pp=sector_threshold_pp, quarters=quarters
        ),
        "consensus_alerts": build_new_consensus_alerts(
            snapshot, min_managers=consensus_min_managers, quarters=quarters
        ),
        "combined_positioning": build_combined_positioning(snapshot),
    }


