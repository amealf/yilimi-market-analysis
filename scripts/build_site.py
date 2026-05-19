from __future__ import annotations

import argparse
import html
import importlib
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
SITE_DIR = ROOT / "site"
CONFIG_PATH = ROOT / "charts.yml"
DATA_SOURCES = "东方财富、新浪财经、CryptoCompare、DefiLlama、KOFIA FreeSIS、Yahoo Finance、Naver Finance、CNBC、TradingView、CSV"
CATEGORY_SOURCES = {
    "a-share-margin": "东方财富、新浪财经",
    "crypto-liquidity": "CryptoCompare、DefiLlama",
    "other-markets": "KOFIA FreeSIS、Yahoo Finance、Naver Finance",
    "global-rates": "CNBC、TradingView",
}


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp)


def site_path(relative_path: str) -> Path:
    return SITE_DIR.joinpath(*relative_path.split("/"))


def ensure_site_dirs() -> None:
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")


def build_margin_csi500(chart: dict) -> dict:
    sys.path.insert(0, str(SCRIPTS_DIR))
    module = importlib.import_module(chart["module"])

    margin = module.fetch_margin_balance()
    csi500 = module.fetch_csi500()
    chinext = module.fetch_chinext()
    data = pd.merge(margin, csi500, on="date", how="outer").sort_values("date")
    data = pd.merge(data, chinext, on="date", how="outer").sort_values("date")
    data = module.add_index_ratios(data)

    csv_path = site_path(chart["output_csv"])
    html_path = site_path(chart["output_html"])
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)

    data.to_csv(csv_path, index=False, encoding="utf-8-sig")
    module.write_interactive_html(data, html_path)

    meta = module.chart_meta(data)
    return {
        "latest_margin_date": meta["latestMarginDate"],
        "latest_margin": meta["latestMargin"],
        "latest_csi_date": meta["latestCsiDate"],
        "latest_csi": meta["latestCsi"],
        "latest_chinext_date": meta["latestChinextDate"],
        "latest_chinext": meta["latestChinext"],
        "metrics": [
            {"label": "融资余额", "value": f"{meta['latestMargin']:.4f} 万亿", "date": meta["latestMarginDate"]},
            {"label": "中证500", "value": f"{meta['latestCsi']:.2f}", "date": meta["latestCsiDate"]},
            {"label": "创业板指", "value": f"{meta['latestChinext']:.2f}", "date": meta["latestChinextDate"]},
        ],
    }


def build_usdt_speed_indicator(chart: dict) -> dict:
    sys.path.insert(0, str(SCRIPTS_DIR))
    module = importlib.import_module(chart["module"])

    csv_path = site_path(chart["output_csv"])
    html_path = site_path(chart["output_html"])
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)

    source_cache_path = ROOT / chart["output_csv"]
    data = module.build_indicator_frame(cache_path=source_cache_path if source_cache_path.exists() else csv_path)
    data.to_csv(csv_path, index=False, encoding="utf-8-sig")
    module.write_interactive_html(data, html_path)
    return module.chart_meta(data)


def build_korea_margin_kospi(chart: dict) -> dict:
    sys.path.insert(0, str(SCRIPTS_DIR))
    module = importlib.import_module(chart["module"])

    financing = module.fetch_credit_financing_balance()
    kospi = module.fetch_kospi()
    foreign = module.fetch_foreign_net_buy()
    data = pd.merge(financing, kospi, on="date", how="outer").sort_values("date")
    data = pd.merge(data, foreign, on="date", how="outer").sort_values("date")
    data = data.dropna(subset=["credit_financing_trillion_krw", "kospi_close"])
    data = module.add_index_ratios(data)

    csv_path = site_path(chart["output_csv"])
    html_path = site_path(chart["output_html"])
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)

    data.to_csv(csv_path, index=False, encoding="utf-8-sig")
    module.write_interactive_html(data, html_path)

    meta = module.chart_meta(data)
    return {
        "latest_financing_date": meta["latestFinancingDate"],
        "latest_financing": meta["latestFinancing"],
        "latest_kospi_date": meta["latestKospiDate"],
        "latest_kospi": meta["latestKospi"],
        "metrics": [
            {
                "label": "信用交易融资余额",
                "value": f"{meta['latestFinancing']:.3f} 万亿韩元",
                "date": meta["latestFinancingDate"],
            },
            {"label": "KOSPI", "value": f"{meta['latestKospi']:.2f}", "date": meta["latestKospiDate"]},
            {
                "label": "外资净买入",
                "value": f"{meta['latestForeignNetBuy']:.0f} 亿韩元",
                "date": meta["latestForeignDate"],
            },
        ],
    }


