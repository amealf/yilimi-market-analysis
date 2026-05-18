from __future__ import annotations

import html
import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs


PYTHON_DEFAULT_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]


RIGHT_PADDING_DAYS = 30


MAJOR_EVENTS = [
    {"date": "2008-09-15", "label": "Lehman", "ax": -58, "ay": 64},
    {"date": "2018-07-06", "label": "Trade war", "ax": 56, "ay": -58},
    {"date": "2020-03-11", "label": "COVID", "ax": -64, "ay": -58},
    {"date": "2022-02-24", "label": "Russia-Ukraine", "ax": 78, "ay": 48},
    {"date": "2022-09-23", "label": "UK mini-budget", "ax": -92, "ay": -62},
    {"date": "2022-12-20", "label": "BOJ YCC", "ax": 98, "ay": 58},
    {"date": "2025-06-22", "label": "US-Iran", "ax": -72, "ay": -64},
]


def write_plot(data: pd.DataFrame, markets: list[dict], output_html: str | Path) -> None:
    fig = go.Figure()
    date_values = pd.to_datetime(data["date"], errors="coerce").dropna()
    default_start = pd.Timestamp("2018-01-01")
    latest_date = date_values.max() if not date_values.empty else pd.Timestamp.today().normalize()
    first_date = date_values.min() if not date_values.empty else default_start
    range_end = latest_date + pd.offsets.BDay(RIGHT_PADDING_DAYS)
    default_range = [default_start.strftime("%Y-%m-%d"), range_end.strftime("%Y-%m-%d")]
    full_range = [first_date.strftime("%Y-%m-%d"), range_end.strftime("%Y-%m-%d")]
    for index, market in enumerate(markets):
        frame = data[data["region"] == market["region"]].copy().sort_values("date")
        if frame.empty:
            continue
        frame["date_text"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
        frame["daily_change_plot"] = pd.to_numeric(frame["daily_change_bp"], errors="coerce").round(1)
        frame["ytd_change_plot"] = pd.to_numeric(frame["ytd_change_bp"], errors="coerce").round(1)
        customdata = frame[
            ["label", "source", "date_text", "daily_change_plot", "ytd_change_plot"]
        ].to_numpy()
        fig.add_trace(
            go.Scatter(
                x=pd.to_datetime(frame["date"]),
                y=frame["close_yield_pct"],
                mode="lines",
                name=f"{market['label']} / {market['source_name']}",
                line={"width": 1.0, "color": PYTHON_DEFAULT_COLORS[index % len(PYTHON_DEFAULT_COLORS)]},
                opacity=1.0 if market["region"] == "US" else 0.6,
                connectgaps=False,
                customdata=customdata,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Yield: %{y:.3f}%<br>"
                    "1D: %{customdata[3]:+.1f} bp<br>"
                    "YTD: %{customdata[4]:+.1f} bp<br>"
                    "Date: %{customdata[2]}<br>"
                    "Source: %{customdata[1]}"
                    "<extra></extra>"
                ),
            )
        )

    add_event_markers(fig, data)
    add_footer_note(fig, markets)

    fig.update_layout(
        title={"text": "Global 30Y Sovereign Yield Daily History", "x": 0.5, "xanchor": "center", "y": 0.965, "yanchor": "top"},
        margin={"l": 72, "r": 76, "t": 104, "b": 96},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        hovermode="x unified",
        hoverlabel={
            "bgcolor": "rgba(255,255,255,0.25)",
            "bordercolor": "rgba(100,116,139,0.35)",
            "font": {"color": "#172033"},
        },
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.015, "xanchor": "left", "x": 0},
        updatemenus=[
            {
                "type": "buttons",
                "direction": "right",
                "active": 0,
                "showactive": True,
                "x": 1,
                "xanchor": "right",
                "y": 1.045,
                "yanchor": "bottom",
                "pad": {"r": 0, "t": 0},
                "bgcolor": "rgba(255,255,255,.75)",
                "bordercolor": "rgba(148,163,184,.55)",
                "font": {"size": 11},
                "buttons": [
                    {
                        "label": "2018+",
                        "method": "relayout",
                        "args": [{"xaxis.range": default_range, "xaxis.autorange": False}],
                    },
                    {
                        "label": "All",
                        "method": "relayout",
                        "args": [{"xaxis.range": full_range, "xaxis.autorange": False}],
                    },
                ],
            }
        ],
        xaxis={
            "title": "Date",
            "showgrid": True,
            "gridcolor": "#e5e7eb",
            "zeroline": False,
            "range": default_range,
            "dtick": "M12",
            "tick0": "2018-01-01",
            "tickformat": "%Y",
            "rangebreaks": [{"bounds": ["sat", "mon"]}],
        },
        yaxis={
            "title": "Yield (%)",
            "showgrid": True,
            "gridcolor": "#e5e7eb",
            "zeroline": False,
        },
        font={"family": "Microsoft YaHei, Noto Sans CJK SC, Arial, sans-serif", "color": "#172033"},
    )
    write_html(fig, output_html)


def add_footer_note(fig: go.Figure, markets: list[dict]) -> None:
    updated = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC")
    sources = ", ".join(f"{market['label']} {market['source_name']}" for market in markets)
    fig.add_annotation(
        x=0,
        y=-0.145,
        xref="paper",
        yref="paper",
        text=f"Updated: {updated} | Sources: {html.escape(sources)}",
        showarrow=False,
        xanchor="left",
        yanchor="top",
        align="left",
        font={"size": 11, "color": "#64748b"},
    )


