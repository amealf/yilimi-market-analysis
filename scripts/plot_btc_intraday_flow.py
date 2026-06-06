from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from mobile_chart_support import add_canvas_mobile_support


SYMBOL = "BTCUSDT"
INTERVAL = "1m"
LOOKBACK_DAYS = 5
KLINE_MINUTES = 1
BINANCE_KLINE_SOURCE = "https://data-api.binance.vision/api/v3/klines"
MAX_CACHE_STALENESS = timedelta(hours=12)


def request_json(url: str, retries: int = 4, pause: float = 0.35, timeout: int = 20) -> object:
    last_error: Exception | None = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"Binance request failed: {url}") from last_error


def utc_minute_now() -> datetime:
    return datetime.now(timezone.utc).replace(second=0, microsecond=0)


def fetch_window() -> tuple[datetime, datetime]:
    current_minute = utc_minute_now()
    end_open_time = current_minute - timedelta(minutes=KLINE_MINUTES)
    start = end_open_time - timedelta(days=LOOKBACK_DAYS) + timedelta(minutes=KLINE_MINUTES)
    return start, end_open_time


def to_millis(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def fetch_binance_klines(start: datetime, end_open_time: datetime) -> pd.DataFrame:
    start_ms = to_millis(start)
    end_ms = to_millis(end_open_time + timedelta(minutes=KLINE_MINUTES)) - 1
    all_rows: list[list[object]] = []
    next_start = start_ms
    while next_start <= end_ms:
        query = urlencode(
            {
                "symbol": SYMBOL,
                "interval": INTERVAL,
                "startTime": next_start,
                "endTime": end_ms,
                "limit": 1000,
            }
        )
        payload = request_json(f"{BINANCE_KLINE_SOURCE}?{query}")
        if not isinstance(payload, list):
            raise RuntimeError("Binance kline payload has unexpected shape")
        if not payload:
            break
        all_rows.extend(payload)
        last_open = int(payload[-1][0])
        next_start = last_open + KLINE_MINUTES * 60_000
        if len(payload) < 1000:
            break
        time.sleep(0.08)

    if not all_rows:
        raise RuntimeError("Binance kline data is empty")
    return parse_klines(all_rows)


def parse_klines(rows: list[list[object]]) -> pd.DataFrame:
    columns = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "trades",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    number_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "taker_buy_base",
        "taker_buy_quote",
    ]
    for column in number_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["trades"] = pd.to_numeric(frame["trades"], errors="coerce").fillna(0).astype(int)
    frame["open_time"] = pd.to_numeric(frame["open_time"], errors="coerce").astype("Int64")
    frame = frame.dropna(subset=["open_time", "open", "high", "low", "close", "quote_volume", "taker_buy_quote"])
    frame["time"] = pd.to_datetime(frame["open_time"].astype("int64"), unit="ms", utc=True)
    frame = frame.drop_duplicates("time").sort_values("time")
    frame["taker_sell_quote"] = (frame["quote_volume"] - frame["taker_buy_quote"]).clip(lower=0)
    frame["taker_net_quote"] = frame["taker_buy_quote"] - frame["taker_sell_quote"]
    frame["quote_volume_m"] = frame["quote_volume"] / 1e6
    frame["taker_buy_m"] = frame["taker_buy_quote"] / 1e6
    frame["taker_sell_m"] = frame["taker_sell_quote"] / 1e6
    frame["taker_net_m"] = frame["taker_net_quote"] / 1e6
    frame["buy_ratio"] = (frame["taker_buy_quote"] / frame["quote_volume"] * 100).where(frame["quote_volume"] > 0)
    frame["binance_day"] = frame["time"].dt.strftime("%Y-%m-%d")
    frame["day_cvd_m"] = frame.groupby("binance_day", sort=False)["taker_net_m"].cumsum()
    frame["range_cvd_m"] = frame["taker_net_m"].cumsum()
    return frame[
        [
            "time",
            "binance_day",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume_m",
            "taker_buy_m",
            "taker_sell_m",
            "taker_net_m",
            "day_cvd_m",
            "range_cvd_m",
            "buy_ratio",
            "trades",
        ]
    ]


