"""形态分析页：和值、奇偶、大小、三区、连号、AC 值。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import analytics as A
from .. import charts as C
from ..config import ACCENT_COLOR, BLUE_COLOR, RED_COLOR
from ..db import Database
from . import common as U

_SHAPE_COLUMNS = {
    "period": "期号",
    "draw_date": "开奖日期",
    "sum_value": "和值",
    "span": "跨度",
    "odd_even_ratio": "奇偶比",
    "big_count": "大数个数",
    "zone1": "一区",
    "zone2": "二区",
    "zone3": "三区",
    "consecutive": "最大连号",
    "ac_value": "AC值",
    "repeat_count": "重号个数",
}


def render(db: Database, data: pd.DataFrame) -> None:
    tab_sum, tab_parity, tab_zone, tab_misc = st.tabs(["和值", "奇偶与大小", "三区分布", "连号与 AC 值"])

    with tab_sum:
        left, right = st.columns(2, gap="large")
        with left:
            U.show_fig(C.histogram(data, "sum_value", "红球和值分布", RED_COLOR, bins=32, x_title="和值"))
        with right:
            U.show_fig(
                C.line_trend(
                    data,
                    "sum_value",
                    "和值走势",
                    RED_COLOR,
                    ma=10,
                    reference=102,
                    reference_text="理论均值 102",
                    y_title="和值",
                )
            )
        left, right = st.columns(2, gap="large")
        with left:
            U.show_fig(C.histogram(data, "span", "跨度分布", "#7c3aed", bins=24, x_title="跨度"))
        with right:
            U.show_fig(
                C.line_trend(
                    data, "span", "跨度走势", "#7c3aed", ma=10, ma_color=ACCENT_COLOR, y_title="跨度"
                )
            )

    with tab_parity:
        odd_summary = A.odd_even_summary(data)
        big_summary = A.big_small_summary(data)
        left, right = st.columns(2, gap="large")
        with left:
            U.show_fig(C.ratio_distribution(odd_summary, "odd", "奇偶比分布", RED_COLOR))
        with right:
            U.show_fig(C.ratio_distribution(big_summary, "big", "大小比分布", BLUE_COLOR))

        st.write("")
        U.section("每期奇偶个数", "红球 6 个号码中奇数与偶数的数量")
        U.show_fig(C.odd_even_stacked(data.tail(min(len(data), 100))))

        left, right = st.columns(2, gap="large")
        left.dataframe(
            odd_summary.rename(columns={"odd_count": "奇数个数", "ratio_label": "奇:偶", "count": "期数", "pct": "占比%"}),
            hide_index=True,
            width="stretch",
        )
        right.dataframe(
            big_summary.rename(columns={"big_count": "大数个数", "ratio_label": "大:小", "count": "期数", "pct": "占比%"}),
            hide_index=True,
            width="stretch",
        )

    with tab_zone:
        zones = A.zone_summary(data)
        left, right = st.columns([1, 1.6], gap="large")
        with left:
            U.show_fig(C.zone_donut(zones))
        with right:
            U.show_fig(C.zone_stacked(data.tail(min(len(data), 60))))
        st.dataframe(
            zones.rename(columns={"zone": "区间", "count": "红球个数", "ratio": "占比%"}).round(2),
            hide_index=True,
            width="stretch",
        )

    with tab_misc:
        left, right = st.columns(2, gap="large")
        with left:
            U.show_fig(
                C.bar_distribution(data, "consecutive", "最大连号长度分布", BLUE_COLOR, x_title="连号长度")
            )
        with right:
            U.show_fig(
                C.bar_distribution(data, "ac_value", "AC 值分布", ACCENT_COLOR, x_title="AC 值")
            )
        U.show_fig(
            C.bar_distribution(data, "repeat_count", "与上期重号个数分布", RED_COLOR, x_title="重号个数")
        )

    st.write("")
    U.section("形态明细", "包含每期和值、跨度、奇偶比、三区个数、连号、AC 值与重号")
    table = data[list(_SHAPE_COLUMNS)].rename(columns=_SHAPE_COLUMNS).copy()
    table["开奖日期"] = pd.to_datetime(table["开奖日期"]).dt.strftime("%Y-%m-%d")
    st.dataframe(
        U.pretty_periods(table.iloc[::-1]), hide_index=True, width="stretch", height=420
    )
    U.export_button(data, key="export_patterns", label="导出形态数据 CSV")
