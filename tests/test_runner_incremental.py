import pandas as pd

import thirteenf.runner as runner
from thirteenf.scrapers.sec_edgar import parse_13f_xml_content
from thirteenf.sec_pipeline import attach_filing_metadata, build_as_of_snapshots, reconcile_amendments
from thirteenf.storage import load_snapshot, save_snapshot


def _raw_holding(accession: str, period: str, accepted: str, cusip: str) -> pd.DataFrame:
    xml = f"""<informationTable><infoTable><nameOfIssuer>X</nameOfIssuer><cusip>{cusip}</cusip>
    <value>100</value><shrsOrPrnAmt><sshPrnamt>10</sshPrnamt></shrsOrPrnAmt></infoTable></informationTable>"""
    filing = {
        "cik": "0001536411",
        "accession_number": accession,
        "form": "13F-HR",
        "report_period": period,
        "filing_date": accepted[:10],
        "acceptance_datetime": accepted,
        "content_hash": accession,
    }
    return attach_filing_metadata(
        parse_13f_xml_content(xml), filing, "DUQ", f"https://www.sec.gov/{accession}"
    )


def test_incremental_refresh_preserves_history_and_replaces_only_changed_periods(tmp_path, monkeypatch):
    old = _raw_holding("OLD", "2025-12-31", "2026-02-14T20:00:00Z", "111111111")
    save_snapshot(reconcile_amendments(old), tmp_path / "sec_holdings_history.csv")
    save_snapshot(build_as_of_snapshots(old), tmp_path / "sec_holdings_events.csv")
    new = _raw_holding("NEW", "2026-03-31", "2026-05-15T20:00:00Z", "222222222")
    observed_known = {}

    monkeypatch.setattr(runner, "SECClient", lambda *_args, **_kwargs: object())

    def fake_fetch(code, _client, **kwargs):
        observed_known[code] = kwargs["known_accessions"]
        return new.copy() if code == "DUQ" else pd.DataFrame()

    monkeypatch.setattr(runner, "fetch_manager_holdings", fake_fetch)
    result = runner.run_sec_ingestion(
        output_dir=tmp_path,
        quarters=2,
        user_agent="Example research@example.com",
        incremental=True,
    )

    assert set(result["report_period"]) == {"2025-12-31", "2026-03-31"}
    assert "OLD" in observed_known["DUQ"]
    saved_events = load_snapshot(tmp_path / "sec_holdings_events.csv")
    assert set(saved_events["snapshot_accession"]) == {"OLD", "NEW"}


def test_incremental_refresh_with_no_new_filings_returns_existing_history(tmp_path, monkeypatch):
    old = _raw_holding("OLD", "2025-12-31", "2026-02-14T20:00:00Z", "111111111")
    expected = reconcile_amendments(old)
    save_snapshot(expected, tmp_path / "sec_holdings_history.csv")
    save_snapshot(build_as_of_snapshots(old), tmp_path / "sec_holdings_events.csv")

    monkeypatch.setattr(runner, "SECClient", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(runner, "fetch_manager_holdings", lambda *_args, **_kwargs: pd.DataFrame())

    result = runner.run_sec_ingestion(
        output_dir=tmp_path,
        user_agent="Example research@example.com",
        incremental=True,
    )
    assert list(result["accession_number"]) == ["OLD"]