def build_global_30y_bond_intraday(chart: dict) -> dict:
    sys.path.insert(0, str(ROOT))
    module = importlib.import_module(chart["module"])

    csv_path = site_path(chart["output_csv"])
    html_path = site_path(chart["output_html"])
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)

    return module.build_history(
        config_path=ROOT / "global_30y_bond_intraday" / "config.yaml",
        output_html=html_path,
        summary_csv=csv_path,
    )


def build_global_30y_bond_daily(chart: dict) -> dict:
    sys.path.insert(0, str(ROOT))
    module = importlib.import_module(chart["module"])

    csv_path = site_path(chart["output_csv"])
    html_path = site_path(chart["output_html"])
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)

    return module.build(
        config_path=ROOT / "global_30y_bond_daily" / "config.yaml",
        output_html=html_path,
        data_csv=csv_path,
    )


BUILDERS = {
    "margin_csi500": build_margin_csi500,
    "usdt_speed_indicator": build_usdt_speed_indicator,
    "korea_margin_kospi": build_korea_margin_kospi,
    "global_30y_bond_intraday": build_global_30y_bond_intraday,
    "global_30y_bond_daily": build_global_30y_bond_daily,
}


def render_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{
      margin: 0;
      color: #142033;
      background: #eef3f7;
      font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif;
    }}
    a {{ color: inherit; text-decoration: none; }}
    .shell {{ max-width: 1380px; margin: 0 auto; padding: 22px 22px 34px; }}
    .top {{
      display: grid;
      grid-template-columns: 1fr auto;
      align-items: end;
      gap: 18px;
      padding: 18px 0 16px;
    }}
    h1 {{ margin: 0; font-size: 30px; line-height: 1.16; letter-spacing: 0; }}
    .home-top {{
      display: block;
      text-align: center;
      padding: 34px 0 30px;
    }}
    .home-top h1 {{
      font-size: 40px;
      line-height: 1.08;
      font-weight: 800;
      color: #0f172a;
    }}
    .home-top .muted {{
      max-width: 760px;
      margin: 12px auto 0;
      font-size: 15px;
      color: #526071;
    }}
    h2 {{ margin: 24px 0 12px; font-size: 19px; }}
    .muted {{ color: #5d6a7d; font-size: 14px; line-height: 1.7; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }}
    .card {{
      background: #fff;
      border: 1px solid #d7e0e8;
      border-radius: 8px;
      padding: 14px;
      box-shadow: 0 12px 30px rgba(15, 23, 42, 0.07);
    }}
    .card h3 {{ margin: 0 0 6px; font-size: 17px; line-height: 1.35; }}
    .card p {{ margin: 0 0 10px; color: #4b586a; line-height: 1.6; font-size: 13px; }}
    .category-list {{ display: flex; flex-wrap: wrap; gap: 7px; margin-top: 10px; }}
    .chip {{
      display: inline-flex;
      align-items: center;
      border: 1px solid #d7e0e8;
      border-radius: 999px;
      padding: 5px 8px;
      color: #475569;
      background: #f8fafc;
      font-size: 12px;
    }}
    .chart-preview {{
      position: relative;
      display: block;
      margin: 10px 0 0;
      aspect-ratio: 16 / 9;
      overflow: hidden;
      border: 1px solid #d7e0e8;
      border-radius: 6px;
      background: #fff;
    }}
    .chart-preview iframe {{
      width: 100%;
      height: 100%;
      display: block;
      border: 0;
      pointer-events: none;
    }}
    .preview-hit {{
      position: absolute;
      inset: 0;
      z-index: 2;
    }}
    .preview-hit:focus-visible {{
      outline: 2px solid #2563eb;
      outline-offset: -2px;
    }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 9px; margin-top: 12px; }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
      color: #475569;
      font-size: 13px;
      line-height: 1.45;
    }}
    .metric {{
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 8px 9px;
      background: #f8fafc;
    }}
    .metric-label {{ color: #64748b; font-size: 12px; }}
    .metric-value {{ margin-top: 3px; font-weight: 700; color: #172033; }}
    .metric-date {{ margin-top: 2px; color: #718096; font-size: 11px; }}
    .button {{
      display: inline-flex;
      align-items: center;
      padding: 8px 11px;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      background: #f8fafc;
      font-size: 14px;
    }}
    .button:hover {{ background: #eef2f7; }}
    footer {{ margin-top: 32px; color: #64748b; font-size: 12px; }}
    @media (max-width: 960px) {{
      .top {{ grid-template-columns: 1fr; }}
      .grid {{ grid-template-columns: 1fr; }}
      .home-top {{ padding: 24px 0 24px; }}
      .home-top h1 {{ font-size: 34px; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    {body}
  </main>
</body>
</html>
"""


def chart_card(chart: dict, category: dict, generated: dict, prefix: str = "") -> str:
    chart_id = chart["id"]
    info = generated.get(chart_id, {})
    chart_url = prefix + chart["output_html"].replace("\\", "/")
    preview_url = chart_url + ("&" if "?" in chart_url else "?") + "notes=0&embed=1"
    csv_url = prefix + chart["output_csv"].replace("\\", "/")
    chart_title = html.escape(chart["title"])
    description = str(chart.get("description") or "").strip()
    description_html = f"\n  <p>{html.escape(description)}</p>" if description else ""
    metric_rows = []
    for metric in info.get("metrics", []):
        date_text = metric.get("date")
        date_html = f'<div class="metric-date">{html.escape(str(date_text))}</div>' if date_text else ""
        metric_rows.append(
            f"""
    <div class="metric">
      <div class="metric-label">{html.escape(str(metric.get("label", "")))}</div>
      <div class="metric-value">{html.escape(str(metric.get("value", "")))}</div>
      {date_html}
    </div>
"""
        )
    metrics_html = "".join(metric_rows)
    return f"""
<article class="card">
  {description_html}
  <div class="chart-preview">
    <iframe src="{html.escape(preview_url)}" title="{chart_title}小图" loading="lazy"></iframe>
    <a class="preview-hit" href="{html.escape(chart_url)}" aria-label="打开{chart_title}"></a>
  </div>
  <div class="actions">
    <a class="button" href="{html.escape(chart_url)}">打开图表</a>
    <a class="button" href="{html.escape(csv_url)}" download>下载 CSV</a>
  </div>
  <div class="meta">{metrics_html}</div>
</article>
"""


def category_card(category: dict, charts: list[dict], prefix: str = "") -> str:
    category_url = prefix + f"{category['id']}/index.html"
    title = html.escape(category["title"])
    description = html.escape(str(category.get("description") or ""))
    chart_chips = "".join(f'<span class="chip">{html.escape(chart["title"])}</span>' for chart in charts)
    return f"""
<article class="card">
  <h3>{title}</h3>
  <p>{description}</p>
  <div class="category-list">{chart_chips}</div>
  <div class="actions">
    <a class="button" href="{html.escape(category_url)}">进入{title}</a>
  </div>
</article>
"""


def category_footer(category_id: str, now: str) -> str:
    sources = CATEGORY_SOURCES.get(category_id, DATA_SOURCES)
    return f"<footer>刷新时间：北京时间 {now}　数据来源：{html.escape(sources)}。</footer>"


def write_index(config: dict, generated: dict, selected_ids: set[str]) -> None:
    categories = {item["id"]: item for item in config["categories"]}
    charts = [chart for chart in config["charts"] if chart["id"] in selected_ids]
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    home_cards = []
    for category in config["categories"]:
        category_charts = [chart for chart in charts if chart["category"] == category["id"]]
        if not category_charts:
            continue
        category_cards = "".join(
            chart_card(chart, category, generated, prefix="../") for chart in category_charts
        )
        category_dir = SITE_DIR / category["id"]
        category_dir.mkdir(parents=True, exist_ok=True)
        category_body = f"""
<div class="top">
  <div>
    <h1>{html.escape(category["title"])}</h1>
    <div class="muted">{html.escape(category["description"])}</div>
  </div>
  <a class="button" href="../index.html">返回首页</a>
</div>
<div class="grid">{category_cards}</div>
{category_footer(category["id"], now)}
"""
        (category_dir / "index.html").write_text(
            render_page(category["title"], category_body),
            encoding="utf-8",
        )
        if category["id"] in {"other-markets", "global-rates"}:
            home_cards.append(category_card(category, category_charts))
        else:
            home_cards.append("".join(chart_card(chart, category, generated) for chart in category_charts))

    body = f"""
<div class="top home-top">
  <div>
    <h1>{html.escape(config["site"]["title"])}</h1>
    <div class="muted">{html.escape(config["site"]["description"])}</div>
  </div>
</div>
<section>
  <h2>市场监控</h2>
  <div class="grid">{''.join(home_cards)}</div>
</section>
"""
    (SITE_DIR / "index.html").write_text(
        render_page(config["site"]["title"], body),
        encoding="utf-8",
    )


def build(selected_chart: str | None) -> None:
    config = load_config()
    ensure_site_dirs()

    if selected_chart:
        charts = [chart for chart in config["charts"] if chart["id"] == selected_chart]
        if not charts:
            raise SystemExit(f"未找到图表：{selected_chart}")
    else:
        charts = config["charts"]

    generated: dict[str, dict] = {}
    for chart in charts:
        builder = BUILDERS.get(chart["builder"])
        if not builder:
            raise SystemExit(f"未注册图表生成器：{chart['builder']}")
        generated[chart["id"]] = builder(chart)

    selected_ids = {chart["id"] for chart in charts}
    write_index(config, generated, selected_ids)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 A 股图表静态站点")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="生成全部图表")
    group.add_argument("--chart", help="只生成指定图表 id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build(None if args.all else args.chart)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
