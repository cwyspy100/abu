"""CLI for the compact MA120 daily watchlist."""

from __future__ import annotations

import argparse
from typing import Optional

from .radar import RadarConfig, scan
from .scorer import score_dataframe
from .watchlist import WatchlistConfig, save_watchlist, select_watchlist


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A股120日线每日精简观察列表")
    parser.add_argument("--pool", default=None, help="可选股票池CSV，列名支持 ts_code/symbol/code")
    parser.add_argument("--out", default=None, help="输出CSV路径，默认 ma120_mvp/output/ma120_watchlist_<today>.csv")
    parser.add_argument("--data-root", action="append", default=None, help="K线根目录，可重复传")
    parser.add_argument("--limit", type=int, default=None, help="调试用：限制扫描股票数量")
    parser.add_argument("--basic-csv", default=None, help="A股基础信息CSV，默认 todolist/stock_A_basic_list.csv")
    parser.add_argument("--include-st", action="store_true", help="包含ST/*ST；默认排除")
    parser.add_argument("--max-stale-days", type=int, default=14, help="跳过最后K线日期早于当前日期N天的文件")
    parser.add_argument("--ma120-slope-lookback", type=int, default=20)
    parser.add_argument("--breakout-lookback", type=int, default=20)
    parser.add_argument("--min-level", default="重点观察", choices=("强候选", "重点观察", "普通观察", "剔除观察"))
    parser.add_argument("--max-total", type=int, default=25, help="每日观察列表最大数量")
    parser.add_argument("--low-new-cap", type=int, default=10, help="低位新站上最多保留数量")
    parser.add_argument("--attack-cap", type=int, default=10, help="进攻突破窗口最多保留数量")
    parser.add_argument("--trend-cap", type=int, default=5, help="长期趋势延续最多保留数量")
    parser.add_argument("--min-price", type=float, default=5.0, help="最低股价过滤，默认5")
    parser.add_argument("--max-volume-ratio", type=float, default=3.0, help="最大量比过滤，默认3")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    radar_config = RadarConfig(
        ma120_slope_lookback=args.ma120_slope_lookback,
        breakout_lookback=args.breakout_lookback,
    )
    full = scan(
        data_roots=args.data_root,
        pool_csv=args.pool,
        limit=args.limit,
        max_stale_days=args.max_stale_days,
        exclude_st=not args.include_st,
        basic_csv=args.basic_csv,
        config=radar_config,
    )
    scored = score_dataframe(full)
    watch_config = WatchlistConfig(
        setup_caps={
            "低位新站上": args.low_new_cap,
            "进攻突破窗口": args.attack_cap,
            "长期趋势延续": args.trend_cap,
        },
        max_total=args.max_total,
        min_level=args.min_level,
        min_price=args.min_price,
        max_volume_ratio=args.max_volume_ratio,
    )
    watchlist = select_watchlist(scored, watch_config)
    out = save_watchlist(watchlist, args.out)

    print(f"趋势池命中 {len(scored)} 只，精简观察列表 {len(watchlist)} 只")
    print(f"观察列表已保存: {out}")
    if not watchlist.empty:
        setup_counts = watchlist["watch_setup"].value_counts().to_dict()
        print(f"形态分布: {setup_counts}")
        cols = [
            "ts_code", "name", "industry", "trade_date", "close",
            "watch_setup", "total_score", "candidate_level",
            "price_vs_ma120_pct", "ma120_slope_pct", "days_above_ma120",
            "volume_ratio", "signals", "watch_reason",
        ]
        print()
        print(watchlist[cols].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
