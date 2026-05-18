from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from ..config import resolve_config_path
from ..transform import convert_yield_to_percent


def fetch(market: dict, target_date, config: dict) -> pd.DataFrame:
    path = resolve_config_path(config, market["path"])
    if not path.exists():
        if market.get("optional", False):
            return empty_frame()
        raise FileNotFoundError(path)

    data = pd.read_csv(path)
    timestamp_column = market.get("timestamp_column", "timestamp")
    yield_column = market.get("yield_column", "yield")
    missing = [column for column in [timestamp_column, yield_column] if column not in data.columns]
    if missing:
        raise ValueError(f"{path} is missing columns: {', '.join(missing)}")

    frame = pd.DataFrame(
        {
            "timestamp_utc": parse_timestamps(data[timestamp_column], market["timezone"]),
            "yield_pct": convert_yield_to_percent(data[yield_column], market),
        }
    )
    frame["source"] = market["source_name"]
    return frame.dropna(subset=["timestamp_utc", "yield_pct"]).sort_values("timestamp_utc")


def parse_timestamps(values: pd.Series, timezone_name: str) -> pd.Series:
    timezone = ZoneInfo(timezone_name)
    parsed = []
    for value in values:
        if pd.isna(value):
            parsed.append(pd.NaT)
            continue
        try:
            timestamp = pd.Timestamp(value)
        except ValueError:
            parsed.append(pd.NaT)
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(timezone)
        parsed.append(timestamp.tz_convert("UTC"))
    return pd.Series(parsed, index=values.index, dtype="datetime64[ns, UTC]")


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["timestamp_utc", "yield_pct", "source"])
