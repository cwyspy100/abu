# -*- encoding:utf-8 -*-
"""
对比两种 ScreenAsOfMomentumBreakout 步骤组合下，远期收益（如 60/90/120 日）的分布。

同一 signal_date 上，步骤 B（如 1,2,3）的标的集合通常是步骤 A（如 1,2）的子集；
这里把各 as_of 截面上的收益当作「两个独立样本」做描述统计与 Mann-Whitney U（可选），
用于粗看哪条规则链在历史上平均表现更好，不是因果结论。

用法（仓库根目录）::

  python cy_quant/screen_steps_forward_compare.py --as-of 20240315 20240601 \\
    --steps-a 1,2 --steps-b 1,2,3 --market cn

  python cy_quant/screen_steps_forward_compare.py --as-of 20241201 \\
    --steps-a 1,2 --steps-b 1,2,3,4,5 --horizons 60 90 120 -v

依赖：ScreenAsOfMomentumBreakout 能正常读到本地 CSV；可选 scipy 做检验。
"""

from __future__ import print_function

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import pandas as pd

from cy_quant.ScreenAsOfMomentumBreakout import (
    MARKET_PRESETS,
    ScreenAsOfMomentumBreakout,
    _default_benchmark_symbol_str,
)


def _mannwhitney(a, b):
    try:
        from scipy.stats import mannwhitneyu

        a = np.asarray(a, dtype=float)
        b = np.asarray(b, dtype=float)
        a = a[~np.isnan(a)]
        b = b[~np.isnan(b)]
        if len(a) < 3 or len(b) < 3:
            return None, None
        r = mannwhitneyu(a, b, alternative="two-sided")
        return float(r.statistic), float(r.pvalue)
    except Exception:
        return None, None


def summarize_series(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return None
    return {
        "n": int(s.shape[0]),
        "mean": round(float(s.mean()), 4),
        "median": round(float(s.median()), 4),
        "std": round(float(s.std()), 4),
        "win_pct": round(float((s > 0).mean() * 100.0), 2),
        "q25": round(float(s.quantile(0.25)), 4),
        "q75": round(float(s.quantile(0.75)), 4),
    }


def run_compare(
    as_ofs,
    market,
    bench,
    steps_a,
    steps_b,
    horizons,
    csv_dir=None,
    bench_ma_n=200,
    stock_ma_n=120,
    stock_ma_slope_bars=1,
    rs_lookback_n=60,
    rs_top_pct=0.2,
    vol_ma_n=5,
    vol_mult=1.5,
    atr_short_n=20,
    atr_long_n=60,
    xd_short=20,
    xd_long=55,
    input_csv=None,
    prefixes=None,
    verbose=False,
):
    preset = MARKET_PRESETS[market]
    bench_eff = bench if bench is not None else _default_benchmark_symbol_str(market)
    prefixes_eff = prefixes if prefixes is not None else preset["prefixes"]
    csv_eff = os.path.expanduser(csv_dir or "~/abu/data/csv")

    frames = []
    configs = [("A", steps_a), ("B", steps_b)]

    for as_of in as_ofs:
        for label, steps in configs:
            sc = ScreenAsOfMomentumBreakout(
                as_of=as_of,
                bench=bench_eff,
                prefixes=prefixes_eff,
                input_csv=input_csv,
                csv_dir=csv_eff,
                bench_ma_n=bench_ma_n,
                stock_ma_n=stock_ma_n,
                stock_ma_slope_bars=stock_ma_slope_bars,
                rs_lookback_n=rs_lookback_n,
                rs_top_pct=rs_top_pct,
                vol_ma_n=vol_ma_n,
                vol_mult=vol_mult,
                atr_short_n=atr_short_n,
                atr_long_n=atr_long_n,
                xd_short=xd_short,
                xd_long=xd_long,
                enabled_steps=steps,
                forward_horizons=horizons,
                verbose=verbose,
            )
            df = sc.run()
            if df is None or df.empty:
                if verbose:
                    print("[{}] as_of={} steps={} -> 0 行".format(label, as_of, steps))
                continue
            d = df.copy()
            d["_compare_label"] = label
            d["_compare_steps"] = steps
            d["_as_of_req"] = str(as_of)
            frames.append(d)

    if not frames:
        print("无数据：请检查 as_of、步骤组合与本地 K 线。")
        return None, None

    all_df = pd.concat(frames, ignore_index=True)
    out_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "output",
        "screen_steps_compare_raw.csv",
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    all_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print("已写出明细: {}".format(out_path))

    rows = []
    for h in horizons:
        col = "fwd_ret_{}d".format(h)
        if col not in all_df.columns:
            print("警告: 无列 {}".format(col))
            continue
        sub_a = all_df.loc[all_df["_compare_label"] == "A", col]
        sub_b = all_df.loc[all_df["_compare_label"] == "B", col]
        sa = summarize_series(sub_a)
        sb = summarize_series(sub_b)
        stat, pval = _mannwhitney(sub_a.values, sub_b.values)
        rows.append(
            {
                "horizon_d": h,
                "A_steps": steps_a,
                "B_steps": steps_b,
                "A_n": sa["n"] if sa else 0,
                "B_n": sb["n"] if sb else 0,
                "A_mean": sa["mean"] if sa else np.nan,
                "B_mean": sb["mean"] if sb else np.nan,
                "A_median": sa["median"] if sa else np.nan,
                "B_median": sb["median"] if sb else np.nan,
                "A_win_pct": sa["win_pct"] if sa else np.nan,
                "B_win_pct": sb["win_pct"] if sb else np.nan,
                "MW_U": stat,
                "MW_pvalue": pval,
            }
        )

    summ = pd.DataFrame(rows)
    print("\n======== 汇总（全 as_of 池化；收益单位为 %%）========")
    if not summ.empty:
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 200)
        print(summ.to_string(index=False))
        print(
            "\n解读: mean/median/win_pct 越高通常越好；MW_pvalue<0.05 仅表示两分布"
            "「显著不同」，不保证 B 优于 A。样本非独立（B 常为 A 子集）时检验作参考即可。"
        )
    summ_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "output",
        "screen_steps_compare_summary.csv",
    )
    summ.to_csv(summ_path, index=False, encoding="utf-8-sig")
    print("\n已写出汇总: {}".format(summ_path))
    return all_df, summ


