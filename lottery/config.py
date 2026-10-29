"""全局配置。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def _load_dotenv(path: Path) -> None:
    """极简 .env 读取（不引依赖）：``KEY=VALUE``，支持 ``#`` 注释与引号。

    已存在的环境变量优先，不会被文件覆盖；文件不存在则静默跳过。
    """
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw in raw_lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _read_setting(name: str) -> str:
    """读取配置项：环境变量 / .env 优先，Streamlit 进程里再回退到 ``st.secrets``。

    Streamlit Community Cloud 的 Secrets 面板配的是 ``st.secrets``，根级键虽然也会
    注入环境变量，但注入时机不一定早于本模块 import，所以这里显式兜一层。
    非 Streamlit 进程（CLI）不会去 import streamlit，避免拖慢命令行。
    """
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    if "streamlit" in sys.modules:
        try:
            import streamlit as st

            return str(st.secrets.get(name) or "").strip()
        except Exception:
            return ""
    return ""


_load_dotenv(PROJECT_ROOT / ".env")

# 可用环境变量 LOTTERY_DB_PATH 指向其他数据库文件（便于测试或部署到别处）
DB_PATH = Path(_read_setting("LOTTERY_DB_PATH") or (DATA_DIR / "lottery.db"))

APP_TITLE = "双色球数据分析平台"
APP_ICON = "🎯"

# 「数据管理」页的访问口令：**只从环境变量注入，代码里不留任何默认值**。
# 可用 export、也可写进项目根目录的 .env（已在 .gitignore 中忽略）；
# 部署到 Streamlit Cloud 时写在 Secrets 面板（根级键，会同时成为环境变量）。
# 未配置时管理页不可达，入口只提示如何配置。
ADMIN_PASSWORD_ENV = "LOTTERY_ADMIN_PASSWORD"
ADMIN_PASSWORD = _read_setting(ADMIN_PASSWORD_ENV)
ADMIN_PASSWORD_CONFIGURED = bool(ADMIN_PASSWORD)

# 视觉规范：红球红、蓝球蓝
RED_COLOR = "#d94a4a"
BLUE_COLOR = "#2f6fd0"
NEUTRAL_COLOR = "#9ca3af"
ACCENT_COLOR = "#f59e0b"

# 双色球规则
RED_MIN, RED_MAX, RED_COUNT = 1, 33, 6
BLUE_MIN, BLUE_MAX = 1, 16
RED_COLUMNS = ["red1", "red2", "red3", "red4", "red5", "red6"]

# 抓取参数
REQUEST_TIMEOUT = 30
REQUEST_RETRIES = 2
CHUNK_DELAY = 0.35  # 分片之间的礼貌间隔（秒）
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
