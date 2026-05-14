from __future__ import annotations

import json
import math
import time
from datetime import date, datetime, timezone
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd


START_DATE = date(2017, 11, 29)
END_DATE = date.today()
BTC_SOURCE = "https://min-api.cryptocompare.com/data/v2/histoday"
USDT_SOURCE = "https://stablecoins.llama.fi/stablecoincharts/all"
PERIODS = [30, 180, 270, 360, 1080]


def request_json(url: str, retries: int = 4, pause: float = 1.0) -> object:
    last_error: Exception | None = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Connection": "close",
                "User-Agent": "Mozilla/5.0",
            },
        )
        try:
            with urlopen(req, timeout=45) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except (HTTPError, URLError, TimeoutError, IncompleteRead, RemoteDisconnected, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"Request failed: {url}") from last_error


def to_timestamp(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def fetch_btc_price(start: date, end: date) -> pd.Series:
    rows: list[dict[str, object]] = []
    to_ts = to_timestamp(end)
    start_ts = to_timestamp(start)

    while to_ts >= start_ts:
        query = urlencode({"fsym": "BTC", "tsym": "USD", "limit": 2000, "toTs": to_ts})
        payload = request_json(f"{BTC_SOURCE}?{query}")
        data = payload.get("Data", {}).get("Data", []) if isinstance(payload, dict) else []
        if not data:
            break
        rows.extend(data)
        earliest = min(int(item["time"]) for item in data)
        if earliest <= start_ts:
            break
        to_ts = earliest - 86400
        time.sleep(0.2)

    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["time"], unit="s", utc=True).dt.tz_localize(None).dt.normalize()
    frame["BTC"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.loc[(frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end)), ["date", "BTC"]]
    return frame.drop_duplicates("date").sort_values("date").set_index("date")["BTC"]


def fetch_usdt_market_cap(start: date, end: date) -> pd.Series:
    payload = request_json(f"{USDT_SOURCE}?{urlencode({'stablecoin': 1})}")
    if not isinstance(payload, list):
        raise RuntimeError("USDT payload has unexpected shape")

    rows: list[dict[str, object]] = []
    for item in payload:
        current_date = datetime.fromtimestamp(int(item["date"]), timezone.utc).replace(tzinfo=None).date()
        value = (
            item.get("totalCirculatingUSD", {}).get("peggedUSD")
            or item.get("totalCirculating", {}).get("peggedUSD")
        )
        rows.append({"date": pd.Timestamp(current_date), "USDT": value})

    frame = pd.DataFrame(rows)
    frame["USDT"] = pd.to_numeric(frame["USDT"], errors="coerce")
    frame = frame.loc[(frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end)), ["date", "USDT"]]
    return frame.drop_duplicates("date").sort_values("date").set_index("date")["USDT"]


def estimate_btc_supply(ts: pd.Timestamp) -> float:
    genesis = pd.Timestamp("2009-01-03")
    blocks = max((ts.normalize() - genesis).days, 0) * 144
    remaining = blocks
    subsidy = 50.0
    supply = 0.0

    while remaining > 0 and subsidy > 0:
        block_count = min(remaining, 210_000)
        supply += block_count * subsidy
        remaining -= block_count
        subsidy /= 2
    return min(supply, 21_000_000.0)


def rolling_zscore(series: pd.Series, window: int = 720, min_periods: int = 180) -> pd.Series:
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std()
    return (series - mean) / std.replace(0, np.nan)


def state_from_score(score: float) -> str:
    if score > 0.75:
        return "偏多"
    if score > 0.25:
        return "轻仓偏多"
    if score >= -0.25:
        return "中性"
    if score >= -0.75:
        return "回避做多"
    return "偏空/对冲"


