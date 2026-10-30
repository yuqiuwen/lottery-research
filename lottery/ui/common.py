"""Streamlit 公共组件：数据加载、样式、球号渲染、导出。"""

from __future__ import annotations

import re
from datetime import date
from typing import Iterable

import pandas as pd
import streamlit as st

from .. import analytics as A
from .. import config, snapshot
from ..crawler.periods import PeriodError, normalize_period, pretty, try_normalize_period
from ..db import Database
from ..models import CrawlReport

PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}

# 手机 UA 粗判：Android 平板不带 "Mobile"，会被当成桌面（屏幕大，误触概率低，这样更合理）
_MOBILE_UA = re.compile(r"iPhone|iPod|Android.*Mobile|Windows Phone|IEMobile|BlackBerry", re.I)


# ---------------------------------------------------------------- 资源
@st.cache_resource(show_spinner=False)
def get_db() -> Database:
    """打开数据库；空库时先尝试从 CSV 快照装载（云端部署靠这一步拿到数据）。"""
    db = Database(config.DB_PATH).init_schema()
    snapshot.ensure_ready(db)
    return db


def persist_snapshot() -> None:
    """把当前数据同步到 CSV 快照。只读模式跳过；失败记到 session 里稍后提示。"""
    if config.READ_ONLY:
        return
    try:
        st.session_state["snapshot_rows"] = snapshot.export(get_db())
        st.session_state.pop("snapshot_error", None)
    except OSError as exc:
        st.session_state["snapshot_error"] = str(exc)


@st.cache_data(ttl=600, show_spinner=False)
def _query(
    version: str,
    start: str | None,
    end: str | None,
    date_from: str | None,
    date_to: str | None,
    limit: int | None,
) -> pd.DataFrame:
    return get_db().load_draws(
        start=start, end=end, date_from=date_from, date_to=date_to, limit=limit
    )