def normalize_cached_frame(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    data["time"] = pd.to_datetime(data["time"], utc=True)
    data = data.drop_duplicates("time").sort_values("time")
    for column in [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume_m",
        "taker_buy_m",
        "taker_sell_m",
        "taker_net_m",
        "day_cvd_m",
        "range_cvd_m",
        "buy_ratio",
        "trades",
    ]:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    if "binance_day" not in data.columns:
        data["binance_day"] = data["time"].dt.strftime("%Y-%m-%d")
    data["day_cvd_m"] = data.groupby("binance_day", sort=False)["taker_net_m"].cumsum()
    data["range_cvd_m"] = data["taker_net_m"].cumsum()
    return data


def load_cache(cache_path: Path) -> pd.DataFrame:
    cached = normalize_cached_frame(pd.read_csv(cache_path))
    latest = cached["time"].max().to_pydatetime()
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - latest > MAX_CACHE_STALENESS:
        raise RuntimeError(f"Cached BTC intraday data is stale: latest {latest.isoformat()}")
    return cached


def build_intraday_frame(cache_path: Path | None = None) -> pd.DataFrame:
    try:
        start, end_open_time = fetch_window()
        return fetch_binance_klines(start, end_open_time)
    except Exception as exc:
        if cache_path and cache_path.exists():
            return load_cache(cache_path)
        raise RuntimeError("BTC intraday flow build failed and no cache is available") from exc


def series_value(value: object, digits: int = 4) -> float | int | None:
    if pd.isna(value):
        return None
    if isinstance(value, int):
        return value
    return round(float(value), digits)


def money_m(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}${value:,.1f}M"


def chart_meta(data: pd.DataFrame) -> dict:
    data = normalize_cached_frame(data)
    latest = data.iloc[-1]
    latest_day = str(latest["binance_day"])
    day_frame = data.loc[data["binance_day"] == latest_day]
    today_net = float(day_frame["taker_net_m"].sum())
    today_volume = float(day_frame["quote_volume_m"].sum())
    latest_time = latest["time"].strftime("%Y-%m-%d %H:%M UTC")
    return {
        "latestTime": latest_time,
        "latestPrice": float(latest["close"]),
        "todayNetM": today_net,
        "todayCvdM": float(latest["day_cvd_m"]),
        "todayVolumeM": today_volume,
        "metrics": [
            {"label": "BTC", "value": f"${float(latest['close']):,.0f}", "date": latest_time},
            {"label": "今日净主动成交额", "value": money_m(today_net), "date": f"{latest_day} UTC+0"},
            {"label": "今日成交额", "value": f"${today_volume / 1000:,.2f}B", "date": f"{latest_day} UTC+0"},
        ],
    }


def row_payload(data: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in normalize_cached_frame(data).itertuples(index=False):
        rows.append(
            {
                "time": row.time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "day": row.binance_day,
                "open": series_value(row.open, 2),
                "high": series_value(row.high, 2),
                "low": series_value(row.low, 2),
                "close": series_value(row.close, 2),
                "volume": series_value(row.volume, 4),
                "quoteVolumeM": series_value(row.quote_volume_m, 4),
                "takerBuyM": series_value(row.taker_buy_m, 4),
                "takerSellM": series_value(row.taker_sell_m, 4),
                "netM": series_value(row.taker_net_m, 4),
                "dayCvdM": series_value(row.day_cvd_m, 4),
                "rangeCvdM": series_value(row.range_cvd_m, 4),
                "buyRatio": series_value(row.buy_ratio, 2),
                "trades": int(row.trades),
            }
        )
    return rows


def write_interactive_html(data: pd.DataFrame, output_html: Path) -> None:
    meta = chart_meta(data)
    payload = json.dumps(
        {
            "rows": row_payload(data),
            "meta": meta,
            "generatedAt": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "source": "Binance public market data",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    html_text = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <script>if(new URLSearchParams(location.search).get("embed")==="1")document.documentElement.classList.add("is-embed");</script>
  <title>BTC 日内净主动成交额</title>
  <style>
    html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#fff;color:#17202a;font-family:"Microsoft YaHei",Arial,sans-serif}
    .page{position:relative;width:100vw;height:100vh;background:#fff}
    .home-link{position:absolute;left:14px;top:14px;z-index:2;width:32px;height:32px;border:1px solid rgba(120,129,145,.34);border-radius:6px;display:flex;align-items:center;justify-content:center;color:#526071;background:rgba(255,255,255,.72);box-shadow:0 6px 18px rgba(15,23,42,.08);backdrop-filter:blur(2px)}
    .is-embed .home-link{display:none}
    .home-link:hover{color:#17202a;background:rgba(255,255,255,.94)}
    .home-link svg{width:18px;height:18px;stroke:currentColor}
    canvas{display:block;width:100vw;height:100vh;cursor:crosshair}
    .tip{position:absolute;display:none;pointer-events:none;box-sizing:border-box;min-width:260px;max-width:390px;background:rgba(255,255,255,.78);border:1px solid rgba(120,129,145,.42);border-radius:6px;color:#17202a;padding:9px 10px;font-size:12px;line-height:1.65;box-shadow:0 8px 22px rgba(15,23,42,.12);backdrop-filter:blur(2px);overflow-wrap:anywhere;white-space:normal}
    .footer-note{position:absolute;left:100px;right:18px;bottom:8px;z-index:2;display:flex;gap:10px;align-items:center;flex-wrap:wrap;color:#526071;font-size:11px;line-height:1.35;pointer-events:none}
    .is-embed .footer-note{display:none}
    @media (max-width:640px){.footer-note{left:64px;right:10px;bottom:8px;font-size:10.5px;gap:8px}}
  </style>
</head>
<body>
<div class="page"><a class="home-link" id="homeLink" href="../../index.html" aria-label="返回主页" title="返回主页"><svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/></svg></a><canvas id="chart"></canvas><div class="tip" id="tip"></div><div class="footer-note" id="footerNote"></div></div>
<script>
const P=__PAYLOAD__;
const rawRows=P.rows.map(r=>({...r,t:new Date(r.time).getTime()}));
const canvas=document.getElementById("chart");
const ctx=canvas.getContext("2d");
const tip=document.getElementById("tip");
const footerNote=document.getElementById("footerNote");
const isEmbed=document.documentElement.classList.contains("is-embed");
const colors={btc:"#1f77b4",candleUpFill:"rgba(255,255,255,.76)",candleDown:"rgba(31,119,180,.42)",buy:"#16a34a",sell:"#dc2626",cvd:"#2563eb",rangeCvd:"rgba(124,58,237,.70)",grid:"#dfe6ed",text:"#17202a",muted:"#526071"};
const DAY=86400000,MINUTE=60000;
let box={},zoom=null,drag=null,modeBoxes=[],rangeBoxes=[],intervalBoxes=[],legendBoxes=[],hoverMode=null,hoverRange=null,hoverInterval=null,rangeMode="one",intervalMode="1m",priceMode="line",hidden={rangeCvd:true};
function finite(v){return v!=null&&Number.isFinite(v)}
function fmtUsd(v,d=0){return v==null?"-":"$"+Number(v).toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d})}
function fmtM(v,d=1){if(v==null)return "-";const n=Number(v),sign=n>0?"+":"";return `${sign}$${n.toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d})}M`}
function fmtB(v,d=2){return v==null?"-":"$"+(Number(v)/1000).toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d})+"B"}
function fmtTime(t){const d=new Date(t);return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}-${String(d.getUTCDate()).padStart(2,"0")} ${String(d.getUTCHours()).padStart(2,"0")}:${String(d.getUTCMinutes()).padStart(2,"0")} UTC+0`}
const rangeDays={one:1,two:2,three:3,four:4,five:5};
const intervalMinutes={one:"1m","1m":1,"5m":5,"15m":15,"30m":30,"1h":60};
function dayKey(t){
  const d=new Date(t);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}-${String(d.getUTCDate()).padStart(2,"0")}`;
}
function aggregateAllRows(){
  const minutes=intervalMinutes[intervalMode]||1;
  let grouped;
  if(minutes===1){
    grouped=rawRows.map(r=>({...r}));
  }else{
    const buckets=new Map();
    rawRows.forEach(r=>{
      const bucket=Math.floor(r.t/(minutes*MINUTE))*minutes*MINUTE;
      if(!buckets.has(bucket))buckets.set(bucket,[]);
      buckets.get(bucket).push(r);
    });
    grouped=Array.from(buckets.entries()).sort((a,b)=>a[0]-b[0]).map(([t,items])=>{
      const first=items[0],last=items[items.length-1],buy=items.reduce((s,r)=>s+r.takerBuyM,0),sell=items.reduce((s,r)=>s+r.takerSellM,0),quote=items.reduce((s,r)=>s+r.quoteVolumeM,0),net=items.reduce((s,r)=>s+r.netM,0);
      return {t,time:new Date(t).toISOString(),day:dayKey(t),open:first.open,high:Math.max(...items.map(r=>r.high)),low:Math.min(...items.map(r=>r.low)),close:last.close,volume:items.reduce((s,r)=>s+r.volume,0),quoteVolumeM:quote,takerBuyM:buy,takerSellM:sell,netM:net,buyRatio:quote>0?buy/quote*100:null,trades:items.reduce((s,r)=>s+r.trades,0)};
    });
  }
  const dayCvd={};
  grouped.forEach(r=>{
    dayCvd[r.day]=(dayCvd[r.day]||0)+r.netM;
    r.dayCvdM=dayCvd[r.day];
  });
  return grouped;
}
function rowsForRange(){
  const all=aggregateAllRows(),last=rawRows[rawRows.length-1],days=rangeDays[rangeMode]||1,cutoff=last.t-days*DAY+MINUTE;
  const visible=all.filter(r=>r.t>=cutoff);
  let cumulative=0;
  visible.forEach(r=>{cumulative+=r.netM;r.rangeCvdM=cumulative});
  return visible.length?visible:all;
}
let rows=rowsForRange();
function refreshRows(){rows=rowsForRange();if(!rows.length)rows=rawRows}
function extent(values){const a=values.filter(finite);return a.length?[Math.min(...a),Math.max(...a)]:[0,1]}
function rangeExtent(keys,list=rows){return extent(keys.flatMap(key=>list.map(r=>r[key])))}
function currentRange(){return zoom||[rows[0].t,rows[rows.length-1].t+MINUTE]}
function visibleRows(){const [t0,t1]=currentRange();const sample=rows.filter(r=>r.t>=t0&&r.t<=t1);return sample.length?sample:rows}
function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}
function xScale(t){return box.x0+(t-box.t0)/(box.t1-box.t0)*(box.x1-box.x0)}
function yPrice(v){return box.priceY1-(v-box.priceMin)/(box.priceMax-box.priceMin)*(box.priceY1-box.priceY0)}
function yFlow(v){return box.flowY1-(v-box.flowMin)/(box.flowMax-box.flowMin)*(box.flowY1-box.flowY0)}
function yCvd(v){return box.flowY1-(v-box.cvdMin)/(box.cvdMax-box.cvdMin)*(box.flowY1-box.flowY0)}
function niceTicks(min,max,n){const span=Math.max(1e-9,max-min),raw=span/Math.max(1,n),pow=Math.pow(10,Math.floor(Math.log10(raw))),base=([1,2,5,10].find(x=>x*pow>=raw)||10)*pow,start=Math.ceil(min/base)*base,out=[];for(let v=start;v<=max+base*.5;v+=base)out.push(v);return out}
function gridLine(y,x0=box.x0,x1=box.x1){ctx.strokeStyle=colors.grid;ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(x0,y);ctx.lineTo(x1,y);ctx.stroke()}
function roundRect(x,y,w,h,r){
  const rr=Math.min(r,w/2,h/2);
  ctx.beginPath();ctx.moveTo(x+rr,y);ctx.lineTo(x+w-rr,y);ctx.quadraticCurveTo(x+w,y,x+w,y+rr);ctx.lineTo(x+w,y+h-rr);ctx.quadraticCurveTo(x+w,y+h,x+w-rr,y+h);ctx.lineTo(x+rr,y+h);ctx.quadraticCurveTo(x,y+h,x,y+h-rr);ctx.lineTo(x,y+rr);ctx.quadraticCurveTo(x,y,x+rr,y);
}
function drawModeTabs(x,y){
  modeBoxes=[];
  [["line"],["candle"]].forEach(([key],i)=>{
    const w=34,h=24,left=x+i*(w+6),active=priceMode===key,hovered=hoverMode===key;
    modeBoxes.push({key,x0:left,y0:y,x1:left+w,y1:y+h});
    ctx.strokeStyle=active?"#60a5fa":hovered?"#93c5fd":"rgba(71,85,105,.42)";
    ctx.lineWidth=active||hovered?1.35:.9;roundRect(left,y,w,h,7);ctx.stroke();
    ctx.strokeStyle=hovered||active?"#17202a":"rgba(71,85,105,.58)";ctx.fillStyle=key==="candle"&&(hovered||active)?"rgba(31,119,180,.50)":"rgba(255,255,255,.88)";ctx.lineWidth=1.15;
    if(key==="line"){ctx.beginPath();ctx.moveTo(left+8,y+16);ctx.lineTo(left+15,y+10);ctx.lineTo(left+21,y+12);ctx.lineTo(left+27,y+6);ctx.stroke()}
    else{ctx.beginPath();ctx.moveTo(left+12,y+6);ctx.lineTo(left+12,y+18);ctx.moveTo(left+23,y+5);ctx.lineTo(left+23,y+19);ctx.stroke();ctx.fillRect(left+9,y+10,7,6);ctx.strokeRect(left+9,y+10,7,6);ctx.fillRect(left+20,y+9,7,8);ctx.strokeRect(left+20,y+9,7,8)}
  });
}
function drawRangeTabs(x,y){
  rangeBoxes=[];
  const labels=[["one","24h"],["two","2D"],["three","3D"],["four","4D"],["five","5D"]];
  ctx.font="12px Microsoft YaHei,Arial";
  labels.forEach(([key,label],i)=>{
    const w=40,h=24,left=x+i*(w+6),active=rangeMode===key,hovered=hoverRange===key;
    rangeBoxes.push({key,x0:left,y0:y,x1:left+w,y1:y+h});
    ctx.strokeStyle=active?"#60a5fa":hovered?"#93c5fd":"rgba(71,85,105,.42)";
    ctx.lineWidth=active||hovered?1.35:.9;roundRect(left,y,w,h,7);ctx.stroke();
    ctx.fillStyle=hovered?"#17202a":active?"#17202a":"rgba(71,85,105,.58)";
    ctx.textAlign="center";ctx.fillText(label,left+w/2,y+16);
  });
}
function drawIntervalTabs(x,y){
  intervalBoxes=[];
  const labels=[["1m","1m"],["5m","5m"],["15m","15m"],["30m","30m"],["1h","1h"]];
  ctx.font="12px Microsoft YaHei,Arial";
  labels.forEach(([key,label],i)=>{
    const w=40,h=24,left=x+i*(w+6),active=intervalMode===key,hovered=hoverInterval===key;
    intervalBoxes.push({key,x0:left,y0:y,x1:left+w,y1:y+h});
    ctx.strokeStyle=active?"#60a5fa":hovered?"#93c5fd":"rgba(71,85,105,.42)";
    ctx.lineWidth=active||hovered?1.35:.9;roundRect(left,y,w,h,7);ctx.stroke();
    ctx.fillStyle=hovered?"#17202a":active?"#17202a":"rgba(71,85,105,.58)";
    ctx.textAlign="center";ctx.fillText(label,left+w/2,y+16);
  });
}
function drawLegend(x,y,maxX){
  legendBoxes=[];
  const items=[
    {key:"price",label:priceMode==="candle"?"BTC K线":"BTC 价格",color:colors.btc,locked:true,kind:priceMode==="candle"?"candle":"line"},
    {key:"net",label:"净主动成交额",color:colors.buy,locked:true,kind:"bar"},
    {key:"dayCvd",label:"日内累计净主动成交额",color:colors.cvd,locked:true},
    {key:"rangeCvd",label:"区间累计净主动成交额",color:colors.rangeCvd},
  ];
  ctx.font="12px Microsoft YaHei,Arial";
  let cur=x,rowY=y;
  items.forEach(item=>{
    const labelW=ctx.measureText(item.label).width,total=labelW+74;
    if(cur>x&&cur+total>maxX){cur=x;rowY+=20}
    if(!item.locked)legendBoxes.push({key:item.key,x0:cur-5,y0:rowY-12,x1:cur+total-16,y1:rowY+9});
    const off=hidden[item.key];
    ctx.globalAlpha=off?.28:1;ctx.strokeStyle=off?"rgba(82,96,113,.45)":item.color;ctx.fillStyle=off?"rgba(82,96,113,.58)":colors.text;ctx.lineWidth=2;
    if(item.kind==="candle"){ctx.beginPath();ctx.moveTo(cur+8,rowY-8);ctx.lineTo(cur+8,rowY+7);ctx.moveTo(cur+20,rowY-6);ctx.lineTo(cur+20,rowY+8);ctx.stroke();ctx.fillStyle="rgba(255,255,255,.90)";ctx.fillRect(cur+5,rowY-4,7,8);ctx.strokeRect(cur+5,rowY-4,7,8);ctx.fillStyle="rgba(31,119,180,.42)";ctx.fillRect(cur+17,rowY-2,7,7);ctx.strokeRect(cur+17,rowY-2,7,7)}
    else if(item.kind==="line"){ctx.beginPath();ctx.moveTo(cur,rowY+3);ctx.lineTo(cur+9,rowY-3);ctx.lineTo(cur+18,rowY);ctx.lineTo(cur+28,rowY-7);ctx.stroke()}
    else if(item.kind==="bar"){ctx.fillStyle=colors.buy;ctx.fillRect(cur+2,rowY-7,8,14);ctx.fillStyle=colors.sell;ctx.fillRect(cur+14,rowY,8,7);ctx.fillStyle=colors.text}
    else{ctx.beginPath();ctx.moveTo(cur,rowY);ctx.lineTo(cur+28,rowY);ctx.stroke()}
    ctx.fillStyle=off?"rgba(82,96,113,.58)":colors.text;ctx.textAlign="left";ctx.fillText(item.label,cur+36,rowY+4);ctx.globalAlpha=1;cur+=total;
  });
}
function hitBox(list,p){return list.find(b=>p.x>=b.x0&&p.x<=b.x1&&p.y>=b.y0&&p.y<=b.y1)}
function drawPriceLine(){
  ctx.beginPath();let open=false;
  rows.forEach(r=>{const x=xScale(r.t),y=yPrice(r.close);if(!open){ctx.moveTo(x,y);open=true}else ctx.lineTo(x,y)});
  ctx.strokeStyle=colors.btc;ctx.lineWidth=1.15;ctx.stroke();
}
function drawCandles(){
  const count=Math.max(visibleRows().length,1),bodyW=Math.max(.8,Math.min(8,(box.x1-box.x0)/count*.58));
  rows.forEach(r=>{
    const x=xScale(r.t);if(x<box.x0-bodyW||x>box.x1+bodyW)return;
    const yO=yPrice(r.open),yH=yPrice(r.high),yL=yPrice(r.low),yC=yPrice(r.close),top=Math.min(yO,yC),bottom=Math.max(yO,yC),bodyH=Math.max(1,bottom-top);
    ctx.strokeStyle=colors.btc;ctx.fillStyle=r.close>=r.open?colors.candleUpFill:colors.candleDown;ctx.lineWidth=.8;
    ctx.beginPath();ctx.moveTo(x,yH);ctx.lineTo(x,yL);ctx.stroke();ctx.fillRect(x-bodyW/2,top,bodyW,bodyH);ctx.strokeRect(x-bodyW/2,top,bodyW,bodyH);
  });
}
function drawNetBars(){
  const count=Math.max(visibleRows().length,1),barW=Math.max(.8,Math.min(7,(box.x1-box.x0)/count*.62)),zero=yFlow(0);
  rows.forEach(r=>{
    const x=xScale(r.t);if(x<box.x0-barW||x>box.x1+barW)return;
    const y=yFlow(r.netM),top=Math.min(y,zero),h=Math.max(1,Math.abs(y-zero));
    ctx.fillStyle=r.netM>=0?"rgba(22,163,74,.68)":"rgba(220,38,38,.58)";
    ctx.fillRect(x-barW/2,top,barW,h);
  });
  ctx.setLineDash([5,5]);ctx.strokeStyle="rgba(82,96,113,.42)";ctx.beginPath();ctx.moveTo(box.x0,zero);ctx.lineTo(box.x1,zero);ctx.stroke();ctx.setLineDash([]);
}
function drawCvd(key,color,width){
  if(hidden[key])return;
  ctx.beginPath();let open=false;
  rows.forEach(r=>{const v=r[key];if(!finite(v)){open=false;return}const x=xScale(r.t),y=yCvd(v);if(!open){ctx.moveTo(x,y);open=true}else ctx.lineTo(x,y)});
  ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();
}
function drawXLabels(){
  const rangeMs=box.t1-box.t0;
  const step=rangeMs>DAY*2?DAY:rangeMs>DAY?6*60*MINUTE:3*60*MINUTE;
  const start=Math.ceil(box.t0/step)*step;
  ctx.font="11px Microsoft YaHei,Arial";
  for(let t=start;t<=box.t1;t+=step){
    const x=xScale(t);if(x<box.x0||x>box.x1)continue;
    const d=new Date(t),isDay=d.getUTCHours()===0&&d.getUTCMinutes()===0;
    if(isDay){ctx.strokeStyle="rgba(148,163,184,.30)";ctx.beginPath();ctx.moveTo(x,box.priceY0);ctx.lineTo(x,box.flowY1);ctx.stroke()}
    ctx.fillStyle=colors.muted;ctx.textAlign="center";
    const label=step>=DAY?`${String(d.getUTCMonth()+1).padStart(2,"0")}-${String(d.getUTCDate()).padStart(2,"0")}`:`${String(d.getUTCHours()).padStart(2,"0")}:${String(d.getUTCMinutes()).padStart(2,"0")}`;
    ctx.fillText(label,x,box.flowY1+24);
  }
}
function drawAxes(){
  ctx.font="11px Microsoft YaHei,Arial";
  niceTicks(box.priceMin,box.priceMax,6).forEach(v=>{const y=yPrice(v);if(y<box.priceY0||y>box.priceY1)return;gridLine(y);ctx.fillStyle=colors.btc;ctx.textAlign="right";ctx.fillText(fmtUsd(v),box.x0-9,y+4)});
  niceTicks(box.flowMin,box.flowMax,5).forEach(v=>{const y=yFlow(v);if(y<box.flowY0||y>box.flowY1)return;ctx.fillStyle=v>=0?colors.buy:colors.sell;ctx.textAlign="right";ctx.fillText(fmtM(v,0),box.x0-9,y+4)});
  niceTicks(box.cvdMin,box.cvdMax,5).forEach(v=>{const y=yCvd(v);if(y<box.flowY0||y>box.flowY1)return;ctx.fillStyle=colors.cvd;ctx.textAlign="left";ctx.fillText(fmtM(v,0),box.x1+9,y+4)});
}
function draw(active=null){
  refreshRows();
  const w=canvas.clientWidth,h=canvas.clientHeight,compact=w<760,outer=Math.round(Math.min(w,h)*.035);
  const axisLeft=82,axisRight=92,x0=outer+axisLeft,x1=w-outer-axisRight,titleY=outer+14,controlY=titleY+(compact?18:22),legendY=titleY+(compact?92:64);
  const y0=legendY+(compact?48:38),bottom=h-outer-(isEmbed?34:38),gap=16,priceH=Math.max(170,(bottom-y0-gap)*.58);
  const priceY0=y0,priceY1=y0+priceH,flowY0=priceY1+gap,flowY1=bottom;
  const [t0,t1]=currentRange(),sample=visibleRows(),[pMin0,pMax0]=rangeExtent(["open","high","low","close"],sample),pPad=Math.max((pMax0-pMin0)*.08,10);
  const [netMin0,netMax0]=rangeExtent(["netM"],sample),netAbs=Math.max(Math.abs(netMin0),Math.abs(netMax0),1),[cvdMin0,cvdMax0]=rangeExtent(hidden.rangeCvd?["dayCvd"]:["dayCvd","rangeCvd"],sample),cvdPad=Math.max((cvdMax0-cvdMin0)*.16,1);
  box={x0,x1,priceY0,priceY1,flowY0,flowY1,t0,t1,priceMin:pMin0-pPad,priceMax:pMax0+pPad,flowMin:-netAbs*1.15,flowMax:netAbs*1.15,cvdMin:cvdMin0-cvdPad,cvdMax:cvdMax0+cvdPad};
  ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);
  ctx.fillStyle=colors.text;ctx.font="700 21px Microsoft YaHei,Arial";ctx.textAlign="center";ctx.fillText("BTC 日内主动成交与价格",w/2,titleY);
  const rangeGroupW=224,intervalGroupW=224,modeGroupW=74,rangeX=compact?x0:x1-rangeGroupW,intervalX=compact?x0:rangeX-intervalGroupW-10,modeX=compact?x0:intervalX-modeGroupW-10,rangeY=compact?controlY+30:controlY,intervalY=controlY;
  drawModeTabs(modeX,controlY);drawIntervalTabs(intervalX,intervalY);drawRangeTabs(rangeX,rangeY);
  drawLegend(x0,legendY,x1);
  drawAxes();drawXLabels();
  ctx.strokeStyle="#cfd8e2";ctx.strokeRect(x0,priceY0,x1-x0,priceY1-priceY0);ctx.strokeRect(x0,flowY0,x1-x0,flowY1-flowY0);
  ctx.save();ctx.beginPath();ctx.rect(x0,priceY0,x1-x0,priceY1-priceY0);ctx.clip();priceMode==="candle"?drawCandles():drawPriceLine();ctx.restore();
  ctx.save();ctx.beginPath();ctx.rect(x0,flowY0,x1-x0,flowY1-flowY0);ctx.clip();drawNetBars();drawCvd("dayCvd",colors.cvd,1.45);drawCvd("rangeCvd",colors.rangeCvd,1.2);ctx.restore();
  ctx.fillStyle=colors.btc;ctx.textAlign="center";ctx.save();ctx.translate(x0-56,(priceY0+priceY1)/2);ctx.rotate(-Math.PI/2);ctx.fillText("BTCUSDT 价格",0,0);ctx.restore();
  ctx.fillStyle=colors.cvd;ctx.save();ctx.translate(x1+58,(flowY0+flowY1)/2);ctx.rotate(Math.PI/2);ctx.fillText("累计净主动成交额",0,0);ctx.restore();
  ctx.fillStyle=colors.muted;ctx.textAlign="left";ctx.font="11px Microsoft YaHei,Arial";ctx.fillText("Binance 日界线：UTC+0 00:00",x0,flowY1+36);
  if(active!=null){const r=rows[active],x=xScale(r.t);ctx.setLineDash([5,5]);ctx.strokeStyle="rgba(82,96,113,.62)";ctx.beginPath();ctx.moveTo(x,priceY0);ctx.lineTo(x,flowY1);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle="#fff";ctx.strokeStyle=colors.btc;ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,yPrice(r.close),3.3,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.strokeStyle=colors.cvd;ctx.beginPath();ctx.arc(x,yCvd(r.dayCvd),3.3,0,Math.PI*2);ctx.fill();ctx.stroke()}
}
function pointer(e){const rect=canvas.getBoundingClientRect();return{x:e.clientX-rect.left,y:e.clientY-rect.top,rect}}
function inPlot(p){return p.x>=box.x0&&p.x<=box.x1&&p.y>=box.priceY0&&p.y<=box.flowY1}
function clampX(x){return Math.max(box.x0,Math.min(box.x1,x))}
function timeAtX(x){return box.t0+(clampX(x)-box.x0)/(box.x1-box.x0)*(box.t1-box.t0)}
function nearest(mx){const t=timeAtX(mx);let l=0,r=rows.length-1;while(l<r){const m=(l+r)>>1;if(rows[m].t<t)l=m+1;else r=m}if(l>0&&Math.abs(rows[l-1].t-t)<Math.abs(rows[l].t-t))l--;return l}
function clearTip(){tip.style.display="none"}
function positionTip(p){
  const margin=8,gap=14,w=tip.offsetWidth||280,h=tip.offsetHeight||160,rightLimit=Math.min(p.rect.width-margin,box.x1-8);
  let left=p.x+gap;if(left+w>rightLimit)left=p.x-w-gap;left=Math.max(margin,Math.min(left,Math.max(margin,rightLimit-w)));
  let top=p.y-88;top=Math.max(margin,Math.min(top,Math.max(margin,p.rect.height-margin-h)));
  tip.style.left=left+"px";tip.style.top=top+"px";
}
function showTip(p){
  if(!inPlot(p)){clearTip();draw();return}
  const i=nearest(p.x),r=rows[i];draw(i);
  tip.innerHTML=`<b>${fmtTime(r.t)}　${intervalMode}</b><br>开 ${fmtUsd(r.open,2)} / 高 ${fmtUsd(r.high,2)} / 低 ${fmtUsd(r.low,2)} / 收 ${fmtUsd(r.close,2)}<br>净主动成交额：${fmtM(r.netM,2)}<br>主动买入：${fmtM(r.takerBuyM,2)}　主动卖出：${fmtM(r.takerSellM,2)}<br>日内累计净主动成交额：${fmtM(r.dayCvdM,2)}<br>区间累计净主动成交额：${fmtM(r.rangeCvdM,2)}<br>成交额：${fmtB(r.quoteVolumeM,3)}　主动买入占比：${r.buyRatio==null?"-":r.buyRatio.toFixed(1)+"%"}`;
  tip.style.display="block";positionTip(p);
}
function drawSelection(){if(!drag)return;const x0=clampX(drag.x0),x1=clampX(drag.x1),left=Math.min(x0,x1),width=Math.abs(x1-x0);if(width<3)return;ctx.fillStyle="rgba(37,99,235,.09)";ctx.strokeStyle="rgba(37,99,235,.42)";ctx.fillRect(left,box.priceY0,width,box.flowY1-box.priceY0);ctx.strokeRect(left,box.priceY0,width,box.flowY1-box.priceY0)}
canvas.addEventListener("click",e=>{const p=pointer(e),mode=hitBox(modeBoxes,p),range=hitBox(rangeBoxes,p),interval=hitBox(intervalBoxes,p),legend=hitBox(legendBoxes,p);if(mode){priceMode=mode.key;hoverMode=mode.key;clearTip();draw();return}if(interval){intervalMode=interval.key;zoom=null;hoverInterval=interval.key;clearTip();draw();return}if(range){rangeMode=range.key;zoom=null;hoverRange=range.key;clearTip();draw();return}if(legend){hidden[legend.key]=!hidden[legend.key];clearTip();draw()}});
canvas.addEventListener("mousedown",e=>{const p=pointer(e);if(hitBox(modeBoxes,p)||hitBox(rangeBoxes,p)||hitBox(intervalBoxes,p)||hitBox(legendBoxes,p)||!inPlot(p))return;drag={x0:p.x,x1:p.x};clearTip()});
canvas.addEventListener("mousemove",e=>{const p=pointer(e);if(drag){drag.x1=p.x;clearTip();draw();drawSelection();return}const mode=hitBox(modeBoxes,p),range=hitBox(rangeBoxes,p),interval=hitBox(intervalBoxes,p);if(mode){hoverMode=mode.key;canvas.style.cursor="pointer";clearTip();draw();return}if(interval){hoverInterval=interval.key;canvas.style.cursor="pointer";clearTip();draw();return}if(range){hoverRange=range.key;canvas.style.cursor="pointer";clearTip();draw();return}if(hoverMode||hoverRange||hoverInterval){hoverMode=null;hoverRange=null;hoverInterval=null;canvas.style.cursor="crosshair";draw()}showTip(p)});
window.addEventListener("mouseup",()=>{if(!drag)return;const x0=clampX(drag.x0),x1=clampX(drag.x1);if(Math.abs(x1-x0)>12){const a=timeAtX(x0),b=timeAtX(x1);zoom=[Math.min(a,b),Math.max(a,b)]}drag=null;clearTip();draw()});
canvas.addEventListener("mouseleave",()=>{if(drag)return;hoverMode=null;hoverRange=null;hoverInterval=null;clearTip();draw()});
canvas.addEventListener("dblclick",()=>{zoom=null;drag=null;clearTip();draw()});
footerNote.innerHTML=`<span>刷新时间：UTC+8 ${P.generatedAt}</span><span>数据来源：${P.source}</span><span>默认最近24小时，日界线 UTC+0</span>`;
window.addEventListener("resize",resize);
resize();
</script>
</body>
</html>
"""
    html_text = add_canvas_mobile_support(html_text)
    output_html.write_text(html_text.replace("__PAYLOAD__", payload), encoding="utf-8")
