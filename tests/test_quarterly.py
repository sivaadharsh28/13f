import pandas as pd

from thirteenf.quarterly import build_consensus_report, build_quarterly_snapshot


def test_build_quarterly_snapshot_preserves_each_source_weight():
    d1 = pd.DataFrame([{"ticker": "BRK.B", "fund": "F1", "pct_portfolio": 10.0}])
    d2 = pd.DataFrame([{"ticker": "AAPL", "fund": "F2", "portfolio_weight": 20.0}])
    result = build_quarterly_snapshot([d1, d2], "2024Q2")
    assert list(result["ticker_clean"]) == ["BRK-B", "AAPL"]
    assert list(result["portfolio_weight"]) == [10.0, 20.0]


def test_consensus_is_calculated_per_quarter():
    data = pd.DataFrame([
        {"ticker_clean": "AAPL", "fund": "F1", "portfolio_weight": 3.0, "quarter": "2024Q2"},
        {"ticker_clean": "AAPL", "fund": "F2", "portfolio_weight": 4.0, "quarter": "2024Q2"},
        {"ticker_clean": "AAPL", "fund": "F1", "portfolio_weight": 5.0, "quarter": "2024Q3"},
    ])
    result = build_consensus_report(data, min_funds=2)
    assert list(result["quarter"]) == ["2024Q2"]

