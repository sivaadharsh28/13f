import pandas as pd

from thirteenf.funds import FUND_CONFIG
from thirteenf.ingest import prepare_holdings_dataframe


def test_fund_config_has_correct_sec_coverage():
    assert len(FUND_CONFIG) == 10
    assert FUND_CONFIG["PSC"]["cik"] == "0001336528"
    assert FUND_CONFIG["DUQ"]["cik"] == "0001536411"
    assert FUND_CONFIG["THIEL"]["cik"] == "0001562087"
    assert len({fund["cik"] for fund in FUND_CONFIG.values()}) == 10


def test_prepare_holdings_dataframe_preserves_class_and_weight():
    raw = pd.DataFrame([{"ticker": "BRK.B", "fund": "Berkshire", "pct_portfolio": 12.5}])
    result = prepare_holdings_dataframe(raw)
    assert result.iloc[0]["ticker_clean"] == "BRK-B"
    assert result.iloc[0]["portfolio_weight"] == 12.5

