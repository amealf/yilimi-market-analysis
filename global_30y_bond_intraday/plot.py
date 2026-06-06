from __future__ import annotations

import html
import json
import os
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from scripts.mobile_chart_support import add_plotly_mobile_support

from .transform import opening_markers


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


CHART_DATA_SOURCES = "CNBC、TradingView"


def write_plot(
    data: pd.DataFrame,
    markets: list[dict],
    target_date,
    output_html: str | Path,
    available_dates: list | None = None,
) -> None:
    fig = go.Figure()
    day_start = pd.Timestamp(datetime.combine(target_date, time.min, tzinfo=timezone.utc))
    day_end = day_start + pd.Timedelta(days=1) - pd.Timedelta(minutes=1)
    latest_items = []

    for index, market in enumerate(markets):
        frame = data[data["region"] == market["region"]].copy()
        frame = trim_for_plot(frame)
        if frame.empty:
            frame = placeholder_frame(day_start, market)
        frame["move_bp_plot"] = pd.to_numeric(frame["move_bp"], errors="coerce").round(3)
        frame["utc_text"] = frame["timestamp_utc"].dt.strftime("%Y-%m-%d %H:%M UTC")
        frame["local_text"] = frame["timestamp_local"].map(format_timestamp)
        customdata = frame[["label", "yield_pct", "utc_text", "local_text", "source"]].to_numpy()
        fig.add_trace(
            go.Scatter(
                x=frame["timestamp_utc"],
                y=frame["move_bp_plot"],
                mode="lines",
                name=f"{market['label']} / {market['source_name']}",
                showlegend=True,
                line={"width": 1.25, "color": PYTHON_DEFAULT_COLORS[index % len(PYTHON_DEFAULT_COLORS)]},
                connectgaps=False,
                customdata=customdata,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Yield: %{customdata[1]:.3f}%<br>"
                    "Move: %{y:+.1f} bp<br>"
                    "UTC: %{customdata[2]}<br>"
                    "Local: %{customdata[3]}<br>"
                    "Source: %{customdata[4]}"
                    "<extra></extra>"
                ),
            )
        )
        latest_items.append((frame, market))

    for frame, market, yshift in latest_annotation_items(latest_items, "move_bp_plot", 2.0):
        add_latest_annotation(fig, frame, market, yshift)

    for open_time, labels in opening_markers(markets, target_date).items():
        x_value = open_time.isoformat()
        at_left_edge = open_time == day_start
        fig.add_shape(
            type="line",
            x0=x_value,
            x1=x_value,
            y0=0,
            y1=1,
            xref="x",
            yref="paper",
            line={"width": 1, "dash": "dot", "color": "#64748b"},
        )
        fig.add_annotation(
            x=x_value,
            y=1,
            xref="x",
            yref="paper",
            text=" / ".join(labels),
            showarrow=False,
            xanchor="left" if at_left_edge else "center",
            xshift=5 if at_left_edge else 0,
            yanchor="bottom",
            font={"size": 11, "color": "#475569"},
        )

    add_footer_note(fig)

    fig.update_layout(
        title={"text": "Global 30Y Sovereign Yield Intraday Moves", "x": 0.5, "xanchor": "center"},
        margin={"l": 70, "r": 150, "t": 124, "b": 96},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        hovermode="x unified",
        hoverdistance=50,
        spikedistance=50,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.06, "xanchor": "left", "x": 0},
        xaxis={
            "title": "UTC+0 time",
            "range": [day_start, day_end],
            "tickformat": "%H:%M",
            "showgrid": True,
            "gridcolor": "#e5e7eb",
            "zeroline": False,
            "showspikes": True,
            "spikemode": "across",
            "spikesnap": "cursor",
            "spikecolor": "rgba(71,85,105,.45)",
            "spikethickness": 1,
        },
        yaxis={
            "title": "Move from local open (bp)",
            "showgrid": True,
            "gridcolor": "#e5e7eb",
            "zeroline": True,
            "zerolinecolor": "#94a3b8",
            "showspikes": True,
            "spikemode": "across",
            "spikesnap": "cursor",
            "spikecolor": "rgba(71,85,105,.45)",
            "spikethickness": 1,
        },
        font={"family": "Microsoft YaHei, Noto Sans CJK SC, Arial, sans-serif", "color": "#172033"},
    )

    write_html(fig, output_html, target_date, available_dates or [])


