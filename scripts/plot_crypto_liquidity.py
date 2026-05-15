from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


START_DATE = date(2015, 8, 7)
END_DATE = date.today()
PRICE_SOURCE = "https://min-api.cryptocompare.com/data/v2/histoday"
STABLECOIN_SOURCE = "https://stablecoins.llama.fi/stablecoincharts/all"


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


def fetch_price(symbol: str, column: str, start: date, end: date) -> pd.Series:
    rows: list[dict[str, object]] = []
    to_ts = to_timestamp(end)
    start_ts = to_timestamp(start)

    while to_ts >= start_ts:
        query = urlencode({"fsym": symbol, "tsym": "USD", "limit": 2000, "toTs": to_ts})
        payload = request_json(f"{PRICE_SOURCE}?{query}")
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
    frame[column] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame[frame[column] > 0]
    frame = frame.loc[(frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end)), ["date", column]]
    return frame.drop_duplicates("date").sort_values("date").set_index("date")[column]


def fetch_stablecoin_supply(stablecoin_id: int, column: str, start: date, end: date) -> pd.Series:
    payload = request_json(f"{STABLECOIN_SOURCE}?{urlencode({'stablecoin': stablecoin_id})}")
    if not isinstance(payload, list):
        raise RuntimeError(f"{column} payload has unexpected shape")

    rows: list[dict[str, object]] = []
    for item in payload:
        current_date = datetime.fromtimestamp(int(item["date"]), timezone.utc).replace(tzinfo=None).date()
        value = (
            item.get("totalCirculatingUSD", {}).get("peggedUSD")
            or item.get("totalCirculating", {}).get("peggedUSD")
        )
        rows.append({"date": pd.Timestamp(current_date), column: value})

    frame = pd.DataFrame(rows)
    frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.loc[(frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end)), ["date", column]]
    return frame.drop_duplicates("date").sort_values("date").set_index("date")[column]


def build_indicator_frame(cache_path: Path | None = None) -> pd.DataFrame:
    try:
        btc = fetch_price("BTC", "BTC", START_DATE, END_DATE)
        eth = fetch_price("ETH", "ETH", START_DATE, END_DATE)
        usdt = fetch_stablecoin_supply(1, "USDT", START_DATE, END_DATE)
        usdc = fetch_stablecoin_supply(2, "USDC", START_DATE, END_DATE)
    except Exception:
        if cache_path and cache_path.exists():
            return pd.read_csv(cache_path, parse_dates=["date"])
        raise

    index = pd.date_range(START_DATE, END_DATE, freq="D")
    data = pd.DataFrame(index=index)
    data = data.join(btc).join(eth).join(usdt).join(usdc)
    for column in ["BTC", "ETH", "USDT", "USDC"]:
        data[column] = data[column].ffill()

    data["usdt_b"] = data["USDT"] / 1e9
    data["usdc_b"] = data["USDC"] / 1e9
    for window in [5, 30, 60]:
        data[f"usdt_ma_{window}d_b"] = data["usdt_b"].rolling(window, min_periods=1).mean()

    data.index.name = "date"
    return data.reset_index()


def first_valid_date(data: pd.DataFrame, column: str) -> str:
    valid = data.dropna(subset=[column])
    if valid.empty:
        return "-"
    return str(valid.iloc[0]["date"].date())


def latest_valid(data: pd.DataFrame, column: str) -> pd.Series:
    valid = data.dropna(subset=[column])
    if valid.empty:
        raise RuntimeError(f"{column} has no data")
    return valid.iloc[-1]


