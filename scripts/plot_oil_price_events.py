from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from global_30y_bond_daily.providers.tradingview_provider import fetch as fetch_tradingview
from mobile_chart_support import add_canvas_mobile_support


ROOT = Path(__file__).resolve().parents[1]
START_DATE = date(2023, 1, 1)
END_DATE = date.today()
DISPLAY_START = pd.Timestamp("2026-01-01")
BAR_COUNT = 7000
INTRADAY_BAR_COUNT = 12000
INTRADAY_INTERVAL = "30"
INTRADAY_FREQ = "30min"
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
        "dateLabel": "2026-03-23 11:05 UTC",
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
        "dateLabel": "2026-04-21 20:10 UTC",
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
    {
        "date": "2026-05-26",
        "dateLabel": "2026-05-26 00:00 UTC",
        "label": "美军再打击",
        "type": "停火受挫",
        "score": "-0.70",
        "description": "美军在伊朗南部实施打击，削弱市场对周末和平框架和霍尔木兹重开的预期。伊朗称美国违反停火，Rubio称谈判可能还需要几天。",
    },
    {
        "date": "2026-05-27",
        "dateLabel": "2026-05-27 20:00 UTC",
        "label": "共管遭否认",
        "type": "谈判受阻",
        "score": "-0.55",
        "description": "川普否认伊朗和阿曼共同管理霍尔木兹的框架设想，并称协议仍未完成；美国随后制裁伊朗试图控制海峡航运的新机构，市场重新计入通航谈判受阻风险。",
    },
    {
        "date": "2026-05-28",
        "dateLabel": "2026-05-28 01:20 UTC",
        "label": "美伊互袭",
        "type": "复战升级",
        "score": "-0.85",
        "description": "伊朗革命卫队称在美军袭击阿巴斯港附近目标后报复打击美军基地；双方再度交火，霍尔木兹通航和停火前景继续承压。",
    },
    {
        "date": "2026-06-03",
        "dateLabel": "2026-06-03 06:10 UTC",
        "label": "科威特机场",
        "type": "海湾外溢",
        "score": "-0.75",
        "description": "伊朗无人机重创科威特国际机场客运楼，造成1人死亡、数十人受伤，机场一度短暂停运。科威特称航站楼刚在周一重新开放，CENTCOM称这是伊朗无人机的蓄意攻击。",
    },
    {
        "date": "2026-06-05",
        "dateLabel": "2026-06-05 23:03 UTC",
        "label": "海湾拦截",
        "type": "停火受压",
        "score": "-0.70",
        "description": "美军称拦截伊朗射向霍尔木兹和海湾盟友的导弹与无人机，并打击伊朗沿岸雷达站。伊朗称目标是科威特Ali Al Salem空军基地和巴林的美国第五舰队。",
    },
    {
        "date": "2026-06-07",
        "dateLabel": "2026-06-07 10:24 UTC",
        "label": "伊以再交火",
        "type": "停火破裂风险",
        "score": "-0.85",
        "description": "伊朗向以色列发射导弹，这是4月脆弱停火以来首次此类轰炸；伊朗称此前以色列在贝鲁特南郊发动打击，以色列则警告会强力回应。",
    },
    {
        "date": "2026-06-09",
        "dateLabel": "2026-06-09 04:43 UTC",
        "label": "直升机事件",
        "type": "美伊摩擦",
        "score": "-0.80",
        "description": "川普指责伊朗在霍尔木兹附近击落一架美国陆军Apache直升机，并表示美国必须回应；两名机组人员获救且未受伤，事件进一步压迫停火谈判。",
    },
]
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


