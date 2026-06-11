from __future__ import annotations

import json
import time
import http.client
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd

from mobile_chart_support import add_canvas_mobile_support


START_DATE = "2014-01-01"
TWSE_TAIEX = "https://www.twse.com.tw/exchangeReport/FMTQIK"
TWSE_TAIEX_OPENAPI = "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK"
TWSE_MARGIN = "https://www.twse.com.tw/exchangeReport/MI_MARGN"
TWSE_FOREIGN = "https://www.twse.com.tw/fund/BFI82U"
FINMIND_DATA = "https://api.finmindtrade.com/api/v4/data"
YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
USDTWD_YAHOO_SYMBOL = "TWD=X"
TAIEX_YAHOO_SYMBOL = "^TWII"
OUT_DIR = Path(__file__).resolve().parent


def fetch_json(req: Request) -> dict:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            with urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            last_error = exc
            if exc.code in {301, 302, 303, 307, 308}:
                try:
                    return fetch_json_http_client(req.full_url)
                except Exception as fallback_exc:
                    last_error = fallback_exc
                try:
                    return fetch_json_curl(req.full_url)
                except Exception as curl_exc:
                    last_error = curl_exc
                time.sleep(1.2)
                continue
            raise
        except (IncompleteRead, RemoteDisconnected, TimeoutError, URLError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.8)
    raise RuntimeError(f"请求接口失败：{req.full_url}") from last_error


def fetch_json_curl(url: str) -> dict:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-sS",
                    "-L",
                    "--compressed",
                    "-A",
                    (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    url,
                ],
                capture_output=True,
                check=True,
                timeout=60,
            )
            text = result.stdout.decode("utf-8").strip()
            if not text:
                raise RuntimeError("curl 返回空响应")
            return json.loads(text)
        except Exception as exc:
            last_error = exc
            time.sleep(1.2)
    raise RuntimeError(f"curl 请求失败：{url}") from last_error


def fetch_json_http_client(url: str) -> dict:
    current = url
    for _ in range(5):
        parsed = urlparse(current)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        conn = http.client.HTTPSConnection(parsed.netloc, timeout=45)
        try:
            conn.request(
                "GET",
                path,
                headers={
                    "Accept": "application/json,text/plain,*/*",
                    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            )
            resp = conn.getresponse()
            body = resp.read()
            if resp.status in {301, 302, 303, 307, 308}:
                location = resp.getheader("Location")
                if not location:
                    break
                next_url = urljoin(current, location)
                if next_url == current:
                    time.sleep(1.2)
                current = next_url
                continue
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}: {current}")
            return json.loads(body.decode("utf-8"))
        finally:
            conn.close()
    raise RuntimeError(f"重定向无法完成：{url}")


def make_request(url: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    )


def parse_number(value: object) -> float | None:
    text = str(value).replace(",", "").replace("+", "").strip()
    if not text or text == "-":
        return None
    return float(text)


def parse_twse_payload_date(value: object) -> date | None:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return None


def parse_roc_date(value: object) -> date | None:
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) == 7:
        return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7]))
    parts = text.split("/")
    if len(parts) != 3:
        return None
    year, month, day = (int(part) for part in parts)
    if year < 1911:
        year += 1911
    return date(year, month, day)


def month_starts(start: date, end: date) -> list[date]:
    months = []
    current = date(start.year, start.month, 1)
    while current <= end:
        months.append(current)
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return months


def fetch_taiex_month(month_start: date) -> list[dict]:
    params = urlencode({"date": month_start.strftime("%Y%m%d"), "response": "json"})
    payload = fetch_json(make_request(f"{TWSE_TAIEX}?{params}"))
    if payload.get("stat") != "OK":
        return []
    rows = []
    for row in payload.get("data") or []:
        if len(row) < 5:
            continue
        row_date = parse_roc_date(row[0])
        close = parse_number(row[4])
        if row_date is None or close is None:
            continue
        rows.append({"date": row_date, "taiex_close": close})
    return rows


def fetch_taiex() -> pd.DataFrame:
    yahoo = fetch_yahoo_close(TAIEX_YAHOO_SYMBOL, "taiex_close", "TAIEX")
    try:
        recent = fetch_taiex_recent()
    except Exception:
        return yahoo
    return (
        pd.concat([recent, yahoo], ignore_index=True)
        .drop_duplicates(subset=["date"], keep="first")
        .sort_values("date")
        .reset_index(drop=True)
    )


def fetch_taiex_recent(month_count: int = 3) -> pd.DataFrame:
    payload = fetch_json(make_request(TWSE_TAIEX_OPENAPI))
    rows: list[dict] = []
    for row in payload if isinstance(payload, list) else []:
        row_date = parse_roc_date(row.get("Date"))
        close = parse_number(row.get("TAIEX"))
        if row_date is None or close is None:
            continue
        rows.append({"date": row_date, "taiex_close": close})
    if not rows:
        raise RuntimeError("TWSE OpenAPI TAIEX 近期接口没有返回数据")
    return pd.DataFrame(rows).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)


