from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "global_30y_bond_intraday"

from .cache import list_cached_dates, read_market_cache, write_market_cache
from .config import DEFAULT_CONFIG_PATH, load_config, parse_target_date, resolve_config_path
from .plot import write_plot
from .providers import cnbc_provider, csv_provider, yahoo_provider
from .summary import build_summary, chart_meta, write_summary_csv
from .transform import standardize_market


PROVIDERS = {
    "cnbc": cnbc_provider.fetch,
    "csv": csv_provider.fetch,
    "yahoo": yahoo_provider.fetch,
}


def build(
    config_path: str | Path | None = None,
    target_date: str | None = None,
    output_html: str | Path | None = None,
    summary_csv: str | Path | None = None,
    strict: bool = False,
    refresh_cache: bool = False,
    allow_fetch: bool = True,
    available_dates: list | None = None,
) -> dict:
    config = load_config(config_path)
    selected_date = parse_target_date(target_date or config.get("date"))
    markets = config["markets"]
    max_gap_minutes = int((config.get("fill") or {}).get("max_gap_minutes", 10))
    warnings: list[str] = []
    frames = []

    for market in markets:
        raw, market_warnings = fetch_market_with_cache(
            config,
            market,
            selected_date,
            strict=strict,
            refresh_cache=refresh_cache,
            allow_fetch=allow_fetch,
        )
        warnings.extend(market_warnings)
        if raw.empty:
            warnings.append(f"{market['label']}: no data rows available")
        frames.append(standardize_market(raw, market, selected_date, max_gap_minutes))

    data = pd.concat(frames, ignore_index=True)
    summary = build_summary(data, markets)

    html_path = Path(output_html) if output_html else resolve_config_path(config, config["output"]["html"])
    csv_path = Path(summary_csv) if summary_csv else resolve_config_path(config, config["output"]["summary_csv"])
    write_plot(data, markets, selected_date, html_path, available_dates=available_dates)
    write_summary_csv(summary, csv_path)

    meta = chart_meta(summary, selected_date, warnings)
    meta["output_html"] = str(html_path)
    meta["summary_csv"] = str(csv_path)
    return meta


def build_history(
    config_path: str | Path | None = None,
    output_html: str | Path | None = None,
    summary_csv: str | Path | None = None,
    strict: bool = False,
) -> dict:
    config = load_config(config_path)
    selected_date = parse_target_date(config.get("date"))
    markets = config["markets"]
    html_path = Path(output_html) if output_html else resolve_config_path(config, config["output"]["html"])
    csv_path = Path(summary_csv) if summary_csv else resolve_config_path(config, config["output"]["summary_csv"])

    current_meta = build(
        config_path=config_path,
        target_date=str(selected_date),
        output_html=html_path,
        summary_csv=csv_path,
        strict=strict,
        allow_fetch=True,
        available_dates=list_cached_dates(config, markets),
    )

    cached_dates = list_cached_dates(config, markets)
    available_dates = sorted(set(cached_dates) | {selected_date})
    date_nav_items = build_date_nav_items(config, markets, available_dates)
    current_meta = build(
        config_path=config_path,
        target_date=str(selected_date),
        output_html=html_path,
        summary_csv=csv_path,
        strict=strict,
        allow_fetch=False,
        available_dates=date_nav_items,
    )

    for cached_date in available_dates:
        dated_html = dated_output_path(html_path, cached_date)
        dated_summary = dated_output_path(csv_path, cached_date)
        build(
            config_path=config_path,
            target_date=str(cached_date),
            output_html=dated_html,
            summary_csv=dated_summary,
            strict=strict,
            allow_fetch=False,
            available_dates=date_nav_items,
        )

    history_csv = resolve_config_path(config, config["output"].get("history_csv", "../site/data/global-rates/global-30y-bond-intraday-history.csv"))
    write_history_manifest(history_csv, date_nav_items)
    current_meta["history_csv"] = str(history_csv)
    current_meta["available_dates"] = date_nav_items
    return current_meta


def fetch_market_with_cache(
    config: dict,
    market: dict,
    target_date: date,
    strict: bool = False,
    refresh_cache: bool = False,
    allow_fetch: bool = True,
) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    cached = read_market_cache(config, market, target_date)
    if not cached.empty and not refresh_cache:
        return cached, warnings
    if not allow_fetch:
        return cached, warnings

    provider_name = market["provider"]
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise ValueError(f"Unsupported provider: {provider_name}")
    try:
        raw = provider(market, target_date, config)
    except Exception as exc:
        if strict or not market.get("optional", False):
            raise
        if not cached.empty:
            warnings.append(f"{market['label']}: provider failed, using cache: {exc}")
            return cached, warnings
        warnings.append(f"{market['label']}: {exc}")
        return pd.DataFrame(columns=["timestamp_utc", "yield_pct", "source"]), warnings

    if raw.empty:
        return cached, warnings
    write_market_cache(config, market, target_date, raw)
    return raw, warnings


