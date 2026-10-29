"""概览页：最新一期、期号查询、近期开奖、频率速览。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import analytics as A
from .. import charts as C
from ..crawler.periods import pretty, try_normalize_period
from ..db import Database
from . import common as U


def render(db: Database, data: pd.DataFrame) -> None:
    stats = db.stats()
    latest = data.iloc[-1]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("数据库总期数", f"{stats.count:,}")
    col2.metric("当前范围期数", f"{len(data):,}")
    col3.metric("红球和值均值", f"{data['sum_value'].mean():.1f}")
    col4.metric("跨度均值", f"{data['span'].mean():.1f}")

    st.write("")
    left, right = st.columns([1.55, 1], gap="large")
    with left:
        st.markdown(U.draw_card(latest, "最新一期"), unsafe_allow_html=True)
    with right:
        _lookup(db)

    st.write("")
    head, action = st.columns([3, 1], vertical_alignment="center")
    with head:
        st.markdown('<div class="ssq-section">近期开奖</div>', unsafe_allow_html=True)
    with action:
        with st.container(horizontal_alignment="right"):
            U.export_button(
                data, key="export_overview", compact=True, show_range=False
            )
    st.markdown(U.draws_list_html(data, limit=10), unsafe_allow_html=True)

    st.write("")
    st.markdown('<div class="ssq-section">号码频率速览</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="ssq-hint">基于当前范围 {len(data)} 期统计，虚线为理论均值</div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2, gap="large")
    with left:
        U.show_fig(C.frequency_bar(A.frequency_table(data, "red"), "red", "红球出现次数"))
    with right:
        U.show_fig(C.frequency_bar(A.frequency_table(data, "blue"), "blue", "蓝球出现次数"))


def _lookup(db: Database) -> None:
    """按期号精确查询。"""
    st.markdown('<div class="ssq-section">期号查询</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ssq-hint">支持 2026123 或 26123 两种写法</div>', unsafe_allow_html=True
    )
    with st.form("lookup_form", border=False):
        raw = st.text_input("期号", placeholder="如 2026123", label_visibility="collapsed")
        submitted = st.form_submit_button("查询", width="stretch")

    if submitted:
        period = try_normalize_period(raw)
        if period is None:
            st.session_state.pop("lookup_period", None)
            st.warning("期号格式不正确")
        elif db.get_draw(period) is None:
            st.session_state["lookup_period"] = period
            st.warning(f"库中没有 {pretty(period)}，可到「数据管理」抓取")
        else:
            st.session_state["lookup_period"] = period

    period = st.session_state.get("lookup_period")
    if not period:
        return

    frame = U.load_draws(start=period, end=period)
    if frame.empty:
        return
    row = A.prepare(frame).iloc[-1]
    st.markdown(U.draw_card(row), unsafe_allow_html=True)

    first_count, first_amount = row.get("first_count"), row.get("first_amount")
    second_count, second_amount = row.get("second_count"), row.get("second_amount")
    if pd.notna(first_count) and pd.notna(first_amount):
        st.caption(
            f"一等奖 {int(first_count)} 注 / {first_amount / 1e4:,.0f} 万元　"
            f"二等奖 {int(second_count or 0)} 注 / {(second_amount or 0) / 1e4:,.0f} 万元"
        )
