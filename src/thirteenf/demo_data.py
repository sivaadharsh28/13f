from __future__ import annotations

import pandas as pd


def get_demo_snapshot() -> pd.DataFrame:
    """Create a small realistic demo dataset for the Streamlit dashboard."""
    return pd.DataFrame(
        [
            {"ticker_clean": "AAPL", "fund": "Warren Buffett - Berkshire", "portfolio_weight": 3.1, "quarter": "2024Q2", "sector": "Information Technology"},
            {"ticker_clean": "AAPL", "fund": "Bill Ackman - Pershing Square", "portfolio_weight": 2.8, "quarter": "2024Q2", "sector": "Information Technology"},
            {"ticker_clean": "AAPL", "fund": "David Tepper - Appaloosa", "portfolio_weight": 2.4, "quarter": "2024Q2", "sector": "Information Technology"},
            {"ticker_clean": "MSFT", "fund": "Warren Buffett - Berkshire", "portfolio_weight": 2.1, "quarter": "2024Q2", "sector": "Information Technology"},
            {"ticker_clean": "AMZN", "fund": "David Tepper - Appaloosa", "portfolio_weight": 1.9, "quarter": "2024Q2", "sector": "Consumer Discretionary"},
            {"ticker_clean": "XOM", "fund": "Stanley Druckenmiller - Duquesne", "portfolio_weight": 2.7, "quarter": "2024Q2", "sector": "Energy"},
            {"ticker_clean": "JPM", "fund": "Bill Ackman - Pershing Square", "portfolio_weight": 2.3, "quarter": "2024Q2", "sector": "Financials"},
            {"ticker_clean": "PG", "fund": "Warren Buffett - Berkshire", "portfolio_weight": 1.8, "quarter": "2024Q2", "sector": "Consumer Staples"},
            {"ticker_clean": "AAPL", "fund": "Warren Buffett - Berkshire", "portfolio_weight": 3.4, "quarter": "2024Q3", "sector": "Information Technology"},
            {"ticker_clean": "MSFT", "fund": "Bill Ackman - Pershing Square", "portfolio_weight": 2.9, "quarter": "2024Q3", "sector": "Information Technology"},
            {"ticker_clean": "NVDA", "fund": "David Tepper - Appaloosa", "portfolio_weight": 2.6, "quarter": "2024Q3", "sector": "Information Technology"},
            {"ticker_clean": "XOM", "fund": "Stanley Druckenmiller - Duquesne", "portfolio_weight": 3.1, "quarter": "2024Q3", "sector": "Energy"},
        ]
    )
