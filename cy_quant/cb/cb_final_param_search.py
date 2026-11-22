"""可转债最终参数搜索（真实强赎过滤版本）。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import List

import numpy as np
import pandas as pd

from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_combo_monthly_backtest import run_backtest, summarize
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter


def score_row(row: pd.Series) -> float:
    """综合评分：收益高、回撤小、换手低、胜率高。"""
    ann = float(row.get("ann_return", np.nan))
    mdd = abs(float(row.get("max_drawdown", np.nan)))
    wr = float(row.get("win_rate", np.nan))
    to = float(row.get("avg_turnover", np.nan))
    if np.isnan(ann) or np.isnan(mdd) or np.isnan(wr) or np.isnan(to):
        return -1e9
    return ann * 100 - mdd * 80 + wr * 10 - to * 3


def main() -> None:
    p = argparse.ArgumentParser(description="可转债最终参数搜索（真实强赎过滤）")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--max-mdd", type=float, default=0.08, help="最大回撤上限（绝对值）")
    p.add_argument("--max-turnover", type=float, default=0.60, help="平均换手上限")
    p.add_argument("--min-win-rate", type=float, default=0.65, help="最小胜率")
    args = p.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_final_param_search_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    intervals = build_real_call_intervals(args.cb_call)
    panel_real = apply_real_call_filter(panel, intervals)

    strategies: List[str] = ["combo_dl_trend", "combo_dl_trend_call", "combo_lp_trend"]
    top_ns = [10, 15, 20, 25, 30]
    min_amounts = [2000, 3000, 4000]
    costs = [20, 40, 60]

    rows = []
    for st in strategies:
        for top_n in top_ns:
            for min_amt in min_amounts:
                for cost in costs:
                    perf, _ = run_backtest(
                        panel_real,
                        st,
                        top_n=top_n,
                        min_amount_wan=min_amt,
                        max_price_for_call_risk=9999.0,
                        roundtrip_cost_bps=cost,
                    )
                    s = summarize(perf)
                    s.update(
                        {
                            "strategy": st,
                            "top_n": top_n,
                            "min_amount_wan": min_amt,
                            "cost_bps": cost,
                            "total_return": float(perf["equity"].iloc[-1] - 1.0) if not perf.empty else np.nan,
                        }
                    )
                    rows.append(s)

    df = pd.DataFrame(rows)
    df = df[
        [
            "strategy",
            "top_n",
            "min_amount_wan",
            "cost_bps",
            "periods",
            "ann_return",
            "total_return",
            "max_drawdown",
            "win_rate",
            "avg_period_ret",
            "avg_turnover",
            "avg_cost",
        ]
    ]
    df["score"] = df.apply(score_row, axis=1)

    all_path = os.path.join(out_dir, "grid_all.csv")
    df.sort_values("score", ascending=False).to_csv(all_path, index=False, encoding="utf-8-sig")

    feasible = df[
        (df["max_drawdown"].abs() <= args.max_mdd)
        & (df["avg_turnover"] <= args.max_turnover)
        & (df["win_rate"] >= args.min_win_rate)
    ].copy()
    feasible = feasible.sort_values(["score", "ann_return"], ascending=[False, False])

    feasible_path = os.path.join(out_dir, "grid_feasible.csv")
    feasible.to_csv(feasible_path, index=False, encoding="utf-8-sig")

    best_path = os.path.join(out_dir, "best_recommendation.csv")
    if not feasible.empty:
        best = feasible.head(1)
    else:
        best = df.sort_values("score", ascending=False).head(1)
    best.to_csv(best_path, index=False, encoding="utf-8-sig")

    print(f"参数搜索完成 -> {out_dir}")
    print(f"all: {all_path}")
    print(f"feasible: {feasible_path}")
    print(f"best: {best_path}")
    print("BEST:")
    print(best.to_string(index=False))


if __name__ == "__main__":
    main()
