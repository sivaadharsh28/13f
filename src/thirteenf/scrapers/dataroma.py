from __future__ import annotations

import re
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup


def _clean_text(cell: Any) -> str:
    return (cell.get_text(" ", strip=True) if hasattr(cell, "get_text") else str(cell)).strip()


def _is_valid_ticker(value: str) -> bool:
    if not value:
        return False
    cleaned = value.strip().upper().replace(".", "")
    return bool(re.fullmatch(r"[A-Z0-9-]+", cleaned)) and cleaned not in {"≡", "—", "-"}


def _parse_pct(value: str) -> float:
    return float(re.sub(r"[^0-9.\-]", "", value or "0"))


def _parse_shares(value: str) -> int:
    cleaned = re.sub(r"[^0-9]", "", value or "0")
    return int(cleaned) if cleaned else 0


def _parse_market_value(value: str) -> float:
    cleaned = value.replace("$", "").replace(",", "").replace("M", "")
    return float(cleaned) if cleaned else 0.0


def parse_dataroma_html(html: str, fund_code: str, fund_name: str) -> pd.DataFrame:
    """Parse a Dataroma HTML table into a normalized holdings DataFrame."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "etf"}) or soup.find("table")
    if table is None:
        return pd.DataFrame(columns=["ticker", "company", "pct_portfolio", "shares", "market_value_m", "fund", "fund_code"])

    rows = table.find_all("tr")
    holdings: list[dict[str, Any]] = []

    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        ticker = _clean_text(cells[0])
        company = _clean_text(cells[1])
        pct_portfolio = _parse_pct(_clean_text(cells[2]))
        shares = _parse_shares(_clean_text(cells[3]))
        market_value_m = _parse_market_value(_clean_text(cells[4]))

        if not ticker or not _is_valid_ticker(ticker):
            continue

        holdings.append(
            {
                "ticker": ticker,
                "company": company,
                "pct_portfolio": pct_portfolio,
                "shares": shares,
                "market_value_m": market_value_m,
                "fund": fund_name,
                "fund_code": fund_code,
            }
        )

    return pd.DataFrame(holdings)


def scrape_dataroma(fund_code: str, fund_name: str, url: str | None = None, timeout: int = 15) -> pd.DataFrame:
    """Fetch and parse one fund's holdings from Dataroma."""
    target_url = url or f"https://www.dataroma.com/m/holdings.php?m={fund_code}"
    try:
        response = requests.get(
            target_url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        response.raise_for_status()
        return parse_dataroma_html(response.text, fund_code, fund_name)
    except requests.RequestException:
        return pd.DataFrame(columns=["ticker", "company", "pct_portfolio", "shares", "market_value_m", "fund", "fund_code"])
