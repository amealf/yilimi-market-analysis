from __future__ import annotations

import json
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from http.client import IncompleteRead, RemoteDisconnected
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pandas as pd

from ..transform import convert_yield_to_percent


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"


def fetch(market: dict, target_date, config: dict | None = None) -> pd.DataFrame:
    symbol = market["symbol"]
    start = datetime.combine(target_date, dt_time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    params = urlencode(
        {
            "period1": int(start.timestamp()),
            "period2": int(end.timestamp()),
            "interval": "1m",
            "includePrePost": "true",
            "events": "div,splits",
        }
    )
    url = f"{YAHOO_CHART_URL}/{quote(symbol, safe='')}?{params}"
    payload = request_json(url)
    result = (((payload.get("chart") or {}).get("result") or [None])[0]) if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        error = (payload.get("chart") or {}).get("error") if isinstance(payload, dict) else None
        raise RuntimeError(f"Yahoo returned no chart data for {symbol}: {error}")

    timestamps = result.get("timestamp") or []
    quote_data = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
    closes = quote_data.get("close") or []
    if not timestamps or not closes:
        return pd.DataFrame(columns=["timestamp_utc", "yield_pct", "source"])

    frame = pd.DataFrame({"timestamp": timestamps, "value": closes})
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp"], unit="s", utc=True)
    frame["yield_pct"] = convert_yield_to_percent(frame["value"], market)
    frame["source"] = market["source_name"]
    return frame.dropna(subset=["timestamp_utc", "yield_pct"]).sort_values("timestamp_utc")


def request_json(url: str, retries: int = 3, pause: float = 0.8) -> dict:
    last_error: Exception | None = None
    for attempt in range(retries):
        request = Request(
            url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Connection": "close",
                "User-Agent": "Mozilla/5.0",
            },
        )
        try:
            with urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"HTTP {exc.code}: {detail[:260]}")
            time.sleep(pause * (attempt + 1))
        except (URLError, TimeoutError, IncompleteRead, RemoteDisconnected, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"Yahoo request failed: {url}") from last_error