def fetch_market(
    market: dict[str, str],
    interval: str = "1D",
    bar_count: int = BAR_COUNT,
    retries: int = 6,
) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            frame = fetch_tradingview(
                {"symbol": market["symbol"]},
                {"history": {"bar_count": bar_count, "interval": interval}},
            )
            frame = frame.copy()
            price_columns = ["open", "high", "low", "close"]
            for column in price_columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            rename_columns = {column: f"{market['key']}_{column}" for column in price_columns}

            if interval == "1D":
                frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
                frame = frame.dropna(subset=["date"]).sort_values("date")
                frame = frame[(frame["date"].dt.date >= START_DATE) & (frame["date"].dt.date <= END_DATE)]
                frame = frame.drop_duplicates("date", keep="last")
                return frame[["date", *price_columns]].rename(columns=rename_columns)

            timestamp_source = frame["timestamp"] if "timestamp" in frame.columns else frame["date"]
            frame["time"] = pd.to_datetime(timestamp_source, errors="coerce", utc=True)
            frame = frame.dropna(subset=["time"]).sort_values("time")
            frame["time"] = frame["time"].dt.floor(INTRADAY_FREQ)
            intraday_start = DISPLAY_START.tz_localize("UTC")
            intraday_end = pd.Timestamp.now(tz="UTC").ceil(INTRADAY_FREQ)
            frame = frame[(frame["time"] >= intraday_start) & (frame["time"] <= intraday_end)]
            frame = frame.drop_duplicates("time", keep="last")
            return frame[["time", *price_columns]].rename(columns=rename_columns)
        except Exception as exc:
            last_error = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"TradingView request failed: {market['symbol']}") from last_error


def add_pct(data: pd.DataFrame, time_column: str, column: str, suffix: str) -> None:
    if column not in data.columns:
        data[f"{column}_{suffix}"] = None
        return
    valid = data.dropna(subset=[column]).set_index(time_column)[column]
    changes = (valid.pct_change() * 100).to_dict()
    data[f"{column}_{suffix}"] = data[time_column].map(changes)


def intraday_cache_path(cache_path: Path | None) -> Path | None:
    if cache_path is None:
        return ROOT / "data" / "other-markets" / "oil-price-events-30m.csv"
    return cache_path.with_name(f"{cache_path.stem}-30m{cache_path.suffix}")


def ensure_cached_columns(cached: pd.DataFrame, time_column: str) -> pd.DataFrame:
    for market in MARKETS:
        close_column = f"{market['key']}_close"
        for price in ["open", "high", "low"]:
            column = f"{market['key']}_{price}"
            if column not in cached.columns and close_column in cached.columns:
                cached[column] = cached[close_column]
        add_pct(cached, time_column, close_column, "daily_pct" if time_column == "date" else "bar_pct")
    return cached


def build_daily_frame(cache_path: Path | None = None) -> pd.DataFrame:
    try:
        frames = [fetch_market(market, interval="1D", bar_count=BAR_COUNT) for market in MARKETS]
    except Exception:
        if cache_path and cache_path.exists():
            cached = pd.read_csv(cache_path, parse_dates=["date"])
            cached = cached[cached["date"].dt.date >= START_DATE]
            return ensure_cached_columns(cached, "date")
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
        add_pct(data, "date", f"{market['key']}_close", "daily_pct")

    return data.sort_values("date").reset_index(drop=True)


def build_intraday_frame(cache_path: Path | None = None) -> pd.DataFrame:
    try:
        frames = [
            fetch_market(market, interval=INTRADAY_INTERVAL, bar_count=INTRADAY_BAR_COUNT)
            for market in MARKETS
        ]
    except Exception:
        if cache_path and cache_path.exists():
            cached = pd.read_csv(cache_path, parse_dates=["time"])
            cached["time"] = pd.to_datetime(cached["time"], errors="coerce", utc=True)
            cached = cached.dropna(subset=["time"])
            return ensure_cached_columns(cached, "time")
        raise

    first_times = [frame["time"].min() for frame in frames if not frame.empty]
    if not first_times:
        raise RuntimeError("Oil 30m price data is empty")

    intraday_start = DISPLAY_START.tz_localize("UTC")
    intraday_end = max(max(frame["time"].max() for frame in frames if not frame.empty), pd.Timestamp.now(tz="UTC")).ceil(
        INTRADAY_FREQ
    )
    calendar = pd.DataFrame({"time": pd.date_range(intraday_start, intraday_end, freq=INTRADAY_FREQ)})
    data = calendar
    for frame in frames:
        data = data.merge(frame, on="time", how="left")

    for market in MARKETS:
        add_pct(data, "time", f"{market['key']}_close", "bar_pct")

    return data.sort_values("time").reset_index(drop=True)


def build_price_frame(cache_path: Path | None = None) -> dict[str, pd.DataFrame]:
    return {
        "day": build_daily_frame(cache_path),
        "m30": build_intraday_frame(intraday_cache_path(cache_path)),
    }


