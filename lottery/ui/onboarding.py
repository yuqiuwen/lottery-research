"""首次使用引导：数据库为空时的落地页。"""

from __future__ import annotations

import streamlit as st

from ..crawler.periods import current_year_end
from ..db import Database
from . import common as U


def render(db: Database) -> None:
    st.markdown(
        '<div style="font-size:28px;font-weight:700;letter-spacing:-0.02em">双色球数据分析</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="ssq-hint" style="font-size:14px;margin-top:4px">'
        "本地 SQLite 存储 · 手动区间抓取 · 多维图表分析 · CSV 导出</div>",
        unsafe_allow_html=True,
    )
    st.write("")

    st.info("数据库还是空的，先抓一批开奖数据吧。抓取会按期号去重，重复执行不会产生重复记录。")

    col1, col2 = st.columns(2)
    if col1.button("抓取最近 100 期", type="primary", width="stretch"):
        U.run_recent(db, 100)
    if col2.button("抓取全部历史（2003 年至今）", width="stretch"):
        U.run_crawl(db, "2003001", current_year_end(), source="auto", only_missing=True)

    st.write("")
    with st.expander("自定义期号区间", expanded=False):
        c1, c2 = st.columns(2)
        start = c1.text_input("起始期号", value="2025001", key="onboard_start")
        end = c2.text_input("结束期号", value=current_year_end(), key="onboard_end")
        if st.button("开始抓取", key="onboard_crawl"):
            U.run_crawl(db, start, end, source="auto", only_missing=True)

    st.caption("提示：期号支持 2025001 与 25001 两种写法；数据来源为 500 彩票网，失败时自动切换福彩官网。")
