"""Command line interface for the MA120 MVP radar."""

from __future__ import annotations

import argparse
from typing import Optional

from .radar import RadarConfig, save_report, scan
from .scorer import score_dataframe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A股120日线每日雷达 MVP")
    parser.add_argument("--pool", default=None, help="可选股票池CSV，列名支持 ts_code/symbol/code")
    parser.add_argument("--out", default=None, help="输出CSV路径，默认 ma120_mvp/output/ma120_daily_<today>.csv")
    parser.add_argument("--data-root", action="append", default=None, help="K线根目录，可重复传；默认 ~/abu/data/csv/astock 和 ~/abu/data/csv")
    parser.add_argument("--limit", type=int, default=None, help="调试用：限制扫描数量")
    parser.add_argument("--max-vs-ma120", type=float, default=25.0, help="买入观察允许的最大MA120偏离百分比")
    parser.add_argument("--chase-risk", type=float, default=35.0, help="超过该MA120偏离百分比标记追高风险")
    parser.add_argument("--drawdown-risk", type=float, default=15.0, help="20日回撤风险阈值百分比")
    parser.add_argument("--breakout-lookback", type=int, default=20, help="突破前N日高点观察窗口")
    parser.add_argument("--max-stale-days", type=int, default=14, help="跳过最后K线日期早于当前日期N天的文件；默认14天")
    parser.add_argument("--ma120-slope-lookback", type=int, default=20, help="MA120斜率观察窗口；默认要求当前MA120高于20个交易日前")
    parser.add_argument("--basic-csv", default=None, help="A股基础信息CSV，默认 todolist/stock_A_basic_list.csv")
    parser.add_argument("--include-st", action="store_true", help="包含ST/*ST；默认排除")
    parser.add_argument("--top", type=int, default=50, help="终端展示Top N；CSV仍保存全部结果")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = RadarConfig(
        ma120_slope_lookback=args.ma120_slope_lookback,
        max_price_vs_ma120_pct=args.max_vs_ma120,
        chase_risk_pct=args.chase_risk,
        max_20d_drawdown_pct=args.drawdown_risk,
        breakout_lookback=args.breakout_lookback,
    )
    df = scan(
        data_roots=args.data_root,
        pool_csv=args.pool,
        limit=args.limit,
        max_stale_days=args.max_stale_days,
        exclude_st=not args.include_st,
        basic_csv=args.basic_csv,
        config=config,
    )
    df = score_dataframe(df)
    out = save_report(df, args.out)

    print(f"扫描完成，命中 {len(df)} 只站上MA120的A股")
    print(f"结果已保存: {out}")
    if not df.empty:
        level_counts = df["candidate_level"].value_counts().to_dict()
        print(f"分层统计: {level_counts}")
        cols = [
            "ts_code", "name", "industry", "trade_date", "close", "ma120_slope_pct",
            "days_above_ma120", "price_vs_ma120_pct", "total_score",
            "candidate_level", "signals", "risks", "score_reason",
        ]
        print()
        print(df[cols].head(args.top).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
