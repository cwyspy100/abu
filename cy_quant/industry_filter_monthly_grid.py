#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Grid search industry_top_pct for A-share monthly candidate pipeline."""

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

from cy_quant.datacsv_obs10_latest_candidates import run as run_candidates


def main() -> None:
    p = argparse.ArgumentParser(description="A股行业过滤阈值月度网格")
    p.add_argument("--csv-dir", default="/Users/water/abu/data/csv")
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--a-basic-csv", default="/Users/water/mylearn/PycharmProjects/abu-master/todolist/stock_A_basic_list.csv")
    p.add_argument("--max-files", type=int, default=2500)
    p.add_argument("--recent-months", type=int, default=1)
    p.add_argument("--top-pcts", nargs="+", type=float, default=[0.2, 0.25, 0.3, 0.35, 0.4])
    args = p.parse_args()

    rows: List[dict] = []
    for pct in args.top_pcts:
        out_dir = run_candidates(
            csv_dir=args.csv_dir,
            output_dir=args.output_dir,
            max_files=args.max_files,
            recent_months=args.recent_months,
            use_industry_filter=True,
            industry_top_pct=pct,
            a_basic_csv=args.a_basic_csv,
            export_ab_compare=True,
            sync_stock_pool=False,
            reset_a_market_status=True,
        )
        ab = pd.read_csv(os.path.join(out_dir, "a_industry_filter_ab_summary.csv"))
        r = ab[ab["variant"] == f"industry_top_{pct:.2f}"].iloc[0]
        rows.append(
            {
                "industry_top_pct": pct,
                "months": int(r["months"]),
                "total_return": float(r["total_return"]),
                "cagr_label": float(r["cagr_label"]),
                "annual_vol": float(r["annual_vol"]),
                "max_drawdown": float(r["max_drawdown"]),
                "win_rate_monthly": float(r["win_rate_monthly"]),
                "pick_count": int(r["pick_count"]),
                "avg_ret_120d_pick": float(r["avg_ret_120d_pick"]),
                "win_rate_120d_pick": float(r["win_rate_120d_pick"]),
                "source_dir": out_dir,
            }
        )

    df = pd.DataFrame(rows).sort_values("industry_top_pct").reset_index(drop=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"industry_filter_monthly_grid_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    grid_csv = os.path.join(out_dir, "grid_summary.csv")
    df.to_csv(grid_csv, index=False, encoding="utf-8-sig")

    # Recommendation: prioritize lower drawdown, then higher cagr.
    best = df.sort_values(["max_drawdown", "cagr_label"], ascending=[False, False]).head(1).copy()
    best_csv = os.path.join(out_dir, "best_params.csv")
    best.to_csv(best_csv, index=False, encoding="utf-8-sig")

    print("done")
    print(f"grid_summary: {grid_csv}")
    print(f"best_params: {best_csv}")


if __name__ == "__main__":
    main()