def main():
    p = argparse.ArgumentParser(description="对比两种 --steps 的远期收益分布")
    p.add_argument(
        "market",
        nargs="?",
        default="cn",
        choices=sorted(MARKET_PRESETS.keys()),
    )
    p.add_argument(
        "--as-of",
        nargs="+",
        required=True,
        help="一个或多个 YYYYMMDD",
    )
    p.add_argument("--steps-a", default="1,2", help="配置 A，如 1,2")
    p.add_argument("--steps-b", default="1,2,3", help="配置 B，如 1,2,3")
    p.add_argument(
        "--horizons",
        type=int,
        nargs="+",
        default=[60, 90, 120],
        help="远期持有日，默认 60 90 120",
    )
    p.add_argument("--bench", default=None)
    p.add_argument("--csv-dir", default=None)
    p.add_argument("--input-csv", default=None)
    p.add_argument("--bench-ma-n", type=int, default=200)
    p.add_argument("--stock-ma-n", type=int, default=120)
    p.add_argument("--stock-ma-slope-bars", type=int, default=1)
    p.add_argument("--rs-lookback-n", type=int, default=60)
    p.add_argument("--rs-top-pct", type=float, default=0.2)
    p.add_argument("--vol-ma-n", type=int, default=5)
    p.add_argument("--vol-mult", type=float, default=1.5)
    p.add_argument("--atr-short-n", type=int, default=20)
    p.add_argument("--atr-long-n", type=int, default=60)
    p.add_argument("--xd-short", type=int, default=20)
    p.add_argument("--xd-long", type=int, default=55)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    run_compare(
        as_ofs=args.as_of,
        market=args.market,
        bench=args.bench,
        steps_a=args.steps_a,
        steps_b=args.steps_b,
        horizons=args.horizons,
        csv_dir=args.csv_dir,
        bench_ma_n=args.bench_ma_n,
        stock_ma_n=args.stock_ma_n,
        stock_ma_slope_bars=args.stock_ma_slope_bars,
        rs_lookback_n=args.rs_lookback_n,
        rs_top_pct=args.rs_top_pct,
        vol_ma_n=args.vol_ma_n,
        vol_mult=args.vol_mult,
        atr_short_n=args.atr_short_n,
        atr_long_n=args.atr_long_n,
        xd_short=args.xd_short,
        xd_long=args.xd_long,
        input_csv=args.input_csv,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
