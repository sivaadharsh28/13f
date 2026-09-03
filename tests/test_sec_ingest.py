import pandas as pd

from thirteenf.scrapers.sec_edgar import parse_13f_xml_content
from thirteenf.sec_pipeline import (
    attach_filing_metadata, build_as_of_snapshots, filing_value_unit,
    reconcile_amendments,
)


def _filing(accession, form, accepted):
    return {
        "cik": "0001536411", "accession_number": accession, "form": form,
        "report_period": "2026-06-30", "filing_date": accepted[:10],
        "acceptance_datetime": accepted,
    }


def _holding(cusip, value):
    xml = f"""<informationTable><infoTable><nameOfIssuer>X</nameOfIssuer><cusip>{cusip}</cusip>
    <value>{value}</value><shrsOrPrnAmt><sshPrnamt>10</sshPrnamt></shrsOrPrnAmt></infoTable></informationTable>"""
    return parse_13f_xml_content(xml)


def test_value_unit_boundary():
    assert filing_value_unit("2023-01-02") == "usd_thousands"
    assert filing_value_unit("2023-01-03") == "usd"


def test_restatement_replaces_and_events_do_not_rewrite_history():
    original = attach_filing_metadata(
        _holding("111111111", 100), _filing("A", "13F-HR", "2026-08-14T16:00:00Z"), "DUQ", "u1"
    )
    amended = attach_filing_metadata(
        _holding("222222222", 200), _filing("B", "13F-HR/A", "2026-08-20T16:00:00Z"), "DUQ", "u2", "restatement"
    )
    rows = pd.concat([original, amended], ignore_index=True)
    final = reconcile_amendments(rows)
    assert list(final["cusip"]) == ["222222222"]
    events = build_as_of_snapshots(rows)
    first_event = events[events["snapshot_accession"].eq("A")]
    assert list(first_event["cusip"]) == ["111111111"]


def test_additive_amendment_appends_and_reweights():
    original = attach_filing_metadata(
        _holding("111111111", 100), _filing("A", "13F-HR", "2026-08-14T16:00:00Z"), "DUQ", "u1"
    )
    added = attach_filing_metadata(
        _holding("222222222", 100), _filing("B", "13F-HR/A", "2026-08-20T16:00:00Z"), "DUQ", "u2", "adds_new_holdings"
    )
    final = reconcile_amendments(pd.concat([original, added], ignore_index=True))
    assert set(final["cusip"]) == {"111111111", "222222222"}
    assert set(final["portfolio_weight"]) == {50.0}

