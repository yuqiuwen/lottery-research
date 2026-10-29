"""SQLite 数据访问层。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import pandas as pd

from . import config
from .models import CrawlReport, DrawRecord, UpsertResult

DRAW_FIELDS = (
    "period",
    "draw_date",
    "red1",
    "red2",
    "red3",
    "red4",
    "red5",
    "red6",
    "blue",
    "pool_amount",
    "sales_amount",
    "first_count",
    "first_amount",
    "second_count",
    "second_amount",
    "source",
)

# 判断记录是否变化的字段（不含期号与数据来源）
_COMPARABLE = DRAW_FIELDS[1:15]

SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    period        TEXT PRIMARY KEY,
    draw_date     TEXT NOT NULL,
    red1          INTEGER NOT NULL,
    red2          INTEGER NOT NULL,
    red3          INTEGER NOT NULL,
    red4          INTEGER NOT NULL,
    red5          INTEGER NOT NULL,
    red6          INTEGER NOT NULL,
    blue          INTEGER NOT NULL,
    pool_amount   INTEGER,
    sales_amount  INTEGER,
    first_count   INTEGER,
    first_amount  INTEGER,
    second_count  INTEGER,
    second_amount INTEGER,
    source        TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_draws_date ON draws(draw_date);
CREATE INDEX IF NOT EXISTS idx_draws_year ON draws(substr(period, 1, 4));

CREATE TABLE IF NOT EXISTS crawl_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT NOT NULL,
    range_start   TEXT,
    range_end     TEXT,
    source        TEXT,
    fetched       INTEGER DEFAULT 0,
    inserted      INTEGER DEFAULT 0,
    updated       INTEGER DEFAULT 0,
    unchanged     INTEGER DEFAULT 0,
    skipped       INTEGER DEFAULT 0,
    chunks_failed INTEGER DEFAULT 0,
    duration      REAL DEFAULT 0,
    status        TEXT,
    message       TEXT
);
"""

_INSERT_SQL = f"""
INSERT INTO draws ({", ".join(DRAW_FIELDS)}, created_at, updated_at)
VALUES ({", ".join("?" * len(DRAW_FIELDS))}, ?, ?)
ON CONFLICT(period) DO UPDATE SET
{", ".join(f"{field} = excluded.{field}" for field in _COMPARABLE)},
    updated_at = excluded.updated_at
"""

_SELECT_SQL = f"SELECT {', '.join(DRAW_FIELDS)} FROM draws"


@dataclass(slots=True)
class DbStats:
    count: int = 0
    min_period: str | None = None
    max_period: str | None = None
    min_date: str | None = None
    max_date: str | None = None
    last_updated: str | None = None
    size_bytes: int = 0

    @property
    def is_empty(self) -> bool:
        return self.count == 0


