"""数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable


@dataclass(frozen=True, slots=True)
class DrawRecord:
    """一期开奖记录（号码已校验、升序）。"""

    period: str
    draw_date: date
    reds: tuple[int, ...]
    blue: int
    pool_amount: int | None = None
    sales_amount: int | None = None
    first_count: int | None = None
    first_amount: int | None = None
    second_count: int | None = None
    second_amount: int | None = None
    source: str = ""

    def to_row(self) -> tuple:
        """转为数据库写入顺序的元组（不含时间戳）。"""
        return (
            self.period,
            self.draw_date.isoformat(),
            *self.reds,
            self.blue,
            self.pool_amount,
            self.sales_amount,
            self.first_count,
            self.first_amount,
            self.second_count,
            self.second_amount,
            self.source,
        )

    def comparable(self) -> tuple:
        """用于判断内容是否变化的字段集合（不含期号与数据来源）。"""
        return self.to_row()[1:-1]


@dataclass(slots=True)
class UpsertResult:
    """批量写入结果。"""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0  # 因“仅补缺失”而跳过的已存在期号

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged + self.skipped


@dataclass(slots=True)
class CrawlReport:
    """一次抓取任务的汇总。"""

    start: str
    end: str
    source: str = ""
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    invalid: int = 0
    chunks_ok: int = 0
    chunks_failed: int = 0
    duration: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.chunks_failed == 0

    @property
    def written(self) -> int:
        return self.inserted + self.updated

    def summary(self) -> str:
        parts = [
            f"区间 {self.start} ~ {self.end}",
            f"抓取 {self.fetched} 期",
            f"新增 {self.inserted}",
            f"更新 {self.updated}",
            f"未变 {self.unchanged}",
        ]
        if self.skipped:
            parts.append(f"跳过已存在 {self.skipped}")
        if self.invalid:
            parts.append(f"无效行 {self.invalid}")
        if self.chunks_failed:
            parts.append(f"失败分片 {self.chunks_failed}")
        parts.append(f"耗时 {self.duration:.1f}s")
        return "｜".join(parts)


def dedupe(records: Iterable[DrawRecord]) -> list[DrawRecord]:
    """按期号去重（后出现的覆盖先出现的），并按期号升序返回。"""
    mapping: dict[str, DrawRecord] = {}
    for record in records:
        mapping[record.period] = record
    return [mapping[key] for key in sorted(mapping)]
