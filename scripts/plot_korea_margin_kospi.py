from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from html import unescape
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd

from mobile_chart_support import add_canvas_mobile_support


START_DATE = "2014-01-01"
KOFIA_DATA = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
NAVER_INVESTOR_TREND = "https://finance.naver.com/sise/investorDealTrendDay.naver"
NAVER_INDEX_DAY = "https://finance.naver.com/sise/sise_index_day.naver"
YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
KOSPI_YAHOO_SYMBOL = "^KS11"
USDKRW_YAHOO_SYMBOL = "KRW=X"
KOREA_10Y_TRADINGVIEW_SYMBOL = "TVC:KR10Y"
OUT_DIR = Path(__file__).resolve().parent


def fetch_json(req: Request) -> dict:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            with urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (IncompleteRead, RemoteDisconnected, TimeoutError, URLError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.8)
    raise RuntimeError(f"请求接口失败：{req.full_url}") from last_error


def fetch_text(req: Request, encoding: str) -> str:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            with urlopen(req, timeout=45) as resp:
                return resp.read().decode(encoding, errors="replace")
        except (IncompleteRead, RemoteDisconnected, TimeoutError, URLError, OSError) as exc:
            last_error = exc
            time.sleep(0.8)
    raise RuntimeError(f"请求接口失败：{req.full_url}") from last_error


def parse_number(value: str) -> int | None:
    value = value.replace(",", "").replace("+", "").strip()
    if not value or value == "-":
        return None
    return int(value)


def parse_float(value: str) -> float | None:
    value = value.replace(",", "").replace("+", "").strip()
    if not value or value == "-":
        return None
    return float(value)


def clean_cell(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return unescape(value).strip()


def parse_naver_investor_rows(content: str) -> list[dict]:
    rows = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", content, flags=re.S):
        cells = [clean_cell(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.S)]
        if len(cells) < 3 or not re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", cells[0]):
            continue
        yy, mm, dd = (int(part) for part in cells[0].split("."))
        row_date = date(2000 + yy, mm, dd)
        foreign_value = parse_number(cells[2])
        if foreign_value is None:
            continue
        rows.append({"date": row_date, "foreign_net_buy_100m_krw": foreign_value})
    return rows


def fetch_naver_investor_page(bizdate: str, page: int) -> list[dict]:
    params = urlencode({"bizdate": bizdate, "sosok": "01", "page": page})
    req = Request(
        f"{NAVER_INVESTOR_TREND}?{params}",
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://finance.naver.com/sise/sise_index.naver?code=KOSPI",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    )
    return parse_naver_investor_rows(fetch_text(req, "euc-kr"))


def fetch_naver_investor_pages(bizdate: str, page_numbers: list[int]) -> list[list[dict]]:
    batch_rows: list[list[dict] | None] = [None] * len(page_numbers)
    failed_pages: list[tuple[int, int]] = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(fetch_naver_investor_page, bizdate, page_number)
            for page_number in page_numbers
        ]
        for index, future in enumerate(futures):
            try:
                batch_rows[index] = future.result()
            except Exception:
                failed_pages.append((index, page_numbers[index]))

    for index, page_number in failed_pages:
        time.sleep(0.4)
        batch_rows[index] = fetch_naver_investor_page(bizdate, page_number)

    return [page_rows or [] for page_rows in batch_rows]


def fetch_foreign_net_buy() -> pd.DataFrame:
    start_date = pd.to_datetime(START_DATE).date()
    bizdate = date.today().strftime("%Y%m%d")
    rows: list[dict] = []
    seen_dates: set[date] = set()
    page = 1
    batch_size = 24

    while True:
        page_numbers = list(range(page, page + batch_size))
        batch_rows = fetch_naver_investor_pages(bizdate, page_numbers)

        if not any(batch_rows):
            break

        oldest = date.today()
        for page_rows in batch_rows:
            for row in page_rows:
                oldest = min(oldest, row["date"])
                if row["date"] not in seen_dates:
                    rows.append(row)
                    seen_dates.add(row["date"])

        if oldest < start_date:
            break

        page += batch_size
        if page > 700:
            break

    if not rows:
        raise RuntimeError("Naver Finance 外国人净买入接口没有返回数据")

    df = pd.DataFrame(rows)
    df = df[df["date"] >= start_date].copy()
    df["foreign_net_buy_trillion_krw"] = df["foreign_net_buy_100m_krw"] / 10_000
    return df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)


