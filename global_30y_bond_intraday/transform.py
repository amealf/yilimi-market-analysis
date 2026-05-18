from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd


UTC = ZoneInfo("UTC")


def convert_yield_to_percent(values, market: dict) -> pd.Series:
    series = pd.to_numeric(values, errors="coerce") * float(market.get("value_scale", 1.0))
    unit = str(market.get("yield_unit", "percent")).lower()
    if unit in {"percent", "pct", "%"}:
        return series
    if unit in {"decimal", "ratio"}:
        return series * 100
    if unit in {"bp", "bps", "basis_points"}:
        return series / 100
    raise ValueError(f"Unsupported yield_unit: {unit}")


def utc_day_index(target_date) -> pd.DatetimeIndex:
    start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
    return pd.date_range(start=start, periods=24 * 60, freq="min")


def local_open_utc(market: dict, target_date) -> pd.Timestamp:
    hour, minute = [int(part) for part in str(market["local_open"]).split(":")[:2]]
    local_dt = datetime.combine(target_date, time(hour, minute), tzinfo=ZoneInfo(market["timezone"]))
    return pd.Timestamp(local_dt.astimezone(timezone.utc))


def standardize_market(raw: pd.DataFrame, market: dict, target_date, max_gap_minutes: int) -> pd.DataFrame:
    index = utc_day_index(target_date)
    day_start = index[0]
    day_end = day_start + pd.Timedelta(days=1)
    open_utc = local_open_utc(market, target_date)

    minute = pd.DataFrame(index=index)
    minute["raw_yield_pct"] = pd.NA

    if not raw.empty:
        data = raw.copy()
        data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True, errors="coerce")
        data["yield_pct"] = pd.to_numeric(data["yield_pct"], errors="coerce")
        data = data.dropna(subset=["timestamp_utc", "yield_pct"])
        data = data[(data["timestamp_utc"] >= day_start) & (data["timestamp_utc"] < day_end)]
        if not data.empty:
            data["minute_utc"] = data["timestamp_utc"].dt.floor("min")
            raw_series = data.groupby("minute_utc")["yield_pct"].last()
            minute["raw_yield_pct"] = raw_series.reindex(index)

    minute["yield_pct"] = minute["raw_yield_pct"].ffill(limit=max_gap_minutes)
    minute["is_forward_filled"] = minute["yield_pct"].notna() & minute["raw_yield_pct"].isna()

    after_open = minute.loc[minute.index >= open_utc, "yield_pct"].dropna()
    if after_open.empty:
        open_observed_utc = pd.NaT
        open_yield_pct = pd.NA
        minute["move_bp"] = pd.NA
    else:
        open_observed_utc = after_open.index[0]
        open_yield_pct = float(after_open.iloc[0])
        minute["move_bp"] = (pd.to_numeric(minute["yield_pct"], errors="coerce") - open_yield_pct) * 100
        minute.loc[minute.index < open_utc, "move_bp"] = pd.NA

    output = minute.reset_index(names="timestamp_utc")
    output["region"] = market["region"]
    output["label"] = market["label"]
    output["source"] = market["source_name"]
    output["timezone"] = market["timezone"]
    output["local_open"] = market["local_open"]
    output["open_timestamp_utc"] = open_utc
    output["open_observed_utc"] = open_observed_utc
    output["open_yield_pct"] = open_yield_pct
    output["timestamp_local"] = output["timestamp_utc"].dt.tz_convert(market["timezone"])
    return output[
        [
            "timestamp_utc",
            "timestamp_local",
            "region",
            "label",
            "source",
            "timezone",
            "local_open",
            "yield_pct",
            "move_bp",
            "is_forward_filled",
            "open_timestamp_utc",
            "open_observed_utc",
            "open_yield_pct",
        ]
    ]


def opening_markers(markets: list[dict], target_date) -> dict[pd.Timestamp, list[str]]:
    markers: dict[pd.Timestamp, list[str]] = {}
    city_names = {
        "Asia/Tokyo": "Tokyo",
        "Asia/Seoul": "Seoul",
        "Europe/London": "London",
        "America/New_York": "New York",
    }
    day_start = pd.Timestamp(datetime.combine(target_date, time.min, tzinfo=timezone.utc))
    day_end = day_start + pd.Timedelta(days=1) - pd.Timedelta(minutes=1)
    for market in markets:
        open_time = local_open_utc(market, target_date)
        if day_start <= open_time <= day_end:
            city = city_names.get(market["timezone"], market["region"])
            markers.setdefault(open_time, []).append(f"{city} open")
    return markers
