from __future__ import annotations

import json
import html
import re
import subprocess
import time
from datetime import date, datetime, timezone
from http.client import IncompleteRead, RemoteDisconnected
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from mobile_chart_support import add_canvas_mobile_support


START_DATE = date(2015, 8, 7)
END_DATE = datetime.now(ZoneInfo("Asia/Shanghai")).date()
DISPLAY_START = pd.Timestamp("2018-09-01")
MAX_CACHE_STALENESS_DAYS = 3
PRICE_SOURCE = "https://min-api.cryptocompare.com/data/v2/histoday"
STABLECOIN_SOURCE = "https://stablecoins.llama.fi/stablecoincharts/all"
FRED_CSV_SOURCE = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FED_H15_TREASURY_CSV_SOURCE = (
    "https://www.federalreserve.gov/datadownload/Output.aspx?"
    "rel=H15&series=bf17364827e38702b42a58cf8eaa3f78&lastobs=&from=&to=&filetype=csv&"
    "label=include&layout=seriescolumn&type=package"
)
FARSIDE_BTC_ETF_FLOW_SOURCE = "https://r.jina.ai/http://r.jina.ai/http://https://farside.co.uk/bitcoin-etf-flow-all-data/"
PRICE_SYMBOLS = ["BTC", "ETH", "SOL", "BNB"]
MARKET_EVENTS = [
    {
        "date": "2020-03-15",
        "dateLabel": "2020-03-12 / 03-15",
        "timezone": "UTC-4（美国东部夏令时间）",
        "label": "COVID / Fed QE",
        "type": "美元流动性扩张起点",
        "description": "3月12日全球风险资产去杠杆，BTC大幅下跌；3月15日Fed将联邦基金目标区间降至0-0.25%，并宣布购买美债和MBS，成为后续风险资产与稳定币扩张的宏观起点。",
    },
    {
        "date": "2021-09-24",
        "dateLabel": "2021-09-24",
        "timezone": "UTC+8（中国标准时间）",
        "label": "中国禁令",
        "type": "监管冲击",
        "description": "中国监管机构强化对加密交易和挖矿的限制，PBOC称加密货币不得流通，境外交易所也不得向中国境内投资者提供服务。",
    },
    {
        "date": "2021-11-03",
        "dateLabel": "2021-11-03",
        "timezone": "UTC-4（美国东部夏令时间）",
        "label": "Fed Taper",
        "type": "流动性转折",
        "description": "Fed宣布开始降低资产购买速度，COVID流动性扩张由高峰转向边际收敛。",
    },
    {
        "date": "2022-03-16",
        "dateLabel": "2022-03-16",
        "timezone": "UTC-4（美国东部夏令时间）",
        "label": "Fed加息周期",
        "type": "美元收缩",
        "description": "Fed将目标利率区间上调至0.25%-0.50%，本轮加息周期开始，并表示后续还会继续加息，同时预告缩表。",
    },
    {
        "date": "2022-05-11",
        "dateLabel": "2022-05-10 / 05-11",
        "timezone": "UTC+0（加密市场日线）",
        "label": "UST脱锚",
        "type": "稳定币信用冲击",
        "description": "TerraUSD脱离1美元锚定并冲击加密市场，适合观察2022年稳定币信任危机和USDT发行量回落。",
    },
    {
        "date": "2022-06-01",
        "dateLabel": "2022-06-01",
        "timezone": "UTC-4（美国东部夏令时间）",
        "label": "QT开始",
        "type": "美元收缩",
        "description": "Fed缩表计划开始执行，美债和MBS到期不再再投资的月度上限逐步提高，美元流动性压力继续上升。",
    },
    {
        "date": "2023-03-12",
        "dateLabel": "2023-03-10 / 03-12",
        "timezone": "UTC-5/UTC-4（美国东部时间）",
        "label": "SVB / USDC",
        "type": "稳定币份额迁移",
        "description": "SVB进入接管后，Circle披露有33亿美元USDC储备在SVB，随后USDC出现赎回压力和脱锚，市场出现从USDC向USDT迁移的需求。",
    },
    {
        "date": "2024-01-10",
        "dateLabel": "2024-01-10",
        "timezone": "UTC-5（美国东部标准时间）",
        "label": "BTC ETF通过",
        "type": "监管/机构采用",
        "description": "SEC批准多个现货比特币ETP上市交易，这是2024年BTC强势的重要制度事件。",
    },
    {
        "date": "2024-06-01",
        "dateLabel": "2024-06-01",
        "timezone": "UTC-4（美国东部夏令时间）",
        "label": "QT降速",
        "type": "流动性压力缓和",
        "description": "Fed将美债缩表月度上限从600亿美元降至250亿美元，美元流动性压力边际放缓。",
    },
    {
        "date": "2024-09-18",
        "dateLabel": "2024-09-18",
        "timezone": "UTC-4（美国东部夏令时间）",
        "label": "Fed降息",
        "type": "流动性宽松信号",
        "description": "Fed将目标区间下调50bp至4.75%-5.00%，成为2024年后半段风险资产定价的重要转折。",
    },
    {
        "date": "2025-07-18",
        "dateLabel": "2025-07-18",
        "timezone": "UTC-4（美国东部夏令时间）",
        "label": "GENIUS法案",
        "type": "美国稳定币法案",
        "description": "美国签署GENIUS Act，为支付稳定币提供联邦监管框架，适合观察稳定币进入制度化阶段。",
    },
    {
        "date": "2025-12-10",
        "dateLabel": "2025-12-01 / 12-10",
        "timezone": "UTC-5（美国东部标准时间）",
        "label": "Fed再降息",
        "type": "降息 / 储备金管理",
        "description": "Fed将联邦基金目标区间下调至3.50%-3.75%。此前12月1日停止缩表，并通过短债购买维持充足准备金，适合观察美元流动性环境从缩表进入储备金管理阶段。",
    },
    {
        "date": "2026-06-05",
        "dateLabel": "2026-06-05",
        "timezone": "UTC-4（美国东部夏令时间）",
        "label": "非农超预期",
        "type": "利率预期冲击",
        "description": "BLS公布美国5月非农就业增加17.2万人，失业率维持4.3%；强于预期的数据推升高利率预期，风险资产承压。",
    },
]

EVENT_TRANSLATIONS_EN = {
    "2020-03-15": {
        "labelEn": "COVID / Fed QE",
        "typeEn": "Dollar liquidity expansion",
        "timezoneEn": "UTC-4 (US Eastern daylight time)",
        "descriptionEn": "Global deleveraging hit risk assets on March 12. On March 15, the Fed cut rates to 0-0.25% and restarted Treasury and MBS purchases.",
    },
    "2021-09-24": {
        "labelEn": "China ban",
        "typeEn": "Regulatory shock",
        "timezoneEn": "UTC+8 (China standard time)",
        "descriptionEn": "Chinese regulators tightened restrictions on crypto trading and mining, and barred offshore exchanges from serving mainland investors.",
    },
    "2021-11-03": {
        "labelEn": "Fed taper",
        "typeEn": "Liquidity turn",
        "timezoneEn": "UTC-4 (US Eastern daylight time)",
        "descriptionEn": "The Fed announced slower asset purchases, moving COVID-era liquidity expansion toward tapering.",
    },
    "2022-03-16": {
        "labelEn": "Fed hiking cycle",
        "typeEn": "Dollar tightening",
        "timezoneEn": "UTC-4 (US Eastern daylight time)",
        "descriptionEn": "The Fed raised the target range to 0.25%-0.50%, starting the rate-hiking cycle and signaling balance-sheet runoff.",
    },
    "2022-05-11": {
        "labelEn": "UST depeg",
        "typeEn": "Stablecoin credit shock",
        "timezoneEn": "UTC+0 (crypto market daily candle)",
        "descriptionEn": "TerraUSD broke its dollar peg and hit the broader crypto market, marking a major stablecoin confidence shock.",
    },
    "2022-06-01": {
        "labelEn": "QT starts",
        "typeEn": "Dollar tightening",
        "timezoneEn": "UTC-4 (US Eastern daylight time)",
        "descriptionEn": "Fed balance-sheet runoff started, raising dollar-liquidity pressure through Treasury and MBS rolloff caps.",
    },
    "2023-03-12": {
        "labelEn": "SVB / USDC",
        "typeEn": "Stablecoin share shift",
        "timezoneEn": "UTC-5/UTC-4 (US Eastern time)",
        "descriptionEn": "After SVB entered receivership, Circle disclosed $3.3B of USDC reserves at SVB. USDC redemptions and depeg pressure drove demand toward USDT.",
    },
    "2024-01-10": {
        "labelEn": "BTC ETF approval",
        "typeEn": "Regulation / institutional adoption",
        "timezoneEn": "UTC-5 (US Eastern standard time)",
        "descriptionEn": "The SEC approved multiple spot Bitcoin ETPs for listing and trading, a key institutional adoption event for BTC.",
    },
    "2024-06-01": {
        "labelEn": "QT slowdown",
        "typeEn": "Liquidity pressure eases",
        "timezoneEn": "UTC-4 (US Eastern daylight time)",
        "descriptionEn": "The Fed lowered the monthly Treasury runoff cap from $60B to $25B, easing marginal dollar-liquidity pressure.",
    },
    "2024-09-18": {
        "labelEn": "Fed rate cut",
        "typeEn": "Liquidity easing signal",
        "timezoneEn": "UTC-4 (US Eastern daylight time)",
        "descriptionEn": "The Fed cut the target range by 50 bps to 4.75%-5.00%, an important pricing turn for risk assets.",
    },
    "2025-07-18": {
        "labelEn": "GENIUS Act",
        "typeEn": "US stablecoin law",
        "timezoneEn": "UTC-4 (US Eastern daylight time)",
        "descriptionEn": "The US signed the GENIUS Act, creating a federal framework for payment stablecoins.",
    },
    "2025-12-10": {
        "labelEn": "Fed cuts again",
        "typeEn": "Rate cut / reserve management",
        "timezoneEn": "UTC-5 (US Eastern standard time)",
        "descriptionEn": "The Fed cut the target range to 3.50%-3.75%. Earlier, it stopped QT and used Treasury-bill purchases to maintain ample reserves.",
    },
    "2026-06-05": {
        "labelEn": "NFP beat",
        "typeEn": "Rate-expectation shock",
        "timezoneEn": "UTC-4 (US Eastern daylight time)",
        "descriptionEn": "BLS reported a 172K gain in May nonfarm payrolls and a 4.3% unemployment rate, lifting high-rate expectations and pressuring risk assets.",
    },
}

for event in MARKET_EVENTS:
    event.update(EVENT_TRANSLATIONS_EN.get(event["date"], {}))

DATA_EXPLANATION_ZH_MD = """# USDT发行量 与 BTC/ETH

## 用途

这张图用于同时观察加密资产价格、稳定币规模、BTC ETF资金、美国1Y利率和关键事件。它适合看资金环境和价格节奏是否同向，也适合发现背离。事件只用于辅助理解，不能单独当成因果结论。

## 价格与比值

BTC、ETH默认显示。SOL、BNB默认隐藏，可以点击图例开启。左轴可以在百分比和对数之间切换：百分比看相对起点的累计涨跌幅，对数形式适合观察长周期的大幅波动。

K线模式会按日、周、月、季显示开高低收。悬停窗仍显示美元价格和当期涨跌幅，方便同时看走势形态和具体价格。

BTC/ETH比值默认隐藏。它用 BTC价格 / ETH价格 计算，用来观察 BTC 相对 ETH 的强弱变化。比值上行表示 BTC 相对占优，比值下行表示 ETH 相对占优。

## 稳定币规模

USDT、USDC和USDT+USDC使用十亿美元为单位。USDT+USDC默认显示，可以作为链上美元存量的参考。

稳定币规模变化通常比价格慢。规模扩张时，说明链上可用美元存量增加；规模收缩时，说明链上美元存量减少。它更适合观察中期资金环境，不适合解释每一天的价格波动。

## ETF累计净流入

BTC ETF累计净流入显示美国现货 BTC ETF每日净流入的累计值，单位为十亿美元。它反映传统金融账户进入或退出 BTC 的资金压力。

ETF资金和稳定币资金属于不同入口。稳定币偏链上和交易所资金环境，ETF偏传统金融账户资金环境。两者同向时，资金信号更一致；两者背离时，需要结合价格和利率一起看。

## 美国1Y利率

美国1Y利率默认隐藏。它常用于观察短端美元利率和Fed政策利率路径的变化。

1Y利率上行时，风险资产通常面临短端利率压力；1Y利率下行时，市场可能在定价货币环境放松，也可能在定价增长压力。需要结合价格和资金同时判断。

## 事件

底部事件包含宏观政策、监管变化、稳定币冲击和ETF相关事件。悬停窗会显示事件日期和当地 UTC±x 时区。例如非农 2026-06-05 使用 UTC-4（美国东部夏令时间）。

事件的作用是给图表提供上下文。判断行情时，需要同时看事件发生前后的价格、稳定币、ETF资金和利率变化。

## 时间

价格采用 UTC日线。事件保留当地时区。刷新时间采用 UTC+8。
"""

