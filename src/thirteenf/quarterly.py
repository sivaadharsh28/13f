from __future__ import annotations

import pandas as pd

from thirteenf.consensus import consensus_long_signal
from thirteenf.ingest import prepare_holdings_dataframe


def build_quarterly_snapshot(frames: list[pd.DataFrame], quarter: str) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    normalized: list[pd.DataFrame] = []
    for frame in frames:
        current = prepare_holdings_dataframe(frame)
        current["quarter"] = quarter
        normalized.append(current)
    return pd.concat(normalized, ignore_index=True, sort=False)


def build_consensus_report(snapshot: pd.DataFrame, min_funds: int = 3, min_weight: float = 2.0) -> pd.DataFrame:
    return consensus_long_signal(snapshot, min_funds=min_funds, min_weight=min_weight)