def download_range(
    config_path: str | Path | None,
    start_date: date,
    end_date: date,
    refresh_cache: bool = False,
    strict: bool = False,
) -> pd.DataFrame:
    config = load_config(config_path)
    rows: list[dict[str, object]] = []
    current = start_date
    while current <= end_date:
        for market in config["markets"]:
            if should_skip_history_fetch(market, current, end_date, refresh_cache):
                rows.append(download_row(current, market, "skipped_lookback_limit", 0, ""))
                continue
            raw, warnings = fetch_market_with_cache(
                config,
                market,
                current,
                strict=strict,
                refresh_cache=refresh_cache,
                allow_fetch=True,
            )
            status = "ok" if not raw.empty else "missing"
            rows.append(download_row(current, market, status, len(raw), "; ".join(warnings)))
        current += timedelta(days=1)

    report = pd.DataFrame(rows)
    report_path = resolve_config_path(config, "../data/global_30y_bond_intraday/download_report.csv")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(report_path, index=False, encoding="utf-8-sig")
    return report


def should_skip_history_fetch(market: dict, target_date: date, end_date: date, refresh_cache: bool) -> bool:
    if refresh_cache:
        return False
    lookback = market.get("history_lookback_days")
    if not lookback:
        return False
    return target_date < end_date - timedelta(days=int(lookback))


def download_row(target_date: date, market: dict, status: str, rows: int, note: str) -> dict[str, object]:
    return {
        "date": target_date.isoformat(),
        "region": market["region"],
        "label": market["label"],
        "provider": market["provider"],
        "source": market["source_name"],
        "status": status,
        "rows": rows,
        "note": note,
    }


def dated_output_path(html_path: Path, target_date: date) -> Path:
    return html_path.with_name(f"{html_path.stem}-{target_date.isoformat()}{html_path.suffix}")


def build_date_nav_items(config: dict, markets: list[dict], dates: list[date]) -> list[dict[str, object]]:
    max_gap_minutes = int((config.get("fill") or {}).get("max_gap_minutes", 10))
    items: list[dict[str, object]] = []
    for target_date in sorted(dates, reverse=True):
        has_data = False
        for market in markets:
            raw = read_market_cache(config, market, target_date)
            standardized = standardize_market(raw, market, target_date, max_gap_minutes)
            if not standardized.dropna(subset=["yield_pct", "move_bp"]).empty:
                has_data = True
                break
        items.append({"date": target_date.isoformat(), "has_data": has_data})
    return items


def write_history_manifest(path: Path, dates: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in dates:
        if isinstance(item, dict):
            rows.append({"date": item["date"], "has_data": bool(item.get("has_data", True))})
        else:
            rows.append({"date": item.isoformat(), "has_data": True})
    frame = pd.DataFrame(rows).sort_values("date", ascending=False)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build global 30Y sovereign yield intraday chart")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.yaml")
    parser.add_argument("--date", help="UTC date, for example 2026-05-18")
    parser.add_argument("--output-html", help="Output Plotly HTML path")
    parser.add_argument("--summary-csv", help="Output summary CSV path")
    parser.add_argument("--strict", action="store_true", help="Fail on optional provider errors")
    parser.add_argument("--refresh-cache", action="store_true", help="Fetch providers even when cache exists")
    parser.add_argument("--build-history", action="store_true", help="Build current chart and cached date pages")
    parser.add_argument("--download-year", type=int, help="Download available intraday data for a UTC calendar year")
    parser.add_argument("--from-date", help="Range download start date")
    parser.add_argument("--to-date", help="Range download end date")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.download_year or args.from_date:
        if args.download_year:
            start_date = date(args.download_year, 1, 1)
            today = parse_target_date("today")
            end_date = min(date(args.download_year, 12, 31), today)
        else:
            start_date = parse_target_date(args.from_date)
            end_date = parse_target_date(args.to_date or args.from_date)
        report = download_range(args.config, start_date, end_date, refresh_cache=args.refresh_cache, strict=args.strict)
        print(report.groupby(["region", "status"]).size().to_string())
        return 0

    if args.build_history:
        meta = build_history(
            config_path=args.config,
            output_html=args.output_html,
            summary_csv=args.summary_csv,
            strict=args.strict,
        )
    else:
        meta = build(
            config_path=args.config,
            target_date=args.date,
            output_html=args.output_html,
            summary_csv=args.summary_csv,
            strict=args.strict,
            refresh_cache=args.refresh_cache,
        )
    print(f"HTML: {meta['output_html']}")
    print(f"CSV: {meta['summary_csv']}")
    if meta.get("history_csv"):
        print(f"History CSV: {meta['history_csv']}")
    for warning in meta.get("warnings", []):
        print(f"Warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