def build_indicator_frame(cache_path: Path | None = None) -> pd.DataFrame:
    try:
        btc = fetch_btc_price(START_DATE, END_DATE)
        usdt = fetch_usdt_market_cap(START_DATE, END_DATE)
    except Exception:
        if cache_path and cache_path.exists():
            return pd.read_csv(cache_path, parse_dates=["date"])
        raise

    index = pd.date_range(START_DATE, END_DATE, freq="D")
    data = pd.DataFrame(index=index)
    data = data.join(btc.rename("BTC")).join(usdt.rename("USDT"))
    data[["BTC", "USDT"]] = data[["BTC", "USDT"]].ffill()
    data = data.dropna(subset=["BTC", "USDT"])
    data.index.name = "date"

    data["btc_supply_est"] = [estimate_btc_supply(ts) for ts in data.index]
    data["btc_market_cap_est"] = data["BTC"] * data["btc_supply_est"]
    rolling_min = data["BTC"].rolling(360, min_periods=90).min()
    rolling_max = data["BTC"].rolling(360, min_periods=90).max()
    data["price_pos_360"] = ((data["BTC"] - rolling_min) / (rolling_max - rolling_min)).clip(0, 1)

    components = []
    weights = {30: 3.154866, 180: 22.162403, 270: 44.205568, 360: 58.458749, 1080: 64.851744}
    for period in PERIODS:
        delta = data["USDT"] - data["USDT"].shift(period)
        speed = delta / 1e9
        intensity = delta / data["btc_market_cap_est"] * 10_000
        change = intensity - intensity.shift(period)
        data[f"usdt_speed_{period}d_b"] = speed
        data[f"usdt_speed_intensity_{period}d_bps"] = intensity
        data[f"usdt_speed_change_{period}d_bps"] = change
        data[f"component_{period}d"] = 0.55 * rolling_zscore(intensity) + 0.45 * rolling_zscore(change)
        components.append((period, data[f"component_{period}d"]))

    signal = pd.Series(0.0, index=data.index)
    available_weight = pd.Series(0.0, index=data.index)
    total_weight = sum(max(weights[period], 0.1) for period in PERIODS)
    for period, component in components:
        weight = max(weights[period], 0.1) / total_weight
        valid = component.notna()
        signal.loc[valid] += component.loc[valid] * weight
        available_weight.loc[valid] += weight

    data["usdt_raw_signal"] = signal / available_weight.replace(0, np.nan)
    data["price_level_need"] = ((data["price_pos_360"] - 0.5) * 1.25).fillna(0)
    data["long_short_score"] = (data["usdt_raw_signal"] - data["price_level_need"]).clip(-3, 3)
    data["long_short_score_smooth"] = data["long_short_score"].ewm(span=7, adjust=False).mean()
    data["state"] = data["long_short_score_smooth"].map(lambda value: state_from_score(float(value)) if pd.notna(value) else "")
    return data.reset_index()


def chart_meta(data: pd.DataFrame) -> dict:
    clean = data.dropna(subset=["long_short_score_smooth"]).copy()
    latest = clean.iloc[-1]
    return {
        "latestDate": str(latest["date"].date()),
        "btc": round(float(latest["BTC"]), 2),
        "usdt": round(float(latest["USDT"]) / 1e9, 2),
        "score": round(float(latest["long_short_score_smooth"]), 3),
        "state": str(latest["state"]),
        "speed30": round(float(latest["usdt_speed_30d_b"]), 2),
        "speed180": round(float(latest["usdt_speed_180d_b"]), 2),
        "speed360": round(float(latest["usdt_speed_360d_b"]), 2),
        "metrics": [
            {"label": "状态", "value": str(latest["state"])},
            {"label": "多空分数", "value": f"{float(latest['long_short_score_smooth']):.3f}"},
            {"label": "BTC", "value": f"${float(latest['BTC']):,.0f}"},
            {"label": "USDT", "value": f"${float(latest['USDT']) / 1e9:.2f}B"},
        ],
    }