def add_event_markers(fig: go.Figure, data: pd.DataFrame) -> None:
    if data.empty:
        return
    us_frame = data[data["region"] == "US"].copy()
    if us_frame.empty:
        return
    us_frame["date"] = pd.to_datetime(us_frame["date"])
    us_frame = us_frame.dropna(subset=["date", "close_yield_pct"]).sort_values("date")
    for index, event in enumerate(MAJOR_EVENTS):
        point = event_point(us_frame, pd.Timestamp(event["date"]))
        if point is None:
            continue
        fig.add_annotation(
            x=point["date"],
            y=point["close_yield_pct"],
            xref="x",
            yref="y",
            text=html.escape(event["label"]),
            showarrow=True,
            arrowhead=2,
            arrowsize=0.8,
            arrowwidth=0.8,
            arrowcolor="#475569",
            ax=event["ax"],
            ay=event["ay"],
            font={"size": 12, "color": "#334155"},
            bgcolor="rgba(255,255,255,.55)",
            bordercolor="rgba(100,116,139,.32)",
            borderwidth=1,
        )


def event_point(frame: pd.DataFrame, event_date: pd.Timestamp) -> pd.Series | None:
    after = frame[frame["date"] >= event_date]
    if after.empty:
        return None
    point = after.iloc[0]
    if point["date"] > event_date + pd.Timedelta(days=7):
        return None
    return point


def latest_annotation_items(items: list[tuple[pd.DataFrame, dict]], y_column: str, threshold: float) -> list[tuple[pd.DataFrame, dict, float]]:
    measured = []
    for position, (frame, market) in enumerate(items):
        valid = frame.dropna(subset=[y_column])
        if valid.empty:
            continue
        measured.append({"position": position, "frame": frame, "market": market, "y": float(valid.iloc[-1][y_column])})

    shifts = {item["position"]: 0.0 for item in measured}
    group: list[dict] = []
    for item in sorted(measured, key=lambda value: value["y"]):
        if not group or item["y"] - group[-1]["y"] <= threshold:
            group.append(item)
            continue
        apply_group_shifts(group, shifts)
        group = [item]
    apply_group_shifts(group, shifts)
    return [(item["frame"], item["market"], shifts[item["position"]]) for item in sorted(measured, key=lambda value: value["position"])]


def apply_group_shifts(group: list[dict], shifts: dict[int, float]) -> None:
    if len(group) <= 1:
        return
    for index, item in enumerate(group):
        shifts[item["position"]] = (index - (len(group) - 1) / 2) * 28


def add_latest_annotation(fig: go.Figure, frame: pd.DataFrame, market: dict, yshift: float) -> None:
    valid = frame.dropna(subset=["close_yield_pct"])
    if valid.empty:
        return
    latest = valid.iloc[-1]
    daily_change = latest["daily_change_bp"]
    change_text = "" if pd.isna(daily_change) else f" / {float(daily_change):+.1f} bp"
    fig.add_annotation(
        x=pd.Timestamp(latest["date"]),
        y=latest["close_yield_pct"],
        text=f"{html.escape(market['label'])}<br>{float(latest['close_yield_pct']):.3f}%{change_text}",
        showarrow=False,
        xanchor="left",
        yanchor="middle",
        yshift=yshift,
        bgcolor="rgba(255,255,255,.72)",
        bordercolor="rgba(148,163,184,.55)",
        borderwidth=1,
        font={"size": 11},
    )


def write_html(fig: go.Figure, output_html: str | Path) -> None:
    path = Path(output_html)
    path.parent.mkdir(parents=True, exist_ok=True)
    plotly_script = ensure_plotly_asset(path)
    graph_html = fig.to_html(
        full_html=False,
        include_plotlyjs=False,
        default_width="100%",
        default_height="100%",
        config={"displaylogo": False, "responsive": True},
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <script>if(new URLSearchParams(location.search).get("embed")==="1")document.documentElement.classList.add("is-embed");</script>
  <script src="{html.escape(plotly_script)}"></script>
  <title>Global 30Y Sovereign Yield Daily History</title>
  <style>
    html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#fff;color:#172033;font-family:"Microsoft YaHei","Noto Sans CJK SC",Arial,sans-serif}}
    .page{{position:relative;width:100vw;height:100vh;background:#fff}}
    .home-link{{position:absolute;left:14px;top:14px;z-index:5;display:grid;place-items:center;width:32px;height:32px;border:1px solid rgba(120,129,145,.34);border-radius:6px;color:#526071;background:rgba(255,255,255,.76);text-decoration:none;box-shadow:0 6px 18px rgba(15,23,42,.08)}}
    .home-link:hover{{color:#172033;background:rgba(255,255,255,.95)}}
    .home-link svg{{width:18px;height:18px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}}
    .is-embed .home-link{{display:none}}
    .chart-frame{{position:absolute;inset:0}}
    .chart-frame>div{{width:100%!important;height:100%!important}}
    .js-plotly-plot,.plot-container,.svg-container{{width:100%!important;height:100%!important}}
  </style>
</head>
<body>
  <div class="page">
    <a class="home-link" href="../../index.html" aria-label="Home">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M3 10.5 12 3l9 7.5"></path>
        <path d="M5 9.5V21h14V9.5"></path>
        <path d="M9 21v-6h6v6"></path>
      </svg>
    </a>
    <div class="chart-frame">{graph_html}</div>
  </div>
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")


def ensure_plotly_asset(output_html: Path) -> str:
    site_root = find_site_root(output_html)
    asset_path = site_root / "assets" / "plotly.min.js"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    if not asset_path.exists():
        asset_path.write_text(get_plotlyjs(), encoding="utf-8")
    relative = os.path.relpath(asset_path, output_html.parent)
    return relative.replace("\\", "/")


def find_site_root(path: Path) -> Path:
    for parent in path.parents:
        if parent.name == "site":
            return parent
    if len(path.parents) >= 3:
        return path.parents[2]
    return path.parent
