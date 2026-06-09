from __future__ import annotations

import asyncio
import json
import random
import string
import time
from datetime import datetime, timezone

import pandas as pd


TRADINGVIEW_SOCKET_URL = "wss://data.tradingview.com/socket.io/websocket"


def fetch(market: dict, config: dict | None = None) -> pd.DataFrame:
    history = (config or {}).get("history") or {}
    bar_count = int(history.get("bar_count", 5000))
    interval = str(history.get("interval", "1D"))
    try:
        return asyncio.run(fetch_async(market["symbol"], bar_count, interval))
    except RuntimeError as exc:
        if "asyncio.run" not in str(exc):
            raise
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(fetch_async(market["symbol"], bar_count, interval))
        finally:
            loop.close()


async def fetch_async(symbol: str, bar_count: int, interval: str = "1D") -> pd.DataFrame:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("websockets package is required for TradingView daily data") from exc

    async with websockets.connect(
        TRADINGVIEW_SOCKET_URL,
        extra_headers={"Origin": "https://www.tradingview.com", "User-Agent": "Mozilla/5.0"},
        open_timeout=20,
        close_timeout=5,
    ) as websocket:
        session = "cs_" + "".join(random.choice(string.ascii_lowercase) for _ in range(12))
        await send(websocket, "set_auth_token", ["unauthorized_user_token"])
        await send(websocket, "chart_create_session", [session, ""])
        await send(websocket, "switch_timezone", [session, "Etc/UTC"])
        symbol_payload = json.dumps(
            {"symbol": symbol, "adjustment": "splits", "session": "regular"},
            separators=(",", ":"),
        )
        await send(websocket, "resolve_symbol", [session, "symbol_1", "=" + symbol_payload])
        await send(websocket, "create_series", [session, "s1", "s1", "symbol_1", interval, bar_count, ""])

        deadline = time.time() + 45
        while time.time() < deadline:
            message = await asyncio.wait_for(websocket.recv(), timeout=45)
            for payload in decode_messages(str(message)):
                if isinstance(payload, dict) and payload.get("m") == "timescale_update":
                    return parse_timescale_update(payload)
                if isinstance(payload, dict) and payload.get("m") == "critical_error":
                    raise RuntimeError(f"TradingView critical error for {symbol}: {payload}")
    raise RuntimeError(f"TradingView request timed out for {symbol}")


async def send(websocket, method: str, params: list) -> None:
    payload = json.dumps({"m": method, "p": params}, separators=(",", ":"))
    await websocket.send(f"~m~{len(payload)}~m~{payload}")


def decode_messages(raw: str) -> list[object]:
    payloads: list[object] = []
    position = 0
    while True:
        start = raw.find("~m~", position)
        if start < 0:
            break
        length_start = start + 3
        length_end = raw.find("~m~", length_start)
        if length_end < 0:
            break
        try:
            size = int(raw[length_start:length_end])
        except ValueError:
            position = length_end + 3
            continue
        payload_start = length_end + 3
        payload = raw[payload_start : payload_start + size]
        position = payload_start + size
        try:
            payloads.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return payloads


def parse_timescale_update(payload: dict) -> pd.DataFrame:
    series = (((payload.get("p") or [None, {}])[1]).get("s1") or {}).get("s") or []
    mark_dates = parse_mark_dates(payload)
    rows: list[dict[str, object]] = []
    for item in series:
        values = item.get("v") or []
        if len(values) < 5:
            continue
        timestamp = datetime.fromtimestamp(float(values[0]), tz=timezone.utc)
        trade_date = mark_dates.get(item.get("i"), timestamp.date())
        rows.append(
            {
                "date": trade_date,
                "timestamp": timestamp,
                "open": values[1],
                "high": values[2],
                "low": values[3],
                "close": values[4],
            }
        )
    return pd.DataFrame(rows).sort_values("date")


def parse_mark_dates(payload: dict) -> dict[int, object]:
    metadata = (payload.get("p") or [None, None, {}])[2]
    marks = metadata.get("marks") if isinstance(metadata, dict) else []
    dates = {}
    for mark in marks or []:
        if len(mark) < 3:
            continue
        dates[int(mark[2])] = datetime.fromtimestamp(float(mark[1]), tz=timezone.utc).date()
    return dates
