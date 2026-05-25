from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from global_30y_bond_daily.providers.tradingview_provider import fetch as fetch_tradingview


ROOT = Path(__file__).resolve().parents[1]
START_DATE = date(2026, 1, 1)
END_DATE = date.today()
DISPLAY_START = pd.Timestamp("2026-01-01")
BAR_COUNT = 7000
OIL_EVENTS: list[dict[str, str]] = [
    {
        "date": "2026-02-28",
        "dateLabel": "2026-02-28 16:00 UTC",
        "label": "战争定价",
        "type": "供应冲击",
        "score": "-1.00",
        "description": "美以打击伊朗，伊朗报复。路透在16:08 UTC报道，联合打击和伊朗对海湾的报复性导弹袭击已经扰乱全球关键产区的出口预期；中东约占全球油气供应的20%，航运和保险风险开始被重新定价。",
    },
    {
        "date": "2026-03-10",
        "dateLabel": "2026-03-10 03:00 UTC",
        "label": "降温交易",
        "type": "停火预期",
        "score": "0.65",
        "description": "川普称战争可能很快结束。虽然当天是开战以来猛烈打击之一，伊朗革命卫队还威胁阻断海湾石油出口，但川普称战争「非常完整，差不多了」，投资者押注他会尽快结束战争。",
    },
    {
        "date": "2026-03-23",
        "dateLabel": "2026-03-23 11:00 UTC",
        "label": "推迟攻击",
        "type": "能源设施风险降温",
        "score": "0.90",
        "description": "川普发帖推迟攻击伊朗能源基础设施。他在11:05 UTC于Truth Social表示，将推迟对伊朗能源基础设施的攻击，并暗示华盛顿和德黑兰仍有建设性谈判。",
    },
    {
        "date": "2026-04-02",
        "dateLabel": "2026-04-02 00:00 UTC",
        "label": "继续重击",
        "type": "战争升级",
        "score": "-0.90",
        "description": "川普讲话没有宣布结束战争，反而威胁继续重击伊朗。他在4月1日晚讲话中没有给出结束战争时间表，称未来两三周会对伊朗「极其严厉」打击；伊朗外长Araqchi回应称，打击民用结构不会迫使伊朗投降。",
    },
    {
        "date": "2026-04-07",
        "dateLabel": "2026-04-07 23:00 UTC",
        "label": "两周停火",
        "type": "停火",
        "score": "1.00",
        "description": "川普宣布与伊朗两周停火。伊朗表示只要攻击停止，霍尔木兹海峡可在两周内开放，川普称伊朗提交了10点和平方案。",
    },
    {
        "date": "2026-04-17",
        "dateLabel": "2026-04-17 02:00 UTC",
        "label": "霍尔木兹开放",
        "type": "通航恢复",
        "score": "0.95",
        "description": "伊朗外长称霍尔木兹在停火期间对商船开放；川普称预计很快达成结束战争协议。伊朗外长Abbas Araqchi在X上称，商船可在以黎停火剩余时间内通过霍尔木兹；川普又称美国会与伊朗合作处理浓缩铀问题，并预计很快达成结束战争协议。",
    },
    {
        "date": "2026-04-20",
        "dateLabel": "2026-04-20 22:00 UTC",
        "label": "扣押货船",
        "type": "复燃风险",
        "score": "-0.80",
        "description": "美国扣押伊朗货船，伊朗称会报复。美国扣押一艘试图突破封锁的伊朗货船，伊朗称将报复；此前由开放海峡带来的市场乐观迅速消退。",
    },
    {
        "date": "2026-04-21",
        "dateLabel": "2026-04-21 20:00 UTC",
        "label": "延长停火",
        "type": "停火延长",
        "score": "0.85",
        "description": "川普宣布无限期延长停火。他在20:10 UTC称会无限期延长与伊朗的停火；此前19:54-19:56 UTC出现约4.3亿美元做空原油的交易。",
    },
    {
        "date": "2026-04-29",
        "dateLabel": "2026-04-29 10:00 UTC",
        "label": "重开霍尔木兹",
        "type": "通航与打击风险",
        "score": "-0.45",
        "description": "美国寻求国际联盟重开霍尔木兹，川普敦促伊朗签「非核协议」。美国国务院电报显示，华盛顿希望组建国际联盟恢复霍尔木兹航行自由；同时有报道称川普将听取新一轮打击伊朗方案简报。",
    },
    {
        "date": "2026-04-30",
        "dateLabel": "2026-04-30 01:00 UTC",
        "label": "四年高位",
        "type": "战争升级担忧",
        "score": "-0.85",
        "description": "战争升级担忧推动Brent触及四年高位，随后大幅回落。有报道称美国考虑通过一系列打击迫使伊朗回到谈判桌；当天价格随后在没有清晰单一催化的情况下回落，显示战时行情波动极高。",
    },
    {
        "date": "2026-05-04",
        "dateLabel": "2026-05-04 22:00 UTC",
        "label": "袭击油港",
        "type": "海湾袭击",
        "score": "-0.95",
        "description": "伊朗袭击阿联酋油港和霍尔木兹附近船只。伊朗在过去24小时内攻击海湾船只，并导致阿联酋油气工业区起火；美国海军拦截伊朗导弹和无人机。",
    },
    {
        "date": "2026-05-05",
        "dateLabel": "2026-05-05 22:00 UTC",
        "label": "护航通行",
        "type": "脆弱停火",
        "score": "0.55",
        "description": "两艘船通过霍尔木兹，美国称脆弱停火仍在。美国称已有两艘商船在海军护航下通过海峡，同时称停火仍有效；伊朗否认部分通航说法。",
    },
    {
        "date": "2026-05-06",
        "dateLabel": "2026-05-06 23:00 UTC",
        "label": "初步和平",
        "type": "谈判进展",
        "score": "0.90",
        "description": "美伊接近初步和平协议的报道出现，伊朗称正在审查美国方案。巴基斯坦调停方称美伊接近就一页备忘录达成一致；伊朗称会通过巴基斯坦尽快回复新美国方案。",
    },
    {
        "date": "2026-05-08",
        "dateLabel": "2026-05-08 00:00 UTC",
        "label": "再度交火",
        "type": "停火压力",
        "score": "-0.25",
        "description": "美伊再度交火，但川普淡化冲突并称停火仍有效。美国和伊朗互相空袭后，川普称停火仍然有效；交易员同时权衡谈判突破和复战风险。",
    },
    {
        "date": "2026-05-10",
        "dateLabel": "2026-05-10 22:00 UTC",
        "label": "生命维持",
        "type": "谈判受挫",
        "score": "-0.65",
        "description": "川普称停火处于「生命维持状态」并否决伊朗回应。伊朗要求赔偿、解除美国封锁、恢复石油销售、解除制裁并确认其对霍尔木兹的主权；川普称伊朗回应「完全不可接受」。",
    },
    {
        "date": "2026-05-12",
        "dateLabel": "2026-05-12 22:00 UTC",
        "label": "分歧扩大",
        "type": "供应假设延长",
        "score": "-0.65",
        "description": "美伊分歧扩大，EIA假设霍尔木兹关闭持续到5月底。报道称美伊围绕结束战争提案存在明显分歧；EIA将霍尔木兹有效关闭的假设从4月底延长到5月底。",
    },
    {
        "date": "2026-05-15",
        "dateLabel": "2026-05-15 01:00 UTC",
        "label": "耐心耗尽",
        "type": "复战风险",
        "score": "-0.75",
        "description": "川普称对伊朗耐心耗尽，伊朗外长称准备恢复战斗。川普表示对伊朗「耐心耗尽」；伊朗外长Araqchi称伊朗对美国「没有信任」，既准备外交解决，也准备回到战斗状态。",
    },
    {
        "date": "2026-05-18",
        "dateLabel": "2026-05-18 22:00 UTC",
        "label": "推迟攻击",
        "type": "供应担忧",
        "score": "-0.35",
        "description": "供应担忧压过制裁豁免消息，盘后又因川普推迟攻击而回吐。市场担心霍尔木兹近乎关闭导致库存快速消耗；盘后川普称会暂缓原定周二对伊朗的攻击。",
    },
    {
        "date": "2026-05-20",
        "dateLabel": "2026-05-20 01:00 UTC",
        "label": "最后阶段",
        "type": "谈判窗口",
        "score": "0.45",
        "description": "川普称谈判进入「最后阶段」，同时警告伊朗不接受就继续打。川普称谈判处于「最后阶段」，但也威胁继续攻击；伊朗外交部发言人Baghaei称，伊朗准备与沿岸国家制定安全航运协议。",
    },
    {
        "date": "2026-05-22",
        "dateLabel": "2026-05-22 22:00 UTC",
        "label": "仍未到点",
        "type": "谈判拉锯",
        "score": "0.20",
        "description": "Rubio称谈判有进展但「还没到」。Rubio称有进展，但仍有工作要做；美伊仍在浓缩铀库存和霍尔木兹控制权上对立。",
    },
    {
        "date": "2026-05-23",
        "dateLabel": "2026-05-23 14:00 UTC",
        "label": "基本谈妥",
        "type": "周末和平消息",
        "score": "0.75",
        "description": "川普称和平备忘录「基本谈妥」，伊朗媒体随后称该说法「与现实不符」。川普发帖称协议备忘录已「largely negotiated」，并称协议会包括重开霍尔木兹；伊朗Fars随后报道，协议会让伊朗管理海峡，并称川普所谓协议接近完成「inconsistent with reality」。",
    },
    {
        "date": "2026-05-24",
        "dateLabel": "2026-05-24 02:00 UTC",
        "label": "不急签约",
        "type": "周末谈判降温",
        "score": "-0.30",
        "description": "川普改称不急着达成协议，美国封锁维持。川普称已要求谈判代表不要急于与伊朗达成协议，并称美国对伊朗船只的封锁会保持，直到协议达成、认证并签署；Tasnim称美国仍阻碍冻结资金释放等事项。",
    },
    {
        "date": "2026-05-25",
        "dateLabel": "2026-05-25 00:00 UTC",
        "label": "风险偏好",
        "type": "协议希望扩散",
        "score": "0.85",
        "description": "协议希望扩散到外汇、股市和航运。霍尔木兹重开希望带动风险偏好；同日两艘LNG船和一艘装载伊拉克Basrah原油的VLCC离开海湾，显示部分通航恢复。",
    },
]
MARKETS = [
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
            price_columns = ["open", "high", "low", "close"]
            for column in price_columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            rename_columns = {column: f"{market['key']}_{column}" for column in price_columns}
            return frame[["date", *price_columns]].rename(columns=rename_columns)
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
            cached = pd.read_csv(cache_path, parse_dates=["date"])
            cached = cached[cached["date"].dt.date >= START_DATE]
            for market in MARKETS:
                close_column = f"{market['key']}_close"
                for price in ["open", "high", "low"]:
                    column = f"{market['key']}_{price}"
                    if column not in cached.columns and close_column in cached.columns:
                        cached[column] = cached[close_column]
            return cached
        raise

    first_dates = [frame["date"].min() for frame in frames if not frame.empty]
    if not first_dates:
        raise RuntimeError("Oil price data is empty")

    start = pd.Timestamp(START_DATE)
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
                "o": series_value(getattr(row, "brent_open", None), 4),
                "h": series_value(getattr(row, "brent_high", None), 4),
                "l": series_value(getattr(row, "brent_low", None), 4),
                "c": series_value(row.brent_close, 4),
                "brentDaily": series_value(row.brent_close_daily_pct, 4),
            }
        )

    payload = json.dumps(
        {
            "rows": records,
            "meta": meta,
            "events": OIL_EVENTS,
            "generatedAt": generated_at,
            "dataSources": "TradingView、ICE Futures Europe",
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
  <title>Brent 原油价格与事件</title>
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
const colors={kline:"rgba(17,17,17,.72)",upFill:"rgba(255,255,255,.88)",downFill:"rgba(17,17,17,.72)",text:"#111827",legend:"#374151",muted:"#4b5563",dateLine:"rgba(0,0,0,.12)",frame:"rgba(17,17,17,.72)",weekend:"rgba(148,163,184,.055)"};
const series=[
  {key:"brent",label:"ICE Brent K线",color:colors.kline,width:1.15}
];
const periodNames={day:"日",week:"周",month:"月"};
let box={},zoom=null,drag=null,legendBoxes=[],eventBoxes=[],periodBoxes=[],period="day",hoverPeriod=null,hidden={};
const DAY=86400000;
function cloneRow(r){return {...r}}
function hasOhlc(r){return [r.o,r.h,r.l,r.c].every(v=>v!=null&&Number.isFinite(v))}
const baseOpen=(rawRows.find(r=>r.o!=null&&Number.isFinite(r.o))||{}).o||null;
function weekKey(t){const d=new Date(t),day=d.getUTCDay(),diff=(day+6)%7,s=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate()-diff));return s.toISOString().slice(0,10)}
function monthKey(t){const d=new Date(t);return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}`}
function periodTime(key,mode){return new Date(`${key}${mode==="month"?"-01":""}T00:00:00Z`).getTime()}
function groupedRows(mode){
  if(mode==="day")return rawRows.map(cloneRow);
  const map=new Map(),keyFn=mode==="week"?weekKey:monthKey;
  rawRows.forEach(r=>{
    if(!hasOhlc(r))return;
    const key=keyFn(r.t),current=map.get(key);
    if(!current){map.set(key,{date:key,t:periodTime(key,mode),o:r.o,h:r.h,l:r.l,c:r.c});return}
    current.h=Math.max(current.h,r.h);
    current.l=Math.min(current.l,r.l);
    current.c=r.c;
  });
  return Array.from(map.values()).sort((a,b)=>a.t-b.t).map((r,i,a)=>({...r,brentDaily:i&&a[i-1].c&&r.c!=null?(r.c/a[i-1].c-1)*100:null}));
}
let rows=groupedRows(period);
function refreshRows(){rows=groupedRows(period)}
function displayEnd(){return rows[rows.length-1].t+DAY*5}
function defaultRange(){return [rows[0].t,displayEnd()]}
function usd(v,d=2){return v==null?"-":"$"+Number(v).toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d})}
function basePct(v){return baseOpen&&v!=null?(v/baseOpen*100).toFixed(0)+"%":"-"}
function signedPct(v){if(v==null)return "-";const n=Number(v);return (n>0?"+":"")+n.toFixed(2)+"%"}
function valueText(r){return hasOhlc(r)?`开 ${usd(r.o)}　高 ${usd(r.h)}　低 ${usd(r.l)}　收 ${usd(r.c)}　${signedPct(r.brentDaily)}`:"-"}
function priceExtent(list=rows){const a=[];list.forEach(r=>{if(r.h!=null&&Number.isFinite(r.h))a.push(r.h);if(r.l!=null&&Number.isFinite(r.l))a.push(r.l)});return a.length?[Math.min(...a),Math.max(...a)]:[0,1]}
function eventColor(score,alpha=1){const s=Math.max(-1,Math.min(1,Number(score)||0)),hue=60+s*60,light=66-Math.abs(s)*34;return `hsla(${hue},70%,${light}%,${alpha})`}
function currentRange(){return zoom||defaultRange()}
function visibleRows(){const [t0,t1]=currentRange();const sample=rows.filter(r=>r.t>=t0&&r.t<=t1);return sample.length?sample:rows}
function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}
function xScale(t){return box.x0+(t-box.t0)/(box.t1-box.t0)*(box.x1-box.x0)}
function yPrice(v){return box.y1-(v-box.priceMin)/(box.priceMax-box.priceMin)*(box.y1-box.y0)}
function roundRect(x,y,w,h,r){const rr=Math.min(r,w/2,h/2);ctx.beginPath();ctx.moveTo(x+rr,y);ctx.lineTo(x+w-rr,y);ctx.quadraticCurveTo(x+w,y,x+w,y+rr);ctx.lineTo(x+w,y+h-rr);ctx.quadraticCurveTo(x+w,y+h,x+w-rr,y+h);ctx.lineTo(x+rr,y+h);ctx.quadraticCurveTo(x,y+h,x,y+h-rr);ctx.lineTo(x,y+rr);ctx.quadraticCurveTo(x,y,x+rr,y)}
function niceTicks(min,max,count){const span=Math.max(1e-9,max-min),raw=span/Math.max(1,count),pow=Math.pow(10,Math.floor(Math.log10(raw))),base=[1,2,5,10].find(v=>v*pow>=raw)*pow,start=Math.ceil(min/base)*base,out=[];for(let v=start;v<=max+base*.45;v+=base)out.push(v);return out}
function drawLegend(x,y,maxX){legendBoxes=[];ctx.font="13px Microsoft YaHei,Arial";let cur=x,rowY=y;series.forEach(item=>{const labelW=ctx.measureText(item.label).width,total=labelW+74,off=hidden[item.key];if(cur>x&&cur+total>maxX){cur=x;rowY+=22}legendBoxes.push({key:item.key,x0:cur-5,y0:rowY-14,x1:cur+total-16,y1:rowY+10});ctx.globalAlpha=off?.28:1;ctx.strokeStyle=off?"rgba(82,96,113,.45)":colors.kline;ctx.fillStyle=off?"rgba(82,96,113,.58)":colors.upFill;ctx.lineWidth=1.2;ctx.beginPath();ctx.moveTo(cur+14,rowY-9);ctx.lineTo(cur+14,rowY+8);ctx.stroke();ctx.strokeRect(cur+8,rowY-4,12,8);ctx.fillRect(cur+8,rowY-4,12,8);ctx.fillStyle=off?"rgba(82,96,113,.58)":colors.legend;ctx.textAlign="left";ctx.fillText(item.label,cur+32,rowY+4);ctx.globalAlpha=1;cur+=total})}
function drawPeriodTabs(x,y){periodBoxes=[];const labels=[["day","日"],["week","周"],["month","月"]];ctx.font="12px Microsoft YaHei,Arial";labels.forEach(([key,label],i)=>{const w=34,h=20,left=x+i*(w+6),active=period===key,hovered=hoverPeriod===key;periodBoxes.push({key,x0:left,y0:y,x1:left+w,y1:y+h});ctx.strokeStyle=active?"#1f77b4":hovered?"#7bb8f8":"rgba(71,85,105,.42)";ctx.lineWidth=active||hovered?1.35:.9;roundRect(left,y,w,h,5);ctx.stroke();ctx.fillStyle=hovered||active?colors.text:"rgba(71,85,105,.68)";ctx.textAlign="center";ctx.fillText(label,left+w/2,y+14)});ctx.lineWidth=1}
function hitPeriod(p){return periodBoxes.find(b=>p.x>=b.x0&&p.x<=b.x1&&p.y>=b.y0&&p.y<=b.y1)}
function drawAxes(){niceTicks(box.priceMin,box.priceMax,7).forEach(v=>{const y=yPrice(v);ctx.fillStyle=colors.text;ctx.textAlign="right";ctx.fillText(usd(v,0),box.x0-9,y+4);ctx.textAlign="left";ctx.fillText(basePct(v),box.x1+9,y+4)})}
function drawDateTicks(){const start=new Date(box.t0);start.setUTCDate(1);start.setUTCHours(0,0,0,0);for(let t=start.getTime();t<=box.t1;){const d=new Date(t),x=xScale(t);if(x>=box.x0&&x<=box.x1){ctx.strokeStyle=colors.dateLine;ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(x,box.y0);ctx.lineTo(x,box.y1);ctx.stroke();ctx.fillStyle=colors.muted;ctx.textAlign="center";ctx.fillText(`${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}`,x,box.y1+(isEmbed?23:28))}t=Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1)}}
function drawWeekends(){if(period!=="day")return;const start=new Date(box.t0);start.setUTCHours(0,0,0,0);for(let t=start.getTime();t<=box.t1;t+=DAY){const d=new Date(t).getUTCDay();if(d!==6&&d!==0)continue;const x0=xScale(t),x1=xScale(t+DAY);ctx.fillStyle=colors.weekend;ctx.fillRect(x0,box.y0,Math.max(1,x1-x0),box.y1-box.y0)}}
function candleWidth(){const visible=rows.filter(r=>r.t>=box.t0&&r.t<=box.t1).length||1,byCount=(box.x1-box.x0)/visible*.56,byDay=(box.x1-box.x0)/Math.max(1,(box.t1-box.t0)/DAY)*.7;return Math.max(period==="day"?2:5,Math.min(period==="day"?10:22,Math.min(byCount,byDay)))}
function drawCandles(){if(hidden.brent)return;const bodyW=candleWidth();rows.forEach(r=>{if(!hasOhlc(r)||r.t<box.t0||r.t>box.t1)return;const x=xScale(r.t),up=r.c>=r.o,yH=yPrice(r.h),yL=yPrice(r.l),yO=yPrice(r.o),yC=yPrice(r.c),top=Math.min(yO,yC),height=Math.max(1.4,Math.abs(yC-yO));ctx.strokeStyle=colors.kline;ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,yH);ctx.lineTo(x,yL);ctx.stroke();ctx.fillStyle=up?colors.upFill:colors.downFill;ctx.strokeStyle=colors.kline;ctx.lineWidth=.8;ctx.fillRect(x-bodyW/2,top,bodyW,height);ctx.strokeRect(x-bodyW/2,top,bodyW,height)})}
function drawEvents(activeEventDate=null){
  eventBoxes=[];
  const laneCount=4,visible=events.filter(e=>e.t>=box.t0&&e.t<=box.t1).sort((a,b)=>a.t-b.t);
  visible.forEach((event,index)=>{
    const active=activeEventDate===event.date,x=xScale(event.t),lane=index%laneCount,y=box.y1-18-lane*17,r=active?6.8:5.6;
    ctx.save();
    ctx.strokeStyle=eventColor(event.score,active?.42:.24);
    ctx.lineWidth=active?1.1:.8;
    ctx.beginPath();ctx.moveTo(x,box.y1);ctx.lineTo(x,y-r-2);ctx.stroke();
    ctx.fillStyle=eventColor(event.score,active?.96:.80);
    ctx.strokeStyle="rgba(255,255,255,.88)";
    ctx.lineWidth=1.4;
    ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();ctx.stroke();
    ctx.restore();
    eventBoxes.push({event,x0:x-11,y0:y-11,x1:x+11,y1:y+11});
  });
}
function draw(active,eventDate=null){
  refreshRows();
  const w=canvas.clientWidth,h=canvas.clientHeight,outer=Math.round(Math.min(w,h)*.035);
  const axisLeft=76,axisRight=76,titleY=outer+18,legendY=outer+56,xLabelGap=isEmbed?35:38;
  const x0=outer+axisLeft,x1=w-outer-axisRight,y0=outer+54,y1=h-outer-xLabelGap;
  const [t0,t1]=currentRange(),sample=visibleRows(),[min0,max0]=priceExtent(sample),pad=Math.max((max0-min0)*.09,4);
  box={x0,x1,y0,y1,t0,t1,priceMin:min0-pad,priceMax:max0+pad};
  ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);
  const titleSize=isEmbed&&w<760?18:21,tabY=isEmbed&&w<760?legendY-14:titleY-15;
  ctx.fillStyle=colors.text;ctx.font=`700 ${titleSize}px Microsoft YaHei,Arial`;ctx.textAlign="center";ctx.fillText("Brent 原油价格与事件",w/2,titleY);
  legendBoxes=[];drawPeriodTabs(x1-112,tabY);
  drawWeekends();
  drawDateTicks();
  if(!isEmbed){ctx.fillStyle=colors.muted;ctx.font="11px Microsoft YaHei,Arial";ctx.textAlign="left";ctx.fillText(`刷新时间：北京时间 ${P.generatedAt}　数据来源：${P.dataSources}`,x0,h-Math.max(8,outer*.35))}
  drawAxes();
  ctx.strokeStyle=colors.frame;ctx.lineWidth=1;ctx.strokeRect(x0,y0,x1-x0,y1-y0);
  ctx.save();ctx.beginPath();ctx.rect(x0,y0,x1-x0,y1-y0);ctx.clip();drawCandles();ctx.restore();
  drawEvents(eventDate);
  ctx.fillStyle=colors.text;ctx.textAlign="center";ctx.save();ctx.translate(x0-52,(y0+y1)/2);ctx.rotate(-Math.PI/2);ctx.fillText("美元 / 桶",0,0);ctx.restore();
  ctx.save();ctx.translate(x1+52,(y0+y1)/2);ctx.rotate(Math.PI/2);ctx.fillText("上涨比例（首个开盘价=100%）",0,0);ctx.restore();
  if(active!=null){const r=rows[active],x=xScale(r.t);ctx.setLineDash([5,5]);ctx.strokeStyle="rgba(31,41,55,.42)";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y0);ctx.lineTo(x,y1);ctx.stroke();ctx.setLineDash([]);if(hasOhlc(r)&&!hidden.brent){ctx.fillStyle="#fff";ctx.strokeStyle=colors.kline;ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,yPrice(r.c),3.6,0,Math.PI*2);ctx.fill();ctx.stroke()}}
}
function clampX(x){return Math.max(box.x0,Math.min(box.x1,x))}
function pointer(e){const rect=canvas.getBoundingClientRect();return{x:e.clientX-rect.left,y:e.clientY-rect.top,rect}}
function inPlot(p){return p.x>=box.x0&&p.x<=box.x1&&p.y>=box.y0&&p.y<=box.y1}
function timeAtX(x){return box.t0+(clampX(x)-box.x0)/(box.x1-box.x0)*(box.t1-box.t0)}
function hitLegend(p){return legendBoxes.find(b=>p.x>=b.x0&&p.x<=b.x1&&p.y>=b.y0&&p.y<=b.y1)}
function hitEvent(p){return eventBoxes.find(b=>p.x>=b.x0&&p.x<=b.x1&&p.y>=b.y0&&p.y<=b.y1)}
function nearest(mx){const source=rows.filter(hasOhlc);if(!source.length)return 0;const t=timeAtX(mx);let l=0,r=source.length-1;while(l<r){const m=(l+r)>>1;if(source[m].t<t)l=m+1;else r=m}if(l>0&&Math.abs(source[l-1].t-t)<Math.abs(source[l].t-t))l--;return rows.indexOf(source[l])}
function drawSelection(){if(!drag)return;const x0=clampX(drag.x0),x1=clampX(drag.x1),left=Math.min(x0,x1),width=Math.abs(x1-x0);if(width<3)return;ctx.fillStyle="rgba(111,74,168,.10)";ctx.strokeStyle="rgba(111,74,168,.55)";ctx.lineWidth=1;ctx.fillRect(left,box.y0,width,box.y1-box.y0);ctx.strokeRect(left,box.y0,width,box.y1-box.y0)}
function showTip(p){
  if(!inPlot(p)){tip.style.display="none";draw();return}
  const eventHit=hitEvent(p);
  if(eventHit){const e=eventHit.event;draw(null,e.date);const x=xScale(e.t);ctx.setLineDash([4,5]);ctx.strokeStyle=eventColor(e.score,.42);ctx.beginPath();ctx.moveTo(x,box.y0);ctx.lineTo(x,box.y1);ctx.stroke();ctx.setLineDash([]);tip.className="tip";tip.innerHTML=`<b>${e.label}</b><br>时间：${e.dateLabel}<br>类型：${e.type}<br>${e.description}`;tip.style.display="block";tip.style.left=Math.min(p.rect.width-310,Math.max(8,p.x+14))+"px";tip.style.top=Math.max(8,Math.min(p.rect.height-190,p.y-92))+"px";return}
  const i=nearest(p.x),r=rows[i];draw(i);
  const line=hidden.brent?"ICE Brent K线：-":`ICE Brent K线：${valueText(r)}`;
  tip.className="tip";tip.innerHTML=`<b>${r.date}（${periodNames[period]}）</b><br>${line}`;tip.style.display="block";tip.style.left=Math.min(p.rect.width-320,Math.max(8,p.x+14))+"px";tip.style.top=Math.max(8,Math.min(p.rect.height-178,p.y-70))+"px";
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
