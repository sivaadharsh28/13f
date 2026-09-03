"""SEC EDGAR discovery and retrieval using declared, rate-limited access."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

from thirteenf.config import sec_user_agent
from thirteenf.funds import normalize_cik


SEC_BASE = "https://www.sec.gov"
SEC_DATA_BASE = "https://data.sec.gov"
FILING_COLUMNS = [
    "cik", "entity_name", "accession_number", "form", "filing_date",
    "report_period", "acceptance_datetime", "primary_document", "index_url",
]


@dataclass
class SECClient:
    user_agent: str
    min_interval_seconds: float = 0.12
    timeout: int = 30
    max_retries: int = 3
    session: requests.Session = field(default_factory=requests.Session)
    _last_request_at: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self.user_agent = sec_user_agent(self.user_agent)
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
        })

    def _get(self, url: str) -> requests.Response:
        for attempt in range(self.max_retries):
            wait = self.min_interval_seconds - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            response = self.session.get(url, timeout=self.timeout)
            self._last_request_at = time.monotonic()
            if response.status_code not in {429, 500, 502, 503, 504}:
                response.raise_for_status()
                return response
            if attempt + 1 < self.max_retries:
                time.sleep(2 ** attempt)
        response.raise_for_status()
        return response

    def get_json(self, url: str) -> dict[str, Any]:
        return self._get(url).json()

    def get_text(self, url: str) -> str:
        return self._get(url).text

    def get_bytes(self, url: str) -> bytes:
        return self._get(url).content


def parse_submissions(
    payload: dict[str, Any],
    forms: tuple[str, ...] = ("13F-HR", "13F-HR/A"),
    cik: str | None = None,
    entity_name: str | None = None,
) -> pd.DataFrame:
    """Convert the columnar SEC submissions response to filing records."""
    recent = payload.get("filings", {}).get("recent", payload)
    accessions = recent.get("accessionNumber", [])
    rows: list[dict[str, str]] = []
    normalized_cik = normalize_cik(payload.get("cik") or cik or "")
    resolved_name = str(payload.get("name") or entity_name or "")

    def value_at(column: str, index: int) -> str:
        values = recent.get(column, [])
        return str(values[index]) if index < len(values) else ""

    for index, accession in enumerate(accessions):
        form = value_at("form", index)
        if form not in forms:
            continue
        accession_compact = str(accession).replace("-", "")
        archive_dir = f"{SEC_BASE}/Archives/edgar/data/{int(normalized_cik)}/{accession_compact}/"
        rows.append({
            "cik": normalized_cik,
            "entity_name": resolved_name,
            "accession_number": str(accession),
            "form": form,
            "filing_date": value_at("filingDate", index),
            "report_period": value_at("reportDate", index),
            "acceptance_datetime": value_at("acceptanceDateTime", index),
            "primary_document": value_at("primaryDocument", index),
            "index_url": f"{archive_dir}{accession}-index.html",
        })
    return pd.DataFrame(rows, columns=FILING_COLUMNS)


def fetch_sec_company_filings(
    cik: str,
    count: int | None = 10,
    client: SECClient | None = None,
    user_agent: str | None = None,
    start_date: str | None = None,
) -> pd.DataFrame:
    """Fetch 13F filings, including SEC archive pages when needed."""
    active_client = client or SECClient(sec_user_agent(user_agent))
    normalized = normalize_cik(cik)
    payload = active_client.get_json(f"{SEC_DATA_BASE}/submissions/CIK{normalized}.json")
    entity_name = str(payload.get("name", ""))
    frames = [parse_submissions(payload, cik=normalized, entity_name=entity_name)]
    if start_date:
        threshold = pd.Timestamp(start_date)
        for archive in payload.get("filings", {}).get("files", []):
            filing_to = pd.to_datetime(archive.get("filingTo"), errors="coerce")
            if pd.notna(filing_to) and filing_to < threshold:
                continue
            archive_name = str(archive.get("name", ""))
            if not archive_name:
                continue
            archive_payload = active_client.get_json(f"{SEC_DATA_BASE}/submissions/{archive_name}")
            frames.append(parse_submissions(
                archive_payload, cik=normalized, entity_name=entity_name,
            ))
    result = pd.concat(frames, ignore_index=True).drop_duplicates("accession_number")
    result = result.sort_values("acceptance_datetime", ascending=False)
    if start_date:
        report_dates = pd.to_datetime(result["report_period"], errors="coerce")
        result = result[report_dates.ge(pd.Timestamp(start_date))]
    if count is not None:
        result = result.head(count)
    return result.reset_index(drop=True)


def validate_manager_identity(entity_name: str, expected_names: list[str]) -> None:
    actual = " ".join(entity_name.upper().split())
    aliases = {" ".join(name.upper().split()) for name in expected_names}
    if actual not in aliases:
        raise ValueError(f"SEC entity mismatch: got {entity_name!r}; expected one of {sorted(aliases)}")


def parse_filing_document_index(html: str, index_url: str = SEC_BASE) -> dict[str, str]:
    """Locate the cover and INFORMATION TABLE XML documents by document type."""
    soup = BeautifulSoup(html, "html.parser")
    result = {"cover_xml_url": "", "information_table_xml_url": ""}
    for row in soup.select("table.tableFile tr, table tr"):
        cells = row.find_all("td")
        link = row.find("a", href=True)
        if not cells or link is None:
            continue
        href = str(link.get("href", ""))
        if not href.lower().endswith(".xml"):
            continue
        cell_text = [cell.get_text(" ", strip=True).upper() for cell in cells]
        document_type = cell_text[3] if len(cell_text) > 3 else ""
        absolute = urljoin(index_url, href)
        if document_type == "INFORMATION TABLE" or "INFORMATION TABLE" in " ".join(cell_text):
            result["information_table_xml_url"] = absolute
        elif document_type in {"13F-HR", "13F-HR/A"}:
            result["cover_xml_url"] = absolute
    return result


def parse_company_filing_index(html: str) -> pd.DataFrame:
    """Compatibility parser for legacy company-search HTML fixtures."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str]] = []
    for row in soup.select("tr"):
        link = row.find("a", href=True)
        cells = row.find_all("td")
        dates = [cell.get_text(" ", strip=True) for cell in cells]
        filing_date = next((value for value in dates if len(value) >= 10 and value[4:5] == "-"), "")
        if link is not None and filing_date:
            rows.append({"filing_date": filing_date, "index_url": str(link["href"])})
    return pd.DataFrame(rows, columns=["filing_date", "index_url"])


def parse_13f_index_entries(index_html: str, index_url: str = SEC_BASE) -> list[dict[str, Any]]:
    documents = parse_filing_document_index(index_html, index_url)
    url = documents["information_table_xml_url"]
    return [{"xml_url": url}] if url else []
