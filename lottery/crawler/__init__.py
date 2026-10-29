"""数据抓取层。"""

from .periods import (
    PeriodError,
    normalize_period,
    to_short_period,
    try_normalize_period,
)
from .service import CrawlerService
from .sources import (
    SOURCE_LABELS,
    Cwl500Source,
    FetchError,
    OfficialSource,
    Source,
    build_sources,
)

__all__ = [
    "CrawlerService",
    "Cwl500Source",
    "FetchError",
    "OfficialSource",
    "PeriodError",
    "SOURCE_LABELS",
    "Source",
    "build_sources",
    "normalize_period",
    "to_short_period",
    "try_normalize_period",
]
