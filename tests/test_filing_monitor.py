import pandas as pd

from thirteenf.filing_monitor import (
    build_combined_positioning,
    build_new_consensus_alerts,
    build_position_change_alerts,
    build_sector_change_alerts,
)


def _row(manager, fund, quarter, ticker, weight, sector, value=None, accepted=None):
    return {
        "manager_code": manager,
        "fund": fund,
        "report_period": quarter,
        "acceptance_datetime": accepted or f"{pd.Timestamp(quarter) + pd.Timedelta(days=40):%Y-%m-%d}",
        "source_url": f"https://www.sec.gov/{manager}/{quarter}",
        "cusip": f"{abs(hash((ticker, 'cusip'))) % 1_000_000_000:09d}" if ticker else "000000000",
        "ticker_clean": ticker,
        "issuer": ticker,
        "put_call": "",
        "portfolio_weight": weight,
        "market_value_usd": value if value is not None else weight * 1_000_000,
        "sector": sector,
    }


def test_position_alerts_include_material_changes_and_every_full_exit():
    data = pd.DataFrame([
        _row("DUQ", "Duquesne", "2025-03-31", "A", 60, "Technology"),
        _row("DUQ", "Duquesne", "2025-03-31", "B", 40, "Energy"),
        _row("DUQ", "Duquesne", "2025-06-30", "A", 93, "Technology"),
        _row("DUQ", "Duquesne", "2025-06-30", "C", 3, "Financials"),
        _row("DUQ", "Duquesne", "2025-06-30", "D", 4, "Industrials"),
    ])
    result = build_position_change_alerts(data, threshold_pp=5)

    assert set(result["change_type"]) == {"Weight increase", "Full exit"}
    assert set(result.loc[result["change_type"].eq("Full exit"), "asset"]) == {"B"}
    assert "C" not in set(result["asset"])


def test_empty_filing_triggers_full_exit_but_not_a_placeholder_alert():
    data = pd.DataFrame([
        _row("THIEL", "Thiel Macro", "2025-09-30", "A", 100, "Technology"),
        _row("THIEL", "Thiel Macro", "2025-12-31", "", 0, "Unknown", value=0),
    ])
    result = build_position_change_alerts(data, threshold_pp=5)

    assert list(result["change_type"]) == ["Full exit"]
    assert list(result["asset"]) == ["A"]


def test_sector_alerts_use_percentage_point_changes_and_exclude_unknown():
    data = pd.DataFrame([
        _row("AM", "Appaloosa", "2025-03-31", "A", 60, "Technology"),
        _row("AM", "Appaloosa", "2025-03-31", "B", 40, "Energy"),
        _row("AM", "Appaloosa", "2025-06-30", "A", 50, "Technology"),
        _row("AM", "Appaloosa", "2025-06-30", "B", 40, "Energy"),
        _row("AM", "Appaloosa", "2025-06-30", "C", 10, "Unknown"),
    ])
    result = build_sector_change_alerts(data, threshold_pp=5)

    assert list(result["sector"]) == ["Technology"]
    assert result.iloc[0]["change_pp"] == -10


def test_combined_positioning_and_new_consensus_use_all_reporting_managers():
    data = pd.DataFrame([
        _row("F1", "Fund 1", "2025-03-31", "A", 20, "Technology", value=200),
        _row("F2", "Fund 2", "2025-03-31", "B", 10, "Energy", value=100),
        _row("F1", "Fund 1", "2025-06-30", "A", 30, "Technology", value=300),
        _row("F2", "Fund 2", "2025-06-30", "A", 10, "Technology", value=100),
    ])
    combined = build_combined_positioning(data)
    latest = combined[(combined["quarter"].eq("2025Q2")) & combined["asset"].eq("A")].iloc[0]

    assert latest["fund_count"] == 2
    assert latest["managers_reporting"] == 2
    assert latest["equal_manager_weight"] == 20
    assert latest["pooled_value_weight"] == 100

    alerts = build_new_consensus_alerts(data, min_managers=2)
    assert list(alerts["asset"]) == ["A"]
    assert alerts.iloc[0]["previous_fund_count"] == 1


def test_zero_threshold_keeps_small_unchanged_and_exited_sectors():
    data = pd.DataFrame([
        _row("AM", "Appaloosa", "2025-03-31", "A", 96, "Technology"),
        _row("AM", "Appaloosa", "2025-03-31", "B", 1, "Energy"),
        _row("AM", "Appaloosa", "2025-03-31", "C", 1, "Utilities"),
        _row("AM", "Appaloosa", "2025-03-31", "D", 2, "Materials"),
        _row("AM", "Appaloosa", "2025-06-30", "A", 97, "Technology"),
        _row("AM", "Appaloosa", "2025-06-30", "B", 2, "Energy"),
        _row("AM", "Appaloosa", "2025-06-30", "C", 1, "Utilities"),
    ])
    result = build_sector_change_alerts(data, threshold_pp=0).set_index("sector")
    assert set(result.index) == {"Technology", "Energy", "Utilities", "Materials"}
    assert result.loc["Utilities", "change_pp"] == 0
    assert result.loc["Energy", "change_pp"] == 1
    assert result.loc["Materials", "current_weight"] == 0
    assert build_sector_change_alerts(data, threshold_pp=5).empty
