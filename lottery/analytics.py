"""指标计算：频率、遗漏、形态特征、冷热。"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from .config import BLUE_MAX, BLUE_MIN, RED_COLUMNS, RED_MAX, RED_MIN

BLUE_COLUMN = "blue"
BALL_COLUMNS = [*RED_COLUMNS, BLUE_COLUMN]
RED_NUMBERS = list(range(RED_MIN, RED_MAX + 1))
BLUE_NUMBERS = list(range(BLUE_MIN, BLUE_MAX + 1))
ZONES = (
    (1, 11, "一区 1-11", "zone1"),
    (12, 22, "二区 12-22", "zone2"),
    (23, 33, "三区 23-33", "zone3"),
)


# ---------------------------------------------------------------- 基础整理
def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    """补齐派生字段，按期号升序。"""
    if frame is None or frame.empty:
        return frame
    data = frame.copy()
    if not pd.api.types.is_datetime64_any_dtype(data["draw_date"]):
        data["draw_date"] = pd.to_datetime(data["draw_date"], errors="coerce")
    data = data.sort_values("period").reset_index(drop=True)
    return shape_features(data)


def shape_features(data: pd.DataFrame) -> pd.DataFrame:
    """红球形态：和值、跨度、奇偶、大小、三区、连号、AC 值、重号。"""
    if data.empty:
        return data
    data = data.copy()
    reds = data[RED_COLUMNS].to_numpy(dtype=int)

    data["sum_value"] = reds.sum(axis=1)
    data["span"] = reds.max(axis=1) - reds.min(axis=1)
    data["odd_count"] = (reds % 2 == 1).sum(axis=1)
    data["even_count"] = len(RED_COLUMNS) - data["odd_count"]
    data["big_count"] = (reds >= 17).sum(axis=1)
    data["small_count"] = len(RED_COLUMNS) - data["big_count"]
    for low, high, _label, key in ZONES:
        data[key] = ((reds >= low) & (reds <= high)).sum(axis=1)
    data["consecutive"] = [_max_run(row) for row in reds]
    data["ac_value"] = [_ac_value(row) for row in reds]
    data["repeat_count"] = _repeat_counts(reds)
    data["odd_even_ratio"] = data["odd_count"].astype(str) + ":" + data["even_count"].astype(str)
    return data


def _max_run(row: Iterable[int]) -> int:
    values = list(row)
    best = current = 1
    for previous, value in zip(values, values[1:]):
        if value - previous == 1:
            current += 1
            best = max(best, current)
        else:
            current = 1
    return best


def _ac_value(row: Iterable[int]) -> int:
    values = list(row)
    diffs = {
        values[j] - values[i]
        for i in range(len(values))
        for j in range(i + 1, len(values))
    }
    return len(diffs) - (len(values) - 1)


def _repeat_counts(reds: np.ndarray) -> list[int]:
    """与上一期重复的红球个数。"""
    counts = [0]
    for index in range(1, len(reds)):
        counts.append(len(set(reds[index]) & set(reds[index - 1])))
    return counts


# ---------------------------------------------------------------- 长表
def to_long(data: pd.DataFrame, color: str = "red") -> pd.DataFrame:
    """把宽表转成 ``(period, draw_date, number)`` 长表。"""
    columns = RED_COLUMNS if color == "red" else [BLUE_COLUMN]
    long = data.melt(
        id_vars=["period", "draw_date"],
        value_vars=columns,
        value_name="number",
        var_name="slot",
    )
    long["color"] = color
    return long.drop(columns="slot").sort_values(["period", "number"]).reset_index(drop=True)


# ---------------------------------------------------------------- 频率
def frequency_table(data: pd.DataFrame, color: str = "red") -> pd.DataFrame:
    """号码出现次数、出现率与理论值偏差。"""
    numbers = RED_NUMBERS if color == "red" else BLUE_NUMBERS
    draws = len(data)
    values = (
        data[RED_COLUMNS].to_numpy().ravel()
        if color == "red"
        else data[BLUE_COLUMN].to_numpy()
    )
    counts = pd.Series(values).value_counts().reindex(numbers, fill_value=0).astype(int)
    per_draw = len(RED_COLUMNS) if color == "red" else 1
    expected = draws * per_draw / len(numbers) if draws else 0.0

    table = pd.DataFrame(
        {
            "number": numbers,
            "count": counts.to_numpy(),
        }
    )
    table["ratio"] = table["count"] / draws * 100 if draws else 0.0
    table["expected"] = expected
    table["deviation"] = table["count"] - expected
    table["rank"] = table["count"].rank(ascending=False, method="min").astype(int)
    return table


# ---------------------------------------------------------------- 遗漏
def omission_table(data: pd.DataFrame, color: str = "red") -> pd.DataFrame:
    """每个号码的当前遗漏、最大遗漏、平均遗漏。"""
    numbers = RED_NUMBERS if color == "red" else BLUE_NUMBERS
    if data.empty:
        return pd.DataFrame(columns=["number", "current", "max_gap", "avg_gap", "last_period", "appearances"])

    if color == "red":
        reds = data[RED_COLUMNS].to_numpy(dtype=int)
        matrix = np.stack([(reds == number).any(axis=1) for number in numbers], axis=1)
    else:
        blues = data[BLUE_COLUMN].to_numpy(dtype=int)
        matrix = np.stack([blues == number for number in numbers], axis=1)

    draws = len(data)
    periods = data["period"].tolist()
    rows = []
    for index, number in enumerate(numbers):
        hits = np.flatnonzero(matrix[:, index])
        if hits.size == 0:
            rows.append((number, draws, draws, float(draws), None, 0))
            continue
        current = draws - 1 - int(hits[-1])
        gaps = np.diff(hits) - 1
        max_gap = max(int(hits[0]), current, *(gaps.tolist() if gaps.size else [0]))
        avg_gap = (draws - hits.size) / (hits.size + 1)
        rows.append((number, current, max_gap, round(float(avg_gap), 2), periods[int(hits[-1])], int(hits.size)))

    return pd.DataFrame(rows, columns=["number", "current", "max_gap", "avg_gap", "last_period", "appearances"])


# ---------------------------------------------------------------- 冷热
def hot_cold_table(data: pd.DataFrame, window: int = 30, color: str = "red") -> pd.DataFrame:
    """近期窗口出现率 vs 全样本出现率。"""
    window = max(1, min(window, len(data)))
    recent = data.tail(window)
    overall = frequency_table(data, color)[["number", "count", "ratio"]]
    near = frequency_table(recent, color)[["number", "count", "ratio"]]
    merged = overall.merge(near, on="number", suffixes=("_all", "_recent"))
    merged["delta"] = merged["ratio_recent"] - merged["ratio_all"]
    merged["state"] = np.where(merged["delta"] >= 3, "热",
                        np.where(merged["delta"] <= -3, "冷", "温"))
    return merged


# ---------------------------------------------------------------- 分布
def zone_summary(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    total = int(data["sum_value"].notna().sum()) * len(RED_COLUMNS)
    for _low, _high, label, key in ZONES:
        count = int(data[key].sum())
        rows.append({"zone": label, "count": count, "ratio": count / total * 100 if total else 0.0})
    return pd.DataFrame(rows)


def odd_even_summary(data: pd.DataFrame) -> pd.DataFrame:
    counts = data["odd_count"].value_counts().reindex(range(0, 7), fill_value=0).astype(int)
    total = counts.sum()
    return pd.DataFrame(
        {
            "odd_count": counts.index,
            "ratio_label": [f"{i}:{6 - i}" for i in counts.index],
            "count": counts.to_numpy(),
            "pct": (counts / total * 100).to_numpy() if total else 0.0,
        }
    )


def big_small_summary(data: pd.DataFrame) -> pd.DataFrame:
    counts = data["big_count"].value_counts().reindex(range(0, 7), fill_value=0).astype(int)
    total = counts.sum()
    return pd.DataFrame(
        {
            "big_count": counts.index,
            "ratio_label": [f"{6 - i}:{i}" for i in counts.index],
            "count": counts.to_numpy(),
            "pct": (counts / total * 100).to_numpy() if total else 0.0,
        }
    )


def distribution(data: pd.DataFrame, column: str, bins: int = 30) -> pd.DataFrame:
    values = data[column].dropna()
    if values.empty:
        return pd.DataFrame(columns=["bin", "count"])
    counts, edges = np.histogram(values.to_numpy(), bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2
    return pd.DataFrame({"bin": centers, "count": counts})


# ---------------------------------------------------------------- 导出
EXPORT_COLUMNS = {
    "period": "期号",
    "draw_date": "开奖日期",
    "red1": "红球1",
    "red2": "红球2",
    "red3": "红球3",
    "red4": "红球4",
    "red5": "红球5",
    "red6": "红球6",
    "blue": "蓝球",
    "sum_value": "和值",
    "span": "跨度",
    "odd_count": "奇数个数",
    "big_count": "大数个数",
    "consecutive": "最大连号",
    "ac_value": "AC值",
    "repeat_count": "重号个数",
    "first_count": "一等奖注数",
    "first_amount": "一等奖金额",
    "second_count": "二等奖注数",
    "second_amount": "二等奖金额",
    "pool_amount": "奖池奖金",
    "sales_amount": "销售额",
    "source": "数据来源",
}


def export_frame(data: pd.DataFrame) -> pd.DataFrame:
    """整理为中文表头、便于 Excel 打开的导出表。"""
    available = [column for column in EXPORT_COLUMNS if column in data.columns]
    if not available:  # 已经是自定义统计表，原样导出
        return data.copy()
    exported = data[available].copy()
    if "draw_date" in exported:
        exported["draw_date"] = pd.to_datetime(exported["draw_date"]).dt.strftime("%Y-%m-%d")
    return exported.rename(columns=EXPORT_COLUMNS)


def csv_bytes(data: pd.DataFrame) -> bytes:
    """导出 CSV（UTF-8 BOM，Excel 直接打开不乱码）。"""
    return export_frame(data).to_csv(index=False).encode("utf-8-sig")


# ---------------------------------------------------------------- 其它
def latest_draw(data: pd.DataFrame) -> pd.Series | None:
    if data.empty:
        return None
    return data.iloc[-1]


def compare_with_previous(data: pd.DataFrame) -> dict:
    """最新一期与上一期的对比信息。"""
    if len(data) < 2:
        return {}
    current, previous = data.iloc[-1], data.iloc[-2]
    current_reds = {int(current[c]) for c in RED_COLUMNS}
    previous_reds = {int(previous[c]) for c in RED_COLUMNS}
    return {
        "repeat": sorted(current_reds & previous_reds),
        "sum_delta": int(current["sum_value"] - previous["sum_value"]),
        "span_delta": int(current["span"] - previous["span"]),
    }