def chart_meta(data: pd.DataFrame) -> dict:
    latest_btc = latest_valid(data, "BTC")
    latest_eth = latest_valid(data, "ETH")
    latest_usdt = latest_valid(data, "USDT")
    latest_usdc = latest_valid(data, "USDC")
    usdt_start = first_valid_date(data, "USDT")
    usdc_start = first_valid_date(data, "USDC")
    btc_start = first_valid_date(data, "BTC")
    eth_start = first_valid_date(data, "ETH")
    return {
        "latestDate": str(max(latest_btc["date"], latest_usdt["date"]).date()),
        "btc": round(float(latest_btc["BTC"]), 2),
        "eth": round(float(latest_eth["ETH"]), 2),
        "usdt": round(float(latest_usdt["USDT"]) / 1e9, 2),
        "usdc": round(float(latest_usdc["USDC"]) / 1e9, 2),
        "dataNote": f"BTC/ETH 行情从 {btc_start}/{eth_start} 开始；USDT/USDC 发行量从 {usdt_start}/{usdc_start} 开始。DefiLlama 暂无更早 USDT/USDC 日频记录。",
        "metrics": [
            {"label": "BTC", "value": f"${float(latest_btc['BTC']):,.0f}", "date": str(latest_btc["date"].date())},
            {"label": "ETH", "value": f"${float(latest_eth['ETH']):,.0f}", "date": str(latest_eth["date"].date())},
            {"label": "USDT发行量", "value": f"${float(latest_usdt['USDT']) / 1e9:.2f}B", "date": str(latest_usdt["date"].date())},
            {"label": "USDC发行量", "value": f"${float(latest_usdc['USDC']) / 1e9:.2f}B", "date": str(latest_usdc["date"].date())},
        ],
    }


def series_value(value: object, digits: int = 4) -> float | None:
    if pd.isna(value):
        return None
    return round(float(value), digits)


