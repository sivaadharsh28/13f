"""Resolve historical identifiers without guessing from issuer names."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


def resolve_historical_holdings(events: pd.DataFrame, master: pd.DataFrame,
                                overrides: pd.DataFrame | None = None) -> pd.DataFrame:
    """Keep unresolved securities in the universe; accept exact US listings only.

    Vendor-adjusted histories represent splits/dividends. Successor symbols may
    only be supplied in dated, sourced overrides; issuer-name matches are not
    automatically accepted as historical security identities.
    """
    result = events.copy()
    result["original_ticker"] = result.get("ticker_clean", pd.Series(index=result.index, dtype=object))
    result["ticker_clean"] = pd.NA
    result["mapping_status"] = "unresolved"
    result["mapping_source"] = ""
    result["mapping_note"] = "No exact reviewed US security mapping"
    dates = pd.to_datetime(result["report_period"], errors="raise")
    cusips = result["cusip"].astype(str).str.strip().str.zfill(9)
    for _, item in master.iterrows():
        ticker = str(item.get("ticker", "") or "").strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9-]{0,12}", ticker):
            continue
        if item.get("match_method") not in {"cusip_search", "reviewed_override"}:
            continue
        mask = cusips.eq(str(item["cusip"]).zfill(9))
        for column, operator in (("valid_from", "ge"), ("valid_to", "le")):
            value = item.get(column)
            if pd.notna(value) and str(value).strip():
                mask &= getattr(dates, operator)(pd.Timestamp(value))
        result.loc[mask, "ticker_clean"] = ticker
        result.loc[mask, "mapping_status"] = "exact_cusip"
        result.loc[mask, "mapping_source"] = str(item.get("classification_source", "security master"))
        result.loc[mask, "mapping_note"] = "Exact CUSIP; vendor-adjusted history; no inferred merger conversion"
        if "sector" in item and pd.notna(item["sector"]):
            result.loc[mask, "sector"] = item["sector"]
    if overrides is not None:
        for _, item in overrides.fillna("").iterrows():
            if not item["source_url"] or not item["valid_from"] or not item["valid_to"]:
                raise ValueError("Historical overrides require source and validity dates")
            mask = cusips.eq(str(item["cusip"]).zfill(9)) & dates.between(item["valid_from"], item["valid_to"])
            result.loc[mask, "ticker_clean"] = item["ticker"] or pd.NA
            result.loc[mask, "mapping_status"] = "reviewed_history" if item["ticker"] else "requires_review"
            result.loc[mask, "mapping_source"] = item["source_url"]
            result.loc[mask, "mapping_note"] = item["note"]
    # An option-style identifier cannot be converted to the underlying merely
    # because the source omitted its put/call flag.
    ambiguous = cusips.str[6].isin(["8", "9"]) & result["put_call"].fillna("").eq("")
    result.loc[ambiguous, "ticker_clean"] = pd.NA
    result.loc[ambiguous, "mapping_status"] = "requires_review"
    result.loc[ambiguous, "mapping_note"] = "Option-style identifier without an instrument flag; retained as unpriced"
    return result


def load_resolved_events(events_path: str | Path, master_path: str | Path,
                         overrides_path: str | Path) -> pd.DataFrame:
    events = pd.read_csv(events_path, dtype={"cusip": str})
    master = pd.read_csv(master_path, dtype=str).fillna("")
    path = Path(overrides_path)
    overrides = pd.read_csv(path, dtype=str).fillna("") if path.exists() else None
    return resolve_historical_holdings(events, master, overrides)
