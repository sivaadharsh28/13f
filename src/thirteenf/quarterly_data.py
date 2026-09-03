from __future__ import annotations

import pandas as pd

from thirteenf.sector import build_sector_rotation


def build_quarterly_sector_rotation_window(holdings: pd.DataFrame) -> pd.DataFrame:
    """Build quarterly sector weights from processed SEC holdings."""
    return build_sector_rotation(holdings)
