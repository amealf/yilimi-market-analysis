from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    config_path = config_path.resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    config["_config_path"] = config_path
    config["_config_dir"] = config_path.parent
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    markets = config.get("markets")
    if not isinstance(markets, list) or not markets:
        raise ValueError("config.yaml must define at least one market")

    required = {"region", "label", "provider", "source_name", "timezone", "local_open"}
    for market in markets:
        missing = sorted(required - set(market))
        if missing:
            label = market.get("label", "unknown")
            raise ValueError(f"{label} is missing config keys: {', '.join(missing)}")


def parse_target_date(value: str | date | None) -> date:
    if value is None or value == "today":
        return datetime.now(timezone.utc).date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def resolve_config_path(config: dict[str, Any], path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (config["_config_dir"] / path).resolve()
