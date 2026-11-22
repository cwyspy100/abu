"""可转债分散约束网格研究（TopN × 成本）。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

import pandas as pd

from cy_quant.cb.cb_diversification_research import run
from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter


def main() -> None:
    p = argparse.ArgumentParser(description="分散约束网格研究")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--min-amount-wan", type=float, default=2000)
    args = p.parse_args()

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    panel["score"] = panel["combo_dl_trend"]

    basic = pd.read_csv(args.cb_basic, dtype={"ts_code": str, "stk_code": str})
    basic = basic[["ts_code", "stk_code"]].drop_duplicates(subset=["ts_code"], keep="first")
    panel = panel.merge(basic, on="ts_code", how="left")
    panel["stk_code"] = panel["stk_code"].fillna(panel["ts_code"])
    panel = apply_real_call_filter(panel, build_real_call_intervals(args.cb_call))

    rows = []
    for top_n in [20, 25, 30]:
        for cost in [20, 40, 60, 80]:
            for mode in ["baseline", "balanced_premium", "combo"]:
                s = run(panel, mode, top_n, args.min_amount_wan, cost)
                s["top_n"] = top_n
                s["cost_bps"] = cost
                rows.append(s)

    out = pd.DataFrame(rows)
    out = out[["mode", "top_n", "cost_bps", "periods", "ann_return", "total_return", "max_drawdown", "win_rate", "avg_turnover"]]

    out["score"] = out["ann_return"] * 100 - out["max_drawdown"].abs() * 80 + out["win_rate"] * 10 - out["avg_turnover"] * 3

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_diversification_grid_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    out.sort_values("score", ascending=False).to_csv(os.path.join(out_dir, "div_grid_all.csv"), index=False, encoding="utf-8-sig")

    # 风控可行集
    feasible = out[(out["max_drawdown"].abs() <= 0.06) & (out["avg_turnover"] <= 0.70) & (out["win_rate"] >= 0.70)].copy()
    feasible.sort_values("score", ascending=False).to_csv(os.path.join(out_dir, "div_grid_feasible.csv"), index=False, encoding="utf-8-sig")

    print(f"分散网格研究完成 -> {out_dir}")
    print("TOP 12:")
    print(out.sort_values("score", ascending=False).head(12).to_string(index=False))


if __name__ == "__main__":
    main()
