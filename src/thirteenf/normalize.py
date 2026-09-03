from __future__ import annotations

import re
from typing import Any

import pandas as pd


def standardize_ticker(ticker: Any) -> str | None:
    """Normalize ticker casing while preserving share-class suffixes."""
    if ticker is None or pd.isna(ticker):
        return None

    value = str(ticker).strip()
    if value == "":
        return None

    value = value.upper().replace(".", "-")

    if not re.fullmatch(r"[A-Z0-9\-]+", value):
        return None

    return value


def standardize_dataframe_ticker_column(df: pd.DataFrame) -> pd.DataFrame:
    """Add a normalized ticker_clean column based on an existing ticker column."""
    result = df.copy()
    if "ticker" not in result.columns:
        raise KeyError("DataFrame must contain a 'ticker' column")

    result["ticker_clean"] = result["ticker"].apply(standardize_ticker)
    return result
