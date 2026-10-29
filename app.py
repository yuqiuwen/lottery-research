"""双色球数据分析平台 —— Streamlit 入口。

启动：streamlit run app.py
"""

from __future__ import annotations

import hashlib
import hmac

import streamlit as st

from lottery import config
from lottery.ui import common as U
from lottery.ui import data_manage, numbers, onboarding, overview, patterns, trend

ADMIN_PAGE = "数据管理"

# 刷新页面后仍记住解锁状态：把口令派生的令牌写进 cookie（7 天）
_ADMIN_COOKIE = "ssq_admin"
_ADMIN_COOKIE_MAX_AGE = 7 * 24 * 3600

PAGES = [
    ("数据概览", "最新开奖、期号精确查询与号码频率速览", overview.render),
    ("号码分析", "红蓝球出现频率、遗漏值与冷热对比", numbers.render),
    ("走势图", "号码点阵走势、和值与跨度曲线", trend.render),
    ("形态分析", "和值、奇偶、大小、三区、连号与 AC 值", patterns.render),
    (ADMIN_PAGE, "按期号区间抓取、查询、导出 CSV 与清理", data_manage.render),
]


def _admin_token() -> str:
    """由口令派生的令牌：口令一改，旧 cookie 自动失效。"""
    return hmac.new(
        config.ADMIN_PASSWORD.encode("utf-8"),
        b"ssq-admin-cookie-v1",
        hashlib.sha256,
    ).hexdigest()


def _cookie_token() -> str:
    """读取请求里携带的 cookie；测试环境没有请求上下文时返回空串。"""
    try:
        return (st.context.cookies or {}).get(_ADMIN_COOKIE) or ""
    except Exception:
        return ""


def _write_cookie(value: str, max_age: int) -> None:
    """用一段内联脚本写 cookie（Streamlit 没有服务端下发 cookie 的接口）。"""
    st.iframe(
        "<script>document.cookie="
        f"'{_ADMIN_COOKIE}={value}; path=/; max-age={max_age}; SameSite=Lax';"
        "</script>",
        height=1,
    )


def _flush_cookie_action() -> None:
    """处理上一次交互留下的 cookie 动作（解锁写入 / 锁定清除）。"""
    action = st.session_state.pop("admin_cookie_action", None)
    if action == "set":
        _write_cookie(_admin_token(), _ADMIN_COOKIE_MAX_AGE)
    elif action == "clear":
        _write_cookie("", 0)


def _admin_unlocked() -> bool:
    # 没配置口令时永远视为锁定，避免任何绕过
    if not config.ADMIN_PASSWORD_CONFIGURED:
        return False
    if st.session_state.get("admin_unlocked"):
        return True
    saved = _cookie_token()
    if saved and hmac.compare_digest(saved, _admin_token()):
        st.session_state["admin_unlocked"] = True
        return True
    return False


def _admin_gate() -> None:
    """侧边栏右下角的管理入口。口令正确后「数据管理」才会出现在导航里。"""
    with st.sidebar:
        with st.container(key="admin_dock", horizontal_alignment="right"):
            if not config.ADMIN_PASSWORD_CONFIGURED:
                with st.popover("⋯", type="tertiary", help="管理入口未启用"):
                    st.caption("管理入口未启用")
                    st.caption(
                        f"请设置环境变量 `{config.ADMIN_PASSWORD_ENV}`（或写进项目根目录的 "
                        f"`.env`）后重启应用。"
                    )
                return

            if _admin_unlocked():
                with st.popover("⋯", type="tertiary", help="管理模式已解锁"):
                    st.caption("🔓 管理模式已解锁")
                    if st.button("锁定并退出", key="admin_lock", width="stretch"):
                        st.session_state["admin_unlocked"] = False
                        st.session_state["admin_cookie_action"] = "clear"
                        st.rerun()
                    st.caption("锁定后会同时清掉本机记住的凭证。")
                return

            with st.popover("⋯", type="tertiary", help="管理入口"):
                with st.form("admin_login", border=False):
                    typed = st.text_input(
                        "管理密码",
                        type="password",
                        key="admin_pwd",
                        label_visibility="collapsed",
                        placeholder="输入密码解锁「数据管理」",
                    )
                    submitted = st.form_submit_button("解锁", type="primary", width="stretch")
                st.caption("解锁后 7 天内免验证（凭证存在本机 cookie）。")
                if submitted:
                    given = (typed or "").strip()
                    if hmac.compare_digest(
                        given.encode("utf-8"), config.ADMIN_PASSWORD.encode("utf-8")
                    ):
                        st.session_state["admin_unlocked"] = True
                        st.session_state["admin_cookie_action"] = "set"
                        st.rerun()
                    else:
                        st.error("密码不正确")


def main() -> None:
    st.set_page_config(
        page_title=config.APP_TITLE,
        page_icon=config.APP_ICON,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    U.inject_css()
    _flush_cookie_action()

    db = U.get_db()

    with st.sidebar:
        st.markdown("## 🎯 双色球分析")

    if db.stats().is_empty:
        onboarding.render(db)
        return

    unlocked = _admin_unlocked()
    visible = [page for page in PAGES if page[0] != ADMIN_PAGE or unlocked]

    with st.sidebar:
        names = [page[0] for page in visible]
        # 解锁前后用不同 key：锁定瞬间即使停在管理页，也会干净地退回默认页
        nav_key = "nav_admin" if unlocked else "nav"
        if st.session_state.get(nav_key) not in names:  # 兜掉旧会话里残留的「数据管理」
            st.session_state[nav_key] = names[0]
        choice = st.radio(
            "导航",
            names,
            label_visibility="collapsed",
            key=nav_key,
        )
        st.divider()

    data = U.sidebar_filters(db)
    _admin_gate()

    page = next((item for item in PAGES if item[0] == choice), PAGES[0])
    if page[0] == ADMIN_PAGE and not unlocked:  # 兜底：未解锁时绝不渲染管理页
        page = PAGES[0]

    st.markdown(
        f'<div style="font-size:26px;font-weight:700;letter-spacing:-0.02em">{page[0]}</div>'
        f'<div class="ssq-hint" style="font-size:13px;margin:2px 0 14px">{page[1]}</div>',
        unsafe_allow_html=True,
    )

    if data.empty:
        st.warning("当前数据范围没有记录。请在侧边栏调整范围，或到「数据管理」抓取数据。")
        return

    page[2](db, data)


if __name__ == "__main__":
    main()
