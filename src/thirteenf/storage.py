from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pandas as pd


def save_snapshot(df: pd.DataFrame, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        df.to_csv(temporary, index=False)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def load_snapshot(path: str | Path, allow_demo: bool = False) -> pd.DataFrame:
    result = pd.read_csv(path, dtype={"cik": str, "cusip": str})
    if not allow_demo and "source" in result and result["source"].astype(str).eq("demo").any():
        raise ValueError("Demo rows are not accepted in production mode")
    return result


def save_raw_artifact(content: bytes, directory: str | Path, filename: str) -> tuple[Path, str]:
    """Persist immutable source content and return its SHA-256 provenance hash."""
    digest = hashlib.sha256(content).hexdigest()
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    if target.exists() and target.read_bytes() != content:
        raise FileExistsError(f"Refusing to overwrite changed raw artifact: {target}")
    target.write_bytes(content)
    return target, digest
