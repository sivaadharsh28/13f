import pandas as pd

from thirteenf import normalize


def test_standardize_ticker_preserves_share_class():
    assert normalize.standardize_ticker("BRK.B") == "BRK-B"
    assert normalize.standardize_ticker("GOOGL") == "GOOGL"


def test_standardize_ticker_rejects_missing_and_ui_symbols():
    assert normalize.standardize_ticker(None) is None
    assert normalize.standardize_ticker(float("nan")) is None
    assert normalize.standardize_ticker("≡") is None


def test_standardize_dataframe_ticker_column():
    result = normalize.standardize_dataframe_ticker_column(pd.DataFrame({"ticker": ["BRK.B", "MSFT"]}))
    assert list(result["ticker_clean"]) == ["BRK-B", "MSFT"]

