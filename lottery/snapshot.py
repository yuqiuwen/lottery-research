"""CSV 快照：把 draws 表导出成可提交进 git 的文本，空库时自动装载回来。

为什么需要它：Streamlit Community Cloud 这类环境没有持久磁盘，容器一重启就
回到仓库状态，写进去的数据全部消失。把数据以 CSV 形式放进仓库后——

- 云端读路径完全不变（启动时把 CSV 装进临时 SQLite）
- 数据历史留在 git 里，可回看、可回滚
- 写入留在本地（或由 GitHub Actions 跑完抓取后提交）

CSV 比直接提交 ``.db`` 好在两点：它是文本，追加一行就是一行 diff，仓库不会
随每次开奖膨胀；而且出问题时肉眼能看。
"""

from __future__ import annotations

import csv
from pathlib import Path

from . import config
from .db import DRAW_FIELDS, Database

# 比表结构多带 updated_at：恢复后「最后更新」显示的仍是真实抓取时间，
# 而不是导入那一刻。created_at 在恢复时取 updated_at 的值。
SNAPSHOT_FIELDS: tuple[str, ...] = (*DRAW_FIELDS, "updated_at")
_COLUMNS: tuple[str, ...] = (*SNAPSHOT_FIELDS, "created_at")

_TEXT_FIELDS = {"period", "draw_date", "source", "updated_at"}
_NUMERIC_FIELDS = [f for f in SNAPSHOT_FIELDS if f not in _TEXT_FIELDS]
_REQUIRED = ("period", "draw_date")

_INSERT_SQL = (
    f"INSERT OR IGNORE INTO draws ({', '.join(_COLUMNS)}) "
    f"VALUES ({', '.join('?' * len(_COLUMNS))})"
)
_REPLACE_SQL = (
    f"INSERT OR REPLACE INTO draws ({', '.join(_COLUMNS)}) "
    f"VALUES ({', '.join('?' * len(_COLUMNS))})"
)


def resolve_path(path: str | Path | None = None) -> Path:
    return Path(path or config.SNAPSHOT_PATH)


def _to_row(raw: dict[str, str]) -> tuple | None:
    """CSV 行 → 插入元组；缺关键字段的行跳过。"""
    values: list[object] = []
    for field in SNAPSHOT_FIELDS:
        text = (raw.get(field) or "").strip()
        if field in _TEXT_FIELDS:
            if field in _REQUIRED and not text:
                return None
            values.append(text or None)
        else:
            try:
                values.append(int(float(text)) if text else None)
            except ValueError:
                return None
    values.append(values[-1])  # created_at = updated_at
    return tuple(values)


# ---------------------------------------------------------------- 导出
def export(db: Database, path: str | Path | None = None) -> int:
    """把全部开奖记录写成 CSV，返回行数。先写临时文件再替换，避免半截文件。"""
    target = resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    sql = f"SELECT {', '.join(SNAPSHOT_FIELDS)} FROM draws ORDER BY period"

    with db.connect() as conn:
        rows = conn.execute(sql).fetchall()

    temp = target.with_name(target.name + ".tmp")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(SNAPSHOT_FIELDS)
        for row in rows:
            writer.writerow(["" if value is None else value for value in tuple(row)])
    temp.replace(target)
    return len(rows)


# ---------------------------------------------------------------- 恢复
def restore(
    db: Database, path: str | Path | None = None, *, overwrite: bool = False
) -> int:
    """把 CSV 装进数据库，返回新增（``overwrite`` 时含覆盖）的行数。"""
    source = resolve_path(path)
    if not source.exists():
        return 0

    with source.open(newline="", encoding="utf-8") as handle:
        payload = [row for row in (_to_row(raw) for raw in csv.DictReader(handle)) if row]
    if not payload:
        return 0

    with db.connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
        conn.executemany(_REPLACE_SQL if overwrite else _INSERT_SQL, payload)
        after = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    return after - before if not overwrite else len(payload)


def ensure_ready(db: Database, path: str | Path | None = None) -> str:
    """空库时从快照装载，供应用启动调用。

    返回 ``existing``（本来就有数据）/ ``restored``（已从快照装载）/
    ``missing``（既没数据也没快照，交给 onboarding 处理）。
    """
    if db.stats().count:
        return "existing"
    return "restored" if restore(db, path) else "missing"


def describe(path: str | Path | None = None) -> dict:
    """快照文件的基本信息，用于界面上说明「数据从哪来」。"""
    target = resolve_path(path)
    if not target.exists():
        return {"path": str(target), "exists": False, "rows": None, "size_kb": None}
    with target.open(encoding="utf-8") as handle:
        rows = max(0, sum(1 for _ in handle) - 1)  # 减掉表头
    return {
        "path": str(target),
        "exists": True,
        "rows": rows,
        "size_kb": round(target.stat().st_size / 1024, 1),
    }
