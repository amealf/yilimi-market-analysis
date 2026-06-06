from __future__ import annotations

import json
import os
import subprocess
import time
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import Request, urlopen

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

from mobile_chart_support import add_canvas_mobile_support


START_DATE = "2014-01-01"
EASTMONEY_DATA_CENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
SINA_KLINE = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
OUT_DIR = Path(__file__).resolve().parent


def fetch_json(url: str, referer: str) -> dict:
    last_error: Exception | None = None
    for _ in range(3):
        req = Request(
            url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Connection": "close",
                "Referer": referer,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        try:
            with urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (IncompleteRead, RemoteDisconnected, TimeoutError, URLError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.8)
    if os.name == "nt":
        safe_url = url.replace("'", "''")
        safe_referer = referer.replace("'", "''")
        ps_script = (
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
            "$ProgressPreference='SilentlyContinue'; "
            f"$h=@{{Referer='{safe_referer}'; 'User-Agent'='Mozilla/5.0'}}; "
            f"(Invoke-WebRequest -Uri '{safe_url}' -Headers $h -UseBasicParsing -TimeoutSec 45).Content"
        )
        try:
            content = subprocess.check_output(
            ["powershell.exe", "-NoProfile", "-Command", ps_script],
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
            return json.loads(content)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"请求东方财富接口失败：{url}") from last_error


def fetch_margin_balance() -> pd.DataFrame:
    rows: list[dict] = []
    page_number = 1
    page_size = 400

    while True:
        params = {
            "reportName": "RPTA_RZRQ_LSHJ",
            "columns": "ALL",
            "source": "WEB",
            "sortColumns": "DIM_DATE",
            "sortTypes": "1",
            "pageNumber": page_number,
            "pageSize": page_size,
            "filter": f"(DIM_DATE>='{START_DATE}')",
        }
        url = f"{EASTMONEY_DATA_CENTER}?{urlencode(params)}"
        payload = fetch_json(url, "https://data.eastmoney.com/rzrq/")
        result = payload.get("result") or {}
        rows.extend(result.get("data") or [])

        pages = int(result.get("pages") or 1)
        if page_number >= pages:
            break

        page_number += 1
        time.sleep(0.15)

    if not rows:
        raise RuntimeError("东方财富融资余额接口没有返回数据")

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["DIM_DATE"]).dt.date
    df["margin_balance_yuan"] = pd.to_numeric(df["RZYE"], errors="coerce")
    df["margin_balance_trillion"] = df["margin_balance_yuan"] / 1_000_000_000_000
    return (
        df[["date", "margin_balance_yuan", "margin_balance_trillion"]]
        .dropna()
        .drop_duplicates(subset=["date"])
        .sort_values("date")
        .reset_index(drop=True)
    )


def fetch_index(secid: str, value_column: str, index_name: str) -> pd.DataFrame:
    params = {
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "beg": START_DATE.replace("-", ""),
        "end": "20500101",
    }
    url = f"{EASTMONEY_KLINE}?{urlencode(params)}"
    try:
        payload = fetch_json(url, "https://quote.eastmoney.com/")
    except RuntimeError:
        sina_symbol = {"1.000905": "sh000905", "0.399006": "sz399006"}[secid]
        return fetch_index_sina(sina_symbol, value_column, index_name)
    klines = ((payload.get("data") or {}).get("klines")) or []
    if not klines:
        raise RuntimeError(f"东方财富{index_name}接口没有返回数据")

    records = [line.split(",") for line in klines]
    df = pd.DataFrame(
        records,
        columns=[
            "date",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "amount",
            "amplitude",
            "pct_change",
            "change",
            "turnover",
        ],
    )
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df[value_column] = pd.to_numeric(df["close"], errors="coerce")
    return df[["date", value_column]].dropna().sort_values("date").reset_index(drop=True)


def fetch_index_sina(symbol: str, value_column: str, index_name: str) -> pd.DataFrame:
    params = {
        "symbol": symbol,
        "scale": "240",
        "ma": "no",
        "datalen": "5000",
    }
    url = f"{SINA_KLINE}?{urlencode(params)}"
    payload = fetch_json(url, "https://finance.sina.com.cn/")
    if not payload:
        raise RuntimeError(f"新浪{index_name}接口没有返回数据")

    df = pd.DataFrame(payload)
    df["date"] = pd.to_datetime(df["day"]).dt.date
    df[value_column] = pd.to_numeric(df["close"], errors="coerce")
    start_date = pd.to_datetime(START_DATE).date()
    df = df[df["date"] >= start_date]
    return df[["date", value_column]].dropna().sort_values("date").reset_index(drop=True)


def fetch_csi500() -> pd.DataFrame:
    return fetch_index("1.000905", "csi500_close", "中证500")


def fetch_chinext() -> pd.DataFrame:
    return fetch_index("0.399006", "chinext_close", "创业板指")


