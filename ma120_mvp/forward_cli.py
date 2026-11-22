"""CLI for MA120 forward tests."""

from __future__ import annotations

import argparse
from typing import Optional

from .forward_test import ForwardTestConfig, run_forward_test, save_forward_report, summarize_forward_results
from .radar import RadarConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A股120日线评分信号前瞻验证")
    parser.add_argument("--pool", default=None, help="可选股票池CSV，列名支持 ts_code/symbol/code")
    parser.add_argument("--out", default=None, help="输出CSV路径，默认 ma120_mvp/output/forward_test_<today>.csv")
    parser.add_argument("--data-root", action="append", default=None, help="K线根目录，可重复传")
    parser.add_argument("--limit", type=int, default=None, help="调试用：限制扫描股票数量")
    parser.add_argument("--basic-csv", default=None, help="A股基础信息CSV，默认 todolist/stock_A_basic_list.csv")
    parser.add_argument("--include-st", action="store_true", help="包含ST/*ST；默认排除")
    parser.add_argument("--recent-days", type=int, default=120, help="只评估每只股票最近N个可产生完整未来窗口的信号日")
    parser.add_argument("--horizon", type=int, default=20, help="未来观察窗口交易日数，默认20")
    parser.add_argument("--min-score", type=int, default=80, help="最低评分阈值，默认80")
    parser.add_argument("--min-level", default="强候选", choices=("强候选", "重点观察", "普通观察", "剔除观察"))
    parser.add_argument("--stop-loss", type=float, default=-8.0, help="止损统计阈值百分比，默认-8")
    parser.add_argument("--signal-cooldown", type=int, default=0, help="同一股票两次入选之间至少间隔N个交易日，默认0不去重")
    parser.add_argument("--ma120-slope-lookback", type=int, default=20)
    parser.add_argument("--breakout-lookback", type=int, default=20)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    radar_config = RadarConfig(
        ma120_slope_lookback=args.ma120_slope_lookback,
        breakout_lookback=args.breakout_lookback,
    )
    test_config = ForwardTestConfig(
        min_total_score=args.min_score,
        horizon_days=args.horizon,
        recent_trade_days=args.recent_days,
        min_level=args.min_level,
        stop_loss_pct=args.stop_loss,
        signal_cooldown_days=args.signal_cooldown,
    )
    df = run_forward_test(
        data_roots=args.data_root,
        pool_csv=args.pool,
        limit=args.limit,
        exclude_st=not args.include_st,
        basic_csv=args.basic_csv,
        radar_config=radar_config,
        test_config=test_config,
    )
    out = save_forward_report(df, args.out)
    print(f"前瞻验证完成，信号数 {len(df)}")
    print(f"结果已保存: {out}")
    if not df.empty:
        summary = summarize_forward_results(df)
        print()
        print("分层统计:")
        print(summary.to_string())
        cols = [
            "ts_code", "signal_date", "entry_price", "total_score", "candidate_level",
            "max_gain_pct", "max_drawdown_pct", "final_return_pct",
            "hit_10pct", "hit_20pct", "hit_stop_loss", "score_reason",
        ]
        print()
        print("Top signals:")
        print(df[cols].head(30).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