def write_interactive_html(data: pd.DataFrame, output_html: Path) -> None:
    meta = chart_meta(data)
    clean = data.dropna(subset=["long_short_score_smooth"]).copy()
    records = []
    for row in clean.itertuples(index=False):
        records.append(
            {
                "date": row.date.strftime("%Y-%m-%d"),
                "btc": round(float(row.BTC), 2),
                "score": round(float(row.long_short_score_smooth), 4),
                "state": str(row.state),
                "s30": None if pd.isna(row.usdt_speed_30d_b) else round(float(row.usdt_speed_30d_b), 3),
                "s180": None if pd.isna(row.usdt_speed_180d_b) else round(float(row.usdt_speed_180d_b), 3),
                "s360": None if pd.isna(row.usdt_speed_360d_b) else round(float(row.usdt_speed_360d_b), 3),
                "s1080": None if pd.isna(row.usdt_speed_1080d_b) else round(float(row.usdt_speed_1080d_b), 3),
            }
        )

    payload = json.dumps({"rows": records, "meta": meta}, ensure_ascii=False, separators=(",", ":"))
    html_text = """
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BTC 与 USDT 速度多空指标</title><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#fff;color:#17202a;font-family:"Microsoft YaHei",Arial,sans-serif}.page{position:relative;width:100vw;height:100vh;background:#fff}canvas{display:block;width:100vw;height:100vh}.tip{position:absolute;display:none;pointer-events:none;min-width:210px;background:rgba(255,255,255,.72);border:1px solid rgba(120,129,145,.42);border-radius:6px;color:#17202a;padding:9px 10px;font-size:12px;line-height:1.65;box-shadow:0 8px 22px rgba(15,23,42,.12);backdrop-filter:blur(2px)}</style></head><body><div class="page"><canvas id="chart"></canvas><div class="tip" id="tip"></div></div><script>
const P=__PAYLOAD__,rows=P.rows.map(r=>({...r,t:new Date(r.date).getTime()})),canvas=document.getElementById("chart"),ctx=canvas.getContext("2d"),tip=document.getElementById("tip");let box={};function usd(v){return "$"+Math.round(v).toLocaleString("en-US")}function fmt(v,d=2){return v==null?"-":Number(v).toFixed(d)}function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}function range(a){return[Math.min(...a),Math.max(...a)]}function xScale(t){return box.x0+(t-box.t0)/(box.t1-box.t0)*(box.x1-box.x0)}function yPrice(v){return box.py1-(Math.log(v)-box.pmin)/(box.pmax-box.pmin)*(box.py1-box.py0)}function yScore(v){return box.sy1-(v+3)/6*(box.sy1-box.sy0)}function path(key,scale,color,width){ctx.beginPath();rows.forEach((r,i)=>{const x=xScale(r.t),y=scale(r[key]);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y)});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke()}function gridY(ticks,scale,x0,x1,color,labelColor){ctx.font="12px Microsoft YaHei,Arial";ticks.forEach(v=>{const y=scale(v);ctx.strokeStyle=color;ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(x0,y);ctx.lineTo(x1,y);ctx.stroke();ctx.fillStyle=labelColor;ctx.textAlign="right";ctx.fillText(v>1000?usd(v):String(v),x0-9,y+4)})}function draw(active){const w=canvas.clientWidth,h=canvas.clientHeight,p={l:78,r:26,t:60,b:44,g:24},ph=(h-p.t-p.b-p.g)*.68,sh=(h-p.t-p.b-p.g)-ph,x0=p.l,x1=w-p.r,py0=p.t,py1=p.t+ph,sy0=py1+p.g,sy1=sy0+sh,[priceMin,priceMax]=range(rows.map(r=>r.btc)),t0=rows[0].t,t1=rows[rows.length-1].t;box={x0,x1,py0,py1,sy0,sy1,t0,t1,pmin:Math.log(priceMin*.82),pmax:Math.log(priceMax*1.12)};ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);ctx.fillStyle="#17202a";ctx.font="700 21px Microsoft YaHei,Arial";ctx.textAlign="center";ctx.fillText("BTC 与 USDT 速度多空指标",w/2,30);ctx.fillStyle="rgba(36,160,100,.13)";ctx.fillRect(x0,yScore(3),x1-x0,yScore(.75)-yScore(3));ctx.fillStyle="rgba(200,62,62,.13)";ctx.fillRect(x0,yScore(-.75),x1-x0,yScore(-3)-yScore(-.75));const startY=new Date(t0).getUTCFullYear(),endY=new Date(t1).getUTCFullYear();for(let y=startY;y<=endY;y++){const x=xScale(new Date(`${y}-01-01T00:00:00Z`).getTime());if(x<x0||x>x1)continue;ctx.strokeStyle="#e5ebf1";ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(x,py0);ctx.lineTo(x,sy1);ctx.stroke();ctx.fillStyle="#526071";ctx.font="12px Microsoft YaHei,Arial";ctx.textAlign="center";ctx.fillText(y,x,sy1+25)}gridY([3000,10000,30000,100000].filter(v=>v>=priceMin*.82&&v<=priceMax*1.12),yPrice,x0,x1,"#dfe6ed","#526071");gridY([-3,-2,-1,0,1,2,3],yScore,x0,x1,"#dfe6ed","#526071");[.75,-.75].forEach(v=>{ctx.setLineDash([5,5]);ctx.strokeStyle=v>0?"#24a064":"#c83e3e";ctx.beginPath();ctx.moveTo(x0,yScore(v));ctx.lineTo(x1,yScore(v));ctx.stroke();ctx.setLineDash([])});ctx.strokeStyle="#cfd8e2";ctx.strokeRect(x0,py0,x1-x0,py1-py0);ctx.strokeRect(x0,sy0,x1-x0,sy1-sy0);path("btc",yPrice,"#3569c8",1.25);path("score",yScore,"#111827",1.05);ctx.fillStyle="#17202a";ctx.font="12px Microsoft YaHei,Arial";ctx.textAlign="left";ctx.fillText(`最新：${P.meta.latestDate}  ${P.meta.state}  分数 ${fmt(P.meta.score,3)}  BTC ${usd(P.meta.btc)}  USDT $${fmt(P.meta.usdt,2)}B`,x0,py0-18);ctx.strokeStyle="#3569c8";ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(x0+18,py0+20);ctx.lineTo(x0+44,py0+20);ctx.stroke();ctx.fillText("BTC",x0+52,py0+24);ctx.strokeStyle="#111827";ctx.beginPath();ctx.moveTo(x0+108,py0+20);ctx.lineTo(x0+134,py0+20);ctx.stroke();ctx.fillText("USDT score",x0+142,py0+24);if(active!=null){const r=rows[active],x=xScale(r.t);ctx.setLineDash([5,5]);ctx.strokeStyle="rgba(82,96,113,.6)";ctx.beginPath();ctx.moveTo(x,py0);ctx.lineTo(x,py1);ctx.moveTo(x,sy0);ctx.lineTo(x,sy1);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle="#fff";ctx.strokeStyle="#3569c8";ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,yPrice(r.btc),4,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.strokeStyle="#111827";ctx.beginPath();ctx.arc(x,yScore(r.score),4,0,Math.PI*2);ctx.fill();ctx.stroke()}}function nearest(mx){const t=box.t0+(mx-box.x0)/(box.x1-box.x0)*(box.t1-box.t0);let l=0,r=rows.length-1;while(l<r){const m=(l+r)>>1;if(rows[m].t<t)l=m+1;else r=m}if(l>0&&Math.abs(rows[l-1].t-t)<Math.abs(rows[l].t-t))l--;return l}canvas.addEventListener("mousemove",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(x<box.x0||x>box.x1||y<box.py0||y>box.sy1){tip.style.display="none";draw();return}const i=nearest(x),r=rows[i];draw(i);tip.innerHTML=`<b>${r.date}</b><br>BTC：${usd(r.btc)}<br>分数：${fmt(r.score,3)}，${r.state}<br>30D：${fmt(r.s30)}B<br>180D：${fmt(r.s180)}B<br>360D：${fmt(r.s360)}B<br>1080D：${fmt(r.s1080)}B`;tip.style.display="block";tip.style.left=Math.min(rect.width-238,Math.max(8,x+14))+"px";tip.style.top=Math.max(8,Math.min(rect.height-150,y-64))+"px"});canvas.addEventListener("mouseleave",()=>{tip.style.display="none";draw()});window.addEventListener("resize",resize);resize();
</script></body></html>
"""
    output_html.write_text("".join(line.strip() for line in html_text.replace("__PAYLOAD__", payload).splitlines()), encoding="utf-8")