def add_index_ratios(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    for source_column, target_column in [
        ("csi500_close", "csi500_ratio"),
        ("chinext_close", "chinext_ratio"),
    ]:
        valid = data[source_column].dropna()
        if valid.empty:
            data[target_column] = pd.NA
            continue
        base = float(valid.iloc[0])
        data[target_column] = data[source_column] / base * 100
    return data


def set_chinese_font() -> None:
    preferred_fonts = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS"]
    installed = {font.name for font in font_manager.fontManager.ttflist}
    for font in preferred_fonts:
        if font in installed:
            plt.rcParams["font.sans-serif"] = [font]
            break
    plt.rcParams["axes.unicode_minus"] = False


def chart_meta(data: pd.DataFrame) -> dict:
    margin = data.dropna(subset=["margin_balance_trillion"]).copy()
    csi500 = data.dropna(subset=["csi500_ratio"]).copy()
    chinext = data.dropna(subset=["chinext_ratio"]).copy()

    margin["date_ts"] = pd.to_datetime(margin["date"])
    csi500["date_ts"] = pd.to_datetime(csi500["date"])

    margin_2015 = margin[
        (margin["date_ts"] >= "2015-01-01") & (margin["date_ts"] <= "2015-12-31")
    ]
    csi_2015 = csi500[
        (csi500["date_ts"] >= "2015-01-01") & (csi500["date_ts"] <= "2015-12-31")
    ]

    margin_peak = margin_2015.loc[margin_2015["margin_balance_trillion"].idxmax()]
    bull_peak = csi_2015.loc[csi_2015["csi500_ratio"].idxmax()]
    crossed = margin[
        (margin["date_ts"] > margin_peak["date_ts"])
        & (margin["margin_balance_trillion"] > margin_peak["margin_balance_trillion"])
    ]
    cross_row = crossed.iloc[0] if len(crossed) else margin.iloc[-1]
    latest_margin = margin.iloc[-1]
    latest_csi = csi500.iloc[-1]
    latest_chinext = chinext.iloc[-1]

    def rounded(row: pd.Series, column: str, digits: int) -> float | None:
        value = row.get(column)
        return None if pd.isna(value) else round(float(value), digits)

    return {
        "marginPeakDate": str(margin_peak["date"]),
        "marginPeak": round(float(margin_peak["margin_balance_trillion"]), 6),
        "marginPeakCsi": rounded(margin_peak, "csi500_close", 2),
        "marginPeakChinext": rounded(margin_peak, "chinext_close", 2),
        "bullPeakDate": str(bull_peak["date"]),
        "bullPeakRatio": round(float(bull_peak["csi500_ratio"]), 6),
        "bullPeakMargin": rounded(bull_peak, "margin_balance_trillion", 6),
        "bullPeakCsi": rounded(bull_peak, "csi500_close", 2),
        "bullPeakChinext": rounded(bull_peak, "chinext_close", 2),
        "crossDate": str(cross_row["date"]),
        "crossMargin": round(float(cross_row["margin_balance_trillion"]), 6),
        "crossCsi": rounded(cross_row, "csi500_close", 2),
        "crossChinext": rounded(cross_row, "chinext_close", 2),
        "latestMarginDate": str(latest_margin["date"]),
        "latestMargin": round(float(latest_margin["margin_balance_trillion"]), 4),
        "latestCsiDate": str(latest_csi["date"]),
        "latestCsi": round(float(latest_csi["csi500_close"]), 2),
        "latestCsiRatio": round(float(latest_csi["csi500_ratio"]), 2),
        "latestChinextDate": str(latest_chinext["date"]),
        "latestChinext": round(float(latest_chinext["chinext_close"]), 2),
        "latestChinextRatio": round(float(latest_chinext["chinext_ratio"]), 2),
    }


def plot_overlay(data: pd.DataFrame, output_png: Path) -> None:
    set_chinese_font()
    meta = chart_meta(data)
    margin = data.dropna(subset=["margin_balance_trillion"])
    csi500 = data.dropna(subset=["csi500_ratio"])
    chinext = data.dropna(subset=["chinext_ratio"])

    fig, ax1 = plt.subplots(figsize=(15, 8), dpi=150)
    ax2 = ax1.twinx()

    line1 = ax1.plot(
        pd.to_datetime(margin["date"]),
        margin["margin_balance_trillion"],
        color="#ff7f0e",
        linewidth=1.25,
        label="A股融资余额（万亿元）",
    )
    ax1.axhline(
        meta["marginPeak"],
        color="#7bb8f8",
        linestyle="--",
        linewidth=0.8,
        alpha=0.7,
        label="2015年融资余额高点",
    )
    line2 = ax2.plot(
        pd.to_datetime(csi500["date"]),
        csi500["csi500_ratio"],
        color="#1f77b4",
        linewidth=1.0,
        label="中证500相对值",
    )
    line3 = ax2.plot(
        pd.to_datetime(chinext["date"]),
        chinext["chinext_ratio"],
        color="#7f7f7f",
        linewidth=1.0,
        alpha=0.5,
        label="创业板指相对值",
    )

    ax1.set_title("A股融资余额 与 中证500、创业板指", fontsize=16, pad=16)
    ax1.set_xlabel("日期")
    ax1.set_ylabel("融资余额（万亿元）", color="#ff7f0e")
    ax2.set_ylabel("股票指数相对值（2014-01=100）", color="#111111")
    ax1.tick_params(axis="y", labelcolor="#ff7f0e")
    ax2.tick_params(axis="y", labelcolor="#111111")
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax1.grid(True, axis="both", linestyle="--", linewidth=0.6, alpha=0.28)

    def annotate_left(date_text: str, y_value: float, text: str, xytext: tuple[int, int]) -> None:
        ax1.annotate(
            text,
            xy=(pd.to_datetime(date_text), y_value),
            xytext=xytext,
            textcoords="offset points",
            fontsize=9,
            color="#1f2937",
            arrowprops={"arrowstyle": "->", "color": "#64748b", "linewidth": 0.8},
            bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "#cbd5e1", "alpha": 0.9},
        )

    def value_line(label: str, value: float | None, digits: int = 0) -> str:
        if value is None:
            return ""
        return f"\n{label} {value:.{digits}f}点"

    def amount_line(value: float | None) -> str:
        if value is None:
            return ""
        return f"\n融资 {value:.4f}万亿"

    annotate_left(
        meta["marginPeakDate"],
        meta["marginPeak"],
        (
            f"2015融资高点\n{meta['marginPeakDate']}\n"
            f"融资 {meta['marginPeak']:.4f}万亿"
            f"{value_line('中证500', meta['marginPeakCsi'])}"
            f"{value_line('创业板指', meta['marginPeakChinext'])}"
        ),
        (28, 30),
    )
    annotate_left(
        meta["crossDate"],
        meta["crossMargin"],
        (
            f"融资突破旧高\n{meta['crossDate']}\n"
            f"融资 {meta['crossMargin']:.4f}万亿"
            f"{value_line('中证500', meta['crossCsi'])}"
            f"{value_line('创业板指', meta['crossChinext'])}"
        ),
        (18, -42),
    )
    ax2.annotate(
        (
            f"2015股指高点\n{meta['bullPeakDate']}"
            f"{amount_line(meta['bullPeakMargin'])}"
            f"{value_line('中证500', meta['bullPeakCsi'])}"
            f"{value_line('创业板指', meta['bullPeakChinext'])}"
        ),
        xy=(pd.to_datetime(meta["bullPeakDate"]), meta["bullPeakRatio"]),
        xytext=(26, -54),
        textcoords="offset points",
        fontsize=9,
        color="#1f2937",
        arrowprops={"arrowstyle": "->", "color": "#64748b", "linewidth": 0.8},
        bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "#cbd5e1", "alpha": 0.9},
    )

    lines = line1 + line2 + line3
    labels = [line.get_label() for line in lines]
    handles, extra_labels = ax1.get_legend_handles_labels()
    ax1.legend(lines + handles[1:], labels + extra_labels[1:], loc="upper left", frameon=False)

    note = (
        f"融资余额最新：{meta['latestMarginDate']}，{meta['latestMargin']:.4f}万亿元；"
        f"中证500最新：{meta['latestCsiDate']}，相对值{meta['latestCsiRatio']:.2f}；"
        f"创业板指最新：{meta['latestChinextDate']}，相对值{meta['latestChinextRatio']:.2f}。数据源：东方财富。"
    )
    fig.text(0.01, 0.01, note, fontsize=9, color="#555555")
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    fig.savefig(output_png, bbox_inches="tight")
    plt.close(fig)


