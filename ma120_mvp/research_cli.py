"""CLI for grouped MA120 research reports."""

from __future__ import annotations

import argparse
from typing import Optional

import pandas as pd

from .research import add_research_factors, build_research_tables, save_research_tables


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MA120 前瞻结果分组研究")
    parser.add_argument("--forward-csv", required=True, help="forward_cli 输出的 CSV")
    parser.add_argument("--out-dir", default=None, help="输出目录，默认 ma120_mvp/output/research_<today>")
    parser.add_argument("--min-signals", type=int, default=5, help="分组最少信号数，默认5")
    parser.add_argument("--top", type=int, default=10, help="每个分组表终端展示行数")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    df = pd.read_csv(args.forward_csv, encoding="utf-8-sig")
    df = add_research_factors(df)
    tables = build_research_tables(df, min_signals=args.min_signals)
    out_dir = save_research_tables(tables, args.out_dir)

    print(f"分组研究完成，原始信号数 {len(df)}")
    print(f"结果目录: {out_dir}")
    for name, table in tables.items():
        print()
        print("=" * 80)
        print(name)
        print("=" * 80)
        if table.empty:
            print("(无满足 min-signals 的分组)")
        else:
            print(table.head(args.top).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

