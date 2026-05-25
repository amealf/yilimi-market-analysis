from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from global_30y_bond_daily.providers.tradingview_provider import fetch as fetch_tradingview


ROOT = Path(__file__).resolve().parents[1]
START_DATE = date(2000, 1, 1)
END_DATE = date.today()
DISPLAY_START = pd.Timestamp("2018-01-01")
BAR_COUNT = 7000
OIL_EVENTS: list[dict[str, str]] = []
MARKETS = [
    {
        "key": "wti",
        "label": "CME WTI",
        "symbol": "NYMEX:CL1!",
        "source": "TradingView / NYMEX:CL1!",
    },
    {
        "key": "brent",
        "label": "ICE Brent",
        "symbol": "ICEEUR:BRN1!",
        "source": "TradingView / ICEEUR:BRN1!",
    },
]


def fetch_market(market: dict[str, str], retries: int = 3) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            frame = fetch_tradingview(
                {"symbol": market["symbol"]},
                {"history": {"bar_count": BAR_COUNT}},
            )
            frame = frame.copy()
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            frame = frame.dropna(subset=["date"]).sort_values("date")
            frame = frame[(frame["date"].dt.date >= START_DATE) & (frame["date"].dt.date <= END_DATE)]
            frame = frame.drop_duplicates("date", keep="last")
            close_column = f"{market['key']}_close"
            return frame[["date", "close"]].rename(columns={"close": close_column})
        except Exception as exc:
            last_error = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"TradingView request failed: {market['symbol']}") from last_error


def add_daily_pct(data: pd.DataFrame, column: str) -> None:
    valid = data.dropna(subset=[column]).set_index("date")[column]
    changes = (valid.pct_change() * 100).to_dict()
    data[f"{column}_daily_pct"] = data["date"].map(changes)


def build_price_frame(cache_path: Path | None = None) -> pd.DataFrame:
    try:
        frames = [fetch_market(market) for market in MARKETS]
    except Exception:
        if cache_path and cache_path.exists():
            return pd.read_csv(cache_path, parse_dates=["date"])
        raise

    first_dates = [frame["date"].min() for frame in frames if not frame.empty]
    if not first_dates:
        raise RuntimeError("Oil price data is empty")

    start = max(pd.Timestamp(START_DATE), min(first_dates))
    calendar = pd.DataFrame({"date": pd.date_range(start, pd.Timestamp(END_DATE), freq="D")})
    data = calendar
    for frame in frames:
        data = data.merge(frame, on="date", how="left")

    for market in MARKETS:
        add_daily_pct(data, f"{market['key']}_close")

    return data.sort_values("date").reset_index(drop=True)


def latest_valid(data: pd.DataFrame, column: str) -> pd.Series:
    valid = data.dropna(subset=[column])
    if valid.empty:
        raise RuntimeError(f"{column} has no data")
    return valid.iloc[-1]


def chart_meta(data: pd.DataFrame) -> dict:
    metrics = []
    latest_dates: list[pd.Timestamp] = []
    for market in MARKETS:
        column = f"{market['key']}_close"
        latest = latest_valid(data, column)
        latest_dates.append(pd.Timestamp(latest["date"]))
        metrics.append(
            {
                "label": market["label"],
                "value": f"${float(latest[column]):,.2f}",
                "date": pd.Timestamp(latest["date"]).strftime("%Y-%m-%d"),
            }
        )
    return {
        "latestDate": max(latest_dates).strftime("%Y-%m-%d"),
        "metrics": metrics,
        "dataNote": "日线按自然日铺开；周末和无交易日保留空值，方便标注周末事件。",
    }


def series_value(value: object, digits: int = 4) -> float | None:
    if pd.isna(value):
        return None
    return round(float(value), digits)