def _write_interactive_html_previous(data: pd.DataFrame, output_html: Path) -> None:
    meta = chart_meta(data)

    def value_or_none(value: object, digits: int) -> float | None:
        return None if pd.isna(value) else round(float(value), digits)

    records = []
    for _, row in data.iterrows():
        records.append(
            [
                str(row["date"]),
                value_or_none(row["margin_balance_trillion"], 6),
                value_or_none(row["csi500_close"], 2),
                value_or_none(row["chinext_close"], 2),
                value_or_none(row["csi500_ratio"], 4),
                value_or_none(row["chinext_ratio"], 4),
            ]
        )

    payload = json.dumps(
        {"data": records, "meta": meta},
        ensure_ascii=False,
        separators=(",", ":"),
    )

    html = """
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>A股融资余额 与 中证500、创业板指</title><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#f4f6f8;color:#111827;font-family:"Microsoft YaHei",Arial,sans-serif}.page{position:relative;width:100vw;height:100vh;background:#fff}canvas{display:block;width:100vw;height:100vh}.tip{position:absolute;display:none;pointer-events:none;background:rgba(17,24,39,.93);color:#fff;border-radius:6px;padding:8px 10px;font-size:12px;line-height:1.65;box-shadow:0 8px 22px rgba(0,0,0,.2);white-space:nowrap}</style></head><body><div class="page"><canvas id="chart"></canvas><div class="tip" id="tip"></div></div><script>
const P=__PAYLOAD__;const rows=P.data.map(d=>({t:new Date(d[0]).getTime(),date:d[0],m:d[1],c:d[2],g:d[3],cr:d[4],gr:d[5]}));const meta=P.meta,canvas=document.getElementById("chart"),ctx=canvas.getContext("2d"),tip=document.getElementById("tip");let box={};function fmt(v,d=2){return v==null?"-":Number(v).toFixed(d)}function values(k){return rows.map(r=>r[k]).filter(v=>v!=null&&Number.isFinite(v))}function extent(keys){const a=keys.flatMap(k=>values(k));return [Math.min(...a),Math.max(...a)]}function niceTicks(min,max,n){const span=max-min,raw=span/Math.max(1,n),pow=Math.pow(10,Math.floor(Math.log10(raw))),base=[1,2,5,10].find(x=>x*pow>=raw)*pow,start=Math.ceil(min/base)*base,out=[];for(let v=start;v<=max+base*.5;v+=base)out.push(v);return out}function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}function textBox(text,x,y,align="left"){const lines=text.split("\\n"),pad=5,lh=16,w=Math.max(...lines.map(s=>ctx.measureText(s).width))+pad*2,h=lines.length*lh+pad*2;let bx=align==="right"?x-w:x;ctx.fillStyle="rgba(255,255,255,.92)";ctx.strokeStyle="#cbd5e1";ctx.lineWidth=.8;ctx.beginPath();ctx.roundRect(bx,y,w,h,5);ctx.fill();ctx.stroke();ctx.fillStyle="#1f2937";ctx.textAlign="left";lines.forEach((s,i)=>ctx.fillText(s,bx+pad,y+pad+12+i*lh));return{bx,y,w,h}}function drawLabel(p,text,dx,dy,color,side){const x=xScale(new Date(p.date).getTime()),y=side==="left"?yLeft(p.value):yRight(p.value);ctx.strokeStyle="#64748b";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+dx,y+dy);ctx.stroke();ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill();textBox(text,x+dx+(dx<0?-6:6),y+dy-20,dx<0?"right":"left")}let xScale,yLeft,yRight;function draw(active){const w=canvas.clientWidth,h=canvas.clientHeight,p={l:78,r:86,t:66,b:76},x0=p.l,x1=w-p.r,y0=h-p.b,y1=p.t;ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);ctx.font="12px Microsoft YaHei,Arial";const tmin=rows[0].t,tmax=rows[rows.length-1].t,[mMin0,mMax0]=extent(["m"]),[rMin0,rMax0]=extent(["cr","gr"]);const mMin=Math.max(0,mMin0*.9),mMax=Math.max(mMax0,meta.marginPeak)*1.08,rMin=Math.max(0,rMin0*.9),rMax=rMax0*1.08;box={x0,x1,y0,y1,tmin,tmax,mMin,mMax,rMin,rMax};xScale=t=>x0+(t-tmin)/(tmax-tmin)*(x1-x0);yLeft=v=>y0-(v-mMin)/(mMax-mMin)*(y0-y1);yRight=v=>y0-(v-rMin)/(rMax-rMin)*(y0-y1);ctx.fillStyle="#111827";ctx.font="700 22px Microsoft YaHei,Arial";ctx.textAlign="center";ctx.fillText("A股融资余额 与 中证500、创业板指",w/2,32);ctx.font="12px Microsoft YaHei,Arial";ctx.lineWidth=.6;niceTicks(mMin,mMax,6).forEach(v=>{const y=yLeft(v);ctx.strokeStyle="#e5e7eb";ctx.beginPath();ctx.moveTo(x0,y);ctx.lineTo(x1,y);ctx.stroke();ctx.fillStyle="#ff7f0e";ctx.textAlign="right";ctx.fillText(v.toFixed(1),x0-9,y+4)});niceTicks(rMin,rMax,6).forEach(v=>{const y=yRight(v);ctx.fillStyle="#111";ctx.textAlign="left";ctx.fillText(Math.round(v),x1+9,y+4)});for(let y=2014;y<=new Date(rows[rows.length-1].t).getFullYear();y++){const x=xScale(new Date(`${y}-01-01`).getTime());ctx.strokeStyle="#eef2f7";ctx.beginPath();ctx.moveTo(x,y1);ctx.lineTo(x,y0);ctx.stroke();ctx.fillStyle="#4b5563";ctx.textAlign="center";ctx.fillText(y,x,y0+24)}ctx.strokeStyle="#111827";ctx.lineWidth=1;ctx.strokeRect(x0,y1,x1-x0,y0-y1);function path(key,color,width,scale){ctx.beginPath();let open=false;for(const r of rows){const v=r[key];if(v==null){open=false;continue}const x=xScale(r.t),y=scale(v);if(!open){ctx.moveTo(x,y);open=true}else ctx.lineTo(x,y)}ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke()}path("m","#ff7f0e",1.18,yLeft);path("cr","#1f77b4",1.0,yRight);path("gr","rgba(127,127,127,.5)",1.0,yRight);const py=yLeft(meta.marginPeak);ctx.setLineDash([6,4]);ctx.strokeStyle="#7bb8f8";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x0,py);ctx.lineTo(x1,py);ctx.stroke();ctx.setLineDash([]);ctx.save();ctx.translate(22,(y0+y1)/2);ctx.rotate(-Math.PI/2);ctx.fillStyle="#ff7f0e";ctx.textAlign="center";ctx.fillText("融资余额（万亿元）",0,0);ctx.restore();ctx.save();ctx.translate(w-24,(y0+y1)/2);ctx.rotate(Math.PI/2);ctx.fillStyle="#111";ctx.textAlign="center";ctx.fillText("股票指数相对值（2014-01=100）",0,0);ctx.restore();drawLabel({date:meta.bullPeakDate,value:meta.bullPeakRatio},`2015股指高点\\n${meta.bullPeakDate}`,34,-48,"#111","right");drawLabel({date:meta.marginPeakDate,value:meta.marginPeak},`2015融资高点\\n${meta.marginPeakDate}`,34,28,"#ff7f0e","left");drawLabel({date:meta.crossDate,value:meta.crossMargin},`融资突破旧高\\n${meta.crossDate}`,-34,-44,"#ff7f0e","left");drawLegend(x0,y0+43);ctx.fillStyle="#4b5563";ctx.textAlign="left";ctx.font="12px Microsoft YaHei,Arial";if(new URLSearchParams(location.search).get("embed")!=="1")ctx.fillText(`融资余额最新：${meta.latestMarginDate}，${fmt(meta.latestMargin,4)}万亿元；中证500相对值：${fmt(meta.latestCsiRatio,2)}；创业板指相对值：${fmt(meta.latestChinextRatio,2)}。数据源：东方财富。`,x0,y0+64);if(active!=null){const r=rows[active],x=xScale(r.t);ctx.strokeStyle="rgba(31,41,55,.42)";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y1);ctx.lineTo(x,y0);ctx.stroke();[[r.m,yLeft,"#ff7f0e"],[r.cr,yRight,"#1f77b4"],[r.gr,yRight,"rgba(127,127,127,.5)"]].forEach(([v,scale,color])=>{if(v!=null){ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,scale(v),3,0,Math.PI*2);ctx.fill()}})}}function drawLegend(x,y){const items=[["#ff7f0e","A股融资余额（万亿元）"],["#1f77b4","中证500相对值"],["rgba(127,127,127,.5)","创业板指相对值"],["#7bb8f8","2015年融资余额高点"]];ctx.font="13px Microsoft YaHei,Arial";let cur=x;items.forEach(([color,label],i)=>{ctx.strokeStyle=color;ctx.lineWidth=i===3?.8:2;ctx.setLineDash(i===3?[6,4]:[]);ctx.beginPath();ctx.moveTo(cur,y);ctx.lineTo(cur+28,y);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle="#374151";ctx.textAlign="left";ctx.fillText(label,cur+36,y+4);cur+=ctx.measureText(label).width+76})}function nearest(mx){const t=box.tmin+(mx-box.x0)/(box.x1-box.x0)*(box.tmax-box.tmin);let l=0,r=rows.length-1;while(l<r){const mid=(l+r)>>1;if(rows[mid].t<t)l=mid+1;else r=mid}if(l>0&&Math.abs(rows[l-1].t-t)<Math.abs(rows[l].t-t))l--;return l}canvas.addEventListener("mousemove",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(x<box.x0||x>box.x1||y<box.y1||y>box.y0){tip.style.display="none";draw();return}const i=nearest(x),r=rows[i];draw(i);tip.innerHTML=`<b>${r.date}</b><br>融资余额：${fmt(r.m,4)} 万亿元<br>中证500收盘：${fmt(r.c,2)}，相对值 ${fmt(r.cr,2)}<br>创业板指收盘：${fmt(r.g,2)}，相对值 ${fmt(r.gr,2)}`;tip.style.display="block";tip.style.left=Math.min(rect.width-230,Math.max(8,x+14))+"px";tip.style.top=Math.max(8,y-54)+"px"});canvas.addEventListener("mouseleave",()=>{tip.style.display="none";draw()});window.addEventListener("resize",resize);resize();
</script></body></html>
"""
    html = html.replace("__PAYLOAD__", payload)
    html = "".join(line.strip() for line in html.splitlines())
    html = add_canvas_mobile_support(html)
    output_html.write_text(html, encoding="utf-8")


