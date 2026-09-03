"""Historical adjusted-close retrieval for reproducible research snapshots."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Iterable

import pandas as pd
import requests


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


def download_adjusted_close(
    tickers: Iterable[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp | None = None,
    delay: float = 0.08,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Download daily adjusted closes and return per-symbol failures.

    Yahoo Finance is convenient but not an institutional corporate-actions
    source. Persisted results should be treated as a replaceable research
    input and coverage must be reviewed before interpreting a backtest.
    """
    start_at = pd.Timestamp(start).tz_localize("UTC") if pd.Timestamp(start).tzinfo is None else pd.Timestamp(start).tz_convert("UTC")
    requested_end = pd.Timestamp(end) if end is not None else pd.Timestamp.today() + timedelta(days=1)
    end_at = requested_end.tz_localize("UTC") if requested_end.tzinfo is None else requested_end.tz_convert("UTC")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 thirteenf-research/1.0"})
    series: list[pd.Series] = []
    errors: dict[str, str] = {}
    for raw_ticker in sorted(set(tickers)):
        ticker = str(raw_ticker).strip()
        if not ticker:
            continue
        try:
            response = session.get(
                YAHOO_CHART_URL.format(ticker=ticker),
                params={
                    "period1": int(start_at.timestamp()),
                    "period2": int(end_at.timestamp()),
                    "interval": "1d",
                    "events": "div,splits",
                    "includeAdjustedClose": "true",
                },
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            indicators = result.get("indicators", {})
            adjusted = indicators.get("adjclose", [{}])[0].get("adjclose")
            if adjusted is None:
                adjusted = indicators.get("quote", [{}])[0].get("close", [])
            if not timestamps or not adjusted:
                raise ValueError("no daily adjusted-close history returned")
            index = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None).normalize()
            values = pd.to_numeric(pd.Series(adjusted), errors="coerce").to_numpy()
            history = pd.Series(values, index=index, name=ticker).dropna()
            if history.empty:
                raise ValueError("adjusted-close history is empty")
            series.append(history[~history.index.duplicated(keep="last")])
        except Exception as exc:
            errors[ticker] = f"{type(exc).__name__}: {exc}"
        time.sleep(delay)
    prices = pd.concat(series, axis=1).sort_index() if series else pd.DataFrame()
    prices.index.name = "date"
    return prices, errors
