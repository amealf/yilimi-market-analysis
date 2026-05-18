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


MAJOR_EVENTS = [
    {"date": "2008-09-15", "label": "Lehman"},
    {"date": "2018-07-06", "label": "Trade war"},
    {"date": "2020-03-11", "label": "COVID"},
    {"date": "2022-02-24", "label": "Russia-Ukraine"},
    {"date": "2022-09-23", "label": "UK mini-budget"},
    {"date": "2022-12-20", "label": "BOJ YCC"},
]


def write_plot(data: pd.DataFrame, markets: list[dict], output_html: str | Path) -> None:
    fig = go.Figure()
    latest_items = []
    for index, market in enumerate(markets):
        frame = data[data["region"] == market["region"]].copy().sort_values("date")
        if frame.empty:
            continue
        frame["date_text"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
        frame["daily_change_plot"] = pd.to_numeric(frame["daily_change_bp"], errors="coerce").round(1)
        frame["ytd_change_plot"] = pd.to_numeric(frame["ytd_change_bp"], errors="coerce").round(1)
        customdata = frame[["daily_change_plot", "ytd_change_plot"]].to_numpy()
        fig.add_trace(
            go.Scatter(
                x=pd.to_datetime(frame["date"]),
                y=frame["close_yield_pct"],
                mode="lines",
                name=f"{market['label']} / {market['source_name']}",
                line={"width": 1.0, "color": PYTHON_DEFAULT_COLORS[index % len(PYTHON_DEFAULT_COLORS)]},
                connectgaps=False,
                customdata=customdata,
                hovertemplate=(
                    f"<b>{html.escape(market['label'])}</b><br>"
                    "Yield: %{y:.3f}%<br>"
                    "1D: %{customdata[0]:+.1f} bp<br>"
                    "YTD: %{customdata[1]:+.1f} bp<br>"
                    "Date: %{x|%Y-%m-%d}<br>"
                    f"Source: {html.escape(market['source_name'])}"
                    "<extra></extra>"
                ),
            )
        )
        latest_items.append((frame, market))

    for frame, market, yshift in latest_annotation_items(latest_items, "close_yield_pct", 0.25):
        add_latest_annotation(fig, frame, market, yshift)
    add_event_markers(fig, data)

    fig.update_layout(
        title={"text": "Global 30Y Sovereign Yield Daily History", "x": 0.5, "xanchor": "center"},
        margin={"l": 72, "r": 150, "t": 112, "b": 74},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        hovermode="closest",
        hoverdistance=18,
        spikedistance=-1,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.05, "xanchor": "left", "x": 0},
        xaxis={
            "title": "Date",
            "showgrid": True,
            "gridcolor": "#e5e7eb",
            "zeroline": False,
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


def add_event_markers(fig: go.Figure, data: pd.DataFrame) -> None:
    if data.empty:
        return
    min_date = pd.to_datetime(data["date"]).min()
    max_date = pd.to_datetime(data["date"]).max()
    for index, event in enumerate(MAJOR_EVENTS):
        event_date = pd.Timestamp(event["date"])
        if event_date < min_date or event_date > max_date:
            continue
        fig.add_shape(
            type="line",
            x0=event_date,
            x1=event_date,
            y0=0,
            y1=1,
            xref="x",
            yref="paper",
            line={"width": 0.8, "dash": "dot", "color": "#64748b"},
        )
        fig.add_annotation(
            x=event_date,
            y=0.98,
            xref="x",
            yref="paper",
            text=html.escape(event["label"]),
            showarrow=False,
            textangle=-90,
            xanchor="left",
            yanchor="top",
            yshift=-(index % 2) * 16,
            font={"size": 10, "color": "#475569"},
            bgcolor="rgba(255,255,255,.62)",
        )


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
