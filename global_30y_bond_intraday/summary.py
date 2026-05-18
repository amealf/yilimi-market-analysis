from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_summary(data: pd.DataFrame, markets: list[dict]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for market in markets:
        frame = data[data["region"] == market["region"]]
        valid = frame.dropna(subset=["yield_pct", "move_bp"])
        raw_count = int(frame["yield_pct"].notna().sum()) if not frame.empty else 0
        filled_count = int(frame["is_forward_filled"].sum()) if not frame.empty else 0
        if valid.empty:
            rows.append(
                {
                    "region": market["region"],
                    "label": market["label"],
                    "source": market["source_name"],
                    "status": "missing",
                    "latest_timestamp_utc": "",
                    "latest_local_time": "",
                    "latest_yield_pct": "",
                    "open_timestamp_utc": format_timestamp(frame["open_timestamp_utc"].dropna().iloc[0]) if not frame.empty and frame["open_timestamp_utc"].notna().any() else "",
                    "open_observed_utc": "",
                    "open_yield_pct": "",
                    "move_bp": "",
                    "valid_minutes": raw_count,
                    "forward_filled_minutes": filled_count,
                }
            )
            continue

        latest = valid.iloc[-1]
        rows.append(
            {
                "region": market["region"],
                "label": market["label"],
                "source": market["source_name"],
                "status": "ok",
                "latest_timestamp_utc": format_timestamp(latest["timestamp_utc"]),
                "latest_local_time": format_timestamp(latest["timestamp_local"]),
                "latest_yield_pct": round(float(latest["yield_pct"]), 6),
                "open_timestamp_utc": format_timestamp(latest["open_timestamp_utc"]),
                "open_observed_utc": format_timestamp(latest["open_observed_utc"]),
                "open_yield_pct": round(float(latest["open_yield_pct"]), 6),
                "move_bp": round(float(latest["move_bp"]), 1),
                "valid_minutes": raw_count,
                "forward_filled_minutes": filled_count,
            }
        )
    return pd.DataFrame(rows)


def write_summary_csv(summary: pd.DataFrame, output_csv: str | Path) -> None:
    path = Path(output_csv)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(path, index=False, encoding="utf-8-sig")


def chart_meta(summary: pd.DataFrame, target_date, warnings: list[str]) -> dict:
    metrics = []
    for row in summary.itertuples(index=False):
        if row.status == "ok":
            value = f"{float(row.latest_yield_pct):.3f}% / {float(row.move_bp):+.1f} bp"
            date_text = row.latest_timestamp_utc
        else:
            value = "No data"
            date_text = str(target_date)
        metrics.append({"label": row.label, "value": value, "date": date_text})
    return {
        "latestDate": str(target_date),
        "metrics": metrics,
        "warnings": warnings,
    }


def format_timestamp(value: object) -> str:
    if pd.isna(value):
        return ""
    return pd.Timestamp(value).isoformat()
