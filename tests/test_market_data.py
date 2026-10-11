import pandas as pd

import thirteenf.market_data as market_data


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "chart": {"result": [{
                "timestamp": [1704067200, 1704153600],
                "indicators": {
                    "quote": [{
                        "open": [100.0, 220.0],
                        "close": [100.0, 202.0],
                    }],
                    "adjclose": [{"adjclose": [100.0, 101.0]}],
                },
            }]}
        }


class FakeSession:
    def __init__(self):
        self.headers = {}

    def get(self, *args, **kwargs):
        return FakeResponse()


def test_download_adjusted_close_parses_daily_history(monkeypatch):
    monkeypatch.setattr(market_data.requests, "Session", FakeSession)
    prices, errors = market_data.download_adjusted_close(
        ["AAPL"], "2024-01-01", "2024-01-03", delay=0,
    )
    assert errors == {}
    assert list(prices.columns) == ["AAPL"]
    assert list(prices["AAPL"]) == [100.0, 101.0]
    assert prices.index.equals(pd.to_datetime(["2024-01-01", "2024-01-02"]).rename("date"))


def test_download_adjusted_ohlc_derives_adjusted_open(monkeypatch):
    monkeypatch.setattr(market_data.requests, "Session", FakeSession)
    opens, closes, errors = market_data.download_adjusted_ohlc(
        ["AAPL"], "2024-01-01", "2024-01-03", delay=0,
    )
    assert errors == {}
    assert list(closes["AAPL"]) == [100.0, 101.0]
    assert list(opens["AAPL"].round(6)) == [100.0, 110.0]
