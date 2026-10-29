"""只读数据接口层。

给 CLI、AI Skill（以及未来的 MCP server）复用的纯函数集合：

- 输入普通参数，输出可直接 JSON 序列化的 dict（统一信封结构）
- 只读，不写数据库，不依赖 Streamlit
- 每个结果都带 ``columns`` 说明字段含义，调用方不必猜字段

信封结构::

    {
      "ok": true,
      "title": "最近 20 期",
      "meta": {"count": 20, "total": 3520, "truncated": true, ...},
      "columns": [{"key": "period", "label": "期号", "type": "string"}],
      "rows": [{...}]
    }

聚合类结果（``shape`` / ``overview`` / ``schema``）用 ``data`` 字段代替 ``rows``。
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from . import analytics as A
from . import config
from .crawler.periods import PeriodError, normalize_period
from .db import Database

VERSION = "1"
MAX_LIMIT = 500
DEFAULT_LIMIT = 20


# ---------------------------------------------------------------- 异常
class ApiError(Exception):
    """接口层异常，``code`` 直接作为进程退出码。"""

    code = 4


class BadRequest(ApiError):
    """参数不合法。"""

    code = 2


class NotFound(ApiError):
    """数据不存在。"""

    code = 3


# ---------------------------------------------------------------- 字段说明
COLUMNS: dict[str, dict[str, str]] = {
    # 开奖记录
    "period": {"label": "期号", "type": "string", "desc": "7 位期号 YYYYNNN，如 2026123"},
    "draw_date": {"label": "开奖日期", "type": "date", "desc": "ISO 日期 YYYY-MM-DD"},
    "reds": {"label": "红球", "type": "integer[]", "desc": "6 个升序红球，取值 1-33"},
    "blue": {"label": "蓝球", "type": "integer", "desc": "取值 1-16"},
    "sum_value": {"label": "和值", "type": "integer", "desc": "6 个红球之和，范围 21-183，理论均值 102"},
    "span": {"label": "跨度", "type": "integer", "desc": "最大红球减最小红球，范围 5-32"},
    "odd_count": {"label": "奇数个数", "type": "integer", "desc": "红球中奇数的数量，0-6"},
    "even_count": {"label": "偶数个数", "type": "integer", "desc": "红球中偶数的数量"},
    "big_count": {"label": "大数个数", "type": "integer", "desc": "红球中 >=17 的数量"},
    "small_count": {"label": "小数个数", "type": "integer", "desc": "红球中 <=16 的数量"},
    "zone1": {"label": "一区个数", "type": "integer", "desc": "落在 1-11 的红球个数"},
    "zone2": {"label": "二区个数", "type": "integer", "desc": "落在 12-22 的红球个数"},
    "zone3": {"label": "三区个数", "type": "integer", "desc": "落在 23-33 的红球个数"},
    "consecutive": {"label": "最大连号长度", "type": "integer", "desc": "最长连续自然数串长度，至少 1"},
    "ac_value": {"label": "AC值", "type": "integer", "desc": "红球两两差值去重个数减 5，越大越分散"},
    "repeat_count": {"label": "重号个数", "type": "integer", "desc": "与上一期重复的红球个数"},
    "odd_even_ratio": {"label": "奇偶比", "type": "string", "desc": "如 3:3"},
    "first_count": {"label": "一等奖注数", "type": "integer", "desc": "当期一等奖中奖注数"},
    "first_amount": {"label": "一等奖单注金额", "type": "integer", "desc": "单位：元"},
    "second_count": {"label": "二等奖注数", "type": "integer", "desc": "当期二等奖中奖注数"},
    "second_amount": {"label": "二等奖单注金额", "type": "integer", "desc": "单位：元"},
    "pool_amount": {"label": "奖池金额", "type": "integer", "desc": "单位：元"},
    "sales_amount": {"label": "销售额", "type": "integer", "desc": "单位：元"},
    "source": {"label": "数据来源", "type": "string", "desc": "500 或 cwl"},
    # 号码统计
    "number": {"label": "号码", "type": "integer", "desc": "红球 1-33 或蓝球 1-16"},
    "count": {"label": "出现次数", "type": "integer", "desc": "在统计范围内出现的总次数"},
    "ratio": {"label": "出现率%", "type": "number", "desc": "出现次数 / 期数 * 100"},
    "expected": {"label": "理论次数", "type": "number", "desc": "按均匀分布应有的出现次数"},
    "deviation": {"label": "偏差", "type": "number", "desc": "实际次数减理论次数，正为偏热"},
    "rank": {"label": "排名", "type": "integer", "desc": "按出现次数降序，1 为最多"},
    "current": {"label": "当前遗漏", "type": "integer", "desc": "距最近一次出现的间隔期数，0 表示上期刚出"},
    "max_gap": {"label": "最大遗漏", "type": "integer", "desc": "历史最长未出现间隔"},
    "avg_gap": {"label": "平均遗漏", "type": "number", "desc": "平均多少期出现一次"},
    "last_period": {"label": "最近出现期号", "type": "string", "desc": "该号码最后一次出现的期号"},
    "appearances": {"label": "出现期数", "type": "integer", "desc": "该号码出现过的期数"},
    "count_all": {"label": "全样本次数", "type": "integer", "desc": "整个统计范围内的出现次数"},
    "count_recent": {"label": "近期次数", "type": "integer", "desc": "最近 N 期内的出现次数"},
    "ratio_all": {"label": "全样本出现率%", "type": "number", "desc": "整个范围内的出现率"},
    "ratio_recent": {"label": "近期出现率%", "type": "number", "desc": "最近 N 期内的出现率"},
    "delta": {"label": "冷热差", "type": "number", "desc": "近期出现率减全样本出现率，正为偏热"},
    "state": {"label": "状态", "type": "string", "desc": "热（差>=3）/ 温 / 冷（差<=-3）"},
    "zone": {"label": "区间", "type": "string", "desc": "一区 1-11 / 二区 12-22 / 三区 23-33"},
    "ratio_label": {"label": "比值", "type": "string", "desc": "如 奇:偶 3:3 或 大:小 2:4"},
    "pct": {"label": "占比%", "type": "number", "desc": "该类期数占总期数的百分比"},
    "value": {"label": "取值", "type": "integer", "desc": "统计指标的取值"},
    "range_label": {"label": "区间", "type": "string", "desc": "分箱区间，如 90-99"},
}

# 各类结果的字段顺序
DRAW_KEYS = ["period", "draw_date", "reds", "blue"]
DRAW_FEATURE_KEYS = [
    "sum_value",
    "span",
    "odd_count",
    "big_count",
    "zone1",
    "zone2",
    "zone3",
    "consecutive",
    "ac_value",
    "repeat_count",
]
DRAW_PRIZE_KEYS = [
    "first_count",
    "first_amount",
    "second_count",
    "second_amount",
    "pool_amount",
    "sales_amount",
]
FREQUENCY_KEYS = ["number", "count", "ratio", "expected", "deviation", "rank"]
OMISSION_KEYS = ["number", "current", "max_gap", "avg_gap", "last_period", "appearances"]
HOT_COLD_KEYS = [
    "number",
    "count_all",
    "count_recent",
    "ratio_all",
    "ratio_recent",
    "delta",
    "state",
]

FIELD_DIGITS = {
    "ratio": 2,
    "pct": 2,
    "expected": 1,
    "deviation": 1,
    "avg_gap": 2,
    "ratio_all": 2,
    "ratio_recent": 2,
    "delta": 2,
    "mean": 1,
    "median": 1,
    "std": 1,
}


# ---------------------------------------------------------------- 序列化
def _clean(value: Any, key: str = "") -> Any:
    """把 pandas / numpy 值转成 JSON 友好类型。"""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return round(number, FIELD_DIGITS.get(key, 4))
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_clean(item) for item in value]
    if isinstance(value, str):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _record(row: dict, keys: Sequence[str]) -> dict:
    record: dict[str, Any] = {}
    for key in keys:
        if key == "reds":
            record["reds"] = [int(row[column]) for column in config.RED_COLUMNS]
        else:
            record[key] = _clean(row.get(key), key)
    return record


def _records(frame: pd.DataFrame, keys: Sequence[str]) -> list[dict]:
    if frame is None or frame.empty:
        return []
    return [_record(row, keys) for row in frame.to_dict("records")]


def _columns(keys: Iterable[str]) -> list[dict]:
    out = []
    for key in keys:
        spec = COLUMNS.get(key, {"label": key, "type": "string", "desc": ""})
        out.append({"key": key, "label": spec["label"], "type": spec["type"]})
    return out


def envelope(
    title: str,
    *,
    rows: list[dict] | None = None,
    keys: Sequence[str] = (),
    data: dict | None = None,
    meta: dict | None = None,
) -> dict:
    """构造统一信封。"""
    payload: dict[str, Any] = {"ok": True, "title": title}

    merged: dict[str, Any] = {}
    if rows is not None:
        merged["count"] = len(rows)
    merged.update(meta or {})
    merged.setdefault("generated_at", datetime.now().isoformat(timespec="seconds"))
    payload["meta"] = merged

    if rows is not None:
        payload["columns"] = _columns(keys)
        payload["rows"] = rows
    if data is not None:
        payload["data"] = data
    return payload


def error_envelope(message: str, *, kind: str = "error") -> dict:
    return {
        "ok": False,
        "error": {"type": kind, "message": message},
        "meta": {"generated_at": datetime.now().isoformat(timespec="seconds")},
    }


# ---------------------------------------------------------------- 取数
def _norm(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        return normalize_period(value)
    except PeriodError as exc:
        raise BadRequest(str(exc)) from exc


def _load(
    db: Database,
    *,
    start: Any = None,
    end: Any = None,
    date_from: Any = None,
    date_to: Any = None,
    window: int | None = None,
) -> pd.DataFrame:
    """按区间 / 最近 N 期取数，并补齐形态字段。"""
    begin, finish = _norm(start), _norm(end)
    if begin and finish and begin > finish:
        raise BadRequest("起始期号不能大于结束期号")

    if window is not None:
        window = int(window)
        if window < 1:
            raise BadRequest("window 必须为正整数")
        window = min(window, MAX_LIMIT * 4)

    frame = db.load_draws(
        start=begin,
        end=finish,
        date_from=date_from,
        date_to=date_to,
        limit=window,
    )
    if frame.empty:
        return frame
    return A.prepare(frame)


def _range_of(frame: pd.DataFrame) -> list[str] | None:
    if frame.empty:
        return None
    return [str(frame["period"].iloc[0]), str(frame["period"].iloc[-1])]


def _db_meta(db: Database) -> dict:
    stats = db.stats()
    return {"db_total": stats.count, "db_range": [stats.min_period, stats.max_period]}


def _range_meta(frame: pd.DataFrame, db: Database, **extra: Any) -> dict:
    meta: dict[str, Any] = {
        "draws": len(frame),
        "range": _range_of(frame),
    }
    for key, value in extra.items():
        if value is not None:  # 不输出空参数，减少噪声
            meta[key] = value
    meta.update(_db_meta(db))
    return meta


# ---------------------------------------------------------------- 查询
def query(
    db: Database,
    *,
    start: Any = None,
    end: Any = None,
    date_from: Any = None,
    date_to: Any = None,
    limit: int = DEFAULT_LIMIT,
    order: str = "asc",
    fields: Sequence[str] | None = None,
    features: bool = True,
    prize: bool = False,
) -> dict:
    """按区间查询开奖记录，``limit`` 截取区间内**最近**的 N 期。"""
    frame = _load(db, start=start, end=end, date_from=date_from, date_to=date_to)

    if fields:
        unknown = [name for name in fields if name not in COLUMNS]
        if unknown:
            raise BadRequest(f"未知字段：{', '.join(unknown)}")
        keys = list(fields)
    else:
        keys = list(DRAW_KEYS)
        if features:
            keys += DRAW_FEATURE_KEYS
        if prize:
            keys += DRAW_PRIZE_KEYS

    total = len(frame)
    selected_range = _range_of(frame)
    limit = max(1, min(int(limit), MAX_LIMIT))
    truncated = total > limit
    if truncated:
        frame = frame.tail(limit)
    if order == "desc":
        frame = frame.iloc[::-1]

    title = f"开奖记录（{total} 期" + (f"，返回最近 {len(frame)} 期）" if truncated else "）")
    return envelope(
        title,
        rows=_records(frame, keys),
        keys=keys,
        meta=_range_meta(
            frame,
            db,
            total=total,
            truncated=truncated,
            order=order,
            limit=limit,
            requested_range=selected_range,
        ),
    )


def draw(db: Database, period: Any) -> dict:
    """单期详情。"""
    code = _norm(period)
    if code is None:
        raise BadRequest("期号不能为空")

    # 多取一期，保证 repeat_count（与上期重号）算得出来
    frame = db.load_draws(end=code, limit=2)
    if frame.empty or code not in set(frame["period"]):
        stats = db.stats()
        raise NotFound(
            f"库中没有 {code}（当前库范围 {stats.min_period} ~ {stats.max_period}）"
        )

    frame = A.prepare(frame)
    frame = frame[frame["period"] == code].reset_index(drop=True)
    keys = DRAW_KEYS + DRAW_FEATURE_KEYS + DRAW_PRIZE_KEYS + ["source"]
    return envelope(
        f"{code} 开奖详情",
        rows=_records(frame, keys),
        keys=keys,
        meta=_db_meta(db),
    )


# ---------------------------------------------------------------- 统计
def analyze_frequency(
    db: Database,
    *,
    color: str = "red",
    start: Any = None,
    end: Any = None,
    window: int | None = None,
    top: int | None = None,
) -> dict:
    """号码出现频率。"""
    color = _color(color)
    frame = _load(db, start=start, end=end, window=window)
    if frame.empty:
        raise NotFound("指定范围内没有数据")

    table = A.frequency_table(frame, color)
    table = table.sort_values(["count", "number"], ascending=[False, True])
    if top:
        table = table.head(max(1, int(top)))
    table = table.reset_index(drop=True)

    scope = "红球" if color == "red" else "蓝球"
    return envelope(
        f"{scope}出现频率（{len(frame)} 期）",
        rows=_records(table, FREQUENCY_KEYS),
        keys=FREQUENCY_KEYS,
        meta=_range_meta(
            frame,
            db,
            color=color,
            window=window,
            theoretical={"expected": _clean(table["expected"].iloc[0], "expected")},
        ),
    )


def analyze_omission(
    db: Database,
    *,
    color: str = "red",
    start: Any = None,
    end: Any = None,
    window: int | None = None,
    top: int | None = None,
) -> dict:
    """当前遗漏、最大遗漏、平均遗漏。"""
    color = _color(color)
    frame = _load(db, start=start, end=end, window=window)
    if frame.empty:
        raise NotFound("指定范围内没有数据")

    table = A.omission_table(frame, color)
    table = table.sort_values(["current", "max_gap"], ascending=[False, False])
    if top:
        table = table.head(max(1, int(top)))
    table = table.reset_index(drop=True)

    scope = "红球" if color == "red" else "蓝球"
    return envelope(
        f"{scope}遗漏（{len(frame)} 期）",
        rows=_records(table, OMISSION_KEYS),
        keys=OMISSION_KEYS,
        meta=_range_meta(frame, db, color=color, window=window),
    )


def analyze_hot_cold(
    db: Database,
    *,
    color: str = "red",
    window: int = 30,
    start: Any = None,
    end: Any = None,
    top: int | None = None,
) -> dict:
    """近期窗口与全样本出现率对比。"""
    color = _color(color)
    frame = _load(db, start=start, end=end)
    if frame.empty:
        raise NotFound("指定范围内没有数据")

    size = max(1, min(int(window), len(frame)))
    table = A.hot_cold_table(frame, size, color)
    table = table.sort_values(["delta", "number"], ascending=[False, True])
    if top:
        table = table.head(max(1, int(top)))
    table = table.reset_index(drop=True)

    scope = "红球" if color == "red" else "蓝球"
    return envelope(
        f"{scope}冷热对比（近 {size} 期 vs 全样本）",
        rows=_records(table, HOT_COLD_KEYS),
        keys=HOT_COLD_KEYS,
        meta=_range_meta(frame, db, color=color, window=size),
    )


def analyze_shape(
    db: Database,
    *,
    start: Any = None,
    end: Any = None,
    window: int | None = None,
) -> dict:
    """形态分布：和值、跨度、奇偶、大小、三区、连号、AC 值、重号。"""
    frame = _load(db, start=start, end=end, window=window)
    if frame.empty:
        raise NotFound("指定范围内没有数据")

    data = {
        "sum_value": _profile(frame["sum_value"], "和值"),
        "span": _profile(frame["span"], "跨度"),
        "odd_count": _profile(frame["odd_count"], "奇数个数"),
        "big_count": _profile(frame["big_count"], "大数个数"),
        "consecutive": _profile(frame["consecutive"], "最大连号长度"),
        "ac_value": _profile(frame["ac_value"], "AC值"),
        "repeat_count": _profile(frame["repeat_count"], "重号个数"),
        "zone": _records(A.zone_summary(frame), ["zone", "count", "ratio"]),
        "odd_even": _records(A.odd_even_summary(frame), ["ratio_label", "count", "pct"]),
        "big_small": _records(A.big_small_summary(frame), ["ratio_label", "count", "pct"]),
    }
    return envelope(
        f"形态分布（{len(frame)} 期）",
        data=data,
        meta=_range_meta(frame, db, window=window),
    )


def analyze_overview(
    db: Database,
    *,
    start: Any = None,
    end: Any = None,
    window: int | None = None,
) -> dict:
    """一段区间的整体画像：最新一期、与上期对比、各指标均值、结构占比。"""
    frame = _load(db, start=start, end=end, window=window)
    if frame.empty:
        raise NotFound("指定范围内没有数据")

    keys = DRAW_KEYS + DRAW_FEATURE_KEYS
    latest = _records(frame.tail(1), keys)[0]
    previous = _records(frame.tail(2).head(1), keys)[0] if len(frame) >= 2 else None

    data = {
        "latest": latest,
        "previous": previous,
        "compare": _clean_compare(A.compare_with_previous(frame)),
        "metrics": {
            column: _summary(frame[column])
            for column in (
                "sum_value",
                "span",
                "odd_count",
                "big_count",
                "consecutive",
                "ac_value",
                "repeat_count",
            )
        },
        "zone": _records(A.zone_summary(frame), ["zone", "count", "ratio"]),
        "odd_even": _records(A.odd_even_summary(frame), ["ratio_label", "count", "pct"]),
        "big_small": _records(A.big_small_summary(frame), ["ratio_label", "count", "pct"]),
    }
    return envelope(
        f"数据概览（{len(frame)} 期）",
        data=data,
        meta=_range_meta(frame, db, window=window),
    )


def stats(db: Database) -> dict:
    """数据库状态。"""
    info = db.stats()
    data = {
        "count": info.count,
        "min_period": info.min_period,
        "max_period": info.max_period,
        "min_date": info.min_date,
        "max_date": info.max_date,
        "last_updated": info.last_updated,
        "size_kb": round(info.size_bytes / 1024, 1),
    }
    return envelope("数据库状态", data=data, meta={"generated_at": _now()})


# ---------------------------------------------------------------- 辅助
def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _color(color: str) -> str:
    value = (color or "red").lower()
    if value in {"red", "r", "红", "红球"}:
        return "red"
    if value in {"blue", "b", "蓝", "蓝球"}:
        return "blue"
    raise BadRequest(f"color 只能是 red 或 blue，收到：{color}")


def _summary(series: pd.Series) -> dict:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return {}
    return {
        "mean": _clean(float(values.mean()), "mean"),
        "median": _clean(float(values.median()), "median"),
        "std": _clean(float(values.std(ddof=0)), "std"),
        "min": int(values.min()),
        "max": int(values.max()),
        "p10": _clean(float(values.quantile(0.10))),
        "p25": _clean(float(values.quantile(0.25))),
        "p75": _clean(float(values.quantile(0.75))),
        "p90": _clean(float(values.quantile(0.90))),
    }


def _profile(series: pd.Series, label: str, buckets: int = 24) -> dict:
    """数值指标：统计量 + 分布（取值少时给精确值，多时给分箱）。"""
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return {"label": label, "count": 0}
    unique = int(values.nunique())
    result = {"label": label, "count": int(values.size), **_summary(values)}
    if unique <= buckets:
        counts = values.value_counts().sort_index()
        result["distribution"] = [
            {"value": int(value), "count": int(count)} for value, count in counts.items()
        ]
        result["binned"] = False
    else:
        result["distribution"] = _binned(values, buckets)
        result["binned"] = True
    return result


def _binned(values: pd.Series, buckets: int) -> list[dict]:
    counts, edges = np.histogram(values.to_numpy(), bins=buckets)
    out = []
    for count, low, high in zip(counts, edges[:-1], edges[1:]):
        out.append(
            {"range_label": f"{int(round(low))}-{int(round(high))}", "count": int(count)}
        )
    return out


def _clean_compare(compare: dict) -> dict:
    if not compare:
        return {}
    return {
        "repeat_reds": [int(n) for n in compare.get("repeat", [])],
        "sum_delta": int(compare.get("sum_delta", 0)),
        "span_delta": int(compare.get("span_delta", 0)),
    }


# ---------------------------------------------------------------- 自描述
def schema() -> dict:
    """接口自描述：命令清单、字段字典、约定。AI 第一步应当调用它。"""
    commands = [
        {
            "name": "schema",
            "usage": "python -m lottery.cli schema",
            "args": [],
            "returns": "data.commands / data.columns / data.conventions",
            "when": "第一次使用或不确定字段含义时先调用",
        },
        {
            "name": "stats",
            "usage": "python -m lottery.cli stats",
            "args": [],
            "returns": "data: count / min_period / max_period / min_date / max_date",
            "when": "确认库里有多少数据、最新到哪一期",
        },
        {
            "name": "query",
            "usage": "python -m lottery.cli query [--start 2026001] [--end 2026123] [--limit 20] [--order desc]",
            "args": ["start", "end", "date_from", "date_to", "limit(默认20,上限500)", "order(asc/desc)", "fields", "features", "prize"],
            "returns": "rows: 每期一条，含 reds 数组与形态字段",
            "when": "需要原始开奖记录、看具体某几期、或自己做小样本推理",
        },
        {
            "name": "draw",
            "usage": "python -m lottery.cli draw 2026123",
            "args": ["period"],
            "returns": "rows: 单期全部字段（含奖金、奖池）",
            "when": "用户问某一期的具体号码与奖金",
        },
        {
            "name": "analyze frequency",
            "usage": "python -m lottery.cli analyze frequency --color red --top 10",
            "args": ["color(red/blue)", "top", "start", "end", "window"],
            "returns": "rows: number / count / ratio / expected / deviation / rank",
            "when": "问哪些号码出现最多/最少、是否偏离理论值",
        },
        {
            "name": "analyze omission",
            "usage": "python -m lottery.cli analyze omission --color red --top 10",
            "args": ["color", "top", "start", "end", "window"],
            "returns": "rows: number / current / max_gap / avg_gap / last_period",
            "when": "问遗漏、多久没出、是否该回补",
        },
        {
            "name": "analyze hot-cold",
            "usage": "python -m lottery.cli analyze hot-cold --window 50 --top 10",
            "args": ["color", "window(默认30)", "top", "start", "end"],
            "returns": "rows: ratio_all / ratio_recent / delta / state(热/温/冷)",
            "when": "问近期冷热、与历史对比",
        },
        {
            "name": "analyze shape",
            "usage": "python -m lottery.cli analyze shape --window 100",
            "args": ["window", "start", "end"],
            "returns": "data: 和值/跨度/奇偶/大小/三区/连号/AC值/重号 的统计量与分布",
            "when": "问形态规律、和值范围、奇偶比、连号、AC 值",
        },
        {
            "name": "analyze overview",
            "usage": "python -m lottery.cli analyze overview --window 100",
            "args": ["window", "start", "end"],
            "returns": "data: latest / previous / compare / metrics / zone / odd_even / big_small",
            "when": "需要一段数据的整体画像，一次拿到最新一期和各项均值",
        },
    ]

    conventions = {
        "period": "统一 7 位 YYYYNNN；入参也接受 26123 / 2026-123 等写法",
        "range": "start/end 为闭区间；window 表示在区间内只看最近 N 期",
        "limit": f"默认 {DEFAULT_LIMIT}，上限 {MAX_LIMIT}；截断时 meta.truncated=true 且 meta.total 为真实总数",
        "rows_vs_data": "表格类结果在 rows（配 columns），聚合类结果在 data",
        "stdout": "stdout 只有 JSON，日志走 stderr，可直接 json.loads",
        "numbers": "红球以 reds 数组返回（升序），蓝球为 blue 标量",
        "no_write": "所有命令只读，不会修改数据库",
        "exit_codes": "0 成功；2 参数错误；3 数据不存在；4 其他错误",
        "compute": "统计量一律由本接口计算，不要让模型自己数；模型只负责解读",
    }

    return envelope(
        "双色球只读数据接口",
        data={
            "version": VERSION,
            "commands": commands,
            "conventions": conventions,
            "columns": {
                key: {"label": spec["label"], "type": spec["type"], "desc": spec["desc"]}
                for key, spec in COLUMNS.items()
            },
        },
    )