def _write_interactive_html_click_legend(data: pd.DataFrame, output_html: Path) -> None:
    meta = chart_meta(data)

    def value_or_none(value: object, digits: int) -> float | None:
        return None if pd.isna(value) else round(float(value), digits)

    records = []
    for _, row in data.iterrows():
        records.append(
            [
                str(row["date"]),
                value_or_none(row["margin_balance_trillion"], 6),
                value_or_none(row["csi500_close"], 2),
                value_or_none(row["chinext_close"], 2),
                value_or_none(row["csi500_ratio"], 4),
                value_or_none(row["chinext_ratio"], 4),
            ]
        )

    payload = json.dumps(
        {"data": records, "meta": meta},
        ensure_ascii=False,
        separators=(",", ":"),
    )

    html = """
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>A股融资余额 与 中证500、创业板指</title><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#f4f6f8;color:#111827;font-family:"Microsoft YaHei",Arial,sans-serif}.page{position:relative;width:100vw;height:100vh;background:#fff}canvas{display:block;width:100vw;height:100vh}.tip{position:absolute;display:none;pointer-events:none;background:rgba(17,24,39,.93);color:#fff;border-radius:6px;padding:8px 10px;font-size:12px;line-height:1.65;box-shadow:0 8px 22px rgba(0,0,0,.2);white-space:nowrap}</style></head><body><div class="page"><canvas id="chart"></canvas><div class="tip" id="tip"></div></div><script>
const P=__PAYLOAD__;const rows=P.data.map(d=>({t:new Date(d[0]).getTime(),date:d[0],m:d[1],c:d[2],g:d[3],cr:d[4],gr:d[5]}));const meta=P.meta,canvas=document.getElementById("chart"),ctx=canvas.getContext("2d"),tip=document.getElementById("tip");const colors={m:"#ff7f0e",cr:"#1f77b4",gr:"rgba(127,127,127,.5)",peak:"#7bb8f8"};let box={},legendHits=[],visible={m:true,cr:true,gr:true,peak:true},xScale,yLeft,yRight;function fmt(v,d=2){return v==null?"-":Number(v).toFixed(d)}function amountLine(v){return v==null?"":`\\n融资 ${fmt(v,4)}万亿`}function pointLine(label,v){return v==null?"":`\\n${label} ${fmt(v,0)}点`}function values(k){return rows.map(r=>r[k]).filter(v=>v!=null&&Number.isFinite(v))}function extent(keys){const a=keys.flatMap(k=>values(k));return [Math.min(...a),Math.max(...a)]}function niceTicks(min,max,n){const span=max-min,raw=span/Math.max(1,n),pow=Math.pow(10,Math.floor(Math.log10(raw))),base=[1,2,5,10].find(x=>x*pow>=raw)*pow,start=Math.ceil(min/base)*base,out=[];for(let v=start;v<=max+base*.5;v+=base)out.push(v);return out}function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}function textBox(text,x,y,align="left"){const lines=text.split("\\n"),pad=5,lh=16,w=Math.max(...lines.map(s=>ctx.measureText(s).width))+pad*2,h=lines.length*lh+pad*2;let bx=align==="right"?x-w:x;ctx.fillStyle="rgba(255,255,255,.92)";ctx.strokeStyle="#cbd5e1";ctx.lineWidth=.8;ctx.beginPath();ctx.roundRect(bx,y,w,h,5);ctx.fill();ctx.stroke();ctx.fillStyle="#1f2937";ctx.textAlign="left";lines.forEach((s,i)=>ctx.fillText(s,bx+pad,y+pad+12+i*lh))}function drawLabel(p,text,dx,dy,color,side){const x=xScale(new Date(p.date).getTime()),y=side==="left"?yLeft(p.value):yRight(p.value);ctx.strokeStyle="#64748b";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+dx,y+dy);ctx.stroke();ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill();textBox(text,x+dx+(dx<0?-6:6),y+dy-20,dx<0?"right":"left")}function draw(active){const w=canvas.clientWidth,h=canvas.clientHeight,p={l:78,r:86,t:98,b:76},x0=p.l,x1=w-p.r,y0=h-p.b,y1=p.t;ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);ctx.font="12px Microsoft YaHei,Arial";const tmin=rows[0].t,tmax=rows[rows.length-1].t,[mMin0,mMax0]=extent(["m"]),[rMin0,rMax0]=extent(["cr","gr"]);const mMin=Math.max(0,mMin0*.9),mMax=Math.max(mMax0,meta.marginPeak)*1.08,rMin=Math.max(0,rMin0*.9),rMax=rMax0*1.08;box={x0,x1,y0,y1,tmin,tmax,mMin,mMax,rMin,rMax};xScale=t=>x0+(t-tmin)/(tmax-tmin)*(x1-x0);yLeft=v=>y0-(v-mMin)/(mMax-mMin)*(y0-y1);yRight=v=>y0-(v-rMin)/(rMax-rMin)*(y0-y1);ctx.fillStyle="#111827";ctx.font="700 22px Microsoft YaHei,Arial";ctx.textAlign="center";ctx.fillText("A股融资余额 与 中证500、创业板指",w/2,32);drawLegend(x0,58);ctx.font="12px Microsoft YaHei,Arial";ctx.lineWidth=.6;niceTicks(mMin,mMax,6).forEach(v=>{const y=yLeft(v);ctx.strokeStyle="#e5e7eb";ctx.beginPath();ctx.moveTo(x0,y);ctx.lineTo(x1,y);ctx.stroke();ctx.fillStyle="#ff7f0e";ctx.textAlign="right";ctx.fillText(v.toFixed(1),x0-9,y+4)});niceTicks(rMin,rMax,6).forEach(v=>{const y=yRight(v);ctx.fillStyle="#111";ctx.textAlign="left";ctx.fillText(Math.round(v),x1+9,y+4)});for(let y=2014;y<=new Date(rows[rows.length-1].t).getFullYear();y++){const x=xScale(new Date(`${y}-01-01`).getTime());ctx.strokeStyle="#eef2f7";ctx.beginPath();ctx.moveTo(x,y1);ctx.lineTo(x,y0);ctx.stroke();ctx.fillStyle="#4b5563";ctx.textAlign="center";ctx.fillText(y,x,y0+24)}ctx.strokeStyle="#111827";ctx.lineWidth=1;ctx.strokeRect(x0,y1,x1-x0,y0-y1);function path(key,color,width,scale){if(!visible[key])return;ctx.beginPath();let open=false;for(const r of rows){const v=r[key];if(v==null){open=false;continue}const x=xScale(r.t),y=scale(v);if(!open){ctx.moveTo(x,y);open=true}else ctx.lineTo(x,y)}ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke()}path("m",colors.m,1.18,yLeft);path("cr",colors.cr,1.0,yRight);path("gr",colors.gr,1.0,yRight);if(visible.peak){const py=yLeft(meta.marginPeak);ctx.setLineDash([6,4]);ctx.strokeStyle=colors.peak;ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x0,py);ctx.lineTo(x1,py);ctx.stroke();ctx.setLineDash([])}ctx.save();ctx.translate(22,(y0+y1)/2);ctx.rotate(-Math.PI/2);ctx.fillStyle="#ff7f0e";ctx.textAlign="center";ctx.fillText("融资余额（万亿元）",0,0);ctx.restore();ctx.save();ctx.translate(w-24,(y0+y1)/2);ctx.rotate(Math.PI/2);ctx.fillStyle="#111";ctx.textAlign="center";ctx.fillText("股票指数相对值（2014-01=100）",0,0);ctx.restore();if(visible.cr)drawLabel({date:meta.bullPeakDate,value:meta.bullPeakRatio},`2015股指高点\\n${meta.bullPeakDate}${amountLine(meta.bullPeakMargin)}${pointLine("中证500",meta.bullPeakCsi)}${pointLine("创业板指",meta.bullPeakChinext)}`,34,-54,"#111","right");if(visible.m&&visible.peak)drawLabel({date:meta.marginPeakDate,value:meta.marginPeak},`2015融资高点\\n${meta.marginPeakDate}\\n融资 ${fmt(meta.marginPeak,4)}万亿${pointLine("中证500",meta.marginPeakCsi)}${pointLine("创业板指",meta.marginPeakChinext)}`,34,30,colors.m,"left");if(visible.m)drawLabel({date:meta.crossDate,value:meta.crossMargin},`融资突破旧高\\n${meta.crossDate}\\n融资 ${fmt(meta.crossMargin,4)}万亿${pointLine("中证500",meta.crossCsi)}${pointLine("创业板指",meta.crossChinext)}`,-34,-54,colors.m,"left");ctx.fillStyle="#4b5563";ctx.textAlign="left";ctx.font="12px Microsoft YaHei,Arial";if(new URLSearchParams(location.search).get("embed")!=="1")ctx.fillText(`融资余额最新：${meta.latestMarginDate}，${fmt(meta.latestMargin,4)}万亿元；中证500相对值：${fmt(meta.latestCsiRatio,2)}；创业板指相对值：${fmt(meta.latestChinextRatio,2)}。数据源：东方财富。`,x0,y0+64);if(active!=null){const r=rows[active],x=xScale(r.t);ctx.strokeStyle="rgba(31,41,55,.42)";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y1);ctx.lineTo(x,y0);ctx.stroke();[[r.m,yLeft,colors.m,"m"],[r.cr,yRight,colors.cr,"cr"],[r.gr,yRight,colors.gr,"gr"]].forEach(([v,scale,color,key])=>{if(visible[key]&&v!=null){ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,scale(v),3,0,Math.PI*2);ctx.fill()}})}}function drawLegend(x,y){legendHits=[];const items=[{key:"m",color:colors.m,label:"A股融资余额（万亿元）"},{key:"cr",color:colors.cr,label:"中证500相对值"},{key:"gr",color:colors.gr,label:"创业板指相对值"},{key:"peak",color:colors.peak,label:"2015年融资余额高点",dash:true}];ctx.font="13px Microsoft YaHei,Arial";let cur=x;items.forEach(item=>{const textW=ctx.measureText(item.label).width,w=textW+46;legendHits.push({key:item.key,x:cur-4,y:y-14,w:w+8,h:26});ctx.globalAlpha=visible[item.key]?1:.28;ctx.strokeStyle=item.color;ctx.lineWidth=item.dash?.8:2;ctx.setLineDash(item.dash?[6,4]:[]);ctx.beginPath();ctx.moveTo(cur,y);ctx.lineTo(cur+28,y);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle="#374151";ctx.textAlign="left";ctx.fillText(item.label,cur+36,y+4);ctx.globalAlpha=1;cur+=w+30})}function legendAt(x,y){return legendHits.find(h=>x>=h.x&&x<=h.x+h.w&&y>=h.y&&y<=h.y+h.h)}function nearest(mx){const t=box.tmin+(mx-box.x0)/(box.x1-box.x0)*(box.tmax-box.tmin);let l=0,r=rows.length-1;while(l<r){const mid=(l+r)>>1;if(rows[mid].t<t)l=mid+1;else r=mid}if(l>0&&Math.abs(rows[l-1].t-t)<Math.abs(rows[l].t-t))l--;return l}canvas.addEventListener("click",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top,hit=legendAt(x,y);if(hit){visible[hit.key]=!visible[hit.key];tip.style.display="none";draw()}});canvas.addEventListener("mousemove",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top,hit=legendAt(x,y);canvas.style.cursor=hit?"pointer":"default";if(hit){tip.style.display="none";draw();return}if(x<box.x0||x>box.x1||y<box.y1||y>box.y0){tip.style.display="none";draw();return}const i=nearest(x),r=rows[i];draw(i);tip.innerHTML=`<b>${r.date}</b><br>融资余额：${fmt(r.m,4)} 万亿元<br>中证500收盘：${fmt(r.c,2)}，相对值 ${fmt(r.cr,2)}<br>创业板指收盘：${fmt(r.g,2)}，相对值 ${fmt(r.gr,2)}`;tip.style.display="block";tip.style.left=Math.min(rect.width-230,Math.max(8,x+14))+"px";tip.style.top=Math.max(8,y-54)+"px"});canvas.addEventListener("mouseleave",()=>{tip.style.display="none";canvas.style.cursor="default";draw()});window.addEventListener("resize",resize);resize();
</script></body></html>
"""
    html = html.replace("__PAYLOAD__", payload)
    html = "".join(line.strip() for line in html.splitlines())
    output_html.write_text(html, encoding="utf-8")


