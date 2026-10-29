"""走势页：号码点阵走势、和值与跨度曲线。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import analytics as A
from .. import charts as C
from ..config import ACCENT_COLOR, RED_COLOR
from ..db import Database
from . import common as U

_ZONES = {
    "全部 1-33": A.RED_NUMBERS,
    "一区 1-11": list(range(1, 12)),
    "二区 12-22": list(range(12, 23)),
    "三区 23-33": list(range(23, 34)),
}


def render(db: Database, data: pd.DataFrame) -> None:
    max_n = min(len(data), 500)
    upper = max(10, max_n)
    controls = st.columns([2, 2])
    with controls[0]:
        count = U.slider_or_value(
            "显示期数", 10, upper, min(100, upper), key="trend_count"
        )
    with controls[1]:
        zone_label = st.radio(
            "红球区段", list(_ZONES), horizontal=True, key="trend_zone"
        )

    subset = data.tail(count)
    numbers = _ZONES[zone_label]

    U.section("红球走势", "点阵图中每个圆点代表该期开出的一个红球，竖向排列即号码分布")
    U.show_fig(
        C.trend_matrix(subset, "red", f"红球走势（近 {count} 期 · {zone_label}）", numbers)
    )

    U.section("蓝球走势", "折线与点阵同时呈现，便于观察蓝球连出与间隔")
    U.show_fig(C.trend_matrix(subset, "blue", f"蓝球走势（近 {count} 期）"))

    st.write("")
    left, right = st.columns(2, gap="large")
    with left:
        U.show_fig(
            C.line_trend(
                subset,
                "sum_value",
                "红球和值走势",
                RED_COLOR,
                ma=10,
                reference=102,
                reference_text="理论均值 102",
                y_title="和值",
            )
        )
    with right:
        U.show_fig(
            C.line_trend(
                subset,
                "span",
                "红球跨度走势",
                "#7c3aed",
                ma=10,
                ma_color=ACCENT_COLOR,
                y_title="跨度",
            )
        )

    U.show_fig(C.blue_trend(subset))

    st.write("")
    with st.expander("查看走势明细数据", expanded=False):
        columns = ["period", "draw_date", *A.RED_COLUMNS, "blue", "sum_value", "span", "repeat_count"]
        st.dataframe(
            U.pretty_periods(
                subset[columns].rename(
                    columns={
                        "period": "期号",
                        "draw_date": "开奖日期",
                        "blue": "蓝球",
                        "sum_value": "和值",
                        "span": "跨度",
                        "repeat_count": "重号个数",
                    }
                )
            ),
            hide_index=True,
            width="stretch",
        )
    U.export_button(subset, key="export_trend", label="导出走势数据 CSV")