DATA_EXPLANATION_EN_MD = """# USDT Supply and BTC/ETH

## Purpose

This chart brings together crypto prices, stablecoin supply, BTC ETF flows, the US 1Y yield, and key events. It helps compare price action with the funding backdrop and spot divergences. Event markers add context, but they should not be read as standalone causal proof.

## Prices and Ratio

BTC and ETH are visible by default. SOL and BNB are hidden by default and can be enabled from the legend. The left axis can switch between percent and log form: percent mode shows cumulative change from the chart start, while log form is useful for long periods with large moves.

Candle mode shows OHLC values by day, week, month, or quarter. The hover box still shows dollar prices and period changes, so price levels and chart shape can be read together.

The BTC/ETH ratio is hidden by default. It is calculated as BTC price / ETH price and helps track relative strength. A rising ratio means BTC is outperforming ETH; a falling ratio means ETH is outperforming BTC.

## Stablecoin Supply

USDT, USDC, and USDT+USDC are shown in billions of dollars. USDT+USDC is visible by default and can be used as a reference for on-chain dollar balances.

Stablecoin supply usually changes more slowly than prices. Expansion points to more on-chain dollar balances; contraction points to fewer on-chain dollar balances. It is better for reading the medium-term funding backdrop than for explaining every daily price move.

## ETF Cumulative Net Inflow

BTC ETF cumulative net inflow tracks cumulative daily net inflow into US spot BTC ETFs, shown in billions of dollars. It reflects buying or selling pressure through traditional financial accounts.

ETF money and stablecoin money enter the market through different channels. Stablecoins reflect on-chain and exchange funding conditions, while ETFs reflect traditional-account access to BTC. When both move together, the funding signal is more aligned; when they diverge, price and rates need extra attention.

## US 1Y Yield

The US 1Y yield is hidden by default. It is often used to read front-end dollar rates and the Fed policy-rate path.

When the 1Y yield rises, risk assets usually face front-end rate pressure. When it falls, the market may be pricing easier monetary conditions or weaker growth. Price, flows, and rates should be read together.

## Events

Bottom event markers cover macro policy, regulation, stablecoin shocks, and ETF-related events. The hover box shows the event date and local UTC±x timezone. For example, the 2026-06-05 nonfarm payrolls marker uses UTC-4 (US Eastern daylight time).

Events provide context for the chart. For market interpretation, compare prices, stablecoins, ETF flows, and rates before and after the event.

## Time

Prices use UTC daily candles. Events keep their local timezone. Refresh time uses UTC+8.
"""

DATA_EXPLANATION_MD = DATA_EXPLANATION_ZH_MD


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


def request_text(url: str, retries: int = 2, pause: float = 1.0, timeout: int = 15) -> str:
    last_error: Exception | None = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "Accept": "text/csv,text/plain,*/*",
                "Connection": "close",
                "User-Agent": "Mozilla/5.0",
            },
        )
        try:
            with urlopen(req, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError, IncompleteRead, RemoteDisconnected, OSError) as exc:
            last_error = exc
            time.sleep(pause * (attempt + 1))
    try:
        completed = subprocess.run(
            ["curl", "-L", "--silent", "--show-error", "--max-time", str(timeout), url],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.stdout.strip():
            return completed.stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        last_error = exc
    raise RuntimeError(f"Request failed: {url}") from last_error


def to_timestamp(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def fetch_price(symbol: str, column: str, start: date, end: date) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    to_ts = to_timestamp(end)
    start_ts = to_timestamp(start)

    while to_ts >= start_ts:
        query = urlencode({"fsym": symbol, "tsym": "USD", "limit": 2000, "toTs": to_ts})
        payload = request_json(f"{PRICE_SOURCE}?{query}")
        data = payload.get("Data", {}).get("Data", []) if isinstance(payload, dict) else []
        if not data:
            break
        valid_data = [
            item
            for item in data
            if isinstance(item, dict) and all(key in item for key in ["time", "open", "high", "low", "close"])
        ]
        if not valid_data:
            raise RuntimeError(f"{symbol} price payload has unexpected shape")
        rows.extend(valid_data)
        earliest = min(int(item["time"]) for item in valid_data)
        if earliest <= start_ts:
            break
        to_ts = earliest - 86400
        time.sleep(0.2)

    if not rows:
        raise RuntimeError(f"{symbol} price data is empty")

    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["time"], unit="s", utc=True).dt.tz_localize(None).dt.normalize()
    rename_map = {"open": f"{column}_open", "high": f"{column}_high", "low": f"{column}_low", "close": column}
    for source, target in rename_map.items():
        frame[target] = pd.to_numeric(frame[source], errors="coerce")
    output_columns = list(rename_map.values())
    frame = frame.loc[frame[output_columns].gt(0).all(axis=1)]
    frame = frame.loc[
        (frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end)),
        ["date", *output_columns],
    ]
    return frame.drop_duplicates("date").sort_values("date").set_index("date")


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


def fetch_fred_rate(series_id: str, column: str, start: date, end: date) -> pd.Series:
    try:
        text = request_text(f"{FRED_CSV_SOURCE}?{urlencode({'id': series_id})}", retries=3, pause=0.35, timeout=20)
    except Exception:
        if series_id != "DGS1":
            raise
        text = request_text(FED_H15_TREASURY_CSV_SOURCE, retries=3, pause=0.35, timeout=20)
        frame = pd.read_csv(StringIO(text), skiprows=5)
        frame = frame.rename(columns={"Time Period": "date", "RIFLGFCY01_N.B": column})
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["date"])
        frame = frame.loc[(frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end)), ["date", column]]
        return frame.drop_duplicates("date").sort_values("date").set_index("date")[column]
    frame = pd.read_csv(StringIO(text), parse_dates=["observation_date"])
    frame = frame.rename(columns={"observation_date": "date", series_id: column})
    frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.loc[(frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end)), ["date", column]]
    return frame.drop_duplicates("date").sort_values("date").set_index("date")[column]


def parse_farside_value(value: str) -> float | None:
    value = value.strip()
    if value == "-":
        return None
    value = value.replace(",", "")
    negative = value.startswith("(") and value.endswith(")")
    value = value.strip("()")
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return None
    return -float(number) if negative else float(number)


def fetch_btc_etf_total_flow(start: date, end: date) -> pd.Series:
    text = request_text(FARSIDE_BTC_ETF_FLOW_SOURCE, retries=1, pause=0.2, timeout=20)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    date_pattern = re.compile(r"^\d{2} [A-Z][a-z]{2} \d{4}$")
    rows: list[dict[str, object]] = []
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 14 or not date_pattern.match(cells[0]):
            continue
        rows.append(
            {
                "date": pd.to_datetime(cells[0], format="%d %b %Y", errors="coerce"),
                "btc_etf_flow": parse_farside_value(cells[-1]),
            }
        )
    if not rows:
        for index, line in enumerate(lines):
            if not date_pattern.match(line):
                continue
            values = lines[index + 1 : index + 14]
            if len(values) < 13:
                continue
            rows.append(
                {
                    "date": pd.to_datetime(line, format="%d %b %Y", errors="coerce"),
                    "btc_etf_flow": parse_farside_value(values[-1]),
                }
            )
    if not rows:
        raise RuntimeError("BTC ETF flow data is empty")

    frame = pd.DataFrame(rows).dropna(subset=["date"])
    if frame.empty:
        raise RuntimeError("BTC ETF flow data is empty")
    frame["btc_etf_flow"] = pd.to_numeric(frame["btc_etf_flow"], errors="coerce").fillna(0).cumsum()
    frame = frame.loc[
        (frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end)),
        ["date", "btc_etf_flow"],
    ]
    return frame.drop_duplicates("date").sort_values("date").set_index("date")["btc_etf_flow"]


def normalize_optional_macro_columns(data: pd.DataFrame) -> None:
    for column in ["us_1y"]:
        if column not in data.columns:
            data[column] = pd.NA
        data[column] = pd.to_numeric(data[column], errors="coerce").ffill()


def normalize_btc_etf_flow_column(data: pd.DataFrame) -> None:
    if "btc_etf_flow" not in data.columns:
        data["btc_etf_flow"] = pd.NA
    data["btc_etf_flow"] = pd.to_numeric(data["btc_etf_flow"], errors="coerce").ffill()


def normalize_price_columns(data: pd.DataFrame) -> None:
    for symbol in PRICE_SYMBOLS:
        if symbol not in data.columns:
            data[symbol] = pd.NA
        data[symbol] = pd.to_numeric(data[symbol], errors="coerce").ffill()


def normalize_price_ohlc_columns(data: pd.DataFrame) -> None:
    for symbol in PRICE_SYMBOLS:
        close = pd.to_numeric(data[symbol], errors="coerce")
        for suffix in ["open", "high", "low"]:
            column = f"{symbol}_{suffix}"
            if column not in data.columns:
                data[column] = close
            data[column] = pd.to_numeric(data[column], errors="coerce").ffill()


def add_btc_eth_ratio(data: pd.DataFrame) -> None:
    btc = pd.to_numeric(data["BTC"], errors="coerce")
    eth = pd.to_numeric(data["ETH"], errors="coerce")
    data["btc_eth_ratio"] = btc.where((btc > 0) & (eth > 0)) / eth.where((btc > 0) & (eth > 0))


def fetch_optional_macro_series() -> dict[str, pd.Series | None]:
    series: dict[str, pd.Series | None] = {"us_1y": None}
    try:
        series["us_1y"] = fetch_fred_rate("DGS1", "us_1y", START_DATE, END_DATE)
    except Exception:
        pass
    return series


def fetch_optional_btc_etf_flow() -> pd.Series | None:
    try:
        return fetch_btc_etf_total_flow(START_DATE, END_DATE)
    except Exception:
        return None


def add_transmission_index(data: pd.DataFrame) -> None:
    if "date" in data.columns:
        source = data[["date", "BTC", "usdt_b"]].copy()
    else:
        source = data[["BTC", "usdt_b"]].copy()
        source["date"] = data.index
    source["date"] = pd.to_datetime(source["date"])
    source["BTC"] = pd.to_numeric(source["BTC"], errors="coerce")
    source["usdt_b"] = pd.to_numeric(source["usdt_b"], errors="coerce")
    source = source.dropna(subset=["BTC", "usdt_b"])
    source = source.loc[(source["BTC"] > 0) & (source["usdt_b"] > 0)].set_index("date")

    for key, freq in [("week", "W-SUN"), ("month", "ME")]:
        column = f"transmission_{key}"
        data[column] = pd.NA
        if source.empty:
            continue

        periodic = source.resample(freq).last()
        periodic["btc_return"] = np.log(periodic["BTC"] / periodic["BTC"].shift(1))
        periodic["usdt_growth"] = np.log(periodic["usdt_b"] / periodic["usdt_b"].shift(1))
        periodic["usdt_marginal"] = periodic["usdt_growth"] - periodic["usdt_growth"].shift(1)
        valid = periodic.dropna(subset=["btc_return", "usdt_marginal"])
        if valid.empty:
            continue

        values = valid["usdt_marginal"].rank(pct=True) * 100 + valid["btc_return"].rank(pct=True) * 100 - 100
        if "date" in data.columns:
            data[column] = pd.to_datetime(data["date"]).map(values)
        else:
            data[column] = pd.Series(data.index, index=data.index).map(values)


