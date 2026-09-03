"""Canonical SEC holdings transformation and amendment reconciliation."""

from __future__ import annotations

import pandas as pd

from thirteenf.funds import manager_name


CANONICAL_HOLDING_COLUMNS = [
    "manager_code", "fund", "cik", "accession_number", "form",
    "report_period", "filing_date", "acceptance_datetime", "available_at",
    "issuer", "title_of_class", "cusip", "figi", "ticker", "ticker_clean",
    "reported_value", "value_unit", "market_value_usd", "shares",
    "share_type", "put_call", "investment_discretion", "other_manager",
    "voting_sole", "voting_shared", "voting_none", "portfolio_weight",
    "source", "source_url", "content_hash", "amendment_type",
]


def filing_value_unit(filing_date: str) -> str:
    """The updated dollar-value Form 13F became mandatory on 2023-01-03."""
    parsed = pd.to_datetime(filing_date, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Missing or invalid filing date: {filing_date!r}")
    return "usd" if parsed >= pd.Timestamp("2023-01-03") else "usd_thousands"


def attach_filing_metadata(
    holdings: pd.DataFrame,
    filing: dict[str, object] | pd.Series,
    manager_code: str,
    source_url: str,
    amendment_type: str = "",
) -> pd.DataFrame:
    """Attach point-in-time filing metadata and compute within-filing weights."""
    result = holdings.copy()
    meta = filing.to_dict() if isinstance(filing, pd.Series) else dict(filing)
    result["manager_code"] = manager_code
    result["fund"] = manager_name(manager_code)
    for column in ("cik", "accession_number", "form", "report_period", "filing_date", "acceptance_datetime", "content_hash"):
        result[column] = meta.get(column, "")
    result["available_at"] = pd.to_datetime(
        result["acceptance_datetime"], format="mixed", utc=True, errors="coerce",
    )
    result["ticker"] = result.get("ticker", "")
    result["ticker_clean"] = result.get("ticker_clean", "")
    result["source"] = "sec"
    result["source_url"] = source_url
    result["amendment_type"] = amendment_type
    total = pd.to_numeric(result["market_value_usd"], errors="coerce").fillna(0).sum()
    result["portfolio_weight"] = (
        pd.to_numeric(result["market_value_usd"], errors="coerce").fillna(0) / total * 100
        if total > 0 else 0.0
    )
    for column in CANONICAL_HOLDING_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    return result[CANONICAL_HOLDING_COLUMNS]


def reconcile_amendments(holdings: pd.DataFrame) -> pd.DataFrame:
    """Resolve restatements and additive amendments for each manager/period.

    Unknown amendment semantics fail closed rather than silently double count.
    """
    if holdings.empty:
        return holdings.copy()
    required = {"manager_code", "report_period", "form", "acceptance_datetime", "amendment_type"}
    missing = required - set(holdings.columns)
    if missing:
        raise KeyError(f"Holdings missing amendment fields: {sorted(missing)}")

    resolved: list[pd.DataFrame] = []
    for _, period_rows in holdings.groupby(["manager_code", "report_period"], dropna=False):
        accessions = (
            period_rows[["accession_number", "form", "acceptance_datetime", "amendment_type"]]
            .drop_duplicates()
            .sort_values("acceptance_datetime")
        )
        current = period_rows.iloc[0:0].copy()
        for accession in accessions.itertuples(index=False):
            rows = period_rows[period_rows["accession_number"] == accession.accession_number]
            if accession.form == "13F-HR":
                current = rows.copy()
            elif accession.amendment_type == "restatement":
                current = rows.copy()
            elif accession.amendment_type == "adds_new_holdings":
                current = pd.concat([current, rows], ignore_index=True)
            else:
                raise ValueError(f"Unknown amendment type for {accession.accession_number}")
        total = pd.to_numeric(current["market_value_usd"], errors="coerce").fillna(0).sum()
        current["portfolio_weight"] = (
            pd.to_numeric(current["market_value_usd"], errors="coerce").fillna(0) / total * 100
            if total > 0 else 0.0
        )
        resolved.append(current)
    return pd.concat(resolved, ignore_index=True) if resolved else holdings.iloc[0:0].copy()


def build_as_of_snapshots(holdings: pd.DataFrame) -> pd.DataFrame:
    """Materialize each disclosure state exactly as it became public."""
    if holdings.empty:
        return holdings.copy()
    snapshots: list[pd.DataFrame] = []
    for _, period_rows in holdings.groupby(["manager_code", "report_period"], dropna=False):
        events = (
            period_rows[["accession_number", "form", "acceptance_datetime", "amendment_type"]]
            .drop_duplicates().sort_values("acceptance_datetime")
        )
        state = period_rows.iloc[0:0].copy()
        for event in events.itertuples(index=False):
            disclosed = period_rows[period_rows["accession_number"] == event.accession_number]
            if event.form == "13F-HR" or event.amendment_type == "restatement":
                state = disclosed.copy()
            elif event.amendment_type == "adds_new_holdings":
                state = pd.concat([state, disclosed], ignore_index=True)
            else:
                raise ValueError(f"Unknown amendment type for {event.accession_number}")
            snapshot = state.copy()
            total = pd.to_numeric(snapshot["market_value_usd"], errors="coerce").fillna(0).sum()
            snapshot["portfolio_weight"] = (
                pd.to_numeric(snapshot["market_value_usd"], errors="coerce").fillna(0) / total * 100
                if total > 0 else 0.0
            )
            snapshot["snapshot_accession"] = event.accession_number
            snapshot["available_at"] = pd.to_datetime(event.acceptance_datetime, utc=True, errors="raise")
            snapshots.append(snapshot)
    return pd.concat(snapshots, ignore_index=True) if snapshots else holdings.iloc[0:0].copy()