def write_interactive_html(data: pd.DataFrame, output_html: Path) -> None:
    meta = chart_meta(data)

    def value_or_none(value: object, digits: int) -> float | None:
        return None if pd.isna(value) else round(float(value), digits)

    records = []
    for _, row in data.iterrows():
        records.append(
            [
                str(row["date"]),
                value_or_none(row["margin_balance_trillion"], 6),
                value_or_none(row["csi500_close"], 2),
                value_or_none(row["chinext_close"], 2),
                value_or_none(row["csi500_ratio"], 4),
                value_or_none(row["chinext_ratio"], 4),
            ]
        )

    payload = json.dumps(
        {"data": records, "meta": meta},
        ensure_ascii=False,
        separators=(",", ":"),
    )

    html = """
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>A股融资余额 与 中证500、创业板指</title><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#f4f6f8;color:#111827;font-family:"Microsoft YaHei",Arial,sans-serif}.page{position:relative;width:100vw;height:100vh;background:#fff}canvas{display:block;width:100vw;height:100vh}.tip{position:absolute;display:none;pointer-events:none;background:rgba(17,24,39,.93);color:#fff;border-radius:6px;padding:8px 10px;font-size:12px;line-height:1.65;box-shadow:0 8px 22px rgba(0,0,0,.2);white-space:nowrap}</style></head><body><div class="page"><canvas id="chart"></canvas><div class="tip" id="tip"></div></div><script>
const P=__PAYLOAD__;const rows=P.data.map(d=>({t:new Date(d[0]).getTime(),date:d[0],m:d[1],c:d[2],g:d[3],cr:d[4],gr:d[5]}));const meta=P.meta,canvas=document.getElementById("chart"),ctx=canvas.getContext("2d"),tip=document.getElementById("tip");const colors={m:"#ff7f0e",cr:"#1f77b4",gr:"rgba(127,127,127,.5)",peak:"#7bb8f8"};let box={},legendHits=[],visible={m:true,cr:true,gr:true,peak:true},view=null,drag=null,selection=null,xScale,yLeft,yRight,plotRows=rows;function fmt(v,d=2){return v==null?"-":Number(v).toFixed(d)}function dayLabel(date){return `${date}（${"日一二三四五六"[new Date(`${date}T00:00:00Z`).getUTCDay()]}）`}function amountLine(v){return v==null?"":`\\n融资 ${fmt(v,4)}万亿`}function pointLine(label,v){return v==null?"":`\\n${label} ${fmt(v,0)}点`}function dataDomain(){const a=rows[0].t,b=rows[rows.length-1].t,pad=(b-a)*.045;return[a-pad,b+pad]}function values(k,source=plotRows){return source.map(r=>r[k]).filter(v=>v!=null&&Number.isFinite(v))}function extent(keys,source=plotRows){const a=keys.flatMap(k=>values(k,source));return a.length?[Math.min(...a),Math.max(...a)]:[0,1]}function niceTicks(min,max,n){const span=Math.max(1e-9,max-min),raw=span/Math.max(1,n),pow=Math.pow(10,Math.floor(Math.log10(raw))),base=[1,2,5,10].find(x=>x*pow>=raw)*pow,start=Math.ceil(min/base)*base,out=[];for(let v=start;v<=max+base*.5;v+=base)out.push(v);return out}function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}function textBox(text,x,y,align="left"){const lines=text.split("\\n"),pad=5,lh=16,w=Math.max(...lines.map(s=>ctx.measureText(s).width))+pad*2,h=lines.length*lh+pad*2;let bx=align==="right"?x-w:x;ctx.fillStyle="rgba(255,255,255,.92)";ctx.strokeStyle="#cbd5e1";ctx.lineWidth=.8;ctx.beginPath();ctx.roundRect(bx,y,w,h,5);ctx.fill();ctx.stroke();ctx.fillStyle="#1f2937";ctx.textAlign="left";lines.forEach((s,i)=>ctx.fillText(s,bx+pad,y+pad+12+i*lh))}function inRange(date){const t=new Date(date).getTime();return t>=box.tmin&&t<=box.tmax}function drawLabel(p,text,dx,dy,color,side){if(!inRange(p.date))return;const x=xScale(new Date(p.date).getTime()),y=side==="left"?yLeft(p.value):yRight(p.value);ctx.strokeStyle="#64748b";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+dx,y+dy);ctx.stroke();ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill();textBox(text,x+dx+(dx<0?-6:6),y+dy-20,dx<0?"right":"left")}function draw(active){const w=canvas.clientWidth,h=canvas.clientHeight,p={l:78,r:92,t:98,b:76},x0=p.l,x1=w-p.r,y0=h-p.b,y1=p.t,[fullMin,fullMax]=dataDomain(),tmin=view?view[0]:fullMin,tmax=view?view[1]:fullMax;plotRows=rows.filter(r=>r.t>=tmin&&r.t<=tmax);if(!plotRows.length)plotRows=rows;ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);ctx.font="12px Microsoft YaHei,Arial";const [mMin0,mMax0]=extent(["m"]),rKeys=[visible.cr?"cr":null,visible.gr?"gr":null].filter(Boolean),[rMin0,rMax0]=extent(rKeys.length?rKeys:["cr","gr"]);const mMin=Math.max(0,mMin0*.9),mMax=Math.max(mMax0,meta.marginPeak)*1.08,rMin=Math.max(0,rMin0*.9),rMax=rMax0*1.08;box={x0,x1,y0,y1,tmin,tmax,mMin,mMax,rMin,rMax};xScale=t=>x0+(t-tmin)/(tmax-tmin)*(x1-x0);yLeft=v=>y0-(v-mMin)/(mMax-mMin)*(y0-y1);yRight=v=>y0-(v-rMin)/(rMax-rMin)*(y0-y1);ctx.fillStyle="#111827";ctx.font="700 22px Microsoft YaHei,Arial";ctx.textAlign="center";ctx.fillText("A股融资余额 与 中证500、创业板指",w/2,32);drawLegend(x0,58);ctx.font="12px Microsoft YaHei,Arial";ctx.lineWidth=.6;niceTicks(mMin,mMax,6).forEach(v=>{const y=yLeft(v);ctx.strokeStyle="#e5e7eb";ctx.beginPath();ctx.moveTo(x0,y);ctx.lineTo(x1,y);ctx.stroke();ctx.fillStyle="#ff7f0e";ctx.textAlign="right";ctx.fillText(v.toFixed(1),x0-9,y+4)});niceTicks(rMin,rMax,6).forEach(v=>{const y=yRight(v);ctx.fillStyle="#111";ctx.textAlign="left";ctx.fillText(Math.round(v),x1+9,y+4)});const startYear=Math.max(2014,new Date(tmin).getFullYear()),endYear=new Date(tmax).getFullYear();for(let y=startYear;y<=endYear;y++){const x=xScale(new Date(`${y}-01-01`).getTime());if(x<x0||x>x1)continue;ctx.strokeStyle="#eef2f7";ctx.beginPath();ctx.moveTo(x,y1);ctx.lineTo(x,y0);ctx.stroke();ctx.fillStyle="#4b5563";ctx.textAlign="center";ctx.fillText(y,x,y0+24)}ctx.strokeStyle="#111827";ctx.lineWidth=1;ctx.strokeRect(x0,y1,x1-x0,y0-y1);function path(key,color,width,scale){if(!visible[key])return;ctx.beginPath();let open=false;for(const r of rows){const v=r[key];if(v==null||r.t<tmin||r.t>tmax){open=false;continue}const x=xScale(r.t),y=scale(v);if(!open){ctx.moveTo(x,y);open=true}else ctx.lineTo(x,y)}ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke()}path("m",colors.m,1.18,yLeft);path("cr",colors.cr,1.0,yRight);path("gr",colors.gr,1.0,yRight);if(visible.peak){const py=yLeft(meta.marginPeak);ctx.setLineDash([6,4]);ctx.strokeStyle=colors.peak;ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x0,py);ctx.lineTo(x1,py);ctx.stroke();ctx.setLineDash([])}ctx.save();ctx.translate(22,(y0+y1)/2);ctx.rotate(-Math.PI/2);ctx.fillStyle="#ff7f0e";ctx.textAlign="center";ctx.fillText("融资余额（万亿元）",0,0);ctx.restore();ctx.save();ctx.translate(w-24,(y0+y1)/2);ctx.rotate(Math.PI/2);ctx.fillStyle="#111";ctx.textAlign="center";ctx.fillText("股票指数相对值（2014-01=100）",0,0);ctx.restore();if(visible.cr)drawLabel({date:meta.bullPeakDate,value:meta.bullPeakRatio},`2015股指高点\\n${meta.bullPeakDate}${amountLine(meta.bullPeakMargin)}${pointLine("中证500",meta.bullPeakCsi)}${pointLine("创业板指",meta.bullPeakChinext)}`,34,-54,"#111","right");if(visible.m&&visible.peak)drawLabel({date:meta.marginPeakDate,value:meta.marginPeak},`2015融资高点\\n${meta.marginPeakDate}\\n融资 ${fmt(meta.marginPeak,4)}万亿${pointLine("中证500",meta.marginPeakCsi)}${pointLine("创业板指",meta.marginPeakChinext)}`,34,30,colors.m,"left");if(visible.m)drawLabel({date:meta.crossDate,value:meta.crossMargin},`融资突破旧高\\n${meta.crossDate}\\n融资 ${fmt(meta.crossMargin,4)}万亿${pointLine("中证500",meta.crossCsi)}${pointLine("创业板指",meta.crossChinext)}`,-34,-54,colors.m,"left");ctx.fillStyle="#4b5563";ctx.textAlign="left";ctx.font="12px Microsoft YaHei,Arial";if(new URLSearchParams(location.search).get("embed")!=="1")ctx.fillText(`融资余额最新：${meta.latestMarginDate}，${fmt(meta.latestMargin,4)}万亿元；中证500相对值：${fmt(meta.latestCsiRatio,2)}；创业板指相对值：${fmt(meta.latestChinextRatio,2)}。数据源：东方财富。`,x0,y0+64);if(active!=null){const r=rows[active],x=xScale(r.t);ctx.strokeStyle="rgba(31,41,55,.42)";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y1);ctx.lineTo(x,y0);ctx.stroke();[[r.m,yLeft,colors.m,"m"],[r.cr,yRight,colors.cr,"cr"],[r.gr,yRight,colors.gr,"gr"]].forEach(([v,scale,color,key])=>{if(visible[key]&&v!=null){ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,scale(v),3,0,Math.PI*2);ctx.fill()}})}if(selection){const x0s=clamp(selection.x0,box.x0,box.x1),x1s=clamp(selection.x1,box.x0,box.x1),left=Math.min(x0s,x1s),width=Math.abs(x1s-x0s);if(width>=3){ctx.fillStyle="rgba(111,74,168,.10)";ctx.strokeStyle="rgba(111,74,168,.55)";ctx.lineWidth=1;ctx.setLineDash([4,3]);ctx.fillRect(left,box.y1,width,box.y0-box.y1);ctx.strokeRect(left,box.y1,width,box.y0-box.y1);ctx.setLineDash([])}}}function drawLegend(x,y){legendHits=[];const items=[{key:"m",color:colors.m,label:"A股融资余额（万亿元）"},{key:"cr",color:colors.cr,label:"中证500相对值"},{key:"gr",color:colors.gr,label:"创业板指相对值"},{key:"peak",color:colors.peak,label:"2015年融资余额高点",dash:true}];ctx.font="13px Microsoft YaHei,Arial";let cur=x;items.forEach(item=>{const textW=ctx.measureText(item.label).width,w=textW+46;legendHits.push({key:item.key,x:cur-4,y:y-14,w:w+8,h:26});ctx.globalAlpha=visible[item.key]?1:.28;ctx.strokeStyle=item.color;ctx.lineWidth=item.dash?.8:2;ctx.setLineDash(item.dash?[6,4]:[]);ctx.beginPath();ctx.moveTo(cur,y);ctx.lineTo(cur+28,y);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle="#374151";ctx.textAlign="left";ctx.fillText(item.label,cur+36,y+4);ctx.globalAlpha=1;cur+=w+30})}function legendAt(x,y){return legendHits.find(h=>x>=h.x&&x<=h.x+h.w&&y>=h.y&&y<=h.y+h.h)}function inPlot(x,y){return x>=box.x0&&x<=box.x1&&y>=box.y1&&y<=box.y0}function clamp(v,a,b){return Math.max(a,Math.min(b,v))}function timeAtX(x){return box.tmin+(x-box.x0)/(box.x1-box.x0)*(box.tmax-box.tmin)}function nearest(mx){const source=plotRows.length?plotRows:rows,t=timeAtX(mx);let best=source[0],dist=Math.abs(source[0].t-t);for(const r of source){const d=Math.abs(r.t-t);if(d<dist){best=r;dist=d}}return rows.indexOf(best)}canvas.addEventListener("mousedown",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(legendAt(x,y)||!inPlot(x,y))return;drag={x0:x,x1:x};selection=null;tip.style.display="none";canvas.style.cursor="crosshair"});window.addEventListener("mouseup",e=>{if(!drag)return;const rect=canvas.getBoundingClientRect(),x=clamp(e.clientX-rect.left,box.x0,box.x1);drag.x1=x;const w=Math.abs(drag.x1-drag.x0);if(w>12){const a=Math.min(drag.x0,drag.x1),b=Math.max(drag.x0,drag.x1);view=[timeAtX(a),timeAtX(b)]}drag=null;selection=null;canvas.style.cursor="default";tip.style.display="none";draw()});canvas.addEventListener("dblclick",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(inPlot(x,y)){view=null;selection=null;tip.style.display="none";draw()}});canvas.addEventListener("click",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top,hit=legendAt(x,y);if(hit){visible[hit.key]=!visible[hit.key];tip.style.display="none";draw()}});canvas.addEventListener("mousemove",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(drag){drag.x1=clamp(x,box.x0,box.x1);selection=drag;tip.style.display="none";draw();return}const hit=legendAt(x,y);canvas.style.cursor=hit?"pointer":inPlot(x,y)?"crosshair":"default";if(hit){tip.style.display="none";draw();return}if(!inPlot(x,y)){tip.style.display="none";draw();return}const i=nearest(x),r=rows[i];draw(i);tip.innerHTML=`<b>${dayLabel(r.date)}</b><br>融资余额：${fmt(r.m,4)} 万亿元<br>中证500收盘：${fmt(r.c,2)}，相对值 ${fmt(r.cr,2)}<br>创业板指收盘：${fmt(r.g,2)}，相对值 ${fmt(r.gr,2)}`;tip.style.display="block";tip.style.left=Math.min(rect.width-230,Math.max(8,x+14))+"px";tip.style.top=Math.max(8,y-54)+"px"});canvas.addEventListener("mouseleave",()=>{if(drag)return;selection=null;tip.style.display="none";canvas.style.cursor="default";draw()});window.addEventListener("resize",resize);resize();
</script></body></html>
"""
    annotation_controls = """
<script>
visible.notes=new URLSearchParams(location.search).get("notes")!=="0";
const baseDrawLabel=drawLabel;
textBox=function(text,x,y,align="left"){const lines=text.split("\\n"),padX=12,padY=5,lh=16,extra=18,w=Math.max(...lines.map(s=>ctx.measureText(s).width))+padX*2+extra,h=lines.length*lh+padY*2;let bx=align==="right"?x-w:x;ctx.fillStyle="rgba(255,255,255,.84)";ctx.strokeStyle="#cbd5e1";ctx.lineWidth=.8;ctx.beginPath();ctx.roundRect(bx,y,w,h,6);ctx.fill();ctx.stroke();ctx.fillStyle="#1f2937";ctx.textAlign="left";lines.forEach((s,i)=>ctx.fillText(s,bx+padX,y+padY+12+i*lh))};
drawLabel=function(...args){if(!visible.notes)return;baseDrawLabel(...args)};
drawLegend=function(x,y){legendHits=[];const items=[{key:"m",color:colors.m,label:"A股融资余额（万亿元）"},{key:"cr",color:colors.cr,label:"中证500相对值"},{key:"gr",color:colors.gr,label:"创业板指相对值"},{key:"peak",color:colors.peak,label:"2015年融资余额高点",dash:true},{key:"notes",color:"#94a3b8",label:"文字注释"}];ctx.font="13px Microsoft YaHei,Arial";let cur=x;items.forEach(item=>{const textW=ctx.measureText(item.label).width,w=textW+46;legendHits.push({key:item.key,x:cur-4,y:y-14,w:w+8,h:26});ctx.globalAlpha=visible[item.key]?1:.28;ctx.strokeStyle=item.color;ctx.lineWidth=item.dash?.8:2;ctx.setLineDash(item.dash?[6,4]:[]);ctx.beginPath();ctx.moveTo(cur,y);ctx.lineTo(cur+28,y);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle="#374151";ctx.textAlign="left";ctx.fillText(item.label,cur+36,y+4);ctx.globalAlpha=1;cur+=w+30})};
draw();
</script>
"""
    html = html.replace("</script></body></html>", "</script>" + annotation_controls + "</body></html>")
    home_controls = """
<style>
.home-link{position:absolute;left:14px;top:14px;z-index:2;width:32px;height:32px;border:1px solid rgba(120,129,145,.34);border-radius:6px;display:flex;align-items:center;justify-content:center;color:#526071;background:rgba(255,255,255,.72);box-shadow:0 6px 18px rgba(15,23,42,.08);backdrop-filter:blur(2px)}
.is-embed .home-link{display:none}
.home-link:hover{color:#17202a;background:rgba(255,255,255,.94)}
.home-link svg{width:18px;height:18px;stroke:currentColor}
</style>
<script>if(new URLSearchParams(location.search).get("embed")==="1")document.documentElement.classList.add("is-embed");</script>
"""
    home_link = """<a class="home-link" href="../../index.html" aria-label="返回主页" title="返回主页"><svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/></svg></a>"""
    html = html.replace("</head>", home_controls + "</head>")
    html = html.replace('<div class="page">', '<div class="page">' + home_link, 1)
    html = html.replace("__PAYLOAD__", payload)
    html = "".join(line.strip() for line in html.splitlines())
    html = add_canvas_mobile_support(html)
    output_html.write_text(html, encoding="utf-8")


def main() -> int:
    margin = fetch_margin_balance()
    csi500 = fetch_csi500()
    chinext = fetch_chinext()
    data = pd.merge(margin, csi500, on="date", how="outer").sort_values("date")
    data = pd.merge(data, chinext, on="date", how="outer").sort_values("date")
    data = add_index_ratios(data)

    csv_path = OUT_DIR / "margin_csi500_data.csv"
    png_path = OUT_DIR / "margin_csi500_overlay.png"
    html_path = OUT_DIR / "margin_csi500_overlay.html"
    data.to_csv(csv_path, index=False, encoding="utf-8-sig")
    plot_overlay(data, png_path)
    write_interactive_html(data, html_path)

    print(f"CSV: {csv_path}")
    print(f"PNG: {png_path}")
    print(f"HTML: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