def write_interactive_html(data: pd.DataFrame, output_html: Path) -> None:
    meta = chart_meta(data)
    generated_at = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    display_data = data.loc[data["date"] >= DISPLAY_START]
    records = []
    for row in display_data.itertuples(index=False):
        records.append(
            {
                "date": row.date.strftime("%Y-%m-%d"),
                "wti": series_value(row.wti_close, 4),
                "brent": series_value(row.brent_close, 4),
                "wtiDaily": series_value(row.wti_close_daily_pct, 4),
                "brentDaily": series_value(row.brent_close_daily_pct, 4),
            }
        )

    payload = json.dumps(
        {
            "rows": records,
            "meta": meta,
            "events": OIL_EVENTS,
            "generatedAt": generated_at,
            "dataSources": "TradingView、NYMEX、ICE Futures Europe",
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
  <title>WTI / Brent 原油价格走势</title>
  <style>
    html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#fff;color:#17202a;font-family:"Microsoft YaHei",Arial,sans-serif}
    .page{position:relative;width:100vw;height:100vh;background:#fff}
    .home-link{position:absolute;left:14px;top:14px;z-index:2;width:32px;height:32px;border:1px solid rgba(120,129,145,.34);border-radius:6px;display:flex;align-items:center;justify-content:center;color:#526071;background:rgba(255,255,255,.72);box-shadow:0 6px 18px rgba(15,23,42,.08);backdrop-filter:blur(2px)}
    .is-embed .home-link{display:none}
    .home-link:hover{color:#17202a;background:rgba(255,255,255,.94)}
    .home-link svg{width:18px;height:18px;stroke:currentColor}
    canvas{display:block;width:100vw;height:100vh;cursor:crosshair}
    .tip{position:absolute;display:none;pointer-events:none;box-sizing:border-box;min-width:220px;max-width:390px;background:rgba(255,255,255,.24);border:1px solid rgba(120,129,145,.42);border-radius:6px;color:#17202a;padding:9px 10px;font-size:12px;line-height:1.65;box-shadow:0 8px 22px rgba(15,23,42,.12);backdrop-filter:blur(2px);overflow-wrap:anywhere;white-space:normal}
  </style>
</head>
<body>
<div class="page"><a class="home-link" href="../../index.html" aria-label="返回主页" title="返回主页"><svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/></svg></a><canvas id="chart"></canvas><div class="tip" id="tip"></div></div>
<script>
const P=__PAYLOAD__;
const rawRows=P.rows.map(r=>({...r,t:new Date(r.date).getTime()}));
const canvas=document.getElementById("chart");
const ctx=canvas.getContext("2d");
const tip=document.getElementById("tip");
const isEmbed=document.documentElement.classList.contains("is-embed");
const events=P.events.map(e=>({...e,t:new Date(e.date).getTime()}));
const colors={wti:"#1f77b4",brent:"#ED7D31",event:"#2563eb",eventText:"rgba(23,32,42,.65)",eventTextActive:"#17202a",eventBorder:"rgba(147,197,253,.42)",eventFill:"rgba(255,255,255,.30)",eventActiveFill:"rgba(255,255,255,.70)",grid:"#dfe6ed",text:"#17202a",muted:"#526071",weekend:"rgba(148,163,184,.055)"};
const series=[
  {key:"wti",label:"CME WTI",color:colors.wti,width:1.15},
  {key:"brent",label:"ICE Brent",color:colors.brent,width:1.05}
];
const periodNames={day:"日",week:"周",month:"月"};
let box={},zoom=null,drag=null,legendBoxes=[],eventBoxes=[],periodBoxes=[],period="week",hoverPeriod=null,hidden={};
const DAY=86400000;
function cloneRow(r){return {...r}}
function hasPrice(r){return series.some(item=>r[item.key]!=null)}
function weekKey(t){const d=new Date(t),day=d.getUTCDay(),diff=(day+6)%7,s=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate()-diff));return s.toISOString().slice(0,10)}
function monthKey(t){const d=new Date(t);return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}`}
function groupedRows(mode){
  if(mode==="day")return rawRows.map(cloneRow);
  const map=new Map(),keyFn=mode==="week"?weekKey:monthKey;
  rawRows.forEach(r=>{if(hasPrice(r))map.set(keyFn(r.t),cloneRow(r))});
  return Array.from(map.values()).sort((a,b)=>a.t-b.t).map((r,i,a)=>({...r,wtiDaily:i&&a[i-1].wti&&r.wti!=null?(r.wti/a[i-1].wti-1)*100:null,brentDaily:i&&a[i-1].brent&&r.brent!=null?(r.brent/a[i-1].brent-1)*100:null}));
}
let rows=groupedRows(period);
function refreshRows(){rows=groupedRows(period)}
function displayEnd(){return rows[rows.length-1].t+DAY*30}
function usd(v,d=2){return v==null?"-":"$"+Number(v).toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d})}
function signedPct(v){if(v==null)return "-";const n=Number(v);return (n>0?"+":"")+n.toFixed(2)+"%"}
function valueText(item,r){const daily=item.key==="wti"?r.wtiDaily:r.brentDaily;return r[item.key]==null?"-":usd(r[item.key])+"，"+signedPct(daily)}
function extent(keys,list=rows){const a=keys.flatMap(k=>list.map(r=>r[k]).filter(v=>v!=null&&Number.isFinite(v)));return a.length?[Math.min(...a),Math.max(...a)]:[0,1]}
function activeKeys(){const keys=series.filter(s=>!hidden[s.key]).map(s=>s.key);return keys.length?keys:["wti","brent"]}
function currentRange(){return zoom||[rows[0].t,displayEnd()]}
function visibleRows(){const [t0,t1]=currentRange();const sample=rows.filter(r=>r.t>=t0&&r.t<=t1);return sample.length?sample:rows}
function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}
function xScale(t){return box.x0+(t-box.t0)/(box.t1-box.t0)*(box.x1-box.x0)}
function yPrice(v){return box.y1-(v-box.priceMin)/(box.priceMax-box.priceMin)*(box.y1-box.y0)}
function gridLine(y){ctx.strokeStyle=colors.grid;ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(box.x0,y);ctx.lineTo(box.x1,y);ctx.stroke()}
function roundRect(x,y,w,h,r){const rr=Math.min(r,w/2,h/2);ctx.beginPath();ctx.moveTo(x+rr,y);ctx.lineTo(x+w-rr,y);ctx.quadraticCurveTo(x+w,y,x+w,y+rr);ctx.lineTo(x+w,y+h-rr);ctx.quadraticCurveTo(x+w,y+h,x+w-rr,y+h);ctx.lineTo(x+rr,y+h);ctx.quadraticCurveTo(x,y+h,x,y+h-rr);ctx.lineTo(x,y+rr);ctx.quadraticCurveTo(x,y,x+rr,y)}
function niceTicks(min,max,count){const span=Math.max(1e-9,max-min),raw=span/Math.max(1,count),pow=Math.pow(10,Math.floor(Math.log10(raw))),base=[1,2,5,10].find(v=>v*pow>=raw)*pow,start=Math.ceil(min/base)*base,out=[];for(let v=start;v<=max+base*.45;v+=base)out.push(v);return out}
function drawLegend(x,y,maxX){legendBoxes=[];ctx.font="12px Microsoft YaHei,Arial";let cur=x,rowY=y;series.forEach(item=>{const labelW=ctx.measureText(item.label).width,total=labelW+68,off=hidden[item.key];if(cur>x&&cur+total>maxX){cur=x;rowY+=20}legendBoxes.push({key:item.key,x0:cur-5,y0:rowY-12,x1:cur+total-16,y1:rowY+9});ctx.globalAlpha=off?.28:1;ctx.strokeStyle=off?"rgba(82,96,113,.45)":item.color;ctx.fillStyle=off?"rgba(82,96,113,.58)":colors.text;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(cur,rowY);ctx.lineTo(cur+28,rowY);ctx.stroke();ctx.textAlign="left";ctx.fillText(item.label,cur+36,rowY+4);ctx.globalAlpha=1;cur+=total})}
function drawPeriodTabs(x,y){periodBoxes=[];const labels=[["day","日"],["week","周"],["month","月"]];ctx.font="12px Microsoft YaHei,Arial";labels.forEach(([key,label],i)=>{const w=34,h=20,left=x+i*(w+6),active=period===key,hovered=hoverPeriod===key;periodBoxes.push({key,x0:left,y0:y,x1:left+w,y1:y+h});ctx.strokeStyle=active?"#60a5fa":hovered?"#93c5fd":"rgba(71,85,105,.42)";ctx.lineWidth=active||hovered?1.35:.9;roundRect(left,y,w,h,6);ctx.stroke();ctx.fillStyle=hovered?"#17202a":active?"#17202a":"rgba(71,85,105,.58)";ctx.textAlign="center";ctx.fillText(label,left+w/2,y+14)});ctx.lineWidth=1}
function hitPeriod(p){return periodBoxes.find(b=>p.x>=b.x0&&p.x<=b.x1&&p.y>=b.y0&&p.y<=b.y1)}
function drawAxes(){niceTicks(box.priceMin,box.priceMax,7).forEach(v=>{const y=yPrice(v);gridLine(y);ctx.fillStyle=colors.text;ctx.textAlign="right";ctx.fillText(usd(v,0),box.x0-9,y+4)})}
function drawWeekends(){if(period!=="day")return;const start=new Date(box.t0);start.setUTCHours(0,0,0,0);for(let t=start.getTime();t<=box.t1;t+=DAY){const d=new Date(t).getUTCDay();if(d!==6&&d!==0)continue;const x0=xScale(t),x1=xScale(t+DAY);ctx.fillStyle=colors.weekend;ctx.fillRect(x0,box.y0,Math.max(1,x1-x0),box.y1-box.y0)}}
function drawPath(item){if(hidden[item.key])return;ctx.beginPath();let open=false;rows.forEach(r=>{const v=r[item.key];if(v==null||!Number.isFinite(v)){open=false;return}const x=xScale(r.t),y=yPrice(v);if(!open){ctx.moveTo(x,y);open=true}else ctx.lineTo(x,y)});ctx.strokeStyle=item.color;ctx.lineWidth=item.width;ctx.stroke()}
function drawEvents(activeEventDate=null){eventBoxes=[];ctx.font="11px Microsoft YaHei,Arial";const lanes=[box.x0-999,box.x0-999,box.x0-999],visible=events.filter(e=>e.t>=box.t0&&e.t<=box.t1).sort((a,b)=>a.t-b.t);visible.forEach(event=>{const active=activeEventDate===event.date,x=xScale(event.t),pad=7,w=Math.ceil(ctx.measureText(event.label).width+pad*2),h=18;let lane=lanes.findIndex(right=>right<=x-w/2-4);if(lane<0)lane=lanes.indexOf(Math.min(...lanes));const y=box.y1-26-lane*22,left=Math.max(box.x0+2,Math.min(box.x1-w-2,x-w/2));lanes[lane]=left+w;ctx.save();ctx.strokeStyle=active?"rgba(37,99,235,.38)":"rgba(147,197,253,.18)";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,box.y1);ctx.lineTo(x,y+h);ctx.stroke();ctx.fillStyle=active?colors.eventActiveFill:colors.eventFill;ctx.strokeStyle=active?colors.event:colors.eventBorder;roundRect(left,y,w,h,9);ctx.fill();ctx.stroke();ctx.fillStyle=active?colors.eventTextActive:colors.eventText;ctx.textAlign="center";ctx.fillText(event.label,left+w/2,y+12.5);ctx.restore();eventBoxes.push({event,x0:left,y0:y,x1:left+w,y1:y+h})})}
function draw(active,eventDate=null){
  refreshRows();
  const w=canvas.clientWidth,h=canvas.clientHeight,outer=Math.round(Math.min(w,h)*.035);
  const axisLeft=76,axisRight=76,titleY=outer+18,legendY=outer+56,xLabelGap=isEmbed?35:38;
  const x0=outer+axisLeft,x1=w-outer-axisRight,y0=outer+94,y1=h-outer-xLabelGap;
  const [t0,t1]=currentRange(),sample=visibleRows(),[min0,max0]=extent(activeKeys(),sample),pad=Math.max((max0-min0)*.09,4);
  box={x0,x1,y0,y1,t0,t1,priceMin:min0-pad,priceMax:max0+pad};
  ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);
  const titleSize=isEmbed&&w<760?18:21,tabY=isEmbed&&w<760?legendY-14:titleY-15;
  ctx.fillStyle=colors.text;ctx.font=`700 ${titleSize}px Microsoft YaHei,Arial`;ctx.textAlign="center";ctx.fillText("WTI / Brent 原油价格走势",w/2,titleY);
  drawLegend(x0,legendY,x1);drawPeriodTabs(x1-112,tabY);
  drawWeekends();
  const startY=new Date(box.t0).getUTCFullYear(),endY=new Date(box.t1).getUTCFullYear();
  for(let year=startY;year<=endY;year++){const x=xScale(new Date(`${year}-01-01T00:00:00Z`).getTime());if(x<x0||x>x1)continue;ctx.strokeStyle="#edf2f7";ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(x,y0);ctx.lineTo(x,y1);ctx.stroke();ctx.fillStyle=colors.muted;ctx.textAlign="center";ctx.fillText(year,x,y1+(isEmbed?23:28))}
  if(!isEmbed){ctx.fillStyle=colors.muted;ctx.font="11px Microsoft YaHei,Arial";ctx.textAlign="left";ctx.fillText(`刷新时间：北京时间 ${P.generatedAt}　数据来源：${P.dataSources}`,x0,h-Math.max(8,outer*.35))}
  drawAxes();
  ctx.strokeStyle="#cfd8e2";ctx.strokeRect(x0,y0,x1-x0,y1-y0);
  ctx.save();ctx.beginPath();ctx.rect(x0,y0,x1-x0,y1-y0);ctx.clip();series.forEach(drawPath);ctx.restore();
  drawEvents(eventDate);
  ctx.fillStyle=colors.text;ctx.textAlign="center";ctx.save();ctx.translate(x0-52,(y0+y1)/2);ctx.rotate(-Math.PI/2);ctx.fillText("美元 / 桶",0,0);ctx.restore();
  if(active!=null){const r=rows[active],x=xScale(r.t);ctx.setLineDash([5,5]);ctx.strokeStyle="rgba(82,96,113,.62)";ctx.beginPath();ctx.moveTo(x,y0);ctx.lineTo(x,y1);ctx.stroke();ctx.setLineDash([]);series.forEach(item=>{const v=r[item.key];if(hidden[item.key]||v==null)return;ctx.fillStyle="#fff";ctx.strokeStyle=item.color;ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,yPrice(v),3.3,0,Math.PI*2);ctx.fill();ctx.stroke()})}
}
function clampX(x){return Math.max(box.x0,Math.min(box.x1,x))}
function pointer(e){const rect=canvas.getBoundingClientRect();return{x:e.clientX-rect.left,y:e.clientY-rect.top,rect}}
function inPlot(p){return p.x>=box.x0&&p.x<=box.x1&&p.y>=box.y0&&p.y<=box.y1}
function timeAtX(x){return box.t0+(clampX(x)-box.x0)/(box.x1-box.x0)*(box.t1-box.t0)}
function hitLegend(p){return legendBoxes.find(b=>p.x>=b.x0&&p.x<=b.x1&&p.y>=b.y0&&p.y<=b.y1)}
function hitEvent(p){return eventBoxes.find(b=>p.x>=b.x0&&p.x<=b.x1&&p.y>=b.y0&&p.y<=b.y1)}
function nearest(mx){const t=timeAtX(mx);let l=0,r=rows.length-1;while(l<r){const m=(l+r)>>1;if(rows[m].t<t)l=m+1;else r=m}if(l>0&&Math.abs(rows[l-1].t-t)<Math.abs(rows[l].t-t))l--;return l}
function drawSelection(){if(!drag)return;const x0=clampX(drag.x0),x1=clampX(drag.x1),left=Math.min(x0,x1),width=Math.abs(x1-x0);if(width<3)return;ctx.fillStyle="rgba(111,74,168,.10)";ctx.strokeStyle="rgba(111,74,168,.55)";ctx.lineWidth=1;ctx.fillRect(left,box.y0,width,box.y1-box.y0);ctx.strokeRect(left,box.y0,width,box.y1-box.y0)}
function showTip(p){
  if(!inPlot(p)){tip.style.display="none";draw();return}
  const eventHit=hitEvent(p);
  if(eventHit){const e=eventHit.event;draw(null,e.date);const x=xScale(e.t);ctx.setLineDash([4,5]);ctx.strokeStyle="rgba(37,99,235,.42)";ctx.beginPath();ctx.moveTo(x,box.y0);ctx.lineTo(x,box.y1);ctx.stroke();ctx.setLineDash([]);tip.className="tip";tip.innerHTML=`<b>${e.label}</b><br>时间：${e.dateLabel}<br>类型：${e.type}<br>${e.description}`;tip.style.display="block";tip.style.left=Math.min(p.rect.width-310,Math.max(8,p.x+14))+"px";tip.style.top=Math.max(8,Math.min(p.rect.height-190,p.y-92))+"px";return}
  const i=nearest(p.x),r=rows[i];draw(i);
  const lines=series.filter(item=>!hidden[item.key]).map(item=>`${item.label}：${valueText(item,r)}`);
  tip.className="tip";tip.innerHTML=`<b>${r.date}（${periodNames[period]}）</b><br>${lines.join("<br>")}`;tip.style.display="block";tip.style.left=Math.min(p.rect.width-250,Math.max(8,p.x+14))+"px";tip.style.top=Math.max(8,Math.min(p.rect.height-178,p.y-70))+"px";
}
canvas.addEventListener("click",e=>{const p=pointer(e),tab=hitPeriod(p);if(tab){period=tab.key;hoverPeriod=tab.key;zoom=null;tip.style.display="none";draw();return}const hit=hitLegend(p);if(!hit)return;hidden[hit.key]=!hidden[hit.key];tip.style.display="none";draw()});
canvas.addEventListener("mousedown",e=>{const p=pointer(e);if(hitLegend(p)||hitPeriod(p)||!inPlot(p))return;drag={x0:p.x,x1:p.x};tip.style.display="none"});
canvas.addEventListener("mousemove",e=>{const p=pointer(e);if(drag){drag.x1=p.x;tip.style.display="none";draw();drawSelection();return}const tab=hitPeriod(p);if(tab){if(hoverPeriod!==tab.key){hoverPeriod=tab.key;draw()}canvas.style.cursor="pointer";tip.style.display="none";return}if(hoverPeriod!==null){hoverPeriod=null;draw()}showTip(p)});
window.addEventListener("mouseup",()=>{if(!drag)return;const x0=clampX(drag.x0),x1=clampX(drag.x1);if(Math.abs(x1-x0)>12){const a=timeAtX(x0),b=timeAtX(x1);zoom=[Math.min(a,b),Math.max(a,b)]}drag=null;tip.style.display="none";draw()});
canvas.addEventListener("mouseleave",()=>{if(drag)return;hoverPeriod=null;tip.style.display="none";canvas.style.cursor="default";draw()});
canvas.addEventListener("dblclick",()=>{zoom=null;drag=null;tip.style.display="none";draw()});
window.addEventListener("resize",resize);
refreshRows();
resize();
</script>
</body>
</html>
"""
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(html_text.replace("__PAYLOAD__", payload), encoding="utf-8")
