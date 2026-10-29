"""期号工具：统一 7 位期号 ``YYYYNNN``，兼容 5 位简写。"""

from __future__ import annotations

import re
from datetime import date
from typing import Iterator

EARLIEST_YEAR = 2003  # 双色球 2003 年上市
PERIOD_LEN = 7
_SHORT_LEN = 5
_DIGITS = re.compile(r"\d+")


class PeriodError(ValueError):
    """期号格式非法。"""


def normalize_period(value: object) -> str:
    """把各种写法的期号统一成 7 位 ``YYYYNNN``。

    支持 ``26123`` / ``2026123`` / ``2026-123`` / ``2026 123`` / ``26123.0``。
    """
    if value is None:
        raise PeriodError("期号不能为空")

    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            raise PeriodError(f"期号格式不正确：{value}")
        digits = str(int(value))
    else:
        text = str(value).strip()
        if not text:
            raise PeriodError("期号不能为空")
        groups = _DIGITS.findall(text)
        if not groups:
            raise PeriodError(f"期号格式不正确：{value}")
        digits = "".join(groups)

    if len(digits) == _SHORT_LEN:
        digits = "20" + digits
    if len(digits) != PERIOD_LEN:
        raise PeriodError(f"期号应为 5 位或 7 位数字：{value}")

    year, seq = int(digits[:4]), int(digits[4:])
    if year < EARLIEST_YEAR or year > date.today().year + 1:
        raise PeriodError(f"期号年份超出范围（{EARLIEST_YEAR} 年至今）：{value}")
    if seq < 1 or seq > 999:
        raise PeriodError(f"期号序号应在 001~999 之间：{value}")
    return f"{year}{seq:03d}"


def try_normalize_period(value: object) -> str | None:
    try:
        return normalize_period(value)
    except PeriodError:
        return None


def to_short_period(period: str) -> str:
    """7 位期号转 500.com 需要的 5 位写法。"""
    return normalize_period(period)[2:]


def period_year(period: str) -> int:
    return int(normalize_period(period)[:4])


def period_seq(period: str) -> int:
    return int(normalize_period(period)[4:])


def next_period(period: str) -> str:
    """下一期期号（序号进位到下一年）。"""
    year, seq = period_year(period), period_seq(period)
    if seq >= 999:
        return f"{year + 1}001"
    return f"{year}{seq + 1:03d}"


def iter_year_chunks(start: str, end: str) -> Iterator[tuple[str, str]]:
    """按自然年切分区间，便于分片抓取与进度展示。"""
    start, end = normalize_period(start), normalize_period(end)
    if start > end:
        raise PeriodError("起始期号不能大于结束期号")

    year = period_year(start)
    cursor = start
    while cursor <= end:
        year_end = min(f"{year}999", end)
        yield cursor, year_end
        year += 1
        cursor = f"{year}001"


def current_year_end() -> str:
    """当前年份的“最大可能期号”，用作增量抓取的右边界。"""
    return f"{date.today().year}999"


def latest_known_default() -> str:
    """数据库为空时的默认起点：最近一个完整年份。"""
    return f"{date.today().year - 1}001"


def pretty(period: str) -> str:
    """展示用：``2026123`` → ``2026-123``。"""
    p = normalize_period(period)
    return f"{p[:4]}-{p[4:]}"