def fetch_credit_financing_balance() -> pd.DataFrame:
    end_date = date.today().strftime("%Y%m%d")
    body = json.dumps(
        {
            "dmSearch": {
                "tmpV40": "1000000",
                "tmpV41": "1",
                "tmpV1": "D",
                "tmpV45": START_DATE.replace("-", ""),
                "tmpV46": end_date,
                "OBJ_NM": "STATSCU0100000070BO",
            }
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    req = Request(
        KOFIA_DATA,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Content-Type": "application/json; charset=UTF-8",
            "Origin": "https://freesis.kofia.or.kr",
            "Referer": (
                "https://freesis.kofia.or.kr/stat/FreeSIS.do"
                "?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000070"
            ),
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    )
    payload = fetch_json(req)
    rows = payload.get("ds1") or []
    if not rows:
        raise RuntimeError("KOFIA FreeSIS 信用交易融资余额接口没有返回数据")

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["TMPV1"], format="%Y%m%d").dt.date
    df["credit_financing_million_krw"] = pd.to_numeric(df["TMPV2"], errors="coerce")
    df["credit_financing_kospi_million_krw"] = pd.to_numeric(df["TMPV3"], errors="coerce")
    df["credit_financing_kosdaq_million_krw"] = pd.to_numeric(df["TMPV4"], errors="coerce")
    df["credit_financing_trillion_krw"] = df["credit_financing_million_krw"] / 1_000_000
    return (
        df[
            [
                "date",
                "credit_financing_million_krw",
                "credit_financing_kospi_million_krw",
                "credit_financing_kosdaq_million_krw",
                "credit_financing_trillion_krw",
            ]
        ]
        .dropna(subset=["credit_financing_million_krw"])
        .drop_duplicates(subset=["date"])
        .sort_values("date")
        .reset_index(drop=True)
    )


def fetch_yahoo_close(symbol: str, column: str, label: str) -> pd.DataFrame:
    start_ts = int(datetime.strptime(START_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    end_ts = int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp())
    params = urlencode(
        {
            "period1": start_ts,
            "period2": end_ts,
            "interval": "1d",
            "events": "history",
        }
    )
    req = Request(
        f"{YAHOO_CHART_BASE}/{quote(symbol, safe='')}?{params}",
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    )
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
        records.append(
            {
                "date": datetime.fromtimestamp(int(timestamp), timezone.utc).date(),
                column: float(close),
            }
        )
    if not records:
        raise RuntimeError(f"Yahoo Finance {label} 接口没有可用收盘价")

    return pd.DataFrame(records).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)


def parse_naver_kospi_rows(content: str) -> list[dict]:
    rows = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", content, flags=re.S):
        cells = [clean_cell(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.S)]
        if len(cells) < 2 or not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", cells[0]):
            continue
        row_date = datetime.strptime(cells[0], "%Y.%m.%d").date()
        close = parse_float(cells[1])
        if close is None:
            continue
        rows.append({"date": row_date, "kospi_close": close})
    return rows


def fetch_naver_kospi_page(page: int) -> list[dict]:
    params = urlencode({"code": "KOSPI", "page": page})
    req = Request(
        f"{NAVER_INDEX_DAY}?{params}",
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://finance.naver.com/sise/sise_index.naver?code=KOSPI",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    )
    return parse_naver_kospi_rows(fetch_text(req, "euc-kr"))


def fetch_naver_kospi_recent(page_count: int = 8) -> pd.DataFrame:
    rows: list[dict] = []
    for page in range(1, page_count + 1):
        rows.extend(fetch_naver_kospi_page(page))
    if not rows:
        raise RuntimeError("Naver Finance KOSPI 接口没有返回数据")
    return pd.DataFrame(rows).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)


def fetch_kospi() -> pd.DataFrame:
    yahoo = fetch_yahoo_close(KOSPI_YAHOO_SYMBOL, "kospi_close", "KOSPI")
    try:
        naver = fetch_naver_kospi_recent()
    except Exception:
        return yahoo
    return (
        pd.concat([naver, yahoo], ignore_index=True)
        .drop_duplicates(subset=["date"], keep="first")
        .sort_values("date")
        .reset_index(drop=True)
    )



def fetch_usdkrw() -> pd.DataFrame:
    return fetch_yahoo_close(USDKRW_YAHOO_SYMBOL, "usdkrw", "USD/KRW")


def fetch_korea_10y_yield() -> pd.DataFrame:
    root_dir = Path(__file__).resolve().parents[1]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))
    from global_30y_bond_daily.providers import tradingview_provider

    raw = tradingview_provider.fetch(
        {"symbol": KOREA_10Y_TRADINGVIEW_SYMBOL, "label": "韩国10年国债收益率"},
        {"history": {"bar_count": 5000}},
    )
    if raw.empty:
        raise RuntimeError("TradingView 韩国10年国债收益率接口没有返回数据")
    frame = raw[["date", "close"]].rename(columns={"close": "korea_10y_yield"}).copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    return frame.dropna(subset=["date", "korea_10y_yield"]).sort_values("date").reset_index(drop=True)


