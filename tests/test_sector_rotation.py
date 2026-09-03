import pandas as pd

from thirteenf.sector import assign_sector, build_overall_sector_rotation, build_sector_rotation


def test_assign_sector_preserves_class_mapping():
    result = assign_sector(pd.DataFrame([{"ticker_clean": "BRK-B"}, {"ticker_clean": "NOPE"}]))
    assert list(result["sector"]) == ["Financials", "Unknown"]


def test_build_sector_rotation_does_not_merge_managers():
    data = pd.DataFrame([
        {"fund": "F1", "report_period": "2024-06-30", "sector": "Energy", "portfolio_weight": 20.0},
        {"fund": "F2", "report_period": "2024-06-30", "sector": "Energy", "portfolio_weight": 30.0},
    ])
    result = build_sector_rotation(data)
    assert len(result) == 2
    assert set(result["fund"]) == {"F1", "F2"}
    assert set(result["quarter"]) == {"2024Q2"}


def test_security_master_is_resolved_point_in_time():
    holdings = pd.DataFrame([
        {"cusip": "123456789", "ticker": "", "report_period": "2020-06-30"},
        {"cusip": "123456789", "ticker": "", "report_period": "2025-06-30"},
    ])
    master = pd.DataFrame([
        {"cusip": "123456789", "ticker": "OLD", "sector": "Energy", "valid_from": "2000-01-01", "valid_to": "2020-12-31"},
        {"cusip": "123456789", "ticker": "NEW", "sector": "Industrials", "valid_from": "2021-01-01", "valid_to": ""},
    ])
    result = assign_sector(holdings, security_master=master)
    assert list(result["ticker"]) == ["OLD", "NEW"]
    assert list(result["sector"]) == ["Energy", "Industrials"]


def test_security_master_replaces_previous_unknown_sector():
    holdings = pd.DataFrame({
        "cusip": ["037833100"],
        "report_period": ["2025-03-31"],
        "ticker": [pd.NA],
        "sector": ["Unknown"],
    })
    master = pd.DataFrame({
        "cusip": ["037833100"],
        "ticker": ["AAPL"],
        "sector": ["Information Technology"],
    })
    result = assign_sector(holdings, security_master=master)
    assert result.loc[0, "ticker"] == "AAPL"
    assert result.loc[0, "sector"] == "Information Technology"


def test_overall_rotation_can_equal_weight_managers_or_pool_values():
    holdings = pd.DataFrame([
        {"fund": "Large", "report_period": "2025-03-31", "sector": "Technology", "portfolio_weight": 90.0, "market_value_usd": 900.0},
        {"fund": "Large", "report_period": "2025-03-31", "sector": "Energy", "portfolio_weight": 10.0, "market_value_usd": 100.0},
        {"fund": "Small", "report_period": "2025-03-31", "sector": "Energy", "portfolio_weight": 100.0, "market_value_usd": 100.0},
    ])

    equal = build_overall_sector_rotation(holdings, "equal_manager").set_index("sector")
    pooled = build_overall_sector_rotation(holdings, "disclosed_value").set_index("sector")

    assert equal.loc["Technology", "portfolio_weight"] == 45.0
    assert equal.loc["Energy", "portfolio_weight"] == 55.0
    assert round(pooled.loc["Technology", "portfolio_weight"], 6) == round(900 / 1100 * 100, 6)
    assert round(pooled["portfolio_weight"].sum(), 8) == 100.0
    assert set(equal["manager_count"]) == {2}


def test_overall_rotation_excludes_zero_value_placeholder_quarters():
    holdings = pd.DataFrame([
        {"fund": "Empty", "report_period": "2020-09-30", "sector": "Unknown", "portfolio_weight": 0.0, "market_value_usd": 0.0},
        {"fund": "Active", "report_period": "2025-03-31", "sector": "Energy", "portfolio_weight": 100.0, "market_value_usd": 50.0},
    ])
    result = build_overall_sector_rotation(holdings)
    assert set(result["quarter"]) == {"2025Q1"}
    assert result["portfolio_weight"].sum() == 100.0