def write_interactive_html(data: pd.DataFrame, output_html: Path) -> None:
    meta = chart_meta(data)
    records = []
    for row in data.itertuples(index=False):
        records.append(
            {
                "date": row.date.strftime("%Y-%m-%d"),
                "btc": series_value(row.BTC, 2),
                "eth": series_value(row.ETH, 2),
                "usdt": series_value(row.usdt_b, 4),
                "usdc": series_value(row.usdc_b, 4),
                "ma5": series_value(row.usdt_ma_5d_b, 4),
                "ma30": series_value(row.usdt_ma_30d_b, 4),
                "ma60": series_value(row.usdt_ma_60d_b, 4),
            }
        )

    payload = json.dumps({"rows": records, "meta": meta}, ensure_ascii=False, separators=(",", ":"))
    html_text = """
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BTC/ETH 与 USDT/USDC 发行量</title><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#fff;color:#17202a;font-family:"Microsoft YaHei",Arial,sans-serif}.page{position:relative;width:100vw;height:100vh;background:#fff}canvas{display:block;width:100vw;height:100vh}.tip{position:absolute;display:none;pointer-events:none;min-width:230px;background:rgba(255,255,255,.68);border:1px solid rgba(120,129,145,.42);border-radius:6px;color:#17202a;padding:9px 10px;font-size:12px;line-height:1.65;box-shadow:0 8px 22px rgba(15,23,42,.12);backdrop-filter:blur(2px)}</style></head><body><div class="page"><canvas id="chart"></canvas><div class="tip" id="tip"></div></div><script>
const P=__PAYLOAD__,rows=P.rows.map(r=>({...r,t:new Date(r.date).getTime()})),canvas=document.getElementById("chart"),ctx=canvas.getContext("2d"),tip=document.getElementById("tip");const colors={btc:"#4472C4",eth:"#A5A5A5",usdt:"#ED7D31",usdc:"#FFC000",grid:"#dfe6ed",text:"#17202a",muted:"#526071"};let box={};function usd(v,d=0){return v==null?"-":"$"+Number(v).toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d})}function b(v){return v==null?"-":Number(v).toFixed(2)+"B"}function values(key){return rows.map(r=>r[key]).filter(v=>v!=null&&Number.isFinite(v))}function extent(keys){const a=keys.flatMap(k=>values(k));return[Math.min(...a),Math.max(...a)]}function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}function xScale(t){return box.x0+(t-box.t0)/(box.t1-box.t0)*(box.x1-box.x0)}function yLog(v){return box.mainY1-(Math.log(v)-box.priceMin)/(box.priceMax-box.priceMin)*(box.mainY1-box.mainY0)}function ySupply(v){return box.mainY1-(v-box.supplyMin)/(box.supplyMax-box.supplyMin)*(box.mainY1-box.mainY0)}function ySub(v,pane){return pane.y1-(v-pane.min)/(pane.max-pane.min)*(pane.y1-pane.y0)}function path(key,scale,color,width,pane){ctx.beginPath();let open=false;rows.forEach(r=>{const v=r[key];if(v==null||!Number.isFinite(v)){open=false;return}const x=xScale(r.t),y=scale(v,pane);if(!open){ctx.moveTo(x,y);open=true}else ctx.lineTo(x,y)});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke()}function gridLine(y,x0,x1){ctx.strokeStyle=colors.grid;ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(x0,y);ctx.lineTo(x1,y);ctx.stroke()}function drawLegend(x,y){const items=[["btc",colors.btc,"BTC"],["eth",colors.eth,"ETH"],["usdt",colors.usdt,"USDT发行量"],["usdc",colors.usdc,"USDC发行量"]];ctx.font="12px Microsoft YaHei,Arial";let cur=x;items.forEach(([key,color,label])=>{ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(cur,y);ctx.lineTo(cur+28,y);ctx.stroke();ctx.fillStyle=colors.text;ctx.textAlign="left";ctx.fillText(label,cur+36,y+4);cur+=ctx.measureText(label).width+74})}function draw(active){const w=canvas.clientWidth,h=canvas.clientHeight,p={l:78,r:88,t:78,b:40,g:12},usable=h-p.t-p.b-p.g*3,mainH=usable*.52,subH=(usable-mainH)/3,x0=p.l,x1=w-p.r,mainY0=p.t,mainY1=p.t+mainH;const panes=[{key:"ma5",title:"USDT发行量 5日均线",y0:mainY1+p.g,y1:mainY1+p.g+subH},{key:"ma30",title:"USDT发行量 30日均线",y0:mainY1+p.g*2+subH,y1:mainY1+p.g*2+subH*2},{key:"ma60",title:"USDT发行量 60日均线",y0:mainY1+p.g*3+subH*2,y1:mainY1+p.g*3+subH*3}];const [priceMin0,priceMax0]=extent(["btc","eth"]),[supplyMin0,supplyMax0]=extent(["usdt","usdc"]);box={x0,x1,mainY0,mainY1,t0:rows[0].t,t1:rows[rows.length-1].t,priceMin:Math.log(priceMin0*.75),priceMax:Math.log(priceMax0*1.18),supplyMin:0,supplyMax:supplyMax0*1.1,panes};panes.forEach(pane=>{const [mn,mx]=extent([pane.key]);pane.min=Math.max(0,mn*.98);pane.max=mx*1.02});ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);ctx.fillStyle=colors.text;ctx.font="700 21px Microsoft YaHei,Arial";ctx.textAlign="center";ctx.fillText("BTC/ETH 与 USDT/USDC 发行量",w/2,24);ctx.font="12px Microsoft YaHei,Arial";ctx.fillStyle=colors.muted;ctx.textAlign="left";ctx.fillText(`${P.meta.latestDate}  BTC ${usd(P.meta.btc)}  ETH ${usd(P.meta.eth)}  USDT ${b(P.meta.usdt)}  USDC ${b(P.meta.usdc)}`,x0,44);drawLegend(x0,62);const startY=new Date(box.t0).getUTCFullYear(),endY=new Date(box.t1).getUTCFullYear();for(let y=startY;y<=endY;y++){const x=xScale(new Date(`${y}-01-01T00:00:00Z`).getTime());if(x<x0||x>x1)continue;ctx.strokeStyle="#edf2f7";ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(x,mainY0);ctx.lineTo(x,panes[2].y1);ctx.stroke();ctx.fillStyle=colors.muted;ctx.textAlign="center";ctx.fillText(y,x,panes[2].y1+25)}[10,100,1000,10000,100000].forEach(v=>{if(Math.log(v)<box.priceMin||Math.log(v)>box.priceMax)return;const y=yLog(v);gridLine(y,x0,x1);ctx.fillStyle=colors.btc;ctx.textAlign="right";ctx.fillText(usd(v),x0-9,y+4)});[0,50,100,150,200,250].forEach(v=>{if(v>box.supplyMax)return;const y=ySupply(v);ctx.fillStyle="#6b7280";ctx.textAlign="left";ctx.fillText("$"+v+"B",x1+9,y+4)});ctx.strokeStyle="#cfd8e2";ctx.strokeRect(x0,mainY0,x1-x0,mainY1-mainY0);path("btc",(v)=>yLog(v),colors.btc,1.15);path("eth",(v)=>yLog(v),colors.eth,1.05);path("usdt",(v)=>ySupply(v),colors.usdt,1.15);path("usdc",(v)=>ySupply(v),colors.usdc,1.15);ctx.fillStyle=colors.btc;ctx.textAlign="center";ctx.save();ctx.translate(24,(mainY0+mainY1)/2);ctx.rotate(-Math.PI/2);ctx.fillText("BTC / ETH（log USD）",0,0);ctx.restore();ctx.save();ctx.translate(w-24,(mainY0+mainY1)/2);ctx.rotate(Math.PI/2);ctx.fillStyle=colors.usdt;ctx.fillText("USDT / USDC 发行量",0,0);ctx.restore();panes.forEach(pane=>{ctx.strokeStyle="#cfd8e2";ctx.strokeRect(x0,pane.y0,x1-x0,pane.y1-pane.y0);const mid=(pane.min+pane.max)/2;[pane.min,mid,pane.max].forEach(v=>{const y=ySub(v,pane);gridLine(y,x0,x1);ctx.fillStyle=colors.muted;ctx.textAlign="right";ctx.fillText(b(v),x0-9,y+4)});ctx.fillStyle=colors.text;ctx.textAlign="left";ctx.font="12px Microsoft YaHei,Arial";ctx.fillText(pane.title,x0+8,pane.y0+16);path(pane.key,(v,p)=>ySub(v,p),colors.usdt,1.05,pane)});if(active!=null){const r=rows[active],x=xScale(r.t);ctx.setLineDash([5,5]);ctx.strokeStyle="rgba(82,96,113,.62)";ctx.beginPath();ctx.moveTo(x,mainY0);ctx.lineTo(x,panes[2].y1);ctx.stroke();ctx.setLineDash([]);[["btc",yLog,colors.btc],["eth",yLog,colors.eth],["usdt",ySupply,colors.usdt],["usdc",ySupply,colors.usdc]].forEach(([key,scale,color])=>{if(r[key]==null)return;ctx.fillStyle="#fff";ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,scale(r[key]),3.6,0,Math.PI*2);ctx.fill();ctx.stroke()});panes.forEach(pane=>{const v=r[pane.key];if(v==null)return;ctx.fillStyle="#fff";ctx.strokeStyle=colors.usdt;ctx.beginPath();ctx.arc(x,ySub(v,pane),3.2,0,Math.PI*2);ctx.fill();ctx.stroke()})}}function nearest(mx){const t=box.t0+(mx-box.x0)/(box.x1-box.x0)*(box.t1-box.t0);let l=0,r=rows.length-1;while(l<r){const m=(l+r)>>1;if(rows[m].t<t)l=m+1;else r=m}if(l>0&&Math.abs(rows[l-1].t-t)<Math.abs(rows[l].t-t))l--;return l}canvas.addEventListener("mousemove",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(x<box.x0||x>box.x1||y<box.mainY0||y>box.panes[2].y1){tip.style.display="none";draw();return}const i=nearest(x),r=rows[i];draw(i);tip.innerHTML=`<b>${r.date}</b><br>BTC：${usd(r.btc)}<br>ETH：${usd(r.eth)}<br>USDT发行量：${b(r.usdt)}<br>USDC发行量：${b(r.usdc)}<br>USDT 5日均线：${b(r.ma5)}<br>USDT 30日均线：${b(r.ma30)}<br>USDT 60日均线：${b(r.ma60)}`;tip.style.display="block";tip.style.left=Math.min(rect.width-250,Math.max(8,x+14))+"px";tip.style.top=Math.max(8,Math.min(rect.height-180,y-70))+"px"});canvas.addEventListener("mouseleave",()=>{tip.style.display="none";draw()});window.addEventListener("resize",resize);resize();
</script></body></html>
"""
    output_html.write_text("".join(line.strip() for line in html_text.replace("__PAYLOAD__", payload).splitlines()), encoding="utf-8")