def fetch_margin_for_date(row_date: date) -> dict | None:
    params = urlencode({"date": row_date.strftime("%Y%m%d"), "selectType": "MS", "response": "json"})
    payload = fetch_json(make_request(f"{TWSE_MARGIN}?{params}"))
    if parse_twse_payload_date(payload.get("date")) != row_date:
        return None
    if payload.get("stat") != "OK":
        return None
    for table in payload.get("tables") or []:
        fields = table.get("fields") or []
        if "今日餘額" not in fields:
            continue
        balance_index = fields.index("今日餘額")
        for row in table.get("data") or []:
            if row and row[0] == "融資金額(仟元)" and len(row) > balance_index:
                balance = parse_number(row[balance_index])
                if balance is None:
                    return None
                return {
                    "date": row_date,
                    "margin_financing_thousand_twd": balance,
                    "margin_financing_trillion_twd": balance / 1_000_000_000,
                }
    return None


def fetch_foreign_for_date(row_date: date) -> dict | None:
    params = urlencode({"dayDate": row_date.strftime("%Y%m%d"), "response": "json"})
    payload = fetch_json(make_request(f"{TWSE_FOREIGN}?{params}"))
    if parse_twse_payload_date(payload.get("date")) != row_date:
        return None
    if payload.get("stat") != "OK":
        return None
    for row in payload.get("data") or []:
        if row and row[0] == "外資及陸資(不含外資自營商)" and len(row) >= 4:
            net_buy = parse_number(row[3])
            if net_buy is None:
                return None
            return {
                "date": row_date,
                "foreign_net_buy_twd": net_buy,
                "foreign_net_buy_100m_twd": net_buy / 100_000_000,
            }
    return None


def write_cash_flow_cache(rows: list[dict], cache_path: Path | None) -> None:
    if cache_path is None or not rows:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame = frame.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    frame.to_csv(cache_path, index=False, encoding="utf-8-sig")


def fetch_twse_cash_flow(
    dates: list[date],
    cache: pd.DataFrame | None = None,
    cache_path: Path | None = None,
) -> pd.DataFrame:
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    refresh_start = today - timedelta(days=21)
    cached_dates: set[date] = set()
    if cache is not None and not cache.empty:
        required = {"date", "margin_financing_trillion_twd", "foreign_net_buy_100m_twd"}
        if required.issubset(cache.columns):
            cached_dates = set(
                cache.loc[
                    cache["margin_financing_trillion_twd"].notna()
                    & cache["foreign_net_buy_100m_twd"].notna(),
                    "date",
                ]
            )
    request_dates = [item for item in dates if item >= refresh_start or item not in cached_dates]
    rows: list[dict] = []
    if cache is not None and not cache.empty:
        rows.extend(
            cache.loc[cache["date"].isin(cached_dates - set(request_dates))].to_dict("records")
        )
    if request_dates:
        completed = 0
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = {executor.submit(fetch_cash_flow_for_date, item): item for item in request_dates}
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception:
                    result = None
                if result is not None:
                    rows.append(result)
                    completed += 1
                    if completed % 100 == 0:
                        write_cash_flow_cache(rows, cache_path)
    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
                "margin_financing_thousand_twd",
                "margin_financing_trillion_twd",
                "foreign_net_buy_twd",
                "foreign_net_buy_100m_twd",
            ]
        )
    frame = pd.DataFrame(rows)
    for column in [
        "margin_financing_thousand_twd",
        "margin_financing_trillion_twd",
        "foreign_net_buy_twd",
        "foreign_net_buy_100m_twd",
    ]:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame = frame.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)
    write_cash_flow_cache(frame.to_dict("records"), cache_path)
    return frame


def fetch_cash_flow_for_date(row_date: date) -> dict | None:
    margin = fetch_margin_for_date(row_date)
    foreign = fetch_foreign_for_date(row_date)
    if margin is None and foreign is None:
        return None
    result = {"date": row_date}
    if margin:
        result.update(margin)
    if foreign:
        result.update(foreign)
    return result


def fetch_yahoo_close(symbol: str, column: str, label: str) -> pd.DataFrame:
    start_ts = int(datetime.strptime(START_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    end_ts = int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp())
    params = urlencode({"period1": start_ts, "period2": end_ts, "interval": "1d", "events": "history"})
    req = make_request(f"{YAHOO_CHART_BASE}/{quote(symbol, safe='')}?{params}")
    payload = fetch_json(req)
    error = (payload.get("chart") or {}).get("error")
    if error:
        raise RuntimeError(f"Yahoo Finance {label} 接口返回错误：{error}")
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"Yahoo Finance {label} 接口没有返回数据")
    timestamps = result.get("timestamp") or []
    quote_data = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
    closes = quote_data.get("close") or []
    records = []
    for timestamp, close in zip(timestamps, closes):
        if close is None:
            continue
        records.append({"date": datetime.fromtimestamp(int(timestamp), timezone.utc).date(), column: float(close)})
    if not records:
        raise RuntimeError(f"Yahoo Finance {label} 接口没有可用收盘价")
    return pd.DataFrame(records).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)


