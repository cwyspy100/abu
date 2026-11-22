#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from itertools import product
from typing import List

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cy_quant.stage3_trade_system_proxy_backtest import run


def main() -> None:
    p = argparse.ArgumentParser(description="Stage3 proxy parameter grid")
    p.add_argument(
        "--input-csv",
        default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/verify_12345_20260516/event_panel_with_345_features.csv",
    )
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--top-n", type=int, default=30)
    p.add_argument("--add-trigger-30d", nargs="+", type=float, default=[0.06, 0.08, 0.1])
    p.add_argument("--add-mult", nargs="+", type=float, default=[1.15, 1.3, 1.45])
    p.add_argument("--stop-loss-120d", nargs="+", type=float, default=[-0.1, -0.12, -0.15])
    p.add_argument("--stop-partial-120d", nargs="+", type=float, default=[-0.06, -0.08, -0.1])
    args = p.parse_args()

    rows: List[dict] = []
    for t, m, sl, sp in product(
        args.add_trigger_30d, args.add_mult, args.stop_loss_120d, args.stop_partial_120d
    ):
        if sp <= sl:
            continue
        out_dir = run(
            input_csv=args.input_csv,
            output_dir=args.output_dir,
            top_n=args.top_n,
            add_trigger_30d=t,
            add_mult=m,
            stop_loss_120d=sl,
            stop_partial_120d=sp,
        )
        perf = pd.read_csv(os.path.join(out_dir, "overall_summary.csv"))
        for _, r in perf.iterrows():
            rows.append(
                {
                    "add_trigger_30d": t,
                    "add_mult": m,
                    "stop_loss_120d": sl,
                    "stop_partial_120d": sp,
                    "strategy": r["strategy"],
                    "total_return": r["total_return"],
                    "cagr": r["cagr"],
                    "annual_vol": r["annual_vol"],
                    "max_drawdown": r["max_drawdown"],
                    "win_rate_monthly": r["win_rate_monthly"],
                    "avg_monthly_ret": r["avg_monthly_ret"],
                    "source_dir": out_dir,
                }
            )

    df = pd.DataFrame(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(args.output_dir, f"stage3_trade_system_proxy_grid_{ts}")
    os.makedirs(base, exist_ok=True)
    all_csv = os.path.join(base, "grid_all.csv")
    df.to_csv(all_csv, index=False, encoding="utf-8-sig")

    # focus full system
    full = df[df["strategy"] == "S4_full_system"].copy()
    full["calmar_proxy"] = full["cagr"] / full["max_drawdown"].abs().replace(0, pd.NA)
    best = full.sort_values(["calmar_proxy", "cagr"], ascending=[False, False]).head(15)
    best_csv = os.path.join(base, "grid_best_s4.csv")
    best.to_csv(best_csv, index=False, encoding="utf-8-sig")

    print("done")
    print(f"grid_all: {all_csv}")
    print(f"grid_best_s4: {best_csv}")


if __name__ == "__main__":
    main()
