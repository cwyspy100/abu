#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import List

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cy_quant.industry_strength_backtest import run_backtest


def main() -> None:
    p = argparse.ArgumentParser(description="行业强度参数网格回测")
    p.add_argument(
        "--input-csv",
        default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/verify_12345_20260516/event_panel_with_345_features.csv",
    )
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--top-n", type=int, default=30)
    p.add_argument("--industry-top-pcts", nargs="+", type=float, default=[0.2, 0.3, 0.4, 0.5])
    args = p.parse_args()

    rows: List[dict] = []
    for pct in args.industry_top_pcts:
        res = run_backtest(
            input_csv=args.input_csv,
            output_dir=args.output_dir,
            top_n=args.top_n,
            industry_top_pct=pct,
        )
        perf = pd.read_csv(res["overall"])
        for _, r in perf.iterrows():
            rows.append(
                {
                    "industry_top_pct": pct,
                    "strategy": r["strategy"],
                    "months": r["months"],
                    "total_return": r["total_return"],
                    "cagr": r["cagr"],
                    "max_drawdown": r["max_drawdown"],
                    "avg_monthly_ret": r["avg_monthly_ret"],
                    "win_rate": r["win_rate"],
                    "result_dir": res["out_dir"],
                }
            )

    out = pd.DataFrame(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"industry_strength_grid_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    out_csv = os.path.join(out_dir, "grid_summary.csv")
    out.to_csv(out_csv, index=False, encoding="utf-8-sig")

    # 简单推荐：在 B/C 策略中，按 max_drawdown 更小优先，cagr 次优
    cand = out[out["strategy"].isin(["B_industry_top_filter", "C_mix_70_30"])].copy()
    cand = cand.sort_values(["max_drawdown", "cagr"], ascending=[False, False])
    best_csv = os.path.join(out_dir, "grid_best.csv")
    cand.head(10).to_csv(best_csv, index=False, encoding="utf-8-sig")

    print("done")
    print(f"grid_summary: {out_csv}")
    print(f"grid_best: {best_csv}")


if __name__ == "__main__":
    main()
