"""命令行工具：数据抓取 + 只读查询接口。

抓取（写库）::

    python -m lottery.cli crawl --all
    python -m lottery.cli crawl --start 2026001 --end 2026123
    python -m lottery.cli crawl --recent 100

只读查询（供人看或 AI Skill 调用，stdout 只有 JSON）::

    python -m lottery.cli schema
    python -m lottery.cli stats
    python -m lottery.cli query --start 2026001 --end 2026123 --limit 20
    python -m lottery.cli draw 2026123
    python -m lottery.cli analyze frequency --color red --top 10
    python -m lottery.cli analyze omission --color red --top 10
    python -m lottery.cli analyze hot-cold --window 50 --top 10
    python -m lottery.cli analyze shape --window 100
    python -m lottery.cli analyze overview --window 100
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from . import api, config
from .crawler import CrawlerService
from .crawler.periods import current_year_end
from .db import Database

READ_COMMANDS = {"schema", "stats", "query", "draw", "analyze"}


# ---------------------------------------------------------------- 参数
def _common() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--db", help="SQLite 数据库路径，默认 data/lottery.db")
    parser.add_argument("--format", choices=["json", "md"], default="json", help="输出格式")
    parser.add_argument("--pretty", action="store_true", help="缩进美化 JSON")
    return parser


def _add_range(parser: argparse.ArgumentParser, window_help: str = "只看最近 N 期") -> None:
    parser.add_argument("--start", help="起始期号，如 2026001 或 26001")
    parser.add_argument("--end", help="结束期号，默认不限制")
    parser.add_argument("--window", type=int, help=window_help)


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(
        prog="lottery", description="双色球数据抓取与只读查询接口"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- 抓取
    crawl = sub.add_parser("crawl", parents=[common], help="抓取开奖数据并写入 SQLite")
    crawl.add_argument("--start", help="起始期号，如 2026001 或 26001")
    crawl.add_argument("--end", help="结束期号，默认当前年份末尾")
    crawl.add_argument("--recent", type=int, help="抓取最近 N 期")
    crawl.add_argument("--all", action="store_true", help="抓取 2003 年至今全部历史")
    crawl.add_argument("--source", default="auto", choices=["auto", "500", "cwl"], help="数据源")
    crawl.add_argument("--force", action="store_true", help="覆盖已存在期号（默认仅补缺失）")

    # ---- 只读接口
    sub.add_parser("schema", parents=[common], help="输出接口说明（AI 第一步调用）")
    sub.add_parser("stats", parents=[common], help="数据库状态")

    query = sub.add_parser("query", parents=[common], help="按期号/日期区间查询开奖记录")
    _add_range(query)
    query.add_argument("--date-from", dest="date_from", help="开奖日期起，YYYY-MM-DD")
    query.add_argument("--date-to", dest="date_to", help="开奖日期止，YYYY-MM-DD")
    query.add_argument(
        "--limit", type=int, default=api.DEFAULT_LIMIT, help=f"最多返回行数，默认 {api.DEFAULT_LIMIT}，上限 {api.MAX_LIMIT}"
    )
    query.add_argument("--order", choices=["asc", "desc"], default="asc", help="返回顺序")
    query.add_argument("--fields", help="自定义字段，逗号分隔，如 period,reds,sum_value")
    query.add_argument(
        "--no-features", dest="features", action="store_false", help="不返回形态派生字段"
    )
    query.add_argument("--prize", action="store_true", help="附带奖金/奖池字段")

    draw = sub.add_parser("draw", parents=[common], help="查询单期详情")
    draw.add_argument("period", help="期号，如 2026123 或 26123")

    analyze = sub.add_parser("analyze", help="统计分析（只读）")
    targets = analyze.add_subparsers(dest="target", required=True)

    freq = targets.add_parser("frequency", parents=[common], help="号码出现频率")
    _add_range(freq)
    freq.add_argument("--color", default="red", help="red 或 blue")
    freq.add_argument("--top", type=int, help="只返回前 N 个号码")

    omit = targets.add_parser("omission", parents=[common], help="号码遗漏")
    _add_range(omit)
    omit.add_argument("--color", default="red", help="red 或 blue")
    omit.add_argument("--top", type=int, help="只返回遗漏最久的 N 个号码")

    hot = targets.add_parser("hot-cold", parents=[common], help="近期与全样本冷热对比")
    hot.add_argument("--color", default="red", help="red 或 blue")
    hot.add_argument("--window", type=int, default=30, help="近期窗口期数，默认 30")
    hot.add_argument("--start", help="起始期号")
    hot.add_argument("--end", help="结束期号")
    hot.add_argument("--top", type=int, help="只返回前 N 个号码")

    shape = targets.add_parser("shape", parents=[common], help="形态分布")
    _add_range(shape)

    overview = targets.add_parser("overview", parents=[common], help="区间整体画像")
    _add_range(overview)

    return parser


# ---------------------------------------------------------------- 输出
def _render_markdown(payload: dict) -> str:
    if not payload.get("ok", False):
        message = (payload.get("error") or {}).get("message", "未知错误")
        return f"**失败**：{message}"

    lines = [f"## {payload.get('title', '结果')}", ""]
    meta = payload.get("meta") or {}
    flat = [f"`{key}`={value}" for key, value in meta.items() if not isinstance(value, (dict, list))]
    if flat:
        lines += ["　".join(flat), ""]

    rows, columns = payload.get("rows"), payload.get("columns")
    if rows and columns:
        lines.append("| " + " | ".join(column["label"] for column in columns) + " |")
        lines.append("| " + " | ".join("---" for _ in columns) + " |")
        for row in rows:
            cells = []
            for column in columns:
                value = row.get(column["key"])
                if isinstance(value, list):
                    value = " ".join(str(item) for item in value)
                cells.append("" if value is None else str(value))
            lines.append("| " + " | ".join(cells) + " |")
    elif payload.get("data"):
        lines += ["```json", json.dumps(payload["data"], ensure_ascii=False, indent=2), "```"]
    return "\n".join(lines)


def _emit(payload: dict, args: argparse.Namespace) -> None:
    if getattr(args, "format", "json") == "md":
        print(_render_markdown(payload))
        return
    if getattr(args, "pretty", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


# ---------------------------------------------------------------- 抓取
def _progress(ratio: float, message: str) -> None:
    width = 28
    filled = int(width * min(max(ratio, 0.0), 1.0))
    # 进度写 stderr，避免污染 stdout 的 JSON
    sys.stderr.write(f"\r[{'#' * filled}{'.' * (width - filled)}] {message[:60]:<60}")
    sys.stderr.flush()


def _run_crawl(args: argparse.Namespace) -> int:
    db = Database(args.db) if args.db else Database()
    db.init_schema()
    service = CrawlerService(db, source=args.source)
    only_missing = not args.force

    if args.all:
        report = service.crawl(
            "2003001", current_year_end(), only_missing=only_missing, progress=_progress
        )
    elif args.recent:
        report = service.crawl_recent(args.recent, only_missing=only_missing, progress=_progress)
    else:
        if not args.start:
            print("需要 --start、--recent 或 --all 之一", file=sys.stderr)
            return 2
        report = service.crawl(
            args.start,
            args.end or current_year_end(),
            only_missing=only_missing,
            progress=_progress,
        )

    print()
    print(report.summary())
    for error in report.errors[:5]:
        print(f"  ! {error}")
    return 0 if report.ok or report.fetched else 1


# ---------------------------------------------------------------- 只读分发
def _dispatch(args: argparse.Namespace) -> dict:
    if args.command == "schema":
        return api.schema()

    path = Path(args.db) if args.db else config.DB_PATH
    if not path.exists():
        raise api.NotFound(f"数据库不存在：{path}。请先运行 python -m lottery.cli crawl --all")
    db = Database(path)

    if args.command == "stats":
        return api.stats(db)

    if args.command == "query":
        fields = [item.strip() for item in args.fields.split(",")] if args.fields else None
        return api.query(
            db,
            start=args.start,
            end=args.end,
            date_from=args.date_from,
            date_to=args.date_to,
            limit=args.limit,
            order=args.order,
            fields=fields,
            features=args.features,
            prize=args.prize,
        )

    if args.command == "draw":
        return api.draw(db, args.period)

    if args.command == "analyze":
        return _dispatch_analyze(db, args)

    raise api.BadRequest(f"未知命令：{args.command}")


def _dispatch_analyze(db: Database, args: argparse.Namespace) -> dict:
    target = args.target
    common = {"start": args.start, "end": args.end, "window": args.window}

    if target == "frequency":
        return api.analyze_frequency(db, color=args.color, top=args.top, **common)
    if target == "omission":
        return api.analyze_omission(db, color=args.color, top=args.top, **common)
    if target == "hot-cold":
        return api.analyze_hot_cold(
            db, color=args.color, window=args.window or 30, start=args.start, end=args.end, top=args.top
        )
    if target == "shape":
        return api.analyze_shape(db, **common)
    if target == "overview":
        return api.analyze_overview(db, **common)
    raise api.BadRequest(f"未知分析目标：{target}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "crawl":
        return _run_crawl(args)

    try:
        payload = _dispatch(args)
    except api.ApiError as exc:
        _emit(api.error_envelope(str(exc), kind=type(exc).__name__), args)
        return exc.code
    except Exception as exc:  # 兜底，保证 stdout 仍是可解析的 JSON
        _emit(api.error_envelope(f"{type(exc).__name__}: {exc}"), args)
        return 4

    _emit(payload, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
