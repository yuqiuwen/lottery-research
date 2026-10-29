"""图表构造（Plotly，浅色主题）。"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from . import analytics as A
from .config import ACCENT_COLOR, BLUE_COLOR, NEUTRAL_COLOR, RED_COLOR

FONT_FAMILY = "-apple-system, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif"
GRID_COLOR = "#eef1f5"
TEXT_COLOR = "#374151"
ZONE_COLORS = ["#e2837f", "#efb366", "#7ea6d4"]


def _color_of(color: str) -> str:
    return RED_COLOR if color == "red" else BLUE_COLOR


def _finalize(fig: go.Figure, title: str, height: int = 380) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=TEXT_COLOR), x=0, xanchor="left"),
        template="plotly_white",
        height=height,
        margin=dict(l=8, r=16, t=48, b=8),
        font=dict(family=FONT_FAMILY, size=12, color=TEXT_COLOR),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(font=dict(family=FONT_FAMILY, size=12), bgcolor="#ffffff"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            x=1,
            xanchor="right",
            font=dict(size=11),
        ),
        bargap=0.25,
    )
    fig.update_xaxes(showgrid=False, linecolor="#e5e7eb", tickfont=dict(size=11))
    fig.update_yaxes(gridcolor=GRID_COLOR, zeroline=False, tickfont=dict(size=11))
    return fig


def _empty(title: str, message: str = "暂无数据") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(size=13, color=NEUTRAL_COLOR))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _finalize(fig, title, height=260)


def _period_axis(fig: go.Figure, nticks: int = 14) -> go.Figure:
    fig.update_xaxes(type="category", nticks=nticks, tickangle=-45, showgrid=False)
    return fig


def _headroom(values, ratio: float = 0.22) -> list[float]:
    """为柱顶外置数值标签留出空间，避免最高柱的数字被裁掉。"""
    numbers = [float(v) for v in values if v is not None and v == v]
    top = max(numbers) if numbers else 1.0
    if top <= 0:
        top = 1.0
    return [0.0, top * (1 + ratio)]


# ---------------------------------------------------------------- 频率 / 遗漏
def frequency_bar(table: pd.DataFrame, color: str = "red", title: str | None = None) -> go.Figure:
    title = title or ("红球出现次数" if color == "red" else "蓝球出现次数")
    if table.empty:
        return _empty(title)

    base = _color_of(color)
    fig = go.Figure(
        go.Bar(
            x=table["count"],
            y=table["number"].astype(str),
            orientation="h",
            marker=dict(color=base, line=dict(width=0)),
            text=table["count"],
            textposition="outside",
            textfont=dict(size=11),
            cliponaxis=False,
            customdata=table[["ratio", "expected", "deviation"]].to_numpy(),
            hovertemplate=(
                "号码 %{y}<br>出现 %{x} 次<br>出现率 %{customdata[0]:.1f}%"
                "<br>理论次数 %{customdata[1]:.1f}<br>偏差 %{customdata[2]:+.1f}<extra></extra>"
            ),
        )
    )
    fig.update_yaxes(autorange="reversed", dtick=1, title=None)
    fig.update_xaxes(title="出现次数", range=_headroom(table["count"], 0.14))
    if len(table):
        fig.add_vline(
            x=float(table["expected"].iloc[0]),
            line=dict(color=NEUTRAL_COLOR, width=1.5, dash="dash"),
            annotation_text=f"理论均值 {table['expected'].iloc[0]:.1f}",
            annotation_position="top",
            annotation_font=dict(size=11, color=NEUTRAL_COLOR),
        )
    return _finalize(fig, title, height=640)


def omission_bar(table: pd.DataFrame, color: str = "red", title: str | None = None) -> go.Figure:
    title = title or ("红球当前遗漏" if color == "red" else "蓝球当前遗漏")
    if table.empty:
        return _empty(title)

    ordered = table.sort_values(["current", "max_gap"], ascending=[False, False])
    colorscale = "Reds" if color == "red" else "Blues"
    fig = go.Figure(
        go.Bar(
            x=ordered["current"],
            y=ordered["number"].astype(str),
            orientation="h",
            marker=dict(
                color=ordered["current"],
                colorscale=colorscale,
                showscale=False,
                line=dict(width=0),
            ),
            text=ordered["current"],
            textposition="outside",
            textfont=dict(size=11),
            cliponaxis=False,
            customdata=ordered[["max_gap", "avg_gap", "last_period"]].to_numpy(),
            hovertemplate=(
                "号码 %{y}<br>当前遗漏 %{x} 期<br>最大遗漏 %{customdata[0]} 期"
                "<br>平均遗漏 %{customdata[1]} 期<br>最近出现 %{customdata[2]}<extra></extra>"
            ),
        )
    )
    fig.update_yaxes(autorange="reversed", dtick=1, title=None)
    fig.update_xaxes(title="遗漏期数", range=_headroom(ordered["current"], 0.12))
    return _finalize(fig, title, height=640)


def hot_cold_bar(table: pd.DataFrame, window: int, color: str = "red") -> go.Figure:
    title = f"近 {window} 期与全样本出现率对比"
    if table.empty:
        return _empty(title)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=table["ratio_all"],
            y=table["number"].astype(str),
            orientation="h",
            name="全样本出现率",
            marker_color="#cbd5e1",
            hovertemplate="号码 %{y}<br>全样本 %{x:.1f}%<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=table["ratio_recent"],
            y=table["number"].astype(str),
            orientation="h",
            name=f"近 {window} 期出现率",
            marker_color=_color_of(color),
            hovertemplate="号码 %{y}<br>近期 %{x:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(barmode="group", bargap=0.2, bargroupgap=0.08)
    fig.update_yaxes(autorange="reversed", dtick=1, title=None)
    fig.update_xaxes(title="出现率 %", rangemode="tozero")
    return _finalize(fig, title, height=max(360, 20 * len(table) + 120))


# ---------------------------------------------------------------- 走势
def trend_matrix(
    data: pd.DataFrame,
    color: str = "red",
    title: str | None = None,
    numbers: list[int] | None = None,
) -> go.Figure:
    """经典号码走势点阵图。"""
    title = title or ("红球走势" if color == "red" else "蓝球走势")
    if data.empty:
        return _empty(title)

    long = A.to_long(data, color)
    numbers = numbers or (A.RED_NUMBERS if color == "red" else A.BLUE_NUMBERS)
    long = long[long["number"].isin(numbers)]
    dates = dict(zip(data["period"], data["draw_date"].dt.strftime("%Y-%m-%d")))
    low, high = min(numbers), max(numbers)
    height = 620 if color == "red" else 420

    fig = go.Figure(
        go.Scatter(
            x=long["period"],
            y=long["number"],
            mode="markers",
            marker=dict(size=9, color=_color_of(color), line=dict(width=1, color="#ffffff")),
            customdata=[[dates.get(p, "")] for p in long["period"]],
            hovertemplate="期号 %{x}<br>日期 %{customdata[0]}<br>号码 %{y}<extra></extra>",
            showlegend=False,
        )
    )

    # 年份分隔线
    years = data["period"].str[:4].tolist()
    for index in range(1, len(years)):
        if years[index] != years[index - 1]:
            fig.add_vline(x=data["period"].iloc[index], line=dict(color="#cbd5e1", width=1, dash="dot"))

    fig.update_yaxes(
        range=[low - 0.7, high + 0.7],
        dtick=1,
        tickmode="linear",
        title=None,
        gridcolor=GRID_COLOR,
    )
    _period_axis(fig, nticks=18)
    return _finalize(fig, title, height=height)


def line_trend(
    data: pd.DataFrame,
    column: str,
    title: str,
    color: str,
    *,
    ma: int | None = None,
    ma_color: str = ACCENT_COLOR,
    reference: float | None = None,
    reference_text: str = "",
    y_title: str = "",
) -> go.Figure:
    if data.empty or column not in data:
        return _empty(title)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=data["period"],
            y=data[column],
            mode="lines+markers",
            name=y_title or title,
            line=dict(color=color, width=1.6),
            marker=dict(size=4, color=color),
            hovertemplate="期号 %{x}<br>%{y}<extra></extra>",
        )
    )
    if ma:
        fig.add_trace(
            go.Scatter(
                x=data["period"],
                y=data[column].rolling(ma, min_periods=1).mean(),
                mode="lines",
                name=f"{ma} 期均线",
                line=dict(color=ma_color, width=2),
                hovertemplate=f"{ma} 期均线 %{{y:.1f}}<extra></extra>",
            )
        )
    if reference is not None:
        fig.add_hline(
            y=reference,
            line=dict(color=NEUTRAL_COLOR, width=1.2, dash="dash"),
            annotation_text=reference_text,
            annotation_position="bottom right",
            annotation_font=dict(size=11, color="#6b7280"),
            annotation_bgcolor="rgba(255,255,255,0.82)",
        )
    fig.update_yaxes(title=y_title or None)
    _period_axis(fig, nticks=12)
    return _finalize(fig, title, height=360)


def blue_trend(data: pd.DataFrame) -> go.Figure:
    fig = line_trend(data, "blue", "蓝球走势", BLUE_COLOR, y_title="蓝球号码")
    if not data.empty:
        fig.update_yaxes(range=[0.4, 16.6], dtick=1)
    return fig


# ---------------------------------------------------------------- 分布
def zone_stacked(data: pd.DataFrame) -> go.Figure:
    title = "每期三区分布"
    if data.empty:
        return _empty(title)
    fig = go.Figure()
    for (low, high, label, key), color in zip(A.ZONES, ZONE_COLORS):
        fig.add_trace(
            go.Bar(
                x=data["period"],
                y=data[key],
                name=label,
                marker_color=color,
                hovertemplate=f"{label}<br>期号 %{{x}}<br>%{{y}} 个<extra></extra>",
            )
        )
    fig.update_layout(barmode="stack", bargap=0.15)
    fig.update_yaxes(title="红球个数", dtick=1)
    _period_axis(fig, nticks=14)
    return _finalize(fig, title, height=340)


def odd_even_stacked(data: pd.DataFrame) -> go.Figure:
    title = "每期奇偶个数"
    if data.empty:
        return _empty(title)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(x=data["period"], y=data["odd_count"], name="奇数", marker_color=RED_COLOR,
               hovertemplate="期号 %{x}<br>奇数 %{y} 个<extra></extra>")
    )
    fig.add_trace(
        go.Bar(x=data["period"], y=data["even_count"], name="偶数", marker_color="#8fb3d9",
               hovertemplate="期号 %{x}<br>偶数 %{y} 个<extra></extra>")
    )
    fig.update_layout(barmode="stack", bargap=0.15)
    fig.update_yaxes(title="红球个数", dtick=1)
    _period_axis(fig, nticks=14)
    return _finalize(fig, title, height=340)


def ratio_distribution(summary: pd.DataFrame, x: str, title: str, color: str) -> go.Figure:
    if summary.empty:
        return _empty(title)
    fig = go.Figure(
        go.Bar(
            x=summary["ratio_label"],
            y=summary["pct"],
            marker_color=color,
            text=[f"{pct:.1f}%" for pct in summary["pct"]],
            textposition="outside",
            textfont=dict(size=11),
            cliponaxis=False,
            customdata=summary["count"].to_numpy(),
            hovertemplate="比值 %{x}<br>占比 %{y:.1f}%<br>期数 %{customdata}<extra></extra>",
        )
    )
    fig.update_xaxes(title="奇:偶" if x == "odd" else "大:小", type="category")
    fig.update_yaxes(title="占比 %", range=_headroom(summary["pct"]))
    return _finalize(fig, title, height=320)


def zone_donut(summary: pd.DataFrame) -> go.Figure:
    title = "红球三区占比"
    if summary.empty:
        return _empty(title)
    fig = go.Figure(
        go.Pie(
            labels=summary["zone"],
            values=summary["count"],
            hole=0.55,
            marker=dict(colors=ZONE_COLORS, line=dict(color="#ffffff", width=2)),
            textinfo="percent",
            hovertemplate="%{label}<br>%{value} 个（%{percent}）<extra></extra>",
        )
    )
    _finalize(fig, title, height=340)
    fig.update_layout(
        legend=dict(orientation="h", yanchor="top", y=-0.02, x=0.5, xanchor="center", font=dict(size=11))
    )
    return fig


def histogram(
    data: pd.DataFrame,
    column: str,
    title: str,
    color: str,
    *,
    bins: int = 30,
    mean_line: bool = True,
    x_title: str = "",
) -> go.Figure:
    if data.empty or column not in data:
        return _empty(title)
    values = data[column].dropna()
    if values.empty:
        return _empty(title)
    fig = go.Figure(
        go.Histogram(
            x=values,
            nbinsx=bins,
            marker=dict(color=color, line=dict(color="#ffffff", width=1)),
            opacity=0.9,
            hovertemplate="区间 %{x}<br>期数 %{y}<extra></extra>",
        )
    )
    if mean_line:
        mean = float(values.mean())
        fig.add_vline(
            x=mean,
            line=dict(color=ACCENT_COLOR, width=2, dash="dash"),
            annotation_text=f"均值 {mean:.1f}",
            annotation_position="top",
            annotation_font=dict(size=11, color=ACCENT_COLOR),
        )
    fig.update_xaxes(title=x_title or None)
    fig.update_yaxes(title="期数")
    return _finalize(fig, title, height=320)


def bar_distribution(
    data: pd.DataFrame, column: str, title: str, color: str, *, x_title: str = ""
) -> go.Figure:
    if data.empty or column not in data:
        return _empty(title)
    counts = data[column].value_counts().sort_index()
    fig = go.Figure(
        go.Bar(
            x=counts.index.astype(str),
            y=counts.to_numpy(),
            marker_color=color,
            text=counts.to_numpy(),
            textposition="outside",
            textfont=dict(size=11),
            cliponaxis=False,
            hovertemplate="%{x}<br>期数 %{y}<extra></extra>",
        )
    )
    fig.update_xaxes(type="category", title=x_title or None)
    fig.update_yaxes(title="期数", range=_headroom(counts.to_numpy()))
    return _finalize(fig, title, height=300)
