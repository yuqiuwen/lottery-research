"""爬虫服务：分片抓取、去重入库、记录任务日志。"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Callable

from ..db import Database
from ..models import CrawlReport, DrawRecord, dedupe
from .periods import (
    current_year_end,
    iter_year_chunks,
    next_period,
    normalize_period,
)
from .sources import FetchError, Source, build_sources

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]


class CrawlerService:
    """把数据源 + 数据库串起来的抓取服务。

    设计要点：

    * 按期分片请求，既能给出进度，也避免单次响应过大；
    * ``draws.period`` 是主键，配合 ``ON CONFLICT`` 写入，天然不会重复；
    * 支持“仅补缺失”，增量更新时跳过已有期号，减少无谓写入；
    * 数据源可自动兜底（500 彩票网失败时切福彩官网）。
    """

    def __init__(
        self,
        db: Database,
        source: str = "auto",
        *,
        delay: float = 0.35,
        chunk_by_year: bool = True,
    ):
        self.db = db
        self.source_choice = source
        self.delay = delay
        self.chunk_by_year = chunk_by_year
        self._sources: list[Source] = build_sources(source)

    # ------------------------------------------------------------------ 对外
    def crawl(
        self,
        start: str,
        end: str,
        *,
        only_missing: bool = False,
        progress: ProgressCallback | None = None,
        tail: int | None = None,
    ) -> CrawlReport:
        """抓取 ``[start, end]`` 区间并入库；``tail`` 只保留最近的 N 期。"""
        start, end = normalize_period(start), normalize_period(end)
        if start > end:
            raise ValueError("起始期号不能大于结束期号")

        chunks = list(iter_year_chunks(start, end)) if self.chunk_by_year else [(start, end)]
        report = CrawlReport(start=start, end=end, source=self.source_choice)
        started_at = datetime.now()
        collected: list[DrawRecord] = []

        try:
            for index, (chunk_start, chunk_end) in enumerate(chunks, start=1):
                if progress:
                    progress(
                        (index - 1) / len(chunks),
                        f"正在抓取 {chunk_start} ~ {chunk_end}（{index}/{len(chunks)}）",
                    )
                records = self._fetch_chunk(chunk_start, chunk_end, report)
                collected.extend(records)
                if self.delay and index < len(chunks):
                    time.sleep(self.delay)

            unique = [r for r in dedupe(collected) if start <= r.period <= end]
            if tail:
                unique = unique[-tail:]
            report.fetched = len(unique)

            result = self.db.upsert_draws(unique, only_missing=only_missing)
            report.inserted = result.inserted
            report.updated = result.updated
            report.unchanged = result.unchanged
            report.skipped = result.skipped
        finally:
            report.duration = (datetime.now() - started_at).total_seconds()
            self.db.log_run(report, started_at=started_at)
            if progress:
                progress(1.0, f"完成：{report.summary()}")

        return report

    def crawl_latest(self, *, only_missing: bool = True, progress: ProgressCallback | None = None) -> CrawlReport:
        """从库内最新一期的下一期抓到当前年份末尾。"""
        stats = self.db.stats()
        start = next_period(stats.max_period) if stats.max_period else "2003001"
        end = current_year_end()
        if start > end:
            report = CrawlReport(start=start, end=end, source=self.source_choice)
            return report
        return self.crawl(start, end, only_missing=only_missing, progress=progress)

    def crawl_all(self, *, progress: ProgressCallback | None = None) -> CrawlReport:
        """抓取 2003 年至今的全部历史。"""
        return self.crawl("2003001", current_year_end(), only_missing=True, progress=progress)

    def crawl_recent(
        self, count: int = 100, *, only_missing: bool = True, progress: ProgressCallback | None = None
    ) -> CrawlReport:
        """抓取最近 ``count`` 期（自动回溯到上一年的起点）。"""
        from datetime import date

        start = f"{date.today().year - 1}001"
        return self.crawl(
            start, current_year_end(), only_missing=only_missing, progress=progress, tail=count
        )

    # ------------------------------------------------------------------ 内部
    def _fetch_chunk(self, start: str, end: str, report: CrawlReport) -> list[DrawRecord]:
        errors: list[str] = []
        for source in self._sources:
            try:
                records = source.fetch(start, end)
            except FetchError as exc:
                logger.warning("%s 抓取 %s~%s 失败：%s", source.label, start, end, exc)
                errors.append(f"{source.label}({start}-{end}): {exc}")
                continue
            except Exception as exc:  # 解析等未预期异常，同样兜底
                logger.exception("%s 解析异常", source.label)
                errors.append(f"{source.label}({start}-{end}): {exc}")
                continue

            report.chunks_ok += 1
            if errors:
                report.errors.extend(errors)
            return records

        report.chunks_failed += 1
        report.errors.extend(errors or [f"{start}-{end}: 无可用数据源"])
        return []