def fetch_usdtwd() -> pd.DataFrame:
    return fetch_yahoo_close(USDTWD_YAHOO_SYMBOL, "usdtwd", "USD/TWD")


def fetch_finmind_dataset(dataset: str) -> pd.DataFrame:
    params = urlencode({"dataset": dataset, "start_date": START_DATE})
    payload = fetch_json(make_request(f"{FINMIND_DATA}?{params}"))
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind {dataset} 接口返回错误：{payload.get('msg')}")
    rows = payload.get("data") or []
    if not rows:
        raise RuntimeError(f"FinMind {dataset} 接口没有返回数据")
    data = pd.DataFrame(rows)
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.date
    return data.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def fetch_finmind_margin_financing() -> pd.DataFrame:
    data = fetch_finmind_dataset("TaiwanStockTotalMarginPurchaseShortSale")
    data = data[data["name"] == "MarginPurchaseMoney"].copy()
    data["margin_financing_twd"] = pd.to_numeric(data["TodayBalance"], errors="coerce")
    data["margin_financing_trillion_twd"] = data["margin_financing_twd"] / 1_000_000_000_000
    return (
        data[["date", "margin_financing_twd", "margin_financing_trillion_twd"]]
        .dropna(subset=["margin_financing_twd"])
        .drop_duplicates(subset=["date"])
        .sort_values("date")
        .reset_index(drop=True)
    )


def fetch_finmind_foreign_net_buy() -> pd.DataFrame:
    data = fetch_finmind_dataset("TaiwanStockTotalInstitutionalInvestors")
    data = data[data["name"] == "Foreign_Investor"].copy()
    data["foreign_buy_twd"] = pd.to_numeric(data["buy"], errors="coerce")
    data["foreign_sell_twd"] = pd.to_numeric(data["sell"], errors="coerce")
    data["foreign_net_buy_twd"] = data["foreign_buy_twd"] - data["foreign_sell_twd"]
    data["foreign_net_buy_100m_twd"] = data["foreign_net_buy_twd"] / 100_000_000
    return (
        data[["date", "foreign_net_buy_twd", "foreign_net_buy_100m_twd"]]
        .dropna(subset=["foreign_net_buy_twd"])
        .drop_duplicates(subset=["date"])
        .sort_values("date")
        .reset_index(drop=True)
    )


def read_cache(cache_path: Path | None) -> pd.DataFrame | None:
    if cache_path is None or not cache_path.exists():
        return None
    data = pd.read_csv(cache_path)
    if "date" not in data.columns:
        return None
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.date
    data = data.dropna(subset=["date"])
    return data


