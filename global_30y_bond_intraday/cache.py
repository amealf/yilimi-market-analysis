from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .config import resolve_config_path


def cache_root(config: dict) -> Path:
    history = config.get("history") or {}
    path_value = history.get("cache_dir", "../data/global_30y_bond_intraday/cache")
    path = resolve_config_path(config, path_value)
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_path(config: dict, market: dict, target_date: date) -> Path:
    return cache_root(config) / market["region"] / f"{target_date.isoformat()}.csv"


def read_market_cache(config: dict, market: dict, target_date: date) -> pd.DataFrame:
    path = cache_path(config, market, target_date)
    if not path.exists():
        return empty_frame()
    data = pd.read_csv(path)
    if data.empty:
        return empty_frame()
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True, errors="coerce")
    data["yield_pct"] = pd.to_numeric(data["yield_pct"], errors="coerce")
    data["source"] = data.get("source", market["source_name"])
    return data.dropna(subset=["timestamp_utc", "yield_pct"])[["timestamp_utc", "yield_pct", "source"]]


def write_market_cache(config: dict, market: dict, target_date: date, data: pd.DataFrame) -> Path | None:
    if data.empty:
        return None
    path = cache_path(config, market, target_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    output = data[["timestamp_utc", "yield_pct", "source"]].copy()
    output["timestamp_utc"] = pd.to_datetime(output["timestamp_utc"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    output.to_csv(path, index=False, encoding="utf-8")
    return path


def list_cached_dates(config: dict, markets: list[dict]) -> list[date]:
    root = cache_root(config)
    dates: set[date] = set()
    for market in markets:
        market_dir = root / market["region"]
        if not market_dir.exists():
            continue
        for path in market_dir.glob("*.csv"):
            try:
                dates.add(date.fromisoformat(path.stem))
            except ValueError:
                continue
    return sorted(dates)


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["timestamp_utc", "yield_pct", "source"])