def add_index_ratios(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()

    def add_ratio(value_column: str, ratio_column: str) -> None:
        valid = data[value_column].dropna()
        if valid.empty:
            data[ratio_column] = pd.NA
        else:
            base = float(valid.iloc[0])
            data[ratio_column] = data[value_column] / base * 100

    add_ratio("kospi_close", "kospi_ratio")
    add_ratio("korea_10y_yield", "korea_10y_yield_ratio")
    add_ratio("usdkrw", "usdkrw_ratio")
    data["foreign_net_buy_cumulative_trillion_krw"] = (
        data["foreign_net_buy_trillion_krw"].fillna(0).cumsum()
    )
    return data


def chart_meta(data: pd.DataFrame) -> dict:
    financing = data.dropna(subset=["credit_financing_trillion_krw"]).copy()
    kospi = data.dropna(subset=["kospi_close", "kospi_ratio"]).copy()
    financing_peak = financing.loc[financing["credit_financing_trillion_krw"].idxmax()]
    old_peak_cutoff = financing_peak["date"] - timedelta(days=365)
    old_peak_candidates = financing[financing["date"] <= old_peak_cutoff]
    if old_peak_candidates.empty:
        old_peak_candidates = financing[financing["date"] < financing_peak["date"]]
    old_peak = old_peak_candidates.loc[old_peak_candidates["credit_financing_trillion_krw"].idxmax()]
    new_high_candidates = financing[
        (financing["date"] > old_peak["date"])
        & (financing["credit_financing_trillion_krw"] > old_peak["credit_financing_trillion_krw"])
    ]
    new_high = new_high_candidates.iloc[0] if len(new_high_candidates) else financing_peak
    latest_financing = financing.iloc[-1]
    latest_kospi = kospi.iloc[-1]
    latest_foreign = data.dropna(subset=["foreign_net_buy_100m_krw"]).iloc[-1]
    latest_dates = [latest_financing["date"], latest_kospi["date"], latest_foreign["date"]]
    for column in ["korea_10y_yield", "usdkrw"]:
        latest_optional = data.dropna(subset=[column])
        if not latest_optional.empty:
            latest_dates.append(latest_optional.iloc[-1]["date"])
    latest_data_date = max(latest_dates)

    def nearest_value(date_value: date, column: str, digits: int) -> float | None:
        values = data[(data["date"] <= date_value) & data[column].notna()]
        if values.empty:
            return None
        return round(float(values.iloc[-1][column]), digits)

    return {
        "latestFinancingDate": str(latest_financing["date"]),
        "latestFinancing": round(float(latest_financing["credit_financing_trillion_krw"]), 6),
        "latestKospiDate": str(latest_kospi["date"]),
        "latestKospi": round(float(latest_kospi["kospi_close"]), 2),
        "latestKospiRatio": round(float(latest_kospi["kospi_ratio"]), 4),
        "latestForeignDate": str(latest_foreign["date"]),
        "latestForeignNetBuy": round(float(latest_foreign["foreign_net_buy_100m_krw"]), 2),
        "latestForeignCumulative": round(
            float(latest_foreign["foreign_net_buy_cumulative_trillion_krw"]), 6
        ),
        "latestDataDate": str(latest_data_date),
        "updatedAt": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M (UTC+8)"),
        "oldPeakDate": str(old_peak["date"]),
        "oldPeak": round(float(old_peak["credit_financing_trillion_krw"]), 6),
        "oldPeakKospi": nearest_value(old_peak["date"], "kospi_close", 2),
        "oldPeakForeignCumulative": nearest_value(
            old_peak["date"], "foreign_net_buy_cumulative_trillion_krw", 6
        ),
        "newHighDate": str(new_high["date"]),
        "newHigh": round(float(new_high["credit_financing_trillion_krw"]), 6),
        "newHighKospi": nearest_value(new_high["date"], "kospi_close", 2),
        "newHighForeignCumulative": nearest_value(
            new_high["date"], "foreign_net_buy_cumulative_trillion_krw", 6
        ),
        "financingPeakDate": str(financing_peak["date"]),
        "financingPeak": round(float(financing_peak["credit_financing_trillion_krw"]), 6),
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
                value_or_none(row["credit_financing_trillion_krw"], 6),
                value_or_none(row["kospi_close"], 2),
                value_or_none(row["kospi_ratio"], 4),
                value_or_none(row["foreign_net_buy_100m_krw"], 2),
                value_or_none(row["foreign_net_buy_cumulative_trillion_krw"], 6),
                value_or_none(row["korea_10y_yield"], 4),
                value_or_none(row["korea_10y_yield_ratio"], 4),
                value_or_none(row["usdkrw"], 4),
                value_or_none(row["usdkrw_ratio"], 4),
            ]
        )

    payload = json.dumps(
        {"data": records, "meta": meta},
        ensure_ascii=False,
        separators=(",", ":"),
    )

    html = """
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KOSPI & Cash flow</title><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#f4f6f8;color:#111827;font-family:"Microsoft YaHei",Arial,sans-serif}.page{position:relative;width:100vw;height:100vh;background:#fff}canvas{display:block;width:100vw;height:100vh}.tip{position:absolute;display:none;pointer-events:none;background:rgba(17,24,39,.93);color:#fff;border-radius:6px;padding:8px 10px;font-size:12px;line-height:1.65;box-shadow:0 8px 22px rgba(0,0,0,.2);white-space:nowrap}.home-link{position:absolute;left:14px;top:14px;z-index:2;width:32px;height:32px;border:1px solid rgba(120,129,145,.34);border-radius:6px;display:flex;align-items:center;justify-content:center;color:#526071;background:rgba(255,255,255,.72);box-shadow:0 6px 18px rgba(15,23,42,.08);backdrop-filter:blur(2px)}.is-embed .home-link{display:none}.home-link:hover{color:#17202a;background:rgba(255,255,255,.94)}.home-link svg{width:18px;height:18px;stroke:currentColor}</style><script>if(new URLSearchParams(location.search).get("embed")==="1")document.documentElement.classList.add("is-embed");</script></head><body><div class="page"><a class="home-link" href="../../index.html" aria-label="返回主页" title="返回主页"><svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/></svg></a><canvas id="chart"></canvas><div class="tip" id="tip"></div></div><script>
const P=__PAYLOAD__;const rows=P.data.map(d=>({t:new Date(d[0]).getTime(),date:d[0],f:d[1],k:d[2],kr:d[3]}));const meta=P.meta,canvas=document.getElementById("chart"),ctx=canvas.getContext("2d"),tip=document.getElementById("tip");const colors={f:"#e56b2f",kr:"#0086b0",peak:"#7bb8f8"};let box={},legendHits=[],visible={f:true,kr:true,peak:true,notes:new URLSearchParams(location.search).get("notes")!=="0"},view=null,drag=null,selection=null,xScale,yLeft,yRight,plotRows=rows;function fmt(v,d=2){return v==null?"-":Number(v).toFixed(d)}function amountLine(v){return v==null?"":`\\n融资 ${fmt(v,3)}万亿韩元`}function kospiLine(v){return v==null?"":`\\nKOSPI ${fmt(v,2)}点`}function dataDomain(){const a=rows[0].t,b=rows[rows.length-1].t,pad=(b-a)*.045;return[a-pad,b+pad]}function values(k,source=plotRows){return source.map(r=>r[k]).filter(v=>v!=null&&Number.isFinite(v))}function extent(keys,source=plotRows){const a=keys.flatMap(k=>values(k,source));return a.length?[Math.min(...a),Math.max(...a)]:[0,1]}function niceTicks(min,max,n){const span=Math.max(1e-9,max-min),raw=span/Math.max(1,n),pow=Math.pow(10,Math.floor(Math.log10(raw))),base=[1,2,5,10].find(x=>x*pow>=raw)*pow,start=Math.ceil(min/base)*base,out=[];for(let v=start;v<=max+base*.5;v+=base)out.push(v);return out}function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}function textBox(text,x,y,align="left"){const lines=text.split("\\n"),padX=12,padY=5,lh=16,w=Math.max(...lines.map(s=>ctx.measureText(s).width))+padX*2,h=lines.length*lh+padY*2;let bx=align==="right"?x-w:x;ctx.fillStyle="rgba(255,255,255,.86)";ctx.strokeStyle="#cbd5e1";ctx.lineWidth=.8;ctx.beginPath();ctx.roundRect(bx,y,w,h,6);ctx.fill();ctx.stroke();ctx.fillStyle="#1f2937";ctx.textAlign="left";lines.forEach((s,i)=>ctx.fillText(s,bx+padX,y+padY+12+i*lh))}function inRange(date){const t=new Date(date).getTime();return t>=box.tmin&&t<=box.tmax}function drawLabel(p,text,dx,dy,color,side){if(!visible.notes||!inRange(p.date))return;const x=xScale(new Date(p.date).getTime()),y=side==="left"?yLeft(p.value):yRight(p.value);ctx.strokeStyle="#64748b";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+dx,y+dy);ctx.stroke();ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill();textBox(text,x+dx+(dx<0?-6:6),y+dy-20,dx<0?"right":"left")}function draw(active){const w=canvas.clientWidth,h=canvas.clientHeight,p={l:96,r:106,t:98,b:76},x0=p.l,x1=w-p.r,y0=h-p.b,y1=p.t,[fullMin,fullMax]=dataDomain(),tmin=view?view[0]:fullMin,tmax=view?view[1]:fullMax;plotRows=rows.filter(r=>r.t>=tmin&&r.t<=tmax);if(!plotRows.length)plotRows=rows;ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);ctx.font="12px Microsoft YaHei,Arial";const [fMin0,fMax0]=extent(["f"]),[rMin0,rMax0]=extent(["kr"]);const fMin=Math.max(0,fMin0*.9),fMax=Math.max(fMax0,meta.financingPeak)*1.08,rMin=Math.max(0,rMin0*.9),rMax=rMax0*1.08;box={x0,x1,y0,y1,tmin,tmax,fMin,fMax,rMin,rMax};xScale=t=>x0+(t-tmin)/(tmax-tmin)*(x1-x0);yLeft=v=>y0-(v-fMin)/(fMax-fMin)*(y0-y1);yRight=v=>y0-(v-rMin)/(rMax-rMin)*(y0-y1);ctx.fillStyle="#9ca3af";ctx.font="11px Microsoft YaHei,Arial";ctx.textAlign="left";ctx.fillText("Made by Yilimi",x0,32);ctx.fillStyle="#111827";ctx.font="700 22px Microsoft YaHei,Arial";ctx.textAlign="center";ctx.fillText("KOSPI & Cash flow",w/2,32);drawLegend(x0,58);ctx.font="12px Microsoft YaHei,Arial";ctx.lineWidth=.6;niceTicks(fMin,fMax,6).forEach(v=>{const y=yLeft(v);ctx.strokeStyle="#e5e7eb";ctx.beginPath();ctx.moveTo(x0,y);ctx.lineTo(x1,y);ctx.stroke();ctx.fillStyle=colors.f;ctx.textAlign="right";ctx.fillText(v.toFixed(1),x0-9,y+4)});niceTicks(rMin,rMax,6).forEach(v=>{const y=yRight(v);ctx.fillStyle="#111";ctx.textAlign="left";ctx.fillText(Math.round(v),x1+9,y+4)});const startYear=Math.max(2014,new Date(tmin).getFullYear()),endYear=new Date(tmax).getFullYear();for(let y=startYear;y<=endYear;y++){const x=xScale(new Date(`${y}-01-01`).getTime());if(x<x0||x>x1)continue;ctx.strokeStyle="#eef2f7";ctx.beginPath();ctx.moveTo(x,y1);ctx.lineTo(x,y0);ctx.stroke();ctx.fillStyle="#4b5563";ctx.textAlign="center";ctx.fillText(y,x,y0+24)}ctx.strokeStyle="#111827";ctx.lineWidth=1;ctx.strokeRect(x0,y1,x1-x0,y0-y1);function path(key,color,width,scale){if(!visible[key])return;ctx.beginPath();let open=false;for(const r of rows){const v=r[key];if(v==null||r.t<tmin||r.t>tmax){open=false;continue}const x=xScale(r.t),y=scale(v);if(!open){ctx.moveTo(x,y);open=true}else ctx.lineTo(x,y)}ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke()}path("f",colors.f,1.18,yLeft);path("kr",colors.kr,1.0,yRight);if(visible.peak){const py=yLeft(meta.financingPeak);ctx.setLineDash([6,4]);ctx.strokeStyle=colors.peak;ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x0,py);ctx.lineTo(x1,py);ctx.stroke();ctx.setLineDash([])}ctx.save();ctx.translate(22,(y0+y1)/2);ctx.rotate(-Math.PI/2);ctx.fillStyle=colors.f;ctx.textAlign="center";ctx.fillText("融资余额（万亿韩元）",0,0);ctx.restore();ctx.save();ctx.translate(w-24,(y0+y1)/2);ctx.rotate(Math.PI/2);ctx.fillStyle="#111";ctx.textAlign="center";ctx.fillText("KOSPI 相对值（2014-01=100）",0,0);ctx.restore();drawLabel({date:meta.financingPeakDate,value:meta.financingPeak},`融资余额高点\\n${meta.financingPeakDate}\\n融资 ${fmt(meta.financingPeak,3)}万亿韩元${kospiLine(meta.financingPeakKospi)}`,34,30,colors.f,"left");drawLabel({date:meta.kospiPeakDate,value:meta.kospiPeakRatio},`KOSPI 高点\\n${meta.kospiPeakDate}${amountLine(meta.kospiPeakFinancing)}${kospiLine(meta.kospiPeak)}`,-34,-54,colors.kr,"right");ctx.fillStyle="#4b5563";ctx.textAlign="left";ctx.font="12px Microsoft YaHei,Arial";if(new URLSearchParams(location.search).get("embed")!=="1")ctx.fillText(`更新时间：${meta.updatedAt}；数据源：KOFIA FreeSIS、Yahoo Finance、Naver Finance。`,x0,y0+64);if(active!=null){const r=rows[active],x=xScale(r.t);ctx.strokeStyle="rgba(31,41,55,.42)";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y1);ctx.lineTo(x,y0);ctx.stroke();[[r.f,yLeft,colors.f,"f"],[r.kr,yRight,colors.kr,"kr"]].forEach(([v,scale,color,key])=>{if(visible[key]&&v!=null){ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,scale(v),3,0,Math.PI*2);ctx.fill()}})}if(selection){const x0s=clamp(selection.x0,box.x0,box.x1),x1s=clamp(selection.x1,box.x0,box.x1),left=Math.min(x0s,x1s),width=Math.abs(x1s-x0s);if(width>=3){ctx.fillStyle="rgba(111,74,168,.10)";ctx.strokeStyle="rgba(111,74,168,.55)";ctx.lineWidth=1;ctx.setLineDash([4,3]);ctx.fillRect(left,box.y1,width,box.y0-box.y1);ctx.strokeRect(left,box.y1,width,box.y0-box.y1);ctx.setLineDash([])}}}function drawLegend(x,y){legendHits=[];const items=[{key:"f",color:colors.f,label:"信用交易融资余额（万亿韩元）"},{key:"kr",color:colors.kr,label:"KOSPI 相对值"},{key:"peak",color:colors.peak,label:"融资余额高点",dash:true},{key:"notes",color:"#94a3b8",label:"文字注释"}];ctx.font="13px Microsoft YaHei,Arial";let cur=x;items.forEach(item=>{const textW=ctx.measureText(item.label).width,w=textW+46;legendHits.push({key:item.key,x:cur-4,y:y-14,w:w+8,h:26});ctx.globalAlpha=visible[item.key]?1:.28;ctx.strokeStyle=item.color;ctx.lineWidth=item.dash?.8:2;ctx.setLineDash(item.dash?[6,4]:[]);ctx.beginPath();ctx.moveTo(cur,y);ctx.lineTo(cur+28,y);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle="#374151";ctx.textAlign="left";ctx.fillText(item.label,cur+36,y+4);ctx.globalAlpha=1;cur+=w+30})}function legendAt(x,y){return legendHits.find(h=>x>=h.x&&x<=h.x+h.w&&y>=h.y&&y<=h.y+h.h)}function inPlot(x,y){return x>=box.x0&&x<=box.x1&&y>=box.y1&&y<=box.y0}function clamp(v,a,b){return Math.max(a,Math.min(b,v))}function timeAtX(x){return box.tmin+(x-box.x0)/(box.x1-box.x0)*(box.tmax-box.tmin)}function nearest(mx){const source=plotRows.length?plotRows:rows,t=timeAtX(mx);let best=source[0],dist=Math.abs(source[0].t-t);for(const r of source){const d=Math.abs(r.t-t);if(d<dist){best=r;dist=d}}return rows.indexOf(best)}canvas.addEventListener("mousedown",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(legendAt(x,y)||!inPlot(x,y))return;drag={x0:x,x1:x};selection=null;tip.style.display="none";canvas.style.cursor="crosshair"});window.addEventListener("mouseup",e=>{if(!drag)return;const rect=canvas.getBoundingClientRect(),x=clamp(e.clientX-rect.left,box.x0,box.x1);drag.x1=x;const width=Math.abs(drag.x1-drag.x0);if(width>12){const a=Math.min(drag.x0,drag.x1),b=Math.max(drag.x0,drag.x1);view=[timeAtX(a),timeAtX(b)]}drag=null;selection=null;canvas.style.cursor="default";tip.style.display="none";draw()});canvas.addEventListener("dblclick",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(inPlot(x,y)){view=null;selection=null;tip.style.display="none";draw()}});canvas.addEventListener("click",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top,hit=legendAt(x,y);if(hit){visible[hit.key]=!visible[hit.key];tip.style.display="none";draw()}});canvas.addEventListener("mousemove",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(drag){drag.x1=clamp(x,box.x0,box.x1);selection=drag;tip.style.display="none";draw();return}const hit=legendAt(x,y);canvas.style.cursor=hit?"pointer":inPlot(x,y)?"crosshair":"default";if(hit){tip.style.display="none";draw();return}if(!inPlot(x,y)){tip.style.display="none";draw();return}const i=nearest(x),r=rows[i];draw(i);tip.innerHTML=`<b>${r.date}</b><br>信用交易融资余额：${fmt(r.f,3)} 万亿韩元<br>KOSPI：${fmt(r.k,2)} 点，相对值 ${fmt(r.kr,2)}`;tip.style.display="block";tip.style.left=Math.min(rect.width-260,Math.max(8,x+14))+"px";tip.style.top=Math.max(8,y-54)+"px"});canvas.addEventListener("mouseleave",()=>{if(drag)return;selection=null;tip.style.display="none";canvas.style.cursor="default";draw()});window.addEventListener("resize",resize);resize();
</script></body></html>
"""
    html = """
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KOSPI & Cash flow</title><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#f4f6f8;color:#111827;font-family:"Microsoft YaHei",Arial,sans-serif}.page{position:relative;width:100vw;height:100vh;background:#fff}canvas{display:block;width:100vw;height:100vh}.tip{position:absolute;display:none;pointer-events:none;background:rgba(17,24,39,.93);color:#fff;border-radius:6px;padding:8px 10px;font-size:12px;line-height:1.65;box-shadow:0 8px 22px rgba(0,0,0,.2);white-space:nowrap}.home-link{position:absolute;left:14px;top:14px;z-index:2;width:32px;height:32px;border:1px solid rgba(120,129,145,.34);border-radius:6px;display:flex;align-items:center;justify-content:center;color:#526071;background:rgba(255,255,255,.72);box-shadow:0 6px 18px rgba(15,23,42,.08);backdrop-filter:blur(2px)}.is-embed .home-link{display:none}.home-link:hover{color:#17202a;background:rgba(255,255,255,.94)}.home-link svg{width:18px;height:18px;stroke:currentColor}</style><script>if(new URLSearchParams(location.search).get("embed")==="1")document.documentElement.classList.add("is-embed");</script></head><body><div class="page"><a class="home-link" href="../../index.html" aria-label="返回主页" title="返回主页"><svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/></svg></a><canvas id="chart"></canvas><div class="tip" id="tip"></div></div><script>
const P=__PAYLOAD__;const rows=P.data.map((d,i)=>({i,date:d[0],f:d[1],k:d[2],kr:d[3],nf:d[4],fc:d[5],by:d[6],byr:d[7],fx:d[8],fxr:d[9]}));const meta=P.meta,canvas=document.getElementById("chart"),ctx=canvas.getContext("2d"),tip=document.getElementById("tip");const colors={f:"#e56b2f",kr:"#0086b0",nf:"#16a34a",by:"#7c3aed",fx:"#334155",fc:"#0f766e",nfDown:"#dc2626",peak:"#7bb8f8"};let box={},legendHits=[],visible={f:true,kr:true,nf:true,by:false,fx:false,peak:true,notes:new URLSearchParams(location.search).get("notes")!=="0"},view=null,drag=null,selection=null,xScale,yLeft,yRight,plotRows=rows;function fmt(v,d=2){return v==null?"-":Number(v).toFixed(d)}function amountLine(v){return v==null?"":`\\n融资 ${fmt(v,3)}万亿韩元`}function kospiLine(v){return v==null?"":`\\nKOSPI ${fmt(v,2)}点`}function foreignCumLine(v){return v==null?"":`\\n外资累计 ${fmt(v,2)}万亿韩元`}function dataDomain(){const a=0,b=rows.length-1,pad=Math.max(1,(b-a)*.045);return[a-pad,b+pad]}function values(k,source=plotRows){return source.map(r=>r[k]).filter(v=>v!=null&&Number.isFinite(v))}function extent(keys,source=plotRows){const a=keys.flatMap(k=>values(k,source));return a.length?[Math.min(...a),Math.max(...a)]:[0,1]}function niceTicks(min,max,n){const span=Math.max(1e-9,max-min),raw=span/Math.max(1,n),pow=Math.pow(10,Math.floor(Math.log10(raw))),base=[1,2,5,10].find(x=>x*pow>=raw)*pow,start=Math.ceil(min/base)*base,out=[];for(let v=start;v<=max+base*.5;v+=base)out.push(v);return out}function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}function rowByDate(date){return rows.find(r=>r.date===date)}function textBox(text,x,y,align="left"){const lines=text.split("\\n"),padX=12,padY=5,lh=16,extra=18,w=Math.max(...lines.map(s=>ctx.measureText(s).width))+padX*2+extra,h=lines.length*lh+padY*2;let bx=align==="right"?x-w:x;ctx.save();ctx.shadowColor="rgba(15,23,42,.16)";ctx.shadowBlur=18;ctx.shadowOffsetY=8;ctx.fillStyle="rgba(255,255,255,.42)";ctx.strokeStyle="rgba(255,255,255,.76)";ctx.lineWidth=.9;ctx.beginPath();ctx.roundRect(bx,y,w,h,8);ctx.fill();ctx.shadowBlur=0;ctx.stroke();ctx.restore();ctx.fillStyle="rgba(15,23,42,.94)";ctx.textAlign="left";lines.forEach((s,i)=>ctx.fillText(s,bx+padX,y+padY+12+i*lh))}function inRange(date){const r=rowByDate(date);return r&&r.i>=box.imin&&r.i<=box.imax}function drawLabel(p,text,dx,dy,color,side){if(!visible.notes||!inRange(p.date))return;const r=rowByDate(p.date),x=xScale(r.i),y=side==="left"?yLeft(p.value):yRight(p.value);ctx.strokeStyle="#64748b";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+dx,y+dy);ctx.stroke();ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill();textBox(text,x+dx+(dx<0?-6:6),y+dy-20,dx<0?"right":"left")}function drawForeignBars(x0,x1,y0,y1){if(!visible.nf)return;const nums=values("nf");if(!nums.length)return;const maxAbs=Math.max(...nums.map(v=>Math.abs(v)));if(!maxAbs)return;const zero=y0-(y0-y1)*.17,band=(y0-y1)*.13,step=Math.abs(xScale(Math.min(box.imax,box.imin+1))-xScale(box.imin))||1,bw=Math.max(1,Math.min(5,step*.72));ctx.strokeStyle="rgba(71,85,105,.38)";ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(x0,zero);ctx.lineTo(x1,zero);ctx.stroke();for(const r of rows){if(r.i<box.imin||r.i>box.imax||r.nf==null)continue;const x=xScale(r.i),y=zero-(r.nf/maxAbs)*band;ctx.fillStyle=r.nf>=0?"rgba(22,163,74,.34)":"rgba(220,38,38,.30)";ctx.fillRect(x-bw/2,Math.min(y,zero),bw,Math.max(1,Math.abs(y-zero)))}ctx.fillStyle="#64748b";ctx.textAlign="left";ctx.font="12px Microsoft YaHei,Arial";ctx.fillText("外资净买入（亿韩元）",x0+8,zero-6)}function draw(active){const w=canvas.clientWidth,h=canvas.clientHeight,p={l:96,r:106,t:98,b:76},x0=p.l,x1=w-p.r,y0=h-p.b,y1=p.t,[fullMin,fullMax]=dataDomain(),imin=view?view[0]:fullMin,imax=view?view[1]:fullMax;plotRows=rows.filter(r=>r.i>=imin&&r.i<=imax);if(!plotRows.length)plotRows=rows;ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);ctx.font="12px Microsoft YaHei,Arial";const rKeys=["kr"];if(visible.by)rKeys.push("byr");if(visible.fx)rKeys.push("fxr");const [fMin0,fMax0]=extent(["f"]),[rMin0,rMax0]=extent(rKeys);const fPad=Math.max(.1,(fMax0-fMin0)*.06),fMin=Math.min(0,fMin0-fPad),fMax=Math.max(fMax0,meta.oldPeak,meta.newHigh)+fPad,rMin=Math.max(0,rMin0*.9),rMax=rMax0*1.08;box={x0,x1,y0,y1,imin,imax,fMin,fMax,rMin,rMax};xScale=i=>x0+(i-imin)/(imax-imin)*(x1-x0);yLeft=v=>y0-(v-fMin)/(fMax-fMin)*(y0-y1);yRight=v=>y0-(v-rMin)/(rMax-rMin)*(y0-y1);ctx.fillStyle="#111827";ctx.font="700 22px Microsoft YaHei,Arial";ctx.textAlign="center";ctx.fillText("KOSPI & Cash flow",w/2,32);drawLegend(x0,58);ctx.font="12px Microsoft YaHei,Arial";ctx.lineWidth=.6;niceTicks(fMin,fMax,6).forEach(v=>{const y=yLeft(v);ctx.strokeStyle="#e5e7eb";ctx.beginPath();ctx.moveTo(x0,y);ctx.lineTo(x1,y);ctx.stroke();ctx.fillStyle=colors.f;ctx.textAlign="right";ctx.fillText(v.toFixed(1),x0-9,y+4)});niceTicks(rMin,rMax,6).forEach(v=>{const y=yRight(v);ctx.fillStyle="#111";ctx.textAlign="left";ctx.fillText(Math.round(v),x1+9,y+4)});let seenYear=null;for(const r of rows){if(r.i<imin||r.i>imax)continue;const year=r.date.slice(0,4);if(year===seenYear)continue;seenYear=year;const x=xScale(r.i);ctx.strokeStyle="#eef2f7";ctx.beginPath();ctx.moveTo(x,y1);ctx.lineTo(x,y0);ctx.stroke();ctx.fillStyle="#4b5563";ctx.textAlign="center";ctx.fillText(year,x,y0+24)}ctx.strokeStyle="#111827";ctx.lineWidth=1;ctx.strokeRect(x0,y1,x1-x0,y0-y1);drawForeignBars(x0,x1,y0,y1);function path(key,color,width,scale,visibleKey=key){if(!visible[visibleKey])return;ctx.beginPath();let open=false;for(const r of rows){const v=r[key];if(v==null||r.i<imin||r.i>imax){open=false;continue}const x=xScale(r.i),y=scale(v);if(!open){ctx.moveTo(x,y);open=true}else ctx.lineTo(x,y)}ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke()}path("f",colors.f,1.18,yLeft);path("kr",colors.kr,1.0,yRight);path("byr",colors.by,.95,yRight,"by");path("fxr",colors.fx,.95,yRight,"fx");if(visible.peak){const py=yLeft(meta.oldPeak);ctx.setLineDash([6,4]);ctx.strokeStyle=colors.peak;ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x0,py);ctx.lineTo(x1,py);ctx.stroke();ctx.setLineDash([])}ctx.save();ctx.translate(22,(y0+y1)/2);ctx.rotate(-Math.PI/2);ctx.fillStyle=colors.f;ctx.textAlign="center";ctx.fillText("融资余额（万亿韩元）",0,0);ctx.restore();ctx.save();ctx.translate(w-24,(y0+y1)/2);ctx.rotate(Math.PI/2);ctx.fillStyle="#111";ctx.textAlign="center";ctx.fillText("相对值（2014-01=100）",0,0);ctx.restore();if(visible.f&&visible.peak)drawLabel({date:meta.oldPeakDate,value:meta.oldPeak},`融资旧高\\n${meta.oldPeakDate}\\n融资 ${fmt(meta.oldPeak,3)}万亿韩元${kospiLine(meta.oldPeakKospi)}`,34,30,colors.f,"left");if(visible.f&&meta.newHighDate!==meta.oldPeakDate)drawLabel({date:meta.newHighDate,value:meta.newHigh},`融资突破旧高\\n${meta.newHighDate}\\n融资 ${fmt(meta.newHigh,3)}万亿韩元${kospiLine(meta.newHighKospi)}`,-34,-54,colors.f,"left");[["2020-03-19",34,-62],["2025-04-09",48,-104]].forEach(([date,dx,dy])=>{const r=rowByDate(date);if(r&&visible.kr)drawLabel({date:date,value:r.kr},`牛市起点\\n${date}${kospiLine(r.k)}${amountLine(r.f)}`,dx,dy,colors.kr,"right")});ctx.fillStyle="#4b5563";ctx.textAlign="left";ctx.font="12px Microsoft YaHei,Arial";if(new URLSearchParams(location.search).get("embed")!=="1"){ctx.textAlign="right";ctx.fillText("Made by Yilimi",x1,y0+46);ctx.textAlign="left";ctx.fillText(`更新时间：${meta.updatedAt}；数据源：KOFIA FreeSIS、Yahoo Finance、Naver Finance、TradingView。`,x0,y0+64);}if(active!=null){const r=rows[active],x=xScale(r.i);ctx.strokeStyle="rgba(31,41,55,.42)";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y1);ctx.lineTo(x,y0);ctx.stroke();[[r.f,yLeft,colors.f,"f"],[r.kr,yRight,colors.kr,"kr"],[r.byr,yRight,colors.by,"by"],[r.fxr,yRight,colors.fx,"fx"]].forEach(([v,scale,color,key])=>{if(visible[key]&&v!=null){ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,scale(v),3,0,Math.PI*2);ctx.fill()}})}if(selection){const x0s=clamp(selection.x0,box.x0,box.x1),x1s=clamp(selection.x1,box.x0,box.x1),left=Math.min(x0s,x1s),width=Math.abs(x1s-x0s);if(width>=3){ctx.fillStyle="rgba(111,74,168,.10)";ctx.strokeStyle="rgba(111,74,168,.55)";ctx.lineWidth=1;ctx.setLineDash([4,3]);ctx.fillRect(left,box.y1,width,box.y0-box.y1);ctx.strokeRect(left,box.y1,width,box.y0-box.y1);ctx.setLineDash([])}}}function drawLegend(x,y){legendHits=[];const items=[{key:"f",color:colors.f,label:"信用交易融资余额（万亿韩元）"},{key:"kr",color:colors.kr,label:"KOSPI 相对值"},{key:"by",color:colors.by,label:"韩国10年国债收益率相对值"},{key:"fx",color:colors.fx,label:"USD/KRW 相对值"},{key:"nf",color:colors.nf,label:"外国人净买入"},{key:"peak",color:colors.peak,label:"融资旧高",dash:true},{key:"notes",color:"#94a3b8",label:"文字注释"}];ctx.font="13px Microsoft YaHei,Arial";let cur=x;items.forEach(item=>{const textW=ctx.measureText(item.label).width,w=textW+46;legendHits.push({key:item.key,x:cur-4,y:y-14,w:w+8,h:26});ctx.globalAlpha=visible[item.key]?1:.28;ctx.strokeStyle=item.color;ctx.lineWidth=item.dash?.8:2;ctx.setLineDash(item.dash?[6,4]:[]);ctx.beginPath();ctx.moveTo(cur,y);ctx.lineTo(cur+28,y);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle="#374151";ctx.textAlign="left";ctx.fillText(item.label,cur+36,y+4);ctx.globalAlpha=1;cur+=w+24})}function legendAt(x,y){return legendHits.find(h=>x>=h.x&&x<=h.x+h.w&&y>=h.y&&y<=h.y+h.h)}function inPlot(x,y){return x>=box.x0&&x<=box.x1&&y>=box.y1&&y<=box.y0}function clamp(v,a,b){return Math.max(a,Math.min(b,v))}function indexAtX(x){return box.imin+(x-box.x0)/(box.x1-box.x0)*(box.imax-box.imin)}function nearest(mx){let idx=Math.round(indexAtX(mx));idx=Math.max(0,Math.min(rows.length-1,idx));return idx}canvas.addEventListener("mousedown",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(legendAt(x,y)||!inPlot(x,y))return;drag={x0:x,x1:x};selection=null;tip.style.display="none";canvas.style.cursor="crosshair"});window.addEventListener("mouseup",e=>{if(!drag)return;const rect=canvas.getBoundingClientRect(),x=clamp(e.clientX-rect.left,box.x0,box.x1);drag.x1=x;const width=Math.abs(drag.x1-drag.x0);if(width>12){const a=Math.min(drag.x0,drag.x1),b=Math.max(drag.x0,drag.x1);view=[indexAtX(a),indexAtX(b)]}drag=null;selection=null;canvas.style.cursor="default";tip.style.display="none";draw()});canvas.addEventListener("dblclick",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(inPlot(x,y)){view=null;selection=null;tip.style.display="none";draw()}});canvas.addEventListener("click",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top,hit=legendAt(x,y);if(hit){visible[hit.key]=!visible[hit.key];tip.style.display="none";draw()}});canvas.addEventListener("mousemove",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(drag){drag.x1=clamp(x,box.x0,box.x1);selection=drag;tip.style.display="none";draw();return}const hit=legendAt(x,y);canvas.style.cursor=hit?"pointer":inPlot(x,y)?"crosshair":"default";if(hit){tip.style.display="none";draw();return}if(!inPlot(x,y)){tip.style.display="none";draw();return}const i=nearest(x),r=rows[i];draw(i);tip.innerHTML=`<b>${r.date}</b><br>信用交易融资余额：${fmt(r.f,3)} 万亿韩元<br>KOSPI：${fmt(r.k,2)} 点，相对值 ${fmt(r.kr,2)}${visible.by&&r.by!=null?`<br>韩国10年国债收益率：${fmt(r.by,3)}%，相对值 ${fmt(r.byr,2)}`:""}${visible.fx&&r.fx!=null?`<br>USD/KRW：${fmt(r.fx,2)}，相对值 ${fmt(r.fxr,2)}`:""}<br>外国人净买入：${fmt(r.nf,0)} 亿韩元`;tip.style.display="block";tip.style.left=Math.min(rect.width-300,Math.max(8,x+14))+"px";tip.style.top=Math.max(8,y-72)+"px"});canvas.addEventListener("mouseleave",()=>{if(drag)return;selection=null;tip.style.display="none";canvas.style.cursor="default";draw()});window.addEventListener("resize",resize);resize();
</script></body></html>
"""
    html = html.replace(
        "ctx.save();ctx.translate(22,(y0+y1)/2);ctx.rotate(-Math.PI/2);",
        "ctx.save();ctx.translate(42,(y0+y1)/2);ctx.rotate(-Math.PI/2);",
    )
    html = html.replace(
        "ctx.save();ctx.translate(w-24,(y0+y1)/2);ctx.rotate(Math.PI/2);",
        "ctx.save();ctx.translate(w-48,(y0+y1)/2);ctx.rotate(Math.PI/2);",
    )
    html = html.replace(
        'if(new URLSearchParams(location.search).get("embed")!=="1"){ctx.textAlign="right";ctx.fillText("Made by Yilimi",x1,y0+46);ctx.textAlign="left";',
        'if(new URLSearchParams(location.search).get("embed")!=="1"){ctx.fillStyle="#cbd5e1";ctx.textAlign="right";ctx.fillText("Made by Yilimi",x1,y0+46);ctx.fillStyle="#4b5563";ctx.textAlign="left";',
    )
    html = html.replace(
        'notes:new URLSearchParams(location.search).get("notes")!=="0"',
        'notes:new URLSearchParams(location.search).get("notes")==="1"',
    )
    html = html.replace(
        'label:"信用交易融资余额（万亿韩元）"',
        'label:"信用交易融资余额"',
    )
    html = html.replace(
        '{key:"f",color:colors.f,label:"信用交易融资余额"},{key:"kr",color:colors.kr,label:"KOSPI 相对值"},{key:"by",color:colors.by,label:"韩国10年国债收益率相对值"},{key:"fx",color:colors.fx,label:"USD/KRW 相对值"},{key:"nf",color:colors.nf,label:"外国人净买入"}',
        '{key:"f",color:colors.f,label:"信用交易融资余额"},{key:"kr",color:colors.kr,label:"KOSPI 相对值"},{key:"nf",color:colors.nf,label:"外国人净买入"},{key:"by",color:colors.by,label:"韩国10年国债收益率相对值"},{key:"fx",color:colors.fx,label:"USD/KRW 相对值"}',
    )
    html = html.replace(
        "peak:true,notes:",
        "peak:false,notes:",
    )
    weekday_tooltip_patch = """
<script>
function dayLabel(date){return `${date}（${"日一二三四五六"[new Date(`${date}T00:00:00Z`).getUTCDay()]}）`}
canvas.addEventListener("mousemove",e=>{
  const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;
  if(drag||legendAt(x,y)||!inPlot(x,y)||tip.style.display==="none")return;
  const r=rows[nearest(x)];
  tip.innerHTML=tip.innerHTML.replace(`<b>${r.date}</b>`,`<b>${dayLabel(r.date)}</b>`);
});
</script>
"""
    html = html.replace("</script></body></html>", "</script>" + weekday_tooltip_patch + "</body></html>")
    html = html.replace("__PAYLOAD__", payload)
    html = "".join(line.strip() for line in html.splitlines())
    html = add_canvas_mobile_support(html)
    output_html.write_text(html, encoding="utf-8")


def main() -> int:
    financing = fetch_credit_financing_balance()
    kospi = fetch_kospi()
    foreign = fetch_foreign_net_buy()
    bond = fetch_korea_10y_yield()
    usdkrw = fetch_usdkrw()
    data = pd.merge(financing, kospi, on="date", how="outer").sort_values("date")
    data = pd.merge(data, foreign, on="date", how="outer").sort_values("date")
    data = pd.merge(data, bond, on="date", how="outer").sort_values("date")
    data = pd.merge(data, usdkrw, on="date", how="outer").sort_values("date")
    data = data.dropna(subset=["kospi_close"])
    data = add_index_ratios(data)

    csv_path = OUT_DIR / "korea_margin_kospi_data.csv"
    html_path = OUT_DIR / "korea_margin_kospi.html"
    data.to_csv(csv_path, index=False, encoding="utf-8-sig")
    write_interactive_html(data, html_path)

    print(f"CSV: {csv_path}")
    print(f"HTML: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
