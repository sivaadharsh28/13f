from thirteenf.runner import fetch_manager_holdings


class FakeSECClient:
    def get_json(self, url):
        return {
            "cik": "1536411",
            "name": "Duquesne Family Office LLC",
            "filings": {"recent": {
                "accessionNumber": ["0001536411-26-000006"],
                "form": ["13F-HR"],
                "filingDate": ["2026-08-14"],
                "reportDate": ["2026-06-30"],
                "acceptanceDateTime": ["2026-08-14T19:55:57.000Z"],
                "primaryDocument": ["primary_doc.xml"],
            }},
        }

    def get_text(self, url):
        return """<table class="tableFile">
        <tr><td>1</td><td></td><td><a href="primary_doc.xml">primary</a></td><td>13F-HR</td><td>1</td></tr>
        <tr><td>2</td><td></td><td><a href="info.xml">info</a></td><td>INFORMATION TABLE</td><td>1</td></tr>
        </table>"""

    def get_bytes(self, url):
        if url.endswith("primary_doc.xml"):
            return b"<edgarSubmission><isAmendment>false</isAmendment><reportCalendarOrQuarter>06-30-2026</reportCalendarOrQuarter></edgarSubmission>"
        return b"""<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
        <infoTable><nameOfIssuer>Apple Inc</nameOfIssuer><cusip>037833100</cusip><value>1000000</value>
        <shrsOrPrnAmt><sshPrnamt>100</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>
        </informationTable>"""


def test_manager_ingestion_is_end_to_end_and_preserves_provenance(tmp_path):
    result = fetch_manager_holdings("DUQ", FakeSECClient(), quarters=1, raw_dir=tmp_path)
    assert len(result) == 1
    assert result.iloc[0]["cik"] == "0001536411"
    assert result.iloc[0]["cusip"] == "037833100"
    assert result.iloc[0]["portfolio_weight"] == 100.0
    assert len(result.iloc[0]["content_hash"]) == 64
    assert (tmp_path / "DUQ" / "0001536411-26-000006" / "information_table.xml").exists()

