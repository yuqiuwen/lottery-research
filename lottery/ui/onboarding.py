"""首次使用引导：数据库为空时的落地页。"""

from __future__ import annotations

import streamlit as st

from .. import config, snapshot
from ..crawler.periods import current_year_end
from ..db import Database
from . import common as U


def _render_read_only() -> None:
    """只读部署（如 Streamlit Community Cloud）且快照没装载成功时的说明页。"""
    info = snapshot.describe()
    if info["exists"]:
        state = f"存在 · {info['rows']:,} 期 · {info['size_kb']} KB"
    else:
        state = "缺失"
    st.warning(
        "当前是**只读部署**，数据库为空，且没有找到可用的 CSV 快照，所以没有任何数据可看。"
    )
    st.markdown(
        f"""
**这个部署的数据来自仓库里的 CSV 快照**，容器启动时自动装载进临时 SQLite，
因此页面无法自己抓取。请检查：

1. `{info['path']}` 是否已提交到仓库（本地用 `python -m lottery.cli export` 生成）；
2. 部署的 Secrets 里是否误设了 `LOTTERY_READ_ONLY=0`；
3. 若快照刚更新，重启应用（Manage app → Reboot）让它重新装载。

快照状态：**{state}**
        """
    )
    st.caption("数据更新由仓库的定时任务负责，不需要在这个页面操作。")


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

    if config.READ_ONLY:
        _render_read_only()
        return

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
