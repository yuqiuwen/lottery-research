"""数据管理页：抓取、查询、导出、清理。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import analytics as A
from .. import config
from ..crawler.periods import current_year_end, next_period, pretty, try_normalize_period
from ..crawler.sources import SOURCE_LABELS
from ..db import Database
from . import common as U


def render(db: Database, data: pd.DataFrame) -> None:
    stats = db.stats()

    U.render_last_report()

    U.section("抓取开奖数据", "按期号区间抓取，写入时以「期号」为主键自动去重；重复抓取不会产生重复记录")
    default_start = next_period(stats.max_period) if stats.max_period else "2003001"
    default_end = current_year_end()

    col1, col2, col3 = st.columns([1, 1, 1.4])
    start_raw = col1.text_input("起始期号", value=default_start, key="crawl_start")
    end_raw = col2.text_input("结束期号", value=default_end, key="crawl_end")
    source = col3.selectbox(
        "数据源",
        options=list(SOURCE_LABELS),
        format_func=lambda key: SOURCE_LABELS[key],
        index=0,
        key="crawl_source",
    )
    only_missing = st.checkbox(
        "仅补缺失期号（已存在的期号跳过，不覆盖）", value=True, key="crawl_only_missing"
    )

    b1, b2, b3, b4 = st.columns(4)
    if b1.button("抓取区间", type="primary", width="stretch"):
        U.run_crawl(db, start_raw, end_raw, source=source, only_missing=only_missing)
    if b2.button("增量抓取最新", width="stretch"):
        U.run_crawl(db, default_start, current_year_end(), source=source, only_missing=True)
    if b3.button("抓取最近 100 期", width="stretch"):
        U.run_recent(db, 100, source=source)
    if b4.button("抓取全部历史", width="stretch"):
        U.run_crawl(db, "2003001", current_year_end(), source=source, only_missing=True)

    st.caption(
        f"建议：首次使用可点「抓取全部历史」（2003 年至今约 3400 期，按年份分片请求）；"
        f"日常点「增量抓取最新」即可。当前库内 {stats.count} 期。"
    )

    st.write("")
    U.section("数据库状态")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("总期数", f"{stats.count:,}")
    m2.metric("最早期号", pretty(stats.min_period) if stats.min_period else "—")
    m3.metric("最晚期号", pretty(stats.max_period) if stats.max_period else "—")
    m4.metric("数据库大小", f"{stats.size_bytes / 1024:.0f} KB")
    st.caption(f"数据文件：`{config.DB_PATH}`　最后更新：{(stats.last_updated or '—').replace('T', ' ')}")

    with st.expander("抓取日志（最近 15 次）", expanded=False):
        runs = db.recent_runs(15)
        if runs.empty:
            st.info("暂无抓取记录")
        else:
            st.dataframe(
                runs.rename(
                    columns={
                        "id": "ID",
                        "started_at": "开始时间",
                        "range_start": "起始期号",
                        "range_end": "结束期号",
                        "source": "数据源",
                        "fetched": "抓取",
                        "inserted": "新增",
                        "updated": "更新",
                        "unchanged": "未变",
                        "skipped": "跳过",
                        "chunks_failed": "失败分片",
                        "duration": "耗时(s)",
                        "status": "状态",
                        "message": "错误信息",
                    }
                ).drop(columns=["finished_at"], errors="ignore"),
                hide_index=True,
                width="stretch",
            )

    st.write("")
    U.section("数据查询与导出", "支持按期号区间、开奖日期筛选，导出为 UTF-8 BOM 编码的 CSV（Excel 直接打开不乱码）")
    _query_panel(db, data)

    st.write("")
    with st.expander("删除指定期号区间的数据", expanded=False):
        st.warning("删除后需重新抓取才能恢复，请谨慎操作。")
        c1, c2 = st.columns(2)
        del_start = c1.text_input("起始期号", key="del_start", placeholder="如 2026001")
        del_end = c2.text_input("结束期号", key="del_end", placeholder="如 2026010")
        confirm = st.checkbox("我确认删除该区间的数据", key="del_confirm")
        if st.button("执行删除", disabled=not confirm, key="del_button"):
            start, end = try_normalize_period(del_start), try_normalize_period(del_end)
            if start is None or end is None or start > end:
                st.error("期号格式不正确，或起始期号大于结束期号")
            else:
                removed = db.delete_range(start, end)
                U.refresh_data()
                st.success(f"已删除 {removed} 条记录（{start} ~ {end}）")
                st.rerun()


def _query_panel(db: Database, data: pd.DataFrame) -> None:
    mode = st.radio(
        "筛选方式", ["期号区间", "开奖日期", "全部"], horizontal=True, key="query_mode"
    )

    frame = data
    if mode == "期号区间":
        stats = db.stats()
        c1, c2 = st.columns(2)
        start_raw = c1.text_input("起始期号", value=stats.min_period or "", key="q_start")
        end_raw = c2.text_input("结束期号", value=stats.max_period or "", key="q_end")
        start, end = try_normalize_period(start_raw), try_normalize_period(end_raw)
        if start is None or end is None or start > end:
            st.error("期号格式不正确，或起始期号大于结束期号")
            return
        frame = U.load_draws(start=start, end=end)
        frame = A.prepare(frame) if not frame.empty else frame
    elif mode == "开奖日期":
        stats = db.stats()
        min_date = pd.to_datetime(stats.min_date).date() if stats.min_date else None
        max_date = pd.to_datetime(stats.max_date).date() if stats.max_date else None
        picked = st.date_input("日期范围", value=(min_date, max_date), key="q_dates")
        if isinstance(picked, tuple) and len(picked) == 2:
            frame = U.load_draws(date_from=picked[0].isoformat(), date_to=picked[1].isoformat())
            frame = A.prepare(frame) if not frame.empty else frame

    if frame.empty:
        st.info("没有符合条件的数据")
        return

    st.caption(f"共 {len(frame)} 期，{pretty(str(frame['period'].iloc[0]))} ~ {pretty(str(frame['period'].iloc[-1]))}")
    st.dataframe(
        U.pretty_periods(A.export_frame(frame).iloc[::-1]),
        hide_index=True,
        width="stretch",
        height=420,
    )
    U.export_button(frame, key="export_query", label="导出查询结果 CSV")
