import pandas as pd

from thirteenf.storage import save_snapshot, load_snapshot


def test_storage_round_trip(tmp_path):
    df = pd.DataFrame([
        {"ticker_clean": "AAPL", "fund": "F1", "portfolio_weight": 3.0, "quarter": "2024Q2"}
    ])

    path = tmp_path / "snapshot.csv"
    save_snapshot(df, path)
    result = load_snapshot(path)

    assert not result.empty
    assert result.iloc[0]["ticker_clean"] == "AAPL"
    assert result.iloc[0]["fund"] == "F1"


def test_production_load_rejects_demo_rows(tmp_path):
    path = tmp_path / "demo.csv"
    save_snapshot(pd.DataFrame([{"ticker": "AAPL", "source": "demo"}]), path)
    try:
        load_snapshot(path)
    except ValueError as exc:
        assert "Demo rows" in str(exc)
    else:
        raise AssertionError("demo data was accepted in production mode")
