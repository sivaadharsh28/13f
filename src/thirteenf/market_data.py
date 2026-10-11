"""Historical price retrieval for reproducible research snapshots."""

from __future__ import annotations

import time
import json
from datetime import timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


def _utc_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def download_adjusted_ohlc(
    tickers: Iterable[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp | None = None,
    delay: float = 0.08,
    metadata_dir: str | Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    """Download daily adjusted open and adjusted close prices.

    Yahoo provides raw OHLC and adjusted close. Adjusted open is derived with
    the same corporate-action factor as adjusted close: raw_open * adj_close / raw_close.
    """
    start_at = _utc_timestamp(start)
    requested_end = pd.Timestamp(end) if end is not None else pd.Timestamp.today() + timedelta(days=1)
    end_at = _utc_timestamp(requested_end)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 thirteenf-research/1.0"})
    close_series: list[pd.Series] = []
    open_series: list[pd.Series] = []
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
            quote = indicators.get("quote", [{}])[0]
            raw_open = quote.get("open", [])
            raw_close = quote.get("close", [])
            adjusted = indicators.get("adjclose", [{}])[0].get("adjclose")
            if adjusted is None:
                raise ValueError("adjusted prices missing; raw-price fallback is not allowed")
            if not timestamps or not adjusted:
                raise ValueError("no daily adjusted-close history returned")

            index = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None).normalize()
            adjusted_close = pd.to_numeric(pd.Series(adjusted), errors="coerce")
            raw_open_series = pd.to_numeric(pd.Series(raw_open), errors="coerce")
            raw_close_series = pd.to_numeric(pd.Series(raw_close), errors="coerce")
            factor = adjusted_close / raw_close_series.replace(0, pd.NA)
            adjusted_open = raw_open_series * factor

            close_history = pd.Series(adjusted_close.to_numpy(), index=index, name=ticker).dropna()
            open_history = pd.Series(adjusted_open.to_numpy(), index=index, name=ticker).dropna()
            if close_history.empty:
                raise ValueError("adjusted-close history is empty")
            if (close_history <= 0).any() or (open_history <= 0).any():
                raise ValueError("nonpositive price in adjusted history")
            if metadata_dir is not None:
                metadata_path = Path(metadata_dir)
                metadata_path.mkdir(parents=True, exist_ok=True)
                (metadata_path / f"{ticker}.json").write_text(json.dumps({
                    "ticker": ticker, "requested_start": str(start_at), "requested_end": str(end_at),
                    "retrieved_at": pd.Timestamp.now(tz="UTC").isoformat(),
                    "source": YAHOO_CHART_URL.format(ticker=ticker),
                    "meta": result.get("meta", {}), "corporate_actions": result.get("events", {}),
                }, indent=2), encoding="utf-8")
            close_series.append(close_history[~close_history.index.duplicated(keep="last")])
            if not open_history.empty:
                open_series.append(open_history[~open_history.index.duplicated(keep="last")])
        except Exception as exc:
            errors[ticker] = f"{type(exc).__name__}: {exc}"
        time.sleep(delay)
    closes = pd.concat(close_series, axis=1).sort_index() if close_series else pd.DataFrame()
    opens = pd.concat(open_series, axis=1).sort_index() if open_series else pd.DataFrame()
    closes.index.name = "date"
    opens.index.name = "date"
    return opens, closes, errors


def download_adjusted_close(
    tickers: Iterable[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp | None = None,
    delay: float = 0.08,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Download daily adjusted closes and return per-symbol failures."""
    _, closes, errors = download_adjusted_ohlc(tickers, start, end, delay)
    return closes, errors
