import pandas as pd

from thirteenf.dashboard import build_dashboard_data


def test_build_dashboard_data_returns_expected_columns():
    snapshot = pd.DataFrame(
        [
            {"ticker_clean": "AAPL", "fund": "F1", "portfolio_weight": 3.0, "quarter": "2024Q2"},
            {"ticker_clean": "AAPL", "fund": "F2", "portfolio_weight": 4.0, "quarter": "2024Q2"},
            {"ticker_clean": "MSFT", "fund": "F1", "portfolio_weight": 2.0, "quarter": "2024Q2"},
        ]
    )

    data = build_dashboard_data(snapshot)

    assert "consensus" in data
    assert "quarterly_holdings" in data
    assert list(data["quarterly_holdings"].columns) == [
        "ticker_clean",
        "fund",
        "portfolio_weight",
        "quarter",
    ]
    assert data["consensus"].iloc[0]["ticker_clean"] == "AAPL"


def test_build_dashboard_data_handles_missing_quarter_column():
    snapshot = pd.DataFrame(
        [
            {"ticker_clean": "AAPL", "fund": "F1", "pct_portfolio": 3.0},
            {"ticker_clean": "AAPL", "fund": "F2", "pct_portfolio": 4.0},
            {"ticker_clean": "MSFT", "fund": "F1", "pct_portfolio": 2.0},
        ]
    )

    data = build_dashboard_data(snapshot)

    assert list(data["quarterly_holdings"].columns) == [
        "ticker_clean",
        "fund",
        "portfolio_weight",
        "quarter",
    ]
    assert set(data["quarterly_holdings"]["quarter"]) == {"unknown"}
    assert data["consensus"].iloc[0]["ticker_clean"] == "AAPL"


def test_build_dashboard_data_filters_invalid_ticker_symbols():
    snapshot = pd.DataFrame(
        [
            {"ticker_clean": "≡", "fund": "F1", "portfolio_weight": 3.0, "quarter": "2024Q2"},
            {"ticker_clean": "AAPL", "fund": "F1", "portfolio_weight": 4.0, "quarter": "2024Q2"},
            {"ticker_clean": "MSFT", "fund": "F1", "portfolio_weight": 2.0, "quarter": "2024Q2"},
        ]
    )

    data = build_dashboard_data(snapshot)

    assert "≡" not in set(data["quarterly_holdings"]["ticker_clean"])
    assert set(data["consensus"]["ticker_clean"]) == {"AAPL", "MSFT"}
