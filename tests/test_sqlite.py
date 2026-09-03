import sqlite3

from thirteenf.db import init_db, insert_snapshot


def test_sqlite_round_trip(tmp_path):
    db_path = tmp_path / "alpha.db"
    init_db(db_path)

    insert_snapshot(
        db_path,
        "2024Q2",
        [
            {
                "ticker_clean": "AAPL",
                "fund": "F1",
                "portfolio_weight": 3.5,
                "source": "dataroma",
                "company": "Apple Inc",
            }
        ],
    )

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT ticker_clean, fund, portfolio_weight FROM quarterly_snapshots WHERE quarter = '2024Q2'"
    ).fetchall()
    conn.close()

    assert rows[0][0] == "AAPL"
    assert rows[0][1] == "F1"
    assert rows[0][2] == 3.5