def add_footer_note(fig: go.Figure) -> None:
    updated = pd.Timestamp.now(tz=ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    fig.add_annotation(
        x=0,
        y=-0.145,
        xref="paper",
        yref="paper",
        text=f"刷新时间：UTC+8 {updated}　数据来源：{html.escape(CHART_DATA_SOURCES)}",
        showarrow=False,
        xanchor="left",
        yanchor="top",
        align="left",
        font={"size": 11, "color": "#64748b"},
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
    valid = frame.dropna(subset=["yield_pct", "move_bp_plot"])
    if valid.empty:
        return
    latest = valid.iloc[-1]
    fig.add_annotation(
        x=latest["timestamp_utc"],
        y=latest["move_bp_plot"],
        text=f"{html.escape(market['label'])}<br>{float(latest['yield_pct']):.3f}% / {float(latest['move_bp_plot']):+.1f} bp",
        showarrow=False,
        xanchor="left",
        yanchor="middle",
        yshift=yshift,
        bgcolor="rgba(255,255,255,.72)",
        bordercolor="rgba(148,163,184,.55)",
        borderwidth=1,
        font={"size": 11},
    )


def trim_for_plot(frame: pd.DataFrame) -> pd.DataFrame:
    valid_positions = frame.index[frame["move_bp"].notna()].tolist()
    if not valid_positions:
        return frame.iloc[0:0].copy()
    start_position = frame.index.get_loc(valid_positions[0])
    end_position = frame.index.get_loc(valid_positions[-1])
    return frame.iloc[start_position : end_position + 1].copy()


def placeholder_frame(day_start: pd.Timestamp, market: dict) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp_utc": day_start,
                "timestamp_local": day_start.tz_convert(market["timezone"]),
                "label": market["label"],
                "yield_pct": pd.NA,
                "move_bp": pd.NA,
                "source": market["source_name"],
            }
        ]
    )


def format_timestamp(value: object) -> str:
    if pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M %Z")


def write_html(fig: go.Figure, output_html: str | Path, target_date, available_dates: list) -> None:
    path = Path(output_html)
    path.parent.mkdir(parents=True, exist_ok=True)
    date_nav = render_date_nav(target_date, available_dates)
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
  <title>Global 30Y Sovereign Yield Intraday Moves</title>
  <style>
    html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#fff;color:#172033;font-family:"Microsoft YaHei","Noto Sans CJK SC",Arial,sans-serif}}
    .page{{position:relative;width:100vw;height:100vh;background:#fff}}
    .home-link{{position:absolute;left:14px;top:14px;z-index:5;display:grid;place-items:center;width:32px;height:32px;border:1px solid rgba(120,129,145,.34);border-radius:6px;color:#526071;background:rgba(255,255,255,.76);text-decoration:none;box-shadow:0 6px 18px rgba(15,23,42,.08)}}
    .home-link:hover{{color:#172033;background:rgba(255,255,255,.95)}}
    .home-link svg{{width:18px;height:18px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}}
    .is-embed .home-link{{display:none}}
    .date-nav{{position:absolute;right:14px;top:14px;z-index:5;display:flex;align-items:center;gap:8px;color:#526071;background:rgba(255,255,255,.76);border:1px solid rgba(120,129,145,.34);border-radius:6px;padding:6px 8px;box-shadow:0 6px 18px rgba(15,23,42,.08)}}
    .date-nav label{{font-size:12px}}
    .date-nav select{{border:1px solid #cbd5e1;border-radius:5px;background:#fff;color:#172033;font-size:13px;padding:3px 6px}}
    .date-nav option[disabled]{{color:#94a3b8;background:#f1f5f9}}
    .is-embed .date-nav{{display:none}}
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
    {date_nav}
    <div class="chart-frame">{graph_html}</div>
  </div>
</body>
</html>
"""
    page = add_plotly_mobile_support(
        page,
        desktop_margin={"l": 70, "r": 150, "t": 124, "b": 96},
        tablet_margin={"l": 62, "r": 98, "t": 112, "b": 82},
        phone_margin={"l": 54, "r": 46, "t": 94, "b": 70},
    )
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


def render_date_nav(target_date, available_dates: list) -> str:
    date_items = normalize_date_nav_items(target_date, available_dates)
    if len(date_items) <= 1:
        return ""
    options = []
    for item in date_items:
        value = item["date"]
        selected = " selected" if value == str(target_date) else ""
        disabled = " disabled" if not item["has_data"] else ""
        label = value if item["has_data"] else f"{value} (No data)"
        options.append(f'<option value="global-30y-bond-intraday-{html.escape(value)}.html"{selected}{disabled}>{html.escape(label)}</option>')
    return f"""<div class="date-nav">
      <label for="history-date">Date</label>
      <select id="history-date" onchange="location.href=this.value">
        {''.join(options)}
      </select>
    </div>
    <script>window.GLOBAL_30Y_AVAILABLE_DATES={json.dumps(date_items)};</script>"""


def normalize_date_nav_items(target_date, available_dates: list) -> list[dict[str, object]]:
    items: dict[str, dict[str, object]] = {}
    for item in available_dates:
        if isinstance(item, dict):
            value = str(item.get("date"))
            has_data = bool(item.get("has_data", True))
        else:
            value = str(item)
            has_data = True
        if value and value != "None":
            items[value] = {"date": value, "has_data": has_data}
    target_value = str(target_date)
    items.setdefault(target_value, {"date": target_value, "has_data": True})
    return sorted(items.values(), key=lambda item: str(item["date"]), reverse=True)
