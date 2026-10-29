"""号码分析页：频率、遗漏、冷热。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import analytics as A
from .. import charts as C
from ..db import Database
from . import common as U

_DISPLAY = {
    "number": "号码",
    "count": "出现次数",
    "ratio": "出现率%",
    "expected": "理论次数",
    "deviation": "偏差",
    "rank": "频次排名",
    "current": "当前遗漏",
    "max_gap": "最大遗漏",
    "avg_gap": "平均遗漏",
    "appearances": "出现期数",
    "last_period": "最近出现",
    "ratio_all": "全样本%",
    "ratio_recent": "近期%",
    "delta": "冷热差",
    "state": "状态",
    "count_all": "全样本次数",
    "count_recent": "近期次数",
}


def render(db: Database, data: pd.DataFrame) -> None:
    color_label = st.radio(
        "号码类型", ["红球", "蓝球"], horizontal=True, label_visibility="collapsed", key="numbers_color"
    )
    color = "red" if color_label == "红球" else "blue"
    color_name = "红球" if color == "red" else "蓝球"

    freq = A.frequency_table(data, color)
    omission = A.omission_table(data, color)

    left, right = st.columns(2, gap="large")
    with left:
        U.show_fig(C.frequency_bar(freq, color, f"{color_name}出现次数"))
    with right:
        U.show_fig(C.omission_bar(omission, color, f"{color_name}当前遗漏"))

    st.write("")
    U.section(
        "冷热对比",
        "近期出现率高于全样本 3 个百分点记作「热」，低于 3 个百分点记作「冷」",
    )
    max_window = max(10, min(len(data), 300))
    window = U.slider_or_value(
        "观察窗口（期）", 10, max_window, min(50, max_window), key="numbers_window"
    )
    hot = A.hot_cold_table(data, window, color)
    U.show_fig(C.hot_cold_bar(hot, window, color))

    st.write("")
    U.section("明细数据", "可排序，支持导出当前范围")
    merged = (
        freq.merge(omission, on="number", how="left")
        .merge(
            hot[["number", "count_recent", "ratio_recent", "delta", "state"]],
            on="number",
            how="left",
        )
        .rename(columns=_DISPLAY)
    )
    merged["出现率%"] = merged["出现率%"].round(2)
    merged["理论次数"] = merged["理论次数"].round(1)
    merged["偏差"] = merged["偏差"].round(1)
    merged["近期%"] = merged["近期%"].round(2)
    merged["冷热差"] = merged["冷热差"].round(2)

    st.dataframe(
        merged,
        hide_index=True,
        width="stretch",
        height=min(560, 36 * len(merged) + 40),
        column_config={
            "号码": st.column_config.NumberColumn(format="%02d"),
        },
    )
    U.export_button(merged, key=f"export_numbers_{color}", label="导出号码统计 CSV")