def add_index_ratios(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()

    def add_ratio(value_column: str, ratio_column: str) -> None:
        valid = data[value_column].dropna()
        if valid.empty:
            data[ratio_column] = pd.NA
        else:
            base = float(valid.iloc[0])
            data[ratio_column] = data[value_column] / base * 100

    add_ratio("taiex_close", "taiex_ratio")
    add_ratio("usdtwd", "usdtwd_ratio")
    return data


def build_data_frame(cache_path: Path | None = None) -> pd.DataFrame:
    taiex = fetch_taiex()
    financing = fetch_finmind_margin_financing()
    foreign = fetch_finmind_foreign_net_buy()
    usdtwd = fetch_usdtwd()
    data = pd.merge(taiex, financing, on="date", how="left").sort_values("date")
    data = pd.merge(data, foreign, on="date", how="left").sort_values("date")
    data = pd.merge(data, usdtwd, on="date", how="left").sort_values("date")
    data = add_index_ratios(data)
    return data.reset_index(drop=True)


def chart_meta(data: pd.DataFrame) -> dict:
    financing = data.dropna(subset=["margin_financing_trillion_twd"]).copy()
    taiex = data.dropna(subset=["taiex_close", "taiex_ratio"]).copy()
    foreign = data.dropna(subset=["foreign_net_buy_100m_twd"]).copy()
    if financing.empty or taiex.empty or foreign.empty:
        raise RuntimeError("台湾图缺少融资、TAIEX 或外资数据")
    financing_peak = financing.loc[financing["margin_financing_trillion_twd"].idxmax()]
    old_peak_cutoff = financing_peak["date"] - timedelta(days=365)
    old_peak_candidates = financing[financing["date"] <= old_peak_cutoff]
    if old_peak_candidates.empty:
        old_peak_candidates = financing[financing["date"] < financing_peak["date"]]
    old_peak = old_peak_candidates.loc[old_peak_candidates["margin_financing_trillion_twd"].idxmax()]
    new_high_candidates = financing[
        (financing["date"] > old_peak["date"])
        & (financing["margin_financing_trillion_twd"] > old_peak["margin_financing_trillion_twd"])
    ]
    new_high = new_high_candidates.iloc[0] if len(new_high_candidates) else financing_peak
    latest_financing = financing.iloc[-1]
    latest_taiex = taiex.iloc[-1]
    latest_foreign = foreign.iloc[-1]
    latest_dates = [latest_financing["date"], latest_taiex["date"], latest_foreign["date"]]
    latest_fx = data.dropna(subset=["usdtwd"])
    if not latest_fx.empty:
        latest_dates.append(latest_fx.iloc[-1]["date"])

    def nearest_value(date_value: date, column: str, digits: int) -> float | None:
        values = data[(data["date"] <= date_value) & data[column].notna()]
        if values.empty:
            return None
        return round(float(values.iloc[-1][column]), digits)

    return {
        "latestFinancingDate": str(latest_financing["date"]),
        "latestFinancing": round(float(latest_financing["margin_financing_trillion_twd"]), 6),
        "latestTaiexDate": str(latest_taiex["date"]),
        "latestTaiex": round(float(latest_taiex["taiex_close"]), 2),
        "latestTaiexRatio": round(float(latest_taiex["taiex_ratio"]), 4),
        "latestForeignDate": str(latest_foreign["date"]),
        "latestForeignNetBuy": round(float(latest_foreign["foreign_net_buy_100m_twd"]), 2),
        "latestDataDate": str(max(latest_dates)),
        "updatedAt": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M (UTC+8)"),
        "oldPeakDate": str(old_peak["date"]),
        "oldPeak": round(float(old_peak["margin_financing_trillion_twd"]), 6),
        "oldPeakTaiex": nearest_value(old_peak["date"], "taiex_close", 2),
        "newHighDate": str(new_high["date"]),
        "newHigh": round(float(new_high["margin_financing_trillion_twd"]), 6),
        "newHighTaiex": nearest_value(new_high["date"], "taiex_close", 2),
        "financingPeakDate": str(financing_peak["date"]),
        "financingPeak": round(float(financing_peak["margin_financing_trillion_twd"]), 6),
    }


def write_interactive_html(data: pd.DataFrame, output_html: Path) -> None:
    meta = chart_meta(data)

    def value_or_none(value: object, digits: int) -> float | None:
        return None if pd.isna(value) else round(float(value), digits)

    records = []
    for _, row in data.iterrows():
        records.append(
            [
                str(row["date"]),
                value_or_none(row["margin_financing_trillion_twd"], 6),
                value_or_none(row["taiex_close"], 2),
                value_or_none(row["taiex_ratio"], 4),
                value_or_none(row["foreign_net_buy_100m_twd"], 2),
                value_or_none(row["usdtwd"], 4),
                value_or_none(row["usdtwd_ratio"], 4),
            ]
        )
    payload = json.dumps({"data": records, "meta": meta}, ensure_ascii=False, separators=(",", ":"))

    html = """
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TAIEX & Cash flow</title><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#f4f6f8;color:#111827;font-family:"Microsoft YaHei",Arial,sans-serif}.page{position:relative;width:100vw;height:100vh;background:#fff}canvas{display:block;width:100vw;height:100vh}.tip{position:absolute;display:none;pointer-events:none;background:rgba(255,255,255,.42);color:#111827;border:1px solid rgba(255,255,255,.72);border-radius:8px;padding:8px 10px;font-size:12px;line-height:1.65;box-shadow:0 14px 32px rgba(15,23,42,.16);white-space:nowrap;backdrop-filter:blur(16px)}.home-link{position:absolute;left:14px;top:14px;z-index:2;width:32px;height:32px;border:1px solid rgba(120,129,145,.34);border-radius:6px;display:flex;align-items:center;justify-content:center;color:#526071;background:rgba(255,255,255,.72);box-shadow:0 6px 18px rgba(15,23,42,.08);backdrop-filter:blur(2px)}.is-embed .home-link{display:none}.home-link:hover{color:#17202a;background:rgba(255,255,255,.94)}.home-link svg{width:18px;height:18px;stroke:currentColor}</style><script>if(new URLSearchParams(location.search).get("embed")==="1")document.documentElement.classList.add("is-embed");</script></head><body><div class="page"><a class="home-link" href="../../index.html" aria-label="返回主页" title="返回主页"><svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/></svg></a><canvas id="chart"></canvas><div class="tip" id="tip"></div></div><script>
const P=__PAYLOAD__;const rawRows=P.data.map((d,i)=>({i,date:d[0],f:d[1],t:d[2],tr:d[3],nf:d[4],fx:d[5],fxr:d[6]}));const meta=P.meta,canvas=document.getElementById("chart"),ctx=canvas.getContext("2d"),tip=document.getElementById("tip"),isEmbed=new URLSearchParams(location.search).get("embed")==="1";const colors={f:"#e56b2f",tr:"#0086b0",nf:"#16a34a",nfDown:"#dc2626",fx:"#334155",peak:"#7bb8f8",text:"#111827",muted:"#64748b"};let box={},legendHits=[],periodHits=[],visible={f:true,tr:true,nf:true,fx:false,peak:false,notes:new URLSearchParams(location.search).get("notes")==="1"},period="day",hoverPeriod=null,view=null,drag=null,selection=null,xScale,yLeft,yRight,rows=[],plotRows=[];function fmt(v,d=2){return v==null?"-":Number(v).toFixed(d)}function dayLabel(date){return `${date}（${"日一二三四五六"[new Date(`${date}T00:00:00Z`).getUTCDay()]}）`}function periodLabel(){return {day:"日",week:"周",month:"月",quarter:"季"}[period]}function amountLine(v){return v==null?"":`\\n融资 ${fmt(v,3)}万亿新台币`}function taiexLine(v){return v==null?"":`\\nTAIEX ${fmt(v,2)}点`}function quarterKey(t){const d=new Date(t),q=Math.floor(d.getUTCMonth()/3)+1;return `${d.getUTCFullYear()} Q${q}`}function periodKey(r){const d=new Date(`${r.date}T00:00:00Z`);if(period==="day")return r.date;if(period==="week"){const day=d.getUTCDay()||7;d.setUTCDate(d.getUTCDate()+4-day);const yearStart=new Date(Date.UTC(d.getUTCFullYear(),0,1));const week=Math.ceil((((d-yearStart)/86400000)+1)/7);return `${d.getUTCFullYear()}-W${String(week).padStart(2,"0")}`}if(period==="month")return r.date.slice(0,7);return quarterKey(d.getTime())}function groupRows(){if(period==="day")return rawRows.map((r,i)=>({...r,i}));const groups=new Map();rawRows.forEach(r=>{const key=periodKey(r);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r)});const out=[];groups.forEach(group=>{const last=group[group.length-1],nf=group.reduce((sum,r)=>sum+(r.nf==null?0:r.nf),0),hasForeign=group.some(r=>r.nf!=null);out.push({...last,nf:hasForeign?nf:null})});return out.map((r,i)=>({...r,i}))}function refreshRows(){rows=groupRows();plotRows=rows}function dataDomain(){const a=0,b=rows.length-1,pad=Math.max(1,(b-a)*.045);return[a-pad,b+pad]}function values(k,source=plotRows){return source.map(r=>r[k]).filter(v=>v!=null&&Number.isFinite(v))}function extent(keys,source=plotRows){const a=keys.flatMap(k=>values(k,source));return a.length?[Math.min(...a),Math.max(...a)]:[0,1]}function niceTicks(min,max,n){const span=Math.max(1e-9,max-min),raw=span/Math.max(1,n),pow=Math.pow(10,Math.floor(Math.log10(raw))),base=[1,2,5,10].find(x=>x*pow>=raw)*pow,start=Math.ceil(min/base)*base,out=[];for(let v=start;v<=max+base*.5;v+=base)out.push(v);return out}function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}function rowByDate(date){return rows.find(r=>r.date===date)}function textBox(text,x,y,align="left"){const lines=text.split("\\n"),padX=12,padY=5,lh=16,extra=18,w=Math.max(...lines.map(s=>ctx.measureText(s).width))+padX*2+extra,h=lines.length*lh+padY*2;let bx=align==="right"?x-w:x;ctx.save();ctx.shadowColor="rgba(15,23,42,.16)";ctx.shadowBlur=18;ctx.shadowOffsetY=8;ctx.fillStyle="rgba(255,255,255,.42)";ctx.strokeStyle="rgba(255,255,255,.76)";ctx.lineWidth=.9;ctx.beginPath();ctx.roundRect(bx,y,w,h,8);ctx.fill();ctx.shadowBlur=0;ctx.stroke();ctx.restore();ctx.fillStyle="rgba(15,23,42,.94)";ctx.textAlign="left";lines.forEach((s,i)=>ctx.fillText(s,bx+padX,y+padY+12+i*lh))}function inRange(date){const r=rowByDate(date);return r&&r.i>=box.imin&&r.i<=box.imax}function drawLabel(p,text,dx,dy,color,side){if(!visible.notes||period!=="day"||!inRange(p.date))return;const r=rowByDate(p.date),x=xScale(r.i),y=side==="left"?yLeft(p.value):yRight(p.value);ctx.strokeStyle="#64748b";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+dx,y+dy);ctx.stroke();ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill();textBox(text,x+dx+(dx<0?-6:6),y+dy-20,dx<0?"right":"left")}function roundRect(x,y,w,h,r){const rr=Math.min(r,w/2,h/2);ctx.beginPath();ctx.moveTo(x+rr,y);ctx.lineTo(x+w-rr,y);ctx.quadraticCurveTo(x+w,y,x+w,y+rr);ctx.lineTo(x+w,y+h-rr);ctx.quadraticCurveTo(x+w,y+h,x+w-rr,y+h);ctx.lineTo(x+rr,y+h);ctx.quadraticCurveTo(x,y+h,x,y+h-rr);ctx.lineTo(x,y+rr);ctx.quadraticCurveTo(x,y,x+rr,y)}function drawPeriodTabs(x,y){periodHits=[];[["day","日"],["week","周"],["month","月"],["quarter","季"]].forEach(([key,label],i)=>{const w=38,h=24,left=x+i*(w+6),active=period===key,hovered=hoverPeriod===key;periodHits.push({key,x0:left,y0:y,x1:left+w,y1:y+h});ctx.strokeStyle=active?"#60a5fa":hovered?"#93c5fd":"rgba(71,85,105,.42)";ctx.lineWidth=active||hovered?1.35:.9;roundRect(left,y,w,h,7);ctx.stroke();ctx.fillStyle=hovered||active?"#17202a":"rgba(71,85,105,.58)";ctx.textAlign="center";ctx.font="12px Microsoft YaHei,Arial";ctx.fillText(label,left+w/2,y+16)});ctx.lineWidth=1}function periodAt(x,y){return periodHits.find(h=>x>=h.x0&&x<=h.x1&&y>=h.y0&&y<=h.y1)}function drawForeignBars(x0,x1,y0,y1){if(!visible.nf)return;const nums=values("nf");if(!nums.length)return;const maxAbs=Math.max(...nums.map(v=>Math.abs(v)));if(!maxAbs)return;const zero=y0-(y0-y1)*.17,band=(y0-y1)*.13,step=Math.abs(xScale(Math.min(box.imax,box.imin+1))-xScale(box.imin))||1,bw=Math.max(1,Math.min(period==="day"?5:12,step*.72));ctx.strokeStyle="rgba(71,85,105,.38)";ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(x0,zero);ctx.lineTo(x1,zero);ctx.stroke();for(const r of rows){if(r.i<box.imin||r.i>box.imax||r.nf==null)continue;const x=xScale(r.i),y=zero-(r.nf/maxAbs)*band;ctx.fillStyle=r.nf>=0?"rgba(22,163,74,.34)":"rgba(220,38,38,.30)";ctx.fillRect(x-bw/2,Math.min(y,zero),bw,Math.max(1,Math.abs(y-zero)))}ctx.fillStyle=colors.muted;ctx.textAlign="left";ctx.font="12px Microsoft YaHei,Arial";ctx.fillText("外资净买入（亿新台币）",x0+8,zero-6)}function draw(active){refreshRows();const w=canvas.clientWidth,h=canvas.clientHeight,compact=w<760,p={l:96,r:106,t:compact?132:98,b:76},x0=p.l,x1=w-p.r,y0=h-p.b,y1=p.t,[fullMin,fullMax]=dataDomain(),imin=view?view[0]:fullMin,imax=view?view[1]:fullMax;plotRows=rows.filter(r=>r.i>=imin&&r.i<=imax);if(!plotRows.length)plotRows=rows;ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);ctx.font="12px Microsoft YaHei,Arial";const rKeys=["tr"];if(visible.fx)rKeys.push("fxr");const [fMin0,fMax0]=extent(["f"]),[rMin0,rMax0]=extent(rKeys);const fPad=Math.max(.02,(fMax0-fMin0)*.06),fMin=Math.min(0,fMin0-fPad),fMax=Math.max(fMax0,meta.oldPeak,meta.newHigh)+fPad,rMin=Math.max(0,rMin0*.9),rMax=rMax0*1.08;box={x0,x1,y0,y1,imin,imax,fMin,fMax,rMin,rMax};xScale=i=>x0+(i-imin)/(imax-imin)*(x1-x0);yLeft=v=>y0-(v-fMin)/(fMax-fMin)*(y0-y1);yRight=v=>y0-(v-rMin)/(rMax-rMin)*(y0-y1);ctx.fillStyle=colors.text;ctx.font="700 22px Microsoft YaHei,Arial";ctx.textAlign="center";ctx.fillText("TAIEX & Cash flow",w/2,32);const tabX=compact?x0:x1-170,tabY=compact?64:20;if(isEmbed){periodHits=[]}else{drawPeriodTabs(tabX,tabY)}drawLegend(x0,58);ctx.font="12px Microsoft YaHei,Arial";ctx.lineWidth=.6;niceTicks(fMin,fMax,6).forEach(v=>{const y=yLeft(v);ctx.strokeStyle="#e5e7eb";ctx.beginPath();ctx.moveTo(x0,y);ctx.lineTo(x1,y);ctx.stroke();ctx.fillStyle=colors.f;ctx.textAlign="right";ctx.fillText(v.toFixed(2),x0-9,y+4)});niceTicks(rMin,rMax,6).forEach(v=>{const y=yRight(v);ctx.fillStyle="#111";ctx.textAlign="left";ctx.fillText(Math.round(v),x1+9,y+4)});let seenYear=null;for(const r of rows){if(r.i<imin||r.i>imax)continue;const year=r.date.slice(0,4);if(year===seenYear)continue;seenYear=year;const x=xScale(r.i);ctx.strokeStyle="#eef2f7";ctx.beginPath();ctx.moveTo(x,y1);ctx.lineTo(x,y0);ctx.stroke();ctx.fillStyle="#4b5563";ctx.textAlign="center";ctx.fillText(year,x,y0+24)}ctx.strokeStyle="#111827";ctx.lineWidth=1;ctx.strokeRect(x0,y1,x1-x0,y0-y1);drawForeignBars(x0,x1,y0,y1);function path(key,color,width,scale,visibleKey=key){if(!visible[visibleKey])return;ctx.beginPath();let open=false;for(const r of rows){const v=r[key];if(v==null||r.i<imin||r.i>imax){open=false;continue}const x=xScale(r.i),y=scale(v);if(!open){ctx.moveTo(x,y);open=true}else ctx.lineTo(x,y)}ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke()}path("f",colors.f,1.18,yLeft);path("tr",colors.tr,1.0,yRight);path("fxr",colors.fx,.95,yRight,"fx");if(visible.peak){const py=yLeft(meta.oldPeak);ctx.setLineDash([6,4]);ctx.strokeStyle=colors.peak;ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x0,py);ctx.lineTo(x1,py);ctx.stroke();ctx.setLineDash([])}ctx.save();ctx.translate(42,(y0+y1)/2);ctx.rotate(-Math.PI/2);ctx.fillStyle=colors.f;ctx.textAlign="center";ctx.fillText("融资余额（万亿新台币）",0,0);ctx.restore();ctx.save();ctx.translate(w-48,(y0+y1)/2);ctx.rotate(Math.PI/2);ctx.fillStyle="#111";ctx.textAlign="center";ctx.fillText("相对值（2014-01=100）",0,0);ctx.restore();if(visible.f&&visible.peak)drawLabel({date:meta.oldPeakDate,value:meta.oldPeak},`融资旧高\\n${meta.oldPeakDate}\\n融资 ${fmt(meta.oldPeak,3)}万亿新台币${taiexLine(meta.oldPeakTaiex)}`,34,30,colors.f,"left");if(visible.f&&meta.newHighDate!==meta.oldPeakDate)drawLabel({date:meta.newHighDate,value:meta.newHigh},`融资突破旧高\\n${meta.newHighDate}\\n融资 ${fmt(meta.newHigh,3)}万亿新台币${taiexLine(meta.newHighTaiex)}`,-34,-54,colors.f,"left");ctx.fillStyle=colors.muted;ctx.textAlign="left";ctx.font="12px Microsoft YaHei,Arial";if(!isEmbed){ctx.fillStyle="#cbd5e1";ctx.textAlign="right";ctx.fillText("Made by Yilimi",x1,y0+46);ctx.fillStyle="#4b5563";ctx.textAlign="left";ctx.fillText(`更新时间：${meta.updatedAt}；数据源：TWSE、Yahoo Finance。`,x0,y0+64)}if(active!=null){const r=rows[active],x=xScale(r.i);ctx.strokeStyle="rgba(31,41,55,.42)";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y1);ctx.lineTo(x,y0);ctx.stroke();[[r.f,yLeft,colors.f,"f"],[r.tr,yRight,colors.tr,"tr"],[r.fxr,yRight,colors.fx,"fx"]].forEach(([v,scale,color,key])=>{if(visible[key]&&v!=null){ctx.fillStyle="#fff";ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,scale(v),3.2,0,Math.PI*2);ctx.fill();ctx.stroke()}})}if(selection){const x0s=clamp(selection.x0,box.x0,box.x1),x1s=clamp(selection.x1,box.x0,box.x1),left=Math.min(x0s,x1s),width=Math.abs(x1s-x0s);if(width>=3){ctx.fillStyle="rgba(111,74,168,.10)";ctx.strokeStyle="rgba(111,74,168,.55)";ctx.lineWidth=1;ctx.setLineDash([4,3]);ctx.fillRect(left,box.y1,width,box.y0-box.y1);ctx.strokeRect(left,box.y1,width,box.y0-box.y1);ctx.setLineDash([])}}}function drawLegend(x,y){legendHits=[];const items=[{key:"f",color:colors.f,label:"融资余额"},{key:"tr",color:colors.tr,label:"TAIEX 相对值"},{key:"nf",color:colors.nf,label:"外资净买入"},{key:"fx",color:colors.fx,label:"USD/TWD 相对值"},{key:"peak",color:colors.peak,label:"融资旧高",dash:true},{key:"notes",color:"#94a3b8",label:"文字注释"}].filter(item=>!isEmbed||visible[item.key]);ctx.font="13px Microsoft YaHei,Arial";let cur=x;items.forEach(item=>{const textW=ctx.measureText(item.label).width,w=textW+46;legendHits.push({key:item.key,x:cur-4,y:y-14,w:w+8,h:26});ctx.globalAlpha=visible[item.key]?1:.28;ctx.strokeStyle=item.color;ctx.lineWidth=item.dash?.8:2;ctx.setLineDash(item.dash?[6,4]:[]);ctx.beginPath();ctx.moveTo(cur,y);ctx.lineTo(cur+28,y);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle="#374151";ctx.textAlign="left";ctx.fillText(item.label,cur+36,y+4);ctx.globalAlpha=1;cur+=w+24})}function legendAt(x,y){return legendHits.find(h=>x>=h.x&&x<=h.x+h.w&&y>=h.y&&y<=h.y+h.h)}function inPlot(x,y){return x>=box.x0&&x<=box.x1&&y>=box.y1&&y<=box.y0}function clamp(v,a,b){return Math.max(a,Math.min(b,v))}function indexAtX(x){return box.imin+(x-box.x0)/(box.x1-box.x0)*(box.imax-box.imin)}function nearest(mx){let idx=Math.round(indexAtX(mx));idx=Math.max(0,Math.min(rows.length-1,idx));return idx}canvas.addEventListener("mousedown",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(periodAt(x,y)||legendAt(x,y)||!inPlot(x,y))return;drag={x0:x,x1:x};selection=null;tip.style.display="none";canvas.style.cursor="crosshair"});window.addEventListener("mouseup",e=>{if(!drag)return;const rect=canvas.getBoundingClientRect(),x=clamp(e.clientX-rect.left,box.x0,box.x1);drag.x1=x;const width=Math.abs(drag.x1-drag.x0);if(width>12){const a=Math.min(drag.x0,drag.x1),b=Math.max(drag.x0,drag.x1);view=[indexAtX(a),indexAtX(b)]}drag=null;selection=null;canvas.style.cursor="default";tip.style.display="none";draw()});canvas.addEventListener("dblclick",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(inPlot(x,y)){view=null;selection=null;tip.style.display="none";draw()}});canvas.addEventListener("click",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top,tab=periodAt(x,y);if(tab){period=tab.key;hoverPeriod=tab.key;view=null;tip.style.display="none";draw();return}const hit=legendAt(x,y);if(hit){visible[hit.key]=!visible[hit.key];tip.style.display="none";draw()}});canvas.addEventListener("mousemove",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(drag){drag.x1=clamp(x,box.x0,box.x1);selection=drag;tip.style.display="none";draw();return}const tab=periodAt(x,y),hit=legendAt(x,y);canvas.style.cursor=(tab||hit)?"pointer":inPlot(x,y)?"crosshair":"default";if(tab){hoverPeriod=tab.key;tip.style.display="none";draw();return}if(hoverPeriod){hoverPeriod=null;draw()}if(hit){tip.style.display="none";draw();return}if(!inPlot(x,y)){tip.style.display="none";draw();return}const i=nearest(x),r=rows[i];draw(i);tip.innerHTML=`<b>${dayLabel(r.date)}　${periodLabel()}</b><br>融资余额：${fmt(r.f,3)} 万亿新台币<br>TAIEX：${fmt(r.t,2)} 点，相对值 ${fmt(r.tr,2)}${visible.fx&&r.fx!=null?`<br>USD/TWD：${fmt(r.fx,2)}，相对值 ${fmt(r.fxr,2)}`:""}<br>外资净买入：${fmt(r.nf,0)} 亿新台币`;tip.style.display="block";tip.style.left=Math.min(rect.width-300,Math.max(8,x+14))+"px";tip.style.top=Math.max(8,y-72)+"px"});canvas.addEventListener("mouseleave",()=>{if(drag)return;selection=null;hoverPeriod=null;tip.style.display="none";canvas.style.cursor="default";draw()});refreshRows();window.addEventListener("resize",resize);resize();
</script></body></html>
"""
    html = html.replace("数据源：TWSE、Yahoo Finance。", "数据源：FinMind、TWSE、Yahoo Finance。")
    html = html.replace("__PAYLOAD__", payload)
    html = "".join(line.strip() for line in html.splitlines())
    html = add_canvas_mobile_support(html)
    output_html.write_text(html, encoding="utf-8")


def main() -> int:
    data = build_data_frame()
    csv_path = OUT_DIR / "taiwan_margin_taiex_data.csv"
    html_path = OUT_DIR / "taiwan_margin_taiex.html"
    data.to_csv(csv_path, index=False, encoding="utf-8-sig")
    write_interactive_html(data, html_path)
    print(f"CSV: {csv_path}")
    print(f"HTML: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