def latest_valid(data: pd.DataFrame, column: str) -> pd.Series:
    valid = data.dropna(subset=[column])
    if valid.empty:
        raise RuntimeError(f"{column} has no data")
    return valid.iloc[-1]


def chart_meta(data: dict[str, pd.DataFrame] | pd.DataFrame) -> dict:
    daily = data["day"] if isinstance(data, dict) else data
    metrics = []
    latest_dates: list[pd.Timestamp] = []
    for market in MARKETS:
        column = f"{market['key']}_close"
        latest = latest_valid(daily, column)
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
        "dataNote": "默认显示WTI；Brent可点选开启。日线按自然日铺开，30分钟按UTC时间铺开，周末、盘外和无交易时段保留空值。",
    }


def series_value(value: object, digits: int = 4) -> float | None:
    if pd.isna(value):
        return None
    return round(float(value), digits)


def market_record(row: object, market: dict[str, str], pct_suffix: str) -> dict[str, float | None]:
    key = market["key"]
    return {
        "o": series_value(getattr(row, f"{key}_open", None), 4),
        "h": series_value(getattr(row, f"{key}_high", None), 4),
        "l": series_value(getattr(row, f"{key}_low", None), 4),
        "c": series_value(getattr(row, f"{key}_close", None), 4),
        "pct": series_value(getattr(row, f"{key}_close_{pct_suffix}", None), 4),
    }