class Database:
    """轻量 SQLite 封装：每次操作独立连接，避免线程问题。"""

    def __init__(self, path: str | Path = config.DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- 连接
    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> "Database":
        with self.connect() as conn:
            conn.executescript(SCHEMA)
        return self

    # ---------------------------------------------------------------- 写入
    def upsert_draws(self, records: Sequence[DrawRecord], *, only_missing: bool = False) -> UpsertResult:
        """写入开奖记录，``period`` 主键保证不重复。

        - 新期号 → 新增
        - 已存在且内容不同 → 更新
        - 已存在且内容相同 → 跳过（不改 ``updated_at``）
        - ``only_missing=True`` → 已存在的期号一律不动
        """
        result = UpsertResult()
        if not records:
            return result

        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            existing = self._existing_rows(conn, [r.period for r in records])
            payload: list[tuple] = []
            for record in records:
                current = existing.get(record.period)
                if current is None:
                    result.inserted += 1
                    payload.append((*record.to_row(), now, now))
                elif only_missing:
                    result.skipped += 1
                elif current == record.comparable():
                    result.unchanged += 1
                else:
                    result.updated += 1
                    payload.append((*record.to_row(), now, now))
            if payload:
                conn.executemany(_INSERT_SQL, payload)
        return result

    @staticmethod
    def _existing_rows(conn: sqlite3.Connection, periods: Iterable[str]) -> dict[str, tuple]:
        periods = list(periods)
        found: dict[str, tuple] = {}
        fields = ", ".join(_COMPARABLE)
        for offset in range(0, len(periods), 400):  # 规避 SQLite 变量上限
            batch = periods[offset : offset + 400]
            placeholders = ", ".join("?" * len(batch))
            rows = conn.execute(
                f"SELECT period, {fields} FROM draws WHERE period IN ({placeholders})", batch
            )
            for row in rows:
                found[row["period"]] = tuple(row[field] for field in _COMPARABLE)
        return found

    def delete_range(self, start: str, end: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM draws WHERE period BETWEEN ? AND ?", (start, end)
            )
            return cursor.rowcount

    # ---------------------------------------------------------------- 读取
    def load_draws(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int | None = None,
        ascending: bool = True,
    ) -> pd.DataFrame:
        clauses: list[str] = []
        params: list[object] = []
        if start:
            clauses.append("period >= ?")
            params.append(start)
        if end:
            clauses.append("period <= ?")
            params.append(end)
        if date_from:
            clauses.append("draw_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("draw_date <= ?")
            params.append(date_to)

        order = "ASC" if ascending else "DESC"
        sql = _SELECT_SQL
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        if limit:
            # limit 语义是“最近的 N 期”，因此先倒序截取，再按需排序
            sql += " ORDER BY period DESC LIMIT ?"
            params.append(int(limit))
        else:
            sql += f" ORDER BY period {order}"

        with self.connect() as conn:
            frame = pd.read_sql_query(sql, conn, params=params)
        return self._finalize(frame, ascending=ascending)

    def load_recent(self, limit: int = 100) -> pd.DataFrame:
        """最近 N 期（升序返回）。"""
        return self.load_draws(limit=limit)

    def get_draw(self, period: str) -> pd.Series | None:
        with self.connect() as conn:
            row = conn.execute(f"{_SELECT_SQL} WHERE period = ?", (period,)).fetchone()
        if row is None:
            return None
        return pd.Series(dict(row))

    @staticmethod
    def _finalize(frame: pd.DataFrame, *, ascending: bool = True) -> pd.DataFrame:
        if frame.empty:
            return frame
        frame["draw_date"] = pd.to_datetime(frame["draw_date"], errors="coerce")
        numeric = [c for c in DRAW_FIELDS if c not in {"period", "draw_date", "source"}]
        frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
        frame = frame.sort_values("period", ascending=ascending).reset_index(drop=True)
        return frame

    def stats(self) -> DbStats:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count,
                       MIN(period) AS min_period,
                       MAX(period) AS max_period,
                       MIN(draw_date) AS min_date,
                       MAX(draw_date) AS max_date,
                       MAX(updated_at) AS last_updated
                FROM draws
                """
            ).fetchone()
        size = self.path.stat().st_size if self.path.exists() else 0
        return DbStats(
            count=row["count"] or 0,
            min_period=row["min_period"],
            max_period=row["max_period"],
            min_date=row["min_date"],
            max_date=row["max_date"],
            last_updated=row["last_updated"],
            size_bytes=size,
        )

    def version_token(self) -> str:
        """数据版本号，用于前端缓存失效。"""
        stats = self.stats()
        return f"{stats.count}-{stats.last_updated}-{stats.max_period}"

    def periods(self) -> set[str]:
        with self.connect() as conn:
            return {row["period"] for row in conn.execute("SELECT period FROM draws")}

    # ---------------------------------------------------------------- 日志
    def log_run(self, report: CrawlReport, *, started_at: datetime) -> None:
        message = "；".join(report.errors[:5]) if report.errors else ""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO crawl_runs (started_at, finished_at, range_start, range_end, source,
                                        fetched, inserted, updated, unchanged, skipped,
                                        chunks_failed, duration, status, message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at.isoformat(timespec="seconds"),
                    datetime.now().isoformat(timespec="seconds"),
                    report.start,
                    report.end,
                    report.source,
                    report.fetched,
                    report.inserted,
                    report.updated,
                    report.unchanged,
                    report.skipped,
                    report.chunks_failed,
                    round(report.duration, 2),
                    "success" if report.ok else ("partial" if report.fetched else "failed"),
                    message,
                ),
            )

    def recent_runs(self, limit: int = 15) -> pd.DataFrame:
        with self.connect() as conn:
            frame = pd.read_sql_query(
                "SELECT * FROM crawl_runs ORDER BY id DESC LIMIT ?", conn, params=[limit]
            )
        return frame
