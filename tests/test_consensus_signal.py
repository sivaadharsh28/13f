import pandas as pd

from thirteenf import consensus


def test_consensus_long_signal_selects_qualified_tickers():
    df = pd.DataFrame(
        {
            "ticker": ["AAPL", "AAPL", "AAPL", "MSFT", "MSFT", "NVDA"],
            "fund": ["F1", "F2", "F3", "F1", "F2", "F1"],
            "pct_portfolio": [3.0, 4.0, 2.5, 2.0, 2.4, 1.8],
        }
    )

    result = consensus.consensus_long_signal(df, min_funds=3, min_weight=2.0)

    assert list(result["ticker"]) == ["AAPL"]
    assert result.iloc[0]["fund_count"] == 3
    assert result.iloc[0]["avg_weight"] >= 2.0