def load_draws(
    *,
    start: str | None = None,
    end: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """带缓存的读取，数据变更后自动失效。"""
    db = get_db()
    return _query(db.version_token(), start, end, date_from, date_to, limit)


def refresh_data() -> None:
    st.cache_data.clear()


# ---------------------------------------------------------------- 样式
_CSS = """
<style>
.block-container { padding-top: 2.4rem; padding-bottom: 3rem; max-width: 1360px; }
h1, h2, h3, h4 { letter-spacing: -0.01em; }
.ssq-hero {
    border: 1px solid #e8ebf0; border-radius: 16px; padding: 18px 22px; background: #fff;
    box-shadow: 0 1px 2px rgba(16,24,40,.04), 0 10px 30px -22px rgba(16,24,40,.35);
    margin-bottom: 4px;
}
.ssq-hero-top { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.ssq-period { font-size: 20px; font-weight: 700; color: #1f2937; letter-spacing: -0.02em; }
.ssq-date { font-size: 13px; color: #8a93a3; }
.ssq-balls { display: flex; gap: 9px; flex-wrap: wrap; align-items: center; margin: 14px 0 12px; }
.ssq-ball {
    display: inline-flex; align-items: center; justify-content: center; border-radius: 50%;
    color: #fff; font-weight: 650; letter-spacing: .3px;
    font-family: -apple-system, 'PingFang SC', 'Helvetica Neue', sans-serif;
    box-shadow: inset 0 -2px 6px rgba(0,0,0,.12), 0 2px 5px rgba(16,24,40,.16);
}
.ssq-ball.red { background: radial-gradient(circle at 32% 26%, #f48787, #c9373b 78%); }
.ssq-ball.blue { background: radial-gradient(circle at 32% 26%, #79aae9, #2358ad 78%); }
.ssq-meta { display: flex; gap: 22px; flex-wrap: wrap; font-size: 12.5px; color: #6b7280; }
.ssq-meta b { color: #374151; font-weight: 600; }
.ssq-list {
    border: 1px solid #eef1f5; border-radius: 14px; background: #fff;
    max-height: min(480px, 62vh); overflow-x: hidden; overflow-y: auto;
    scrollbar-width: thin;
}
.ssq-list::-webkit-scrollbar { width: 8px; }
.ssq-list::-webkit-scrollbar-thumb { background: #dfe3ea; border-radius: 999px; }
.ssq-list::-webkit-scrollbar-thumb:hover { background: #cfd5df; }
.ssq-list::-webkit-scrollbar-track { background: transparent; }
.ssq-row {
    display: flex; align-items: center; gap: 14px; padding: 9px 16px; border-bottom: 1px solid #f3f5f8;
    font-size: 13px;
}
.ssq-row:last-child { border-bottom: none; }
.ssq-row:hover { background: #fafbfc; }
.ssq-row .p { width: 74px; font-weight: 600; color: #374151; font-variant-numeric: tabular-nums; }
.ssq-row .d { width: 88px; color: #9aa1ad; font-variant-numeric: tabular-nums; }
.ssq-row .s { margin-left: auto; color: #9aa1ad; font-variant-numeric: tabular-nums; }
.ssq-tag {
    display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11.5px;
    background: #f3f5f8; color: #6b7280; margin-right: 6px;
}
.ssq-section { font-size: 15px; font-weight: 650; color: #1f2937; margin: 6px 0 2px; }
.ssq-hint { font-size: 12.5px; color: #98a0ac; margin-bottom: 8px; }
div[data-testid="stMetricValue"] { font-size: 24px; }
div[data-testid="stMetricLabel"] { font-size: 12.5px; color: #8a93a3; }
/* 窄屏：把纵向手势交还给浏览器，避免在图表上滑动时被 Plotly 抢走（PC 不受影响） */
@media (max-width: 768px) {
    .js-plotly-plot, .js-plotly-plot .nsewdrag,
    .js-plotly-plot .draglayer, .js-plotly-plot .plot-container {
        touch-action: pan-y !important;
    }
}
/* 侧边栏右下角的管理入口 */
.st-key-admin_dock { padding-top: 4px; }
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------- 球号
def balls_html(reds: Iterable[int], blue: int, size: int = 34) -> str:
    def ball(number: int, kind: str) -> str:
        font = int(size * 0.42)
        return (
            f'<span class="ssq-ball {kind}" style="width:{size}px;height:{size}px;font-size:{font}px">'
            f"{int(number):02d}</span>"
        )

    red_html = "".join(ball(n, "red") for n in reds)
    return f'<div class="ssq-balls">{red_html}{ball(blue, "blue")}</div>'


def draw_card(row: pd.Series, title: str = "") -> str:
    reds = [int(row[c]) for c in config.RED_COLUMNS]
    date_text = pd.to_datetime(row["draw_date"]).strftime("%Y-%m-%d")
    pool = row.get("pool_amount")
    sales = row.get("sales_amount")
    meta = [
        f"和值 <b>{int(row['sum_value'])}</b>",
        f"跨度 <b>{int(row['span'])}</b>",
        f"奇偶 <b>{int(row['odd_count'])}:{int(row['even_count'])}</b>",
    ]
    if pd.notna(pool):
        meta.append(f"奖池 <b>{pool / 1e8:.2f} 亿</b>")
    if pd.notna(sales):
        meta.append(f"销量 <b>{sales / 1e8:.2f} 亿</b>")
    head = f'<span class="ssq-tag">{title}</span>' if title else ""
    return (
        '<div class="ssq-hero">'
        '<div class="ssq-hero-top">'
        f'<span class="ssq-period">{head}{pretty(str(row["period"]))}</span>'
        f'<span class="ssq-date">{date_text}</span>'
        "</div>"
        f"{balls_html(reds, int(row['blue']))}"
        f'<div class="ssq-meta">{"".join(f"<span>{m}</span>" for m in meta)}</div>'
        "</div>"
    )


def draws_list_html(data: pd.DataFrame, limit: int = 10) -> str:
    rows = []
    for _, row in data.tail(limit).iloc[::-1].iterrows():
        reds = [int(row[c]) for c in config.RED_COLUMNS]
        rows.append(
            '<div class="ssq-row">'
            f'<span class="p">{pretty(str(row["period"]))}</span>'
            f'<span class="d">{pd.to_datetime(row["draw_date"]).strftime("%m-%d")}</span>'
            f"{balls_html(reds, int(row['blue']), size=26)}"
            f'<span class="s">和值 {int(row["sum_value"])}</span>'
            "</div>"
        )
    return '<div class="ssq-list">' + "".join(rows) + "</div>"


# ---------------------------------------------------------------- 图表
def is_small_screen() -> bool:
    """是否手机屏：按 User-Agent 粗判。

    Python 侧拿不到视口宽度（``st.context.headers`` 是 websocket 握手头，
    连 ``Sec-CH-UA-Mobile`` 都没有），只能看 UA 字符串。
    """
    try:
        ua = st.context.headers.get("User-Agent", "") or ""
    except Exception:  # 非 Streamlit 运行环境（脚本里 import）没有请求上下文
        return False
    return bool(_MOBILE_UA.search(ua))


def show_fig(fig) -> None:
    # 手机上关掉拖拽：Plotly 会把单指拖拽当成框选缩放，还会 preventDefault 吃掉页面滑动。
    # 桌面保留 zoom，框选放大密集图表时有用。CSS 里另有一条 touch-action 兜底。
    fig.update_layout(dragmode=False if is_small_screen() else "zoom")
    try:
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
    except TypeError:  # 兼容旧版 Streamlit
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)


def section(title: str, hint: str = "") -> None:
    st.markdown(f'<div class="ssq-section">{title}</div>', unsafe_allow_html=True)
    if hint:
        st.markdown(f'<div class="ssq-hint">{hint}</div>', unsafe_allow_html=True)


def slider_or_value(
    label: str,
    minimum: int,
    maximum: int,
    default: int,
    *,
    step: int = 10,
    key: str | None = None,
) -> int:
    """数据量不足以形成区间时退化为固定值（Streamlit 不允许 min == max）。"""
    if maximum <= minimum:
        return max(1, maximum)
    value = min(max(default, minimum), maximum)
    return st.slider(label, minimum, maximum, value, step=step, key=key)


# ---------------------------------------------------------------- 导出
def export_button(
    data: pd.DataFrame,
    *,
    key: str,
    label: str = "导出 CSV",
    compact: bool = False,
    filename: str | None = None,
    show_range: bool = True,
) -> None:
    """导出按钮，标签上直接标明本次导出的行数与期号范围。"""
    if data is None or data.empty:
        return

    has_period = "period" in data.columns
    if filename is None:
        if has_period:
            start, end = str(data["period"].iloc[0]), str(data["period"].iloc[-1])
            filename = f"双色球_{start}-{end}.csv"
        else:
            filename = "双色球_统计.csv"

    count = len(data)
    if has_period:
        span = f"{pretty(str(data['period'].iloc[0]))} ~ {pretty(str(data['period'].iloc[-1]))}"
        text = f"{label} · {count} 期（{span}）" if show_range else f"{label} · {count} 期"
        hint = f"导出 {count} 期：{span}。UTF-8 BOM 编码，Excel 直接打开不乱码。"
    else:
        text = f"{label} · {count} 行"
        hint = f"导出 {count} 行统计结果。"

    st.download_button(
        text,
        data=A.csv_bytes(data),
        file_name=filename,
        mime="text/csv",
        key=key,
        help=hint,
        width="stretch" if not compact else "content",
    )


def pretty_periods(frame: pd.DataFrame, column: str = "期号") -> pd.DataFrame:
    """展示用：把 7 位期号格式化为 ``2026-123``。"""
    if frame is None or frame.empty or column not in frame.columns:
        return frame
    out = frame.copy()
    out[column] = (
        out[column].astype(str).str.replace(r"^(\d{4})(\d{3})$", r"\1-\2", regex=True)
    )
    return out


# ---------------------------------------------------------------- 筛选器
RANGE_MODES = ["最近 N 期", "期号区间", "日期区间", "全部数据"]


def sidebar_filters(db: Database) -> pd.DataFrame:
    """侧边栏数据范围筛选，返回已整理的分析用 DataFrame。"""
    stats = db.stats()
    with st.sidebar:
        st.markdown("#### 数据范围")
        mode = st.radio(
            "范围",
            RANGE_MODES,
            index=0,
            label_visibility="collapsed",
            key="range_mode",
        )

        frame: pd.DataFrame
        if mode == "最近 N 期":
            upper = max(10, min(stats.count, 1000))
            if upper <= 10:
                count = stats.count
            else:
                count = st.slider("期数", 10, upper, min(100, upper), step=10, key="range_recent")
            frame = load_draws(limit=count)
        elif mode == "期号区间":
            tail = load_draws(limit=min(100, stats.count))
            default_start = str(tail["period"].iloc[0]) if not tail.empty else (stats.min_period or "")
            default_end = str(tail["period"].iloc[-1]) if not tail.empty else (stats.max_period or "")
            col_a, col_b = st.columns(2)
            start_raw = col_a.text_input("起始期号", value=default_start, key="range_start")
            end_raw = col_b.text_input("结束期号", value=default_end, key="range_end")
            start = try_normalize_period(start_raw)
            end = try_normalize_period(end_raw)
            if start is None or end is None:
                st.error("期号格式不正确，应形如 2026001 或 26001")
                frame = pd.DataFrame()
            elif start > end:
                st.error("起始期号不能大于结束期号")
                frame = pd.DataFrame()
            else:
                frame = load_draws(start=start, end=end)
        elif mode == "日期区间":
            min_date = pd.to_datetime(stats.min_date).date() if stats.min_date else date.today()
            max_date = pd.to_datetime(stats.max_date).date() if stats.max_date else date.today()
            picked = st.date_input(
                "开奖日期", value=(min_date, max_date), min_value=min_date, max_value=max_date, key="range_dates"
            )
            if isinstance(picked, tuple) and len(picked) == 2:
                frame = load_draws(date_from=picked[0].isoformat(), date_to=picked[1].isoformat())
            else:
                frame = load_draws(date_from=picked.isoformat(), date_to=picked.isoformat())
        else:
            frame = load_draws()

        if not frame.empty:
            span = f"{pretty(str(frame['period'].iloc[0]))} ~ {pretty(str(frame['period'].iloc[-1]))}"
            st.caption(f"共 **{len(frame)}** 期　{span}")
        else:
            st.caption("当前范围没有数据")

        st.divider()
        st.caption(f"数据库共 {stats.count} 期")
        if stats.last_updated:
            st.caption(f"最后更新 {stats.last_updated.replace('T', ' ')}")

    return A.prepare(frame)


# ---------------------------------------------------------------- 抓取交互
def _with_progress(worker) -> None:
    """执行抓取任务并展示进度条，成功后刷新页面。"""
    bar = st.progress(0.0, text="准备抓取…")

    def on_progress(ratio: float, message: str) -> None:
        bar.progress(min(max(ratio, 0.0), 1.0), text=message)

    try:
        report = worker(on_progress)
    except Exception as exc:  # 网络等异常不炸页面
        bar.empty()
        st.error(f"抓取失败：{exc}")
        return

    bar.empty()
    st.session_state["last_crawl"] = report
    persist_snapshot()
    refresh_data()
    st.rerun()


def run_crawl(
    db: Database,
    start: str,
    end: str,
    *,
    source: str = "auto",
    only_missing: bool = False,
) -> None:
    """按区间抓取。"""
    from ..crawler import CrawlerService

    try:
        start_n, end_n = normalize_period(start), normalize_period(end)
    except PeriodError as exc:
        st.error(str(exc))
        return
    if start_n > end_n:
        st.error("起始期号不能大于结束期号")
        return

    service = CrawlerService(db, source=source)
    _with_progress(
        lambda cb: service.crawl(start_n, end_n, only_missing=only_missing, progress=cb)
    )


def run_recent(db: Database, count: int = 100, *, source: str = "auto") -> None:
    """抓取最近 N 期。"""
    from ..crawler import CrawlerService

    service = CrawlerService(db, source=source)
    _with_progress(lambda cb: service.crawl_recent(count, progress=cb))


def render_last_report() -> None:
    """展示上一次抓取结果（跨 rerun 保留）。"""
    report: CrawlReport | None = st.session_state.get("last_crawl")
    if not report:
        return
    if report.chunks_failed and not report.fetched:
        st.error(f"抓取未成功：{report.summary()}")
    elif report.chunks_failed:
        st.warning(f"部分分片失败：{report.summary()}")
    else:
        st.success(f"抓取完成：{report.summary()}")
    if report.errors:
        with st.expander("查看失败详情", expanded=False):
            for error in report.errors[:20]:
                st.text(error)

    failure = st.session_state.pop("snapshot_error", None)
    if failure:
        st.warning(f"CSV 快照写入失败：{failure}")
    else:
        rows = st.session_state.pop("snapshot_rows", None)
        if rows:
            st.caption(f"已同步 CSV 快照：{rows:,} 期 → `{config.SNAPSHOT_PATH.name}`")
