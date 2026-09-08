from __future__ import annotations

from pathlib import Path

import pandas as pd


def parquet_path(
    data_root: Path,
    dataset: str,
    scope_key: str,
    period_start: str,
    period_end: str,
) -> Path:
    safe_scope = scope_key.replace("/", "_")
    return (
        data_root
        / "raw"
        / "entsoe"
        / dataset
        / safe_scope
        / f"{period_start}_{period_end}.parquet"
    )


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def read_parquet(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)