def add_usdt_indicators(data: pd.DataFrame) -> None:
    add_transmission_index(data)


def build_indicator_frame(cache_path: Path | None = None) -> pd.DataFrame:
    try:
        btc = fetch_price("BTC", "BTC", START_DATE, END_DATE)
        eth = fetch_price("ETH", "ETH", START_DATE, END_DATE)
        sol = fetch_price("SOL", "SOL", START_DATE, END_DATE)
        bnb = fetch_price("BNB", "BNB", START_DATE, END_DATE)
        usdt = fetch_stablecoin_supply(1, "USDT", START_DATE, END_DATE)
        usdc = fetch_stablecoin_supply(2, "USDC", START_DATE, END_DATE)
    except Exception as exc:
        if cache_path and cache_path.exists():
            cached = pd.read_csv(cache_path, parse_dates=["date"])
            if "stable_b" not in cached.columns:
                cached["stable_b"] = cached[["usdt_b", "usdc_b"]].sum(axis=1, min_count=1)
            normalize_optional_macro_columns(cached)
            for column, macro in fetch_optional_macro_series().items():
                if macro is not None:
                    cached[column] = pd.to_datetime(cached["date"]).map(macro)
            normalize_optional_macro_columns(cached)
            normalize_btc_etf_flow_column(cached)
            normalize_price_columns(cached)
            normalize_price_ohlc_columns(cached)
            add_btc_eth_ratio(cached)
            add_usdt_indicators(cached)
            return cached.drop(columns=["dxy", "us_rate", "us_2y"], errors="ignore")
        raise

    macro_series = fetch_optional_macro_series()
    btc_etf_flow = fetch_optional_btc_etf_flow()
    index = pd.date_range(START_DATE, END_DATE, freq="D")
    data = pd.DataFrame(index=index)
    data = data.join(btc).join(eth).join(sol).join(bnb).join(usdt).join(usdc)
    for macro in macro_series.values():
        if macro is not None:
            data = data.join(macro)
    if btc_etf_flow is not None:
        data = data.join(btc_etf_flow)
    normalize_optional_macro_columns(data)
    normalize_btc_etf_flow_column(data)
    data = data.drop(columns=["dxy", "us_rate"], errors="ignore")
    for column in [*PRICE_SYMBOLS, "USDT", "USDC"]:
        if column not in data.columns:
            data[column] = pd.NA
        data[column] = data[column].ffill()
    normalize_price_columns(data)
    normalize_price_ohlc_columns(data)
    add_btc_eth_ratio(data)

    data["usdt_b"] = data["USDT"] / 1e9
    data["usdc_b"] = data["USDC"] / 1e9
    data["stable_b"] = data[["usdt_b", "usdc_b"]].sum(axis=1, min_count=1)
    add_usdt_indicators(data)

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
    sol_start = first_valid_date(data, "SOL")
    bnb_start = first_valid_date(data, "BNB")
    return {
        "latestDate": str(max(latest_btc["date"], latest_usdt["date"]).date()),
        "btc": round(float(latest_btc["BTC"]), 2),
        "eth": round(float(latest_eth["ETH"]), 2),
        "usdt": round(float(latest_usdt["USDT"]) / 1e9, 2),
        "usdc": round(float(latest_usdc["USDC"]) / 1e9, 2),
        "dataNote": f"BTC/ETH/SOL/BNB 行情从 {btc_start}/{eth_start}/{sol_start}/{bnb_start} 开始；USDT/USDC 发行量从 {usdt_start}/{usdc_start} 开始。",
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


def _write_interactive_html_legacy(data: pd.DataFrame, output_html: Path) -> None:
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
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>USDT发行量 与 BTC/ETH</title><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#fff;color:#17202a;font-family:"Microsoft YaHei",Arial,sans-serif}.page{position:relative;width:100vw;height:100vh;background:#fff}canvas{display:block;width:100vw;height:100vh}.tip{position:absolute;display:none;pointer-events:none;min-width:230px;background:rgba(255,255,255,.68);border:1px solid rgba(120,129,145,.42);border-radius:6px;color:#17202a;padding:9px 10px;font-size:12px;line-height:1.65;box-shadow:0 8px 22px rgba(15,23,42,.12);backdrop-filter:blur(2px)}</style></head><body><div class="page"><canvas id="chart"></canvas><div class="tip" id="tip"></div></div><script>
const P=__PAYLOAD__,rows=P.rows.map(r=>({...r,t:new Date(r.date).getTime()})),canvas=document.getElementById("chart"),ctx=canvas.getContext("2d"),tip=document.getElementById("tip");const colors={btc:"#4472C4",eth:"#A5A5A5",usdt:"#ED7D31",usdc:"#FFC000",grid:"#dfe6ed",text:"#17202a",muted:"#526071"};let box={};function usd(v,d=0){return v==null?"-":"$"+Number(v).toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d})}function b(v){return v==null?"-":Number(v).toFixed(2)+"B"}function values(key){return rows.map(r=>r[key]).filter(v=>v!=null&&Number.isFinite(v))}function extent(keys){const a=keys.flatMap(k=>values(k));return[Math.min(...a),Math.max(...a)]}function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}function xScale(t){return box.x0+(t-box.t0)/(box.t1-box.t0)*(box.x1-box.x0)}function yLog(v){return box.mainY1-(Math.log(v)-box.priceMin)/(box.priceMax-box.priceMin)*(box.mainY1-box.mainY0)}function ySupply(v){return box.mainY1-(v-box.supplyMin)/(box.supplyMax-box.supplyMin)*(box.mainY1-box.mainY0)}function ySub(v,pane){return pane.y1-(v-pane.min)/(pane.max-pane.min)*(pane.y1-pane.y0)}function path(key,scale,color,width,pane){ctx.beginPath();let open=false;rows.forEach(r=>{const v=r[key];if(v==null||!Number.isFinite(v)){open=false;return}const x=xScale(r.t),y=scale(v,pane);if(!open){ctx.moveTo(x,y);open=true}else ctx.lineTo(x,y)});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke()}function gridLine(y,x0,x1){ctx.strokeStyle=colors.grid;ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(x0,y);ctx.lineTo(x1,y);ctx.stroke()}function drawLegend(x,y){const items=[["btc",colors.btc,"BTC"],["eth",colors.eth,"ETH"],["usdt",colors.usdt,"USDT发行量"],["usdc",colors.usdc,"USDC发行量"]];ctx.font="12px Microsoft YaHei,Arial";let cur=x;items.forEach(([key,color,label])=>{ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(cur,y);ctx.lineTo(cur+28,y);ctx.stroke();ctx.fillStyle=colors.text;ctx.textAlign="left";ctx.fillText(label,cur+36,y+4);cur+=ctx.measureText(label).width+74})}function draw(active){const w=canvas.clientWidth,h=canvas.clientHeight,p={l:78,r:88,t:78,b:40,g:12},usable=h-p.t-p.b-p.g*3,mainH=usable*.52,subH=(usable-mainH)/3,x0=p.l,x1=w-p.r,mainY0=p.t,mainY1=p.t+mainH;const panes=[{key:"ma5",title:"USDT发行量 5日均线",y0:mainY1+p.g,y1:mainY1+p.g+subH},{key:"ma30",title:"USDT发行量 30日均线",y0:mainY1+p.g*2+subH,y1:mainY1+p.g*2+subH*2},{key:"ma60",title:"USDT发行量 60日均线",y0:mainY1+p.g*3+subH*2,y1:mainY1+p.g*3+subH*3}];const [priceMin0,priceMax0]=extent(["btc","eth"]),[supplyMin0,supplyMax0]=extent(["usdt","usdc"]);box={x0,x1,mainY0,mainY1,t0:rows[0].t,t1:rows[rows.length-1].t,priceMin:Math.log(priceMin0*.75),priceMax:Math.log(priceMax0*1.18),supplyMin:0,supplyMax:supplyMax0*1.1,panes};panes.forEach(pane=>{const [mn,mx]=extent([pane.key]);pane.min=Math.max(0,mn*.98);pane.max=mx*1.02});ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);ctx.fillStyle=colors.text;ctx.font="700 21px Microsoft YaHei,Arial";ctx.textAlign="center";ctx.fillText("BTC/ETH 与 USDT/USDC 发行量",w/2,24);ctx.font="12px Microsoft YaHei,Arial";ctx.fillStyle=colors.muted;ctx.textAlign="left";ctx.fillText(`${P.meta.latestDate}  BTC ${usd(P.meta.btc)}  ETH ${usd(P.meta.eth)}  USDT ${b(P.meta.usdt)}  USDC ${b(P.meta.usdc)}`,x0,44);drawLegend(x0,62);const startY=new Date(box.t0).getUTCFullYear(),endY=new Date(box.t1).getUTCFullYear();for(let y=startY;y<=endY;y++){const x=xScale(new Date(`${y}-01-01T00:00:00Z`).getTime());if(x<x0||x>x1)continue;ctx.strokeStyle="#edf2f7";ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(x,mainY0);ctx.lineTo(x,panes[2].y1);ctx.stroke();ctx.fillStyle=colors.muted;ctx.textAlign="center";ctx.fillText(y,x,panes[2].y1+25)}[10,100,1000,10000,100000].forEach(v=>{if(Math.log(v)<box.priceMin||Math.log(v)>box.priceMax)return;const y=yLog(v);gridLine(y,x0,x1);ctx.fillStyle=colors.btc;ctx.textAlign="right";ctx.fillText(usd(v),x0-9,y+4)});[0,50,100,150,200,250].forEach(v=>{if(v>box.supplyMax)return;const y=ySupply(v);ctx.fillStyle="#6b7280";ctx.textAlign="left";ctx.fillText("$"+v+"B",x1+9,y+4)});ctx.strokeStyle="#cfd8e2";ctx.strokeRect(x0,mainY0,x1-x0,mainY1-mainY0);path("btc",(v)=>yLog(v),colors.btc,1.15);path("eth",(v)=>yLog(v),colors.eth,1.05);path("usdt",(v)=>ySupply(v),colors.usdt,1.15);path("usdc",(v)=>ySupply(v),colors.usdc,1.15);ctx.fillStyle=colors.btc;ctx.textAlign="center";ctx.save();ctx.translate(24,(mainY0+mainY1)/2);ctx.rotate(-Math.PI/2);ctx.fillText("BTC / ETH（log USD）",0,0);ctx.restore();ctx.save();ctx.translate(w-24,(mainY0+mainY1)/2);ctx.rotate(Math.PI/2);ctx.fillStyle=colors.usdt;ctx.fillText("USDT / USDC 发行量",0,0);ctx.restore();panes.forEach(pane=>{ctx.strokeStyle="#cfd8e2";ctx.strokeRect(x0,pane.y0,x1-x0,pane.y1-pane.y0);const mid=(pane.min+pane.max)/2;[pane.min,mid,pane.max].forEach(v=>{const y=ySub(v,pane);gridLine(y,x0,x1);ctx.fillStyle=colors.muted;ctx.textAlign="right";ctx.fillText(b(v),x0-9,y+4)});ctx.fillStyle=colors.text;ctx.textAlign="left";ctx.font="12px Microsoft YaHei,Arial";ctx.fillText(pane.title,x0+8,pane.y0+16);path(pane.key,(v,p)=>ySub(v,p),colors.usdt,1.05,pane)});if(active!=null){const r=rows[active],x=xScale(r.t);ctx.setLineDash([5,5]);ctx.strokeStyle="rgba(82,96,113,.62)";ctx.beginPath();ctx.moveTo(x,mainY0);ctx.lineTo(x,panes[2].y1);ctx.stroke();ctx.setLineDash([]);[["btc",yLog,colors.btc],["eth",yLog,colors.eth],["usdt",ySupply,colors.usdt],["usdc",ySupply,colors.usdc]].forEach(([key,scale,color])=>{if(r[key]==null)return;ctx.fillStyle="#fff";ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,scale(r[key]),3.6,0,Math.PI*2);ctx.fill();ctx.stroke()});panes.forEach(pane=>{const v=r[pane.key];if(v==null)return;ctx.fillStyle="#fff";ctx.strokeStyle=colors.usdt;ctx.beginPath();ctx.arc(x,ySub(v,pane),3.2,0,Math.PI*2);ctx.fill();ctx.stroke()})}}function nearest(mx){const t=box.t0+(mx-box.x0)/(box.x1-box.x0)*(box.t1-box.t0);let l=0,r=rows.length-1;while(l<r){const m=(l+r)>>1;if(rows[m].t<t)l=m+1;else r=m}if(l>0&&Math.abs(rows[l-1].t-t)<Math.abs(rows[l].t-t))l--;return l}canvas.addEventListener("mousemove",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(x<box.x0||x>box.x1||y<box.mainY0||y>box.panes[2].y1){tip.style.display="none";draw();return}const i=nearest(x),r=rows[i];draw(i);tip.innerHTML=`<b>${r.date}</b><br>BTC：${usd(r.btc)}<br>ETH：${usd(r.eth)}<br>USDT发行量：${b(r.usdt)}<br>USDC发行量：${b(r.usdc)}<br>USDT 5日均线：${b(r.ma5)}<br>USDT 30日均线：${b(r.ma30)}<br>USDT 60日均线：${b(r.ma60)}`;tip.style.display="block";tip.style.left=Math.min(rect.width-250,Math.max(8,x+14))+"px";tip.style.top=Math.max(8,Math.min(rect.height-180,y-70))+"px"});canvas.addEventListener("mouseleave",()=>{tip.style.display="none";draw()});window.addEventListener("resize",resize);resize();
</script></body></html>
"""
    output_html.write_text("".join(line.strip() for line in html_text.replace("__PAYLOAD__", payload).splitlines()), encoding="utf-8")


def _write_interactive_html_overlay_legacy(data: pd.DataFrame, output_html: Path) -> None:
    meta = chart_meta(data)
    display_data = data.loc[data["date"] >= DISPLAY_START]
    records = []
    for row in display_data.itertuples(index=False):
        records.append(
            {
                "date": row.date.strftime("%Y-%m-%d"),
                "btc": series_value(row.BTC, 2),
                "eth": series_value(row.ETH, 2),
                "usdt": series_value(row.usdt_b, 4),
                "usdc": series_value(row.usdc_b, 4),
                "stable": series_value(row.stable_b, 4),
            }
        )

    payload = json.dumps({"rows": records, "meta": meta}, ensure_ascii=False, separators=(",", ":"))
    html_text = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>USDT发行量 与 BTC/ETH</title>
  <style>
    html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#fff;color:#17202a;font-family:"Microsoft YaHei",Arial,sans-serif}
    .page{position:relative;width:100vw;height:100vh;background:#fff}
    canvas{display:block;width:100vw;height:100vh}
    .tip{position:absolute;display:none;pointer-events:none;min-width:250px;background:rgba(255,255,255,.68);border:1px solid rgba(120,129,145,.42);border-radius:6px;color:#17202a;padding:9px 10px;font-size:12px;line-height:1.65;box-shadow:0 8px 22px rgba(15,23,42,.12);backdrop-filter:blur(2px)}
  </style>
</head>
<body>
<div class="page"><canvas id="chart"></canvas><div class="tip" id="tip"></div></div>
<script>
const P=__PAYLOAD__;
const rows=P.rows.map(r=>({...r,t:new Date(r.date).getTime()}));
const canvas=document.getElementById("chart");
const ctx=canvas.getContext("2d");
const tip=document.getElementById("tip");
const colors={btc:"#4472C4",eth:"#A5A5A5",usdt:"#ED7D31",usdc:"#FFC000",dev5:"rgba(111,74,168,.50)",dev30:"rgba(111,74,168,.50)",dev60:"rgba(111,74,168,.50)",grid:"#dfe6ed",text:"#17202a",muted:"#526071"};
let box={},zoom=null,drag=null;
function usd(v,d=0){return v==null?"-":"$"+Number(v).toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d})}
function b(v){return v==null?"-":Number(v).toFixed(2)+"B"}
function values(key){return rows.map(r=>r[key]).filter(v=>v!=null&&Number.isFinite(v))}
function extent(keys,list=rows){const a=keys.flatMap(k=>list.map(r=>r[k]).filter(v=>v!=null&&Number.isFinite(v)));return a.length?[Math.min(...a),Math.max(...a)]:[0,1]}
function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}
function xScale(t){return box.x0+(t-box.t0)/(box.t1-box.t0)*(box.x1-box.x0)}
function yLog(v){return box.y1-(Math.log(v)-box.priceMin)/(box.priceMax-box.priceMin)*(box.y1-box.y0)}
function ySupply(v){return box.y1-(v-box.supplyMin)/(box.supplyMax-box.supplyMin)*(box.y1-box.y0)}
function yDev(v){return box.y1-(v-box.devMin)/(box.devMax-box.devMin)*(box.y1-box.y0)}
function drawPath(key,scale,color,width,dash=[]){if(key==="dev5"){width=.65;dash=[2,4]}else if(key==="dev30"){width=.85}else if(key==="dev60"){width=.75;dash=[6,5]}ctx.beginPath();let open=false;rows.forEach(r=>{const v=r[key];if(v==null||!Number.isFinite(v)){open=false;return}const x=xScale(r.t),y=scale(v);if(!open){ctx.moveTo(x,y);open=true}else ctx.lineTo(x,y)});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([])}
function gridLine(y){ctx.strokeStyle=colors.grid;ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(box.x0,y);ctx.lineTo(box.x1,y);ctx.stroke()}
function drawLegend(x,y){const items=[["btc",colors.btc,"BTC",[]],["eth",colors.eth,"ETH",[]],["usdt",colors.usdt,"USDT发行量",[]],["usdc",colors.usdc,"USDC发行量",[]],["dev5",colors.dev5,"5D全均",[2,4]],["dev30",colors.dev30,"30D全均",[]],["dev60",colors.dev60,"60D全均",[6,5]]];ctx.font="12px Microsoft YaHei,Arial";let cur=x,rowY=y;items.forEach((item,index)=>{if(index===4){cur=x;rowY=y+18}const [key,color,label,dash]=item;ctx.strokeStyle=color;ctx.lineWidth=key.startsWith("dev")?1.2:2;ctx.setLineDash(dash);ctx.beginPath();ctx.moveTo(cur,rowY);ctx.lineTo(cur+28,rowY);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle=colors.text;ctx.textAlign="left";ctx.fillText(label,cur+36,rowY+4);cur+=ctx.measureText(label).width+76})}
function drawAxes(){[10,100,1000,10000,100000].forEach(v=>{if(Math.log(v)<box.priceMin||Math.log(v)>box.priceMax)return;const y=yLog(v);gridLine(y);ctx.fillStyle=colors.btc;ctx.textAlign="right";ctx.fillText(usd(v),box.x0-9,y+4)});[0,50,100,150,200,250].forEach(v=>{if(v>box.supplyMax)return;const y=ySupply(v);ctx.fillStyle=colors.usdt;ctx.textAlign="left";ctx.fillText("$"+v+"B",box.x1+9,y+4)});const step=box.devTick;[-2,-1,0,1,2].map(n=>n*step).forEach(v=>{if(v<box.devMin||v>box.devMax)return;const y=yDev(v);if(v===0){ctx.setLineDash([5,5]);ctx.strokeStyle="rgba(82,96,113,.45)";ctx.beginPath();ctx.moveTo(box.x0,y);ctx.lineTo(box.x1,y);ctx.stroke();ctx.setLineDash([])}ctx.fillStyle="#6f4aa8";ctx.textAlign="left";ctx.fillText((v>0?"+":"")+v.toFixed(1)+"B",box.x1+62,y+4)})}
function draw(active){const w=canvas.clientWidth,h=canvas.clientHeight,p={l:78,r:138,t:96,b:42},x0=p.l,x1=w-p.r,y0=p.t,y1=h-p.b;const [priceMin0,priceMax0]=extent(["btc","eth"]),[supplyMin0,supplyMax0]=extent(["usdt","usdc"]),[devMin0,devMax0]=extent(["dev5","dev30","dev60"]);const devAbs=Math.max(Math.abs(devMin0),Math.abs(devMax0),.5),devTick=Math.ceil(devAbs/2*10)/10;box={x0,x1,y0,y1,t0:rows[0].t,t1:rows[rows.length-1].t,priceMin:Math.log(priceMin0*.75),priceMax:Math.log(priceMax0*1.18),supplyMin:0,supplyMax:supplyMax0*1.1,devMin:-devTick*2,devMax:devTick*2,devTick};ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);ctx.fillStyle=colors.text;ctx.font="700 21px Microsoft YaHei,Arial";ctx.textAlign="center";ctx.fillText("BTC/ETH 与 USDT/USDC 发行量",w/2,24);ctx.font="12px Microsoft YaHei,Arial";ctx.fillStyle=colors.muted;ctx.textAlign="left";ctx.fillText(`${P.meta.latestDate}  BTC ${usd(P.meta.btc)}  ETH ${usd(P.meta.eth)}  USDT ${b(P.meta.usdt)}  USDC ${b(P.meta.usdc)}`,x0,44);drawLegend(x0,62);const startY=new Date(box.t0).getUTCFullYear(),endY=new Date(box.t1).getUTCFullYear();for(let year=startY;year<=endY;year++){const x=xScale(new Date(`${year}-01-01T00:00:00Z`).getTime());if(x<x0||x>x1)continue;ctx.strokeStyle="#edf2f7";ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(x,y0);ctx.lineTo(x,y1);ctx.stroke();ctx.fillStyle=colors.muted;ctx.textAlign="center";ctx.fillText(year,x,y1+25)}drawAxes();ctx.strokeStyle="#cfd8e2";ctx.strokeRect(x0,y0,x1-x0,y1-y0);drawPath("btc",yLog,colors.btc,1.15);drawPath("eth",yLog,colors.eth,1.05);drawPath("usdt",ySupply,colors.usdt,1.15);drawPath("usdc",ySupply,colors.usdc,1.15);drawPath("dev5",yDev,colors.dev5,1.15);drawPath("dev30",yDev,colors.dev30,1.25);drawPath("dev60",yDev,colors.dev60,1.25);ctx.fillStyle=colors.btc;ctx.textAlign="center";ctx.save();ctx.translate(24,(y0+y1)/2);ctx.rotate(-Math.PI/2);ctx.fillText("BTC / ETH（log USD）",0,0);ctx.restore();ctx.save();ctx.translate(w-64,(y0+y1)/2);ctx.rotate(Math.PI/2);ctx.fillStyle=colors.usdt;ctx.fillText("USDT / USDC 发行量",0,0);ctx.restore();ctx.save();ctx.translate(w-18,(y0+y1)/2);ctx.rotate(Math.PI/2);ctx.fillStyle="#6f4aa8";ctx.fillText("USDT净增-全样本均值",0,0);ctx.restore();if(active!=null){const r=rows[active],x=xScale(r.t);ctx.setLineDash([5,5]);ctx.strokeStyle="rgba(82,96,113,.62)";ctx.beginPath();ctx.moveTo(x,y0);ctx.lineTo(x,y1);ctx.stroke();ctx.setLineDash([]);[["btc",yLog,colors.btc],["eth",yLog,colors.eth],["usdt",ySupply,colors.usdt],["usdc",ySupply,colors.usdc],["dev5",yDev,colors.dev5],["dev30",yDev,colors.dev30],["dev60",yDev,colors.dev60]].forEach(([key,scale,color])=>{if(r[key]==null)return;ctx.fillStyle="#fff";ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,scale(r[key]),3.3,0,Math.PI*2);ctx.fill();ctx.stroke()})}}
function nearest(mx){const t=box.t0+(mx-box.x0)/(box.x1-box.x0)*(box.t1-box.t0);let l=0,r=rows.length-1;while(l<r){const m=(l+r)>>1;if(rows[m].t<t)l=m+1;else r=m}if(l>0&&Math.abs(rows[l-1].t-t)<Math.abs(rows[l].t-t))l--;return l}
canvas.addEventListener("mousemove",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;if(x<box.x0||x>box.x1||y<box.y0||y>box.y1){tip.style.display="none";draw();return}const i=nearest(x),r=rows[i];draw(i);tip.innerHTML=`<b>${r.date}</b><br>BTC：${usd(r.btc)}<br>ETH：${usd(r.eth)}<br>USDT发行量：${b(r.usdt)}<br>USDC发行量：${b(r.usdc)}<br>5D净增-全样本均值：${b(r.dev5)}<br>30D净增-全样本均值：${b(r.dev30)}<br>60D净增-全样本均值：${b(r.dev60)}`;tip.style.display="block";tip.style.left=Math.min(rect.width-270,Math.max(8,x+14))+"px";tip.style.top=Math.max(8,Math.min(rect.height-178,y-70))+"px"});
canvas.addEventListener("mouseleave",()=>{tip.style.display="none";draw()});
window.addEventListener("resize",resize);
resize();
</script>
</body>
</html>
"""
    html_text = add_canvas_mobile_support(html_text)
    output_html.write_text(html_text.replace("__PAYLOAD__", payload), encoding="utf-8")


def inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)


def render_markdown_document(markdown_text: str) -> str:
    blocks: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{inline_markdown(' '.join(paragraph))}</p>")
            paragraph.clear()

    for raw_line in markdown_text.strip().splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            continue
        match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if match:
            flush_paragraph()
            level = len(match.group(1))
            blocks.append(f"<h{level}>{inline_markdown(match.group(2))}</h{level}>")
            continue
        paragraph.append(line)
    flush_paragraph()
    return "\n".join(blocks)


def render_data_explanation_html(zh_markdown: str, en_markdown: str) -> str:
    zh_body = render_markdown_document(zh_markdown)
    en_body = render_markdown_document(en_markdown)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>USDT发行量 与 BTC/ETH 数据解释</title>
  <style>
    body{{margin:0;background:#eef3f7;color:#17202a;font-family:"Microsoft YaHei",Arial,sans-serif;line-height:1.7}}
    main{{max-width:860px;margin:0 auto;padding:34px 18px 48px}}
    article{{background:#fff;border:1px solid #d7e0e8;border-radius:8px;padding:28px 32px;box-shadow:0 12px 30px rgba(15,23,42,.07)}}
    h1{{margin:0 0 20px;font-size:30px;line-height:1.28;text-align:center}}
    h2{{margin:26px 0 10px;font-size:21px;line-height:1.38}}
    h3{{margin:22px 0 8px;font-size:19px;line-height:1.38}}
    p{{margin:0 0 15px;color:#344054;font-size:18px}}
    code{{padding:2px 5px;border-radius:4px;background:#f1f5f9;color:#0f172a;font-family:Consolas,monospace;font-size:.92em}}
    a{{color:#2563eb;text-decoration:underline;text-underline-offset:2px}}
    .back{{display:inline-flex;margin-bottom:14px;color:#2563eb;font-size:16px}}
    .lang-switch{{position:fixed;right:16px;bottom:16px;z-index:5;display:inline-flex;align-items:center;justify-content:center;min-width:54px;height:34px;border:1px solid rgba(120,129,145,.34);border-radius:7px;background:rgba(255,255,255,.82);color:#2563eb;font-weight:700;box-shadow:0 8px 22px rgba(15,23,42,.12);backdrop-filter:blur(4px);cursor:pointer}}
    .lang-switch:hover{{background:#fff;color:#17202a}}
    .doc-lang{{display:none}}
    body[data-lang="zh"] .doc-zh{{display:block}}
    body[data-lang="en"] .doc-en{{display:block}}
    @media (max-width:640px){{main{{padding:18px 10px 32px}}article{{padding:20px 18px}}h1{{font-size:28px}}h2{{font-size:20px}}p{{font-size:16px}}}}
  </style>
</head>
<body>
  <main>
    <a class="back" id="backLink" href="usdt-speed-indicator.html">返回图表</a>
    <article class="doc-lang doc-zh">
      {zh_body}
    </article>
    <article class="doc-lang doc-en">
      {en_body}
    </article>
  </main>
  <button class="lang-switch" id="langSwitch" type="button" aria-label="Switch language"></button>
  <script>
    const params=new URLSearchParams(location.search);
    let lang=params.get("lang")==="en"?"en":"zh";
    const backLink=document.getElementById("backLink");
    const switcher=document.getElementById("langSwitch");
    function applyLang(){{
      document.body.dataset.lang=lang;
      document.documentElement.lang=lang==="en"?"en":"zh-CN";
      backLink.textContent=lang==="en"?"Back to chart":"返回图表";
      backLink.href=`usdt-speed-indicator.html?lang=${{lang}}`;
      switcher.textContent=lang==="en"?"中":"EN";
    }}
    switcher.addEventListener("click",()=>{{
      lang=lang==="en"?"zh":"en";
      params.set("lang",lang);
      history.replaceState(null,"",`${{location.pathname}}?${{params.toString()}}`);
      applyLang();
    }});
    applyLang();
  </script>
</body>
</html>
"""


def write_data_explanation(output_html: Path) -> None:
    markdown_path = output_html.with_name("usdt-speed-indicator-data-explained.md")
    html_path = output_html.with_name("usdt-speed-indicator-data-explained.html")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(DATA_EXPLANATION_ZH_MD, encoding="utf-8")
    html_path.write_text(render_data_explanation_html(DATA_EXPLANATION_ZH_MD, DATA_EXPLANATION_EN_MD), encoding="utf-8")


def write_interactive_html(data: pd.DataFrame, output_html: Path) -> None:
    meta = chart_meta(data)
    generated_at = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    data = data.copy()
    normalize_btc_etf_flow_column(data)
    normalize_price_columns(data)
    normalize_price_ohlc_columns(data)
    add_btc_eth_ratio(data)
    data["btc_daily_pct"] = data["BTC"].pct_change() * 100
    data["eth_daily_pct"] = data["ETH"].pct_change() * 100
    display_data = data.loc[data["date"] >= DISPLAY_START]
    records = []
    for row in display_data.itertuples(index=False):
        records.append(
            {
                "date": row.date.strftime("%Y-%m-%d"),
                "btc": series_value(row.BTC, 2),
                "btcOpen": series_value(row.BTC_open, 2),
                "btcHigh": series_value(row.BTC_high, 2),
                "btcLow": series_value(row.BTC_low, 2),
                "eth": series_value(row.ETH, 2),
                "ethOpen": series_value(row.ETH_open, 2),
                "ethHigh": series_value(row.ETH_high, 2),
                "ethLow": series_value(row.ETH_low, 2),
                "sol": series_value(row.SOL, 2),
                "solOpen": series_value(row.SOL_open, 2),
                "solHigh": series_value(row.SOL_high, 2),
                "solLow": series_value(row.SOL_low, 2),
                "bnb": series_value(row.BNB, 2),
                "bnbOpen": series_value(row.BNB_open, 2),
                "bnbHigh": series_value(row.BNB_high, 2),
                "bnbLow": series_value(row.BNB_low, 2),
                "btcEthRatio": series_value(row.btc_eth_ratio, 4),
                "btcDaily": series_value(row.btc_daily_pct, 2),
                "ethDaily": series_value(row.eth_daily_pct, 2),
                "usdt": series_value(row.usdt_b, 4),
                "usdc": series_value(row.usdc_b, 4),
                "stable": series_value(row.stable_b, 4),
                "us1y": series_value(row.us_1y, 4),
                "btcEtfFlow": series_value(row.btc_etf_flow, 2),
                "transmissionWeek": series_value(row.transmission_week, 4),
                "transmissionMonth": series_value(row.transmission_month, 4),
            }
        )

    payload = json.dumps(
        {
            "rows": records,
            "meta": meta,
            "events": MARKET_EVENTS,
            "generatedAt": generated_at,
            "dataSources": "CryptoCompare、DefiLlama、FRED、Farside Investors",
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
  <title>USDT发行量 与 BTC/ETH</title>
  <style>
    html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#fff;color:#17202a;font-family:"Microsoft YaHei",Arial,sans-serif}
    .page{position:relative;width:100vw;height:100vh;background:#fff}
    .home-link{position:absolute;left:14px;top:14px;z-index:2;width:32px;height:32px;border:1px solid rgba(120,129,145,.34);border-radius:6px;display:flex;align-items:center;justify-content:center;color:#526071;background:rgba(255,255,255,.72);box-shadow:0 6px 18px rgba(15,23,42,.08);backdrop-filter:blur(2px)}
    .is-embed .home-link{display:none}
    .home-link:hover{color:#17202a;background:rgba(255,255,255,.94)}
    .home-link svg{width:18px;height:18px;stroke:currentColor}
    canvas{display:block;width:100vw;height:100vh;cursor:crosshair}
    .tip{position:absolute;display:none;pointer-events:none;box-sizing:border-box;min-width:230px;max-width:390px;background:rgba(255,255,255,.10);border:1px solid rgba(120,129,145,.42);border-radius:6px;color:#17202a;padding:9px 10px;font-size:12px;line-height:1.65;box-shadow:0 8px 22px rgba(15,23,42,.12);backdrop-filter:blur(2px);overflow-wrap:anywhere;white-space:normal}
    .footer-note{position:absolute;left:100px;right:86px;bottom:8px;z-index:2;display:flex;gap:10px;align-items:center;flex-wrap:wrap;color:#526071;font-size:11px;line-height:1.35;pointer-events:none}
    .footer-note a{color:#2563eb;text-decoration:underline;text-underline-offset:2px;pointer-events:auto}
    .is-embed .footer-note{display:none}
    .lang-switch{position:absolute;right:14px;bottom:8px;z-index:3;display:inline-flex;align-items:center;justify-content:center;min-width:52px;height:30px;border:1px solid rgba(120,129,145,.34);border-radius:7px;background:rgba(255,255,255,.82);color:#2563eb;font-size:12px;font-weight:700;box-shadow:0 8px 22px rgba(15,23,42,.10);backdrop-filter:blur(4px);cursor:pointer}
    .lang-switch:hover{background:#fff;color:#17202a}
    .is-embed .lang-switch{display:none}
    @media (max-width:640px){.footer-note{left:92px;right:78px;bottom:8px;font-size:10.5px;gap:8px}.lang-switch{right:10px;bottom:8px;min-width:48px}}
  </style>
</head>
<body>
<div class="page"><a class="home-link" id="homeLink" href="../../index.html" aria-label="返回主页" title="返回主页"><svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/></svg></a><canvas id="chart"></canvas><div class="tip" id="tip"></div><div class="footer-note" id="footerNote"></div><button class="lang-switch" id="langSwitch" type="button" aria-label="Switch language"></button></div>
<script>
const P=__PAYLOAD__;
const rawRows=P.rows.map(r=>({...r,t:new Date(r.date).getTime()}));
const canvas=document.getElementById("chart");
const ctx=canvas.getContext("2d");
const tip=document.getElementById("tip");
const footerNote=document.getElementById("footerNote");
const homeLink=document.getElementById("homeLink");
const langSwitch=document.getElementById("langSwitch");
const isEmbed=document.documentElement.classList.contains("is-embed");
const events=P.events.map(e=>({...e,t:new Date(e.date).getTime()}));
const colors={btc:"#1f77b4",eth:"rgba(165,165,165,.70)",sol:"#0f9f6e",bnb:"#8b5cf6",btcEthRatio:"#334155",candleUpFill:"rgba(255,255,255,.76)",candleDownAlpha:.42,usdt:"#ED7D31",usdc:"#FFC000",stable:"#70AD47",us1y:"rgba(248,113,113,.62)",btcEtfFlow:"rgba(220,38,38,.74)",event:"#2563eb",eventText:"rgba(23,32,42,.65)",eventTextActive:"#17202a",eventBorder:"rgba(147,197,253,.42)",eventFill:"rgba(255,255,255,.30)",eventActiveFill:"rgba(255,255,255,.70)",grid:"#dfe6ed",text:"#17202a",muted:"#526071"};
const params=new URLSearchParams(location.search);
let lang=params.get("lang")==="en"?"en":"zh";
const text={
  zh:{title:"USDT发行量 与 BTC/ETH",refresh:"刷新时间",sources:"数据来源",explain:"数据解释",home:"返回主页",axisPct:"价格与BTC/ETH比值（起点=0%）",axisLog:"价格与BTC/ETH比值（对数变化）",axisSupply:"USDT / USDC / ETF累计净流入（$B）",time:"时间",type:"类型",open:"开",high:"高",low:"低",close:"收",period_day:"日",period_week:"周",period_month:"月",period_quarter:"季",series_btc:"BTC",series_eth:"ETH",series_sol:"SOL",series_bnb:"BNB",series_btcEthRatio:"BTC/ETH比值",series_usdt:"USDT发行量",series_usdc:"USDC发行量",series_stable:"USDT+USDC",series_btcEtfFlow:"BTC ETF累计净流入",series_us1y:"美国1Y利率",dataSources:"CryptoCompare、DefiLlama、FRED、Farside Investors"},
  en:{title:"USDT Supply and BTC/ETH",refresh:"Refresh",sources:"Sources",explain:"Data notes",home:"Home",axisPct:"Price and BTC/ETH ratio (start = 0%)",axisLog:"Price and BTC/ETH ratio (log change)",axisSupply:"USDT / USDC / ETF cumulative net inflow ($B)",time:"Time",type:"Type",open:"O",high:"H",low:"L",close:"C",period_day:"D",period_week:"W",period_month:"M",period_quarter:"Q",series_btc:"BTC",series_eth:"ETH",series_sol:"SOL",series_bnb:"BNB",series_btcEthRatio:"BTC/ETH ratio",series_usdt:"USDT supply",series_usdc:"USDC supply",series_stable:"USDT+USDC",series_btcEtfFlow:"Spot BTC ETF cum. net inflow",series_us1y:"US 1Y yield",dataSources:"CryptoCompare, DefiLlama, FRED, Farside Investors"}
};
function tr(key){return text[lang]?.[key]||text.zh[key]||key}
function colon(){return lang==="en"?":":"："}
function seriesLabel(item){return tr(`series_${item.key}`)}
function eventText(event,key){return lang==="en"&&event[`${key}En`]?event[`${key}En`]:event[key]||""}
function applyLanguageChrome(){
  document.documentElement.lang=lang==="en"?"en":"zh-CN";
  document.title=tr("title");
  if(homeLink){homeLink.setAttribute("aria-label",tr("home"));homeLink.setAttribute("title",tr("home"))}
  if(footerNote)footerNote.innerHTML=`<span>${tr("refresh")}${colon()} UTC+8 ${P.generatedAt}</span><span>${tr("sources")}${colon()} ${tr("dataSources")}</span><a href="usdt-speed-indicator-data-explained.html?lang=${lang}" target="_blank" rel="noopener">${tr("explain")}</a>`;
  if(langSwitch)langSwitch.textContent=lang==="en"?"中":"EN";
}
if(langSwitch)langSwitch.addEventListener("click",()=>{
  lang=lang==="en"?"zh":"en";
  params.set("lang",lang);
  history.replaceState(null,"",`${location.pathname}?${params.toString()}`);
  clearTip();
  applyLanguageChrome();
  draw();
});
const series=[
  {key:"btc",color:colors.btc,scale:"ratio",width:1.15,kind:"candle"},
  {key:"eth",color:colors.eth,scale:"ratio",width:1.05,kind:"candle"},
  {key:"sol",color:colors.sol,scale:"ratio",width:1.05,kind:"candle"},
  {key:"bnb",color:colors.bnb,scale:"ratio",width:1.05,kind:"candle"},
  {key:"btcEthRatio",color:colors.btcEthRatio,scale:"ratio",width:1.05,format:"number"},
  {key:"usdt",color:colors.usdt,scale:"supply",width:1.15},
  {key:"usdc",color:colors.usdc,scale:"supply",width:1.15},
  {key:"stable",color:colors.stable,scale:"supply",width:1.1},
  {key:"btcEtfFlow",color:colors.btcEtfFlow,scale:"supply",width:1.05,valueDivisor:1000},
  {key:"us1y",color:colors.us1y,scale:"rate",width:1.1}
];
let box={},zoom=null,drag=null,legendBoxes=[],eventBoxes=[],periodBoxes=[],scaleBoxes=[],modeBoxes=[],period="day",priceMode="line",valueScale="pct",hoverPeriod=null,hoverScale=null,hoverMode=null,hidden={sol:true,bnb:true,btcEthRatio:true,usdt:true,usdc:true,us1y:true};
const DAY=86400000;
function cloneRow(r){return {...r}}
function finite(v){return v!=null&&Number.isFinite(v)}
function periodName(key){return tr(`period_${key}`)}
function dayLabel(date){return lang==="en"?date:`${date}（${"日一二三四五六"[new Date(`${date}T00:00:00Z`).getUTCDay()]}）`}
function periodTitle(r){
  if(period==="day")return dayLabel(r.date);
  const value=period==="quarter"?quarterKey(r.t):r.date,label=periodName(period);
  return lang==="en"?`${value} (${label})`:`${value}（${label}）`;
}
function weekKey(t){const d=new Date(t),day=d.getUTCDay(),diff=(day+6)%7,s=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate()-diff));return s.toISOString().slice(0,10)}
function monthKey(t){const d=new Date(t);return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}`}
function quarterKey(t){const d=new Date(t);return `${d.getUTCFullYear()}-Q${Math.floor(d.getUTCMonth()/3)+1}`}
function dailyKey(key){return `${key}Daily`}
function addPeriodChanges(list){const ratioKeys=series.filter(item=>item.scale==="ratio").map(item=>item.key);return list.map((r,i,a)=>{const next={...r};ratioKeys.forEach(key=>{next[dailyKey(key)]=i&&a[i-1][key]&&r[key]!=null?(r[key]/a[i-1][key]-1)*100:null});return next})}
function groupOhlc(group,last,key){
  const openKey=`${key}Open`,highKey=`${key}High`,lowKey=`${key}Low`;
  const openRow=group.find(r=>finite(r[openKey]));
  const highs=group.map(r=>r[highKey]).filter(finite),lows=group.map(r=>r[lowKey]).filter(finite);
  last[openKey]=openRow?openRow[openKey]:last[key];
  last[highKey]=highs.length?Math.max(...highs):last[key];
  last[lowKey]=lows.length?Math.min(...lows):last[key];
}
function groupedRows(mode){
  if(mode==="day")return addPeriodChanges(rawRows.map(cloneRow));
  const groups=new Map(),keyFn=mode==="week"?weekKey:mode==="month"?monthKey:quarterKey;
  rawRows.forEach(r=>{const key=keyFn(r.t);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r)});
  return addPeriodChanges(Array.from(groups.values()).map(group=>{
    const last=cloneRow(group[group.length-1]);
    ["btc","eth","sol","bnb"].forEach(key=>groupOhlc(group,last,key));
    return last;
  }).sort((a,b)=>a.t-b.t));
}
let rows=groupedRows(period),ratioBase={},rowsPeriod=null,hoverKey="",pendingPoint=null,hoverFrame=false;
function refreshRows(){if(rowsPeriod===period)return;rows=groupedRows(period);ratioBase=Object.fromEntries(series.filter(item=>item.scale==="ratio").map(item=>[item.key,rows.find(r=>r[item.key]!=null)?.[item.key]]));rowsPeriod=period}
function displayEnd(){return rows[rows.length-1].t+DAY*120}
function usd(v,d=0){return v==null?"-":"$"+Number(v).toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d})}
function b(v){return v==null?"-":Number(v).toFixed(2)+"B"}
function signedB(v){if(v==null)return "-";const n=Number(v);return (n>0?"+":"")+n.toFixed(2)+"B"}
function signedPct(v){if(v==null)return "-";const n=Number(v);return (n>0?"+":"")+n.toFixed(2)+"%"}
function ratePct(v){return v==null?"-":Number(v).toFixed(2)+"%"}
function flowValue(v){if(v==null)return "-";const n=Number(v),sign=n>0?"+":"";return Math.abs(n)>=1000?sign+"$"+(n/1000).toFixed(2)+"B":sign+"$"+n.toFixed(1)+"M"}
function pct(v,d=1){return v==null?"-":Number(v).toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d})+"%"}
function axisPct(v){if(v==null)return "-";const n=Math.round(Number(v));return n===0?"0%":(n>0?"+":"")+n.toLocaleString("en-US")+"%"}
function ratioValue(item,r,suffix=""){const key=item.candle||item.key,base=ratioBase[key],source=suffix?`${key}${suffix}`:key;if(!base||r[source]==null)return null;const ratio=r[source]/base;return valueScale==="log"?Math.log(ratio)*100:(ratio-1)*100}
function plotValue(item,r){const v=item.scale==="ratio"?ratioValue(item,r):r[item.key];return v!=null&&item.valueDivisor?v/item.valueDivisor:v}
function wrapNote(text){return lang==="en"?` (${text})`:`（${text}）`}
function ohlcText(item,r){const key=item.candle;return `${tr("open")} ${usd(r[`${key}Open`])} / ${tr("high")} ${usd(r[`${key}High`])} / ${tr("low")} ${usd(r[`${key}Low`])} / ${tr("close")} ${usd(r[key])}`}
function valueText(item,r){if(item.scale==="ratio"){const daily=r[dailyKey(item.key)];if(r[item.key]==null)return "-";if(item.kind==="candle"&&priceMode==="candle")return `${ohlcText({candle:item.key},r)}${wrapNote(signedPct(daily))}`;if(item.format==="number")return Number(r[item.key]).toFixed(2)+wrapNote(signedPct(daily));return usd(r[item.key])+wrapNote(signedPct(daily))}if(item.key==="btcEtfFlow")return flowValue(r[item.key]);if(item.scale==="rate")return ratePct(r[item.key]);return item.scale==="dev"?signedB(r[item.key]):b(r[item.key])}
function extentValues(item,r){return item.kind==="candle"&&priceMode==="candle"?["Open","High","Low",""].map(s=>ratioValue(item,r,s)):[plotValue(item,r)]}
function extent(keys,list=rows){const a=keys.flatMap(k=>{const item=series.find(s=>s.key===k);return list.flatMap(r=>extentValues(item,r)).filter(finite)});return a.length?[Math.min(...a),Math.max(...a)]:[0,1]}
function activeKeys(scale,allKeys){const keys=series.filter(s=>s.scale===scale&&!hidden[s.key]).map(s=>s.key);return keys.length?keys:allKeys}
function baseRange(){return [rows[0].t,displayEnd()]}
function currentRange(){return zoom||baseRange()}
function visibleRows(){const [t0,t1]=currentRange();const sample=rows.filter(r=>r.t>=t0&&r.t<=t1);return sample.length?sample:rows}
function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}
function xScale(t){return box.x0+(t-box.t0)/(box.t1-box.t0)*(box.x1-box.x0)}
function yRatio(v){return box.y1-(v-box.ratioMin)/(box.ratioMax-box.ratioMin)*(box.y1-box.y0)}
function ySupply(v){return box.y1-(v-box.supplyMin)/(box.supplyMax-box.supplyMin)*(box.y1-box.y0)}
function yRate(v){return box.y1-(v-box.rateMin)/(box.rateMax-box.rateMin)*(box.y1-box.y0)}
function yFor(item,v){if(item.scale==="ratio")return yRatio(v);if(item.scale==="rate")return yRate(v);return ySupply(v)}
function gridLine(y){ctx.strokeStyle=colors.grid;ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(box.x0,y);ctx.lineTo(box.x1,y);ctx.stroke()}
function niceTicks(min,max,n){const span=Math.max(1e-9,max-min),raw=span/Math.max(1,n),pow=Math.pow(10,Math.floor(Math.log10(raw))),base=[1,2,5,10].find(x=>x*pow>=raw)*pow,start=Math.ceil(min/base)*base,out=[];for(let v=start;v<=max+base*.5;v+=base)out.push(v);return out}
function drawLegend(x,y,maxX){
  legendBoxes=[];
  ctx.font="12px Microsoft YaHei,Arial";
  let cur=x,rowY=y;
  series.forEach(item=>{
    const label=seriesLabel(item),labelW=ctx.measureText(label).width,total=labelW+68,off=hidden[item.key];
    if(cur>x&&cur+total>maxX){cur=x;rowY+=20}
    legendBoxes.push({key:item.key,x0:cur-5,y0:rowY-12,x1:cur+total-16,y1:rowY+9});
    ctx.globalAlpha=off?.28:1;
    ctx.strokeStyle=off?"rgba(82,96,113,.45)":item.color;
    ctx.fillStyle=off?"rgba(82,96,113,.58)":colors.text;
    ctx.lineWidth=2;
    ctx.setLineDash(item.dash||[]);
    ctx.beginPath();
    if(item.kind==="candle"){
      ctx.moveTo(cur,rowY+3);ctx.lineTo(cur+9,rowY-3);ctx.lineTo(cur+18,rowY);ctx.lineTo(cur+28,rowY-7);
    }else{
      ctx.moveTo(cur,rowY);ctx.lineTo(cur+28,rowY);
    }
    ctx.stroke();ctx.setLineDash([]);
    ctx.textAlign="left";ctx.fillText(label,cur+36,rowY+4);
    ctx.globalAlpha=1;
    cur+=total;
  });
}
function drawPeriodTabs(x,y){
  periodBoxes=[];
  const labels=[["day",periodName("day")],["week",periodName("week")],["month",periodName("month")],["quarter",periodName("quarter")]];
  ctx.font="12px Microsoft YaHei,Arial";
  labels.forEach(([key,label],i)=>{
    const w=38,h=24,left=x+i*(w+6),active=period===key,hovered=hoverPeriod===key;
    periodBoxes.push({key,x0:left,y0:y,x1:left+w,y1:y+h});
    ctx.strokeStyle=active?"#60a5fa":hovered?"#93c5fd":"rgba(71,85,105,.42)";
    ctx.lineWidth=active||hovered?1.35:.9;
    roundRect(left,y,w,h,7);ctx.stroke();
    ctx.fillStyle=hovered?"#17202a":active?"#17202a":"rgba(71,85,105,.58)";
    ctx.textAlign="center";ctx.fillText(label,left+w/2,y+16);
  });
  ctx.lineWidth=1;
}
function hitPeriod(p){return periodBoxes.find(b=>p.x>=b.x0&&p.x<=b.x1&&p.y>=b.y0&&p.y<=b.y1)}
function drawScaleTabs(x,y){
  scaleBoxes=[];
  const labels=[["pct","%"],["log","ln"]];
  ctx.font="12px Microsoft YaHei,Arial";
  let left=x;
  labels.forEach(([key,label])=>{
    const w=38,h=24,active=valueScale===key,hovered=hoverScale===key;
    scaleBoxes.push({key,x0:left,y0:y,x1:left+w,y1:y+h});
    ctx.strokeStyle=active?"#60a5fa":hovered?"#93c5fd":"rgba(71,85,105,.42)";
    ctx.lineWidth=active||hovered?1.35:.9;
    roundRect(left,y,w,h,7);ctx.stroke();
    ctx.fillStyle=hovered?"#17202a":active?"#17202a":"rgba(71,85,105,.58)";
    ctx.font=key==="pct"?"700 12px Microsoft YaHei,Arial":"700 11px Microsoft YaHei,Arial";
    ctx.textAlign="center";ctx.fillText(label,left+w/2,y+16);
    left+=w+6;
  });
  ctx.font="12px Microsoft YaHei,Arial";
  ctx.lineWidth=1;
}
function hitScale(p){return scaleBoxes.find(b=>p.x>=b.x0&&p.x<=b.x1&&p.y>=b.y0&&p.y<=b.y1)}
function drawModeTabs(x,y){
  modeBoxes=[];
  const labels=[["line"],["candle"]];
  labels.forEach(([key],i)=>{
    const w=34,h=24,left=x+i*(w+6),active=priceMode===key,hovered=hoverMode===key;
    modeBoxes.push({key,x0:left,y0:y,x1:left+w,y1:y+h});
    ctx.strokeStyle=active?"#60a5fa":hovered?"#93c5fd":"rgba(71,85,105,.42)";
    ctx.lineWidth=active||hovered?1.35:.9;
    roundRect(left,y,w,h,7);ctx.stroke();
    ctx.strokeStyle=hovered||active?"#17202a":"rgba(71,85,105,.58)";
    ctx.fillStyle=key==="candle"&&(hovered||active)?"rgba(31,119,180,.50)":"rgba(255,255,255,.88)";
    ctx.lineWidth=1.15;
    if(key==="line"){
      ctx.beginPath();ctx.moveTo(left+8,y+16);ctx.lineTo(left+15,y+10);ctx.lineTo(left+21,y+12);ctx.lineTo(left+27,y+6);ctx.stroke();
    }else{
      ctx.beginPath();ctx.moveTo(left+12,y+6);ctx.lineTo(left+12,y+18);ctx.moveTo(left+23,y+5);ctx.lineTo(left+23,y+19);ctx.stroke();
      ctx.fillRect(left+9,y+10,7,6);ctx.strokeRect(left+9,y+10,7,6);
      ctx.fillStyle=hovered||active?"rgba(31,119,180,.50)":"rgba(255,255,255,.88)";
      ctx.fillRect(left+20,y+9,7,8);ctx.strokeRect(left+20,y+9,7,8);
    }
  });
  ctx.lineWidth=1;
}
function hitMode(p){return modeBoxes.find(b=>p.x>=b.x0&&p.x<=b.x1&&p.y>=b.y0&&p.y<=b.y1)}
function drawAxes(){
  const zeroY=yRatio(0);
  if(zeroY>=box.y0&&zeroY<=box.y1){
    ctx.save();
    ctx.setLineDash([5,5]);
    ctx.strokeStyle="rgba(82,96,113,.36)";
    ctx.lineWidth=.75;
    ctx.beginPath();ctx.moveTo(box.x0,zeroY);ctx.lineTo(box.x1,zeroY);ctx.stroke();
    ctx.restore();
  }
  niceTicks(box.ratioMin,box.ratioMax,6).forEach(v=>{const y=yRatio(v);if(y<box.y0||y>box.y1)return;ctx.fillStyle=colors.btc;ctx.textAlign="right";ctx.fillText(axisPct(v),box.x0-9,y+4)});
  [-50,0,50,100,150,200,250,300].forEach(v=>{if(v<box.supplyMin||v>box.supplyMax)return;const y=ySupply(v);if(y<box.y0||y>box.y1)return;ctx.fillStyle=colors.usdt;ctx.textAlign="left";ctx.fillText("$"+v+"B",box.x1+9,y+4)});
  if(!hidden.us1y)[box.rateMin,(box.rateMin+box.rateMax)/2,box.rateMax].forEach(v=>{const y=yRate(v);if(y<box.y0||y>box.y1)return;ctx.fillStyle=colors.us1y;ctx.textAlign="left";ctx.fillText(ratePct(v),box.x1+68,y+4)});
}
function drawCandles(key){
  if(hidden[key])return;
  const seriesItem=series.find(item=>item.key===key);
  const item={key,candle:key},count=Math.max(visibleRows().length,1),bodyW=Math.max(.8,Math.min(period==="quarter"?16:period==="month"?12:period==="week"?8:5,(box.x1-box.x0)/count*.48));
  const candleLine=seriesItem?.color||colors.btc,candleDown=candleLine.replace(/rgba?\\(([^)]+)\\)/,(_,value)=>`rgba(${value.split(",").slice(0,3).join(",")},${colors.candleDownAlpha})`);
  rows.forEach(r=>{
    const o=ratioValue(item,r,"Open"),h=ratioValue(item,r,"High"),l=ratioValue(item,r,"Low"),c=ratioValue(item,r);
    if([o,h,l,c].some(v=>!finite(v)))return;
    const x=xScale(r.t);
    if(x<box.x0-bodyW||x>box.x1+bodyW)return;
    const yO=yRatio(o),yH=yRatio(h),yL=yRatio(l),yC=yRatio(c),top=Math.min(yO,yC),bottom=Math.max(yO,yC),bodyH=Math.max(1,bottom-top);
    ctx.strokeStyle=candleLine;ctx.fillStyle=c>=o?colors.candleUpFill:candleDown;ctx.lineWidth=.8;
    ctx.beginPath();if(yH<top){ctx.moveTo(x,yH);ctx.lineTo(x,top)}if(yL>top+bodyH){ctx.moveTo(x,top+bodyH);ctx.lineTo(x,yL)}ctx.stroke();
    ctx.fillRect(x-bodyW/2,top,bodyW,bodyH);ctx.strokeRect(x-bodyW/2,top,bodyW,bodyH);
  });
}
function drawPath(item){
  if(hidden[item.key])return;
  if(priceMode==="candle"&&item.kind==="candle")return;
  ctx.beginPath();
  let open=false;
  rows.forEach(r=>{
    const v=plotValue(item,r);
    if(v==null||!Number.isFinite(v)){open=false;return}
    const x=xScale(r.t),y=yFor(item,v);
    if(!open){ctx.moveTo(x,y);open=true}else ctx.lineTo(x,y)
  });
  ctx.strokeStyle=item.color;ctx.lineWidth=item.width;ctx.setLineDash(item.dash||[]);ctx.stroke();ctx.setLineDash([]);
}
function roundRect(x,y,w,h,r){
  const rr=Math.min(r,w/2,h/2);
  ctx.beginPath();
  ctx.moveTo(x+rr,y);ctx.lineTo(x+w-rr,y);ctx.quadraticCurveTo(x+w,y,x+w,y+rr);ctx.lineTo(x+w,y+h-rr);ctx.quadraticCurveTo(x+w,y+h,x+w-rr,y+h);ctx.lineTo(x+rr,y+h);ctx.quadraticCurveTo(x,y+h,x,y+h-rr);ctx.lineTo(x,y+rr);ctx.quadraticCurveTo(x,y,x+rr,y);
}
function drawEvents(activeEventDate=null){
  eventBoxes=[];
  ctx.font="11px Microsoft YaHei,Arial";
  const laneCount=box.x1-box.x0<520?5:3,lanes=Array(laneCount).fill(box.x0-999),visible=events.filter(e=>e.t>=box.t0&&e.t<=box.t1).sort((a,b)=>a.t-b.t);
  visible.forEach(event=>{
    const label=eventText(event,"label"),active=activeEventDate===event.date,x=xScale(event.t),pad=7,w=Math.ceil(ctx.measureText(label).width+pad*2),h=18;
    let lane=lanes.findIndex(right=>right<=x-w/2-4);
    if(lane<0)lane=lanes.indexOf(Math.min(...lanes));
    const y=box.y1-26-lane*22,left=Math.max(box.x0+2,Math.min(box.x1-w-2,x-w/2));
    lanes[lane]=left+w;
    ctx.save();ctx.strokeStyle=active?"rgba(37,99,235,.38)":"rgba(147,197,253,.18)";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,box.y1);ctx.lineTo(x,y+h);ctx.stroke();
    ctx.fillStyle=active?colors.eventActiveFill:colors.eventFill;ctx.strokeStyle=active?colors.event:colors.eventBorder;roundRect(left,y,w,h,9);ctx.fill();ctx.stroke();
    ctx.fillStyle=active?colors.eventTextActive:colors.eventText;ctx.textAlign="center";ctx.fillText(label,left+w/2,y+12.5);ctx.restore();
    eventBoxes.push({event,x0:left,y0:y,x1:left+w,y1:y+h});
  });
}
function draw(active,eventDate=null){
  refreshRows();
  const w=canvas.clientWidth,h=canvas.clientHeight,outer=Math.round(Math.min(w,h)*.035),compactHeader=w<760;
  const axisLeft=76,axisRight=86,titleY=outer+14,legendY=outer+(compactHeader?(isEmbed?56:116):46),xLabelGap=isEmbed?32:38;
  const x0=outer+axisLeft,x1=w-outer-axisRight,y0=outer+(compactHeader?(isEmbed?136:230):(isEmbed?76:82)),y1=h-outer-xLabelGap;
  const [t0,t1]=currentRange(),sample=visibleRows();
  const [ratioMin0,ratioMax0]=extent(activeKeys("ratio",["btc","eth"]),sample),ratioPad=Math.max((ratioMax0-ratioMin0)*.12,8);
  const [supplyMin0,supplyMax0]=extent(activeKeys("supply",["usdt","usdc","stable","btcEtfFlow"]),sample);
  const [rateMin0,rateMax0]=extent(activeKeys("rate",["us1y"]),sample),ratePad=Math.max((rateMax0-rateMin0)*.18,.15);
  let ratioMin=Math.min(ratioMin0-ratioPad,0),ratioMax=Math.max(ratioMax0+ratioPad,10);
  const zeroFloorFraction=.16,ratioFloorMin=-(zeroFloorFraction*ratioMax)/(1-zeroFloorFraction);
  ratioMin=Math.min(ratioMin,ratioFloorMin);
  const zeroFraction=(0-ratioMin)/(ratioMax-ratioMin);
  let supplyMax=Math.max(supplyMax0*1.1,1),supplyMin=-(zeroFraction*supplyMax)/(1-zeroFraction);
  if(supplyMin0<0&&supplyMin0<supplyMin){
    supplyMin=supplyMin0*1.1;
    supplyMax=Math.max(supplyMax,(-supplyMin)*(1-zeroFraction)/zeroFraction);
  }
  box={x0,x1,y0,y1,t0,t1,ratioMin,ratioMax,supplyMin,supplyMax,rateMin:rateMin0-ratePad,rateMax:rateMax0+ratePad};
  ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);
  ctx.fillStyle=colors.text;ctx.font="700 21px Microsoft YaHei,Arial";ctx.textAlign="center";ctx.fillText(tr("title"),w/2,titleY);
  const periodWidth=170,scaleWidth=82,modeWidth=74,controlY=compactHeader?titleY+18:titleY-18;
  let periodX=x1-periodWidth,scaleX=periodX-scaleWidth-10,modeX=scaleX-modeWidth-10,periodY=controlY;
  if(compactHeader){modeX=x0;scaleX=x1-scaleWidth;periodX=x0;periodY=controlY+30}
  drawLegend(x0,legendY,x1);
  if(isEmbed){modeBoxes=[];scaleBoxes=[];periodBoxes=[]}else{drawModeTabs(modeX,controlY);drawScaleTabs(scaleX,controlY);drawPeriodTabs(periodX,periodY)}
  const startYear=new Date(box.t0).getUTCFullYear(),endYear=new Date(box.t1).getUTCFullYear();
  for(let year=startYear;year<=endYear;year++){const x=xScale(new Date(`${year}-01-01T00:00:00Z`).getTime());if(x<x0||x>x1)continue;ctx.fillStyle=colors.muted;ctx.textAlign="center";ctx.fillText(year,x,y1+(isEmbed?23:28))}
  drawAxes();
  ctx.strokeStyle="#cfd8e2";ctx.strokeRect(x0,y0,x1-x0,y1-y0);
  ctx.save();ctx.beginPath();ctx.rect(x0,y0,x1-x0,y1-y0);ctx.clip();series.forEach(drawPath);if(priceMode==="candle"){["btc","eth","sol","bnb"].forEach(drawCandles)}ctx.restore();
  if(isEmbed){eventBoxes=[]}else{drawEvents(eventDate)}
  ctx.fillStyle=colors.btc;ctx.textAlign="center";ctx.save();ctx.translate(x0-52,(y0+y1)/2);ctx.rotate(-Math.PI/2);ctx.fillText(valueScale==="log"?tr("axisLog"):tr("axisPct"),0,0);ctx.restore();
  ctx.save();ctx.translate(x1+52,(y0+y1)/2);ctx.rotate(Math.PI/2);ctx.fillStyle=colors.usdt;ctx.fillText(tr("axisSupply"),0,0);ctx.restore();
  if(active!=null){const r=rows[active],x=xScale(r.t);ctx.setLineDash([5,5]);ctx.strokeStyle="rgba(82,96,113,.62)";ctx.beginPath();ctx.moveTo(x,y0);ctx.lineTo(x,y1);ctx.stroke();ctx.setLineDash([]);series.forEach(item=>{if(priceMode==="candle"&&item.kind==="candle")return;const v=plotValue(item,r);if(hidden[item.key]||v==null)return;ctx.fillStyle="#fff";ctx.strokeStyle=item.color;ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,yFor(item,v),3.3,0,Math.PI*2);ctx.fill();ctx.stroke()})}
}
function clampX(x){return Math.max(box.x0,Math.min(box.x1,x))}
function pointer(e){const rect=canvas.getBoundingClientRect();return{x:e.clientX-rect.left,y:e.clientY-rect.top,rect}}
function inPlot(p){return p.x>=box.x0&&p.x<=box.x1&&p.y>=box.y0&&p.y<=box.y1}
function timeAtX(x){return box.t0+(clampX(x)-box.x0)/(box.x1-box.x0)*(box.t1-box.t0)}
function hitLegend(p){return legendBoxes.find(b=>p.x>=b.x0&&p.x<=b.x1&&p.y>=b.y0&&p.y<=b.y1)}
function hitEvent(p){return eventBoxes.find(b=>p.x>=b.x0&&p.x<=b.x1&&p.y>=b.y0&&p.y<=b.y1)}
function nearest(mx){const t=timeAtX(mx);let l=0,r=rows.length-1;while(l<r){const m=(l+r)>>1;if(rows[m].t<t)l=m+1;else r=m}if(l>0&&Math.abs(rows[l-1].t-t)<Math.abs(rows[l].t-t))l--;return l}
function drawSelection(){if(!drag)return;const x0=clampX(drag.x0),x1=clampX(drag.x1),left=Math.min(x0,x1),width=Math.abs(x1-x0);if(width<3)return;ctx.fillStyle="rgba(111,74,168,.10)";ctx.strokeStyle="rgba(111,74,168,.55)";ctx.lineWidth=1;ctx.fillRect(left,box.y0,width,box.y1-box.y0);ctx.strokeRect(left,box.y0,width,box.y1-box.y0)}
function clearTip(){hoverKey="";pendingPoint=null;tip.style.display="none"}
function positionTip(p,shiftY=70){
  const margin=8,gap=14,w=tip.offsetWidth||280,h=tip.offsetHeight||150,rightLimit=Math.min(p.rect.width-margin,box.x1?box.x1-8:p.rect.width-margin);
  let left=p.x+gap;
  if(left+w>rightLimit)left=p.x-w-gap;
  left=Math.max(margin,Math.min(left,Math.max(margin,rightLimit-w)));
  let top=p.y-shiftY;
  top=Math.max(margin,Math.min(top,Math.max(margin,p.rect.height-margin-h)));
  tip.style.left=left+"px";tip.style.top=top+"px";
}
function showTipNow(p){
  if(!inPlot(p)){if(hoverKey!=="out"){tip.style.display="none";draw();hoverKey="out"}return}
  const eventHit=hitEvent(p);
  if(eventHit){
    const e=eventHit.event,key=`event:${e.date}`;
    if(hoverKey!==key){
      draw(null,e.date);const x=xScale(e.t);
      ctx.setLineDash([4,5]);ctx.strokeStyle="rgba(37,99,235,.42)";ctx.beginPath();ctx.moveTo(x,box.y0);ctx.lineTo(x,box.y1);ctx.stroke();ctx.setLineDash([]);
      tip.className="tip";
      tip.innerHTML=`<b>${eventText(e,"label")}</b><br>${tr("time")}${colon()} ${e.dateLabel} ${eventText(e,"timezone")}<br>${tr("type")}${colon()} ${eventText(e,"type")}<br>${eventText(e,"description")}`;
      hoverKey=key;
    }
    tip.style.display="block";positionTip(p,92);
    return;
  }
  const i=nearest(p.x),r=rows[i],key=`point:${period}:${i}`;
  if(hoverKey!==key){
    draw(i);
    const lines=series.filter(item=>!hidden[item.key]).map(item=>`${seriesLabel(item)}${colon()} ${valueText(item,r)}`);
    tip.className="tip";
    tip.innerHTML=`<b>${periodTitle(r)}</b><br>${lines.join("<br>")}`;
    hoverKey=key;
  }
  tip.style.display="block";positionTip(p,70);
}
function showTip(p){pendingPoint=p;if(hoverFrame)return;hoverFrame=true;requestAnimationFrame(()=>{hoverFrame=false;const next=pendingPoint;pendingPoint=null;if(next)showTipNow(next)})}
canvas.addEventListener("click",e=>{const p=pointer(e),mode=hitMode(p),scale=hitScale(p),tab=hitPeriod(p);if(mode){priceMode=mode.key;hoverMode=mode.key;clearTip();draw();return}if(scale){valueScale=scale.key;hoverScale=scale.key;clearTip();draw();return}if(tab){period=tab.key;hoverPeriod=tab.key;zoom=null;clearTip();draw();return}const hit=hitLegend(p);if(!hit)return;hidden[hit.key]=!hidden[hit.key];clearTip();draw()});
canvas.addEventListener("mousedown",e=>{const p=pointer(e);if(hitLegend(p)||hitMode(p)||hitScale(p)||hitPeriod(p)||!inPlot(p))return;drag={x0:p.x,x1:p.x};clearTip()});
canvas.addEventListener("mousemove",e=>{const p=pointer(e);if(drag){drag.x1=p.x;clearTip();draw();drawSelection();return}const mode=hitMode(p);if(mode){if(hoverMode!==mode.key){hoverMode=mode.key;clearTip();draw()}canvas.style.cursor="pointer";clearTip();return}const scale=hitScale(p);if(scale){if(hoverScale!==scale.key){hoverScale=scale.key;clearTip();draw()}canvas.style.cursor="pointer";clearTip();return}const tab=hitPeriod(p);if(tab){if(hoverPeriod!==tab.key){hoverPeriod=tab.key;clearTip();draw()}canvas.style.cursor="pointer";clearTip();return}if(hoverMode!==null||hoverScale!==null||hoverPeriod!==null){hoverMode=null;hoverScale=null;hoverPeriod=null;clearTip();draw()}showTip(p)});
window.addEventListener("mouseup",()=>{if(!drag)return;const x0=clampX(drag.x0),x1=clampX(drag.x1);if(Math.abs(x1-x0)>12){const a=timeAtX(x0),b=timeAtX(x1);zoom=[Math.min(a,b),Math.max(a,b)]}drag=null;clearTip();draw()});
canvas.addEventListener("mouseleave",()=>{if(drag)return;hoverMode=null;hoverScale=null;hoverPeriod=null;clearTip();canvas.style.cursor="default";draw()});
canvas.addEventListener("dblclick",()=>{zoom=null;drag=null;clearTip();draw()});
window.addEventListener("resize",resize);
applyLanguageChrome();
refreshRows();
resize();
</script>
</body>
</html>
"""
    html_text = add_canvas_mobile_support(html_text)
    write_data_explanation(output_html)
    output_html.write_text(html_text.replace("__PAYLOAD__", payload), encoding="utf-8")
