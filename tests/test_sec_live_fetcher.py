from thirteenf.sec_live import (
    fetch_sec_company_filings, parse_company_filing_index,
    parse_filing_document_index, parse_submissions, validate_manager_identity,
)


PAYLOAD = {
    "cik": "1536411",
    "name": "Duquesne Family Office LLC",
    "filings": {"recent": {
        "accessionNumber": ["0001536411-26-000006", "0000000000-26-000001"],
        "form": ["13F-HR", "N-PX"],
        "filingDate": ["2026-08-14", "2026-08-01"],
        "reportDate": ["2026-06-30", "2026-06-30"],
        "acceptanceDateTime": ["2026-08-14T19:55:57.000Z", "2026-08-01T00:00:00.000Z"],
        "primaryDocument": ["primary_doc.xml", "npx.xml"],
    }},
}


class FakeClient:
    def get_json(self, url):
        assert url.endswith("CIK0001536411.json")
        return PAYLOAD


class FakeArchiveClient:
    def get_json(self, url):
        if url.endswith("CIK0001536411.json"):
            payload = dict(PAYLOAD)
            payload["filings"] = dict(PAYLOAD["filings"])
            payload["filings"]["files"] = [{
                "name": "CIK0001536411-submissions-001.json",
                "filingFrom": "2013-01-01",
                "filingTo": "2015-01-01",
            }]
            return payload
        assert url.endswith("CIK0001536411-submissions-001.json")
        return {
            "accessionNumber": ["0001536411-14-000001"],
            "form": ["13F-HR"],
            "filingDate": ["2014-05-15"],
            "reportDate": ["2014-03-31"],
            "acceptanceDateTime": ["2014-05-15T16:00:00.000Z"],
            "primaryDocument": ["primary.xml"],
        }


def test_parse_submissions_and_fetch_are_offline():
    result = fetch_sec_company_filings("1536411", client=FakeClient())
    assert len(result) == 1
    assert result.iloc[0]["report_period"] == "2026-06-30"
    assert result.iloc[0]["cik"] == "0001536411"


def test_fetch_includes_archived_submission_files_for_start_date():
    result = fetch_sec_company_filings(
        "1536411", count=None, client=FakeArchiveClient(), start_date="2014-01-01",
    )
    assert set(result["report_period"]) == {"2014-03-31", "2026-06-30"}
    assert set(result["entity_name"]) == {"Duquesne Family Office LLC"}


def test_document_index_selects_by_type():
    html = """<table class="tableFile">
    <tr><td>1</td><td></td><td><a href="primary_doc.xml">primary_doc.xml</a></td><td>13F-HR</td><td>1</td></tr>
    <tr><td>2</td><td></td><td><a href="info.xml">info.xml</a></td><td>INFORMATION TABLE</td><td>1</td></tr>
    </table>"""
    result = parse_filing_document_index(html, "https://www.sec.gov/Archives/example/index.html")
    assert result["cover_xml_url"].endswith("primary_doc.xml")
    assert result["information_table_xml_url"].endswith("info.xml")


def test_identity_mismatch_fails():
    try:
        validate_manager_identity("Wrong Entity", ["DUQUESNE FAMILY OFFICE LLC"])
    except ValueError as exc:
        assert "mismatch" in str(exc)
    else:
        raise AssertionError("identity mismatch was accepted")


def test_legacy_html_parser_is_retained():
    html = '<table><tr><td><a href="/index.html">Index</a></td><td>2024-05-15</td></tr></table>'
    assert parse_company_filing_index(html).iloc[0]["filing_date"] == "2024-05-15"