def iso_utc(value: object) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def write_interactive_html(data: dict[str, pd.DataFrame] | pd.DataFrame, output_html: Path) -> None:
    daily = data["day"] if isinstance(data, dict) else data
    intraday = data["m30"] if isinstance(data, dict) else pd.DataFrame()
    meta = chart_meta(data)
    generated_at = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    day_records = []
    for row in daily.itertuples(index=False):
        day_records.append(
            {
                "date": row.date.strftime("%Y-%m-%d"),
                **{market["key"]: market_record(row, market, "daily_pct") for market in MARKETS},
            }
        )
    m30_records = []
    if not intraday.empty:
        for row in intraday.itertuples(index=False):
            m30_records.append(
                {
                    "time": iso_utc(row.time),
                    **{market["key"]: market_record(row, market, "bar_pct") for market in MARKETS},
                }
            )

    payload = json.dumps(
        {
            "dayRows": day_records,
            "m30Rows": m30_records,
            "meta": meta,
            "events": OIL_EVENTS,
            "generatedAt": generated_at,
            "dataSources": "TradingView、NYMEX/CME、ICE Futures Europe",
            "markets": [{"key": market["key"], "label": market["label"]} for market in MARKETS],
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
  <title>WTI/Brent 原油价格与事件</title>
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
const canvas=document.getElementById("chart");
const ctx=canvas.getContext("2d");
const tip=document.getElementById("tip");
const isEmbed=document.documentElement.classList.contains("is-embed");
const DAY=86400000;
const SLOT30=1800000;
const markets=P.markets||[{key:"wti",label:"CME WTI"},{key:"brent",label:"ICE Brent"}];
const periodDefs={
  day:{label:"日",rows:(P.dayRows||[]).map(r=>({...r,t:new Date(`${r.date}T00:00:00Z`).getTime()}))},
  m30:{label:"30m",rows:(P.m30Rows||[]).map(r=>({...r,t:new Date(r.time).getTime()}))}
};
const events=(P.events||[]).map(e=>{const exact=eventExactTime(e),dayT=new Date(`${e.date}T00:00:00Z`).getTime();return{...e,exactT:exact,dayT,m30T:Math.floor(exact/SLOT30)*SLOT30}});
const colors={text:"#111827",legend:"#374151",muted:"#4b5563",frame:"rgba(17,17,17,.48)",weekend:"rgba(148,163,184,.045)",control:"rgba(71,85,105,.42)",controlOn:"#1f77b4"};
const marketStyle={
  wti:{stroke:"rgba(17,17,17,.59)",upFill:"rgba(255,255,255,.92)",downFill:"rgba(17,17,17,.55)"},
  brent:{stroke:"rgba(31,119,180,.52)",upFill:"rgba(255,255,255,.90)",downFill:"rgba(31,119,180,.42)"}
};
const startOptions=[["2026-01-01","2026"],["2025-01-01","2025"],["2024-01-01","2024"],["2023-01-01","2023"]];
let period="day",rows=periodDefs.day.rows,box={},zoom=null,drag=null,eventBoxes=[],startBoxes=[],marketBoxes=[],periodBoxes=[],viewStart="2026-01-01",hoverStart=null,hidden={brent:true};
function eventExactTime(e){const m=String(e.dateLabel||"").match(/^(\\d{4})-(\\d{2})-(\\d{2})\\s+(\\d{2}):(\\d{2})/);if(m)return Date.UTC(+m[1],+m[2]-1,+m[3],+m[4],+m[5]);return new Date(`${e.date}T00:00:00Z`).getTime()}
function refreshRows(){rows=periodDefs[period].rows||[]}
function weekChar(t){return "日一二三四五六"[new Date(t).getUTCDay()]}
function dateText(t){const d=new Date(t);return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}-${String(d.getUTCDate()).padStart(2,"0")}`}
function timeText(t){const d=new Date(t);return `${dateText(t)}（${weekChar(t)}） ${String(d.getUTCHours()).padStart(2,"0")}:${String(d.getUTCMinutes()).padStart(2,"0")} UTC`}
function dayLabel(date){const t=new Date(`${date}T00:00:00Z`).getTime();return `${date}（${weekChar(t)}）`}
function eventTime(e){return period==="m30"?e.m30T:e.dayT}
function eventKey(e){return `${period}-${e.dateLabel||e.date}`}
function q(r,key){return r&&r[key]?r[key]:{}}
function hasOhlc(r,key){const v=q(r,key);return [v.o,v.h,v.l,v.c].every(n=>n!=null&&Number.isFinite(n))}
function visibleMarkets(fallback=true){const active=markets.filter(m=>!hidden[m.key]);return active.length?active:(fallback?[markets[0]]:[])}
function firstMarketKey(){return visibleMarkets()[0].key}
function displayEnd(){return (rows.length?rows[rows.length-1].t:Date.now())+DAY*5}
function selectedStart(){return new Date(`${viewStart}T00:00:00Z`).getTime()}
function defaultRange(){const start=rows.length?rows[0].t:Date.now();return [Math.max(start,selectedStart()),displayEnd()]}
function usd(v,d=2){return v==null?"-":"$"+Number(v).toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d})}
function visibleBaseOpen(){const [t0,t1]=currentRange();for(const r of rows){if(r.t<t0||r.t>t1)continue;for(const m of visibleMarkets()){const v=q(r,m.key);if(v.o!=null&&Number.isFinite(v.o))return v.o}}return null}
function basePct(v){return box.baseOpen&&v!=null?(v/box.baseOpen*100).toFixed(0)+"%":"-"}
function signedPct(v){if(v==null)return "-";const n=Number(v);return (n>0?"+":"")+n.toFixed(2)+"%"}
function valueText(r,key){const v=q(r,key);return hasOhlc(r,key)?`开 ${usd(v.o)}　高 ${usd(v.h)}　低 ${usd(v.l)}　收 ${usd(v.c)}　${signedPct(v.pct)}`:"-"}
function priceExtent(list=rows){const a=[];const active=visibleMarkets();list.forEach(r=>active.forEach(m=>{const v=q(r,m.key);if(v.h!=null&&Number.isFinite(v.h))a.push(v.h);if(v.l!=null&&Number.isFinite(v.l))a.push(v.l)}));return a.length?[Math.min(...a),Math.max(...a)]:[0,1]}
function eventColor(score,alpha=1){const s=Math.max(-1,Math.min(1,Number(score)||0)),hue=60+s*60,light=66-Math.abs(s)*34;return `hsla(${hue},70%,${light}%,${alpha})`}
function currentRange(){return zoom||defaultRange()}
function visibleRows(){const [t0,t1]=currentRange();const sample=rows.filter(r=>r.t>=t0&&r.t<=t1);return sample.length?sample:rows}
function resize(){const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}
function xScale(t){return box.x0+(t-box.t0)/(box.t1-box.t0)*(box.x1-box.x0)}
function yPrice(v){return box.y1-(v-box.priceMin)/(box.priceMax-box.priceMin)*(box.y1-box.y0)}
function roundRect(x,y,w,h,r){const rr=Math.min(r,w/2,h/2);ctx.beginPath();ctx.moveTo(x+rr,y);ctx.lineTo(x+w-rr,y);ctx.quadraticCurveTo(x+w,y,x+w,y+rr);ctx.lineTo(x+w,y+h-rr);ctx.quadraticCurveTo(x+w,y+h,x+w-rr,y+h);ctx.lineTo(x+rr,y+h);ctx.quadraticCurveTo(x,y+h,x,y+h-rr);ctx.lineTo(x,y+rr);ctx.quadraticCurveTo(x,y,x+rr,y)}
function niceTicks(min,max,count){const span=Math.max(1e-9,max-min),raw=span/Math.max(1,count),pow=Math.pow(10,Math.floor(Math.log10(raw))),base=[1,2,5,10].find(v=>v*pow>=raw)*pow,start=Math.ceil(min/base)*base,out=[];for(let v=start;v<=max+base*.45;v+=base)out.push(v);return out}
function drawButton(x,y,w,label,active,hovered){ctx.strokeStyle=active?colors.controlOn:hovered?"#7bb8f8":colors.control;ctx.lineWidth=active||hovered?1.35:.9;roundRect(x,y,w,20,5);ctx.stroke();ctx.fillStyle=hovered||active?colors.text:"rgba(71,85,105,.68)";ctx.textAlign="center";ctx.fillText(label,x+w/2,y+14);ctx.lineWidth=1}
function drawMarketTabs(x,y){marketBoxes=[];ctx.font="12px Microsoft YaHei,Arial";ctx.fillStyle="rgba(71,85,105,.68)";ctx.textAlign="left";ctx.fillText("品种",x,y+14);let cur=x+36;markets.forEach(m=>{const w=m.key==="brent"?60:50,active=!hidden[m.key];marketBoxes.push({key:m.key,x0:cur,y0:y,x1:cur+w,y1:y+20});drawButton(cur,y,w,m.key==="wti"?"WTI":"Brent",active,false);cur+=w+6});return cur}
function drawPeriodTabs(x,y){periodBoxes=[];ctx.font="12px Microsoft YaHei,Arial";ctx.fillStyle="rgba(71,85,105,.68)";ctx.textAlign="left";ctx.fillText("周期",x,y+14);let cur=x+36;[["day","日"],["m30","30m"]].forEach(([key,label])=>{const w=key==="day"?36:48,active=period===key;periodBoxes.push({key,x0:cur,y0:y,x1:cur+w,y1:y+20});drawButton(cur,y,w,label,active,false);cur+=w+6});return cur}
function drawStartTabs(x,y){startBoxes=[];ctx.font="12px Microsoft YaHei,Arial";ctx.fillStyle="rgba(71,85,105,.68)";ctx.textAlign="right";ctx.fillText("起点",x-8,y+14);startOptions.forEach(([key,label],i)=>{const w=42,h=20,left=x+i*(w+6),active=viewStart===key,hovered=hoverStart===key;startBoxes.push({key,x0:left,y0:y,x1:left+w,y1:y+h});drawButton(left,y,w,label,active,hovered)})}
function hitBox(p,boxes){return boxes.find(b=>p.x>=b.x0&&p.x<=b.x1&&p.y>=b.y0&&p.y<=b.y1)}
function drawAxes(){niceTicks(box.priceMin,box.priceMax,7).forEach(v=>{const y=yPrice(v);ctx.fillStyle=colors.text;ctx.textAlign="right";ctx.fillText(usd(v,0),box.x0-9,y+4);ctx.textAlign="left";ctx.fillText(basePct(v),box.x1+9,y+4)})}
function monthIndex(t){const d=new Date(t);return d.getUTCFullYear()*12+d.getUTCMonth()}
function drawDateTicks(){if(period==="m30"){const spanDays=Math.max(1,(box.t1-box.t0)/DAY),step=spanDays>150?21:spanDays>80?14:spanDays>35?7:2;const start=new Date(box.t0);start.setUTCHours(0,0,0,0);for(let t=start.getTime();t<=box.t1;t+=DAY*step){const x=xScale(t);if(x>=box.x0&&x<=box.x1){ctx.fillStyle=colors.muted;ctx.textAlign="center";ctx.fillText(dateText(t).slice(5),x,box.y1+(isEmbed?23:28))}}return}const start=new Date(box.t0);start.setUTCDate(1);start.setUTCHours(0,0,0,0);const spanMonths=Math.max(1,monthIndex(box.t1)-monthIndex(box.t0)+1),step=spanMonths>48?6:spanMonths>18?3:1;for(let t=start.getTime();t<=box.t1;){const d=new Date(t),x=xScale(t),idx=monthIndex(t);if(idx%step===0&&x>=box.x0&&x<=box.x1){ctx.fillStyle=colors.muted;ctx.textAlign="center";ctx.fillText(`${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}`,x,box.y1+(isEmbed?23:28))}t=Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1)}}
function drawWeekends(){const start=new Date(box.t0);start.setUTCHours(0,0,0,0);for(let t=start.getTime();t<=box.t1;t+=DAY){const d=new Date(t).getUTCDay();if(d!==6&&d!==0)continue;const x0=xScale(t),x1=xScale(t+DAY);ctx.fillStyle=colors.weekend;ctx.fillRect(x0,box.y0,Math.max(1,x1-x0),box.y1-box.y0)}}
function candleWidth(){const visible=rows.filter(r=>r.t>=box.t0&&r.t<=box.t1).length||1,byCount=(box.x1-box.x0)/visible*.62,byDay=(box.x1-box.x0)/Math.max(1,(box.t1-box.t0)/DAY)*.72,maxW=period==="m30"?5:10,minW=period==="m30"?.8:2;return Math.max(minW,Math.min(maxW,Math.min(byCount,byDay)))}
function drawCandles(){const active=visibleMarkets(),bodyW=candleWidth();active.forEach((m,mi)=>{const style=marketStyle[m.key]||marketStyle.wti,offset=(mi-(active.length-1)/2)*bodyW*.62;rows.forEach(r=>{if(!hasOhlc(r,m.key)||r.t<box.t0||r.t>box.t1)return;const v=q(r,m.key),x=xScale(r.t)+offset,up=v.c>=v.o,yH=yPrice(v.h),yL=yPrice(v.l),yO=yPrice(v.o),yC=yPrice(v.c),top=Math.min(yO,yC),height=Math.max(1.1,Math.abs(yC-yO));ctx.strokeStyle=style.stroke;ctx.lineWidth=period==="m30"?.45:.6;ctx.beginPath();ctx.moveTo(x,yH);ctx.lineTo(x,yL);ctx.stroke();ctx.fillStyle=up?style.upFill:style.downFill;ctx.strokeStyle=style.stroke;ctx.fillRect(x-bodyW/2,top,bodyW,height);ctx.strokeRect(x-bodyW/2,top,bodyW,height)})})}
function drawEvents(activeKey=null){eventBoxes=[];const laneCount=4,visible=events.filter(e=>eventTime(e)>=box.t0&&eventTime(e)<=box.t1).sort((a,b)=>eventTime(a)-eventTime(b));visible.forEach((event,index)=>{const key=eventKey(event),active=activeKey===key,x=xScale(eventTime(event)),lane=index%laneCount,y=box.y1-18-lane*17,r=active?7.2:6.1;ctx.save();ctx.strokeStyle=eventColor(event.score,active?.42:.24);ctx.lineWidth=active?1.1:.8;ctx.beginPath();ctx.moveTo(x,box.y1);ctx.lineTo(x,y-r-2);ctx.stroke();ctx.fillStyle=eventColor(event.score,active?.96:.82);ctx.strokeStyle="rgba(255,255,255,.88)";ctx.lineWidth=1.4;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.restore();eventBoxes.push({event,key,x0:x-12,y0:y-12,x1:x+12,y1:y+12})})}
function draw(active,eventActiveKey=null){
  refreshRows();
  const w=canvas.clientWidth,h=canvas.clientHeight,outer=Math.round(Math.min(w,h)*.035);
  const axisLeft=76,axisRight=76,titleY=outer+18,xLabelGap=isEmbed?35:38,compact=w<760;
  const controlY=compact?outer+42:outer+33;
  const x0=outer+axisLeft,x1=w-outer-axisRight,y0=outer+(compact?88:60),y1=h-outer-xLabelGap;
  const [t0,t1]=currentRange(),sample=visibleRows(),[min0,max0]=priceExtent(sample),pad=Math.max((max0-min0)*.09,4);
  box={x0,x1,y0,y1,t0,t1,priceMin:min0-pad,priceMax:max0+pad,baseOpen:null};
  box.baseOpen=visibleBaseOpen();
  ctx.clearRect(0,0,w,h);ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);
  const titleSize=isEmbed&&w<760?18:21;
  ctx.fillStyle=colors.text;ctx.font=`700 ${titleSize}px Microsoft YaHei,Arial`;ctx.textAlign="center";ctx.fillText("WTI/Brent 原油价格与事件",w/2,titleY);
  const marketEnd=drawMarketTabs(x0,controlY);
  drawPeriodTabs(marketEnd+16,controlY);
  drawStartTabs(Math.max(x0+300,x1-184),controlY);
  drawWeekends();
  drawDateTicks();
  if(!isEmbed){ctx.fillStyle=colors.muted;ctx.font="11px Microsoft YaHei,Arial";ctx.textAlign="left";ctx.fillText(`刷新时间：UTC+8 ${P.generatedAt}　数据来源：${P.dataSources}　事件颜色：绿色表示好消息，红色表示坏消息，颜色越深表示强度越高`,x0,h-Math.max(8,outer*.35))}
  drawAxes();
  ctx.strokeStyle=colors.frame;ctx.lineWidth=1;ctx.strokeRect(x0,y0,x1-x0,y1-y0);
  ctx.save();ctx.beginPath();ctx.rect(x0,y0,x1-x0,y1-y0);ctx.clip();drawCandles();ctx.restore();
  drawEvents(eventActiveKey);
  ctx.fillStyle=colors.text;ctx.textAlign="center";ctx.save();ctx.translate(x0-52,(y0+y1)/2);ctx.rotate(-Math.PI/2);ctx.fillText("美元 / 桶",0,0);ctx.restore();
  ctx.save();ctx.translate(x1+52,(y0+y1)/2);ctx.rotate(Math.PI/2);ctx.fillText("上涨比例（首个开盘价=100%）",0,0);ctx.restore();
  if(!rows.length){ctx.fillStyle=colors.muted;ctx.textAlign="center";ctx.fillText("当前周期暂无数据",w/2,(y0+y1)/2)}
  if(active!=null&&rows[active]){const r=rows[active],x=xScale(r.t),key=firstMarketKey();ctx.setLineDash([5,5]);ctx.strokeStyle="rgba(31,41,55,.42)";ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(x,y0);ctx.lineTo(x,y1);ctx.stroke();ctx.setLineDash([]);if(hasOhlc(r,key)){const style=marketStyle[key]||marketStyle.wti;ctx.fillStyle="#fff";ctx.strokeStyle=style.stroke;ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,yPrice(q(r,key).c),3.6,0,Math.PI*2);ctx.fill();ctx.stroke()}}
}
function clampX(x){return Math.max(box.x0,Math.min(box.x1,x))}
function pointer(e){const rect=canvas.getBoundingClientRect();return{x:e.clientX-rect.left,y:e.clientY-rect.top,rect}}
function inPlot(p){return p.x>=box.x0&&p.x<=box.x1&&p.y>=box.y0&&p.y<=box.y1}
function timeAtX(x){return box.t0+(clampX(x)-box.x0)/(box.x1-box.x0)*(box.t1-box.t0)}
function hitEvent(p){return hitBox(p,eventBoxes)}
function nearest(mx){const key=firstMarketKey(),source=rows.filter(r=>hasOhlc(r,key));if(!source.length)return null;const t=timeAtX(mx);let l=0,r=source.length-1;while(l<r){const m=(l+r)>>1;if(source[m].t<t)l=m+1;else r=m}if(l>0&&Math.abs(source[l-1].t-t)<Math.abs(source[l].t-t))l--;return rows.indexOf(source[l])}
function drawSelection(){if(!drag)return;const x0=clampX(drag.x0),x1=clampX(drag.x1),left=Math.min(x0,x1),width=Math.abs(x1-x0);if(width<3)return;ctx.fillStyle="rgba(111,74,168,.10)";ctx.strokeStyle="rgba(111,74,168,.55)";ctx.lineWidth=1;ctx.fillRect(left,box.y0,width,box.y1-box.y0);ctx.strokeRect(left,box.y0,width,box.y1-box.y0)}
function rowLabel(r){return period==="m30"?timeText(r.t):dayLabel(r.date)}
function marketLines(r){return visibleMarkets().map(m=>`${m.label} K线：${valueText(r,m.key)}`).join("<br>")}
function showTip(p){
  if(!inPlot(p)){tip.style.display="none";draw();return}
  const eventHit=hitEvent(p);
  if(eventHit){const e=eventHit.event,key=eventHit.key,t=eventTime(e);draw(null,key);const x=xScale(t);ctx.setLineDash([4,5]);ctx.strokeStyle=eventColor(e.score,.42);ctx.beginPath();ctx.moveTo(x,box.y0);ctx.lineTo(x,box.y1);ctx.stroke();ctx.setLineDash([]);const slot=period==="m30"?`<br>30分钟格：${timeText(e.m30T)}`:"";tip.className="tip";tip.innerHTML=`<b>${e.label}</b><br>时间：${e.dateLabel}${slot}<br>类型：${e.type}<br>${e.description}`;tip.style.display="block";tip.style.left=Math.min(p.rect.width-330,Math.max(8,p.x+14))+"px";tip.style.top=Math.max(8,Math.min(p.rect.height-210,p.y-96))+"px";return}
  const i=nearest(p.x);if(i==null){tip.style.display="none";draw();return}const r=rows[i];draw(i);
  tip.className="tip";tip.innerHTML=`<b>${rowLabel(r)}</b><br>${marketLines(r)}`;tip.style.display="block";tip.style.left=Math.min(p.rect.width-340,Math.max(8,p.x+14))+"px";tip.style.top=Math.max(8,Math.min(p.rect.height-178,p.y-70))+"px";
}
canvas.addEventListener("click",e=>{const p=pointer(e),startTab=hitBox(p,startBoxes),periodTab=hitBox(p,periodBoxes),marketTab=hitBox(p,marketBoxes);if(startTab){viewStart=startTab.key;hoverStart=startTab.key;zoom=null;tip.style.display="none";draw();return}if(periodTab){period=periodTab.key;zoom=null;tip.style.display="none";draw();return}if(marketTab){const visible=visibleMarkets(false);if(!hidden[marketTab.key]&&visible.length===1)return;hidden[marketTab.key]=!hidden[marketTab.key];tip.style.display="none";draw()}});
canvas.addEventListener("mousedown",e=>{const p=pointer(e);if(hitBox(p,marketBoxes)||hitBox(p,periodBoxes)||hitBox(p,startBoxes)||!inPlot(p))return;drag={x0:p.x,x1:p.x};tip.style.display="none"});
canvas.addEventListener("mousemove",e=>{const p=pointer(e);if(drag){drag.x1=p.x;tip.style.display="none";draw();drawSelection();return}const startTab=hitBox(p,startBoxes),periodTab=hitBox(p,periodBoxes),marketTab=hitBox(p,marketBoxes);if(startTab||periodTab||marketTab){if(startTab&&hoverStart!==startTab.key){hoverStart=startTab.key;draw()}canvas.style.cursor="pointer";tip.style.display="none";return}if(hoverStart!==null){hoverStart=null;draw()}canvas.style.cursor=inPlot(p)?"crosshair":"default";showTip(p)});
window.addEventListener("mouseup",()=>{if(!drag)return;const x0=clampX(drag.x0),x1=clampX(drag.x1);if(Math.abs(x1-x0)>12){const a=timeAtX(x0),b=timeAtX(x1);zoom=[Math.min(a,b),Math.max(a,b)]}drag=null;tip.style.display="none";draw()});
canvas.addEventListener("mouseleave",()=>{if(drag)return;hoverStart=null;tip.style.display="none";canvas.style.cursor="default";draw()});
canvas.addEventListener("dblclick",()=>{zoom=null;drag=null;tip.style.display="none";draw()});
window.addEventListener("resize",resize);
refreshRows();
resize();
</script>
</body>
</html>
"""
    output_html.parent.mkdir(parents=True, exist_ok=True)
    html_text = add_canvas_mobile_support(html_text)
    output_html.write_text(html_text.replace("__PAYLOAD__", payload), encoding="utf-8")
