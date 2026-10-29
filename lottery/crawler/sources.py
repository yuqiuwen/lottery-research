"""数据源：500 彩票网（原项目逻辑）与福彩官网 JSON 接口。"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Protocol, runtime_checkable

import requests
from lxml import etree

from .. import config
from ..models import DrawRecord
from .periods import normalize_period, to_short_period

logger = logging.getLogger(__name__)


class FetchError(RuntimeError):
    """抓取失败（网络、状态码或解析异常）。"""


def _clean(text: str) -> str:
    return text.replace("\xa0", " ").replace("\u3000", " ").strip()


def _to_int(value: object) -> int | None:
    """``"2,712,273,374"`` → ``2712273374``；空值/``&nbsp;`` → ``None``。"""
    if value is None:
        return None
    text = _clean(str(value)).replace(",", "").replace(" ", "")
    if text in {"", "-", "--", "0"}:
        return 0 if text == "0" else None
    try:
        return int(float(text))
    except ValueError:
        return None


def _build_record(
    period_raw: object,
    reds_raw: list[object],
    blue_raw: object,
    date_raw: object,
    *,
    source: str,
    pool_amount: int | None = None,
    sales_amount: int | None = None,
    first_count: int | None = None,
    first_amount: int | None = None,
    second_count: int | None = None,
    second_amount: int | None = None,
) -> DrawRecord:
    """校验并构造记录，非法数据抛 ``ValueError``。"""
    period = normalize_period(period_raw)
    reds = sorted(_to_int(item) for item in reds_raw)
    if len(reds) != 6 or any(r is None for r in reds):
        raise ValueError(f"{period} 红球数量或格式异常")
    if len(set(reds)) != 6:
        raise ValueError(f"{period} 红球重复")
    if not all(config.RED_MIN <= r <= config.RED_MAX for r in reds):
        raise ValueError(f"{period} 红球超出 1~33")

    blue = _to_int(blue_raw)
    if blue is None or not (config.BLUE_MIN <= blue <= config.BLUE_MAX):
        raise ValueError(f"{period} 蓝球异常")

    if isinstance(date_raw, date):
        draw_date = date_raw
    else:
        text = _clean(str(date_raw))[:10]
        try:
            draw_date = datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(f"{period} 开奖日期异常：{date_raw}") from exc

    return DrawRecord(
        period=period,
        draw_date=draw_date,
        reds=tuple(reds),
        blue=blue,
        pool_amount=pool_amount,
        sales_amount=sales_amount,
        first_count=first_count,
        first_amount=first_amount,
        second_count=second_count,
        second_amount=second_amount,
        source=source,
    )


@runtime_checkable
class Source(Protocol):
    name: str
    label: str

    def fetch(self, start: str, end: str) -> list[DrawRecord]:
        """抓取 ``[start, end]`` 区间的全部开奖记录（升序）。"""


class _HttpSource:
    """带重试的 HTTP 基类。"""

    name = "base"
    label = "基础数据源"

    def __init__(self, timeout: int = config.REQUEST_TIMEOUT, retries: int = config.REQUEST_RETRIES):
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.USER_AGENT})

    def _get(self, url: str, **kwargs) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout, **kwargs)
                if response.status_code >= 500:
                    raise FetchError(f"服务端返回 {response.status_code}")
                response.raise_for_status()
                return response
            except (requests.RequestException, FetchError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1.0 + attempt)
        raise FetchError(f"{self.label} 请求失败：{last_error}")


class Cwl500Source(_HttpSource):
    """500 彩票网历史开奖页（沿用原项目解析方式）。"""

    name = "500"
    label = "500彩票网"
    URL = "https://datachart.500.com/ssq/history/newinc/history.php"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session.headers.update({"Referer": "https://datachart.500.com/ssq/history/history.shtml"})

    def fetch(self, start: str, end: str) -> list[DrawRecord]:
        start, end = normalize_period(start), normalize_period(end)
        params = {"start": to_short_period(start), "end": to_short_period(end)}
        response = self._get(self.URL, params=params)
        html_text = response.content.decode("utf-8", errors="ignore")
        tree = etree.HTML(html_text)
        if tree is None:
            raise FetchError("500彩票网返回内容无法解析")

        rows = tree.xpath("//tbody[@id='tdata']/tr[@class='t_tr1']")
        records: list[DrawRecord] = []
        for row in rows:
            cells = [_clean("".join(td.itertext())) for td in row.xpath("./td")]
            if len(cells) < 9:
                continue
            # 右侧固定列：… 一等奖注数, 一等奖奖金, 二等奖注数, 二等奖奖金, 总投注额, 开奖日期
            try:
                record = _build_record(
                    cells[0],
                    cells[1:7],
                    cells[7],
                    cells[-1],
                    source=self.name,
                    pool_amount=_to_int(cells[-7]) if len(cells) >= 15 else None,
                    first_count=_to_int(cells[-6]) if len(cells) >= 15 else None,
                    first_amount=_to_int(cells[-5]) if len(cells) >= 15 else None,
                    second_count=_to_int(cells[-4]) if len(cells) >= 15 else None,
                    second_amount=_to_int(cells[-3]) if len(cells) >= 15 else None,
                    sales_amount=_to_int(cells[-2]) if len(cells) >= 15 else None,
                )
            except ValueError as exc:
                logger.debug("跳过无效行：%s", exc)
                continue
            records.append(record)

        if not records:
            logger.info("500彩票网 %s~%s 无数据", start, end)
        return sorted(records, key=lambda r: r.period)


class OfficialSource(_HttpSource):
    """中国福利彩票官网开奖公告 JSON 接口。"""

    name = "cwl"
    label = "福彩官网"
    URL = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
    PAGE_SIZE = 100
    MAX_PAGES = 80

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session.headers.update(
            {
                "Referer": "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            }
        )

    def fetch(self, start: str, end: str) -> list[DrawRecord]:
        start, end = normalize_period(start), normalize_period(end)
        records: list[DrawRecord] = []
        page = 1
        total_pages = 1
        while page <= min(total_pages, self.MAX_PAGES):
            payload = self._get(
                self.URL,
                params={
                    "name": "ssq",
                    "issueStart": start,
                    "issueEnd": end,
                    "pageNo": page,
                    "pageSize": self.PAGE_SIZE,
                    "systemType": "PC",
                },
            ).json()
            if payload.get("state") not in (0, "0"):
                raise FetchError(f"福彩官网返回异常：{payload.get('message')}")
            total_pages = int(payload.get("pageNum") or 1)
            items = payload.get("result") or []
            if not items:
                break
            for item in items:
                try:
                    records.append(self._parse(item))
                except (ValueError, TypeError) as exc:
                    logger.debug("跳过无效行：%s", exc)
            page += 1
        return sorted(records, key=lambda r: r.period)

    def _parse(self, item: dict) -> DrawRecord:
        prizes = {int(p.get("type", 0)): p for p in item.get("prizegrades") or []}
        first, second = prizes.get(1, {}), prizes.get(2, {})
        return _build_record(
            item["code"],
            str(item["red"]).split(","),
            item["blue"],
            str(item["date"])[:10],
            source=self.name,
            pool_amount=_to_int(item.get("poolmoney")),
            sales_amount=_to_int(item.get("sales")),
            first_count=_to_int(first.get("typenum")),
            first_amount=_to_int(first.get("typemoney")),
            second_count=_to_int(second.get("typenum")),
            second_amount=_to_int(second.get("typemoney")),
        )


SOURCE_REGISTRY: dict[str, type[_HttpSource]] = {
    Cwl500Source.name: Cwl500Source,
    OfficialSource.name: OfficialSource,
}

SOURCE_LABELS: dict[str, str] = {
    "auto": "自动（500彩票网优先，失败切福彩官网）",
    Cwl500Source.name: Cwl500Source.label,
    OfficialSource.name: OfficialSource.label,
}


def build_sources(choice: str = "auto") -> list[Source]:
    """按选择构造数据源列表；``auto`` 返回带兜底的链。"""
    if choice == "auto":
        return [Cwl500Source(), OfficialSource()]
    if choice not in SOURCE_REGISTRY:
        raise ValueError(f"未知数据源：{choice}")
    return [SOURCE_REGISTRY[choice]()]
